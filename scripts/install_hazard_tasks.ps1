param(
    [string]$HazardTaskName = "HAP-HazardRunner",
    [string]$StormTaskName = "HAP-ECMWFStorms",
    [switch]$Remove
)

# Registers the two shadow hazard jobs (see scripts/run_hazard_job.ps1):
#   HAP-HazardRunner  hourly       per-station storm / wave / heat / cold / disease records
#   HAP-ECMWFStorms   every 6 h    ECMWF Open Data cyclone tracks -> storm_watch records
# Remove with: scripts/install_hazard_tasks.ps1 -Remove

$ErrorActionPreference = "Stop"

if ($Remove) {
    foreach ($name in @($HazardTaskName, $StormTaskName)) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Output "Removed scheduled task: $name"
    }
    exit 0
}

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$runner = Join-Path $PSScriptRoot "run_hazard_job.ps1"
if (-not (Test-Path -LiteralPath $runner)) { throw "Job runner not found: $runner" }

# Same power settings as HAP-WeatherSnapshot: run on battery, wake the laptop, never overlap.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$jobs = @(
    @{ Name = $HazardTaskName; Job = "hazards"; Every = (New-TimeSpan -Hours 1); Offset = 3; Description = "Hourly per-station hazard shadow pass (theory only, not sent to farmers)." },
    # ECMWF publishes the 00/06/12/18 UTC cyclone tracks ~6-8 h after each cycle; the job takes the newest run available.
    @{ Name = $StormTaskName; Job = "storms"; Every = (New-TimeSpan -Hours 6); Offset = 7; Description = "ECMWF Open Data cyclone tracks every 6 h -> storm_watch shadow records." }
)

foreach ($j in $jobs) {
    $action = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Job $($j.Job)"
    $startAt = (Get-Date).AddMinutes($j.Offset)
    $trigger = New-ScheduledTaskTrigger -Once -At $startAt -RepetitionInterval $j.Every -RepetitionDuration (New-TimeSpan -Days 3650)
    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger -Settings $settings -Description $j.Description -Force | Out-Null
    Write-Output "Registered $($j.Name): first run ~$($startAt.ToString('yyyy-MM-dd HH:mm')), then every $($j.Every)."
}
