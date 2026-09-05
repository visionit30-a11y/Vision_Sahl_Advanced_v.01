# ---------------------------------------------------------------
#  05-stop.ps1  -  stop the processes started by 02-run.ps1
#  Only the recorded process ids are stopped. Nothing else is touched.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '05-stop'

try {
    if (-not (Test-Path (Get-RunPidFile))) {
        Write-Info 'No running services were recorded. Nothing to stop.'
    }
    else {
        Stop-SahlServices
        Write-Ok 'Recorded services stopped.'
    }
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
