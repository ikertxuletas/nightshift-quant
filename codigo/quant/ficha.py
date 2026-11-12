import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from quant import expresiones, indicadores

_ESQUEMA = Draft202012Validator(json.loads((Path(__file__).parent / "esquema_ficha.json").read_text(encoding="utf-8")))
TAMANO_DEFECTO = {"tipo": "riesgo", "valor": 1.0}


class ErrorFicha(ValueError):
    def __init__(self, errores):
        super().__init__("; ".join(errores))
        self.errores = errores


def _tokens(datos):
    for seccion in ("entrada", "salida"):
        for cond in (datos.get(seccion) or {}).values():
            yield from expresiones.operandos(cond)
    t = datos.get("transversal") or {}
    if t.get("ranking"):
        yield t["ranking"]
    if t.get("filtro"):
        yield from expresiones.operandos(t["filtro"])


def errores(datos):
    lista = [f"{'/'.join(map(str, e.absolute_path)) or 'raiz'}: {e.message}" for e in _ESQUEMA.iter_errors(datos)]
    if lista:
        return lista
    if datos["forma"] == "serie_temporal" and not (datos.get("entrada") or {}):
        lista.append("entrada: una serie_temporal necesita al menos un lado de entrada")
    if datos["forma"] == "transversal":
        if "transversal" not in datos:
            lista.append("transversal: falta la sección para forma transversal")
        for seccion in ("entrada", "salida", "horario"):
            if seccion in datos:
                lista.append(f"{seccion}: una transversal no usa esta sección")
        for clave in datos["gestion"]:
            if clave != "tamano":
                lista.append(f"gestion/{clave}: una transversal solo admite tamano")
    elif "transversal" in datos:
        lista.append("transversal: una serie_temporal no usa esta sección")
    for token in _tokens(datos):
        try:
            indicadores.analizar(token)
        except indicadores.ErrorIndicador as e:
            lista.append(f"indicador: {e}")
    return lista


def con_defectos(datos):
    nueva = copy.deepcopy(datos)
    nueva["gestion"].setdefault("tamano", dict(TAMANO_DEFECTO))
    return nueva


def cargar(ruta):
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    lista = errores(datos)
    if lista:
        raise ErrorFicha(lista)
    return con_defectos(datos)
