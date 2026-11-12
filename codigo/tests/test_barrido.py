import json

import pytest

from quant import barrido, familias
from quant.investigacion.catalogo import abrir

UNI = {"instrumentos": {"A": {"clase": "indice"}}}


def fam(name, values, markets=("indice",)):
    return familias.Family(name, "x", {"n": values}, markets, ("D1",), "serie",
                           lambda p, i, tf, f: {"universo": {"instrumentos": i, "plazo": tf}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(familias, "FAMILIES", {"f1": fam("f1", (1, 2, 3)), "f2": fam("f2", (1, 2))})
    monkeypatch.setattr(barrido, "_load", lambda raiz: ({}, {}, UNI))
    (tmp_path / "registro").mkdir()
    (tmp_path / "registro" / "actualizar_ultimo.json").write_text(json.dumps({"hasta": "2026-11-03"}))
    con = abrir(tmp_path / "catalogo.db")
    barrido.ensure_schema(con)
    return tmp_path, con


def ok(verdict="no_pasa", sharpe=0.0):
    return lambda ficha, *a: {"A": {"veredicto": verdict, "metricas": {"fuera": {"sharpe": sharpe}}}}


def run(env, probar=ok(), **kw):
    raiz, con = env
    kw.setdefault("max_hours", 1)
    kw.setdefault("max_combos", None)
    kw.setdefault("notification", lambda: 0)
    return barrido.run(con, raiz, probar=probar, **kw)


def combo(fam_name, n, origin="barrido"):
    return familias.Combo(fam_name, {"n": n}, ("A",), "D1", "sin_filtro", origin)


def store(con, c, until, verdict="no_pasa", sharpe=0.0):
    barrido._store(con, c, {"id": "x"},
                   {"A": {"veredicto": verdict, "metricas": {"fuera": {"sharpe": sharpe}}}}, until)
    return con.execute("SELECT MAX(id) FROM combinations").fetchone()[0]


def test_skips_already_tested_fingerprint(env):
    assert run(env)["tested"] == 5
    assert run(env)["tested"] == 0


def test_retests_demo_strategy_when_data_newer(env):
    _, con = env
    for f, n in (("f1", 1), ("f1", 3), ("f2", 1), ("f2", 2)):
        store(con, combo(f, n), "2026-11-03")
    cid = store(con, combo("f1", 2), "2026-10-01")
    assert barrido.queue(con, UNI, "2026-11-03", []) == []
    q = barrido.queue(con, UNI, "2026-11-03", [cid])
    assert [c.params for c in q] == [{"n": 2}]


def test_order_fewest_tested_family_first(env):
    _, con = env
    store(con, combo("f1", 1), "2026-11-03")
    q = barrido.queue(con, UNI, "2026-11-03", [])
    assert [c.family for c in q[:2]] == ["f2", "f2"]


def test_neighbors_of_best_dudosa_queued(env, monkeypatch):
    _, con = env
    store(con, combo("f1", 2), "2026-11-03", "dudosa", 0.5)
    store(con, combo("f2", 1), "2026-11-03", "dudosa", 0.1)
    store(con, combo("f1", 3), "2026-11-03")
    monkeypatch.setattr(familias, "combos", lambda *a, **k: iter(()))
    q = barrido.queue(con, UNI, "2026-11-03", [])
    assert [(c.family, c.params["n"], c.origin) for c in q] == [("f1", 1, "vecina"), ("f2", 2, "vecina")]


def test_stops_at_hour_budget(env):
    t = iter(range(0, 10_000_000, 2000))
    r = run(env, clock=lambda: next(t), max_hours=1)
    assert r["stopped"] == "tope" and r["tested"] == 1


def test_pauses_while_fullscreen_game(env):
    states = iter([3, 3] + [0] * 100)
    r = run(env, notification=lambda: next(states), sleep=lambda s: None, max_combos=1)
    assert r["paused_s"] == 120 and r["stopped"] == "max"


def test_pendiente_datos_does_not_stop_run(env):
    r = run(env, probar=lambda *a: {"A": {"veredicto": "pendiente_datos", "motivo": "x"}})
    assert r["tested"] == 5 and r["pendiente_datos"] == 5 and r["stopped"] == "vacia"


def test_store_failure_leaves_no_half_rows_and_run_continues(env):
    _, con = env
    r = run(env, probar=lambda *a: {"A": {"veredicto": "pasa", "x": {1}}})
    assert r["errores"] == 5 and r["tested"] == 0 and r["stopped"] == "vacia"
    for t in ("fichas", "resultados", "combinations"):
        assert con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_any_exception_in_a_combo_is_counted_and_run_continues(env):
    raiz, con = env
    good = ok()

    def probar(ficha, *a):
        if ficha["universo"]["instrumentos"] == ["A"] and not probar.failed:
            probar.failed = True
            raise RuntimeError("boom")
        return good(ficha, *a)
    probar.failed = False
    r = run(env, probar=probar)
    assert r["errores"] == 1 and r["tested"] == 4 and r["stopped"] == "vacia"
    assert con.execute("SELECT COUNT(*) FROM combinations").fetchone()[0] == 4
    assert json.loads((raiz / "registro" / "barrido_ultimo.json").read_text())["errores"] == 1


def test_summary_written_even_when_run_is_interrupted(env):
    raiz, _ = env

    def probar(*a):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(env, probar=probar)
    assert json.loads((raiz / "registro" / "barrido_ultimo.json").read_text())["stopped"] == "interrumpida"


def test_neighbors_skip_unknown_family_param_or_value(env, monkeypatch):
    _, con = env
    store(con, familias.Combo("gone", {"n": 1}, ("A",), "D1", "sin_filtro", "barrido"), "2026-11-03", "dudosa", 0.9)
    store(con, familias.Combo("f1", {"m": 1}, ("A",), "D1", "sin_filtro", "barrido"), "2026-11-03", "dudosa", 0.8)
    store(con, combo("f1", 99), "2026-11-03", "dudosa", 0.7)
    store(con, combo("f2", 1), "2026-11-03", "dudosa", 0.1)
    monkeypatch.setattr(familias, "combos", lambda *a, **k: iter(()))
    q = barrido.queue(con, UNI, "2026-11-03", [])
    assert [(c.family, c.params["n"]) for c in q] == [("f2", 2)]


def test_pause_loop_respects_hour_budget(env):
    t = iter(range(0, 10_000_000, 600))
    states = iter([3] * 50)
    r = run(env, clock=lambda: next(t), notification=lambda: next(states), sleep=lambda s: None, max_hours=1)
    assert r["stopped"] == "tope" and r["tested"] == 0
