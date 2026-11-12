import fnmatch
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ROLES = {"jefe", "motor", "estrategias", "demo", "panel", "operaciones", "revisor"}


def _tabla():
    filas = {}
    for linea in (RAIZ / "CLAUDE.md").read_text(encoding="utf-8").splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if linea.startswith("|") and len(celdas) == 4 and celdas[0] not in ("Role", "") and not set(celdas[0]) <= {"-"}:
            rutas = re.findall(r"`([^`]+)`", celdas[2])
            filas[celdas[0].strip("*").lower()] = rutas
    return filas


def test_every_role_has_file_and_unique_zones():
    filas = _tabla()
    assert set(filas) == ROLES
    for rol in ROLES:
        assert (RAIZ / "roles" / f"{rol}.md").is_file()
    todas = [r for rutas in filas.values() for r in rutas]
    assert len(todas) == len(set(todas))
    assert filas["revisor"] == []


def test_owner_only_paths_not_writable():
    todas = [r for rutas in _tabla().values() for r in rutas]
    for prohibida in ("config/criterios.json", "config/costes.json", "examen/"):
        for z in todas:
            assert not _cubre(z, prohibida), (z, prohibida)


def _cubre(zona, ruta):
    if "*" in zona:
        return fnmatch.fnmatch(ruta, zona) and ruta.count("/") == zona.count("/")
    return ruta == zona or (zona.endswith("/") and ruta.startswith(zona))


def test_planned_paths_have_exactly_one_owner():
    filas = _tabla()
    previstas = [
        "codigo/quant/barrido.py", "codigo/quant/ranking.py", "codigo/quant/familias/cruce_medias.py",
        "codigo/quant/demo/pasada.py", "codigo/quant/panel/servidor.py", "config/demo.json",
        "codigo/quant/actualizar.py", "codigo/quant/motor.py", "codigo/quant/esquema_ficha.json",
        "codigo/quant/investigacion/noche.py", "codigo/instalar_tareas.ps1",
    ]
    for ruta in previstas:
        duenos = {(r, z) for r, zs in filas.items() for z in zs if "*" not in z and _cubre(z, ruta)}
        if not duenos:
            duenos = {(r, z) for r, zs in filas.items() for z in zs if _cubre(z, ruta)}
        assert len({r for r, _ in duenos}) == 1, (ruta, duenos)


def test_no_phantom_zones():
    carpetas = ("codigo/", "config/", "docs/", "roles/", "encargos/", "informes/", "skills/")
    for rutas in _tabla().values():
        for z in rutas:
            assert z == "CLAUDE.md" or z.startswith(carpetas), z
