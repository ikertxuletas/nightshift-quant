from quant.familias import ALL_CLASSES, STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    return serie("ruptura", instruments, timeframe, {"cruza_arriba": ["close", f"MAX({p['entry']})[1]"]},
                 {"cruza_abajo": ["close", f"MIN({p['exit']})[1]"]}, {"stop": stop(p)})


FAMILY = Family(
    "ruptura_donchian", "Compra al superar el máximo de los últimos N días y vende al romper el mínimo de los últimos M.",
    {"entry": (20, 55, 100), "exit": (10, 20), "stop_atr": STOP_ATR},
    ALL_CLASSES, ("D1",), "serie_temporal", generate)
