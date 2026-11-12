import json

import pytest

from quant.familias import propias
from quant.investigacion import asesor, catalogo, claude_cli
from quant.investigacion import laboratorio as lab

BASE = propias.ficha_base("ejemplo")


@pytest.fixture
def con(tmp_path):
    c = catalogo.abrir(tmp_path / "catalogo.db")
    lab.ensure_schema(c)
    return c


def _exp(con, i, veredicto="no_pasa", examen=None, estrategia="ejemplo"):
    entreno = {"veredicto": veredicto, "criterios": [{"criterio": "drawdown", "cumple": False}],
               "metricas": {"total": {"profit_factor": 0.71, "operaciones": 300}}}
    return con.execute(
        "INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, entreno_json,"
        " examen_json, creado) VALUES (?, '2026-11-10', ?, ?, ?, 1, ?, ?, ?, 'x')",
        (estrategia, f"h{i}", json.dumps(BASE), f"motivo {i}", veredicto, json.dumps(entreno),
         json.dumps(examen) if examen else None)).lastrowid


def test_paquete_no_filtra_el_examen(con):
    eid = _exp(con, 1, "ganadora", examen={"profit_factor": 1.77})
    con.execute("INSERT INTO lab_ganadoras (experimento_id, estrategia, estado, examen_json) VALUES (?, 'ejemplo',"
                " 'vigente', ?)", (eid, json.dumps({"profit_factor": 1.88})))
    texto = asesor.paquete(con, {"ejemplo": propias.PROPIAS["ejemplo"]}, {"ejemplo": "MAPA"})
    assert "1.77" not in texto and "1.88" not in texto and "ganadora" not in texto
    assert "examen" not in texto.lower() and "pasa_validador" in texto and "MAPA" in texto and "motivo 1" in texto


def test_paquete_respeta_el_tope(con):
    for i in range(1, 3001):
        _exp(con, i)
    texto = asesor.paquete(con, dict(propias.PROPIAS), {"ejemplo": "M" * 5000})
    assert len(texto.encode("utf-8")) <= asesor.MAX_BYTES_ASESOR
    assert "#3000 " in texto and "#1 " not in texto


BUENA = {"informe": "Se aprendió algo.", "direccion": ["Try a slower Hull."], "direccion_es": ["Probar una Hull más lenta."],
         "propuestas": [{"que": "Indicador ADX", "motivo": "medir la fuerza de la tendencia"}]}


def test_validar_descarta_lo_raro():
    datos = {"estrategias": {"ejemplo": BUENA, "otra": BUENA,
                             "manual": {**BUENA, "direccion": ["a"] * 6, "direccion_es": ["a"] * 6}}}
    assert set(asesor.validar(datos, {"ejemplo", "manual"})) == {"ejemplo"}
    sin_es = {k: v for k, v in BUENA.items() if k != "direccion_es"}
    assert asesor.validar({"estrategias": {"ejemplo": sin_es}}, {"ejemplo"}) == {}
    assert asesor.validar("no es un dict", {"ejemplo"}) == {}


def _main(tmp_path, monkeypatch, respuesta):
    monkeypatch.setattr(claude_cli, "chat", lambda *a, **k: respuesta)
    return asesor.main(["--raiz", str(tmp_path), "--fecha", "20261115"])


def test_main_con_respuesta_rota_no_escribe(tmp_path, monkeypatch, con):
    assert _main(tmp_path, monkeypatch, "no json") == 0
    assert con.execute("SELECT COUNT(*) FROM lab_asesor").fetchone()[0] == 0
    linea = json.loads((tmp_path / "registro" / "asesor_20261115.log").read_text(encoding="utf-8").splitlines()[-1])
    assert linea["error"]


def test_main_guarda_y_la_direccion_queda_vigente(tmp_path, monkeypatch, con):
    assert _main(tmp_path, monkeypatch, json.dumps({"estrategias": {"manual": BUENA}})) == 0
    assert lab.direccion_vigente(con, "manual") == "Try a slower Hull."
    assert lab.direccion_vigente(con, "ejemplo") is None
