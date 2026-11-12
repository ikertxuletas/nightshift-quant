import numpy as np
import pytest

from quant import motor


def ficha(entrada, salida=None, gestion=None, horario=None):
    f = {"forma": "serie_temporal", "universo": {"instrumentos": ["X"], "plazo": "D1"},
         "entrada": entrada, "salida": salida or {},
         "gestion": gestion or {"tamano": {"tipo": "unidades", "valor": 1}}}
    if horario:
        f["horario"] = horario
    return f


SIEMPRE = {"largo": {">": ["close", 0]}}


def test_no_mira_al_futuro(barras, costes_cero):
    b = barras([101] * 8, open=[100] * 8, high=[102] * 8, low=[99] * 8)
    f = ficha({"largo": {">": ["close", "open"]}}, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "max_barras": 1})
    r = motor.backtest_serie(f, "X", b, costes_cero(), 5000)
    normales = [o for o in r.operaciones if o.motivo != "fin"]
    assert len(normales) >= 3
    assert all(o.pnl == pytest.approx(0) for o in normales)
    assert all(o.i_entrada >= 1 for o in r.operaciones)


def test_stop_pct(barras, costes_cero):
    b = barras([100] * 5, high=[101] * 5, low=[99, 99, 90, 99, 99])
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "stop": {"tipo": "pct", "valor": 5}})
    op = motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_entrada, op.i_salida, op.precio_salida, op.motivo) == (1, 2, 95, "stop")
    assert op.pnl == pytest.approx(-5)


def test_stop_con_hueco_sale_en_apertura(barras, costes_cero):
    b = barras([100, 100, 91, 100], open=[100, 100, 92, 100], high=[101] * 4, low=[99, 99, 90, 99])
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "stop": {"tipo": "pct", "valor": 5}})
    assert motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0].precio_salida == 92


def test_objetivo_pct(barras, costes_cero):
    b = barras([100] * 4, high=[101, 101, 104, 101], low=[99] * 4)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "objetivo": {"tipo": "pct", "valor": 3}})
    op = motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.precio_salida, op.motivo) == (103, "objetivo")


def test_trailing(barras, costes_cero):
    o = [100, 100, 110, 120, 119]
    c = [100, 110, 120, 119, 119]
    low = [99, 99, 109, 113, 118]
    b = barras(c, open=o, low=low)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "trailing": {"tipo": "pct", "valor": 5}})
    op = motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_salida, op.motivo) == (3, "stop")
    assert op.precio_salida == pytest.approx(114)


def test_tamano_por_riesgo_y_limite_apalancamiento(barras, costes_cero):
    b = barras([100] * 20, high=[101] * 20, low=[99.9] * 20)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "riesgo", "valor": 1}, "stop": {"tipo": "pct", "valor": 2}})
    assert motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0].unidades == pytest.approx(25)
    f2 = ficha(SIEMPRE, gestion={"tamano": {"tipo": "riesgo", "valor": 1}, "stop": {"tipo": "pct", "valor": 0.05}})
    assert motor.backtest_serie(f2, "X", b, costes_cero(apalancamiento=1), 5000).operaciones[0].unidades == pytest.approx(50)


def test_costes_de_spread(barras, costes_cero):
    b = barras([100] * 3, high=[101] * 3, low=[99] * 3)
    op = motor.backtest_serie(ficha(SIEMPRE), "X", b, costes_cero(spread_pct=0.01), 5000).operaciones[0]
    assert (op.precio_entrada, op.precio_salida, op.motivo) == (pytest.approx(100.5), pytest.approx(99.5), "fin")
    assert op.pnl == pytest.approx(-1)


def test_equity_cuadra_con_operaciones(barras, costes_cero):
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 1, 300))
    b = barras(c, open=np.concatenate(([100], c[:-1])))
    f = ficha({"largo": {"cruza_arriba": ["close", "SMA(10)"]}, "corto": {"cruza_abajo": ["close", "SMA(10)"]}})
    r = motor.backtest_serie(f, "X", b, costes_cero(spread_pct=0.001, comision_pct=0.0005, swap_pct_anual=0.05), 5000)
    assert r.equity[-1] - 5000 == pytest.approx(sum(o.pnl for o in r.operaciones))


def test_cortos_ignorados_si_broker_no_permite(barras, costes_cero):
    b = barras([100] * 5)
    f = ficha({"corto": {">": ["close", 0]}})
    assert motor.backtest_serie(f, "X", b, costes_cero(permite_corto=False), 5000).operaciones == ()


def test_horario_solo_lunes(barras, costes_cero):
    b = barras([100] * 21, inicio="2024-01-01")
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "max_barras": 1}, horario={"dias": [0]})
    r = motor.backtest_serie(f, "X", b, costes_cero(), 5000)
    dias = [int((b["ts"][o.i_entrada].astype("datetime64[D]").astype(int) + 3) % 7) for o in r.operaciones]
    assert dias and set(dias) == {1}


def test_no_abre_si_nivel_atr_no_disponible(barras, costes_cero):
    low = [99] * 30
    low[5] = 10
    b = barras([100] * 30, high=[101] * 30, low=low)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "stop": {"tipo": "atr", "valor": 2}})
    r = motor.backtest_serie(f, "X", b, costes_cero(), 5000)
    assert r.operaciones[0].i_entrada == motor.PERIODO_ATR


def test_senal_aislada_se_ejecuta_en_la_vela_siguiente(barras, costes_cero):
    c = [100] * 8
    c[3] = 101
    b = barras(c, open=[100] * 8, high=[102] * 8, low=[99] * 8)
    f = ficha({"largo": {">": ["close", "open"]}}, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "max_barras": 1})
    op = motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_entrada, op.i_salida) == (4, 5)


def test_permitido_sesion_nocturna():
    ts = np.array(["2024-01-01T22:30", "2024-01-02T03:00", "2024-01-02T12:00"], dtype="datetime64[ns]")
    ok = motor.permitido(ts, {"sesiones": [{"desde": "22:00", "hasta": "06:00"}]})
    assert list(ok) == [True, True, False]


def test_tamano_en_unidades_limitado_por_apalancamiento(barras, costes_cero):
    b = barras([100] * 5, high=[101] * 5, low=[99] * 5)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1000}})
    op = motor.backtest_serie(f, "X", b, costes_cero(apalancamiento=1, spread_pct=0.02), 5000).operaciones[0]
    assert op.unidades == pytest.approx(5000 / 101)
    assert motor.backtest_serie(f, "X", b, costes_cero(apalancamiento=100), 5000).operaciones[0].unidades == 1000


def test_no_abre_si_objetivo_atr_no_disponible_con_tamano_riesgo(barras, costes_cero):
    b = barras([100] * 30, high=[101] * 30, low=[99] * 30)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "riesgo", "valor": 1}, "stop": {"tipo": "pct", "valor": 2},
                                "objetivo": {"tipo": "atr", "valor": 3}})
    r = motor.backtest_serie(f, "X", b, costes_cero(), 5000)
    assert r.operaciones[0].i_entrada == motor.PERIODO_ATR


def test_no_abre_si_trailing_atr_no_disponible(barras, costes_cero):
    b = barras([100] * 30, high=[101] * 30, low=[99] * 30)
    f = ficha(SIEMPRE, gestion={"tamano": {"tipo": "unidades", "valor": 1}, "trailing": {"tipo": "atr", "valor": 2}})
    r = motor.backtest_serie(f, "X", b, costes_cero(), 5000)
    assert r.operaciones[0].i_entrada == motor.PERIODO_ATR


def test_equity_cuadra_con_stop_objetivo_max_barras_y_cortos(barras, costes_cero):
    rng = np.random.default_rng(9)
    c = 100 + np.cumsum(rng.normal(0, 1, 400))
    o = np.concatenate(([100], c[:-1]))
    b = barras(c, open=o, high=np.maximum(o, c) + rng.uniform(0, 2, 400), low=np.minimum(o, c) - rng.uniform(0, 2, 400))
    f = ficha({"largo": {"cruza_arriba": ["close", "SMA(10)"]}, "corto": {"cruza_abajo": ["close", "SMA(10)"]}},
              gestion={"tamano": {"tipo": "riesgo", "valor": 1}, "stop": {"tipo": "pct", "valor": 1.5},
                       "objetivo": {"tipo": "pct", "valor": 2}, "max_barras": 8})
    costes = costes_cero(spread_pct=0.001, comision_pct=0.0005, deslizamiento_pct=0.0002, swap_pct_anual=0.05)
    r = motor.backtest_serie(f, "X", b, costes, 5000)
    motivos = {op.motivo for op in r.operaciones}
    assert {"stop", "objetivo", "senal"} <= motivos and {-1, 1} == {op.lado for op in r.operaciones}
    assert r.equity[-1] - 5000 == pytest.approx(sum(o.pnl for o in r.operaciones))


def test_pending_enter_on_last_bar(barras, costes_cero):
    b = barras([100, 100, 100, 100, 105], open=[100] * 5)
    r = motor.backtest_serie(ficha({"largo": {">": ["close", "open"]}}), "X", b, costes_cero(), 5000)
    assert r.pending == {"enter": 1, "exit": False}
    assert r.open_position is None


def test_open_position_survives_fin_close(barras, costes_cero):
    b = barras([100] * 6, high=[101] * 6, low=[99] * 6)
    r = motor.backtest_serie(ficha(SIEMPRE), "X", b, costes_cero(), 5000)
    p = r.open_position
    assert p["side"] == 1 and p["units"] == 1 and p["entry_price"] == 100
    assert p["stop"] is None and p["target"] is None and p["i_entry"] == 1
    assert r.pending == {"enter": 0, "exit": False}
    assert r.operaciones[-1].motivo == "fin"


def test_existing_results_unchanged(barras, costes_cero):
    import json
    from pathlib import Path
    rng = np.random.default_rng(7)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    o = c * (1 + rng.normal(0, 0.002, 400))
    b = barras(c, open=o, high=np.maximum(o, c) * 1.003, low=np.minimum(o, c) * 0.997)
    k = costes_cero(spread_pct=0.0005, comision_pct=0.0005, deslizamiento_pct=0.0002, swap_pct_anual=0.03, apalancamiento=10.0)
    f = json.loads((Path(__file__).parents[2] / "fichas" / "ejemplos" / "cruce_sma_spy.json").read_text(encoding="utf-8"))
    r = motor.backtest_serie(f, "SPY", b, k, 10000)
    assert len(r.operaciones) == 11
    assert r.equity[-1] == pytest.approx(9496.812163308156, rel=1e-12)
    assert r.equity.sum() == pytest.approx(3921279.949243506, rel=1e-12)


def test_stop_en_el_minimo_de_las_ultimas_velas(barras, costes_cero):
    low = [95, 97, 96, 98, 99, 99, 80, 99]
    b = barras([100] * 8, high=[101] * 8, low=low)
    f = ficha({"largo": {">": ["close", 0]}}, gestion={"tamano": {"tipo": "riesgo", "valor": 1},
                                                     "stop": {"tipo": "barras", "valor": 3}})
    b["close"][:3] = 0  # first signal at bar 3, entry at bar 4: stop = min low of bars 1-3 = 96
    op = motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_entrada, op.i_salida, op.precio_salida, op.motivo) == (4, 6, 96, "stop")
    assert op.unidades == pytest.approx(5000 * 0.01 / 4)


def test_tope_de_perdida_diaria_corta_las_entradas_del_dia(barras, costes_cero):
    # 4 bars a day; buys every bar and holds one bar. Day 1 opens with a 3% loss, then no more entries that day.
    o = [100, 100, 100, 100, 100, 100, 100, 100]
    c = [100, 97, 97, 97, 100, 100, 100, 100]
    b = barras(c, open=o, high=[101] * 8, low=[96] * 8, inicio="2024-01-01T00:00", paso="6h")
    gestion = {"tamano": {"tipo": "unidades", "valor": 50}, "max_barras": 1, "perdida_diaria_max": 2}
    r = motor.backtest_serie(ficha(SIEMPRE, gestion=gestion), "X", b, costes_cero(), 5000)
    assert [op.i_entrada for op in r.operaciones] == [1, 4, 6]
    sin_tope = {k: v for k, v in gestion.items() if k != "perdida_diaria_max"}
    libre = motor.backtest_serie(ficha(SIEMPRE, gestion=sin_tope), "X", b, costes_cero(), 5000)
    assert [op.i_entrada for op in libre.operaciones] == [1, 3, 5, 7]


def test_horario_en_hora_de_nueva_york_sigue_el_cambio_de_hora():
    ts = np.array(["2026-07-01T13:30", "2026-07-01T16:30", "2026-01-15T13:30", "2026-01-15T14:30",
                   "2026-01-15T17:29", "2026-01-15T17:30"], "datetime64[ns]")
    horario = {"zona": "America/New_York", "sesiones": [{"desde": "09:30", "hasta": "12:30"}]}
    assert list(motor.permitido(ts, horario)) == [True, False, False, True, True, False]


def test_objetivo_por_rango_del_dia_anterior(barras, costes_cero):
    # 4 bars a day. Day 1 range 110-90 = 20; signal on bar 4, entry at bar 5 open 100 -> target 100 + 0.5*20 = 110
    c = [100] * 8
    high = [110, 100, 100, 100, 101, 101, 111, 101]
    low = [90, 100, 100, 100, 99, 99, 99, 99]
    b = barras(c, high=high, low=low, inicio="2024-01-01T00:00", paso="6h")
    b["close"][:4] = 0
    g = {"tamano": {"tipo": "unidades", "valor": 1}, "objetivo": {"tipo": "rango_dia", "valor": 0.5}}
    op = motor.backtest_serie(ficha({"largo": {">": ["close", 0]}}, gestion=g), "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_entrada, op.precio_salida, op.motivo) == (5, 110, "objetivo")


def test_objetivo_por_rango_sin_dia_anterior_no_abre(barras, costes_cero):
    b = barras([100] * 4, high=[101] * 4, low=[99] * 4, inicio="2024-01-01T00:00", paso="6h")
    g = {"tamano": {"tipo": "unidades", "valor": 1}, "objetivo": {"tipo": "rango_dia", "valor": 0.5}}
    assert motor.backtest_serie(ficha(SIEMPRE, gestion=g), "X", b, costes_cero(), 5000).operaciones == ()


def test_rango_dia_solo_vale_para_el_objetivo():
    from quant import ficha as mficha
    from quant.familias import propias
    f = propias.ficha_base("ejemplo")
    f["gestion"]["objetivo"] = {"tipo": "rango_dia", "valor": 0.5}
    assert mficha.errores(f) == []
    f["gestion"]["trailing"] = {"tipo": "rango_dia", "valor": 0.5}
    assert mficha.errores(f)


NY_CIERRE = {"zona": "America/New_York", "cierre": "15:45"}
SENAL_PRIMERA = {"largo": {">": ["close", "open"]}}


def test_tras_cierre_en_hora_local():
    ts = np.array(["2026-01-15T19:30", "2026-01-15T20:30", "2026-01-15T20:45", "2026-01-15T21:00"], "datetime64[ns]")
    assert list(motor.tras_cierre(ts, NY_CIERRE)) == [False, False, True, True]
    assert not motor.tras_cierre(ts, {"zona": "America/New_York"}).any()


def test_dia_local_de_nueva_york():
    ts = np.array(["2026-01-15T23:00", "2026-01-16T03:00", "2026-01-16T06:00"], "datetime64[ns]")
    assert [str(d) for d in motor.dia_local(ts, NY_CIERRE)] == ["2026-01-15", "2026-01-15", "2026-01-16"]


def test_cierre_forzado_aunque_entre_tarde(barras, costes_cero):
    # 15-min bars 14:00-15:45 NY; one signal on the first bar, entry 14:15, forced close at the 15:45 bar's close
    c = [101] + [100] * 7
    b = barras(c, open=[100] * 8, inicio="2026-01-15T19:00", paso="15m")
    op = motor.backtest_serie(ficha(SENAL_PRIMERA, horario=NY_CIERRE), "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_entrada, op.i_salida, op.precio_salida, op.motivo) == (1, 7, 100, "sesion")


def _con_hueco(barras):
    b = barras([101, 100, 100, 100], open=[100, 100, 100, 105])
    b["ts"] = np.array(["2026-01-15T19:00", "2026-01-15T19:15", "2026-01-15T19:30", "2026-01-16T15:00"],
                       "datetime64[ns]")
    return b


def test_hueco_de_datos_cierra_en_la_apertura_del_dia_siguiente(barras, costes_cero):
    op = motor.backtest_serie(ficha(SENAL_PRIMERA, horario=NY_CIERRE), "X", _con_hueco(barras), costes_cero(),
                              5000).operaciones[0]
    assert (op.i_entrada, op.i_salida, op.precio_salida, op.motivo) == (1, 3, 105, "sesion")


def test_sin_cierre_la_posicion_pasa_la_noche(barras, costes_cero):
    op = motor.backtest_serie(ficha(SENAL_PRIMERA, horario={"zona": "America/New_York"}), "X", _con_hueco(barras),
                              costes_cero(), 5000).operaciones[0]
    assert op.motivo == "fin"


def test_parar_tras_objetivo_bloquea_solo_ese_dia(barras, costes_cero):
    # 4 bars a day, buy every bar. Day 1: every trade hits the 1% target. Day 2: every trade hits the 1% stop.
    b = barras([100] * 8, open=[100] * 8, high=[102] * 4 + [100.5] * 4, low=[99.5] * 4 + [98] * 4,
               inicio="2024-01-01T00:00", paso="6h")
    gestion = {"tamano": {"tipo": "unidades", "valor": 1}, "objetivo": {"tipo": "pct", "valor": 1},
               "stop": {"tipo": "pct", "valor": 1}, "parar_tras_objetivo": True}
    r = motor.backtest_serie(ficha(SIEMPRE, gestion=gestion), "X", b, costes_cero(), 5000)
    assert [op.i_entrada for op in r.operaciones] == [1, 5, 6, 7]
    libre = {k: v for k, v in gestion.items() if k != "parar_tras_objetivo"}
    r = motor.backtest_serie(ficha(SIEMPRE, gestion=libre), "X", b, costes_cero(), 5000)
    assert [op.i_entrada for op in r.operaciones] == [1, 2, 3, 4, 5, 6, 7]


def test_objetivo_por_rango_salta_el_trozo_del_domingo(barras, costes_cero):
    # Friday range 110-90 = 20; Sunday has one 22:00 bar (range 2) that belongs to Monday's session.
    ts = ["2024-01-05T00:00", "2024-01-05T06:00", "2024-01-05T12:00", "2024-01-05T18:00", "2024-01-07T22:00",
          "2024-01-08T00:00", "2024-01-08T06:00", "2024-01-08T12:00", "2024-01-08T18:00"]
    high = [110, 100, 100, 100, 101, 101, 101, 101, 111]
    low = [90, 100, 100, 100, 99, 99, 99, 99, 99]
    b = barras([100] * 9, high=high, low=low)
    b["ts"] = np.array(ts, "datetime64[ns]")
    b["close"][:6] = 0
    g = {"tamano": {"tipo": "unidades", "valor": 1}, "objetivo": {"tipo": "rango_dia", "valor": 0.5}}
    op = motor.backtest_serie(ficha({"largo": {">": ["close", 0]}}, gestion=g), "X", b, costes_cero(), 5000).operaciones[0]
    assert (op.i_entrada, op.precio_salida, op.motivo) == (7, 110, "objetivo")
