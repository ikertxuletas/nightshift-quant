import os
from pathlib import Path

import pandas as pd

from quant import rutas

COLUMNAS = ["ts", "open", "high", "low", "close", "volume"]
ORDEN = ["M1", "M5", "M15", "H1", "H4", "D1", "W1"]
_REGLAS = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1D", "W1": "W-MON"}


class ErrorDatos(RuntimeError):
    pass


def _ruta(raiz, instrumento, resolucion):
    return Path(raiz) / instrumento / f"{resolucion}.parquet"


def _carpeta(raiz, instrumento, resolucion):
    return Path(raiz) / instrumento / resolucion


def _limpiar(df, instrumento, resolucion):
    faltan = [c for c in COLUMNAS if c not in df.columns]
    if faltan or resolucion not in ORDEN:
        raise ErrorDatos(f"datos inválidos para {instrumento} {resolucion}: faltan {faltan}")
    limpio = df[COLUMNAS].copy()
    ts = pd.to_datetime(limpio["ts"])
    limpio["ts"] = ts.dt.tz_convert("UTC").dt.tz_localize(None) if ts.dt.tz is not None else ts
    return limpio.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)


def _escribir(destino, df):
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    df.to_parquet(temporal, index=False)
    os.replace(temporal, destino)
    return destino


def guardar(instrumento, resolucion, df, raiz=rutas.DATOS):
    return _escribir(_ruta(raiz, instrumento, resolucion), _limpiar(df, instrumento, resolucion))


def guardar_anual(instrumento, resolucion, df, raiz=rutas.DATOS):
    nuevo = _limpiar(df, instrumento, resolucion)
    escritos = []
    for anio, parte in nuevo.groupby(nuevo["ts"].dt.year):
        destino = _carpeta(raiz, instrumento, resolucion) / f"{anio}.parquet"
        if destino.exists():
            parte = _limpiar(pd.concat([pd.read_parquet(destino), parte]), instrumento, resolucion)
        escritos.append(_escribir(destino, parte))
    return escritos


def _particiones(raiz, instrumento, resolucion):
    carpeta = _carpeta(raiz, instrumento, resolucion)
    return sorted(carpeta.glob("*.parquet")) if carpeta.is_dir() else []


def resoluciones(instrumento, raiz=rutas.DATOS):
    return [r for r in ORDEN if _particiones(raiz, instrumento, r) or _ruta(raiz, instrumento, r).exists()]


def _leer(raiz, instrumento, resolucion):
    partes = _particiones(raiz, instrumento, resolucion)
    if partes:
        df = pd.concat([pd.read_parquet(p) for p in partes], ignore_index=True)
        return df.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    return pd.read_parquet(_ruta(raiz, instrumento, resolucion))


def ultimo_ts(instrumento, resolucion, raiz=rutas.DATOS):
    partes = _particiones(raiz, instrumento, resolucion)
    if partes:
        return pd.read_parquet(partes[-1], columns=["ts"])["ts"].max()
    ruta = _ruta(raiz, instrumento, resolucion)
    return pd.read_parquet(ruta, columns=["ts"])["ts"].max() if ruta.exists() else None


def meses_con_velas(instrumento, resolucion, raiz=rutas.DATOS):
    partes = _particiones(raiz, instrumento, resolucion)
    if not partes:
        ruta = _ruta(raiz, instrumento, resolucion)
        partes = [ruta] if ruta.exists() else []
    meses = set()
    for p in partes:
        ts = pd.read_parquet(p, columns=["ts"])["ts"]
        meses.update((int(a), int(m)) for a, m in zip(ts.dt.year, ts.dt.month))
    return meses


def cargar(instrumento, plazo, raiz=rutas.DATOS, desde=None):
    candidatas = [r for r in resoluciones(instrumento, raiz) if ORDEN.index(r) <= ORDEN.index(plazo)]
    if not candidatas:
        raise ErrorDatos(f"pendiente de datos: {instrumento} {plazo}")
    base = candidatas[-1]
    df = _leer(raiz, instrumento, base).sort_values("ts")
    if desde is not None:
        df = df[df["ts"] >= pd.Timestamp(desde)]
    if base != plazo:
        df = (df.set_index("ts")
                .resample(_REGLAS[plazo], label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna(subset=["open"])
                .reset_index())
    salida = {"ts": df["ts"].to_numpy("datetime64[ns]")}
    salida.update({c: df[c].to_numpy(float) for c in COLUMNAS[1:]})
    return salida
