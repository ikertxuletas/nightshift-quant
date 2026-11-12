import json
from pathlib import Path

import pytest
import requests

from quant.investigacion import local, memoria


class SesionPost:
    def __init__(self, respuesta, error=None):
        self.respuesta, self.error, self.enviado = respuesta, error, None

    def post(self, url, json=None, timeout=None):
        if self.error:
            raise self.error
        self.enviado = {"url": url, "cuerpo": json}
        return self

    def raise_for_status(self):
        return None

    def json(self):
        return self.respuesta


class SesionRespuestaNoJson(SesionPost):
    def json(self):
        raise ValueError("no json")


def test_chat_envia_lo_correcto():
    s = SesionPost({"message": {"content": "hola"}})
    assert local.chat("m", "sys", "pregunta", formato="json", sesion=s, base="http://x") == "hola"
    cuerpo = s.enviado["cuerpo"]
    assert s.enviado["url"] == "http://x/api/chat"
    assert cuerpo["model"] == "m" and cuerpo["stream"] is False and cuerpo["think"] is False
    assert cuerpo["format"] == "json" and cuerpo["options"]["temperature"] == 0.1
    assert [m["role"] for m in cuerpo["messages"]] == ["system", "user"]


def test_chat_errores():
    with pytest.raises(local.ErrorModelo):
        local.chat("m", "s", "p", sesion=SesionPost(None, error=requests.ConnectionError("no")))
    with pytest.raises(local.ErrorModelo):
        local.chat("m", "s", "p", sesion=SesionPost({"error": "modelo no encontrado"}))


def test_chat_respuesta_no_json():
    with pytest.raises(local.ErrorModelo):
        local.chat("m", "s", "p", sesion=SesionRespuestaNoJson({}))


def test_json_de_tolerante():
    assert local.json_de('```json\n{"a": 1}\n```') == {"a": 1}
    assert local.json_de('bla bla {"a": [1, 2]} fin') == {"a": [1, 2]}
    with pytest.raises(local.ErrorModelo):
        local.json_de("sin json")


class _RespuestaGet:
    def __init__(self, datos):
        self.datos = datos

    def json(self):
        return self.datos


class _RespuestaPost:
    def __init__(self, status_code=200, cuerpo=None):
        self.status_code = status_code
        self.cuerpo = cuerpo if cuerpo is not None else {"message": {"content": "ok"}}

    def raise_for_status(self):
        pass

    def json(self):
        return self.cuerpo


class SesionCompleta:
    def __init__(self, ps=None, tags=None, posts=None, error_ps=None):
        self.ps, self.tags, self.error_ps = ps or {"models": []}, tags or {"models": []}, error_ps
        self.posts = list(posts) if posts is not None else [_RespuestaPost()]
        self.llamadas_post = 0

    def get(self, url, timeout=None):
        if self.error_ps and url.endswith("/api/ps"):
            raise self.error_ps
        return _RespuestaGet(self.ps if url.endswith("/api/ps") else self.tags)

    def post(self, url, json=None, timeout=None):
        respuesta = self.posts[min(self.llamadas_post, len(self.posts) - 1)]
        self.llamadas_post += 1
        return respuesta


def test_chat_modelo_ya_cargado_no_llama_a_liberar(monkeypatch, tmp_path):
    llamado = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: llamado.append(1))
    s = SesionCompleta(ps={"models": [{"name": "m:latest"}]})
    assert local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path) == "ok"
    assert llamado == []


def test_chat_modelo_no_cargado_llama_a_liberar(monkeypatch, tmp_path):
    llamados = []
    monkeypatch.setattr(memoria, "liberar", lambda necesario, config, raiz=None: llamados.append(necesario))
    s = SesionCompleta(ps={"models": []}, tags={"models": [{"name": "m:latest", "size": 4 * 1024 ** 3}]})
    assert local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path) == "ok"
    assert llamados == [5.0]


def test_chat_500_libera_duerme_y_reintenta_una_vez(monkeypatch, tmp_path):
    dormidos = []
    preparados = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: preparados.append(1))
    monkeypatch.setattr(memoria, "cargar_config", lambda raiz: {"margen_gb": 2.0, "espera_tras_500_segundos": 42})
    posts = [_RespuestaPost(status_code=500), _RespuestaPost(cuerpo={"message": {"content": "segundo"}})]
    s = SesionCompleta(tags={"models": [{"name": "m:latest", "size": 1024 ** 3}]}, posts=posts)
    resultado = local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=dormidos.append)
    assert resultado == "segundo"
    assert dormidos == [42]
    assert len(preparados) == 2


def test_chat_dos_500_lanza_error_modelo(monkeypatch, tmp_path):
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: None)
    posts = [_RespuestaPost(status_code=500), _RespuestaPost(status_code=500)]
    s = SesionCompleta(posts=posts)
    with pytest.raises(local.ErrorModelo):
        local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=lambda s: None)


def test_chat_error_en_ps_no_impide_la_llamada(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "asegurar_servidor", lambda **k: False)
    s = SesionCompleta(error_ps=requests.ConnectionError("no"))
    assert local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path) == "ok"


# I2: modelos distintos de la misma familia no deben confundirse por el prefijo antes de ":".


def test_chat_no_confunde_modelos_de_la_misma_familia(monkeypatch, tmp_path):
    llamados = []
    monkeypatch.setattr(memoria, "liberar", lambda necesario, config, raiz=None: llamados.append(necesario))
    s = SesionCompleta(
        ps={"models": [{"name": "qwen3.5:27b"}]},
        tags={"models": [{"name": "qwen3.5:27b", "size": 16 * 1024 ** 3},
                          {"name": "qwen3.5:35b-a3b", "size": 20 * 1024 ** 3}]},
    )
    assert local.chat("qwen3.5:35b-a3b", "s", "p", sesion=s, base="http://x", raiz=tmp_path,
                      dormir=lambda s: None) == "ok"
    assert llamados == [21.0]


def test_chat_modelo_cargado_exacto_no_libera_aunque_haya_otro_de_la_familia(monkeypatch, tmp_path):
    llamado = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: llamado.append(1))
    s = SesionCompleta(ps={"models": [{"name": "qwen3.5:27b"}, {"name": "qwen3.5:35b-a3b"}]})
    assert local.chat("qwen3.5:35b-a3b", "s", "p", sesion=s, base="http://x", raiz=tmp_path) == "ok"
    assert llamado == []


def test_normalizar_solo_rellena_etiqueta_que_falta():
    assert local._normalizar("quant-lector") == "quant-lector:latest"
    assert local._normalizar("quant-lector:latest") == "quant-lector:latest"
    assert local._normalizar("qwen3.5:27b") != local._normalizar("qwen3.5:35b-a3b")


# M1: el camino de reintento tiene que ser a prueba de fallos con una config invalida.


def test_chat_500_con_config_no_numerica_usa_60_por_defecto(monkeypatch, tmp_path):
    dormidos = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: None)
    monkeypatch.setattr(memoria, "cargar_config", lambda raiz: {"espera_tras_500_segundos": "no-numero"})
    posts = [_RespuestaPost(status_code=500), _RespuestaPost(cuerpo={"message": {"content": "ok2"}})]
    s = SesionCompleta(posts=posts)
    resultado = local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=dormidos.append)
    assert resultado == "ok2"
    assert dormidos == [60.0]


def test_chat_500_con_config_que_no_es_dict_usa_60_por_defecto(monkeypatch, tmp_path):
    dormidos = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: None)
    monkeypatch.setattr(memoria, "cargar_config", lambda raiz: [])
    posts = [_RespuestaPost(status_code=500), _RespuestaPost(cuerpo={"message": {"content": "ok2"}})]
    s = SesionCompleta(posts=posts)
    resultado = local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=dormidos.append)
    assert resultado == "ok2"
    assert dormidos == [60.0]


# M2: el segundo 500 conserva el texto de error de Ollama.


def test_chat_dos_500_conserva_el_error_de_ollama(monkeypatch, tmp_path):
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: None)
    posts = [_RespuestaPost(status_code=500, cuerpo={"error": "model requires more system memory"}),
             _RespuestaPost(status_code=500, cuerpo={"error": "model requires more system memory"})]
    s = SesionCompleta(posts=posts)
    with pytest.raises(local.ErrorModelo, match="model requires more system memory"):
        local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=lambda s: None)


# A3: primero se intenta que Ollama libere solo, descargando otros modelos cargados;
# solo si con eso no alcanza se llama a memoria.liberar.


def test_preparar_descarga_otros_modelos_si_falta_ram_antes_de_liberar(monkeypatch, tmp_path):
    liberados = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: liberados.append(1))
    s = SesionCompleta(ps={"models": [{"name": "qwen3.5:27b"}]},
                       tags={"models": [{"name": "qwen3.5:35b-a3b", "size": 20 * 1024 ** 3}]})
    dormidos = []
    local._preparar("qwen3.5:35b-a3b", s, "http://x", tmp_path, dormir=dormidos.append, libre=lambda: 2.0)
    assert liberados == [1]
    assert dormidos == [2]


def test_preparar_no_descarga_nada_si_hay_ram_suficiente(monkeypatch, tmp_path):
    liberados = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: liberados.append(1))
    s = SesionCompleta(ps={"models": [{"name": "qwen3.5:27b"}]},
                       tags={"models": [{"name": "qwen3.5:35b-a3b", "size": 20 * 1024 ** 3}]})
    dormidos = []
    local._preparar("qwen3.5:35b-a3b", s, "http://x", tmp_path, dormir=dormidos.append, libre=lambda: 999.0)
    assert liberados == [1]
    assert dormidos == []


def test_preparar_no_descarga_nada_si_no_hay_otros_modelos_cargados(monkeypatch, tmp_path):
    liberados = []
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: liberados.append(1))
    s = SesionCompleta(ps={"models": []}, tags={"models": [{"name": "m:latest", "size": 4 * 1024 ** 3}]})
    dormidos = []
    local._preparar("m", s, "http://x", tmp_path, dormir=dormidos.append, libre=lambda: 0.5)
    assert liberados == [1]
    assert dormidos == []


def test_descargar_otros_modelos_pide_generate_con_keep_alive_0():
    enviados = []

    class _Sesion:
        def post(self, url, json=None, timeout=None):
            enviados.append((url, json, timeout))

    cargados = [{"name": "qwen3.5:27b"}, {"name": "qwen3.5:35b-a3b"}, {"model": "otro-modelo:latest"}]
    local._descargar_otros_modelos(cargados, "qwen3.5:35b-a3b", _Sesion(), "http://x")
    assert enviados == [("http://x/api/generate", {"model": "qwen3.5:27b", "keep_alive": 0}, 10),
                        ("http://x/api/generate", {"model": "otro-modelo:latest", "keep_alive": 0}, 10)]


def test_descargar_otros_modelos_ignora_fallos_de_un_modelo(tmp_path):
    class _Sesion:
        def post(self, url, json=None, timeout=None):
            raise RuntimeError("no responde")

    local._descargar_otros_modelos([{"name": "otro:latest"}], "m:latest", _Sesion(), "http://x")


# F1: el servidor de Ollama puede autoactualizarse y no volver; hay que relanzarlo sin ventana ni CLI extra.


def test_chat_llama_a_asegurar_servidor_si_ps_falla_por_conexion(monkeypatch, tmp_path):
    llamadas = []
    monkeypatch.setattr(local, "asegurar_servidor", lambda **k: llamadas.append(k) or True)
    s = SesionCompleta(error_ps=requests.ConnectionError("no"))
    assert local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path) == "ok"
    assert len(llamadas) == 1
    assert llamadas[0]["sesion"] is s and llamadas[0]["base"] == "http://x"


def test_asegurar_servidor_ya_disponible_no_lanza(monkeypatch):
    monkeypatch.setattr(local, "disponible", lambda *a, **k: True)
    lanzados = []
    assert local.asegurar_servidor(lanzar=lambda exe: lanzados.append(exe)) is True
    assert lanzados == []


def test_asegurar_servidor_sin_exe_no_lanza_y_devuelve_false(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "disponible", lambda *a, **k: False)
    monkeypatch.setenv("QUANT_OLLAMA_EXE", str(tmp_path / "no_existe.exe"))
    lanzados, dormidos = [], []
    assert local.asegurar_servidor(lanzar=lambda e: lanzados.append(e), dormir=dormidos.append) is False
    assert lanzados == [] and dormidos == []


def test_asegurar_servidor_lanza_y_espera_hasta_que_responde(monkeypatch, tmp_path):
    exe = tmp_path / "ollama.exe"
    exe.write_text("")
    monkeypatch.setenv("QUANT_OLLAMA_EXE", str(exe))
    respuestas = iter([False, False, True])
    monkeypatch.setattr(local, "disponible", lambda *a, **k: next(respuestas))
    lanzados, dormidos = [], []
    resultado = local.asegurar_servidor(lanzar=lambda e: lanzados.append(e), dormir=dormidos.append)
    assert resultado is True
    assert lanzados == [str(exe)]
    assert dormidos == [2, 2]


def test_asegurar_servidor_agota_espera_max_y_devuelve_false(monkeypatch, tmp_path):
    exe = tmp_path / "ollama.exe"
    exe.write_text("")
    monkeypatch.setenv("QUANT_OLLAMA_EXE", str(exe))
    monkeypatch.setattr(local, "disponible", lambda *a, **k: False)
    dormidos = []
    resultado = local.asegurar_servidor(lanzar=lambda e: None, dormir=dormidos.append, espera_max=6)
    assert resultado is False
    assert dormidos == [2, 2, 2]


def test_asegurar_servidor_lanza_ollama_serve_sin_ventana_ni_detached(monkeypatch, tmp_path):
    exe = tmp_path / "ollama.exe"
    exe.write_text("")
    monkeypatch.setenv("QUANT_OLLAMA_EXE", str(exe))
    monkeypatch.setattr(local, "disponible", lambda *a, **k: False)
    capturado = {}

    def falso_popen(args, **kwargs):
        capturado["args"], capturado["kwargs"] = args, kwargs

        class _P:
            pass
        return _P()

    monkeypatch.setattr(local.subprocess, "Popen", falso_popen)
    resultado = local.asegurar_servidor(dormir=lambda s: None, espera_max=0)
    assert resultado is False
    assert capturado["args"] == [str(exe), "serve"]
    assert capturado["kwargs"]["creationflags"] == 0x08000000
    assert capturado["kwargs"]["stdout"] == local.subprocess.DEVNULL
    assert capturado["kwargs"]["stderr"] == local.subprocess.DEVNULL
    assert capturado["kwargs"]["stdin"] == local.subprocess.DEVNULL
    assert "DETACHED_PROCESS" not in str(capturado["kwargs"])


# S1: un rollback de autoactualizacion de Ollama puede borrar llama-server.exe aunque el
# servicio siga respondiendo; hay que poder detectarlo con una comprobacion de fichero pura.


def test_motor_presente_true_si_existe_el_binario(tmp_path):
    exe = tmp_path / "llama-server.exe"
    exe.write_text("")
    assert local.motor_presente(exe=str(exe)) is True


def test_motor_presente_false_si_no_existe(tmp_path):
    assert local.motor_presente(exe=str(tmp_path / "no_existe.exe")) is False


def test_motor_presente_usa_llama_server_por_defecto(monkeypatch, tmp_path):
    exe = tmp_path / "llama-server.exe"
    exe.write_text("")
    monkeypatch.setattr(local, "LLAMA_SERVER", str(exe))
    assert local.motor_presente() is True


def test_motor_presente_respeta_variable_de_entorno(monkeypatch, tmp_path):
    exe = tmp_path / "otro.exe"
    exe.write_text("")
    monkeypatch.setenv("QUANT_LLAMA_SERVER", str(exe))
    assert local.motor_presente() is True


def test_llama_server_se_deriva_de_ollama_exe():
    assert local.LLAMA_SERVER == str(
        Path(local.OLLAMA_EXE).parent / "lib" / "ollama" / "llama-server.exe")


def test_dos_500_lanzan_errormodelo_sin_nombre_interno(tmp_path):
    from quant.investigacion import local

    class _Resp:
        status_code = 500
        text = "sin memoria"

        def json(self):
            return {"error": "sin memoria"}

    class _Sesion:
        def post(self, *a, **k):
            return _Resp()

        def get(self, *a, **k):
            raise OSError("sin ps")

    with pytest.raises(local.ErrorModelo) as e:
        local.chat("m", "s", "p", sesion=_Sesion(), raiz=tmp_path, dormir=lambda s: None)
    assert type(e.value) is local.ErrorModelo
    assert "_Reintentar" not in str(e.value)
    assert "sin memoria" in str(e.value)


def test_chat_dos_500_y_exito_devuelve_contenido_y_duerme_dos_veces(monkeypatch, tmp_path):
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: None)
    dormidos = []
    posts = [_RespuestaPost(status_code=500), _RespuestaPost(status_code=500),
             _RespuestaPost(cuerpo={"message": {"content": "tercero"}})]
    s = SesionCompleta(posts=posts)
    assert local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=dormidos.append) == "tercero"
    assert len(dormidos) == 2 and s.llamadas_post == 3


def test_chat_tres_500_lanzan_errormodelo_con_el_mensaje_de_ollama(monkeypatch, tmp_path):
    monkeypatch.setattr(memoria, "liberar", lambda *a, **k: None)
    dormidos = []
    posts = [_RespuestaPost(status_code=500, cuerpo={"error": "illegal memory access"})] * 3
    s = SesionCompleta(posts=posts)
    with pytest.raises(local.ErrorModelo, match="illegal memory access") as e:
        local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=dormidos.append)
    assert type(e.value) is local.ErrorModelo
    assert len(dormidos) == 2 and s.llamadas_post == 3


def test_chat_400_conserva_el_cuerpo_del_error(tmp_path):
    class _Resp400(_RespuestaPost):
        text = '{"error":"request (16628 tokens) exceeds the available context size (16384 tokens)"}'

        def raise_for_status(self):
            raise requests.HTTPError("400 Client Error: Bad Request for url: http://x/api/chat")

    s = SesionCompleta(posts=[_Resp400(status_code=400, cuerpo={
        "error": "request (16628 tokens) exceeds the available context size (16384 tokens)"})])
    with pytest.raises(local.ErrorModelo, match="exceeds the available context size"):
        local.chat("m", "s", "p", sesion=s, base="http://x", raiz=tmp_path, dormir=lambda s: None)
