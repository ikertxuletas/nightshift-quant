import json

import pytest

from quant.investigacion import agentes, catalogo, relator

FICHA = {"id": "rsi2-spy", "titulo": "RSI(2) en SPY", "fuente": {"url": "x://y", "cita": "tabla 3"},
         "tipo": "reversion", "forma": "serie_temporal",
         "universo": {"instrumentos": ["SPY"], "plazo": "D1"},
         "entrada": {"largo": {"<": ["RSI(2)", 10]}}, "salida": {"largo": {">": ["close", "SMA(5)"]}},
         "gestion": {}, "estado": "borrador"}

RESULTADO = {"veredicto": "pasa",
             "criterios": [{"criterio": "drawdown", "valor": 0.12, "umbral": 0.2, "sentido": "max", "cumple": True,
                            "distancia": 0.4},
                           {"criterio": "sharpe_fuera", "valor": 0.8, "umbral": 0.5, "sentido": "min", "cumple": True,
                            "distancia": 0.6}],
             "metricas": {"total": {"sharpe": 0.9, "drawdown": 0.12, "cagr": 0.07, "rentabilidad": 0.5,
                                    "operaciones": 140, "acierto": 0.61, "profit_factor": 1.4}},
             "referencias": {"vs_fuente": {"sharpe": -0.3}, "vs_tipo": []}, "avisos": ["con sesgo de supervivencia"]}


def _llamar(respuestas):
    guardadas = list(respuestas)
    enviados = []

    def llamar(modelo, system, prompt, **kw):
        enviados.append({"modelo": modelo, "system": system, "prompt": prompt, "kw": kw})
        return guardadas.pop(0)
    llamar.enviados = enviados
    return llamar


def _con_resultado(tmp_path, veredicto="pasa"):
    con = catalogo.abrir(tmp_path / "c.db")
    doc = catalogo.anadir_documento(con, "arxiv", "u://1", "T1", "2026-01-01", "texto", tmp_path / "documentos")
    ficha_id = catalogo.guardar_ficha(con, doc, FICHA, "aprobada")
    catalogo.guardar_resultado(con, ficha_id, "SPY", veredicto, {**RESULTADO, "veredicto": veredicto})
    return con


def test_ajustes_texto_devuelve_formato_none(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "agentes.json").write_text(json.dumps({"relator": {"modelo": "haiku", "temperatura": 0.3,
                                                                  "formato": "texto"}}),
                                         encoding="utf-8")
    a = agentes.ajustes("relator", config)
    assert a["modelo"] == "haiku"
    assert a["formato"] is None and a["opciones"] == {"temperature": 0.3}


def test_explicar_valla_y_filtra():
    llamar = _llamar(["La estrategia compra cuando el RSI cae.\nEsto garantiza beneficios.\nPasa los criterios."])
    texto = relator.explicar(FICHA, "SPY", RESULTADO, llamar=llamar)
    enviado = llamar.enviados[0]
    assert enviado["kw"]["formato"] is None
    assert enviado["prompt"].count("<<<DOCUMENTO") == 2 and "Ficha:" in enviado["prompt"]
    assert "garantiza" not in texto and "[frase retirada por el filtro]" in texto
    assert texto.splitlines()[0].startswith("La estrategia compra")


def test_explicar_filtra_la_orden_de_invertir():
    llamar = _llamar(["Invierte en SPY cuando el RSI cae."])
    assert relator.explicar(FICHA, "SPY", RESULTADO, llamar=llamar) == relator.RETIRADA


def test_explicar_filtra_solo_la_frase_prohibida_del_parrafo():
    llamar = _llamar(["La estrategia compra cuando el RSI cae. Esto garantiza beneficios. Pasa los criterios."])
    texto = relator.explicar(FICHA, "SPY", RESULTADO, llamar=llamar)
    assert texto == ("La estrategia compra cuando el RSI cae. [frase retirada por el filtro] "
                     "Pasa los criterios.")


def test_procesar_relatos_fila_con_json_corrupto_no_tumba(tmp_path):
    con = _con_resultado(tmp_path, "pasa")
    doc2 = catalogo.anadir_documento(con, "arxiv", "u://2", "T2", "2026-01-01", "t", tmp_path / "documentos")
    f2 = catalogo.guardar_ficha(con, doc2, FICHA, "aprobada")
    catalogo.guardar_resultado(con, f2, "SPY", "pasa", {**RESULTADO, "veredicto": "pasa"})
    con.execute("UPDATE resultados SET json = 'no es json' WHERE id = 1")
    con.commit()
    llamar = _llamar(["Explicacion llana."])
    resumen = relator.procesar_relatos(con, llamar=llamar)
    assert resumen == {"relatados": 1, "errores": 1, "omitidos": 0}
    assert catalogo.relato(con, 1) is None
    assert catalogo.relato(con, 2) == "Explicacion llana."


def test_procesar_relatos_omitidos_por_tiempo(tmp_path):
    con = _con_resultado(tmp_path, "pasa")
    llamar = _llamar(["Explicacion llana."])
    resumen = relator.procesar_relatos(con, llamar=llamar, hasta=0, reloj=lambda: 1)
    assert resumen == {"relatados": 0, "errores": 0, "omitidos": 1}


def test_procesar_relatos_solo_pasa_y_dudosa(tmp_path):
    con = _con_resultado(tmp_path, "pasa")
    doc2 = catalogo.anadir_documento(con, "arxiv", "u://2", "T2", "2026-01-01", "t", tmp_path / "documentos")
    f2 = catalogo.guardar_ficha(con, doc2, FICHA, "aprobada")
    catalogo.guardar_resultado(con, f2, "SPY", "no_pasa", {**RESULTADO, "veredicto": "no_pasa"})
    llamar = _llamar(["Explicacion llana."])
    resumen = relator.procesar_relatos(con, llamar=llamar)
    assert resumen == {"relatados": 1, "errores": 0, "omitidos": 0}
    assert catalogo.relato(con, 1) == "Explicacion llana."
    assert catalogo.resultados_sin_relato(con) == []


def test_procesar_relatos_error_no_tumba(tmp_path):
    con = _con_resultado(tmp_path, "dudosa")

    def rompe(*a, **k):
        raise agentes.local.ErrorModelo("caido")
    resumen = relator.procesar_relatos(con, llamar=rompe)
    assert resumen["errores"] == 1 and catalogo.relato(con, 1) is None


def test_informe_secciones(tmp_path):
    con = _con_resultado(tmp_path, "pasa")
    catalogo.guardar_relato(con, 1, "Compra barato y vende en la media.")
    doc2 = catalogo.anadir_documento(con, "arxiv", "u://2", "T2", "2026-01-01", "t", tmp_path / "documentos")
    f2 = catalogo.guardar_ficha(con, doc2, {**FICHA, "titulo": "Otra"}, "aprobada")
    catalogo.guardar_resultado(con, f2, "US500", "pendiente_datos", {"veredicto": "pendiente_datos",
                                                                     "motivo": "faltan 73 dias"})
    ruta = relator.informe(con, tmp_path, "20260917")
    texto = ruta.read_text(encoding="utf-8")
    assert ruta.name == "informe_20260917.md"
    assert "Candidata no significa rentable" in texto
    for seccion in ("## Candidatas", "## Dudosas", "## No pasan", "## Pendientes de datos", "## Fichas invalidas",
                    "## Catalogo"):
        assert seccion in texto
    assert "RSI(2) en SPY" in texto and "| drawdown | 0.12 | 0.2 | si |" in texto
    assert "Compra barato" in texto and "faltan 73 dias" in texto
    assert texto.index("## Dudosas") < texto.index("(ninguna)")
