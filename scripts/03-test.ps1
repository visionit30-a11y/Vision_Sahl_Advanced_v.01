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

    Write-Section 'Database - role separation'
    # The same two gates CI runs, so the local baseline and the pipeline cannot
    # drift apart. Both are blocking: an application role that can bypass
    # isolation, or that owns a table, makes every later isolation test pass for
    # the wrong reason.
    $psqlExe = Resolve-PsqlPath
    if (-not $psqlExe) {
        Write-Fail 'psql.exe was not found; the role gates cannot run.'
        Add-Result 'app role cannot bypass RLS' 1 $true
        Add-Result 'app role owns nothing' 1 $true
    }
    elseif (-not ($databasePort -and (Test-TcpPort -Port $databasePort))) {
        Write-Fail 'PostgreSQL is not reachable; the role gates cannot run.'
        Add-Result 'app role cannot bypass RLS' 1 $true
        Add-Result 'app role owns nothing' 1 $true
    }
    else {
        # Connecting as the application role itself: no superuser password is
        # needed, and pg_roles and pg_class are readable by any role.
        $appUser = $null
        $appPassword = $null
        $appDatabase = $null
        if ($databaseUrl -match '^postgresql\+psycopg://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)$') {
            $appUser = $Matches[1]
            $appPassword = $Matches[2]
            $appHost = $Matches[3]
            $appDatabase = $Matches[5]
        }

        if (-not $appUser) {
            Write-Fail 'DATABASE_URL could not be parsed; the role gates cannot run.'
            Add-Result 'app role cannot bypass RLS' 1 $true
            Add-Result 'app role owns nothing' 1 $true
        }
        else {
            $env:PGPASSWORD = $appPassword
            try {
                $flags = Invoke-NativeCapture -File $psqlExe -Arguments @(
                    '-tAX', '-h', $appHost, '-p', "$databasePort", '-U', $appUser, '-d', $appDatabase, '-c',
                    ("SELECT rolsuper::text || ' ' || rolbypassrls::text FROM pg_roles WHERE rolname = '" + $appUser + "';")
                )
                Write-Info ($appUser + ' rolsuper rolbypassrls: ' + $flags.Text.Trim())
                $bypassExit = 1
                if ($flags.ExitCode -eq 0 -and $flags.Text.Trim() -eq 'false false') { $bypassExit = 0 }
                Add-Result 'app role cannot bypass RLS' $bypassExit $true

                $owned = Invoke-NativeCapture -File $psqlExe -Arguments @(
                    '-tAX', '-h', $appHost, '-p', "$databasePort", '-U', $appUser, '-d', $appDatabase, '-c',
                    ("SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner WHERE r.rolname = '" + $appUser + "' AND c.relkind IN ('r','p','v','m','S');")
                )
                Write-Info ('objects owned by ' + $appUser + ': ' + $owned.Text.Trim())
                $ownedExit = 1
                if ($owned.ExitCode -eq 0 -and $owned.Text.Trim() -eq '0') { $ownedExit = 0 }
                Add-Result 'app role owns nothing' $ownedExit $true
            }
            finally {
                Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
            }
        }
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
