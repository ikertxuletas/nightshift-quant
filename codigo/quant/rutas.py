import os
from pathlib import Path

RAIZ = Path(os.environ.get("QUANT_RAIZ", Path(__file__).resolve().parents[2]))
CONFIG = RAIZ / "config"
DATOS = RAIZ / "datos"
