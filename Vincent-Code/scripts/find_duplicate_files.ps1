# Busca archivos duplicados por nombre + tamaño en un disco o carpeta.
# Ejecutar en PowerShell:
#   cd E:\Vincent\Vincent-Code\scripts
#   .\find_duplicate_files.ps1 -Root "D:\"
#   .\find_duplicate_files.ps1 -Root "E:\"
#   .\find_duplicate_files.ps1 -Root "F:\"
#
# El CSV se guarda como duplicados-disco-X.csv (no sobrescribe escaneos de otros discos).

param(
    [string]$Root = "D:\",
    [string]$OutputCsv = ""
)

if (-not $OutputCsv) {
    $driveLetter = $Root.TrimEnd('\').Split(':')[0].ToUpperInvariant()
    if (-not $driveLetter) {
        Write-Error "No se pudo inferir la letra de unidad desde: $Root"
        exit 1
    }
    $OutputCsv = "${driveLetter}:\duplicados-disco-${driveLetter}.csv"
}

if (-not (Test-Path -LiteralPath $Root)) {
    Write-Error "No existe la ruta: $Root"
    exit 1
}

$files = @{}
$count = 0
$lastUpdate = Get-Date
$sw = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host "Escaneando: $Root"
Write-Host ""

Get-ChildItem -LiteralPath $Root -File -Recurse -ErrorAction SilentlyContinue |
ForEach-Object {
    $count++

    if ((Get-Date) - $lastUpdate -gt [TimeSpan]::FromSeconds(5)) {
        $elapsed = [math]::Round($sw.Elapsed.TotalMinutes, 1)
        Write-Host "Procesados: $count archivos (${elapsed} min)..."
        Write-Progress -Activity "Escaneando duplicados" `
            -Status "$count archivos procesados" `
            -PercentComplete -1
        $lastUpdate = Get-Date
    }

    $clave = "$($_.Name.ToLowerInvariant())|$($_.Length)"
    if (-not $files.ContainsKey($clave)) {
        $files[$clave] = New-Object System.Collections.ArrayList
    }
    [void]$files[$clave].Add($_)
}

Write-Progress -Activity "Escaneando duplicados" -Completed

$gruposDuplicados = @($files.Keys | Where-Object { $files[$_].Count -gt 1 })
$archivosDuplicados = ($gruposDuplicados | ForEach-Object { $files[$_].Count } | Measure-Object -Sum).Sum
$bytesRecuperables = 0

$resultados = foreach ($clave in $gruposDuplicados) {
    $grupo = $files[$clave]
    $bytesRecuperables += ($grupo.Count - 1) * $grupo[0].Length

    foreach ($archivo in $grupo) {
        [PSCustomObject]@{
            Clave    = $clave
            Name     = $archivo.Name
            FullName = $archivo.FullName
            Length   = $archivo.Length
        }
    }
}

if ($resultados.Count -eq 0) {
    Write-Host ""
    Write-Host "Escaneo terminado."
    Write-Host "Archivos procesados: $count"
    Write-Host "No se encontraron duplicados (mismo nombre y tamaño)."
    exit 0
}

$gbRecuperables = [math]::Round($bytesRecuperables / 1GB, 2)

$resultados |
    Sort-Object Clave, FullName |
    Export-Csv -LiteralPath $OutputCsv -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "Escaneo terminado."
Write-Host "Archivos procesados: $count"
Write-Host "Grupos duplicados: $($gruposDuplicados.Count)"
Write-Host "Archivos en grupos duplicados: $archivosDuplicados"
Write-Host "Espacio potencialmente recuperable (dejando 1 copia por grupo): $gbRecuperables GB"
Write-Host "CSV generado: $OutputCsv"
