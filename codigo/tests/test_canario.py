import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from quant.costes import Costes
from quant.investigacion import canario, contratos

COSTES = Costes(broker="p", clase="indice", spread_pct=0.0, comision_pct=0.0, deslizamiento_pct=0.0,
                swap_pct_anual=0.0, apalancamiento=100.0, permite_corto=True)
CANARIO = Path(__file__).resolve().parents[2] / "canario"

EXTRACTO = {"operable": "si", "tipo": "tendencia", "mercado": ["accion"], "plazo": "D1",
            "extracto": "Compra SPY cuando el cierre supera la SMA de 200 sesiones y vende cuando cae por debajo.",
            "prometido": {"cagr": 8.1, "drawdown": -23.4, "sharpe": 0.62, "periodo": "1994-2023", "cita": "c"},
            "alarmas": []}
FICHA = {"id": "canario-sma200-spy", "titulo": "SMA 200 en SPY", "tipo": "tendencia", "forma": "serie_temporal",
         "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
         "entrada": {"largo": {">": ["close", "SMA(200)"]}}, "salida": {"largo": {"<": ["close", "SMA(200)"]}},
         "gestion": {}, "prometido": EXTRACTO["prometido"], "supuestos": []}


def _raiz(tmp_path):
    """Idempotente: se puede llamar varias veces con el mismo tmp_path dentro de un test."""
    if not (tmp_path / "canario").exists():
        shutil.copytree(CANARIO, tmp_path / "canario")
        for agente in ("lector", "formalizador", "critico"):
            carpeta = tmp_path / "skills" / agente
            carpeta.mkdir(parents=True)
            (carpeta / "skill.md").write_text(f"skill de {agente} (una linea, no la real)", encoding="utf-8")
        (tmp_path / "config").mkdir()
    return tmp_path


def _barras_papel(inst=None, tf=None):
    n = 60
    close = 100 + np.arange(n) * 0.5
    ts = (np.datetime64("now", "D") - np.timedelta64(n + 2, "D")).astype("datetime64[ns]") \
        + np.arange(n) * np.timedelta64(1, "D")
    return {"ts": ts, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": np.ones(n)}


def _ejecutar(raiz, **kw):
    """No debe leer skills\\ ni config\\agentes.json reales: siempre con raiz_skills/config de tmp_path."""
    raiz = Path(raiz)
    kw.setdefault("papel", {"barras": _barras_papel, "costes": lambda inst: COSTES})
    return canario.ejecutar(raiz, raiz_skills=raiz / "skills", config=raiz / "config", **kw)


def _llamar(extracto=EXTRACTO, ficha=FICHA, veredicto="aprobada"):
    respuestas = iter([json.dumps(extracto), json.dumps({"expresable": True, "motivo": "", "ficha": ficha}),
                       json.dumps({"veredicto": veredicto, "motivos": []})])
    return lambda modelo, sistema, prompt, **kw: next(respuestas)


def _validar_con(operaciones):
    return lambda ficha, raiz: {"SPY": {"veredicto": "no_pasa", "metricas": {"total": {"operaciones": operaciones}}}}


_validar_ok = _validar_con(14)


def test_canario_sano(tmp_path):
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=_validar_ok)
    assert salida["ok"] is True and "fallo" not in salida
    assert salida["pasos"] == {"lector": "ok", "formalizador": "ok", "critico": "ok", "validacion": "ok",
                              "papel": "ok"}
    assert contratos.hay_fallo(salida) is None


@pytest.mark.parametrize("cambio,paso", [
    ({"extracto": EXTRACTO | {"plazo": "H1"}}, "lector"),
    ({"extracto": EXTRACTO | {"operable": "no"}}, "lector"),
    ({"ficha": FICHA | {"universo": {"instrumentos": ["QQQ"], "plazo": "D1"}}}, "formalizador"),
    ({"ficha": FICHA | {"entrada": {"largo": {">": ["close", "SMA(50)"]}}}}, "formalizador"),
    ({"ficha": FICHA | {"entrada": FICHA["entrada"] | {"corto": {"<": ["close", "SMA(200)"]}}}}, "formalizador"),
    ({"ficha": FICHA | {"entrada": {"largo": {">": ["close", "SMA(2000)"]}}}}, "formalizador"),
    ({"ficha": FICHA | {"entrada": {"largo": {"<": ["close", "SMA(200)"]}}}}, "formalizador"),
    ({"ficha": FICHA | {"entrada": {"largo": {"y": [{">": ["close", "SMA(50)"]},
                                                     {"<": ["close", "SMA(200)"]}]}}}}, "formalizador"),
    ({"veredicto": "rechazada"}, "critico"),
])
def test_canario_dice_que_paso_falla(tmp_path, cambio, paso):
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(**cambio), validar=_validar_ok)
    assert salida["ok"] is False and salida["pasos"][paso] != "ok"
    assert salida["fallo"].startswith(f"canario: {paso}:")
    assert contratos.hay_fallo(salida) == salida["fallo"]
    posteriores = list(salida["pasos"])[list(salida["pasos"]).index(paso) + 1:]
    assert all(salida["pasos"][p] == "no ejecutado" for p in posteriores)


@pytest.mark.parametrize("token", ["SMA( 200 )", "SMA(200.0)"])
def test_canario_acepta_variaciones_de_formato_del_indicador(tmp_path, token):
    ficha = FICHA | {"entrada": {"largo": {">": ["close", token]}}}
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(ficha=ficha), validar=_validar_ok)
    assert salida["ok"] is True


def test_canario_acepta_la_comparacion_escrita_al_reves(tmp_path):
    ficha = FICHA | {"entrada": {"largo": {"<": ["SMA(200)", "close"]}},
                     "salida": {"largo": {">": ["SMA(200)", "close"]}}}
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(ficha=ficha), validar=_validar_ok)
    assert salida["ok"] is True


@pytest.mark.parametrize("cambio", [
    {"entrada": {"largo": {">": ["SMA(200)", "close"]}}},
    {"salida": {"largo": {"<": ["SMA(200)", "close"]}}},
])
def test_canario_rechaza_la_comparacion_al_reves_con_el_operador_equivocado(tmp_path, cambio):
    ficha = FICHA | cambio
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(ficha=ficha), validar=_validar_ok)
    assert salida["ok"] is False and salida["pasos"]["formalizador"] != "ok"


@pytest.mark.parametrize("cambio", [
    {"entrada": {"largo": {"<": ["SMA(200)", "SMA(200)"]}}},
    {"entrada": {"largo": {"<": ["SMA(200)", "SMA(50)"]}}},
    {"entrada": {"largo": {">": ["open", "SMA(200)"]}}},
])
def test_canario_exige_comparar_el_precio_con_el_indicador(tmp_path, cambio):
    ficha = FICHA | cambio
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(ficha=ficha), validar=_validar_ok)
    assert salida["ok"] is False and salida["pasos"]["formalizador"] != "ok"


@pytest.mark.parametrize("cambio", [
    {"entrada": {"largo": {">": ["close", "SMA(200)"]}}},
    {"entrada": {"largo": {"<": ["SMA(200)", "close"]}}},
])
def test_canario_sigue_aceptando_close_contra_el_indicador(tmp_path, cambio):
    ficha = FICHA | cambio
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(ficha=ficha), validar=_validar_ok)
    assert salida["ok"] is True


def test_canario_validacion_sin_datos_es_fallo(tmp_path):
    sin_datos = lambda ficha, raiz: {"SPY": {"veredicto": "pendiente_datos", "motivo": "sin barras"}}
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=sin_datos)
    assert salida["ok"] is False and salida["fallo"].startswith("canario: validacion:")


def test_canario_no_pasa_sin_operaciones_es_fallo(tmp_path):
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=_validar_con(0))
    assert salida["ok"] is False and salida["fallo"] == "canario: validacion: SPY: sin operaciones"
    sin_metricas = lambda ficha, raiz: {"SPY": {"veredicto": "no_pasa"}}
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=sin_metricas)
    assert salida["ok"] is False and salida["fallo"] == "canario: validacion: SPY: sin operaciones"


def test_canario_no_pasa_con_operaciones_pasa(tmp_path):
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=_validar_con(14))
    assert salida["ok"] is True


@pytest.mark.parametrize("mercado,pasa", [
    (["accion"], True),
    (["indice"], True),
    (["divisa"], False),
    (["divisa", "indice"], True),
])
def test_mercado_contiene_acepta_lista(mercado, pasa):
    assert canario.mercado_contiene(mercado, ["accion", "indice"]) is pasa


def test_mercado_contiene_sigue_aceptando_cadena():
    assert canario.mercado_contiene(["accion"], "accion") is True
    assert canario.mercado_contiene(["indice"], "accion") is False


def test_canario_sin_tiempo_se_omite_sin_fallo(tmp_path):
    tiempos = iter([0, 100, 100, 100, 100, 100, 100])
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=_validar_ok, hasta=50,
                       reloj=lambda: next(tiempos))
    assert salida["omitido"] == "sin tiempo" and "ok" not in salida
    assert salida["pasos"]["lector"] == "ok" and salida["pasos"]["formalizador"] == "no ejecutado"
    assert contratos.hay_fallo(salida) is None


def test_canario_nunca_lanza(tmp_path):
    def roto(*a, **kw):
        raise RuntimeError("ollama caido")
    salida = _ejecutar(_raiz(tmp_path), llamar=roto, validar=_validar_ok)
    assert salida["ok"] is False and "ollama caido" in salida["fallo"]
    assert canario.ejecutar(tmp_path / "vacio", llamar=_llamar(), validar=_validar_ok)["ok"] is False


def test_canario_runs_paper_pass(tmp_path):
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=_validar_ok)
    assert salida["ok"] is True and salida["pasos"]["papel"] == "ok"


def test_canario_paper_pass_without_data_is_failure(tmp_path):
    def sin_barras(inst, tf):
        raise OSError("sin datos de US500")
    salida = _ejecutar(_raiz(tmp_path), llamar=_llamar(), validar=_validar_ok,
                       papel={"barras": sin_barras, "costes": lambda inst: COSTES})
    assert salida["ok"] is False and salida["fallo"].startswith("canario: papel:")


def test_canario_paper_pass_ignores_real_stop_file(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "PARAR").write_text("", encoding="utf-8")
    salida = _ejecutar(raiz, llamar=_llamar(), validar=_validar_ok)
    assert salida["ok"] is True and salida["pasos"]["papel"] == "ok"
