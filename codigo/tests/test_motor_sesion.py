import numpy as np
import pytest

from quant import ficha as mficha
from quant import motor
from quant.familias import propias

NY = "America/New_York"
SIEMPRE = {"largo": {">": ["close", 0]}}
CORTO = {"corto": {">": ["close", 0]}}
UNIDAD = {"tipo": "unidades", "valor": 1}


def ficha(entrada, gestion=None, horario=None):
    f = {"forma": "serie_temporal", "universo": {"instrumentos": ["X"], "plazo": "M15"},
         "entrada": entrada, "salida": {}, "gestion": gestion or {"tamano": UNIDAD}}
    if horario:
        f["horario"] = horario
    return f


def con_ts(b, ts):
    b["ts"] = np.array(ts, "datetime64[ns]")
    return b


def rango_dia(valor):
    return {"tamano": UNIDAD, "objetivo": {"tipo": "rango_dia", "valor": valor}}


def correr(f, b, costes, capital=5000):
    return motor.backtest_serie(f, "X", b, costes, capital)


def cuartos(inicio, n):
    return np.datetime64(inicio, "ns") + np.arange(n) * np.timedelta64(15, "m")


# --- rango_sesion_anterior ---

def test_rango_tres_dias_utc(barras):
    high = [110, 100, 100, 100] + [130, 100, 100, 100] + [100] * 4
    low = [90, 100, 100, 100] + [90, 100, 100, 100] + [100] * 4
    b = barras([100] * 12, high=high, low=low, inicio="2024-01-01T00:00", paso="6h")
    r = motor.rango_sesion_anterior(b, None)
    assert np.isnan(r[:4]).all()
    assert list(r[4:]) == [20] * 4 + [40] * 4


def test_rango_lunes_usa_el_viernes_sin_fin_de_semana(barras):
    ts = [f"2024-01-04T{h:02d}:00" for h in (0, 6, 12, 18)] + [f"2024-01-05T{h:02d}:00" for h in (0, 6, 12, 18)] \
        + [f"2024-01-08T{h:02d}:00" for h in (0, 6, 12, 18)]
    high = [140, 100, 100, 100, 110, 100, 100, 100, 100, 100, 100, 100]
    low = [100, 100, 100, 100, 90, 100, 100, 100, 100, 100, 100, 100]
    b = con_ts(barras([100] * 12, high=high, low=low), ts)
    assert list(motor.rango_sesion_anterior(b, None)[8:]) == [20] * 4


def test_rango_trozo_del_domingo_se_une_al_lunes(barras):
    ts = ["2024-01-05T00:00", "2024-01-05T06:00", "2024-01-05T12:00", "2024-01-05T18:00", "2024-01-07T22:00",
          "2024-01-08T00:00", "2024-01-08T06:00", "2024-01-08T12:00", "2024-01-08T18:00",
          "2024-01-09T00:00", "2024-01-09T06:00", "2024-01-09T12:00", "2024-01-09T18:00"]
    high = [110, 100, 100, 100, 150, 101, 101, 101, 101, 100, 100, 100, 100]
    low = [90, 100, 100, 100, 99, 99, 99, 99, 99, 100, 100, 100, 100]
    b = con_ts(barras([100] * 13, high=high, low=low), ts)
    r = motor.rango_sesion_anterior(b, None)
    assert list(r[4:9]) == [20] * 5
    assert list(r[9:]) == [51] * 4


def test_rango_ultimo_dia_corto_no_se_une(barras):
    b = barras([100] * 9, high=[110] + [100] * 7 + [105], low=[90] + [100] * 8, inicio="2024-01-01T00:00", paso="6h")
    r = motor.rango_sesion_anterior(b, None)
    assert list(r[4:]) == [20, 20, 20, 20, 0]


@pytest.mark.parametrize("zona,i,esperado", [(NY, 24, 21), (NY, 47, 21), (None, 30, 2), (None, 45, 21)])
def test_rango_depende_de_la_zona(barras, zona, i, esperado):
    # Hourly bars from 00:00 NY (05:00 UTC). The spike at 01:00 UTC is still the first NY day but the second UTC day.
    high = [101] * 48
    high[20] = 120
    b = barras([100] * 48, high=high, low=[99] * 48, inicio="2024-01-01T05:00", paso="1h")
    assert motor.rango_sesion_anterior(b, {"zona": zona} if zona else None)[i] == esperado


# --- objetivo rango_dia in the backtest ---

def _dos_dias(barras, high1=110, low1=90, n_dia2=4, **cols):
    n = 4 + n_dia2
    high = [high1, 100, 100, 100] + [100.5] * n_dia2
    low = [low1, 100, 100, 100] + [99.5] * n_dia2
    b = barras([100] * n, open=[100] * n, high=cols.get("high", high), low=cols.get("low", low),
               inicio="2024-01-01T00:00", paso="6h")
    return b


@pytest.mark.parametrize("valor,objetivo", [(0.25, 105), (0.5, 110), (1.0, 120), (2.0, 140)])
def test_objetivo_largo_segun_valor(barras, costes_cero, valor, objetivo):
    b = _dos_dias(barras)
    r = correr(ficha(SIEMPRE, rango_dia(valor)), b, costes_cero())
    assert r.operaciones[0].i_entrada == 5
    assert r.open_position["target"] == pytest.approx(objetivo)


@pytest.mark.parametrize("valor,objetivo", [(0.5, 90), (1.5, 70)])
def test_objetivo_corto_por_debajo(barras, costes_cero, valor, objetivo):
    b = _dos_dias(barras)
    r = correr(ficha(CORTO, rango_dia(valor)), b, costes_cero())
    assert r.open_position["side"] == -1 and r.open_position["target"] == pytest.approx(objetivo)


def test_objetivo_corto_tocado(barras, costes_cero):
    low = [90, 100, 100, 100, 99.5, 99.5, 85, 99.5]
    b = _dos_dias(barras, low=low)
    op = correr(ficha(CORTO, rango_dia(0.5)), b, costes_cero()).operaciones[0]
    assert (op.lado, op.i_entrada, op.i_salida, op.precio_salida, op.motivo) == (-1, 5, 6, 90, "objetivo")
    assert op.pnl == pytest.approx(10)


def test_objetivo_con_hueco_sale_en_la_apertura(barras, costes_cero):
    b = _dos_dias(barras, high=[110, 100, 100, 100, 100.5, 100.5, 125, 100.5])
    b["open"][6] = 115
    op = correr(ficha(SIEMPRE, rango_dia(0.5)), b, costes_cero()).operaciones[0]
    assert (op.i_salida, op.precio_salida, op.motivo) == (6, 115, "objetivo")


def test_objetivo_parte_del_precio_con_spread(barras, costes_cero):
    r = correr(ficha(SIEMPRE, rango_dia(0.5)), _dos_dias(barras), costes_cero(spread_pct=0.01))
    assert r.open_position["entry_price"] == pytest.approx(100.5)
    assert r.open_position["target"] == pytest.approx(110.5)


def test_primer_dia_sin_rango_no_abre_y_espera_al_segundo(barras, costes_cero):
    r = correr(ficha(SIEMPRE, rango_dia(0.5)), _dos_dias(barras), costes_cero())
    assert [op.i_entrada for op in r.operaciones] == [5]


def test_objetivo_usa_el_rango_del_dia_de_la_senal(barras, costes_cero):
    # Signal on the last bar of day 2 (whose previous day has range 20), entry on day 3 (whose previous day has 40).
    high = [110, 100, 100, 100, 130, 100, 100, 100, 100.5, 100.5]
    low = [90, 100, 100, 100, 90, 100, 100, 100, 99.5, 99.5]
    b = barras([100] * 10, open=[100] * 10, high=high, low=low, inicio="2024-01-01T00:00", paso="6h")
    b["close"][:7] = 0
    r = correr(ficha(SIEMPRE, rango_dia(0.5)), b, costes_cero())
    assert r.open_position["i_entry"] == 8 and r.open_position["target"] == pytest.approx(110)


def test_dia_anterior_plano_no_abre(barras, costes_cero):
    b = _dos_dias(barras, high1=100, low1=100)
    assert correr(ficha(SIEMPRE, rango_dia(0.5)), b, costes_cero()).operaciones == ()


def test_objetivo_tras_fin_de_semana_usa_el_viernes(barras, costes_cero):
    ts = [f"2024-01-04T{h:02d}:00" for h in (0, 6, 12, 18)] + [f"2024-01-05T{h:02d}:00" for h in (0, 6, 12, 18)] \
        + [f"2024-01-08T{h:02d}:00" for h in (0, 6, 12, 18)]
    high = [140, 100, 100, 100, 110, 100, 100, 100] + [100.5] * 4
    low = [100, 100, 100, 100, 90, 100, 100, 100] + [99.5] * 4
    b = con_ts(barras([100] * 12, open=[100] * 12, high=high, low=low), ts)
    b["close"][:8] = 0
    r = correr(ficha(SIEMPRE, rango_dia(0.5)), b, costes_cero())
    assert r.open_position["i_entry"] == 9 and r.open_position["target"] == pytest.approx(110)


# --- horario.cierre ---

@pytest.mark.parametrize("ts,esperado", [
    ("2024-03-08T20:44", False), ("2024-03-08T20:45", True),
    ("2024-03-11T19:44", False), ("2024-03-11T19:45", True),
    ("2024-11-01T19:45", True), ("2024-11-04T19:45", False), ("2024-11-04T20:45", True),
])
def test_tras_cierre_sigue_el_cambio_de_hora(ts, esperado):
    assert bool(motor.tras_cierre(np.array([ts], "datetime64[ns]"), {"zona": NY, "cierre": "15:45"})[0]) is esperado


@pytest.mark.parametrize("horario,ts,esperado", [
    ({"zona": "Europe/Madrid", "cierre": "17:30"}, "2024-01-15T16:30", True),
    ({"zona": "Europe/Madrid", "cierre": "17:30"}, "2024-07-15T16:29", True),
    ({"zona": "Europe/Madrid", "cierre": "17:30"}, "2024-07-15T15:29", False),
    ({"cierre": "17:30"}, "2024-07-15T16:29", False),
    ({"cierre": "17:30"}, "2024-07-15T17:30", True),
])
def test_tras_cierre_zona_y_utc(horario, ts, esperado):
    assert bool(motor.tras_cierre(np.array([ts], "datetime64[ns]"), horario)[0]) is esperado


@pytest.mark.parametrize("ts,dia", [("2024-03-10T04:30", "2024-03-09"), ("2024-11-03T04:30", "2024-11-03")])
def test_dia_local_en_la_noche_del_cambio_de_hora(ts, dia):
    assert str(motor.dia_local(np.array([ts], "datetime64[ns]"), {"zona": NY})[0]) == dia


def _dia_ny(dia, n=12):
    return cuartos(f"{dia}T19:00", n)  # 14:00 NY in winter


def test_sin_entradas_tras_el_cierre_y_vuelve_al_dia_siguiente(barras, costes_cero):
    b = con_ts(barras([100] * 24), np.concatenate((_dia_ny("2024-01-16"), _dia_ny("2024-01-17"))))
    r = correr(ficha(SIEMPRE, horario={"zona": NY, "cierre": "15:45"}), b, costes_cero())
    assert [(o.i_entrada, o.i_salida, o.motivo) for o in r.operaciones] == [(1, 7, "sesion"), (13, 19, "sesion")]
    assert r.open_position is None and r.pending == {"enter": 0, "exit": False}


def test_sin_cierre_una_sola_operacion(barras, costes_cero):
    b = con_ts(barras([100] * 24), np.concatenate((_dia_ny("2024-01-16"), _dia_ny("2024-01-17"))))
    r = correr(ficha(SIEMPRE, horario={"zona": NY}), b, costes_cero())
    assert [(o.i_entrada, o.motivo) for o in r.operaciones] == [(1, "fin")]


def test_entra_en_la_vela_del_cierre_y_sale_en_ella(barras, costes_cero):
    b = barras([100, 101, 103, 100], open=[100] * 4, inicio="2024-01-16T20:15", paso="15m")
    r = correr(ficha({"largo": {">": ["close", "open"]}}, horario={"zona": NY, "cierre": "15:45"}), b, costes_cero())
    assert len(r.operaciones) == 1
    op = r.operaciones[0]
    assert (op.i_entrada, op.i_salida, op.precio_entrada, op.precio_salida, op.motivo) == (2, 2, 100, 103, "sesion")
    assert op.pnl == pytest.approx(3)


@pytest.mark.parametrize("high,low,motivo,precio", [(106, 99, "objetivo", 105), (101, 94, "stop", 95),
                                                    (101, 99, "sesion", 100)])
def test_salida_intrabarra_gana_al_cierre(barras, costes_cero, high, low, motivo, precio):
    b = barras([100] * 8, open=[100] * 8, high=[101] * 7 + [high], low=[99] * 7 + [low], inicio="2024-01-16T19:00",
               paso="15m")
    g = {"tamano": UNIDAD, "stop": {"tipo": "pct", "valor": 5}, "objetivo": {"tipo": "pct", "valor": 5}}
    op = correr(ficha(SIEMPRE, g, {"zona": NY, "cierre": "15:45"}), b, costes_cero()).operaciones[0]
    assert (op.i_salida, op.motivo, op.precio_salida) == (7, motivo, precio)


def test_datos_acaban_antes_del_cierre(barras, costes_cero):
    b = barras([100, 100, 100, 102], inicio="2024-01-16T19:00", paso="15m")
    r = correr(ficha(SIEMPRE, horario={"zona": NY, "cierre": "15:45"}), b, costes_cero())
    op = r.operaciones[0]
    assert (op.i_entrada, op.i_salida, op.precio_salida, op.motivo) == (1, 3, 102, "fin")
    assert r.open_position == {"side": 1, "entry_price": 100, "units": 1, "stop": None, "target": None, "i_entry": 1}


@pytest.mark.parametrize("inicio,i_salida", [("2024-03-08T18:00", 11), ("2024-03-11T18:00", 7),
                                             ("2024-11-04T18:00", 11)])
def test_cierre_en_el_backtest_en_fechas_de_cambio_de_hora(barras, costes_cero, inicio, i_salida):
    b = barras([100] * 12, inicio=inicio, paso="15m")
    op = correr(ficha(SIEMPRE, horario={"zona": NY, "cierre": "15:45"}), b, costes_cero()).operaciones[0]
    assert (op.i_entrada, op.i_salida, op.motivo) == (1, i_salida, "sesion")


# --- costs on "sesion" exits ---

def test_costes_en_salida_por_cierre(barras, costes_cero):
    b = barras([100] * 8, open=[100] * 8, inicio="2024-01-16T19:00", paso="15m")
    r = correr(ficha(SIEMPRE, horario={"zona": NY, "cierre": "15:45"}), b,
               costes_cero(spread_pct=0.01, comision_pct=0.001))
    op = r.operaciones[0]
    assert (op.motivo, op.precio_entrada, op.precio_salida) == ("sesion", pytest.approx(100.5), pytest.approx(99.5))
    assert op.costes == pytest.approx(1.2) and op.pnl == pytest.approx(-1.2)
    assert r.equity[-1] == pytest.approx(5000 - 1.2)


def test_costes_en_salida_por_hueco_de_datos(barras, costes_cero):
    b = con_ts(barras([101, 100, 100, 100], open=[100, 100, 100, 105]),
               ["2026-01-15T19:00", "2026-01-15T19:15", "2026-01-15T19:30", "2026-01-16T15:00"])
    op = correr(ficha({"largo": {">": ["close", "open"]}}, horario={"zona": NY, "cierre": "15:45"}), b,
                costes_cero(spread_pct=0.01)).operaciones[0]
    assert (op.i_salida, op.motivo, op.precio_salida) == (3, "sesion", pytest.approx(105 * 0.995))
    assert op.pnl == pytest.approx(105 * 0.995 - 100.5)


def test_costes_corto_cerrado_por_sesion(barras, costes_cero):
    b = barras([100] * 8, open=[100] * 8, inicio="2024-01-16T19:00", paso="15m")
    b["close"][7] = 98
    op = correr(ficha(CORTO, horario={"zona": NY, "cierre": "15:45"}), b,
                costes_cero(spread_pct=0.02, deslizamiento_pct=0.001)).operaciones[0]
    assert (op.lado, op.motivo) == (-1, "sesion")
    assert op.precio_entrada == pytest.approx(100 * 0.989) and op.precio_salida == pytest.approx(98 * 1.011)
    assert op.pnl == pytest.approx(98.9 - 99.078)


def test_equity_cuadra_con_salidas_por_sesion(barras, costes_cero):
    rng = np.random.default_rng(3)
    ts = np.concatenate([_dia_ny(f"2024-01-{d}", 12) for d in (16, 17, 18, 19)])
    c = 100 + np.cumsum(rng.normal(0, 0.5, 48))
    o = np.concatenate(([100], c[:-1]))
    b = con_ts(barras(c, open=o), ts)
    f = ficha({"largo": {">": ["close", "open"]}, "corto": {"<": ["close", "open"]}},
              horario={"zona": NY, "cierre": "15:45"})
    r = correr(f, b, costes_cero(spread_pct=0.001, comision_pct=0.0005, swap_pct_anual=0.05))
    assert "sesion" in {op.motivo for op in r.operaciones}
    assert all(b["ts"][op.i_salida] < b["ts"][op.i_entrada] + np.timedelta64(2, "h") for op in r.operaciones)
    assert r.equity[-1] - 5000 == pytest.approx(sum(op.pnl for op in r.operaciones))


# --- parar_tras_objetivo ---

def _objetivo_cada_vela():
    return {"tamano": UNIDAD, "objetivo": {"tipo": "pct", "valor": 1}, "parar_tras_objetivo": True}


@pytest.mark.parametrize("horario,entradas", [({"zona": NY}, [1, 5]), (None, [1, 4])])
def test_parar_usa_el_dia_de_la_zona(barras, costes_cero, horario, entradas):
    ts = ["2024-01-02T20:00", "2024-01-02T21:00", "2024-01-02T22:00", "2024-01-03T02:00", "2024-01-03T06:00",
          "2024-01-03T07:00"]
    b = con_ts(barras([100] * 6, open=[100] * 6, high=[102] * 6, low=[99.5] * 6), ts)
    r = correr(ficha(SIEMPRE, _objetivo_cada_vela(), horario), b, costes_cero())
    assert [op.i_entrada for op in r.operaciones] == entradas
    assert {op.motivo for op in r.operaciones} == {"objetivo"}


def test_stop_no_activa_parar_y_el_objetivo_si(barras, costes_cero):
    b = barras([100] * 8, open=[100] * 8, high=[100.5, 100.5, 100.5, 102, 102, 102, 102, 102],
               low=[98] * 3 + [99.5] * 5, inicio="2024-01-01T00:00", paso="3h")
    g = {**_objetivo_cada_vela(), "stop": {"tipo": "pct", "valor": 1}}
    r = correr(ficha(SIEMPRE, g), b, costes_cero())
    assert [(op.i_entrada, op.motivo) for op in r.operaciones] == [(1, "stop"), (2, "stop"), (3, "objetivo")]


def test_parar_falso_es_como_no_ponerlo(barras, costes_cero):
    b = barras([100] * 8, open=[100] * 8, high=[102] * 8, low=[99.5] * 8, inicio="2024-01-01T00:00", paso="6h")
    g = {**_objetivo_cada_vela(), "parar_tras_objetivo": False}
    r = correr(ficha(SIEMPRE, g), b, costes_cero())
    assert [op.i_entrada for op in r.operaciones] == list(range(1, 8))


def test_salida_por_sesion_no_activa_parar(barras, costes_cero):
    b = con_ts(barras([100] * 24, open=[100] * 24, high=[100.5] * 24, low=[99.5] * 24),
               np.concatenate((_dia_ny("2024-01-16"), _dia_ny("2024-01-17"))))
    r = correr(ficha(SIEMPRE, _objetivo_cada_vela(), {"zona": NY, "cierre": "15:45"}), b, costes_cero())
    assert [(op.i_entrada, op.motivo) for op in r.operaciones] == [(1, "sesion"), (13, "sesion")]


def test_rango_dia_con_parar_una_operacion_por_dia(barras, costes_cero):
    high = [110, 100, 100, 100] + [111] * 4 + [111] * 4
    low = [90, 100, 100, 100] + [99] * 8
    b = barras([100] * 12, open=[100] * 12, high=high, low=low, inicio="2024-01-01T00:00", paso="6h")
    g = {**rango_dia(0.5), "parar_tras_objetivo": True}
    r = correr(ficha(SIEMPRE, g), b, costes_cero())
    assert [(op.i_entrada, op.precio_salida, op.motivo) for op in r.operaciones] == [(5, 110, "objetivo"),
                                                                                     (9, 106, "objetivo")]


@pytest.mark.parametrize("claves,entradas", [
    (("perdida_diaria_max", "parar_tras_objetivo"), [1, 2, 3, 5, 9]),
    (("perdida_diaria_max",), [1, 2, 3, 5, 6, 7, 8, 9, 10, 11]),
    (("parar_tras_objetivo",), [1, 2, 3, 4, 9]),
    ((), list(range(1, 12))),
])
def test_parar_y_tope_diario_juntos(barras, costes_cero, claves, entradas):
    # Day 1: every trade stops out (-1% each, tope 2% reached after two). Days 2-3: every trade hits the target.
    b = barras([100] * 12, open=[100] * 12, high=[100.5] * 4 + [102] * 8, low=[98] * 4 + [99.5] * 8,
               inicio="2024-01-01T00:00", paso="6h")
    g = {"tamano": {"tipo": "unidades", "valor": 50}, "stop": {"tipo": "pct", "valor": 1},
         "objetivo": {"tipo": "pct", "valor": 1}}
    g.update({k: {"perdida_diaria_max": 2, "parar_tras_objetivo": True}[k] for k in claves})
    r = correr(ficha(SIEMPRE, g), b, costes_cero())
    assert [op.i_entrada for op in r.operaciones] == entradas


# --- schema ---

def _base():
    return propias.ficha_base("ejemplo")


@pytest.mark.parametrize("seccion,clave,valor", [
    ("gestion", "objetivo", {"tipo": "rango_dia", "valor": 0.5}),
    ("gestion", "objetivo", {"tipo": "rango_dia", "valor": 3}),
    ("gestion", "parar_tras_objetivo", True),
    ("gestion", "parar_tras_objetivo", False),
    ("horario", "cierre", "15:45"),
    ("horario", "cierre", "00:00"),
])
def test_esquema_acepta(seccion, clave, valor):
    f = _base()
    f.setdefault(seccion, {})[clave] = valor
    assert mficha.errores(f) == []


@pytest.mark.parametrize("seccion,clave,valor", [
    ("gestion", "objetivo", {"tipo": "rango_dia", "valor": 0}),
    ("gestion", "objetivo", {"tipo": "rango_dia", "valor": -0.5}),
    ("gestion", "objetivo", {"tipo": "rango_dia"}),
    ("gestion", "objetivo", {"tipo": "rango_dia", "valor": "0.5"}),
    ("gestion", "objetivo", {"tipo": "rango_dia", "valor": 0.5, "extra": 1}),
    ("gestion", "stop", {"tipo": "rango_dia", "valor": 0.5}),
    ("gestion", "parar_tras_objetivo", "si"),
    ("gestion", "parar_tras_objetivo", 1),
    ("horario", "cierre", "1545"),
    ("horario", "cierre", "9:30"),
    ("horario", "cierre", 1545),
])
def test_esquema_rechaza(seccion, clave, valor):
    f = _base()
    f.setdefault(seccion, {})[clave] = valor
    assert mficha.errores(f)
