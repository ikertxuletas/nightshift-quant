from quant.familias import STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    ema = f"EMA({p['n']})"
    return serie("tendencia", instruments, timeframe, {"cruza_arriba": ["close", ema]},
                 {"cruza_abajo": ["close", ema]}, {"stop": stop(p)})


FAMILY = Family(
    "tendencia_cripto", "Está comprado en BTC y ETH mientras el precio se mantenga sobre su media exponencial larga.",
    {"n": (50, 100, 200), "stop_atr": STOP_ATR},
    ("BTCUSDT", "ETHUSDT"), ("D1",), "serie_temporal", generate)
