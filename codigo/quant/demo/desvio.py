from datetime import datetime, timezone

import numpy as np


def naive(t):
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def expected_band(pnls, n, capital, sims=1000, seed=12345, pct=5):
    """pnls are fractions of the backtest capital; the band is in currency of `capital`."""
    sums = np.random.default_rng(seed).choice(np.asarray(pnls, float), size=(sims, n)).sum(axis=1) * capital
    return tuple(float(x) for x in np.percentile(sums, [pct, 50, 100 - pct]))


def evaluate(con, strategy_id, cfg, now, backtest_pnls, costes=None):
    added = con.execute("SELECT added, capital FROM demo_strategies WHERE id=?", (strategy_id,)).fetchone()
    trades = con.execute("SELECT pnl, costs, units, entry, exit FROM demo_trades WHERE strategy_id=?",
                         (strategy_id,)).fetchall()
    n = len(trades)
    weeks = (naive(now) - naive(datetime.fromisoformat(added[0]))).days / 7
    ratio = None
    if costes is not None and n:
        unit_cost = costes.comision_pct + costes.spread_pct / 2 + costes.deslizamiento_pct
        assumed = sum(t[2] * (t[3] + t[4]) for t in trades) * unit_cost
        ratio = sum(t[1] for t in trades) / assumed if assumed else None
    flag = ratio is not None and ratio > cfg["cost_ratio_flag"]
    out = {"decision": "keep", "reason_es": "", "cost_ratio": ratio, "cost_flag": flag}
    if n < cfg["drift_min_trades"] and weeks < cfg["drift_min_weeks"]:
        out.update(decision="wait", reason_es=f"Aún pocos datos: {n} operaciones y {weeks:.1f} semanas.")
    elif n and len(backtest_pnls):
        p5 = expected_band(backtest_pnls, n, added[1], pct=cfg["drift_percentile"])[0]
        total = sum(t[0] for t in trades)
        if total < p5:
            out.update(decision="retire", reason_es=(
                f"Tras {n} operaciones la demo suma {total:.2f}, por debajo del límite normal de {p5:.2f} "
                f"que daba su backtest (percentil {cfg['drift_percentile']})."))
    if flag:
        out["reason_es"] = (out["reason_es"] + " " if out["reason_es"] else "") + (
            f"Los costes reales son {ratio:.1f} veces los asumidos; conviene revisar costes.json.")
    return out
