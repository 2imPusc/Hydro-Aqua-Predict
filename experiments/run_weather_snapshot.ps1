param(
    [string]$Station = "06M26042804",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
if (-not $Output) {
    $Output = Join-Path $repoRoot "artifacts\experiments\forecast-v2\weather-snapshots.jsonl"
}

$logDir = Split-Path -Parent $Output
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "weather-snapshot-collector.log"
$startedAt = (Get-Date).ToUniversalTime().ToString("o")

try {
    & (Join-Path $scriptDir "capture_weather_snapshot.ps1") -Station $Station -Output $Output 2>&1 |
        Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "capture_weather_snapshot exited with code $LASTEXITCODE"
    }
    "[$startedAt] status=ok station=$Station output=$Output" |
        Tee-Object -FilePath $logPath -Append
}
catch {
    "[$startedAt] status=failed station=$Station error=$($_.Exception.Message)" |
        Tee-Object -FilePath $logPath -Append
    throw
}
