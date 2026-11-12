import numpy as np

from quant import datos
from quant.panel import piezas


def test_logo_desconocido_usa_las_letras_y_escapa():
    s = piezas.logo("<X>YZ", 20)
    assert "&lt;X&gt;Y" in s and "<X>" not in s and 'width="20"' in s


def test_mercado_mini_salta_lo_que_falta(tmp_path, monkeypatch):
    def cargar(inst, plazo, raiz=None, desde=None):
        if inst == "ETHUSDT":
            raise datos.ErrorDatos("pendiente")
        return {"ts": np.arange(3).astype("datetime64[D]").astype("datetime64[ns]"), "close": np.array([100.0, 100.0, 101.0])}
    piezas._MERCADO_CACHE.clear()
    monkeypatch.setattr(piezas.datos, "cargar", cargar)
    m = piezas.mercado_mini(tmp_path)
    assert [x["instrumento"] for x in m] == ["US500", "BTCUSDT"] and round(m[0]["cambio_pct"], 2) == 1.0


def test_cifra_con_ayuda_escapa_y_enlaza():
    a = piezas.ayuda("h1", "Qué es <b>", "Texto <i>", glosario="Demo")
    s = piezas.cifra("Resultado", "−27,27 €", "sobre 5.000 €", "baja", a, grande=True)
    assert 'popovertarget="h1"' in s and 'id="h1"' in s and "&lt;b&gt;" in s and "&lt;i&gt;" in s
    assert 'href="/glosario#demo"' in s and "baja" in s


def test_barra_uno_marca_el_1_y_satura():
    s = piezas.barra_uno(5.0)
    assert 'width="100.0"' in s and 'x="50.0"' in s


def test_selector_y_deshabilitadas():
    s = piezas.selector("p", [("1", "Día"), ("30", "Mes"), ("0", "Todo")], "0", deshabilitadas=("30",))
    assert 'data-p="0" aria-pressed="true"' in s and 'data-p="30"' in s and "disabled" in s


def test_graficos_no_rompe_el_script():
    s = piezas.graficos([{"id": "g", "series": [{"tipo": "linea", "color": "acento", "datos": [{"time": 1, "value": 1}]}], "texto": "</script><b>"}])
    assert "</script><b>" not in s and "graficos.js" in s


def test_spark_dibuja_y_aguanta_valores_iguales():
    s = piezas.spark([1.0, 1.0, 1.0], 70, 28, "sube")
    assert "<polyline" in s and 'class="spark sube"' in s and "nan" not in s
    assert piezas.spark([], 70, 28, "suave") == ""
