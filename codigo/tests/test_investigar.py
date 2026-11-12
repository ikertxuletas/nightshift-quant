import json
import types

import pytest

from quant.investigacion import catalogo, investigar


def _preparar(tmp_path):
    (tmp_path / "config").mkdir()
    import shutil
    from quant import criterios, rutas
    for f in ("criterios.json", "costes.json", "universo.json"):
        shutil.copy(rutas.CONFIG / f, tmp_path / "config" / f)
    criterios.firmar(tmp_path / "config")
    con = catalogo.abrir(tmp_path / "catalogo.db")
    return con


def test_encadena_etapas_y_valida(tmp_path, monkeypatch, capsys):
    con = _preparar(tmp_path)
    ficha = {"id": "ficha-prueba", "titulo": "Tendencia SPY", "fuente": {"url": "materiales://prueba.md", "cita": "regla 1"}, "tipo": "tendencia",
             "forma": "serie_temporal", "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
             "entrada": {"largo": {">": ["close", "SMA(5)"]}}, "gestion": {}, "estado": "borrador"}
    doc = catalogo.anadir_documento(con, "arxiv", "u", "T", "2026-01-01", "t", tmp_path / "documentos")
    ficha_id = catalogo.guardar_ficha(con, doc, ficha, "aprobada")
    catalogo.marcar(con, doc, "criticado")
    recibido = {}

    def _procesar_lectura(con, raiz, **k):
        recibido["raiz_lectura"] = raiz
        return {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0}

    def _procesar_fichas(con, **k):
        recibido["fichas"] = True
        return {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0}

    monkeypatch.setattr(investigar.explorar, "main", lambda *a, **k: 0)
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", _procesar_lectura)
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", _procesar_fichas)
    monkeypatch.setattr(investigar.validacion, "validar", lambda *a, **k: {"SPY": {"veredicto": "no_pasa", "criterios": []}})
    monkeypatch.setattr(investigar.datos, "cargar", lambda *a, **k: {"ts": [], "close": []})
    monkeypatch.setattr(investigar.calidad, "bloqueo", lambda *a, **k: None)
    assert investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "",
                           ocupado=lambda: "") == 0
    fila = con.execute("SELECT * FROM resultados").fetchone()
    assert (fila["ficha_id"], fila["veredicto"]) == (ficha_id, "no_pasa")
    assert [r["id"] for r in catalogo.pendientes(con, "validado")] == [doc]
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["validadas"] == 1
    assert recibido["raiz_lectura"] == tmp_path / "documentos" and recibido["fichas"]


def test_calidad_bloqueada_no_valida(tmp_path, monkeypatch):
    con = _preparar(tmp_path)
    ficha = {"id": "ficha-prueba", "titulo": "Tendencia SPY", "fuente": {"url": "materiales://prueba.md", "cita": "regla 1"}, "tipo": "tendencia",
             "forma": "serie_temporal", "universo": {"instrumentos": ["US500"], "plazo": "D1"},
             "entrada": {"largo": {">": ["close", "SMA(5)"]}}, "gestion": {}, "estado": "borrador"}
    doc = catalogo.anadir_documento(con, "arxiv", "u", "T", "2026-01-01", "t", tmp_path / "documentos")
    catalogo.guardar_ficha(con, doc, ficha, "aprobada")
    catalogo.marcar(con, doc, "criticado")
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.calidad, "bloqueo", lambda *a, **k: "faltan 73 dias")
    investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "", ocupado=lambda: "")
    fila = con.execute("SELECT * FROM resultados").fetchone()
    assert fila["veredicto"] == "pendiente_datos" and "73 dias" in fila["json"]


def test_espera_si_el_pc_esta_ocupado_pero_valida_igual(tmp_path, monkeypatch):
    con = _preparar(tmp_path)
    ficha = {"id": "ficha-prueba", "titulo": "Tendencia SPY", "fuente": {"url": "materiales://prueba.md", "cita": "regla 1"}, "tipo": "tendencia",
             "forma": "serie_temporal", "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
             "entrada": {"largo": {">": ["close", "SMA(5)"]}}, "gestion": {}, "estado": "borrador"}
    doc = catalogo.anadir_documento(con, "arxiv", "u", "T", "2026-01-01", "t", tmp_path / "documentos")
    catalogo.guardar_ficha(con, doc, ficha, "aprobada")
    esperas, llamadas = [], []
    monkeypatch.setattr(investigar.time, "sleep", esperas.append)
    monkeypatch.setattr(investigar.validacion, "validar", lambda *a, **k: {"SPY": {"veredicto": "no_pasa", "criterios": []}})
    monkeypatch.setattr(investigar.datos, "cargar", lambda *a, **k: {"ts": [], "close": []})
    monkeypatch.setattr(investigar.calidad, "bloqueo", lambda *a, **k: None)
    codigo = investigar.main(["--raiz", str(tmp_path), "--sin-explorar"],
                             llamar=lambda *a, **k: llamadas.append(1),
                             ocupado=lambda: "juego a pantalla completa")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 0 and ultimo["omitido"] == "pc ocupado" and len(esperas) == 10
    assert llamadas == [] and ultimo["validadas"] == 1


def test_main_devuelve_1_si_el_proceso_revienta(tmp_path, monkeypatch):
    _preparar(tmp_path)

    def _explota(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(investigar.agentes, "procesar_lectura", _explota)
    codigo = investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "",
                             ocupado=lambda: "")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 1 and ultimo["fallo"] == "RuntimeError: boom" and ultimo["errores"] == 1
    assert ultimo["errores_infra"] == 1
    lineas = [json.loads(l) for l in
              (tmp_path / "registro").glob("investigar_*.log").__next__().read_text(encoding="utf-8").splitlines()]
    assert lineas[-1] == {"etapa": "proceso", "error": "RuntimeError: boom"}


def test_errores_de_fuente_no_cambian_el_codigo_de_salida(tmp_path, monkeypatch):
    """Cuando falla alguna fuente pero no todas, explorar.main devuelve 0: no debe tirar la etapa."""
    _preparar(tmp_path)

    def _explorar(argv, **k):
        (tmp_path / "registro").mkdir(parents=True, exist_ok=True)
        (tmp_path / "registro" / "explorar_ultimo.json").write_text(
            json.dumps({"por_fuente": {}, "nuevos": 0, "errores": 2}), encoding="utf-8")
        return 0

    monkeypatch.setattr(investigar.explorar, "main", _explorar)
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    codigo = investigar.main(["--raiz", str(tmp_path)], llamar=lambda *a, **k: "", ocupado=lambda: "")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 0 and ultimo["fuentes_con_error"] == 2


def test_explorar_fallido_es_infra_y_hace_fallar_investigar(tmp_path, monkeypatch):
    """explorar.main solo devuelve distinto de 0 si fallaron todas las fuentes: eso es infra."""
    _preparar(tmp_path)

    def _explorar(argv, **k):
        (tmp_path / "registro").mkdir(parents=True, exist_ok=True)
        (tmp_path / "registro" / "explorar_ultimo.json").write_text(
            json.dumps({"por_fuente": {}, "nuevos": 0, "errores": 3}), encoding="utf-8")
        return 1

    monkeypatch.setattr(investigar.explorar, "main", _explorar)
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    codigo = investigar.main(["--raiz", str(tmp_path)], llamar=lambda *a, **k: "", ocupado=lambda: "")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 1 and ultimo["errores_infra"] == 1 and ultimo["errores"] == 1


def test_errores_de_contenido_no_hacen_fallar_main(tmp_path, monkeypatch):
    _preparar(tmp_path)
    monkeypatch.setattr(investigar.explorar, "main", lambda *a, **k: 0)
    monkeypatch.setattr(investigar.agentes, "procesar_lectura",
                        lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 2,
                                         "errores_contenido": 2, "errores_infra": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas",
                        lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0,
                                         "errores_contenido": 0, "errores_infra": 0, "omitidos": 0, "agotados": 0})
    codigo = investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "",
                             ocupado=lambda: "")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 0 and ultimo["errores"] == 2 and ultimo["errores_contenido"] == 2 and ultimo["errores_infra"] == 0


def test_errores_de_infra_hacen_fallar_main(tmp_path, monkeypatch):
    _preparar(tmp_path)
    monkeypatch.setattr(investigar.explorar, "main", lambda *a, **k: 0)
    monkeypatch.setattr(investigar.agentes, "procesar_lectura",
                        lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 1,
                                         "errores_contenido": 0, "errores_infra": 1, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas",
                        lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0,
                                         "errores_contenido": 0, "errores_infra": 0, "omitidos": 0, "agotados": 0})
    codigo = investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "",
                             ocupado=lambda: "")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 1 and ultimo["errores"] == 1 and ultimo["errores_infra"] == 1


def test_validar_fichas_nuevas_ficha_invalida_es_error_de_contenido(tmp_path):
    con = _preparar(tmp_path)
    ficha = {"id": "ficha-mala", "titulo": "x", "fuente": {"url": "materiales://x", "cita": "c"}}
    doc = catalogo.anadir_documento(con, "arxiv", "u", "T", "2026-01-01", "t", tmp_path / "documentos")
    catalogo.guardar_ficha(con, doc, ficha, "aprobada")
    catalogo.marcar(con, doc, "criticado")
    r = investigar._validar_fichas_nuevas(con, tmp_path, None, lambda: 0)
    assert r == {"validadas": 0, "errores": 1, "errores_contenido": 1}


def test_validar_ficha_sin_catalogo(tmp_path, monkeypatch):
    _preparar(tmp_path)
    ficha = {"id": "ficha-prueba", "forma": "serie_temporal", "universo": {"instrumentos": ["SPY", "QQQ"], "plazo": "D1"}}
    monkeypatch.setattr(investigar.calidad, "bloqueo", lambda instrumento, raiz: "hueco" if instrumento == "QQQ" else None)
    monkeypatch.setattr(investigar.datos, "cargar", lambda *a, **k: {"ts": [], "close": []})
    monkeypatch.setattr(investigar.validacion, "validar",
                        lambda f, barras, costes, crit: {i: {"veredicto": "no_pasa"} for i in barras})
    resultado = investigar.validar_ficha(ficha, tmp_path)
    assert resultado == {"QQQ": {"veredicto": "pendiente_datos", "motivo": "calidad: hueco"},
                         "SPY": {"veredicto": "no_pasa"}}


def test_canario_valida_con_la_misma_funcion_que_investigar(monkeypatch):
    from quant.investigacion import canario
    monkeypatch.setattr(investigar, "validar_ficha", lambda ficha, raiz: {"SPY": {"veredicto": "visto", "raiz": raiz}})
    assert canario.validar_real({"id": "x"}, "r") == {"SPY": {"veredicto": "visto", "raiz": "r"}}


def test_ocupado_defecto_sin_pantalla_completa_no_ocupa(tmp_path, monkeypatch):
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: False)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: None)
    assert investigar._ocupado_defecto(tmp_path) == ""


def test_ocupado_defecto_pantalla_completa_con_alguien_delante_ocupa(tmp_path, monkeypatch):
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: True)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: None)
    monkeypatch.setattr(investigar.memoria, "cargar_config", lambda raiz: {"inactividad_minutos": 15})
    monkeypatch.setattr(investigar.memoria, "inactivo_minutos", lambda: 2.0)
    assert investigar._ocupado_defecto(tmp_path) == "juego o pantalla completa"


def test_ocupado_defecto_pantalla_completa_sin_nadie_delante_no_ocupa(tmp_path, monkeypatch):
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: True)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: None)
    monkeypatch.setattr(investigar.memoria, "cargar_config", lambda raiz: {"inactividad_minutos": 15})
    monkeypatch.setattr(investigar.memoria, "inactivo_minutos", lambda: 30.0)
    assert investigar._ocupado_defecto(tmp_path) == ""


def test_ocupado_defecto_sin_carga_py_no_ocupa(tmp_path, monkeypatch):
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (None, "no existe"))
    assert investigar._ocupado_defecto(tmp_path) == ""


def test_ocupado_defecto_juego_d3d_exclusivo_siempre_ocupa_aunque_lleve_horas_inactivo(tmp_path, monkeypatch):
    """Mando de juego o video a pantalla completa: no reinicia GetLastInputInfo, pero
    SHQueryUserNotificationState==3 (QUNS_RUNNING_D3D_FULL_SCREEN) debe parar la noche igual."""
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: False)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: investigar.QUNS_RUNNING_D3D_FULL_SCREEN)
    monkeypatch.setattr(investigar.memoria, "cargar_config", lambda raiz: {"inactividad_minutos": 15})
    monkeypatch.setattr(investigar.memoria, "inactivo_minutos", lambda: 999.0)
    assert investigar._ocupado_defecto(tmp_path) == "juego o pantalla completa"


def test_ocupado_defecto_estado_notificacion_distinto_de_3_sigue_la_regla_normal(tmp_path, monkeypatch):
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: True)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: 2)
    monkeypatch.setattr(investigar.memoria, "cargar_config", lambda raiz: {"inactividad_minutos": 15})
    monkeypatch.setattr(investigar.memoria, "inactivo_minutos", lambda: 30.0)
    assert investigar._ocupado_defecto(tmp_path) == ""


def test_ocupado_defecto_config_inactividad_no_numerica_usa_el_defecto(tmp_path, monkeypatch):
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: True)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: None)
    monkeypatch.setattr(investigar.memoria, "cargar_config", lambda raiz: {"inactividad_minutos": None})
    monkeypatch.setattr(investigar.memoria, "inactivo_minutos", lambda: 2.0)
    assert investigar._ocupado_defecto(tmp_path) == "juego o pantalla completa"


def test_inactividad_minutos_config_valores():
    f = investigar._inactividad_minutos_config
    assert f({"inactividad_minutos": 20}) == 20.0
    assert f({"inactividad_minutos": "20"}) == 20.0
    assert f({"inactividad_minutos": None}) == investigar.INACTIVIDAD_MINUTOS_DEFECTO
    assert f({}) == investigar.INACTIVIDAD_MINUTOS_DEFECTO


def test_aviso_de_carga_py_se_registra_con_ocupado_por_defecto(tmp_path, monkeypatch):
    _preparar(tmp_path)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (None, "no existe carga.py, el PC se considera libre"))
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "")
    hoy = investigar.datetime.now(investigar.timezone.utc).strftime("%Y%m%d")
    lineas = [json.loads(l) for l in
              (tmp_path / "registro" / f"investigar_{hoy}.log").read_text(encoding="utf-8").splitlines()]
    assert {"etapa": "ocupado", "aviso": "no existe carga.py, el PC se considera libre"} in lineas


def test_aviso_de_carga_py_se_registra_cuando_noche_pasa_ocupado_defecto_explicito(tmp_path, monkeypatch):
    """noche.py hace ocupado = ocupado or investigar._ocupado_defecto y lo reenvia: sigue siendo el defecto."""
    _preparar(tmp_path)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (None, "no existe carga.py, el PC se considera libre"))
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "",
                    ocupado=investigar._ocupado_defecto)
    hoy = investigar.datetime.now(investigar.timezone.utc).strftime("%Y%m%d")
    lineas = [json.loads(l) for l in
              (tmp_path / "registro" / f"investigar_{hoy}.log").read_text(encoding="utf-8").splitlines()]
    assert {"etapa": "ocupado", "aviso": "no existe carga.py, el PC se considera libre"} in lineas


def test_sin_aviso_cuando_se_pasa_un_ocupado_propio(tmp_path, monkeypatch):
    _preparar(tmp_path)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (None, "no existe carga.py, el PC se considera libre"))
    monkeypatch.setattr(investigar.agentes, "procesar_lectura", lambda *a, **k: {"leidos": 0, "descartados": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", lambda *a, **k: {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "omitidos": 0, "agotados": 0})
    investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "", ocupado=lambda: "")
    hoy = investigar.datetime.now(investigar.timezone.utc).strftime("%Y%m%d")
    lineas = [json.loads(l) for l in
              (tmp_path / "registro" / f"investigar_{hoy}.log").read_text(encoding="utf-8").splitlines()]
    assert all(l.get("etapa") != "ocupado" or "aviso" not in l for l in lineas)


def test_ocupado_defecto_cualquier_error_no_ocupa(tmp_path, monkeypatch):
    modulo = types.SimpleNamespace(_pantalla_completa=lambda: True)
    monkeypatch.setattr(investigar, "_cargar_carga", lambda: (modulo, ""))
    monkeypatch.setattr(investigar, "_estado_notificacion", lambda: None)
    monkeypatch.setattr(investigar.memoria, "cargar_config", lambda raiz: (_ for _ in ()).throw(OSError("no")))
    assert investigar._ocupado_defecto(tmp_path) == ""


def test_corte_escribe_el_resumen_y_se_propaga(tmp_path, monkeypatch):
    from quant.investigacion import claude_cli
    _preparar(tmp_path)

    def _corta(*a, **k):
        raise claude_cli.CorteClaude("tope")
    monkeypatch.setattr(investigar.agentes, "procesar_fichas", _corta)
    with pytest.raises(claude_cli.CorteClaude):
        investigar.main(["--raiz", str(tmp_path), "--sin-explorar"], llamar=lambda *a, **k: "", ocupado=lambda: "")
    ultimo = json.loads((tmp_path / "registro" / "investigar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["corte"] == "tope" and "lectura" in ultimo
