import json

from quant.investigacion import catalogo, explorar


def _fuente(nombre, n=2):
    def f(sesion, max_n=20, dormir=None):
        return [{"fuente": nombre, "url": f"{nombre}://{i}", "titulo": f"T{i}",
                 "fecha": "2026-09-01", "texto": f"texto {nombre} {i}"} for i in range(n)]
    return f


def test_explorar_guarda_y_deduplica(tmp_path, capsys):
    registro = {"arxiv": _fuente("arxiv"), "reddit": _fuente("reddit")}
    assert explorar.main(["--raiz", str(tmp_path)], sesion=object(), registro=registro, materiales=[]) == 0
    con = catalogo.abrir(tmp_path / "catalogo.db")
    assert len(catalogo.pendientes(con, "nuevo")) == 4
    assert explorar.main(["--raiz", str(tmp_path)], sesion=object(), registro=registro, materiales=[]) == 0
    assert len(catalogo.pendientes(con, "nuevo")) == 4
    ultimo = json.loads((tmp_path / "registro" / "explorar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["nuevos"] == 0 and ultimo["por_fuente"]["arxiv"] == 0


def test_una_fuente_rota_no_para_el_resto(tmp_path):
    def rota(sesion, max_n=20, dormir=None):
        raise RuntimeError("caida")
    registro = {"arxiv": rota, "reddit": _fuente("reddit")}
    assert explorar.main(["--raiz", str(tmp_path)], sesion=object(), registro=registro, materiales=[]) == 0
    con = catalogo.abrir(tmp_path / "catalogo.db")
    assert [r["fuente"] for r in catalogo.pendientes(con, "nuevo")] == ["reddit", "reddit"]
    ultimo = json.loads((tmp_path / "registro" / "explorar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["errores"] == 1


def test_todas_las_fuentes_rotas_falla(tmp_path):
    def rota(sesion, max_n=20, dormir=None):
        raise RuntimeError("caida")
    registro = {"arxiv": rota, "reddit": rota}
    assert explorar.main(["--raiz", str(tmp_path)], sesion=object(), registro=registro, materiales=[]) == 1
    ultimo = json.loads((tmp_path / "registro" / "explorar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["errores"] == 2


def test_solo_y_materiales(tmp_path):
    registro = {"arxiv": _fuente("arxiv"), "reddit": _fuente("reddit")}
    propios = [{"fuente": "materiales", "url": "materiales://a.md", "titulo": "a", "fecha": "2026-09-01",
                "texto": "mi estrategia"}]
    explorar.main(["--raiz", str(tmp_path), "--solo", "reddit"], sesion=object(), registro=registro,
                  materiales=propios)
    con = catalogo.abrir(tmp_path / "catalogo.db")
    assert sorted({r["fuente"] for r in catalogo.pendientes(con, "nuevo")}) == ["materiales", "reddit"]


def test_materiales_rotos_no_paran_el_explorador(tmp_path):
    (tmp_path / "materiales").mkdir(parents=True, exist_ok=True)
    (tmp_path / "materiales" / "roto.pdf").write_bytes(b"no es pdf")
    registro = {"reddit": _fuente("reddit")}
    assert explorar.main(["--raiz", str(tmp_path)], sesion=object(), registro=registro) == 0
    con = catalogo.abrir(tmp_path / "catalogo.db")
    docs_reddit = [r for r in catalogo.pendientes(con, "nuevo") if r["fuente"] == "reddit"]
    assert len(docs_reddit) == 2
    ultimo = json.loads((tmp_path / "registro" / "explorar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["errores"] == 1
