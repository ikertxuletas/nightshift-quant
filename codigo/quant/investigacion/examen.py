"""Examen fijo de los agentes: casos escritos a mano que sirven de vara de medir."""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import rutas
from quant.investigacion import agentes, claude_cli

CASOS = rutas.RAIZ / "examen" / "casos"
NOTAS = rutas.RAIZ / "examen" / "notas.json"

CAMPOS_EXACTOS = ("operable", "tipo", "plazo")


def _texto(valor):
    return re.sub(r"\s+", " ", str(valor or "")).strip().lower()


def _frases(texto):
    return [f for f in (_texto(p) for p in re.split(r"[.;\n]", texto or "")) if len(f) >= 10]


def _valor(valor):
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return _texto(valor)


def _hojas(datos, prefijo=""):
    if isinstance(datos, dict) and datos:
        pares = set()
        for clave, valor in datos.items():
            pares |= _hojas(valor, f"{prefijo}.{clave}" if prefijo else str(clave))
        return pares
    if isinstance(datos, list) and datos:
        pares = set()
        for i, valor in enumerate(datos):
            pares |= _hojas(valor, f"{prefijo}.{i}" if prefijo else str(i))
        return pares
    if isinstance(datos, (dict, list)):
        return {f"{prefijo}=vacio"}
    return {f"{prefijo}={_valor(datos)}"}


def _f1(esperadas, obtenidas):
    if not esperadas and not obtenidas:
        return 1.0
    comunes = len(esperadas & obtenidas)
    if not comunes:
        return 0.0
    precision = comunes / len(obtenidas)
    recall = comunes / len(esperadas)
    return 2 * precision * recall / (precision + recall)


def _jaccard(esperado, obtenido):
    a, b = {_texto(x) for x in esperado or []}, {_texto(x) for x in obtenido or []}
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 1.0


def _hueco(valor):
    """Un cero o un texto vacio son huecos de plantilla; un booleano si dice algo."""
    if valor is None or valor == "":
        return True
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor == 0


def _prometido_real(prometido):
    """Solo cuentan las cifras que el documento da de verdad: los huecos no son una promesa."""
    return _hojas({k: v for k, v in (prometido or {}).items() if not _hueco(v)})


def nota_extracto(esperado, obtenido):
    exactos = sum(1 for c in CAMPOS_EXACTOS if _texto(esperado.get(c)) == _texto(obtenido.get(c)))
    partes = [exactos / len(CAMPOS_EXACTOS), _jaccard(esperado.get("mercado"), obtenido.get("mercado"))]
    frases = _frases(esperado.get("extracto"))
    texto_obtenido = _texto(obtenido.get("extracto"))
    partes.append(1.0 if not frases else sum(1 for f in frases if f in texto_obtenido) / len(frases))
    partes.append(_f1(_prometido_real(esperado.get("prometido")), _prometido_real(obtenido.get("prometido"))))
    return sum(partes) / len(partes)


def nota_ficha(esperada, obtenida):
    return _f1(_hojas(esperada or {}), _hojas(obtenida or {}))


def nota_critica(esperada, obtenida):
    uno, otro = esperada.get("veredicto"), obtenida.get("veredicto")
    if uno == otro:
        return 1.0
    if {uno, otro} == {"devolver", "rechazada"}:
        return 0.5
    return 0.0


def _leer_json(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))


def _caso_lector(carpeta, meta, llamar, raiz_skills, modelo):
    documento = (carpeta / "documento.txt").read_text(encoding="utf-8")
    obtenido = agentes.leer(meta["titulo"], meta["fuente"], documento, raiz_skills=raiz_skills,
                            llamar=llamar, modelo=modelo)
    return nota_extracto(_leer_json(carpeta / "extracto.json"), obtenido)


def _caso_formalizador(carpeta, meta, llamar, raiz_skills, modelo):
    fuente = {"url": meta.get("url") or "sin-url", "cita": meta.get("cita") or meta["titulo"]}
    salida = agentes.formalizar(_leer_json(carpeta / "extracto.json"), fuente, raiz_skills=raiz_skills,
                                llamar=llamar, modelo=modelo)
    esperada = _leer_json(carpeta / "ficha.json")
    if esperada.get("expresable") is False:
        return 0.0 if salida.get("expresable") else 1.0
    return nota_ficha(esperada, salida.get("ficha") or {})


def _caso_critico(carpeta, meta, llamar, raiz_skills, modelo):
    critica = _leer_json(carpeta / "critica.json")
    entradas = critica if isinstance(critica, list) else [critica]
    extracto = _leer_json(carpeta / "extracto.json")
    notas = [nota_critica(entrada, agentes.criticar(entrada["ficha"], extracto, raiz_skills=raiz_skills,
                                                    llamar=llamar, modelo=modelo))
             for entrada in entradas]
    return sum(notas) / len(notas)


_AGENTES = {"lector": ("extracto.json", _caso_lector),
            "formalizador": ("ficha.json", _caso_formalizador),
            "critico": ("critica.json", _caso_critico)}


def evaluar(agente, llamar=claude_cli.chat, casos=None, raiz_skills=None, modelo=None, hasta=None, reloj=time.monotonic):
    if agente not in _AGENTES:
        raise ValueError(f"agente desconocido: {agente}")
    requerido, funcion = _AGENTES[agente]
    carpeta_casos = Path(casos or CASOS)
    detalle, inicio_total, interrumpido = [], time.monotonic(), False
    for carpeta in sorted(p for p in carpeta_casos.iterdir() if p.is_dir()):
        meta = _leer_json(carpeta / "meta.json")
        # Without the source text (not redistributed; see examen/README.md) the case cannot be graded.
        sin_texto = not (carpeta / "documento.txt").exists()
        if agente not in meta.get("agentes", []) or not (carpeta / requerido).exists() or sin_texto:
            continue
        if hasta is not None and reloj() >= hasta:
            interrumpido = True
            break
        inicio = time.monotonic()
        try:
            fila = {"caso": carpeta.name, "nota": funcion(carpeta, meta, llamar, raiz_skills, modelo)}
        except Exception as e:
            fila = {"caso": carpeta.name, "nota": 0.0, "error": f"{type(e).__name__}: {e}"}
        fila["segundos"] = round(time.monotonic() - inicio, 1)
        detalle.append(fila)
    nota = sum(f["nota"] for f in detalle) / len(detalle) if detalle else 0.0
    caidos = bool(detalle) and all(f.get("error") for f in detalle)
    return {"agente": agente, "modelo": modelo or agentes._modelo_defecto(agente, None),
            "casos": len(detalle), "nota": round(nota, 4),
            "segundos": round(time.monotonic() - inicio_total, 1), "detalle": detalle,
            "interrumpido": interrumpido, "concluyente": bool(detalle) and not caidos and not interrumpido}


def guardar_nota(resultado, notas=None):
    ruta = Path(notas or NOTAS)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    guardadas = _leer_json(ruta) if ruta.exists() else {}
    guardadas[resultado["agente"]] = {"nota": resultado["nota"], "casos": resultado["casos"],
                                      "modelo": resultado.get("modelo"),
                                      "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ruta.write_text(json.dumps(guardadas, indent=1, ensure_ascii=False), encoding="utf-8")
    return ruta


def nota_guardada(agente, notas=None):
    ruta = Path(notas or NOTAS)
    if not ruta.exists():
        return None
    fila = _leer_json(ruta).get(agente)
    return fila["nota"] if fila and fila.get("casos", 1) != 0 else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Examen fijo de los agentes")
    parser.add_argument("--agente", required=True, choices=sorted(_AGENTES))
    parser.add_argument("--modelo")
    parser.add_argument("--guardar", action="store_true")
    args = parser.parse_args(argv)
    resultado = evaluar(args.agente, modelo=args.modelo)
    if args.guardar:
        guardar_nota(resultado)
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
