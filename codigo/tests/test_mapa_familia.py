from copy import deepcopy

import numpy as np
import pytest

from quant import ficha as ficha_mod
from quant import indicadores, motor
from quant.familias import FAMILIES, manual, propias
from quant.investigacion import mapa
from tests.conftest import hacer_barras
from tests.test_mapa import _diarias, _ficha

ABRE = [100, 100, 115, 100, 92, 100, 100]


def _siete(lado="largo"):
    f = _ficha({"tipo": "pct", "valor": 10})
    f["entrada"] = {lado: {">": ["close", 0]}}
    return f, hacer_barras(ABRE, open=ABRE)


def _espia(monkeypatch):
    vistas = []
    original = motor.backtest_serie

    def espia(ficha, instrumento, barras, costes, capital):
        vistas.append((deepcopy(ficha), barras, capital))
        return original(ficha, instrumento, barras, costes, capital)
    monkeypatch.setattr(motor, "backtest_serie", espia)
    return vistas


def _op(i, precio, lado=1):
    return motor.Operacion("X", lado, i, i + 1, precio, precio, 1.0, 0.0, 0.0, "senal")


# --- operaciones ---

def test_r_por_operacion_es_pnl_entre_riesgo(costes_cero):
    f, b = _siete()
    filas = mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")
    assert [x["R"] for x in filas] == pytest.approx([1.5, -0.8, 0.0])
    assert {x["salida"] for x in filas} == {"senal"} and {x["lado"] for x in filas} == {"largo"}


def test_cortos_se_etiquetan_corto_y_r_invertido(costes_cero):
    f, b = _siete("corto")
    filas = mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")
    assert [x["R"] for x in filas] == pytest.approx([-1.5, 0.8, 0.0])
    assert {x["lado"] for x in filas} == {"corto"}


def test_fuerza_una_unidad_y_quita_tope_diario(monkeypatch, costes_cero):
    vistas = _espia(monkeypatch)
    f, b = _siete()
    mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")
    gestion = vistas[0][0]["gestion"]
    assert gestion["tamano"] == {"tipo": "unidades", "valor": 1} and "perdida_diaria_max" not in gestion
    assert vistas[0][2] == 5000


def test_no_muta_la_ficha_de_entrada(barras, costes_cero):
    f = _ficha({"tipo": "pct", "valor": 5})
    antes = deepcopy(f)
    b = _diarias(barras, 200, "2022-01-01")
    mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")
    mapa.mapa(f, "X", b, costes_cero(spread_pct=0.001), "2030-01-01")
    assert f == antes


def test_solo_entran_velas_anteriores_al_corte(monkeypatch, barras, costes_cero):
    vistas = _espia(monkeypatch)
    b = _diarias(barras, 900, "2022-01-01")
    mapa.operaciones(_ficha({"tipo": "pct", "valor": 5}), "X", b, costes_cero(), "2023-01-01")
    ts = vistas[0][1]["ts"]
    assert ts.max() < np.datetime64("2023-01-01") and len(ts) == int((b["ts"] < np.datetime64("2023-01-01")).sum())


def test_velas_tras_el_corte_no_cambian_nada(barras, costes_cero):
    b = _diarias(barras, 900, "2022-01-01")
    f = _ficha({"tipo": "pct", "valor": 5})
    antes = mapa.operaciones(f, "X", b, costes_cero(), "2023-01-01")
    tras = b["ts"] >= np.datetime64("2023-01-01")
    otra = {k: v.copy() for k, v in b.items()}
    for k in ("open", "high", "low", "close"):
        otra[k][tras] *= 7
    assert antes and mapa.operaciones(f, "X", otra, costes_cero(), "2023-01-01") == antes


def test_menos_de_dos_velas_antes_del_corte_da_vacio(monkeypatch, barras, costes_cero):
    vistas = _espia(monkeypatch)
    b = _diarias(barras, 50, "2022-01-01")
    assert mapa.operaciones(_ficha({"tipo": "pct", "valor": 5}), "X", b, costes_cero(), "2022-01-02") == []
    assert vistas == []


def test_descarta_las_salidas_fin(costes_cero):
    precios = [100, 100, 100, 85, 100, 100, 100]
    b = hacer_barras(precios, open=precios)
    f = _ficha({"tipo": "pct", "valor": 10})
    del f["gestion"]["max_barras"]
    g = deepcopy(f)
    g["gestion"]["tamano"] = {"tipo": "unidades", "valor": 1}
    motivos = [o.motivo for o in motor.backtest_serie(g, "X", b, costes_cero(), 5000).operaciones]
    filas = mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")
    assert motivos == ["stop", "fin"] and [x["salida"] for x in filas] == ["stop"]


@pytest.mark.parametrize("riesgos, esperado", [([10.0, 0.0, float("nan")], [1.5]),
                                               ([-1.0, 10.0, 5.0], [-0.8, 0.0])])
def test_salta_operaciones_con_riesgo_no_positivo(monkeypatch, costes_cero, riesgos, esperado):
    monkeypatch.setattr(mapa, "_riesgos", lambda ficha, barras, ops: riesgos)
    f, b = _siete()
    assert [x["R"] for x in mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")] == pytest.approx(esperado)


@pytest.mark.parametrize("lado, esperado", [("largo", ["sin_dato", "en_contra", "a_favor"]),
                                            ("corto", ["sin_dato", "a_favor", "en_contra"])])
def test_tendencia_frente_a_ema100_en_la_vela_de_senal(monkeypatch, costes_cero, lado, esperado):
    ema = np.array([np.nan, 1.0, 200.0, 1.0, 50.0, 1.0, 1.0])
    pedidos = []
    monkeypatch.setitem(indicadores.CATALOGO, "EMA", (1, lambda b, n: pedidos.append(n) or ema))
    f, b = _siete(lado)
    filas = mapa.operaciones(f, "X", b, costes_cero(), "2030-01-01")
    assert [x["tendencia"] for x in filas] == esperado and pedidos == [100]


@pytest.mark.parametrize("entrada, hora, dia, anio", [
    ("2022-01-12T08:00", "09h", "X", 2022),
    ("2022-07-12T08:00", "10h", "M", 2022),
    ("2022-03-27T00:30", "01h", "D", 2022),
    ("2022-03-27T01:30", "03h", "D", 2022),
    ("2022-10-30T00:30", "02h", "D", 2022),
    ("2022-10-30T01:30", "02h", "D", 2022),
    ("2022-12-31T23:30", "00h", "D", 2023),
])
def test_hora_dia_y_anio_en_hora_de_madrid(costes_cero, entrada, hora, dia, anio):
    t = np.datetime64(entrada, "ns")
    b = hacer_barras([100, 100, 101], open=[100, 100, 101])
    b["ts"] = np.array([t - np.timedelta64(1, "h"), t, t + np.timedelta64(1, "h")])
    filas = mapa.operaciones(_ficha({"tipo": "pct", "valor": 10}), "X", b, costes_cero(), "2030-01-01")
    assert [(x["hora"], x["dia"], x["anio"]) for x in filas] == [(hora, dia, anio)]


# --- _riesgos ---

def _barras_estructura():
    b = hacer_barras([100.0] * 30, open=[100.0] * 30, high=[105.0] * 30, low=[95.0] * 30)
    b["low"][[16, 18, 20]] = [85, 92, 80]
    b["high"][[16, 19, 20]] = [115, 108, 120]
    return b


def _barras_atr():
    b = hacer_barras([100.0] * 40, open=[100.0] * 40)
    b["high"][30] = 150
    return b


def test_riesgo_stop_barras_usa_las_n_velas_previas():
    f = {"gestion": {"stop": {"tipo": "barras", "valor": 3}}}
    assert mapa._riesgos(f, _barras_estructura(), [_op(20, 100.0, 1), _op(20, 100.0, -1)]) == pytest.approx([8.0, 8.0])


@pytest.mark.parametrize("gestion, esperado", [
    ({"stop": {"tipo": "pct", "valor": 2}}, 5.0),
    ({"stop": {"tipo": "atr", "valor": 1.5}}, 3.0),
    ({"trailing": {"tipo": "pct", "valor": 4}}, 10.0),
    ({"trailing": {"tipo": "atr", "valor": 1}}, 2.0),
    ({"stop": {"tipo": "pct", "valor": 1}, "trailing": {"tipo": "atr", "valor": 3}}, 2.5),
    ({}, 4.0),
])
def test_riesgo_por_tipo_de_stop(gestion, esperado):
    assert mapa._riesgos({"gestion": gestion}, _barras_atr(), [_op(30, 250.0)]) == pytest.approx([esperado])


def test_riesgo_por_defecto_sin_gestion_son_dos_atr():
    assert mapa._riesgos({}, _barras_atr(), [_op(30, 100.0)]) == pytest.approx([4.0])


# --- _pf ---

@pytest.mark.parametrize("rs, esperado", [([1.0, 2.0], None), ([-1.0, -2.0], 0.0), ([], None), ([0.0, 0.0], None),
                                          ([2.0, -1.0, 1.0, -2.0], 1.0), ([3.0, -2.0, 0.0], 1.5), ([1.0, -3.0], 0.33)])
def test_profit_factor(rs, esperado):
    assert mapa._pf(rs) == esperado


# --- mapa ---

def test_mapa_totales_y_grupos(barras, costes_cero):
    b = _diarias(barras, 300, "2022-01-01")
    f = _ficha({"tipo": "pct", "valor": 5})
    f["entrada"]["corto"] = {"<": ["close", "close[1]"]}
    m = mapa.mapa(f, "X", b, costes_cero(spread_pct=0.0005), "2030-01-01")
    assert tuple(m["grupos"]) == mapa.GRUPOS and m["ops"] > 50
    for g, valores in m["grupos"].items():
        assert sum(d["ops"] for d in valores.values()) == m["ops"], g
    assert set(m["grupos"]["lado"]) == {"largo", "corto"}


def test_mapa_pf_sin_costes_es_el_de_costes_cero(barras, costes_cero):
    b = _diarias(barras, 300, "2022-01-01")
    f = _ficha({"tipo": "pct", "valor": 5})
    c = costes_cero(spread_pct=0.001, comision_pct=0.0005)
    m, cero = mapa.mapa(f, "X", b, c, "2030-01-01"), mapa.mapa(f, "X", b, c.escalar(0), "2030-01-01")
    assert m["pf_sin"] == cero["pf_con"] == cero["pf_sin"]
    assert m["pf_con"] == mapa._pf([x["R"] for x in mapa.operaciones(f, "X", b, c, "2030-01-01")])
    assert m["pf_sin"] >= m["pf_con"]
    for valores in m["grupos"].values():
        for d in valores.values():
            assert d["pf_con"] is None or d["pf_sin"] is None or d["pf_sin"] >= d["pf_con"]


# --- texto ---

M = {"ops": 5, "pf_con": 1.2, "pf_sin": 1.5,
     "grupos": {"lado": {"corto": {"ops": 2, "pf_con": 0.5, "pf_sin": None},
                         "largo": {"ops": 3, "pf_con": 1.2, "pf_sin": 1.4}},
                "anio": {2022: {"ops": 5, "pf_con": 1.2, "pf_sin": 1.5}}}}


def test_texto_formato_exacto():
    assert mapa.texto("base", M) == ("base: 5 trades, pf with costs 1.2, pf without costs 1.5\n"
                                     "  lado: corto 2 pf 0.5/None; largo 3 pf 1.2/1.4\n"
                                     "  anio: 2022 5 pf 1.2/1.5")


def test_texto_sin_excluye_grupos():
    t = mapa.texto("base", M, sin=("anio",))
    assert "anio" not in t and "2022" not in t and t.splitlines()[1].startswith("  lado: ")


def test_trocear_parte_en_trozos_enteros_cerca_de_200():
    trozos = [f"valor{i:02d} {i} pf 1.23/1.45" for i in range(40)]
    linea = "  hora: " + "; ".join(trozos)
    partes = mapa._trocear(linea).split("\n")
    assert len(partes) > 1 and all(len(p) <= 200 for p in partes)
    assert all(p.startswith("    ") and not p.startswith("     ") for p in partes[1:])
    assert "; ".join(p.strip() if i else p for i, p in enumerate(partes)) == linea
    for p, siguiente in zip(partes, partes[1:]):
        assert len(p) + 2 + len(siguiente.strip().split("; ")[0]) > 200
        assert len(p) > 150


def test_trocear_no_parte_dentro_de_un_trozo():
    largo = "x" * 250
    assert mapa._trocear(largo) == largo
    partes = mapa._trocear("a; " + largo + "; b").split("\n")
    assert partes == ["a", "    " + largo, "    b"]


@pytest.mark.parametrize("n", [10, 200])
def test_trocear_deja_las_lineas_cortas(n):
    linea = ("a; " * n)[:n]
    assert mapa._trocear(linea) == linea


# --- manual ---

def test_ficha_base_de_la_manual_exacta():
    f = propias.ficha_base("manual")
    assert f["horario"] == {"zona": "America/New_York", "sesiones": [{"desde": "10:00", "hasta": "15:00"}],
                            "cierre": "15:55"}
    assert f["gestion"] == {"stop": {"tipo": "atr", "valor": 2.0}, "objetivo": {"tipo": "atr", "valor": 3.0},
                            "perdida_diaria_max": 2, "tamano": {"tipo": "riesgo", "valor": 1.0}}
    assert f["universo"] == {"instrumentos": ["US500"], "plazo": "M15"} and f["forma"] == "serie_temporal"
    assert ficha_mod.errores(f) == []


def test_propia_manual_registrada_con_cortes_de_v21():
    p, v21 = propias.PROPIAS["manual"], propias.PROPIAS["ejemplo"]
    assert (p.family, p.params, p.instrument, p.timeframe) == ("manual", {"stop_atr": 2.0, "objetivo_atr": 3.0},
                                                               "US500", "M15")
    assert (p.corte, p.confirmacion) == ("2023-01-01", "2026-04-01") == (v21.corte, v21.confirmacion)
    assert propias.es_propia("manual") and FAMILIES["manual"] is manual.FAMILY


def test_regla_de_entrada_cruce_de_medias_a_favor_de_la_tendencia():
    e = propias.ficha_base("manual")["entrada"]
    assert e == {"largo": {"y": [{"cruza_arriba": ["EMA(9)", "EMA(21)"]}, {">": ["close", "SMA(200)"]}]},
                 "corto": {"y": [{"cruza_abajo": ["EMA(9)", "EMA(21)"]}, {"<": ["close", "SMA(200)"]}]}}


@pytest.mark.parametrize("tendencia, entra", [(0.0, False), (2.0, True)])
def test_la_manual_entra_en_corto_solo_bajo_la_media_de_200(monkeypatch, tendencia, entra):
    rapida = np.array([60.0] * 5 + [40.0] * 5)
    monkeypatch.setitem(indicadores.CATALOGO, "EMA", (1, lambda b, n: rapida if n == 9 else np.full(10, 50.0)))
    monkeypatch.setitem(indicadores.CATALOGO, "SMA", (1, lambda b, n: np.full(10, tendencia)))
    corto = propias.ficha_base("manual")["entrada"]["corto"]
    senal = motor._senal(corto, {"close": np.ones(10)}, {}, 10)
    assert senal.any() == entra and (not entra or np.flatnonzero(senal).tolist() == [5])


@pytest.mark.parametrize("stop_atr, objetivo_atr", [(1.5, 2.0), (3.0, 4.0)])
def test_generate_lleva_los_parametros_a_la_gestion(stop_atr, objetivo_atr):
    f = manual.generate({"stop_atr": stop_atr, "objetivo_atr": objetivo_atr}, ["US500"], "H1", "sin_filtro")
    assert f["gestion"]["stop"] == {"tipo": "atr", "valor": stop_atr}
    assert f["gestion"]["objetivo"] == {"tipo": "atr", "valor": objetivo_atr}
    assert f["universo"] == {"instrumentos": ["US500"], "plazo": "H1"}


def test_mapa_de_la_manual_entra_en_la_sesion_americana(costes_cero):
    rng = np.random.default_rng(7)
    n = 96 * 70
    c = 4000 + np.cumsum(rng.normal(0, 3, n))
    b = hacer_barras(c, open=np.r_[c[0], c[:-1]], inicio="2022-01-03", paso="15m")
    filas = mapa.operaciones(propias.ficha_base("manual"), "US500", b, costes_cero(), "2023-01-01")
    assert len(filas) > 10
    assert {x["hora"] for x in filas} <= {f"{h}h" for h in range(15, 22)}
    assert {x["salida"] for x in filas} <= {"stop", "objetivo", "sesion", "senal"}
