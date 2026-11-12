import json

from quant.investigacion import examen

ESPERADO = {"operable": "si", "tipo": "reversion", "mercado": ["accion"], "plazo": "D1",
            "extracto": "Compramos cuando el RSI(2) cae por debajo de 10. Vendemos al superar la SMA(5).",
            "prometido": {"sharpe": 1.2}, "alarmas": []}
FICHA = {"id": "a", "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
         "entrada": {"largo": {"<": ["RSI(2)", 10]}}}


def test_nota_extracto():
    assert examen.nota_extracto(ESPERADO, ESPERADO) == 1.0
    parcial = {**ESPERADO, "plazo": "H1", "extracto": "Compramos cuando el RSI(2) cae por debajo de 10."}
    assert 0.4 < examen.nota_extracto(ESPERADO, parcial) < 0.95
    malo = {"operable": "no", "tipo": "otro", "mercado": ["cripto"], "plazo": "", "extracto": "", "prometido": {},
            "alarmas": []}
    assert examen.nota_extracto(ESPERADO, malo) < 0.2
    sin_cifras = {**malo, "mercado": [], "prometido": {}}
    plantilla = {**sin_cifras, "prometido": {"sharpe": 0, "drawdown": 0, "cagr": 0, "acierto": 0,
                                             "periodo": "", "cita": ""}}
    assert examen.nota_extracto(sin_cifras, plantilla) == 1.0


def test_los_booleanos_del_prometido_cuentan():
    esperado = {"operable": "si", "tipo": "reversion", "mercado": [], "plazo": "D1", "extracto": "",
                "prometido": {"con_costes": False}, "alarmas": []}
    obtenido = {**esperado, "prometido": {"con_costes": True}}
    assert examen._prometido_real({"con_costes": False}) == {"con_costes=false"}
    assert examen.nota_extracto(esperado, obtenido) < 1.0
    assert examen.nota_extracto(esperado, esperado) == 1.0


def test_nota_ficha():
    assert examen.nota_ficha(FICHA, FICHA) == 1.0
    cambiada = {**FICHA, "entrada": {"largo": {"<": ["RSI(2)", 5]}}}
    assert 0.5 < examen.nota_ficha(FICHA, cambiada) < 1.0
    assert examen.nota_ficha(FICHA, {"id": "z"}) < 0.3


def test_nota_critica():
    assert examen.nota_critica({"veredicto": "devolver"}, {"veredicto": "devolver"}) == 1.0
    assert examen.nota_critica({"veredicto": "devolver"}, {"veredicto": "rechazada"}) == 0.5
    assert examen.nota_critica({"veredicto": "devolver"}, {"veredicto": "aprobada"}) == 0.0


def test_evaluar_con_agente_falso(tmp_path):
    caso = tmp_path / "caso1"
    caso.mkdir()
    (caso / "meta.json").write_text(json.dumps({"titulo": "T", "fuente": "arxiv", "agentes": ["lector"]}),
                                    encoding="utf-8")
    (caso / "documento.txt").write_text("texto del documento", encoding="utf-8")
    (caso / "extracto.json").write_text(json.dumps(ESPERADO), encoding="utf-8")
    resultado = examen.evaluar("lector", llamar=lambda *a, **k: json.dumps(ESPERADO), casos=tmp_path)
    assert resultado["casos"] == 1 and resultado["nota"] == 1.0
    roto = examen.evaluar("lector", llamar=lambda *a, **k: "no json", casos=tmp_path)
    assert roto["nota"] == 0.0 and roto["detalle"][0]["nota"] == 0.0


def _caso_no_expresable(tmp_path):
    caso = tmp_path / "caso1"
    caso.mkdir()
    (caso / "meta.json").write_text(json.dumps({"titulo": "T", "fuente": "quantpedia", "url": "u", "cita": "c",
                                                "agentes": ["formalizador"]}), encoding="utf-8")
    (caso / "documento.txt").write_text("texto del documento", encoding="utf-8")
    (caso / "extracto.json").write_text(json.dumps(ESPERADO), encoding="utf-8")
    (caso / "ficha.json").write_text(json.dumps({"expresable": False}), encoding="utf-8")
    return caso


def test_evaluar_formalizador_acierta_al_no_expresar(tmp_path):
    _caso_no_expresable(tmp_path)
    respuesta = json.dumps({"expresable": False, "motivo": "necesita datos de tipos de interes", "ficha": None})
    resultado = examen.evaluar("formalizador", llamar=lambda *a, **k: respuesta, casos=tmp_path)
    assert resultado["casos"] == 1 and resultado["nota"] == 1.0


def test_evaluar_formalizador_falla_si_inventa_ficha(tmp_path):
    _caso_no_expresable(tmp_path)
    ficha = {"id": "prueba-1", "titulo": "Prueba", "tipo": "tendencia", "forma": "serie_temporal",
             "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
             "entrada": {"largo": {">": ["close", "SMA(200)"]}}, "gestion": {}}
    respuesta = json.dumps({"expresable": True, "motivo": "", "ficha": ficha})
    resultado = examen.evaluar("formalizador", llamar=lambda *a, **k: respuesta, casos=tmp_path)
    assert resultado["nota"] == 0.0


def test_evaluar_critico_con_varias_criticas(tmp_path):
    caso = tmp_path / "caso1"
    caso.mkdir()
    (caso / "meta.json").write_text(json.dumps({"titulo": "T", "fuente": "quantpedia", "agentes": ["critico"]}),
                                    encoding="utf-8")
    (caso / "documento.txt").write_text("texto del documento", encoding="utf-8")
    (caso / "extracto.json").write_text(json.dumps(ESPERADO), encoding="utf-8")
    (caso / "critica.json").write_text(json.dumps([
        {"ficha": FICHA, "veredicto": "devolver", "motivos": ["inventa el stop"]},
        {"ficha": FICHA, "veredicto": "aprobada", "motivos": []}]), encoding="utf-8")
    respuesta = json.dumps({"veredicto": "aprobada", "motivos": []})
    resultado = examen.evaluar("critico", llamar=lambda *a, **k: respuesta, casos=tmp_path)
    assert resultado["casos"] == 1 and resultado["nota"] == 0.5


def test_guardar_y_leer_nota(tmp_path):
    notas = tmp_path / "notas.json"
    examen.guardar_nota({"agente": "lector", "nota": 0.8, "casos": 5, "modelo": "m"}, notas)
    assert examen.nota_guardada("lector", notas) == 0.8
    assert examen.nota_guardada("critico", notas) is None


def _casos_lector(tmp_path, n):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        carpeta = tmp_path / f"caso{i}"
        carpeta.mkdir()
        (carpeta / "meta.json").write_text(json.dumps({"titulo": "t", "fuente": "f", "agentes": ["lector"]}),
                                           encoding="utf-8")
        (carpeta / "documento.txt").write_text("texto del documento", encoding="utf-8")
        (carpeta / "extracto.json").write_text(json.dumps(ESPERADO), encoding="utf-8")
    return tmp_path


def _llamar_fijo(*a, **k):
    return json.dumps(ESPERADO)


def _sin_skills_ni_config_reales(tmp_path, monkeypatch):
    """Ni skills\\ ni config\\agentes.json reales: skill minima en tmp_path y ajustes fijos."""
    carpeta = tmp_path / "skills" / "lector"
    carpeta.mkdir(parents=True)
    (carpeta / "skill.md").write_text("skill de lector (una linea, no la real)", encoding="utf-8")
    monkeypatch.setattr(examen.agentes.especialistas, "agentes",
                        lambda config=None: {"lector": {"modelo": "haiku"}})
    return tmp_path / "skills"


def test_evaluar_se_corta_con_hasta(tmp_path, monkeypatch):
    raiz_skills = _sin_skills_ni_config_reales(tmp_path, monkeypatch)
    casos = _casos_lector(tmp_path / "casos", n=3)
    reloj = iter([0, 0, 100, 100, 100, 100, 100, 100]).__next__
    resultado = examen.evaluar("lector", llamar=_llamar_fijo, casos=casos, hasta=50, reloj=reloj,
                               raiz_skills=raiz_skills)
    assert resultado["interrumpido"] is True and resultado["concluyente"] is False
    assert resultado["casos"] < 3


def test_evaluar_completo_es_concluyente(tmp_path, monkeypatch):
    raiz_skills = _sin_skills_ni_config_reales(tmp_path, monkeypatch)
    casos = _casos_lector(tmp_path / "casos", n=2)
    resultado = examen.evaluar("lector", llamar=_llamar_fijo, casos=casos, raiz_skills=raiz_skills)
    assert resultado["interrumpido"] is False and resultado["concluyente"] is True


def test_nota_guardada_sin_casos_no_cuenta(tmp_path):
    notas = tmp_path / "notas.json"
    notas.write_text('{"lector": {"nota": 0.0, "casos": 0}, "critico": {"nota": 0.6, "casos": 5}}', encoding="utf-8")
    assert examen.nota_guardada("lector", notas) is None
    assert examen.nota_guardada("critico", notas) == 0.6


def test_examen_real_tiene_casos_suficientes():
    casos = sorted(p for p in examen.CASOS.iterdir() if p.is_dir())
    assert len(casos) >= 20
    fuentes = set()
    for caso in casos:
        meta = json.loads((caso / "meta.json").read_text(encoding="utf-8"))
        fuentes.add(meta["fuente"])
        assert meta["url"].startswith("http")
        assert (caso / "extracto.json").exists()
    assert len(fuentes) >= 3


def test_caso_sin_documento_se_salta(tmp_path):
    caso = tmp_path / "caso1"
    caso.mkdir()
    (caso / "meta.json").write_text(json.dumps({"titulo": "T", "fuente": "arxiv", "agentes": ["lector"]}),
                                    encoding="utf-8")
    (caso / "extracto.json").write_text(json.dumps(ESPERADO), encoding="utf-8")
    resultado = examen.evaluar("lector", llamar=lambda *a, **k: json.dumps(ESPERADO), casos=tmp_path)
    assert resultado["casos"] == 0 and resultado["detalle"] == []
