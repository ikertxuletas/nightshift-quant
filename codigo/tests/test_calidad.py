import json

import numpy as np
import pandas as pd

from quant import calidad, datos


def _limpias(barras, n=5000):
    c = 100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.001, n))
    return barras(c, open=c, high=c * 1.001, low=c * 0.999)


def test_limpias_no_bloquean(barras):
    r = calidad.revisar(_limpias(barras), "indice")
    assert r["velas"] == 5000 and not r["bloqueante"] and r["motivos"] == []


def test_precio_no_positivo_bloquea(barras):
    b = _limpias(barras)
    b["low"][10] = -1.0
    r = calidad.revisar(b, "materia")
    assert r["bloqueante"] and r["no_positivos"] == 1 and "no positivos" in r["motivos"][0]


def test_ohlc_incoherente_por_encima_de_fraccion(barras):
    b = _limpias(barras)
    b["high"][:10] = b["low"][:10] * 0.5
    r = calidad.revisar(b, "indice")
    assert r["ohlc_incoherentes"] == 10 and r["bloqueante"]


def test_salto_aislado_no_bloquea(barras):
    b = _limpias(barras)
    b["close"][500] *= 1.5
    b["open"][500] = b["low"][500] = b["close"][500]
    b["high"][500] = b["close"][500] * 1.001
    uno = calidad.revisar(b, "indice")
    assert uno["saltos"] >= 1 and not uno["bloqueante"]


def test_saltos_reales_que_se_mantienen_no_bloquean(barras):
    b = _limpias(barras)
    for i in range(100, 2000, 100):
        b["close"][i] *= 2
        b["open"][i] = b["low"][i] = b["close"][i]
        b["high"][i] = b["close"][i]
        b["close"][i + 1] = b["close"][i]
        b["open"][i + 1] = b["low"][i + 1] = b["close"][i + 1]
        b["high"][i + 1] = b["close"][i + 1] * 1.001
    r = calidad.revisar(b, "indice")
    assert r["saltos"] >= 19 and r["picos"] == 0 and not r["bloqueante"]


def test_picos_que_se_deshacen_bloquean(barras):
    b = _limpias(barras)
    for i in range(100, 2000, 100):
        nivel = b["close"][i - 1]
        b["close"][i] = nivel * 1.5
        b["open"][i] = b["low"][i] = b["close"][i]
        b["high"][i] = b["close"][i] * 1.001
        b["close"][i + 1] = nivel
        b["open"][i + 1] = b["low"][i + 1] = b["close"][i + 1]
        b["high"][i + 1] = b["close"][i + 1] * 1.001
    r = calidad.revisar(b, "indice")
    assert r["picos"] >= 19 and r["bloqueante"]
    assert any("picos" in m for m in r["motivos"])


def test_incoherencia_pequena_no_bloquea(barras):
    b = _limpias(barras)
    b["high"][:10] = np.minimum(b["high"][:10], np.maximum(b["open"][:10], b["close"][:10]) * (1 - 0.0005))
    r = calidad.revisar(b, "indice")
    assert not r["bloqueante"]


def test_incoherencia_grande_bloquea(barras):
    b = _limpias(barras)
    b["high"][:10] = np.maximum(b["open"][:10], b["close"][:10]) * (1 - 0.05)
    r = calidad.revisar(b, "indice")
    assert r["ohlc_incoherentes"] == 10 and r["bloqueante"]


def _quitar(b, desde, hasta):
    mascara = np.ones(len(b["ts"]), bool)
    mascara[desde:hasta] = False
    return {k: v[mascara] for k, v in b.items()}


def test_hueco_grande_en_medio_bloquea(barras):
    c = np.full(400, 100.0)
    b = barras(c, open=c, high=c * 1.001, low=c * 0.999)
    b = _quitar(b, 155, 245)
    r = calidad.revisar(b, "accion")
    assert r["bloqueante"]
    assert r["mayor_hueco_dias"] > 15
    assert "dias_con_velas" in r and "dias_esperados" in r and "dias_ausentes" in r


def test_festivos_sueltos_no_bloquea(barras):
    calendario = pd.bdate_range("2024-01-01", periods=260)
    calendario = calendario.delete([20, 90, 160, 230])
    n = len(calendario)
    c = np.full(n, 100.0)
    b = {"ts": calendario.values.astype("datetime64[ns]"), "open": c, "high": c * 1.001, "low": c * 0.999,
         "close": c, "volume": np.ones(n)}
    r = calidad.revisar(b, "accion")
    assert not r["bloqueante"]
    assert r["mayor_hueco_dias"] <= 15


def test_cripto_cinco_dias_ausentes_bloquea(barras):
    c = np.full(60, 100.0)
    b = barras(c, open=c, high=c * 1.001, low=c * 0.999)
    b = _quitar(b, 25, 30)
    r = calidad.revisar(b, "cripto")
    assert r["bloqueante"]
    assert r["mayor_hueco_dias"] > 3


def test_sin_velas_bloquea(barras):
    assert calidad.revisar(barras([]), "forex")["motivos"] == ["sin velas"]


def test_vela_toda_nan_bloquea_sin_avisos(barras):
    import warnings
    b = _limpias(barras)
    for k in ("open", "high", "low", "close"):
        b[k][7] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        r = calidad.revisar(b, "indice")
    assert r["bloqueante"] and r["no_positivos"] == 1


def test_revisar_todo_fusiona_y_bloqueo(tmp_path, barras):
    import pandas as pd
    def df(c):
        return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=len(c), freq="1D"), "open": c,
                             "high": c, "low": c, "close": c, "volume": 1.0})
    datos.guardar("A", "D1", df(np.full(50, 10.0)), tmp_path)
    datos.guardar("B", "D1", df(np.concatenate([np.full(49, 10.0), [-1.0]])), tmp_path)
    uni = {"instrumentos": {"A": {"clase": "accion"}, "B": {"clase": "materia"}, "C": {"clase": "forex"}}}
    informe = calidad.revisar_todo(uni, tmp_path)
    assert set(informe) == {"A", "B"} and informe["A"]["resolucion"] == "D1"
    assert calidad.bloqueo("A", tmp_path) is None
    assert "no positivos" in calidad.bloqueo("B", tmp_path)
    datos.guardar("B", "D1", df(np.full(50, 10.0)), tmp_path)
    calidad.revisar_todo(uni, tmp_path, solo=["B"])
    guardado = json.loads((tmp_path / calidad.FICHERO).read_text(encoding="utf-8"))
    assert set(guardado) == {"A", "B"} and calidad.bloqueo("B", tmp_path) is None
    assert calidad.bloqueo("ZZZ", tmp_path) == "sin revisar"


def test_revisar_todo_audita_tambien_d1_agregado(tmp_path):
    partes = []
    for dia, cierre in enumerate([100.0, 100.0, 150.0, 100.0]):
        c = np.full(400, cierre)
        ts = pd.date_range(f"2024-01-0{dia + 1}", periods=400, freq="1min")
        partes.append(pd.DataFrame({"ts": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1.0}))
    datos.guardar("US500", "M1", pd.concat(partes, ignore_index=True), tmp_path)
    uni = {"instrumentos": {"US500": {"clase": "indice"}}}
    informe = calidad.revisar_todo(uni, tmp_path)
    entrada = informe["US500"]
    assert entrada["resolucion"] == "M1"
    assert entrada["d1"]["bloqueante"] and entrada["d1"]["saltos"] >= 1 and entrada["d1"]["picos"] >= 1
    assert entrada["bloqueante"]
    assert calidad.bloqueo("US500", tmp_path) is not None


def _con_hueco_antes_de_desde():
    dias = pd.bdate_range("2013-06-01", periods=250)
    ts = pd.DatetimeIndex([pd.Timestamp("2013-02-22")]).append(dias)
    c = np.full(len(ts), 100.0)
    return pd.DataFrame({"ts": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1.0}), len(dias)


def test_revisar_todo_ignora_velas_anteriores_a_desde(tmp_path):
    df, n_dias = _con_hueco_antes_de_desde()
    datos.guardar("US500", "D1", df, tmp_path)
    uni_sin_desde = {"instrumentos": {"US500": {"clase": "indice"}}}
    calidad.revisar_todo(uni_sin_desde, tmp_path)
    assert calidad.bloqueo("US500", tmp_path) is not None

    uni_con_desde = {"instrumentos": {"US500": {"clase": "indice", "desde": "2013-06-01"}}}
    informe = calidad.revisar_todo(uni_con_desde, tmp_path)
    assert calidad.bloqueo("US500", tmp_path) is None
    assert informe["US500"]["velas"] == n_dias


def test_tope_absoluto_de_incoherentes_bloquea(barras):
    n = 1_000_000
    c = 100 * np.cumprod(1 + np.random.default_rng(2).normal(0, 0.0001, n))
    b = barras(c, open=c, high=c * 1.0005, low=c * 0.9995, paso="1m")
    for i in range(600):
        b["high"][i] = b["low"][i] * 0.5
    r = calidad.revisar(b, "indice")
    assert r["ohlc_incoherentes"] == 600
    assert r["ohlc_incoherentes"] / n <= calidad.FRACCION_BLOQUEO
    assert r["bloqueante"]
