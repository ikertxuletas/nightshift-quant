import hashlib
import json
import sys
from pathlib import Path

from quant import rutas


class ErrorCriterios(RuntimeError):
    pass


def huella(ruta):
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def firmar(config=rutas.CONFIG):
    valor = huella(Path(config) / "criterios.json")
    (Path(config) / "criterios.sha256").write_text(valor, encoding="ascii")
    return valor


def cargar(config=rutas.CONFIG):
    ruta, firma = Path(config) / "criterios.json", Path(config) / "criterios.sha256"
    if not firma.exists():
        raise ErrorCriterios("criterios sin firma: ejecutar 'python -m quant.criterios --firmar'")
    if firma.read_text(encoding="ascii").strip() != huella(ruta):
        raise ErrorCriterios("criterios.json cambiado sin firmar: parada")
    return json.loads(ruta.read_text(encoding="utf-8"))


if __name__ == "__main__":
    if "--firmar" in sys.argv:
        print(f"firmado {firmar()}")
    else:
        print(json.dumps(cargar(), indent=2))
