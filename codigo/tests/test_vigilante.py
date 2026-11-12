import json
from datetime import datetime, timedelta

import pytest

from quant.investigacion import vigilante

FECHA = "20260918"
AHORA = datetime(2026, 9, 18, 7, 30)


def _parte(**cambios):
    base = {"fecha": FECHA, "inicio": "2026-09-18T02:00:05", "desde": "2026-09-18T00:00:05+00:00",
            "fin_previsto": "2026-09-18T06:00:00", "fin_real": "2026-09-18T05:10:00", "equipo": "PRINCIPAL",
            "etapas": {"investigar": {"inicio": 0, "segundos": 9, "resultado": {"codigo": 0}}},
            "catalogo": {}, "corte": False, "errores": 0}
    return base | cambios


def _revision(**cambios):
    base = {"fecha": FECHA, "estado": "ok", "resumen": "r", "correo": "c", "criterios": "", "paquete_bytes": 10,
            "notas": {}, "acciones": [], "error": ""}
    return base | cambios


def _sistema(procesos=(), **tareas):
    reciente = (AHORA - timedelta(hours=5)).isoformat()
    base = {"Quant_Noche": {"estado": "Ready", "ultima": reciente},
            "Quant_Revision": {"estado": "Ready", "ultima": reciente},
            "Quant_Demo": {"estado": "Ready", "ultima": reciente},
            "Quant_Barrido": {"estado": "Ready", "ultima": reciente}}
    return {"procesos": list(procesos), "tareas": base | tareas}


def _raiz(tmp_path, parte=None, revision=None, correo=0):
    (tmp_path / "informes").mkdir()
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "registro").mkdir()
    if parte is not None:
        (tmp_path / "informes" / f"parte_{FECHA}.json").write_text(json.dumps(parte), encoding="utf-8")
    if revision is not None:
        (tmp_path / "supervisor" / f"revision_{FECHA}.json").write_text(json.dumps(revision), encoding="utf-8")
    if correo is not False:
        lineas = [{"fecha": FECHA, "estado": "sin revision", "correo": None}, {"fecha": FECHA, "estado": "ok", "correo": correo}]
        (tmp_path / "registro" / f"revision_{FECHA}.log").write_text(
            "\n".join(json.dumps(l) for l in lineas) + "\n", encoding="utf-8")
    (tmp_path / "registro" / f"noche_{FECHA}.log").write_text("linea 1\nlinea 2\n", encoding="utf-8")
    return tmp_path


class _Smtp:
    enviados = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, usuario, contrasena):
        pass

    def send_message(self, mensaje):
        _Smtp.enviados.append(mensaje)


def _obtener(servicio, clave):
    return {"usuario": "usuario@example.com", "usuario@example.com": "app-pass"}.get(clave)


def test_todo_bien_es_silencio(tmp_path):
    _Smtp.enviados = []
    raiz = _raiz(tmp_path, _parte(), _revision())
    assert vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA) == {"graves": [], "avisados": []}
    codigo = vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_sistema(), smtp=_Smtp(),
                            obtener=_obtener, ahora=AHORA)
    assert codigo == 0 and _Smtp.enviados == []
    linea = json.loads((raiz / "registro" / f"vigilante_{FECHA}.log").read_text(encoding="utf-8").splitlines()[-1])
    assert linea["graves"] == [] and linea["correo"] is None


def test_fallo_de_etapa_ya_lo_conto_el_correo(tmp_path):
    parte = _parte(errores=1, etapas={"investigar": {"inicio": 0, "segundos": 9,
                                                     "resultado": {"codigo": 1, "fallo": "TypeError: x"}}})
    raiz = _raiz(tmp_path, parte, _revision(estado="aviso"))
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert salida["graves"] == [] and any("investigar" in a for a in salida["avisados"])


# S1: sin llama-server.exe, todos los modelos fallan aunque Ollama responda; hay que avisar
# aunque el correo de la manana ya haya salido.


def test_ollama_sin_motor_es_grave(tmp_path):
    parte = _parte(ollama={"arrancado": False, "disponible": True, "motor": False})
    raiz = _raiz(tmp_path, parte, _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.local.MENSAJE_SIN_MOTOR in salida["graves"]


def test_ollama_con_motor_no_es_grave(tmp_path):
    parte = _parte(ollama={"arrancado": False, "disponible": True, "motor": True})
    raiz = _raiz(tmp_path, parte, _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.local.MENSAJE_SIN_MOTOR not in salida["graves"]


def test_parte_sin_clave_motor_no_avisa(tmp_path):
    parte = _parte(ollama={"arrancado": False, "disponible": True})
    raiz = _raiz(tmp_path, parte, _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.local.MENSAJE_SIN_MOTOR not in salida["graves"]


def test_parte_vieja_sin_ollama_no_avisa(tmp_path):
    raiz = _raiz(tmp_path, _parte(), _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.local.MENSAJE_SIN_MOTOR not in salida["graves"]


def test_graves(tmp_path):
    raiz = _raiz(tmp_path, parte=None, revision=None, correo=False)
    viejo = (AHORA - timedelta(hours=40)).isoformat()
    sistema = _sistema(procesos=[{"pid": 77, "horas": 9.5, "orden": "pythonw -m quant.investigacion.noche"}],
                       Quant_Noche={"estado": "Disabled", "ultima": viejo}, Quant_Revision=None)
    graves = vigilante.comprobar(raiz, FECHA, sistema, ahora=AHORA)["graves"]
    texto = "\n".join(graves)
    assert "parte" in texto and "revision" in texto and "correo" in texto
    assert "77" in texto and "Quant_Noche" in texto and "Quant_Revision" in texto


def test_noche_sin_terminar_y_correo_fallido(tmp_path):
    raiz = _raiz(tmp_path, _parte(fin_real=None), _revision(), correo=1)
    graves = "\n".join(vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)["graves"])
    assert "no termino" in graves and "correo" in graves


def test_main_manda_el_aviso_sin_la_contrasena(tmp_path):
    _Smtp.enviados = []
    raiz = _raiz(tmp_path, parte=None, revision=_revision(), correo=False)
    codigo = vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_sistema(), smtp=_Smtp(),
                            obtener=_obtener, ahora=AHORA)
    assert codigo == 0 and len(_Smtp.enviados) == 1
    mensaje = _Smtp.enviados[0]
    assert mensaje["Subject"] == "[Quant] 18-sep · vigilante · 🛑"
    cuerpo = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert "parte" in cuerpo and "linea 2" in cuerpo and "app-pass" not in mensaje.as_string()


def test_main_sin_credencial_o_sin_smtp_devuelve_1(tmp_path):
    raiz = _raiz(tmp_path, parte=None, revision=None, correo=False)
    sin_credencial = lambda servicio, clave: None
    assert vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_sistema(), smtp=_Smtp(),
                          obtener=sin_credencial, ahora=AHORA) == 1
    linea = json.loads((raiz / "registro" / f"vigilante_{FECHA}.log").read_text(encoding="utf-8").splitlines()[-1])
    assert linea["graves"] and linea["correo"] == "sin credencial"


def test_un_sistema_que_no_responde_no_tumba_al_vigilante(tmp_path):
    raiz = _raiz(tmp_path, _parte(), _revision())

    def roto():
        raise OSError("powershell no responde")
    codigo = vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=roto, smtp=_Smtp(), obtener=_obtener,
                            ahora=AHORA)
    linea = json.loads((raiz / "registro" / f"vigilante_{FECHA}.log").read_text(encoding="utf-8").splitlines()[-1])
    assert codigo == 0 and any("sistema" in a for a in linea["avisados"])


def test_fallo_de_envio_devuelve_1(tmp_path):
    raiz = _raiz(tmp_path, parte=None, revision=_revision(), correo=False)

    class _SmtpRoto:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, usuario, contrasena):
            pass

        def send_message(self, mensaje):
            raise OSError("smtp caido")

    codigo = vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_sistema(), smtp=_SmtpRoto(),
                            obtener=_obtener, ahora=AHORA)
    assert codigo == 1
    linea = json.loads((raiz / "registro" / f"vigilante_{FECHA}.log").read_text(encoding="utf-8").splitlines()[-1])
    assert linea["correo"].startswith("fallo")


def test_arranque_tardio_usa_la_fecha_de_ayer(tmp_path):
    fecha_ayer = "20260917"
    (tmp_path / "informes").mkdir()
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "registro").mkdir()
    parte = {**_parte(), "fecha": fecha_ayer}
    revision = {**_revision(), "fecha": fecha_ayer}
    (tmp_path / "informes" / f"parte_{fecha_ayer}.json").write_text(json.dumps(parte), encoding="utf-8")
    (tmp_path / "supervisor" / f"revision_{fecha_ayer}.json").write_text(json.dumps(revision), encoding="utf-8")
    lineas = [{"fecha": fecha_ayer, "estado": "ok", "correo": 0}]
    (tmp_path / "registro" / f"revision_{fecha_ayer}.log").write_text(
        "\n".join(json.dumps(l) for l in lineas) + "\n", encoding="utf-8")
    (tmp_path / "registro" / f"noche_{fecha_ayer}.log").write_text("linea 1\n", encoding="utf-8")

    madrugada = datetime(2026, 9, 18, 0, 30)
    reciente = (madrugada - timedelta(hours=5)).isoformat()
    sistema = {"procesos": [], "tareas": {"Quant_Noche": {"estado": "Ready", "ultima": reciente},
                                          "Quant_Revision": {"estado": "Ready", "ultima": reciente},
            "Quant_Demo": {"estado": "Ready", "ultima": reciente},
            "Quant_Barrido": {"estado": "Ready", "ultima": reciente}}}
    codigo = vigilante.main(["--raiz", str(tmp_path)], sistema=sistema, smtp=_Smtp(), obtener=_obtener,
                            ahora=madrugada)
    assert codigo == 0
    assert (tmp_path / "registro" / f"vigilante_{fecha_ayer}.log").exists()
    assert not (tmp_path / "registro" / "vigilante_20260918.log").exists()


@pytest.mark.parametrize("hora,minuto,fecha", [(0, 30, "20260917"), (7, 0, "20260917"),
                                               (7, 30, "20260918"), (9, 0, "20260918")])
def test_sin_fecha_antes_de_la_hora_del_vigilante_revisa_ayer(tmp_path, hora, minuto, fecha):
    for carpeta in ("informes", "supervisor", "registro"):
        (tmp_path / carpeta).mkdir()
    ahora = datetime(2026, 9, 18, hora, minuto)
    vigilante.main(["--raiz", str(tmp_path)], sistema=_sistema(), smtp=_Smtp(), obtener=lambda s, c: None,
                   ahora=ahora)
    assert [p.name for p in (tmp_path / "registro").glob("vigilante_*.log")] == [f"vigilante_{fecha}.log"]


def test_estado_sistema_lanza_si_powershell_falla(monkeypatch):
    class _Resultado:
        def __init__(self, returncode, stdout, stderr):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    monkeypatch.setattr(vigilante.subprocess, "run", lambda *a, **k: _Resultado(1, "", "acceso denegado"))
    try:
        vigilante.estado_sistema()
        assert False, "debia lanzar OSError"
    except OSError as e:
        assert "1" in str(e) and "acceso denegado" in str(e)

    monkeypatch.setattr(vigilante.subprocess, "run", lambda *a, **k: _Resultado(0, "   ", ""))
    try:
        vigilante.estado_sistema()
        assert False, "debia lanzar OSError"
    except OSError:
        pass

    salida_ok = json.dumps({"procesos": [], "tareas": [{"nombre": "Quant_Noche", "estado": "Redy", "ultima": None}]})
    monkeypatch.setattr(vigilante.subprocess, "run", lambda *a, **k: _Resultado(0, salida_ok, ""))
    estado = vigilante.estado_sistema()
    assert estado["tareas"]["Quant_Noche"]["estado"] == "Redy"


def test_cola_recorta_lineas_muy_largas(tmp_path):
    ruta = tmp_path / "largo.log"
    ruta.write_text("x" * 10000 + "\n", encoding="utf-8")
    cola = vigilante._cola(ruta)
    assert len(cola) == vigilante._MAX_LINEA_COLA


@pytest.mark.parametrize("correo,donde", [(0, "avisados"), (False, "graves")])
def test_sin_parte_con_correo_salido_no_es_grave(tmp_path, correo, donde):
    raiz = _raiz(tmp_path, parte=None, revision=_revision(), correo=correo)
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert any("sin parte" in g for g in salida[donde])
    assert not any("sin parte" in g for g in salida["avisados" if donde == "graves" else "graves"])


@pytest.mark.parametrize("correo,donde", [(0, "avisados"), (False, "graves")])
def test_noche_sin_terminar_con_correo_salido_no_es_grave(tmp_path, correo, donde):
    raiz = _raiz(tmp_path, _parte(fin_real=None), _revision(), correo=correo)
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert any("no termino" in g for g in salida[donde])
    assert not any("no termino" in g for g in salida["avisados" if donde == "graves" else "graves"])


@pytest.mark.parametrize("orden,horas,grave", [
    ("pythonw -m quant.actualizar --desde 2000", 9.0, False),
    ("pythonw -m quant.actualizar --desde 2000", 12.5, True),
    ("pythonw -m quant.investigacion.noche", 6.5, True),
    ("pythonw -m quant.investigacion.revision --correo", 6.5, True),
    ("pythonw -m quant.investigacion.vigilante", 6.5, True),
    ("pythonw -m quant.investigacion.noche", 5.0, False),
])
def test_umbral_de_proceso_colgado_segun_la_orden(tmp_path, orden, horas, grave):
    raiz = _raiz(tmp_path, _parte(), _revision())
    sistema = _sistema(procesos=[{"pid": 77, "horas": horas, "orden": orden}])
    graves = vigilante.comprobar(raiz, FECHA, sistema, ahora=AHORA)["graves"]
    assert any("colgado" in g for g in graves) is grave


def test_consulta_de_procesos_filtra_las_ordenes_vigiladas():
    assert r"quant\.investigacion\.(noche|revision|vigilante)" in vigilante._CONSULTA
    assert r"quant\.actualizar" in vigilante._CONSULTA
    assert vigilante.MAX_HORAS_ACTUALIZAR == 12


def _roto():
    raise OSError("powershell no responde")


def test_sistema_sin_consultar_dos_dias_seguidos_es_grave(tmp_path):
    raiz = _raiz(tmp_path, _parte(), _revision())
    ayer = raiz / "registro" / "vigilante_20260917.log"
    ayer.write_text(json.dumps({"graves": [], "avisados": ["no se pudo consultar el sistema: OSError: x"],
                                "correo": None}) + "\n", encoding="utf-8")
    vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_roto, smtp=_Smtp(), obtener=lambda s, c: None,
                   ahora=AHORA)
    linea = json.loads((raiz / "registro" / f"vigilante_{FECHA}.log").read_text(encoding="utf-8").splitlines()[-1])
    assert "no se puede consultar el sistema desde hace dos dias" in linea["graves"]


def test_sistema_sin_consultar_un_solo_dia_no_es_grave(tmp_path):
    raiz = _raiz(tmp_path, _parte(), _revision())
    (raiz / "registro" / "vigilante_20260917.log").write_text(
        json.dumps({"graves": [], "avisados": [], "correo": None}) + "\n", encoding="utf-8")
    vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_roto, smtp=_Smtp(), obtener=lambda s, c: None,
                   ahora=AHORA)
    linea = json.loads((raiz / "registro" / f"vigilante_{FECHA}.log").read_text(encoding="utf-8").splitlines()[-1])
    assert linea["graves"] == []


def test_sesion_claude_caducada_es_grave(tmp_path):
    parte = _parte(claude={"exe": "claude", "sesion": False, "error": "Please run /login", "llamadas": 0})
    raiz = _raiz(tmp_path, parte, _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.MENSAJE_SESION_CLAUDE in salida["graves"]


def test_sesion_claude_viva_no_avisa(tmp_path):
    parte = _parte(claude={"exe": "claude", "sesion": True, "llamadas": 40})
    raiz = _raiz(tmp_path, parte, _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.MENSAJE_SESION_CLAUDE not in salida["graves"]


def test_claude_sin_respuesta_no_pide_login(tmp_path):
    parte = _parte(claude={"exe": "claude", "sesion": False, "causa": "fallo", "llamadas": 0})
    raiz = _raiz(tmp_path, parte, _revision())
    salida = vigilante.comprobar(raiz, FECHA, _sistema(), ahora=AHORA)
    assert vigilante.MENSAJE_SESION_CLAUDE not in salida["graves"]
    assert vigilante.MENSAJE_CLAUDE_SIN_RESPUESTA in salida["graves"]


def test_vigilante_reports_demo_events_once(tmp_path):
    import sqlite3
    from quant.demo import diario
    raiz = _raiz(tmp_path, parte=_parte(), revision=_revision())
    con = sqlite3.connect(raiz / "catalogo.db")
    diario.ensure_schema(con)
    for kind, text in (("retire", "Retirada por desvio"), ("enter", "Entra"), ("mismatch", "Descuadre raro"),
                       ("warn", "Muchas posiciones")):
        con.execute("INSERT INTO demo_events(ts,kind,strategy_id,detail_es) VALUES(?,?,?,?)",
                    ("2026-09-18T01:00:00", kind, None, text))
    con.commit()
    con.close()
    _Smtp.enviados.clear()
    args = ["--raiz", str(raiz), "--fecha", FECHA]
    assert vigilante.main(args, sistema=_sistema(), smtp=_Smtp(), obtener=_obtener, ahora=AHORA) == 0
    assert len(_Smtp.enviados) == 1
    cuerpo = _Smtp.enviados[0].get_body(preferencelist=("plain",)).get_content()
    assert "Retirada por desvio" in cuerpo and "Descuadre raro" in cuerpo and "Muchas posiciones" in cuerpo
    assert "Entra" not in cuerpo
    assert vigilante.main(args, sistema=_sistema(), smtp=_Smtp(), obtener=_obtener, ahora=AHORA) == 0
    assert len(_Smtp.enviados) == 1


def test_vigilante_watches_demo_and_barrido_tasks(tmp_path):
    assert {"Quant_Demo", "Quant_Barrido"} <= set(vigilante.TAREAS_VIGILADAS)
    raiz = _raiz(tmp_path, parte=_parte(), revision=_revision())
    viejo = (AHORA - timedelta(days=5)).isoformat()
    res = vigilante.comprobar(raiz, FECHA, _sistema(Quant_Barrido={"estado": "Ready", "ultima": viejo}), ahora=AHORA)
    assert res["graves"] == []
    res = vigilante.comprobar(raiz, FECHA, _sistema(Quant_Demo={"estado": "Ready", "ultima": viejo}), ahora=AHORA)
    assert any("Quant_Demo" in g for g in res["graves"])


def test_vigilante_dedupes_persistent_warnings(tmp_path):
    import sqlite3
    from quant.demo import diario
    raiz = _raiz(tmp_path, parte=_parte(), revision=_revision())
    con = sqlite3.connect(raiz / "catalogo.db")
    diario.ensure_schema(con)

    def warn(texto):
        con.execute("INSERT INTO demo_events(ts,kind,detail_es) VALUES('2026-09-18T01:00:00','warn',?)", (texto,))
        con.commit()
    _Smtp.enviados.clear()
    args = ["--raiz", str(raiz), "--fecha", FECHA]
    correr = lambda: vigilante.main(args, sistema=_sistema(), smtp=_Smtp(), obtener=_obtener, ahora=AHORA)
    warn("Demasiadas posiciones")
    warn("Demasiadas posiciones")
    assert correr() == 0 and len(_Smtp.enviados) == 1
    warn("Demasiadas posiciones")
    assert correr() == 0 and len(_Smtp.enviados) == 1
    assert correr() == 0 and len(_Smtp.enviados) == 1
    warn("Otra cosa")
    assert correr() == 0 and len(_Smtp.enviados) == 2
    assert correr() == 0
    warn("Demasiadas posiciones")
    assert correr() == 0 and len(_Smtp.enviados) == 3


def test_vigilante_dedupes_repeated_mismatch(tmp_path):
    import sqlite3
    from quant.demo import diario
    raiz = _raiz(tmp_path, parte=_parte(), revision=_revision())
    con = sqlite3.connect(raiz / "catalogo.db")
    diario.ensure_schema(con)

    def mismatch():
        con.execute("INSERT INTO demo_events(ts,kind,detail_es) VALUES('2026-09-18T01:00:00','mismatch','Descuadre 3')")
        con.commit()
    _Smtp.enviados.clear()
    correr = lambda: vigilante.main(["--raiz", str(raiz), "--fecha", FECHA], sistema=_sistema(), smtp=_Smtp(),
                                    obtener=_obtener, ahora=AHORA)
    mismatch()
    mismatch()
    assert correr() == 0 and len(_Smtp.enviados) == 1
    assert _Smtp.enviados[0].get_body(preferencelist=("plain",)).get_content().count("Descuadre 3") == 1
    mismatch()
    assert correr() == 0 and len(_Smtp.enviados) == 1


def test_estado_sistema_trae_proxima_y_resultado(monkeypatch):
    class _Resultado:
        returncode, stderr = 0, ""
        stdout = json.dumps({"procesos": [], "tareas": [
            {"nombre": "Quant_Noche", "estado": "Ready", "ultima": "2026-11-12T01:00:00", "proxima": "2026-11-13T01:00:00",
             "resultado": 0},
            {"nombre": "Quant_Panel", "estado": "Running", "ultima": "2026-11-12T08:00:00", "proxima": None,
             "resultado": 267009}]})

    assert "NextRunTime" in vigilante._CONSULTA and "LastTaskResult" in vigilante._CONSULTA
    monkeypatch.setattr(vigilante.subprocess, "run", lambda *a, **k: _Resultado())
    t = vigilante.estado_sistema()["tareas"]
    assert t["Quant_Noche"] == {"estado": "Ready", "ultima": "2026-11-12T01:00:00", "proxima": "2026-11-13T01:00:00",
                                "resultado": 0}
    assert t["Quant_Panel"]["proxima"] is None and t["Quant_Panel"]["resultado"] == 267009
