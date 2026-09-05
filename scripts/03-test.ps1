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
    # ExitCode -1 means the gate was skipped because a precondition was missing.
    param([string] $Name, [int] $Code, [bool] $Blocking)
    [void]$results.Add([pscustomobject]@{ Gate = $Name; ExitCode = $Code; Blocking = $Blocking })
}

try {
    $venvPython = Get-VenvPython
    $npmExe = if (Test-CommandExists 'npm.cmd') { 'npm.cmd' } else { 'npm' }

    Write-Section 'Backend - dependency lock'
    if (-not (Test-CommandExists 'uv')) {
        throw 'uv was not found in PATH. Install it from https://docs.astral.sh/uv/ and run scripts\01-setup.ps1.'
    }
    # Blocking: a lock that no longer matches pyproject means the tree that CI
    # installs and the tree installed here can differ, which is the whole reason
    # the lock exists.
    Add-Result 'uv lock --check' (Invoke-Native -File 'uv' -Arguments @('lock', '--check') -WorkingDirectory $apiDir -AllowFailure) $true
    Invoke-Native -File 'uv' -Arguments @('sync', '--frozen') -WorkingDirectory $apiDir -AllowFailure | Out-Null

    Write-Section 'Frontend - dependency freshness'
    $manifest = Join-Path $webDir 'package.json'
    $installMarker = Join-Path $webDir 'node_modules\.package-lock.json'
    $needsInstall = -not (Test-Path $installMarker)
    if (-not $needsInstall) {
        $needsInstall = (Get-Item $manifest).LastWriteTimeUtc -gt (Get-Item $installMarker).LastWriteTimeUtc
    }
    if ($needsInstall) {
        Write-Info 'package.json is newer than the installed tree - refreshing packages'
        Invoke-Native -File $npmExe -Arguments @('install', '--no-fund', '--no-audit') -WorkingDirectory $webDir | Out-Null
    }
    else {
        Write-Info 'Frontend packages are up to date'
    }

    # Formatting is applied, not just checked, so the gates below run on
    # formatted sources. Only layout changes; no tool behaviour is altered.
    Write-Section 'Auto-format (ruff format / prettier --write)'
    Invoke-Native -File $venvPython -Arguments @('-m', 'ruff', 'format', '.') -WorkingDirectory $apiDir -AllowFailure | Out-Null
    Invoke-Native -File $npmExe -Arguments @('run', 'format') -WorkingDirectory $webDir -AllowFailure | Out-Null

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

    Write-Section 'Database - migration round trip'
    $databasePort = $null
    $databaseUrl = Get-EnvValue 'DATABASE_URL'
    if ($databaseUrl -match '@[^:/]+:(\d+)/') { $databasePort = [int]$Matches[1] }
    if ($databasePort -and (Test-TcpPort -Port $databasePort)) {
        $down = Invoke-Native -File $venvPython -Arguments @('-m', 'alembic', 'downgrade', 'base') -WorkingDirectory $apiDir -AllowFailure
        $up = Invoke-Native -File $venvPython -Arguments @('-m', 'alembic', 'upgrade', 'head') -WorkingDirectory $apiDir -AllowFailure
        Invoke-Native -File $venvPython -Arguments @('-m', 'alembic', 'current') -WorkingDirectory $apiDir -AllowFailure | Out-Null
        $roundTrip = if ($down -ne 0) { $down } else { $up }
        Add-Result 'alembic down/up' $roundTrip $true
    }
    else {
        # No longer a skip: the database gate is blocking in CI, and a local run
        # that silently skips it stops being the same baseline.
        Write-Fail 'PostgreSQL is not reachable; the migration round trip cannot run.'
        Add-Result 'alembic down/up' 1 $true
    }

    Write-Section 'Frontend - prettier (advisory)'
    Add-Result 'prettier --check' (Invoke-Native -File $npmExe -Arguments @('run', 'format:check') -WorkingDirectory $webDir -AllowFailure) $false

    Write-Section 'Summary'
    foreach ($result in $results) {
        $label =
        if ($result.ExitCode -eq -1) { 'SKIP' }
        elseif ($result.ExitCode -eq 0) { 'PASS' }
        elseif ($result.Blocking) { 'FAIL' }
        else { 'WARN' }
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
