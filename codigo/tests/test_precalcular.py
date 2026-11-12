import json

import pytest

from quant import barrido, motor, ranking
from quant.investigacion import catalogo
from quant.panel import ficha_stats, precalcular
from tests.test_ficha_stats import TPL, _curva


def _alta(con, inst, verdict, params, family="cruce_medias"):
    fid = con.execute("INSERT INTO fichas (json, estado) VALUES (?, 'generada')",
                      (json.dumps({"universo": {"instrumentos": [inst], "plazo": "D1"}}),)).lastrowid
    metricas = {**TPL, "total": {**TPL.get("total", {}), "profit_factor": 1.0 + params.get("fast", 0) / 100}}
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?, ?, ?, ?)",
                (fid, inst, verdict, json.dumps({"veredicto": verdict, "metricas": metricas})))
    con.execute("INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter,"
                " ficha_id, data_until) VALUES (?, ?, ?, ?, 'D1', 'sin_filtro', ?, '2026-11-01')",
                (inst + json.dumps(params), family, json.dumps(params), json.dumps([inst]), fid))


@pytest.fixture
def con(tmp_path, monkeypatch):
    c = catalogo.abrir(tmp_path / "catalogo.db")
    barrido.ensure_schema(c)
    _alta(c, "AAA", "pasa", {"fast": 20, "slow": 100})
    _alta(c, "BBB", "dudosa", {"fast": 20, "slow": 100})
    _alta(c, "CCC", "no_pasa", {"fast": 20, "slow": 100})
    c.commit()
    ts, eq = _curva()
    monkeypatch.setattr(ficha_stats, "ejecutar", lambda raiz, ficha, inst: (motor.Resultado(ts, eq, (), 1000.0), 1000.0))
    yield c
    c.close()


def test_precalcular_guarda_el_analisis_y_no_repite(con, tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(precalcular, "analisis_de", lambda raiz, ficha, inst, vecinos: llamadas.append(inst) or {"n": 3})
    out = precalcular.precalcular(con, tmp_path)
    assert out["analisis"]["hechas"] == 2 and con.execute("SELECT COUNT(*) FROM panel_analisis").fetchone()[0] == 2
    assert sorted(r[0] for r in con.execute("SELECT clave FROM panel_analisis"))[0].startswith("r:")
    assert precalcular.precalcular(con, tmp_path)["analisis"]["saltadas"] == 2 and sorted(llamadas) == ["AAA", "BBB"]


def test_un_fallo_no_para_a_los_demas(con, tmp_path, monkeypatch):
    def fallo(raiz, ficha, inst, vecinos):
        if inst == "AAA":
            raise OSError("sin datos")
        return None
    monkeypatch.setattr(precalcular, "analisis_de", fallo)
    a = precalcular.precalcular(con, tmp_path)["analisis"]
    assert a["hechas"] == 1 and len(a["errores"]) == 1 and "AAA" in a["errores"][0]
    assert con.execute("SELECT json FROM panel_analisis").fetchone()[0] == "null"


def test_el_presupuesto_de_tiempo_para(con, tmp_path, monkeypatch):
    monkeypatch.setattr(precalcular, "analisis_de", lambda *a: {"n": 3})
    a = precalcular.precalcular(con, tmp_path, minutos=0)["analisis"]
    assert a["hechas"] == 0 and a["pendientes"] == 2


def test_vecinos_solo_un_parametro_distinto(tmp_path):
    c = catalogo.abrir(tmp_path / "c.db")
    barrido.ensure_schema(c)
    for inst, p in (("AAA", {"fast": 20, "slow": 100}), ("AAA", {"fast": 10, "slow": 100}),
                    ("AAA", {"fast": 10, "slow": 50}), ("BBB", {"fast": 20, "slow": 50})):
        _alta(c, inst, "no_pasa", p)
    latest = ranking.latest_results(c)
    base = next(r for r in latest if r["instrumento"] == "AAA" and json.loads(r["params_json"]) == {"fast": 20, "slow": 100})
    assert [v["etiqueta"] for v in precalcular.vecinos_barrido(latest, base)] == ["fast 10"]


import time
VISTOS = []
from quant.investigacion import laboratorio


@pytest.fixture
def con_lab(tmp_path, monkeypatch):
    c = catalogo.abrir(tmp_path / "lab.db")
    laboratorio.ensure_schema(c)
    ficha = json.dumps({"universo": {"instrumentos": ["US500"], "plazo": "M15"}, "gestion": {}})
    for i, (ver, inval, pf) in enumerate((("no_pasa", None, 1.2), ("pasa_validador", None, 1.0), ("no_pasa", "rota", None)), 1):
        entreno = None if inval else json.dumps({"metricas": {**TPL, "total": {**TPL["total"], "profit_factor": pf, "operaciones": 300}}})
        c.execute("INSERT INTO lab_experimentos (id, estrategia, noche, huella, ficha_json, cambios, veredicto, invalido, entreno_json)"
                  " VALUES (?, 'manual', '2026-11-12', ?, ?, 1, ?, ?, ?)", (i, f"h{i}", ficha, ver, inval, entreno))
    c.commit()
    ts, eq = _curva()
    vistos = []
    monkeypatch.setattr(ficha_stats, "ejecutar", lambda raiz, f, inst, hasta=None: vistos.append(hasta) or (
        motor.Resultado(ts, eq, (), 1000.0), 1000.0))
    VISTOS[:] = []
    VISTOS.append(vistos)
    yield c
    c.close()


def test_precalcular_lab_orden_y_presupuesto(con_lab, tmp_path, monkeypatch):
    monkeypatch.setattr(precalcular, "analisis_de", lambda raiz, f, inst, vecinos, hasta=None: {"n": 3, "hasta": hasta})
    out = precalcular.precalcular_lab(con_lab, tmp_path, minutos=5)
    assert out["hechas"] == 2 and out["errores"] == []
    assert {r[0]: r[1] for r in con_lab.execute("SELECT clave, json FROM panel_analisis")}.keys() == {"e:1", "e:2"}
    assert '"hasta": "2023-01-01"' in con_lab.execute("SELECT json FROM panel_analisis WHERE clave='e:1'").fetchone()[0]
    assert precalcular.precalcular_lab(con_lab, tmp_path)["saltadas"] == 2


def test_precalcular_lab_respeta_el_hasta_de_la_noche(con_lab, tmp_path, monkeypatch):
    monkeypatch.setattr(precalcular, "analisis_de", lambda *a, **k: {"n": 3})
    out = precalcular.precalcular_lab(con_lab, tmp_path, minutos=5, hasta=time.monotonic() - 1)
    assert out["hechas"] == 0 and out["pendientes"] == 2


def test_un_experimento_que_falla_no_para(con_lab, tmp_path, monkeypatch):
    def analisis(raiz, f, inst, vecinos, hasta=None):
        if not analisis.llamadas:
            analisis.llamadas.append(1)
            raise ValueError("raro")
        return {"n": 3}
    analisis.llamadas = []
    monkeypatch.setattr(precalcular, "analisis_de", analisis)
    out = precalcular.precalcular_lab(con_lab, tmp_path, minutos=5)
    assert out["hechas"] == 1 and len(out["errores"]) == 1 and "#1" in out["errores"][0]


def test_vecinos_lab_un_cambio():
    base = {"entrada": {"largo": {"y": ["A", "B"]}}, "gestion": {"stop": {"tipo": "pct", "valor": 1}}}
    uno = json.loads(json.dumps(base)); uno["entrada"]["largo"]["y"] = ["A", "C"]
    dos = json.loads(json.dumps(uno)); dos["entrada"]["largo"]["y"] = ["D", "C"]
    pf = lambda v: json.dumps({"metricas": {"total": {"profit_factor": v}}})
    filas = [{"id": 1, "ficha_json": json.dumps(base), "entreno_json": pf(1.0)},
             {"id": 2, "ficha_json": json.dumps(uno), "entreno_json": pf(1.1)},
             {"id": 3, "ficha_json": json.dumps(dos), "entreno_json": pf(0.9)}]
    v = precalcular.vecinos_lab(filas, base, 1)
    assert [x["pf"] for x in v] == [1.1] and v[0]["etiqueta"]


def test_precalcular_lab_no_hace_backtests_que_nadie_lee(con_lab, tmp_path, monkeypatch):
    monkeypatch.setattr(precalcular, "analisis_de", lambda *a, **k: {"n": 3})
    precalcular.precalcular_lab(con_lab, tmp_path, minutos=5)
    assert VISTOS[0] == []


def test_precalcular_lab_salta_filas_rotas(con_lab, tmp_path, monkeypatch):
    con_lab.execute("UPDATE lab_experimentos SET entreno_json = '{roto' WHERE id = 2")
    con_lab.commit()
    monkeypatch.setattr(precalcular, "analisis_de", lambda *a, **k: {"n": 3})
    out = precalcular.precalcular_lab(con_lab, tmp_path, minutos=5)
    assert out["hechas"] == 1
