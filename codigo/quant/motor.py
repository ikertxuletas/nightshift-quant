"""Motor de backtest: señal al cierre de la vela i, ejecución en la apertura de i+1."""
from dataclasses import dataclass

import numpy as np

from quant import expresiones, indicadores

PERIODO_ATR = 14
TAMANO_DEFECTO = {"tipo": "riesgo", "valor": 1.0}


@dataclass(frozen=True)
class Operacion:
    instrumento: str
    lado: int
    i_entrada: int
    i_salida: int
    precio_entrada: float
    precio_salida: float
    unidades: float
    pnl: float
    costes: float
    motivo: str


@dataclass(frozen=True)
class Resultado:
    ts: np.ndarray
    equity: np.ndarray
    operaciones: tuple
    capital: float
    open_position: dict | None = None
    pending: dict | None = None


def _senal(cond, barras, cache, n):
    return expresiones.evaluar(cond, barras, cache) if cond else np.zeros(n, bool)


def _minutos(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _a_zona(ts, zona):
    """UTC bar times to local wall-clock times."""
    import pandas as pd
    return pd.DatetimeIndex(ts).tz_localize("UTC").tz_convert(zona).tz_localize(None).to_numpy().astype(ts.dtype)


def permitido(ts, horario):
    ok = np.ones(len(ts), bool)
    if not horario:
        return ok
    if horario.get("zona"):
        ts = _a_zona(ts, horario["zona"])
    if horario.get("dias") is not None:
        dia = (ts.astype("datetime64[D]").astype(np.int64) + 3) % 7
        ok &= np.isin(dia, horario["dias"])
    if horario.get("sesiones"):
        minuto = ((ts - ts.astype("datetime64[D]")) // np.timedelta64(1, "m")).astype(np.int64)
        dentro = np.zeros(len(ts), bool)
        for s in horario["sesiones"]:
            d, h = _minutos(s["desde"]), _minutos(s["hasta"])
            dentro |= ((minuto >= d) & (minuto < h)) if d <= h else ((minuto >= d) | (minuto < h))
        ok &= dentro
    return ok


def dia_local(ts, horario):
    local = _a_zona(ts, horario["zona"]) if horario and horario.get("zona") else ts
    return local.astype("datetime64[D]")


def rango_sesion_anterior(b, horario):
    """High-low range of the previous trading day, per bar. Days with under half the usual bars (the Sunday
    evening stub) belong to the next day's session, so Monday's previous day is Friday."""
    dia = dia_local(b["ts"], horario)
    nuevo = np.r_[True, dia[1:] != dia[:-1]]
    d = np.cumsum(nuevo) - 1
    cuenta = np.bincount(d)
    sesion = np.arange(len(cuenta))
    for k in range(len(cuenta) - 2, -1, -1):
        if cuenta[k] < np.median(cuenta) / 2:
            sesion[k] = sesion[k + 1]
    s = np.unique(sesion[d], return_inverse=True)[1]
    inicios = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])
    rango = np.maximum.reduceat(b["high"], inicios) - np.minimum.reduceat(b["low"], inicios)
    return np.where(s >= 1, rango[np.maximum(s - 1, 0)], np.nan)


def tras_cierre(ts, horario):
    if not horario or not horario.get("cierre"):
        return np.zeros(len(ts), bool)
    local = _a_zona(ts, horario["zona"]) if horario.get("zona") else ts
    minuto = ((local - local.astype("datetime64[D]")) // np.timedelta64(1, "m")).astype(np.int64)
    return minuto >= _minutos(horario["cierre"])


def _distancia(spec, precio, atr):
    if not spec:
        return None
    if spec["tipo"] in ("barras", "rango_dia"):
        return np.nan  # needs the bars: only _abrir with `extremos` / `rango` can place it
    return spec["valor"] * atr if spec["tipo"] == "atr" else precio * spec["valor"] / 100


def _extremos(spec, barras, cache):
    """Structural stop levels: lowest low / highest high of the N bars before the entry bar."""
    if not spec or spec["tipo"] != "barras":
        return None
    n = int(spec["valor"])
    return {1: indicadores.calcular(f"MIN({n})[1]", barras, cache),
            -1: indicadores.calcular(f"MAX({n})[1]", barras, cache)}


def _abrir(lado, precio, i, atr, gestion, costes, efectivo, extremos=None, rango=None):
    tamano = gestion.get("tamano") or TAMANO_DEFECTO
    fill = costes.precio_ejecucion(precio, compra=lado > 0)
    if extremos is not None:
        dist_stop = lado * (fill - extremos[lado][i])
        if not dist_stop > 0:
            return None, efectivo
    else:
        dist_stop = _distancia(gestion.get("stop"), fill, atr) or _distancia(gestion.get("trailing"), fill, atr)
    if tamano["tipo"] == "unidades":
        unidades = min(float(tamano["valor"]), efectivo * costes.apalancamiento / fill)
    else:
        dist = dist_stop or 2 * atr
        if not np.isfinite(dist) or dist <= 0:
            return None, efectivo
        unidades = min(efectivo * tamano["valor"] / 100 / dist, efectivo * costes.apalancamiento / fill)
    if not unidades > 0:
        return None, efectivo
    dist_obj = _distancia(gestion.get("objetivo"), fill, atr)
    if (gestion.get("objetivo") or {}).get("tipo") == "rango_dia" and rango is not None and rango > 0:
        dist_obj = gestion["objetivo"]["valor"] * rango
    dist_trailing = _distancia(gestion.get("trailing"), fill, atr)
    for spec, dist in ((gestion.get("stop"), dist_stop), (gestion.get("trailing"), dist_trailing), (gestion.get("objetivo"), dist_obj)):
        if spec and not np.isfinite(dist):
            return None, efectivo
    comision = unidades * fill * costes.comision_pct
    pos = {
        "q": lado * unidades, "i": i, "precio": fill, "gastos": comision,
        "friccion": unidades * abs(fill - precio),
        "stop": fill - lado * dist_stop if dist_stop else None,
        "objetivo": fill + lado * dist_obj if dist_obj else None,
    }
    return pos, efectivo - lado * unidades * fill - comision


def _cerrar(instrumento, pos, precio, i, motivo, costes, efectivo):
    q = pos["q"]
    unidades, lado = abs(q), (1 if q > 0 else -1)
    fill = costes.precio_ejecucion(precio, compra=lado < 0)
    comision = unidades * fill * costes.comision_pct
    gastos = pos["gastos"] + comision
    op = Operacion(instrumento, lado, pos["i"], i, pos["precio"], fill, unidades,
                   q * (fill - pos["precio"]) - gastos,
                   gastos + pos["friccion"] + unidades * abs(fill - precio), motivo)
    return op, efectivo + q * fill - comision


def _salida_intrabarra(pos, o, h, l):
    largo = pos["q"] > 0
    stop, objetivo = pos["stop"], pos["objetivo"]
    if stop is not None:
        if largo and l <= stop:
            return min(o, stop), "stop"
        if not largo and h >= stop:
            return max(o, stop), "stop"
    if objetivo is not None:
        if largo and h >= objetivo:
            return max(o, objetivo), "objetivo"
        if not largo and l <= objetivo:
            return min(o, objetivo), "objetivo"
    return None, None


def _trailing(pos, cierre, atr, spec):
    dist = _distancia(spec, cierre, atr)
    if not dist or not np.isfinite(dist):
        return pos
    largo = pos["q"] > 0
    nuevo = cierre - dist if largo else cierre + dist
    actual = pos["stop"]
    if actual is None or not np.isfinite(actual) or (nuevo > actual if largo else nuevo < actual):
        return {**pos, "stop": nuevo}
    return pos


def backtest_serie(ficha, instrumento, barras, costes, capital):
    ts, o, h, l, c = (barras[k] for k in ("ts", "open", "high", "low", "close"))
    n = len(c)
    cache = {}
    entrada, salida, gestion = ficha.get("entrada") or {}, ficha.get("salida") or {}, ficha["gestion"]
    entra = {1: _senal(entrada.get("largo"), barras, cache, n),
             -1: _senal(entrada.get("corto"), barras, cache, n) if costes.permite_corto else np.zeros(n, bool)}
    sale = {1: _senal(salida.get("largo"), barras, cache, n), -1: _senal(salida.get("corto"), barras, cache, n)}
    abierto = permitido(ts, ficha.get("horario"))
    cierre = tras_cierre(ts, ficha.get("horario"))
    con_cierre = bool((ficha.get("horario") or {}).get("cierre"))
    parar = bool(gestion.get("parar_tras_objetivo"))
    dia_l = dia_local(ts, ficha.get("horario")) if con_cierre or parar else None
    dia_objetivo = None
    atr = indicadores.calcular(f"ATR({PERIODO_ATR})", barras, cache)
    extremos = _extremos(gestion.get("stop"), barras, cache)
    rango = (rango_sesion_anterior(barras, ficha.get("horario"))
             if (gestion.get("objetivo") or {}).get("tipo") == "rango_dia" else None)
    tope_dia = gestion.get("perdida_diaria_max")
    dia = ts.astype("datetime64[D]")
    efectivo, equity, ops = float(capital), np.empty(n), []
    pos, pend_salida, pend_entrada = None, False, 0
    inicio_dia = float(capital)
    for i in range(n):
        if tope_dia and i and dia[i] != dia[i - 1]:
            inicio_dia = equity[i - 1]
        if pos and pend_salida:
            op, efectivo = _cerrar(instrumento, pos, o[i], i, "senal", costes, efectivo)
            ops.append(op)
            pos = None
        if pos is None and pend_entrada and efectivo > 0:
            pos, efectivo = _abrir(pend_entrada, o[i], i, atr[i - 1], gestion, costes, efectivo, extremos,
                                   None if rango is None else rango[i - 1])
        pend_salida, pend_entrada = False, 0
        if pos and con_cierre and dia_l[i] != dia_l[pos["i"]]:
            op, efectivo = _cerrar(instrumento, pos, o[i], i, "sesion", costes, efectivo)
            ops.append(op)
            pos = None
        if pos:
            precio, motivo = _salida_intrabarra(pos, o[i], h[i], l[i])
            if precio is not None:
                op, efectivo = _cerrar(instrumento, pos, precio, i, motivo, costes, efectivo)
                ops.append(op)
                pos = None
                if parar and motivo == "objetivo":
                    dia_objetivo = dia_l[i]
        if pos and cierre[i]:
            op, efectivo = _cerrar(instrumento, pos, c[i], i, "sesion", costes, efectivo)
            ops.append(op)
            pos = None
        if pos:
            lado = 1 if pos["q"] > 0 else -1
            dias = (ts[i] - ts[i - 1]) / np.timedelta64(1, "D")
            swap = abs(pos["q"]) * c[i] * costes.swap_pct_anual * dias / 365
            efectivo -= swap
            pos = _trailing({**pos, "gastos": pos["gastos"] + swap}, c[i], atr[i], gestion.get("trailing"))
            maximo = gestion.get("max_barras")
            pend_salida = bool((maximo and i - pos["i"] + 1 >= maximo) or sale[lado][i] or entra[-lado][i])
        # Daily loss cap (measured on the last close's equity): no new entries for the rest of that UTC day.
        bloqueado = bool(tope_dia and i and (inicio_dia - equity[i - 1]) / inicio_dia * 100 >= tope_dia)
        bloqueado = bloqueado or bool(parar and dia_l[i] == dia_objetivo)
        if (pos is None or pend_salida) and abierto[i] and not bloqueado and not cierre[i]:
            for lado in (1, -1):
                if entra[lado][i] and not (pos and (pos["q"] > 0) == (lado > 0)):
                    pend_entrada = lado
                    break
        equity[i] = efectivo + (pos["q"] * c[i] if pos else 0.0)
    open_position = None
    if pos:
        open_position = {"side": 1 if pos["q"] > 0 else -1, "entry_price": pos["precio"], "units": abs(pos["q"]),
                         "stop": pos["stop"], "target": pos["objetivo"], "i_entry": pos["i"]}
        op, efectivo = _cerrar(instrumento, pos, c[-1], n - 1, "fin", costes, efectivo)
        ops.append(op)
        equity[-1] = efectivo
    return Resultado(ts, equity, tuple(ops), float(capital), open_position,
                     {"enter": pend_entrada, "exit": bool(pend_salida)})


def _rebalancear(k, actual, destino, mid, i, costes, efectivo, motivo):
    """Ajusta la tenencia de `k` a `destino` unidades en `mid`.

    Si el signo se mantiene, la `Operacion` sigue abierta: se ajustan las unidades,
    la fricción se suma a `gastos` y el P&L no realizado se acumula en `pnl_acum`.
    Se cierra (generando `Operacion`) solo si el destino es 0, si cambia de signo
    (la fricción del giro va íntegra al tramo nuevo) o en `fin`.
    """
    q = actual["q"] if actual else 0.0
    delta = destino - q
    friccion = 0.0
    if delta:
        fill = costes.precio_ejecucion(mid, compra=delta > 0)
        friccion = abs(delta) * (abs(fill - mid) + fill * costes.comision_pct)
    efectivo -= delta * mid + friccion

    if actual and (destino == 0 or (destino > 0) != (q > 0)):
        gastos = actual["gastos"] if destino else actual["gastos"] + friccion
        pnl = actual["pnl_acum"] + q * (mid - actual["precio_ref"]) - gastos
        op = Operacion(k, 1 if q > 0 else -1, actual["i_entrada"], i, actual["precio_entrada"], mid,
                       abs(q), pnl, gastos, motivo)
    else:
        op = None

    if not destino:
        nuevo = None
    elif actual and (destino > 0) == (q > 0):
        nuevo = {"q": destino, "i_entrada": actual["i_entrada"], "precio_entrada": actual["precio_entrada"],
                  "precio_ref": mid, "gastos": actual["gastos"] + friccion,
                  "pnl_acum": actual["pnl_acum"] + q * (mid - actual["precio_ref"])}
    else:
        nuevo = {"q": destino, "i_entrada": i, "precio_entrada": mid, "precio_ref": mid,
                  "gastos": friccion, "pnl_acum": 0.0}
    return nuevo, efectivo, op


def _objetivo(instrs, rank, filtro, barras, costes, i, top, bottom, valor):
    if valor <= 0:
        return {}
    validos = {k: rank[k][i] for k in instrs if np.isfinite(rank[k][i]) and filtro[k][i]}
    orden = sorted(validos, key=validos.get, reverse=True)
    largos = orden[:top]
    cortos = [k for k in reversed(orden) if k not in largos and costes[k].permite_corto][:bottom]
    hueco = valor / (top + bottom)
    objetivo = {k: hueco / barras[k]["close"][i] for k in largos}
    objetivo.update({k: -hueco / barras[k]["close"][i] for k in cortos})
    return objetivo


def backtest_transversal(ficha, barras_por_instr, costes_por_instr, capital):
    instrs = sorted(barras_por_instr)
    ts = barras_por_instr[instrs[0]]["ts"]
    for k in instrs[1:]:
        ts = np.intersect1d(ts, barras_por_instr[k]["ts"])
    barras = {}
    for k in instrs:
        mascara = np.isin(barras_por_instr[k]["ts"], ts)
        barras[k] = {campo: v[mascara] for campo, v in barras_por_instr[k].items()}
    n, t = len(ts), ficha["transversal"]
    rank, filtro = {}, {}
    for k in instrs:
        cache = {}
        rank[k] = indicadores.calcular(t["ranking"], barras[k], cache)
        filtro[k] = _senal(t.get("filtro"), barras[k], cache, n) if t.get("filtro") else np.ones(n, bool)
    top, bottom, cada = t["top"], t.get("bottom", 0), t["cada_barras"]
    efectivo, equity, ops, pos, objetivo = float(capital), np.empty(n), [], {}, None
    for i in range(n):
        if objetivo is not None:
            for k in instrs:
                nuevo, efectivo, op = _rebalancear(k, pos.get(k), objetivo.get(k, 0.0), barras[k]["open"][i],
                                                   i, costes_por_instr[k], efectivo, "rebalanceo")
                if op:
                    ops.append(op)
                pos = {**{x: p for x, p in pos.items() if x != k}, **({k: nuevo} if nuevo else {})}
            objetivo = None
        if i > 0 and pos:
            dias = (ts[i] - ts[i - 1]) / np.timedelta64(1, "D")
            nuevos = {}
            for k, p in pos.items():
                swap = abs(p["q"]) * barras[k]["close"][i] * costes_por_instr[k].swap_pct_anual * dias / 365
                efectivo -= swap
                nuevos[k] = {**p, "gastos": p["gastos"] + swap}
            pos = nuevos
        valor = efectivo + sum(p["q"] * barras[k]["close"][i] for k, p in pos.items())
        if i % cada == 0 and i < n - 1:
            objetivo = _objetivo(instrs, rank, filtro, barras, costes_por_instr, i, top, bottom, valor)
        equity[i] = valor
    for k in sorted(pos):
        _, efectivo, op = _rebalancear(k, pos[k], 0.0, barras[k]["close"][-1], n - 1,
                                       costes_por_instr[k], efectivo, "fin")
        ops.append(op)
    if n and pos:
        equity[-1] = efectivo
    return Resultado(ts, equity, tuple(ops), float(capital))
