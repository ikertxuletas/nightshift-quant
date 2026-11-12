"""Correo de la manana: asunto, cuerpo con 7 secciones y envio por Gmail SMTP SSL."""
import argparse
import json
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from quant import rutas
from quant.investigacion import catalogo, contratos, tiempos

SERVICIO = "Quant/gmail"
SMTP_HOST = "smtp.gmail.com"
SMTP_PUERTO = 465
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
ICONOS = {"ok": "✅", "aviso": "⚠️", "parada": "🛑", "sin revision": "⚠️"}


def estado_icono(estado):
    return ICONOS.get(estado, "⚠️")


def _fecha_corta(fecha):
    try:
        return f"{fecha[6:8]}-{MESES[int(fecha[4:6]) - 1]}"
    except (ValueError, IndexError, TypeError):
        return str(fecha)


def asunto(fecha, parte, revision):
    resultado_investigar = ((parte.get("etapas") or {}).get("investigar") or {}).get("resultado") or {}
    fichas_investigar = resultado_investigar.get("fichas") or {}
    fichas = sum(fichas_investigar.get(k, 0) for k in ("aprobadas", "rechazadas", "no_expresables"))
    candidatas = ((parte.get("catalogo") or {}).get("resultados") or {}).get("pasa", 0)
    plural = "candidata" if candidatas == 1 else "candidatas"
    icono = estado_icono(revision.get("estado", ""))
    if parte.get("errores") and icono == ICONOS["ok"]:
        icono = ICONOS["aviso"]
    return f"[Quant] {_fecha_corta(fecha)} · {fichas} fichas · {candidatas} {plural} · {icono}"


# ---------------------------------------------------------------------------
# credenciales


def credencial(obtener=None):
    if obtener is None:
        import keyring
        obtener = keyring.get_password
    usuario = obtener(SERVICIO, "usuario")
    if not usuario:
        return None
    contrasena = obtener(SERVICIO, usuario)
    if not contrasena:
        return None
    return (usuario, contrasena)


def guardar_credencial(usuario, contrasena, guardar=None):
    if guardar is None:
        import keyring
        guardar = keyring.set_password
    guardar(SERVICIO, "usuario", usuario)
    guardar(SERVICIO, usuario, contrasena)


# ---------------------------------------------------------------------------
# cuerpo


def _numerico(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _cifras_etapa(resultado):
    partes = []
    for clave in ("lectura", "fichas"):
        sub = resultado.get(clave)
        if isinstance(sub, dict):
            plano = " ".join(f"{k}={v}" for k, v in sub.items() if _numerico(v))
            if plano:
                partes.append(f"{clave} {plano}")
    resto = " ".join(f"{k}={v}" for k, v in resultado.items()
                      if k not in ("lectura", "fichas") and _numerico(v))
    if resto:
        partes.append(resto)
    return " · ".join(partes)


def _seccion1(revision):
    if revision.get("estado") == "sin revision":
        motivo = revision.get("error") or revision.get("resumen") or "motivo desconocido"
        cuerpo = f"Sin revisión de Claude: {motivo}"
    else:
        icono = estado_icono(revision.get("estado", ""))
        cuerpo = f"{icono} {revision.get('estado', '')} - {revision.get('resumen', '')}"
    return "1. Estado\n" + cuerpo


def _linea_canario(datos):
    resultado = datos.get("resultado")
    if not isinstance(resultado, dict):
        return None
    if resultado.get("omitido"):
        return f"- canario: omitido ({resultado['omitido']})"
    if resultado.get("ok"):
        return f"- canario: ok ({datos.get('segundos', 0)} s)"
    if contratos.hay_fallo(resultado):
        paso = next((p for p, r in (resultado.get("pasos") or {}).items() if r not in ("ok", "no ejecutado")), None)
        return f"- canario: FALLA en {paso or contratos.hay_fallo(resultado)}"
    return None


def _seccion2(parte):
    lineas = []
    for etapa, datos in (parte.get("etapas") or {}).items():
        if etapa == "canario":
            linea = _linea_canario(datos)
            if linea:
                lineas.append(linea)
            continue
        resultado = datos.get("resultado")
        if not isinstance(resultado, dict):
            resultado = {}
        segundos = datos.get("segundos", 0)
        detalle = _cifras_etapa(resultado)
        linea = f"- {etapa}: {segundos} s"
        if detalle:
            linea += f" · {detalle}"
        lineas.append(linea)
    return "2. Cifras por etapa\n" + ("\n".join(lineas) or "(sin etapas)")


def _candidatas_noche(con, desde):
    sql = ("SELECT r.id AS id, r.ficha_id AS ficha_id, r.instrumento AS instrumento, r.veredicto AS veredicto,"
           " r.json AS json, r.creado AS creado, f.json AS ficha_json, l.texto AS relato FROM resultados r"
           " JOIN fichas f ON f.id = r.ficha_id LEFT JOIN relatos l ON l.resultado_id = r.id"
           " WHERE r.veredicto IN ('pasa', 'dudosa')")
    parametros = []
    if desde:
        sql += " AND r.creado >= ?"
        parametros.append(desde)
    sql += " ORDER BY r.id"
    return con.execute(sql, parametros).fetchall()


def _criterio_linea(criterio):
    marca = "si" if criterio.get("cumple") else "no"
    return f"- {criterio.get('criterio')} {criterio.get('valor')} (umbral {criterio.get('umbral')}) {marca}"


def _referencia_linea(nombre, valores):
    if not isinstance(valores, dict) or not valores:
        return None
    return nombre + ": " + " ".join(f"{k} {v}" for k, v in valores.items())


def _bloque_candidata(fila):
    ficha = json.loads(fila["ficha_json"])
    resultado = json.loads(fila["json"])
    titulo = ficha.get("titulo", ficha.get("id"))
    lineas = [f"### {titulo} · {fila['instrumento']} ({fila['veredicto']})"]
    for criterio in resultado.get("criterios") or []:
        lineas.append(_criterio_linea(criterio))
    referencias = resultado.get("referencias") or {}
    for nombre in ("vs_fuente", "vs_tipo"):
        linea = _referencia_linea(nombre, referencias.get(nombre))
        if linea:
            lineas.append(linea)
    avisos = resultado.get("avisos") or []
    if avisos:
        lineas.append("avisos: " + "; ".join(str(a) for a in avisos))
    if fila["relato"]:
        lineas.append(fila["relato"])
    return "\n".join(lineas)


def _seccion3(con, desde):
    filas = _candidatas_noche(con, desde)
    cuerpo = "\n\n".join(_bloque_candidata(f) for f in filas) or "(ninguna)"
    return "3. Candidatas y dudosas\n" + cuerpo


def _descartadas_noche(con, desde):
    sql = "SELECT estado, motivo, creado FROM fichas WHERE estado IN ('rechazada', 'no_expresable')"
    parametros = []
    if desde:
        sql += " AND creado >= ?"
        parametros.append(desde)
    sql += " ORDER BY id"
    return con.execute(sql, parametros).fetchall()


def _seccion4(con, desde):
    filas = _descartadas_noche(con, desde)
    conteo = {}
    for fila in filas:
        clave = fila["motivo"] or "(sin motivo)"
        conteo[clave] = conteo.get(clave, 0) + 1
    lineas = [f"- {motivo}: {n}" for motivo, n in conteo.items()]
    return "4. Descartes por motivo\n" + ("\n".join(lineas) or "(ninguno)")


def _seccion5(parte):
    documentos = ((parte.get("catalogo") or {}).get("documentos")) or {}
    lineas = [f"- {etapa}: {documentos[etapa]}" for etapa in ("nuevo", "leido", "criticado") if etapa in documentos]
    if parte.get("corte"):
        lineas.append("- corte: si")
    omitidas = [nombre for nombre, datos in (parte.get("etapas") or {}).items()
                if isinstance(datos.get("resultado"), dict) and datos["resultado"].get("omitido")]
    if omitidas:
        lineas.append("- omitido: " + ", ".join(omitidas))
    return "5. Pendiente\n" + ("\n".join(lineas) or "(nada pendiente)")


def _seccion6(parte, revision):
    lineas = []
    if parte.get("errores"):
        lineas.append(f"- errores totales: {parte['errores']}")
    for etapa, datos in (parte.get("etapas") or {}).items():
        detalle = contratos.hay_fallo(datos.get("resultado"))
        if detalle:
            lineas.append(f"- {detalle}" if detalle.startswith(f"{etapa}:") else f"- {etapa}: {detalle}")
    if parte.get("contrato"):
        lineas.append("- parte fuera de contrato: " + "; ".join(parte["contrato"][:3]))
    if revision.get("contrato"):
        lineas.append("- revision fuera de contrato: " + "; ".join(revision["contrato"][:3]))
    if revision.get("correo"):
        lineas.append(revision["correo"])
    return "6. Problemas y que se hizo\n" + ("\n".join(lineas) or "(sin incidencias)")


def _nota_linea(agente, nota):
    if not isinstance(nota, dict):
        return f"- nota {agente}: {nota}"
    if nota.get("pendiente"):
        return f"- nota {agente}: {nota['pendiente']}"
    if nota.get("omitido"):
        return f"- nota {agente}: {nota['omitido']}"
    if nota.get("nota_antes") is None:
        return f"- nota {agente}: aplicada sin examen"
    veredicto = "aceptada" if nota.get("aceptado") else "rechazada"
    return f"- nota {agente}: {veredicto}, nota {nota.get('nota_antes')}→{nota.get('nota_despues')}"


def _accion_linea(accion):
    if not isinstance(accion, dict):
        return f"- accion: {accion}"
    tipo = accion.get("tipo")
    ficha_id = accion.get("doc_id", accion.get("ficha_id"))
    if accion.get("hecho"):
        resultado = "hecho"
    else:
        motivo = accion.get("motivo")
        resultado = "no hecho" + (f": {motivo}" if motivo else "")
    return f"- accion {tipo} ficha {ficha_id}: {resultado}"


def _dia_antes(desde):
    try:
        return (datetime.fromisoformat(desde) - timedelta(days=1)).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return desde


def _cambios_de_la_vispera(con, desde):
    """Las notas del supervisor se aplican tras el correo: sus cambios salen en el correo del dia siguiente."""
    if not desde:
        return []
    sql = ("SELECT agente, motivo, nota_antes, nota_despues, aceptado, creado, origen FROM skills_cambios"
          " WHERE creado >= ? ORDER BY id")
    return con.execute(sql, (_dia_antes(desde),)).fetchall()


def _cambio_linea(fila):
    veredicto = "aceptado" if fila["aceptado"] else "rechazado"
    return (f"- cambio ({fila['origen'] or 'mentor'}) {fila['agente']}: {fila['motivo']}"
            f" · {fila['nota_antes']}→{fila['nota_despues']} · {veredicto} · {fila['creado']}")


def _seccion7(parte, revision, con, desde):
    lineas = []
    mentor = ((parte.get("etapas") or {}).get("mentor") or {}).get("resultado")
    if isinstance(mentor, dict):
        propuesta = mentor.get("propuesta") or {}
        if propuesta:
            lineas.append(f"- propuesta: {propuesta.get('agente')} · {propuesta.get('motivo')}")
        aplicado = mentor.get("aplicado") or {}
        if aplicado:
            lineas.append(f"- aplicado: aceptado={aplicado.get('aceptado')} nota_antes={aplicado.get('nota_antes')}"
                          f" nota_despues={aplicado.get('nota_despues')}")
    for agente, nota in (revision.get("notas") or {}).items():
        lineas.append(_nota_linea(agente, nota))
    for accion in revision.get("acciones") or []:
        lineas.append(_accion_linea(accion))
    for fila in _cambios_de_la_vispera(con, desde):
        lineas.append(_cambio_linea(fila))
    return "7. Cambios de skills y notas\n" + ("\n".join(lineas) or "(sin cambios)")


def cuerpo(fecha, parte, revision, con):
    desde = tiempos.desde_utc(parte)
    secciones = [_seccion1(revision), _seccion2(parte), _seccion3(con, desde), _seccion4(con, desde),
                 _seccion5(parte), _seccion6(parte, revision), _seccion7(parte, revision, con, desde)]
    return "\n\n".join(secciones) + "\n\nCandidata no significa rentable."


# ---------------------------------------------------------------------------
# enviar y main


def enviar(asunto_texto, cuerpo_texto, adjuntos, credencial, smtp=None):
    usuario, contrasena = credencial
    msg = EmailMessage()
    msg["Subject"] = asunto_texto
    msg["From"] = usuario
    msg["To"] = usuario
    msg.set_content(cuerpo_texto)
    for ruta in adjuntos:
        ruta = Path(ruta)
        msg.add_attachment(ruta.read_bytes(), maintype="text", subtype="markdown", filename=ruta.name)
    if smtp is None:
        import smtplib
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PUERTO, timeout=60)
    with smtp as servidor:
        servidor.login(usuario, contrasena)
        servidor.send_message(msg)


def _leer_parte(raiz, fecha):
    datos, errores = contratos.leer_parte(raiz, fecha)
    if datos is None:
        return {}, errores[0]
    if errores and "contrato" not in datos:
        datos["contrato"] = errores
    return datos, ""


def cuerpo_sin_parte(raiz, fecha, motivo):
    partes = [f"Sin parte de la noche: {motivo}"]
    revision_ruta = raiz / "supervisor" / f"revision_{fecha}.json"
    if revision_ruta.exists():
        partes.append("Revision del supervisor:\n" + revision_ruta.read_text(encoding="utf-8", errors="replace"))
    else:
        partes.append("Revision del supervisor: (sin fichero de revision)")
    log_ruta = raiz / "registro" / f"noche_{fecha}.log"
    if log_ruta.exists():
        lineas = log_ruta.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
        partes.append("Ultimas lineas del registro de la noche:\n" + "\n".join(lineas))
    else:
        partes.append("Sin registro de la noche.")
    return "\n\n".join(partes)


def _entregar(raiz, fecha, texto_asunto, texto_cuerpo, codigo, args, smtp, obtener):
    borrador_ruta = raiz / "informes" / f"correo_{fecha}.txt"

    def _escribir_borrador():
        borrador_ruta.parent.mkdir(parents=True, exist_ok=True)
        borrador_ruta.write_text(texto_asunto + "\n\n" + texto_cuerpo, encoding="utf-8")

    if args.borrador:
        _escribir_borrador()
        return codigo

    cred = credencial(obtener=obtener)
    if cred is None:
        _escribir_borrador()
        print(json.dumps({"omitido": "sin credencial"}, ensure_ascii=False))
        return 1

    informe_ruta = raiz / "informes" / f"informe_{fecha}.md"
    adjuntos = [informe_ruta] if informe_ruta.exists() else []
    try:
        enviar(texto_asunto, texto_cuerpo, adjuntos, cred, smtp=smtp)
    except Exception as e:
        _escribir_borrador()
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    return codigo


def main(argv=None, con=None, smtp=None, obtener=None):
    parser = argparse.ArgumentParser(description="Correo de la manana con el resumen de la noche")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--fecha")
    parser.add_argument("--borrador", action="store_true")
    parser.add_argument("--guardar-credencial")
    args = parser.parse_args(argv)

    if args.guardar_credencial:
        import getpass
        contrasena = getpass.getpass(f"Contrasena de aplicacion para {args.guardar_credencial}: ")
        guardar_credencial(args.guardar_credencial, contrasena)
        return 0

    raiz = Path(args.raiz)
    fecha = args.fecha or tiempos.fecha_local()
    parte, motivo = _leer_parte(raiz, fecha)
    if motivo:
        print(json.dumps({"error": motivo}, ensure_ascii=False))
        return _entregar(raiz, fecha, f"[Quant] {_fecha_corta(fecha)} · sin parte · {ICONOS['parada']}",
                         cuerpo_sin_parte(raiz, fecha, motivo), 0, args, smtp, obtener)

    cerrar_con = con is None
    con = con or catalogo.abrir(raiz / "catalogo.db")
    try:
        revision, errores_revision = contratos.leer_revision(raiz, fecha)
        if revision is None:
            revision = {"estado": "sin revision", "error": "; ".join(errores_revision)}
        elif errores_revision:
            if revision.get("estado") in contratos.ESTADOS_REVISION:
                revision = {**revision, "contrato": errores_revision}
            else:
                revision = {**revision, "estado": "sin revision", "error": "; ".join(errores_revision)}
        try:
            texto_asunto = asunto(fecha, parte, revision)
            texto_cuerpo = cuerpo(fecha, parte, revision, con)
        except Exception as e:
            errores_contrato = parte.get("contrato") or []
            motivo = (f"el parte esta fuera de contrato y no se pudo resumir: {type(e).__name__}: {e}; "
                     + "; ".join(errores_contrato[:3]))
            print(json.dumps({"error": motivo}, ensure_ascii=False))
            return _entregar(raiz, fecha, f"[Quant] {_fecha_corta(fecha)} · sin parte · {ICONOS['parada']}",
                             cuerpo_sin_parte(raiz, fecha, motivo), 0, args, smtp, obtener)
        return _entregar(raiz, fecha, texto_asunto, texto_cuerpo, 0, args, smtp, obtener)
    finally:
        if cerrar_con:
            con.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
