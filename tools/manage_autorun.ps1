param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$taskName = "WyyVisualAssistDaily"

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "已删除计划任务：$taskName"
    }
    else {
        Write-Host "计划任务不存在，无需删除：$taskName"
    }
    exit 0
}

$projectDirectory = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_autorun.ps1"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = "-NoProfile -NonInteractive -WindowStyle Minimized -ExecutionPolicy Bypass -File `"$runner`""

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument $arguments `
    -WorkingDirectory $projectDirectory
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At "00:05"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($logonTrigger, $dailyTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description "登录 Windows 或进入新的一天后运行 Android 视觉状态机；当日 limit 后自动跳过。" `
    -Force | Out-Null

Write-Host "已安装计划任务：$taskName"
Write-Host "触发时间：当前用户登录时，以及每日 00:05（错过后尽快补跑）"
