import subprocess

import pytest

from quant.investigacion import claude_cli, local


class Ejecutor:
    def __init__(self, codigo=0, salida='{"a":1}', error="", lanza=None, crea_ajustes=None):
        self.codigo, self.salida, self.error, self.lanza = codigo, salida, error, lanza
        self.crea_ajustes = crea_ajustes
        self.llamadas = []

    def __call__(self, argumentos, entrada, timeout):
        self.llamadas.append((argumentos, entrada, timeout))
        if self.crea_ajustes is not None:
            (self.crea_ajustes / ".claude").mkdir(parents=True, exist_ok=True)
        if self.lanza is not None:
            raise self.lanza
        return self.codigo, self.salida, self.error


@pytest.fixture
def entorno(tmp_path):
    (tmp_path / "supervisor").mkdir()
    claude_cli.reiniciar(None)
    yield {"raiz": tmp_path, "candado": tmp_path / "claude.lock"}
    claude_cli.reiniciar(None)


def _chat(entorno, ejecutar, **kw):
    return claude_cli.chat(kw.pop("modelo", "haiku"), "SISTEMA", kw.pop("prompt", "PREGUNTA"), ejecutar=ejecutar,
                           raiz=entorno["raiz"], candado=entorno["candado"], **kw)


def test_argumentos_seguros(entorno):
    ej = Ejecutor()
    _chat(entorno, ej)
    argumentos, entrada, _ = ej.llamadas[0]
    assert argumentos[1] == "-p"
    assert argumentos[argumentos.index("--model") + 1] == "haiku"
    assert argumentos[argumentos.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argumentos
    assert argumentos[argumentos.index("--system-prompt") + 1] == "SISTEMA"
    assert "PREGUNTA" in entrada
    assert not any("PREGUNTA" in a for a in argumentos)


def test_json_anade_instruccion(entorno):
    ej = Ejecutor()
    _chat(entorno, ej, formato="json")
    assert ej.llamadas[0][1].endswith("Responde solo con el JSON pedido, sin texto alrededor.")


def test_texto_no_anade_instruccion(entorno):
    ej = Ejecutor(salida="hola")
    _chat(entorno, ej)
    assert "Responde solo con el JSON" not in ej.llamadas[0][1]


def test_devuelve_salida(entorno):
    assert _chat(entorno, Ejecutor()) == '{"a":1}'


def test_error_codigo(entorno):
    with pytest.raises(local.ErrorModelo):
        _chat(entorno, Ejecutor(codigo=1, salida="", error="boom"))


def test_salida_vacia(entorno):
    with pytest.raises(local.ErrorModelo):
        _chat(entorno, Ejecutor(salida="   "))


def test_tiempo_agotado(entorno):
    with pytest.raises(local.ErrorModelo):
        _chat(entorno, Ejecutor(lanza=subprocess.TimeoutExpired("claude", 5)))


@pytest.mark.parametrize("codigo,salida", [(0, "Claude AI usage limit reached|1761800000"),
                                           (1, "You've hit your limit · resets 3am"),
                                           (1, "You've hit your weekly limit · resets 11am (Europe/Berlin)")])
def test_limite_corta(entorno, codigo, salida):
    with pytest.raises(claude_cli.CorteClaude) as e:
        _chat(entorno, Ejecutor(codigo=codigo, salida=salida))
    assert e.value.motivo == "limite"


def test_corte_no_es_error_modelo():
    assert not issubclass(claude_cli.CorteClaude, Exception)


def test_tope(entorno):
    ej = Ejecutor()
    claude_cli.reiniciar(2)
    _chat(entorno, ej)
    _chat(entorno, ej)
    with pytest.raises(claude_cli.CorteClaude) as e:
        _chat(entorno, ej)
    assert e.value.motivo == "tope"
    assert len(ej.llamadas) == 2
    assert claude_cli.llamadas() == 2


def test_limpia_ajustes(entorno):
    cwd = entorno["raiz"] / "supervisor"
    _chat(entorno, Ejecutor(crea_ajustes=cwd))
    assert not (cwd / ".claude").exists()
    with pytest.raises(local.ErrorModelo):
        _chat(entorno, Ejecutor(crea_ajustes=cwd, lanza=OSError("x")))
    assert not (cwd / ".claude").exists()


def test_registro_sin_texto(entorno):
    _chat(entorno, Ejecutor(), prompt="SECRETO DEL DOCUMENTO", modelo="sonnet")
    logs = list((entorno["raiz"] / "registro").glob("claude_*.log"))
    assert len(logs) == 1
    linea = logs[0].read_text(encoding="utf-8").strip()
    assert "sonnet" in linea and "ok" in linea
    assert "SECRETO" not in linea


def test_comprobar_sesion_caducada(entorno):
    r = claude_cli.comprobar(ejecutar=Ejecutor(codigo=1, salida="Invalid API key · Please run /login"),
                             raiz=entorno["raiz"], candado=entorno["candado"])
    assert r["sesion"] is False
    assert "login" in r["error"]


def test_comprobar_no_cuenta_para_el_tope(entorno):
    claude_cli.reiniciar(1)
    r = claude_cli.comprobar(ejecutar=Ejecutor(salida="OK"), raiz=entorno["raiz"], candado=entorno["candado"])
    assert r["sesion"] is True
    assert claude_cli.llamadas() == 0


def test_el_error_muestra_la_salida_aunque_haya_un_aviso_en_stderr(entorno):
    ej = Ejecutor(codigo=1, salida="Something broke", error="Warning: this sign-in ends soon.")
    with pytest.raises(local.ErrorModelo, match="Something broke"):
        _chat(entorno, ej)


@pytest.mark.parametrize("salida", ["The price limit reached the daily cap, so trading halted.",
                                    '{"extracto": "usage limit reached by the exchange"}'])
def test_texto_normal_no_corta(entorno, salida):
    assert _chat(entorno, Ejecutor(salida=salida)) == salida


def test_tras_limite_no_hay_mas_llamadas(entorno):
    ej = Ejecutor(salida="Claude AI usage limit reached|1761800000")
    with pytest.raises(claude_cli.CorteClaude):
        _chat(entorno, ej)
    ej.salida = '{"a":1}'
    with pytest.raises(claude_cli.CorteClaude):
        _chat(entorno, ej)
    assert len(ej.llamadas) == 1


def test_comprobar_reintenta_un_fallo_pasajero(entorno):
    class Pasajero(Ejecutor):
        def __call__(self, argumentos, entrada, timeout):
            self.llamadas.append(1)
            return (1, "", "getaddrinfo ENOTFOUND") if len(self.llamadas) == 1 else (0, "OK", "")
    r = claude_cli.comprobar(ejecutar=Pasajero(), raiz=entorno["raiz"], candado=entorno["candado"], dormir=lambda s: None)
    assert r["sesion"] is True


def test_comprobar_distingue_caducada_de_otro_fallo(entorno):
    r = claude_cli.comprobar(ejecutar=Ejecutor(codigo=1, salida="", error="getaddrinfo ENOTFOUND"),
                             raiz=entorno["raiz"], candado=entorno["candado"], dormir=lambda s: None)
    assert r["sesion"] is False and r["causa"] == "fallo"
    r = claude_cli.comprobar(ejecutar=Ejecutor(codigo=1, salida="Invalid API key · Please run /login"),
                             raiz=entorno["raiz"], candado=entorno["candado"], dormir=lambda s: None)
    assert r["causa"] == "login"
    r = claude_cli.comprobar(ejecutar=Ejecutor(salida="You've hit your limit · resets 3am"),
                             raiz=entorno["raiz"], candado=entorno["candado"], dormir=lambda s: None)
    assert r["causa"] == "limite"
