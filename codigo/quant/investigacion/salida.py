"""Puerta unica para lo que devuelven los modelos: tipa, normaliza lo recuperable y nombra lo que no lo es."""
import copy
import re

PLAZOS = {"M5", "M15", "H1", "H4", "D1", "W1", ""}
_PLAZO_ALIAS = {"1W": "W1", "SEMANAL": "W1", "WEEKLY": "W1", "1D": "D1", "DIARIO": "D1", "DAILY": "D1",
                "1H": "H1", "4H": "H4", "15M": "M15", "5M": "M5",
                "MN": "D1", "1MO": "D1", "MENSUAL": "D1", "MONTHLY": "D1",
                # Plazos sin datos propios: se aproximan al mas cercano en vez de perder la estrategia.
                "M1": "M5", "1M": "M5", "M10": "M15", "10M": "M15", "M30": "H1", "30M": "H1",
                "H2": "H1", "2H": "H1", "H6": "H4", "H8": "H4", "H12": "H4", "12H": "H4"}
_NUMERO = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*%?\s*$")
_BOOLEANOS = {"true": True, "si": True, "sí": True, "false": False, "no": False}

ESQUEMAS = {
    "lector": {"operable": "texto_o_nulo", "tipo": "texto", "mercado": "lista_texto", "plazo": "plazo",
               "extracto": "texto", "prometido": "cifras", "alarmas": "lista_texto", "motivo": "texto",
               "faltan": "lista_texto"},
    "formalizador": {"expresable": "bool", "motivo": "texto", "ficha": "dict"},
    "critico": {"veredicto": "texto", "motivos": "lista_texto"},
    "mentor": {"agente": "texto_o_nulo", "fichero": "texto", "texto_nuevo": "texto", "motivo": "texto"},
}


class _NoVale(Exception):
    pass


def _texto(valor, avisos, campo):
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list) and len(valor) == 1 and isinstance(valor[0], str):
        avisos.append(f"{campo}: lista de un texto tomada como texto")
        return valor[0]
    raise _NoVale(f"se esperaba texto, llego {type(valor).__name__}")


def _texto_o_nulo(valor, avisos, campo):
    return None if valor is None else _texto(valor, avisos, campo)


def _lista_texto(valor, avisos, campo):
    if valor is None:
        return []
    if isinstance(valor, str):
        avisos.append(f"{campo}: texto tomado como lista")
        return [valor] if valor.strip() else []
    if isinstance(valor, list) and all(isinstance(x, str) for x in valor):
        return list(valor)
    raise _NoVale("se esperaba una lista de textos")


def _bool(valor, avisos, campo):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.strip().lower() in _BOOLEANOS:
        avisos.append(f"{campo}: texto tomado como booleano")
        return _BOOLEANOS[valor.strip().lower()]
    raise _NoVale(f"se esperaba true o false, llego {type(valor).__name__}")


def _dict(valor, avisos, campo):
    if valor is None:
        return {}
    if isinstance(valor, dict):
        return copy.deepcopy(valor)
    raise _NoVale(f"se esperaba un objeto, llego {type(valor).__name__}")


_CIFRAS_EXENTAS = {"cita", "periodo"}


def _cifras(valor, avisos, campo):
    """'prometido': objeto plano cuyas cifras a veces llegan como texto ('0.78', '-12,5 %').
    Una coma seguida de exactamente 3 cifras es ambigua (separador de miles): no se convierte."""
    datos = _dict(valor, avisos, campo)
    cambiadas = []
    for clave, hoja in datos.items():
        if isinstance(hoja, str) and clave not in _CIFRAS_EXENTAS:
            m = _NUMERO.match(hoja)
            if m:
                numero = m.group(1)
                if "," in numero and len(numero.split(",", 1)[1]) == 3:
                    continue
                datos[clave] = float(numero.replace(",", "."))
                cambiadas.append(clave)
    if cambiadas:
        avisos.append(f"{campo}: cifras en texto pasadas a numero ({', '.join(cambiadas)})")
    return datos


def _plazo(valor, avisos, campo):
    if valor is None:
        return None
    original = _texto(valor, avisos, campo)
    normalizado = original.strip().upper()
    if normalizado in PLAZOS:
        if normalizado != original:
            avisos.append(f"plazo normalizado: {valor!r} -> {normalizado!r}")
        return normalizado
    if normalizado in _PLAZO_ALIAS:
        avisos.append(f"plazo normalizado: {valor!r} -> {_PLAZO_ALIAS[normalizado]!r}")
        return _PLAZO_ALIAS[normalizado]
    return original


_TIPOS = {"texto": _texto, "texto_o_nulo": _texto_o_nulo, "lista_texto": _lista_texto, "bool": _bool,
          "dict": _dict, "cifras": _cifras, "plazo": _plazo}


def limpiar(agente, datos):
    if not isinstance(datos, dict):
        return {}, [], ["la respuesta no es un objeto JSON"]
    limpio, avisos, errores = copy.deepcopy(datos), [], []
    for campo, tipo in ESQUEMAS.get(agente, {}).items():
        if campo not in limpio:
            continue
        try:
            limpio[campo] = _TIPOS[tipo](limpio[campo], avisos, campo)
        except _NoVale as e:
            errores.append(f"{campo}: {e}")
    return limpio, avisos, errores
