import numpy as np
import pytest

from quant import motor


def _referencia(o, c, n):
    sma = np.full(len(c), np.nan)
    sma[n - 1:] = np.convolve(c, np.ones(n) / n, "valid")
    arriba, abajo = np.zeros(len(c), bool), np.zeros(len(c), bool)
    for i in range(1, len(c)):
        if np.isnan(sma[i - 1]):
            continue
        arriba[i] = c[i] > sma[i] and c[i - 1] <= sma[i - 1]
        abajo[i] = c[i] < sma[i] and c[i - 1] >= sma[i - 1]
    pnls, dentro, entrada = [], False, 0.0
    for i in range(1, len(c)):
        if dentro and abajo[i - 1]:
            pnls.append(o[i] - entrada)
            dentro = False
        elif not dentro and arriba[i - 1]:
            entrada, dentro = o[i], True
    if dentro:
        pnls.append(c[-1] - entrada)
    return pnls


def test_cruce_sma_igual_que_referencia_independiente(barras, costes_cero):
    rng = np.random.default_rng(42)
    c = 200 + np.cumsum(rng.normal(0, 1, 2000))
    o = np.concatenate(([100], c[:-1])) + rng.normal(0, 0.2, 2000)
    b = barras(c, open=o, high=np.maximum(o, c) + 5, low=np.minimum(o, c) - 5)
    f = {"entrada": {"largo": {"cruza_arriba": ["close", "SMA(20)"]}},
         "salida": {"largo": {"cruza_abajo": ["close", "SMA(20)"]}},
         "gestion": {"tamano": {"tipo": "unidades", "valor": 1}}}
    r = motor.backtest_serie(f, "X", b, costes_cero(), 5000)
    esperado = _referencia(o, c, 20)
    assert len(r.operaciones) == len(esperado)
    np.testing.assert_allclose([op.pnl for op in r.operaciones], esperado, atol=1e-9)
