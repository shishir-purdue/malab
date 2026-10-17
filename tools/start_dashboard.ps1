param([int]$Port = 8765, [string]$Config = '', [string]$Usb, [switch]$Restart, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dashboardPython = Join-Path $dashboardRoot '.venv-bench/Scripts/python.exe'
if (-not $Config) { $Config = if ($env:DAC_BENCH_CONFIG) { $env:DAC_BENCH_CONFIG } else { Join-Path $dashboardRoot 'config/bench.local.json' } }
$Config = (Resolve-Path -LiteralPath $Config).Path
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
if ($dashboardLive -and $Restart) {
    if (@($dashboardState.units | Where-Object { $_.pending -or $_.ramp.state -eq 'RUNNING' -or $_.recovery.state -eq 'ACTIVE' }).Count -gt 0) {
        throw 'A unit is busy. Stop its ramp or wait for safe zero before restarting the dashboard.'
    }
    if (-not $dashboardState.server_pid) { throw 'This older server has no process ID; stop its terminal before restarting.' }
    $dashboardOwner = Get-CimInstance Win32_Process -Filter "ProcessId=$($dashboardState.server_pid)"
    if ($dashboardOwner.Name -ne 'python.exe' -or $dashboardOwner.CommandLine -notmatch '-m malab.dashboard') { throw 'Unexpected dashboard process' }
    $dashboardStopping = [System.Diagnostics.Process]::GetProcessById([int]$dashboardState.server_pid)
    $dashboardStopping.Kill()
    $dashboardStopping.WaitForExit(3000) | Out-Null
    $dashboardLive = $false
}
if (-not $dashboardLive) {
    $dashboardLogs = Join-Path $dashboardRoot 'tests/results/dashboard'
    New-Item -ItemType Directory -Force -Path $dashboardLogs | Out-Null
    $dashboardArguments = @('-u','-m','malab.dashboard','--port',"$Port",'--config',('"{0}"' -f $Config))
    if ($PSBoundParameters.ContainsKey('Usb')) { $dashboardArguments += @('--usb', $Usb) }
    $dashboardProcess = Start-Process -FilePath $dashboardPython -ArgumentList $dashboardArguments -WorkingDirectory $dashboardRoot -WindowStyle Hidden -RedirectStandardOutput "$dashboardLogs/server.log" -RedirectStandardError "$dashboardLogs/server-error.log" -PassThru
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
if ($dashboardState.server_pid) { $dashboardState.server_pid | Set-Content (Join-Path $dashboardRoot 'tests/results/dashboard/server.pid') }
Write-Output "Dashboard: $dashboardUrl"
Write-Output 'After changing the IP/USB list or meter channel, use -Restart while all units are idle.'
if (-not $NoBrowser) {
    $dashboardChrome = @("${env:ProgramFiles}/Google/Chrome/Application/chrome.exe", "${env:ProgramFiles(x86)}/Google/Chrome/Application/chrome.exe", "$env:LOCALAPPDATA/Google/Chrome/Application/chrome.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($dashboardChrome) { Start-Process -FilePath $dashboardChrome -ArgumentList $dashboardUrl }
    else { Write-Output "Open $dashboardUrl in Chrome." }
}
