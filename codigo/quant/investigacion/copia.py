import contextlib
import os
import shutil
import sqlite3
from pathlib import Path


def _copiar_carpeta(origen, destino):
    if not origen.is_dir():
        return 0
    shutil.copytree(origen, destino, dirs_exist_ok=True)
    return sum(1 for p in destino.rglob("*") if p.is_file())


def copiar(raiz, destino=None, ahora=None):
    raiz = Path(raiz)
    if destino is None:
        base = os.environ.get("OneDrive")
        if not base:
            return {"omitido": "sin OneDrive"}
        destino = Path(base) / "Quant"
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    salida = {"destino": str(destino), "catalogo": False, "informes": 0, "skills": 0}
    origen_db = raiz / "catalogo.db"
    if origen_db.exists():
        with contextlib.closing(sqlite3.connect(origen_db)) as src:
            with contextlib.closing(sqlite3.connect(destino / "catalogo.db")) as dst:
                src.backup(dst)
        salida["catalogo"] = True
    salida["informes"] = _copiar_carpeta(raiz / "informes", destino / "informes")
    salida["skills"] = _copiar_carpeta(raiz / "skills", destino / "skills")
    return salida
