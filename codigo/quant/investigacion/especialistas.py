"""Construccion de los especialistas de Ollama a partir de agentes.json y las skills."""
import json
import sys

import requests

from quant import rutas
from quant.investigacion import local, skills


def agentes(config=rutas.CONFIG):
    return json.loads((config / "agentes.json").read_text(encoding="utf-8"))


def modelfile(agente, config=rutas.CONFIG, raiz_skills=None):
    datos = agentes(config)[agente]
    sistema = skills.system(agente, raiz=raiz_skills)
    return (
        f"FROM {datos['modelo_base']}\n"
        f"PARAMETER temperature {datos['temperatura']}\n"
        f"PARAMETER num_ctx {datos['contexto']}\n"
        f'SYSTEM """{sistema}"""\n'
    )


def crear(agente, config=rutas.CONFIG, raiz_skills=None, carpeta=None, sesion=None):
    datos = agentes(config)[agente]
    carpeta = carpeta or (rutas.RAIZ / "especialistas")
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = datos["especialista"]
    ruta = carpeta / f"{nombre}.Modelfile"
    ruta.write_text(modelfile(agente, config, raiz_skills), encoding="utf-8")
    cuerpo = {
        "model": nombre,
        "from": datos["modelo_base"],
        "system": skills.system(agente, raiz=raiz_skills),
        "parameters": {"temperature": datos["temperatura"], "num_ctx": datos["contexto"]},
        "stream": False,
    }
    sesion = sesion or requests.Session()
    datos_respuesta = None
    try:
        respuesta = sesion.post(f"{local.BASE}/api/create", json=cuerpo, timeout=600)
        respuesta.raise_for_status()
        datos_respuesta = respuesta.json()
    except requests.RequestException as e:
        raise local.ErrorModelo(f"fallo al crear {nombre}: {e}") from e
    if not isinstance(datos_respuesta, dict) or datos_respuesta.get("status") != "success":
        motivo = datos_respuesta.get("error") if isinstance(datos_respuesta, dict) else datos_respuesta
        raise local.ErrorModelo(motivo or f"fallo al crear {nombre}")
    return nombre


if __name__ == "__main__":
    if "--crear" in sys.argv:
        objetivo = sys.argv[sys.argv.index("--crear") + 1:] or list(agentes())
        for agente in objetivo:
            print(crear(agente))
