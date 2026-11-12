from quant.familias import STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    return serie("reversion", instruments, timeframe,
                 {"y": [{"<": [f"RSI({p['n']})", p["threshold"]]}, {">": ["close", "SMA(200)"]}]},
                 {"cruza_arriba": ["close", "SMA(5)"]}, {"stop": stop(p)})


FAMILY = Family(
    "rsi_reversion", "Compra tras una caída fuerte (RSI muy bajo) si el precio sigue sobre su media de 200 días; vende al recuperar la media corta.",
    {"n": (2, 3), "threshold": (5, 10, 20), "stop_atr": STOP_ATR},
    ("indice", "accion"), ("D1",), "serie_temporal", generate)
