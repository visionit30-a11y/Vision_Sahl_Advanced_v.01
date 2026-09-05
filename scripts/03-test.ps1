# ---------------------------------------------------------------
#  03-test.ps1  -  run every quality gate for the current phase
#
#  Blocking gates : ruff check, mypy, pytest, eslint, tsc, vitest, build
#  Advisory gates : formatting checks (reported, never fail the run)
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '03-test'
$root = Get-ProjectRoot
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$results = New-Object System.Collections.ArrayList

function Add-Result {
    param([string] $Name, [int] $Code, [bool] $Blocking)
    [void]$results.Add([pscustomobject]@{ Gate = $Name; ExitCode = $Code; Blocking = $Blocking })
}

try {
    $venvPython = Get-VenvPython
    $npmExe = if (Test-CommandExists 'npm.cmd') { 'npm.cmd' } else { 'npm' }

    Write-Section 'Backend - ruff (lint)'
    Add-Result 'ruff check' (Invoke-Native -File $venvPython -Arguments @('-m', 'ruff', 'check', '.') -WorkingDirectory $apiDir -AllowFailure) $true

    Write-Section 'Backend - ruff (format check, advisory)'
    Add-Result 'ruff format --check' (Invoke-Native -File $venvPython -Arguments @('-m', 'ruff', 'format', '--check', '.') -WorkingDirectory $apiDir -AllowFailure) $false

    Write-Section 'Backend - mypy (types)'
    Add-Result 'mypy' (Invoke-Native -File $venvPython -Arguments @('-m', 'mypy') -WorkingDirectory $apiDir -AllowFailure) $true

    Write-Section 'Backend - pytest'
    Add-Result 'pytest' (Invoke-Native -File $venvPython -Arguments @('-m', 'pytest') -WorkingDirectory $apiDir -AllowFailure) $true

    Write-Section 'Frontend - eslint'
    Add-Result 'eslint' (Invoke-Native -File $npmExe -Arguments @('run', 'lint') -WorkingDirectory $webDir -AllowFailure) $true

    Write-Section 'Frontend - typescript'
    Add-Result 'tsc --noEmit' (Invoke-Native -File $npmExe -Arguments @('run', 'typecheck') -WorkingDirectory $webDir -AllowFailure) $true

    Write-Section 'Frontend - vitest'
    Add-Result 'vitest' (Invoke-Native -File $npmExe -Arguments @('run', 'test') -WorkingDirectory $webDir -AllowFailure) $true

    Write-Section 'Frontend - production build'
    Add-Result 'vite build' (Invoke-Native -File $npmExe -Arguments @('run', 'build') -WorkingDirectory $webDir -AllowFailure) $true

    Write-Section 'Frontend - prettier (advisory)'
    Add-Result 'prettier --check' (Invoke-Native -File $npmExe -Arguments @('run', 'format:check') -WorkingDirectory $webDir -AllowFailure) $false

    Write-Section 'Summary'
    foreach ($result in $results) {
        $label = if ($result.ExitCode -eq 0) { 'PASS' } elseif ($result.Blocking) { 'FAIL' } else { 'WARN' }
        Write-Host ("  {0,-6} {1,-22} exit={2}" -f $label, $result.Gate, $result.ExitCode)
    }

    $blockingFailures = @($results | Where-Object { $_.Blocking -and $_.ExitCode -ne 0 })
    if ($blockingFailures.Count -eq 0) {
        Write-Host ''
        Write-Host 'All blocking quality gates passed.'
    }
    else {
        Write-Host ''
        Write-Host ('Blocking failures: ' + ($blockingFailures.Gate -join ', '))
    }
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
