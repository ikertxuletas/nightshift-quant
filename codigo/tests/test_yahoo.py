import numpy as np
import pandas as pd

from quant import datos
from quant.fuentes import yahoo

INFO = {"clase": "accion", "fuente": "yahoo", "simbolo": "SPY", "desde": "1993-01-01"}


def _bajar_falso(llamadas, filas=3):
    def bajar(simbolo, **kwargs):
        llamadas.append((simbolo, kwargs))
        indice = pd.DatetimeIndex(pd.date_range("2024-01-02", periods=filas, freq="1D"), name="Date")
        return pd.DataFrame({"Close": [1.0, 2.0, 3.0][:filas], "High": [1.5, 2.5, 3.5][:filas],
                             "Low": [0.5, 1.5, 2.5][:filas], "Open": [1.1, 2.1, 3.1][:filas],
                             "Volume": [10, 20, 30][:filas]}, index=indice)
    return bajar


def test_descargar_normaliza():
    llamadas = []
    df = yahoo.descargar("SPY", "1993-01-01", _bajar_falso(llamadas))
    assert list(df.columns) == datos.COLUMNAS and len(df) == 3
    assert df.iloc[0]["ts"] == pd.Timestamp("2024-01-02") and df.iloc[2]["close"] == 3.0
    simbolo, kw = llamadas[0]
    assert simbolo == "SPY" and kw["auto_adjust"] is True and kw["interval"] == "1d"
    assert kw["start"] == "1993-01-01" and kw["progress"] is False and kw["multi_level_index"] is False


def test_actualizar_reescribe(tmp_path):
    r = yahoo.actualizar("SPY", INFO, tmp_path, _bajar_falso([]), dormir=lambda s: None)
    assert (r["velas"], r["hasta"], r["error"]) == (3, "2024-01-04", None)
    assert len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 3
    yahoo.actualizar("SPY", INFO, tmp_path, _bajar_falso([], filas=3), dormir=lambda s: None)
    assert len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 3


def test_sin_datos_no_toca_lo_guardado(tmp_path):
    yahoo.actualizar("SPY", INFO, tmp_path, _bajar_falso([]), dormir=lambda s: None)
    r = yahoo.actualizar("SPY", INFO, tmp_path, lambda s, **k: pd.DataFrame(), dormir=lambda s: None)
    assert "sin datos" in r["error"]
    assert len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 3


def test_excepcion_de_yfinance(tmp_path):
    def roto(simbolo, **kwargs):
        raise ValueError("rate limited")
    r = yahoo.actualizar("SPY", INFO, tmp_path, roto, dormir=lambda s: None)
    assert "rate limited" in r["error"]


def _bajar_n(n, inicio="2024-01-02"):
    def bajar(simbolo, **kwargs):
        indice = pd.DatetimeIndex(pd.date_range(inicio, periods=n, freq="1D"), name="Date")
        base = np.arange(1, n + 1, dtype=float)
        return pd.DataFrame({"Close": base, "High": base + 0.5, "Low": base - 0.5, "Open": base,
                             "Volume": base * 10}, index=indice)
    return bajar


def test_descarga_muy_recortada_no_se_guarda(tmp_path):
    yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(100), dormir=lambda s: None)
    r = yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(50), dormir=lambda s: None)
    assert "descarga sospechosa" in r["error"]
    assert len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 100


def test_descarga_reducida_dentro_de_tolerancia_se_guarda(tmp_path):
    yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(100), dormir=lambda s: None)
    r = yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(98, inicio="2024-01-04"), dormir=lambda s: None)
    assert r["error"] is None
    assert len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 98


def test_descarga_que_termina_antes_no_se_guarda(tmp_path):
    yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(100), dormir=lambda s: None)
    r = yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(97, inicio="2023-12-01"), dormir=lambda s: None)
    assert "descarga sospechosa" in r["error"]
    assert len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 100


def test_no_guarda_la_vela_del_dia_en_curso(tmp_path):
    r = yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(10), dormir=lambda s: None, hoy=pd.Timestamp("2024-01-11"))
    assert (r["velas"], r["hasta"]) == (9, "2024-01-10")
    assert pd.Timestamp(datos.cargar("SPY", "D1", tmp_path)["ts"].max()) == pd.Timestamp("2024-01-10")


def test_adelantar_el_inicio_no_hace_sospechosa_la_descarga(tmp_path):
    yahoo.actualizar("SPY", INFO, tmp_path, _bajar_n(100), dormir=lambda s: None)
    tarde = {**INFO, "desde": "2024-02-11"}
    r = yahoo.actualizar("SPY", tarde, tmp_path, _bajar_n(60, inicio="2024-02-11"), dormir=lambda s: None)
    assert r["error"] is None and len(datos.cargar("SPY", "D1", tmp_path)["close"]) == 60
