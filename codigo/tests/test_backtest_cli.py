import json
import shutil

import numpy as np
import pandas as pd

from quant import backtest, calidad, criterios, datos, rutas

FICHA = {"id": "cruce-sma", "titulo": "Cruce de medias", "fuente": {"url": "x://y", "cita": "p1"},
         "tipo": "tendencia", "forma": "serie_temporal",
         "universo": {"instrumentos": ["US500", "GER40"], "plazo": "D1"},
         "entrada": {"largo": {"cruza_arriba": ["SMA(10)", "SMA(40)"]}},
         "salida": {"largo": {"cruza_abajo": ["SMA(10)", "SMA(40)"]}},
         "gestion": {"stop": {"tipo": "atr", "valor": 3}}, "estado": "borrador"}


def _raiz(tmp_path, instrumentos=("US500",)):
    (tmp_path / "config").mkdir()
    shutil.copy(rutas.CONFIG / "costes.json", tmp_path / "config" / "costes.json")
    shutil.copy(rutas.CONFIG / "criterios.json", tmp_path / "config" / "criterios.json")
    criterios.firmar(tmp_path / "config")
    rng = np.random.default_rng(11)
    c = 4000 * np.cumprod(1 + rng.normal(0.0003, 0.01, 800))
    df = pd.DataFrame({"ts": pd.date_range("2020-01-01", periods=800, freq="1D"), "open": c, "high": c * 1.005,
                       "low": c * 0.995, "close": c, "volume": 1.0})
    datos.guardar("US500", "D1", df, tmp_path / "datos")
    (tmp_path / "datos").mkdir(parents=True, exist_ok=True)
    calidad_info = {inst: {"bloqueante": False, "motivos": []} for inst in instrumentos}
    (tmp_path / "datos" / calidad.FICHERO).write_text(json.dumps(calidad_info), encoding="utf-8")
    ruta = tmp_path / "ficha.json"
    ruta.write_text(json.dumps(FICHA), encoding="utf-8")
    return ruta


def test_cli_valida_y_marca_pendiente(tmp_path, capsys):
    ruta = _raiz(tmp_path)
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["US500"]["veredicto"] in {"pasa", "dudosa", "no_pasa"}
    assert salida["GER40"]["veredicto"] == "pendiente_datos"


def test_cli_criterios_manipulados(tmp_path, capsys):
    ruta = _raiz(tmp_path)
    (tmp_path / "config" / "criterios.json").write_text('{"drawdown_max": 0.9}', encoding="utf-8")
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 3


def test_cli_ficha_invalida(tmp_path):
    _raiz(tmp_path)
    mala = tmp_path / "mala.json"
    mala.write_text('{"id": "x"}', encoding="utf-8")
    assert backtest.main([str(mala), "--raiz", str(tmp_path)]) == 2


def test_cli_ficha_inexistente(tmp_path, capsys):
    _raiz(tmp_path)
    assert backtest.main([str(tmp_path / "no_existe.json"), "--raiz", str(tmp_path)]) == 2
    assert capsys.readouterr().err.strip()


def test_cli_ficha_json_roto(tmp_path, capsys):
    _raiz(tmp_path)
    rota = tmp_path / "rota.json"
    rota.write_text('{"id": ', encoding="utf-8")
    assert backtest.main([str(rota), "--raiz", str(tmp_path)]) == 2
    assert capsys.readouterr().err.strip()


def test_cli_costes_ausente(tmp_path, capsys):
    ruta = _raiz(tmp_path)
    (tmp_path / "config" / "costes.json").unlink()
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 3
    assert capsys.readouterr().err.startswith("PARADA: ")


def test_cli_costes_json_roto(tmp_path, capsys):
    ruta = _raiz(tmp_path)
    (tmp_path / "config" / "costes.json").write_text("{", encoding="utf-8")
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 3
    assert capsys.readouterr().err.startswith("PARADA: ")


def test_cli_usa_clase_del_universo(tmp_path, capsys):
    ruta = _raiz(tmp_path, instrumentos=("US500", "NVDA"))
    shutil.copy(rutas.CONFIG / "universo.json", tmp_path / "config" / "universo.json")
    (tmp_path / "config" / "universo_acciones.json").write_text('["NVDA"]', encoding="utf-8")
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 800))
    df = pd.DataFrame({"ts": pd.date_range("2020-01-01", periods=800, freq="1D"), "open": c, "high": c * 1.01,
                       "low": c * 0.99, "close": c, "volume": 1.0})
    datos.guardar("NVDA", "D1", df, tmp_path / "datos")
    ruta.write_text(json.dumps({**FICHA, "universo": {"instrumentos": ["NVDA"], "plazo": "D1"}}), encoding="utf-8")
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["NVDA"]["veredicto"] in {"pasa", "dudosa", "no_pasa"}


def test_cli_bloquea_por_calidad(tmp_path, capsys):
    ruta = _raiz(tmp_path)
    (tmp_path / "datos" / "_calidad.json").write_text(
        json.dumps({"US500": {"bloqueante": True, "motivos": ["3 velas con precios no positivos o no finitos"]}}),
        encoding="utf-8")
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["US500"]["veredicto"] == "pendiente_datos"
    assert salida["US500"]["motivo"].startswith("calidad:")


def test_cli_recorta_por_desde_del_universo(tmp_path, capsys, monkeypatch):
    ruta = _raiz(tmp_path)
    shutil.copy(rutas.CONFIG / "universo.json", tmp_path / "config" / "universo.json")
    llamadas = []
    original = datos.cargar

    def espia(instrumento, plazo, raiz, desde=None):
        llamadas.append((instrumento, desde))
        return original(instrumento, plazo, raiz, desde=desde)

    monkeypatch.setattr(backtest.datos, "cargar", espia)
    backtest.main([str(ruta), "--raiz", str(tmp_path)])
    assert ("US500", "2013-06-01") in llamadas


def test_cli_instrumento_sin_revisar_es_pendiente(tmp_path, capsys):
    ruta = _raiz(tmp_path, instrumentos=())
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["US500"]["veredicto"] == "pendiente_datos"
    assert salida["US500"]["motivo"] == "calidad: sin revisar"


def test_probar_matches_cli_output(tmp_path, capsys):
    from quant import costes as mcostes, universo
    ruta = _raiz(tmp_path)
    assert backtest.main([str(ruta), "--raiz", str(tmp_path)]) == 0
    salida = json.loads(capsys.readouterr().out)
    resultado = backtest.probar(FICHA, tmp_path, criterios.cargar(tmp_path / "config"),
                                mcostes.cargar(tmp_path / "config" / "costes.json"),
                                universo.cargar(tmp_path / "config"))
    assert json.loads(json.dumps(resultado)) == salida
    assert resultado["GER40"]["veredicto"] == "pendiente_datos"
