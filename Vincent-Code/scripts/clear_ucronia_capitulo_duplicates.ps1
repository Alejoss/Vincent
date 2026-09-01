# Fase 3: elimina capitulos/renders duplicados en Copied_Capitulo33 si ya existen
# en Render Final Ucronia. Criterio: mismo nombre + mismo tamano.
#
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\clear_ucronia_capitulo_duplicates.ps1 -PreviewOnly
#   .\clear_ucronia_capitulo_duplicates.ps1 -WhatIf
#   .\clear_ucronia_capitulo_duplicates.ps1
#
# Genera:
#   - log en E:\ucronia-capitulo-cleanup-YYYYMMDD-HHmmss.log
#   - CSV de plan/resultado en E:\ucronia-capitulo-cleanup-YYYYMMDD-HHmmss.csv

param(
    [string]$DriveRoot = "E:\",
    [string]$UcroniaRoot = "",
    [string]$CanonicalRoot = "",
    [string]$TargetRoot = "",
    [string[]]$Extensions = @(".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"),
    [string]$LogFile = "",
    [string]$CsvFile = "",
    [switch]$WhatIf,
    [switch]$PreviewOnly
)

function Resolve-UcroniaRoot {
    param([string]$Root)

    if ($UcroniaRoot -and (Test-Path -LiteralPath $UcroniaRoot)) {
        return $UcroniaRoot
    }

    $match = Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "Ucron*" } |
        Select-Object -First 1

    if (-not $match) {
        Write-Error "No se encontro carpeta Ucron* en: $Root"
        exit 1
    }

    return $match.FullName
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

function Test-IsUnderPath {
    param(
        [string]$ChildPath,
        [string]$ParentPath
    )

    $child = [System.IO.Path]::GetFullPath($ChildPath)
    $parent = [System.IO.Path]::GetFullPath($ParentPath).TrimEnd('\') + '\'
    return $child.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)
}

function Test-IsVideoFile {
    param([System.IO.FileInfo]$File)

    return $Extensions -contains $File.Extension.ToLowerInvariant()
}

$resolvedUcroniaRoot = Resolve-UcroniaRoot -Root $DriveRoot

if (-not $CanonicalRoot) {
    $CanonicalRoot = Join-Path $resolvedUcroniaRoot "Render Final Ucronia"
}
if (-not $TargetRoot) {
    $TargetRoot = Join-Path $resolvedUcroniaRoot "Copied_Capitulo33"
}

if (-not (Test-Path -LiteralPath $CanonicalRoot)) {
    Write-Error "No existe CanonicalRoot: $CanonicalRoot"
    exit 1
}

if (-not (Test-Path -LiteralPath $TargetRoot)) {
    Write-Error "No existe TargetRoot: $TargetRoot"
    exit 1
}

if (Test-IsUnderPath -ChildPath $TargetRoot -ParentPath $CanonicalRoot) {
    Write-Error "TargetRoot no puede estar dentro de CanonicalRoot."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $LogFile) { $LogFile = "E:\ucronia-capitulo-cleanup-$timestamp.log" }
if (-not $CsvFile) { $CsvFile = "E:\ucronia-capitulo-cleanup-$timestamp.csv" }

$script:LogPath = $LogFile
$script:DeletedFiles = 0
$script:DeletedBytes = [long]0
$script:FailedItems = New-Object System.Collections.ArrayList

$header = @"
========================================
Ucronia capitulo duplicate cleanup
UcroniaRoot: $resolvedUcroniaRoot
CanonicalRoot: $CanonicalRoot
TargetRoot: $TargetRoot
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
Log: $LogFile
Csv: $CsvFile
========================================
"@

Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
Write-Log "Inicio del script"
Write-Log "UcroniaRoot (auto): $resolvedUcroniaRoot"
Write-Log "Canonico (conservar): $CanonicalRoot"
Write-Log "Target (borrar duplicados): $TargetRoot"

if ($WhatIf) { Write-Log "Modo simulacion (-WhatIf)" "WARN" }
if ($PreviewOnly) { Write-Log "Modo preview (-PreviewOnly)" "WARN" }

# --- Paso 1: inventario de renders finales ---
Write-Log "Paso 1/3: inventariando renders finales..."
$canonical = @{}
$canonicalCount = 0
$lastUpdate = Get-Date

Get-ChildItem -LiteralPath $CanonicalRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { Test-IsVideoFile $_ } |
    ForEach-Object {
        $canonicalCount++
        if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
            Write-Log "  Canonico escaneado: $canonicalCount archivos..."
            $lastUpdate = Get-Date
        }

        $clave = Get-Clave $_
        if (-not $canonical.ContainsKey($clave)) {
            $canonical[$clave] = New-Object System.Collections.ArrayList
        }
        [void]$canonical[$clave].Add($_.FullName)
    }

$ambiguousCanonical = @($canonical.Keys | Where-Object { $canonical[$_].Count -gt 1 })
Write-Log "Renders finales: $canonicalCount archivos, $($canonical.Keys.Count) claves unicas"
if ($ambiguousCanonical.Count -gt 0) {
    Write-Log "Claves con mas de 1 copia en Render Final: $($ambiguousCanonical.Count) (se conservan todas)" "WARN"
}

# --- Paso 2: cruzar con Copied_Capitulo33 ---
Write-Log "Paso 2/3: buscando duplicados en Copied_Capitulo33..."
$plan = New-Object System.Collections.ArrayList
$targetCount = 0
$script:TargetOnlyCount = 0
$lastUpdate = Get-Date

Get-ChildItem -LiteralPath $TargetRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { Test-IsVideoFile $_ } |
    ForEach-Object {
        $targetCount++
        if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
            Write-Log "  Target escaneado: $targetCount archivos..."
            $lastUpdate = Get-Date
        }

        $clave = Get-Clave $_
        if (-not $canonical.ContainsKey($clave)) {
            $script:TargetOnlyCount++
            return
        }

        [void]$plan.Add([PSCustomObject]@{
            Clave         = $clave
            Name          = $_.Name
            Length        = $_.Length
            CanonicalPath = ($canonical[$clave] -join " | ")
            DuplicatePath = $_.FullName
            Action        = if ($PreviewOnly -or $WhatIf) { "PLAN_BORRAR" } else { "BORRAR" }
        })
    }

$planBytes = ($plan | Measure-Object -Property Length -Sum).Sum
if ($null -eq $planBytes) { $planBytes = 0 }

Write-Log "Videos en Copied_Capitulo33: $targetCount"
Write-Log "Duplicados con Render Final: $($plan.Count)"
Write-Log "Solo en Copied_Capitulo33 (no se tocan): $script:TargetOnlyCount"
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
        Write-Log ("  {0} MB | {1} -> canon en {2}" -f (
            [math]::Round($_.Length / 1MB, 1),
            $_.DuplicatePath,
            $_.CanonicalPath
        ))
    }
    exit 0
}

# --- Paso 3: borrar duplicados ---
Write-Log "Paso 3/3: eliminando duplicados..."
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
            $msg = "Error al borrar $($item.DuplicatePath): $($_.Exception.Message)"
            Write-Log $msg "ERROR"
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
        if ($script:FailedItems -contains $_.DuplicatePath) {
            $_.Action = "ERROR"
        }
        else {
            $_.Action = "BORRADO"
        }
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
