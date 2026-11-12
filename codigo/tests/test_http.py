import pytest
import requests

from quant.fuentes import http


def test_404_es_vacio(sesion_falsa):
    assert http.descargar("u", sesion_falsa({"u": 404}), dormir=lambda s: None) == b""


def test_reintenta_hasta_exito(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [503, requests.ConnectionError("x"), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [1.0, 2.0]


def test_agota_reintentos(sesion_falsa):
    esperas = []
    with pytest.raises(http.ErrorFuente, match="3 intentos"):
        http.descargar("u", sesion_falsa({"u": 503}), reintentos=3, dormir=esperas.append)
    assert len(esperas) == 2


def test_429_respeta_retry_after(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "30"}), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [30]


def test_429_retry_after_tiene_tope_de_120(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "600"}), b"ok"]})
    http.descargar("u", s, espera=1.0, dormir=esperas.append)
    assert esperas == [120]


def test_429_sin_retry_after_usa_el_backoff_normal(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [429, b"ok"]})
    http.descargar("u", s, espera=1.0, dormir=esperas.append)
    assert esperas == [1.0]


def test_cabeceras_por_defecto_son_agente(sesion_falsa):
    s = sesion_falsa({"u": b"ok"})
    http.descargar("u", s, dormir=lambda x: None)
    assert s.cabeceras_enviadas == [http.AGENTE]


def test_cabeceras_propias_se_envian(sesion_falsa):
    s = sesion_falsa({"u": b"ok"})
    propias = {"User-Agent": "prueba"}
    http.descargar("u", s, dormir=lambda x: None, cabeceras=propias)
    assert s.cabeceras_enviadas == [propias]


def test_429_retry_after_negativo_no_lanza_y_usa_backoff_normal(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "-5"}), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [0.0]


def test_429_retry_after_nan_no_lanza_y_usa_backoff_normal(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "nan"}), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [1.0]


def test_429_retry_after_infinito_no_lanza_y_usa_backoff_normal(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "inf"}), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [1.0]


def test_429_retry_after_fecha_http_usa_backoff_normal(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [1.0]


def test_429_retry_after_vacio_usa_backoff_normal(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": ""}), b"ok"]})
    assert http.descargar("u", s, espera=1.0, dormir=esperas.append) == b"ok"
    assert esperas == [1.0]


def test_tope_total_de_espera_por_llamada(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "120"}), (429, {"Retry-After": "120"}),
                            (429, {"Retry-After": "120"}), (429, {"Retry-After": "120"}), b"ok"]})
    assert http.descargar("u", s, reintentos=5, dormir=esperas.append) == b"ok"
    assert esperas == [120, 60, 0.0, 0.0]
    assert sum(esperas) <= 180


def test_tope_total_de_espera_no_afecta_una_espera_normal_por_debajo_del_tope(sesion_falsa):
    esperas = []
    s = sesion_falsa({"u": [(429, {"Retry-After": "30"}), b"ok"]})
    http.descargar("u", s, espera=1.0, dormir=esperas.append)
    assert esperas == [30]


def test_tuple_con_contenido_no_lo_pierde(sesion_falsa):
    s = sesion_falsa({"u": (200, {}, b"contenido")})
    assert http.descargar("u", s, dormir=lambda x: None) == b"contenido"
