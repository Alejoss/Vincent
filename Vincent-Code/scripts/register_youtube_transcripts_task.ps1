# Registra una tarea en Windows Task Scheduler para el pipeline YouTube.
# Ejecutar una vez en PowerShell (como tu usuario):
#   cd E:\Vincent\Vincent-Code\scripts
#   .\register_youtube_transcripts_task.ps1
#
# Por defecto: al iniciar sesión (con retraso), para cuando la PC estaba apagada.
# Requiere: venv, .env con YOUTUBE_API_KEY y OAuth token en cache/youtube_oauth/

param(
    [string]$TaskName = "Vincent - YouTube transcripts",
    [ValidateSet("Logon", "Daily", "Both")]
    [string]$TriggerType = "Logon",
    [int]$LogonDelayMinutes = 3,
    [string]$DailyTime = "03:00",
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$bat = Join-Path $ProjectRoot "scripts\run_youtube_channel_transcripts_scheduled.bat"
if (-not (Test-Path $bat)) {
    Write-Error "No se encuentra: $bat"
    exit 1
}

$venvPy = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "No se encuentra el venv: $venvPy"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $bat `
    -WorkingDirectory $ProjectRoot

$triggers = @()

if ($TriggerType -eq "Logon" -or $TriggerType -eq "Both") {
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    if ($LogonDelayMinutes -gt 0) {
        $logonTrigger.Delay = "PT${LogonDelayMinutes}M"
    }
    $triggers += $logonTrigger
}

if ($TriggerType -eq "Daily" -or $TriggerType -eq "Both") {
    $triggers += New-ScheduledTaskTrigger -Daily -At $DailyTime
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Tarea registrada: $TaskName"
Write-Host "  Script: $bat"
Write-Host "  Logs: $ProjectRoot\logs\youtube_scheduler_task.log"
Write-Host ""
if ($TriggerType -eq "Logon" -or $TriggerType -eq "Both") {
    Write-Host "  Desencadenador: al iniciar sesion (+$LogonDelayMinutes min de retraso)"
}
if ($TriggerType -eq "Daily" -or $TriggerType -eq "Both") {
    Write-Host "  Desencadenador: diario a las $DailyTime (StartWhenAvailable si la PC estaba apagada)"
}
Write-Host ""
Write-Host "Probar ahora manualmente:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host ""
Write-Host "Ver en GUI: Win+R -> taskschd.msc -> buscar '$TaskName'"
Write-Host ""
Write-Host "Opciones:"
Write-Host "  .\register_youtube_transcripts_task.ps1 -TriggerType Daily -DailyTime 08:00"
Write-Host "  .\register_youtube_transcripts_task.ps1 -TriggerType Both"
