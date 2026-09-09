$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $projectDirectory "start.py"
$logDirectory = Join-Path $projectDirectory "logs"
$logPath = Join-Path $logDirectory "autorun.log"
$preferredPython = "D:\Basement\Miniconda3\envs\jiaoworun\python.exe"

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Add-Content -LiteralPath $logPath -Value "`r`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

if (Test-Path -LiteralPath $preferredPython -PathType Leaf) {
    $python = $preferredPython
}
else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        Add-Content -LiteralPath $logPath -Value "找不到 Python：$preferredPython"
        exit 2
    }
    $python = $pythonCommand.Source
}

Push-Location $projectDirectory
try {
    & $python $startScript --no-pause *>> $logPath
    $exitCode = $LASTEXITCODE
}
catch {
    $_ | Out-String | Add-Content -LiteralPath $logPath
    $exitCode = 2
}
finally {
    Pop-Location
}

Add-Content -LiteralPath $logPath -Value "退出码：$exitCode"
exit $exitCode
