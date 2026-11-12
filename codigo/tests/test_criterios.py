import json

import pytest

from quant import criterios, rutas


def test_firmar_y_cargar(tmp_path):
    (tmp_path / "criterios.json").write_text(json.dumps({"drawdown_max": 0.2}), encoding="utf-8")
    criterios.firmar(tmp_path)
    assert criterios.cargar(tmp_path)["drawdown_max"] == 0.2


def test_cambio_sin_firmar_para(tmp_path):
    ruta = tmp_path / "criterios.json"
    ruta.write_text(json.dumps({"drawdown_max": 0.2}), encoding="utf-8")
    criterios.firmar(tmp_path)
    ruta.write_text(json.dumps({"drawdown_max": 0.5}), encoding="utf-8")
    with pytest.raises(criterios.ErrorCriterios, match="sin firmar"):
        criterios.cargar(tmp_path)


def test_sin_firma(tmp_path):
    (tmp_path / "criterios.json").write_text("{}", encoding="utf-8")
    with pytest.raises(criterios.ErrorCriterios):
        criterios.cargar(tmp_path)


def test_config_real_firmada_y_con_valores_del_diseno(tmp_path):
    c = criterios.cargar(rutas.CONFIG)
    assert (c["capital"], c["drawdown_max"], c["sharpe_oos_min"], c["montecarlo_p95_dd_max"]) == (5000, 0.20, 0.5, 0.30)
    assert (c["operaciones_min"], c["operaciones_oos_min"], c["robustez_min"], c["margen_dudosa"]) == (100, 30, 0.70, 0.10)
