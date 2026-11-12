import lzma
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from quant import datos, rutas
from quant.fuentes import http

BASE = "https://datafeed.dukascopy.com/datafeed"
LOTE_DIAS = 31
_REGISTRO = struct.Struct(">IIIIIf")


def url_dia(simbolo, dia):
    return f"{BASE}/{simbolo}/{dia.year:04d}/{dia.month - 1:02d}/{dia.day:02d}/BID_candles_min_1.bi5"


def decodificar(contenido, dia, divisor):
    if not contenido:
        return pd.DataFrame(columns=datos.COLUMNAS)
    crudo = lzma.decompress(contenido)
    n = len(crudo) // _REGISTRO.size
    if n == 0:
        return pd.DataFrame(columns=datos.COLUMNAS)
    valores = np.array(list(_REGISTRO.iter_unpack(crudo[:n * _REGISTRO.size])), dtype=float)
    df = pd.DataFrame({
        "ts": pd.Timestamp(dia) + pd.to_timedelta(valores[:, 0], unit="s"),
        "open": valores[:, 1] / divisor,
        "high": valores[:, 4] / divisor,
        "low": valores[:, 3] / divisor,
        "close": valores[:, 2] / divisor,
        "volume": valores[:, 5],
    })
    return df[df["volume"] > 0].reset_index(drop=True)


def actualizar(instrumento, info, hasta, raiz=rutas.DATOS, sesion=None, max_dias=None, hilos=4, dormir=time.sleep,
                limite=None, reloj=time.monotonic):
    sesion = sesion or requests.Session()
    ultimo = datos.ultimo_ts(instrumento, "M1", raiz)
    inicio = ultimo.date() + timedelta(days=1) if ultimo is not None else date.fromisoformat(info["desde"])
    pendientes = [inicio + timedelta(days=i) for i in range(max((hasta - inicio).days + 1, 0))][:max_dias]
    resumen = {"instrumento": instrumento, "dias": 0, "velas": 0, "hasta": None, "error": None}

    def bajar(dia):
        return http.descargar(url_dia(info["simbolo"], dia), sesion, dormir=dormir)

    for i in range(0, len(pendientes), LOTE_DIAS):
        if limite is not None and reloj() > limite:
            resumen["omitido"] = "tiempo agotado"
            break
        lote = pendientes[i:i + LOTE_DIAS]
        intento = 0
        while True:
            intento += 1
            with ThreadPoolExecutor(hilos) as ejecutor:
                futuros = [ejecutor.submit(bajar, d) for d in lote]
            marcos = []
            fallo = None
            for dia, futuro in zip(lote, futuros):
                try:
                    marcos.append(decodificar(futuro.result(), dia, info["divisor"]))
                except (http.ErrorFuente, lzma.LZMAError) as e:
                    fallo = (dia, e)
                    break
                resumen["dias"] += 1
                resumen["hasta"] = dia.isoformat()
            utiles = [m for m in marcos if len(m)]
            if utiles:
                df = pd.concat(utiles, ignore_index=True)
                datos.guardar_anual(instrumento, "M1", df, raiz)
                resumen["velas"] += len(df)
            if fallo is None:
                break
            dia_fallo, excepcion = fallo
            if intento >= 3:
                resumen["error"] = f"{dia_fallo.isoformat()}: {excepcion}"
                break
            dormir(60)
            lote = lote[lote.index(dia_fallo):]
        if resumen["error"]:
            break
    if not resumen["error"] and not resumen.get("omitido") and resumen["velas"] == 0 and len(pendientes) >= 30:
        resumen["error"] = "sin datos en todo el rango solicitado"
    return resumen
