from datetime import datetime, timezone

import numpy as np

from quant import datos
from quant.demo import desvio

_SIN_PRECIO = (datos.ErrorDatos, OSError, KeyError, ValueError)


def _t(texto):
    return np.datetime64(str(texto)[:19], "s")


def _segundos(ts):
    return np.asarray(ts).astype("datetime64[s]").astype("int64")


def _activas(con):
    return con.execute("SELECT * FROM demo_strategies WHERE status='active' ORDER BY id").fetchall()


def _cerradas(con):
    return con.execute("SELECT t.*, s.label FROM demo_trades t JOIN demo_strategies s ON s.id = t.strategy_id"
                       " WHERE s.status = 'active' ORDER BY t.exit_ts, t.id").fetchall()


def _apertura(con, strategy_id):
    r = con.execute("SELECT created FROM demo_orders WHERE strategy_id = ? AND kind = 'open' AND status = 'filled'"
                    " ORDER BY id DESC LIMIT 1", (strategy_id,)).fetchone()
    return r[0] if r else None


def _posiciones(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_paper_positions'").fetchone():
        return []
    return con.execute("SELECT p.*, s.label FROM demo_paper_positions p JOIN demo_strategies s ON s.id = p.strategy_id"
                       " WHERE s.status = 'active' ORDER BY p.strategy_id").fetchall()


def _precios(cargar_h1, instrumentos):
    precios, sin = {}, []
    for inst in instrumentos:
        try:
            b = cargar_h1(inst)
            precios[inst] = (_segundos(b["ts"]), np.asarray(b["close"], float))
        except _SIN_PRECIO:
            sin.append(inst)
    return precios, sin


def _precio_en(serie, t):
    ts, close = serie
    i = np.searchsorted(ts, t, side="right") - 1
    return float(close[i]) if i >= 0 else None


def curva_demo(con, cargar_h1, desde=None):
    activas = _activas(con)
    cerradas = _cerradas(con)
    piernas = [(p, _apertura(con, p["strategy_id"])) for p in _posiciones(con)]
    inicios = [_t(t["entry_ts"]) for t in cerradas if t["entry_ts"]] + [_t(a) for _, a in piernas if a]
    vacia = {"total": [], "estrategias": [], "controles": [], "sin_precio": []}
    if desde is not None:
        inicio = _t(desde)
    elif inicios:
        inicio = min(inicios)
    else:
        return vacia
    inicio_s = int(inicio.astype("int64"))
    precios, sin = _precios(cargar_h1, sorted({s["instrument"] for s in activas if s["instrument"]}))
    tiempos = np.unique(np.concatenate([ts[ts >= inicio_s] for ts, _ in precios.values()] or [np.array([], "int64")]))
    if not len(tiempos):
        ahora = int(datetime.now(timezone.utc).timestamp())
        tiempos = np.arange(inicio_s - inicio_s % 3600, ahora + 1, 3600, dtype="int64")
    control = np.zeros(len(tiempos))
    propia = np.zeros(len(tiempos))
    for t in cerradas:
        if not t["exit_ts"]:
            continue
        suma = np.where(tiempos >= int(_t(t["exit_ts"]).astype("int64")), float(t["pnl"] or 0), 0.0)
        if t["label"] == "control":
            control += suma
        else:
            propia += suma
    for p, abierta in piernas:
        serie = precios.get(p["instrument"])
        if serie is None:
            continue
        desde_s = int(_t(abierta).astype("int64")) if abierta else inicio_s
        valores = np.array([0.0 if k < desde_s or (v := _precio_en(serie, k)) is None
                            else p["side"] * p["units"] * (v - p["entry_price"]) for k in tiempos])
        if p["label"] == "control":
            control += valores
        else:
            propia += valores
    puntos = lambda vals: [{"time": int(k), "value": round(float(v), 2)} for k, v in zip(tiempos, vals)]
    return {"total": puntos(control + propia), "estrategias": puntos(propia), "controles": puntos(control),
            "sin_precio": sorted(set(sin) & {p["instrument"] for p, _ in piernas})}


def resumen_demo(con, curva):
    activas = _activas(con)
    cerradas = _cerradas(con)
    cap_c = sum(s["capital"] or 0 for s in activas if s["label"] == "control")
    cap_e = sum(s["capital"] or 0 for s in activas if s["label"] != "control")
    ultimo = lambda k: curva[k][-1]["value"] if curva.get(k) else 0.0
    pct = lambda v, cap: v / cap * 100 if cap else None
    total = ultimo("total")
    return {"total": total, "cerrado": round(sum(t["pnl"] or 0 for t in cerradas), 2),
            "pct_total": pct(total, cap_c + cap_e), "pct_estrategias": pct(ultimo("estrategias"), cap_e),
            "pct_controles": pct(ultimo("controles"), cap_c), "capital": cap_c + cap_e, "n_cerradas": len(cerradas)}


def franja_demo(curva_total, pnls, ops_por_dia, capital):
    if not len(pnls) or not curva_total:
        return []
    dias, t0 = {}, curva_total[0]["time"]
    for p in curva_total:
        dias[(p["time"] - t0) // 86400] = p["time"]
    salida = []
    for n, (_, t) in enumerate(sorted(dias.items()), start=1):
        bajo, _, alto = desvio.expected_band(pnls, max(1, round(ops_por_dia * n)), capital, pct=5)
        salida.append({"time": int(t), "bajo": round(bajo, 2), "alto": round(alto, 2)})
    return salida


def _cierres_diarios(serie, n=30):
    ts, close = serie
    dias = ts // 86400
    ultimos = np.r_[np.nonzero(np.diff(dias))[0], len(dias) - 1] if len(dias) else np.array([], int)
    return [float(close[i]) for i in ultimos[-n:]]


def abiertas(con, cargar_h1):
    pos = _posiciones(con)
    precios, _ = _precios(cargar_h1, sorted({p["instrument"] for p in pos}))
    salida = []
    for p in pos:
        serie = precios.get(p["instrument"])
        ahora = float(serie[1][-1]) if serie is not None and len(serie[1]) else None
        salida.append({"estrategia": p["strategy_id"], "instrumento": p["instrument"], "etiqueta": p["label"],
                       "desde": _apertura(con, p["strategy_id"]), "entrada": p["entry_price"], "ahora": ahora,
                       "resultado": None if ahora is None else round(p["side"] * p["units"] * (ahora - p["entry_price"]), 2),
                       "cierres30": _cierres_diarios(serie) if serie is not None else []})
    return salida


_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_TITULARES = {"verde": "Todo en orden", "ambar": "Hay algo que mirar", "rojo": "Algo falló"}
_EVENTOS = ("mismatch", "retire", "warn", "stop_file")


def _fecha(texto):
    try:
        return datetime.fromisoformat(str(texto)).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _inicio_parte(p):
    return _fecha(p.get("inicio")) or _fecha(f'{str(p.get("fecha", ""))[:4]}-{str(p.get("fecha", ""))[4:6]}-{str(p.get("fecha", ""))[6:8]}')


def _malos(p):
    r = (((p or {}).get("etapas") or {}).get("precios") or {}).get("resultado") or {}
    return [i.get("instrumento") for i in r.get("instrumentos") or [] if isinstance(i, dict) and i.get("error")]


def estado(partes, tareas, eventos, ahora):
    from quant.investigacion import contratos
    rojo, ambar = [], []
    ultimo = partes[0] if partes else None
    inicio = _inicio_parte(ultimo) if ultimo else None
    if inicio is None or (ahora - inicio).total_seconds() > 26 * 3600:
        rojo.append("No hay parte de la noche en las últimas 26 horas.")
    etapas = (ultimo or {}).get("etapas") or {}
    for nombre in contratos.ETAPAS:
        r = (etapas.get(nombre) or {}).get("resultado")
        if nombre != "precios" and contratos.hay_fallo(r):
            rojo.append(f"La etapa {nombre} falló: {contratos.hay_fallo(r)}")
        elif isinstance(r, dict) and r.get("omitido"):
            ambar.append(f"La etapa {nombre} se omitió: {r['omitido']}")
        elif isinstance(r, dict) and r.get("errores_contenido"):
            ambar.append(f"La etapa {nombre} tuvo {r['errores_contenido']} errores de contenido.")
    lab = (etapas.get("laboratorio") or {}).get("resultado")
    if isinstance(lab, dict) and not lab.get("omitido") and lab.get("probados") == 0:
        ambar.append("El laboratorio no probó ningún experimento.")
    demo = (tareas or {}).get("Quant_Demo")
    revisada = _fecha(demo.get("ultima")) if isinstance(demo, dict) else None
    if isinstance(demo, dict) and (revisada is None or (ahora - revisada).total_seconds() > 26 * 3600):
        rojo.append("La demo lleva más de un día sin revisar precios.")
    malos = _malos(ultimo)
    precios = (etapas.get("precios") or {}).get("resultado")
    criticos = list((precios or {}).get("criticos_con_error") or []) if isinstance(precios, dict) else []
    conocidos = [m for m in malos if m not in criticos and len(partes) >= 3 and all(m in _malos(p) for p in partes[1:3])]
    if contratos.hay_fallo(precios) and not malos:
        ambar.append(f"La descarga de precios falló: {contratos.hay_fallo(precios)}")
    ambar += [f"{m} es imprescindible para la demo y falló al descargar." for m in criticos]
    malos = [m for m in malos if m not in criticos]
    ambar += [f"{m} trajo datos sospechosos; no se sobrescribió nada." for m in malos if m not in conocidos]
    for e in eventos or []:
        try:
            t = desvio.naive(datetime.fromisoformat(str(e["ts"])))
        except ValueError:
            continue
        if e["kind"] in _EVENTOS and (ahora - t).total_seconds() <= 24 * 3600:
            ambar.append(str(e["detail_es"] or e["kind"]))
    nivel = "rojo" if rojo else "ambar" if ambar else "verde"
    if nivel == "verde":
        frase = "La noche terminó bien" + (f" y la demo revisó precios a las {revisada:%H:%M}." if revisada else ".")
    elif nivel == "ambar":
        frase = "Hay avisos que conviene mirar."
    else:
        frase = rojo[0]
    return {"nivel": nivel, "titular": _TITULARES[nivel], "frase": frase, "avisos": rojo + ambar, "conocidos": conocidos}


def resumen_noche(parte):
    if not parte:
        return []
    from quant.investigacion import contratos
    from quant.panel.paginas import _que_hizo
    etapas = parte.get("etapas") or {}
    lineas = [_que_hizo(n, (etapas.get(n) or {}).get("resultado")) for n in ("laboratorio", "investigar") if n in etapas]
    malas = [n for n in ("precios", "demo", "copia") if contratos.hay_fallo((etapas.get(n) or {}).get("resultado"))]
    nombres = {"precios": "precios", "demo": "demo", "copia": "copia de seguridad"}
    lineas.append("Con problemas: " + ", ".join(nombres[n] for n in malas) + "." if malas
                  else "Precios, demo y copia de seguridad, sin problemas.")
    return [l for l in lineas if l]


def _cuando(t, ahora):
    hora = f"a las {t:%H:%M}"
    dias = (t.date() - ahora.date()).days
    if (dias == 0 and t.hour >= 20) or (dias == 1 and t.hour < 6):
        return f"Esta noche {hora}"
    if dias == 0:
        return f"Hoy {hora}"
    if dias == 1:
        return f"Mañana {hora}"
    return f"El {_DIAS[t.weekday()]} {t.day} {hora}"


def proximo(tareas, ahora):
    frases = []
    for nombre, que in (("Quant_Noche", "noche de laboratorio"), ("Quant_Asesor", "informe del asesor")):
        d = (tareas or {}).get(nombre)
        t = _fecha(d.get("proxima")) if isinstance(d, dict) else None
        if t is not None:
            frases.append(f"{_cuando(t, ahora)}, {que}.")
    return " ".join(frases)


def progreso_propia(con, estrategia, min_ops=200):
    import json
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_experimentos'").fetchone():
        return None
    filas = con.execute("SELECT id, noche, veredicto, entreno_json FROM lab_experimentos WHERE estrategia = ?"
                        " AND invalido IS NULL AND COALESCE(cambios, 0) != 0 ORDER BY noche, id", (estrategia,)).fetchall()
    if not filas:
        return None
    mejor, evolucion = None, {}
    for f in filas:
        try:
            t = ((json.loads(f["entreno_json"]) if f["entreno_json"] else {}).get("metricas") or {}).get("total") or {}
        except ValueError:
            continue
        pf, ops = t.get("profit_factor"), t.get("operaciones") or 0
        if pf is not None and ops >= min_ops and (mejor is None or pf > mejor[1]):
            mejor = (f["id"], pf, ops)
        if mejor is not None:
            evolucion[f["noche"]] = round(mejor[1], 2)
    ganadoras = con.execute("SELECT estado FROM lab_ganadoras WHERE estrategia = ?", (estrategia,)).fetchall() if \
        con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_ganadoras'").fetchone() else []
    fase = ("En examen" if ganadoras else "Pasa el validador" if any(f["veredicto"] == "pasa_validador" for f in filas)
            else "Entrenamiento")
    return {"mejor_id": mejor[0] if mejor else None, "pf": round(mejor[1], 2) if mejor else None,
            "ops": mejor[2] if mejor else None, "variantes": len(filas), "evolucion": list(evolucion.items()), "fase": fase}
