$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:ANONYMIZED_TELEMETRY = 'false'
$env:UV_INSTALL_DIR = Join-Path $PSScriptRoot '.runtime'
$uvPath = Join-Path $env:UV_INSTALL_DIR 'uv.exe'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$stoppedPrevious = $false
if (Test-Path -LiteralPath $projectPython) {
    Write-Host 'Checking and stopping the previous NCT Group Manager instance...'
    & $projectPython (Join-Path $PSScriptRoot 'restart_previous.py')
    if ($LASTEXITCODE -ne 0) { throw 'Previous instance could not be stopped safely. See the message above.' }
    $stoppedPrevious = $true
}
if (-not (Test-Path $uvPath)) {
    Write-Host 'Installing the official uv runtime (first start only)...'
    $env:UV_NO_MODIFY_PATH = '1'
    Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression
}
if (-not (Test-Path $uvPath)) { throw 'uv installation failed. Check your internet connection.' }
Write-Host 'Preparing Python 3.14 and Windows MCP. First start may take several minutes.'
& $uvPath sync --locked --python 3.14
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; the error is shown above.' }
if (-not $stoppedPrevious) {
    & $projectPython (Join-Path $PSScriptRoot 'restart_previous.py')
    if ($LASTEXITCODE -ne 0) { throw 'Previous instance could not be stopped safely. See the message above.' }
}
& $uvPath run --no-sync python app.py
if ($LASTEXITCODE -ne 0) { throw 'Application stopped unexpectedly. See data/app.log.' }

