import pytest

from quant import costes, rutas

CONFIG = {
    "brokers": {"darwinex": {"indice": {"spread_pct": 0.0002, "comision_pct": 0.0, "deslizamiento_pct": 0.0001,
                                        "swap_pct_anual": 0.06, "apalancamiento": 20, "permite_corto": True}}},
    "instrumentos": {"US500": "darwinex/indice"},
}


def test_costes_de():
    c = costes.costes_de("US500", CONFIG)
    assert (c.broker, c.clase, c.apalancamiento) == ("darwinex", "indice", 20)


def test_instrumento_desconocido():
    with pytest.raises(costes.ErrorCostes):
        costes.costes_de("NOEXISTE", CONFIG)


def test_escalar_no_muta():
    c = costes.costes_de("US500", CONFIG)
    doble = c.escalar(2)
    assert doble.spread_pct == pytest.approx(0.0004) and doble.swap_pct_anual == pytest.approx(0.12)
    assert c.spread_pct == pytest.approx(0.0002) and doble.apalancamiento == 20


def test_precio_ejecucion():
    c = costes.costes_de("US500", CONFIG)
    assert c.precio_ejecucion(100, compra=True) == pytest.approx(100 * 1.0002)
    assert c.precio_ejecucion(100, compra=False) == pytest.approx(100 * 0.9998)


def test_config_real_resuelve_todo():
    cfg = costes.cargar(rutas.CONFIG / "costes.json")
    for instrumento in cfg["instrumentos"]:
        assert costes.costes_de(instrumento, cfg).spread_pct > 0


def test_costes_por_clase():
    cfg = {**CONFIG, "por_clase": {"indice": "darwinex/indice"}}
    assert costes.costes_de("NUEVO", cfg, clase="indice").broker == "darwinex"
    with pytest.raises(costes.ErrorCostes):
        costes.costes_de("NUEVO", cfg, clase="cripto")
    with pytest.raises(costes.ErrorCostes):
        costes.costes_de("NUEVO", cfg)
