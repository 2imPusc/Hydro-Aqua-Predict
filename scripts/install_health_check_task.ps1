param(
    [string]$Station = "06M26042804",
    [string]$TaskName = "HAP-HealthCheck",
    [string]$At = "00:25",
    [switch]$FixDockerStaleSockets,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled task: $TaskName"
    exit 0
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# pythonw: no console window flashing every hour (output goes to health.log only).
$python = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Root venv not found: $python" }

# Hourly, read-only check; appends one JSON line to runtime\logs\health.log and pops up a
# 30 s WScript.Shell message on FAIL or on a new WARN. Exit code 0 ok / 1 warn / 2 fail.
# Runs on battery, does NOT wake the machine (no -WakeToRun), and catches up once after sleep.
$arguments = "scripts\health_check.py --station $Station"
if ($FixDockerStaleSockets) { $arguments += " --fix-docker-stale-sockets" }
$action = New-ScheduledTaskAction -Execute $python -WorkingDirectory $repoRoot -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Hourly data-collection health check (docker, snapshots, logs, coverage, HAP-* tasks) -> runtime\logs\health.log." -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
