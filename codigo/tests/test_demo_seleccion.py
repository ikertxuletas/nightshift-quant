import json
from datetime import datetime
from pathlib import Path

from quant.barrido import ensure_schema
from quant.demo import diario, seleccion
from quant.demo.config import cargar
from quant.investigacion import catalogo

CFG = cargar(Path(__file__).parents[2] / "config" / "demo.json")
UNI = {"instrumentos": {**{k: {"clase": "indice", "fuente": "dukascopy"} for k in ["A", "B", "C", "D", "E", "F", "G", "US500"]},
                        "BTCUSDT": {"clase": "cripto", "fuente": "binance"}, "Y": {"clase": "accion", "fuente": "yahoo"}}}
NOW = datetime(2026, 11, 3)
_n = [0]


def con_():
    con = catalogo.abrir(":memory:")
    ensure_schema(con)
    diario.ensure_schema(con)
    return con


def add(con, instrument, verdict, family="f", sharpe=1.0, failed=(), forma="serie_temporal"):
    _n[0] += 1
    res = {"criterios": [{"criterio": c, "cumple": False} for c in failed],
           "metricas": {"total": {}, "fuera": {"sharpe": sharpe}}}
    fid = con.execute("INSERT INTO fichas (json, estado) VALUES (?, 'g')",
                      (json.dumps({"id": f"{family}-{_n[0]}", "forma": forma, "gestion": {}}),)).lastrowid
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?,?,?,?)",
                (fid, instrument, verdict, json.dumps(res)))
    cur = con.execute(
        "INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter, ficha_id, data_until)"
        " VALUES (?,?,?,?, 'D1', 'x', ?, '2026-01-01')",
        (f"fp{_n[0]}", family, json.dumps({"n": _n[0]}), json.dumps([instrument]), fid))
    con.commit()
    return cur.lastrowid


def chosen_of(con):
    return seleccion.select(con, CFG, uni=UNI)


def test_select_always_includes_control():
    out = chosen_of(con_())
    assert sorted(c["instrument"] for c in out if c["label"] == "control") == ["BTCUSDT", "US500"]
    assert all(c["ficha"] for c in out)


def test_select_fills_with_dudosa_then_en_prueba():
    con = con_()
    add(con, "A", "pasa", family="f1", sharpe=0.5)
    add(con, "B", "dudosa", family="f2", sharpe=2.0)
    add(con, "C", "no_pasa", family="f3", failed=("a", "b"))
    add(con, "D", "no_pasa", family="f4", failed=("a",))
    out = [c for c in chosen_of(con) if c["label"] != "control"]
    assert [(c["instrument"], c["label"]) for c in out] == [("A", "aprobada"), ("B", "dudosa"), ("D", "en_prueba"),
                                                            ("C", "en_prueba")]


def test_select_diversity_limits():
    con = con_()
    for i, inst in enumerate(["A", "B", "C", "D", "E", "F"]):
        add(con, inst, "pasa", family="same", sharpe=10 - i)
    add(con, "A", "pasa", family="other", sharpe=1)
    add(con, "G", "pasa", family="tr", sharpe=1, forma="transversal")
    out = [c for c in chosen_of(con) if c["label"] != "control"]
    assert [c["family"] for c in out].count("same") == 2
    assert len({c["instrument"] for c in out}) == len(out)
    assert "G" not in {c["instrument"] for c in out}


def test_select_keeps_incumbents():
    con = con_()
    add(con, "A", "pasa", family="f1", sharpe=1)
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    for inst, fam, sh in [("B", "f2", 9), ("C", "f3", 8), ("D", "f4", 7), ("E", "f5", 6), ("F", "f6", 5)]:
        add(con, inst, "pasa", family=fam, sharpe=sh)
    second = chosen_of(con)
    kept = [c for c in second if c["instrument"] == "A"]
    assert kept and kept[0]["existing_id"] is not None
    assert sum(c["label"] != "control" for c in second) == CFG["n_demo"]
    seleccion.apply(con, second, NOW, CFG)
    act = diario.active(con)
    assert len(act) == 2 + CFG["n_demo"] and all(r["capital"] == CFG["capital"] / len(act) for r in act)
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    assert len(diario.active(con)) == len(act)


def test_apply_retires_worsened():
    con = con_()
    add(con, "A", "pasa", family="f1")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    con.execute("UPDATE resultados SET veredicto='no_pasa'")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    r = con.execute("SELECT status, retire_reason_es FROM demo_strategies WHERE instrument='A'").fetchone()
    assert r[0] == "retired" and "empeor" in r[1]


def test_retired_not_reselectable_until_90_days_more_data():
    con = con_()
    cid = add(con, "A", "pasa", family="f1")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    con.execute("UPDATE resultados SET veredicto='no_pasa'")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    con.execute("UPDATE resultados SET veredicto='pasa'")
    assert "A" not in {c["instrument"] for c in chosen_of(con)}
    con.execute("UPDATE combinations SET data_until='2027-02-02' WHERE id=?", (cid,))
    assert "A" in {c["instrument"] for c in chosen_of(con)}


def test_incumbent_label_refreshed_when_verdict_improves():
    con = con_()
    add(con, "A", "no_pasa", family="f1", failed=("a",))
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    assert con.execute("SELECT label FROM demo_strategies WHERE instrument='A'").fetchone()[0] == "en_prueba"
    con.execute("UPDATE resultados SET veredicto='pasa'")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    assert con.execute("SELECT label FROM demo_strategies WHERE instrument='A'").fetchone()[0] == "aprobada"
    assert con.execute("SELECT COUNT(*) FROM demo_strategies WHERE instrument='US500'").fetchone()[0] == 1


def retest(con, cid, verdict, data_until, failed=()):
    _n[0] += 1
    c = con.execute("SELECT * FROM combinations WHERE id=?", (cid,)).fetchone()
    res = {"criterios": [{"criterio": f, "cumple": False} for f in failed],
           "metricas": {"total": {}, "fuera": {"sharpe": 1.0}}}
    fid = con.execute("INSERT INTO fichas (json, estado) VALUES (?, 'g')",
                      (json.dumps({"id": f"{c['family']}-{_n[0]}", "forma": "serie_temporal", "gestion": {}}),)).lastrowid
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?,?,?,?)",
                (fid, json.loads(c["instruments_json"])[0], verdict, json.dumps(res)))
    con.execute("INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter, ficha_id,"
                " data_until) VALUES (?,?,?,?,?,?,?,?)", (f"fp{_n[0]}", c["family"], c["params_json"],
                                                         c["instruments_json"], c["timeframe"], c["filter"], fid, data_until))
    con.commit()


def test_retest_row_with_worse_verdict_retires_incumbent():
    con = con_()
    cid = add(con, "A", "pasa", family="f1")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    retest(con, cid, "no_pasa", "2026-02-01", failed=("a",))
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    rows = con.execute("SELECT status FROM demo_strategies WHERE instrument='A'").fetchall()
    assert [r[0] for r in rows] == ["retired"]


def test_retest_row_refreshes_incumbent_label():
    con = con_()
    cid = add(con, "A", "no_pasa", family="f1", failed=("a",))
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    retest(con, cid, "pasa", "2026-02-01")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    rows = con.execute("SELECT label, status FROM demo_strategies WHERE instrument='A'").fetchall()
    assert [tuple(r) for r in rows] == [("aprobada", "active")]


def test_drift_retired_not_reselected_via_retest_until_90_days_more_data():
    con = con_()
    cid = add(con, "A", "pasa", family="f1")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    con.execute("UPDATE demo_strategies SET status='retired', retired=? WHERE instrument='A'", (NOW.isoformat(),))
    retest(con, cid, "pasa", "2026-11-08")
    assert "A" not in {c["instrument"] for c in chosen_of(con)}
    retest(con, cid, "pasa", "2027-02-02")
    assert "A" in {c["instrument"] for c in chosen_of(con)}


def test_candidates_limited_to_minute_data_instruments():
    con = con_()
    add(con, "Y", "pasa", family="f1", sharpe=99)
    add(con, "A", "pasa", family="f2", sharpe=1)
    assert {c["instrument"] for c in chosen_of(con) if c["label"] != "control"} == {"A"}


def test_apply_stores_effective_ficha():
    con = con_()
    add(con, "A", "pasa", family="f1")
    seleccion.apply(con, chosen_of(con), NOW, CFG)
    g = json.loads(con.execute("SELECT ficha_json FROM demo_strategies WHERE instrument='A'").fetchone()[0])["gestion"]
    assert g["stop"] == {"tipo": "atr", "valor": CFG["stop_atr"][0]}
    assert g["tamano"] == {"tipo": "riesgo", "valor": CFG["risk_pct"]}
    for row in con.execute("SELECT ficha_json FROM demo_strategies WHERE label='control'"):
        assert "tamano" not in json.loads(row[0])["gestion"]
