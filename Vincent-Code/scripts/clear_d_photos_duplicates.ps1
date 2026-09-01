# Limpieza de duplicados en D: - Fotos Videos Memorias y Cargas de camara.
# Criterio: mismo nombre + mismo tamano. Conserva 1 copia por grupo.
#
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\clear_d_photos_duplicates.ps1 -PreviewOnly
#   .\clear_d_photos_duplicates.ps1 -WhatIf
#   .\clear_d_photos_duplicates.ps1
#
# Genera:
#   - log en D:\d-photos-cleanup-YYYYMMDD-HHmmss.log
#   - CSV en D:\d-photos-cleanup-YYYYMMDD-HHmmss.csv

param(
    [string]$DriveRoot = "D:\",
    [string]$FotosRoot = "",
    [string]$CargasRoot = "",
    [string[]]$ExcludePathContains = @(
        "node_modules",
        "\.pnpm\",
        "__MACOSX",
        "Adobe Premiere Pro Video Previews",
        "Adobe Premiere Pro Audio Previews",
        "\Peak Files\"
    ),
    [string]$LogFile = "",
    [string]$CsvFile = "",
    [switch]$WhatIf,
    [switch]$PreviewOnly
)

function Resolve-ChildFolder {
    param(
        [string]$Parent,
        [string]$Pattern
    )

    if (-not (Test-Path -LiteralPath $Parent)) { return $null }

    $match = Get-ChildItem -LiteralPath $Parent -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $Pattern } |
        Select-Object -First 1

    if ($match) { return $match.FullName }
    return $null
}

function Get-Clave {
    param([System.IO.FileInfo]$File)
    return "$($File.Name.ToLowerInvariant())|$($File.Length)"
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

function Test-ShouldSkipPath {
    param([string]$Path)

    foreach ($pattern in $ExcludePathContains) {
        if ($Path -like "*$pattern*") { return $true }
    }
    return $false
}

function Get-KeepScore {
    param([string]$Path)

    if ($script:FotosRoot -and $Path.StartsWith($script:FotosRoot, [StringComparison]::OrdinalIgnoreCase)) {
        if ($Path -like "*\Takeout\*") { return 50 }
        if ($Path -like "*\fb\*") { return 20 }
        if ($Path -like "*\Fotos Celu Paula\*") { return 2 }
        if ($Path -like "*\Montaña\*" -or $Path -like "*\Monta*\*") { return 3 }
        if ($Path -like "*\Viaje 2018\*") { return 4 }
        if ($Path -like "*\Arte y Otros\*") { return 5 }
        return 1
    }

    if ($script:CargasRoot -and $Path.StartsWith($script:CargasRoot, [StringComparison]::OrdinalIgnoreCase)) {
        if ($Path -like "*\Takeout\*") { return 40 }
        if ($Path -like "*\Backup Cel Media*") { return 15 }
        return 10
    }

    return 100
}

function Select-Keeper {
    param([System.IO.FileInfo[]]$Files)

    $ranked = $Files | ForEach-Object {
        [PSCustomObject]@{
            File  = $_
            Score = Get-KeepScore -Path $_.FullName
            Path  = $_.FullName
        }
    } | Sort-Object Score, @{ Expression = { $_.Path.Length } }, Path

    return $ranked[0].File
}

# --- Resolver rutas ---
if (-not $FotosRoot) {
    $FotosRoot = Resolve-ChildFolder -Parent $DriveRoot -Pattern "Fotos Videos Memorias"
}
if (-not $CargasRoot) {
    $CargasRoot = Resolve-ChildFolder -Parent $DriveRoot -Pattern "Cargas*"
}

$scanRoots = @()
if ($FotosRoot -and (Test-Path -LiteralPath $FotosRoot)) { $scanRoots += $FotosRoot }
if ($CargasRoot -and (Test-Path -LiteralPath $CargasRoot)) { $scanRoots += $CargasRoot }

if ($scanRoots.Count -eq 0) {
    Write-Error "No se encontraron carpetas Fotos Videos Memorias ni Cargas* en $DriveRoot"
    exit 1
}

$script:FotosRoot = $FotosRoot
$script:CargasRoot = $CargasRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $LogFile) { $LogFile = "D:\d-photos-cleanup-$timestamp.log" }
if (-not $CsvFile) { $CsvFile = "D:\d-photos-cleanup-$timestamp.csv" }

$script:LogPath = $LogFile
$script:DeletedFiles = 0
$script:DeletedBytes = [long]0
$script:FailedItems = New-Object System.Collections.ArrayList

$header = @"
========================================
D: photos duplicate cleanup
FotosRoot: $FotosRoot
CargasRoot: $CargasRoot
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
Prioridad (menor = conservar):
  Fotos Videos Memorias general = 1
  Fotos Celu Paula = 2
  Montana / Tablon = 3
  Viaje 2018 (sin fb) = 4
  Arte y Otros = 5
  Cargas de camara = 10
  Cargas + Takeout = 40
  Fotos con \fb\ = 20
Log: $LogFile
Csv: $CsvFile
========================================
"@

Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
Write-Log "Inicio del script"
foreach ($root in $scanRoots) { Write-Log "Escanear: $root" }

if ($WhatIf) { Write-Log "Modo simulacion (-WhatIf)" "WARN" }
if ($PreviewOnly) { Write-Log "Modo preview (-PreviewOnly)" "WARN" }

# --- Paso 1: escanear y agrupar ---
Write-Log "Paso 1/2: escaneando carpetas..."
$groups = @{}
$fileCount = 0
$skipped = 0
$lastUpdate = Get-Date

foreach ($scanRoot in $scanRoots) {
    Get-ChildItem -LiteralPath $scanRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            if (Test-ShouldSkipPath $_.FullName) {
                $skipped++
                return
            }

            $fileCount++
            if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
                Write-Log "  Escaneados: $fileCount..."
                $lastUpdate = Get-Date
            }

            $clave = Get-Clave $_
            if (-not $groups.ContainsKey($clave)) {
                $groups[$clave] = New-Object System.Collections.ArrayList
            }
            [void]$groups[$clave].Add($_)
        }
}

$dupGroups = @($groups.Keys | Where-Object { $groups[$_].Count -gt 1 }).Count
Write-Log "Archivos: $fileCount | Omitidos: $skipped | Grupos duplicados: $dupGroups"

# --- Paso 2: plan y borrado ---
Write-Log "Paso 2/2: planificando..."
$plan = New-Object System.Collections.ArrayList

foreach ($clave in $groups.Keys) {
    $members = @($groups[$clave])
    if ($members.Count -lt 2) { continue }

    $keeper = Select-Keeper -Files $members

    foreach ($file in $members) {
        if ($file.FullName -eq $keeper.FullName) { continue }

        [void]$plan.Add([PSCustomObject]@{
            Clave          = $clave
            Name           = $file.Name
            Length         = $file.Length
            KeeperPath     = $keeper.FullName
            KeeperScore    = Get-KeepScore $keeper.FullName
            DuplicatePath  = $file.FullName
            DuplicateScore = Get-KeepScore $file.FullName
            Action         = if ($PreviewOnly -or $WhatIf) { "PLAN_BORRAR" } else { "BORRAR" }
        })
    }
}

$planBytes = ($plan | Measure-Object -Property Length -Sum).Sum
if ($null -eq $planBytes) { $planBytes = 0 }

Write-Log "Archivos a eliminar: $($plan.Count)"
Write-Log "Espacio potencial: $([math]::Round($planBytes / 1GB, 2)) GB"

$plan |
    Sort-Object Length -Descending |
    Export-Csv -LiteralPath $CsvFile -NoTypeInformation -Encoding UTF8

Write-Log "Plan exportado: $CsvFile"

if ($plan.Count -eq 0) {
    Write-Log "No hay duplicados para borrar." "OK"
    exit 0
}

if ($PreviewOnly) {
    Write-Log "Preview terminado. Revisa el CSV antes de borrar." "OK"
    Write-Log "Top 10 por tamano:"
    $plan | Sort-Object Length -Descending | Select-Object -First 10 | ForEach-Object {
        Write-Log ("  {0} MB | score {1} borrar: {2} | conservar score {3}: {4}" -f (
            [math]::Round($_.Length / 1MB, 1),
            $_.DuplicateScore,
            $_.DuplicatePath,
            $_.KeeperScore,
            $_.KeeperPath
        ))
    }
    exit 0
}

Write-Log "Eliminando duplicados..."
$processed = 0
$lastUpdate = Get-Date

foreach ($item in $plan) {
    $processed++
    $size = [long]$item.Length
    $action = if ($WhatIf) { "SIMULARIA borrar" } else { "Borrando" }
    Write-Log "$action ($([math]::Round($size / 1MB, 1)) MB): $($item.DuplicatePath)"

    if (-not $WhatIf) {
        try {
            if (Test-Path -LiteralPath $item.DuplicatePath) {
                Remove-Item -LiteralPath $item.DuplicatePath -Force -ErrorAction Stop
            }
            else {
                Write-Log "Ya no existe: $($item.DuplicatePath)" "WARN"
                continue
            }
        }
        catch {
            Write-Log "Error al borrar $($item.DuplicatePath): $($_.Exception.Message)" "ERROR"
            [void]$script:FailedItems.Add($item.DuplicatePath)
            continue
        }
    }

    $script:DeletedFiles++
    $script:DeletedBytes += $size

    if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
        Write-Log "Progreso: $processed / $($plan.Count)"
        $lastUpdate = Get-Date
    }
}

if (-not $WhatIf) {
    $plan | ForEach-Object {
        $_.Action = if ($script:FailedItems -contains $_.DuplicatePath) { "ERROR" } else { "BORRADO" }
    } | Export-Csv -LiteralPath $CsvFile -NoTypeInformation -Encoding UTF8
}

Write-Log "========================================" "OK"
Write-Log "Resumen final:" "OK"
Write-Log "  Archivos eliminados: $script:DeletedFiles" "OK"
Write-Log "  Espacio liberado: $([math]::Round($script:DeletedBytes / 1GB, 2)) GB" "OK"
Write-Log "  Fallos: $($script:FailedItems.Count)" $(if ($script:FailedItems.Count -gt 0) { "WARN" } else { "OK" })

if ($script:FailedItems.Count -gt 0) {
    foreach ($item in $script:FailedItems) {
        Write-Log "  $item" "WARN"
    }
}

if ($WhatIf) {
    Write-Log "Simulacion completada. Ejecuta sin -WhatIf para borrar." "WARN"
}
else {
    Write-Log "Limpieza completada." "OK"
}

Write-Log "Log: $LogFile" "OK"
Write-Log "CSV: $CsvFile" "OK"
