# ---------------------------------------------------------------
#  02-run.ps1  -  start the API and the web application locally
#
#  Both processes run in the background. Their output goes to
#  _logs\api-*.log and _logs\web-*.log. Stop them with 05-stop.ps1.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '02-run'
$root = Get-ProjectRoot
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$logDir = Join-Path $root '_logs'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

function Wait-ForUrl {
    param([string] $Url, [int] $TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        }
        catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

try {
    Write-Section 'Preconditions'
    $venvPython = Get-VenvPython
    Write-Ok 'Virtual environment found'
    if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
        throw 'Frontend packages are missing. Run scripts\01-setup.ps1 first.'
    }
    Write-Ok 'Frontend packages found'

    Write-Section 'Starting the API (uvicorn)'
    $apiOut = Join-Path $logDir ('api-' + $stamp + '.log')
    $apiErr = Join-Path $logDir ('api-' + $stamp + '.err.log')
    $api = Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload') `
        -WorkingDirectory $apiDir `
        -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr `
        -WindowStyle Hidden -PassThru
    Write-Info ('API process id: ' + $api.Id)

    Write-Section 'Starting the web application (vite)'
    $webOut = Join-Path $logDir ('web-' + $stamp + '.log')
    $webErr = Join-Path $logDir ('web-' + $stamp + '.err.log')
    $web = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/c', 'npm run dev') `
        -WorkingDirectory $webDir `
        -RedirectStandardOutput $webOut -RedirectStandardError $webErr `
        -WindowStyle Hidden -PassThru
    Write-Info ('Web process id: ' + $web.Id)

    @{ api = $api.Id; web = $web.Id; started = $stamp } |
        ConvertTo-Json | Set-Content -Path (Join-Path $logDir 'run-pids.json') -Encoding ASCII

    Write-Section 'Waiting for the services'
    $apiUp = Wait-ForUrl -Url 'http://127.0.0.1:8000/health' -TimeoutSeconds 90
    if ($apiUp) { Write-Ok 'API answered on http://127.0.0.1:8000/health' } else { Write-Fail 'API did not answer in time - see the api-*.log file' }

    $webUp = Wait-ForUrl -Url 'http://localhost:5173' -TimeoutSeconds 120
    if ($webUp) { Write-Ok 'Web application answered on http://localhost:5173' } else { Write-Fail 'Web application did not answer in time - see the web-*.log file' }

    if ($apiUp) {
        Write-Section 'Health snapshot'
        foreach ($path in @('/health', '/health/db', '/health/redis')) {
            try {
                $response = Invoke-WebRequest -Uri ('http://127.0.0.1:8000' + $path) -UseBasicParsing -TimeoutSec 10
                Write-Host ('  ' + $path + ' -> ' + $response.StatusCode + ' ' + $response.Content)
            }
            catch {
                $status = $_.Exception.Response.StatusCode.value__
                Write-Host ('  ' + $path + ' -> ' + $status + ' (dependency not available)')
            }
        }
    }

    Write-Section 'Open in the browser'
    Write-Host '  http://localhost:5173'
    Write-Host ''
    Write-Host '  Stop both services later with: scripts\05-stop.ps1'
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
