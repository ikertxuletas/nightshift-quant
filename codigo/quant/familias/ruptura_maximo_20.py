from quant.familias import STOP_ATR, Family, serie, stop


def generate(p, instruments, timeframe, filter):
    entry = {"y": [{"cruza_arriba": ["close", f"MAX({p['n']})[1]"]}, {"<": [f"VOL({p['vol']})", "VOL(100)"]}]}
    return serie("ruptura", instruments, timeframe, entry, None, {"stop": stop(p), "max_barras": 20})


FAMILY = Family(
    "ruptura_maximo_20", "Compra al cerrar en máximo de 20 días cuando la volatilidad previa era baja; sale por stop o a las 20 velas.",
    {"n": (20,), "vol": (20,), "stop_atr": STOP_ATR},
    ("indice", "cripto"), ("D1",), "serie_temporal", generate)
