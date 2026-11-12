import json
from dataclasses import dataclass, replace
from pathlib import Path


class ErrorCostes(KeyError):
    pass


@dataclass(frozen=True)
class Costes:
    broker: str
    clase: str
    spread_pct: float
    comision_pct: float
    deslizamiento_pct: float
    swap_pct_anual: float
    apalancamiento: float
    permite_corto: bool

    def escalar(self, k):
        return replace(self, spread_pct=self.spread_pct * k, comision_pct=self.comision_pct * k,
                       deslizamiento_pct=self.deslizamiento_pct * k, swap_pct_anual=self.swap_pct_anual * k)

    def precio_ejecucion(self, precio, compra):
        friccion = self.spread_pct / 2 + self.deslizamiento_pct
        return precio * (1 + friccion) if compra else precio * (1 - friccion)


def cargar(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def costes_de(instrumento, config, clase=None):
    try:
        ref = config["instrumentos"].get(instrumento) or config.get("por_clase", {})[clase]
        broker, clase_costes = ref.split("/")
        return Costes(broker=broker, clase=clase_costes, **config["brokers"][broker][clase_costes])
    except KeyError as e:
        raise ErrorCostes(f"sin costes definidos para {instrumento}") from e
