import numpy as np

from quant.investigacion import mapa


def _ficha(stop):
    return {"forma": "serie_temporal", "universo": {"instrumentos": ["X"], "plazo": "D1"},
            "entrada": {"largo": {">": ["close", 0]}},
            "gestion": {"tamano": {"tipo": "riesgo", "valor": 1}, "stop": stop, "max_barras": 1,
                        "perdida_diaria_max": 2}}


def _diarias(barras, n, inicio):
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    return barras(c, open=np.r_[c[0], c[:-1]], inicio=inicio, paso="1D")


def test_mapa_solo_mira_antes_del_corte(barras, costes_cero):
    b = _diarias(barras, 900, "2022-01-01")
    m = mapa.mapa(_ficha({"tipo": "pct", "valor": 5}), "X", b, costes_cero(), "2023-01-01")
    assert m["ops"] > 100 and set(m["grupos"]["anio"]) == {2022}


def test_mapa_agrupa_por_lado_y_salida(barras, costes_cero):
    b = barras([100] * 5, open=[100] * 5, high=[101, 102, 100.5, 100.5, 100.5], low=[99, 99.5, 98, 99.5, 99.5])
    f = _ficha({"tipo": "pct", "valor": 1})
    f["gestion"]["objetivo"] = {"tipo": "pct", "valor": 1}
    del f["gestion"]["max_barras"]
    m = mapa.mapa(f, "X", b, costes_cero(), "2030-01-01")
    salida = m["grupos"]["salida"]
    assert {"objetivo", "stop"} <= set(salida) and salida["objetivo"]["pf_sin"] is None
    assert set(m["grupos"]["lado"]) == {"largo"}


def test_mapa_con_stop_atr(barras, costes_cero):
    b = _diarias(barras, 300, "2022-01-01")
    assert mapa.mapa(_ficha({"tipo": "atr", "valor": 2}), "X", b, costes_cero(), "2030-01-01")["ops"] > 50


def test_texto_es_compacto(barras, costes_cero):
    b = _diarias(barras, 300, "2022-01-01")
    t = mapa.texto("base", mapa.mapa(_ficha({"tipo": "pct", "valor": 5}), "X", b, costes_cero(), "2030-01-01"))
    assert "lado" in t and "largo" in t and "pf" in t
    assert max(len(linea) for linea in t.splitlines()) <= 200


def test_mapa_sin_stop_usa_el_trailing(barras, costes_cero):
    b = _diarias(barras, 300, "2022-01-01")
    f = _ficha({"tipo": "pct", "valor": 5})
    del f["gestion"]["stop"]
    f["gestion"]["trailing"] = {"tipo": "atr", "valor": 2}
    assert mapa.mapa(f, "X", b, costes_cero(), "2030-01-01")["ops"] > 50


import pytest


@pytest.mark.parametrize("stop", [{"tipo": "pct", "valor": 2}, {"tipo": "atr", "valor": 1}, {"tipo": "barras", "valor": 3}])
def test_salida_por_stop_vale_menos_un_r(barras, costes_cero, stop):
    b = _diarias(barras, 400, "2022-01-01")
    f = _ficha(stop)
    del f["gestion"]["max_barras"]
    f["salida"] = {"largo": {"<": ["close", 0]}}
    rs = [x["R"] for x in mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01") if x["salida"] == "stop"]
    huecos = [r for r in rs if abs(r + 1) > 1e-9]
    assert len(rs) >= 2 and len(huecos) <= len(rs) // 3 and all(r <= -1 + 1e-9 for r in huecos)
