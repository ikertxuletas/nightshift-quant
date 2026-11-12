"""Example own strategy: Larry Connors' RSI(2) pullback, adapted to SP500 15-minute bars in the New York session."""
from quant.familias import Family

HORARIO = {"zona": "America/New_York", "sesiones": [{"desde": "09:30", "hasta": "15:30"}]}


def generate(p, instruments, timeframe, filter):
    rsi = f"RSI({p['n']})"
    return {
        "tipo": "otro", "forma": "serie_temporal",
        "universo": {"instrumentos": instruments, "plazo": timeframe},
        "entrada": {"largo": {"y": [{"<": [rsi, p["umbral"]]}, {">": ["close", "SMA(200)"]}]},
                    "corto": {"y": [{">": [rsi, 100 - p["umbral"]]}, {"<": ["close", "SMA(200)"]}]}},
        "salida": {"largo": {"o": [{"cruza_arriba": ["close", "SMA(5)"]}]},
                   "corto": {"o": [{"cruza_abajo": ["close", "SMA(5)"]}]}},
        "gestion": {"stop": {"tipo": "barras", "valor": 16}, "max_barras": 64, "perdida_diaria_max": 2,
                    "tamano": {"tipo": "riesgo", "valor": 1.0}},
        "horario": HORARIO,
        "supuestos": ["RSI(2) de Larry Connors (Short Term Trading Strategies That Work, 2008), llevado a velas de 15 minutos.",
                      "Solo en la sesión regular de Nueva York.",
                      "Stop en el extremo de las últimas 16 velas."],
    }


FAMILY = Family(
    "ejemplo", "Estrategia propia de ejemplo: compra un retroceso fuerte (RSI de 2 velas muy bajo) a favor de la media de "
    "200 y vende al recuperar la media de 5; lo contrario para cortos, en la sesión americana.",
    {"n": (2, 3), "umbral": (5, 10)},
    ("US500",), ("M15",), "serie_temporal", generate)
