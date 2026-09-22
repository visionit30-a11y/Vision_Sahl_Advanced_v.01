[CmdletBinding()]
param(
    # Use this switch when running from an existing PowerShell window.
    [switch] $CurrentWindow,
    # Internal switch used by the script when it opens its own console.
    [switch] $Relaunched
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runScript = Join-Path $projectRoot 'scripts\02-run.ps1'
$setupScript = Join-Path $projectRoot 'scripts\01-setup.ps1'
$envFile = Join-Path $projectRoot '.env'
$apiVenv = Join-Path $projectRoot 'apps\api\.venv'
$webModules = Join-Path $projectRoot 'apps\web\node_modules'

function Stop-WithMessage {
    param([string] $Message)

    Write-Host ''
    Write-Host ('[X] ' + $Message) -ForegroundColor Red
    Write-Host ''
    exit 1
}

function Test-HttpEndpoint {
    param([string] $Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

if (-not $CurrentWindow -and -not $Relaunched) {
    $powerShell = (Get-Process -Id $PID).Path
    $arguments = @(
        '-NoExit',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"'),
        '-Relaunched'
    )
    Start-Process -FilePath $powerShell -ArgumentList $arguments -WorkingDirectory $projectRoot
    return
}

Set-Location -LiteralPath $projectRoot

Write-Host ''
Write-Host 'Sahl Developer Platform - Local Startup' -ForegroundColor Cyan
Write-Host '---------------------------------------' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $runScript)) {
    Stop-WithMessage 'scripts\02-run.ps1 is missing.'
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host 'The local environment has not been prepared yet.' -ForegroundColor Yellow
    Write-Host ('Run once: ' + $setupScript)
    Stop-WithMessage '.env is missing.'
}

if (-not (Test-Path -LiteralPath $apiVenv) -or -not (Test-Path -LiteralPath $webModules)) {
    Write-Host 'Local dependencies are incomplete.' -ForegroundColor Yellow
    Write-Host ('Run once: ' + $setupScript)
    Stop-WithMessage 'Python or frontend dependencies are missing.'
}

$postgresReady = $false
try {
    $connection = New-Object System.Net.Sockets.TcpClient
    $async = $connection.BeginConnect('127.0.0.1', 5433, $null, $null)
    $postgresReady = $async.AsyncWaitHandle.WaitOne(2000, $false) -and $connection.Connected
    $connection.Close()
}
catch {
    $postgresReady = $false
}

if (-not $postgresReady) {
    Stop-WithMessage 'Sahl PostgreSQL is not listening on 127.0.0.1:5433. Start the approved local PostgreSQL service, then run this file again.'
}

Write-Host '[OK] PostgreSQL is available on 127.0.0.1:5433' -ForegroundColor Green
Write-Host '[..] Starting Backend on 127.0.0.1:8010 and Frontend on localhost:5173'
Write-Host ''

& $runScript

if (-not (Test-HttpEndpoint -Url 'http://127.0.0.1:8010/health')) {
    Stop-WithMessage 'Backend startup verification failed. Review the latest files in _logs.'
}

if (-not (Test-HttpEndpoint -Url 'http://localhost:5173/login')) {
    Stop-WithMessage 'Frontend startup verification failed. Review the latest files in _logs.'
}

Write-Host ''
Write-Host '[OK] Local services are ready.' -ForegroundColor Green
Write-Host 'Frontend: http://localhost:5173/login' -ForegroundColor Cyan
Write-Host 'Backend:  http://127.0.0.1:8010' -ForegroundColor Cyan
Write-Host 'API docs: http://127.0.0.1:8010/docs' -ForegroundColor Cyan
Write-Host 'Stop:     .\scripts\05-stop.ps1' -ForegroundColor Cyan
