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

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument ('"' + $Runner + '" --station 06M26042804 --interval-seconds 60') -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force -ErrorAction Stop | Out-Null
Write-Host "Đã đăng ký Scheduled Task: $TaskName"
if ($Start) { Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop; Write-Host "Đã khởi động task." }
