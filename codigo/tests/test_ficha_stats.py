import numpy as np
import pytest

from quant.motor import Operacion
from quant.panel import ficha_stats, nota


def _curva():
    # Two full years of daily bars: +1 % in every month of 2021 except a -5 % March, flat 2022.
    ts = np.arange(np.datetime64("2021-01-01"), np.datetime64("2023-01-01")).astype("datetime64[ns]")
    eq = np.empty(len(ts))
    valor, mes_prev = 1000.0, None
    for i, t in enumerate(ts):
        y, m = int(str(t)[:4]), int(str(t)[5:7])
        if (y, m) != mes_prev and i:
            prev_y, prev_m = mes_prev
            if prev_y == 2021:
                valor *= 0.95 if prev_m == 3 else 1.01
        mes_prev = (y, m)
        eq[i] = valor
    # the move of each month lands on its last bar
    out = eq.copy()
    for i in range(len(ts) - 1):
        out[i] = eq[i + 1]
    out[-1] = eq[-1]
    return ts, out


def test_estadisticas_de_una_curva_conocida():
    ts, eq = _curva()
    ops = [Operacion("X", 1, 10, 40, 1, 1, 1, 5.0, 0, "senal"), Operacion("X", 1, 100, 110, 1, 1, 1, -2.0, 0, "stop")]
    s = ficha_stats.estadisticas(ts, eq, ops, 1000.0)
    assert (s["desde"], s["hasta"]) == ("2021-01-01", "2022-12-31")
    assert s["anios"] == pytest.approx(2.0, abs=0.01)
    assert s["meses"]["2021"][0] == pytest.approx(0.01) and s["meses"]["2021"][2] == pytest.approx(-0.05)
    assert s["meses"]["2022"] == [0.0] * 12
    assert s["anual"]["2021"] == pytest.approx(1.01 ** 11 * 0.95 - 1, abs=1e-6) and s["anual"]["2022"] == 0.0
    assert s["mejor_mes"]["mes"] == "2021-01" and s["peor_mes"] == {"valor": pytest.approx(-0.05), "mes": "2021-03"}
    assert (s["anios_positivos"], s["n_anios"]) == (1, 2)
    assert s["tiempo_mercado"] == pytest.approx(40 / len(ts))
    assert s["duracion_media_dias"] == pytest.approx(20.0)
    assert s["total"] == pytest.approx(eq[-1] / 1000 - 1, abs=1e-6)
    assert s["cagr"] == pytest.approx((1 + s["total"]) ** (1 / s["anios"]) - 1, abs=1e-3)


def test_estadisticas_con_un_anio_a_medias_deja_huecos():
    ts = np.arange(np.datetime64("2024-03-01"), np.datetime64("2024-06-01")).astype("datetime64[ns]")
    s = ficha_stats.estadisticas(ts, np.full(len(ts), 1000.0), [], 1000.0)
    assert s["meses"]["2024"][:2] == [None, None] and s["meses"]["2024"][5:] == [None] * 7
    assert s["duracion_media_dias"] is None and s["tiempo_mercado"] == 0.0


TPL = {"total": {"sharpe": 0.827, "drawdown": 0.164, "rentabilidad": 7.5805, "operaciones": 106},
       "dentro": {"sharpe": 0.7563}, "fuera": {"sharpe": 1.0673}, "robustez": 1.0,
       "rentabilidad_costes_x2": 6.64, "sharpe_comprar_mantener": 0.6617}


def test_nota_quant_de_tpl_es_74():
    n = nota.nota(TPL, {"anios": 36.84, "anios_positivos": 28, "n_anios": 37})
    assert n["nota"] == 74 and len(n["atributos"]) == 8
    valores = {a["clave"]: a["valor"] for a in n["atributos"]}
    assert valores["riesgo"] == pytest.approx(5.51, abs=0.01) and valores["caidas"] == pytest.approx(4.53, abs=0.01)
    assert valores["experiencia"] == 10 and valores["ventaja"] == pytest.approx(3.31, abs=0.01)
    assert all(a["por_que"] for a in n["atributos"])


def test_nota_quant_aguanta_metricas_raras():
    raro = {"total": {"sharpe": -1.0, "drawdown": 0.9, "rentabilidad": -0.5, "operaciones": 0},
            "dentro": {"sharpe": 0.0}, "fuera": {"sharpe": -0.2}, "robustez": 0.0,
            "rentabilidad_costes_x2": -0.7, "sharpe_comprar_mantener": 0.5}
    n = nota.nota(raro, None)
    assert n["nota"] == 0 and all(0 <= a["valor"] <= 10 for a in n["atributos"])
    assert next(a for a in n["atributos"] if a["clave"] == "consistencia")["valor"] == 0


def test_precalcular_guarda_nota_y_salta_lo_ya_hecho(tmp_path, monkeypatch):
    import json
    from quant import barrido, motor
    from quant.investigacion import catalogo
    from quant.panel import precalcular
    con = catalogo.abrir(tmp_path / "catalogo.db")
    barrido.ensure_schema(con)
    for inst, verdict in (("AAA", "pasa"), ("BBB", "no_pasa")):
        fid = con.execute("INSERT INTO fichas (json, estado) VALUES (?, 'generada')",
                          (json.dumps({"universo": {"instrumentos": [inst], "plazo": "D1"}}),)).lastrowid
        con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?, ?, ?, ?)",
                    (fid, inst, verdict, json.dumps({"veredicto": verdict, "metricas": TPL})))
        con.execute("INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter,"
                    " ficha_id, data_until) VALUES (?, 'cruce_medias', '{}', ?, 'D1', 'sin_filtro', ?, '2026-11-01')",
                    (inst, json.dumps([inst]), fid))
    con.commit()
    ts, eq = _curva()
    llamadas = []
    monkeypatch.setattr(ficha_stats, "ejecutar", lambda raiz, ficha, inst: llamadas.append(inst) or (
        motor.Resultado(ts, eq, (), 1000.0), 1000.0))
    monkeypatch.setattr(precalcular, "analisis_de", lambda *a: None)
    out = precalcular.precalcular(con, tmp_path)
    assert {k: out[k] for k in ("hechas", "saltadas", "errores")} == {"hechas": 1, "saltadas": 0, "errores": []}
    fila = con.execute("SELECT * FROM panel_stats").fetchone()
    assert json.loads(fila["nota_json"])["nota"] >= 0 and json.loads(fila["stats_json"])["desde"] == "2021-01-01"
    out = precalcular.precalcular(con, tmp_path)
    assert {k: out[k] for k in ("hechas", "saltadas", "errores")} == {"hechas": 0, "saltadas": 1, "errores": []}
    assert llamadas == ["AAA"]


def test_estadisticas_incluyen_la_caida_maxima():
    ts = np.arange(np.datetime64("2024-01-01"), np.datetime64("2024-01-06")).astype("datetime64[ns]")
    s = ficha_stats.estadisticas(ts, np.array([100.0, 120.0, 90.0, 110.0, 130.0]), [], 100.0)
    assert s["drawdown"] == pytest.approx(0.25)


def test_ejecutar_corta_en_hasta(tmp_path, monkeypatch):
    from quant import costes as mcostes, criterios as mcriterios, datos, motor, universo
    ts = np.arange(np.datetime64("2022-12-25"), np.datetime64("2023-01-04")).astype("datetime64[ns]")
    barras = {k: np.ones(len(ts)) for k in ("open", "high", "low", "close", "volume")} | {"ts": ts}
    vistos = []
    monkeypatch.setattr(datos, "cargar", lambda *a, **k: barras)
    monkeypatch.setattr(motor, "backtest_serie", lambda f, i, b, c, cap: vistos.append(len(b["ts"])))
    monkeypatch.setattr(mcriterios, "cargar", lambda *a: {"capital": 1000})
    monkeypatch.setattr(mcostes, "cargar", lambda *a: {})
    monkeypatch.setattr(mcostes, "costes_de", lambda *a, **k: None)
    monkeypatch.setattr(universo, "cargar", lambda *a: {})
    monkeypatch.setattr(universo, "desde_de", lambda *a: None)
    monkeypatch.setattr(universo, "clase_de", lambda *a: None)
    ficha_stats.ejecutar(tmp_path, {"universo": {"plazo": "D1"}}, "X", hasta="2023-01-01")
    ficha_stats.ejecutar(tmp_path, {"universo": {"plazo": "D1"}}, "X")
    assert vistos == [7, 10]
