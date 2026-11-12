"""Weekly advisor: reads every lab experiment and the edge maps, reports to the owner and sets the lab's direction.

It sees what the lab agent sees and nothing more: no exam or confirmation results, no winners.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from quant import rutas
from quant.familias import propias as mpropias
from quant.investigacion import agentes, catalogo, claude_cli, local, skills
from quant.investigacion import laboratorio as lab

MAX_BYTES_ASESOR = 150_000
MAX_DIRECCION = 4
MAX_BYTES_INFORME = 20_000


def _cortar(texto, n):
    return texto.encode("utf-8")[:n].decode("utf-8", "ignore")


def _linea(f):
    e = json.loads(f["entreno_json"]) if f["entreno_json"] else {}
    total = (e.get("metricas") or {}).get("total") or {}
    fallados = ",".join(c["criterio"] for c in e.get("criterios") or [] if not c.get("cumple", True))
    veredicto = "pasa_validador" if f["veredicto"] == "ganadora" else f["veredicto"]
    extra = f" invalid: {f['invalido']}" if f["invalido"] else ""
    return (f"#{f['id']} c{f['cambios']} {veredicto} pf {total.get('profit_factor')} ops {total.get('operaciones')}"
            f" fails {fallados or '-'}{extra} | {f['motivo']}")


def _historial(con, nombre, presupuesto):
    filas = con.execute("SELECT id, cambios, veredicto, invalido, entreno_json, motivo FROM lab_experimentos"
                        " WHERE estrategia = ? ORDER BY id DESC", (nombre,)).fetchall()
    lineas, usados = [], 0
    for f in filas:
        linea = _linea(f)
        usados += len(linea.encode("utf-8")) + 1
        if usados > presupuesto:
            break
        lineas.append(linea)
    return len(filas), lineas


def paquete(con, propias_dict, mapas):
    """MAX_BYTES_ASESOR bounds the whole package: the fixed parts go first, the rest is shared as history."""
    fijos = {}
    for nombre, p in propias_dict.items():
        base = mpropias.ficha_base(nombre)
        anterior = con.execute("SELECT fecha, informe, direccion FROM lab_asesor WHERE estrategia = ?"
                               " ORDER BY fecha DESC, id DESC LIMIT 1", (nombre,)).fetchone()
        previo = (f"## Your previous report ({anterior['fecha']})\n{_cortar(anterior['informe'], MAX_BYTES_INFORME)}\n\n"
                  f"## Your previous direction\n{_cortar(anterior['direccion'], MAX_BYTES_INFORME)}\n"
                  ) if anterior else "## Your previous report\n(none)\n"
        mapa = _cortar(mapas.get(nombre) or "", lab.MAX_BYTES_MAPA)
        fijos[nombre] = (f"# Strategy {nombre} (origin: {p.origen})\n\n## Base ficha\n{lab._canon(base)}\n\n"
                         + lab._explorado(con, p, base),
                         f"\n\n## Edge map (training data only)\n{mapa or '(not available)'}\n\n" + previo)
    ocupado = sum(len((a + b).encode("utf-8")) + 200 for a, b in fijos.values())
    presupuesto = max(0, (MAX_BYTES_ASESOR - ocupado) // max(1, len(fijos)))
    partes = []
    for nombre, (cabeza, cola) in fijos.items():
        total, lineas = _historial(con, nombre, presupuesto)
        partes.append(agentes.vallar(cabeza + f"\n## Experiments, newest first ({len(lineas)} of {total})\n"
                                     + ("\n".join(lineas) or "(none yet)") + cola))
    return "\n\n".join(partes)


def _lista_texto(x, maximo):
    return isinstance(x, list) and 1 <= len(x) <= maximo and all(isinstance(i, str) and i.strip() for i in x)


def validar(datos, nombres):
    estrategias = datos.get("estrategias") if isinstance(datos, dict) else None
    if not isinstance(estrategias, dict):
        return {}
    validos = {}
    for nombre, d in estrategias.items():
        if nombre not in nombres or not isinstance(d, dict) or not isinstance(d.get("informe"), str):
            continue
        if not (_lista_texto(d.get("direccion"), MAX_DIRECCION) and _lista_texto(d.get("direccion_es"), MAX_DIRECCION)
                and len(d["direccion"]) == len(d["direccion_es"])):
            continue
        propuestas = d.get("propuestas") or []
        if not isinstance(propuestas, list):
            continue
        propuestas = [{"que": x["que"], "motivo": x["motivo"]} for x in propuestas
                      if isinstance(x, dict) and isinstance(x.get("que"), str) and isinstance(x.get("motivo"), str)]
        validos[nombre] = {"informe": d["informe"], "direccion": d["direccion"], "direccion_es": d["direccion_es"],
                           "propuestas": propuestas}
    return validos


def guardar(con, fecha, validos):
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        for nombre, d in validos.items():
            con.execute("INSERT INTO lab_asesor (estrategia, fecha, informe, direccion, direccion_es, propuestas_json,"
                        " creado) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (nombre, fecha, d["informe"], "\n".join(d["direccion"]), "\n".join(d["direccion_es"]),
                         json.dumps(d["propuestas"], ensure_ascii=False), ahora))


def _mapas(con, raiz, propias_dict):
    try:
        barras, costes_of = lab._cargadores(raiz, None, None)
    except Exception:
        return {}
    mapas = {}
    for nombre, p in propias_dict.items():
        try:
            mapas[nombre] = lab.mapa_de(con, p, barras, costes_of)
        except Exception:
            mapas[nombre] = ""
    return mapas


def main(argv=None):
    a = argparse.ArgumentParser(description="Asesor semanal del laboratorio")
    a.add_argument("--raiz", default=str(rutas.RAIZ))
    a.add_argument("--fecha", default=datetime.now().strftime("%Y%m%d"))
    args = a.parse_args(argv)
    raiz, fecha = Path(args.raiz), f"{args.fecha[:4]}-{args.fecha[4:6]}-{args.fecha[6:]}"
    con = catalogo.abrir(raiz / "catalogo.db")
    registro = {"fecha": fecha, "guardadas": [], "error": ""}
    try:
        lab.ensure_schema(con)
        propias_dict = dict(mpropias.PROPIAS)
        texto = paquete(con, propias_dict, _mapas(con, raiz, propias_dict))
        respuesta = claude_cli.chat("opus", skills.system("asesor"), texto, formato="json", timeout=1800, raiz=raiz)
        validos = validar(local.json_de(respuesta), set(propias_dict))
        if not validos:
            raise ValueError("respuesta sin ninguna estrategia valida")
        guardar(con, fecha, validos)
        registro["guardadas"] = sorted(validos)
    except (Exception, claude_cli.CorteClaude) as e:  # the week's direction just stays as it was
        registro["error"] = f"{type(e).__name__}: {e}"[:500]
    finally:
        con.close()
        (raiz / "registro").mkdir(parents=True, exist_ok=True)
        with open(raiz / "registro" / f"asesor_{args.fecha}.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
    print(json.dumps(registro, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
