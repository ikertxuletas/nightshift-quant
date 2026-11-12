import numpy as np
import pytest

from quant import datos, motor, rutas
from tests.test_referencia import _referencia

ETF = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
hay_etf = all("D1" in datos.resoluciones(t, rutas.DATOS) for t in ETF)
requiere_etf = pytest.mark.skipif(not hay_etf, reason="faltan datos reales de ETF (python -m quant.actualizar --fuente yahoo)")


@requiere_etf
def test_cruce_sma_spy_real_igual_que_referencia(costes_cero):
    b = datos.cargar("SPY", "D1")
    f = {"entrada": {"largo": {"cruza_arriba": ["close", "SMA(50)"]}},
         "salida": {"largo": {"cruza_abajo": ["close", "SMA(50)"]}},
         "gestion": {"tamano": {"tipo": "unidades", "valor": 1}}}
    r = motor.backtest_serie(f, "SPY", b, costes_cero(), 5000)
    esperado = _referencia(b["open"], b["close"], 50)
    assert len(r.operaciones) == len(esperado) > 50
    np.testing.assert_allclose([op.pnl for op in r.operaciones], esperado, atol=1e-6)


def _momentum_independiente(barras, n, cada, capital):
    ts = barras[ETF[0]]["ts"]
    for t in ETF[1:]:
        ts = np.intersect1d(ts, barras[t]["ts"])
    c = np.column_stack([barras[t]["close"][np.isin(barras[t]["ts"], ts)] for t in ETF])
    o = np.column_stack([barras[t]["open"][np.isin(barras[t]["ts"], ts)] for t in ETF])
    efectivo, unidades, objetivo = capital, np.zeros(len(ETF)), None
    for i in range(len(ts)):
        if objetivo is not None:
            efectivo -= float(np.dot(objetivo - unidades, o[i]))
            unidades, objetivo = objetivo, None
        valor = efectivo + float(np.dot(unidades, c[i]))
        if i % cada == 0 and i < len(ts) - 1 and i >= n and valor > 0:
            mom = c[i] / c[i - n] - 1
            objetivo = np.zeros(len(ETF))
            mejor = int(np.argmax(mom))
            objetivo[mejor] = valor / c[i, mejor]
    return efectivo + float(np.dot(unidades, c[-1]))


@requiere_etf
def test_momentum_etf_real_igual_que_calculo_independiente(costes_cero):
    barras = {t: datos.cargar(t, "D1") for t in ETF}
    f = {"forma": "transversal", "universo": {"instrumentos": ETF, "plazo": "D1"},
         "transversal": {"ranking": "MOM(126)", "cada_barras": 21, "top": 1, "bottom": 0}, "gestion": {}}
    r = motor.backtest_transversal(f, barras, {t: costes_cero() for t in ETF}, 5000)
    assert r.equity[-1] == pytest.approx(_momentum_independiente(barras, 126, 21, 5000), rel=1e-9)
