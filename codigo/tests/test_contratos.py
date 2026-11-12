import json
from datetime import datetime, timezone

from quant.investigacion import contratos, tiempos


def _parte():
    return {"fecha": "20260917", "inicio": "2026-09-17T02:00:09", "desde": "2026-09-17T00:00:09+00:00",
            "fin_previsto": "2026-09-17T06:00:00", "fin_real": "2026-09-17T04:42:00", "equipo": "PRINCIPAL",
            "etapas": {"precios": {"inicio": 0, "segundos": 12, "resultado": {"codigo": 0}},
                       "investigar": {"inicio": 12, "segundos": 30, "resultado": {"codigo": 0}, "ocupado": "juego"}},
            "catalogo": {"documentos": {"nuevo": 3}}, "corte": False, "errores": 0}


def _revision():
    return {"fecha": "20260917", "estado": "aviso", "resumen": "r", "correo": "c", "criterios": "",
            "paquete_bytes": 4331, "notas": {"critico": {"pendiente": "p"}},
            "acciones": [{"tipo": "reencolar", "hecho": True}], "error": ""}


def test_parte_y_revision_validos():
    assert contratos.validar_parte(_parte()) == []
    assert contratos.validar_revision(_revision()) == []
    en_curso = _parte() | {"fin_real": None}
    assert contratos.validar_parte(en_curso) == []


def test_validar_parte_acepta_memoria_lista_y_es_opcional():
    assert contratos.validar_parte(_parte() | {"memoria": []}) == []
    assert contratos.validar_parte(_parte() | {"memoria": [{"cerrados": []}]}) == []
    assert contratos.validar_parte(_parte()) == []


def test_validar_parte_rechaza_memoria_que_no_es_lista():
    errores = contratos.validar_parte(_parte() | {"memoria": "no es lista"})
    assert any(e.startswith("memoria:") for e in errores)


def test_validar_parte_nombra_el_campo():
    malo = _parte()
    malo["errores"] = True
    malo["desde"] = "2026-09-17T02:00:09"
    malo["etapas"]["investigar"]["resultado"] = ["lista"]
    malo["etapas"]["inventada"] = {"inicio": 0, "segundos": 0, "resultado": {}}
    del malo["corte"]
    errores = contratos.validar_parte(malo)
    assert any(e.startswith("errores:") for e in errores)
    assert any(e.startswith("desde:") and "zona" in e for e in errores)
    assert any(e.startswith("etapas.investigar.resultado:") for e in errores)
    assert any(e.startswith("etapas.inventada:") for e in errores)
    assert any(e.startswith("corte:") and "falta" in e for e in errores)
    assert contratos.validar_parte(["no", "objeto"]) == ["parte: no es un objeto"]


def test_validar_revision_nombra_el_campo():
    mala = _revision() | {"estado": "verde", "notas": ["x"], "acciones": [1]}
    errores = contratos.validar_revision(mala)
    assert any(e.startswith("estado:") for e in errores)
    assert any(e.startswith("notas:") for e in errores)
    assert any(e.startswith("acciones[0]:") for e in errores)


def test_hay_fallo():
    assert contratos.hay_fallo({"codigo": 0}) is None
    assert contratos.hay_fallo({"omitido": "sin tiempo"}) is None
    assert contratos.hay_fallo({"codigo": 1, "fallo": "TypeError: x"}) == "TypeError: x"
    assert contratos.hay_fallo({"error": "e", "fallo": "f"}) == "e"
    assert contratos.hay_fallo({"codigo": 3}) == "codigo 3"
    assert contratos.hay_fallo(["lista"]) is None


def test_leer_parte_nunca_lanza(tmp_path):
    datos, errores = contratos.leer_parte(tmp_path, "20260917")
    assert datos is None and "no existe" in errores[0]
    carpeta = tmp_path / "informes"
    carpeta.mkdir()
    ruta = carpeta / "parte_20260917.json"
    ruta.write_text("{roto", encoding="utf-8")
    datos, errores = contratos.leer_parte(tmp_path, "20260917")
    assert datos is None and "no se puede leer" in errores[0]
    ruta.write_text("[1, 2]", encoding="utf-8")
    datos, errores = contratos.leer_parte(tmp_path, "20260917")
    assert datos is None and errores == ["parte: no es un objeto"]
    ruta.write_text(json.dumps(_parte() | {"errores": "dos"}), encoding="utf-8")
    datos, errores = contratos.leer_parte(tmp_path, "20260917")
    assert datos["fecha"] == "20260917" and any(e.startswith("errores:") for e in errores)
    ruta.write_text(json.dumps(_parte()), encoding="utf-8")
    assert contratos.leer_parte(tmp_path, "20260917") == (_parte(), [])


def test_leer_revision(tmp_path):
    datos, errores = contratos.leer_revision(tmp_path, "20260917")
    assert datos is None and "no existe" in errores[0]
    carpeta = tmp_path / "supervisor"
    carpeta.mkdir()
    (carpeta / "revision_20260917.json").write_text(json.dumps(_revision()), encoding="utf-8")
    assert contratos.leer_revision(tmp_path, "20260917") == (_revision(), [])


def test_existe_parte(tmp_path):
    assert contratos.existe_parte(tmp_path, "20260917") is False
    carpeta = tmp_path / "informes"
    carpeta.mkdir()
    (carpeta / "parte_20260917.json").write_text("{roto", encoding="utf-8")
    assert contratos.existe_parte(tmp_path, "20260917") is True


def test_sanear_recorta_y_quita_rutas_de_usuario():
    largo = "x" * 200
    datos = {"a": largo, "b": [{"ruta": r"C:\Users\usuario\OneDrive\Quant"}], "n": 3, "c": None}
    limpio = contratos.sanear(datos)
    assert len(limpio["a"]) == 81 and limpio["a"].endswith("…")
    assert limpio["b"][0]["ruta"] == r"~\OneDrive\Quant"
    assert limpio["n"] == 3 and limpio["c"] is None and datos["a"] == largo


def test_guardar_real_conserva_las_ultimas(tmp_path):
    for dia in range(1, 14):
        ruta = contratos.guardar_real(tmp_path, "parte", _parte() | {"fecha": f"202609{dia:02d}"}, conservar=10)
    carpeta = tmp_path / "codigo" / "tests" / "reales"
    nombres = sorted(p.name for p in carpeta.glob("parte_*.json"))
    assert len(nombres) == 10 and nombres[0] == "parte_20260904.json" and ruta.name == "parte_20260913.json"
    assert contratos.guardar_real(tmp_path, "inventado", {}) is None


def test_guardar_real_no_poda_migradas_ni_semillas(tmp_path):
    carpeta = tmp_path / "codigo" / "tests" / "reales"
    carpeta.mkdir(parents=True)
    (carpeta / "parte_20260101.json").write_text(json.dumps(_parte() | {"fecha": "20260101", "migrado": True}),
                                                 encoding="utf-8")
    contratos.guardar_real(tmp_path, "parte", _parte(), conservar=3)
    for dia in range(1, 8):
        contratos.guardar_real(tmp_path, "parte", _parte() | {"fecha": f"202610{dia:02d}"}, conservar=3)
    nombres = sorted(p.name for p in carpeta.glob("parte_*.json"))
    assert nombres == ["parte_20260101.json", "parte_20260917.json", "parte_20261005.json",
                       "parte_20261006.json", "parte_20261007.json"]


def test_guardar_real_rechaza_fecha_no_valida(tmp_path):
    for fecha in (r"..\..\fuera", "../fuera", None, 20260917):
        datos = _parte() | ({"fecha": fecha} if fecha is not None else {})
        if fecha is None:
            del datos["fecha"]
        assert contratos.guardar_real(tmp_path, "parte", datos) is None
    assert not list(tmp_path.rglob("*fuera*"))


def test_fecha_local_y_ahora_utc():
    assert tiempos.fecha_local(datetime(2026, 9, 17, 2, 0)) == "20260917"
    con_zona = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    assert tiempos.fecha_local(con_zona) == con_zona.astimezone().strftime("%Y%m%d")
    assert tiempos.ahora_utc().tzinfo is not None


def test_contratos_etapas_include_demo():
    assert contratos.ETAPAS[contratos.ETAPAS.index("canario") + 1] == "demo"


def test_contratos_laboratorio_va_el_ultimo():
    assert contratos.ETAPAS[-1] == "laboratorio"
