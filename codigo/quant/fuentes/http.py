import math
import time

import requests

AGENTE = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}


RETRY_AFTER_TOPE = 120
TOPE_ESPERA_TOTAL = 180.0


class ErrorFuente(RuntimeError):
    pass


def _espera_retry_after(respuesta):
    """Delta-seconds valido y finito, acotado a RETRY_AFTER_TOPE. Fecha HTTP, vacio, ausente, negativo
    o no finito (nan/inf): None, para que el llamador caiga al backoff normal sin lanzar nunca."""
    cabeceras = getattr(respuesta, "headers", None) or {}
    crudo, margen = cabeceras.get("Retry-After"), 0.0
    if crudo is None:
        # Reddit sends the seconds left in its window instead; one more second lands past the reset.
        crudo, margen = cabeceras.get("x-ratelimit-reset"), 1.0
    if crudo is None:
        return None
    try:
        valor = float(crudo)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(valor):
        return None
    return min(max(valor, 0.0) + margen, RETRY_AFTER_TOPE)


def descargar(url, sesion, reintentos=5, espera=2.0, dormir=time.sleep, timeout=30, cabeceras=None):
    cabeceras = cabeceras or AGENTE
    acumulado = 0.0

    def _dormir_acotado(segundos):
        """Nunca duerme mas de TOPE_ESPERA_TOTAL en total dentro de esta llamada a descargar."""
        nonlocal acumulado
        real = max(0.0, min(segundos, TOPE_ESPERA_TOTAL - acumulado))
        dormir(real)
        acumulado += real

    for intento in range(reintentos):
        try:
            respuesta = sesion.get(url, headers=cabeceras, timeout=timeout)
            if respuesta.status_code == 200:
                return respuesta.content
            if respuesta.status_code == 404:
                return b""
            if respuesta.status_code == 429 and intento < reintentos - 1:
                espera_retry = _espera_retry_after(respuesta)
                _dormir_acotado(espera_retry if espera_retry is not None else espera * 2 ** intento)
                continue
        except requests.RequestException:
            pass
        if intento < reintentos - 1:
            _dormir_acotado(espera * 2 ** intento)
    raise ErrorFuente(f"sin respuesta tras {reintentos} intentos: {url}")
