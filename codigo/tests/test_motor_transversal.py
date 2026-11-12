import numpy as np
import pytest

from quant import motor


def _ficha(bottom=1):
    return {"forma": "transversal", "universo": {"instrumentos": ["A", "B", "C"], "plazo": "D1"},
            "transversal": {"ranking": "MOM(1)", "cada_barras": 5, "top": 1, "bottom": bottom},
            "gestion": {}}


def _universo(barras):
    i = np.arange(60)
    return {"A": barras(100 * 1.01 ** i), "B": barras(np.full(60, 100.0)), "C": barras(100 * 0.99 ** i)}


def test_largo_mejor_corto_peor(barras, costes_cero):
    u = _universo(barras)
    costes = {k: costes_cero() for k in u}
    r = motor.backtest_transversal(_ficha(), u, costes, 5000)
    assert {o.instrumento for o in r.operaciones} == {"A", "C"}
    assert {o.lado for o in r.operaciones if o.instrumento == "C"} == {-1}
    assert r.equity[-1] > 5000


def test_sin_cortos_si_broker_no_permite(barras, costes_cero):
    u = _universo(barras)
    costes = {k: costes_cero(permite_corto=False) for k in u}
    r = motor.backtest_transversal(_ficha(), u, costes, 5000)
    assert {o.instrumento for o in r.operaciones} == {"A"}


def test_equity_cuadra_con_operaciones(barras, costes_cero):
    rng = np.random.default_rng(3)
    u = {k: barras(100 + np.cumsum(rng.normal(0, 1, 120))) for k in "ABCD"}
    costes = {k: costes_cero(spread_pct=0.002, comision_pct=0.001, swap_pct_anual=0.04) for k in u}
    f = _ficha()
    f["universo"]["instrumentos"] = list("ABCD")
    r = motor.backtest_transversal(f, u, costes, 5000)
    assert r.equity[-1] - 5000 == pytest.approx(sum(o.pnl for o in r.operaciones))


def test_tenencia_continua_es_una_sola_operacion(barras, costes_cero):
    u = _universo(barras)
    r = motor.backtest_transversal(_ficha(), u, {k: costes_cero() for k in u}, 5000)
    assert len(r.operaciones) == 2
    assert {(o.instrumento, o.motivo) for o in r.operaciones} == {("A", "fin"), ("C", "fin")}
    assert all(o.i_entrada == 6 for o in r.operaciones)


def test_alinea_velas_comunes(barras, costes_cero):
    a = barras(np.linspace(100, 150, 40))
    b = barras(np.linspace(100, 90, 40), inicio="2024-01-11")
    r = motor.backtest_transversal(
        {"transversal": {"ranking": "MOM(1)", "cada_barras": 5, "top": 1, "bottom": 0}, "gestion": {}},
        {"A": a, "B": b}, {"A": costes_cero(), "B": costes_cero()}, 5000)
    assert len(r.ts) == 30


def test_entrada_en_apertura_de_la_vela_siguiente(barras, costes_cero):
    i = np.arange(60)
    cierres = {"A": 100 * 1.01 ** i, "B": np.full(60, 100.0), "C": 100 * 0.99 ** i}
    u = {k: barras(c, open=c * 0.98) for k, c in cierres.items()}
    r = motor.backtest_transversal(_ficha(), u, {k: costes_cero() for k in u}, 5000)
    for op in r.operaciones:
        assert op.i_entrada == 6
        assert op.precio_entrada == pytest.approx(u[op.instrumento]["open"][6])
        assert op.precio_entrada != pytest.approx(u[op.instrumento]["close"][5])


def test_giro_y_redimensionado_con_spread_y_comision(barras, costes_cero):
    u = {"A": barras([100.0, 100, 125, 125, 40, 40]), "B": barras([50.0] * 6)}
    costes = {k: costes_cero(spread_pct=0.02, comision_pct=0.001) for k in u}
    f = {"transversal": {"ranking": "close", "cada_barras": 2, "top": 1, "bottom": 1}, "gestion": {}}
    r = motor.backtest_transversal(f, u, costes, 5000)

    def friccion(unidades, mid, compra):
        fill = mid * (1.01 if compra else 0.99)
        return unidades * (abs(fill - mid) + fill * 0.001)

    qa1, qb1 = 2500 / 100, -2500 / 50
    efectivo = 5000 - qa1 * 100 - friccion(25, 100, True) - qb1 * 50 - friccion(50, 50, False)
    hueco = (efectivo + qa1 * 125 + qb1 * 50) / 2
    qa2, qb2 = hueco / 125, -hueco / 50
    efectivo -= (qa2 - qa1) * 125 + friccion(qa1 - qa2, 125, False)
    efectivo -= (qb2 - qb1) * 50 + friccion(qb1 - qb2, 50, False)
    gastos_a_largo = friccion(25, 100, True) + friccion(qa1 - qa2, 125, False)
    gastos_b_corto = friccion(50, 50, False) + friccion(qb1 - qb2, 50, False)
    pnl_a_largo = qa1 * (125 - 100) + qa2 * (40 - 125) - gastos_a_largo
    pnl_b_corto = 0.0 - gastos_b_corto
    hueco = (efectivo + qa2 * 40 + qb2 * 50) / 2
    qa3, qb3 = -hueco / 40, hueco / 50
    gastos_a_corto = friccion(qa2 - qa3, 40, False) + friccion(-qa3, 40, True)
    gastos_b_largo = friccion(qb3 - qb2, 50, True) + friccion(qb3, 50, False)

    esperado = {("A", 1): (1, 5, qa2, pnl_a_largo, gastos_a_largo, "rebalanceo"),
                ("B", -1): (1, 5, -qb2, pnl_b_corto, gastos_b_corto, "rebalanceo"),
                ("A", -1): (5, 5, -qa3, -gastos_a_corto, gastos_a_corto, "fin"),
                ("B", 1): (5, 5, qb3, -gastos_b_largo, gastos_b_largo, "fin")}
    assert len(r.operaciones) == 4
    for op in r.operaciones:
        i_e, i_s, unidades, pnl, gastos, motivo = esperado[(op.instrumento, op.lado)]
        assert (op.i_entrada, op.i_salida, op.motivo) == (i_e, i_s, motivo)
        assert op.unidades == pytest.approx(unidades)
        assert op.pnl == pytest.approx(pnl) and op.costes == pytest.approx(gastos)
    assert qa2 < qa1 and qb2 < qb1
    assert sum(o.pnl for o in r.operaciones) == pytest.approx(r.equity[-1] - 5000)
