import numpy as np

from quant import indicadores

_COMPARADORES = {"<": np.less, ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal}


def _es_numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _valor(operando, barras, cache):
    if _es_numero(operando):
        return np.full(len(barras["close"]), float(operando))
    return indicadores.calcular(operando, barras, cache)


def _evaluar(cond, barras, cache):
    if "y" in cond or "o" in cond:
        hijos = [_evaluar(c, barras, cache) for c in cond.get("y", cond.get("o"))]
        union = np.logical_and if "y" in cond else np.logical_or
        return (union.reduce([v for v, _ in hijos]), np.logical_and.reduce([ok for _, ok in hijos]))
    if "no" in cond:
        valor, valido = _evaluar(cond["no"], barras, cache)
        return ~valor, valido
    (op, (a, b)), = cond.items()
    va, vb = _valor(a, barras, cache), _valor(b, barras, cache)
    valido = ~np.isnan(va) & ~np.isnan(vb)
    with np.errstate(invalid="ignore"):
        if op in _COMPARADORES:
            return _COMPARADORES[op](va, vb), valido
        pa, pb = indicadores.desplazar(va, 1), indicadores.desplazar(vb, 1)
        valido = valido & ~np.isnan(pa) & ~np.isnan(pb)
        if op == "cruza_arriba":
            return (va > vb) & (pa <= pb), valido
        if op == "cruza_abajo":
            return (va < vb) & (pa >= pb), valido
    raise ValueError(f"operador desconocido: {op}")


def evaluar(cond, barras, cache=None):
    valor, valido = _evaluar(cond, barras, {} if cache is None else cache)
    return valor & valido


def operandos(cond):
    if "y" in cond or "o" in cond:
        return [x for c in cond.get("y", cond.get("o")) for x in operandos(c)]
    if "no" in cond:
        return operandos(cond["no"])
    (_, par), = cond.items()
    return [x for x in par if isinstance(x, str)]
