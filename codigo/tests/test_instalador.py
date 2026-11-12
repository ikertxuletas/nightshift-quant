from pathlib import Path

from quant.investigacion import contratos


def test_instalador_define_las_tareas_ocultas():
    texto = Path(__file__).resolve().parents[1].joinpath("instalar_tareas.ps1").read_text(encoding="utf-8")
    assert "Quant_Noche" in texto and "Quant_Revision" in texto
    assert "pythonw.exe" in texto and "python.exe" not in texto.replace("pythonw.exe", "")
    assert '"02:00"' in texto and '"06:15"' in texto
    assert "WakeToRun" in texto and "StartWhenAvailable" in texto and "QUANT_EQUIPO" in texto
    assert "quant.investigacion.noche" in texto and "quant.investigacion.revision --correo" in texto
    assert "Quant_Vigilante" in texto and '"07:30"' in texto and "quant.investigacion.vigilante" in texto
    assert "Start-Process" not in texto
    revision = [l for l in texto.splitlines() if "Quant_Revision" in l and l.startswith("Instalar")][0]
    assert f"New-TimeSpan -Hours {contratos.LIMITE_REVISION_HORAS}" in revision
    noche = [l for l in texto.splitlines() if "Quant_Noche" in l and l.startswith("Instalar")][0]
    horas, minutos = contratos.LIMITE_NOCHE
    assert f"New-TimeSpan -Hours {horas} -Minutes {minutos}" in noche
    assert contratos.MARGEN_EXAMEN_MINUTOS < contratos.LIMITE_REVISION_HORAS * 60
    vigilante = [l for l in texto.splitlines() if "Quant_Vigilante" in l and l.startswith("Instalar")][0]
    hora, minuto = contratos.HORA_VIGILANTE
    assert f'"{hora:02d}:{minuto:02d}"' in vigilante


def test_installer_registers_new_tasks():
    texto = Path(__file__).resolve().parents[1].joinpath("instalar_tareas.ps1").read_text(encoding="utf-8")
    linea = lambda nombre: [l for l in texto.splitlines() if nombre in l and l.startswith("Instalar")][0]
    barrido = linea("Quant_Barrido")
    assert "-m quant.barrido --horas 30" in barrido and "Saturday" in barrido and '"08:00"' in barrido
    assert "New-TimeSpan -Hours 31" in barrido
    demo = linea("Quant_Demo")
    assert "-m quant.demo.pasada" in demo and "New-TimeSpan -Minutes 20" in demo and '"00:15"' in demo
    assert "New-TimeSpan -Hours 1)" in demo and "-RepetitionInterval $cada" in texto
    panel = linea("Quant_Panel")
    assert "-m quant.panel.servidor" in panel and "AtLogOn" in texto and "[TimeSpan]::Zero" in texto
    assert "Panel Quant" in texto and "quant.panel.abrir" in texto and "WorkingDirectory" in texto
    assert "python.exe" not in texto.replace("pythonw.exe", "")
