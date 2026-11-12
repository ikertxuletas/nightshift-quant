"""Cliente HTTP para modelos locales servidos por Ollama."""
import json
import os
import subprocess
import time

import requests

from quant import rutas
from quant.investigacion import memoria

BASE = os.environ.get("QUANT_OLLAMA", "http://localhost:11434")
OLLAMA_EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
LLAMA_SERVER = os.path.join(os.path.dirname(OLLAMA_EXE), "lib", "ollama", "llama-server.exe")
MENSAJE_SIN_MOTOR = "ollama sin motor: falta llama-server.exe (reinstalar Ollama)"


class ErrorModelo(RuntimeError):
    pass


class _Reintentar(ErrorModelo):
    pass


REINTENTOS_500 = 2


def _normalizar(nombre):
    """Nombre completo en minusculas; solo se rellena la etiqueta cuando falta, nunca se recorta."""
    nombre = (nombre or "").strip().lower()
    if not nombre or ":" in nombre:
        return nombre
    return nombre + ":latest"


def _descargar_otros_modelos(cargados, objetivo, sesion, base):
    """Descarga (keep_alive: 0) los modelos cargados que no son el objetivo, para que Ollama libere
    su RAM el solo antes de recurrir a cerrar programas de usuario. Fail-open por modelo."""
    for m in cargados:
        nombre = m.get("name") or m.get("model")
        if not nombre or _normalizar(nombre) == objetivo:
            continue
        try:
            sesion.post(f"{base or BASE}/api/generate", json={"model": nombre, "keep_alive": 0}, timeout=10)
        except Exception:
            pass


def _lanzar_ollama(exe):
    return subprocess.Popen([exe, "serve"], creationflags=0x08000000, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


def asegurar_servidor(sesion=None, base=None, lanzar=None, dormir=time.sleep, espera_max=90):
    """Si Ollama no responde (p.ej. tras autoactualizarse), lo relanza sin ventana y espera a que conteste."""
    if disponible(sesion, base):
        return True
    exe = os.environ.get("QUANT_OLLAMA_EXE", OLLAMA_EXE)
    if not os.path.exists(exe):
        return False
    (lanzar or _lanzar_ollama)(exe)
    for _ in range(int(espera_max // 2)):
        dormir(2)
        if disponible(sesion, base):
            return True
    return False


def _preparar(modelo, sesion, base, raiz, dormir=time.sleep, libre=None):
    """Libera RAM si el modelo no esta ya cargado en Ollama. Fail-open: cualquier fallo se ignora."""
    libre = libre or memoria.libre_gb
    try:
        objetivo = _normalizar(modelo)
        try:
            cargados = sesion.get(f"{base or BASE}/api/ps", timeout=10).json().get("models") or []
        except requests.RequestException:
            asegurar_servidor(sesion=sesion, base=base, dormir=dormir)
            return
        nombres_cargados = set()
        for m in cargados:
            for clave in ("name", "model"):
                valor = m.get(clave)
                if valor:
                    nombres_cargados.add(_normalizar(valor))
        if objetivo in nombres_cargados:
            return
        tags = sesion.get(f"{base or BASE}/api/tags", timeout=10).json().get("models") or []
        tamano = next((t.get("size") for t in tags if _normalizar(t.get("name")) == objetivo), None)
        if not tamano:
            return
        config = memoria.cargar_config(raiz)
        necesario = tamano / (1024 ** 3) + config.get("margen_gb", 1.0)
        if cargados and libre() < necesario:
            _descargar_otros_modelos(cargados, objetivo, sesion, base)
            dormir(2)
        memoria.liberar(necesario, config, raiz=raiz)
    except Exception:
        pass


def _espera_tras_500(raiz):
    """Fail-open: config invalida o valor no numerico no debe impedir el reintento."""
    try:
        config = memoria.cargar_config(raiz)
        if not isinstance(config, dict):
            raise TypeError("config de memoria invalida")
        return float(config.get("espera_tras_500_segundos", 60))
    except Exception:
        return 60.0


def _detalle_error(respuesta, defecto):
    detalle = None
    try:
        cuerpo = respuesta.json()
        if isinstance(cuerpo, dict):
            detalle = cuerpo.get("error")
    except Exception:
        detalle = None
    return detalle or getattr(respuesta, "text", None) or defecto


def _enviar(sesion, cuerpo, base, modelo, timeout):
    datos = None
    try:
        respuesta = sesion.post(f"{base or BASE}/api/chat", json=cuerpo, timeout=timeout)
        estado = getattr(respuesta, "status_code", None)
        if estado == 500:
            raise _Reintentar(f"fallo de conexion con {modelo}: {_detalle_error(respuesta, 'HTTP 500')}")
        if estado == 400:
            raise ErrorModelo(f"fallo de conexion con {modelo}: {_detalle_error(respuesta, 'HTTP 400')}")
        respuesta.raise_for_status()
        datos = respuesta.json()
        return datos["message"]["content"]
    except requests.RequestException as e:
        raise ErrorModelo(f"fallo de conexion con {modelo}: {e}") from e
    except (KeyError, TypeError, ValueError) as e:
        motivo = datos.get("error") if isinstance(datos, dict) else None
        raise ErrorModelo(motivo or f"respuesta sin contenido de {modelo}: {e}") from e


def chat(modelo, system, prompt, formato=None, opciones=None, timeout=900, sesion=None, base=None,
         raiz=None, dormir=time.sleep):
    cuerpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.1, "num_ctx": 16384, **(opciones or {})},
    }
    if formato is not None:
        cuerpo["format"] = formato
    sesion = sesion or requests.Session()
    raiz = raiz or rutas.RAIZ
    _preparar(modelo, sesion, base, raiz, dormir=dormir)
    for _ in range(REINTENTOS_500):
        try:
            return _enviar(sesion, cuerpo, base, modelo, timeout)
        except _Reintentar:
            _preparar(modelo, sesion, base, raiz, dormir=dormir)
            dormir(_espera_tras_500(raiz))
    try:
        return _enviar(sesion, cuerpo, base, modelo, timeout)
    except _Reintentar as e:
        raise ErrorModelo(str(e)) from e


def json_de(texto):
    limpio = texto.replace("```json", "```").strip()
    if limpio.startswith("```"):
        limpio = limpio[3:]
    if limpio.endswith("```"):
        limpio = limpio[:-3]
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio == -1 or fin == -1 or fin < inicio:
        raise ErrorModelo(f"sin JSON valido en la respuesta: {texto}")
    try:
        return json.loads(limpio[inicio:fin + 1])
    except ValueError as e:
        raise ErrorModelo(f"JSON malformado: {e}") from e


def disponible(sesion=None, base=None):
    sesion = sesion or requests.Session()
    try:
        respuesta = sesion.get(f"{base or BASE}/api/tags", timeout=5)
        respuesta.raise_for_status()
        return True
    except requests.RequestException:
        return False


def motor_presente(exe=None):
    """Comprobacion pura de fichero: un rollback de autoactualizacion puede borrar el binario que
    de verdad carga los modelos aunque Ollama siga respondiendo a /api/tags."""
    ruta = exe or os.environ.get("QUANT_LLAMA_SERVER", LLAMA_SERVER)
    return os.path.exists(ruta)
