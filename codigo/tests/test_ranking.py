import json
import time

from quant import ranking
from quant.barrido import ensure_schema
from quant.investigacion import catalogo

UNI = {"instrumentos": {"A": {"clase": "indice"}, "B": {"clase": "indice"}, "C": {"clase": "indice"},
                        "D": {"clase": "accion"}}}


def _con():
    con = catalogo.abrir(":memory:")
    ensure_schema(con)
    return con


def _add(con, instrument, verdict, sharpe=1.0, family="f", params=None, data_until="2026-01-01", failed=()):
    res = {"veredicto": verdict,
           "criterios": [],
           "metricas": {"total": {"drawdown": 0.1, "cagr": 0.2, "operaciones": 50}, "fuera": {"sharpe": sharpe}}}
    if failed:
        res["criterios"] = [{"criterio": n, "cumple": False} for n in failed]
    fid = con.execute("INSERT INTO fichas (json, estado) VALUES ('{}', 'generada')").lastrowid
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?, ?, ?, ?)",
                (fid, instrument, verdict, json.dumps(res)))
    cur = con.execute(
        "INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter, ficha_id, data_until)"
        " VALUES (?, ?, ?, ?, 'D1', 'ninguno', ?, ?)",
        (f"{instrument}{family}{data_until}{params}", family, json.dumps(params or {"n": 1}),
         json.dumps([instrument]), fid, data_until))
    con.commit()
    return cur.lastrowid


def test_rows_sorted_and_filtered():
    con = _con()
    _add(con, "A", "no_pasa", 3.0)
    _add(con, "B", "pasa", 0.5)
    _add(con, "C", "pasa", 1.5)
    _add(con, "D", "dudosa", 2.0, failed=("robustez",))
    out = ranking.rows(con, uni=UNI)
    assert [r["instrument"] for r in out] == ["C", "B", "D", "A"]
    assert out[2]["failed"] == ["robustez"] and out[0]["sharpe_oos"] == 1.5 and out[0]["trades"] == 50
    assert [r["instrument"] for r in ranking.rows(con, verdict="pasa", uni=UNI)] == ["C", "B"]
    assert [r["instrument"] for r in ranking.rows(con, market="accion", uni=UNI)] == ["D"]
    assert len(ranking.rows(con, limit=1, uni=UNI)) == 1


def test_rows_latest_data_until_only():
    con = _con()
    _add(con, "A", "pasa", 1.0, data_until="2026-01-01")
    _add(con, "A", "no_pasa", 0.1, data_until="2026-06-01")
    out = ranking.rows(con, uni=UNI)
    assert len(out) == 1 and out[0]["verdict"] == "no_pasa"


def test_consistency_counts_same_class_only():
    con = _con()
    a = _add(con, "A", "pasa")
    _add(con, "B", "dudosa")
    _add(con, "C", "no_pasa")
    _add(con, "D", "pasa")
    _add(con, "A", "pasa", params={"n": 2})
    assert ranking.consistency(con, a, UNI) == (2, 3)


def test_single_instrument_success_is_suspicious():
    con = _con()
    _add(con, "A", "pasa")
    _add(con, "B", "no_pasa")
    _add(con, "C", "no_pasa")
    out = {r["instrument"]: r for r in ranking.rows(con, uni=UNI)}
    assert out["A"]["suspicious"] is True and out["A"]["consistency"] == "1/3"
    assert out["B"]["suspicious"] is False


def test_family_stats_expected_by_chance():
    con = _con()
    for i in range(20):
        _add(con, "A", "pasa" if i == 0 else "dudosa" if i == 1 else "no_pasa", params={"n": i})
    _add(con, "A", "pendiente_datos", params={"n": 99})
    assert ranking.family_stats(con) == [
        {"family": "f", "tested": 20, "pasa": 1, "dudosa": 1, "expected_by_chance": 1.0}]


def test_rows_scales_linearly():
    con = _con()
    for i in range(3000):
        _add(con, "ABCD"[i % 4], ("pasa", "no_pasa", "dudosa")[i % 3], float(i % 7), params={"n": i // 4})
    t = time.perf_counter()
    out = ranking.rows(con, uni=UNI)
    assert time.perf_counter() - t < 1.0 and len(out) == 500
