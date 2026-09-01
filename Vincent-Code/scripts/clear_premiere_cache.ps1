# Elimina cache de Adobe Premiere en un disco o carpeta (Fase 1 de limpieza).
# Cierra Premiere Pro antes de ejecutar.
#
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\clear_premiere_cache.ps1
#   .\clear_premiere_cache.ps1 -Root "E:\"
#   .\clear_premiere_cache.ps1 -WhatIf          # simulacion, no borra
#   .\clear_premiere_cache.ps1 -PreviewOnly     # solo escanea y loguea

param(
    [string]$Root = "E:\",
    [string]$LogFile = "",
    [switch]$WhatIf,
    [switch]$PreviewOnly
)

$cacheFolderNames = @(
    "Adobe Premiere Pro Video Previews",
    "Adobe Premiere Pro Audio Previews",
    "Peak Files"
)

$cacheExtensions = @(".pek", ".cfa")

if (-not (Test-Path -LiteralPath $Root)) {
    Write-Error "No existe la ruta: $Root"
    exit 1
}

if (-not $LogFile) {
    $driveLetter = $Root.TrimEnd('\').Split(':')[0].ToUpperInvariant()
    if (-not $driveLetter) { $driveLetter = "X" }
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $LogFile = "${driveLetter}:\premiere-cache-cleanup-${timestamp}.log"
}

$script:DeletedFolders = 0
$script:DeletedFiles = 0
$script:DeletedBytes = [long]0
$script:FailedItems = New-Object System.Collections.ArrayList
$script:LogPath = $LogFile

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

function Get-FolderSizeBytes {
    param([string]$Path)

    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum

    if ($null -eq $sum) { return [long]0 }
    return [long]$sum
}

function Remove-CacheFolder {
    param(
        [System.IO.DirectoryInfo]$Folder
    )

    $size = Get-FolderSizeBytes -Path $Folder.FullName
    $action = if ($WhatIf) { "SIMULARIA borrar carpeta" } else { "Borrando carpeta" }
    Write-Log "$action ($([math]::Round($size / 1GB, 2)) GB): $($Folder.FullName)"

    if ($PreviewOnly) { return }

    try {
        if ($WhatIf) {
            $script:DeletedFolders++
            $script:DeletedBytes += $size
            return
        }

        Remove-Item -LiteralPath $Folder.FullName -Recurse -Force -ErrorAction Stop
        $script:DeletedFolders++
        $script:DeletedBytes += $size
    }
    catch {
        $msg = "No se pudo borrar carpeta: $($Folder.FullName) -> $($_.Exception.Message)"
        Write-Log $msg "ERROR"
        [void]$script:FailedItems.Add($Folder.FullName)
    }
}

function Remove-CacheFile {
    param(
        [System.IO.FileInfo]$File
    )

    if ($PreviewOnly) { return }

    try {
        if (-not $WhatIf) {
            Remove-Item -LiteralPath $File.FullName -Force -ErrorAction Stop
        }

        $script:DeletedFiles++
        $script:DeletedBytes += $File.Length
    }
    catch {
        $msg = "No se pudo borrar archivo: $($File.FullName) -> $($_.Exception.Message)"
        Write-Log $msg "ERROR"
        [void]$script:FailedItems.Add($File.FullName)
    }
}

# --- Inicio ---
$header = @"
========================================
Premiere cache cleanup
Root: $Root
WhatIf: $WhatIf
PreviewOnly: $PreviewOnly
Log: $LogFile
========================================
"@

Set-Content -LiteralPath $LogFile -Value $header -Encoding UTF8
Write-Log "Inicio del script"
Write-Log "Root: $Root"
Write-Log "Log: $LogFile"

if ($WhatIf) {
    Write-Log "Modo simulacion (-WhatIf): no se borrara nada" "WARN"
}
if ($PreviewOnly) {
    Write-Log "Modo preview (-PreviewOnly): solo escaneo, sin borrado" "WARN"
}

Write-Log "Buscando carpetas de cache de Premiere..."
$cacheFolders = @(Get-ChildItem -LiteralPath $Root -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $cacheFolderNames -contains $_.Name })

Write-Log "Carpetas de cache encontradas: $($cacheFolders.Count)"

$folderBytes = [long]0
foreach ($folder in $cacheFolders) {
    $size = Get-FolderSizeBytes -Path $folder.FullName
    $folderBytes += $size
    Write-Log ("  {0} GB | {1}" -f ([math]::Round($size / 1GB, 2)), $folder.FullName)
}

Write-Log "Total en carpetas de cache: $([math]::Round($folderBytes / 1GB, 2)) GB"

Write-Log "Buscando archivos .pek y .cfa..."
$cacheFiles = @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $cacheExtensions -contains $_.Extension.ToLowerInvariant() })

$fileBytes = ($cacheFiles | Measure-Object -Property Length -Sum).Sum
if ($null -eq $fileBytes) { $fileBytes = 0 }

Write-Log "Archivos .pek/.cfa encontrados: $($cacheFiles.Count)"
Write-Log "Total en .pek/.cfa: $([math]::Round($fileBytes / 1GB, 2)) GB"

if ($PreviewOnly) {
    Write-Log "Preview terminado. Espacio potencial: $([math]::Round(($folderBytes + $fileBytes) / 1GB, 2)) GB" "OK"
    Write-Log "Para borrar de verdad, ejecuta sin -PreviewOnly"
    exit 0
}

Write-Log "Eliminando carpetas de cache..."
foreach ($folder in $cacheFolders) {
    Remove-CacheFolder -Folder $folder
}

Write-Log "Eliminando archivos .pek y .cfa..."
$fileCount = 0
$lastLog = Get-Date
foreach ($file in $cacheFiles) {
    $fileCount++
    Remove-CacheFile -File $file

    if ((Get-Date) - $lastLog -gt [TimeSpan]::FromSeconds(5)) {
        Write-Log "Progreso archivos: $fileCount / $($cacheFiles.Count)"
        $lastLog = Get-Date
    }
}

Write-Log "========================================" "OK"
Write-Log "Resumen final:" "OK"
Write-Log "  Carpetas eliminadas: $script:DeletedFolders" "OK"
Write-Log "  Archivos eliminados: $script:DeletedFiles" "OK"
Write-Log "  Espacio liberado (estimado): $([math]::Round($script:DeletedBytes / 1GB, 2)) GB" "OK"
Write-Log "  Fallos: $($script:FailedItems.Count)" $(if ($script:FailedItems.Count -gt 0) { "WARN" } else { "OK" })

if ($script:FailedItems.Count -gt 0) {
    Write-Log "Items con error:"
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

Write-Log "Log guardado en: $LogFile" "OK"
