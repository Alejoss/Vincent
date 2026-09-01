# Fase 4b: elimina duplicados internos en Backup Lacie HardDrive (F:).
# Criterio: mismo nombre + mismo tamano. Conserva 1 copia por grupo segun prioridad de carpeta.
#
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\clear_f_backup_internal_duplicates.ps1 -PreviewOnly
#   .\clear_f_backup_internal_duplicates.ps1 -WhatIf
#   .\clear_f_backup_internal_duplicates.ps1
#
# Genera:
#   - log en F:\f-backup-internal-cleanup-YYYYMMDD-HHmmss.log
#   - CSV de plan/resultado en F:\f-backup-internal-cleanup-YYYYMMDD-HHmmss.csv

param(
    [string]$BackupRoot = "F:\Backup Lacie HardDrive",
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
        if ($Path -like "*$pattern*") {
            return $true
        }
    }
    return $false
}

function Get-KeepScore {
    param([string]$Path)

    $rules = @(
        @{ Prefix = "$BackupRoot\Stock Files Edicion"; Score = 1 },
        @{ Prefix = "$BackupRoot\Proyectos - Archivos Ucronia\Render Final Ucronia"; Score = 2 },
        @{ Prefix = "$BackupRoot\Proyectos Video"; Score = 3 },
        @{ Prefix = "$BackupRoot\Backup"; Score = 4 },
        @{ Prefix = "$BackupRoot\Proyectos - Archivos Ucronia"; Score = 5 },
        @{ Prefix = "$BackupRoot\backup cargas camara"; Score = 6 },
        @{ Prefix = "$BackupRoot\Videos"; Score = 7 }
    )

    foreach ($rule in $rules) {
        if ($Path.StartsWith($rule.Prefix, [StringComparison]::OrdinalIgnoreCase)) {
            return $rule.Score
        }
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

if (-not (Test-Path -LiteralPath $BackupRoot)) {
    Write-Error "No existe BackupRoot: $BackupRoot"
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $LogFile) { $LogFile = "F:\f-backup-internal-cleanup-$timestamp.log" }
if (-not $CsvFile) { $CsvFile = "F:\f-backup-internal-cleanup-$timestamp.csv" }

$script:LogPath = $LogFile
$script:DeletedFiles = 0
$script:DeletedBytes = [long]0
$script:FailedItems = New-Object System.Collections.ArrayList
$script:SkippedExcluded = 0

$header = @"
========================================
Fase 4b: duplicados internos en Backup Lacie
BackupRoot: $BackupRoot
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
Prioridad conservar (menor = gana):
  1 Stock Files Edicion
  2 Render Final Ucronia
  3 Proyectos Video
  4 Backup
  5 Proyectos - Archivos Ucronia
  6 backup cargas camara
  7 Videos
Log: $LogFile
Csv: $CsvFile
========================================
"@

Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
Write-Log "Inicio del script"
Write-Log "BackupRoot: $BackupRoot"

if ($WhatIf) { Write-Log "Modo simulacion (-WhatIf)" "WARN" }
if ($PreviewOnly) { Write-Log "Modo preview (-PreviewOnly)" "WARN" }

# --- Paso 1: inventario y agrupacion ---
Write-Log "Paso 1/3: escaneando Backup Lacie HardDrive..."
$groups = @{}
$fileCount = 0
$lastUpdate = Get-Date

Get-ChildItem -LiteralPath $BackupRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
    ForEach-Object {
        if (Test-ShouldSkipPath $_.FullName) {
            $script:SkippedExcluded++
            return
        }

        $fileCount++
        if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
            Write-Log "  Archivos escaneados: $fileCount..."
            $lastUpdate = Get-Date
        }

        $clave = Get-Clave $_
        if (-not $groups.ContainsKey($clave)) {
            $groups[$clave] = New-Object System.Collections.ArrayList
        }
        [void]$groups[$clave].Add($_)
    }

$dupGroupCount = @($groups.Keys | Where-Object { $groups[$_].Count -gt 1 }).Count
Write-Log "Archivos escaneados: $fileCount"
Write-Log "Omitidos (node_modules, cache, etc.): $script:SkippedExcluded"
Write-Log "Grupos duplicados: $dupGroupCount"

# --- Paso 2: plan de borrado ---
Write-Log "Paso 2/3: eligiendo copia a conservar por grupo..."
$plan = New-Object System.Collections.ArrayList

foreach ($clave in $groups.Keys) {
    $members = @($groups[$clave])
    if ($members.Count -lt 2) { continue }

    $keeper = Select-Keeper -Files $members

    foreach ($file in $members) {
        if ($file.FullName -eq $keeper.FullName) { continue }

        [void]$plan.Add([PSCustomObject]@{
            Clave         = $clave
            Name          = $file.Name
            Length        = $file.Length
            KeeperPath    = $keeper.FullName
            KeeperScore   = Get-KeepScore -Path $keeper.FullName
            DuplicatePath = $file.FullName
            DuplicateScore = Get-KeepScore -Path $file.FullName
            Action        = if ($PreviewOnly -or $WhatIf) { "PLAN_BORRAR" } else { "BORRAR" }
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
        Write-Log ("  {0} MB | score {1} -> {2} | conservar score {3} -> {4}" -f (
            [math]::Round($_.Length / 1MB, 1),
            $_.DuplicateScore,
            $_.DuplicatePath,
            $_.KeeperScore,
            $_.KeeperPath
        ))
    }
    exit 0
}

# --- Paso 3: borrar ---
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
