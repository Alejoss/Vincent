# Fase 4c y 4d en F:
#   4c - duplicados internos en Alejandro Data (conserva 1 por grupo)
#   4d - duplicados en Envy PC si ya existen en Alejandro Data
#
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\clear_f_alejandro_envy_duplicates.ps1 -PreviewOnly
#   .\clear_f_alejandro_envy_duplicates.ps1 -Phase 4c -PreviewOnly
#   .\clear_f_alejandro_envy_duplicates.ps1 -Phase 4d -WhatIf
#   .\clear_f_alejandro_envy_duplicates.ps1

param(
    [ValidateSet("Both", "4c", "4d")]
    [string]$Phase = "Both",
    [string]$DriveRoot = "F:\",
    [string]$AlejandroRoot = "",
    [string]$EnvyRoot = "",
    [string[]]$ExcludePathContains = @(
        "node_modules",
        "\.pnpm\",
        "__MACOSX",
        "Adobe Premiere Pro Video Previews",
        "Adobe Premiere Pro Audio Previews",
        "\Peak Files\"
    ),
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

function Test-IsUnderPath {
    param(
        [string]$ChildPath,
        [string]$ParentPath
    )

    $child = [System.IO.Path]::GetFullPath($ChildPath)
    $parent = [System.IO.Path]::GetFullPath($ParentPath).TrimEnd('\') + '\'
    return $child.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)
}

function Get-AlejandroKeepScore {
    param([string]$Path)

    if (-not $script:AlejandroRules) { return 100 }

    foreach ($rule in $script:AlejandroRules) {
        if ($Path.StartsWith($rule.Prefix, [StringComparison]::OrdinalIgnoreCase)) {
            return $rule.Score
        }
    }
    return 100
}

function Initialize-AlejandroRules {
    param([string]$Root)

    $patterns = @(
        @{ Pattern = "Fotos Videos Memorias"; Score = 1 },
        @{ Pattern = "Camera"; Score = 2 },
        @{ Pattern = "Arte Propio"; Score = 3 },
        @{ Pattern = "Documentos"; Score = 4 },
        @{ Pattern = "Imagenes"; Score = 5 },
        @{ Pattern = "Publiciones Redes"; Score = 6 },
        @{ Pattern = "Cargas*"; Score = 7 }
    )

    $rules = New-Object System.Collections.ArrayList
    foreach ($item in $patterns) {
        $folder = Resolve-ChildFolder -Parent $Root -Pattern $item.Pattern
        if ($folder) {
            [void]$rules.Add([PSCustomObject]@{
                Prefix = $folder
                Score  = $item.Score
                Name   = (Split-Path $folder -Leaf)
            })
        }
    }

    return ,$rules.ToArray()
}

function Select-Keeper {
    param(
        [System.IO.FileInfo[]]$Files,
        [scriptblock]$ScoreScript
    )

    $ranked = $Files | ForEach-Object {
        [PSCustomObject]@{
            File  = $_
            Score = & $ScoreScript $_.FullName
            Path  = $_.FullName
        }
    } | Sort-Object Score, @{ Expression = { $_.Path.Length } }, Path

    return $ranked[0].File
}

function Invoke-DeletePlan {
    param(
        [System.Collections.ArrayList]$Plan,
        [string]$CsvFile
    )

    if ($Plan.Count -eq 0) {
        Write-Log "No hay duplicados para borrar." "OK"
        return
    }

    $planBytes = ($Plan | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $planBytes) { $planBytes = 0 }

    Write-Log "Archivos a eliminar: $($Plan.Count)"
    Write-Log "Espacio potencial: $([math]::Round($planBytes / 1GB, 2)) GB"

    $Plan |
        Sort-Object Length -Descending |
        Export-Csv -LiteralPath $CsvFile -NoTypeInformation -Encoding UTF8

    Write-Log "Plan exportado: $CsvFile"

    if ($PreviewOnly) {
        Write-Log "Preview terminado. Revisa el CSV antes de borrar." "OK"
        Write-Log "Top 10 por tamano:"
        $Plan | Sort-Object Length -Descending | Select-Object -First 10 | ForEach-Object {
            Write-Log ("  {0} MB | borrar: {1} | conservar: {2}" -f (
                [math]::Round($_.Length / 1MB, 1),
                $_.DuplicatePath,
                $_.KeeperPath
            ))
        }
        return
    }

    Write-Log "Eliminando duplicados..."
    $processed = 0
    $deletedFiles = 0
    $deletedBytes = [long]0
    $failedItems = New-Object System.Collections.ArrayList
    $lastUpdate = Get-Date

    foreach ($item in $Plan) {
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
                [void]$failedItems.Add($item.DuplicatePath)
                continue
            }
        }

        $deletedFiles++
        $deletedBytes += $size

        if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
            Write-Log "Progreso: $processed / $($Plan.Count)"
            $lastUpdate = Get-Date
        }
    }

    if (-not $WhatIf) {
        $Plan | ForEach-Object {
            $_.Action = if ($failedItems -contains $_.DuplicatePath) { "ERROR" } else { "BORRADO" }
        } | Export-Csv -LiteralPath $CsvFile -NoTypeInformation -Encoding UTF8
    }

    Write-Log "Archivos eliminados: $deletedFiles" "OK"
    Write-Log "Espacio liberado: $([math]::Round($deletedBytes / 1GB, 2)) GB" "OK"
    Write-Log "Fallos: $($failedItems.Count)" $(if ($failedItems.Count -gt 0) { "WARN" } else { "OK" })
}

function Invoke-Phase4c {
    param(
        [string]$Root,
        [string]$LogFile,
        [string]$CsvFile
    )

    $script:LogPath = $LogFile
    $header = @"
========================================
Fase 4c: duplicados internos Alejandro Data
Root: $Root
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
Log: $LogFile
Csv: $CsvFile
========================================
"@
    Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
    Write-Log "=== FASE 4c ===" "OK"
    Write-Log "Alejandro Data: $Root"
    Write-Log "Prioridad conservar: Fotos Videos Memorias > Camera > Arte Propio > Documentos > Imagenes > Publiciones Redes > Cargas*"

    foreach ($rule in $script:AlejandroRules) {
        Write-Log ("  score {0}: {1}" -f $rule.Score, $rule.Name)
    }

    Write-Log "Paso 1/2: escaneando y agrupando..."
    $groups = @{}
    $fileCount = 0
    $skipped = 0
    $lastUpdate = Get-Date

    Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            if (Test-ShouldSkipPath $_.FullName) { $skipped++; return }

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

    $dupGroups = @($groups.Keys | Where-Object { $groups[$_].Count -gt 1 }).Count
    Write-Log "Archivos: $fileCount | Omitidos: $skipped | Grupos duplicados: $dupGroups"

    Write-Log "Paso 2/2: planificando borrados..."
    $plan = New-Object System.Collections.ArrayList

    foreach ($clave in $groups.Keys) {
        $members = @($groups[$clave])
        if ($members.Count -lt 2) { continue }

        $keeper = Select-Keeper -Files $members -ScoreScript ${function:Get-AlejandroKeepScore}

        foreach ($file in $members) {
            if ($file.FullName -eq $keeper.FullName) { continue }

            [void]$plan.Add([PSCustomObject]@{
                Clave          = $clave
                Name           = $file.Name
                Length         = $file.Length
                KeeperPath     = $keeper.FullName
                KeeperScore    = Get-AlejandroKeepScore $keeper.FullName
                DuplicatePath  = $file.FullName
                DuplicateScore = Get-AlejandroKeepScore $file.FullName
                Action         = if ($PreviewOnly -or $WhatIf) { "PLAN_BORRAR" } else { "BORRAR" }
            })
        }
    }

    Invoke-DeletePlan -Plan $plan -CsvFile $CsvFile
}

function Invoke-Phase4d {
    param(
        [string]$CanonicalRoot,
        [string]$TargetRoot,
        [string]$LogFile,
        [string]$CsvFile
    )

    $script:LogPath = $LogFile
    $header = @"
========================================
Fase 4d: Envy PC vs Alejandro Data
CanonicalRoot: $CanonicalRoot
TargetRoot: $TargetRoot
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
Log: $LogFile
Csv: $CsvFile
========================================
"@
    Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
    Write-Log "=== FASE 4d ===" "OK"
    Write-Log "Conservar: $CanonicalRoot"
    Write-Log "Borrar duplicados en: $TargetRoot"

    Write-Log "Paso 1/3: inventariando Alejandro Data..."
    $canonical = @{}
    $canonicalCount = 0
    $lastUpdate = Get-Date

    Get-ChildItem -LiteralPath $CanonicalRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-ShouldSkipPath $_.FullName) } |
        ForEach-Object {
            $canonicalCount++
            if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
                Write-Log "  Canonico: $canonicalCount..."
                $lastUpdate = Get-Date
            }

            $clave = Get-Clave $_
            if (-not $canonical.ContainsKey($clave)) {
                $canonical[$clave] = New-Object System.Collections.ArrayList
            }
            [void]$canonical[$clave].Add($_.FullName)
        }

    Write-Log "Alejandro Data indexado: $canonicalCount archivos, $($canonical.Keys.Count) claves"

    Write-Log "Paso 2/3: buscando duplicados en Envy PC..."
    $plan = New-Object System.Collections.ArrayList
    $targetCount = 0
    $targetOnly = 0
    $skipped = 0
    $lastUpdate = Get-Date

    Get-ChildItem -LiteralPath $TargetRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            if (Test-ShouldSkipPath $_.FullName) { $skipped++; return }

            $targetCount++
            if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
                Write-Log "  Envy PC: $targetCount..."
                $lastUpdate = Get-Date
            }

            if (Test-IsUnderPath -ChildPath $_.FullName -ParentPath $CanonicalRoot) { return }

            $clave = Get-Clave $_
            if (-not $canonical.ContainsKey($clave)) {
                $targetOnly++
                return
            }

            [void]$plan.Add([PSCustomObject]@{
                Clave         = $clave
                Name          = $_.Name
                Length        = $_.Length
                KeeperPath    = ($canonical[$clave] -join " | ")
                KeeperScore   = ""
                DuplicatePath = $_.FullName
                DuplicateScore = ""
                Action        = if ($PreviewOnly -or $WhatIf) { "PLAN_BORRAR" } else { "BORRAR" }
            })
        }

    Write-Log "Envy PC archivos: $targetCount | Omitidos: $skipped | Solo en Envy: $targetOnly"

    Write-Log "Paso 3/3: ejecutar plan..."
    Invoke-DeletePlan -Plan $plan -CsvFile $CsvFile
}

# --- Setup rutas ---
if (-not $AlejandroRoot) {
    $AlejandroRoot = Resolve-ChildFolder -Parent $DriveRoot -Pattern "Alejandro Data"
}
if (-not $AlejandroRoot -or -not (Test-Path -LiteralPath $AlejandroRoot)) {
    Write-Error "No se encontro Alejandro Data en $DriveRoot"
    exit 1
}

if (-not $EnvyRoot) {
    $EnvyRoot = Resolve-ChildFolder -Parent $DriveRoot -Pattern "Envy PC"
}
if (-not $EnvyRoot -or -not (Test-Path -LiteralPath $EnvyRoot)) {
    Write-Warning "No se encontro Envy PC en $DriveRoot. Fase 4d se omitira si se solicita."
}

$script:AlejandroRules = Initialize-AlejandroRules -Root $AlejandroRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$run4c = $Phase -eq "Both" -or $Phase -eq "4c"
$run4d = ($Phase -eq "Both" -or $Phase -eq "4d") -and $EnvyRoot

if ($run4c) {
    $log4c = "F:\f-alejandro-internal-cleanup-$timestamp.log"
    $csv4c = "F:\f-alejandro-internal-cleanup-$timestamp.csv"
    Invoke-Phase4c -Root $AlejandroRoot -LogFile $log4c -CsvFile $csv4c
}

if ($run4d) {
    $log4d = "F:\f-envy-pc-cleanup-$timestamp.log"
    $csv4d = "F:\f-envy-pc-cleanup-$timestamp.csv"
    Invoke-Phase4d -CanonicalRoot $AlejandroRoot -TargetRoot $EnvyRoot -LogFile $log4d -CsvFile $csv4d
}
elseif ($Phase -eq "4d" -or $Phase -eq "Both") {
    Write-Warning "Fase 4d omitida: Envy PC no encontrado."
}

Write-Host ""
Write-Host "Proceso completado. Phase=$Phase" -ForegroundColor Green
