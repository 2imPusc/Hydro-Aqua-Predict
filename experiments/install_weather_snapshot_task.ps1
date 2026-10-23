param(
    [string]$Station = "06M26042804",
    [string]$TaskName = "HAP-WeatherSnapshot-06M26042804",
    [ValidateRange(15, 1440)]
    [int]$IntervalMinutes = 60,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled task: $TaskName"
    exit 0
}

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$runner = Join-Path $scriptDir "run_weather_snapshot.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Snapshot runner was not found: $runner"
}

# A single hourly task is enough for forecast products published on hourly
# boundaries.  It is append-only and is intentionally separate from runtime.
$action = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Station `"$Station`""
$startAt = (Get-Date).AddMinutes(2)
$trigger = New-ScheduledTaskTrigger -Once -At $startAt -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
# Run on battery too: the B5 study needs an unbroken hourly as-issued record,
# and the default "no start on batteries" silently queued captures on laptops.
# WakeToRun: the laptop sleeps between uses; without it the hourly record has
# multi-day holes (7-day coverage was ~32% on 2026-10-15). Wake timers must
# also be enabled in the power plan (see AGENTS.md).
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Append-only as-issued Open-Meteo forecast capture for sensor $Station (research/shadow only)." -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath
Write-Output "Next capture starts at approximately $($startAt.ToString('yyyy-MM-dd HH:mm:ss')) then every $IntervalMinutes minutes."
