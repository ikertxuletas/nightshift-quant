import json
from datetime import date
from pathlib import Path

import pandas as pd

from quant import actualizar, datos

UNI = {"instrumentos": {
    "EURUSD": {"clase": "forex", "fuente": "dukascopy", "simbolo": "EURUSD", "divisor": 100000, "desde": "2024-01-01"},
    "SPY": {"clase": "accion", "fuente": "yahoo", "simbolo": "SPY", "desde": "1993-01-01"},
}}


def _raiz(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "universo.json").write_text(json.dumps(UNI), encoding="utf-8")
    return tmp_path


def _fuente_que_guarda(llamadas):
    def fuente(instrumento, info, contexto):
        llamadas.append((instrumento, contexto["hasta"], contexto["max_dias"]))
        df = pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=20, freq="1D"), "open": 1.0, "high": 1.0,
                           "low": 1.0, "close": 1.0, "volume": 1.0})
        datos.guardar(instrumento, "D1", df, contexto["datos"])
        return {"instrumento": instrumento, "velas": 20, "error": None}
    return fuente


def test_recorre_universo_y_registra(tmp_path, capsys):
    raiz, llamadas = _raiz(tmp_path), []
    f = _fuente_que_guarda(llamadas)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--max-dias", "7"],
                             fuentes={"dukascopy": f, "yahoo": f}, sesion=object())
    assert codigo == 0
    assert sorted(llamadas) == [("EURUSD", date(2024, 5, 10), 7), ("SPY", date(2024, 5, 10), 7)]
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["hasta"] == "2024-05-10" and ultimo["errores"] == 0 and len(ultimo["instrumentos"]) == 2
    assert (raiz / "registro" / "actualizar_20240510.log").read_text(encoding="utf-8").count("\n") == 2
    assert set(json.loads((raiz / "datos" / "_calidad.json").read_text(encoding="utf-8"))) == {"EURUSD", "SPY"}
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["errores"] == 0


def test_error_de_una_fuente_no_para_el_resto(tmp_path):
    raiz, llamadas = _raiz(tmp_path), []
    def rota(instrumento, info, contexto):
        raise RuntimeError("caida")
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10"],
                             fuentes={"dukascopy": rota, "yahoo": _fuente_que_guarda(llamadas)}, sesion=object())
    assert codigo == 1 and [l[0] for l in llamadas] == ["SPY"]
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["errores"] == 1 and "RuntimeError: caida" in ultimo["instrumentos"][0]["error"]


def test_filtros_solo_y_fuente(tmp_path):
    raiz = _raiz(tmp_path)
    l1, l2 = [], []
    actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--solo", "SPY"],
                    fuentes={"dukascopy": _fuente_que_guarda(l1), "yahoo": _fuente_que_guarda(l1)}, sesion=object())
    actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--fuente", "dukascopy"],
                    fuentes={"dukascopy": _fuente_que_guarda(l2), "yahoo": _fuente_que_guarda(l2)}, sesion=object())
    assert [l[0] for l in l1] == ["SPY"] and [l[0] for l in l2] == ["EURUSD"]


def test_hasta_por_defecto_es_ayer(tmp_path):
    raiz, llamadas = _raiz(tmp_path), []
    f = _fuente_que_guarda(llamadas)
    actualizar.main(["--raiz", str(raiz), "--solo", "SPY"], fuentes={"dukascopy": f, "yahoo": f},
                    sesion=object(), hoy=date(2024, 5, 11))
    assert llamadas[0][1] == date(2024, 5, 10)


def test_max_minutos_omite_el_resto(tmp_path):
    raiz, llamadas = _raiz(tmp_path), []
    f = _fuente_que_guarda(llamadas)
    tiempos = iter([0.0, 0.0, 120.0, 120.0, 120.0])
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--max-minutos", "1"],
                             fuentes={"dukascopy": f, "yahoo": f}, sesion=object(), reloj=lambda: next(tiempos))
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    assert codigo == 0 and len(llamadas) == 1
    assert ultimo["instrumentos"][1]["omitido"] == "tiempo agotado"


def test_max_minutos_registra_los_omitidos_en_el_log(tmp_path):
    raiz, llamadas = _raiz(tmp_path), []
    f = _fuente_que_guarda(llamadas)
    tiempos = iter([0.0, 0.0, 120.0, 120.0, 120.0])
    actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--max-minutos", "1"],
                    fuentes={"dukascopy": f, "yahoo": f}, sesion=object(), reloj=lambda: next(tiempos))
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    log = (raiz / "registro" / "actualizar_20240510.log").read_text(encoding="utf-8")
    assert log.count("\n") == len(ultimo["instrumentos"]) == 2
    assert "tiempo agotado" in log


def test_max_minutos_pasa_limite_por_contexto(tmp_path):
    raiz, llamadas = _raiz(tmp_path), []
    limites = []
    def f(instrumento, info, contexto):
        limites.append(contexto.get("limite"))
        return _fuente_que_guarda(llamadas)(instrumento, info, contexto)
    actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--max-minutos", "5"],
                    fuentes={"dukascopy": f, "yahoo": f}, sesion=object(), reloj=lambda: 100.0)
    assert limites == [400.0, 400.0]


def test_sin_max_minutos_no_hay_limite_en_contexto(tmp_path):
    raiz, llamadas = _raiz(tmp_path), []
    limites = []
    def f(instrumento, info, contexto):
        limites.append(contexto.get("limite"))
        return _fuente_que_guarda(llamadas)(instrumento, info, contexto)
    actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10"],
                    fuentes={"dukascopy": f, "yahoo": f}, sesion=object())
    assert limites == [None, None]


def test_hasta_mal_formado_termina_con_mensaje_claro(tmp_path, capsys):
    raiz = _raiz(tmp_path)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "no-es-una-fecha"], fuentes={}, sesion=object())
    assert codigo == 2
    assert capsys.readouterr().err.strip() != ""


def test_fallo_de_disco_al_crear_registro_termina_con_mensaje_claro(tmp_path, monkeypatch, capsys):
    raiz = _raiz(tmp_path)
    original = Path.mkdir

    def rota(self, *a, **k):
        if self.name == "registro":
            raise OSError("disco lleno")
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", rota)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10"], fuentes={}, sesion=object())
    assert codigo == 2
    assert capsys.readouterr().err.strip() != ""


def test_fallo_al_abrir_el_log_termina_con_mensaje_claro(tmp_path, monkeypatch, capsys):
    raiz, llamadas = _raiz(tmp_path), []
    original_open = open

    def rota(archivo, *a, **k):
        if str(archivo).endswith(".log"):
            raise OSError("sin permiso")
        return original_open(archivo, *a, **k)

    monkeypatch.setattr("builtins.open", rota)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10"],
                             fuentes={"dukascopy": _fuente_que_guarda(llamadas), "yahoo": _fuente_que_guarda(llamadas)},
                             sesion=object())
    assert codigo == 2
    assert capsys.readouterr().err.strip() != ""


def test_universo_cargar_falla_devuelve_informe_minimo(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)

    def rota(config=None):
        raise ValueError("universo corrupto")

    monkeypatch.setattr(actualizar.universo, "cargar", rota)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10"], fuentes={}, sesion=object())
    assert codigo == 2
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["hasta"] == "2024-05-10"
    assert ultimo["instrumentos"] == []
    assert ultimo["errores"] == 1
    assert ultimo["bloqueados"] == []
    assert "ValueError: universo corrupto" == ultimo["fallo_general"]


def test_calidad_revisar_todo_falla(tmp_path, monkeypatch):
    raiz, llamadas = _raiz(tmp_path), []
    f = _fuente_que_guarda(llamadas)

    def rota(uni, raiz, solo=None):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(actualizar.calidad, "revisar_todo", rota)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10"],
                             fuentes={"dukascopy": f, "yahoo": f}, sesion=object())
    assert codigo == 1
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    assert ultimo["bloqueados"] == []
    assert "RuntimeError: disco lleno" == ultimo["error_calidad"]


def test_refrescar_acciones_falla_continua_con_universo_existente(tmp_path, monkeypatch):
    raiz, llamadas = _raiz(tmp_path), []
    f = _fuente_que_guarda(llamadas)

    def rota(config=None):
        raise OSError("sin red")

    monkeypatch.setattr(actualizar.universo, "refrescar_acciones", rota)
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", "--refrescar-acciones"],
                             fuentes={"dukascopy": f, "yahoo": f}, sesion=object())
    assert codigo == 0
    assert sorted(l[0] for l in llamadas) == ["EURUSD", "SPY"]
    ultimo = json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))
    assert "OSError: sin red" == ultimo["refresco_acciones"]


def _raiz_100(tmp_path):
    uni = {"instrumentos": {f"I{n:03d}": {"clase": "accion", "fuente": "yahoo", "simbolo": f"I{n}", "desde": "2024-01-01"}
                            for n in range(100)}}
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "universo.json").write_text(json.dumps(uni), encoding="utf-8")
    return tmp_path


def _correr_con_fallos(tmp_path, fallan, extra=()):
    raiz = _raiz_100(tmp_path)

    def fuente(instrumento, info, contexto):
        if instrumento in fallan:
            raise RuntimeError("caida")
        return {"instrumento": instrumento, "velas": 1, "error": None}
    codigo = actualizar.main(["--raiz", str(raiz), "--hasta", "2024-05-10", *extra],
                             fuentes={"yahoo": fuente}, sesion=object())
    return codigo, json.loads((raiz / "registro" / "actualizar_ultimo.json").read_text(encoding="utf-8"))


def test_few_errors_return_zero(tmp_path):
    codigo, ultimo = _correr_con_fallos(tmp_path, {"I000", "I001", "I002"})
    assert codigo == 0 and ultimo["errores"] == 3 and ultimo["criticos_con_error"] == []


def test_many_errors_return_one(tmp_path):
    codigo, _ = _correr_con_fallos(tmp_path, {f"I{n:03d}" for n in range(6)})
    assert codigo == 1


def test_critical_error_returns_one(tmp_path):
    codigo, ultimo = _correr_con_fallos(tmp_path, {"I050"}, ["--criticos", "I050", "I051"])
    assert codigo == 1 and ultimo["criticos_con_error"] == ["I050"]
