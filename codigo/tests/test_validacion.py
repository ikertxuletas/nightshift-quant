import numpy as np
import pytest

from quant import validacion as v

CRIT = {"capital": 5000, "riesgo_pct": 1.0, "fraccion_oos": 0.30, "drawdown_max": 0.20, "sharpe_oos_min": 0.5,
        "sharpe_oos_ratio_min": 0.5, "costes_multiplicador": 2.0, "robustez_variacion": 0.20, "robustez_min": 0.70,
        "operaciones_min": 100, "operaciones_oos_min": 30, "operaciones_min_posicional": 30,
        "operaciones_oos_min_posicional": 10, "dias_posicional": 20, "benchmark_margen": 0.0,
        "montecarlo_n": 200, "montecarlo_p95_dd_max": 0.30, "margen_dudosa": 0.10}

FICHA = {"forma": "serie_temporal", "universo": {"instrumentos": ["X"], "plazo": "D1"},
         "entrada": {"largo": {"<": ["RSI(14)", 30]}}, "salida": {"largo": {">": ["close", "SMA(5)"]}},
         "gestion": {"stop": {"tipo": "atr", "valor": 2}, "tamano": {"tipo": "riesgo", "valor": 1}},
         "prometido": {"sharpe": 1.8, "drawdown": 0.08},
         "umbrales_tipo": [{"metrica": "acierto", "valor": 0.55, "sentido": "min", "fuente": "Connors 2009"}]}


def test_parametros():
    p = v.parametros(FICHA)
    assert ("arg", "RSI(14)", 0) in p and ("arg", "SMA(5)", 0) in p
    assert ("ruta", ("entrada", "largo", "<", 1)) in p
    assert ("ruta", ("gestion", "stop", "valor")) in p
    assert not any("tamano" in x[1] for x in p if x[0] == "ruta")


def test_variante_no_muta_y_redondea():
    arriba = v.variante(FICHA, ("arg", "RSI(14)", 0), 1.2)
    abajo = v.variante(FICHA, ("arg", "RSI(14)", 0), 0.8)
    assert arriba["entrada"]["largo"] == {"<": ["RSI(17)", 30]}
    assert abajo["entrada"]["largo"] == {"<": ["RSI(11)", 30]}
    assert FICHA["entrada"]["largo"] == {"<": ["RSI(14)", 30]}
    assert v.variante(FICHA, ("ruta", ("entrada", "largo", "<", 1)), 1.2)["entrada"]["largo"]["<"][1] == 36


def test_variante_entera_siempre_cambia():
    f = {**FICHA, "entrada": {"largo": {"<": ["RSI(2)", 10]}}}
    assert v.variante(f, ("arg", "RSI(2)", 0), 1.2)["entrada"]["largo"] == {"<": ["RSI(3)", 10]}
    assert v.variante(f, ("arg", "RSI(2)", 0), 0.8)["entrada"]["largo"] == {"<": ["RSI(1)", 10]}


def test_montecarlo_sin_perdidas_es_cero():
    assert v.montecarlo_dd(np.array([10.0, 5.0, 20.0]), 5000, 50) == 0


def test_criterio_distancias():
    c = v.criterio("sharpe_oos", 0.45, 0.5, "min")
    assert not c["cumple"] and c["distancia"] == pytest.approx(0.1)
    d = v.criterio("drawdown", 0.22, 0.20, "max")
    assert not d["cumple"] and d["distancia"] == pytest.approx(0.1)
    assert v.criterio("drawdown", 0.15, 0.20, "max")["cumple"]


def test_veredicto():
    ok = {"cumple": True, "distancia": -0.5}
    assert v.veredicto([ok, ok], 0.1) == "pasa"
    assert v.veredicto([ok, {"cumple": False, "distancia": 0.05}], 0.1) == "dudosa"
    assert v.veredicto([ok, {"cumple": False, "distancia": 0.2}], 0.1) == "no_pasa"
    assert v.veredicto([{"cumple": False, "distancia": 0.01}] * 2, 0.1) == "no_pasa"


def test_referencias():
    total = {"sharpe": 0.6, "drawdown": 0.17, "cagr": 0.1, "acierto": 0.6, "profit_factor": 1.4}
    r = v.referencias(total, FICHA)
    assert r["vs_fuente"]["sharpe"] == pytest.approx(-1.2) and r["vs_fuente"]["drawdown"] == pytest.approx(0.09)
    assert r["vs_tipo"][0]["cumple"] and r["vs_tipo"][0]["fuente"] == "Connors 2009"


def test_comparar():
    antes = {"metricas": {"total": {"sharpe": 0.5, "drawdown": 0.2}}}
    ahora = {"metricas": {"total": {"sharpe": 0.7, "drawdown": 0.25}}}
    c = v.comparar(antes, ahora)
    assert c["sharpe"]["mejora"] and not c["drawdown"]["mejora"]


def test_validar_serie_completo(barras, costes_cero):
    rng = np.random.default_rng(7)
    c = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, 1500))
    b = barras(c, open=np.concatenate(([100], c[:-1])))
    res = v.validar(FICHA, {"X": b}, {"X": costes_cero(clase="accion")}, CRIT)["X"]
    assert res["veredicto"] in {"pasa", "dudosa", "no_pasa"}
    assert len(res["criterios"]) == 9
    assert 0 <= res["metricas"]["robustez"] <= 1 and res["metricas"]["variantes"] == 2 * len(v.parametros(FICHA))
    assert any("supervivencia" in a for a in res["avisos"])


def test_validar_transversal(barras, costes_cero):
    i = np.arange(400)
    u = {"A": barras(100 * 1.002 ** i), "B": barras(100 + np.sin(i / 5)), "C": barras(100 * 0.999 ** i)}
    f = {"forma": "transversal", "universo": {"instrumentos": list(u), "plazo": "D1"},
         "transversal": {"ranking": "MOM(20)", "cada_barras": 10, "top": 1, "bottom": 0}, "gestion": {}}
    res = v.validar(f, u, {k: costes_cero() for k in u}, CRIT)
    assert list(res) == ["_cartera"] and res["_cartera"]["veredicto"] in {"pasa", "dudosa", "no_pasa"}


def test_umbral_cero_es_estricto_y_sin_margen_de_dudosa():
    perdida = v.criterio("rentabilidad_costes_x2", -0.09, 0.0, "min", estricto=True)
    empate = v.criterio("rentabilidad_costes_x2", 0.0, 0.0, "min", estricto=True)
    assert not perdida["cumple"] and not empate["cumple"]
    assert v.veredicto([perdida], 0.1) == "no_pasa"
    assert v.criterio("rentabilidad_costes_x2", 0.01, 0.0, "min", estricto=True)["cumple"]


def test_umbral_negativo_conserva_signo():
    f = {**FICHA, "entrada": {"largo": {"<": ["ZSCORE(20)", -2]}}}
    ruta = ("ruta", ("entrada", "largo", "<", 1))
    assert v.variante(f, ruta, 0.8)["entrada"]["largo"]["<"][1] == pytest.approx(-1.6)
    assert v.variante(f, ruta, 1.2)["entrada"]["largo"]["<"][1] == pytest.approx(-2.4)


def test_valor_de_stop_varia_en_coma_flotante():
    ruta = ("ruta", ("gestion", "stop", "valor"))
    assert v.variante(FICHA, ruta, 0.8)["gestion"]["stop"]["valor"] == pytest.approx(1.6)
    assert v.variante(FICHA, ruta, 1.2)["gestion"]["stop"]["valor"] == pytest.approx(2.4)


def test_variantes_identicas_se_descartan_y_aviso_sin_parametros(barras, costes_cero):
    b = barras(100 + np.cumsum(np.random.default_rng(5).normal(0, 1, 300)))
    uno = {**FICHA, "entrada": {"largo": {">": ["close", "SMA(1)[1]"]}}, "salida": {},
           "gestion": {"tamano": {"tipo": "unidades", "valor": 1}}}
    res = v.validar(uno, {"X": b}, {"X": costes_cero()}, CRIT)["X"]
    assert res["metricas"]["variantes"] == 1
    nada = {**FICHA, "entrada": {"largo": {">": ["close", "open"]}}, "salida": {},
            "gestion": {"tamano": {"tipo": "unidades", "valor": 1}}}
    res2 = v.validar(nada, {"X": b}, {"X": costes_cero()}, CRIT)["X"]
    assert res2["metricas"]["variantes"] == 0
    assert any("sin variantes" in a for a in res2["avisos"])


def test_robustez_transversal_solo_cuenta_ranking_y_cada_barras(barras, costes_cero):
    i = np.arange(400)
    u = {"A": barras(100 * 1.002 ** i), "B": barras(100 + np.sin(i / 5)), "C": barras(100 * 0.999 ** i)}
    costes = {k: costes_cero() for k in u}
    f = {"forma": "transversal", "universo": {"instrumentos": list(u), "plazo": "D1"},
         "transversal": {"ranking": "MOM(20)", "cada_barras": 10, "top": 1, "bottom": 0},
         "gestion": {"stop": {"tipo": "atr", "valor": 2}, "objetivo": {"tipo": "pct", "valor": 5},
                     "trailing": {"tipo": "atr", "valor": 3}, "max_barras": 15,
                     "tamano": {"tipo": "riesgo", "valor": 1}}}
    efectivos = v.parametros(v.ficha_efectiva(f, costes))
    assert sorted(efectivos) == sorted([("arg", "MOM(20)", 0), ("ruta", ("transversal", "cada_barras"))])
    res = v.validar(f, u, costes, CRIT)["_cartera"]
    assert res["metricas"]["variantes"] == 2 * len(efectivos)


def test_robustez_serie_sin_parametros_de_corto_si_broker_no_permite(barras, costes_cero):
    f = {**FICHA, "entrada": {"largo": {"<": ["RSI(14)", 30]}, "corto": {">": ["RSI(9)", 70]}},
         "salida": {"largo": {">": ["close", "SMA(5)"]}, "corto": {"<": ["close", "SMA(8)"]}}}
    b = barras(100 + np.cumsum(np.random.default_rng(2).normal(0, 1, 300)))
    costes = costes_cero(permite_corto=False)
    efectivos = v.parametros(v.ficha_efectiva(f, costes))
    assert not any("corto" in p[1] for p in efectivos if p[0] == "ruta")
    assert not {"RSI(9)", "SMA(8)"} & {p[1] for p in efectivos if p[0] == "arg"}
    ejecutadas = []

    def ejecutar(fx, c):
        ejecutadas.append(fx)
        return v.motor.backtest_serie(fx, "X", b, c, 5000)

    res = v.evaluar(f, ejecutar, costes, lambda c, k: c.escalar(k), 0.0, CRIT)
    assert res["metricas"]["variantes"] == 2 * len(efectivos)
    assert all(fx["entrada"]["corto"] == f["entrada"]["corto"] and fx["salida"]["corto"] == f["salida"]["corto"]
               for fx in ejecutadas)


def test_poda_serie_salida_sin_entrada_y_varios_instrumentos(costes_cero):
    f = {**FICHA, "entrada": {"corto": {">": ["RSI(9)", 70]}},
         "salida": {"largo": {">": ["close", "SMA(5)"]}, "corto": {"<": ["close", "SMA(8)"]}},
         "transversal": {"ranking": "MOM(20)", "cada_barras": 10, "top": 1}}
    con_corto = v.ficha_efectiva(f, costes_cero())
    assert "transversal" not in con_corto and "largo" not in con_corto["salida"] and "corto" in con_corto["salida"]
    sin_corto = v.ficha_efectiva(f, costes_cero(permite_corto=False))
    assert sin_corto["entrada"] == {} and sin_corto["salida"] == {}
    assert f["salida"]["largo"] == {">": ["close", "SMA(5)"]}


def test_aviso_cortos_ignorados(barras, costes_cero):
    b = barras(100 + np.cumsum(np.random.default_rng(4).normal(0, 1, 200)))
    f = {**FICHA, "entrada": {"largo": {"<": ["RSI(14)", 30]}, "corto": {">": ["RSI(14)", 70]}}}
    aviso = "cortos ignorados: el bróker no los permite"
    assert aviso in v.validar(f, {"X": b}, {"X": costes_cero(permite_corto=False)}, CRIT)["X"]["avisos"]
    assert aviso not in v.validar(f, {"X": b}, {"X": costes_cero()}, CRIT)["X"]["avisos"]
    assert aviso not in v.validar(FICHA, {"X": b}, {"X": costes_cero(permite_corto=False)}, CRIT)["X"]["avisos"]


def _resultado_falso(m_dentro, m_fuera, n_ops, s=0.01, n=1001, corte=700, capital=5000.0):
    r = np.array([(m_dentro if j < corte else m_fuera) + (s if j % 2 == 0 else -s) for j in range(n - 1)])
    equity = capital * np.concatenate(([1.0], np.cumprod(1 + r)))
    ts = np.datetime64("2020-01-01", "ns") + np.arange(n) * np.timedelta64(1, "D")
    paso = (n - 10) // n_ops
    ops = tuple(v.motor.Operacion("X", 1, k * paso, k * paso + 3, 100.0, 101.0, 1.0, 1.0, 0.0, "senal")
                for k in range(n_ops))
    return v.motor.Resultado(ts, equity, ops, capital)


def _evaluar_falso(res, costes_cero):
    return v.evaluar(FICHA, lambda f, c: res, costes_cero(), lambda c, k: c.escalar(k), 0.0, CRIT)


def _fallidos(salida):
    return {c["criterio"] for c in salida["criterios"] if not c["cumple"]}


def test_evaluar_de_extremo_a_extremo_pasa(costes_cero):
    salida = _evaluar_falso(_resultado_falso(0.001, 0.001, 120), costes_cero)
    assert _fallidos(salida) == set()
    assert salida["veredicto"] == "pasa"


def test_evaluar_de_extremo_a_extremo_dudosa(costes_cero):
    salida = _evaluar_falso(_resultado_falso(0.00042, 0.00024854, 120), costes_cero)
    assert _fallidos(salida) == {"sharpe_fuera_de_muestra"}
    fallo = next(c for c in salida["criterios"] if not c["cumple"])
    assert 0 < fallo["distancia"] <= 0.10 and fallo["valor"] == pytest.approx(0.475, abs=1e-3)
    assert salida["veredicto"] == "dudosa"


def test_evaluar_de_extremo_a_extremo_no_pasa(costes_cero):
    salida = _evaluar_falso(_resultado_falso(0.00042, 0.00024854, 20), costes_cero)
    assert _fallidos(salida) == {"sharpe_fuera_de_muestra", "operaciones", "operaciones_fuera_de_muestra"}
    assert salida["veredicto"] == "no_pasa"


def test_dias_medios_excluye_cierre_forzado_fin(costes_cero):
    n = 1001
    ts = np.datetime64("2020-01-01", "ns") + np.arange(n) * np.timedelta64(1, "D")
    ops = [v.motor.Operacion("X", 1, k * 20, k * 20 + 3, 100.0, 101.0, 1.0, 1.0, 0.0, "senal") for k in range(40)]
    ops.append(v.motor.Operacion("X", 1, 200, n - 1, 100.0, 101.0, 1.0, 1.0, 0.0, "fin"))
    res = v.motor.Resultado(ts, np.linspace(5000, 6000, n), tuple(ops), 5000.0)
    assert v._dias_medios(res) == pytest.approx(3)
    assert not _evaluar_falso(res, costes_cero)["metricas"]["posicional"]
