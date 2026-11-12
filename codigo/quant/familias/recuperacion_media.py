from quant.familias import ALL_CLASSES, STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    ma = f"SMA({p['n']})"
    return serie("reversion", instruments, timeframe, {"cruza_arriba": ["close", ma]},
                 {"cruza_abajo": ["close", ma]}, {"stop": stop(p)})


FAMILY = Family(
    "recuperacion_media", "Compra cuando el precio vuelve a cerrar sobre su media tras haber estado por debajo; vende si la pierde otra vez.",
    {"n": (20, 50), "stop_atr": STOP_ATR},
    ALL_CLASSES, ("D1",), "serie_temporal", generate)
