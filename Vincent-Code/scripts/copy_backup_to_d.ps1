# Copia carpetas seleccionadas de E: y F: a D: antes de retirar el disco.
# No incluye Videos, Podcasts ni Musica de F:.
#
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\copy_backup_to_d.ps1 -PreviewOnly
#   .\copy_backup_to_d.ps1 -WhatIf
#   .\copy_backup_to_d.ps1
#
# Destino por defecto: D:\Backup-Offsite

param(
    [string]$DestRoot = "D:\Backup-Offsite",
    [string]$LogFile = "",
    [switch]$WhatIf,
    [switch]$PreviewOnly
)

function Resolve-Folder {
    param(
        [string]$DriveRoot,
        [string]$Pattern
    )

    if (-not (Test-Path -LiteralPath $DriveRoot)) { return $null }

    $match = Get-ChildItem -LiteralPath $DriveRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $Pattern } |
        Select-Object -First 1

    if ($match) { return $match.FullName }
    return $null
}

function Get-FolderSizeGB {
    param([string]$Path)

    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum

    if ($null -eq $sum) { return 0.0 }
    return [math]::Round($sum / 1GB, 2)
}

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR", "OK")]
        [string]$Level = "INFO"
    )

    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8

    switch ($Level) {
        "ERROR" { Write-Host $line -ForegroundColor Red }
        "WARN"  { Write-Host $line -ForegroundColor Yellow }
        "OK"    { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line }
    }
}

# --- Definir origenes ---
$ucroniaSubs = Resolve-Folder -DriveRoot "F:\" -Pattern "Ucronia Subtitlos*"

$copyPlan = @(
    @{ Name = "Buho Serpiente";          Source = "E:\Buho Serpiente" },
    @{ Name = "Arte Propio";              Source = "E:\Arte Propio" },
    @{ Name = "Envy PC";                  Source = "F:\Envy PC" },
    @{ Name = "Ucronia Subtitulos";       Source = $ucroniaSubs },
    @{ Name = "Mira Tele Para Ser";        Source = "F:\Mira Tele Para Ser" },
    @{ Name = "Documentos";               Source = "F:\Documentos" }
)

$validPlan = @()
foreach ($item in $copyPlan) {
    if ($item.Source -and (Test-Path -LiteralPath $item.Source)) {
        $validPlan += $item
    }
    else {
        Write-Warning "Origen no encontrado, se omite: $($item.Name) -> $($item.Source)"
    }
}

if ($validPlan.Count -eq 0) {
    Write-Error "Ningun origen valido encontrado."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $LogFile) { $LogFile = "D:\copy-backup-to-d-$timestamp.log" }
$script:LogPath = $LogFile

$dFreeGB = [math]::Round((Get-Volume -DriveLetter D).SizeRemaining / 1GB, 1)

$header = @"
========================================
Copy backup E/F -> D:
DestRoot: $DestRoot
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
D: libre: $dFreeGB GB
Log: $LogFile
========================================
"@

Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
Write-Log "Inicio del script"
Write-Log "Destino: $DestRoot"
Write-Log "Espacio libre en D: $dFreeGB GB"

$totalGB = 0.0
Write-Log "Plan de copia:"
foreach ($item in $validPlan) {
    $gb = Get-FolderSizeGB -Path $item.Source
    $totalGB += $gb
    Write-Log ("  {0,-22} {1,8} GB  <- {2}" -f $item.Name, $gb, $item.Source)
}
Write-Log "Total a copiar: $totalGB GB"

if ($totalGB -gt $dFreeGB) {
    Write-Log "ADVERTENCIA: el total ($totalGB GB) supera el espacio libre en D: ($dFreeGB GB)" "WARN"
}
else {
    Write-Log "Cabe en D: sobrarian ~$([math]::Round($dFreeGB - $totalGB, 1)) GB" "OK"
}

if ($PreviewOnly) {
    Write-Log "Preview terminado. Ejecuta sin -PreviewOnly para copiar." "OK"
    exit 0
}

if (-not (Test-Path -LiteralPath $DestRoot)) {
    if ($WhatIf) {
        Write-Log "SIMULARIA crear: $DestRoot" "WARN"
    }
    else {
        New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null
        Write-Log "Carpeta destino creada: $DestRoot"
    }
}

foreach ($item in $validPlan) {
    $dest = Join-Path $DestRoot $item.Name
    $src = $item.Source

    Write-Log "----------------------------------------"
    Write-Log "Copiando: $($item.Name)"
    Write-Log "  Origen:  $src"
    Write-Log "  Destino: $dest"

    if ($WhatIf) {
        Write-Log "SIMULARIA: robocopy `"$src`" `"$dest`" /E /XO /R:2 /W:5 /MT:8" "WARN"
        continue
    }

    $robocopyArgs = @(
        $src,
        $dest,
        "/E",
        "/XO",
        "/R:2",
        "/W:5",
        "/MT:8",
        "/LOG+:$LogFile",
        "/TEE"
    )

    Write-Log "Ejecutando robocopy..."
    & robocopy @robocopyArgs
    $exitCode = $LASTEXITCODE

    # robocopy: 0-7 = exito, >=8 = error
    if ($exitCode -ge 8) {
        Write-Log "robocopy termino con error (codigo $exitCode): $($item.Name)" "ERROR"
    }
    else {
        Write-Log "robocopy OK (codigo $exitCode): $($item.Name)" "OK"
    }
}

Write-Log "========================================" "OK"
Write-Log "Proceso completado." "OK"
Write-Log "Log: $LogFile" "OK"

$freeAfter = [math]::Round((Get-Volume -DriveLetter D).SizeRemaining / 1GB, 1)
Write-Log "D: libre ahora: $freeAfter GB" "OK"
