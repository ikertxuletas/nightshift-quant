import json

import numpy as np
import pytest

from quant import datos
from quant.demo import diario
from quant.investigacion import catalogo
from quant.panel import hoy_datos

T0 = np.datetime64("2026-11-03T17:00:00", "ns")


def _ts(horas):
    return np.array([T0 + np.timedelta64(h, "h") for h in horas], "datetime64[ns]")


def cargar_h1(precios):
    def cargar(inst):
        if inst not in precios:
            raise datos.ErrorDatos(f"pendiente de datos: {inst}")
        return {"ts": _ts(range(len(precios[inst]))), "close": np.array(precios[inst], float)}
    return cargar


def cargar_que_falla_para(inst):
    def cargar(i):
        raise datos.ErrorDatos(f"pendiente de datos: {i}")
    return cargar


@pytest.fixture
def con(tmp_path):
    c = catalogo.abrir(tmp_path / "catalogo.db")
    diario.ensure_schema(c)
    c.execute("CREATE TABLE IF NOT EXISTS demo_paper_positions(strategy_id INTEGER PRIMARY KEY, instrument TEXT,"
              " side INTEGER, units REAL, entry_price REAL, stop REAL, target REAL, last_checked TEXT)")
    c.executemany("INSERT INTO demo_strategies (id, instrument, timeframe, label, status, capital, added)"
                  " VALUES (?, 'US500', 'D1', ?, 'active', 500, '2026-11-03T17:15:56+00:00')",
                  [(1, "control"), (2, "en_prueba")])
    c.execute("INSERT INTO demo_paper_positions VALUES (1, 'US500', 1, 1.0, 100.0, NULL, NULL, NULL)")
    c.execute("INSERT INTO demo_orders (client_id, strategy_id, kind, side, units, status, created)"
              " VALUES ('a', 1, 'open', 1, 1.0, 'filled', '2026-11-03T17:00:00.000000000')")
    c.execute("INSERT INTO demo_trades (strategy_id, side, entry_ts, exit_ts, entry, exit, units, pnl, costs, reason)"
              " VALUES (2, 1, '2026-11-03T17:00:00.000000000', '2026-11-03T19:00:00.000000000', 10, 15, 1, 5.0, 0, 'x')")
    c.commit()
    yield c
    c.close()


def test_curva_suma_cerradas_y_abiertas_por_grupo(con):
    c = hoy_datos.curva_demo(con, cargar_h1(precios={"US500": [100, 102, 104]}))
    assert [p["value"] for p in c["controles"]] == [0.0, 2.0, 4.0]
    assert [p["value"] for p in c["estrategias"]] == [0.0, 0.0, 5.0]
    assert [p["value"] for p in c["total"]] == [0.0, 2.0, 9.0]
    assert c["total"][0]["time"] == int(T0.astype("datetime64[s]").astype("int64")) and c["sin_precio"] == []


def test_curva_sin_precio_no_rompe(con):
    c = hoy_datos.curva_demo(con, cargar_que_falla_para("US500"))
    assert c["sin_precio"] == ["US500"] and all(p["value"] == 0 for p in c["controles"])


def test_franja_crece_con_los_dias():
    curva = [{"time": 1_700_000_000 + h * 3600, "value": 0} for h in range(24 * 4)]
    f = hoy_datos.franja_demo(curva, np.array([0.01, -0.01, 0.02]), ops_por_dia=1, capital=1000)
    assert len(f) == 4 and f[0]["bajo"] > f[-1]["bajo"] and f[0]["alto"] < f[-1]["alto"]


def test_franja_vacia_sin_backtest():
    assert hoy_datos.franja_demo([{"time": 1, "value": 0}], np.array([]), 1, 1000) == []


def test_resumen_demo_separa_porcentajes(con):
    r = hoy_datos.resumen_demo(con, hoy_datos.curva_demo(con, cargar_h1(precios={"US500": [100, 102, 104]})))
    assert r["total"] == 9.0 and r["cerrado"] == 5.0 and r["n_cerradas"] == 1 and r["capital"] == 1000
    assert r["pct_controles"] == pytest.approx(0.8) and r["pct_estrategias"] == pytest.approx(1.0)
    assert r["pct_total"] == pytest.approx(0.9)


def test_abiertas_valor_actual_y_sin_precio(con):
    a = hoy_datos.abiertas(con, cargar_h1(precios={"US500": [100, 102, 104]}))
    assert a == [{"estrategia": 1, "instrumento": "US500", "etiqueta": "control", "desde": "2026-11-03T17:00:00.000000000",
                  "entrada": 100.0, "ahora": 104.0, "resultado": 4.0, "cierres30": [104.0]}]
    b = hoy_datos.abiertas(con, cargar_que_falla_para("US500"))
    assert b[0]["ahora"] is None and b[0]["resultado"] is None and b[0]["cierres30"] == []


from datetime import datetime

AHORA = datetime(2026, 11, 12, 10, 0)


def parte(fecha, malos=(), etapas=None):
    inst = [{"instrumento": "US500", "error": None}] + [{"instrumento": m, "error": "descarga sospechosa"} for m in malos]
    base = {"precios": {"segundos": 10, "resultado": {"codigo": 0, "instrumentos": inst}},
            "investigar": {"segundos": 5, "resultado": {"codigo": 0, "lectura": {"leidos": 1, "descartados": 7},
                                                        "fichas": {"aprobadas": 1}, "validadas": 0}},
            "demo": {"segundos": 5, "resultado": {"evaluated": 7, "retired": 0}},
            "laboratorio": {"segundos": 9, "resultado": {"tandas": 6, "probados": 60, "ganadoras": 0}},
            "copia": {"segundos": 3, "resultado": {"catalogo": True}}}
    return {"fecha": fecha, "inicio": f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}T01:00:00", "etapas": {**base, **(etapas or {})}}


def test_estado_verde():
    assert hoy_datos.estado([parte("20261112")], {"Quant_Demo": {"ultima": "2026-11-12T09:15:00"}}, [], AHORA)["nivel"] == "verde"


def test_estado_rojo_si_la_demo_no_revisa():
    assert hoy_datos.estado([parte("20261112")], {"Quant_Demo": {"ultima": "2026-11-10T09:15:00"}}, [], AHORA)["nivel"] == "rojo"


def test_estado_rojo_sin_parte_reciente_o_con_etapa_fallida():
    assert hoy_datos.estado([parte("20261110")], {}, [], AHORA)["nivel"] == "rojo"
    assert hoy_datos.estado([], {}, [], AHORA)["nivel"] == "rojo"
    e = hoy_datos.estado([parte("20261112", etapas={"copia": {"segundos": 1, "resultado": {"fallo": "sin disco"}}})], {}, [], AHORA)
    assert e["nivel"] == "rojo" and e["titular"] == "Algo falló" and any("sin disco" in a for a in e["avisos"])


def test_aviso_repetido_es_conocido_y_no_sube_el_nivel():
    ps = [parte(f, malos=["KVUE"]) for f in ("20261112", "20261111", "20261110")]
    e = hoy_datos.estado(ps, {}, [], AHORA)
    assert e["nivel"] == "verde" and e["conocidos"] == ["KVUE"] and not e["avisos"]


def test_aviso_nuevo_pone_ambar():
    e = hoy_datos.estado([parte("20261112", malos=["WBD"]), parte("20261111")], {}, [], AHORA)
    assert e["nivel"] == "ambar" and any("WBD" in a for a in e["avisos"]) and e["titular"] == "Hay algo que mirar"


def test_ambar_por_laboratorio_parado_y_eventos_de_la_demo():
    p = parte("20261112", etapas={"laboratorio": {"segundos": 1, "resultado": {"probados": 0}}})
    assert hoy_datos.estado([p], {}, [], AHORA)["nivel"] == "ambar"
    ev = [{"ts": "2026-11-12T08:00:00+00:00", "kind": "warn", "detail_es": "<b>raro</b>"},
          {"ts": "2026-11-10T08:00:00+00:00", "kind": "retire", "detail_es": "viejo"}]
    e = hoy_datos.estado([parte("20261112")], {}, ev, AHORA)
    assert e["nivel"] == "ambar" and e["avisos"] == ["<b>raro</b>"]


def test_resumen_noche_frases_fijas():
    r = hoy_datos.resumen_noche(parte("20261112"))
    assert r[0].startswith("6 tandas, 60 experimentos") and r[1].startswith("Leyó 8 documentos")
    assert r[2] == "Precios, demo y copia de seguridad, sin problemas."
    r = hoy_datos.resumen_noche(parte("20261112", etapas={"demo": {"segundos": 1, "resultado": {"fallo": "x"}}}))
    assert r[2] == "Con problemas: demo."
    assert hoy_datos.resumen_noche(None) == []


def test_proximo_dice_esta_noche_y_el_domingo():
    t = {"Quant_Noche": {"proxima": "2026-11-13T01:00:00"}, "Quant_Asesor": {"proxima": "2026-11-15T09:00:00"}}
    assert hoy_datos.proximo(t, AHORA) == "Esta noche a las 01:00, noche de laboratorio. El domingo 15 a las 09:00, informe del asesor."


def test_proximo_hoy_manana_y_sin_datos():
    t = {"Quant_Noche": {"proxima": "2026-11-12T15:00:00"}, "Quant_Asesor": {"proxima": "2026-11-13T09:00:00"}}
    assert hoy_datos.proximo(t, AHORA) == "Hoy a las 15:00, noche de laboratorio. Mañana a las 09:00, informe del asesor."
    assert hoy_datos.proximo({"Quant_Noche": {"proxima": None}}, AHORA) == ""
    assert hoy_datos.proximo({"error": "OSError"}, AHORA) == ""


@pytest.fixture
def con_lab(tmp_path):
    from quant.investigacion import laboratorio
    c = catalogo.abrir(tmp_path / "catalogo.db")
    laboratorio.ensure_schema(c)
    filas = [("2026-11-11", 1, None, 0.91, 300), ("2026-11-11", 1, None, 2.5, 50), ("2026-11-11", 0, None, 1.5, 900),
             ("2026-11-12", 2, None, 1.03, 370), ("2026-11-12", 1, "mal", 3.0, 999), ("2026-11-12", 1, None, 0.95, 400)]
    for n, (noche, cambios, inval, pf, ops) in enumerate(filas):
        c.execute("INSERT INTO lab_experimentos (estrategia, noche, huella, cambios, veredicto, invalido, entreno_json)"
                  " VALUES ('manual', ?, ?, ?, 'no_pasa', ?, ?)",
                  (noche, f"h{n}", cambios, inval, json.dumps({"metricas": {"total": {"profit_factor": pf, "operaciones": ops}}})))
    c.commit()
    yield c
    c.close()


def test_progreso_propia_evolucion_y_fase(con_lab):
    p = hoy_datos.progreso_propia(con_lab, "manual")
    assert p["evolucion"] == [("2026-11-11", 0.91), ("2026-11-12", 1.03)] and p["fase"] == "Entrenamiento"
    assert p["pf"] == 1.03 and p["ops"] == 370 and p["variantes"] == 4 and p["mejor_id"] == 4


def test_progreso_propia_sin_experimentos(con_lab):
    assert hoy_datos.progreso_propia(con_lab, "ejemplo") is None


def test_precios_fallidos_sin_lista_ponen_ambar():
    p = parte("20261112", etapas={"precios": {"segundos": 1, "resultado": {"codigo": 2, "error": "sin red"}}})
    e = hoy_datos.estado([p], {}, [], AHORA)
    assert e["nivel"] == "ambar" and any("precios" in a for a in e["avisos"])


def test_instrumento_critico_conocido_sigue_avisando():
    ps = [parte(f, malos=["US500"]) for f in ("20261112", "20261111", "20261110")]
    for p in ps:
        p["etapas"]["precios"]["resultado"].update(codigo=1, criticos_con_error=["US500"])
    e = hoy_datos.estado(ps, {}, [], AHORA)
    assert e["nivel"] == "ambar" and any("US500" in a for a in e["avisos"])
