import copy
import json

import pytest

from quant.investigacion import agentes, catalogo, local

EXTRACTO = {"operable": "si", "tipo": "reversion", "mercado": ["accion"], "plazo": "D1",
            "extracto": "Compramos cuando el RSI(2) cae por debajo de 10 y vendemos al superar la SMA(5).",
            "prometido": {"sharpe": 1.2, "cita": "tabla 3"}, "alarmas": []}

FICHA = {"id": "rsi2-spy", "titulo": "RSI(2) en SPY", "fuente": {"url": "x://y", "cita": "tabla 3"},
         "tipo": "reversion", "forma": "serie_temporal",
         "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
         "entrada": {"largo": {"<": ["RSI(2)", 10]}}, "salida": {"largo": {">": ["close", "SMA(5)"]}},
         "gestion": {"stop": {"tipo": "atr", "valor": 3}}, "estado": "borrador"}


def _llamar(respuestas):
    guardadas = list(respuestas)
    enviados = []

    def llamar(modelo, system, prompt, **kw):
        enviados.append(prompt)
        return guardadas.pop(0)
    llamar.enviados = enviados
    return llamar


def test_formalizar_corrige_ficha_invalida():
    mala = copy.deepcopy(FICHA)
    mala["entrada"]["largo"] = {"<": ["RSI(2)[-1]", 10]}
    llamar = _llamar([json.dumps({"expresable": True, "ficha": mala}),
                      json.dumps({"expresable": True, "ficha": FICHA})])
    salida = agentes.formalizar(EXTRACTO, {"url": "x://y", "cita": "tabla 3"}, llamar=llamar)
    assert salida["expresable"] and salida["ficha"]["id"] == "rsi2-spy"
    assert "futuro" in llamar.enviados[1]
    with pytest.raises(agentes.ErrorAgente):
        agentes.formalizar(EXTRACTO, {"url": "x://y", "cita": "c"},
                           llamar=_llamar([json.dumps({"expresable": True, "ficha": mala})] * 2))


def test_formalizar_inyecta_fuente_y_estado():
    sin_fuente = {k: v for k, v in FICHA.items() if k not in ("fuente", "estado")}
    salida = agentes.formalizar(EXTRACTO, {"url": "u://1", "cita": "p2"},
                                llamar=_llamar([json.dumps({"expresable": True, "ficha": sin_fuente})]))
    assert salida["ficha"]["fuente"] == {"url": "u://1", "cita": "p2"}
    assert salida["ficha"]["estado"] == "borrador"


def test_no_expresable():
    salida = agentes.formalizar(EXTRACTO, {"url": "u", "cita": "c"},
                                llamar=_llamar([json.dumps({"expresable": False, "motivo": "usa otra temporalidad"})]))
    assert not salida["expresable"] and salida["ficha"] is None and "temporalidad" in salida["motivo"]


def test_criticar():
    salida = agentes.criticar(FICHA, EXTRACTO, llamar=_llamar([json.dumps({"veredicto": "devolver",
                                                                          "motivos": ["falta el stop"]})]))
    assert salida["veredicto"] == "devolver" and salida["motivos"] == ["falta el stop"]
    with pytest.raises(agentes.ErrorAgente):
        agentes.criticar(FICHA, EXTRACTO, llamar=_llamar([json.dumps({"veredicto": "quiza"})] * 2))


def test_criticar_veredicto_como_lista_reintenta():
    llamar = _llamar([json.dumps({"veredicto": ["aprobada", "devolver"], "motivos": []}),
                      json.dumps({"veredicto": "aprobada", "motivos": []})])
    salida = agentes.criticar(FICHA, EXTRACTO, llamar=llamar)
    assert salida["veredicto"] == "aprobada" and len(llamar.enviados) == 2


def test_formalizar_ficha_ilegible_para_el_validador(monkeypatch):
    def revienta(datos):
        raise TypeError("boom")

    monkeypatch.setattr(agentes.mficha, "errores", revienta)
    llamar = _llamar([json.dumps({"expresable": True, "ficha": FICHA})] * 2)
    with pytest.raises(agentes.ErrorAgente) as exc:
        agentes.formalizar(EXTRACTO, {"url": "x://y", "cita": "c"}, llamar=llamar)
    assert "ficha ilegible" in str(exc.value) and len(llamar.enviados) == 2


def test_prompts_no_llevan_avisos_salida():
    extracto = {**EXTRACTO, "avisos_salida": ["plazo normalizado: 'daily' -> 'D1'"]}
    llamar = _llamar([json.dumps({"expresable": True, "ficha": FICHA})])
    agentes.formalizar(extracto, {"url": "x://y", "cita": "c"}, llamar=llamar)
    assert "avisos_salida" not in llamar.enviados[0] and "plazo normalizado" not in llamar.enviados[0]

    critico = _llamar([json.dumps({"veredicto": "aprobada", "motivos": []})])
    agentes.criticar(FICHA, extracto, llamar=critico)
    assert "avisos_salida" not in critico.enviados[0] and "plazo normalizado" not in critico.enviados[0]


def test_los_prompts_vallan_el_contenido_externo():
    llamar = _llamar([json.dumps({"expresable": True, "ficha": FICHA})])
    agentes.formalizar(EXTRACTO, {"url": "x://y", "cita": "c"}, llamar=llamar)
    assert "<<<DOCUMENTO" in llamar.enviados[0] and "DOCUMENTO>>>" in llamar.enviados[0]
    critico = _llamar([json.dumps({"veredicto": "aprobada", "motivos": []})])
    agentes.criticar(FICHA, EXTRACTO, llamar=critico)
    assert critico.enviados[0].count("<<<DOCUMENTO") == 2
    assert critico.enviados[0].startswith("Ficha:") and "\nExtracto:\n" in critico.enviados[0]


def test_procesar_fichas_vuelta_del_critico(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    doc = catalogo.anadir_documento(con, "arxiv", "u://1", "T1", "2026-01-01", "texto", tmp_path)
    catalogo.guardar_extracto(con, doc, EXTRACTO)
    catalogo.marcar(con, doc, "leido")
    llamar = _llamar([json.dumps({"expresable": True, "ficha": FICHA}),
                      json.dumps({"veredicto": "devolver", "motivos": ["el stop no esta en el texto"]}),
                      json.dumps({"expresable": True, "ficha": {**FICHA, "gestion": {}}}),
                      json.dumps({"veredicto": "aprobada", "motivos": []})])
    resumen = agentes.procesar_fichas(con, llamar=llamar)
    assert resumen["aprobadas"] == 1
    assert "el stop no esta en el texto" in llamar.enviados[2]
    assert [f["estado"] for f in catalogo.fichas(con)] == ["aprobada"]
    assert [r["id"] for r in catalogo.pendientes(con, "criticado")] == [doc]


def test_procesar_fichas_rechazo_y_no_expresable(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    uno = catalogo.anadir_documento(con, "arxiv", "u://1", "T1", "2026-01-01", "a", tmp_path)
    dos = catalogo.anadir_documento(con, "arxiv", "u://2", "T2", "2026-01-01", "b", tmp_path)
    for d in (uno, dos):
        catalogo.guardar_extracto(con, d, EXTRACTO)
        catalogo.marcar(con, d, "leido")
    llamar = _llamar([json.dumps({"expresable": True, "ficha": FICHA}),
                      json.dumps({"veredicto": "rechazada", "motivos": ["inventa reglas"]}),
                      json.dumps({"expresable": False, "motivo": "no cabe en el esquema"})])
    resumen = agentes.procesar_fichas(con, llamar=llamar)
    assert (resumen["rechazadas"], resumen["no_expresables"]) == (1, 1)
    assert sorted(f["estado"] for f in catalogo.fichas(con)) == ["no_expresable", "rechazada"]
    assert [r["id"] for r in catalogo.pendientes(con, "no_expresable")] == [dos]


def _doc_leido(con, tmp_path, i=0):
    doc = catalogo.anadir_documento(con, "arxiv", f"u://{i}", f"T{i}", "2026-01-01", f"texto {i}", tmp_path)
    catalogo.guardar_extracto(con, doc, EXTRACTO)
    catalogo.marcar(con, doc, "leido")
    return doc


def _llamar_roto(*a, **kw):
    raise local.ErrorModelo("ollama no responde")


def test_procesar_fichas_sobrevive_a_un_fallo_del_modelo(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    doc = _doc_leido(con, tmp_path)
    resumen = agentes.procesar_fichas(con, llamar=_llamar_roto)
    assert resumen == {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 1,
                       "errores_contenido": 0, "errores_infra": 1, "omitidos": 0, "agotados": 0}
    fila = con.execute("SELECT etapa, intentos FROM documentos WHERE id = ?", (doc,)).fetchone()
    assert (fila["etapa"], fila["intentos"]) == ("leido", 1)


def test_procesar_fichas_agota_los_intentos(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    doc = _doc_leido(con, tmp_path)
    for _ in range(2):
        assert agentes.procesar_fichas(con, llamar=_llamar_roto)["agotados"] == 0
    resumen = agentes.procesar_fichas(con, llamar=_llamar_roto)
    assert (resumen["errores"], resumen["agotados"]) == (1, 1)
    fila = con.execute("SELECT etapa, intentos FROM documentos WHERE id = ?", (doc,)).fetchone()
    assert (fila["etapa"], fila["intentos"]) == ("error", 3)


def test_procesar_fichas_para_si_antes_devuelve_motivo(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    for i in range(3):
        d = catalogo.anadir_documento(con, "arxiv", f"u://{i}", f"T{i}", "2026-01-01", f"texto {i}", tmp_path)
        catalogo.guardar_extracto(con, d, EXTRACTO)
        catalogo.marcar(con, d, "leido")
    llamadas = []

    def antes():
        llamadas.append(1)
        return "" if len(llamadas) == 1 else "ocupado"

    llamar = _llamar([json.dumps({"expresable": True, "ficha": FICHA}),
                      json.dumps({"veredicto": "aprobada", "motivos": []})])
    resumen = agentes.procesar_fichas(con, llamar=llamar, antes=antes)
    assert resumen["aprobadas"] == 1 and resumen["omitidos"] == 2


def test_ficha_rechaza_claves_extra_por_eso_los_avisos_van_fuera():
    from quant import ficha as mficha
    assert mficha.errores({**FICHA, "avisos_salida": ["x"]})


def test_formalizar_devuelve_los_avisos_de_salida_fuera_de_la_ficha():
    llamar = _llamar([json.dumps({"expresable": "true", "ficha": FICHA})])
    salida = agentes.formalizar(EXTRACTO, {"url": "x://y", "cita": "tabla 3"}, llamar=llamar)
    assert salida["avisos_salida"] == ["expresable: texto tomado como booleano"]
    assert "avisos_salida" not in salida["ficha"]
    limpia = agentes.formalizar(EXTRACTO, {"url": "x://y", "cita": "tabla 3"},
                                llamar=_llamar([json.dumps({"expresable": True, "ficha": FICHA})]))
    assert "avisos_salida" not in limpia


def test_procesar_fichas_conserva_los_avisos_del_formalizador_fuera_del_prompt(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    doc = catalogo.anadir_documento(con, "arxiv", "u://1", "T1", "2026-01-01", "texto", tmp_path)
    catalogo.guardar_extracto(con, doc, EXTRACTO)
    catalogo.marcar(con, doc, "leido")
    llamar = _llamar([json.dumps({"expresable": "true", "ficha": FICHA}),
                      json.dumps({"veredicto": "devolver", "motivos": ["otra vuelta"]}),
                      json.dumps({"expresable": True, "ficha": FICHA}),
                      json.dumps({"veredicto": "aprobada", "motivos": []})])
    assert agentes.procesar_fichas(con, llamar=llamar)["aprobadas"] == 1
    assert all("texto tomado como booleano" not in p and "avisos_" not in p for p in llamar.enviados)
    assert catalogo.extracto(con, doc)["avisos_formalizador"] == ["expresable: texto tomado como booleano"]
    ficha = json.loads(catalogo.fichas(con)[0]["json"])
    assert "avisos_salida" not in ficha and "avisos_formalizador" not in ficha


def test_procesar_fichas_sobrevive_a_un_fallo_inesperado(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    docs = [_doc_leido(con, tmp_path, i) for i in range(2)]
    llamadas = []

    def llamar(*a, **kw):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise TypeError("cannot use 'list' as a set element")
        raise local.ErrorModelo("ollama no responde")

    resumen = agentes.procesar_fichas(con, llamar=llamar)
    assert resumen["errores"] == 2 and resumen["errores_infra"] == 2 and len(llamadas) == 2
    fila = con.execute("SELECT etapa, error FROM documentos WHERE id = ?", (docs[0],)).fetchone()
    assert fila["etapa"] == "leido" and fila["error"].startswith("TypeError: ")


def test_procesar_fichas_ficha_invalida_tras_reintento_cuenta_como_error_de_contenido(tmp_path):
    con = catalogo.abrir(tmp_path / "c.db")
    _doc_leido(con, tmp_path)
    mala = copy.deepcopy(FICHA)
    mala["entrada"]["largo"] = {"<": ["RSI(2)[-1]", 10]}
    llamar = _llamar([json.dumps({"expresable": True, "ficha": mala})] * 2)
    resumen = agentes.procesar_fichas(con, llamar=llamar)
    assert resumen == {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 1,
                       "errores_contenido": 1, "errores_infra": 0, "omitidos": 0, "agotados": 0}
