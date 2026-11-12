import copy

import pytest

from quant.investigacion import salida

EXTRACTO = {"operable": "si", "tipo": "tendencia", "mercado": ["accion"], "plazo": "D1",
            "extracto": "Compra cuando el cierre supera la media de 200 sesiones y vende cuando cae por debajo.",
            "prometido": {"sharpe": 0.78, "cita": "Sharpe 0.78"}, "alarmas": []}


def test_limpio_no_toca_nada_ni_muta():
    original = copy.deepcopy(EXTRACTO)
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO)
    assert datos == original and avisos == [] and errores == []
    assert EXTRACTO == original and datos is not EXTRACTO


def test_respuesta_que_no_es_objeto():
    datos, avisos, errores = salida.limpiar("lector", ["lista"])
    assert datos == {} and errores == ["la respuesta no es un objeto JSON"]


@pytest.mark.parametrize("llega,queda", [("1w", "W1"), ("Semanal", "W1"), ("weekly", "W1"), ("daily", "D1"),
                                         ("1D", "D1"), ("diario", "D1"), ("1h", "H1"), ("4H", "H4"),
                                         ("15m", "M15"), ("5M", "M5"), ("monthly", "D1"), ("MN", "D1"),
                                         ("mensual", "D1"), ("d1", "D1"), ("M30", "H1"), ("30m", "H1"),
                                         ("H2", "H1"), ("M1", "M5"), ("M10", "M15"), ("H8", "H4"),
                                         ("H12", "H4")])
def test_plazo_se_normaliza(llega, queda):
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {"plazo": llega})
    assert datos["plazo"] == queda and errores == []
    assert any("plazo normalizado" in a for a in avisos)


def test_plazo_desconocido_se_deja_para_la_validacion_de_negocio():
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {"plazo": "tick"})
    assert datos["plazo"] == "tick" and errores == []


def test_operable_nulo_se_tolera():
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {"operable": None})
    assert datos["operable"] is None and avisos == [] and errores == []


def test_plazo_nulo_se_deja_para_la_validacion_de_negocio():
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {"plazo": None})
    assert datos["plazo"] is None and avisos == [] and errores == []


def test_texto_y_lista_se_intercambian_con_aviso():
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {"mercado": "accion", "tipo": ["tendencia"],
                                                                "alarmas": None})
    assert datos["mercado"] == ["accion"] and datos["tipo"] == "tendencia" and datos["alarmas"] == []
    assert errores == [] and len(avisos) == 2


def test_nulo_en_texto_pasa_a_vacio():
    datos, avisos, errores = salida.limpiar("critico", {"veredicto": "devolver", "motivos": None})
    assert datos == {"veredicto": "devolver", "motivos": []} and errores == []


def test_numeros_como_texto_en_prometido():
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {
        "prometido": {"sharpe": "0.78", "drawdown": "-12,5 %", "periodo": "1990-2020", "cita": "x"}})
    assert datos["prometido"] == {"sharpe": 0.78, "drawdown": -12.5, "periodo": "1990-2020", "cita": "x"}
    assert errores == [] and any("prometido" in a for a in avisos)


def test_cifras_no_convierte_periodo_ni_ambiguedad_de_miles():
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | {
        "prometido": {"periodo": "2020", "muestras": "1,234", "drawdown": "-12,5 %"}})
    assert datos["prometido"]["periodo"] == "2020"
    assert datos["prometido"]["muestras"] == "1,234"
    assert datos["prometido"]["drawdown"] == -12.5
    assert errores == [] and any("drawdown" in a for a in avisos)
    assert not any("periodo" in a or "muestras" in a for a in avisos)


def test_formas_no_recuperables_son_errores_con_campo():
    entrada = {"tipo": {"x": 1}, "mercado": [["accion"]], "plazo": ["D1", "H1"], "prometido": "nada"}
    datos, avisos, errores = salida.limpiar("lector", EXTRACTO | entrada)
    assert len(errores) == 4
    assert any(e.startswith("tipo:") for e in errores)
    assert any(e.startswith("mercado:") for e in errores)
    assert any(e.startswith("plazo:") for e in errores)
    assert any(e.startswith("prometido:") for e in errores)
    for campo, valor in entrada.items():
        assert datos[campo] == valor


def test_formalizador_critico_y_mentor():
    datos, _, errores = salida.limpiar("formalizador", {"expresable": "true", "motivo": None, "ficha": {"id": "x"}})
    assert datos == {"expresable": True, "motivo": "", "ficha": {"id": "x"}} and errores == []
    _, _, errores = salida.limpiar("formalizador", {"expresable": True, "ficha": ["x"]})
    assert any(e.startswith("ficha:") for e in errores)
    _, _, errores = salida.limpiar("critico", {"veredicto": ["aprobada", "devolver"], "motivos": []})
    assert any(e.startswith("veredicto:") for e in errores)
    datos, _, errores = salida.limpiar("mentor", {"agente": None, "motivo": "nada que cambiar"})
    assert datos["agente"] is None and errores == []
    _, _, errores = salida.limpiar("mentor", {"agente": "lector", "fichero": "skill.md", "texto_nuevo": {"a": 1},
                                             "motivo": "m"})
    assert any(e.startswith("texto_nuevo:") for e in errores)


def test_claves_desconocidas_se_conservan():
    datos, _, errores = salida.limpiar("lector", EXTRACTO | {"motivo": "porque si", "extra": [1, 2]})
    assert datos["extra"] == [1, 2] and datos["motivo"] == "porque si" and errores == []


def test_agente_sin_esquema_devuelve_copia_intacta():
    entrada = {"cualquier": "cosa", "lista": [1, 2]}
    datos, avisos, errores = salida.limpiar("desconocido", entrada)
    assert datos == entrada and datos is not entrada and avisos == [] and errores == []
