import json
from copy import deepcopy

import numpy as np
import pytest

from quant import validacion
from quant.familias import propias
from quant.investigacion import catalogo
from quant.investigacion import laboratorio as lab

BASE = propias.ficha_base("ejemplo")


@pytest.fixture
def con():
    c = catalogo.abrir(":memory:")
    lab.ensure_schema(c)
    return c


def test_umbral_pf():
    assert lab.umbral_pf(0, 0) == 1.0 and lab.umbral_pf(3, 0) == pytest.approx(1.15)
    assert lab.umbral_pf(10, 0) == 1.3 and lab.umbral_pf(10, 20) == pytest.approx(1.4)
    assert lab.umbral_pf(2, 20) == pytest.approx(1.2)


def test_el_examen_se_endurece_con_cada_examen_hecho():
    assert lab.umbral_pf(0, 60) == pytest.approx(1.2) and lab.umbral_pf(0, 140) == pytest.approx(1.3)
    seguidos = [lab.umbral_pf(4, n) for n in range(0, 400)]
    assert all(b > a for a, b in zip(seguidos, seguidos[1:]))


def test_cambios():
    assert lab.cambios(BASE, BASE) == 0
    f = deepcopy(BASE)
    f["gestion"]["stop"]["valor"] = 24
    assert lab.cambios(BASE, f) == 1
    f["salida"]["largo"]["o"].append({">=": ["RSI(2)", 70]})
    assert lab.cambios(BASE, f) == 2
    f["horario"]["dias"] = [1, 2, 3]
    assert lab.cambios(BASE, f) == 3
    g = deepcopy(BASE)
    g["entrada"]["largo"]["y"][1] = {"<=": ["RSI(14)[1]", 40]}
    assert lab.cambios(BASE, g) == 1
    g["horario"]["sesiones"] = [{"desde": "09:15", "hasta": "11:00"}]
    assert lab.cambios(BASE, g) == 2


def test_huella_ignora_titulo_y_orden_de_claves():
    f = json.loads(json.dumps(BASE, sort_keys=False))
    f["titulo"] = "otro titulo"
    f["gestion"] = dict(reversed(list(f["gestion"].items())))
    assert lab.huella(f) == lab.huella(BASE)
    f["gestion"]["max_barras"] = 32
    assert lab.huella(f) != lab.huella(BASE)


@pytest.mark.parametrize("cambio, motivo", [
    (lambda f: f["universo"].update(instrumentos=["US100"]), "instrumento"),
    (lambda f: f["universo"].update(plazo="H1"), "plazo"),
    (lambda f: f.update(tipo="tendencia"), "tipo"),
    (lambda f: f["entrada"]["largo"]["y"].append({">": ["FOO(3)", 1]}), "indicador"),
    (lambda f: f["entrada"]["largo"]["y"].append({">": ["close[-1]", 1]}), "futuro"),
])
def test_comprobar_rechaza_fichas_que_cambian_el_terreno(cambio, motivo):
    f = deepcopy(BASE)
    cambio(f)
    assert any(motivo in m for m in lab.comprobar(BASE, f))


def test_comprobar_acepta_un_cambio_de_logica():
    f = deepcopy(BASE)
    f["salida"]["largo"]["o"] = [{">=": ["RSI(14)", 80]}]
    f["horario"]["dias"] = [1, 2, 3]
    assert lab.comprobar(BASE, f) == []


def test_ensure_schema_crea_las_tablas(con):
    tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lab_experimentos", "lab_ganadoras"} <= tablas


SIMPLE = {"id": "simple-x", "titulo": "simple", "fuente": {"url": "x://y", "cita": "c"}, "tipo": "otro",
          "forma": "serie_temporal", "universo": {"instrumentos": ["X"], "plazo": "D1"},
          "entrada": {"largo": {">": ["close", "close[1]"]}}, "salida": {"largo": {"<": ["close", "close[1]"]}},
          "gestion": {"tamano": {"tipo": "unidades", "valor": 1}}, "estado": "borrador"}


def _barras_diarias(barras, inicio="2021-01-01", n=1300):
    rng = np.random.default_rng(1)
    return barras(100 + np.cumsum(rng.normal(0, 1, n)), inicio=inicio, paso="1D")


def test_recortar_deja_solo_lo_anterior(barras):
    b = _barras_diarias(barras)
    r = lab.recortar(b, "2023-01-01")
    assert r["ts"].max() < np.datetime64("2023-01-01") and len(r["close"]) == len(r["ts"]) < len(b["ts"])


def test_el_validador_solo_ve_velas_anteriores_al_corte(barras, costes_cero, monkeypatch):
    visto = []

    def validar_falso(f, b, c, k):
        visto.append(b["X"]["ts"].max())
        return {"X": {"veredicto": "no_pasa"}}
    monkeypatch.setattr(validacion, "validar", validar_falso)
    out = lab.evaluar(SIMPLE, {"X": _barras_diarias(barras)}, {"X": costes_cero()}, {"capital": 5000},
                      "2023-01-01", "2024-01-01")
    assert visto[0] < np.datetime64("2023-01-01")
    assert out == {"entreno": {"veredicto": "no_pasa"}, "examen": None, "confirmacion": None}


def test_si_pasa_el_validador_se_examina_despues_del_corte(barras, costes_cero, monkeypatch):
    monkeypatch.setattr(validacion, "validar", lambda f, b, c, k: {"X": {"veredicto": "pasa"}})
    out = lab.evaluar(SIMPLE, {"X": _barras_diarias(barras)}, {"X": costes_cero()}, {"capital": 5000},
                      "2023-01-01", "2024-01-01")
    assert out["examen"]["operaciones"] > out["confirmacion"]["operaciones"] > 0


def test_metricas_desde_solo_cuentan_operaciones_del_tramo(barras, costes_cero):
    b = _barras_diarias(barras)
    from quant import motor
    todas = motor.backtest_serie(SIMPLE, "X", b, costes_cero(), 5000).operaciones
    corte = np.datetime64("2023-01-01")
    esperadas = sum(b["ts"][o.i_entrada] >= corte for o in todas)
    m = lab.metricas_desde(SIMPLE, "X", b, costes_cero(), 5000, "2023-01-01")
    assert m["operaciones"] == esperadas and 0 < esperadas < len(todas)
    assert lab.metricas_desde(SIMPLE, "X", b, costes_cero(), 5000, "2030-01-01") is None


def test_examen_sin_operaciones_suspende_con_motivo():
    assert lab.pasa_examen({"operaciones": 0, "rentabilidad": 0.0, "drawdown": 0.0, "profit_factor": 0.0},
                           1.0, 0.2) == (False, "sin operaciones en el examen")
    assert lab.pasa_examen(None, 1.0, 0.2) == (False, "sin datos en el examen")
    bueno = {"operaciones": 40, "rentabilidad": 0.1, "drawdown": 0.1, "profit_factor": 1.2}
    assert lab.pasa_examen(bueno, 1.15, 0.2) == (True, "")
    assert lab.pasa_examen({**bueno, "profit_factor": 1.14}, 1.15, 0.2)[0] is False
    assert lab.pasa_examen({**bueno, "operaciones": 29}, 1.0, 0.2)[0] is False
    assert lab.pasa_examen({**bueno, "drawdown": 0.21}, 1.0, 0.2)[0] is False
    assert lab.pasa_examen({**bueno, "rentabilidad": -0.01}, 1.0, 0.2)[0] is False


PROPIA = propias.PROPIAS["ejemplo"]


def _experimento(con, veredicto, ficha=None, examen=None, motivo="m", entreno=None):
    f = ficha or BASE
    cur = con.execute(
        "INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, entreno_json,"
        " examen_json, umbral_pf, creado) VALUES ('ejemplo', '2026-11-04', ?, ?, ?, 1, ?, ?, ?, 1.05, 'x')",
        (lab.huella(f) + motivo, json.dumps(f), motivo, veredicto,
         json.dumps(entreno or {"veredicto": "pasa", "criterios": [], "metricas": {"total": {"profit_factor": 1.11}}}),
         json.dumps(examen) if examen else None))
    con.commit()
    return cur.lastrowid


def test_el_contexto_no_filtra_el_examen(con):
    eid = _experimento(con, "ganadora", examen={"profit_factor": 1.77}, motivo="stop mas ancho")
    con.execute("INSERT INTO lab_ganadoras (experimento_id, estrategia, estado, examen_json) VALUES (?, 'ejemplo',"
                " 'vigente', ?)", (eid, json.dumps({"profit_factor": 1.88})))
    _experimento(con, "invalido", motivo="usa FOO")
    texto = lab.contexto(con, PROPIA, BASE)
    assert "ganadora" not in texto and "1.77" not in texto and "1.88" not in texto
    assert "examen" not in texto.lower() and "1.05" not in texto
    assert "pasa_validador" in texto and "stop mas ancho" in texto and "1.11" in texto and "usa FOO" in texto


def test_el_contexto_resume_lo_probado_fuera_de_la_ventana(con):
    viejo = deepcopy(BASE)
    viejo["gestion"]["stop"]["valor"] = 99
    _experimento(con, "no_pasa", ficha=viejo, motivo="stop enorme")
    for i in range(3):
        _experimento(con, "no_pasa", motivo=f"reciente {i}")
    texto = lab.contexto(con, PROPIA, BASE, limite=2)
    assert "stop enorme" not in texto
    assert "1x gestion.stop.valor=99" in texto and "4 experiments" in texto


def test_proponer_aguanta_respuestas_rotas():
    lista, error = lab.proponer(lambda *a, **k: "no es json", PROPIA, "ctx", 10)
    assert lista == [] and error
    doce = {"experimentos": [{"motivo": f"m{i}", "ficha": BASE} for i in range(12)] + [{"motivo": 3}]}
    lista, error = lab.proponer(lambda *a, **k: json.dumps(doce), PROPIA, "ctx", 10)
    assert len(lista) == 10 and error and "1" in error and lista[0] == {"motivo": "m0", "ficha": BASE}
    lista, error = lab.proponer(lambda *a, **k: json.dumps({"experimentos": [{"motivo": 3}, "x"]}), PROPIA, "ctx", 10)
    assert lista == [] and error


def test_proponer_si_la_llamada_falla_devuelve_el_error():
    def falla(*a, **k):
        raise RuntimeError("limite de uso")
    assert lab.proponer(falla, PROPIA, "ctx", 10) == ([], "RuntimeError: limite de uso")


def test_proponer_pide_sonnet_con_la_skill_del_laboratorio():
    vistos = []
    lab.proponer(lambda *a, **k: vistos.append((a, k)) or '{"experimentos": []}', PROPIA, "CTX", 4)
    (modelo, system, prompt), k = vistos[0]
    assert modelo == "sonnet" and k["formato"] == "json" and "CTX" in prompt and "4" in prompt
    assert "experimentos" in system


CRIT = {"capital": 5000, "drawdown_max": 0.2}
BUENO = {"operaciones": 40, "rentabilidad": 0.1, "drawdown": 0.1, "profit_factor": 1.5}
MALO = {**BUENO, "profit_factor": 0.8}


def _variante(n):
    f = deepcopy(BASE)
    f["gestion"]["max_barras"] = 64 + n
    return f


def _correr(con, monkeypatch, propuestas, veredicto="pasa", examen=BUENO, con_base=True, mapa=None, **kw):
    monkeypatch.setattr(lab, "mapa_de", mapa or (lambda *a, **k: ""))
    if con_base and not con.execute("SELECT 1 FROM lab_experimentos WHERE huella = ?", (lab.huella(BASE),)).fetchone():
        _experimento(con, "no_pasa", motivo="")
    monkeypatch.setattr(lab, "evaluar", lambda f, b, c, k, corte, conf: {
        "entreno": {"veredicto": veredicto, "criterios": [], "metricas": {"total": {"profit_factor": 1.2}}},
        "examen": examen if veredicto == "pasa" else None, "confirmacion": examen if veredicto == "pasa" else None})
    monkeypatch.setattr(lab, "simular_ayer", lambda *a: {"fecha": "2026-11-03", "operaciones": []})
    monkeypatch.setattr(propias, "PROPIAS", {"ejemplo": PROPIA})
    llamar = kw.pop("llamar", lambda *a, **k: json.dumps({"experimentos": propuestas}))
    return lab.ejecutar(con, None, llamar, crit=CRIT, bars_of=lambda i, t: {"ts": np.array([], "datetime64[ns]")},
                        costes_of=lambda i: None, **kw)


def test_registra_invalidos_repetidos_y_probados(con, monkeypatch):
    malo = deepcopy(BASE)
    malo["universo"]["plazo"] = "H1"
    propuestas = [{"motivo": "otro plazo", "ficha": malo}, {"motivo": "a", "ficha": _variante(1)},
                  {"motivo": "a otra vez", "ficha": _variante(1)}, {"motivo": "b", "ficha": _variante(2)}]
    out = _correr(con, monkeypatch, propuestas, veredicto="no_pasa")
    assert (out["propuestos"], out["invalidos"], out["repetidos"], out["probados"]) == (4, 1, 1, 2)
    filas = con.execute("SELECT motivo, veredicto, invalido, cambios FROM lab_experimentos WHERE motivo != ''"
                        " ORDER BY id").fetchall()
    assert [(f["motivo"], f["veredicto"]) for f in filas] == [("otro plazo", "invalido"), ("a", "no_pasa"),
                                                               ("b", "no_pasa")]
    assert "plazo" in filas[0]["invalido"] and filas[1]["cambios"] == 1


def test_fija_ganadora_y_la_retira_cuando_suspende(con, monkeypatch):
    out = _correr(con, monkeypatch, [{"motivo": "a", "ficha": _variante(1)}])
    assert out["ganadoras"] == 1
    g = con.execute("SELECT * FROM lab_ganadoras").fetchone()
    assert g["estado"] == "vigente" and g["umbral_pf"] == pytest.approx(1.05)
    assert con.execute("SELECT veredicto FROM lab_experimentos WHERE motivo != ''").fetchone()[0] == "ganadora"
    monkeypatch.setattr(lab, "metricas_desde", lambda *a: MALO)
    out = _correr(con, monkeypatch, [])
    g = con.execute("SELECT * FROM lab_ganadoras").fetchone()
    assert (out["reexaminadas"], out["retiradas"], out["simuladas"]) == (1, 1, 1)
    assert g["estado"] == "retirada" and "profit factor 0,80" in g["motivo_retiro"] and g["ayer_json"]


def test_pasa_validador_pero_no_el_examen(con, monkeypatch):
    out = _correr(con, monkeypatch, [{"motivo": "a", "ficha": _variante(1)}], examen=MALO)
    assert out["ganadoras"] == 0
    assert con.execute("SELECT veredicto FROM lab_experimentos WHERE motivo != ''").fetchone()[0] == "pasa_validador"


def test_sin_tiempo_corta_experimentos_pero_reexamina(con, monkeypatch):
    _correr(con, monkeypatch, [{"motivo": "a", "ficha": _variante(1)}])
    monkeypatch.setattr(lab, "metricas_desde", lambda *a: BUENO)
    out = _correr(con, monkeypatch, [{"motivo": "b", "ficha": _variante(2)}, {"motivo": "c", "ficha": _variante(3)}],
                  hasta=100, reloj=lambda: 99)
    assert out["reexaminadas"] == 1 and out["probados"] == 0 and out["sin_tiempo"] >= 1


def test_el_agente_falla_y_la_etapa_sigue(con, monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("limite de uso")
    out = _correr(con, monkeypatch, [], llamar=falla)
    assert out["probados"] == 0 and any("limite de uso" in e for e in out["errores"])


def test_simular_ayer_lista_las_operaciones_del_ultimo_dia(barras, costes_cero):
    b = barras([100, 101, 102, 101, 103, 104, 103, 105], inicio="2024-01-01T00:00", paso="6h")
    out = lab.simular_ayer(SIMPLE, "X", b, costes_cero(), 5000)
    assert out["fecha"] == "2024-01-02"
    assert out["operaciones"] and all(o["entrada"].startswith("2024-01-02") for o in out["operaciones"])


def test_fix_una_invalida_no_bloquea_su_version_corregida(con, monkeypatch):
    mala = _variante(5)
    mala["tipo"] = "tendencia"
    _correr(con, monkeypatch, [{"motivo": "tipo cambiado", "ficha": mala}], veredicto="no_pasa")
    out = _correr(con, monkeypatch, [{"motivo": "corregida", "ficha": _variante(5)}], veredicto="no_pasa")
    assert (out["repetidos"], out["probados"]) == (0, 1)


def test_fix_no_se_puede_cambiar_el_tamano_de_posicion():
    f = deepcopy(BASE)
    f["gestion"]["tamano"]["valor"] = 0.05
    assert any("tamaño" in m for m in lab.comprobar(BASE, f))


def test_fix_cambiar_y_por_o_cuenta_como_cambio():
    f = deepcopy(BASE)
    f["entrada"]["largo"] = {"o": f["entrada"]["largo"]["y"]}
    assert lab.cambios(BASE, f) == 1


def test_fix_sin_tiempo_no_llama_al_agente(con, monkeypatch):
    llamadas = []
    out = _correr(con, monkeypatch, [], llamar=lambda *a, **k: llamadas.append(1) or '{"experimentos": []}',
                  hasta=1000, reloj=lambda: 300)
    assert llamadas == [] and out["sin_tiempo"] >= 1


def test_fix_los_fallos_del_agente_se_cuentan_para_el_diagnostico(con, monkeypatch):
    out = _correr(con, monkeypatch, [], llamar=lambda *a, **k: "no es json")
    assert out["errores_contenido"] == 1


def test_fix_proponer_avisa_si_la_forma_es_otra_o_descarta_elementos():
    assert lab.proponer(lambda *a, **k: '{"experiments": []}', PROPIA, "ctx", 10)[1]
    lista, error = lab.proponer(lambda *a, **k: json.dumps({"experimentos": [{"motivo": 3}, {"motivo": "a", "ficha": BASE}]}),
                                PROPIA, "ctx", 10)
    assert len(lista) == 1 and "1" in error


def test_fix_la_simulacion_que_falla_no_impide_retirar(con, monkeypatch):
    _correr(con, monkeypatch, [{"motivo": "a", "ficha": _variante(1)}])
    monkeypatch.setattr(lab, "metricas_desde", lambda *a: None)

    def rompe(*a):
        raise IndexError("sin velas")
    monkeypatch.setattr(lab, "simular_ayer", rompe)
    monkeypatch.setattr(lab, "evaluar", lambda *a: {"entreno": {"veredicto": "no_pasa"}, "examen": None, "confirmacion": None})
    monkeypatch.setattr(propias, "PROPIAS", {"ejemplo": PROPIA})
    out = lab.ejecutar(con, None, lambda *a, **k: '{"experimentos": []}', crit=CRIT,
                       bars_of=lambda i, t: {"ts": np.array([], "datetime64[ns]")}, costes_of=lambda i: None)
    assert con.execute("SELECT estado FROM lab_ganadoras").fetchone()[0] == "retirada" and out["retiradas"] == 1


def test_fix_simular_ayer_usa_el_ultimo_dia_completo(barras, costes_cero):
    b = barras([100, 101, 102, 101, 103, 104, 103, 105, 106], inicio="2024-01-01T00:00", paso="6h")
    out = lab.simular_ayer(SIMPLE, "X", b, costes_cero(), 5000, antes="2024-01-03")
    assert out["fecha"] == "2024-01-02"


class _Reloj:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def _tanda_falsa(reloj, salidas, vistos):
    def ejecutar(con, raiz, llamar, hasta=None, reloj=None, reexaminar=True, **kw):
        vistos.append(reexaminar)
        salida = salidas.pop(0) if salidas else {"propuestos": 10, "probados": 10}
        if isinstance(salida, BaseException):
            raise salida
        reloj_ext.t += 720
        return {"reexaminadas": 0, "retiradas": 0, "simuladas": 0, "propuestos": 0, "invalidos": 0, "repetidos": 0,
                "probados": 0, "ganadoras": 0, "sin_tiempo": 0, "errores": [], **salida}
    reloj_ext = reloj
    return ejecutar


def test_tandas_repite_hasta_la_hora_limite_sin_empezar_una_que_no_cabe(monkeypatch):
    reloj, vistos = _Reloj(), []
    monkeypatch.setattr(lab, "ejecutar", _tanda_falsa(reloj, [], vistos))
    out = lab.tandas(None, None, None, hasta=3 * 3600, reloj=reloj)
    # 12 min per batch, no batch starts with less than 13 min left: 3 h fit 14 batches.
    assert out["tandas"] == 14 and out["probados"] == 140
    assert vistos[0] is True and not any(vistos[1:])
    assert reloj.t <= 3 * 3600


def test_tandas_para_en_el_tope_de_la_noche(monkeypatch):
    reloj, vistos = _Reloj(), []
    monkeypatch.setattr(lab, "ejecutar", _tanda_falsa(reloj, [], vistos))
    out = lab.tandas(None, None, None, hasta=10 * 3600, reloj=reloj)
    assert out["tandas"] == lab.TANDAS_MAX == 15 and out["parado"] == "tope de 15 tandas por noche"


def test_una_tanda_que_revienta_no_para_las_demas(monkeypatch):
    reloj, vistos = _Reloj(), []
    monkeypatch.setattr(lab, "ejecutar", _tanda_falsa(reloj, [MemoryError("sin memoria")], vistos))
    out = lab.tandas(None, None, None, hasta=2 * 3600, reloj=reloj)
    assert out["fallidas"] == 1 and out["probados"] > 0
    assert any("MemoryError" in e for e in out["errores"]) and out["errores_contenido"] == len(out["errores"])
    assert "error" not in out


def test_tres_tandas_seguidas_sin_probar_nada_paran_el_laboratorio(monkeypatch):
    reloj, vistos = _Reloj(), []
    vacia = {"propuestos": 0, "probados": 0, "errores": ["ejemplo: el agente no responde"]}
    monkeypatch.setattr(lab, "ejecutar", _tanda_falsa(reloj, [dict(vacia), dict(vacia), dict(vacia)], vistos))
    out = lab.tandas(None, None, None, hasta=4 * 3600, reloj=reloj)
    assert out["tandas"] == 3 and "parado" in out


def test_el_corte_de_claude_para_las_tandas_y_guarda_lo_hecho(monkeypatch):
    from quant.investigacion import claude_cli
    reloj, vistos = _Reloj(), []
    monkeypatch.setattr(lab, "ejecutar", _tanda_falsa(reloj, [{"probados": 10}, claude_cli.CorteClaude("tope")], vistos))
    out = lab.tandas(None, None, None, hasta=4 * 3600, reloj=reloj)
    assert out["tandas"] == 1 and out["probados"] == 10 and out["corte"] == "tope"


def test_cambios_cuenta_el_cierre():
    f = deepcopy(BASE)
    f["horario"]["cierre"] = "15:45"
    assert lab.cambios(BASE, f) == 1
    assert "horario.cierre=\"15:45\"" in lab._cambios_vistos(BASE, f)


def test_la_ficha_base_se_prueba_una_sola_vez(con, monkeypatch):
    _correr(con, monkeypatch, [], veredicto="no_pasa", con_base=False)
    _correr(con, monkeypatch, [], veredicto="no_pasa", con_base=False)
    filas = con.execute("SELECT cambios, huella FROM lab_experimentos").fetchall()
    assert [(f["cambios"], f["huella"]) for f in filas] == [(0, lab.huella(BASE))]


def _direccion(con, estrategia, texto, fecha="2026-11-15"):
    con.execute("INSERT INTO lab_asesor (estrategia, fecha, informe, direccion, direccion_es, propuestas_json, creado)"
                " VALUES (?, ?, 'informe', ?, 'es', '[]', 'x')", (estrategia, fecha, texto))
    con.commit()


def test_contexto_incluye_mapa_y_direccion(con):
    _direccion(con, "ejemplo", "Old idea", "2026-11-08")
    _direccion(con, "ejemplo", "Try slower Hull")
    texto = lab.contexto(con, PROPIA, BASE, mapa_texto="MAPA X")
    assert "## Edge map (training data only)" in texto and "MAPA X" in texto
    assert "## Direction from the weekly advisor" in texto and "Try slower Hull" in texto and "Old idea" not in texto
    assert lab.direccion_vigente(con, "ejemplo") == "Try slower Hull"


def test_contexto_sin_asesor(con):
    texto = lab.contexto(con, PROPIA, BASE)
    assert "Direction from the weekly advisor" not in texto and lab.direccion_vigente(con, "ejemplo") is None


def test_mapa_que_falla_no_para_el_laboratorio(con, monkeypatch):
    def rompe(*a, **k):
        raise ValueError("sin velas")
    out = _correr(con, monkeypatch, [{"motivo": "a", "ficha": _variante(1)}], veredicto="no_pasa", mapa=rompe)
    assert any("mapa" in e for e in out["errores"]) and out["probados"] == 1


def test_mejores_saca_las_de_mas_profit_factor(con):
    for pf, n in ((0.7, 1), (1.1, 2), (0.9, 3), (1.3, 4)):
        _experimento(con, "no_pasa", ficha=_variante(n), motivo=f"m{n}",
                     entreno={"veredicto": "no_pasa", "metricas": {"total": {"profit_factor": pf}}})
    _experimento(con, "invalido", ficha=_variante(9), motivo="inv",
                 entreno={"metricas": {"total": {"profit_factor": 9}}})
    assert [f["gestion"]["max_barras"] for f in lab.mejores(con, "ejemplo")] == [68, 66, 67]


def test_tanda_con_dos_estrategias_ve_mapa_y_direccion(con, monkeypatch, barras, costes_cero):
    rng = np.random.default_rng(5)
    c = 4000 + np.cumsum(rng.normal(0, 3, 3000))
    b = barras(c, open=np.r_[c[0], c[:-1]], inicio="2022-06-01T13:00", paso="15m")
    _direccion(con, "manual", "Widen the stop.")
    _experimento(con, "no_pasa", motivo="")
    prompts = []

    def llamar(modelo, system, prompt, **k):
        prompts.append(prompt)
        nombre = "manual" if "Strategy\nmanual" in prompt else "ejemplo"
        f = deepcopy(propias.ficha_base(nombre))
        f["gestion"]["max_barras"] = 40
        return json.dumps({"experimentos": [{"motivo": f"idea {nombre}", "ficha": f}]})
    monkeypatch.setattr(lab, "evaluar", lambda *a: {"entreno": {"veredicto": "no_pasa", "criterios": [],
                                                               "metricas": {"total": {"profit_factor": 0.8}}},
                                                    "examen": None, "confirmacion": None})
    out = lab.ejecutar(con, None, llamar, crit=CRIT, bars_of=lambda i, t: b, costes_of=lambda i: costes_cero(),
                       max_experimentos=4)
    assert out["errores"] == [] and len(prompts) == 2
    assert all("## Edge map (training data only)" in p and "trades, pf with costs" in p for p in prompts)
    manual = next(p for p in prompts if "Strategy\nmanual" in p)
    assert "Widen the stop." in manual
    estrategias = {r[0] for r in con.execute("SELECT estrategia FROM lab_experimentos WHERE motivo LIKE 'idea %'")}
    assert estrategias == {"ejemplo", "manual"}
