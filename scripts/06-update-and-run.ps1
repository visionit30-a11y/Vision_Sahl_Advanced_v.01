# ---------------------------------------------------------------
#  06-update-and-run.ps1 - guarded local startup on fixed ports
#  Port 8010 never falls back, changes automatically, or kills an
#  unrelated process. Project-owned leftovers are handled by 02-run.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '06-update-and-run'
$exitCode = 0
$apiPort = 8010

try {
    Write-Section 'Fixed local port preflight'
    $owner = Get-PortOwner -Port $apiPort
    if ($null -ne $owner) {
        if (-not (Test-ProcessBelongsToProject -ProcessId $owner.Id)) {
            throw ("Port 8010 is already used by {0} (pid {1}), which is not part of this project. " +
                "Nothing was stopped. Close or move that application, then retry; port 8000 is not a fallback." -f
                $owner.ProcessName, $owner.Id)
        }
        Write-Info ("Port 8010 is held by this project (pid {0}); the normal project cleanup may stop it." -f $owner.Id)
    }
    else {
        Write-Ok 'Port 8010 is available.'
    }

}
catch {
    $exitCode = 1
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}

if ($exitCode -ne 0) { exit $exitCode }

# 02-run owns its own transcript and performs a second, race-safe port check.
& (Join-Path $PSScriptRoot '02-run.ps1')
