$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $projectDirectory "start.py"
$configPath = Join-Path $projectDirectory "config.json"
$preferredPython = "D:\Basement\Miniconda3\envs\jiaoworun\python.exe"
try {
    if (Test-Path -LiteralPath $preferredPython -PathType Leaf) {
        $python = $preferredPython
    }
    else {
        $python = (Get-Command python.exe -ErrorAction Stop).Source
    }
    Push-Location $projectDirectory
    try {
        # Python supervises its worker and writes UTF-8 logs. PS 5.1 redirection
        # previously turned native stderr into a terminating NativeCommandError.
        $ErrorActionPreference = "Continue"
        & $python -u $startScript --config $configPath --no-pause --autorun
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
}
catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "自动运行启动失败：$($_.Exception.Message)", "启动失败") | Out-Null
    $exitCode = 2
}
exit $exitCode
