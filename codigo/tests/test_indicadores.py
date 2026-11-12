import numpy as np
import pytest

from quant import indicadores as ind


def test_sma_y_ema(barras):
    b = barras([1, 2, 3, 4, 5])
    np.testing.assert_allclose(ind.calcular("SMA(3)", b), [np.nan, np.nan, 2, 3, 4])
    np.testing.assert_allclose(ind.calcular("EMA(3)", b), [np.nan, np.nan, 2, 3, 4])


def test_rsi_wilder_valor_clasico(barras):
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
              45.89, 46.03, 45.61, 46.28, 46.28]
    r = ind.calcular("RSI(14)", barras(closes))
    assert np.isnan(r[13])
    assert r[14] == pytest.approx(70.464, abs=0.01)


def test_rsi_solo_subidas_es_100(barras):
    assert ind.calcular("RSI(14)", barras(list(range(1, 21))))[14] == 100


def test_atr_rango_constante(barras):
    b = barras([10, 10, 10, 10], high=[11] * 4, low=[9] * 4)
    np.testing.assert_allclose(ind.calcular("ATR(3)", b), [np.nan, np.nan, 2, 2])


def test_max_min_mom(barras):
    b = barras([1, 2, 4], high=[5, 3, 4], low=[0, 1, 2])
    np.testing.assert_allclose(ind.calcular("MAX(2)", b), [np.nan, 5, 4])
    np.testing.assert_allclose(ind.calcular("MIN(2)", b), [np.nan, 0, 1])
    np.testing.assert_allclose(ind.calcular("MOM(2)", b), [np.nan, np.nan, 3])


def test_bandas_y_zscore(barras):
    b = barras([1, 2, 3])
    sup = ind.calcular("BB_SUP(3,2)", b)[2]
    assert sup == pytest.approx(2 + 2 * np.std([1, 2, 3]))
    assert ind.calcular("ZSCORE(3)", b)[2] == pytest.approx((3 - 2) / np.std([1, 2, 3]))


def test_retardo(barras):
    np.testing.assert_allclose(ind.calcular("close[1]", barras([1, 2, 3])), [np.nan, 1, 2])


@pytest.mark.parametrize("token", ["close[-1]", "XYZ(3)", "SMA(2.5)", "SMA(0)", "BB_SUP(20)", "sma(3)"])
def test_tokens_invalidos(token):
    with pytest.raises(ind.ErrorIndicador):
        ind.analizar(token)


def test_cache_reutiliza(barras):
    cache = {}
    b = barras([1, 2, 3])
    a = ind.calcular("SMA(2)", b, cache)
    assert ind.calcular("SMA(2)", b, cache) is a


def test_hma_sigue_una_recta_sin_retraso(barras):
    b = barras(np.arange(1.0, 41.0))
    h = ind.calcular("HMA(4)", b)
    assert np.isnan(h[:4]).all() and np.allclose(h[4:], b["close"][4:])


def test_rsi_sin_volumen_no_rompe(barras):
    b = {**barras(100 + np.sin(np.arange(80.0))), "volume": np.zeros(80)}
    sv = ind.calcular("RSI(14)", b)
    assert np.isfinite(sv[-30:]).all() and ((sv[-30:] >= 0) & (sv[-30:] <= 100)).all()


def test_rango_dia_es_el_del_dia_anterior(barras):
    c = np.full(12, 100.0)
    high = np.array([101, 103, 102, 101, 110, 105, 101, 100, 100, 101, 102, 100.0])
    low = np.array([99, 98, 99, 99, 95, 99, 99, 97, 99, 99, 99, 99.0])
    b = barras(c, high=high, low=low, inicio="2024-01-01T20:00", paso="1h")
    r = ind.calcular("RANGO_DIA(1)", b)
    assert np.isnan(r[:4]).all()
    assert (r[4:] == 5).all()
    assert np.isnan(ind.calcular("RANGO_DIA(2)", b)).all()
