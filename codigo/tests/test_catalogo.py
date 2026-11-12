from pathlib import Path

import pytest

from quant.investigacion import catalogo


@pytest.fixture
def con(tmp_path):
    return catalogo.abrir(tmp_path / "c.db")


def test_anadir_y_duplicados(con, tmp_path):
    uno = catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "texto uno", tmp_path)
    assert uno and catalogo.texto(con, uno, tmp_path) == "texto uno"
    assert catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "otro", tmp_path) is None
    assert catalogo.anadir_documento(con, "reddit", "u2", "T2", "2026-01-01", "texto uno", tmp_path) is None
    assert catalogo.anadir_documento(con, "reddit", "u2", "T2", "2026-01-01", "texto dos", tmp_path)


def test_duplicado_no_deja_transaccion_abierta(con, tmp_path):
    """Un duplicado dejaba la transaccion viva y bloqueaba al resto de conexiones toda la noche."""
    otra = catalogo.abrir(tmp_path / "c.db")
    catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "texto uno", tmp_path)
    assert catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "otro", tmp_path) is None
    assert con.in_transaction is False
    catalogo.guardar_extracto(otra, 1, {"operable": "si"})
    assert catalogo.extracto(otra, 1) == {"operable": "si"}


def test_fallo_al_escribir_el_texto_no_deja_transaccion_abierta(con, tmp_path, monkeypatch):
    """Si el fichero de texto no se puede escribir, el INSERT ya hecho no puede quedarse en vuelo."""
    otra = catalogo.abrir(tmp_path / "c.db")
    monkeypatch.setattr(Path, "write_text", lambda *a, **kw: (_ for _ in ()).throw(OSError("disco lleno")))
    with pytest.raises(OSError):
        catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "texto uno", tmp_path)
    assert con.in_transaction is False
    monkeypatch.undo()
    assert catalogo.anadir_documento(otra, "arxiv", "u1", "T1", "2026-01-01", "texto uno", tmp_path)


def test_pendientes_y_marcar(con, tmp_path):
    a = catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "aaa", tmp_path)
    b = catalogo.anadir_documento(con, "arxiv", "u2", "T2", "2026-01-02", "bbb", tmp_path)
    assert [r["id"] for r in catalogo.pendientes(con, "nuevo")] == [a, b]
    catalogo.marcar(con, a, "leido")
    assert [r["id"] for r in catalogo.pendientes(con, "nuevo")] == [b]
    assert [r["id"] for r in catalogo.pendientes(con, "leido")] == [a]
    for _ in range(3):
        catalogo.marcar(con, b, "nuevo", error="falla")
    assert catalogo.pendientes(con, "nuevo") == []


def test_extracto_ficha_resultado_y_resumen(con, tmp_path):
    doc = catalogo.anadir_documento(con, "arxiv", "u1", "T1", "2026-01-01", "aaa", tmp_path)
    assert catalogo.extracto(con, doc) is None
    catalogo.guardar_extracto(con, doc, {"operable": "si", "extracto": "regla"})
    assert catalogo.extracto(con, doc)["operable"] == "si"
    ficha_id = catalogo.guardar_ficha(con, doc, {"id": "x"}, "aprobada")
    catalogo.guardar_resultado(con, ficha_id, "SPY", "no_pasa", {"criterios": []})
    catalogo.marcar(con, doc, "validado")
    r = catalogo.resumen(con)
    assert r["documentos"]["validado"] == 1 and r["fichas"]["aprobada"] == 1 and r["resultados"]["no_pasa"] == 1
    assert [f["json"] for f in catalogo.fichas(con, "aprobada")] == ['{"id": "x"}']


def test_cambios_de_skill(con):
    catalogo.registrar_cambio_skill(con, "formalizador", "menos supuestos", 0.71, 0.74, True)
    fila = con.execute("SELECT * FROM skills_cambios").fetchone()
    assert (fila["agente"], fila["aceptado"]) == ("formalizador", 1)


def test_origen_del_cambio_y_migracion(tmp_path):
    import sqlite3
    ruta = tmp_path / "viejo.db"
    viejo = sqlite3.connect(ruta)
    viejo.execute("CREATE TABLE skills_cambios (id INTEGER PRIMARY KEY, agente TEXT, motivo TEXT, nota_antes REAL,"
                  " nota_despues REAL, aceptado INTEGER, creado TEXT)")
    viejo.execute("INSERT INTO skills_cambios (agente, motivo, aceptado, creado) VALUES ('lector','m',1,'2026-09-16')")
    viejo.commit(); viejo.close()
    con = catalogo.abrir(ruta)
    catalogo.registrar_cambio_skill(con, "critico", "nota", 0.6, 0.7, True, origen="supervisor")
    filas = con.execute("SELECT agente, origen FROM skills_cambios ORDER BY id").fetchall()
    assert [(f["agente"], f["origen"]) for f in filas] == [("lector", None), ("critico", "supervisor")]
    con.close()
    catalogo.abrir(ruta).close()
