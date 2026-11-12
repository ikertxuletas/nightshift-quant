"""B1: red de seguridad global contra cerrar procesos reales por accidente en la suite.

Este fichero no es test_memoria.py, asi que el fixture autouse de conftest.py se aplica:
memoria.cerrar y memoria.procesos deben ser los stubs prohibidos salvo que un test los
parchee explicitamente.
"""
import pytest

from quant.investigacion import memoria


def test_memoria_procesos_esta_prohibido_por_defecto():
    with pytest.raises(AssertionError, match="memoria.procesos"):
        memoria.procesos()


def test_memoria_cerrar_esta_prohibido_por_defecto():
    with pytest.raises(AssertionError, match="memoria.cerrar"):
        memoria.cerrar("chrome.exe", lambda s: None)


def test_liberar_sin_pasar_listar_ni_cerrar_no_toca_procesos_reales():
    """El escenario de M4: un test que llama a liberar de verdad, sin parchear listar/cerrar,
    con RAM insuficiente e inactividad alta. liberar es fail-open (atrapa la excepcion), pero la
    red de seguridad debe impedir que memoria.procesos real (tasklist) llegue a ejecutarse: el
    resultado queda como un error, no como un cierre real."""
    r = memoria.liberar(999.0, {"inactividad_minutos": 15, "franja_cierre": [0, 24]},
                        libre=lambda: 1.0, inactivo=lambda: 30.0,
                        hora_local=lambda: __import__("datetime").datetime(2026, 1, 1, 3, 0),
                        estado_notificacion=lambda: 0)
    assert r["cerrados"] == []
    assert "memoria.procesos" in r["omitido"]


def test_liberar_se_puede_seguir_parcheando_explicitamente(monkeypatch):
    """Un test que si pasa listar/cerrar sigue funcionando con normalidad pese al fixture."""
    monkeypatch.setattr(memoria, "cerrar", lambda nombre, dormir: None)
    monkeypatch.setattr(memoria, "procesos", lambda: [("chrome.exe", 5.0)])
    r = memoria.liberar(4.0, {"inactividad_minutos": 15, "cerrables": ["chrome.exe"], "franja_cierre": [0, 24]},
                        libre=lambda: 1.0, inactivo=lambda: 30.0,
                        hora_local=lambda: __import__("datetime").datetime(2026, 1, 1, 3, 0),
                        estado_notificacion=lambda: 0, primer_plano=lambda: memoria.SIN_VENTANA)
    assert [c["nombre"] for c in r["cerrados"]] == ["chrome.exe"]


def test_claude_real_prohibido(tmp_path):
    from quant.investigacion import claude_cli
    (tmp_path / "supervisor").mkdir()
    with pytest.raises(AssertionError, match="claude real"):
        claude_cli.chat("haiku", "s", "p", raiz=tmp_path, candado=tmp_path / "c.lock")
