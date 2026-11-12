from quant.familias import Family, serie


def generate(p, instruments, timeframe, filter):
    return serie("otro", instruments, timeframe, {">": ["close", 0]}, None, {})


FAMILY = Family(
    "control_comprar_mantener", "Compra al principio y no vende nunca: la referencia contra la que se compara todo lo demás.",
    {}, ("US500", "BTCUSDT"), ("D1",), "serie_temporal", generate)
