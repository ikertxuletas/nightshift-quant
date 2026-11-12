from quant.familias import Family


def generate(p, instruments, timeframe, filter):
    return {"tipo": "momentum_transversal", "forma": "transversal",
            "universo": {"instrumentos": instruments, "plazo": timeframe},
            "transversal": {"ranking": f"MOM({p['window']})", "cada_barras": 21, "top": p["top"]},
            "gestion": {}}


FAMILY = Family(
    "momentum_rotacion", "Cada mes compra los instrumentos que más han subido en el último tramo y rota el resto.",
    {"window": (63, 126, 252), "top": (1, 3)},
    ("indice", "cripto", "materia"), ("D1",), "transversal", generate)
