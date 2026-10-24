param(
    [switch]$Start,
    [string]$TaskName = "HAP-ShadowRunner"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Runner = Join-Path $RepoRoot "core\shadow_runner.py"

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Không tìm thấy Python môi trường dự án: $PythonExe" }
if (-not (Test-Path -LiteralPath $Runner)) { throw "Không tìm thấy shadow runner: $Runner" }

# Wrapper sets GREENLAB_FETCH_MODE=live / MARINE_ENABLED=true for this process and logs to runtime/logs/shadow-runner.log.
$Wrapper = Join-Path $RepoRoot "scripts\run_shadow_runner.ps1"
$Action = New-ScheduledTaskAction -Execute (Get-Command powershell.exe).Source -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $Wrapper + '" -Station 06M26042804 -IntervalSeconds 60') -WorkingDirectory $RepoRoot
# No admin needed (an -AtLogOn trigger or an explicit principal is refused without elevation): start now and
# re-check every 5 min; IgnoreNew keeps a single long-running runner and restarts it if it ever exits.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Shadow runner (H1.5): live sensor forecasts + ledgers, research only." -Force -ErrorAction Stop | Out-Null
Write-Host "Đã đăng ký Scheduled Task: $TaskName"
if ($Start) { Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop; Write-Host "Đã khởi động task." }
