# Instala las tareas nocturnas de Quant. Ejecutar una vez, a mano, desde PowerShell.
if ($env:QUANT_EQUIPO -and $env:COMPUTERNAME -ne $env:QUANT_EQUIPO) { Write-Output "Solo en $env:QUANT_EQUIPO"; exit 2 }
$raiz = Split-Path -Parent $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$dir = Join-Path $raiz "codigo"
if (-not (Test-Path $py)) { Write-Output "Falta $py"; exit 3 }
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

function Instalar($nombre, $argumentos, $hora, $limite, $dia = $null, $cada = $null, $alIniciar = $false) {
    $accion = New-ScheduledTaskAction -Execute $py -Argument $argumentos -WorkingDirectory $dir
    if ($alIniciar) { $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME }
    elseif ($dia) { $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dia -At $hora }
    else { $trigger = New-ScheduledTaskTrigger -Daily -At $hora }
    if ($cada) {
        $trigger.Repetition = (New-ScheduledTaskTrigger -Once -At $hora -RepetitionInterval $cada `
            -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
    }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit $limite
    if (-not $cada -and -not $alIniciar) { $settings.WakeToRun = $true }
    Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null
}

Instalar "Quant_Noche" "-X utf8 -m quant.investigacion.noche" "02:00" (New-TimeSpan -Hours 4 -Minutes 30)
Instalar "Quant_Revision" "-X utf8 -m quant.investigacion.revision --correo" "06:15" (New-TimeSpan -Hours 2)
Instalar "Quant_Vigilante" "-X utf8 -m quant.investigacion.vigilante" "07:30" (New-TimeSpan -Minutes 15)
Instalar "Quant_Barrido" "-X utf8 -m quant.barrido --horas 30" "08:00" (New-TimeSpan -Hours 31) "Saturday"
Instalar "Quant_Demo" "-X utf8 -m quant.demo.pasada" "00:15" (New-TimeSpan -Minutes 20) $null (New-TimeSpan -Hours 1)
Instalar "Quant_Panel" "-X utf8 -m quant.panel.servidor" "00:00" ([TimeSpan]::Zero) $null $null $true
Instalar "Quant_Asesor" "-X utf8 -m quant.investigacion.asesor" "09:00" (New-TimeSpan -Hours 1) "Sunday"

$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Panel Quant.lnk"))
$acceso.TargetPath = $py
$acceso.Arguments = "-m quant.panel.abrir"
$acceso.WorkingDirectory = $dir
$acceso.IconLocation = "$dir\quant\panel\static\logo.ico,0"
$acceso.Save()
Get-ScheduledTask -TaskName "Quant_*" | Format-Table TaskName, State -AutoSize
