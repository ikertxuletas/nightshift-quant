import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from quant.investigacion import memoria

_MODULO_MEMORIA = "test_memoria"


def _prohibido(nombre):
    def f(*a, **k):
        raise AssertionError(f"memoria.{nombre} llamado sin parchear en un test (ver memoria.liberar)")
    return f


@pytest.fixture(autouse=True)
def _memoria_sin_cerrar_procesos_reales(request, monkeypatch):
    """Red de seguridad: ningun test debe llegar a tasklist/taskkill de verdad sin parchearlos
    explicitamente. test_memoria.py prueba memoria.cerrar/memoria.procesos de verdad, asi que se
    excluye (mockea subprocess.run en su lugar)."""
    if request.module.__name__.rsplit(".", 1)[-1] == _MODULO_MEMORIA:
        return
    monkeypatch.setattr(memoria, "cerrar", _prohibido("cerrar"))
    monkeypatch.setattr(memoria, "procesos", _prohibido("procesos"))


@pytest.fixture(autouse=True)
def _sin_claude_real(monkeypatch):
    """Ningun test lanza `claude` de verdad: el ejecutor por defecto queda prohibido.
    test_claude_cli.py pasa siempre su propio ejecutor."""
    from quant.investigacion import claude_cli

    def prohibido(*a, **k):
        raise AssertionError("claude real llamado en un test (pasa un ejecutor o un llamar falso)")
    monkeypatch.setattr(claude_cli, "_ejecutar_defecto", prohibido)


def hacer_barras(close, open=None, high=None, low=None, inicio="2024-01-01", paso="1D"):
    c = np.asarray(close, float)
    o = c.copy() if open is None else np.asarray(open, float)
    h = np.maximum(o, c) + 1 if high is None else np.asarray(high, float)
    l = np.minimum(o, c) - 1 if low is None else np.asarray(low, float)
    ts = np.datetime64(inicio, "ns") + np.arange(len(c)) * np.timedelta64(1, paso[-1]) * int(paso[:-1])
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": np.ones(len(c))}


@pytest.fixture
def barras():
    return hacer_barras


@pytest.fixture
def costes_cero():
    from quant.costes import Costes

    def crear(**cambios):
        base = dict(broker="prueba", clase="indice", spread_pct=0.0, comision_pct=0.0,
                    deslizamiento_pct=0.0, swap_pct_anual=0.0, apalancamiento=100.0, permite_corto=True)
        return Costes(**{**base, **cambios})
    return crear


class _Respuesta:
    def __init__(self, codigo, contenido=b"", headers=None):
        self.status_code = codigo
        self.content = contenido
        self.headers = headers or {}


class SesionFalsa:
    def __init__(self, respuestas):
        self.respuestas = {k: (list(v) if isinstance(v, list) else [v]) for k, v in respuestas.items()}
        self.pedidas = []
        self.cabeceras_enviadas = []

    def get(self, url, headers=None, timeout=None):
        self.pedidas.append(url)
        self.cabeceras_enviadas.append(headers)
        cola = self.respuestas.get(url, [404])
        valor = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(valor, Exception):
            raise valor
        if isinstance(valor, tuple):
            codigo, headers_respuesta, *resto = valor
            contenido = resto[0] if resto else b""
            return _Respuesta(codigo, contenido=contenido, headers=headers_respuesta)
        if isinstance(valor, int):
            return _Respuesta(valor)
        return _Respuesta(200, valor)


@pytest.fixture
def sesion_falsa():
    return SesionFalsa


_RESULTADOS = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "fallos": []}
_RAIZ = Path(__file__).resolve().parents[2]


def _completa(config):
    """Only a run of the whole suite is recorded; a single file or -k would show a part as the whole."""
    o = config.option
    if o.keyword or getattr(o, "lf", False) or getattr(o, "deselect", None):
        return False
    dirs = {_RAIZ / "codigo", _RAIZ / "codigo" / "tests"}
    return all(Path(a).resolve() in dirs for a in config.args)


def pytest_runtest_logreport(report):
    if hasattr(report, "wasxfail"):
        if report.when == "call" or report.skipped:
            _RESULTADOS["xfailed"] += 1
    elif report.failed:
        _RESULTADOS["failed"] += 1
        _RESULTADOS["fallos"].append(report.nodeid)
    elif report.skipped:
        _RESULTADOS["skipped"] += 1
    elif report.when == "call":
        _RESULTADOS["passed"] += 1


def pytest_sessionstart(session):
    session.config._inicio_pruebas = time.monotonic()


def pytest_sessionfinish(session, exitstatus):
    if not _completa(session.config) or session.testscollected == 0:
        return
    r = _RESULTADOS
    datos = {"fecha": datetime.now().isoformat(timespec="seconds"), "total": session.testscollected,
             "pasan": r["passed"], "fallan": len(set(r["fallos"])), "omitidas": r["skipped"], "esperadas": r["xfailed"],
             "segundos": round(time.monotonic() - session.config._inicio_pruebas, 1),
             "fallos": sorted(set(r["fallos"]))[:50]}
    destino = _RAIZ / "registro" / "pruebas.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
