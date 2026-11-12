"""Vigilante de las 07:30: comprueba que hubo parte, revision y correo, y avisa por Gmail de lo que nadie conto."""
import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant import rutas
from quant.investigacion import contratos, correo, local, tiempos

TAREAS_VIGILADAS = ("Quant_Noche", "Quant_Revision", "Quant_Demo", "Quant_Barrido")
HORAS_SIN_CORRER_SEMANAL = {"Quant_Barrido": 24 * 8}
EVENTOS_DEMO = ("retire", "mismatch", "warn")
_EVENTOS_REPETIBLES = ("warn", "mismatch")
MAX_HORAS_PROCESO = 6
MAX_HORAS_ACTUALIZAR = 12
SISTEMA_NO_CONSULTADO = "no se pudo consultar el sistema"
MENSAJE_SESION_CLAUDE = "la sesion de Claude estaba caducada: la noche no pudo usar los agentes (abre Claude Code y vuelve a iniciar sesion)"
MENSAJE_CLAUDE_SIN_RESPUESTA = "Claude no respondio al empezar la noche (red, tiempo o limite de uso): la noche no pudo usar los agentes"
MAX_HORAS_SIN_CORRER = 26
_OCULTO = 0x08000000
_MAX_ARCHIVO_COLA = 5 * 1024 * 1024
_TROZO_COLA = 64 * 1024
_MAX_LINEA_COLA = 500
_CONSULTA = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
    "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\\.exe$' -and"
    " $_.CommandLine -match 'quant\\.investigacion\\.(noche|revision|vigilante)|quant\\.actualizar' } |"
    " ForEach-Object {"
    " [pscustomobject]@{ pid = $_.ProcessId;"
    " horas = [math]::Round(((Get-Date) - $_.CreationDate).TotalHours, 2); orden = $_.CommandLine } };"
    " $t = Get-ScheduledTask -TaskName 'Quant_*' -ErrorAction SilentlyContinue | ForEach-Object {"
    " $i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ nombre = $_.TaskName; estado = [string]$_.State;"
    " ultima = if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('s') } else { $null };"
    " proxima = if ($i.NextRunTime -and $i.NextRunTime.Year -gt 2000) { $i.NextRunTime.ToString('s') } else { $null };"
    " resultado = $i.LastTaskResult } };"
    " [pscustomobject]@{ procesos = @($p); tareas = @($t) } | ConvertTo-Json -Depth 4 -Compress")


def estado_sistema():
    salida = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CONSULTA],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                            creationflags=_OCULTO)
    if salida.returncode != 0 or not (salida.stdout or "").strip():
        raise OSError(f"powershell devolvio {salida.returncode}: {(salida.stderr or '')[:200]}")
    datos = json.loads(salida.stdout)
    tareas = {t["nombre"]: {"estado": t.get("estado"), "ultima": t.get("ultima"), "proxima": t.get("proxima"),
                         "resultado": t.get("resultado")} for t in datos.get("tareas") or []}
    return {"procesos": datos.get("procesos") or [], "tareas": tareas}


def _correo_salio(raiz, fecha):
    ruta = Path(raiz) / "registro" / f"revision_{fecha}.log"
    if not ruta.exists():
        return False
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            if json.loads(linea).get("correo") == 0:
                return True
        except ValueError:
            continue
    return False


def _horas_desde(texto, ahora):
    try:
        return (ahora - datetime.fromisoformat(texto)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _max_horas(orden):
    """Un backfill de precios lanzado a mano puede durar horas; las piezas de la noche no."""
    if re.search(r"quant\.investigacion\.(noche|revision|vigilante)", str(orden or "")):
        return MAX_HORAS_PROCESO
    return MAX_HORAS_ACTUALIZAR


def _consulta_fallo_ayer(raiz, fecha):
    try:
        ayer = (datetime.strptime(fecha, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        ruta = Path(raiz) / "registro" / f"vigilante_{ayer}.log"
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
        ultima = json.loads(lineas[-1]) if lineas else {}
    except (OSError, ValueError):
        return False
    avisos = (ultima.get("avisados") or []) + (ultima.get("graves") or []) if isinstance(ultima, dict) else []
    return any(str(a).startswith(SISTEMA_NO_CONSULTADO) for a in avisos)


def comprobar(raiz, fecha, sistema, ahora=None):
    ahora = ahora or datetime.now()
    graves, avisados = [], []
    correo_salio = _correo_salio(raiz, fecha)
    # Si el correo de las 06:15 salio, ya conto la falta de parte o la noche sin terminar.
    ya_contado = avisados if correo_salio else graves

    parte, fuera = contratos.leer_parte(raiz, fecha)
    if parte is None:
        ya_contado.append(f"sin parte de la noche: {fuera[0]}")
    else:
        if fuera:
            avisados.append("parte fuera de contrato: " + "; ".join(fuera[:3]))
        if not parte.get("fin_real"):
            ya_contado.append("la noche no termino (el parte no tiene fin_real)")
        for etapa, entrada in (parte.get("etapas") or {}).items():
            fallo = contratos.hay_fallo(entrada.get("resultado") if isinstance(entrada, dict) else None)
            if fallo:
                avisados.append(f"etapa {etapa}: {fallo[:160]}")
        ollama = parte.get("ollama")
        if isinstance(ollama, dict) and ollama.get("motor") is False:
            graves.append(local.MENSAJE_SIN_MOTOR)
        claude = parte.get("claude")
        if isinstance(claude, dict) and claude.get("sesion") is False:
            graves.append(MENSAJE_SESION_CLAUDE if claude.get("causa", "login") == "login"
                          else MENSAJE_CLAUDE_SIN_RESPUESTA)

    revision, fuera = contratos.leer_revision(raiz, fecha)
    if revision is None:
        graves.append(f"sin revision del supervisor: {fuera[0]}")
    else:
        if fuera:
            avisados.append("revision fuera de contrato: " + "; ".join(fuera[:3]))
        if revision.get("estado") == "sin revision":
            avisados.append(f"Claude no reviso: {str(revision.get('error') or revision.get('resumen'))[:160]}")

    if not correo_salio:
        graves.append("el correo de la manana no salio (ninguna linea con correo 0 en el registro de la revision)")

    for proceso in sistema.get("procesos") or []:
        if (proceso.get("horas") or 0) > _max_horas(proceso.get("orden")):
            graves.append(f"proceso colgado pid {proceso.get('pid')} ({proceso.get('horas')} h): "
                          f"{str(proceso.get('orden'))[:120]}")
    for nombre in TAREAS_VIGILADAS:
        tarea = (sistema.get("tareas") or {}).get(nombre)
        if not tarea:
            graves.append(f"la tarea {nombre} no existe")
            continue
        if tarea.get("estado") == "Disabled":
            graves.append(f"la tarea {nombre} esta deshabilitada")
        horas = _horas_desde(tarea.get("ultima"), ahora)
        limite = HORAS_SIN_CORRER_SEMANAL.get(nombre, MAX_HORAS_SIN_CORRER)
        if horas is None and nombre in HORAS_SIN_CORRER_SEMANAL:
            continue
        if horas is None or horas > limite:
            graves.append(f"la tarea {nombre} no ha corrido en las ultimas {limite} h")
    return {"graves": graves, "avisados": avisados}


def _cola(ruta, n=20):
    ruta = Path(ruta)
    if not ruta.exists():
        return f"(no existe {ruta.name})"
    if ruta.stat().st_size > _MAX_ARCHIVO_COLA:
        with open(ruta, "rb") as f:
            f.seek(-_TROZO_COLA, 2)
            crudo = f.read()
        texto = crudo.decode("utf-8", errors="replace")
    else:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    return "\n".join(linea[:_MAX_LINEA_COLA] for linea in texto.splitlines()[-n:])


def eventos_demo(raiz, ahora):
    """Eventos de la demo aun no avisados; sin marca previa, solo los de las ultimas 26 h."""
    try:
        con = sqlite3.connect(Path(raiz) / "catalogo.db", timeout=30)
        try:
            fila = con.execute("SELECT value FROM demo_state WHERE key='vigilante_evento'").fetchone()
            desde_id = int(fila[0]) if fila else 0
            limite = (ahora - timedelta(hours=MAX_HORAS_SIN_CORRER)).isoformat(timespec="seconds")
            marcas = ",".join("?" * len(EVENTOS_DEMO))
            fila = con.execute("SELECT value FROM demo_state WHERE key='vigilante_warns'").fetchone()
            conocidos = set(json.loads(fila[0])) if fila else set()
            filas = con.execute(f"SELECT id, ts, kind, detail_es FROM demo_events WHERE id>? AND kind IN ({marcas})"
                                " AND (?>0 OR ts>=?) ORDER BY id", (desde_id, *EVENTOS_DEMO, desde_id, limite)).fetchall()
        finally:
            con.close()
    except (OSError, sqlite3.Error, ValueError):
        return [], None, None
    avisos = {texto for _, _, kind, texto in filas if kind in _EVENTOS_REPETIBLES}
    nuevas = [f for f in filas if f[2] not in _EVENTOS_REPETIBLES or f[3] not in conocidos]
    vistos, lineas = set(), []
    for _, ts, kind, texto in nuevas:
        if kind not in _EVENTOS_REPETIBLES or texto not in vistos:
            lineas.append(f"{ts[:16]} {kind}: {texto}")
            vistos.add(texto)
    return lineas, (filas[-1][0] if filas else None), avisos


def _marcar_eventos(raiz, ultimo, avisos):
    con = sqlite3.connect(Path(raiz) / "catalogo.db", timeout=30)
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO demo_state VALUES('vigilante_evento', ?)", (str(ultimo),))
            con.execute("INSERT OR REPLACE INTO demo_state VALUES('vigilante_warns', ?)",
                        (json.dumps(sorted(avisos), ensure_ascii=False),))
    finally:
        con.close()


def _cuerpo(raiz, fecha, resultado):
    partes = ["El vigilante de las 07:30 ha encontrado esto:", *[f"- {g}" for g in resultado["graves"]]]
    if resultado.get("demo"):
        partes += ["", "Novedades de la demo desde el ultimo aviso:", *[f"- {e}" for e in resultado["demo"]]]
    if resultado["avisados"]:
        partes += ["", "Ademas (ya contado en el correo de la manana, si salio):",
                   *[f"- {a}" for a in resultado["avisados"]]]
    registro = Path(raiz) / "registro"
    partes += ["", "Ultimas lineas del registro de la noche:", _cola(registro / f"noche_{fecha}.log"),
               "", "Ultimas lineas del registro de la revision:", _cola(registro / f"revision_{fecha}.log")]
    return "\n".join(partes)


def main(argv=None, sistema=None, smtp=None, obtener=None, ahora=None):
    parser = argparse.ArgumentParser(description="Vigilante de Quant: avisa si la noche, la revision o el correo fallaron")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--fecha")
    args = parser.parse_args(argv)
    raiz = Path(args.raiz)
    ahora = ahora or datetime.now()
    if args.fecha:
        fecha = args.fecha
    else:
        # Con StartWhenAvailable, si el equipo arranca antes de la hora del vigilante, la noche de hoy
        # no ha ocurrido o acaba de empezar: se revisa la de ayer.
        antes_de_hora = (ahora.hour, ahora.minute) < contratos.HORA_VIGILANTE
        referencia = ahora - timedelta(days=1) if antes_de_hora else ahora
        fecha = tiempos.fecha_local(referencia)

    extra = []
    try:
        estado = sistema() if callable(sistema) else (sistema if sistema is not None else estado_sistema())
    except Exception as e:
        estado, extra = None, [f"{SISTEMA_NO_CONSULTADO}: {type(e).__name__}: {e}"]
    if estado is None:
        reciente = ahora.isoformat()
        estado = {"procesos": [], "tareas": {n: {"estado": "?", "ultima": reciente} for n in TAREAS_VIGILADAS}}
    resultado = comprobar(raiz, fecha, estado, ahora=ahora)
    resultado["avisados"] += extra
    if extra and _consulta_fallo_ayer(raiz, fecha):
        resultado["graves"].append("no se puede consultar el sistema desde hace dos dias")

    resultado["demo"], ultimo_evento, avisos_demo = eventos_demo(raiz, ahora)
    envio = None
    if resultado["graves"] or resultado["demo"]:
        credencial = correo.credencial(obtener=obtener)
        if credencial is None:
            envio = "sin credencial"
        else:
            try:
                correo.enviar(f"[Quant] {correo._fecha_corta(fecha)} · vigilante · {correo.ICONOS['parada']}",
                              _cuerpo(raiz, fecha, resultado), [], credencial, smtp=smtp)
                envio = "enviado"
                if ultimo_evento is not None:
                    _marcar_eventos(raiz, ultimo_evento, avisos_demo)
            except Exception as e:
                envio = f"fallo: {type(e).__name__}: {e}"
    elif ultimo_evento is not None:
        _marcar_eventos(raiz, ultimo_evento, avisos_demo)

    (raiz / "registro").mkdir(parents=True, exist_ok=True)
    with open(raiz / "registro" / f"vigilante_{fecha}.log", "a", encoding="utf-8") as log:
        log.write(json.dumps({"hora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              **resultado, "correo": envio}, ensure_ascii=False) + "\n")
    return 0 if envio in (None, "enviado") else 1


if __name__ == "__main__":
    sys.exit(main())
