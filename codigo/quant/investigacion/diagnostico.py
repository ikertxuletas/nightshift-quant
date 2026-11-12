"""Diagnostico de solo lectura: las ultimas noches de Quant en menos de un kilobyte por noche."""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from quant import rutas
from quant.investigacion import contratos, vigilante

MAX_MOTIVO = 60


def _recortar(texto, max_bytes):
    return texto.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _estado_canario(resultado):
    if resultado.get("omitido"):
        return f"omitido: {resultado['omitido']}"
    if resultado.get("ok"):
        return "ok"
    fallo = contratos.hay_fallo(resultado)
    if not fallo:
        return None
    trozos = fallo.split(":")
    if len(trozos) >= 3 and trozos[0].strip() == "canario":
        return "falla: " + trozos[1].strip()
    return "falla: " + _recortar(fallo, MAX_MOTIVO)


def noche(raiz, fecha):
    raiz = Path(raiz)
    parte, fuera = contratos.leer_parte(raiz, fecha)
    parte = parte or {}
    etapas = {}
    for nombre, entrada in (parte.get("etapas") or {}).items():
        resultado = entrada.get("resultado") if isinstance(entrada, dict) else None
        fallo = contratos.hay_fallo(resultado)
        etapas[nombre] = {"s": entrada.get("segundos") if isinstance(entrada, dict) else None,
                          "fallo": _recortar(fallo, MAX_MOTIVO) if fallo else None,
                          "omitido": resultado.get("omitido") if isinstance(resultado, dict) else None}
        errores_contenido = resultado.get("errores_contenido") if isinstance(resultado, dict) else None
        if errores_contenido:
            etapas[nombre]["errores_contenido"] = errores_contenido
    canario = None
    res_canario = ((parte.get("etapas") or {}).get("canario") or {}).get("resultado")
    if isinstance(res_canario, dict):
        canario = _estado_canario(res_canario)
    revision, _ = contratos.leer_revision(raiz, fecha)
    memoria_lineas = parte.get("memoria") or []
    cerrados = sum(len(m.get("cerrados") or []) for m in memoria_lineas if isinstance(m, dict))
    return {"fecha": fecha, "etapas": etapas, "errores": parte.get("errores"), "corte": parte.get("corte"),
            "canario": canario, "revision": (revision or {}).get("estado"),
            "correo": vigilante._correo_salio(raiz, fecha), "contrato": fuera, "cerrados": cerrados,
            "ollama": bool((parte.get("ollama") or {}).get("arrancado")),
            "motor_ollama": (parte.get("ollama") or {}).get("motor"),
            "claude": parte.get("claude") if isinstance(parte.get("claude"), dict) else None}


def _fechas(raiz, noches):
    nombres = sorted((p.stem[len("parte_"):] for p in (Path(raiz) / "informes").glob("parte_*.json")), reverse=True)
    return nombres[:noches]


def _catalogo(raiz):
    ruta = Path(raiz) / "catalogo.db"
    vacio = {"cambios": {}, "documentos": {}, "normalizaciones": [], "errores_frecuentes": []}
    if not ruta.exists():
        return vacio
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cambios = {}
        try:
            for fila in con.execute("SELECT COALESCE(origen, 'mentor') o, aceptado a, COUNT(*) n FROM skills_cambios"
                                    " GROUP BY o, a"):
                cambios.setdefault(fila["o"], {"aceptados": 0, "rechazados": 0})[
                    "aceptados" if fila["a"] else "rechazados"] += fila["n"]
        except sqlite3.Error:
            cambios = {}

        documentos = {}
        try:
            documentos = {f["etapa"]: f["n"] for f in
                          con.execute("SELECT etapa, COUNT(*) n FROM documentos GROUP BY etapa")}
        except sqlite3.Error:
            documentos = {}

        errores = Counter()
        try:
            errores = Counter(_recortar(f["error"] or "", MAX_MOTIVO) for f in con.execute(
                "SELECT error FROM documentos WHERE etapa = 'error' OR (error IS NOT NULL AND error <> ''"
                " AND etapa IN ('nuevo', 'leido'))"))
        except sqlite3.Error:
            errores = Counter()

        avisos = Counter()
        try:
            for fila in con.execute("SELECT json FROM extractos"):
                try:
                    extracto = json.loads(fila["json"])
                    for aviso in (extracto.get("avisos_salida") or []) + (extracto.get("avisos_formalizador") or []):
                        avisos[_recortar(str(aviso).split(":")[0], MAX_MOTIVO)] += 1
                except (ValueError, AttributeError, TypeError):
                    continue
        except sqlite3.Error:
            avisos = Counter()

        return {"cambios": cambios, "documentos": documentos, "normalizaciones": avisos.most_common(5),
                "errores_frecuentes": errores.most_common(5)}
    except sqlite3.Error:
        return vacio
    finally:
        con.close()


def _notas(raiz):
    try:
        datos = json.loads((Path(raiz) / "examen" / "notas.json").read_text(encoding="utf-8"))
        return {agente: fila.get("nota") for agente, fila in datos.items() if isinstance(fila, dict)}
    except (OSError, ValueError):
        return {}


def resumen(raiz, noches=7, sistema=None):
    try:
        estado = sistema if sistema is not None else vigilante.estado_sistema()
    except Exception as e:
        estado = {"tareas": {"error": f"{type(e).__name__}: {e}"}}
    return {"noches": [noche(raiz, f) for f in _fechas(raiz, noches)], "notas": _notas(raiz),
            **_catalogo(raiz), "tareas": estado.get("tareas") or {}}


def _linea_noche(n):
    trozos = []
    for nombre, e in n["etapas"].items():
        if e["fallo"]:
            marca = "FALLO " + e["fallo"]
        elif e.get("errores_contenido"):
            marca = f"{e['errores_contenido']} errores de contenido"
        else:
            marca = e["omitido"] or f"{e['s']}s"
        trozos.append(f"{nombre}={marca}")
    cabecera = (f"{n['fecha']} err={n['errores']} canario={n['canario']} rev={n['revision']}"
                f" correo={'si' if n['correo'] else 'NO'}")
    if n.get("cerrados"):
        cabecera += f" cerrados={n['cerrados']}"
    if n.get("ollama"):
        cabecera += " ollama=arrancado"
    if n.get("motor_ollama") is False:
        cabecera += " ollama=SIN MOTOR"
    if n.get("claude"):
        sesion = n["claude"].get("sesion")
        cabecera += " claude=SESION CADUCADA" if sesion is False else f" claude={n['claude'].get('llamadas', '?')}"
    contrato = f" CONTRATO: {'; '.join(n['contrato'][:2])}" if n["contrato"] else ""
    return _recortar(cabecera + " | " + " ".join(trozos) + contrato, 1000)


def texto(r):
    lineas = [_linea_noche(n) for n in r["noches"]]
    lineas.append("notas: " + " ".join(f"{a} {v}" for a, v in r["notas"].items()))
    lineas.append("cambios: " + " ".join(f"{o} +{c['aceptados']}/-{c['rechazados']}" for o, c in r["cambios"].items()))
    lineas.append("documentos: " + " ".join(f"{e}={n}" for e, n in r["documentos"].items()))
    lineas.append("errores: " + " | ".join(f"{n}x {m}" for m, n in r["errores_frecuentes"]))
    lineas.append("normaliza: " + " | ".join(f"{n}x {m}" for m, n in r["normalizaciones"]))
    lineas.append("tareas: " + " ".join(f"{t}={d.get('estado')}@{d.get('ultima')}" if isinstance(d, dict) else f"{t}={d}"
                                        for t, d in r["tareas"].items()))
    return "\n".join(_recortar(l, 1000) for l in lineas)


def main(argv=None, sistema=None):
    parser = argparse.ArgumentParser(description="Resumen de las ultimas noches de Quant (solo lectura)")
    parser.add_argument("--raiz", default=str(rutas.RAIZ))
    parser.add_argument("--noches", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    r = resumen(args.raiz, noches=args.noches, sistema=sistema)
    print(json.dumps(r, ensure_ascii=False) if args.json else texto(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
