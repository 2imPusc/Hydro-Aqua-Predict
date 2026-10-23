param(
    [string]$Station = "06M26042804",
    [string]$Region = "HAIPHONG",
    [string]$TaskName = "",
    [string]$At = "06:13",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
if (-not $TaskName) { $TaskName = "HAP-SensorCollector-$Station" }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled task: $TaskName"
    exit 0
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Root venv not found: $python" }

# Daily catch-up: DataByDate is retrospective, so a missed day is fetched by
# the next successful run (--since-last). Existing files are never overwritten.
$action = New-ScheduledTaskAction -Execute $python -WorkingDirectory $repoRoot -Argument "scripts\backfill_sensor.py --station $Station --region $Region --since-last"
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily GreenLab DataByDate catch-up for $Station (append-only files)." -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
