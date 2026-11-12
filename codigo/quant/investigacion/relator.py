"""Agente Relator: explica en espanol llano los resultados de las pruebas y escribe el informe de la noche."""
import json
import re
import time
from pathlib import Path

from quant.investigacion import agentes, catalogo, claude_cli, local, skills

PROHIBIDAS = ("garantiza", "seguro que", "compra ahora", "vende ahora", "deberias comprar", "deberias vender",
              "te recomiendo", "deberias invertir", "invierte en", "rentabilidad asegurada")
RETIRADA = "[frase retirada por el filtro]"


def _filtrar(texto):
    lineas = []
    for linea in texto.splitlines():
        frases = re.split(r"(?<=[.!?])\s+", linea)
        frases = [RETIRADA if any(p in frase.lower() for p in PROHIBIDAS) else frase for frase in frases]
        lineas.append(" ".join(frases))
    return "\n".join(lineas).strip()


def explicar(ficha, instrumento, resultado, config=None, raiz_skills=None, llamar=claude_cli.chat, modelo=None):
    ajuste = agentes.ajustes("relator", config)
    sistema = skills.system("relator", raiz=raiz_skills)
    prompt = (f"Instrumento: {instrumento}\nFicha:\n{agentes.vallar(json.dumps(ficha, ensure_ascii=False))}\n"
              f"Resultado:\n{agentes.vallar(json.dumps(resultado, ensure_ascii=False))}\n"
              "Explica en 6 a 12 lineas, en espanol llano, que hace la estrategia, como le fue y por que pasa o no.")
    try:
        texto = llamar(modelo or ajuste["modelo"], sistema, prompt, formato=ajuste["formato"], opciones=ajuste["opciones"])
    except local.ErrorModelo as e:
        raise agentes.ErrorAgente(f"relator: {e}") from e
    return _filtrar(texto)


def procesar_relatos(con, config=None, raiz_skills=None, llamar=claude_cli.chat, hasta=None, reloj=time.monotonic,
                     antes=None):
    resumen = {"relatados": 0, "errores": 0, "omitidos": 0}
    pendientes = catalogo.resultados_sin_relato(con)
    for i, fila in enumerate(pendientes):
        if (hasta is not None and reloj() >= hasta) or (antes and antes()):
            resumen["omitidos"] = len(pendientes) - i
            break
        try:
            texto = explicar(json.loads(fila["ficha_json"]), fila["instrumento"], json.loads(fila["json"]),
                             config, raiz_skills, llamar)
        except agentes.FALLOS + (ValueError,):
            resumen["errores"] += 1
            continue
        catalogo.guardar_relato(con, fila["id"], texto)
        resumen["relatados"] += 1
    return resumen


def _tabla_criterios(criterios):
    filas = ["| criterio | valor | umbral | cumple |", "|---|---|---|---|"]
    for c in criterios:
        filas.append(f"| {c['criterio']} | {c['valor']} | {c['umbral']} | {'si' if c['cumple'] else 'no'} |")
    return "\n".join(filas)


def _bloque(con, fila):
    ficha, res = json.loads(fila["ficha_json"]), json.loads(fila["json"])
    partes = [f"### {ficha.get('titulo', ficha.get('id'))} · {fila['instrumento']}",
              _tabla_criterios(res.get("criterios", []))]
    ref = res.get("referencias") or {}
    if ref.get("vs_fuente"):
        partes.append("Frente a lo prometido por la fuente: " +
                      ", ".join(f"{k} {v:+}" for k, v in ref["vs_fuente"].items()))
    if ref.get("vs_tipo"):
        partes.append("Frente a lo normal para su tipo: " + ", ".join(
            f"{u['criterio']} {u['valor']} (ref {u['umbral']}, {u['fuente']})" for u in ref["vs_tipo"]))
    if res.get("avisos"):
        partes.append("Avisos: " + "; ".join(res["avisos"]))
    texto = catalogo.relato(con, fila["id"])
    partes.append(texto or "(sin relato)")
    return "\n\n".join(partes)


def _linea(fila, detalle):
    ficha = json.loads(fila["ficha_json"])
    return f"- {ficha.get('titulo', ficha.get('id'))} · {fila['instrumento']}: {detalle}"


def _todos(con):
    return con.execute("SELECT r.id AS id, r.instrumento AS instrumento, r.veredicto AS veredicto, r.json AS json,"
                       " f.json AS ficha_json FROM resultados r JOIN fichas f ON f.id = r.ficha_id ORDER BY r.id"
                       ).fetchall()


def informe(con, raiz, fecha):
    filas = _todos(con)
    por = {v: [f for f in filas if f["veredicto"] == v]
           for v in ("pasa", "dudosa", "no_pasa", "pendiente_datos", "ficha_invalida")}
    secciones = [f"# Quant · Informe del {fecha}", "",
                 "> **Candidata no significa rentable.** Una candidata es una ficha que ha pasado los criterios en"
                 " datos históricos con costes; no es una recomendación de operar.", ""]

    def seccion(titulo, elementos):
        secciones.extend([f"## {titulo}", ""] + (elementos or ["(ninguna)"]) + [""])

    seccion("Candidatas", [_bloque(con, f) for f in por["pasa"]])
    seccion("Dudosas", [_bloque(con, f) for f in por["dudosa"]])
    seccion("No pasan", [_linea(f, "fallan " + ", ".join(
        c["criterio"] for c in json.loads(f["json"]).get("criterios", []) if not c["cumple"]))
        for f in por["no_pasa"]])
    seccion("Pendientes de datos", [_linea(f, json.loads(f["json"]).get("motivo", "")) for f in por["pendiente_datos"]])
    seccion("Fichas invalidas", [_linea(f, (json.loads(f["json"]).get("errores") or [""])[0])
                                 for f in por["ficha_invalida"]])
    seccion("Catalogo", [f"- {tabla}: {valores}" for tabla, valores in catalogo.resumen(con).items()])
    destino = Path(raiz) / "informes" / f"informe_{fecha}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(secciones), encoding="utf-8")
    return destino
