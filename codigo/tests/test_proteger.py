import importlib.util
import io
import json
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "proteger.py"
_spec = importlib.util.spec_from_file_location("proteger", _RUTA)
proteger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proteger)

PREGUNTA = [("Edit", {"file_path": r"D:\Quant\config\costes.json"}),
            ("Write", {"file_path": "D:/Quant/examen/casos/x.json", "content": "{}"}),
            ("MultiEdit", {"file_path": r"D:\Quant\config\criterios.json"}),
            ("Bash", {"command": "sed -i 's/1/2/' config/criterios.json"}),
            ("PowerShell", {"command": "Set-Content D:\\Quant\\examen\\notas.json '{}'"}),
            ("Bash", {"command": "python fix.py > config/costes.json"}),
            ("Bash", {"command": "git checkout -- examen/notas.json"}),
            ("Write", {"file_path": "C:/tmp/p.py", "content": "open('config/costes.json','w')"}),
            ("Edit", {"file_path": "C:/tmp/p.py", "new_string": "Path('examen/notas.json').write_text(x)"})]
BLOQUEO = [("PowerShell", {"command": "$env:ANTHROPIC_API_KEY"}),
           ("Bash", {"command": "echo $CLAUDE_CODE_OAUTH_TOKEN"}),
           ("PowerShell", {"command": "$env:OPENROUTER_API_KEY"}),
           ("PowerShell", {"command": "Get-ChildItem env:"}),
           ("Bash", {"command": "printenv"}),
           ("Bash", {"command": "env | sort"}),
           ("Read", {"file_path": "D:/Quant/registro/panel_clave"}),
           ("Grep", {"pattern": ".", "path": "D:/Quant/registro/panel_clave"}),
           ("Bash", {"command": "cat registro/panel_clave"}),
           ("PowerShell", {"command": "Get-Content D:\\Quant\\registro\\panel_clave"}),
           ("Read", {"file_path": r"C:\Users\user\.claude\.credentials.json"})]
LIBRE = [("Bash", {"command": "git diff config/costes.json"}),
         ("Bash", {"command": "grep -n umbral config/criterios.json"}),
         ("Grep", {"pattern": "x", "path": "D:/Quant/examen"}),
         ("Read", {"file_path": "D:/Quant/config/costes.json"}),
         ("Read", {"file_path": "D:/Quant/examen/notas.json"}),
         ("Write", {"file_path": "C:/tmp/p.py", "content": "clave = open('registro/panel_clave').read()"}),
         ("Bash", {"command": "node prueba.js"}),
         ("Bash", {"command": "pytest -q"}),
         ("Edit", {"file_path": "D:/Quant/codigo/quant/costes.py", "new_string": "x = 1"}),
         ("Bash", {"command": "git commit -m 'env vars'"}),
         ("Bash", {"command": "ls -d examen .claude 2>&1"}),
         ("Bash", {"command": "grep -n umbral config/criterios.json 2>/dev/null"}),
         ("PowerShell", {"command": "Get-Content examen/notas.json 2>$null"}),
         ("Bash", {"command": "grep -rn panel_clave codigo/quant/panel/servidor.py"})]


@pytest.mark.parametrize("herramienta,entrada", PREGUNTA)
def test_owner_files_are_blocked(herramienta, entrada):
    assert proteger.decidir(herramienta, entrada)[0] == "deny"


@pytest.mark.parametrize("herramienta,entrada", BLOQUEO)
def test_claves_se_bloquean(herramienta, entrada):
    assert proteger.decidir(herramienta, entrada)[0] == "deny"


@pytest.mark.parametrize("herramienta,entrada", LIBRE)
def test_lecturas_no_preguntan(herramienta, entrada):
    assert proteger.decidir(herramienta, entrada) is None


def test_main_escribe_json_de_hook(capsys, monkeypatch):
    entrada = {"tool_name": "Read", "tool_input": {"file_path": "D:/Quant/registro/panel_clave"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(entrada)))
    assert proteger.main() == 0
    salida = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert salida["hookEventName"] == "PreToolUse" and salida["permissionDecision"] == "deny"
    assert salida["permissionDecisionReason"]


def test_main_con_entrada_rota_deja_pasar(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{no"))
    assert proteger.main() == 0 and capsys.readouterr().out == ""


@pytest.mark.parametrize("orden", ["rm -rf examen", "Remove-Item D:/Quant/examen -Recurse", "mv examen viejo"])
def test_borrar_la_carpeta_del_examen_se_bloquea(orden):
    assert proteger.decidir("Bash", {"command": orden})[0] == "deny"


def test_examen_py_no_es_el_examen():
    assert proteger.decidir("Bash", {"command": "rm codigo/quant/investigacion/examen.py"}) is None
