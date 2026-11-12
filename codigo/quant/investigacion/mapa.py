"""Where a ficha wins and loses, on training bars only: trades grouped by side, hour, day, exit, trend and year."""
from copy import deepcopy

import numpy as np
import pandas as pd

from quant import indicadores, motor

GRUPOS = ("lado", "hora", "dia", "salida", "tendencia", "anio")


def _riesgos(ficha, barras, ops):
    """Initial risk per trade, placed as the motor places it: the stop, else the trailing, else 2 ATR (sizing)."""
    gestion = ficha.get("gestion") or {}
    stop = gestion.get("stop") or gestion.get("trailing") or {"tipo": "atr", "valor": 2}
    cache = {}
    if stop["tipo"] == "barras":
        lo = indicadores.calcular(f"MIN({int(stop['valor'])})[1]", barras, cache)
        hi = indicadores.calcular(f"MAX({int(stop['valor'])})[1]", barras, cache)
        return [o.precio_entrada - lo[o.i_entrada] if o.lado > 0 else hi[o.i_entrada] - o.precio_entrada for o in ops]
    if stop["tipo"] == "pct":
        return [o.precio_entrada * stop["valor"] / 100 for o in ops]
    atr = indicadores.calcular(f"ATR({motor.PERIODO_ATR})", barras, cache)
    return [stop["valor"] * atr[o.i_entrada - 1] for o in ops]


def operaciones(ficha, instrumento, barras, costes, corte):
    """1 unit per trade, result in R; the daily loss cap is dropped because it only bends the sizing."""
    f = deepcopy(ficha)
    f["gestion"]["tamano"] = {"tipo": "unidades", "valor": 1}
    f["gestion"].pop("perdida_diaria_max", None)
    fin = np.datetime64(corte, "ns")
    b = {k: v[barras["ts"] < fin] for k, v in barras.items()}
    if len(b["ts"]) < 2:
        return []
    ops = [o for o in motor.backtest_serie(f, instrumento, b, costes, 5000).operaciones if o.motivo != "fin"]
    ema = indicadores.calcular("EMA(100)", b, {})
    local = pd.DatetimeIndex(b["ts"]).tz_localize("UTC").tz_convert("Europe/Madrid")
    filas = []
    for o, riesgo in zip(ops, _riesgos(f, b, ops)):
        if not riesgo > 0:
            continue
        s, t = o.i_entrada - 1, local[o.i_entrada]
        tendencia = "sin_dato" if not np.isfinite(ema[s]) else (
            "a_favor" if (b["close"][s] > ema[s]) == (o.lado > 0) else "en_contra")
        filas.append({"R": o.pnl / (riesgo * o.unidades), "lado": "largo" if o.lado > 0 else "corto",
                      "hora": f"{t.hour:02d}h", "dia": "LMXJVSD"[t.weekday()], "salida": o.motivo,
                      "tendencia": tendencia, "anio": t.year})
    return filas


def _pf(rs):
    gana, pierde = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return round(gana / pierde, 2) if pierde > 0 else None


def mapa(ficha, instrumento, barras, costes, corte):
    con = operaciones(ficha, instrumento, barras, costes, corte)
    sin = operaciones(ficha, instrumento, barras, costes.escalar(0), corte)
    grupos = {}
    for g in GRUPOS:
        valores = {}
        for v in sorted({x[g] for x in con} | {x[g] for x in sin}, key=str):
            rc, rs = [x["R"] for x in con if x[g] == v], [x["R"] for x in sin if x[g] == v]
            valores[v] = {"ops": len(rc), "pf_con": _pf(rc), "pf_sin": _pf(rs)}
        grupos[g] = valores
    return {"ops": len(con), "pf_con": _pf([x["R"] for x in con]), "pf_sin": _pf([x["R"] for x in sin]),
            "grupos": grupos}


def texto(nombre, m, sin=()):
    lineas = [f"{nombre}: {m['ops']} trades, pf with costs {m['pf_con']}, pf without costs {m['pf_sin']}"]
    for g, valores in m["grupos"].items():
        if g in sin:
            continue
        lineas.append(f"  {g}: " + "; ".join(f"{v} {d['ops']} pf {d['pf_con']}/{d['pf_sin']}" for v, d in valores.items()))
    return "\n".join(_trocear(l) for l in lineas)


def _trocear(linea, ancho=200):
    if len(linea) <= ancho:
        return linea
    partes, actual = [], ""
    for trozo in linea.split("; "):
        if actual and len(actual) + len(trozo) + 2 > ancho:
            partes.append(actual)
            actual = "    " + trozo
        else:
            actual = f"{actual}; {trozo}" if actual else trozo
    return "\n".join(partes + [actual])
