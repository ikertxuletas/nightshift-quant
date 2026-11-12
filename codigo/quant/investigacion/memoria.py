"""Libera RAM cerrando programas de usuario antes de cargar un modelo grande, sin abrir ventanas."""
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime
import io
import json
import re
import subprocess
import time
from pathlib import Path

from quant.investigacion import tiempos

_OCULTO = 0x08000000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
QUNS_RUNNING_D3D_FULL_SCREEN = 3

SIN_VENTANA = object()  # no hay ninguna ventana en primer plano (p.ej. pantalla de bloqueo): proceder normal

PROTEGIDOS = {
    "claude.exe", "node.exe", "python.exe", "pythonw.exe", "ollama.exe", "ollama app.exe",
    "llama-server.exe", "onedrive.exe", "explorer.exe", "winword.exe", "excel.exe",
    "powerpnt.exe", "outlook.exe", "code.exe", "svchost.exe",
}

_DEFECTO = {
    "margen_gb": 1.0,
    "inactividad_minutos": 15,
    "espera_tras_500_segundos": 60,
    "cerrables": ["chrome.exe", "msedge.exe", "ChatGPT Classic.exe", "ChatGPT.exe", "Discord.exe", "Spotify.exe"],
    "franja_cierre": [2, 6],
}


def cargar_config(raiz):
    try:
        datos = json.loads((Path(raiz) / "config" / "memoria.json").read_text(encoding="utf-8"))
        if not isinstance(datos, dict):
            return dict(_DEFECTO)
        return {**_DEFECTO, **datos}
    except (OSError, ValueError):
        return dict(_DEFECTO)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def libre_gb():
    estado = _MemoryStatusEx()
    estado.dwLength = ctypes.sizeof(estado)
    ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado))
    if not ok:
        raise OSError("GlobalMemoryStatusEx fallo")
    return estado.ullAvailPhys / (1024 ** 3)


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]


def _ocioso_ms(tick, dw_time):
    """GetTickCount y dwTime son ambos de 32 bits sin signo: dan la vuelta juntos cada ~49.7 dias."""
    return (tick - dw_time) & 0xFFFFFFFF


def _interactiva(exito, id_sesion):
    """GetLastInputInfo solo tiene sentido en la sesion interactiva (Session Id != 0)."""
    return bool(exito) and id_sesion != 0


def _sesion_interactiva():
    try:
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        id_sesion = ctypes.c_ulong()
        exito = ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(id_sesion))
        return _interactiva(exito, id_sesion.value)
    except Exception:
        return False


def inactivo_minutos():
    try:
        if not _sesion_interactiva():
            return 0.0
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            raise OSError("GetLastInputInfo fallo")
        get_tick = ctypes.windll.kernel32.GetTickCount
        get_tick.restype = ctypes.c_uint32
        get_tick.argtypes = []
        return _ocioso_ms(get_tick(), info.dwTime) / 60000.0
    except Exception:
        return 0.0


def procesos():
    salida = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             encoding="oem", errors="replace", timeout=20, creationflags=_OCULTO)
    agrupado = {}
    for campos in csv.reader(io.StringIO(salida.stdout or "")):
        if len(campos) < 5:
            continue
        nombre = campos[0].strip().lower()
        digitos = re.sub(r"\D", "", campos[4])
        if not digitos:
            continue
        gb = int(digitos) / (1024 ** 2)
        agrupado[nombre] = agrupado.get(nombre, 0.0) + gb
    return list(agrupado.items())


def _vivo(nombre):
    salida = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {nombre}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, encoding="oem", errors="replace",
                             timeout=20, creationflags=_OCULTO)
    return nombre.lower() in (salida.stdout or "").lower()


def cerrar(nombre, dormir):
    subprocess.run(["taskkill", "/IM", nombre], capture_output=True, timeout=20, creationflags=_OCULTO)
    for _ in range(20):
        if not _vivo(nombre):
            return
        dormir(1)
    if _vivo(nombre):
        subprocess.run(["taskkill", "/F", "/IM", nombre], capture_output=True, timeout=20, creationflags=_OCULTO)


def _proceso_primer_plano():
    """Nombre (minusculas) del proceso dueno de la ventana en primer plano.
    SIN_VENTANA si no hay ninguna ventana en primer plano (p.ej. pantalla de bloqueo): proceder normal.
    None si hay ventana pero no se pudo averiguar su proceso: fail-safe, no cerrar nada."""
    try:
        user32, kernel32 = _api_primer_plano()
        hwnd = user32.GetForegroundWindow()
    except Exception:
        return None
    if not hwnd:
        return SIN_VENTANA
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(260)
            tam = wintypes.DWORD(260)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(tam)):
                return None
            nombre = Path(buffer.value).name
            return nombre.lower() if nombre else None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _api_primer_plano():
    """Instancias propias de user32/kernel32 con tipos de 64 bits, sin tocar los prototipos globales de windll."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return user32, kernel32


def _estado_notificacion():
    """Lectura de SHQueryUserNotificationState: S_OK y el estado, o None si falla."""
    estado = ctypes.c_int()
    resultado = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(estado))
    return estado.value if resultado == 0 else None


def _franja_de(config):
    try:
        inicio, fin = config.get("franja_cierre", _DEFECTO["franja_cierre"])
        return int(inicio), int(fin)
    except (TypeError, ValueError):
        return tuple(_DEFECTO["franja_cierre"])


def _en_franja(momento, franja):
    """[inicio, fin) en horas locales; si fin <= inicio, la franja cruza la medianoche."""
    inicio_min, fin_min = franja[0] * 60, franja[1] * 60
    minutos = momento.hour * 60 + momento.minute
    if inicio_min <= fin_min:
        return inicio_min <= minutos < fin_min
    return minutos >= inicio_min or minutos < fin_min


def _registrar(raiz, resultado, hora):
    if raiz is None:
        return
    if not resultado["cerrados"] and resultado["omitido"] != "usuario activo":
        return
    carpeta = Path(raiz) / "registro"
    carpeta.mkdir(parents=True, exist_ok=True)
    linea = {**resultado, "hora": hora.isoformat(timespec="seconds")}
    with open(carpeta / f"memoria_{tiempos.fecha_local()}.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def liberar(necesario_gb, config, raiz=None, libre=None, inactivo=None,
            listar=None, cerrar=None, dormir=time.sleep, ahora=None,
            primer_plano=None, hora_local=None, estado_notificacion=None):
    # Los parametros con valor por defecto None se resuelven aqui (y no en la firma) para que un
    # monkeypatch de memoria.procesos/memoria.cerrar en los tests siga afectando a las llamadas que
    # no pasan esos argumentos explicitamente (ver conftest.py, red de seguridad de la suite).
    libre = libre or libre_gb
    inactivo = inactivo or inactivo_minutos
    listar = listar or procesos
    if cerrar is None:
        cerrar = globals()["cerrar"]
    ahora = ahora or tiempos.ahora_utc
    primer_plano = primer_plano or _proceso_primer_plano
    hora_local = hora_local or datetime.now
    estado_notificacion = estado_notificacion or _estado_notificacion

    resultado = {"necesario": necesario_gb, "libre_antes": None, "libre_despues": None,
                 "cerrados": [], "omitido": ""}
    try:
        libre_antes = libre()
        resultado["libre_antes"] = libre_antes
        if libre_antes >= necesario_gb:
            resultado["omitido"] = "ya hay memoria"
            resultado["libre_despues"] = libre_antes
            return resultado
        if not _en_franja(hora_local(), _franja_de(config)):
            resultado["omitido"] = "fuera de franja"
            resultado["libre_despues"] = libre_antes
            return resultado
        umbral = config.get("inactividad_minutos", _DEFECTO["inactividad_minutos"])
        if inactivo() < umbral:
            resultado["omitido"] = "usuario activo"
            resultado["libre_despues"] = libre_antes
            _registrar(raiz, resultado, ahora())
            return resultado
        if estado_notificacion() == QUNS_RUNNING_D3D_FULL_SCREEN:
            resultado["omitido"] = "juego a pantalla completa"
            resultado["libre_despues"] = libre_antes
            return resultado
        cerrables = {n.lower() for n in config.get("cerrables", _DEFECTO["cerrables"])}
        candidatos = sorted((item for item in listar() if item[0] in cerrables and item[0] not in PROTEGIDOS),
                             key=lambda item: item[1], reverse=True)
        if libre_antes + sum(gb for _, gb in candidatos) < necesario_gb:
            resultado["omitido"] = "no alcanza"
            resultado["libre_despues"] = libre_antes
            return resultado
        libre_actual = libre_antes
        for nombre, gb in candidatos:
            if libre_actual >= necesario_gb:
                break
            if inactivo() < umbral:
                resultado["omitido"] = "usuario activo"
                break
            # Nunca se cierra el proceso dueno de la ventana en primer plano ahora mismo (ademas de
            # PROTEGIDOS): un mando de juego o un video no reinician GetLastInputInfo, pero la ventana
            # que se esta viendo no debe cerrarse. Fail-safe: si no se puede saber cual es, no se cierra
            # nada mas esta noche (salvo que no haya ninguna ventana en primer plano, p.ej. pantalla
            # bloqueada, en cuyo caso se procede con normalidad).
            nombre_fg = primer_plano()
            if nombre_fg is None:
                resultado["omitido"] = "sin ventana en primer plano conocida"
                break
            if nombre_fg is not SIN_VENTANA and nombre == nombre_fg:
                continue
            cerrar(nombre, dormir)
            resultado["cerrados"].append({"nombre": nombre, "gb": gb})
            libre_actual = libre()
        resultado["libre_despues"] = libre_actual
        _registrar(raiz, resultado, ahora())
        return resultado
    except Exception as e:
        resultado["omitido"] = f"error: {type(e).__name__}: {e}"
        try:
            if resultado["cerrados"]:
                _registrar(raiz, resultado, ahora())
        except Exception:
            pass
        return resultado
