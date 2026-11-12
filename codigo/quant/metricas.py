import numpy as np

_SEGUNDOS_ANIO = 365.25 * 86400


def anios(ts):
    if len(ts) < 2:
        return 0.0
    return float((ts[-1] - ts[0]) / np.timedelta64(1, "s")) / _SEGUNDOS_ANIO


def drawdown_max(equity):
    equity = np.asarray(equity, float)
    if len(equity) == 0:
        return 0.0
    pico = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        caida = np.where(pico > 0, (pico - equity) / pico, 0.0)
    return float(np.max(caida))


def sharpe(serie, ts):
    serie = np.asarray(serie, float)
    if len(serie) < 3 or anios(ts) <= 0:
        return 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(serie) / serie[:-1]
    r = r[np.isfinite(r)]
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(len(r) / anios(ts)))


def cagr(equity, ts):
    t = anios(ts)
    if len(equity) < 2 or t <= 0:
        return 0.0
    if equity[-1] <= 0:
        return -1.0
    return float((equity[-1] / equity[0]) ** (1 / t) - 1)


def resumen(equity, ts, operaciones):
    pnl = np.array([o.pnl for o in operaciones], float)
    ganancias, perdidas = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    if perdidas > 0:
        pf = min(float(ganancias / perdidas), 999.0)
    else:
        pf = 999.0 if ganancias > 0 else 0.0
    return {
        "sharpe": round(sharpe(equity, ts), 4),
        "drawdown": round(drawdown_max(equity), 4),
        "cagr": round(cagr(equity, ts), 4),
        "rentabilidad": round(float(equity[-1] / equity[0] - 1), 4) if len(equity) else 0.0,
        "operaciones": int(len(pnl)),
        "acierto": round(float((pnl > 0).mean()), 4) if len(pnl) else 0.0,
        "profit_factor": round(pf, 4),
    }
