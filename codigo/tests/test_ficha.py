import copy
import json

import pytest

from quant import ficha

BASE = {
    "id": "rsi2-spy",
    "titulo": "RSI(2) en SPY",
    "fuente": {"url": "https://ejemplo.org/rsi2", "cita": "sección 3"},
    "tipo": "reversion",
    "forma": "serie_temporal",
    "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
    "entrada": {"largo": {"y": [{"<": ["RSI(2)", 10]}, {">": ["close", "SMA(200)"]}]}},
    "salida": {"largo": {">": ["close", "SMA(5)"]}},
    "gestion": {"stop": {"tipo": "atr", "valor": 3}},
    "estado": "borrador",
}


def test_ficha_valida():
    assert ficha.errores(BASE) == []


def test_falta_campo():
    datos = {k: v for k, v in BASE.items() if k != "universo"}
    assert any("universo" in e for e in ficha.errores(datos))


def test_retardo_negativo_rechazado():
    datos = copy.deepcopy(BASE)
    datos["salida"]["largo"] = {">": ["close[-1]", "close"]}
    assert any("futuro" in e for e in ficha.errores(datos))


def test_serie_sin_entradas():
    datos = copy.deepcopy(BASE)
    datos["entrada"] = {}
    assert any("entrada" in e for e in ficha.errores(datos))


def test_transversal_necesita_seccion():
    datos = copy.deepcopy(BASE)
    datos["forma"] = "transversal"
    assert any("transversal" in e for e in ficha.errores(datos))


def test_umbral_de_tipo_sin_fuente_rechazado():
    datos = copy.deepcopy(BASE)
    datos["umbrales_tipo"] = [{"metrica": "sharpe", "valor": 0.4, "sentido": "min", "fuente": ""}]
    assert ficha.errores(datos)


def test_cargar_aplica_defectos_sin_mutar(tmp_path):
    ruta = tmp_path / "f.json"
    ruta.write_text(json.dumps(BASE), encoding="utf-8")
    cargada = ficha.cargar(ruta)
    assert cargada["gestion"]["tamano"] == {"tipo": "riesgo", "valor": 1.0}
    assert "tamano" not in BASE["gestion"]


def test_cargar_invalida_lanza(tmp_path):
    ruta = tmp_path / "f.json"
    ruta.write_text(json.dumps({"id": "x"}), encoding="utf-8")
    with pytest.raises(ficha.ErrorFicha):
        ficha.cargar(ruta)


def _transversal(**extra):
    datos = {k: v for k, v in copy.deepcopy(BASE).items() if k not in ("entrada", "salida")}
    datos.update({"forma": "transversal", "gestion": {},
                  "transversal": {"ranking": "MOM(20)", "cada_barras": 10, "top": 1}}, **extra)
    return datos


def test_transversal_minima_valida():
    assert ficha.errores(_transversal()) == []
    assert ficha.errores(_transversal(gestion={"tamano": {"tipo": "riesgo", "valor": 1.0}})) == []


@pytest.mark.parametrize("seccion", ["entrada", "salida"])
def test_transversal_rechaza_entrada_y_salida(seccion):
    datos = _transversal(**{seccion: {"largo": {">": ["close", "SMA(5)"]}}})
    assert any(e.startswith(f"{seccion}:") for e in ficha.errores(datos))


def test_transversal_rechaza_horario():
    assert any(e.startswith("horario:") for e in ficha.errores(_transversal(horario={"dias": [0]})))


@pytest.mark.parametrize("clave,valor", [("stop", {"tipo": "atr", "valor": 2}), ("objetivo", {"tipo": "pct", "valor": 3}),
                                         ("trailing", {"tipo": "atr", "valor": 1}), ("max_barras", 5)])
def test_transversal_rechaza_gestion_distinta_de_tamano(clave, valor):
    datos = _transversal(gestion={clave: valor, "tamano": {"tipo": "riesgo", "valor": 1.0}})
    assert any(e.startswith(f"gestion/{clave}:") for e in ficha.errores(datos))


def test_serie_rechaza_transversal():
    datos = copy.deepcopy(BASE)
    datos["transversal"] = {"ranking": "MOM(20)", "cada_barras": 10, "top": 1}
    assert any(e.startswith("transversal:") for e in ficha.errores(datos))
