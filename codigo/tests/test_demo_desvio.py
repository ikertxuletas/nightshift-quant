import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from quant.costes import Costes
from quant.demo import desvio, diario
from quant.demo.config import cargar

CFG = cargar(Path(__file__).parents[2] / "config" / "demo.json")
NOW = datetime(2026, 11, 3)
BT = np.array([10.0, -5.0, 8.0, -4.0, 6.0] * 10) / 1000


def montar(pnls, added="2026-10-20T00:00:00", costs=0.0):
    con = sqlite3.connect(":memory:")
    diario.ensure_schema(con)
    con.execute("INSERT INTO demo_strategies(id,status,capital,added) VALUES(1,'active',1000,?)", (added,))
    for p in pnls:
        con.execute("INSERT INTO demo_trades(strategy_id,units,entry,exit,pnl,costs) VALUES(1,1,100,100,?,?)", (p, costs))
    return con


def test_expected_band_ordered_and_deterministic():
    a = desvio.expected_band(BT, 10, 1000)
    assert a[0] < a[1] < a[2] and a == desvio.expected_band(BT, 10, 1000)


def test_drift_waits_until_10_trades_or_6_weeks():
    assert desvio.evaluate(montar([-50] * 9), 1, CFG, NOW, BT)["decision"] == "wait"
    assert desvio.evaluate(montar([-50] * 3, added="2026-09-01T00:00:00"), 1, CFG, NOW, BT)["decision"] == "retire"
    assert desvio.evaluate(montar([-50] * 10), 1, CFG, NOW, BT)["decision"] == "retire"


def test_drift_retires_below_p5_with_spanish_reason():
    bad = desvio.evaluate(montar([-100] * 10), 1, CFG, NOW, BT)
    assert bad["decision"] == "retire" and "por debajo" in bad["reason_es"]
    assert desvio.evaluate(montar([8] * 10), 1, CFG, NOW, BT)["decision"] == "keep"


def test_cost_ratio_flag():
    cst = Costes("p", "indice", 0.0, 0.001, 0.0, 0.0, 20, True)
    assumed = 200 * 0.001
    ok = desvio.evaluate(montar([8] * 10, costs=assumed), 1, CFG, NOW, BT, costes=cst)
    assert ok["cost_ratio"] == pytest.approx(1.0) and not ok["cost_flag"]
    hi = desvio.evaluate(montar([8] * 10, costs=assumed * 2), 1, CFG, NOW, BT, costes=cst)
    assert hi["cost_ratio"] == pytest.approx(2.0) and hi["cost_flag"] and "costes" in hi["reason_es"]


def test_band_scales_with_capital_and_uses_configured_percentile():
    a = desvio.expected_band(BT, 10, 1000)
    assert desvio.expected_band(BT, 10, 2000)[0] == pytest.approx(2 * a[0])
    assert desvio.expected_band(BT, 10, 1000, pct=20)[0] > a[0]


def test_evaluate_accepts_aware_now():
    from datetime import timezone
    r = desvio.evaluate(montar([-50] * 9), 1, CFG, NOW.replace(tzinfo=timezone.utc), BT)
    assert r["decision"] == "wait"
