$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Build desktop requires Windows x64.' }
$tools = Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$sdkVersion = '1.0.4314.35'
$sdkZip = Join-Path $tools 'webview2.zip'
$sdkDirectory = Join-Path $tools 'webview2'
if (-not (Test-Path (Join-Path $sdkDirectory 'lib/net462/Microsoft.Web.WebView2.Core.dll'))) {
    Invoke-WebRequest "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$sdkVersion/microsoft.web.webview2.$sdkVersion.nupkg" -OutFile $sdkZip
    Expand-Archive -LiteralPath $sdkZip -DestinationPath $sdkDirectory -Force
}
$compiler = Join-Path $tools 'InnoSetup643/ISCC.exe'
if (-not (Test-Path $compiler)) {
    $installer = Join-Path $tools 'innosetup643.exe'
    Invoke-WebRequest 'https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe' -OutFile $installer
    if ((Get-AuthenticodeSignature $installer).Status -ne 'Valid') { throw 'Could not verify Inno Setup publisher signature.' }
    $installDirectory = Join-Path $tools 'InnoSetup643'
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/CURRENTUSER', "/DIR=`"$installDirectory`"", '/NOICONS')
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw "Inno Setup install failed: $($process.ExitCode)" }
}
Write-Host 'Build tools are ready. Run build.ps1 next.'
