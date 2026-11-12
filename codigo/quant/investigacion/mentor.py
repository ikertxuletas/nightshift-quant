"""Mentor: agrupa los errores de la noche y propone un unico cambio de skill, vigilado por el examen."""
import ctypes
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import rutas
from quant.investigacion import agentes, catalogo, claude_cli, examen, local, salida, skills

AGENTES_EXAMINADOS = ("lector", "formalizador", "critico")

TIEMPO_MINIMO = 15 * 60

NO_CONCLUYENTE = "examen no concluyente"

MAX_HORAS_MARCADOR = 6
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5


def _vivo_defecto(pid):
    """Windows: OpenProcess + GetExitCodeProcess. Acceso denegado (error 5) significa que el proceso existe
    pero es de otro usuario o elevado: vivo. Cualquier otro fallo al abrirlo: no existe."""
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.windll.kernel32.GetLastError() == ERROR_ACCESS_DENIED
    try:
        codigo = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(codigo)):
            raise OSError("GetExitCodeProcess fallo")
        return codigo.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _concluyente(resultado):
    """Sin casos, o con todos los casos caidos, el examen no mide nada: aceptar seria aceptar a ciegas."""
    if not isinstance(resultado, dict):
        return False
    if "concluyente" in resultado:
        return bool(resultado["concluyente"])
    if not resultado.get("casos"):
        return False
    detalle = resultado.get("detalle") or []
    return not (detalle and all(caso.get("error") for caso in detalle))


def _hojas_json(texto):
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return {}


def errores_de_la_noche(con, desde):
    # Como en diagnostico.py: etapa='error' (reintentos agotados) o error en curso en 'nuevo'/'leido'.
    # 'descartado' y 'no_expresable' reutilizan la columna error para guardar el motivo del agente,
    # no un fallo real, y no deben contarse (aunque conserven un texto de un intento anterior).
    documentos_error = [
        {"id": f["id"], "fuente": f["fuente"], "etapa": f["etapa"], "error": f["error"]}
        for f in con.execute(
            "SELECT id, fuente, etapa, error FROM documentos WHERE actualizado >= ? AND"
            " (etapa = 'error' OR (error IS NOT NULL AND etapa IN ('nuevo', 'leido'))) ORDER BY id",
            (desde,))]
    fichas_rechazadas = [
        {"id": f["id"], "motivo": f["motivo"]}
        for f in con.execute(
            "SELECT id, motivo FROM fichas WHERE creado >= ? AND estado = 'rechazada' ORDER BY id", (desde,))]
    no_expresables = [
        {"id": f["id"], "motivo": f["motivo"]}
        for f in con.execute(
            "SELECT id, motivo FROM fichas WHERE creado >= ? AND estado = 'no_expresable' ORDER BY id", (desde,))]
    fichas_invalidas = [
        {"ficha_id": f["ficha_id"], "errores": _hojas_json(f["json"]).get("errores", [])}
        for f in con.execute(
            "SELECT ficha_id, json FROM resultados WHERE creado >= ? AND veredicto = 'ficha_invalida' ORDER BY id",
            (desde,))]
    conteo = {"documentos_error": len(documentos_error), "fichas_rechazadas": len(fichas_rechazadas),
              "no_expresables": len(no_expresables), "fichas_invalidas": len(fichas_invalidas)}
    return {"documentos_error": documentos_error, "fichas_rechazadas": fichas_rechazadas,
            "no_expresables": no_expresables, "fichas_invalidas": fichas_invalidas, "conteo": conteo}


def historial(con):
    filas = con.execute(
        "SELECT agente, motivo, nota_antes, nota_despues, aceptado, creado FROM skills_cambios"
        " ORDER BY id DESC LIMIT 30").fetchall()
    filas = list(reversed(filas))
    lineas = ["| agente | motivo | nota antes | nota despues | aceptado | fecha |",
              "| --- | --- | --- | --- | --- | --- |"]
    for f in filas:
        lineas.append(f"| {f['agente']} | {f['motivo']} | {f['nota_antes']} | {f['nota_despues']} |"
                      f" {'si' if f['aceptado'] else 'no'} | {f['creado']} |")
    return "\n".join(lineas)


def _skills_actuales(raiz_skills):
    """Skills propias vistas por el Mentor: valladas con un delimitador propio, sin tocar su contenido
    (a diferencia de agentes.vallar, que desactivaria la linea de datos no confiables que ya traen)."""
    partes = []
    for agente in AGENTES_EXAMINADOS:
        cargado = skills.cargar(agente, raiz=raiz_skills)
        partes.append(f"<<<SKILL {agente}/skill.md\n{cargado['skill']}\nSKILL>>>")
        nombres = sorted(cargado["referencias"])
        if nombres:
            partes.append(f"<<<SKILL {agente}/ref\n{', '.join(nombres)}\nSKILL>>>")
    return "\n\n".join(partes)


def _lineas_confiables(texto):
    return [linea for linea in texto.splitlines() if "<<<DOCUMENTO" in linea or "DOCUMENTO>>>" in linea]


def _validar_propuesta(propuesta, raiz_skills):
    agente = propuesta.get("agente")
    if agente not in AGENTES_EXAMINADOS:
        return f"agente invalido: {agente!r}"
    fichero = propuesta.get("fichero") or ""
    if ".." in Path(fichero).parts:
        return f"fichero fuera de la carpeta del agente: {fichero!r}"
    carpeta_agente = (raiz_skills / agente).resolve()
    ruta = (raiz_skills / agente / fichero).resolve()
    if carpeta_agente not in ruta.parents and ruta != carpeta_agente:
        return f"fichero fuera de la carpeta del agente: {fichero!r}"
    if ruta.name == "notas.md":
        return "no se puede proponer notas.md"
    if not ruta.is_file():
        return f"fichero inexistente: {fichero!r}"
    texto_nuevo = propuesta.get("texto_nuevo") or ""
    if not texto_nuevo.strip():
        return "texto_nuevo vacio"
    original = ruta.read_text(encoding="utf-8")
    if not (0.5 * len(original) <= len(texto_nuevo) <= 2 * len(original)):
        return "texto_nuevo con longitud fuera de 0.5x-2x el original"
    lineas_originales = _lineas_confiables(original)
    if lineas_originales:
        lineas_nuevas = set(texto_nuevo.splitlines())
        if not all(linea in lineas_nuevas for linea in lineas_originales):
            return "pierde la linea de datos no confiables"
    return None


def proponer(errores, con, config=None, raiz_skills=None, llamar=claude_cli.chat, modelo=None):
    raiz_skills = Path(raiz_skills or rutas.RAIZ / "skills")
    sistema = (skills.system("mentor", raiz=raiz_skills) + "\n\n## Historial de cambios\n" + historial(con) +
              "\n\n## Skills actuales\n" + _skills_actuales(raiz_skills))
    ajuste = agentes.ajustes("mentor", config)
    modelo_usado = modelo or ajuste["modelo"]
    prompt = f"Errores de la noche:\n{agentes.vallar(json.dumps(errores, ensure_ascii=False))}"

    try:
        respuesta = llamar(modelo_usado, sistema, prompt, formato=ajuste["formato"], opciones=ajuste["opciones"])
        datos = local.json_de(respuesta)
    except local.ErrorModelo as e:
        return {"agente": None, "motivo": f"modelo: {e}"}

    datos, _, errores_forma = salida.limpiar("mentor", datos)
    if errores_forma:
        return {"agente": None, "motivo": "propuesta invalida: " + "; ".join(errores_forma)}

    if datos.get("agente") is None:
        return {"agente": None, "motivo": datos.get("motivo", "nada que cambiar")}

    error = _validar_propuesta(datos, raiz_skills)
    if error:
        return {"agente": None, "motivo": f"propuesta invalida: {error}"}
    return datos


def aplicar_con_examen(propuesta, con, raiz_skills=None, evaluar=examen.evaluar, notas=None, llamar=claude_cli.chat,
                       ahora=None, permitir_notas=False, hasta=None, reloj=time.monotonic, origen="mentor", vivo=None):
    raiz_skills = Path(raiz_skills or rutas.RAIZ / "skills")
    notas = Path(notas) if notas is not None else raiz_skills.parent / "examen" / "notas.json"
    agente, fichero, motivo = propuesta["agente"], propuesta["fichero"], propuesta["motivo"]

    if _examen_en_curso(raiz_skills / agente / "historial", vivo or _vivo_defecto):
        return {"aceptado": False, "nota_antes": None, "nota_despues": None, "copia": None,
                "motivo": "skill en examen por otro proceso"}

    if Path(fichero).name == "notas.md" and not permitir_notas:
        catalogo.registrar_cambio_skill(con, agente, "notas.md solo con permitir_notas", None, None, False,
                                        origen=origen)
        return {"aceptado": False, "nota_antes": None, "nota_despues": None, "copia": None,
                "motivo": "notas.md solo con permitir_notas"}

    ruta = raiz_skills / agente / fichero
    ahora = ahora or datetime.now(timezone.utc)
    marca = ahora.strftime("%Y%m%d_%H%M%S")
    nombre_copia = fichero.replace("/", "_").replace("\\", "_")
    copia = raiz_skills / agente / "historial" / f"{marca}_{nombre_copia}"
    marcador = copia.with_name(copia.name + ".pendiente")
    extra = {"hasta": hasta, "reloj": reloj} if hasta is not None else {}

    def _borrar_marcador():
        try:
            marcador.unlink(missing_ok=True)
        except OSError:
            pass

    original, nota_antes = None, None
    try:
        copia.parent.mkdir(parents=True, exist_ok=True)
        original = ruta.read_text(encoding="utf-8")
        shutil.copy2(ruta, copia)
        marcador.write_text(json.dumps({"agente": agente, "fichero": fichero, "motivo": motivo, "origen": origen,
                                        "pid": os.getpid(),
                                        "creado": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                       ensure_ascii=False), encoding="utf-8")
        try:
            nota_antes = examen.nota_guardada(agente, notas)
            if nota_antes is None:
                base = evaluar(agente, llamar=llamar, raiz_skills=raiz_skills, **extra)
                if not _concluyente(base):
                    marcador.unlink(missing_ok=True)
                    catalogo.registrar_cambio_skill(con, agente, f"{motivo}; linea base no concluyente", None, None,
                                                    False, origen=origen)
                    return {"aceptado": False, "nota_antes": None, "nota_despues": None, "copia": str(copia),
                            "motivo": NO_CONCLUYENTE}
                nota_antes = base["nota"]

            ruta.write_text(propuesta["texto_nuevo"], encoding="utf-8")
            resultado = evaluar(agente, llamar=llamar, raiz_skills=raiz_skills, **extra)
            if not _concluyente(resultado):
                shutil.copy2(copia, ruta)
                marcador.unlink(missing_ok=True)
                catalogo.registrar_cambio_skill(con, agente, f"{motivo}; examen no concluyente", nota_antes, None,
                                                False, origen=origen)
                return {"aceptado": False, "nota_antes": nota_antes, "nota_despues": None, "copia": str(copia),
                        "motivo": NO_CONCLUYENTE}
            nota_despues = resultado["nota"]
            if nota_despues < nota_antes:
                shutil.copy2(copia, ruta)
                marcador.unlink(missing_ok=True)
                aceptado = False
            else:
                marcador.unlink(missing_ok=True)
                examen.guardar_nota(resultado, notas)
                aceptado = True
            catalogo.registrar_cambio_skill(con, agente, motivo, nota_antes, nota_despues, aceptado, origen=origen)
            return {"aceptado": aceptado, "nota_antes": nota_antes, "nota_despues": nota_despues, "copia": str(copia)}
        finally:
            _borrar_marcador()
    except claude_cli.CorteClaude as e:
        # El corte atraviesa el except Exception de examen.evaluar: sin esto la skill editada
        # quedaria puesta sin examinar y, ya sin marcador, nadie la restauraria.
        if original is not None:
            _restaurar(copia, ruta, original)
        catalogo.registrar_cambio_skill(con, agente, f"{motivo}; corte de claude: {e.motivo}", nota_antes, None,
                                        False, origen=origen)
        raise
    except Exception as e:
        if original is not None:
            _restaurar(copia, ruta, original)
        detalle = f"{motivo}; error: {type(e).__name__}: {e}"
        catalogo.registrar_cambio_skill(con, agente, detalle, nota_antes, None, False, origen=origen)
        return {"aceptado": False, "nota_antes": nota_antes, "nota_despues": None, "copia": str(copia),
                "motivo": detalle}


def _restaurar(copia, ruta, original):
    try:
        shutil.copy2(copia, ruta)
    except OSError:
        ruta.write_text(original, encoding="utf-8")


def _edad_horas(creado, ahora):
    if not creado:
        return float("inf")
    try:
        return (ahora - datetime.fromisoformat(creado)).total_seconds() / 3600
    except ValueError:
        return float("inf")


def _marcador_vivo(datos, vivo, ahora):
    """Vivo y reciente: se deja en paz (el examen sigue en marcha). Cualquier otro caso, se restaura."""
    pid = datos.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        esta_vivo = False
    else:
        try:
            esta_vivo = vivo(pid)
        except Exception:
            esta_vivo = True
    return esta_vivo and _edad_horas(datos.get("creado"), ahora) <= MAX_HORAS_MARCADOR


def _examen_en_curso(historial, vivo):
    ahora = datetime.now(timezone.utc)
    for marcador in sorted(Path(historial).glob("*.pendiente")):
        try:
            if _marcador_vivo(json.loads(marcador.read_text(encoding="utf-8")), vivo, ahora):
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def restaurar_huerfanas(con, raiz_skills=None, vivo=None, ahora=None):
    """Si el proceso murio a mitad de un examen, la skill quedo con texto sin evaluar: se vuelve a la copia."""
    raiz_skills = Path(raiz_skills or rutas.RAIZ / "skills")
    vivo = vivo or _vivo_defecto
    ahora = ahora or datetime.now(timezone.utc)
    restauradas = []
    for marcador in sorted(raiz_skills.glob("*/historial/*.pendiente")):
        try:
            datos = json.loads(marcador.read_text(encoding="utf-8"))
            if _marcador_vivo(datos, vivo, ahora):
                continue
            agente, fichero = datos["agente"], datos["fichero"]
            carpeta = (raiz_skills / agente).resolve()
            destino = (carpeta / fichero).resolve()
            copia = marcador.with_name(marcador.name[:-len(".pendiente")])
            if marcador.parent.parent.resolve() != carpeta or carpeta not in destino.parents or not copia.is_file():
                continue
            if copia.read_bytes() != destino.read_bytes():
                shutil.copy2(copia, destino)
                catalogo.registrar_cambio_skill(con, agente, f"interrumpido: {datos.get('motivo', '')}", None, None,
                                                False, origen=datos.get("origen", "mentor"))
            marcador.unlink()
            restauradas.append({"agente": agente, "fichero": fichero, "copia": str(copia)})
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            continue
    return restauradas


def ciclo(con, raiz, desde, config=None, raiz_skills=None, llamar=claude_cli.chat, evaluar=examen.evaluar, hasta=None,
         reloj=time.monotonic, ahora=None, notas=None, permitir_notas=False):
    errores = errores_de_la_noche(con, desde)
    if hasta is not None and hasta - reloj() < TIEMPO_MINIMO:
        return {"errores": errores["conteo"], "omitido": "sin tiempo"}

    raiz_skills = Path(raiz_skills or Path(raiz) / "skills")
    propuesta = proponer(errores, con, config=config, raiz_skills=raiz_skills, llamar=llamar)
    aplicado = None
    propuesta_parte = propuesta
    if propuesta and propuesta.get("agente") is not None:
        aplicado = aplicar_con_examen(propuesta, con, raiz_skills=raiz_skills, evaluar=evaluar, notas=notas,
                                      llamar=llamar, ahora=ahora, permitir_notas=permitir_notas, hasta=hasta,
                                      reloj=reloj)
        propuesta_parte = {"agente": propuesta["agente"], "fichero": propuesta["fichero"], "motivo": propuesta["motivo"]}
    return {"errores": errores["conteo"], "propuesta": propuesta_parte, "aplicado": aplicado, "omitido": ""}
