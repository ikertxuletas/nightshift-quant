from quant.familias import STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    return serie("reversion", instruments, timeframe, {"cruza_abajo": ["close", f"BB_INF({p['n']},{p['k']})"]},
                 {"cruza_arriba": ["close", f"SMA({p['n']})"]}, {"stop": stop(p)})


FAMILY = Family(
    "bollinger_reversion", "Compra cuando el precio cierra por debajo de la banda inferior de Bollinger y vende al volver a la media.",
    {"n": (20,), "k": (2, 2.5), "stop_atr": STOP_ATR},
    ("forex", "indice"), ("H4", "D1"), "serie_temporal", generate)
