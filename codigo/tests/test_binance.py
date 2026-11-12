import io
import zipfile
from datetime import date

import pandas as pd

from quant import datos
from quant.fuentes import binance as bn

INFO = {"clase": "cripto", "fuente": "binance", "simbolo": "BTCUSDT", "desde": "2024-11-01"}


def _zip(filas):
    texto = "\n".join(f"{t},{o},{o + 1},{o - 1},{o + 0.5},2.5,{t + 59999},0,1,0,0,0" for t, o in filas)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("x.csv", texto)
    return buffer.getvalue()


def _ms(txt):
    return int(pd.Timestamp(txt).value // 1_000_000)


def test_urls():
    assert bn.url_mes("BTCUSDT", 2024, 3).endswith("/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2024-03.zip")
    assert bn.url_dia("BTCUSDT", date(2025, 1, 2)).endswith("/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2025-01-02.zip")


def test_decodificar_milisegundos_y_microsegundos():
    ms = bn.decodificar(_zip([(_ms("2024-12-01 00:00"), 100.0)]))
    us = bn.decodificar(_zip([(_ms("2025-06-01 00:01") * 1000, 200.0)]))
    assert list(ms.columns) == datos.COLUMNAS
    assert ms.iloc[0]["ts"] == pd.Timestamp("2024-12-01 00:00") and ms.iloc[0]["high"] == 101.0
    assert us.iloc[0]["ts"] == pd.Timestamp("2025-06-01 00:01") and us.iloc[0]["close"] == 200.5


def test_decodificar_redondea_hacia_abajo_al_minuto():
    ts = int(pd.Timestamp("2017-12-04 06:00:20.799").value // 1_000_000)
    df = bn.decodificar(_zip([(ts, 50.0)]))
    assert df.iloc[0]["ts"] == pd.Timestamp("2017-12-04 06:00:00")


def test_actualizar_mensual_diario_e_incremental(tmp_path, sesion_falsa):
    respuestas = {
        bn.url_mes("BTCUSDT", 2024, 11): _zip([(_ms("2024-11-05 10:00"), 1.0)]),
        bn.url_mes("BTCUSDT", 2024, 12): _zip([(_ms("2024-12-15 08:00"), 2.0)]),
        bn.url_dia("BTCUSDT", date(2025, 1, 2)): _zip([(_ms("2025-01-02 00:00") * 1000, 3.0),
                                                      (_ms("2025-01-03 00:00") * 1000, 4.0)]),
    }
    s = sesion_falsa(respuestas)
    r = bn.actualizar("BTCUSDT", INFO, date(2025, 1, 2), tmp_path, s, dormir=lambda x: None)
    assert (r["meses"], r["velas"], r["error"]) == (3, 3, None)
    assert bn.url_mes("BTCUSDT", 2024, 12) in s.pedidas
    assert bn.url_mes("BTCUSDT", 2025, 1) not in s.pedidas
    assert datos.ultimo_ts("BTCUSDT", "M1", tmp_path) == pd.Timestamp("2025-01-02 00:00")
    s2 = sesion_falsa(respuestas)
    r2 = bn.actualizar("BTCUSDT", INFO, date(2025, 1, 2), tmp_path, s2, dormir=lambda x: None)
    assert bn.url_mes("BTCUSDT", 2024, 11) not in s2.pedidas
    assert r2["velas"] == 1
    assert s2.pedidas == [bn.url_mes("BTCUSDT", 2024, 12),
                          bn.url_dia("BTCUSDT", date(2025, 1, 1)),
                          bn.url_dia("BTCUSDT", date(2025, 1, 2))]


def test_error_detiene(tmp_path, sesion_falsa):
    s = sesion_falsa({bn.url_mes("BTCUSDT", 2024, 11): 503})
    r = bn.actualizar("BTCUSDT", INFO, date(2025, 1, 2), tmp_path, s, dormir=lambda x: None)
    assert "intentos" in r["error"] and r["velas"] == 0
    assert datos.ultimo_ts("BTCUSDT", "M1", tmp_path) is None


INFO_MESES = {"clase": "cripto", "fuente": "binance", "simbolo": "BTCUSDT", "desde": "2020-01-01"}


def _zip_mes(txt, valor):
    return _zip([(_ms(txt), valor)])


def test_limite_de_tiempo_entre_meses(tmp_path, sesion_falsa):
    respuestas = {bn.url_mes("BTCUSDT", 2024, 11): _zip([(_ms("2024-11-05 10:00"), 1.0)]),
                  bn.url_mes("BTCUSDT", 2024, 12): _zip([(_ms("2024-12-05 10:00"), 2.0)])}
    s = sesion_falsa(respuestas)
    relojes = iter([0.0, 100.0])
    r = bn.actualizar("BTCUSDT", INFO, date(2025, 1, 2), tmp_path, s, dormir=lambda x: None,
                      limite=10.0, reloj=lambda: next(relojes))
    assert r["omitido"] == "tiempo agotado"
    assert r["error"] is None
    assert datos.ultimo_ts("BTCUSDT", "M1", tmp_path) == pd.Timestamp("2024-11-05 10:00")


def test_sin_datos_en_todo_el_rango_da_error(tmp_path, sesion_falsa):
    info = {"clase": "cripto", "fuente": "binance", "simbolo": "NOEXISTE", "desde": "2024-02-01"}
    s = sesion_falsa({})
    r = bn.actualizar("NOEXISTE", info, date(2024, 3, 5), tmp_path, s, dormir=lambda x: None)
    assert r["velas"] == 0
    assert r["error"] == "sin datos en todo el rango solicitado"


def test_mes_intermedio_ausente_se_reintenta_hasta_tener_datos(tmp_path, sesion_falsa):
    respuestas = {
        bn.url_mes("BTCUSDT", 2020, 1): _zip_mes("2020-01-05 00:00", 1.0),
        bn.url_mes("BTCUSDT", 2020, 4): _zip_mes("2020-04-05 00:00", 4.0),
    }
    s = sesion_falsa(respuestas)
    hasta = date(2020, 5, 10)
    r = bn.actualizar("BTCUSDT", INFO_MESES, hasta, tmp_path, s, dormir=lambda x: None)
    assert r["meses_vacios"] == ["2020-02", "2020-03"]
    assert "meses sin datos: 2020-02, 2020-03" in r["error"]
    assert datos.meses_con_velas("BTCUSDT", "M1", tmp_path) == {(2020, 1), (2020, 4)}

    respuestas2 = dict(respuestas)
    respuestas2[bn.url_mes("BTCUSDT", 2020, 2)] = _zip_mes("2020-02-10 00:00", 2.0)
    respuestas2[bn.url_mes("BTCUSDT", 2020, 3)] = _zip_mes("2020-03-10 00:00", 3.0)
    s2 = sesion_falsa(respuestas2)
    r2 = bn.actualizar("BTCUSDT", INFO_MESES, hasta, tmp_path, s2, dormir=lambda x: None)
    assert bn.url_mes("BTCUSDT", 2020, 1) not in s2.pedidas
    assert r2["meses_vacios"] == []
    assert r2["error"] is None
    assert datos.meses_con_velas("BTCUSDT", "M1", tmp_path) >= {(2020, 1), (2020, 2), (2020, 3), (2020, 4)}


def test_recupera_dia_suelto_del_mes_anterior_en_la_segunda_noche(tmp_path, sesion_falsa):
    info = {"clase": "cripto", "fuente": "binance", "simbolo": "BTCUSDT", "desde": "2024-12-28"}
    hasta = date(2025, 1, 2)
    respuestas = {
        bn.url_dia("BTCUSDT", date(2024, 12, 28)): _zip([(_ms("2024-12-28 00:00") * 1000, 1.0)]),
        bn.url_dia("BTCUSDT", date(2024, 12, 29)): _zip([(_ms("2024-12-29 00:00") * 1000, 2.0)]),
        bn.url_dia("BTCUSDT", date(2024, 12, 31)): _zip([(_ms("2024-12-31 00:00") * 1000, 3.0)]),
        bn.url_dia("BTCUSDT", date(2025, 1, 1)): _zip([(_ms("2025-01-01 00:00") * 1000, 4.0)]),
        bn.url_dia("BTCUSDT", date(2025, 1, 2)): _zip([(_ms("2025-01-02 00:00") * 1000, 5.0)]),
    }
    s = sesion_falsa(respuestas)
    bn.actualizar("BTCUSDT", info, hasta, tmp_path, s, dormir=lambda x: None)
    df2024 = pd.read_parquet(tmp_path / "BTCUSDT" / "M1" / "2024.parquet")
    assert pd.Timestamp("2024-12-30") not in set(df2024["ts"])

    respuestas2 = dict(respuestas)
    respuestas2[bn.url_dia("BTCUSDT", date(2024, 12, 30))] = _zip([(_ms("2024-12-30 00:00") * 1000, 9.0)])
    s2 = sesion_falsa(respuestas2)
    r2 = bn.actualizar("BTCUSDT", info, hasta, tmp_path, s2, dormir=lambda x: None)
    assert r2["error"] is None
    df2024 = pd.read_parquet(tmp_path / "BTCUSDT" / "M1" / "2024.parquet")
    assert pd.Timestamp("2024-12-30") in set(df2024["ts"])


def test_mes_reciente_anterior_recupera_dia_intermedio_perdido(tmp_path, sesion_falsa):
    respuestas = {
        bn.url_mes("BTCUSDT", 2020, 1): _zip_mes("2020-01-05 00:00", 1.0),
        bn.url_dia("BTCUSDT", date(2020, 4, 20)): _zip([(_ms("2020-04-20 00:00") * 1000, 20.0)]),
    }
    s = sesion_falsa(respuestas)
    hasta = date(2020, 5, 10)
    r = bn.actualizar("BTCUSDT", INFO_MESES, hasta, tmp_path, s, dormir=lambda x: None)
    assert r["meses_vacios"] == ["2020-02", "2020-03"]
    assert datos.meses_con_velas("BTCUSDT", "M1", tmp_path) == {(2020, 1), (2020, 4)}

    respuestas2 = dict(respuestas)
    respuestas2[bn.url_mes("BTCUSDT", 2020, 2)] = _zip_mes("2020-02-10 00:00", 2.0)
    respuestas2[bn.url_mes("BTCUSDT", 2020, 3)] = _zip_mes("2020-03-10 00:00", 3.0)
    respuestas2[bn.url_dia("BTCUSDT", date(2020, 4, 5))] = _zip([(_ms("2020-04-05 00:00") * 1000, 5.0)])
    s2 = sesion_falsa(respuestas2)
    r2 = bn.actualizar("BTCUSDT", INFO_MESES, hasta, tmp_path, s2, dormir=lambda x: None)
    assert r2["meses_vacios"] == []
    assert r2["error"] is None
    df2020 = pd.read_parquet(tmp_path / "BTCUSDT" / "M1" / "2020.parquet")
    ts = set(df2020["ts"])
    assert pd.Timestamp("2020-04-05") in ts and pd.Timestamp("2020-04-20") in ts
    assert pd.Timestamp("2020-02-10") in ts and pd.Timestamp("2020-03-10") in ts
