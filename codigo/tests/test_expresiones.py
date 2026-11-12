import numpy as np

from quant import expresiones as ex


def test_comparacion_con_numero(barras):
    b = barras([10, 40, 20])
    assert list(ex.evaluar({"<": ["close", 30]}, b)) == [True, False, True]


def test_calentamiento_es_falso_incluso_negado(barras):
    b = barras([1, 2, 3])
    assert list(ex.evaluar({"no": {"<": ["close", "SMA(3)"]}}, b)) == [False, False, True]


def test_y_o(barras):
    b = barras([1, 5, 9])
    assert list(ex.evaluar({"y": [{">": ["close", 2]}, {"<": ["close", 8]}]}, b)) == [False, True, False]
    assert list(ex.evaluar({"o": [{"<": ["close", 2]}, {">": ["close", 8]}]}, b)) == [True, False, True]


def test_cruces(barras):
    b = barras([1, 3, 2, 4])
    assert list(ex.evaluar({"cruza_arriba": ["close", 2.5]}, b)) == [False, True, False, True]
    assert list(ex.evaluar({"cruza_abajo": ["close", 2.5]}, b)) == [False, False, True, False]


def test_operandos():
    cond = {"y": [{"<": ["RSI(14)", 30]}, {"no": {">": ["close", "SMA(200)"]}}]}
    assert ex.operandos(cond) == ["RSI(14)", "close", "SMA(200)"]
