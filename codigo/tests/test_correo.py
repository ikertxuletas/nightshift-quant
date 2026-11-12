import json
from datetime import datetime, timedelta, timezone

from quant.investigacion import catalogo, contratos, correo, revision

PARTE = {"fecha": "20260917", "errores": 1, "corte": False,
         "etapas": {"precios": {"segundos": 100, "resultado": {"codigo": 0}},
                    "investigar": {"segundos": 3000, "resultado": {"lectura": {"leidos": 4, "descartados": 6, "errores": 1,
                                                                             "omitidos": 0, "agotados": 0},
                                                                 "fichas": {"aprobadas": 2, "rechazadas": 3, "no_expresables": 1,
                                                                            "errores": 0, "omitidos": 0, "agotados": 0},
                                                                 "validadas": 2}},
                    "relator": {"segundos": 200, "resultado": {"relatados": 1, "errores": 0, "omitidos": 0}},
                    "mentor": {"segundos": 900, "resultado": {"propuesta": {"agente": "lector", "motivo": "aclarar tipo"},
                                                             "aplicado": {"aceptado": False, "nota_antes": 0.79, "nota_despues": 0.7}}},
                    "copia": {"segundos": 5, "resultado": {"catalogo": True}}},
         "catalogo": {"documentos": {"nuevo": 80, "validado": 2}, "fichas": {"aprobada": 2, "rechazada": 3, "no_expresable": 1},
                      "resultados": {"pasa": 1, "no_pasa": 1}}}

REVISION = {"estado": "aviso", "resumen": "Una candidata con avisos.", "correo": "Que paso: bien.\nProblemas: ninguno.",
            "notas": {"critico": {"aceptado": True, "nota_antes": 0.6, "nota_despues": 0.7}},
            "acciones": [{"tipo": "reencolar", "doc_id": 3, "hecho": True}], "criterios": "", "error": ""}


class SmtpFalso:
    def __init__(self):
        self.enviados, self.credencial = [], None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        self.credencial = (u, p)

    def send_message(self, msg):
        self.enviados.append(msg)


def _raiz(tmp_path):
    (tmp_path / "informes").mkdir()
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "informes" / "parte_20260917.json").write_text(json.dumps(PARTE), encoding="utf-8")
    (tmp_path / "informes" / "informe_20260917.md").write_text("# informe", encoding="utf-8")
    (tmp_path / "supervisor" / "revision_20260917.json").write_text(json.dumps(REVISION), encoding="utf-8")
    con = catalogo.abrir(tmp_path / "catalogo.db")
    doc = catalogo.anadir_documento(con, "arxiv", "u://1", "T", "2026-09-16", "t", tmp_path / "documentos")
    ficha = catalogo.guardar_ficha(con, doc, {"id": "a", "titulo": "Candidata A"}, "aprobada")
    catalogo.guardar_resultado(con, ficha, "SPY", "pasa", {"veredicto": "pasa", "criterios": [
        {"criterio": "drawdown", "valor": 0.1, "umbral": 0.2, "cumple": True}], "referencias": {"vs_fuente": {"sharpe": -0.2}},
        "avisos": []})
    catalogo.guardar_relato(con, 1, "Relato llano.")
    return con


def test_asunto():
    assert correo.asunto("20260917", PARTE, REVISION) == "[Quant] 17-sep · 6 fichas · 1 candidata · ⚠️"
    assert correo.asunto("20260917", PARTE, {**REVISION, "estado": "parada"}).endswith("🛑")
    sin = {**PARTE, "catalogo": {"documentos": {}, "fichas": {}, "resultados": {"pasa": 2}}}
    assert "2 candidatas" in correo.asunto("20260917", sin, {**REVISION, "estado": "ok"})


def test_cuerpo_secciones(tmp_path):
    con = _raiz(tmp_path)
    texto = correo.cuerpo("20260917", PARTE, REVISION, con)
    for titulo in ("1. Estado", "2. Cifras por etapa", "3. Candidatas y dudosas", "4. Descartes por motivo", "5. Pendiente",
                   "6. Problemas y que se hizo", "7. Cambios de skills y notas"):
        assert titulo in texto
    assert "Candidata A" in texto and "drawdown" in texto and "Relato llano" in texto and "sharpe -0.2" in texto
    assert "aclarar tipo" in texto and "critico" in texto and "reencolar" in texto
    assert texto.rstrip().endswith("Candidata no significa rentable.")
    sin = correo.cuerpo("20260917", PARTE, {"estado": "sin revision", "error": "login caducado"}, con)
    assert "Sin revisión de Claude" in sin and "login caducado" in sin


def test_enviar_y_main(tmp_path):
    con = _raiz(tmp_path)
    smtp = SmtpFalso()
    obtener = lambda servicio, clave: {"usuario": "usuario@example.com", "usuario@example.com": "app-pass"}.get(clave)
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=smtp, obtener=obtener) == 0
    msg = smtp.enviados[0]
    assert smtp.credencial == ("usuario@example.com", "app-pass") and msg["To"] == "usuario@example.com"
    assert msg["Subject"].startswith("[Quant] 17-sep") and "app-pass" not in msg.as_string()
    assert [p.get_filename() for p in msg.iter_attachments()] == ["informe_20260917.md"]


def test_sin_credencial_deja_borrador(tmp_path, capsys):
    con = _raiz(tmp_path)
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=SmtpFalso(), obtener=lambda s, c: None) == 1
    assert "sin credencial" in capsys.readouterr().out
    borrador = (tmp_path / "informes" / "correo_20260917.txt").read_text(encoding="utf-8")
    assert borrador.startswith("[Quant] 17-sep") and "1. Estado" in borrador


def test_sin_credencial_en_sin_parte_devuelve_1(tmp_path, capsys):
    (tmp_path / "informes").mkdir()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], smtp=SmtpFalso(),
                       obtener=lambda s, c: None) == 1
    assert "sin credencial" in capsys.readouterr().out
    assert (tmp_path / "informes" / "correo_20260917.txt").exists()


def test_fallo_smtp_devuelve_1_y_borrador(tmp_path):
    con = _raiz(tmp_path)

    class Roto(SmtpFalso):
        def login(self, u, p):
            raise OSError("smtp caido")
    obtener = lambda servicio, clave: {"usuario": "usuario@example.com", "usuario@example.com": "x"}.get(clave)
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=Roto(), obtener=obtener) == 1
    assert (tmp_path / "informes" / "correo_20260917.txt").exists()


def _obtener(servicio, clave):
    return {"usuario": "usuario@example.com", "usuario@example.com": "app-pass"}.get(clave)


def test_main_sin_parte_manda_correo_minimo(tmp_path):
    (tmp_path / "informes").mkdir()
    (tmp_path / "registro").mkdir()
    (tmp_path / "registro" / "noche_20260917.log").write_text(
        "\n".join(f"linea {i}" for i in range(30)), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], smtp=smtp, obtener=_obtener) == 0
    msg = smtp.enviados[0]
    assert msg["Subject"] == "[Quant] 17-sep · sin parte · 🛑"
    texto = msg.get_content()
    assert "linea 29" in texto and "linea 9" not in texto
    assert not (tmp_path / "catalogo.db").exists()


def test_main_con_parte_corrupto_manda_correo_minimo(tmp_path):
    (tmp_path / "informes").mkdir()
    (tmp_path / "informes" / "parte_20260917.json").write_text("{roto", encoding="utf-8")
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "revision_20260917.json").write_text(json.dumps(REVISION), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], smtp=smtp, obtener=_obtener) == 0
    msg = smtp.enviados[0]
    assert "sin parte · 🛑" in msg["Subject"] and "Una candidata con avisos" in msg.get_content()


def test_fecha_corta_aguanta_una_fecha_rara():
    assert correo._fecha_corta("rara") == "rara"


def test_linea_canario_omitido_ok_y_falla():
    assert correo._linea_canario({"segundos": 0, "resultado": {"omitido": "sin tiempo"}}) == \
        "- canario: omitido (sin tiempo)"
    assert correo._linea_canario({"segundos": 12, "resultado": {"ok": True, "pasos": {}}}) == "- canario: ok (12 s)"
    falla = {"ok": False, "pasos": {"lector": "operable=no", "formalizador": "no ejecutado",
                                    "critico": "no ejecutado", "validacion": "no ejecutado"},
             "fallo": "canario: lector: operable=no"}
    assert correo._linea_canario({"segundos": 3, "resultado": falla}) == "- canario: FALLA en lector"


def test_seccion2_y_6_canario_sin_prefijo_duplicado(tmp_path):
    con = _raiz(tmp_path)
    falla = {"ok": False, "pasos": {"lector": "operable=no", "formalizador": "no ejecutado",
                                    "critico": "no ejecutado", "validacion": "no ejecutado"},
             "fallo": "canario: lector: operable=no"}
    parte = {**PARTE, "etapas": {**PARTE["etapas"], "canario": {"segundos": 1, "resultado": falla}}}
    texto = correo.cuerpo("20260917", parte, REVISION, con)
    assert "- canario: FALLA en lector" in texto
    assert "- canario: canario:" not in texto


def test_seccion6_ve_el_fallo_y_el_codigo_de_la_etapa(tmp_path):
    con = _raiz(tmp_path)
    parte = {**PARTE, "etapas": {**PARTE["etapas"],
                                 "investigar": {"segundos": 7628, "resultado": {"codigo": 1, "errores": 1,
                                                                                "fallo": "TypeError: raro"}},
                                 "relator": {"segundos": 1, "resultado": {"codigo": 3}}}}
    texto = correo.cuerpo("20260917", parte, REVISION, con)
    assert "- investigar: TypeError: raro" in texto and "- relator: codigo 3" in texto


def test_asunto_no_se_pone_verde_con_errores():
    assert correo.asunto("20260917", PARTE, {**REVISION, "estado": "ok"}).endswith("⚠️")
    assert correo.asunto("20260917", {**PARTE, "errores": 0}, {**REVISION, "estado": "ok"}).endswith("✅")
    assert correo.asunto("20260917", PARTE, {**REVISION, "estado": "parada"}).endswith("🛑")


def test_seccion7_lista_los_cambios_de_skills_de_la_vispera(tmp_path):
    con = _raiz(tmp_path)
    catalogo.registrar_cambio_skill(con, "critico", "nota del supervisor de ayer", 0.6, 0.7, True)
    catalogo.registrar_cambio_skill(con, "lector", "cambio de la semana pasada", 0.5, 0.5, True)
    ahora = datetime.now(timezone.utc)
    con.execute("UPDATE skills_cambios SET creado = ? WHERE agente = 'critico'",
                ((ahora - timedelta(hours=20)).isoformat(timespec="seconds"),))
    con.execute("UPDATE skills_cambios SET creado = ? WHERE agente = 'lector'",
                ((ahora - timedelta(days=3)).isoformat(timespec="seconds"),))
    con.commit()
    texto = correo.cuerpo("20260917", {**PARTE, "desde": ahora.isoformat(timespec="seconds")}, REVISION, con)
    assert "nota del supervisor de ayer" in texto and "0.6" in texto
    assert "cambio de la semana pasada" not in texto


def test_nota_pendiente_se_explica_en_el_correo():
    con = catalogo.abrir(":memory:")
    rev = {**REVISION, "notas": {"critico": {"pendiente": revision.PENDIENTE_NOTA}}}
    texto = correo.cuerpo("20260917", PARTE, rev, con)
    assert "se evaluará con el examen tras este correo" in texto


def test_de_la_noche_normaliza_inicio_local_naive_a_utc(tmp_path):
    con = _raiz(tmp_path)
    inicio_local = "2026-09-17T00:30:00"
    limite_utc = datetime.fromisoformat(inicio_local).astimezone(timezone.utc)
    parte_local = {**PARTE, "inicio": inicio_local}

    dentro = (limite_utc + timedelta(seconds=1)).isoformat(timespec="seconds")
    con.execute("UPDATE resultados SET creado = ? WHERE id = 1", (dentro,))
    con.commit()
    assert "Candidata A" in correo.cuerpo("20260917", parte_local, REVISION, con)

    fuera = (limite_utc - timedelta(seconds=1)).isoformat(timespec="seconds")
    con.execute("UPDATE resultados SET creado = ? WHERE id = 1", (fuera,))
    con.commit()
    assert "Candidata A" not in correo.cuerpo("20260917", parte_local, REVISION, con)


def test_desde_utc_prioriza_sobre_inicio_local(tmp_path):
    con = _raiz(tmp_path)
    creado_real = con.execute("SELECT creado FROM resultados WHERE id = 1").fetchone()["creado"]
    parte_con_desde = {**PARTE, "inicio": "2099-01-01T00:00:00", "desde": creado_real}
    assert "Candidata A" in correo.cuerpo("20260917", parte_con_desde, REVISION, con)


def test_seccion1_sin_revision_usa_resumen_si_falta_error():
    revision_sin_claude = {"estado": "sin revision",
                            "resumen": "Ejecutado con --sin-claude: no se ha llamado a Claude."}
    con = catalogo.abrir(":memory:")
    texto = correo.cuerpo("20260917", PARTE, revision_sin_claude, con)
    assert "Sin revisión de Claude: Ejecutado con --sin-claude" in texto


def test_seccion7_notas_y_acciones_no_vuelcan_dicts():
    con = catalogo.abrir(":memory:")
    texto = correo.cuerpo("20260917", PARTE, REVISION, con)
    assert "aceptada, nota 0.6→0.7" in texto
    assert "accion reencolar ficha 3: hecho" in texto
    assert "'tipo'" not in texto and "{'aceptado'" not in texto


def test_correo_con_parte_fuera_de_contrato_lo_dice_en_seccion6(tmp_path):
    con = _raiz(tmp_path)
    parte_malo = dict(PARTE)
    del parte_malo["corte"]
    (tmp_path / "informes" / "parte_20260917.json").write_text(json.dumps(parte_malo), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=smtp, obtener=_obtener) == 0
    texto = smtp.enviados[0].get_body().get_content()
    assert "parte fuera de contrato" in texto


def test_correo_con_revision_de_estado_inventado(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "supervisor" / "revision_20260917.json").write_text(
        json.dumps({**REVISION, "estado": "verde"}), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=smtp, obtener=_obtener) == 0
    msg = smtp.enviados[0]
    assert msg["Subject"].endswith("⚠️")
    texto = msg.get_body().get_content()
    assert "Sin revisión de Claude" in texto and "estado:" in texto


def _parte_valida():
    return {"fecha": "20260917", "inicio": "2026-09-17T02:00:09", "desde": "2026-09-17T00:00:09+00:00",
            "fin_previsto": "2026-09-17T06:00:00", "fin_real": "2026-09-17T04:42:00", "equipo": "PRINCIPAL",
            "etapas": {}, "catalogo": {}, "corte": False, "errores": 0}


def test_correo_con_parte_con_etapas_lista_no_revienta(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "informes" / "parte_20260917.json").write_text(
        json.dumps({**_parte_valida(), "etapas": ["rota"]}), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=smtp, obtener=_obtener) == 0
    msg = smtp.enviados[0]
    assert msg["Subject"].endswith("🛑")
    assert "etapas" in msg.get_body().get_content()


def test_correo_con_parte_con_catalogo_lista_no_revienta(tmp_path):
    con = _raiz(tmp_path)
    (tmp_path / "informes" / "parte_20260917.json").write_text(
        json.dumps({**_parte_valida(), "catalogo": ["rota"]}), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=smtp, obtener=_obtener) == 0
    msg = smtp.enviados[0]
    assert msg["Subject"].endswith("🛑")


def test_seccion7_sin_desde_no_vuelca_el_historico(tmp_path):
    con = _raiz(tmp_path)
    catalogo.registrar_cambio_skill(con, "critico", "cambio antiguo", 0.5, 0.6, True)
    texto = correo.cuerpo("20260917", PARTE, REVISION, con)
    assert "cambio antiguo" not in texto


def test_seccion7_muestra_el_origen(tmp_path):
    con = _raiz(tmp_path)
    catalogo.registrar_cambio_skill(con, "critico", "nota del supervisor", 0.6, 0.7, True, origen="supervisor")
    ahora = datetime.now(timezone.utc)
    con.execute("UPDATE skills_cambios SET creado = ? WHERE agente = 'critico'",
                ((ahora - timedelta(hours=1)).isoformat(timespec="seconds"),))
    con.commit()
    texto = correo.cuerpo("20260917", {**PARTE, "desde": ahora.isoformat(timespec="seconds")}, REVISION, con)
    assert "(supervisor) critico" in texto


def test_correo_con_revision_estado_valido_pero_incompleta_conserva_estado(tmp_path):
    con = _raiz(tmp_path)
    revision_mala = {k: v for k, v in REVISION.items() if k != "criterios"}
    revision_mala["estado"] = "parada"
    (tmp_path / "supervisor" / "revision_20260917.json").write_text(json.dumps(revision_mala), encoding="utf-8")
    smtp = SmtpFalso()
    assert correo.main(["--raiz", str(tmp_path), "--fecha", "20260917"], con=con, smtp=smtp, obtener=_obtener) == 0
    msg = smtp.enviados[0]
    assert msg["Subject"].endswith("🛑")
    texto = msg.get_body().get_content()
    assert "revision fuera de contrato" in texto
