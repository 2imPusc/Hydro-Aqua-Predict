param(
    [string]$Station = "06M26042804",
    [int]$IntervalSeconds = 60
)

# Long-running shadow runner for HAP-ShadowRunner (H1.5). Live GreenLab fetch for this process only: the root
# .env keeps GREENLAB_FETCH_MODE=cache for offline demos/tests. Output: runtime/forecast-shadow/ (append-only);
# stdout/stderr: runtime/logs/shadow-runner.log.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "core\shadow_runner.py"
if (-not (Test-Path -LiteralPath $python)) { throw "Project Python not found: $python" }

$logDir = Join-Path $repoRoot "runtime\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "shadow-runner.log"

$env:GREENLAB_FETCH_MODE = "live"
$env:MARINE_ENABLED = "true"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Push-Location $repoRoot
try {
    $ErrorActionPreference = "Continue"
    "[$((Get-Date).ToUniversalTime().ToString('o'))] start station=$Station interval=$IntervalSeconds" | Out-File -FilePath $logPath -Append -Encoding utf8
    & $python $runner --station $Station --interval-seconds $IntervalSeconds 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $logPath -Append -Encoding utf8
    "[$((Get-Date).ToUniversalTime().ToString('o'))] exit=$LASTEXITCODE" | Out-File -FilePath $logPath -Append -Encoding utf8
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
