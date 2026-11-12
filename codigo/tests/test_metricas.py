from types import SimpleNamespace

import numpy as np
import pytest

from quant import metricas


def _ts(n):
    return np.datetime64("2020-01-01", "ns") + np.arange(n) * np.timedelta64(1, "D")


def test_drawdown():
    assert metricas.drawdown_max(np.array([100, 120, 90, 130.0])) == pytest.approx(0.25)


def test_sharpe_sin_varianza_es_cero():
    assert metricas.sharpe(np.array([100, 100, 100, 100.0]), _ts(4)) == 0


def test_sharpe_positivo_si_sube_con_ruido():
    eq = 100 * np.cumprod(1 + np.tile([0.01, -0.005], 50))
    assert metricas.sharpe(eq, _ts(100)) > 0


def test_cagr_duplicar_en_un_anio():
    ts = np.array(["2020-01-01", "2020-12-31T06:00"], dtype="datetime64[ns]")
    assert metricas.cagr(np.array([100, 200.0]), ts) == pytest.approx(1.0, abs=0.01)


def test_resumen():
    ops = [SimpleNamespace(pnl=p) for p in (10, -5, 20, -5)]
    r = metricas.resumen(np.array([100, 110, 105, 125, 120.0]), _ts(5), ops)
    assert r["operaciones"] == 4 and r["acierto"] == 0.5
    assert r["profit_factor"] == pytest.approx(3.0)
    assert r["rentabilidad"] == pytest.approx(0.2)


def test_resumen_sin_operaciones():
    r = metricas.resumen(np.array([100.0]), _ts(1), [])
    assert r["operaciones"] == 0 and r["cagr"] == 0 and r["profit_factor"] == 0
