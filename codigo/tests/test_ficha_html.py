from quant.panel import ficha_html


def test_franjas_de_la_nota():
    assert ficha_html.franja(75) == ("muy alta", "nota-4") and ficha_html.franja(74)[1] == "nota-3"
    assert ficha_html.franja(65)[1] == "nota-2" and ficha_html.franja(64)[1] == "nota-1" and ficha_html.franja(None)[1] == "nota-0"
    assert 'class="circulo nota-4"' in ficha_html.circulo(80) and "–" in ficha_html.circulo(None)


def test_minibarras():
    assert ficha_html.minibarras(None) == ""
    s = ficha_html.minibarras([{"nombre": "<R>", "valor": 8.0}, {"nombre": "C", "valor": 5.0}, {"nombre": "D", "valor": 1.0}])
    assert s.count('class="b-pos"') == 1 and 'class="b-mid"' in s and 'class="b-neg"' in s and "&lt;R&gt;" in s


def _celdas(ops_por_celda):
    return [{"dia": "LMXJVSD"[i % 7], "hora": f"{8 + i // 7:02d}h", "ops": o, "pf": 1.2} for i, o in enumerate(ops_por_celda)]


def test_rejilla_minimo_adaptado():
    s = ficha_html.rejilla(_celdas([6, 4] + [10] * 89), "x")
    assert "6 operaciones" in s and "4 operaciones" not in s and "orientación" in s
    s = ficha_html.rejilla(_celdas([19, 25] + [20] * 58), "x")
    assert "19 operaciones" not in s and "25 operaciones" in s and "orientación" not in s
    assert "No hay franjas" in ficha_html.rejilla(_celdas([2, 3]), "x")


def test_gauge_y_grupos_sin_datos():
    assert "Sin nota" in ficha_html.gauge(None) and "de 100" in ficha_html.gauge(80)
    a = {"n": 30, "g1": {"r_medio": 0.1, "costes_sobre_bruto": 0.5, "bruto_por_op_pts": 3.0, "coste_por_op_pts": 1.5},
         "g2": {"salidas": {"stop": 1.0}, "pts": {"mae_ganadoras": 1, "mae_perdedoras": 2, "mfe": 3, "resultado": -1, "dejado": 4, "stop": 5}},
         "g3": {"peor_racha": 3, "dias_sin_maximo": 400, "ops_semana": 1.5, "dias_con_op": 0.2},
         "g4": {"prob_suerte": 0.2, "t": 0.8, "n": 30, "vecinos": []}, "g5": None, "g6": None, "rejilla": []}
    s = ficha_html.seis_grupos(a)
    assert "faltan los precios diarios" in s and "No se pudo comparar con el SP500" in s and "¿Es real o es suerte?" in s and "13 meses" in s


def test_meses_ultimos_tres():
    meses = {str(y): [0.01] * 12 for y in range(2018, 2026)}
    anual = {str(y): 0.12 for y in range(2018, 2026)}
    assert ficha_html.meses(meses, anual, 3).count("<tr><th scope=\"row\">") == 3 and "2025" in ficha_html.meses(meses, anual, 3)


def _a(p):
    return {"n": 30, "g1": {"r_medio": 0.1, "costes_sobre_bruto": 0.5, "bruto_por_op_pts": 3.0, "coste_por_op_pts": 1.5},
            "g2": {"salidas": {"stop": 1.0}, "pts": {"mae_ganadoras": 1, "mae_perdedoras": 2, "mfe": 3, "resultado": -1, "dejado": 4, "stop": 5}},
            "g3": {"peor_racha": 3, "dias_sin_maximo": 40, "ops_semana": 1.5, "dias_con_op": 0.2},
            "g4": {"prob_suerte": p, "t": 3.0, "n": 30, "vecinos": []},
            "g5": {"tendencia": {"ops": 5, "pf": 1.1}, "lateral": {"ops": 5, "pf": 0.9}, "volatil": {"ops": 5, "pf": 1.35}, "tranquilo": {"ops": 5, "pf": 0.54}},
            "g6": None, "rejilla": []}


def test_suerte_bien_explicada_y_con_cuantas_se_probaron():
    s = ficha_html.seis_grupos(_a(0.0004), probadas=34456)
    assert "&lt;0,1 %" in s and "pura suerte" not in s and "Sin ninguna ventaja" in s
    assert "34.456" in s and "1.723" in s


def test_cuando_funciona_etiquetado():
    s = ficha_html.seis_grupos(_a(0.2))
    assert "Días movidos" in s and "Días tranquilos" in s and "Días laterales" in s and "Días de tendencia" in s
    assert "No se pudo comparar con el SP500" in s


def test_franja_pf_y_casillas():
    assert ficha_html.franja_pf(1.3) == "nota-4" and ficha_html.franja_pf(1.0) == "nota-3"
    assert ficha_html.franja_pf(0.95) == "nota-2" and ficha_html.franja_pf(0.5) == "nota-1" and ficha_html.franja_pf(None) == "nota-0"
    s = ficha_html.casillas([{"criterio": "drawdown", "cumple": True}, {"criterio": "robustez", "cumple": False}])
    assert s.count('class="si"') == 1 and s.count('class="no"') == 1 and "Poco robusta: no cumple" in s


def test_gauge_pf():
    s = ficha_html.gauge_pf(1.0)
    assert 'class="marca-uno"' in s and "Por encima de 1" in s
    assert "Por debajo de 1" in ficha_html.gauge_pf(0.6) and "–" in ficha_html.gauge_pf(None)
