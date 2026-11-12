"""Cliente de modelos por `claude -p` con la suscripcion del dueño. Misma firma que local.chat."""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import rutas
from quant.investigacion import candados
from quant.investigacion.local import ErrorModelo, json_de  # noqa: F401  (reexportados para los agentes)

INSTRUCCION_JSON = "Responde solo con el JSON pedido, sin texto alrededor."
# Solo los avisos exactos de Claude Code: un paper puede decir "limit reached" y no debe cortar la noche.
LIMITE_USO = re.compile(r"Claude AI usage limit reached|You've hit your (?:(?:usage|weekly|daily|session) )?limit", re.I)
MAX_SALIDA_AVISO = 300
SIN_LOGIN = re.compile(r"/login|invalid api key|not logged in|oauth token", re.I)
MODELO_COMPROBACION = "haiku"
ESPERA_REINTENTO = 30

_estado = {"tope": None, "llamadas": 0, "cortado": None}


class CorteClaude(BaseException):
    """Tope de la noche o limite de la suscripcion. Hereda de BaseException para que los bucles por
    documento (que capturan Exception) no lo traguen y marquen documentos como erroneos."""

    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def _detectar_claude_exe():
    candidatos = (Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@anthropic-ai" /
                 "claude-code" / "bin" / "claude.exe",
                 Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "claude.exe")
    for candidato in candidatos:
        if candidato.exists():
            return str(candidato)
    return "claude"


CLAUDE_EXE = _detectar_claude_exe()


def limpiar_ajustes(cwd):
    """Los hooks de los plugins dejan un .claude con permisos que nadie ha revisado: se borra tras cada llamada."""
    carpeta = Path(cwd) / ".claude"
    if carpeta.is_dir():
        shutil.rmtree(carpeta, ignore_errors=True)


def _ejecutar_defecto(argumentos, entrada, timeout, cwd):
    proc = subprocess.run(argumentos, input=entrada, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout, cwd=cwd, creationflags=0x08000000)
    return proc.returncode, proc.stdout, proc.stderr


def reiniciar(tope):
    _estado["tope"] = tope
    _estado["llamadas"] = 0
    _estado["cortado"] = None


def llamadas():
    return _estado["llamadas"]


def _registrar(raiz, modelo, segundos, resultado):
    carpeta = Path(raiz) / "registro"
    carpeta.mkdir(parents=True, exist_ok=True)
    linea = {"hora": datetime.now(timezone.utc).isoformat(timespec="seconds"), "modelo": modelo,
             "segundos": round(segundos, 1), "resultado": resultado}
    with open(carpeta / f"claude_{datetime.now().strftime('%Y%m%d')}.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(linea, ensure_ascii=False) + "\n")


def _invocar(modelo, system, entrada, timeout, ejecutar, raiz, candado):
    raiz = Path(raiz) if raiz is not None else rutas.RAIZ
    cwd = raiz / "supervisor"
    argumentos = [CLAUDE_EXE, "-p", "--model", modelo, "--output-format", "text", "--tools", "",
                  "--strict-mcp-config", "--system-prompt", system]
    marca = time.monotonic()
    with candados.turno(candado):
        try:
            if ejecutar is not None:
                codigo, salida, error = ejecutar(argumentos, entrada, timeout)
            else:
                codigo, salida, error = _ejecutar_defecto(argumentos, entrada, timeout, cwd)
        except (subprocess.TimeoutExpired, OSError) as e:
            _registrar(raiz, modelo, time.monotonic() - marca, f"fallo: {type(e).__name__}")
            raise ErrorModelo(f"fallo al ejecutar claude: {e}") from e
        finally:
            limpiar_ajustes(cwd)
    segundos = time.monotonic() - marca
    aviso = f"{salida or ''}\n{error or ''}"
    if LIMITE_USO.search(aviso) and (codigo != 0 or len((salida or "").strip()) <= MAX_SALIDA_AVISO):
        _registrar(raiz, modelo, segundos, "limite de uso")
        _estado["cortado"] = "limite"
        raise CorteClaude("limite")
    if codigo != 0:
        _registrar(raiz, modelo, segundos, f"codigo {codigo}")
        # stderr puede traer solo un aviso (sesion a punto de caducar) y el motivo real ir por stdout.
        raise ErrorModelo(f"claude devolvio codigo {codigo}: {' | '.join(t.strip() for t in (salida, error) if t and t.strip())[:300]}")
    if not salida or not salida.strip():
        _registrar(raiz, modelo, segundos, "salida vacia")
        raise ErrorModelo("claude devolvio una salida vacia")
    _registrar(raiz, modelo, segundos, "ok")
    return salida.strip()


def chat(modelo, system, prompt, formato=None, opciones=None, timeout=600, ejecutar=None, raiz=None,
         candado=candados.CLAUDE, **_):
    if _estado["cortado"]:
        raise CorteClaude(_estado["cortado"])
    if _estado["tope"] is not None and _estado["llamadas"] >= _estado["tope"]:
        raise CorteClaude("tope")
    entrada = prompt if formato is None else f"{prompt}\n\n{INSTRUCCION_JSON}"
    _estado["llamadas"] += 1
    return _invocar(modelo, system, entrada, timeout, ejecutar, raiz, candado)


def comprobar(ejecutar=None, raiz=None, candado=candados.CLAUDE, dormir=time.sleep):
    """causa: login (sesion caducada), limite (suscripcion agotada) o fallo (red, tiempo, exe); un reintento si es fallo."""
    resultado = {"exe": CLAUDE_EXE, "sesion": False}
    for intento in range(2):
        try:
            _invocar(MODELO_COMPROBACION, "Responde con una palabra.", "Responde OK", 120, ejecutar, raiz, candado)
            return {"exe": CLAUDE_EXE, "sesion": True}
        except CorteClaude as e:
            return {**resultado, "causa": "limite", "error": f"corte: {e.motivo}"}
        except ErrorModelo as e:
            resultado["error"] = str(e)[:300]
            resultado["causa"] = "login" if SIN_LOGIN.search(str(e)) else "fallo"
            if resultado["causa"] == "login" or intento == 1:
                return resultado
            dormir(ESPERA_REINTENTO)
    return resultado
