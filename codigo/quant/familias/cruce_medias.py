from quant.familias import ALL_CLASSES, STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    fast, slow = f"{p['kind']}({p['fast']})", f"{p['kind']}({p['slow']})"
    return serie("tendencia", instruments, timeframe, {"cruza_arriba": [fast, slow]},
                 {"cruza_abajo": [fast, slow]}, {"stop": stop(p)})


FAMILY = Family(
    "cruce_medias", "Compra cuando la media rápida cruza por encima de la lenta y vende cuando la cruza por debajo.",
    {"fast": (10, 20, 50), "slow": (50, 100, 200), "kind": ("SMA", "EMA"), "stop_atr": STOP_ATR},
    ALL_CLASSES, ("H4", "D1"), "serie_temporal", generate, lambda p: p["fast"] < p["slow"])
