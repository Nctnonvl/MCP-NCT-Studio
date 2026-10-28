$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) { $uvPath = $uv.Source }
elseif (Test-Path 'source/.runtime/uv.exe') { $uvPath = Join-Path $PSScriptRoot 'source/.runtime/uv.exe' }
else { throw 'Install uv from https://docs.astral.sh/uv/ or run source/start.bat once.' }
& $uvPath sync --project source --locked --python 3.14
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$python = Join-Path $PSScriptRoot 'source/.venv/Scripts/python.exe'
if (-not (Test-Path 'tools/webview2/lib/net462/Microsoft.Web.WebView2.Core.dll')) { throw 'Run prepare_build.ps1 first.' }
if (-not (Test-Path 'tools/InnoSetup643/ISCC.exe')) { throw 'Run prepare_build.ps1 first.' }
& $python -X utf8 build_release.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
& 'tools/InnoSetup643/ISCC.exe' /Qp 'native/setup.iss'
if ($LASTEXITCODE -ne 0) { throw 'Setup build failed.' }
Write-Host 'Ready: output/NCT-Studio-Portable/NCT Studio.exe and output/NCT-Studio-Setup.exe'
