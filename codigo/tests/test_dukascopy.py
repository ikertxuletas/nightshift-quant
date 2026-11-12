import lzma
import struct
from datetime import date, timedelta

import pandas as pd
import pytest

from quant import datos
from quant.fuentes import dukascopy as dk

INFO = {"clase": "forex", "fuente": "dukascopy", "simbolo": "EURUSD", "divisor": 100000, "desde": "2024-05-10"}


def _bi5(*registros):
    return lzma.compress(b"".join(struct.pack(">IIIIIf", *r) for r in registros), format=lzma.FORMAT_ALONE)


def _url(d):
    return dk.url_dia("EURUSD", d)


def test_url_con_mes_en_base_cero():
    assert dk.url_dia("EURUSD", date(2024, 5, 10)).endswith("/EURUSD/2024/04/10/BID_candles_min_1.bi5")


def test_decodificar():
    contenido = _bi5((0, 107817, 107821, 107816, 107822, 69.5), (60, 107821, 107830, 107820, 107835, 0.0))
    df = dk.decodificar(contenido, date(2024, 5, 10), 100000)
    assert list(df.columns) == datos.COLUMNAS and len(df) == 1
    fila = df.iloc[0]
    assert fila["ts"] == pd.Timestamp("2024-05-10 00:00")
    assert (fila["open"], fila["high"], fila["low"], fila["close"]) == pytest.approx((1.07817, 1.07822, 1.07816, 1.07821))


def test_decodificar_vacio():
    assert dk.decodificar(b"", date(2024, 5, 10), 100000).empty


def test_actualizar_incremental(tmp_path, sesion_falsa):
    s = sesion_falsa({_url(date(2024, 5, 10)): _bi5((0, 1, 1, 1, 1, 1.0)),
                      _url(date(2024, 5, 12)): _bi5((3600, 2, 2, 2, 2, 1.0))})
    r = dk.actualizar("EURUSD", INFO, date(2024, 5, 12), tmp_path, s, dormir=lambda x: None)
    assert (r["dias"], r["velas"], r["hasta"], r["error"]) == (3, 2, "2024-05-12", None)
    assert datos.ultimo_ts("EURUSD", "M1", tmp_path) == pd.Timestamp("2024-05-12 01:00")
    s2 = sesion_falsa({_url(date(2024, 5, 13)): _bi5((0, 3, 3, 3, 3, 1.0))})
    r2 = dk.actualizar("EURUSD", INFO, date(2024, 5, 13), tmp_path, s2, dormir=lambda x: None)
    assert s2.pedidas == [_url(date(2024, 5, 13))] and r2["velas"] == 1


def test_error_detiene_sin_huecos(tmp_path, sesion_falsa):
    s = sesion_falsa({_url(date(2024, 5, 10)): _bi5((0, 1, 1, 1, 1, 1.0)),
                      _url(date(2024, 5, 11)): 503,
                      _url(date(2024, 5, 12)): _bi5((0, 2, 2, 2, 2, 1.0))})
    r = dk.actualizar("EURUSD", INFO, date(2024, 5, 12), tmp_path, s, dormir=lambda x: None)
    assert r["hasta"] == "2024-05-10" and "intentos" in r["error"]
    assert datos.ultimo_ts("EURUSD", "M1", tmp_path) == pd.Timestamp("2024-05-10 00:00")


def test_sin_datos_en_todo_el_rango_da_error(tmp_path, sesion_falsa):
    r = dk.actualizar("EURUSD", INFO, date(2024, 6, 15), tmp_path, sesion_falsa({}), dormir=lambda x: None)
    assert r["velas"] == 0
    assert r["error"] == "sin datos en todo el rango solicitado"


def test_dia_falla_dos_veces_y_a_la_tercera_responde(tmp_path, sesion_falsa):
    dormidos = []
    s = sesion_falsa({_url(date(2024, 5, 10)): _bi5((0, 1, 1, 1, 1, 1.0)),
                      _url(date(2024, 5, 11)): [503] * 10 + [_bi5((0, 2, 2, 2, 2, 1.0))],
                      _url(date(2024, 5, 12)): _bi5((0, 3, 3, 3, 3, 1.0))})
    r = dk.actualizar("EURUSD", INFO, date(2024, 5, 12), tmp_path, s, dormir=lambda x: dormidos.append(x))
    assert r["error"] is None
    assert (r["dias"], r["velas"], r["hasta"]) == (3, 3, "2024-05-12")
    assert dormidos.count(60) == 2
    assert datos.ultimo_ts("EURUSD", "M1", tmp_path) == pd.Timestamp("2024-05-12 00:00")


def test_dia_falla_siempre_tres_intentos_y_error_sin_guardar_nada_posterior(tmp_path, sesion_falsa):
    dormidos = []
    s = sesion_falsa({_url(date(2024, 5, 10)): _bi5((0, 1, 1, 1, 1, 1.0)),
                      _url(date(2024, 5, 11)): 503,
                      _url(date(2024, 5, 12)): _bi5((0, 3, 3, 3, 3, 1.0))})
    r = dk.actualizar("EURUSD", INFO, date(2024, 5, 12), tmp_path, s, dormir=lambda x: dormidos.append(x))
    assert "intentos" in r["error"]
    assert dormidos.count(60) == 2
    assert datos.ultimo_ts("EURUSD", "M1", tmp_path) == pd.Timestamp("2024-05-10 00:00")


def test_limite_de_tiempo_entre_lotes(tmp_path, sesion_falsa):
    dias = [date(2024, 5, 10) + timedelta(days=i) for i in range(35)]
    s = sesion_falsa({_url(dias[0]): _bi5((0, 1, 1, 1, 1, 1.0))})
    relojes = iter([0.0, 100.0])
    r = dk.actualizar("EURUSD", INFO, dias[-1], tmp_path, s, dormir=lambda x: None,
                       limite=10.0, reloj=lambda: next(relojes))
    assert r["omitido"] == "tiempo agotado"
    assert r["error"] is None
    assert datos.ultimo_ts("EURUSD", "M1", tmp_path) == pd.Timestamp("2024-05-10 00:00")


def test_frontera_de_lotes_70_dias_tres_lotes(tmp_path, sesion_falsa):
    dias = [date(2024, 5, 10) + timedelta(days=i) for i in range(70)]
    respuestas = {_url(d): _bi5((0, i + 1, i + 1, i + 1, i + 1, 1.0)) for i, d in enumerate(dias)}
    s = sesion_falsa(respuestas)
    r = dk.actualizar("EURUSD", INFO, dias[-1], tmp_path, s, dormir=lambda x: None)
    assert (r["dias"], r["velas"], r["error"]) == (70, 70, None)
    b = datos.cargar("EURUSD", "M1", tmp_path)
    assert list(b["ts"]) == [pd.Timestamp(d) for d in dias]
    assert b["close"] == pytest.approx([(i + 1) / 100000 for i in range(70)])


def test_max_dias(tmp_path, sesion_falsa):
    r = dk.actualizar("EURUSD", INFO, date(2024, 6, 30), tmp_path, sesion_falsa({}), max_dias=5, dormir=lambda x: None)
    assert r["dias"] == 5 and r["hasta"] == "2024-05-14"
