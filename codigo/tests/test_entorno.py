from quant import rutas


def test_rutas_por_defecto():
    assert rutas.CONFIG == rutas.RAIZ / "config"
    assert rutas.DATOS == rutas.RAIZ / "datos"


def test_fixture_barras(barras):
    b = barras([1, 2, 3], paso="15m")
    assert (b["ts"][1] - b["ts"][0]) == __import__("numpy").timedelta64(15, "m")
    assert list(b["high"]) == [2, 3, 4]
