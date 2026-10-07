param(
    [string]$Station = "06M26042804",
    [string]$Output = ""
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Output) {
    $Output = Join-Path $repoRoot "artifacts\experiments\forecast-v2\weather-snapshots.jsonl"
}
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment Python was not found: $python"
}

& $python (Join-Path $PSScriptRoot "forecast_snapshot_store.py") --station $Station --output $Output
if ($LASTEXITCODE -ne 0) {
    throw "Open-Meteo snapshot capture failed with exit code $LASTEXITCODE"
}
