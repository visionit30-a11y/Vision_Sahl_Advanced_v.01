# ---------------------------------------------------------------
#  02-run.ps1  -  start the API and the web application locally
#
#  Safe to run repeatedly: it stops whatever an earlier run left behind,
#  frees the development ports, starts both services, then proves they are
#  really serving - including through the exact path the browser uses.
#
#  Output goes to _logs\api-*.log and _logs\web-*.log. Stop with 05-stop.ps1.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '02-run'
$root = Get-ProjectRoot
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$logDir = Join-Path $root '_logs'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$API_PORT = 8000
$WEB_PORT = 5173

function Wait-ForUrl {
    param([string] $Url, [int] $TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        }
        catch {
            $status = $_.Exception.Response.StatusCode.value__
            if ($status -ge 200 -and $status -lt 500) { return $true }
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

function Get-HealthPayload {
    param([string] $Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        return [pscustomobject]@{ Status = $response.StatusCode; Body = $response.Content }
    }
    catch {
        $status = $_.Exception.Response.StatusCode.value__
        $body = ''
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $body = $reader.ReadToEnd()
        }
        catch { }
        return [pscustomobject]@{ Status = $status; Body = $body }
    }
}

try {
    Write-Section 'Preconditions'
    $venvPython = Get-VenvPython
    Write-Ok 'Virtual environment found'
    if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
        throw 'Frontend packages are missing. Run scripts\01-setup.ps1 first.'
    }
    Write-Ok 'Frontend packages found'

    Write-Section 'Clearing anything left from an earlier run'
    Stop-SahlServices
    Start-Sleep -Seconds 1
    foreach ($port in @($API_PORT, $WEB_PORT)) {
        if (-not (Clear-DevelopmentPort -Port $port)) {
            throw "Port $port could not be freed. Nothing was started."
        }
        Write-Ok "port $port is free"
    }

    Write-Section 'Starting the API (uvicorn)'
    $apiOut = Join-Path $logDir ('api-' + $stamp + '.log')
    $apiErr = Join-Path $logDir ('api-' + $stamp + '.err.log')
    $api = Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$API_PORT", '--reload') `
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
        ConvertTo-Json | Set-Content -Path (Get-RunPidFile) -Encoding ASCII

    Write-Section 'Waiting for the services'
    $apiUp = Wait-ForUrl -Url ("http://127.0.0.1:{0}/health" -f $API_PORT) -TimeoutSeconds 90
    if ($apiUp) { Write-Ok ('API answered on port ' + $API_PORT) } else { Write-Fail 'API did not answer in time' }

    $webUp = Wait-ForUrl -Url ("http://localhost:{0}" -f $WEB_PORT) -TimeoutSeconds 120
    if ($webUp) { Write-Ok ('Web application answered on port ' + $WEB_PORT) } else { Write-Fail 'Web application did not answer in time' }

    Write-Section 'Are the processes this script started still alive?'
    $failures = @()
    foreach ($item in @(@{ Name = 'api'; Process = $api; Log = $apiErr }, @{ Name = 'web'; Process = $web; Log = $webErr })) {
        if ($null -eq (Get-Process -Id $item.Process.Id -ErrorAction SilentlyContinue)) {
            Write-Fail ($item.Name + ' exited straight after starting. Last lines of its log:')
            if (Test-Path $item.Log) {
                Get-Content $item.Log -Tail 12 | ForEach-Object { Write-Host ('    ' + $_) }
            }
            $failures += $item.Name
        }
        else {
            Write-Ok ($item.Name + ' is running (pid ' + $item.Process.Id + ')')
        }
    }

    Write-Section 'Health through the API directly'
    foreach ($path in @('/health', '/health/db', '/health/redis')) {
        $result = Get-HealthPayload -Url ("http://127.0.0.1:{0}{1}" -f $API_PORT, $path)
        Write-Host ('  ' + $path + ' -> ' + $result.Status + ' ' + $result.Body)
    }

    Write-Section 'Health through the web origin (the path the browser uses)'
    foreach ($path in @('/health', '/health/db', '/health/redis')) {
        $result = Get-HealthPayload -Url ("http://localhost:{0}{1}" -f $WEB_PORT, $path)
        $isJson = $result.Body -match '"(status|dependency)"'
        Write-Host ('  ' + $path + ' -> ' + $result.Status + ' ' + $result.Body)
        if (-not $isJson) {
            Write-Fail ($path + ' did not return the API payload through the dev server proxy.')
            $failures += ('proxy' + $path)
        }
    }

    Write-Section 'Result'
    if ($failures.Count -eq 0 -and $apiUp -and $webUp) {
        Write-Ok 'Both services are running and the browser path is verified end to end.'
        Write-Host ''
        Write-Host ("  Open in the browser: http://localhost:{0}" -f $WEB_PORT)
        Write-Host '  Stop both services later with: scripts\05-stop.ps1'
    }
    else {
        Write-Fail ('Startup problems: ' + ($failures -join ', '))
        Write-Host '  Do not review in the browser yet; the log above explains what failed.'
    }
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
