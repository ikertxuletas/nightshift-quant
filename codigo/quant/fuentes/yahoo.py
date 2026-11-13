import time

import pandas as pd

from quant import datos, rutas
from quant.fuentes import http


def descargar(simbolo, desde, bajar=None, hoy=None):
    if bajar is None:
        import yfinance
        bajar = yfinance.download
    crudo = bajar(simbolo, start=desde, interval="1d", auto_adjust=True, progress=False,
                  multi_level_index=False, threads=False)
    if crudo is None or crudo.empty:
        raise http.ErrorFuente(f"sin datos de yahoo para {simbolo}")
    df = crudo.rename(columns=str.lower).reset_index()
    df = df.rename(columns={df.columns[0]: "ts"})
    df = df[datos.COLUMNAS].dropna(subset=["open", "high", "low", "close"])
    # A run during market hours gets a partial bar for today: keep only finished days.
    hoy = pd.Timestamp.now().normalize() if hoy is None else pd.Timestamp(hoy)
    return df[pd.to_datetime(df["ts"]) < hoy]


def _descarga_sospechosa(df, instrumento, raiz, desde=None):
    try:
        anteriores = datos.cargar(instrumento, "D1", raiz, desde=desde)
    except datos.ErrorDatos:
        return None
    guardadas = len(anteriores["ts"])
    if guardadas == 0:
        return None
    if len(df) < 0.95 * guardadas:
        return f"descarga sospechosa: {len(df)} velas frente a {guardadas} guardadas"
    ultimo_guardado = pd.Timestamp(anteriores["ts"].max())
    ultimo_descargado = pd.Timestamp(df["ts"].max())
    if ultimo_descargado < ultimo_guardado:
        return (f"descarga sospechosa: ultimo dato {ultimo_descargado.date()} "
                f"anterior al guardado {ultimo_guardado.date()}")
    return None


def actualizar(instrumento, info, raiz=rutas.DATOS, bajar=None, pausa=1.0, dormir=time.sleep, hoy=None):
    resumen = {"instrumento": instrumento, "velas": 0, "hasta": None, "error": None}
    try:
        df = descargar(info["simbolo"], info["desde"], bajar, hoy)
        motivo = _descarga_sospechosa(df, instrumento, raiz, info["desde"])
        if motivo:
            resumen["error"] = motivo
        else:
            datos.guardar(instrumento, "D1", df, raiz)
            resumen["velas"] = len(df)
            resumen["hasta"] = pd.Timestamp(df["ts"].max()).date().isoformat()
    except Exception as e:
        resumen["error"] = f"{type(e).__name__}: {e}"
    dormir(pausa)
    return resumen
