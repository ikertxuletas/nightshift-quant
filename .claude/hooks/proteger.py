"""PreToolUse hook for Quant: never change the owner's files, never read the keys.

The validator criteria, the costs and the exam (config/criterios.json, config/costes.json, examen/) are the
owner's decision, so Claude never changes them (a block, not an 'ask': auto mode approves an 'ask' on its
own). Keys and the Claude token never reach the model. registro/panel_clave may be used by a script but not shown."""
import json
import re
import sys

PROTEGIDOS = re.compile(r"config/(criterios|costes)\.json|(?<![a-z0-9_.-])examen(?=/|[\"'\s]|$)")
CLAVES = re.compile(r"claude_code_oauth_token|anthropic_api_key|openrouter_api_key|\.credentials\.json")
VOLCADO_ENTORNO = re.compile(r"(^|[;&|(]\s*)(printenv|env|set)\s*($|[|;&>)])|(get-childitem|gci|dir|ls)\s+env:"
                             r"|environment\]::getenvironmentvariables")
ESCRITURA_SHELL = re.compile(r">|\bsed\s+-i|\btee\b|\bmv\s|\bcp\s|\brm\s|\bdel\s|remove-item|set-content|add-content"
                             r"|out-file|move-item|copy-item|git\s+checkout\s+--|git\s+restore|\bpython|\bpy\s")
ESCRITURA_CODIGO = re.compile(r"open\([^)]*['\"][wa]|write_text|write_bytes|json\.dump|\.write\(|set-content|out-file")
MUESTRA = re.compile(r"(^|[;&|(]\s*)(cat|type|get-content|gc|more|less|head|tail|echo|write-output|write-host"
                     r"|select-string|grep|rg|findstr)\b")
SIN_SALIDA = re.compile(r"\d?>>?\s*(/dev/null|\$null|nul\b|&\d)")
EDICION = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
LECTURA = {"Read", "Grep", "Glob"}
SHELL = {"Bash", "PowerShell"}

DUENO = "Blocked: the owner decides this file. Edit it by hand or turn this hook off for a moment."
CLAVE = "Blocked: keys and the Claude token are never read or shown."
PANEL = "Blocked: the panel key may be used by a script but never shown."


def _n(texto):
    return str(texto or "").replace("\\", "/").lower()


def decidir(herramienta, entrada):
    """('ask'|'deny', Spanish reason) or None to let the tool run."""
    entrada = entrada if isinstance(entrada, dict) else {}
    ruta = _n(entrada.get("file_path") or entrada.get("notebook_path") or entrada.get("path"))
    orden = _n(entrada.get("command"))
    if CLAVES.search(ruta) or CLAVES.search(orden):
        return "deny", CLAVE
    if herramienta in SHELL and VOLCADO_ENTORNO.search(orden):
        return "deny", CLAVE
    if "panel_clave" in ruta and herramienta in LECTURA:
        return "deny", PANEL
    if herramienta in SHELL and "registro/panel_clave" in orden and MUESTRA.search(orden):
        return "deny", PANEL
    orden = SIN_SALIDA.sub(" ", orden)  # 2>&1, 2>/dev/null and 2>$null only silence a command, they write nothing
    if herramienta in EDICION:
        if PROTEGIDOS.search(ruta):
            return "deny", DUENO
        contenido = _n(" ".join(str(entrada.get(k) or "") for k in ("content", "new_string", "new_source")))
        contenido += _n(" ".join(str(e.get("new_string") or "") for e in entrada.get("edits") or []
                                 if isinstance(e, dict)))
        if PROTEGIDOS.search(contenido) and ESCRITURA_CODIGO.search(contenido):
            return "deny", DUENO
    if herramienta in SHELL and PROTEGIDOS.search(orden) and ESCRITURA_SHELL.search(orden):
        return "deny", DUENO
    return None


def main():
    try:
        datos = json.load(sys.stdin)
        decision = decidir(datos.get("tool_name"), datos.get("tool_input"))
    except Exception:  # a broken hook must not block all work
        return 0
    if decision:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision[0],
                                                 "permissionDecisionReason": decision[1]}}))  # ASCII-safe on cp1252
    return 0


if __name__ == "__main__":
    sys.exit(main())
