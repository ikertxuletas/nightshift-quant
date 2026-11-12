import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant import datos, rutas

UMBRAL_SALTO = {"cripto": 0.30, "accion": 0.25, "indice": 0.10, "forex": 0.05, "materia": 0.15}
FRACCION_BLOQUEO = 0.001
MAX_INCOHERENTES = 500
MAX_PICOS = 50
FRACCION_DESHECHO_PICO = 0.30
TOLERANCIA_OHLC = 1e-3
UMBRAL_AUSENCIAS = {"cripto": 0.02, "accion": 0.10, "indice": 0.10, "forex": 0.10, "materia": 0.10}
MAX_HUECO_DIAS = {"cripto": 3, "accion": 15, "indice": 15, "forex": 15, "materia": 15}
FICHERO = "_calidad.json"


def _dias_esperados(desde, hasta, clase):
    todos = pd.date_range(desde, hasta, freq="D")
    return todos if clase == "cripto" else todos[todos.day_of_week < 5]


def _huecos(ts, clase):
    dias = pd.DatetimeIndex(pd.to_datetime(ts)).normalize().unique().sort_values()
    esperados = _dias_esperados(dias[0], dias[-1], clase)
    presentes = set(dias)
    tiene_dato = esperados.isin(presentes)
    dias_esperados = len(esperados)
    dias_ausentes = int(dias_esperados - tiene_dato.sum())
    fechas_con_dato = esperados[tiene_dato]
    mayor_hueco_dias = int((fechas_con_dato[1:] - fechas_con_dato[:-1]).days.max()) if len(fechas_con_dato) > 1 else 0
    return len(dias), dias_esperados, dias_ausentes, mayor_hueco_dias


def revisar(barras, clase):
    o, h, l, c = (np.asarray(barras[k], float) for k in ("open", "high", "low", "close"))
    n = len(c)
    if n == 0:
        return {"velas": 0, "desde": None, "hasta": None, "no_positivos": 0, "ohlc_incoherentes": 0,
                "saltos": 0, "picos": 0, "dias_con_velas": 0, "dias_esperados": 0, "dias_ausentes": 0,
                "mayor_hueco_dias": 0, "bloqueante": True, "motivos": ["sin velas"]}
    precios = np.vstack([o, h, l, c])
    finitos = np.isfinite(precios)
    no_positivos = int(np.sum(~finitos.all(axis=0) | (np.where(finitos, precios, 1.0).min(axis=0) <= 0)))
    incoherentes = int(np.sum((h < np.maximum(o, c) * (1 - TOLERANCIA_OHLC)) |
                              (l > np.minimum(o, c) * (1 + TOLERANCIA_OHLC)) | (h < l)))
    umbral = UMBRAL_SALTO[clase]
    with np.errstate(divide="ignore", invalid="ignore"):
        cambio = np.abs(c[1:] / c[:-1] - 1)
    saltos_mask = np.nan_to_num(cambio, nan=0.0) > umbral
    saltos = int(np.sum(saltos_mask))
    idx = np.nonzero(saltos_mask)[0]
    idx = idx[idx + 2 < n]
    c_pre, c_pico, c_post = c[idx], c[idx + 1], c[idx + 2]
    con_datos = np.isfinite(c_pre) & np.isfinite(c_pico) & np.isfinite(c_post)
    c_pre, c_pico, c_post = c_pre[con_datos], c_pico[con_datos], c_post[con_datos]
    picos = int(np.sum(np.abs(c_post - c_pre) < FRACCION_DESHECHO_PICO * np.abs(c_pico - c_pre)))
    dias_con_velas, dias_esperados, dias_ausentes, mayor_hueco_dias = _huecos(barras["ts"], clase)
    motivos = []
    if no_positivos:
        motivos.append(f"{no_positivos} velas con precios no positivos o no finitos")
    if incoherentes / n > FRACCION_BLOQUEO or incoherentes > MAX_INCOHERENTES:
        motivos.append(f"{incoherentes} velas con OHLC incoherente")
    if picos / n > FRACCION_BLOQUEO or picos > MAX_PICOS:
        motivos.append(f"{picos} picos de precio que se deshacen en la vela siguiente (dato probablemente erroneo)")
    if dias_esperados and dias_ausentes / dias_esperados > UMBRAL_AUSENCIAS[clase]:
        motivos.append(f"faltan {dias_ausentes} de {dias_esperados} dias esperados "
                        f"({dias_ausentes / dias_esperados:.0%})")
    if mayor_hueco_dias > MAX_HUECO_DIAS[clase]:
        motivos.append(f"hueco de {mayor_hueco_dias} dias sin datos (maximo {MAX_HUECO_DIAS[clase]})")
    return {"velas": n, "desde": pd.Timestamp(barras["ts"][0]).isoformat(),
            "hasta": pd.Timestamp(barras["ts"][-1]).isoformat(), "no_positivos": no_positivos,
            "ohlc_incoherentes": incoherentes, "saltos": saltos, "picos": picos,
            "dias_con_velas": dias_con_velas, "dias_esperados": dias_esperados, "dias_ausentes": dias_ausentes,
            "mayor_hueco_dias": mayor_hueco_dias, "bloqueante": bool(motivos), "motivos": motivos}


def _leer(raiz):
    ruta = Path(raiz) / FICHERO
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def revisar_todo(uni, raiz=rutas.DATOS, solo=None):
    informe = _leer(raiz)
    for instrumento, info in uni["instrumentos"].items():
        if solo is not None and instrumento not in solo:
            continue
        disponibles = datos.resoluciones(instrumento, raiz)
        if not disponibles:
            continue
        base = disponibles[0]
        desde = info.get("desde")
        barras = datos.cargar(instrumento, base, raiz, desde=desde)
        entrada = {"resolucion": base, **revisar(barras, info["clase"])}
        if datos.ORDEN.index(base) < datos.ORDEN.index("D1"):
            barras_d1 = datos.cargar(instrumento, "D1", raiz, desde=desde)
            entrada["d1"] = revisar(barras_d1, info["clase"])
            if entrada["d1"]["bloqueante"]:
                entrada["bloqueante"] = True
                entrada["motivos"] = entrada["motivos"] + [f"D1: {m}" for m in entrada["d1"]["motivos"]]
        informe[instrumento] = entrada
    Path(raiz).mkdir(parents=True, exist_ok=True)
    (Path(raiz) / FICHERO).write_text(json.dumps(informe, indent=1, ensure_ascii=False), encoding="utf-8")
    return informe


def bloqueo(instrumento, raiz=rutas.DATOS):
    info = _leer(raiz).get(instrumento)
    if info is None:
        return "sin revisar"
    return "; ".join(info["motivos"]) if info.get("bloqueante") else None
