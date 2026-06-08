$ErrorActionPreference = "Stop"

$envValues = @{}
Get-Content ".env.local" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $parts = $line.Split("=", 2)
        $envValues[$parts[0]] = $parts[1]
    }
}

$migration = Get-Content "sql/migrations/20260531_create_resumen_validacion_radicado.sql" -Raw
$match = [regex]::Match(
    $migration,
    "INSERT\s+INTO\s+jnc\.resumen_validacion_radicado\s*\((.*?)\)\s*SELECT",
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor
        [System.Text.RegularExpressions.RegexOptions]::Singleline
)
if (-not $match.Success) {
    throw "No se encontro el INSERT del resumen."
}

$calculatedColumns = $match.Groups[1].Value.Split(",") |
    ForEach-Object { $_.Trim().Trim("[", "]") } |
    Where-Object { $_ }

$connectionString = "Server=tcp:$($envValues["AZURE_SQL_SERVER"]),1433;Database=$($envValues["AZURE_SQL_DATABASE"]);User ID=$($envValues["AZURE_SQL_USER"]);Password=$($envValues["AZURE_SQL_PASSWORD"]);Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;"
$connection = New-Object System.Data.SqlClient.SqlConnection($connectionString)
$connection.Open()
try {
    $command = $connection.CreateCommand()
    $command.CommandText = @"
SELECT
    c.COLUMN_NAME,
    c.ORDINAL_POSITION,
    c.DATA_TYPE,
    c.IS_NULLABLE,
    c.COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS AS c
WHERE c.TABLE_SCHEMA = 'jnc'
  AND c.TABLE_NAME = 'resumen_validacion_radicado'
ORDER BY c.ORDINAL_POSITION
"@
    $reader = $command.ExecuteReader()
    $schemaRows = @()
    while ($reader.Read()) {
        $schemaRows += [pscustomobject]@{
            COLUMN_NAME = $reader.GetString(0)
            ORDINAL_POSITION = $reader.GetInt32(1)
            DATA_TYPE = $reader.GetString(2)
            IS_NULLABLE = $reader.GetString(3)
            COLUMN_DEFAULT = if ($reader.IsDBNull(4)) { "" } else { $reader.GetString(4) }
        }
    }
    $reader.Close()
}
finally {
    $connection.Close()
}

$calculatedSet = @{}
$calculatedColumns | ForEach-Object { $calculatedSet[$_] = $true }
$technicalKeep = @{ "id_resumen_validacion" = $true }

Write-Output "CALCULATED_COLUMNS"
$calculatedColumns | ForEach-Object { Write-Output $_ }

Write-Output "SCHEMA_COLUMNS"
$schemaRows | ForEach-Object {
    Write-Output "$($_.COLUMN_NAME)|$($_.ORDINAL_POSITION)|$($_.DATA_TYPE)|$($_.IS_NULLABLE)|$($_.COLUMN_DEFAULT)"
}

Write-Output "NOT_CALCULATED_COLUMNS"
$schemaRows | ForEach-Object {
    if (-not $calculatedSet.ContainsKey($_.COLUMN_NAME) -and -not $technicalKeep.ContainsKey($_.COLUMN_NAME)) {
        Write-Output $_.COLUMN_NAME
    }
}
