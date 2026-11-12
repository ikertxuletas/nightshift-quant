import sqlite3
from pathlib import Path

import pytest

from quant.costes import Costes
from quant.demo import broker as B, diario, papel, seguridad
from quant.demo.config import cargar

COSTES = Costes(broker="p", clase="indice", spread_pct=0.002, comision_pct=0.001, deslizamiento_pct=0.0,
                swap_pct_anual=0.0, apalancamiento=20, permite_corto=True)


def montar(barras_dict):
    con = sqlite3.connect(":memory:")
    diario.ensure_schema(con)
    return con, papel.PaperBroker(con, lambda i: COSTES, lambda i: barras_dict)


def test_paper_fill_includes_half_spread(barras):
    con, br = montar(barras([100, 100, 100]))
    f = br.send(B.Order("c1", 1, "X", 1, 2.0, 90.0, 120.0))
    assert f.price == pytest.approx(100 * 1.001) and f.costs == pytest.approx(2 * f.price * 0.001)
    assert br.positions()[0].entry_price == pytest.approx(100.1)
    fs = br.close(1, "c2")
    assert fs.price == pytest.approx(100 * 0.999) and br.positions() == []
    assert br.is_demo() is True


def test_paper_stop_hit_by_low(barras):
    b = barras([100, 100, 100, 100], low=[99, 99, 94, 99], high=[101, 101, 101, 101])
    full = b
    short = {k: v[:2] for k, v in b.items()}
    con, br = montar(short)
    br.send(B.Order("c1", 1, "X", 1, 1.0, 95.0, None))
    br.bars_loader = lambda i: full
    fills = br.advance(None)
    assert len(fills) == 1 and fills[0].price == pytest.approx(95.0) and br.positions() == []
    assert br.advance(None) == []


def test_paper_stop_priority_matches_motor(barras):
    short = barras([100, 100])
    full = barras([100, 100, 100], open=[100, 100, 100], low=[99, 99, 94], high=[101, 101, 111])
    con, br = montar(short)
    br.send(B.Order("c1", 1, "X", 1, 1.0, 95.0, 110.0))
    br.bars_loader = lambda i: full
    assert br.advance(None)[0].price == pytest.approx(95.0)


def test_require_demo_raises_on_real():
    class Real:
        def is_demo(self):
            return False
    with pytest.raises(RuntimeError, match="cuenta no demo"):
        seguridad.require_demo(Real())


def test_client_id_deterministic():
    a = seguridad.client_id(3, "2026-11-03T08:00", "open")
    assert a == seguridad.client_id(3, "2026-11-03T08:00", "open") != seguridad.client_id(3, "2026-11-03T08:00", "close")


def test_orders_client_id_unique(barras):
    con, _ = montar(barras([100]))
    q = "INSERT INTO demo_orders(client_id,strategy_id,kind,side,units,status) VALUES('a',1,'open',1,1,'filled')"
    con.execute(q)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(q)


def test_reconcile_detects_mismatch(barras):
    con, br = montar(barras([100, 100]))
    assert seguridad.reconcile(con, br) == []
    br.send(B.Order("c1", 1, "X", 1, 1.0, None, None))
    assert len(seguridad.reconcile(con, br)) == 1
    con.execute("INSERT INTO demo_orders(client_id,strategy_id,kind,side,units,status) VALUES('c1',1,'open',1,1.0,'filled')")
    assert seguridad.reconcile(con, br) == []
    con.execute("INSERT INTO demo_orders(client_id,strategy_id,kind,side,units,status) VALUES('c2',2,'open',1,1.0,'filled')")
    assert len(seguridad.reconcile(con, br)) == 1


def test_stop_file_present(tmp_path):
    assert not seguridad.stop_file_present(tmp_path)
    (tmp_path / "PARAR").write_text("")
    assert seguridad.stop_file_present(tmp_path)


def test_portfolio_limits_only_warn(barras):
    con, _ = montar(barras([100]))
    cfg = {"daily_loss_ref_pct": 2.0, "max_positions_ref": 1}
    con.execute("INSERT INTO demo_strategies(id,status,capital) VALUES(1,'active',1000)")
    con.execute("INSERT INTO demo_trades(strategy_id,exit_ts,pnl) VALUES(1,'2026-11-03T10:00',-30)")
    for i in (1, 2):
        con.execute("INSERT INTO demo_orders(client_id,strategy_id,kind,side,units,status) VALUES(?,?,'open',1,1,'filled')", (f"o{i}", i))
    w = seguridad.portfolio_warnings(con, cfg, "2026-11-03")
    assert len(w) == 2 and all(isinstance(x, str) for x in w)
    assert seguridad.portfolio_warnings(con, {**cfg, "max_positions_ref": 5, "daily_loss_ref_pct": 5.0}, "2026-11-03") == []


def test_config_loads():
    assert cargar(Path(__file__).resolve().parents[2] / "config" / "demo.json")["n_demo"] == 5
