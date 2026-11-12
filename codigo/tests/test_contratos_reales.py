import json
import shutil
from pathlib import Path

import pytest

from quant.investigacion import catalogo, contratos, correo, revision

REALES = Path(__file__).resolve().parent / "reales"
PARTES = sorted(REALES.glob("parte_*.json"))
REVISIONES = sorted(REALES.glob("revision_*.json"))


@pytest.mark.parametrize("ruta", PARTES, ids=lambda r: r.name)
def test_parte_real_cumple_el_contrato_y_se_puede_contar(ruta, tmp_path):
    parte = json.loads(ruta.read_text(encoding="utf-8"))
    assert contratos.validar_parte(parte) == []
    fecha = parte["fecha"]
    con = catalogo.abrir(tmp_path / "catalogo.db")
    try:
        sin = {"estado": "sin revision", "error": "prueba"}
        assert correo.asunto(fecha, parte, sin).startswith("[Quant] ")
        assert "1." in correo.cuerpo(fecha, parte, sin, con)
        (tmp_path / "informes").mkdir()
        shutil.copy2(ruta, tmp_path / "informes" / f"parte_{fecha}.json")
        texto = revision.paquete(con, tmp_path, fecha)
        assert len(texto.encode("utf-8")) <= revision.MAX_BYTES
        assert texto.count("<<<DOCUMENTO") == texto.count("DOCUMENTO>>>") > 0
        assert revision.MARCA_RECORTE not in texto
    finally:
        con.close()


@pytest.mark.parametrize("ruta", REVISIONES, ids=lambda r: r.name)
def test_revision_real_cumple_el_contrato(ruta):
    assert contratos.validar_revision(json.loads(ruta.read_text(encoding="utf-8"))) == []


def test_hay_al_menos_una_noche_real():
    assert PARTES and REVISIONES
