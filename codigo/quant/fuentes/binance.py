import calendar
import io
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from quant import datos, rutas
from quant.fuentes import http

BASE = "https://data.binance.vision/data/spot"
_MICROSEGUNDOS = 10 ** 14


def url_mes(simbolo, anio, mes):
    return f"{BASE}/monthly/klines/{simbolo}/1m/{simbolo}-1m-{anio:04d}-{mes:02d}.zip"


def url_dia(simbolo, dia):
    return f"{BASE}/daily/klines/{simbolo}/1m/{simbolo}-1m-{dia:%Y-%m-%d}.zip"


def decodificar(contenido):
    if not contenido:
        return pd.DataFrame(columns=datos.COLUMNAS)
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        tabla = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None, usecols=range(6))
    tiempo = tabla[0].to_numpy(np.int64)
    milis = np.where(tiempo > _MICROSEGUNDOS, tiempo // 1000, tiempo)
    ts = pd.to_datetime(milis, unit="ms").floor("min")
    return pd.DataFrame({"ts": ts, "open": tabla[1].astype(float),
                         "high": tabla[2].astype(float), "low": tabla[3].astype(float),
                         "close": tabla[4].astype(float), "volume": tabla[5].astype(float)})


def _meses(desde, hasta):
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        yield anio, mes
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def _dias(desde, hasta):
    return [desde + timedelta(days=i) for i in range(max((hasta - desde).days + 1, 0))]


def _meses_recientes(hasta):
    anterior = (hasta.year - 1, 12) if hasta.month == 1 else (hasta.year, hasta.month - 1)
    return {(hasta.year, hasta.month), anterior}


def actualizar(instrumento, info, hasta, raiz=rutas.DATOS, sesion=None, dormir=time.sleep,
                limite=None, reloj=time.monotonic):
    sesion = sesion or requests.Session()
    ultimo = datos.ultimo_ts(instrumento, "M1", raiz)
    desde = date.fromisoformat(info["desde"])
    existentes = datos.meses_con_velas(instrumento, "M1", raiz)
    recientes = _meses_recientes(hasta)
    limite_ts = pd.Timestamp(hasta + timedelta(days=1))
    simbolo = info["simbolo"]
    resumen = {"instrumento": instrumento, "meses": 0, "velas": 0, "hasta": None, "error": None, "meses_vacios": []}
    bruto = 0

    def bajar(url):
        return decodificar(http.descargar(url, sesion, dormir=dormir))

    for anio, mes in _meses(desde, hasta):
        if limite is not None and reloj() > limite:
            resumen["omitido"] = "tiempo agotado"
            break
        if (anio, mes) in existentes and (anio, mes) not in recientes:
            continue
        primero = max(date(anio, mes, 1), desde)
        ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
        try:
            marcos = []
            if (anio, mes) < (hasta.year, hasta.month):
                mensual = bajar(url_mes(simbolo, anio, mes))
                marcos = [mensual] if len(mensual) else [bajar(url_dia(simbolo, d)) for d in _dias(primero, ultimo_dia)]
            else:
                marcos = [bajar(url_dia(simbolo, d)) for d in _dias(primero, hasta)]
        except http.ErrorFuente as e:
            resumen["error"] = f"{anio:04d}-{mes:02d}: {e}"
            break
        utiles = [m for m in marcos if len(m)]
        if utiles:
            bruto += sum(len(m) for m in utiles)
            df = pd.concat(utiles, ignore_index=True)
            mascara = df["ts"] < limite_ts
            if ultimo is not None and (anio, mes) == (hasta.year, hasta.month):
                mascara &= df["ts"] > ultimo
            df = df[mascara]
            if len(df):
                datos.guardar_anual(instrumento, "M1", df, raiz)
                resumen["velas"] += len(df)
        elif (anio, mes) not in recientes:
            resumen["meses_vacios"].append(f"{anio:04d}-{mes:02d}")
        resumen["meses"] += 1
        resumen["hasta"] = min(ultimo_dia, hasta).isoformat()
    if resumen["meses_vacios"] and not resumen["error"]:
        resumen["error"] = "meses sin datos: " + ", ".join(resumen["meses_vacios"])
    elif not resumen["error"] and not resumen.get("omitido") and bruto == 0 and resumen["meses"] >= 1:
        resumen["error"] = "sin datos en todo el rango solicitado"
    return resumen
