import json
import re
import sqlite3
from copy import deepcopy

import numpy as np
import pytest

from quant.familias import propias
from quant.investigacion import catalogo
from quant.investigacion import laboratorio as lab
from quant.investigacion import mapa as mmapa
from tests.test_asesor import con  # noqa: F401  (tmp_path catalog fixture)
from tests.test_laboratorio import BASE, CRIT, PROPIA, _direccion

MANUAL = propias.PROPIAS["manual"]
BASE_MANUAL = propias.ficha_base("manual")


def _fila(con, estrategia="ejemplo", ficha=None, veredicto="no_pasa", cambios=1, pf=1.0, entreno="auto",
          motivo="m", examen=None, confirmacion=None):
    if entreno == "auto":
        entreno = {"veredicto": veredicto, "criterios": [], "metricas": {"total": {"profit_factor": pf}}}
    f = ficha if ficha is not None else BASE
    cur = con.execute(
        "INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, entreno_json,"
        " examen_json, confirmacion_json, creado) VALUES (?, '2026-11-10', ?, ?, ?, ?, ?, ?, ?, ?, 'x')",
        (estrategia, None if veredicto == "invalido" else lab.huella(f) + motivo, json.dumps(f), motivo, cambios,
         veredicto, json.dumps(entreno) if entreno is not None else None,
         json.dumps(examen) if examen else None, json.dumps(confirmacion) if confirmacion else None))
    con.commit()
    return cur.lastrowid


def _barras_hasta(base, n):
    f = deepcopy(base)
    f["gestion"]["max_barras"] = n
    return f


# --- lab_asesor schema ---

def test_lab_asesor_has_the_spec_columns(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(lab_asesor)")]
    assert cols == ["id", "estrategia", "fecha", "informe", "direccion", "direccion_es", "propuestas_json", "creado"]


def test_ensure_schema_twice_keeps_rows(con):
    _direccion(con, "ejemplo", "Keep me")
    _fila(con, motivo="kept")
    lab.ensure_schema(con)
    lab.ensure_schema(con)
    assert con.execute("SELECT COUNT(*) FROM lab_asesor").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM lab_experimentos").fetchone()[0] == 1
    assert lab.direccion_vigente(con, "ejemplo") == "Keep me"


# --- direccion_vigente ---

def test_direccion_vigente_without_the_table_is_none(tmp_path):
    c = catalogo.abrir(tmp_path / "sin_lab.db")
    assert lab.direccion_vigente(c, "ejemplo") is None


def test_direccion_vigente_without_rows_is_none(con):
    assert lab.direccion_vigente(con, "ejemplo") is None


def test_direccion_vigente_latest_fecha_wins_over_insert_order(con):
    _direccion(con, "ejemplo", "Newer by date", "2026-11-22")
    _direccion(con, "ejemplo", "Inserted later, older date", "2026-11-15")
    assert lab.direccion_vigente(con, "ejemplo") == "Newer by date"


def test_direccion_vigente_same_fecha_highest_id_wins(con):
    _direccion(con, "ejemplo", "First", "2026-11-15")
    _direccion(con, "ejemplo", "Second", "2026-11-15")
    assert lab.direccion_vigente(con, "ejemplo") == "Second"


def test_direccion_vigente_is_per_strategy(con):
    _direccion(con, "ejemplo", "Auto idea", "2026-11-15")
    _direccion(con, "manual", "Manual idea", "2026-11-22")
    assert lab.direccion_vigente(con, "ejemplo") == "Auto idea"
    assert lab.direccion_vigente(con, "manual") == "Manual idea"
    assert lab.direccion_vigente(con, "otra") is None


def test_multiline_direction_reaches_context_intact(con):
    texto = "1. Test slower Hull periods.\n2. Drop Friday entries.\n3. Keep the stop fixed."
    _direccion(con, "ejemplo", texto)
    assert lab.direccion_vigente(con, "ejemplo") == texto
    assert f"## Direction from the weekly advisor (follow it)\n{texto}\n" in lab.contexto(con, PROPIA, BASE)


# --- mejores ---

def test_mejores_orders_by_training_pf_and_respects_n(con):
    for n, pf in ((1, 0.9), (2, 1.4), (3, 1.1), (4, 0.5), (5, 1.2)):
        _fila(con, ficha=_barras_hasta(BASE, n), pf=pf, motivo=f"m{n}")
    assert [f["gestion"]["max_barras"] for f in lab.mejores(con, "ejemplo")] == [2, 5, 3]
    assert [f["gestion"]["max_barras"] for f in lab.mejores(con, "ejemplo", n=1)] == [2]
    assert [f["gestion"]["max_barras"] for f in lab.mejores(con, "ejemplo", n=10)] == [2, 5, 3, 1, 4]


@pytest.mark.parametrize("veredicto", ["no_pasa", "pasa_validador", "ganadora"])
def test_mejores_includes_every_non_invalid_verdict(con, veredicto):
    _fila(con, ficha=_barras_hasta(BASE, 7), veredicto=veredicto, pf=1.3)
    assert lab.mejores(con, "ejemplo") == [_barras_hasta(BASE, 7)]


@pytest.mark.parametrize("kw", [
    {"veredicto": "invalido", "pf": 9.0},
    {"cambios": 0, "pf": 9.0},
    {"cambios": None, "pf": 9.0},
    {"entreno": None},
    {"entreno": {"veredicto": "no_pasa"}},
    {"pf": None},
    {"pf": float("inf")},
    {"pf": "1.5"},
], ids=["invalido", "base", "cambios_null", "sin_entreno", "sin_metricas", "pf_none", "pf_inf", "pf_texto"])
def test_mejores_excludes_rows_without_a_usable_training_pf(con, kw):
    _fila(con, ficha=_barras_hasta(BASE, 1), pf=0.6, motivo="ok")
    _fila(con, ficha=_barras_hasta(BASE, 2), motivo="excluded", **kw)
    assert lab.mejores(con, "ejemplo") == [_barras_hasta(BASE, 1)]


def test_mejores_is_per_strategy(con):
    _fila(con, estrategia="manual", ficha=_barras_hasta(BASE_MANUAL, 3), pf=5.0)
    _fila(con, ficha=_barras_hasta(BASE, 4), pf=1.0)
    assert lab.mejores(con, "ejemplo") == [_barras_hasta(BASE, 4)]
    assert lab.mejores(con, "manual") == [_barras_hasta(BASE_MANUAL, 3)]


# --- mapa_de ---

def _mapa_falso(monkeypatch, tam_con, tam_sin, vistos=None):
    def mapa(f, inst, b, c, corte):
        if vistos is not None:
            vistos.append((f, inst, b, c, corte))
        return f

    def texto(nombre, m, sin=()):
        return nombre + ":" + "x" * ((tam_sin if "anio" in sin else tam_con)(nombre) - len(nombre) - 1)
    monkeypatch.setattr(mmapa, "mapa", mapa)
    monkeypatch.setattr(mmapa, "texto", texto)


def _tres_variantes(con):
    for n, pf in ((1, 1.1), (2, 1.3), (3, 1.2)):
        _fila(con, ficha=_barras_hasta(BASE, n), pf=pf, motivo=f"m{n}")


def test_mapa_de_maps_base_and_best_variants_on_training_cut(con, monkeypatch):
    _tres_variantes(con)
    _fila(con, ficha=_barras_hasta(BASE, 9), pf=0.1, motivo="worst")
    vistos, pedidos = [], []
    _mapa_falso(monkeypatch, lambda n: 50, lambda n: 20, vistos)
    texto = lab.mapa_de(con, PROPIA, lambda i, t: pedidos.append((i, t)) or "BARS", lambda i: f"COSTS {i}")
    assert pedidos == [("US500", "M15")]
    assert [v[0] for v in vistos] == [BASE, _barras_hasta(BASE, 2), _barras_hasta(BASE, 3), _barras_hasta(BASE, 1)]
    assert all(v[1:] == ("US500", "BARS", "COSTS US500", "2023-01-01") for v in vistos)
    assert [l.split(":")[0] for l in texto.splitlines()] == ["base", "best variant 1", "best variant 2",
                                                             "best variant 3"]


def test_mapa_de_drops_variants_before_years(con, monkeypatch):
    _tres_variantes(con)
    _mapa_falso(monkeypatch, lambda n: 6000, lambda n: 100)
    texto = lab.mapa_de(con, PROPIA, lambda i, t: None, lambda i: None)
    assert len(texto.encode()) <= lab.MAX_BYTES_MAPA
    assert [l.split(":")[0] for l in texto.splitlines()] == ["base", "best variant 1", "best variant 2"]
    assert len(texto) == 3 * 6000 + 2


def test_mapa_de_drops_years_when_base_alone_does_not_fit(con, monkeypatch):
    _tres_variantes(con)
    _mapa_falso(monkeypatch, lambda n: 25_000, lambda n: 8000)
    texto = lab.mapa_de(con, PROPIA, lambda i, t: None, lambda i: None)
    assert [l.split(":")[0] for l in texto.splitlines()] == ["base", "best variant 1"]
    assert len(texto.encode()) == 2 * 8000 + 1 <= lab.MAX_BYTES_MAPA


def test_mapa_de_counts_bytes_not_characters(con, monkeypatch):
    monkeypatch.setattr(mmapa, "mapa", lambda *a: None)
    monkeypatch.setattr(mmapa, "texto", lambda n, m, sin=(): "ñ" * (12_000 if not sin else 100))
    texto = lab.mapa_de(con, PROPIA, lambda i, t: None, lambda i: None)
    assert texto == "ñ" * 100


def test_mapa_de_propagates_backtest_errors_to_the_caller(con, monkeypatch):
    def rompe(*a):
        raise ValueError("sin velas")
    monkeypatch.setattr(mmapa, "mapa", rompe)
    with pytest.raises(ValueError, match="sin velas"):
        lab.mapa_de(con, PROPIA, lambda i, t: None, lambda i: None)


def test_mapa_de_on_real_bars_only_counts_training_years(con, barras, costes_cero):
    rng = np.random.default_rng(7)
    c = 4000 + np.cumsum(rng.normal(0, 3, 8000))
    b = barras(c, open=np.r_[c[0], c[:-1]], inicio="2022-11-01T13:00", paso="15m")
    assert b["ts"][-1] > np.datetime64("2023-01-15")
    texto = lab.mapa_de(con, MANUAL, lambda i, t: b, lambda i: costes_cero())
    anio = next(l for l in texto.splitlines() if l.strip().startswith("anio:"))
    assert "2022" in anio and "2023" not in anio
    assert texto.startswith("base: ") and "trades, pf with costs" in texto


# --- contexto ---

def test_contexto_puts_map_then_direction_after_the_explored_summary(con):
    _direccion(con, "ejemplo", "Follow this.")
    texto = lab.contexto(con, PROPIA, BASE, mapa_texto="MAP BODY")
    i_exp = texto.index("## Already explored")
    i_map = texto.index("## Edge map (training data only)\nMAP BODY\n")
    i_dir = texto.index("## Direction from the weekly advisor (follow it)\nFollow this.\n")
    assert i_exp < i_map < i_dir and texto.endswith("Follow this.\n")


def test_contexto_without_map_or_direction_omits_both_headings(con):
    _direccion(con, "manual", "Not mine.")
    texto = lab.contexto(con, PROPIA, BASE, mapa_texto="")
    assert "Edge map" not in texto and "Direction from the weekly advisor" not in texto and "Not mine." not in texto


def test_contexto_with_map_and_direction_still_hides_exam_and_confirmation(con):
    eid = _fila(con, ficha=_barras_hasta(BASE, 5), veredicto="ganadora", pf=1.23, motivo="winner idea",
                examen={"profit_factor": 7.77, "rentabilidad": 0.4321}, confirmacion={"profit_factor": 8.88})
    con.execute("INSERT INTO lab_ganadoras (experimento_id, estrategia, estado, examen_json, confirmacion_json)"
                " VALUES (?, 'ejemplo', 'vigente', ?, ?)", (eid, '{"profit_factor": 6.66}', '{"profit_factor": 5.55}'))
    _direccion(con, "ejemplo", "Probe the stop.")
    texto = lab.contexto(con, PROPIA, BASE, mapa_texto="base: 10 trades")
    for prohibido in ("ganadora", "7.77", "8.88", "6.66", "5.55", "0.4321", "confirmacion", "examen", "lab_ganadoras"):
        assert prohibido not in texto.lower()
    assert '"veredicto": "pasa_validador"' in texto and "1.23" in texto and "winner idea" in texto


def test_contexto_history_is_capped_but_explored_counts_everything(con):
    for i in range(45):
        _fila(con, ficha=_barras_hasta(BASE, 100 + i), motivo=f"idea {i}")
    texto = lab.contexto(con, PROPIA, BASE)
    assert "## History (oldest first, 40 experiments)" in texto
    assert '"idea 4"' not in texto and '"idea 5"' in texto and '"idea 44"' in texto
    assert "all 45 experiments" in texto
    assert all(f"1x gestion.max_barras={100 + i}" in texto for i in range(45))


# --- _explorado / _cambios_vistos ---

def test_explorado_counts_each_change_once_per_experiment_most_used_first(con):
    doble = deepcopy(BASE)
    doble["gestion"]["stop"]["valor"] = 20
    doble["horario"]["dias"] = [1, 2]
    for k in range(3):
        _fila(con, ficha=doble, motivo=f"d{k}")
    _fila(con, ficha=_barras_hasta(BASE, 30), motivo="once")
    _fila(con, ficha=BASE, cambios=0, motivo="base")
    texto = lab._explorado(con, PROPIA, BASE)
    lineas = texto.splitlines()
    assert lineas[0] == "## Already explored (all 5 experiments: each change vs the base and how many used it)"
    assert sorted(lineas[1:3]) == ["3x gestion.stop.valor=20", "3x horario.dias=[1, 2]"]
    assert lineas[3:] == ["1x gestion.max_barras=30"]


def test_explorado_includes_invalid_experiments(con):
    mala = _barras_hasta(BASE, 12)
    mala["universo"]["plazo"] = "H1"
    _fila(con, ficha=mala, veredicto="invalido", cambios=None, entreno=None)
    assert "1x gestion.max_barras=12" in lab._explorado(con, PROPIA, BASE)


def test_explorado_is_per_strategy_and_says_none_yet(con):
    _fila(con, estrategia="manual", ficha=_barras_hasta(BASE_MANUAL, 77))
    texto = lab._explorado(con, PROPIA, BASE)
    assert texto == ("## Already explored (all 0 experiments: each change vs the base and how many used it)\n"
                     "(none yet)\n")
    assert "1x gestion.max_barras=77" in lab._explorado(con, MANUAL, BASE_MANUAL)


def test_cambios_vistos_lists_condition_edits_with_side(con):
    f = deepcopy(BASE)
    quitada = f["salida"]["largo"]["o"].pop(0)
    f["entrada"]["corto"]["y"].append({"<": ["close", 1]})
    vistos = lab._cambios_vistos(BASE, f)
    assert f"salida.largo -{lab._canon(quitada)}" in vistos
    assert 'entrada.corto +{"<": ["close", 1]}' in vistos
    assert len(vistos) == lab.cambios(BASE, f) == 2


@pytest.mark.parametrize("cierre, n, linea", [
    (None, 1, "horario.cierre=null"),
    ("16:00", 1, 'horario.cierre="16:00"'),
    ("15:55", 0, None),
])
def test_cierre_edits_on_the_manual_base(cierre, n, linea):
    f = deepcopy(BASE_MANUAL)
    if cierre is None:
        del f["horario"]["cierre"]
    else:
        f["horario"]["cierre"] = cierre
    assert lab.cambios(BASE_MANUAL, f) == n
    assert lab._cambios_vistos(BASE_MANUAL, f) == ([linea] if linea else [])


# --- ejecutar across both strategies ---

def _llamar_ambas(prompts, n=1):
    def llamar(modelo, system, prompt, **k):
        prompts.append(prompt)
        nombre = "manual" if "## Strategy\nmanual" in prompt else "ejemplo"
        base = propias.ficha_base(nombre)
        return json.dumps({"experimentos": [{"motivo": f"idea {nombre} {i}", "ficha": _barras_hasta(base, 40 + i)}
                                            for i in range(n)]})
    return llamar


def _ejecutar_ambas(con, monkeypatch, llamar, mapa=None, **kw):
    monkeypatch.setattr(lab, "mapa_de", mapa or (lambda con, propia, *a: f"MAP OF {propia.name}"))
    monkeypatch.setattr(lab, "evaluar", lambda *a: {"entreno": {"veredicto": "no_pasa", "criterios": [],
                                                               "metricas": {"total": {"profit_factor": 0.8}}},
                                                    "examen": None, "confirmacion": None})
    return lab.ejecutar(con, None, llamar, crit=CRIT, bars_of=lambda i, t: {"ts": np.array([], "datetime64[ns]")},
                        costes_of=lambda i: None, **kw)


def test_base_ficha_tested_once_per_strategy_across_batches(con, monkeypatch):
    prompts = []
    primera = _ejecutar_ambas(con, monkeypatch, _llamar_ambas(prompts), max_experimentos=4)
    segunda = _ejecutar_ambas(con, monkeypatch, _llamar_ambas(prompts), max_experimentos=4)
    filas = con.execute("SELECT estrategia, huella, motivo FROM lab_experimentos WHERE cambios = 0 ORDER BY id").fetchall()
    assert [(f["estrategia"], f["huella"]) for f in filas] == [("ejemplo", lab.huella(BASE)),
                                                               ("manual", lab.huella(BASE_MANUAL))]
    assert all(f["motivo"].startswith("Ficha base sin cambios") for f in filas)
    assert (primera["probados"], primera["repetidos"]) == (4, 0)
    assert (segunda["probados"], segunda["repetidos"]) == (0, 2)


def test_batch_splits_the_quota_between_both_strategies(con, monkeypatch):
    prompts = []
    out = _ejecutar_ambas(con, monkeypatch, _llamar_ambas(prompts, n=5), max_experimentos=4)
    assert len(prompts) == 2
    assert prompts[0].endswith("Propose up to 2 new experiments for ejemplo.")
    assert prompts[1].endswith("Propose up to 2 new experiments for manual.")
    assert out["propuestos"] == 4 and out["probados"] == 6
    por = dict(con.execute("SELECT estrategia, COUNT(*) FROM lab_experimentos WHERE motivo LIKE 'idea %'"
                           " GROUP BY estrategia").fetchall())
    assert por == {"ejemplo": 2, "manual": 2}


def test_quota_is_at_least_one_per_strategy(con, monkeypatch):
    prompts = []
    out = _ejecutar_ambas(con, monkeypatch, _llamar_ambas(prompts, n=3), max_experimentos=1)
    assert all(re.search(r"Propose up to 1 new experiments", p) for p in prompts) and out["propuestos"] == 2


def test_map_error_for_one_strategy_is_logged_and_the_batch_goes_on(con, monkeypatch):
    def mapa(con, propia, *a):
        if propia.name == "ejemplo":
            raise KeyError("ts")
        return "MANUAL MAP"
    prompts = []
    out = _ejecutar_ambas(con, monkeypatch, _llamar_ambas(prompts), mapa=mapa)
    assert out["errores"] == ["ejemplo: mapa: KeyError: 'ts'"] and out["errores_contenido"] == 1
    auto, manual = prompts
    assert "Edge map" not in auto
    assert "## Edge map (training data only)\nMANUAL MAP\n" in manual
    assert out["probados"] == 4


def test_each_strategy_prompt_gets_only_its_own_map_and_direction(con, monkeypatch):
    _direccion(con, "ejemplo", "Auto direction.")
    _direccion(con, "manual", "Manual direction.")
    prompts = []
    _ejecutar_ambas(con, monkeypatch, _llamar_ambas(prompts))
    auto, manual = prompts
    assert "MAP OF ejemplo\n" in auto and "MAP OF manual" not in auto
    assert "Auto direction." in auto and "Manual direction." not in auto
    assert "Manual direction." in manual and "Auto direction." not in manual
