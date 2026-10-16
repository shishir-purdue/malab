param([int]$Port = 8765, [string]$Usb = 'COM5', [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dashboardPython = Join-Path $dashboardRoot '.venv-bench/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $dashboardPython)) {
    throw "Bench Python is missing: $dashboardPython. Follow malab/dashboard/README.md first."
}
$dashboardUrl = "http://localhost:$Port"
$dashboardProbe = "http://127.0.0.1:$Port"
$dashboardLive = $false
try {
    $dashboardState = Invoke-RestMethod "$dashboardProbe/api/state" -TimeoutSec 2
    $dashboardLive = ($null -ne $dashboardState.server_started)
} catch { }
if (-not $dashboardLive) {
    $dashboardLogs = Join-Path $dashboardRoot 'tests/results/dashboard'
    New-Item -ItemType Directory -Force -Path $dashboardLogs | Out-Null
    $dashboardProcess = Start-Process -FilePath $dashboardPython -ArgumentList '-u','-m','malab.dashboard','--port',"$Port",'--usb',$Usb -WorkingDirectory $dashboardRoot -WindowStyle Hidden -RedirectStandardOutput "$dashboardLogs/server.log" -RedirectStandardError "$dashboardLogs/server-error.log" -PassThru
    $dashboardProcess.Id | Set-Content "$dashboardLogs/server.pid"
    for ($dashboardAttempt=0; $dashboardAttempt -lt 30; $dashboardAttempt++) {
        try {
            $dashboardState = Invoke-RestMethod "$dashboardProbe/api/state" -TimeoutSec 1
            $dashboardLive = ($null -ne $dashboardState.server_started)
            if ($dashboardLive) { break }
        } catch { }
        Start-Sleep -Milliseconds 200
        if ($dashboardProcess.HasExited) { throw "Dashboard stopped; inspect $dashboardLogs/server-error.log" }
    }
    if (-not $dashboardLive) { throw "Dashboard did not become ready; inspect $dashboardLogs/server-error.log" }
}
Write-Output "Dashboard: $dashboardUrl"
if (-not $NoBrowser) {
    $dashboardChrome = @("${env:ProgramFiles}/Google/Chrome/Application/chrome.exe", "${env:ProgramFiles(x86)}/Google/Chrome/Application/chrome.exe", "$env:LOCALAPPDATA/Google/Chrome/Application/chrome.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($dashboardChrome) { Start-Process -FilePath $dashboardChrome -ArgumentList $dashboardUrl }
    else { Write-Output "Open $dashboardUrl in Chrome." }
}
