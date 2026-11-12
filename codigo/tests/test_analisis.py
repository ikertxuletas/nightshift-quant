import numpy as np

from quant import familias
from quant.costes import Costes
from quant.investigacion import analisis

FICHA = familias.to_ficha(familias.Combo("cruce_medias", {"fast": 5, "slow": 20, "kind": "SMA", "stop_atr": 3},
                                         ("X",), "H1", "sin_filtro", "barrido"))
COSTES = Costes("prueba", "indice", 0.0002, 0.0001, 0.0001, 0.0, 1.0, True)


def velas(n):
    ts = (np.datetime64("2025-01-06T08:00") + np.arange(n) * np.timedelta64(1, "h")).astype("datetime64[ns]")
    i = np.arange(n)
    close = 100 + 8 * np.sin(i / 15) + 3 * np.sin(i / 4.3) + i * 0.01
    open_ = np.r_[close[0], close[:-1]]
    return {"ts": ts, "open": open_, "high": np.maximum(open_, close) + 0.6, "low": np.minimum(open_, close) - 0.6,
            "close": close, "volume": np.ones(n)}


def dia(b):
    d = b["ts"].astype("datetime64[D]")
    claves, primero = np.unique(d, return_index=True)
    ultimo = np.r_[primero[1:] - 1, len(d) - 1]
    return {"ts": claves.astype("datetime64[ns]"), "open": b["open"][primero], "close": b["close"][ultimo],
            "high": np.maximum.reduceat(b["high"], primero), "low": np.minimum.reduceat(b["low"], primero),
            "volume": np.ones(len(claves))}


def test_analizar_devuelve_los_seis_grupos_y_el_mapa():
    b = velas(2000)
    a = analisis.analizar(FICHA, "X", b, COSTES, dia(b), dia(b))
    assert set(a) == {"n", "g1", "g2", "g3", "g4", "g5", "g6", "rejilla"} and a["n"] >= 10
    assert a["g1"]["costes_sobre_bruto"] is None or 0 <= a["g1"]["costes_sobre_bruto"] <= 1
    assert abs(sum(a["g2"]["salidas"].values()) - 1) < 0.01 and a["g3"]["peor_racha"] >= 1
    assert 0 <= a["g4"]["prob_suerte"] <= 1 and sum(c["ops"] for c in a["rejilla"]) == a["n"]
    assert {c["dia"] for c in a["rejilla"]} <= set("LMXJVSD")
    assert set(a["g5"]) == {"tendencia", "lateral", "volatil", "tranquilo"} and a["g6"]["dias"] >= 20


def test_sin_costes_los_costes_no_comen_nada():
    a = analisis.analizar(FICHA, "X", velas(2000), COSTES.escalar(0), None, None)
    assert a["g1"]["coste_por_op_pts"] == 0 and a["g5"] is None and a["g6"] is None


def test_pocas_operaciones_devuelve_none():
    assert analisis.analizar(FICHA, "X", velas(30), COSTES, None, None) is None


def test_suerte_es_alta_si_no_hay_ventaja_y_baja_si_la_hay():
    assert analisis._prob_suerte(np.array([1.0, -1.0] * 50)) > 0.4
    assert analisis._prob_suerte(np.array([1.0, 0.8] * 50)) < 0.01
    assert analisis._prob_suerte(np.array([1.0, 1.0])) is None


def test_mapa_en_hora_de_madrid():
    assert analisis._celda(np.datetime64("2026-01-05T15:00")) == ("L", "16h")
    assert analisis._celda(np.datetime64("2026-07-06T15:00")) == ("L", "17h")


def test_vecinos_ordenados_y_limitados():
    v = [{"pf": x / 10, "etiqueta": str(x)} for x in range(12)]
    a = analisis.analizar(FICHA, "X", velas(2000), COSTES, None, None, vecinos=v)
    assert [x["pf"] for x in a["g4"]["vecinos"]] == [1.1, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]


def test_r_no_depende_del_precio_ni_de_las_unidades():
    b = velas(2000)
    caro = {k: (v * 100 if k in ("open", "high", "low", "close") else v) for k, v in b.items()}
    a, c = analisis.analizar(FICHA, "X", b, COSTES, None, None), analisis.analizar(FICHA, "X", caro, COSTES, None, None)
    assert a["n"] == c["n"] and abs(a["g1"]["r_medio"] - c["g1"]["r_medio"]) < 0.01
    assert a["g4"]["prob_suerte"] == c["g4"]["prob_suerte"]
