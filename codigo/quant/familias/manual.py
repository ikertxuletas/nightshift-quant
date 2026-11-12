"""Example of a manual trading routine described in words and turned into rules (SP500, intraday)."""
from quant.familias import Family

HORARIO = {"zona": "America/New_York", "sesiones": [{"desde": "10:00", "hasta": "15:00"}], "cierre": "15:55"}


def generate(p, instruments, timeframe, filter):
    return {
        "tipo": "otro", "forma": "serie_temporal",
        "universo": {"instrumentos": instruments, "plazo": timeframe},
        "entrada": {"largo": {"y": [{"cruza_arriba": ["EMA(9)", "EMA(21)"]}, {">": ["close", "SMA(200)"]}]},
                    "corto": {"y": [{"cruza_abajo": ["EMA(9)", "EMA(21)"]}, {"<": ["close", "SMA(200)"]}]}},
        "gestion": {"stop": {"tipo": "atr", "valor": p["stop_atr"]},
                    "objetivo": {"tipo": "atr", "valor": p["objetivo_atr"]},
                    "perdida_diaria_max": 2, "tamano": {"tipo": "riesgo", "valor": 1.0}},
        "horario": HORARIO,
        "supuestos": ["Entrada cuando la media de 9 cruza la de 21 a favor de la media de 200.",
                      "Stop y objetivo medidos en ATR desde la entrada.",
                      "Sin overnight: cierre a las 15:55 de Nueva York."],
    }


FAMILY = Family(
    "manual", "Operativa manual de ejemplo: entra cuando la media rápida cruza la lenta a favor de la tendencia "
    "(media de 200), con stop y objetivo medidos en ATR y todo cerrado antes del final de la sesión.",
    {"stop_atr": (1.5, 2.0, 3.0), "objetivo_atr": (2.0, 3.0, 4.0)},
    ("US500",), ("M15", "H1"), "serie_temporal", generate)
