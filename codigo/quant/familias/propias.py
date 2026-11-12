"""the owner's own strategies: kept out of the sweep and the ranking, iterated nightly by the lab instead."""
from dataclasses import dataclass

from quant import familias


@dataclass(frozen=True)
class Propia:
    name: str
    family: str
    params: dict
    instrument: str
    timeframe: str
    origen: str
    corte: str
    confirmacion: str


PROPIAS = {
    "ejemplo": Propia("ejemplo", "ejemplo", {"n": 2, "umbral": 10}, "US500", "M15",
                      "RSI(2) de Larry Connors, adaptado a velas de 15 minutos", "2023-01-01", "2026-04-01"),
    "manual": Propia("manual", "manual", {"stop_atr": 2.0, "objetivo_atr": 3.0}, "US500", "M15",
                     "Ejemplo de operativa manual descrita con palabras", "2023-01-01", "2026-04-01"),
}


def ficha_base(name):
    p = PROPIAS[name]
    return familias.to_ficha(familias.Combo(p.family, p.params, (p.instrument,), p.timeframe, "sin_filtro", "laboratorio"))


def es_propia(family):
    return any(p.family == family for p in PROPIAS.values())
