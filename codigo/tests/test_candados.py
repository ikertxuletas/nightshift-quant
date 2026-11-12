import pytest

from quant.investigacion import candados


def test_turno_libre_y_fail_open(tmp_path):
    ruta = tmp_path / "x.lock"
    with candados.turno(ruta) as tuvo:
        assert tuvo is True
        esperas = []
        with candados.turno(ruta, espera=12, dormir=esperas.append, reloj=_Reloj(paso=5).tick) as segundo:
            assert segundo is False
        assert len(esperas) >= 2


def test_turno_libera_al_salir(tmp_path):
    ruta = tmp_path / "x.lock"
    with candados.turno(ruta) as tuvo:
        assert tuvo is True
    with candados.turno(ruta, espera=0) as segundo:
        assert segundo is True


def test_turno_libera_al_salir_con_excepcion(tmp_path):
    ruta = tmp_path / "x.lock"
    with pytest.raises(ValueError):
        with candados.turno(ruta) as tuvo:
            assert tuvo is True
            raise ValueError("boom")
    with candados.turno(ruta, espera=0) as segundo:
        assert segundo is True


class _Reloj:
    def __init__(self, paso):
        self.t, self.paso = 0.0, paso

    def tick(self):
        self.t += self.paso
        return self.t
