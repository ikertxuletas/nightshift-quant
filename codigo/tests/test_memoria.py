import json
from datetime import datetime

import pytest

from quant.investigacion import memoria


class _Salida:
    def __init__(self, stdout=""):
        self.stdout = stdout


def _config(**cambios):
    base = {"margen_gb": 2.0, "inactividad_minutos": 15, "espera_tras_500_segundos": 60,
            "cerrables": ["chrome.exe", "steam.exe"]}
    return {**base, **cambios}


# Hora dentro de la franja nocturna por defecto (02:00-06:00) y PC no ocupado por un juego: la mayoria
# de los tests de esta suite prueban el resto de la logica de liberar, no A1/A4, asi que fijan estos dos
# por defecto salvo que quieran probarlos explicitamente.


def _liberar(*args, **kwargs):
    kwargs.setdefault("hora_local", lambda: datetime(2026, 1, 1, 3, 0))
    kwargs.setdefault("estado_notificacion", lambda: 0)
    return memoria.liberar(*args, **kwargs)


def test_no_cierra_si_hay_memoria():
    r = _liberar(4.0, _config(), libre=lambda: 8.0, inactivo=lambda: 0.0,
                         listar=lambda: (_ for _ in ()).throw(AssertionError("no deberia listar")))
    assert r == {"necesario": 4.0, "libre_antes": 8.0, "libre_despues": 8.0, "cerrados": [], "omitido": "ya hay memoria"}


def test_no_cierra_con_usuario_activo():
    r = _liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 3.0)
    assert r["cerrados"] == []
    assert r["omitido"] == "usuario activo"


def test_cierra_de_mayor_a_menor_y_para():
    libres = iter([1.0, 4.0, 5.0])
    cerrados = []

    def cerrar(nombre, dormir):
        cerrados.append(nombre)

    r = _liberar(4.0, _config(), libre=lambda: next(libres), inactivo=lambda: 30.0,
                         listar=lambda: [("chrome.exe", 1.0), ("steam.exe", 3.0)], cerrar=cerrar,
                         dormir=lambda s: None, primer_plano=lambda: memoria.SIN_VENTANA)
    assert cerrados == ["steam.exe"]
    assert [c["nombre"] for c in r["cerrados"]] == ["steam.exe"]
    assert r["libre_despues"] == 4.0
    assert r["omitido"] == ""


def test_nunca_cierra_un_protegido_aunque_este_en_cerrables():
    cerrados = []
    r = _liberar(2.0, _config(cerrables=["python.exe", "steam.exe"]), libre=lambda: 1.0,
                         inactivo=lambda: 30.0,
                         listar=lambda: [("python.exe", 5.0), ("steam.exe", 1.0)],
                         cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                         primer_plano=lambda: memoria.SIN_VENTANA)
    assert cerrados == ["steam.exe"]
    assert [c["nombre"] for c in r["cerrados"]] == ["steam.exe"]


def test_excepcion_en_listado_no_lanza():
    def listar_roto():
        raise OSError("tasklist fallo")

    r = _liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0, listar=listar_roto)
    assert r["cerrados"] == []
    assert r["omitido"].startswith("error: OSError")


def test_log_escrito_en_tmp(tmp_path):
    _liberar(3.0, _config(), raiz=tmp_path, libre=lambda: 1.0, inactivo=lambda: 30.0,
                     listar=lambda: [("chrome.exe", 2.0)], cerrar=lambda nombre, dormir: None,
                     dormir=lambda s: None, primer_plano=lambda: memoria.SIN_VENTANA)
    ficheros = list((tmp_path / "registro").glob("memoria_*.log"))
    assert len(ficheros) == 1
    linea = json.loads(ficheros[0].read_text(encoding="utf-8").strip())
    assert linea["cerrados"] == [{"nombre": "chrome.exe", "gb": 2.0}]
    assert "hora" in linea


def test_log_usuario_activo_tambien_se_escribe(tmp_path):
    _liberar(4.0, _config(), raiz=tmp_path, libre=lambda: 1.0, inactivo=lambda: 0.0)
    ficheros = list((tmp_path / "registro").glob("memoria_*.log"))
    assert len(ficheros) == 1


def test_no_hay_log_si_ya_hay_memoria(tmp_path):
    _liberar(4.0, _config(), raiz=tmp_path, libre=lambda: 8.0, inactivo=lambda: 0.0)
    assert not (tmp_path / "registro").exists()


def test_cargar_config_valores_por_defecto(tmp_path):
    c = memoria.cargar_config(tmp_path)
    assert c["margen_gb"] == 1.0
    assert c["inactividad_minutos"] == 15
    assert "chrome.exe" in c["cerrables"]
    assert c["franja_cierre"] == [2, 6]


def test_cargar_config_desde_fichero(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "memoria.json").write_text(json.dumps({"margen_gb": 3.5}), encoding="utf-8")
    assert memoria.cargar_config(tmp_path)["margen_gb"] == 3.5


def test_cargar_config_fusiona_con_defecto_si_faltan_claves(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "memoria.json").write_text(json.dumps({"margen_gb": 3.5}), encoding="utf-8")
    c = memoria.cargar_config(tmp_path)
    assert c["margen_gb"] == 3.5
    assert c["inactividad_minutos"] == 15
    assert "chrome.exe" in c["cerrables"]


def test_cargar_config_ignora_json_que_no_es_dict(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "memoria.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert memoria.cargar_config(tmp_path) == dict(memoria._DEFECTO)


# I1: parseo de la columna "Mem Usage" de tasklist en distintos formatos.


def test_procesos_parsea_formatos_espanol_e_ingles(monkeypatch):
    texto = (
        '"System","4","Services","0","16.080 KB"\r\n'
        '"chrome.exe","111","Console","1","2.345.678 K"\r\n'
        '"ChatGPT Classic.exe","222","Console","1","1,234 K"\r\n'
        '"Idle","0","Services","0","12\xa0345 K"\r\n'
        '"sinmemoria.exe","9","Console","1","N/A"\r\n'
    )
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append((cmd, kw))
        return _Salida(texto)

    monkeypatch.setattr(memoria.subprocess, "run", fake_run)
    resultado = dict(memoria.procesos())
    assert resultado["system"] == pytest.approx(16080 / (1024 ** 2))
    assert resultado["chrome.exe"] == pytest.approx(2345678 / (1024 ** 2))
    assert resultado["chatgpt classic.exe"] == pytest.approx(1234 / (1024 ** 2))
    assert resultado["idle"] == pytest.approx(12345 / (1024 ** 2))
    assert "sinmemoria.exe" not in resultado
    cmd, kw = llamadas[0]
    assert cmd == ["tasklist", "/FO", "CSV", "/NH"]
    assert kw["creationflags"] == 0x08000000
    assert kw["encoding"] == "oem"


# I3: aritmetica de inactividad con vuelta de los 32 bits (funcion pura).


def test_ocioso_ms_maneja_la_vuelta_de_32_bits():
    assert memoria._ocioso_ms(1000, 400) == 600
    assert memoria._ocioso_ms(100, 0xFFFFFFF0) == (100 - 0xFFFFFFF0) & 0xFFFFFFFF
    assert memoria._ocioso_ms(100, 0xFFFFFFF0) < 1000


def test_interactiva_solo_si_hay_exito_y_sesion_no_es_0():
    assert memoria._interactiva(1, 1) is True
    assert memoria._interactiva(1, 0) is False
    assert memoria._interactiva(0, 1) is False


# I4: si un cierre falla a mitad del bucle, los ya cerrados quedan registrados.


def test_registra_los_ya_cerrados_si_uno_posterior_lanza(tmp_path):
    def cerrar(nombre, dormir):
        if nombre == "steam.exe":
            raise OSError("taskkill colgado")

    r = _liberar(7.0, _config(cerrables=["chrome.exe", "steam.exe"]), raiz=tmp_path,
                         libre=lambda: 1.0, inactivo=lambda: 30.0,
                         listar=lambda: [("steam.exe", 5.0), ("chrome.exe", 1.0)], cerrar=cerrar,
                         dormir=lambda s: None, primer_plano=lambda: memoria.SIN_VENTANA)
    assert r["omitido"].startswith("error: OSError")
    assert r["cerrados"] == []
    ficheros = list((tmp_path / "registro").glob("memoria_*.log"))
    assert ficheros == []


def test_registra_los_ya_cerrados_si_uno_posterior_lanza_tras_cerrar_alguno(tmp_path):
    def cerrar(nombre, dormir):
        if nombre == "chrome.exe":
            raise OSError("taskkill colgado")

    r = _liberar(7.0, _config(cerrables=["chrome.exe", "steam.exe"]), raiz=tmp_path,
                         libre=lambda: 1.0, inactivo=lambda: 30.0,
                         listar=lambda: [("steam.exe", 5.0), ("chrome.exe", 1.0)], cerrar=cerrar,
                         dormir=lambda s: None, primer_plano=lambda: memoria.SIN_VENTANA)
    assert r["omitido"].startswith("error: OSError")
    assert [c["nombre"] for c in r["cerrados"]] == ["steam.exe"]
    ficheros = list((tmp_path / "registro").glob("memoria_*.log"))
    assert len(ficheros) == 1
    linea = json.loads(ficheros[0].read_text(encoding="utf-8").strip())
    assert linea["cerrados"] == [{"nombre": "steam.exe", "gb": 5.0}]


# I5: se re-comprueba la inactividad antes de cada cierre.


def test_para_si_el_usuario_vuelve_a_mitad_del_bucle(tmp_path):
    inactividades = iter([30.0, 30.0, 3.0])
    cerrados = []
    r = _liberar(10.0, _config(cerrables=["chrome.exe", "steam.exe", "msedge.exe"]), raiz=tmp_path,
                         libre=lambda: 1.0, inactivo=lambda: next(inactividades),
                         listar=lambda: [("steam.exe", 5.0), ("chrome.exe", 3.0), ("msedge.exe", 1.0)],
                         cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                         primer_plano=lambda: memoria.SIN_VENTANA)
    assert cerrados == ["steam.exe"]
    assert r["omitido"] == "usuario activo"
    ficheros = list((tmp_path / "registro").glob("memoria_*.log"))
    assert len(ficheros) == 1


# M3: GlobalMemoryStatusEx sin comprobar el valor de retorno cerraria todo con AvailPhys en 0.


def test_libre_gb_lanza_si_globalmemorystatusex_falla(monkeypatch):
    llamado = {}

    class _Kernel32:
        def GlobalMemoryStatusEx(self, ref):
            llamado["ok"] = True
            return 0

    monkeypatch.setattr(memoria.ctypes, "windll", type("W", (), {"kernel32": _Kernel32()})())
    with pytest.raises(OSError):
        memoria.libre_gb()
    assert llamado.get("ok")


# M4: el cierre forzado nunca usa /T, solo /F /IM.


def test_cerrar_primer_intento_sin_forzar_y_espera_hasta_20s(monkeypatch):
    llamadas = []
    dormidos = []

    def fake_run(cmd, **kw):
        llamadas.append(cmd)
        if cmd[0] == "tasklist":
            # sigue vivo la primera vez, ya no la segunda
            vivo = len([c for c in llamadas if c[0] == "tasklist"]) == 1
            return _Salida("chrome.exe presente" if vivo else "")
        return _Salida("")

    monkeypatch.setattr(memoria.subprocess, "run", fake_run)
    memoria.cerrar("chrome.exe", dormidos.append)
    taskkills = [c for c in llamadas if c[0] == "taskkill"]
    assert taskkills == [["taskkill", "/IM", "chrome.exe"]]
    assert dormidos == [1]
    assert all(kw != "/T" for c in llamadas for kw in c)


def test_cerrar_fuerza_sin_T_si_no_muere_en_20s(monkeypatch):
    llamadas = []
    dormidos = []

    def fake_run(cmd, **kw):
        llamadas.append(cmd)
        if cmd[0] == "tasklist":
            return _Salida("chrome.exe presente")
        return _Salida("")

    monkeypatch.setattr(memoria.subprocess, "run", fake_run)
    memoria.cerrar("chrome.exe", dormidos.append)
    taskkills = [c for c in llamadas if c[0] == "taskkill"]
    assert taskkills == [["taskkill", "/IM", "chrome.exe"], ["taskkill", "/F", "/IM", "chrome.exe"]]
    assert len(dormidos) == 20
    assert all("/T" not in c for c in taskkills)


def test_vivo_usa_codepage_oem(monkeypatch):
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append(kw)
        return _Salida("")

    monkeypatch.setattr(memoria.subprocess, "run", fake_run)
    memoria._vivo("chrome.exe")
    assert llamadas[0]["encoding"] == "oem"
    assert llamadas[0]["creationflags"] == 0x08000000


# M5: fuera de la sesion interactiva (Session Id 0) no se cierra nada.


def test_inactivo_minutos_devuelve_0_si_no_es_interactiva(monkeypatch):
    monkeypatch.setattr(memoria, "_sesion_interactiva", lambda: False)
    assert memoria.inactivo_minutos() == 0.0


# I4 parte 2: nunca se cierra el proceso dueno de la ventana en primer plano.


def test_nunca_cierra_el_proceso_en_primer_plano():
    cerrados = []
    r = _liberar(7.0, _config(cerrables=["chrome.exe", "steam.exe"]), libre=lambda: 1.0,
                         inactivo=lambda: 30.0,
                         listar=lambda: [("steam.exe", 5.0), ("chrome.exe", 1.0)],
                         cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                         primer_plano=lambda: "steam.exe")
    assert cerrados == ["chrome.exe"]
    assert [c["nombre"] for c in r["cerrados"]] == ["chrome.exe"]
    assert r["omitido"] == ""


def test_sin_ventana_en_primer_plano_procede_con_normalidad():
    """Pantalla bloqueada, por ejemplo: no hay ninguna ventana en primer plano, se puede cerrar."""
    cerrados = []
    r = _liberar(6.0, _config(cerrables=["chrome.exe"]), libre=lambda: 1.0, inactivo=lambda: 30.0,
                         listar=lambda: [("chrome.exe", 5.0)],
                         cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                         primer_plano=lambda: memoria.SIN_VENTANA)
    assert cerrados == ["chrome.exe"]
    assert r["omitido"] == ""


def test_proceso_en_primer_plano_desconocido_no_cierra_nada():
    cerrados = []
    r = _liberar(7.0, _config(cerrables=["chrome.exe", "steam.exe"]), libre=lambda: 1.0,
                         inactivo=lambda: 30.0,
                         listar=lambda: [("steam.exe", 5.0), ("chrome.exe", 1.0)],
                         cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                         primer_plano=lambda: None)
    assert cerrados == []
    assert r["cerrados"] == []
    assert r["omitido"] == "sin ventana en primer plano conocida"


def test_proceso_en_primer_plano_desconocido_tras_cerrar_alguno_para_ahi(tmp_path):
    """Si cambia el foco a mitad del bucle y deja de poder averiguarse, lo ya cerrado queda registrado."""
    cerrados = []
    respuestas = iter(["msedge.exe", None])

    def cerrar(nombre, dormir):
        cerrados.append(nombre)

    r = _liberar(7.0, _config(cerrables=["chrome.exe", "steam.exe"]), raiz=tmp_path,
                         libre=lambda: 1.0, inactivo=lambda: 30.0,
                         listar=lambda: [("steam.exe", 5.0), ("chrome.exe", 1.0)], cerrar=cerrar,
                         dormir=lambda s: None, primer_plano=lambda: next(respuestas))
    assert cerrados == ["steam.exe"]
    assert [c["nombre"] for c in r["cerrados"]] == ["steam.exe"]
    assert r["omitido"] == "sin ventana en primer plano conocida"
    ficheros = list((tmp_path / "registro").glob("memoria_*.log"))
    assert len(ficheros) == 1


def test_proceso_primer_plano_ventana_valida_devuelve_nombre_en_minusculas(monkeypatch):
    class _User32:
        def GetForegroundWindow(self):
            return 999

        def GetWindowThreadProcessId(self, hwnd, ref):
            ref._obj.value = 4242

    class _Kernel32:
        def OpenProcess(self, acceso, heredar, pid):
            assert pid == 4242
            return 1

        def QueryFullProcessImageNameW(self, handle, flags, buffer, tam):
            buffer.value = r"C:\Program Files\Steam\Steam.exe"
            return 1

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(memoria, "_api_primer_plano", lambda: (_User32(), _Kernel32()))
    assert memoria._proceso_primer_plano() == "steam.exe"


def test_proceso_primer_plano_sin_ventana_devuelve_sin_ventana(monkeypatch):
    class _User32:
        def GetForegroundWindow(self):
            return 0

    monkeypatch.setattr(memoria, "_api_primer_plano", lambda: (_User32(), None))
    assert memoria._proceso_primer_plano() is memoria.SIN_VENTANA


def test_proceso_primer_plano_sin_poder_abrir_proceso_devuelve_none(monkeypatch):
    class _User32:
        def GetForegroundWindow(self):
            return 999

        def GetWindowThreadProcessId(self, hwnd, ref):
            ref._obj.value = 4242

    class _Kernel32:
        def OpenProcess(self, acceso, heredar, pid):
            return 0

    monkeypatch.setattr(memoria, "_api_primer_plano", lambda: (_User32(), _Kernel32()))
    assert memoria._proceso_primer_plano() is None


def test_proceso_primer_plano_excepcion_devuelve_none(monkeypatch):
    class _User32:
        def GetForegroundWindow(self):
            raise OSError("no")

    monkeypatch.setattr(memoria, "_api_primer_plano", lambda: (_User32(), None))
    assert memoria._proceso_primer_plano() is None


# A1: liberar no cierra nada fuera de la franja nocturna configurada.


def test_en_franja_limites_inclusivo_y_exclusivo():
    franja = (2, 6)
    assert memoria._en_franja(datetime(2026, 1, 1, 1, 59), franja) is False
    assert memoria._en_franja(datetime(2026, 1, 1, 2, 0), franja) is True
    assert memoria._en_franja(datetime(2026, 1, 1, 5, 59), franja) is True
    assert memoria._en_franja(datetime(2026, 1, 1, 6, 0), franja) is False


def test_liberar_no_cierra_fuera_de_franja():
    r = memoria.liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                        estado_notificacion=lambda: 0,
                        listar=lambda: (_ for _ in ()).throw(AssertionError("no deberia listar")),
                        hora_local=lambda: datetime(2026, 1, 1, 1, 59))
    assert r["cerrados"] == []
    assert r["omitido"] == "fuera de franja"
    assert r["libre_despues"] == 1.0


def test_liberar_cierra_justo_al_entrar_en_franja():
    r = _liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                listar=lambda: [("chrome.exe", 5.0)],
                cerrar=lambda nombre, dormir: None, dormir=lambda s: None,
                primer_plano=lambda: memoria.SIN_VENTANA,
                hora_local=lambda: datetime(2026, 1, 1, 2, 0))
    assert r["omitido"] == ""


def test_liberar_no_cierra_justo_al_salir_de_franja():
    r = memoria.liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                        estado_notificacion=lambda: 0,
                        listar=lambda: (_ for _ in ()).throw(AssertionError("no deberia listar")),
                        hora_local=lambda: datetime(2026, 1, 1, 6, 0))
    assert r["omitido"] == "fuera de franja"


def test_liberar_respeta_franja_configurada_distinta_a_la_por_defecto():
    r = _liberar(4.0, _config(franja_cierre=[22, 23]), libre=lambda: 1.0, inactivo=lambda: 30.0,
                listar=lambda: (_ for _ in ()).throw(AssertionError("no deberia listar")),
                hora_local=lambda: datetime(2026, 1, 1, 3, 0))
    assert r["omitido"] == "fuera de franja"


def test_franja_de_usa_defecto_si_config_invalida():
    assert memoria._franja_de({"franja_cierre": "no-lista"}) == tuple(memoria._DEFECTO["franja_cierre"])
    assert memoria._franja_de({}) == tuple(memoria._DEFECTO["franja_cierre"])


# A3: liberar no cierra nada si ni cerrando todos los candidatos se llega al objetivo.


def test_liberar_no_cierra_si_no_alcanza():
    cerrados = []
    r = _liberar(20.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                listar=lambda: [("chrome.exe", 2.0), ("steam.exe", 1.0)],
                cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                primer_plano=lambda: memoria.SIN_VENTANA)
    assert cerrados == []
    assert r["cerrados"] == []
    assert r["omitido"] == "no alcanza"
    assert r["libre_despues"] == 1.0


def test_liberar_cierra_si_justo_alcanza_con_todos_los_candidatos():
    cerrados = []
    r = _liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                listar=lambda: [("chrome.exe", 2.0), ("steam.exe", 1.0)],
                cerrar=lambda nombre, dormir: cerrados.append(nombre), dormir=lambda s: None,
                primer_plano=lambda: memoria.SIN_VENTANA)
    assert cerrados == ["chrome.exe", "steam.exe"]
    assert r["omitido"] == ""


# A4: liberar no cierra nada si el PC esta ocupado por un juego o pantalla completa D3D (QUNS=3).


def test_liberar_no_cierra_si_juego_a_pantalla_completa():
    r = memoria.liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                        hora_local=lambda: datetime(2026, 1, 1, 3, 0),
                        listar=lambda: (_ for _ in ()).throw(AssertionError("no deberia listar")),
                        estado_notificacion=lambda: memoria.QUNS_RUNNING_D3D_FULL_SCREEN)
    assert r["cerrados"] == []
    assert r["omitido"] == "juego a pantalla completa"
    assert r["libre_despues"] == 1.0


def test_liberar_cierra_si_estado_notificacion_no_es_juego():
    r = _liberar(4.0, _config(), libre=lambda: 1.0, inactivo=lambda: 30.0,
                listar=lambda: [("chrome.exe", 5.0)],
                cerrar=lambda nombre, dormir: None, dormir=lambda s: None,
                primer_plano=lambda: memoria.SIN_VENTANA, estado_notificacion=lambda: 2)
    assert r["omitido"] == ""
