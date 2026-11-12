import json
from pathlib import Path

from quant import rutas


def cargar(ruta=None):
    return json.loads((ruta or rutas.CONFIG / "demo.json").read_text(encoding="utf-8"))


def cargar_de(raiz):
    ruta = Path(raiz) / "config" / "demo.json"
    return cargar(ruta if ruta.exists() else Path(__file__).parents[3] / "config" / "demo.json")
