import json
import pytest

from quant import barrido, ranking
from quant import ficha as ficha_mod
from quant.familias import propias
from quant.investigacion import catalogo

UNI = {"instrumentos": {"US500": {"clase": "indice"}, "BTCUSDT": {"clase": "cripto"}}}


def _con():
    con = catalogo.abrir(":memory:")
    barrido.ensure_schema(con)
    return con


def _add(con, family):
    res = {"veredicto": "pasa", "criterios": [], "metricas": {"total": {}, "fuera": {"sharpe": 1.0}}}
    fid = con.execute("INSERT INTO fichas (json, estado) VALUES ('{}', 'generada')").lastrowid
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?, 'US500', 'pasa', ?)",
                (fid, json.dumps(res)))
    con.execute("INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter,"
                " ficha_id, data_until) VALUES (?, ?, '{}', '[\"US500\"]', 'D1', 'sin_filtro', ?, '2026-01-01')",
                (family, family, fid))
    con.commit()


def test_ficha_base_de_ejemplo_es_valida():
    f = propias.ficha_base("ejemplo")
    assert ficha_mod.errores(f) == [] and f["universo"] == {"instrumentos": ["US500"], "plazo": "M15"}
    p = propias.PROPIAS["ejemplo"]
    assert (p.corte, p.confirmacion, p.params) == ("2023-01-01", "2026-04-01", {"n": 2, "umbral": 10})


def test_el_barrido_no_encola_propias():
    assert propias.es_propia("ejemplo") and not propias.es_propia("cruce_medias")
    cola = barrido.queue(_con(), UNI, "2026-11-03", [])
    assert cola and not [c for c in cola if propias.es_propia(c.family)]


def test_el_ranking_ignora_propias():
    con = _con()
    _add(con, "ejemplo")
    _add(con, "cruce_medias")
    assert {r["family"] for r in ranking.rows(con, uni=UNI)} == {"cruce_medias"}
    assert "ejemplo" not in {s["family"] for s in ranking.family_stats(con)}


def test_ficha_base_de_la_manual_es_valida():
    f = propias.ficha_base("manual")
    assert ficha_mod.errores(f) == []
    assert f["gestion"]["objetivo"] == {"tipo": "atr", "valor": 3.0} and f["horario"]["cierre"] == "15:55"


@pytest.mark.parametrize("tendencia, entra", [(2.0, False), (0.0, True)])
def test_la_manual_solo_compra_sobre_la_media_de_200(monkeypatch, tendencia, entra):
    import numpy as np
    from quant import indicadores, motor
    rapida = np.array([40.0] * 5 + [60.0] * 5)
    monkeypatch.setitem(indicadores.CATALOGO, "EMA", (1, lambda b, n: rapida if n == 9 else np.full(10, 50.0)))
    monkeypatch.setitem(indicadores.CATALOGO, "SMA", (1, lambda b, n: np.full(10, tendencia)))
    b = {"close": np.ones(10)}
    largo = propias.ficha_base("manual")["entrada"]["largo"]
    assert motor._senal(largo, b, {}, 10).any() == entra


def test_ficha_base_es_una_copia_nueva():
    f = propias.ficha_base("ejemplo")
    f["horario"]["cierre"] = 1545
    f["gestion"]["riesgo"] = 99
    assert propias.ficha_base("ejemplo") == propias.ficha_base("ejemplo")
    assert "cierre" not in propias.ficha_base("ejemplo")["horario"]
