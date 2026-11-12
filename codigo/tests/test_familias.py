import pytest

from quant import ficha as ficha_mod
from quant import motor
from quant.familias import FAMILIES, Combo, combos, to_ficha

CLASES = {"indice": ["US500", "GER40", "NAS100", "UK100", "JP225", "FRA40", "ESP35"],
          "forex": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY"],
          "materia": ["XAUUSD", "XAGUSD", "WTI", "NATGAS"],
          "accion": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA"],
          "cripto": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
                     "AVAXUSDT", "LINKUSDT", "LTCUSDT"]}
UNI = {"instrumentos": {n: {"clase": c} for c, ns in CLASES.items() for n in ns}}

SPEC = {
    "cruce_medias": (("indice", "forex", "materia", "accion", "cripto"), ("H4", "D1")),
    "ruptura_donchian": (("indice", "forex", "materia", "accion", "cripto"), ("D1",)),
    "momentum_rotacion": (("indice", "cripto", "materia"), ("D1",)),
    "rsi_reversion": (("indice", "accion"), ("D1",)),
    "bollinger_reversion": (("forex", "indice"), ("H4", "D1")),
    "recuperacion_media": (("indice", "forex", "materia", "accion", "cripto"), ("D1",)),
    "ruptura_maximo_20": (("indice", "cripto"), ("D1",)),
    "zscore_reversion": (("forex",), ("H4", "D1")),
    "tendencia_cripto": (("BTCUSDT", "ETHUSDT"), ("D1",)),
    "control_comprar_mantener": (("US500", "BTCUSDT"), ("D1",)),
    "ejemplo": (("US500",), ("M15",)),
    "manual": (("US500",), ("M15", "H1")),
}


def test_all_combos_produce_valid_fichas():
    for fam in FAMILIES.values():
        n = 0
        for c in combos(fam, UNI):
            assert ficha_mod.errores(to_ficha(c)) == [], (fam.name, c)
            n += 1
        assert n > 0


def test_family_table_matches_spec():
    assert set(FAMILIES) == set(SPEC)
    for name, (markets, tfs) in SPEC.items():
        assert (FAMILIES[name].markets, FAMILIES[name].timeframes) == (markets, tfs)


S = (2, 3)
PARAMS = {
    "cruce_medias": {"fast": (10, 20, 50), "slow": (50, 100, 200), "kind": ("SMA", "EMA"), "stop_atr": S},
    "ruptura_donchian": {"entry": (20, 55, 100), "exit": (10, 20), "stop_atr": S},
    "momentum_rotacion": {"window": (63, 126, 252), "top": (1, 3)},
    "rsi_reversion": {"n": (2, 3), "threshold": (5, 10, 20), "stop_atr": S},
    "bollinger_reversion": {"n": (20,), "k": (2, 2.5), "stop_atr": S},
    "recuperacion_media": {"n": (20, 50), "stop_atr": S},
    "ruptura_maximo_20": {"n": (20,), "vol": (20,), "stop_atr": S},
    "zscore_reversion": {"n": (20, 50), "z": (1.5, 2), "stop_atr": S},
    "tendencia_cripto": {"n": (50, 100, 200), "stop_atr": S},
    "control_comprar_mantener": {},
    "ejemplo": {"n": (2, 3), "umbral": (5, 10)},
    "manual": {"stop_atr": (1.5, 2.0, 3.0), "objetivo_atr": (2.0, 3.0, 4.0)},
}


def test_family_params_match_spec():
    for name, expected in PARAMS.items():
        assert FAMILIES[name].params == expected, name
        if name not in ("control_comprar_mantener", "momentum_rotacion", "ejemplo", "manual"):
            assert FAMILIES[name].params["stop_atr"] == (2, 3)


def test_cruce_medias_skips_fast_ge_slow():
    for c in combos(FAMILIES["cruce_medias"], UNI):
        assert c.params["fast"] < c.params["slow"]


def test_ids_are_deterministic_and_unique():
    ids = [to_ficha(c)["id"] for c in combos(FAMILIES["rsi_reversion"], UNI)]
    assert len(ids) == len(set(ids))
    assert ids == [to_ficha(c)["id"] for c in combos(FAMILIES["rsi_reversion"], UNI)]


def test_donchian_enters_on_breakout(barras, costes_cero):
    close = [100] * 30 + [110, 110, 110]
    b = barras(close, high=[100] * 30 + [111, 111, 111], low=[100] * 33)
    c = Combo("ruptura_donchian", {"entry": 20, "exit": 10, "stop_atr": 3}, ("X",), "D1", "sin_filtro", "t")
    f = ficha_mod.con_defectos(to_ficha(c))
    ops = motor.backtest_serie(f, "X", b, costes_cero(), 5000).operaciones
    assert ops and ops[0].i_entrada == 31


def test_control_buys_and_holds(barras, costes_cero):
    c = next(combos(FAMILIES["control_comprar_mantener"], UNI))
    f = ficha_mod.con_defectos(to_ficha(c))
    ops = motor.backtest_serie(f, "X", barras(list(range(100, 140))), costes_cero(), 5000).operaciones
    assert len(ops) == 1 and ops[0].motivo == "fin"


def test_momentum_rotacion_is_transversal():
    fam = FAMILIES["momentum_rotacion"]
    got = list(combos(fam, UNI))
    assert {len(c.instruments) for c in got} == {7, 10, 4}
    for c in got:
        f = to_ficha(c)
        assert f["forma"] == "transversal" and f["transversal"]["top"] in fam.params["top"]
        assert list(c.instruments) == f["universo"]["instrumentos"]


def test_tendencia_cripto_explanation_names_its_markets():
    assert "BTC y ETH" in FAMILIES["tendencia_cripto"].explanation_es


def test_ejemplo_reproduce_el_rsi2_de_connors():
    c = next(x for x in combos(FAMILIES["ejemplo"], UNI) if x.params == {"n": 2, "umbral": 10})
    f = to_ficha(c)
    assert f["universo"] == {"instrumentos": ["US500"], "plazo": "M15"}
    assert f["entrada"]["largo"]["y"] == [{"<": ["RSI(2)", 10]}, {">": ["close", "SMA(200)"]}]
    assert f["entrada"]["corto"]["y"] == [{">": ["RSI(2)", 90]}, {"<": ["close", "SMA(200)"]}]
    assert f["salida"]["largo"]["o"] == [{"cruza_arriba": ["close", "SMA(5)"]}]
    assert f["salida"]["corto"]["o"] == [{"cruza_abajo": ["close", "SMA(5)"]}]
    assert f["gestion"] == {"stop": {"tipo": "barras", "valor": 16}, "max_barras": 64, "perdida_diaria_max": 2,
                            "tamano": {"tipo": "riesgo", "valor": 1.0}}
    assert f["horario"]["zona"] == "America/New_York"
