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

# PowerShell 5.1 turns the first native stderr line into a terminating error
# under "Stop", which truncated tracebacks in the collector log. Collect all
# output first, then decide on the exit code.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$lines = & $python (Join-Path $PSScriptRoot "forecast_snapshot_store.py") --station $Station --output $Output 2>&1 | ForEach-Object { "$_" }
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
$lines
if ($exitCode -ne 0) {
    throw "Open-Meteo snapshot capture failed with exit code $exitCode"
}
