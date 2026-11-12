import json

import pytest

from quant.investigacion import especialistas, local, skills


class SesionCreatePost:
    def __init__(self, respuesta):
        self.respuesta, self.enviado = respuesta, None

    def post(self, url, json=None, timeout=None):
        self.enviado = {"url": url, "json": json}
        return self

    def raise_for_status(self):
        return None

    def json(self):
        return self.respuesta


def _skills(tmp_path):
    for agente in ("lector",):
        carpeta = tmp_path / agente
        (carpeta / "ref").mkdir(parents=True)
        (carpeta / "skill.md").write_text("Eres el Lector.", encoding="utf-8")
        (carpeta / "notas.md").write_text("No confundas stop con trailing.", encoding="utf-8")
        (carpeta / "ref" / "alarmas.md").write_text("Sin costes = alarma.", encoding="utf-8")
    return tmp_path


def test_cargar_y_system(tmp_path):
    raiz = _skills(tmp_path)
    cargado = skills.cargar("lector", raiz)
    assert cargado["skill"].startswith("Eres el Lector")
    assert list(cargado["referencias"]) == ["alarmas"]
    completo = skills.system("lector", raiz=raiz)
    assert "Eres el Lector" in completo and "## Referencia: alarmas" in completo
    assert completo.index("Sin costes") < completo.index("No confundas")
    assert "alarmas" not in skills.system("lector", referencias=[], raiz=raiz)


def test_agente_sin_ficheros(tmp_path):
    assert skills.cargar("nadie", tmp_path) == {"skill": "", "notas": "", "referencias": {}}


def test_catalogo_de_indicadores_cubre_todo():
    texto = skills.catalogo_indicadores()
    from quant import indicadores
    for nombre in list(indicadores.CATALOGO) + list(indicadores.CAMPOS):
        assert nombre in texto
    assert "MAX(n)" in texto and "vela actual" in texto


def test_modelfile_y_crear(tmp_path):
    raiz = _skills(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "agentes.json").write_text(json.dumps({"lector": {"especialista": "quant-lector",
                                                                "modelo_base": "qwen3.5:35b-a3b",
                                                                "temperatura": 0.2, "contexto": 16384,
                                                                "formato": "json"}}), encoding="utf-8")
    texto = especialistas.modelfile("lector", config, raiz)
    assert texto.startswith("FROM qwen3.5:35b-a3b")
    assert "PARAMETER temperature 0.2" in texto and "PARAMETER num_ctx 16384" in texto
    assert "Eres el Lector" in texto
    s = SesionCreatePost({"status": "success"})
    nombre = especialistas.crear("lector", config, raiz, tmp_path / "especialistas", sesion=s)
    assert nombre == "quant-lector"
    assert (tmp_path / "especialistas" / "quant-lector.Modelfile").exists()
    assert s.enviado["url"] == f"{local.BASE}/api/create"
    json_enviado = s.enviado["json"]
    assert json_enviado["model"] == "quant-lector"
    assert json_enviado["from"] == "qwen3.5:35b-a3b"
    assert json_enviado["parameters"] == {"temperature": 0.2, "num_ctx": 16384}
    assert "Eres el Lector" in json_enviado["system"]

    s_error = SesionCreatePost({"error": "modelo no encontrado"})
    with pytest.raises(local.ErrorModelo):
        especialistas.crear("lector", config, raiz, tmp_path / "especialistas", sesion=s_error)


def test_llamar_por_defecto_es_claude():
    import inspect
    from quant.investigacion import agentes, canario, claude_cli, examen, mentor, relator
    for f in (agentes.leer, agentes.formalizar, agentes.criticar, agentes.procesar_lectura, agentes.procesar_fichas,
              relator.explicar, relator.procesar_relatos, mentor.proponer, mentor.ciclo, mentor.aplicar_con_examen,
              examen.evaluar, canario.ejecutar):
        assert inspect.signature(f).parameters["llamar"].default is claude_cli.chat, f.__qualname__


def test_agentes_json_real_usa_claude():
    from quant.investigacion import agentes
    esperados = {"lector": "haiku", "formalizador": "sonnet", "critico": "sonnet", "mentor": "sonnet",
                 "relator": "haiku"}
    for agente, modelo in esperados.items():
        assert agentes.ajustes(agente)["modelo"] == modelo
    assert especialistas.agentes()["_tope_llamadas_noche"] == 150
