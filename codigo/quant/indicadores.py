"""Catálogo cerrado de indicadores. Cada valor usa solo datos hasta su vela incluida."""
import re

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

CAMPOS = ("open", "high", "low", "close", "volume")
_TOKEN = re.compile(r"^([A-Za-z_]+)(?:\(([^)]*)\))?(?:\[(-?\d+)\])?$")


class ErrorIndicador(ValueError):
    pass


def desplazar(x, k):
    out = np.full(len(x), np.nan)
    if k == 0:
        return np.asarray(x, float).copy()
    if k < len(x):
        out[k:] = x[:-k]
    return out


def _ventana(x, n, fn):
    out = np.full(len(x), np.nan)
    if 1 <= n <= len(x):
        out[n - 1:] = fn(sliding_window_view(x, n), axis=1)
    return out


def sma(x, n):
    return _ventana(x, n, np.mean)


def desviacion(x, n):
    return _ventana(x, n, np.std)


def ema(x, n):
    out = np.full(len(x), np.nan)
    if n > len(x):
        return out
    alfa = 2.0 / (n + 1)
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = alfa * x[i] + (1 - alfa) * out[i - 1]
    return out


def _wilder(valores, n, inicio):
    out = np.full(len(valores), np.nan)
    if inicio + n > len(valores):
        return out
    out[inicio + n - 1] = valores[inicio:inicio + n].mean()
    for i in range(inicio + n, len(valores)):
        out[i] = (out[i - 1] * (n - 1) + valores[i]) / n
    return out


def rsi(close, n):
    delta = np.diff(close, prepend=np.nan)
    media_g = _wilder(np.where(delta > 0, delta, 0.0), n, 1)
    media_p = _wilder(np.where(delta < 0, -delta, 0.0), n, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + media_g / media_p)
    return np.where(media_p == 0, np.where(media_g == 0, 50.0, 100.0), out)


def atr(high, low, close, n):
    previo = desplazar(close, 1)
    tr = np.maximum(high - low, np.maximum(np.abs(high - previo), np.abs(low - previo)))
    tr[0] = high[0] - low[0]
    return _wilder(tr, n, 0)


def _momentum(close, n):
    return close / desplazar(close, n) - 1


def _zscore(close, n):
    with np.errstate(divide="ignore", invalid="ignore"):
        return (close - sma(close, n)) / desviacion(close, n)


def _volatilidad(close, n):
    return desviacion(close / desplazar(close, 1) - 1, n)


def _wma(x, n):
    pesos = np.arange(1, n + 1, dtype=float)
    return _ventana(x, n, lambda v, axis: v @ pesos / pesos.sum())


def hma(close, n):
    bruta = 2 * _wma(close, n // 2) - _wma(close, n)
    out = np.full(len(close), np.nan)
    m = int(round(np.sqrt(n)))
    validos = np.flatnonzero(np.isfinite(bruta))
    if len(validos):
        out[validos[0]:] = _wma(bruta[validos[0]:], m)
    return out


def mfi(high, low, close, volume, n):
    tipico = (high + low + close) / 3
    flujo = tipico * volume
    previo = desplazar(tipico, 1)
    positivo = _ventana(np.where(tipico > previo, flujo, 0.0), n, np.sum)
    negativo = _ventana(np.where(tipico < previo, flujo, 0.0), n, np.sum)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + positivo / negativo)
    out = np.where(negativo == 0, 100.0, out)
    out[:n] = np.nan
    return out


def estocastico(high, low, close, n, suavizado):
    # MT5 iStochastic main line with STO_LOWHIGH: sums over the slowing window, not an SMA of %K.
    bajo, alto = _ventana(low, n, np.min), _ventana(high, n, np.max)
    arriba, rango = _ventana(close - bajo, suavizado, np.sum), _ventana(alto - bajo, suavizado, np.sum)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(rango == 0, 100.0, 100 * arriba / rango)


def rango_dia(b, k):
    """High-low range of the k-th previous calendar day (UTC) present in the data."""
    dia = np.asarray(b["ts"]).astype("datetime64[D]")
    inicios = np.flatnonzero(np.r_[True, dia[1:] != dia[:-1]])
    rango = np.maximum.reduceat(b["high"], inicios) - np.minimum.reduceat(b["low"], inicios)
    cual = np.cumsum(np.r_[True, dia[1:] != dia[:-1]]) - 1 - k
    return np.where(cual >= 0, rango[np.maximum(cual, 0)], np.nan)


CATALOGO = {
    "SMA": (1, lambda b, n: sma(b["close"], n)),
    "EMA": (1, lambda b, n: ema(b["close"], n)),
    "RSI": (1, lambda b, n: rsi(b["close"], n)),
    "ATR": (1, lambda b, n: atr(b["high"], b["low"], b["close"], n)),
    "BB_SUP": (2, lambda b, n, k: sma(b["close"], n) + k * desviacion(b["close"], n)),
    "BB_INF": (2, lambda b, n, k: sma(b["close"], n) - k * desviacion(b["close"], n)),
    "MAX": (1, lambda b, n: _ventana(b["high"], n, np.max)),
    "MIN": (1, lambda b, n: _ventana(b["low"], n, np.min)),
    "MOM": (1, lambda b, n: _momentum(b["close"], n)),
    "ZSCORE": (1, lambda b, n: _zscore(b["close"], n)),
    "VOL": (1, lambda b, n: _volatilidad(b["close"], n)),
    "HMA": (1, lambda b, n: hma(b["close"], n)),
    "RANGO_DIA": (1, lambda b, n: rango_dia(b, n)),
}


def analizar(token):
    m = _TOKEN.match(token.strip())
    if not m:
        raise ErrorIndicador(f"token ilegible: {token}")
    nombre, args_txt, lag_txt = m.groups()
    lag = int(lag_txt) if lag_txt else 0
    if lag < 0:
        raise ErrorIndicador(f"retardo negativo (mira al futuro): {token}")
    if nombre in CAMPOS:
        if args_txt is not None:
            raise ErrorIndicador(f"un campo no lleva argumentos: {token}")
        return nombre, (), lag
    if nombre not in CATALOGO:
        raise ErrorIndicador(f"indicador fuera del catálogo: {nombre}")
    esperados = CATALOGO[nombre][0]
    try:
        args = tuple(float(a) for a in (args_txt or "").split(",")) if args_txt else ()
    except ValueError as e:
        raise ErrorIndicador(f"argumentos no numéricos: {token}") from e
    if len(args) != esperados:
        raise ErrorIndicador(f"{nombre} necesita {esperados} argumento(s): {token}")
    if not args[0].is_integer() or args[0] < 1:
        raise ErrorIndicador(f"el periodo debe ser entero >= 1: {token}")
    return nombre, (int(args[0]),) + args[1:], lag


def calcular(token, barras, cache=None):
    clave = token.replace(" ", "")
    if cache is not None and clave in cache:
        return cache[clave]
    nombre, args, lag = analizar(clave)
    base = np.asarray(barras[nombre], float) if nombre in CAMPOS else CATALOGO[nombre][1](barras, *args)
    valor = desplazar(base, lag)
    if cache is not None:
        cache[clave] = valor
    return valor
