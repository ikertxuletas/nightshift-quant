from quant.familias import STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    z = f"ZSCORE({p['n']})"
    return serie("reversion", instruments, timeframe, {"<": [z, -p["z"]]}, {">": [z, 0]}, {"stop": stop(p)})


FAMILY = Family(
    "zscore_reversion", "Compra cuando el precio está muy por debajo de su media (Z desviaciones) y vende al volver a ella.",
    {"n": (20, 50), "z": (1.5, 2), "stop_atr": STOP_ATR},
    ("forex",), ("H4", "D1"), "serie_temporal", generate)
