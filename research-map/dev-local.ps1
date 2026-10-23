# Local dev launcher: Postgres in Docker, API/worker/frontend on host.
#   powershell -ExecutionPolicy Bypass -File dev-local.ps1 [-NoWorker]
param([switch]$NoWorker)

$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend-fastapi"
$Frontend = Join-Path $Root "frontend"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"

function Import-DotEnv($Path) {
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$' -and $Matches[2] -ne '') {
            if (-not [Environment]::GetEnvironmentVariable($Matches[1])) {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'))
            }
        }
    }
}

Import-DotEnv (Join-Path $Root ".env")
# Reuse GreenLab credentials from the project .env when research-map/.env leaves them blank.
Import-DotEnv (Join-Path $Root "..\.env")

# Containers reach Postgres as postgres:5432; the host sees the published port 5434.
if ($env:DATABASE_URL) {
    $env:DATABASE_URL = $env:DATABASE_URL -replace '@postgres:5432', '@localhost:5434'
}
$env:PYTHONPATH = $Backend
# The Docker Postgres has no SSL; a machine-wide PGSSLMODE=require would break the connection.
$env:PGSSLMODE = "prefer"

if (-not (Test-Path $Py)) {
    Write-Error "Missing $Py. Run: py -3.11 -m venv backend-fastapi\.venv; backend-fastapi\.venv\Scripts\python -m pip install -r backend-fastapi\requirements.txt"
    exit 1
}

Push-Location $Root
docker compose up -d postgres
Pop-Location

Start-Process powershell -WorkingDirectory $Backend -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='research-map api'; & '$Py' -m uvicorn app.main:app --reload --port 8010"
if (-not $NoWorker) {
    Start-Process powershell -WorkingDirectory $Backend -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='research-map worker'; & '$Py' -m app.worker"
}
Start-Process powershell -WorkingDirectory $Frontend -ArgumentList "-NoExit", "-Command", "`$host.UI.RawUI.WindowTitle='research-map frontend'; npm run dev"

Write-Host "API      http://localhost:8010/docs"
Write-Host "Frontend http://localhost:5173"
