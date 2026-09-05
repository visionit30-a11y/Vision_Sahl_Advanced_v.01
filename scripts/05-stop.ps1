# ---------------------------------------------------------------
#  05-stop.ps1  -  stop the processes started by 02-run.ps1
#  Only the recorded process ids are stopped. Nothing else is touched.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '05-stop'
$root = Get-ProjectRoot
$pidFile = Join-Path $root '_logs\run-pids.json'

try {
    if (-not (Test-Path $pidFile)) {
        Write-Info 'No running services were recorded. Nothing to stop.'
        return
    }

    $recorded = Get-Content $pidFile -Raw | ConvertFrom-Json
    foreach ($name in @('api', 'web')) {
        $processId = $recorded.$name
        if (-not $processId) { continue }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            Write-Info ($name + ' (pid ' + $processId + ') is not running')
            continue
        }
        Invoke-Native -File 'taskkill' -Arguments @('/PID', "$processId", '/T', '/F') -AllowFailure | Out-Null
        Write-Ok ($name + ' stopped (pid ' + $processId + ')')
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
