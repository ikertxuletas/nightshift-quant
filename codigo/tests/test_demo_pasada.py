import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from quant import datos, motor
from quant.demo import broker as B, diario, papel, pasada, seleccion
from quant.demo.config import cargar

CFG = cargar(Path(__file__).parents[2] / "config" / "demo.json")
NOW = datetime(2026, 11, 3, 0, 0, 0)
ALWAYS = {"id": "x-1", "forma": "serie_temporal", "entrada": {"largo": {">": ["close", 0]}},
          "gestion": {"stop": {"tipo": "atr", "valor": 2}}}
NEVER = {**ALWAYS, "entrada": {"largo": {">": ["close", 1e9]}}}


def serie(barras, n=33):
    return barras([100 + 0.5 * i for i in range(n)], inicio="2026-10-01")


def env(barras, costes_cero, fichas, n=33, label="en_prueba"):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    diario.ensure_schema(con)
    for inst, ficha in fichas:
        con.execute("INSERT INTO demo_strategies(ficha_json,instrument,timeframe,broker,label,status,capital,added)"
                    " VALUES(?,?,'D1','papel',?,'active',5000,'2026-10-01T00:00:00')",
                    (json.dumps(ficha), inst, label))
    cst = costes_cero(spread_pct=0.002, comision_pct=0.001)
    data = serie(barras, n)
    br = papel.PaperBroker(con, lambda i: cst, lambda i: data)
    kw = dict(bars_of=lambda inst, tf: data, costes_of=lambda i: cst, update=lambda insts: None)
    return con, br, kw


def hold(con, br, sid, inst="X", price_ref=100.0, stop=None):
    br.send(B.Order(f"h{sid}", sid, inst, 1, 2.0, stop, None))
    con.execute("INSERT INTO demo_orders(client_id,strategy_id,kind,side,units,price_ref,status,created)"
                " VALUES(?,?,'open',1,2.0,?,'filled','2026-10-30')", (f"h{sid}", sid, price_ref))


def test_pass_opens_on_pending_enter(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS)])
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["opened"] == 1
    p = br.positions()[0]
    assert p.side == 1 and p.stop is not None and p.units > 0
    o = con.execute("SELECT kind,status,price_fill FROM demo_orders").fetchall()
    assert [(r[0], r[1]) for r in o] == [("open", "filled")] and o[0][2] == pytest.approx(p.entry_price)
    assert con.execute("SELECT COUNT(*) FROM demo_events WHERE kind='enter'").fetchone()[0] == 1


def test_pass_closes_on_pending_exit(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", NEVER)])
    hold(con, br, 1)
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["closed"] == 1 and br.positions() == []
    assert con.execute("SELECT COUNT(*) FROM demo_trades").fetchone()[0] == 1
    assert con.execute("SELECT kind FROM demo_orders ORDER BY id DESC").fetchone()[0] == "close"


def test_pass_twice_same_bar_no_duplicate_orders(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS)])
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    con.execute("DELETE FROM demo_state")
    con.execute("DELETE FROM demo_paper_positions")
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["opened"] == 0
    assert con.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0] == 1
    assert br.positions() == []


def test_stop_file_blocks_opens_not_closes(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", NEVER), ("Y", ALWAYS)])
    hold(con, br, 1)
    (tmp_path / "PARAR").write_text("")
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["closed"] == 1 and out["opened"] == 0
    assert any("PARAR" in s for s in out["skipped"])
    assert con.execute("SELECT COUNT(*) FROM demo_events WHERE kind='stop_file'").fetchone()[0] == 1


def test_mismatch_blocks_opens_and_logs_event(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS), ("Y", ALWAYS)])
    br.send(B.Order("ghost", 2, "Y", 1, 1.0, None, None))
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["opened"] == 0 and any("descuadre" in s for s in out["skipped"])
    assert con.execute("SELECT COUNT(*) FROM demo_events WHERE kind='mismatch'").fetchone()[0] == 1


def test_strategy_size_overrides_reference(barras, costes_cero, tmp_path):
    ficha = {**ALWAYS, "gestion": {"tamano": {"tipo": "unidades", "valor": 3}}}
    con, br, kw = env(barras, costes_cero, [("X", ficha)])
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert br.positions()[0].units == pytest.approx(3.0)


def test_missing_data_skips_strategy_only(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS), ("Y", ALWAYS)])
    ok = kw["bars_of"]

    def bars_of(inst, tf):
        if inst == "Y":
            raise datos.ErrorDatos("pendiente de datos: Y D1")
        return ok(inst, tf)
    kw["bars_of"] = bars_of
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["opened"] == 1 and len(out["skipped"]) == 1 and "Y" in out["skipped"][0]


def test_unclosed_last_bar_is_dropped(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS)], n=34)
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert con.execute("SELECT client_id FROM demo_orders").fetchone()[0].startswith("q9-1-2026-11-02")


def test_control_sizes_capital_over_price_without_stop(barras, costes_cero, tmp_path):
    ficha = {**ALWAYS, "gestion": {}}
    con, br, kw = env(barras, costes_cero, [("X", ficha)], label="control")
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    p = br.positions()[0]
    assert p.stop is None and p.units == pytest.approx(5000 / 116.0, rel=1e-6)


def test_ficha_without_stop_gets_reference_stop_in_order(barras, costes_cero, tmp_path):
    ficha = {**ALWAYS, "gestion": {}}
    con, br, kw = env(barras, costes_cero, [("X", ficha)])
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    p = br.positions()[0]
    assert p.stop is not None and p.stop < p.entry_price
    assert con.execute("SELECT stop FROM demo_orders").fetchone()[0] == pytest.approx(p.stop)


def test_data_failures_in_advance_and_send_skip_only_that_strategy(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS), ("Y", NEVER), ("Z", ALWAYS)])
    data = br.bars_loader("X")
    hold(con, br, 2, inst="Y", stop=50.0)

    def loader(inst):
        if inst in ("Y", "Z"):
            raise datos.ErrorDatos("pendiente de datos")
        return data
    br.bars_loader = loader
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["opened"] == 1
    assert any("Z" in s and "enviar" in s for s in out["skipped"])
    assert con.execute("SELECT COUNT(*) FROM demo_orders WHERE strategy_id=3").fetchone()[0] == 0
    assert any("Y" in s for s in out["skipped"])


def test_malformed_ficha_skips_only_that_strategy(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS), ("Y", {"id": "bad"})])
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["opened"] == 1 and len(out["skipped"]) == 1


def test_advance_stop_fill_is_journaled_and_reconciles(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", NEVER)])
    full = br.bars_loader("X")
    br.bars_loader = lambda i: {k: v[:30] for k, v in full.items()}
    hold(con, br, 1, stop=95.0)
    low = full["low"].copy()
    low[31] = 80.0
    br.bars_loader = lambda i: {**full, "low": low}
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["closed"] == 1 and br.positions() == []
    o = con.execute("SELECT client_id, kind, status FROM demo_orders ORDER BY id DESC").fetchone()
    assert o[0].startswith("paper-1-stop") and o[1:] == ("close", "filled")
    t = con.execute("SELECT reason, exit FROM demo_trades").fetchone()
    assert t[0] == "stop" and t[1] == pytest.approx(95.0)
    assert pasada.seguridad.reconcile(con, br) == []


def test_retired_strategy_position_is_closed_idempotently(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS)])
    con.execute("UPDATE demo_strategies SET status='retired'")
    hold(con, br, 1)
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["closed"] == 1 and br.positions() == []
    assert con.execute("SELECT client_id FROM demo_orders WHERE kind='close'").fetchone()[0] == "h1-retired"
    assert con.execute("SELECT reason FROM demo_trades").fetchone()[0] == "retirada"
    con.execute("DELETE FROM demo_state")
    br.send(B.Order("h1b", 1, "X", 1, 2.0, None, None))
    out = pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert out["closed"] == 0


def test_pass_and_night_backtest_use_the_stored_effective_ficha(barras, costes_cero, tmp_path, monkeypatch):
    stored = seleccion.effective_ficha({**ALWAYS, "gestion": {}}, "en_prueba", CFG)
    con, br, kw = env(barras, costes_cero, [("X", stored)])
    seen = []
    real = motor._abrir
    monkeypatch.setattr(pasada.motor, "_abrir", lambda *a: seen.append(a[4]) or real(*a))
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert seen and all(g == stored["gestion"] for g in seen)
    assert json.loads(con.execute("SELECT ficha_json FROM demo_strategies").fetchone()[0]) == stored


def test_pass_decides_once_per_new_closed_bar_per_strategy(barras, costes_cero, tmp_path, monkeypatch):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS)])
    full = kw["bars_of"]("X", "D1")
    n = [32]
    kw["bars_of"] = lambda inst, tf: {k: v[:n[0]] for k, v in full.items()}
    calls = []
    real = motor.backtest_serie
    monkeypatch.setattr(pasada.motor, "backtest_serie", lambda *a: calls.append(1) or real(*a))
    pasada.run_pass(con, tmp_path, br, NOW, CFG, **kw)
    assert len(calls) == 1
    pasada.run_pass(con, tmp_path, br, datetime(2026, 11, 3, 1), CFG, **kw)
    assert len(calls) == 1
    n[0] = 33
    pasada.run_pass(con, tmp_path, br, datetime(2026, 11, 3, 5), CFG, **kw)
    assert len(calls) == 2
    assert con.execute("SELECT value FROM demo_state WHERE key='last_bar:1'").fetchone()[0].startswith("2026-11-02")


def test_price_update_skipped_inside_night_window(barras, costes_cero, tmp_path):
    con, br, kw = env(barras, costes_cero, [("X", ALWAYS)])
    updates = []
    kw["update"] = updates.append
    pasada.run_pass(con, tmp_path, br, datetime(2026, 11, 3, 2, 0), CFG, **kw)
    assert updates == []
    pasada.run_pass(con, tmp_path, br, datetime(2026, 11, 3, 7, 0), CFG, **kw)
    assert updates == [["X"]]
