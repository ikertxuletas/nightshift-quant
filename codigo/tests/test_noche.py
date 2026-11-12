import json
import os
import time
from datetime import datetime, timezone

import pytest

from quant.costes import Costes
from quant.demo import diario as demo
from quant.investigacion import catalogo, contratos, local, noche


@pytest.fixture(autouse=True)
def _claude_falso(monkeypatch):
    monkeypatch.setattr(noche.claude_cli, "comprobar", lambda *a, **k: {"exe": "claude", "sesion": True})

    def prohibido(*a, **k):
        raise AssertionError("la noche no debe tocar Ollama")
    for nombre in ("disponible", "asegurar_servidor", "motor_presente"):
        monkeypatch.setattr(local, nombre, prohibido)


def _etapa(nombre, salida=None, segundos=0.0, reloj=None):
    def etapa(ctx):
        if reloj:
            reloj.t += segundos
        return {"vi": nombre, "minutos": ctx["minutos"], **(salida or {})}
    return etapa


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def tick(self):
        return self.t


def _main(tmp_path, reloj, etapas, extra=()):
    catalogo.abrir(tmp_path / "catalogo.db")
    return noche.main(["--raiz", str(tmp_path), "--fin", "06:00", "--forzar", "--fecha", "20260917", *extra],
                      ahora=datetime(2026, 9, 17, 2, 0), reloj=reloj.tick, dormir=lambda s: None, etapas=etapas)


def test_orden_presupuesto_y_parte(tmp_path):
    reloj = _Reloj()
    vistos = []
    etapas = {n: (lambda n: (lambda ctx: (vistos.append(n), {"minutos": ctx["minutos"]})[1]))(n) for n in noche.ETAPAS}
    assert _main(tmp_path, reloj, etapas) == 0
    assert vistos == list(noche.ETAPAS)
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["fecha"] == "20260917" and parte["corte"] is False and parte["errores"] == 0
    assert parte["etapas"]["precios"]["resultado"]["minutos"] == 30
    assert parte["etapas"]["investigar"]["resultado"]["minutos"] == 110
    assert parte["etapas"]["canario"]["resultado"]["minutos"] == 10
    assert noche.ETAPAS[-1] == "laboratorio"
    assert parte["etapas"]["laboratorio"]["resultado"]["minutos"] == 240
    assert set(parte["etapas"]) == set(noche.ETAPAS) and "catalogo" in parte
    lineas_log = (tmp_path / "registro" / "noche_20260917.log").read_text(encoding="utf-8")
    assert lineas_log.count("\n") == len(noche.ETAPAS)
    assert "ollama" not in parte
    assert parte["claude"]["sesion"] is True and parte["claude"]["llamadas"] == 0
    desde_utc = datetime.fromisoformat(parte["desde"])
    assert desde_utc.tzinfo == timezone.utc
    assert desde_utc == datetime(2026, 9, 17, 2, 0).astimezone(timezone.utc)
    assert sum(noche.RESERVA.values()) <= 240


def test_corte_por_tiempo_salta_etapas_y_respeta_copia(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["investigar"] = _etapa("investigar", segundos=4 * 3600, reloj=reloj)
    assert _main(tmp_path, reloj, etapas) == 0
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["corte"] is True
    assert parte["etapas"]["relator"]["resultado"] == {"omitido": "sin tiempo"}
    assert parte["etapas"]["copia"]["resultado"]["vi"] == "copia"


def test_error_en_una_etapa_no_para_la_noche(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}

    def rompe(ctx):
        raise RuntimeError("boom")
    etapas["relator"] = rompe
    assert _main(tmp_path, reloj, etapas) == 1
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["etapas"]["relator"]["resultado"] == {"error": "RuntimeError: boom"}
    assert parte["etapas"]["mentor"]["resultado"]["vi"] == "mentor" and parte["errores"] == 1


def test_etapa_con_fallo_interno_cuenta_como_error(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["investigar"] = lambda ctx: {"codigo": 1, "errores": 1,
                                        "fallo": "TypeError: cannot use 'list' as a set element"}
    etapas["mentor"] = lambda ctx: {"codigo": 0, "omitido": ""}
    assert _main(tmp_path, reloj, etapas) == 1
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["errores"] == 1


def test_canario_con_fallo_cuenta_como_error(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["canario"] = lambda ctx: {"ok": False, "pasos": {"lector": "operable=no", "formalizador": "no ejecutado",
                                                             "critico": "no ejecutado", "validacion": "no ejecutado"},
                                      "segundos": 0.1, "fallo": "canario: lector: x"}
    assert _main(tmp_path, reloj, etapas) == 1
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["errores"] == 1
    assert contratos.validar_parte(parte) == []












def test_noche_con_motor_no_anade_error(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    assert _main(tmp_path, reloj, etapas) == 0
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["errores"] == 0


def test_etapa_canario_respeta_su_presupuesto(monkeypatch):
    visto = {}
    monkeypatch.setattr(noche.canario, "ejecutar", lambda raiz, **k: visto.update(k) or {"ok": True})
    reloj = lambda: 7.0
    noche._etapa_canario({"raiz": "r", "llamar": None, "hasta": 600.0, "reloj": reloj})
    assert visto["hasta"] == 600.0 and visto["reloj"] is reloj


def test_parte_se_escribe_sin_dejar_temporales(tmp_path):
    reloj = _Reloj()
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    assert not list((tmp_path / "informes").glob("*.tmp"))
    assert json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))["fin_real"]


def test_ocupado_no_se_hereda_entre_etapas(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["investigar"] = lambda ctx: {"vi": "investigar", "motivo": ctx["antes"]()}
    catalogo.abrir(tmp_path / "catalogo.db")
    noche.main(["--raiz", str(tmp_path), "--fin", "06:00", "--forzar", "--fecha", "20260917"],
              ahora=datetime(2026, 9, 17, 2, 0), reloj=reloj.tick, dormir=lambda s: None,
              ocupado=lambda: "juego", etapas=etapas)
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["etapas"]["investigar"]["ocupado"] == "juego"
    assert "ocupado" not in parte["etapas"]["relator"]




def test_solo_el_equipo_elegido(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_EQUIPO", "PRINCIPAL")
    monkeypatch.setenv("COMPUTERNAME", "OTRO")
    codigo = noche.main(["--raiz", str(tmp_path), "--fecha", "20260917"], ahora=datetime(2026, 9, 17, 2, 0),
                        etapas={n: _etapa(n) for n in noche.ETAPAS})
    assert codigo == 2 and not (tmp_path / "informes").exists()


def test_desde_en_ctx_es_utc(tmp_path):
    reloj = _Reloj()
    capturado = {}

    def etapa_mentor(ctx):
        capturado["desde"] = ctx["desde"]
        return {"vi": "mentor"}

    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["mentor"] = etapa_mentor
    catalogo.abrir(tmp_path / "catalogo.db")
    ahora_utc = datetime(2026, 9, 17, 2, 0, tzinfo=timezone.utc)
    noche.main(["--raiz", str(tmp_path), "--fin", "06:00", "--forzar", "--fecha", "20260917"],
              ahora=ahora_utc, reloj=reloj.tick, dormir=lambda s: None, etapas=etapas)
    assert capturado["desde"] == "2026-09-17T02:00:00+00:00"

    reloj2 = _Reloj()
    capturado2 = {}
    etapas2 = {n: _etapa(n) for n in noche.ETAPAS}
    etapas2["mentor"] = lambda ctx: (capturado2.__setitem__("desde", ctx["desde"]), {"vi": "mentor"})[1]
    ahora_local = datetime(2026, 9, 17, 2, 0)
    noche.main(["--raiz", str(tmp_path), "--fin", "06:00", "--forzar", "--fecha", "20260917"],
              ahora=ahora_local, reloj=reloj2.tick, dormir=lambda s: None, etapas=etapas2)
    assert capturado2["desde"] == ahora_local.astimezone(timezone.utc).isoformat(timespec="seconds")


def test_ocupado_llega_a_las_etapas(tmp_path):
    reloj = _Reloj()
    esperas = []
    capturado = {}

    def etapa_investigar(ctx):
        capturado["motivo"] = ctx["antes"]()
        return {"vi": "investigar"}

    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["investigar"] = etapa_investigar
    catalogo.abrir(tmp_path / "catalogo.db")
    codigo = noche.main(["--raiz", str(tmp_path), "--fin", "06:00", "--forzar", "--fecha", "20260917"],
                        ahora=datetime(2026, 9, 17, 2, 0), reloj=reloj.tick, dormir=esperas.append,
                        ocupado=lambda: "juego", etapas=etapas)
    assert codigo == 0 and capturado["motivo"] == "juego" and len(esperas) == 10
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["etapas"]["investigar"]["ocupado"] == "juego"


def test_copiar_a_onedrive(tmp_path, monkeypatch):
    from quant.investigacion import copia
    raiz, destino = tmp_path / "raiz", tmp_path / "onedrive"
    (raiz / "informes").mkdir(parents=True)
    (raiz / "skills" / "lector").mkdir(parents=True)
    (raiz / "datos").mkdir()
    (raiz / "informes" / "a.md").write_text("a", encoding="utf-8")
    (raiz / "skills" / "lector" / "skill.md").write_text("s", encoding="utf-8")
    (raiz / "datos" / "x.parquet").write_bytes(b"0")
    con = catalogo.abrir(raiz / "catalogo.db")
    catalogo.anadir_documento(con, "arxiv", "u://1", "T", "2026-01-01", "t", raiz / "documentos")
    monkeypatch.setenv("OneDrive", str(destino))
    salida = copia.copiar(raiz)
    assert salida["catalogo"] is True and salida["informes"] == 1 and salida["skills"] == 1
    assert (destino / "Quant" / "informes" / "a.md").exists() and not (destino / "Quant" / "datos").exists()
    assert catalogo.abrir(destino / "Quant" / "catalogo.db").execute("SELECT COUNT(*) n FROM documentos").fetchone()["n"] == 1
    monkeypatch.delenv("OneDrive")
    assert copia.copiar(raiz) == {"omitido": "sin OneDrive"}


def test_parte_cumple_el_contrato(tmp_path):
    reloj = _Reloj()
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert contratos.validar_parte(parte) == []
    assert "contrato" not in parte


# A2: el parte incluye lo que memoria.liberar registro esa noche.


def test_parte_incluye_memoria_vacia_si_no_hubo_log(tmp_path):
    reloj = _Reloj()
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["memoria"] == []


def test_parte_incluye_las_lineas_del_log_de_memoria_del_dia(tmp_path):
    reloj = _Reloj()
    registro = tmp_path / "registro"
    registro.mkdir(parents=True)
    linea1 = {"necesario": 5.0, "libre_antes": 1.0, "libre_despues": 3.0,
              "cerrados": [{"nombre": "chrome.exe", "gb": 2.0}], "omitido": "", "hora": "2026-09-17T02:10:00+00:00"}
    linea2 = {"necesario": 5.0, "libre_antes": 1.0, "libre_despues": 1.0,
              "cerrados": [], "omitido": "usuario activo", "hora": "2026-09-17T03:00:00+00:00"}
    (registro / "memoria_20260917.log").write_text(
        json.dumps(linea1) + "\n" + json.dumps(linea2) + "\n", encoding="utf-8")
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["memoria"] == [linea1, linea2]
    assert contratos.validar_parte(parte) == []


def test_noche_deja_copia_real(tmp_path):
    reloj = _Reloj()
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    copia = tmp_path / "codigo" / "tests" / "reales" / "parte_20260917.json"
    assert copia.exists()


def test_guardar_real_roto_no_cambia_el_codigo_de_salida(tmp_path, monkeypatch):
    monkeypatch.setattr(contratos, "guardar_real", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    reloj = _Reloj()
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0


def test_main_restaura_huerfanas_al_arrancar(tmp_path):
    reloj = _Reloj()
    skill = tmp_path / "skills" / "critico"
    skill.mkdir(parents=True)
    ruta = skill / "skill.md"
    ruta.write_text("skill original", encoding="utf-8")
    original = ruta.read_bytes()
    historial = skill / "historial"
    historial.mkdir(parents=True, exist_ok=True)
    copia = historial / "20260916_061500_skill.md"
    copia.write_bytes(original)
    (historial / "20260916_061500_skill.md.pendiente").write_text(
        '{"agente": "critico", "fichero": "skill.md", "motivo": "m"}', encoding="utf-8")
    ruta.write_text("texto sin evaluar", encoding="utf-8")
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    assert ruta.read_bytes() == original
    assert list(historial.glob("*.pendiente")) == []
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert parte["restauradas"] == [{"agente": "critico", "fichero": "skill.md", "copia": str(copia)}]


def test_parte_fuera_de_contrato_se_escribe_y_cuenta(tmp_path):
    reloj = _Reloj()
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["investigar"] = lambda ctx: ["lista"]
    codigo = _main(tmp_path, reloj, etapas)
    assert codigo == 1
    parte = json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))
    assert any(e.startswith("etapas.investigar.resultado:") for e in parte["contrato"])
    assert parte["errores"] >= 1



CON_MODELO = ("investigar", "canario", "relator", "mentor")


def _parte(tmp_path):
    return json.loads((tmp_path / "informes" / "parte_20260917.json").read_text(encoding="utf-8"))


def test_sin_etapa_ollama(tmp_path):
    reloj = _Reloj()
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    log = (tmp_path / "registro" / "noche_20260917.log").read_text(encoding="utf-8")
    assert '"etapa": "ollama"' not in log


def test_corte_omite_siguientes(tmp_path):
    reloj = _Reloj()
    vistos = []

    def investigar(ctx):
        vistos.append("investigar")
        raise noche.claude_cli.CorteClaude("tope")
    etapas = {n: (lambda n: (lambda ctx: (vistos.append(n), {"vi": n})[1]))(n) for n in noche.ETAPAS}
    etapas["investigar"] = investigar
    assert _main(tmp_path, reloj, etapas) == 0
    parte = _parte(tmp_path)
    for n in CON_MODELO:
        assert parte["etapas"][n]["resultado"] == {"omitido": "tope de llamadas alcanzado"}, n
    assert vistos == ["precios", "investigar", "demo", "copia"]
    assert parte["errores"] == 0


def test_limite_de_uso_omite_con_su_motivo(tmp_path):
    reloj = _Reloj()

    def canario(ctx):
        raise noche.claude_cli.CorteClaude("limite")
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    etapas["canario"] = canario
    assert _main(tmp_path, reloj, etapas) == 0
    parte = _parte(tmp_path)
    assert parte["etapas"]["investigar"]["resultado"]["vi"] == "investigar"
    for n in ("canario", "relator", "mentor"):
        assert parte["etapas"][n]["resultado"] == {"omitido": "limite de uso de la suscripcion"}, n


def test_sesion_caducada(tmp_path, monkeypatch):
    reloj = _Reloj()
    monkeypatch.setattr(noche.claude_cli, "comprobar",
                        lambda *a, **k: {"exe": "claude", "sesion": False, "error": "Please run /login"})
    vistos = []
    etapas = {n: (lambda n: (lambda ctx: (vistos.append(n), {"vi": n})[1]))(n) for n in noche.ETAPAS}
    assert _main(tmp_path, reloj, etapas) == 1
    parte = _parte(tmp_path)
    assert parte["errores"] == 1 and parte["claude"]["sesion"] is False
    for n in CON_MODELO:
        assert parte["etapas"][n]["resultado"] == {"omitido": "sesion de claude caducada"}, n
    assert vistos == ["precios", "demo", "copia"]


def test_tope_sale_de_la_config(tmp_path, monkeypatch):
    reloj = _Reloj()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agentes.json").write_text('{"_tope_llamadas_noche": 7}', encoding="utf-8")
    vistos = []
    monkeypatch.setattr(noche.claude_cli, "reiniciar", lambda tope: vistos.append(tope))
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 0
    assert vistos == [7]


def test_motivo_segun_la_causa_de_la_comprobacion(tmp_path, monkeypatch):
    reloj = _Reloj()
    monkeypatch.setattr(noche.claude_cli, "comprobar",
                        lambda *a, **k: {"exe": "claude", "sesion": False, "causa": "fallo", "error": "red"})
    assert _main(tmp_path, reloj, {n: _etapa(n) for n in noche.ETAPAS}) == 1
    assert _parte(tmp_path)["etapas"]["investigar"]["resultado"] == {"omitido": "claude no responde"}


def _precios_argv(tmp_path, monkeypatch):
    visto = []
    monkeypatch.setattr(noche.actualizar, "main", lambda argv, **k: visto.append(argv) or 0)
    noche._etapa_precios({"raiz": tmp_path, "minutos": 30, "reloj": None})
    return visto[0]


def test_precios_passes_demo_instruments_as_critical(tmp_path, monkeypatch):
    con = catalogo.abrir(tmp_path / "catalogo.db")
    demo.ensure_schema(con)
    for i, (inst, status) in enumerate([("US500", "active"), ("EURUSD", "active"), ("US500", "active"), ("XAUUSD", "retired")]):
        con.execute("INSERT INTO demo_strategies(id, instrument, status) VALUES (?,?,?)", (i, inst, status))
    con.commit()
    con.close()
    argv = _precios_argv(tmp_path, monkeypatch)
    assert argv[argv.index("--criticos") + 1:] == ["EURUSD", "US500"]


def test_precios_without_demo_instruments_has_no_criticos(tmp_path, monkeypatch):
    assert "--criticos" not in _precios_argv(tmp_path, monkeypatch)


def _demo_env(tmp_path, monkeypatch, fracs=None):
    con = catalogo.abrir(tmp_path / "catalogo.db")
    demo.ensure_schema(con)
    for sid, label in ((1, "en_prueba"), (2, "en_prueba"), (3, "control")):
        con.execute("INSERT INTO demo_strategies(id,instrument,status,capital,added,label,ficha_json) "
                    "VALUES (?,?,?,?,?,?,?)", (sid, "US500", "active", 1000, "2026-09-01T00:00:00", label, "{}"))
    for _ in range(10):
        con.execute("INSERT INTO demo_trades(strategy_id,units,entry,exit,pnl,costs) VALUES(1,1,100,100,-100,0)")
        con.execute("INSERT INTO demo_trades(strategy_id,units,entry,exit,pnl,costs) VALUES(2,1,100,100,8,0)")
        con.execute("INSERT INTO demo_trades(strategy_id,units,entry,exit,pnl,costs) VALUES(3,1,100,100,-100,0)")
    con.commit()
    con.close()
    llamadas = []
    monkeypatch.setattr(noche, "_backtest_fractions", lambda s, ctx: [0.01, -0.005, 0.008, -0.004, 0.006] * 10)
    monkeypatch.setattr(noche.seleccion, "select", lambda con, cfg: llamadas.append("select") or ["x"])
    monkeypatch.setattr(noche.seleccion, "apply", lambda con, chosen, now, cfg: llamadas.append(("apply", chosen)))
    return llamadas


def _ctx_demo(tmp_path, ahora):
    return {"raiz": tmp_path, "con": catalogo.abrir(tmp_path / "catalogo.db"), "ahora": ahora,
            "costes_of": lambda inst: Costes(broker="p", clase="indice", spread_pct=0.0, comision_pct=0.0,
                                             deslizamiento_pct=0.0, swap_pct_anual=0.0, apalancamiento=100.0,
                                             permite_corto=True)}


def test_demo_stage_runs_drift_daily_and_rotation_on_monday(tmp_path, monkeypatch):
    llamadas = _demo_env(tmp_path, monkeypatch)
    ctx = _ctx_demo(tmp_path, datetime(2026, 11, 3, 2, 0))
    assert noche._etapa_demo(ctx) == {"evaluated": 3, "retired": 1, "rotated": False, "skipped": []}
    assert llamadas == []
    row = ctx["con"].execute("SELECT status, retired, retire_reason_es FROM demo_strategies WHERE id=1").fetchone()
    assert row[0] == "retired" and row[1] and "por debajo" in row[2]
    assert ctx["con"].execute("SELECT status FROM demo_strategies WHERE id=3").fetchone()[0] == "active"
    ev = ctx["con"].execute("SELECT kind, strategy_id FROM demo_events").fetchall()
    assert [tuple(e) for e in ev] == [("retire", 1)]
    ctx["ahora"] = datetime(2026, 11, 2, 2, 0)
    res = noche._etapa_demo(ctx)
    assert res["rotated"] is True and res["retired"] == 0
    assert llamadas == ["select", ("apply", ["x"])]


def test_demo_stage_skips_strategy_without_data(tmp_path, monkeypatch):
    _demo_env(tmp_path, monkeypatch)

    def sin_datos(s, ctx):
        if s["id"] == 1:
            raise noche.datos.ErrorDatos("pendiente de datos: US500 D1")
        return [0.001] * 5
    monkeypatch.setattr(noche, "_backtest_fractions", sin_datos)
    res = noche._etapa_demo(_ctx_demo(tmp_path, datetime(2026, 11, 3, 2, 0)))
    assert res["evaluated"] == 2 and res["retired"] == 0 and len(res["skipped"]) == 1
    assert "1" in res["skipped"][0] and "pendiente de datos" in res["skipped"][0]
    assert not contratos.hay_fallo(res)


def test_demo_stage_warns_when_every_strategy_is_skipped(tmp_path, monkeypatch):
    _demo_env(tmp_path, monkeypatch)

    def sin_datos(s, ctx):
        raise noche.datos.ErrorDatos("pendiente de datos")
    monkeypatch.setattr(noche, "_backtest_fractions", sin_datos)
    res = noche._etapa_demo(_ctx_demo(tmp_path, datetime(2026, 11, 3, 2, 0)))
    assert res["evaluated"] == 0 and len(res["skipped"]) == 3 and "Ninguna estrategia" in res["aviso"]
    assert not contratos.hay_fallo(res)


def test_demo_stage_stamps_utc_naive(tmp_path, monkeypatch):
    _demo_env(tmp_path, monkeypatch)
    ctx = _ctx_demo(tmp_path, datetime(2026, 11, 3, 2, 0))
    noche._etapa_demo(ctx)
    esperado = datetime(2026, 11, 3, 2, 0).astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    assert ctx["con"].execute("SELECT retired FROM demo_strategies WHERE id=1").fetchone()[0] == esperado


def test_laboratorio_tiene_reserva_y_necesita_modelo():
    assert noche.RESERVA["laboratorio"] == 30 and noche.RESERVA["investigar"] == 110
    assert "laboratorio" in noche.CON_MODELO and "laboratorio" in noche.ETAPAS_REALES


def test_etapa_laboratorio_pasa_tiempo_y_llamada(monkeypatch):
    from quant.investigacion import laboratorio
    visto = {}
    monkeypatch.setattr(laboratorio, "tandas", lambda con, raiz, llamar, hasta, reloj: visto.update(
        con=con, raiz=raiz, llamar=llamar, hasta=hasta) or {"probados": 0})
    from quant.panel import precalcular
    monkeypatch.setattr(precalcular, "precalcular_lab", lambda con, raiz, minutos, hasta, reloj: {"hechas": 1, "hasta": hasta})
    f = lambda *a, **k: "{}"
    out = noche.ETAPAS_REALES["laboratorio"]({"con": "C", "raiz": "R", "llamar": f, "hasta": 9.0, "reloj": time.monotonic})
    assert out == {"probados": 0, "panel": {"hechas": 1, "hasta": 9.0}} and visto == {"con": "C", "raiz": "R", "llamar": f, "hasta": 9.0}


def test_etapa_laboratorio_aguanta_que_falle_el_panel(monkeypatch):
    from quant.investigacion import laboratorio
    from quant.panel import precalcular
    monkeypatch.setattr(laboratorio, "tandas", lambda con, raiz, llamar, hasta, reloj: {"probados": 3})
    def falla(*a, **k):
        raise OSError("sin disco")
    monkeypatch.setattr(precalcular, "precalcular_lab", falla)
    out = noche.ETAPAS_REALES["laboratorio"]({"con": "C", "raiz": "R", "llamar": None, "hasta": 9.0, "reloj": time.monotonic})
    assert out == {"probados": 3, "panel": {"error": "OSError: sin disco"}}


def test_en_invierno_la_noche_acaba_4_horas_despues_de_empezar(tmp_path):
    # The task trigger is fixed in CET: 01:00 in winter, so 06:00 would overrun the 4h30 task limit (05:30).
    catalogo.abrir(tmp_path / "catalogo.db")
    etapas = {n: _etapa(n) for n in noche.ETAPAS}
    assert noche.main(["--raiz", str(tmp_path), "--fin", "06:00", "--forzar", "--fecha", "20261105"],
                      ahora=datetime(2026, 11, 5, 1, 0), reloj=_Reloj().tick, dormir=lambda s: None, etapas=etapas) == 0
    parte = json.loads((tmp_path / "informes" / "parte_20261105.json").read_text(encoding="utf-8"))
    assert parte["fin_previsto"] == "2026-11-05T05:00:00"
    assert parte["etapas"]["laboratorio"]["resultado"]["minutos"] == 240
