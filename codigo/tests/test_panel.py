import http.client
import re
import json
import threading
from datetime import datetime, timedelta

import numpy as np
import pytest

from quant import barrido
from quant.demo import diario
from quant.investigacion import catalogo
from quant.panel import paginas, servidor

TITLE = "<script>alert(1)</script>"


def _stats():
    import numpy as np
    from quant.panel import ficha_stats
    ts = np.arange(np.datetime64("2021-01-01"), np.datetime64("2026-11-01")).astype("datetime64[ns]")
    eq = 10000 * (1 + np.sin(np.arange(len(ts)) / 90) * 0.05 + np.arange(len(ts)) / 4000)
    return ficha_stats.estadisticas(ts, eq, [], 10000.0)


STATS = _stats()
IDS = {}
UNI = {"instrumentos": {
    "AAA": {"clase": "indice", "fuente": "yahoo", "simbolo": "AAA", "desde": "2010-01-01"},
    "BBB": {"clase": "forex", "fuente": "yahoo", "simbolo": "BBB", "desde": "2010-01-01"}}}
CRITERIA = [{"criterio": "drawdown", "valor": 0.1, "umbral": 0.3, "sentido": "max", "cumple": True, "distancia": -0.6},
            {"criterio": "robustez", "valor": 0.2, "umbral": 0.6, "sentido": "min", "cumple": False, "distancia": 0.6}]


def add(con, instrument, verdict, sharpe, family="cruce_medias", title="t"):
    res = {"veredicto": verdict, "criterios": CRITERIA,
           "metricas": {"total": {"drawdown": 0.1, "cagr": 0.2, "operaciones": 50, "sharpe": 1.0,
                                  "rentabilidad": 0.4567, "acierto": 0.3154, "profit_factor": 1.925},
                        "dentro": {"sharpe": 1.2}, "fuera": {"sharpe": sharpe}}}
    ficha = {"titulo": title, "universo": {"instrumentos": [instrument], "plazo": "D1"}, "forma": "serie_temporal"}
    fid = con.execute("INSERT INTO fichas (json, estado) VALUES (?, 'generada')", (json.dumps(ficha),)).lastrowid
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json) VALUES (?, ?, ?, ?)",
                (fid, instrument, verdict, json.dumps(res)))
    return con.execute(
        "INSERT INTO combinations (fingerprint, family, params_json, instruments_json, timeframe, filter, ficha_id,"
        " data_until) VALUES (?, ?, ?, ?, 'D1', 'sin_filtro', ?, '2026-11-01')",
        (f"{instrument}{verdict}{title}", family, json.dumps({"n": 1}), json.dumps([instrument]), fid)).lastrowid


@pytest.fixture
def raiz(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "universo.json").write_text(json.dumps(UNI), encoding="utf-8")
    (tmp_path / "registro").mkdir()
    (tmp_path / "registro" / "barrido_ultimo.json").write_text(json.dumps({"tested": 7, "stopped": "max"}))
    con = catalogo.abrir(tmp_path / "catalogo.db")
    barrido.ensure_schema(con)
    diario.ensure_schema(con)
    IDS.update(evil=add(con, "AAA", "pasa", 1.5, title=TITLE), fx=add(con, "BBB", "no_pasa", 0.1, title="x"))
    con.commit()
    con.close()
    return tmp_path


@pytest.fixture
def server(raiz, monkeypatch):
    monkeypatch.setattr(paginas, "backtest_view", lambda raiz, ficha, instrument: (
        [[1700000000, 10000.0], [1700086400, 10100.0]], [0.03, -0.01, 0.05, -0.02], STATS))
    httpd, key = servidor.make_server(raiz, port=0, sistema={"tareas": {}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, key, raiz
    httpd.shutdown()
    httpd.server_close()


def get(httpd, path, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
    c.request("GET", path, headers={"Cookie": cookie} if cookie else {})
    r = c.getresponse()
    body = r.read().decode("utf-8")
    return r.status, r, body


def test_binds_localhost_only(server):
    httpd, key, raiz = server
    assert httpd.server_address[0] == "127.0.0.1"
    assert (raiz / "registro" / "panel_clave").read_text().strip() == key


def test_no_key_returns_403(server):
    httpd, key, _ = server
    for path in ("/", "/ranking", "/static/panel.css", "/?key=wrong"):
        status, _, body = get(httpd, path)
        assert status == 403 and "AAA" not in body and "cruce" not in body
    assert get(httpd, "/ranking", cookie="panel=wrong")[0] == 403


def test_key_sets_cookie_then_pages_200(server):
    httpd, key, _ = server
    status, resp, _ = get(httpd, f"/?key={key}")
    cookie = resp.getheader("Set-Cookie")
    assert status == 200 and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert get(httpd, "/ranking", cookie=cookie.split(";")[0])[0] == 200


def test_all_tabs_render(server):
    httpd, key, raiz = server
    ck = f"panel={key}"
    for path in ("/", "/ranking", "/glosario", "/static/panel.css",
                 "/static/lightweight-charts.standalone.production.js", "/static/logo.svg"):
        assert get(httpd, path, ck)[0] == 200, path
    assert get(httpd, "/estrategia/999999", ck)[0] == 404
    assert get(httpd, "/static/../servidor.py", ck)[0] == 404
    _, _, body = get(httpd, "/glosario", ck)
    assert "Sharpe" in body and "percentil 5" in body.lower()


def test_db_text_is_escaped(server):
    httpd, key, raiz = server
    status, _, body = get(httpd, f"/estrategia/{IDS['evil']}", f"panel={key}")
    assert status == 200 and "<script>alert(1)" not in body


def test_ranking_filters_apply(server):
    httpd, key, _ = server
    ck = f"panel={key}"
    _, _, body = get(httpd, "/ranking", ck)
    assert "AAA" in body and "BBB" in body
    _, _, body = get(httpd, "/ranking?veredicto=pasa", ck)
    assert "AAA" in body and "BBB" not in body
    _, _, body = get(httpd, "/ranking?mercado=forex", ck)
    assert "BBB" in body and "AAA" not in body


def test_strategy_page_has_criteria_and_chart_data(server):
    httpd, key, raiz = server
    _, _, body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    assert "La peor caída no pasa del 30 %" in body and "✓" in body and "✗" in body
    assert "1700086400" in body and "10100" in body
    assert "Fuera de muestra" in body


def test_today_without_parte_is_red_and_says_why(server):
    httpd, key, raiz = server
    _, _, body = get(httpd, "/", f"panel={key}")
    assert "Algo falló" in body and "No hay parte de la noche en las últimas 26 horas." in body and "Aún no hay" in body


def test_non_ascii_key_is_denied(server):
    httpd, _, _ = server
    assert get(httpd, "/?key=%C3%B1")[0] == 403
    assert get(httpd, "/", cookie="panel=\xf1")[0] == 403


def test_static_rejects_drive_relative_escape(server, tmp_path, monkeypatch):
    import os
    httpd, key, _ = server
    drive = os.path.splitdrive(str(tmp_path))[0]
    if not drive or drive.lower() == os.path.splitdrive(str(servidor.STATIC))[0].lower():
        pytest.skip("needs tmp_path on a different drive than the panel")
    (tmp_path / "secreto.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    assert get(httpd, f"/static/{drive}secreto.txt?key={key}")[0] == 404


def test_trade_stats_values():
    st = paginas.trade_stats([0.03, -0.01, 0.05, -0.02])
    assert (st["n"], st["wins"], st["losses"], st["win_rate"]) == (4, 2, 2, 0.5)
    assert st["mean"] == pytest.approx(0.0125)
    assert (st["avg_win"], st["max_win"]) == (pytest.approx(0.04), 0.05)
    assert (st["avg_loss"], st["max_loss"]) == (pytest.approx(-0.015), -0.02)
    assert st["profit_factor"] == pytest.approx(8 / 3)
    assert paginas.trade_stats([]) is None
    only_wins = paginas.trade_stats([0.01])
    assert only_wins["max_loss"] is None and only_wins["profit_factor"] is None


def test_strategy_page_shows_trade_stats(server):
    httpd, key, _ = server
    _, _, body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    assert "Ganadoras / perdedoras" in body and "2 / 2" in body
    assert "+1,25 %" in body and "+5,00 %" in body and "−2,00 %" in body


def test_ranking_shows_return_win_rate_profit_factor(server):
    httpd, key, _ = server
    _, _, body = get(httpd, "/ranking", f"panel={key}")
    assert "Rentabilidad total" in body and "+45,7 %" in body and "32 %" in body and "1,93" in body


def test_ranking_cache_refreshes_when_catalog_changes(server):
    httpd, key, raiz = server
    ck = f"panel={key}"
    assert "CCC" not in get(httpd, "/ranking", ck)[2]
    con = catalogo.abrir(raiz / "catalogo.db")
    add(con, "CCC", "pasa", 2.0, title="nueva")
    con.commit()
    con.close()
    assert "CCC" in get(httpd, "/ranking", ck)[2]


def request(httpd, method, path, cookie=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    headers = {"Cookie": cookie} if cookie else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body, headers)
    r = conn.getresponse()
    out = r.status, dict(r.getheaders()), r.read().decode("utf-8")
    conn.close()
    return out
def test_post_is_rejected(server):
    httpd, key, _ = server
    assert request(httpd, "POST", "/ranking", f"panel={key}", body="{}")[0] == 405
def test_ranking_dropdown_hides_own_strategies(server):
    httpd, key, _ = server
    _, _, body = get(httpd, "/ranking", f"panel={key}")
    assert 'value="cruce_medias"' in body and 'value="ejemplo"' not in body


def _lab(raiz, motivo="stop mas ancho", retirada=False):
    from quant.familias import propias
    from quant.investigacion import laboratorio as lab
    con = catalogo.abrir(raiz / "catalogo.db")
    lab.ensure_schema(con)
    base = propias.ficha_base("ejemplo")
    entreno = {"veredicto": "pasa", "criterios": [], "metricas": {"total": {"profit_factor": 1.21, "drawdown": 0.12,
                                                                            "operaciones": 300}}}
    examen = {"profit_factor": 1.33, "rentabilidad": 0.2, "drawdown": 0.08, "operaciones": 90}
    eid = con.execute(
        "INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, entreno_json,"
        " examen_json, confirmacion_json, umbral_pf, creado) VALUES ('ejemplo', '2026-11-04', 'h1', ?, ?, 1,"
        " 'ganadora', ?, ?, ?, 1.05, '2026-11-04T01:00:00+00:00')",
        (json.dumps(base), motivo, json.dumps(entreno), json.dumps(examen), json.dumps(examen))).lastrowid
    con.execute("INSERT INTO lab_ganadoras (experimento_id, estrategia, fijada, estado, umbral_pf, examen_json,"
                " ayer_json, retirada, motivo_retiro) VALUES (?, 'ejemplo', '2026-11-04', ?, 1.05, ?, ?, ?, ?)",
                (eid, "retirada" if retirada else "vigente", json.dumps(examen),
                 json.dumps({"fecha": "2026-11-03", "operaciones": [{"pnl": 4.2}]}),
                 "2026-11-05" if retirada else None, "profit factor 0,80 por debajo de 1,05" if retirada else None))
    con.commit()
    con.close()
    return eid


def test_hoy_is_the_first_tab_and_propias_waits_for_the_lab(server):
    httpd, key, _ = server
    _, _, body = get(httpd, "/", f"panel={key}")
    nav = body[body.index('class="pestanas"'):]
    assert nav.index('href="/"') < nav.index('href="/demo"') < nav.index('href="/ranking"')
    status, _, body = get(httpd, "/propias", f"panel={key}")
    assert status == 200 and "El laboratorio aún no ha corrido" in body


def test_propias_lists_experiments_and_winners_escaped(server):
    httpd, key, raiz = server
    eid = _lab(raiz, motivo="<script>x</script>")
    _, _, body = get(httpd, "/propias?estrategia=ejemplo", f"panel={key}")
    assert "&lt;script&gt;x" in body and "<script>x" not in body
    assert "Ganadora" in body and "vigente" in body and f'href="/propias/{eid}"' in body
    status, _, body = get(httpd, f"/propias/{eid}", f"panel={key}")
    assert status == 200 and "&lt;script&gt;x" in body and "Operaciones del backtest" in body
    assert get(httpd, "/propias/999", f"panel={key}")[0] == 404


def test_propias_shows_retired_winner_with_reason(server):
    httpd, key, raiz = server
    _lab(raiz, retirada=True)
    _, _, body = get(httpd, "/propias?estrategia=ejemplo", f"panel={key}")
    assert "Retirada" in body and "profit factor 0,80 por debajo de 1,05" in body


def test_propias_survives_null_exam_json(server):
    httpd, key, raiz = server
    _lab(raiz)
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("UPDATE lab_ganadoras SET examen_json = 'null', confirmacion_json = 'null'")
    con.commit()
    con.close()
    assert get(httpd, "/propias", f"panel={key}")[0] == 200


def test_strategy_page_explains_period_annual_return_months_and_score(server):
    httpd, key, _ = server
    _, _, body = get(httpd, f"/estrategia/{IDS['evil']}", f"panel={key}")
    for texto in ("Rentabilidad anual", "Periodo estudiado", "5,8 años", "2021-01-01", "Cómo se ha probado",
                  "Rentabilidad por año", "Rentabilidad por mes", "Nota Quant", "de dónde sale el",
                  "La peor caída no pasa del 30 %", "Mejor mes"):
        assert texto in body, texto
    assert body.count('<tr><th scope="row">') == 3 + 6 and "Últimos 3 años" in body and 'style="' not in body
    _, _, body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    assert "Sin nota: solo la tienen las que pasan o casi." in body


def test_ranking_shows_quant_score_sorted_and_filtered(server):
    httpd, key, raiz = server
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("CREATE TABLE IF NOT EXISTS panel_stats (resultado_id INTEGER PRIMARY KEY, stats_json TEXT,"
                " nota_json TEXT, creado TEXT)")
    otro = add(con, "CCC", "pasa", 0.2, title="otra")
    rid = {r[0]: r[1] for r in con.execute("SELECT c.id, r.id FROM combinations c JOIN resultados r ON r.ficha_id = c.ficha_id")}
    attrs = [{"clave": "riesgo", "nombre": "Riesgo", "valor": 9.0, "por_que": "x"}] * 8
    con.execute("INSERT INTO panel_stats VALUES (?, ?, ?, 'x')",
                (rid[otro], json.dumps(STATS), json.dumps({"nota": 88, "atributos": attrs})))
    con.execute("INSERT INTO panel_stats VALUES (?, ?, ?, 'x')",
                (rid[IDS["evil"]], json.dumps(STATS), json.dumps({"nota": 41, "atributos": attrs})))
    con.commit()
    con.close()
    _, _, body = get(httpd, "/ranking", f"panel={key}")
    assert "La nota Quant" in body and ">88<" in body and ">41<" in body and body.index(">88<") < body.index(">41<")
    assert 'class="circulo nota-0"' in body and "5,8 años" in body and 'style="' not in body
    _, _, body = get(httpd, "/ranking?nota=60", f"panel={key}")
    assert ">88<" in body and ">41<" not in body and 'class="circulo nota-0"' not in body


def test_sweep_strategy_figures_match_the_ranking(server):
    httpd, key, _ = server
    _, _, body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    assert "+46 %" in body and "+20,0 %" in body and "−10,0 %" in body
PARTE = {"fecha": "20261104", "inicio": "2026-11-04T02:00:00", "errores": 0, "etapas": {
    "precios": {"segundos": 1706, "resultado": {"codigo": 0, "instrumentos": [{"instrumento": "X", "error": None}] * 5
                                                 + [{"instrumento": "PSKY", "error": "descarga sospechosa"}], "errores": 1}},
    "investigar": {"segundos": 382, "resultado": {"codigo": 0, "lectura": {"leidos": 2, "descartados": 18},
                                                  "fichas": {"aprobadas": 1}, "validadas": 1}},
    "demo": {"segundos": 5, "resultado": {"evaluated": 7, "retired": 0}},
    "laboratorio": {"segundos": 900, "resultado": {"probados": 10, "ganadoras": 0, "errores": []}},
    "mentor": {"segundos": 8, "resultado": {"omitido": "sin modelo"}}}}


def _parte(raiz, fecha="20261104", parte=PARTE):
    (raiz / "informes").mkdir(exist_ok=True)
    (raiz / "informes" / f"parte_{fecha}.json").write_text(json.dumps({**parte, "fecha": fecha}), encoding="utf-8")


def test_today_tells_what_happened_last_night(server):
    httpd, key, raiz = server
    _parte(raiz)
    paginas._SISTEMA_CACHE.clear()
    _, _, body = get(httpd, "/", f"panel={key}")
    for texto in ("Anoche", "10 experimentos", "Leyó 20 documentos", "Precios, demo y copia de seguridad, sin problemas.",
                  "Lo próximo", 'href="#sistema"'):
        assert texto in body, texto
    assert 'style="' not in body


def test_sistema_shows_night_grid_errors_and_tasks(raiz):
    _parte(raiz, "20261103", {**PARTE, "etapas": {"precios": {"segundos": 10, "resultado": {"codigo": 1}}}})
    _parte(raiz)
    paginas._SISTEMA_CACHE.clear()
    httpd, key = servidor.make_server(raiz, port=0, sistema={"tareas": {"Quant_Noche": {"estado": "Ready", "ultima": "2026-11-04T02:00:00"}}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        _, _, body = get(httpd, "/", f"panel={key}")
        assert "Últimas 7 noches" in body and "3-nov" in body and "4-nov" in body
        assert 'class="dot-r"' in body and 'class="dot-v"' in body and "Tareas programadas" in body
        assert "Noche" in body and "4 nov, 02:00" in body and 'style="' not in body
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_glossary_has_groups_examples_and_search(server):
    httpd, key, _ = server
    _, _, body = get(httpd, "/glosario", f"panel={key}")
    for texto in ("Rentabilidad", "Riesgo", "Validación", "Demo", "Laboratorio", "Profit factor", "Nota Quant",
                  "Examen final", "En Quant", 'type="search"'):
        assert texto in body, texto


def test_experimento_vuelve_a_su_estrategia(server):
    httpd, key, raiz = server
    eid = _lab(raiz)
    _, _, body = get(httpd, f"/propias/{eid}", f"panel={key}")
    assert 'href="/propias?estrategia=ejemplo"' in body


def test_propias_muestra_la_tarjeta_del_asesor(server):
    httpd, key, raiz = server
    _lab(raiz)
    con = catalogo.abrir(raiz / "catalogo.db")
    for fecha, informe in (("2026-11-08", "informe viejo"), ("2026-11-15", "<b>x</b>")):
        con.execute("INSERT INTO lab_asesor (estrategia, fecha, informe, direccion, direccion_es, propuestas_json, creado)"
                    " VALUES ('ejemplo', ?, ?, 'Try slower Hull', 'Probar una Hull más lenta', ?, 'x')",
                    (fecha, informe, json.dumps([{"que": "Indicador ADX", "motivo": "fuerza de tendencia"}])))
    con.commit()
    con.close()
    _, _, body = get(httpd, "/propias?estrategia=ejemplo", f"panel={key}")
    assert "2026-11-15" in body and "Probar una Hull más lenta" in body and "Indicador ADX" in body
    assert "&lt;b&gt;x" in body and "<b>x" not in body and "informe viejo" in body
    assert 'class="informe"' in body


def _hoy_body(raiz):
    paginas._SISTEMA_CACHE.clear()
    httpd, key = servidor.make_server(raiz, port=0, sistema={"tareas": {}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        return get(httpd, "/", f"panel={key}")[2]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_sistema_muestra_las_pruebas(raiz):
    (raiz / "registro" / "pruebas.json").write_text(json.dumps(
        {"fecha": "2026-11-11T14:05:00", "total": 1174, "pasan": 1172, "fallan": 2, "omitidas": 0, "esperadas": 0,
         "segundos": 48.2, "fallos": ["tests/test_x.py::test_<b>uno</b>", "tests/test_y.py::test_dos"]}), encoding="utf-8")
    body = _hoy_body(raiz)
    assert "Pruebas del programa" in body and "1172 de 1174" in body and "11/11/2026 14:05" in body
    assert "2 fallan" in body and "test_&lt;b&gt;uno" in body and "test_dos" in body and 'style="' not in body


def test_sistema_pruebas_todo_bien_y_sin_fichero(raiz):
    body = _hoy_body(raiz)
    assert "Pruebas del programa" in body and "Aún no se han ejecutado todas las pruebas" in body
    (raiz / "registro" / "pruebas.json").write_text(json.dumps(
        {"fecha": "2026-11-11T14:05:00", "total": 10, "pasan": 10, "fallan": 0, "omitidas": 0, "esperadas": 0,
         "segundos": 3, "fallos": []}), encoding="utf-8")
    body = _hoy_body(raiz)
    assert "10 de 10" in body and "fallan" not in body


def test_hoy_abiertas_escapa_y_muestra_la_ultima_revision(server_con_demo):
    httpd, key, raiz = server_con_demo
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("INSERT INTO demo_paper_positions VALUES (2, '<BTC>', -1, 0.01, 74000.0, NULL, NULL, '2026-11-11T22:00:00.000000000')")
    con.execute("INSERT INTO demo_state VALUES ('last_bar:1', '2026-11-11T00:00:00')")
    con.commit()
    con.close()
    paginas._HOY_CACHE.clear()
    _, _, body = get(httpd, "/", f"panel={key}")
    assert "&lt;BTC&gt;" in body and "<BTC>" not in body and "+20,00 €" in body
    assert "Último precio usado: 12/11/2026 00:00" in body and 'style="' not in body


def test_hoy_sin_posiciones_abiertas(server):
    httpd, key, raiz = server
    _, _, body = get(httpd, "/", f"panel={key}")
    assert "Posiciones abiertas" in body and "No hay posiciones abiertas" in body


def test_cabecera_nueva_en_todas_las_paginas(server):
    httpd, key, raiz = server
    for ruta in ("/", "/ranking", "/propias", "/glosario"):
        body = get(httpd, ruta, f"panel={key}")[2]
        assert 'class="arriba"' in body and "Actualizado a las" in body and 'href="/sistema"' not in body
        assert 'style="' not in body


def test_css_tiene_la_paleta_marquina(server):
    httpd, key, raiz = server
    css = get(httpd, "/static/panel.css", f"panel={key}")[2]
    for v in ("#131518", "#1B1E23", "#E9EBEE", "#3CC796", "#F2727A", "prefers-reduced-motion", "overflow-x:clip"):
        assert v in css


def test_la_letra_se_sirve_desde_static(server):
    httpd, key, raiz = server
    status, resp, _ = get(httpd, "/static/fonts/OFL.txt", f"panel={key}")
    assert status == 200
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
    c.request("GET", "/static/fonts/Geist-Variable.woff2", headers={"Cookie": f"panel={key}"})
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type") == "font/woff2" and r.read()[:4] == b"wOF2"
    assert get(httpd, "/static/fonts/../../servidor.py", f"panel={key}")[0] == 404


def _demo(raiz):
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("CREATE TABLE IF NOT EXISTS demo_paper_positions(strategy_id INTEGER PRIMARY KEY, instrument TEXT,"
                " side INTEGER, units REAL, entry_price REAL, stop REAL, target REAL, last_checked TEXT)")
    con.executemany("INSERT INTO demo_strategies (id, instrument, timeframe, label, status, capital, added)"
                    " VALUES (?, ?, 'D1', ?, 'active', 500, '2026-11-03T17:15:56+00:00')",
                    [(1, "US500", "control"), (2, "<BTC>", "en_prueba")])
    con.execute("INSERT INTO demo_paper_positions VALUES (1, 'US500', 1, 0.1, 7500.0, NULL, NULL, '2026-11-11T23:00:00.000000000')")
    con.execute("INSERT INTO demo_orders (client_id, strategy_id, kind, side, units, status, created)"
                " VALUES ('a', 1, 'open', 1, 0.1, 'filled', '2026-11-03T17:00:00.000000000')")
    con.execute("INSERT INTO demo_trades (strategy_id, side, entry_ts, exit_ts, entry, exit, units, pnl, costs, reason)"
                " VALUES (2, 1, '2026-11-04T10:00:00.000000000', '2026-11-05T10:00:00.000000000', 10, 15, 1, 5.0, 0, 'x')")
    con.commit()
    con.close()


def _h1(monkeypatch, precios):
    ts = np.arange(np.datetime64("2026-11-03T17:00"), np.datetime64("2026-11-12T00:00"), np.timedelta64(1, "h")).astype("datetime64[ns]")
    monkeypatch.setattr(paginas.datos, "cargar", lambda inst, plazo, raiz=None, desde=None: {
        "ts": ts, "open": np.full(len(ts), precios[inst]), "high": np.full(len(ts), precios[inst]),
        "low": np.full(len(ts), precios[inst]), "close": np.full(len(ts), precios[inst]), "volume": np.ones(len(ts))})


@pytest.fixture
def server_con_demo(server, monkeypatch):
    httpd, key, raiz = server
    monkeypatch.setattr(paginas, "_now", lambda: datetime(2026, 11, 12, 12, 0))
    _demo(raiz)
    _parte(raiz, "20261112")
    _h1(monkeypatch, {"US500": 7600.0, "<BTC>": 72000.0, "BTCUSDT": 70000.0, "ETHUSDT": 2500.0})
    paginas._HOY_CACHE.clear()
    return httpd, key, raiz


def test_hoy_nuevo_orden_y_contenido(server_con_demo):
    httpd, key, raiz = server_con_demo
    body = get(httpd, "/", f"panel={key}")[2]
    orden = ["Resultado de la demo", "Ya cerrado", "Tus estrategias", "Comprar y mantener", "Abiertas ahora", "Anoche", "Lo próximo"]
    assert [body.index(t) for t in orden] == sorted(body.index(t) for t in orden)
    assert 'http-equiv="refresh" content="120"' in body and 'id="graficos-datos"' in body
    assert body.count("popovertarget=") >= 8 and 'style="' not in body


def test_hoy_cifras_y_abiertas_con_datos(server_con_demo):
    httpd, key, raiz = server_con_demo
    body = get(httpd, "/", f"panel={key}")[2]
    assert "+15,00 €" in body and "+5,00 €" in body and "+10,00 €" in body and "7.600,00" in body
    assert "Control, 3 nov" in body and "Último precio usado: 12/11/2026 00:00" in body


@pytest.fixture
def server_con_partes_repetidas(server):
    httpd, key, raiz = server
    malo = {**PARTE, "etapas": {**PARTE["etapas"], "precios": {"segundos": 9, "resultado": {"codigo": 0, "instrumentos": [
        {"instrumento": m, "error": "descarga sospechosa"} for m in ("KVUE", "PSKY", "WBD")]}}}}
    hoy = datetime.now()
    for d in range(3):
        _parte(raiz, (hoy - timedelta(days=d)).strftime("%Y%m%d"), {**malo, "inicio": (hoy - timedelta(days=d, hours=1)).isoformat()})
    paginas._HOY_CACHE.clear()
    return httpd, key, raiz


def test_hoy_avisos_conocidos(server_con_partes_repetidas):
    httpd, key, raiz = server_con_partes_repetidas
    body = get(httpd, "/", f"panel={key}")[2]
    assert "3 avisos conocidos" in body and "KVUE" in body


def test_hoy_incluye_sistema(server):
    httpd, key, raiz = server
    _parte(raiz, "20261112")
    paginas._SISTEMA_CACHE.clear()
    body = get(httpd, "/", f"panel={key}")[2]
    assert 'id="sistema"' in body and "Tareas programadas" in body and "La última noche, etapa por etapa" in body
    assert "Últimas 7 noches" in body and "Bajó 6 valores" in body and "Omitida: sin modelo" in body


def test_sistema_redirige_a_hoy(server):
    httpd, key, raiz = server
    status, headers, _ = get(httpd, "/sistema", f"panel={key}")
    assert status == 302 and headers.getheader("Location") == "/#sistema"


def test_hoy_sin_tareas_no_rompe(raiz):
    paginas._SISTEMA_CACHE.clear()
    httpd, key = servidor.make_server(raiz, port=0, sistema={"tareas": {"error": "OSError: sin powershell"}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, _, body = get(httpd, "/", f"panel={key}")
        assert status == 200 and "No se pudo consultar las tareas programadas." in body
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hoy_catalogo_vacio(raiz):
    body = _hoy_body(raiz)
    for t in ("Aún no hay operaciones cerradas en la demo.", "No hay posiciones abiertas.",
              "Aún no hay ningún parte de la noche.", "Aún no hay experimentos."):
        assert t in body, t


def test_hoy_escapa_textos_del_parte(raiz):
    _parte(raiz, "20261112", {**PARTE, "etapas": {"investigar": {"segundos": 5, "resultado": {"fallo": "<script>x</script>"}}}})
    body = _hoy_body(raiz)
    assert "<script>x</script>" not in body and "&lt;script&gt;x&lt;/script&gt;" in body


def test_graficos_de_hoy_van_en_utc_y_crecen_en_el_cambio_de_hora(raiz):
    t0 = 1792886400  # 2026-10-25 00:00 UTC, the autumn change is at 01:00 UTC
    puntos = [{"time": t0 + k * 900, "value": float(k)} for k in range(12)]
    d = {"curva": {"total": puntos, "estrategias": puntos, "controles": puntos, "sin_precio": []}, "franja": [], "abiertas": []}
    _, specs = paginas._grafico_hoy(raiz, d)
    tiempos = [p["time"] for p in specs[0]["series"][0]["datos"]]
    assert tiempos == [p["time"] for p in puntos]


def test_demo_que_falla_no_parece_vacia(server, monkeypatch):
    httpd, key, raiz = server
    _demo(raiz)
    paginas._HOY_CACHE.clear()
    monkeypatch.setattr(paginas.hoy_datos, "curva_demo", lambda *a, **k: 1 / 0)
    body = get(httpd, "/", f"panel={key}")[2]
    assert "No se pudo calcular la demo ahora mismo." in body and "La demo no tiene estrategias activas." not in body
    assert "No hay posiciones abiertas." not in body


def test_ranking_tarjetas_filtros_y_paginas(server):
    httpd, key, raiz = server
    body = get(httpd, "/ranking", f"panel={key}")[2]
    assert 'class="circulo' in body and "Gana por € perdido" in body and "2 de 2 estrategias" in body
    assert 'href="/estrategia/' in body and 'style="' not in body
    body = get(httpd, "/ranking?veredicto=pasa", f"panel={key}")[2]
    assert "1 de 2 estrategias" in body and "AAA" in body and "BBB" not in body


def test_ranking_parametros_basura(server):
    httpd, key, raiz = server
    for q in ("nota=abc", "pagina=-3", "pagina=99999", "familia=nada", "orden=x", "mercado=%3Cb%3E"):
        assert get(httpd, f"/ranking?{q}", f"panel={key}")[0] == 200, q


def test_ranking_busqueda_escapada(server):
    httpd, key, raiz = server
    body = get(httpd, "/ranking?q=%3Cb%3E%22%26", f"panel={key}")[2]
    assert '<b>"&' not in body and "&lt;b&gt;&quot;&amp;" in body


def test_filtrar_pagina_de_50():
    filas = [{"verdict": "no_pasa", "family": "cruce_medias", "instrument": f"I{i}", "timeframe": "D1", "profit_factor": 1.0,
              "cagr": 0.1, "_nota": None, "_mercado": "accion"} for i in range(120)]
    lista, total = paginas._ranking_filtrar(filas, {"pagina": "3"})
    assert total == 120 and len(lista) == 20


ANALISIS_FALSO = {"n": 30, "g1": {"r_medio": 0.1, "costes_sobre_bruto": 0.5, "bruto_por_op_pts": 3.0, "coste_por_op_pts": 1.5},
                  "g2": {"salidas": {"stop": 1.0}, "pts": {"mae_ganadoras": 1, "mae_perdedoras": 2, "mfe": 3, "resultado": -1,
                                                          "dejado": 4, "stop": 5}},
                  "g3": {"peor_racha": 3, "dias_sin_maximo": 40, "ops_semana": 1.5, "dias_con_op": 0.2},
                  "g4": {"prob_suerte": 0.02, "t": 2.1, "n": 30, "vecinos": [{"pf": 1.1, "etiqueta": "fast 10"}]},
                  "g5": {k: {"ops": 7, "pf": 1.1} for k in ("tendencia", "lateral", "volatil", "tranquilo")},
                  "g6": {"corr_sp500": 0.1, "dias": 50},
                  "rejilla": [{"dia": "L", "hora": "10h", "ops": 30, "pf": 1.4}]}


def test_ficha_nueva_orden_y_lo_nuevo(server, monkeypatch):
    httpd, key, raiz = server
    monkeypatch.setattr(paginas.precalcular, "analisis_de", lambda *a, **k: ANALISIS_FALSO)
    paginas._ANALISIS_CACHE.clear()
    body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")[2]
    orden = ["Cifras clave", "Cómo se ha probado", "Crecimiento de la cuenta", "Rentabilidad por año", "Rentabilidad por mes",
             "Medidor", "Los criterios del validador", "Lo nuevo", "Dónde gana y dónde pierde", "Por qué gana o pierde"]
    assert [body.index(t) for t in orden] == sorted(body.index(t) for t in orden)
    assert 'id="graficos-datos"' in body and 'style="' not in body and "¿Es real o es suerte?" in body


def test_ficha_sin_analisis_no_rompe(server, monkeypatch):
    httpd, key, raiz = server
    def falla(*a, **k):
        raise OSError("sin datos")
    monkeypatch.setattr(paginas.precalcular, "analisis_de", falla)
    paginas._ANALISIS_CACHE.clear()
    status, _, body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    assert status == 200 and "No se pudo calcular: faltan los precios." in body


def test_ficha_sin_operaciones(server, monkeypatch):
    httpd, key, raiz = server
    monkeypatch.setattr(paginas.precalcular, "analisis_de", lambda *a, **k: None)
    paginas._ANALISIS_CACHE.clear()
    body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")[2]
    assert "No tiene operaciones cerradas suficientes para este análisis." in body


def test_ficha_error_interno_no_dice_faltan_precios(server, monkeypatch):
    httpd, key, raiz = server
    def falla(*a, **k):
        raise ValueError("fallo raro")
    monkeypatch.setattr(paginas.precalcular, "analisis_de", falla)
    paginas._ANALISIS_CACHE.clear()
    body = get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")[2]
    assert "No se pudo calcular (error interno)." in body and "faltan los precios" not in body


def test_analisis_al_vuelo_no_se_repite_si_cambia_el_catalogo(server, monkeypatch):
    httpd, key, raiz = server
    llamadas = []
    monkeypatch.setattr(paginas.precalcular, "analisis_de", lambda *a, **k: llamadas.append(1) or None)
    paginas._ANALISIS_CACHE.clear()
    get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("INSERT INTO demo_state VALUES ('x', 'y')")
    con.commit()
    con.close()
    get(httpd, f"/estrategia/{IDS['fx']}", f"panel={key}")
    assert len(llamadas) == 1


def test_propias_dentro_de_ranking(server):
    httpd, key, raiz = server
    _lab(raiz)
    body = get(httpd, "/propias?estrategia=ejemplo", f"panel={key}")[2]
    nav = body[body.index('class="pestanas"'):body.index("</nav>")]
    assert 'href="/ranking" aria-current="page"' in nav and "/propias" not in nav
    for t in ("Mejor variante", "El camino de cada variante", "Cómo ha mejorado noche a noche", "Lo que pide el asesor",
              "1 de 1 experimentos", 'class="circulo pf nota-'):
        assert t in body, t
    assert 'style="' not in body


def test_propias_filtros_basura(server):
    httpd, key, raiz = server
    _lab(raiz)
    for q in ("pf=abc", "ops=-5", "noche=%3Cb%3E", "pagina=999", "estrategia=nada", "orden=x"):
        assert get(httpd, f"/propias?estrategia=ejemplo&{q}", f"panel={key}")[0] == 200, q
    body = get(httpd, "/propias?estrategia=ejemplo&q=%3Cb%3Ex", f"panel={key}")[2]
    assert "&lt;b&gt;x" in body and "<b>x" not in body


def test_propias_sin_laboratorio_y_experimento_inexistente(server):
    httpd, key, raiz = server
    assert "El laboratorio aún no ha corrido." in get(httpd, "/propias", f"panel={key}")[2]
    assert get(httpd, "/propias/5", f"panel={key}")[0] == 404


def test_propias_experimento_invalido_en_la_tarjeta(server):
    httpd, key, raiz = server
    _lab(raiz)
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, invalido, creado)"
                " VALUES ('ejemplo', '2026-11-05', 'h7', '{}', 'idea rota', 1, 'invalido', 'la ficha no compila', 'x')")
    con.commit()
    con.close()
    body = get(httpd, "/propias?estrategia=ejemplo", f"panel={key}")[2]
    assert "Inválido" in body and "la ficha no compila" in body and 'class="circulo pf nota-0"' in body


def test_propias_tarjetas_con_casillas_y_evolucion(server):
    httpd, key, raiz = server
    _lab(raiz, motivo="ganadora")
    con = catalogo.abrir(raiz / "catalogo.db")
    entreno = {"veredicto": "no_pasa", "metricas": {"total": {"profit_factor": 1.9, "drawdown": 0.05, "operaciones": 80}},
               "criterios": [{"criterio": "drawdown", "valor": 0.05, "umbral": 0.2, "cumple": True},
                             {"criterio": "operaciones", "valor": 80, "umbral": 100, "cumple": False}]}
    con.execute("INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto,"
                " entreno_json, creado) VALUES ('ejemplo', '2026-11-05', 'h9', '{}', '<b>casi</b>', 2, 'no_pasa', ?, 'x')",
                (json.dumps(entreno),))
    con.commit()
    con.close()
    _, _, body = get(httpd, "/propias?estrategia=ejemplo", f"panel={key}")
    assert "&lt;b&gt;casi" in body and 'class="casillas"' in body and 'class="no"' in body and 'class="si"' in body
    assert "Cómo ha mejorado noche a noche" in body and 'style="' not in body


def test_propias_selector_de_estrategia(server):
    httpd, key, raiz = server
    _lab(raiz)
    body = get(httpd, "/propias", f"panel={key}")[2]
    assert 'href="/propias?estrategia=manual" aria-current="page"' in body and 'href="/propias?estrategia=ejemplo"' in body
    body = get(httpd, "/propias?estrategia=%3Cscript%3E", f"panel={key}")[2]
    assert 'href="/propias?estrategia=manual" aria-current="page"' in body and "&lt;script&gt;" not in body


def _exp(raiz, veredicto="no_pasa", examen=None, invalido=None, entreno=True, cambios=1):
    from quant.familias import propias
    from quant.investigacion import laboratorio as lab
    con = catalogo.abrir(raiz / "catalogo.db")
    lab.ensure_schema(con)
    base = propias.ficha_base("manual")
    ent = {"veredicto": "no_pasa", "criterios": CRITERIA, "metricas": {
        "total": {"profit_factor": 1.03, "drawdown": 0.03, "operaciones": 370, "cagr": 0.001, "rentabilidad": 0.008, "acierto": 0.44,
                  "sharpe": 0.07}, "dentro": {"sharpe": 0.1, "operaciones": 260}, "fuera": {"sharpe": 0.02, "operaciones": 110}}}
    eid = con.execute(
        "INSERT INTO lab_experimentos (estrategia, noche, huella, ficha_json, motivo, cambios, veredicto, invalido, entreno_json,"
        " examen_json, confirmacion_json, creado) VALUES ('manual', '2026-11-12', ?, ?, 'stop a 80', ?, ?, ?, ?, ?, ?, 'x')",
        (f"h{veredicto}{invalido}{examen}{cambios}", json.dumps(base), cambios, veredicto, invalido, json.dumps(ent) if entreno else None,
         json.dumps(examen) if examen else None, json.dumps(examen) if examen else None)).lastrowid
    con.commit()
    con.close()
    return eid


@pytest.fixture
def server_exp(server, monkeypatch):
    httpd, key, raiz = server
    from quant import motor
    ts, eq = np.arange(np.datetime64("2021-01-01"), np.datetime64("2022-12-31")).astype("datetime64[ns]"), None
    eq = 5000 * (1 + np.arange(len(ts)) / 5000)
    vistos = []
    monkeypatch.setattr(paginas.ficha_stats, "ejecutar", lambda raiz, ficha, inst, hasta=None: vistos.append(hasta) or (
        motor.Resultado(ts, eq, (), 5000.0), 5000.0))
    monkeypatch.setattr(paginas.precalcular, "analisis_de", lambda *a, **k: ANALISIS_FALSO)
    paginas._ANALISIS_CACHE.clear()
    paginas._EQUITY_CACHE.clear()
    return httpd, key, raiz, vistos


def test_experimento_orden_y_solo_entrenamiento(server_exp):
    httpd, key, raiz, vistos = server_exp
    original = _exp(raiz, cambios=0)
    eid = _exp(raiz)
    body = get(httpd, f"/propias/{eid}", f"panel={key}")[2]
    assert f"Tu original (#{original})" in body
    orden = ["Cifras clave", "Comparado con tu original", "Cómo se ha probado", "Crecimiento de la cuenta",
             "Los criterios del validador", "Lo nuevo", "Por qué gana o pierde"]
    assert [body.index(t) for t in orden] == sorted(body.index(t) for t in orden)
    assert "solo entrenamiento, hasta finales de 2022" in body and "Entrenamiento, examen y confirmación" not in body
    assert 'style="' not in body and "Volver a Propias" in body and "Experimento #" in body
    assert vistos and set(vistos) == {"2023-01-01"}


def test_experimento_no_pasa_con_examen_lo_oculta(server_exp):
    httpd, key, raiz, _ = server_exp
    eid = _exp(raiz, examen={"profit_factor": 1.4, "rentabilidad": 0.1, "drawdown": 0.05, "operaciones": 90})
    assert "Entrenamiento, examen y confirmación" not in get(httpd, f"/propias/{eid}", f"panel={key}")[2]


def test_experimento_que_pasa_muestra_examen(server_exp):
    httpd, key, raiz, _ = server_exp
    eid = _exp(raiz, veredicto="pasa_validador", examen={"profit_factor": 1.4, "rentabilidad": 0.1, "drawdown": 0.05, "operaciones": 90})
    body = get(httpd, f"/propias/{eid}", f"panel={key}")[2]
    assert "Entrenamiento, examen y confirmación" in body and "1,40" in body


def test_experimento_invalido_explica_por_que(server_exp):
    httpd, key, raiz, _ = server_exp
    eid = _exp(raiz, veredicto="invalido", invalido="ficha <rota>", entreno=False)
    status, _, body = get(httpd, f"/propias/{eid}", f"panel={key}")
    assert status == 200 and "ficha &lt;rota&gt;" in body and "Sin criterios" in body


def test_experimento_de_estrategia_desconocida_no_calcula_con_el_examen(server_exp):
    httpd, key, raiz, vistos = server_exp
    eid = _exp(raiz)
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("UPDATE lab_experimentos SET estrategia = 'vieja' WHERE id = ?", (eid,))
    con.commit()
    con.close()
    status, _, body = get(httpd, f"/propias/{eid}", f"panel={key}")
    assert status == 200 and vistos == [] and "ya no está entre tus estrategias" in body


def test_experimento_dice_hasta_finales_de_2022(server_exp):
    httpd, key, raiz, _ = server_exp
    body = get(httpd, f"/propias/{_exp(raiz)}", f"panel={key}")[2]
    assert "solo entrenamiento, hasta finales de 2022" in body and "hasta 2023" not in body


def test_filtro_pasa_validador_incluye_ganadoras():
    filas = [{"id": 1, "invalido": None, "veredicto": "ganadora", "motivo": "", "noche": "", "_t": {}},
             {"id": 2, "invalido": None, "veredicto": "pasa_validador", "motivo": "", "noche": "", "_t": {}},
             {"id": 3, "invalido": None, "veredicto": "no_pasa", "motivo": "", "noche": "", "_t": {}}]
    assert paginas._propias_filtrar(filas, {"resultado": "pasa_validador"})[1] == 2


def test_demo_pestana_y_contenido(server_con_demo):
    httpd, key, raiz = server_con_demo
    body = get(httpd, "/demo", f"panel={key}")[2]
    nav = body[body.index('class="pestanas"'):body.index("</nav>")]
    assert nav.index('href="/"') < nav.index('href="/demo"') < nav.index('href="/ranking"')
    for t in ("Resultado total", "Ya cerrado", "Costes pagados", "Peor caída", "Cuándo se retira una estrategia",
              "Operaciones cerradas", "faltan 9 operaciones", "+1 abierta", "2 estrategias operando con 1.000 €",
              "no se compara: es la referencia"):
        assert t in body, t
    assert "10 operaciones" in body and "6 semanas" in body and "1,5 veces" in body and 'style="' not in body
    assert "&lt;BTC&gt;" in body and "<BTC>" not in body and "05/11" in body


def test_demo_filtro_por_etiqueta(server_con_demo):
    httpd, key, raiz = server_con_demo
    body = get(httpd, "/demo?etiqueta=control", f"panel={key}")[2]
    assert "Control" in body and "&lt;BTC&gt;" not in body and "<BTC>" not in body
    assert 'href="/demo?etiqueta=control" aria-current="page"' in body


def test_demo_retirada_no_cuenta(server_con_demo):
    httpd, key, raiz = server_con_demo
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("UPDATE demo_strategies SET status='retired', retired='2026-11-10', retire_reason_es='<b>desvío</b>' WHERE id=2")
    con.commit()
    con.close()
    paginas._HOY_CACHE.clear()
    body = get(httpd, "/demo", f"panel={key}")[2]
    assert "Retirada el 10/11" in body and "&lt;b&gt;desvío&lt;/b&gt;" in body and "<b>desvío" not in body
    total = body[body.index("Resultado total"):body.index("Ya cerrado")]
    assert "+10,00 €" in total and "1 estrategia operando" in body


def test_demo_vacia(raiz):
    paginas._HOY_CACHE.clear()
    httpd, key = servidor.make_server(raiz, port=0, sistema={"tareas": {}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = get(httpd, "/demo", f"panel={key}")[2]
    finally:
        httpd.shutdown(); httpd.server_close()
    assert "La demo no tiene estrategias activas." in body and "Aún no hay operaciones cerradas en la demo." in body


def test_frente_backtest():
    cfg = {"drift_min_trades": 10, "drift_min_weeks": 6, "drift_percentile": 5}
    pnls = np.array([0.01, -0.01] * 20)
    assert paginas._frente_backtest(3, 1, 1.0, pnls, 1000, cfg) == ("faltan 7 operaciones", "suave")
    assert paginas._frente_backtest(12, 1, 0.0, np.array([]), 1000, cfg)[0] == "sin backtest para comparar"
    assert paginas._frente_backtest(12, 1, -500.0, pnls, 1000, cfg)[1] == "baja"
    assert paginas._frente_backtest(3, 7, -500.0, pnls, 1000, cfg)[1] == "baja"
    assert paginas._frente_backtest(0, 7, 0.0, pnls, 1000, cfg) == ("aún sin operaciones", "suave")
    assert paginas._frente_backtest(12, 1, 500.0, pnls, 1000, cfg)[1] == "sube"
    assert paginas._frente_backtest(12, 1, 0.0, pnls, 1000, cfg) == ("dentro de lo esperable", "")


def test_glosario_nuevo_y_anclas(server):
    httpd, key, raiz = server
    body = get(httpd, "/glosario", f"panel={key}")[2]
    for t in ("Mapa de días y horas", "Probabilidad de azar", "Lo que deja por el camino", 'id="demo"', 'id="nota-quant"',
              'href="#g-por-que-gana-o-pierde"', 'id="g-por-que-gana-o-pierde"', "<h1>Glosario</h1>", "En Quant: "):
        assert t in body, t
    assert 'id="buscar"' in body and 'style="' not in body and '<article id="sharpe"><h3>Sharpe</h3>' in body
    assert len(re.findall(r'<article id="', body)) == len(paginas.GLOSARIO) == 26
    assert [g for g, *_ in paginas.GLOSARIO] == sorted((g for g, *_ in paginas.GLOSARIO), key=paginas.GRUPOS_GLOSARIO.index)


def test_cada_interrogacion_lleva_a_un_termino(server_con_demo, monkeypatch):
    httpd, key, raiz = server_con_demo
    monkeypatch.setattr(paginas.precalcular, "analisis_de", lambda *a, **k: ANALISIS_FALSO)
    glos = get(httpd, "/glosario", f"panel={key}")[2]
    eid = _lab(raiz)
    enlaces = set()
    for ruta in ("/", "/demo", "/ranking", f"/estrategia/{IDS['fx']}", "/propias?estrategia=ejemplo", f"/propias/{eid}"):
        enlaces |= set(re.findall(r'href="/glosario#([a-z0-9-]+)"', get(httpd, ruta, f"panel={key}")[2]))
    assert enlaces and all(f'id="{a}"' in glos for a in enlaces), enlaces
    nuevos = {"mapa-de-dias-y-horas", "asesor", "variante", "probabilidad-de-azar", "costes-sobre-el-beneficio",
              "lo-que-deja-por-el-camino", "tiempo-sin-un-nuevo-maximo", "correlacion-con-el-sp500"}
    assert nuevos <= enlaces, nuevos - enlaces


def test_catalogo_vacio_todas_las_pestanas(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "universo.json").write_text(json.dumps(UNI), encoding="utf-8")
    paginas._SISTEMA_CACHE.clear(); paginas._RANKING_CACHE.clear(); paginas._HOY_CACHE.clear()
    httpd, key = servidor.make_server(tmp_path, port=0, sistema={"tareas": {}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        for ruta in ("/", "/demo", "/ranking", "/propias", "/propias?estrategia=ejemplo", "/glosario"):
            assert get(httpd, ruta, f"panel={key}")[0] == 200, ruta
        for ruta in ("/estrategia/1", "/propias/1"):
            assert get(httpd, ruta, f"panel={key}")[0] == 404, ruta
    finally:
        httpd.shutdown(); httpd.server_close()


def test_demo_catalogo_sin_tablas_demo(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "universo.json").write_text(json.dumps(UNI), encoding="utf-8")
    catalogo.abrir(tmp_path / "catalogo.db").close()
    paginas._HOY_CACHE.clear()
    httpd, key = servidor.make_server(tmp_path, port=0, sistema={"tareas": {}})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, _, body = get(httpd, "/demo", f"panel={key}")
    finally:
        httpd.shutdown(); httpd.server_close()
    assert status == 200 and "La demo no tiene estrategias activas." in body


def test_demo_compara_con_la_misma_banda_que_la_noche(server_con_demo, monkeypatch):
    httpd, key, raiz = server_con_demo
    con = catalogo.abrir(raiz / "catalogo.db")
    con.executemany("INSERT INTO demo_trades (strategy_id, side, entry_ts, exit_ts, entry, exit, units, pnl, costs, reason)"
                    " VALUES (2, 1, '2026-11-06T10:00:00', '2026-11-07T10:00:00', 10, 9, 1, -10.0, 0, 'stop')", [()] * 10)
    con.commit(); con.close()
    vistos = []
    monkeypatch.setattr(paginas.noche, "_backtest_fractions", lambda s, ctx: vistos.append(s["id"]) or [0.01, -0.01] * 20)
    body = get(httpd, "/demo", f"panel={key}")[2]
    assert vistos == [2] and "por debajo del 5 % peor de su backtest" in body


def test_demo_cierres_y_fechas_en_madrid(server_con_demo):
    httpd, key, raiz = server_con_demo
    con = catalogo.abrir(raiz / "catalogo.db")
    con.execute("UPDATE demo_trades SET reason='objetivo', exit_ts='2026-11-05T23:30:00.000000000' WHERE strategy_id=2")
    con.execute("INSERT INTO demo_trades (strategy_id, side, entry_ts, exit_ts, entry, exit, units, pnl, costs, reason)"
                " VALUES (2, -1, '2026-11-08T10:00:00', '2026-11-09T10:00:00', 10, 9, 1, 1.0, 0, 'retirada')")
    con.execute("UPDATE demo_strategies SET status='retired', retired=NULL, retire_reason_es='desvío' WHERE id=2")
    con.commit(); con.close()
    body = get(httpd, "/demo", f"panel={key}")[2]
    assert "cerrada por objetivo" in body and "cerrada al retirarla" in body and "04/11 → 06/11" in body
    assert "Retirada: desvío" in body and "Retirada el /" not in body
