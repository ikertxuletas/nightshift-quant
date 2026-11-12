import json

from quant.investigacion import catalogo, diagnostico


def _noche(raiz, fecha, fallo=None, canario=True, revision="ok", correo=0, memoria=None, ollama=None):
    etapas = {"investigar": {"inicio": 0, "segundos": 1400,
                             "resultado": {"codigo": 1, "fallo": fallo} if fallo else {"codigo": 0}},
              "canario": {"inicio": 1400, "segundos": 420,
                          "resultado": {"ok": True, "pasos": {}} if canario else
                          {"ok": False, "pasos": {}, "fallo": "canario: formalizador: forma='transversal'"}},
              "copia": {"inicio": 1900, "segundos": 1, "resultado": {"omitido": "sin tiempo"}}}
    parte = {"fecha": fecha, "inicio": "x", "desde": "2026-09-18T00:00:05+00:00", "fin_previsto": "x",
             "fin_real": "x", "equipo": "PRINCIPAL", "etapas": etapas, "catalogo": {}, "corte": False,
             "errores": int(bool(fallo)) + int(not canario)}
    if memoria is not None:
        parte["memoria"] = memoria
    if ollama is not None:
        parte["ollama"] = ollama
    (raiz / "informes").mkdir(exist_ok=True)
    (raiz / "informes" / f"parte_{fecha}.json").write_text(json.dumps(parte), encoding="utf-8")
    if revision:
        (raiz / "supervisor").mkdir(exist_ok=True)
        (raiz / "supervisor" / f"revision_{fecha}.json").write_text(json.dumps(
            {"fecha": fecha, "estado": revision, "resumen": "", "correo": "", "criterios": "", "paquete_bytes": 1,
             "notas": {}, "acciones": [], "error": ""}), encoding="utf-8")
    (raiz / "registro").mkdir(exist_ok=True)
    (raiz / "registro" / f"revision_{fecha}.log").write_text(json.dumps({"correo": correo}) + "\n", encoding="utf-8")


def test_noche_resumida(tmp_path):
    _noche(tmp_path, "20260918", fallo="TypeError: lista en set", canario=False, revision="aviso", correo=1)
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["etapas"]["investigar"] == {"s": 1400, "fallo": "TypeError: lista en set", "omitido": None}
    assert n["etapas"]["copia"]["omitido"] == "sin tiempo"
    assert n["canario"] == "falla: formalizador" and n["revision"] == "aviso" and n["correo"] is False
    assert n["errores"] == 2 and n["contrato"] == []
    assert n["cerrados"] == 0


def test_noche_muestra_errores_de_contenido_sin_fallo(tmp_path):
    """codigo 0 con errores_contenido: la etapa no fallo, pero la cifra no debe perderse."""
    etapas = {"investigar": {"inicio": 0, "segundos": 1400,
                             "resultado": {"codigo": 0, "errores": 2, "errores_contenido": 2, "errores_infra": 0}}}
    parte = {"fecha": "20260918", "inicio": "x", "desde": "2026-09-18T00:00:05+00:00", "fin_previsto": "x",
             "fin_real": "x", "equipo": "PRINCIPAL", "etapas": etapas, "catalogo": {}, "corte": False, "errores": 2}
    (tmp_path / "informes").mkdir(exist_ok=True)
    (tmp_path / "informes" / "parte_20260918.json").write_text(json.dumps(parte), encoding="utf-8")
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["etapas"]["investigar"] == {"s": 1400, "fallo": None, "omitido": None, "errores_contenido": 2}
    assert "investigar=2 errores de contenido" in diagnostico._linea_noche(n)


def test_noche_sin_errores_de_contenido_no_anade_la_clave(tmp_path):
    _noche(tmp_path, "20260918")
    n = diagnostico.noche(tmp_path, "20260918")
    assert "errores_contenido" not in n["etapas"]["investigar"]
    assert "errores de contenido" not in diagnostico._linea_noche(n)


def test_noche_muestra_cerrados_cuando_hay(tmp_path):
    memoria = [{"cerrados": [{"nombre": "chrome.exe", "gb": 2.0}]},
              {"cerrados": [{"nombre": "discord.exe", "gb": 0.5}, {"nombre": "spotify.exe", "gb": 0.3}]},
              {"cerrados": [], "omitido": "usuario activo"}]
    _noche(tmp_path, "20260918", memoria=memoria)
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["cerrados"] == 3
    assert "cerrados=3" in diagnostico._linea_noche(n)


def test_noche_sin_cerrados_no_muestra_la_cifra(tmp_path):
    _noche(tmp_path, "20260918")
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["cerrados"] == 0
    assert "cerrados=" not in diagnostico._linea_noche(n)


def test_noche_muestra_ollama_arrancado_cuando_tuvo_que_arrancar(tmp_path):
    _noche(tmp_path, "20260918", ollama={"arrancado": True, "disponible": True})
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["ollama"] is True
    assert "ollama=arrancado" in diagnostico._linea_noche(n)


def test_noche_sin_ollama_arrancado_no_lo_muestra(tmp_path):
    _noche(tmp_path, "20260918", ollama={"arrancado": False, "disponible": True})
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["ollama"] is False
    assert "ollama=" not in diagnostico._linea_noche(n)


def test_noche_sin_clave_ollama_no_la_muestra(tmp_path):
    _noche(tmp_path, "20260918")
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["ollama"] is False
    assert "ollama=" not in diagnostico._linea_noche(n)


def test_noche_muestra_sin_motor_cuando_falta_llama_server(tmp_path):
    _noche(tmp_path, "20260918", ollama={"arrancado": False, "disponible": True, "motor": False})
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["motor_ollama"] is False
    assert "ollama=SIN MOTOR" in diagnostico._linea_noche(n)


def test_noche_con_motor_no_muestra_sin_motor(tmp_path):
    _noche(tmp_path, "20260918", ollama={"arrancado": False, "disponible": True, "motor": True})
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["motor_ollama"] is True
    assert "SIN MOTOR" not in diagnostico._linea_noche(n)


def test_noche_sin_clave_motor_no_muestra_sin_motor(tmp_path):
    _noche(tmp_path, "20260918")
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["motor_ollama"] is None
    assert "SIN MOTOR" not in diagnostico._linea_noche(n)


def test_noche_sin_parte(tmp_path):
    n = diagnostico.noche(tmp_path, "20260918")
    assert n["etapas"] == {} and n["contrato"] and n["revision"] is None and n["correo"] is False


def test_resumen_y_texto_caben_en_un_kilobyte_por_noche(tmp_path):
    for dia in range(10, 19):
        _noche(tmp_path, f"202609{dia}", fallo="ErrorAgente: " + "x" * 300 if dia % 2 else None)
    con = catalogo.abrir(tmp_path / "catalogo.db")
    catalogo.registrar_cambio_skill(con, "critico", "nota", 0.6, 0.7, True, origen="supervisor")
    catalogo.registrar_cambio_skill(con, "lector", "cambio", 0.8, 0.7, False, origen="mentor")
    con.close()
    (tmp_path / "examen").mkdir()
    (tmp_path / "examen" / "notas.json").write_text('{"critico": {"nota": 0.7, "casos": 5}}', encoding="utf-8")
    sistema = {"procesos": [], "tareas": {"Quant_Noche": {"estado": "Ready", "ultima": "2026-09-18T02:00:00"}}}
    r = diagnostico.resumen(tmp_path, noches=7, sistema=sistema)
    assert [n["fecha"] for n in r["noches"]] == [f"202609{d}" for d in range(18, 11, -1)]
    assert r["cambios"] == {"supervisor": {"aceptados": 1, "rechazados": 0}, "mentor": {"aceptados": 0, "rechazados": 1}}
    assert r["notas"] == {"critico": 0.7} and r["tareas"]["Quant_Noche"]["estado"] == "Ready"
    texto = diagnostico.texto(r)
    assert len(texto.encode("utf-8")) <= 1024 * 8 and "20260918" in texto and "critico 0.7" in texto


def test_main_json_y_solo_lectura(tmp_path, capsys):
    _noche(tmp_path, "20260918")
    assert diagnostico.main(["--raiz", str(tmp_path), "--noches", "1", "--json"], sistema={"procesos": [], "tareas": {}}) == 0
    assert json.loads(capsys.readouterr().out)["noches"][0]["fecha"] == "20260918"
    assert not (tmp_path / "catalogo.db").exists()


def test_recorte_por_bytes_no_por_caracteres(tmp_path):
    for dia in range(10, 19):
        _noche(tmp_path, f"202609{dia}", fallo="ñ€" * 150 if dia % 2 else None)
    r = diagnostico.resumen(tmp_path, noches=9, sistema={"procesos": [], "tareas": {}})
    texto = diagnostico.texto(r)
    texto.encode("utf-8").decode("utf-8")
    assert len(texto.encode("utf-8")) <= 1024 * 10
    for n in r["noches"]:
        for e in n["etapas"].values():
            if e["fallo"]:
                assert len(e["fallo"].encode("utf-8")) <= diagnostico.MAX_MOTIVO


def test_catalogo_aisla_cada_consulta(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "catalogo.db")
    con.execute("CREATE TABLE skills_cambios (id INTEGER PRIMARY KEY, agente TEXT, aceptado INTEGER)")
    con.execute("CREATE TABLE documentos (id INTEGER PRIMARY KEY, etapa TEXT, error TEXT)")
    con.execute("INSERT INTO documentos (etapa, error) VALUES ('nuevo', NULL)")
    con.execute("INSERT INTO documentos (etapa, error) VALUES ('error', 'fallo de prueba')")
    con.commit()
    con.close()
    r = diagnostico._catalogo(tmp_path)
    assert r["cambios"] == {}
    assert r["documentos"] == {"nuevo": 1, "error": 1}


def _canario(raiz, fecha, resultado):
    _noche(raiz, fecha)
    ruta = raiz / "informes" / f"parte_{fecha}.json"
    parte = json.loads(ruta.read_text(encoding="utf-8"))
    parte["etapas"]["canario"]["resultado"] = resultado
    ruta.write_text(json.dumps(parte), encoding="utf-8")
    return diagnostico.noche(raiz, fecha)["canario"]


def test_canario_omitido_ok_y_fallo_sin_forma_de_canario(tmp_path):
    assert _canario(tmp_path, "20260918", {"omitido": "sin tiempo", "pasos": {}}) == "omitido: sin tiempo"
    assert _canario(tmp_path, "20260918", {"ok": True, "pasos": {}}) == "ok"
    assert _canario(tmp_path, "20260918", {"ok": False, "fallo": "canario: critico: veredicto='x'"}) == "falla: critico"
    error = "RuntimeError: " + "y" * 200
    salida = _canario(tmp_path, "20260918", {"error": error})
    assert salida.startswith("falla: RuntimeError: yyy") and len(salida.encode("utf-8")) <= 7 + diagnostico.MAX_MOTIVO


def test_catalogo_cuenta_avisos_del_formalizador(tmp_path):
    con = catalogo.abrir(tmp_path / "catalogo.db")
    doc = catalogo.anadir_documento(con, "arxiv", "u://1", "T", "2026-09-17", "t", tmp_path / "documentos")
    catalogo.guardar_extracto(con, doc, {"operable": "si", "avisos_salida": ["plazo normalizado: 'x' -> 'D1'"],
                                         "avisos_formalizador": ["expresable: texto tomado como booleano"]})
    con.close()
    normalizaciones = dict(diagnostico._catalogo(tmp_path)["normalizaciones"])
    assert normalizaciones == {"plazo normalizado": 1, "expresable": 1}


def _con_claude(raiz, fecha, claude):
    ruta = raiz / "informes" / f"parte_{fecha}.json"
    parte = json.loads(ruta.read_text(encoding="utf-8"))
    parte["claude"] = claude
    ruta.write_text(json.dumps(parte), encoding="utf-8")


def test_cabecera_claude(tmp_path):
    _noche(tmp_path, "20260918")
    _con_claude(tmp_path, "20260918", {"exe": "claude", "sesion": True, "llamadas": 37})
    assert "claude=37" in diagnostico._linea_noche(diagnostico.noche(tmp_path, "20260918"))


def test_cabecera_claude_caducada(tmp_path):
    _noche(tmp_path, "20260918")
    _con_claude(tmp_path, "20260918", {"exe": "claude", "sesion": False, "llamadas": 0})
    assert "claude=SESION CADUCADA" in diagnostico._linea_noche(diagnostico.noche(tmp_path, "20260918"))


def test_cabecera_sin_claude_no_lo_muestra(tmp_path):
    _noche(tmp_path, "20260918")
    assert "claude=" not in diagnostico._linea_noche(diagnostico.noche(tmp_path, "20260918"))
