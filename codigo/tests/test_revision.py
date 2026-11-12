import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant import criterios, rutas
from quant.investigacion import catalogo, contratos, revision


@pytest.fixture(autouse=True)
def _candado_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(revision, "GPU_LOCK", tmp_path / "gpu.lock", raising=False)

FICHA = {"id": "rsi2-spy", "titulo": "RSI(2) en SPY", "fuente": {"url": "x://y", "cita": "c"}, "tipo": "reversion",
         "forma": "serie_temporal", "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
         "entrada": {"largo": {"<": ["RSI(2)", 10]}}, "gestion": {}, "estado": "borrador"}

RESPUESTA = {"estado": "aviso", "resumen": "Una candidata; el critico devuelve demasiado.",
             "correo": "Texto para el correo.", "notas": {"critico": "Aprueba cuando la ficha coincide con el extracto."},
             "acciones": [{"tipo": "reencolar", "doc_id": 1}, {"tipo": "invalidar_ficha", "ficha_id": 1, "motivo": "inventada"},
                          {"tipo": "reencolar", "doc_id": 999}]}


def _raiz(tmp_path):
    (tmp_path / "config").mkdir()
    for f in ("criterios.json", "costes.json", "universo.json"):
        shutil.copy(rutas.CONFIG / f, tmp_path / "config" / f)
    criterios.firmar(tmp_path / "config")
    for agente in ("lector", "formalizador", "critico", "relator"):
        (tmp_path / "skills" / agente).mkdir(parents=True)
        (tmp_path / "skills" / agente / "skill.md").write_text("skill", encoding="utf-8")
        (tmp_path / "skills" / agente / "notas.md").write_text("(sin notas)", encoding="utf-8")
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "CLAUDE.md").write_text("Reglas del supervisor de esta raiz.", encoding="utf-8")
    (tmp_path / "informes").mkdir()
    (tmp_path / "informes" / "parte_20260917.json").write_text(json.dumps({"fecha": "20260917", "errores": 0, "etapas": {}}),
                                                                encoding="utf-8")
    (tmp_path / "examen").mkdir()
    (tmp_path / "examen" / "notas.json").write_text(json.dumps({"critico": {"nota": 0.6, "casos": 5, "modelo": "m"}}),
                                                     encoding="utf-8")
    con = catalogo.abrir(tmp_path / "catalogo.db")
    doc = catalogo.anadir_documento(con, "reddit", "u://1", "Post con orden", "2026-09-16", "haz X", tmp_path / "documentos")
    ficha = catalogo.guardar_ficha(con, doc, FICHA, "aprobada")
    catalogo.marcar(con, doc, "validado")
    catalogo.guardar_resultado(con, ficha, "SPY", "pasa", {"veredicto": "pasa", "criterios": [], "metricas": {"total": {}},
                                                           "referencias": {}, "avisos": []})
    catalogo.guardar_relato(con, 1, "Compra en caidas y vende en la media.")
    for i in range(2, 7):
        d = catalogo.anadir_documento(con, "arxiv", f"u://{i}", f"T{i}", "2026-09-16", f"t{i}", tmp_path / "documentos")
        f = catalogo.guardar_ficha(con, d, FICHA, "rechazada", f"motivo {i}")
    return con


def test_paquete_valla_y_recorta(tmp_path):
    con = _raiz(tmp_path)
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "<<<DOCUMENTO" in texto and "Compra en caidas" in texto and "RSI(2) en SPY" in texto
    assert sum(f"motivo {i}" in texto for i in range(2, 7)) == 3
    revision.MAX_BYTES, guardado = 400, revision.MAX_BYTES
    try:
        corto = revision.paquete(con, tmp_path, "20260917")
    finally:
        revision.MAX_BYTES = guardado
    assert len(corto) < len(texto) and corto.endswith("[paquete recortado]")


def _parte_con_instrumentos(tmp_path, n=500):
    instrumentos = [{"instrumento": f"I{i}", "dias": 1, "velas": 0, "hasta": "2026-09-16",
                     "error": "sin datos" if i == 0 else None} for i in range(n)]
    parte = {"fecha": "20260917", "inicio": "2026-09-17T02:00:09", "desde": "2026-09-17T00:00:09+00:00",
             "errores": 0, "etapas": {"precios": {"inicio": 0, "segundos": 2000,
                                                  "resultado": {"codigo": 0, "instrumentos": instrumentos,
                                                                "errores": 1}}}}
    (tmp_path / "informes" / "parte_20260917.json").write_text(json.dumps(parte), encoding="utf-8")


def test_paquete_resume_el_parte_y_no_se_come_las_candidatas(tmp_path):
    con = _raiz(tmp_path)
    _parte_con_instrumentos(tmp_path)
    texto = revision.paquete(con, tmp_path, "20260917")
    assert len(texto.encode("utf-8")) <= revision.MAX_BYTES
    assert texto.count("<<<DOCUMENTO") == texto.count("DOCUMENTO>>>")
    assert "RSI(2) en SPY" in texto and "Compra en caidas" in texto
    assert revision.MARCA_RECORTE not in texto
    assert '"total": 500' in texto and "sin datos" in texto and '"I499"' not in texto


def test_paquete_recortado_cierra_la_valla(tmp_path):
    con = _raiz(tmp_path)
    _parte_con_instrumentos(tmp_path)
    guardado = revision.MAX_BYTES
    revision.MAX_BYTES = 900
    try:
        corto = revision.paquete(con, tmp_path, "20260917")
    finally:
        revision.MAX_BYTES = guardado
    assert corto.count("<<<DOCUMENTO") == corto.count("DOCUMENTO>>>")
    assert corto.endswith(revision.MARCA_RECORTE) and len(corto.encode("utf-8")) <= 900


def test_paquete_con_el_parte_real_cabe_entero(tmp_path):
    real = rutas.RAIZ / "informes" / "parte_20260917.json"
    if not real.exists():
        pytest.skip("no hay parte real que contrastar")
    con = _raiz(tmp_path)
    shutil.copy(real, tmp_path / "informes" / "parte_20260917.json")
    texto = revision.paquete(con, tmp_path, "20260917")
    assert len(texto.encode("utf-8")) <= revision.MAX_BYTES
    assert revision.MARCA_RECORTE not in texto and "RSI(2) en SPY" in texto
    assert texto.count("<<<DOCUMENTO") == texto.count("DOCUMENTO>>>")


def test_paquete_ignora_el_barrido_y_las_candidatas_de_otras_noches(tmp_path):
    con = _raiz(tmp_path)
    _parte_con_instrumentos(tmp_path)
    for i in range(246):
        fid = con.execute("INSERT INTO fichas (doc_id, json, estado, motivo, creado) VALUES (NULL, ?, 'generada', NULL,"
                          " '2026-09-17T01:00:00')", (json.dumps({**FICHA, "titulo": f"barrido {i}"}),)).lastrowid
        catalogo.guardar_resultado(con, fid, "SPY", "pasa", {"veredicto": "pasa", "criterios": [], "x": "y" * 2000})
    vieja = catalogo.guardar_ficha(con, 1, {**FICHA, "titulo": "de otra noche"}, "aprobada")
    catalogo.guardar_resultado(con, vieja, "SPY", "dudosa", {"veredicto": "dudosa", "criterios": []})
    con.execute("UPDATE resultados SET creado = '2026-09-10T00:00:00+00:00' WHERE ficha_id = ?", (vieja,))
    con.commit()
    texto = revision.paquete(con, tmp_path, "20260917")
    assert revision.MARCA_RECORTE not in texto and len(texto.encode("utf-8")) <= revision.MAX_BYTES
    assert "RSI(2) en SPY" in texto and '"total": 500' in texto
    assert "barrido 0" not in texto and "de otra noche" not in texto


def test_paquete_con_muchas_candidatas_conserva_el_parte(tmp_path):
    con = _raiz(tmp_path)
    _parte_con_instrumentos(tmp_path)
    for i in range(300):
        f = catalogo.guardar_ficha(con, 1, {**FICHA, "titulo": f"cand {i}", "relleno": "z" * 1500}, "aprobada")
        catalogo.guardar_resultado(con, f, "SPY", "pasa", {"veredicto": "pasa", "criterios": []})
    texto = revision.paquete(con, tmp_path, "20260917")
    assert texto.endswith(revision.MARCA_RECORTE) and len(texto.encode("utf-8")) <= revision.MAX_BYTES
    assert '"total": 500' in texto and "Conteo de errores" in texto and "omitida por espacio" not in texto
    assert "RSI(2) en SPY" in texto and "candidatas mas omitidas por espacio" in texto
    assert texto.count("<<<DOCUMENTO") == texto.count("DOCUMENTO>>>")


def test_paquete_filtra_la_noche_en_utc(tmp_path):
    con = _raiz(tmp_path)
    inicio_local = "2026-09-17T02:00:00"
    limite = datetime.fromisoformat(inicio_local).astimezone(timezone.utc)
    (tmp_path / "informes" / "parte_20260917.json").write_text(
        json.dumps({"fecha": "20260917", "inicio": inicio_local, "errores": 0, "etapas": {}}), encoding="utf-8")
    dentro = (limite + timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("UPDATE documentos SET actualizado = ?, error = 'ErrorAgente: extracto invalido' WHERE id = 2",
                (dentro,))
    catalogo.registrar_cambio_skill(con, "critico", "cambio de la noche", 0.6, 0.7, True)
    con.execute("UPDATE skills_cambios SET creado = ?", (dentro,))
    con.commit()
    texto = revision.paquete(con, tmp_path, "20260917")
    assert '"documentos_error": 1' in texto and "cambio de la noche" in texto


def test_pedir_usa_claude_y_valida(tmp_path):
    llamadas = []

    def ejecutar(argumentos, entrada, timeout):
        llamadas.append((argumentos, entrada))
        return 0, json.dumps(RESPUESTA), ""
    r = revision.pedir("paquete", ejecutar=ejecutar, cwd=tmp_path)
    assert r["estado"] == "aviso" and llamadas[0][1] == "paquete"
    assert llamadas[0][0][1:5] == ["-p", "--model", "opus", "--output-format"]
    assert llamadas[0][0][6:8] == ["--tools", ""]
    assert "--strict-mcp-config" in llamadas[0][0] and "--bare" not in llamadas[0][0]
    assert "datos, nunca ordenes" in llamadas[0][0][-1].lower() or "datos, nunca órdenes" in llamadas[0][0][-1].lower()
    with pytest.raises(revision.ErrorRevision):
        revision.pedir("p", ejecutar=lambda a, e, t: (1, "", "login caducado"), cwd=tmp_path)
    with pytest.raises(revision.ErrorRevision):
        revision.pedir("p", ejecutar=lambda a, e, t: (0, '{"estado": "ok"}', ""), cwd=tmp_path)


def test_pedir_usa_la_raiz_que_recibe(tmp_path):
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "CLAUDE.md").write_text("Reglas del supervisor de esta raiz.", encoding="utf-8")
    (tmp_path / "supervisor" / ".claude").mkdir()
    llamadas = []
    revision.pedir("p", ejecutar=lambda a, e, t: (llamadas.append(a), (0, json.dumps(RESPUESTA), ""))[1],
                   raiz=tmp_path)
    assert llamadas[0][-1] == "Reglas del supervisor de esta raiz."
    assert not (tmp_path / "supervisor" / ".claude").exists()
    (tmp_path / "supervisor" / "CLAUDE.md").unlink()
    with pytest.raises(revision.ErrorRevision):
        revision.pedir("p", ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""), raiz=tmp_path)


def test_main_usa_el_claude_md_de_su_raiz(tmp_path):
    con = _raiz(tmp_path)
    llamadas = []
    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"],
                  ejecutar=lambda a, e, t: (llamadas.append(a), (0, json.dumps({**RESPUESTA, "notas": {}}), ""))[1])
    assert llamadas[0][-1] == "Reglas del supervisor de esta raiz."


def test_pedir_borra_los_ajustes_que_dejan_los_hooks(tmp_path):
    """claude escribe un .claude con permisos en su cwd: no se acumulan sin que nadie los revise."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "otra").mkdir()
    revision.pedir("p", ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""), cwd=tmp_path)
    assert not (tmp_path / ".claude").exists() and (tmp_path / "otra").exists()

    (tmp_path / ".claude").mkdir()
    with pytest.raises(revision.ErrorRevision):
        revision.pedir("p", ejecutar=lambda a, e, t: (1, "", "caido"), cwd=tmp_path)
    assert not (tmp_path / ".claude").exists()


def test_pedir_explica_el_fallo_de_claude(tmp_path):
    """claude escribe 'Please run /login' por stdout, no por stderr: sin eso el correo no dice nada."""
    with pytest.raises(revision.ErrorRevision) as fallo:
        revision.pedir("p", ejecutar=lambda a, e, t: (1, "Please run /login", ""), cwd=tmp_path)
    assert "codigo 1" in str(fallo.value) and "Please run /login" in str(fallo.value)
    with pytest.raises(revision.ErrorRevision) as otro:
        revision.pedir("p", ejecutar=lambda a, e, t: (1, "x" * 900, "y" * 900), cwd=tmp_path)
    assert "x" * 500 in str(otro.value) and "x" * 501 not in str(otro.value)
    assert "y" * 500 in str(otro.value) and "y" * 501 not in str(otro.value)


def test_pedir_rechaza_respuesta_malformada(tmp_path):
    malas = ({**RESPUESTA, "estado": "raro"}, {**RESPUESTA, "notas": {"critico": 5}},
             {**RESPUESTA, "acciones": ["reencolar"]})
    for mala in malas:
        with pytest.raises(revision.ErrorRevision):
            revision.pedir("p", ejecutar=lambda a, e, t, mala=mala: (0, json.dumps(mala), ""), cwd=tmp_path)


def test_aplicar_notas_con_examen_y_acciones(tmp_path):
    con = _raiz(tmp_path)
    salida = revision.aplicar(con, tmp_path, RESPUESTA, notas=tmp_path / "examen" / "notas.json",
                              evaluar=lambda agente, **k: {"agente": agente, "nota": 0.7, "casos": 5, "modelo": "m"})
    assert salida["notas"]["critico"]["aceptado"] is True
    assert "Aprueba cuando" in (tmp_path / "skills" / "critico" / "notas.md").read_text(encoding="utf-8")
    assert [a["hecho"] for a in salida["acciones"]] == [True, True, False]
    assert con.execute("SELECT etapa, intentos FROM documentos WHERE id = 1").fetchone()["etapa"] == "nuevo"
    assert con.execute("SELECT estado, motivo FROM fichas WHERE id = 1").fetchone()["estado"] == "invalidada"
    antes_del_rechazo = (tmp_path / "skills" / "critico" / "notas.md").read_text(encoding="utf-8")
    peor = revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [], "notas": {"critico": "Nota mala."}},
                            notas=tmp_path / "examen" / "notas.json",
                            evaluar=lambda agente, **k: {"agente": agente, "nota": 0.5, "casos": 5, "modelo": "m"})
    assert peor["notas"]["critico"]["aceptado"] is False
    assert "Nota mala" not in (tmp_path / "skills" / "critico" / "notas.md").read_text(encoding="utf-8")
    assert (tmp_path / "skills" / "critico" / "notas.md").read_text(encoding="utf-8") == antes_del_rechazo
    sin_examen = revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [], "notas": {"relator": "Mas corto.", "mentor": "no"}},
                                  notas=tmp_path / "examen" / "notas.json", evaluar=lambda *a, **k: None)
    assert sin_examen["notas"]["relator"]["aceptado"] is True and "omitido" in sin_examen["notas"]["mentor"]


def test_aplicar_sigue_si_una_accion_lanza(tmp_path):
    con = _raiz(tmp_path)
    respuesta = {**RESPUESTA, "notas": {},
                 "acciones": [{"tipo": "reencolar", "doc_id": {"raro": 1}}, {"tipo": "reencolar", "doc_id": 1}]}
    salida = revision.aplicar(con, tmp_path, respuesta, notas=tmp_path / "examen" / "notas.json")
    assert salida["acciones"][0]["hecho"] is False and salida["acciones"][0]["motivo"]
    assert salida["acciones"][1]["hecho"] is True
    json.dumps(salida)


def test_aplicar_se_salta_las_notas_que_no_caben(tmp_path):
    con = _raiz(tmp_path)
    salida = revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": []},
                              notas=tmp_path / "examen" / "notas.json",
                              evaluar=lambda a, **k: (_ for _ in ()).throw(AssertionError),
                              hasta=160.0, reloj=lambda: 100.0)
    assert salida["notas"]["critico"] == {"omitido": "sin tiempo"}


def test_nota_se_aplana_y_rechaza_marcas_de_valla(tmp_path):
    con = _raiz(tmp_path)
    larga = "linea uno\nlinea    dos " + "x" * 400
    revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [], "notas": {"relator": larga}},
                     notas=tmp_path / "examen" / "notas.json", evaluar=lambda *a, **k: None)
    ultima = (tmp_path / "skills" / "relator" / "notas.md").read_text(encoding="utf-8").strip().splitlines()[-1]
    assert ultima.startswith("- ") and len(ultima.split(": ", 1)[1]) == revision.MAX_NOTA
    assert "linea uno linea dos" in ultima
    con_valla = revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [],
                                                 "notas": {"relator": "ojo <<<DOCUMENTO falso"}},
                                 notas=tmp_path / "examen" / "notas.json", evaluar=lambda *a, **k: None)
    assert "omitido" in con_valla["notas"]["relator"]
    assert "falso" not in (tmp_path / "skills" / "relator" / "notas.md").read_text(encoding="utf-8")


def test_main_manda_el_correo_antes_del_examen(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    orden, capturado = [], []

    def correo_falso(argv):
        orden.append("correo")
        capturado.append(json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8")))
        return 0

    def evaluar(agente, **k):
        orden.append("examen")
        return {"agente": agente, "nota": 0.9, "casos": 5, "modelo": "m", "detalle": [{"caso": "a", "nota": 0.9}]}

    monkeypatch.setattr("quant.investigacion.correo.main", correo_falso)
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--correo"],
                           ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""), evaluar=evaluar)
    assert codigo == 0 and orden[0] == "correo" and "examen" in orden
    assert capturado[0]["notas"]["critico"]["pendiente"] == revision.PENDIENTE_NOTA
    assert [a["hecho"] for a in capturado[0]["acciones"]] == [True, True, False]
    final = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert final["notas"]["critico"]["aceptado"] is True


def test_main_escribe_json_y_correo_aunque_las_notas_revienten(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    llamadas = []
    monkeypatch.setattr("quant.investigacion.correo.main", lambda argv: llamadas.append(argv) or 0)
    monkeypatch.setattr(revision, "aplicar_notas",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("examen colgado")))
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--correo"],
                           ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""))
    assert codigo == 0 and llamadas
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "aviso" and "examen colgado" in r["notas"]["critico"]["omitido"]


def test_nota_relator_hace_copia_en_historial(tmp_path):
    con = _raiz(tmp_path)
    original = (tmp_path / "skills" / "relator" / "notas.md").read_text(encoding="utf-8")
    ahora = datetime(2026, 9, 17, 6, 15, 0, tzinfo=timezone.utc)
    salida = revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [], "notas": {"relator": "Se mas breve."}},
                              notas=tmp_path / "examen" / "notas.json", ahora=ahora)
    assert salida["notas"]["relator"]["aceptado"] is True
    copia = tmp_path / "skills" / "relator" / "historial" / "20260917_061500_notas.md"
    assert copia.exists() and copia.read_text(encoding="utf-8") == original
    assert "Se mas breve" in (tmp_path / "skills" / "relator" / "notas.md").read_text(encoding="utf-8")


def test_descartes_no_pasa_reconstruye_motivo(tmp_path):
    con = catalogo.abrir(tmp_path / "catalogo.db")
    doc = catalogo.anadir_documento(con, "arxiv", "u://1", "T1", "2026-09-16", "t1", tmp_path / "documentos")
    ficha = catalogo.guardar_ficha(con, doc, FICHA, "aprobada")
    resultado = {"veredicto": "no_pasa", "criterios": [
        {"criterio": "drawdown", "valor": 0.5, "umbral": 0.2, "cumple": False},
        {"criterio": "robustez", "valor": 0.9, "umbral": 0.5, "cumple": True}],
        "metricas": {"total": {}}, "referencias": {}, "avisos": []}
    catalogo.guardar_resultado(con, ficha, "SPY", "no_pasa", resultado)
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "drawdown 0.5 (umbral 0.2)" in texto
    assert '"motivo": ""' not in texto


def test_main_parada_por_criterios_y_sin_claude(tmp_path):
    con = _raiz(tmp_path)
    ok = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"], ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""),
                       evaluar=lambda agente, **k: {"agente": agente, "nota": 0.9, "casos": 5, "modelo": "m"})
    assert ok == 0
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "aviso" and r["criterios"] == "" and r["notas"]["critico"]["aceptado"] is True

    (tmp_path / "config" / "criterios.json").write_text("{}", encoding="utf-8")
    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"],
                  ejecutar=lambda *a: (_ for _ in ()).throw(AssertionError))
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "parada" and r["criterios"]

    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"],
                  ejecutar=lambda *a: (_ for _ in ()).throw(AssertionError))
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "parada" and r["criterios"]

    shutil.copy(rutas.CONFIG / "criterios.json", tmp_path / "config" / "criterios.json")
    criterios.firmar(tmp_path / "config")
    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"],
                  ejecutar=lambda *a: (_ for _ in ()).throw(AssertionError))
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "sin revision" and r["criterios"] == ""

    roto = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"], ejecutar=lambda a, e, t: (1, "", "caido"))
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert roto == 0 and r["estado"] == "sin revision" and "caido" in r["error"] and r["criterios"] == ""


def test_main_correo_llama_a_correo_main(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    llamadas = []
    monkeypatch.setattr("quant.investigacion.correo.main", lambda argv: llamadas.append(argv) or 0)
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude", "--correo"])
    assert codigo == 0
    assert llamadas == [["--raiz", str(tmp_path), "--fecha", "20260917"]]
    ultima = json.loads((tmp_path / "registro" / "revision_20260917.log").read_text(encoding="utf-8")
                        .strip().splitlines()[-1])
    assert ultima["correo"] == 0


def test_main_registra_el_correo_antes_de_los_examenes_largos(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    monkeypatch.setattr("quant.investigacion.correo.main", lambda argv: 0)

    def aplicar_notas_lenta(*a, **k):
        ultima = json.loads((tmp_path / "registro" / "revision_20260917.log").read_text(encoding="utf-8")
                            .strip().splitlines()[-1])
        assert ultima["correo"] == 0
        return {}

    monkeypatch.setattr(revision, "aplicar_notas", aplicar_notas_lenta)
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--correo"],
                           ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""))
    assert codigo == 0


def test_main_correo_registra_codigo_de_fallo_sin_cambiar_estado(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    monkeypatch.setattr("quant.investigacion.correo.main", lambda argv: 1)
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude", "--correo"])
    assert codigo == 0
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "sin revision"
    ultima = json.loads((tmp_path / "registro" / "revision_20260917.log").read_text(encoding="utf-8")
                        .strip().splitlines()[-1])
    assert ultima["correo"] == 1


def test_main_sin_correo_registra_correo_nulo(tmp_path):
    con = _raiz(tmp_path)
    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"])
    ultima = json.loads((tmp_path / "registro" / "revision_20260917.log").read_text(encoding="utf-8")
                        .strip().splitlines()[-1])
    assert ultima["correo"] is None


def test_comprobar_criterios_con_config_rota(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "config" / "criterios.json").unlink()
    assert revision.comprobar_criterios(tmp_path) != ""
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"],
                           ejecutar=lambda *a: (_ for _ in ()).throw(AssertionError))
    assert codigo == 0
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "parada" and r["criterios"]


def test_paquete_con_parte_inexistente_dice_sin_parte(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "informes" / "parte_20260917.json").unlink()
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "Sin parte de la noche" in texto
    assert "Parte fuera de contrato" not in texto


def test_paquete_con_parte_ilegible_adjunta_el_crudo_recortado(tmp_path):
    con = _raiz(tmp_path)
    contenido = "{roto" + "".join(f"x{i:05d}" for i in range(500))
    marca_lejana = "MARCA-FUERA-DE-RANGO"
    contenido = contenido[:2500] + marca_lejana
    (tmp_path / "informes" / "parte_20260917.json").write_text(contenido, encoding="utf-8")
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "{roto" in texto and "x00000" in texto
    assert marca_lejana not in texto
    assert "Parte fuera de contrato" not in texto and "Sin parte de la noche" not in texto


def test_paquete_con_parte_que_es_una_lista_adjunta_el_crudo(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "informes" / "parte_20260917.json").write_text(json.dumps(["no", "objeto"]), encoding="utf-8")
    texto = revision.paquete(con, tmp_path, "20260917")
    assert '"no"' in texto and '"objeto"' in texto
    assert "Parte fuera de contrato" not in texto and "Sin parte de la noche" not in texto


def test_paquete_con_parte_objeto_mal_formado_dice_fuera_de_contrato(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "informes" / "parte_20260917.json").write_text(
        json.dumps({"fecha": "20260917", "errores": 0, "etapas": {}}), encoding="utf-8")
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "Parte fuera de contrato" in texto and "falta" in texto


def test_main_sin_fecha_usa_fecha_local(tmp_path):
    con = _raiz(tmp_path)
    ahora = datetime(2026, 9, 17, 23, 0, tzinfo=timezone.utc)
    revision.main(["--raiz", str(tmp_path), "--sin-claude"], ahora=ahora)
    fecha_esperada = ahora.astimezone().strftime("%Y%m%d")
    assert (tmp_path / "supervisor" / f"revision_{fecha_esperada}.json").exists()


def test_main_marca_la_revision_fuera_de_contrato(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    monkeypatch.setattr(revision, "aplicar_acciones", lambda con, respuesta: ["mal", "tambien mal"])
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"],
                           ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""),
                           evaluar=lambda agente, **k: {"agente": agente, "nota": 0.9, "casos": 5, "modelo": "m"})
    assert codigo == 0
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert any(e.startswith("acciones[0]:") for e in r["contrato"])


def test_revision_deja_copia_real(tmp_path):
    con = _raiz(tmp_path)
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"])
    assert codigo == 0
    copia = tmp_path / "codigo" / "tests" / "reales" / "revision_20260917.json"
    assert copia.exists()


def test_guardar_real_roto_no_cambia_el_codigo_de_salida(tmp_path, monkeypatch):
    con = _raiz(tmp_path)
    monkeypatch.setattr(contratos, "guardar_real", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"])
    assert codigo == 0


def test_main_restaura_huerfanas_al_arrancar(tmp_path):
    con = _raiz(tmp_path)
    ruta = tmp_path / "skills" / "critico" / "skill.md"
    original = ruta.read_bytes()
    historial = tmp_path / "skills" / "critico" / "historial"
    historial.mkdir(parents=True, exist_ok=True)
    copia = historial / "20260916_061500_skill.md"
    copia.write_bytes(original)
    (historial / "20260916_061500_skill.md.pendiente").write_text(
        '{"agente": "critico", "fichero": "skill.md", "motivo": "nota del supervisor"}', encoding="utf-8")
    ruta.write_text("texto sin evaluar", encoding="utf-8")
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"])
    assert codigo == 0
    assert ruta.read_bytes() == original
    assert list(historial.glob("*.pendiente")) == []


def test_nota_del_supervisor_registra_su_origen(tmp_path):
    con = _raiz(tmp_path)
    revision.aplicar(con, tmp_path, RESPUESTA, notas=tmp_path / "examen" / "notas.json",
                     evaluar=lambda agente, **k: {"agente": agente, "nota": 0.7, "casos": 5, "modelo": "m"})
    fila = con.execute("SELECT origen FROM skills_cambios WHERE agente = 'critico' ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["origen"] == "supervisor"


def test_nota_del_supervisor_relator_registra_su_origen(tmp_path):
    con = _raiz(tmp_path)
    revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [], "notas": {"relator": "Se mas breve."}},
                     notas=tmp_path / "examen" / "notas.json", evaluar=lambda *a, **k: None)
    fila = con.execute("SELECT origen FROM skills_cambios WHERE agente = 'relator' ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["origen"] == "supervisor"


def test_aplicar_nota_hasta_reloj_solo_si_hasta_no_es_none(tmp_path):
    con = _raiz(tmp_path)
    raiz_skills = tmp_path / "skills"
    notas = tmp_path / "examen" / "notas.json"
    visto = {}

    def evaluar(agente, **k):
        visto["kwargs"] = set(k)
        return {"agente": agente, "nota": 0.9, "casos": 5, "detalle": [], "concluyente": True}

    ahora = datetime.now(timezone.utc)
    revision._aplicar_nota(con, raiz_skills, "critico", "una nota", evaluar, None, notas, ahora)
    assert "hasta" not in visto["kwargs"] and "reloj" not in visto["kwargs"]

    revision._aplicar_nota(con, raiz_skills, "critico", "otra nota", evaluar, None, notas, ahora,
                           hasta=1000, reloj=lambda: 0)
    assert "hasta" in visto["kwargs"] and "reloj" in visto["kwargs"]


def test_aviso_de_restauradas_solo_en_correo_no_en_resumen(tmp_path):
    con = _raiz(tmp_path)
    ruta = tmp_path / "skills" / "critico" / "skill.md"
    original = ruta.read_bytes()
    historial = tmp_path / "skills" / "critico" / "historial"
    historial.mkdir(parents=True, exist_ok=True)
    copia = historial / "20260916_061500_skill.md"
    copia.write_bytes(original)
    (historial / "20260916_061500_skill.md.pendiente").write_text(
        '{"agente": "critico", "fichero": "skill.md", "motivo": "nota del supervisor"}', encoding="utf-8")
    ruta.write_text("texto sin evaluar", encoding="utf-8")
    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"])
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["correo"].count("restauraron") == 1
    assert "restauraron" not in r["resumen"]


def test_main_no_revienta_con_respuesta_malformada(tmp_path):
    con = _raiz(tmp_path)
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"],
                           ejecutar=lambda a, e, t: (0, json.dumps({**RESPUESTA, "estado": "raro"}), ""))
    assert codigo == 0
    r = json.loads((tmp_path / "supervisor" / "revision_20260917.json").read_text(encoding="utf-8"))
    assert r["estado"] == "sin revision" and r["error"]


def test_main_deja_margen_para_que_el_ultimo_examen_termine(tmp_path, monkeypatch):
    import time
    _raiz(tmp_path)
    visto = {}
    monkeypatch.setattr(revision, "aplicar_notas", lambda *a, **k: visto.update(k) or {})
    codigo = revision.main(["--raiz", str(tmp_path), "--fecha", "20260917"],
                           ejecutar=lambda a, e, t: (0, json.dumps(RESPUESTA), ""))
    despues = time.monotonic()
    assert codigo == 0
    assert visto["hasta"] <= despues + contratos.LIMITE_REVISION_HORAS * 3600 - 25 * 60


def test_aplicar_notas_examina_dentro_del_candado_de_gpu(tmp_path, monkeypatch):
    from contextlib import contextmanager
    con = _raiz(tmp_path)
    estado = {"dentro": False, "ruta": None, "visto": None}

    @contextmanager
    def turno(ruta, **k):
        estado["dentro"], estado["ruta"] = True, ruta
        yield True
        estado["dentro"] = False

    def evaluar(agente, **k):
        estado["visto"] = estado["dentro"]
        return {"agente": agente, "nota": 0.9, "casos": 5, "modelo": "m", "detalle": [], "concluyente": True}

    monkeypatch.setattr(revision.candados, "turno", turno)
    revision.aplicar_notas(con, tmp_path, RESPUESTA, evaluar=evaluar, notas=tmp_path / "examen" / "notas.json")
    assert estado["visto"] is True and estado["ruta"] == tmp_path / "gpu.lock" and estado["dentro"] is False


def test_revision_pone_su_propio_tope(tmp_path, monkeypatch):
    from quant.investigacion import claude_cli
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "agentes.json").write_text('{"_tope_llamadas_revision": 9}', encoding="utf-8")
    vistos = []
    monkeypatch.setattr(claude_cli, "reiniciar", lambda tope: vistos.append(tope))
    revision.main(["--raiz", str(tmp_path), "--fecha", "20260917", "--sin-claude"])
    assert vistos == [9]


def _lab_noche(con):
    from quant.investigacion import laboratorio as lab
    lab.ensure_schema(con)
    entreno = json.dumps({"veredicto": "pasa", "criterios": [], "metricas": {"total": {"profit_factor": 1.12,
                                                                                       "operaciones": 300}}})
    filas = [("2026-09-17", "h1", "quitar la vuelta", "no_pasa", None), ("2026-09-17", "h2", "stop mas ancho",
             "pasa_validador", json.dumps({"profit_factor": 0.97})), ("2026-09-16", "h3", "idea de ayer", "no_pasa", None)]
    con.execute("INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto,"
                " entreno_json, creado) VALUES ('manual', '2026-09-10', 'h0', '{}', 'base', 0, 'no_pasa', ?, 'x')",
                (json.dumps({"veredicto": "no_pasa", "metricas": {"total": {"profit_factor": 0.61, "operaciones": 4700}}}),))
    for noche, h, motivo, veredicto, examen in filas:
        con.execute("INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto,"
                    " entreno_json, examen_json, creado) VALUES ('manual', ?, ?, '{}', ?, 1, ?, ?, ?, 'x')",
                    (noche, h, motivo, veredicto, entreno, examen))
    con.commit()


def test_paquete_trae_el_laboratorio_de_la_noche(tmp_path):
    con = _raiz(tmp_path)
    _lab_noche(con)
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "## Laboratorio" in texto and "manual" in texto
    assert "quitar la vuelta" in texto and "stop mas ancho" in texto and "0.97" in texto
    assert "idea de ayer" not in texto
    assert '"experimentos_hasta_hoy": 4' in texto and '"experimentos_hasta_hoy": 0' in texto
    assert '"base_entreno": {"profit_factor": 0.61' in texto


def test_paquete_sin_tabla_de_laboratorio(tmp_path):
    con = _raiz(tmp_path)
    assert "(el laboratorio no ha corrido)" in revision.paquete(con, tmp_path, "20260917")


def test_el_supervisor_no_puede_dejar_notas_al_laboratorio(tmp_path):
    con = _raiz(tmp_path)
    revision.aplicar(con, tmp_path, {**RESPUESTA, "acciones": [], "notas": {"laboratorio": "Prueba sin la vuelta."}},
                     notas=tmp_path / "examen" / "notas.json", evaluar=lambda *a, **k: None)
    assert not (tmp_path / "skills" / "laboratorio" / "notas.md").exists()


def test_paquete_incluye_el_asesor_reciente(tmp_path):
    from quant.investigacion import laboratorio as lab
    con = _raiz(tmp_path)
    lab.ensure_schema(con)
    for fecha, informe in (("2026-09-16", "informe reciente"), ("2026-09-10", "informe viejo")):
        con.execute("INSERT INTO lab_asesor (estrategia, fecha, informe, direccion, direccion_es, propuestas_json, creado)"
                    " VALUES ('ejemplo', ?, ?, 'd', 'd es', '[]', 'x')", (fecha, informe))
    con.commit()
    texto = revision.paquete(con, tmp_path, "20260917")
    assert "## Asesor semanal" in texto and "informe reciente" in texto and "informe viejo" not in texto
