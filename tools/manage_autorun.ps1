param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$taskName = "WyyVisualAssistDaily"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

if ($Uninstall) {
    # Same current-user Run mechanism as dmaid; never touch DigitMaid's value.
    Remove-ItemProperty -LiteralPath $runKey -Name $taskName -ErrorAction SilentlyContinue
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
$startupCommand = "`"$powershell`" $arguments"
if ($startupCommand.Length -gt 260) {
    throw "开机命令超过 Windows Run 项的 260 字符限制，请缩短项目路径。"
}

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument $arguments `
    -WorkingDirectory $projectDirectory
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

$runProperties = Get-ItemProperty -LiteralPath $runKey -ErrorAction SilentlyContinue
$previousStartup = $null
if ($null -ne $runProperties -and $null -ne $runProperties.PSObject.Properties[$taskName]) {
    $previousStartup = $runProperties.PSObject.Properties[$taskName].Value
}
if (-not (Test-Path -LiteralPath $runKey)) { New-Item -Path $runKey | Out-Null }
New-ItemProperty -LiteralPath $runKey -Name $taskName -PropertyType String -Value $startupCommand -Force | Out-Null
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger @($dailyTrigger) `
        -Settings $settings `
        -Principal $principal `
        -Description "每日 00:05 检查当日 limit；登录自启由同名当前用户 Run 项负责。" `
        -Force | Out-Null
}
catch {
    if ($null -eq $previousStartup) {
        Remove-ItemProperty -LiteralPath $runKey -Name $taskName -ErrorAction SilentlyContinue
    }
    else {
        Set-ItemProperty -LiteralPath $runKey -Name $taskName -Value $previousStartup
    }
    throw
}
if ((Get-ItemPropertyValue -LiteralPath $runKey -Name $taskName) -ne $startupCommand) {
    throw "开机启动项写入校验失败。"
}

Write-Host "已安装当前用户 Run 启动项：$taskName（与 dmaid 相同机制）"
Write-Host "已保留每日 00:05 计划任务：$taskName；移除重复的登录触发器"
