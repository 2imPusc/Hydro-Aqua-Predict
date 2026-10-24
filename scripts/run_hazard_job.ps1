param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("hazards", "storms")]
    [string]$Job
)

# One scheduled hazard job (shadow only, nothing is sent to farmers):
#   hazards: per-station shadow pass (core.hazard_runner), hourly.
#   storms:  ECMWF Open Data tropical-cyclone tracks -> storm_watch records (experiments/ecmwf_opendata.py run), every 6 h.
# Output goes to runtime/hazard-shadow/ (append-only); a one-line status per run goes to runtime/logs/hazard-jobs.log.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Project Python not found: $python" }

$logDir = Join-Path $repoRoot "runtime\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "hazard-jobs.log"
$startedAt = (Get-Date).ToUniversalTime().ToString("o")

# Heat / cold / disease need the Open-Meteo marine SST; enabled for these jobs only (owner decision 2026-10-24).
$env:MARINE_ENABLED = "true"
$env:PYTHONIOENCODING = "utf-8"

Push-Location $repoRoot
try {
    # Windows PowerShell 5.1 turns any native stderr line (e.g. a numpy RuntimeWarning) into a terminating
    # error under "Stop"; the exit code decides success instead.
    $ErrorActionPreference = "Continue"
    if ($Job -eq "hazards") {
        $output = & $python -m core.hazard_runner 2>&1
    } else {
        $output = & $python (Join-Path $repoRoot "experiments\ecmwf_opendata.py") run 2>&1
    }
    $code = $LASTEXITCODE
    $last = ($output | ForEach-Object { "$_" } | Where-Object { $_ -notmatch "RuntimeWarning|nanmean|return np\." } | Select-Object -Last 1)
    "[$startedAt] job=$Job exit=$code $last" | Out-File -FilePath $logPath -Append -Encoding utf8
    if ($code -ne 0) { exit $code }
}
catch {
    "[$startedAt] job=$Job status=failed error=$($_.Exception.Message)" | Out-File -FilePath $logPath -Append -Encoding utf8
    throw
}
finally {
    Pop-Location
}
