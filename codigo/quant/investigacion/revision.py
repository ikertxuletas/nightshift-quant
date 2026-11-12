"""Supervisor: revision de Claude a las 06:15 sobre el trabajo de la noche."""
import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import criterios, rutas
from quant.investigacion import agentes, candados, catalogo, claude_cli, contratos, examen, local, mentor, tiempos

MAX_BYTES = 60000
MAX_BYTES_PARTE = 15000
MAX_LISTA = 20
MARCA_RECORTE = "[paquete recortado]"
PENDIENTE_NOTA = "se evaluará con el examen tras este correo; el resultado saldrá en el correo de mañana"
MAX_NOTA = 300
LIMITE_TAREA = contratos.LIMITE_REVISION_HORAS * 3600
AGENTES_NOTAS = ("lector", "formalizador", "critico", "relator")
AGENTES_EXAMEN = ("lector", "formalizador", "critico")
GPU_LOCK = candados.GPU


class ErrorRevision(RuntimeError):
    pass


CLAUDE_EXE = claude_cli.CLAUDE_EXE


# ---------------------------------------------------------------------------
# paquete


def _fecha_iso(fecha):
    return f"{fecha[0:4]}-{fecha[4:6]}-{fecha[6:8]}T00:00:00"


def _candidatas(con, desde):
    # Sweep fichas (doc_id NULL) are judged by the engine's numbers, not against a paper: not reviewed here.
    return con.execute(
        "SELECT r.id AS id, r.ficha_id AS ficha_id, r.instrumento AS instrumento, r.veredicto AS veredicto,"
        " r.json AS json, f.json AS ficha_json, l.texto AS relato FROM resultados r"
        " JOIN fichas f ON f.id = r.ficha_id LEFT JOIN relatos l ON l.resultado_id = r.id"
        " WHERE r.veredicto IN ('pasa', 'dudosa') AND f.doc_id IS NOT NULL AND r.creado >= ?"
        " ORDER BY r.id", (desde,)).fetchall()


def _motivo_no_pasa(datos):
    """validacion.evaluar no pone 'motivo' en un veredicto no_pasa: se reconstruye con los criterios incumplidos."""
    if datos.get("motivo"):
        return datos["motivo"]
    fallos = [c for c in (datos.get("criterios") or []) if not c.get("cumple", True)]
    if not fallos:
        return ""
    return "; ".join(f"{c.get('criterio')} {c.get('valor')} (umbral {c.get('umbral')})" for c in fallos)


def _pool_descartes(con):
    pool = []
    for fila in con.execute("SELECT id, ficha_id, json FROM resultados WHERE veredicto = 'no_pasa' ORDER BY id"):
        datos = json.loads(fila["json"])
        pool.append({"tipo": "no_pasa", "id": fila["id"], "ficha_id": fila["ficha_id"],
                     "motivo": _motivo_no_pasa(datos)})
    for tabla_estado in ("rechazada", "no_expresable"):
        for fila in con.execute("SELECT id, motivo FROM fichas WHERE estado = ? ORDER BY id", (tabla_estado,)):
            pool.append({"tipo": tabla_estado, "id": fila["id"], "motivo": fila["motivo"]})
    return pool


def _descartes(con, azar, n=3):
    pool = _pool_descartes(con)
    return azar.sample(pool, min(n, len(pool)))


def _bloque_candidata(fila, con_relato=True, con_criterios=True):
    ficha = json.loads(fila["ficha_json"])
    resultado = json.loads(fila["json"])
    if not con_criterios:
        resultado = {k: v for k, v in resultado.items() if k != "criterios"}
    partes = [f"### ficha {fila['ficha_id']} - {fila['instrumento']} ({fila['veredicto']})",
              agentes.vallar(json.dumps(ficha, ensure_ascii=False)),
              agentes.vallar(json.dumps(resultado, ensure_ascii=False))]
    if con_relato and fila["relato"]:
        partes.append(agentes.vallar(fila["relato"]))
    return "\n".join(partes)


def _bloque_descarte(descarte):
    return agentes.vallar(json.dumps(descarte, ensure_ascii=False))


def _skills_cambios_noche(con, desde):
    filas = con.execute(
        "SELECT agente, motivo, nota_antes, nota_despues, aceptado, creado FROM skills_cambios"
        " WHERE creado >= ? ORDER BY id", (desde,)).fetchall()
    return [dict(f) for f in filas]


def _seccion_candidatas(candidatas, con_relato=True, con_criterios=True, omitidas=0):
    cuerpo = "\n\n".join(_bloque_candidata(f, con_relato, con_criterios) for f in candidatas) or "(ninguna)"
    if omitidas:
        cuerpo += f"\n\n({omitidas} candidatas mas omitidas por espacio)"
    return f"## Candidatas y dudosas\n{cuerpo}"


def _seccion_descartes(descartes):
    cuerpo = "\n\n".join(_bloque_descarte(d) for d in descartes) or "(ninguno)"
    return f"## Descartes al azar\n{cuerpo}"


def _resumir_valor(valor):
    if isinstance(valor, dict):
        return {k: _resumir_valor(v) for k, v in valor.items()}
    if isinstance(valor, list):
        if len(valor) > MAX_LISTA:
            return {"total": len(valor), "primeros": [_resumir_valor(v) for v in valor[:5]]}
        return [_resumir_valor(v) for v in valor]
    return valor


def _sin_instrumentos(parte):
    """De la lista por instrumento de precios solo interesan cuantos son y cuales fallaron."""
    etapas = parte.get("etapas")
    precios = etapas.get("precios") if isinstance(etapas, dict) else None
    resultado = precios.get("resultado") if isinstance(precios, dict) else None
    instrumentos = resultado.get("instrumentos") if isinstance(resultado, dict) else None
    if not isinstance(instrumentos, list):
        return parte
    resumen = {"total": len(instrumentos),
               "con_error": [i for i in instrumentos if isinstance(i, dict) and i.get("error") is not None]}
    return {**parte, "etapas": {**etapas,
                                "precios": {**precios, "resultado": {**resultado, "instrumentos": resumen}}}}


def _contenido_parte(raiz, fecha, parte, fuera):
    """Distingue 'no existe' (sin parte), 'ilegible' (JSON roto o no objeto: se adjunta el crudo) y
    'legible pero fuera de contrato' (objeto con campos que no cuadran)."""
    if not contratos.existe_parte(raiz, fecha):
        motivo = fuera[0] if fuera else "no existe"
        return f"Sin parte de la noche: {motivo}"
    if parte is None:
        ruta = Path(raiz) / "informes" / f"parte_{fecha}.json"
        try:
            crudo = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            crudo = ""
        return crudo[:2000]
    texto = json.dumps(_resumir_valor(_sin_instrumentos(parte)), ensure_ascii=False)
    if fuera:
        texto = "Parte fuera de contrato: " + "; ".join(fuera[:5]) + "\n" + texto
    return texto


def _seccion_parte(texto):
    crudo = texto.encode("utf-8")
    if len(crudo) > MAX_BYTES_PARTE:
        texto = crudo[:MAX_BYTES_PARTE].decode("utf-8", errors="ignore")
    return f"## Parte de la noche\n{agentes.vallar(texto)}"


MAX_EXPERIMENTOS_JUEZ = 15


def _seccion_laboratorio(con, noche, parte):
    """What the morning mail's judge reads. It goes to the owner only: nothing here returns to the lab agent."""
    from quant.familias import propias
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_experimentos'").fetchone():
        return "## Laboratorio\n(el laboratorio no ha corrido)"
    etapa = ((parte.get("etapas") or {}).get("laboratorio") or {}).get("resultado") or {}
    datos = {"tandas_de_la_noche_todas_las_estrategias": {k: etapa.get(k) for k in ("tandas", "propuestos", "repetidos", "probados",
                                                              "ganadoras", "parado") if k in etapa},
             "estrategias": []}
    for p in propias.PROPIAS.values():
        filas = con.execute("SELECT motivo, cambios, veredicto, entreno_json, examen_json FROM lab_experimentos"
                            " WHERE estrategia = ? AND noche = ? ORDER BY id LIMIT ?",
                            (p.name, noche, MAX_EXPERIMENTOS_JUEZ)).fetchall()
        experimentos = []
        for f in filas:
            total = ((json.loads(f["entreno_json"]) if f["entreno_json"] else {}).get("metricas") or {}).get("total") or {}
            examen = json.loads(f["examen_json"]) if f["examen_json"] else None
            experimentos.append({"motivo": f["motivo"], "cambios": f["cambios"], "veredicto": f["veredicto"],
                                 "entreno": {k: total.get(k) for k in ("profit_factor", "operaciones", "drawdown")},
                                 **({"examen_profit_factor": examen.get("profit_factor")} if examen else {})})
        vigentes = con.execute("SELECT COUNT(*) FROM lab_ganadoras WHERE estrategia = ? AND estado = 'vigente'",
                               (p.name,)).fetchone()[0]
        base = con.execute("SELECT entreno_json FROM lab_experimentos WHERE estrategia = ? AND cambios = 0"
                           " AND entreno_json IS NOT NULL ORDER BY id DESC LIMIT 1", (p.name,)).fetchone()
        base_total = ((json.loads(base[0]).get("metricas") or {}).get("total") or {}) if base else {}
        total_hasta_hoy = con.execute("SELECT COUNT(*) FROM lab_experimentos WHERE estrategia = ?",
                                      (p.name,)).fetchone()[0]
        datos["estrategias"].append({"estrategia": p.name, "origen": p.origen,
                                     "experimentos_hasta_hoy": total_hasta_hoy,
                                     "base_entreno": {k: base_total.get(k) for k in ("profit_factor", "operaciones",
                                                                                     "drawdown")} if base else None,
                                     "experimentos": experimentos,
                                     "ganadoras_vigentes": vigentes})
    return f"## Laboratorio\n{agentes.vallar(json.dumps(datos, ensure_ascii=False))}"


def _seccion_asesor(con, fecha):
    """The weekly advisor's reports from the last 2 days, for the Monday mail."""
    from datetime import date, timedelta
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lab_asesor'").fetchone():
        return "## Asesor semanal\n(sin informe reciente)"
    dia = date(int(fecha[:4]), int(fecha[4:6]), int(fecha[6:]))
    filas = con.execute("SELECT estrategia, fecha, informe, direccion_es, propuestas_json FROM lab_asesor"
                        " WHERE fecha >= ? AND fecha <= ? ORDER BY id", ((dia - timedelta(days=2)).isoformat(),
                                                                          dia.isoformat())).fetchall()
    if not filas:
        return "## Asesor semanal\n(sin informe reciente)"
    datos = [{"estrategia": f["estrategia"], "fecha": f["fecha"], "informe": f["informe"],
              "direccion": (f["direccion_es"] or "").splitlines(), "propuestas": json.loads(f["propuestas_json"] or "[]")}
             for f in filas]
    return f"## Asesor semanal\n{agentes.vallar(json.dumps(datos, ensure_ascii=False))}"


def paquete(con, raiz, fecha, azar=None):
    import random
    raiz = Path(raiz)
    azar = azar or random.Random(fecha)

    parte, fuera = contratos.leer_parte(raiz, fecha)
    texto_parte = _contenido_parte(raiz, fecha, parte, fuera)
    parte = parte or {}

    desde = tiempos.desde_utc(parte) or _fecha_iso(fecha)
    candidatas = _candidatas(con, desde)
    descartes = _descartes(con, azar, n=3)
    errores = mentor.errores_de_la_noche(con, desde)["conteo"]
    cambios = _skills_cambios_noche(con, desde)

    secciones = {
        "parte": _seccion_parte(texto_parte),
        "candidatas": _seccion_candidatas(candidatas),
        "laboratorio": _seccion_laboratorio(con, f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}", parte),
        "asesor": _seccion_asesor(con, fecha),
        "descartes": _seccion_descartes(descartes),
        "errores": f"## Conteo de errores de la noche\n{json.dumps(errores, ensure_ascii=False)}",
        "skills": f"## Cambios de skills de la noche\n{agentes.vallar(json.dumps(cambios, ensure_ascii=False))}",
    }
    orden = ("parte", "candidatas", "laboratorio", "asesor", "descartes", "errores", "skills")

    def _texto():
        return "\n\n".join(secciones[k] for k in orden)

    texto = _texto()
    if len(texto.encode("utf-8")) <= MAX_BYTES:
        return texto

    limite = MAX_BYTES - len(MARCA_RECORTE.encode("utf-8")) - 1

    secciones["descartes"] = "## Descartes al azar\n(omitidos por espacio)"
    texto = _texto()
    if len(texto.encode("utf-8")) <= limite:
        return texto + "\n" + MARCA_RECORTE

    secciones["candidatas"] = _seccion_candidatas(candidatas, con_relato=False)
    texto = _texto()
    if len(texto.encode("utf-8")) <= limite:
        return texto + "\n" + MARCA_RECORTE

    secciones["candidatas"] = _seccion_candidatas(candidatas, con_relato=False, con_criterios=False)
    texto = _texto()
    if len(texto.encode("utf-8")) <= limite:
        return texto + "\n" + MARCA_RECORTE

    # Drop whole candidates from the end before touching other sections: never cut inside a fence.
    for n in range(len(candidatas) - 1, -1, -1):
        secciones["candidatas"] = _seccion_candidatas(candidatas[:n], con_relato=False, con_criterios=False,
                                                      omitidas=len(candidatas) - n)
        texto = _texto()
        if len(texto.encode("utf-8")) <= limite:
            return texto + "\n" + MARCA_RECORTE

    # Ultimo recurso por secciones enteras, de menos a mas importante: el parte es lo ultimo que se quita.
    for clave, titulo in (("skills", "Cambios de skills de la noche"), ("errores", "Conteo de errores de la noche"),
                          ("asesor", "Asesor semanal"), ("laboratorio", "Laboratorio"),
                          ("parte", "Parte de la noche")):
        secciones[clave] = f"## {titulo}\n(omitida por espacio)"
        texto = _texto()
        if len(texto.encode("utf-8")) <= limite:
            break
    return texto + "\n" + MARCA_RECORTE


# ---------------------------------------------------------------------------
# pedir


def _recorte_externo(texto, limite=500):
    return agentes.vallar((texto or "").strip()[:limite])


_limpiar_ajustes = claude_cli.limpiar_ajustes


def pedir(paquete_texto, ejecutar=None, timeout=900, modelo="opus", cwd=None, raiz=None, dormir=time.sleep,
         reloj=time.monotonic):
    raiz = Path(raiz) if raiz is not None else rutas.RAIZ
    cwd_real = Path(cwd) if cwd is not None else (raiz / "supervisor")

    def _ejecutar_defecto(argumentos, entrada, timeout):
        proc = subprocess.run(argumentos, input=entrada, text=True, encoding="utf-8", errors="replace",
                              capture_output=True, timeout=timeout, cwd=cwd_real, creationflags=0x08000000)
        return proc.returncode, proc.stdout, proc.stderr

    ejecutar = ejecutar or _ejecutar_defecto
    try:
        system = (raiz / "supervisor" / "CLAUDE.md").read_text(encoding="utf-8")
    except OSError as e:
        raise ErrorRevision(f"no se pudo leer supervisor/CLAUDE.md: {e}") from e
    argumentos = [CLAUDE_EXE, "-p", "--model", modelo, "--output-format", "text", "--tools", "",
                  "--strict-mcp-config", "--append-system-prompt", system]

    with candados.turno(candados.CLAUDE, dormir=dormir, reloj=reloj):
        try:
            codigo, salida, error = ejecutar(argumentos, paquete_texto, timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise ErrorRevision(f"fallo al ejecutar claude: {e}") from e
        finally:
            _limpiar_ajustes(cwd_real)

    if codigo != 0:
        # claude avisa del login caducado o del limite de uso por stdout, no por stderr.
        raise ErrorRevision(f"claude devolvio codigo {codigo}: stderr {_recorte_externo(error)}"
                            f" stdout {_recorte_externo(salida)}")
    if not salida or not salida.strip():
        raise ErrorRevision("claude devolvio una salida vacia")
    try:
        datos = local.json_de(salida)
    except local.ErrorModelo as e:
        raise ErrorRevision(f"respuesta de claude ilegible: {e}") from e

    faltantes = [c for c in ("estado", "resumen", "correo", "notas", "acciones") if c not in datos]
    if faltantes:
        raise ErrorRevision(f"faltan claves en la respuesta de claude: {', '.join(faltantes)}")

    if datos["estado"] not in ("ok", "aviso", "parada"):
        raise ErrorRevision(f"estado invalido en la respuesta de claude: {datos['estado']!r}")
    notas_resp = datos["notas"]
    if not isinstance(notas_resp, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in notas_resp.items()):
        raise ErrorRevision("notas debe ser un diccionario de texto a texto")
    acciones_resp = datos["acciones"]
    if not isinstance(acciones_resp, list) or not all(isinstance(a, dict) for a in acciones_resp):
        raise ErrorRevision("acciones debe ser una lista de objetos")
    return datos


# ---------------------------------------------------------------------------
# aplicar


def _marcar_accion(accion, hecho, motivo=None):
    salida = dict(accion)
    salida["hecho"] = hecho
    if motivo is not None:
        salida["motivo"] = motivo
    else:
        salida.setdefault("motivo", "")
    return salida


def _aplicar_accion(con, accion):
    tipo = accion.get("tipo")
    if tipo == "reencolar":
        doc_id = accion.get("doc_id")
        fila = con.execute("SELECT id FROM documentos WHERE id = ?", (doc_id,)).fetchone()
        if fila is None:
            return _marcar_accion(accion, False, "documento inexistente")
        catalogo.marcar(con, doc_id, "nuevo")
        con.execute("UPDATE documentos SET intentos = 0 WHERE id = ?", (doc_id,))
        con.commit()
        return _marcar_accion(accion, True)
    if tipo == "invalidar_ficha":
        ficha_id = accion.get("ficha_id")
        fila = con.execute("SELECT id FROM fichas WHERE id = ?", (ficha_id,)).fetchone()
        if fila is None:
            return _marcar_accion(accion, False, "ficha inexistente")
        con.execute("UPDATE fichas SET estado = 'invalidada', motivo = ? WHERE id = ?",
                    (accion.get("motivo", ""), ficha_id))
        con.commit()
        return _marcar_accion(accion, True)
    return _marcar_accion(accion, False, f"tipo de accion desconocido: {tipo}")


def _nota_limpia(texto):
    """La nota de Claude entra tal cual en notas.md: una sola linea, corta y sin marcas de valla."""
    plano = " ".join((texto or "").split())
    if not plano or "<<<" in plano or ">>>" in plano:
        return None
    return plano[:MAX_NOTA]


def _aplicar_nota(con, raiz_skills, agente, texto, evaluar, llamar, notas, ahora, hasta=None, reloj=time.monotonic):
    if agente not in AGENTES_NOTAS:
        return {"omitido": f"el supervisor no admite notas para {agente}"}
    texto = _nota_limpia(texto)
    if texto is None:
        return {"omitido": "nota vacia o con marcas de valla"}

    ruta_notas = raiz_skills / agente / "notas.md"
    anterior = ruta_notas.read_text(encoding="utf-8") if ruta_notas.exists() else ""
    fecha_nota = ahora.strftime("%Y-%m-%d")
    nuevo = anterior.rstrip("\n") + f"\n- {fecha_nota}: {texto}\n"

    if agente not in AGENTES_EXAMEN:
        ruta_notas.parent.mkdir(parents=True, exist_ok=True)
        if ruta_notas.exists():
            marca = ahora.strftime("%Y%m%d_%H%M%S")
            copia = raiz_skills / agente / "historial" / f"{marca}_notas.md"
            copia.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ruta_notas, copia)
        ruta_notas.write_text(nuevo, encoding="utf-8")
        catalogo.registrar_cambio_skill(con, agente, texto, None, None, True, origen="supervisor")
        return {"aceptado": True, "nota_antes": None, "nota_despues": None}

    propuesta = {"agente": agente, "fichero": "notas.md", "texto_nuevo": nuevo, "motivo": texto}
    resultado = mentor.aplicar_con_examen(propuesta, con, raiz_skills=raiz_skills, evaluar=evaluar,
                                          notas=notas, llamar=llamar, ahora=ahora, permitir_notas=True,
                                          hasta=hasta, reloj=reloj, origen="supervisor")
    return {"aceptado": resultado["aceptado"], "nota_antes": resultado["nota_antes"],
            "nota_despues": resultado["nota_despues"]}


def aplicar_acciones(con, respuesta):
    salida = []
    for accion in (respuesta.get("acciones") or []):
        try:
            salida.append(_aplicar_accion(con, accion))
        except Exception as e:
            con.rollback()
            salida.append(_marcar_accion(accion, False, f"{type(e).__name__}: {e}"))
    return salida


def aplicar_notas(con, raiz, respuesta, evaluar=examen.evaluar, llamar=claude_cli.chat, notas=None, ahora=None,
                  hasta=None, reloj=time.monotonic):
    raiz = Path(raiz)
    raiz_skills = raiz / "skills"
    notas = Path(notas) if notas is not None else raiz / "examen" / "notas.json"
    ahora = ahora or datetime.now(timezone.utc)

    salida = {}
    with candados.turno(GPU_LOCK, reloj=reloj):
        for agente, texto in (respuesta.get("notas") or {}).items():
            if hasta is not None and hasta - reloj() < mentor.TIEMPO_MINIMO:
                salida[agente] = {"omitido": "sin tiempo"}
                continue
            try:
                salida[agente] = _aplicar_nota(con, raiz_skills, agente, texto, evaluar, llamar, notas, ahora,
                                               hasta=hasta, reloj=reloj)
            except Exception as e:
                salida[agente] = {"omitido": f"{type(e).__name__}: {e}"}
    return salida


def aplicar(con, raiz, respuesta, evaluar=examen.evaluar, llamar=claude_cli.chat, notas=None, ahora=None,
            hasta=None, reloj=time.monotonic):
    return {"notas": aplicar_notas(con, raiz, respuesta, evaluar=evaluar, llamar=llamar, notas=notas, ahora=ahora,
                                   hasta=hasta, reloj=reloj),
            "acciones": aplicar_acciones(con, respuesta)}


# ---------------------------------------------------------------------------
# comprobar_criterios y main


def comprobar_criterios(raiz):
    try:
        criterios.cargar(Path(raiz) / "config")
        return ""
    except (criterios.ErrorCriterios, OSError, ValueError) as e:
        return str(e)


def _registrar(raiz, fecha, estado, bytes_paquete, segundos, error, correo=None):
    carpeta = Path(raiz) / "registro"
    carpeta.mkdir(parents=True, exist_ok=True)
    linea = {"fecha": fecha, "estado": estado, "paquete_bytes": bytes_paquete,
             "segundos": round(segundos, 1), "error": error, "correo": correo}
    with open(carpeta / f"revision_{fecha}.log", "a", encoding="utf-8") as log:
        log.write(json.dumps(linea, ensure_ascii=False) + "\n")


def main(argv=None, ejecutar=None, evaluar=examen.evaluar, llamar=None, ahora=None):
    parser = argparse.ArgumentParser(description="Supervisor: revision de Claude a las 06:15")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--fecha")
    parser.add_argument("--sin-claude", action="store_true")
    parser.add_argument("--correo", action="store_true")
    args = parser.parse_args(argv)

    raiz = Path(args.raiz)
    ahora = ahora or datetime.now(timezone.utc)
    fecha = args.fecha or tiempos.fecha_local(ahora)
    inicio = time.monotonic()
    llamar = llamar or claude_cli.chat
    try:
        config_agentes = json.loads((raiz / "config" / "agentes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config_agentes = {}
    claude_cli.reiniciar(config_agentes.get("_tope_llamadas_revision"))
    con = catalogo.abrir(raiz / "catalogo.db")

    restauradas = []
    try:
        restauradas = mentor.restaurar_huerfanas(con, raiz / "skills")
    except Exception:
        pass

    salida = {"fecha": fecha, "estado": "", "resumen": "", "correo": "", "criterios": "",
              "paquete_bytes": 0, "notas": {}, "acciones": [], "error": ""}
    codigo_correo = None

    def _escribir():
        salida.pop("contrato", None)
        fuera = contratos.validar_revision(salida)
        if fuera:
            salida["contrato"] = fuera
        destino = raiz / "supervisor" / f"revision_{fecha}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(salida, indent=1, ensure_ascii=False), encoding="utf-8")

    try:
        respuesta = None
        mensaje_criterios = comprobar_criterios(raiz)
        salida["criterios"] = mensaje_criterios
        if mensaje_criterios:
            salida["estado"] = "parada"
            salida["resumen"] = f"criterios.json no cuadra con su firma: {mensaje_criterios}"
            salida["correo"] = salida["resumen"]
        else:
            if args.sin_claude:
                salida["estado"] = "sin revision"
                salida["resumen"] = "Ejecutado con --sin-claude: no se ha llamado a Claude."
                salida["correo"] = salida["resumen"]
            else:
                texto = paquete(con, raiz, fecha)
                salida["paquete_bytes"] = len(texto.encode("utf-8"))
                try:
                    respuesta = pedir(texto, ejecutar=ejecutar, raiz=raiz)
                except ErrorRevision as e:
                    salida["estado"] = "sin revision"
                    salida["error"] = str(e)
                    salida["resumen"] = "No se pudo completar la revision de Claude."
                    salida["correo"] = salida["resumen"]
                else:
                    salida["estado"] = respuesta["estado"]
                    salida["resumen"] = respuesta["resumen"]
                    salida["correo"] = respuesta["correo"]
                    salida["notas"] = {agente: {"pendiente": PENDIENTE_NOTA}
                                       for agente in (respuesta.get("notas") or {})}

        if restauradas:
            aviso = f"Se restauraron {len(restauradas)} skills que quedaron a medias."
            salida["correo"] = (salida["correo"] + " " + aviso).strip()

        # El orden importa: primero el fichero y el correo, y solo despues los examenes, que pueden tardar horas.
        _escribir()
        if respuesta is not None:
            salida["acciones"] = aplicar_acciones(con, respuesta)
            _escribir()

        if args.correo:
            from quant.investigacion import correo
            codigo_correo = correo.main(["--raiz", str(raiz), "--fecha", fecha])
            # El correo ya salio (o no); registrarlo ya para que el vigilante de las 07:30 no lo de
            # por perdido si los examenes que vienen a continuacion tardan hasta 2h o la tarea se mata.
            _registrar(raiz, fecha, salida["estado"], salida["paquete_bytes"], time.monotonic() - inicio,
                      salida["error"], codigo_correo)

        if respuesta is not None and respuesta.get("notas"):
            try:
                salida["notas"] = aplicar_notas(con, raiz, respuesta, evaluar=evaluar, llamar=llamar, ahora=ahora,
                                                hasta=inicio + LIMITE_TAREA - contratos.MARGEN_EXAMEN_MINUTOS * 60)
            except Exception as e:
                salida["notas"] = {agente: {"omitido": f"{type(e).__name__}: {e}"} for agente in respuesta["notas"]}
            _escribir()
        try:
            contratos.guardar_real(raiz, "revision", salida)
        except Exception:
            pass
        return 0
    finally:
        _registrar(raiz, fecha, salida["estado"], salida["paquete_bytes"], time.monotonic() - inicio,
                  salida["error"], codigo_correo)
        con.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
