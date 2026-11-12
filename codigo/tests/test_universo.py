import json

import pandas as pd
import pytest

from quant import rutas, universo


def test_universo_real_valido():
    inst = universo.cargar(rutas.CONFIG)["instrumentos"]
    assert inst["US500"] == {"clase": "indice", "fuente": "dukascopy", "simbolo": "USA500IDXUSD",
                             "divisor": 1000, "desde": "2013-06-01"}
    assert inst["EURUSD"]["divisor"] == 100000 and inst["USDJPY"]["divisor"] == 1000
    assert inst["BTCUSDT"]["fuente"] == "binance" and inst["SPY"]["fuente"] == "yahoo"
    assert len([k for k, v in inst.items() if v["clase"] == "cripto"]) == 10


def test_cargar_sin_fichero(tmp_path):
    assert universo.cargar(tmp_path) == {"instrumentos": {}}


def test_desde_de():
    uni = {"instrumentos": {"X": {"clase": "indice", "desde": "2013-06-01"}}}
    assert universo.desde_de("X", uni) == "2013-06-01"
    assert universo.desde_de("ZZZ", uni) is None


def test_validacion(tmp_path):
    (tmp_path / "universo.json").write_text(json.dumps(
        {"instrumentos": {"X": {"clase": "indice", "fuente": "dukascopy", "simbolo": "X", "desde": "2020-01-01"}}}),
        encoding="utf-8")
    with pytest.raises(universo.ErrorUniverso, match="divisor"):
        universo.cargar(tmp_path)


def test_acciones_se_fusionan_sin_pisar(tmp_path):
    (tmp_path / "universo.json").write_text(json.dumps(
        {"instrumentos": {"SPY": {"clase": "accion", "fuente": "yahoo", "simbolo": "SPY", "desde": "1993-01-01"}}}),
        encoding="utf-8")
    (tmp_path / "universo_acciones.json").write_text(json.dumps(["AAPL", "SPY"]), encoding="utf-8")
    inst = universo.cargar(tmp_path)["instrumentos"]
    assert inst["SPY"]["desde"] == "1993-01-01"
    assert inst["AAPL"] == {"clase": "accion", "fuente": "yahoo", "simbolo": "AAPL", "desde": "1990-01-01"}
    assert universo.clase_de("AAPL", {"instrumentos": inst}) == "accion"
    assert universo.clase_de("ZZZ", {"instrumentos": inst}) is None


def _html_falso(sp_n=500):
    def f(url, **_):
        if "S%26P" in url:
            simbolos = ["BRK.B", "COMPARTIDO"] + [f"S{i}" for i in range(sp_n - 2)]
            return [pd.DataFrame({"Symbol": simbolos, "Security": ["x"] * sp_n})]
        tickers = ["COMPARTIDO"] + [f"T{i}.DE" for i in range(39)]
        return [pd.DataFrame({"x": [1]}), pd.DataFrame({"Ticker": tickers})]
    return f


def test_tickers_indices_y_refresco(tmp_path):
    html = _html_falso(500)
    tickers = universo.tickers_indices(html)
    assert "BRK-B" in tickers and len(tickers) == 539
    assert tickers.count("COMPARTIDO") == 1
    assert universo.refrescar_acciones(tmp_path, html) == 539
    assert json.loads((tmp_path / "universo_acciones.json").read_text(encoding="utf-8")) == tickers


def test_refrescar_acciones_rechaza_menos_de_400(tmp_path):
    with pytest.raises(universo.ErrorUniverso, match="400"):
        universo.refrescar_acciones(tmp_path, _html_falso(300))
    assert not (tmp_path / "universo_acciones.json").exists()


def test_refrescar_acciones_rechaza_caida_del_80_por_ciento(tmp_path):
    (tmp_path / "universo_acciones.json").write_text(json.dumps([f"X{i}" for i in range(600)]), encoding="utf-8")
    with pytest.raises(universo.ErrorUniverso, match="80"):
        universo.refrescar_acciones(tmp_path, _html_falso(410))
    assert len(json.loads((tmp_path / "universo_acciones.json").read_text(encoding="utf-8"))) == 600
