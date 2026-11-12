import numpy as np
import pandas as pd
import pytest

from quant import datos


def _minutos(n, inicio="2024-01-01 00:00"):
    ts = pd.date_range(inicio, periods=n, freq="1min")
    return pd.DataFrame({"ts": ts, "open": np.arange(n) + 1.0, "high": np.arange(n) + 2.0,
                         "low": np.arange(n) + 0.5, "close": np.arange(n) + 1.5, "volume": np.ones(n)})


def test_guardar_y_agregar(tmp_path):
    datos.guardar("EURUSD", "M1", _minutos(10), tmp_path)
    b = datos.cargar("EURUSD", "M5", tmp_path)
    assert len(b["ts"]) == 2
    assert list(b["open"]) == [1, 6] and list(b["high"]) == [6, 11]
    assert list(b["low"]) == [0.5, 5.5] and list(b["close"]) == [5.5, 10.5]
    assert list(b["volume"]) == [5, 5]


def test_misma_resolucion(tmp_path):
    datos.guardar("EURUSD", "M1", _minutos(3), tmp_path)
    assert len(datos.cargar("EURUSD", "M1", tmp_path)["close"]) == 3


def test_sin_resolucion_fina_es_pendiente(tmp_path):
    df = _minutos(3)
    df["ts"] = pd.date_range("2024-01-01", periods=3, freq="1D")
    datos.guardar("SPY", "D1", df, tmp_path)
    assert datos.resoluciones("SPY", tmp_path) == ["D1"]
    with pytest.raises(datos.ErrorDatos, match="pendiente de datos"):
        datos.cargar("SPY", "H1", tmp_path)


def test_zona_horaria_a_utc(tmp_path):
    df = _minutos(2)
    df["ts"] = pd.date_range("2024-01-01 01:00", periods=2, freq="1min", tz="Europe/Berlin")
    datos.guardar("X", "M1", df, tmp_path)
    assert datos.cargar("X", "M1", tmp_path)["ts"][0] == np.datetime64("2024-01-01T00:00", "ns")


def test_columnas_obligatorias(tmp_path):
    with pytest.raises(datos.ErrorDatos):
        datos.guardar("X", "M1", _minutos(2).drop(columns=["volume"]), tmp_path)


def test_guardar_anual_fusiona_y_parte_por_anio(tmp_path):
    a = _minutos(3, "2023-12-31 23:58")
    datos.guardar_anual("X", "M1", a, tmp_path)
    assert sorted(p.name for p in (tmp_path / "X" / "M1").iterdir()) == ["2023.parquet", "2024.parquet"]
    b = _minutos(2, "2024-01-01 00:00")
    b["close"] = [99.0, 98.0]
    datos.guardar_anual("X", "M1", b, tmp_path)
    cargado = datos.cargar("X", "M1", tmp_path)
    assert len(cargado["ts"]) == 4
    assert list(cargado["close"][-2:]) == [99.0, 98.0]


def test_ultimo_ts(tmp_path):
    assert datos.ultimo_ts("X", "M1", tmp_path) is None
    datos.guardar_anual("X", "M1", _minutos(5, "2024-03-01 10:00"), tmp_path)
    assert datos.ultimo_ts("X", "M1", tmp_path) == pd.Timestamp("2024-03-01 10:04")
    datos.guardar("Y", "D1", _minutos(2), tmp_path)
    assert datos.ultimo_ts("Y", "D1", tmp_path) == pd.Timestamp("2024-01-01 00:01")


def test_leer_deduplica_entre_particiones(tmp_path):
    carpeta = tmp_path / "X" / "M1"
    carpeta.mkdir(parents=True)
    a = _minutos(3, "2024-01-01 00:00")
    b = _minutos(3, "2024-01-01 00:01")
    b["close"] = [999.0, 998.0, 997.0]
    a.to_parquet(carpeta / "2024-a.parquet", index=False)
    b.to_parquet(carpeta / "2024-b.parquet", index=False)
    cargado = datos.cargar("X", "M1", tmp_path)
    assert len(cargado["ts"]) == 4
    assert list(cargado["close"]) == [1.5, 999.0, 998.0, 997.0]


def test_particion_se_agrega_a_otro_plazo(tmp_path):
    datos.guardar_anual("X", "M1", _minutos(10), tmp_path)
    assert datos.resoluciones("X", tmp_path) == ["M1"]
    assert len(datos.cargar("X", "M5", tmp_path)["ts"]) == 2


def test_meses_con_velas_sin_datos(tmp_path):
    assert datos.meses_con_velas("X", "M1", tmp_path) == set()


def test_meses_con_velas_particionado_por_anio(tmp_path):
    a = _minutos(2, "2023-12-31 23:59")
    datos.guardar_anual("X", "M1", a, tmp_path)
    b = _minutos(2, "2024-03-15 00:00")
    datos.guardar_anual("X", "M1", b, tmp_path)
    assert datos.meses_con_velas("X", "M1", tmp_path) == {(2023, 12), (2024, 1), (2024, 3)}


def test_meses_con_velas_sin_particionar(tmp_path):
    datos.guardar("X", "D1", _minutos(2, "2024-06-01 00:00"), tmp_path)
    assert datos.meses_con_velas("X", "D1", tmp_path) == {(2024, 6)}


def test_cargar_recorta_por_desde(tmp_path):
    datos.guardar("X", "M1", _minutos(10), tmp_path)
    completo = datos.cargar("X", "M1", tmp_path)
    assert len(completo["ts"]) == 10
    recortado = datos.cargar("X", "M1", tmp_path, desde="2024-01-01 00:05")
    assert len(recortado["ts"]) == 5
    assert recortado["ts"][0] == np.datetime64("2024-01-01T00:05", "ns")


def test_cargar_recorta_por_desde_antes_de_agregar(tmp_path):
    datos.guardar("X", "M1", _minutos(10), tmp_path)
    recortado = datos.cargar("X", "M5", tmp_path, desde="2024-01-01 00:05")
    assert len(recortado["ts"]) == 1
    assert recortado["ts"][0] == np.datetime64("2024-01-01T00:05", "ns")
