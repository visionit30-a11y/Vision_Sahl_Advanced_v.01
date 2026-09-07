# ---------------------------------------------------------------
#  03-test.ps1 - run the blocking quality gates for the current phase
#  Every failed command, prerequisite or revision check fails the run.
# ---------------------------------------------------------------

$ErrorActionPreference = 'Stop'
$results = New-Object System.Collections.ArrayList
$exitCode = 1
$logStarted = $false
$root = $null

function Add-Result {
    param([string] $Name, [int] $Code)
    [void]$results.Add([pscustomobject]@{ Gate = $Name; ExitCode = $Code })
}

function Write-GitState {
    param([string] $Stage)

    Write-Section ('Repository state - ' + $Stage)
    foreach ($command in @(
            @{ Label = 'Git HEAD'; Arguments = @('-C', $root, 'rev-parse', '--verify', 'HEAD') },
            @{ Label = 'Git worktree'; Arguments = @('-C', $root, 'status', '--short', '--untracked-files=normal') })) {
        $state = Invoke-NativeCapture -File 'git' -Arguments $command.Arguments
        if ($state.ExitCode -ne 0) {
            throw ('Cannot record ' + $command.Label + ': ' + $state.Text)
        }
        $value = $state.Text.Trim()
        if (-not $value) { $value = '(clean)' }
        Write-Info ($command.Label + ': ' + $value)
    }
}

function Invoke-AlembicGateCommand {
    param([string[]] $Arguments)

    Write-Info ('alembic ' + ($Arguments -join ' '))
    Push-Location $apiDir
    try {
        $result = Invoke-NativeCapture -File $venvPython -Arguments (@('-m', 'alembic') + $Arguments)
    }
    finally {
        Pop-Location
    }
    foreach ($line in $result.Output) { Write-Host ('    ' + $line) }
    Write-Info ('Command exit code: ' + $result.ExitCode)
    return $result
}

function Assert-AlembicRevision {
    param([string] $ExpectedHead, [switch] $AtBase)

    $current = Invoke-AlembicGateCommand -Arguments @('current')
    if ($current.ExitCode -ne 0) { throw 'alembic current failed.' }
    $actual = @(
        foreach ($line in $current.Output) {
            if ($line.Trim() -match '^([A-Za-z0-9_.-]+)(?: \(head\))?$') { $Matches[1] }
        }
    )
    $actualLabel = if ($actual.Count) { $actual -join ', ' } else { '(base / no revision)' }
    $expectedLabel = if ($AtBase) { '(base / no revision)' } else { $ExpectedHead }
    Write-Info ('Expected Alembic revision: ' + $expectedLabel)
    Write-Info ('Actual Alembic revision: ' + $actualLabel)
    # A successful command or a "(head)" annotation alone is not evidence.
    # A downgrade must remove every revision; an upgrade must record exactly
    # the head from the scripts. This also catches a successful no-op downgrade.
    if ($AtBase) {
        if ($actual.Count -ne 0) { throw 'Database did not reach base after downgrade.' }
    }
    elseif ($actual.Count -ne 1 -or $actual[0] -cne $ExpectedHead) {
        throw ('Database revision does not equal the expected head ' + $ExpectedHead + '.')
    }
}

function Invoke-MigrationRoundTrip {
    try {
        $heads = Invoke-AlembicGateCommand -Arguments @('heads')
        if ($heads.ExitCode -ne 0) { throw 'alembic heads failed.' }
        $expected = @(
            foreach ($line in $heads.Output) {
                if ($line.Trim() -match '^([A-Za-z0-9_.-]+) \(head\)$') { $Matches[1] }
            }
        )
        if ($expected.Count -ne 1) {
            throw 'The migration scripts must expose exactly one unambiguous head.'
        }
        Write-Info ('Expected Alembic head from migration scripts: ' + $expected[0])

        $firstUpgrade = Invoke-AlembicGateCommand -Arguments @('upgrade', 'head')
        if ($firstUpgrade.ExitCode -ne 0) { throw 'The initial alembic upgrade failed.' }
        Assert-AlembicRevision -ExpectedHead $expected[0]

        $downgrade = Invoke-AlembicGateCommand -Arguments @('downgrade', 'base')
        if ($downgrade.ExitCode -ne 0) { throw 'alembic downgrade failed.' }
        Assert-AlembicRevision -AtBase

        $finalUpgrade = Invoke-AlembicGateCommand -Arguments @('upgrade', 'head')
        if ($finalUpgrade.ExitCode -ne 0) { throw 'The final alembic upgrade failed.' }
        Assert-AlembicRevision -ExpectedHead $expected[0]
        return 0
    }
    catch {
        Write-Fail $_.Exception.Message
        return 1
    }
}

try {
    . (Join-Path $PSScriptRoot '_common.ps1')
    $log = Start-SahlLog -Name '03-test'
    $logStarted = $true
    $root = Get-ProjectRoot
    $apiDir = Join-Path $root 'apps\api'
    $webDir = Join-Path $root 'apps\web'
    Write-GitState -Stage 'before gates'

    $venvPython = Get-VenvPython
    $npmExe = if (Test-CommandExists 'npm.cmd') { 'npm.cmd' } else { 'npm' }

    Write-Section 'Backend - dependency lock'
    if (-not (Test-CommandExists 'uv')) {
        throw 'uv was not found in PATH. Install it from https://docs.astral.sh/uv/ and run scripts\01-setup.ps1.'
    }
    Add-Result 'uv lock --check' (Invoke-Native -File 'uv' -Arguments @('lock', '--check') -WorkingDirectory $apiDir -AllowFailure)
    $syncExit = Invoke-Native -File 'uv' -Arguments @('sync', '--frozen') -WorkingDirectory $apiDir -AllowFailure
    Add-Result 'uv sync --frozen' $syncExit
    if ($syncExit -ne 0) { throw 'Frozen dependency installation failed; the test environment is not verified.' }

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

    Write-Section 'Auto-format (ruff format / prettier --write)'
    Add-Result 'ruff format' (Invoke-Native -File $venvPython -Arguments @('-m', 'ruff', 'format', '.') -WorkingDirectory $apiDir -AllowFailure)
    Add-Result 'prettier --write' (Invoke-Native -File $npmExe -Arguments @('run', 'format') -WorkingDirectory $webDir -AllowFailure)
    Write-GitState -Stage 'after formatting (sources being tested)'

    Write-Section 'Backend - ruff (lint)'
    Add-Result 'ruff check' (Invoke-Native -File $venvPython -Arguments @('-m', 'ruff', 'check', '.') -WorkingDirectory $apiDir -AllowFailure)

    Write-Section 'Backend - ruff (format check)'
    Add-Result 'ruff format --check' (Invoke-Native -File $venvPython -Arguments @('-m', 'ruff', 'format', '--check', '.') -WorkingDirectory $apiDir -AllowFailure)

    Write-Section 'Backend - mypy (types)'
    Add-Result 'mypy' (Invoke-Native -File $venvPython -Arguments @('-m', 'mypy') -WorkingDirectory $apiDir -AllowFailure)

    # Tests must never run against the older schema left by a failed migration.
    # Keep the other gates in their existing order.
    Write-Section 'Database - migration round trip'
    $databasePort = $null
    $databaseUrl = Get-EnvValue 'DATABASE_URL'
    if ($databaseUrl -match '@[^:/]+:(\d+)/') { $databasePort = [int]$Matches[1] }
    $migrationExit = 1
    if ($databasePort -and (Test-TcpPort -Port $databasePort)) {
        $migrationExit = Invoke-MigrationRoundTrip
    }
    else {
        Write-Fail 'PostgreSQL is not reachable; the migration prerequisite failed.'
    }
    Add-Result 'alembic upgrade/down/up + head' $migrationExit

    Write-Section 'Backend - pytest'
    if ($migrationExit -eq 0) {
        Add-Result 'pytest' (Invoke-Native -File $venvPython -Arguments @('-m', 'pytest', '--strict-security-gates', '--tb=short') -WorkingDirectory $apiDir -AllowFailure)
    }
    else {
        Write-Fail 'pytest prerequisite failed: the migration round trip did not verify the current schema. No tests were run against an older schema.'
        Add-Result 'pytest (migration prerequisite)' 1
    }

    # Runs after pytest even when a test failed: a failed teardown is blocking.
    Write-Section 'Database - post-test artifact and RLS guard'
    Add-Result 'post-test database guard' (Invoke-Native -File $venvPython -Arguments @('-m', 'tests.db.verify_clean_database') -WorkingDirectory $apiDir -AllowFailure)

    Write-Section 'Frontend - eslint'
    Add-Result 'eslint' (Invoke-Native -File $npmExe -Arguments @('run', 'lint') -WorkingDirectory $webDir -AllowFailure)

    Write-Section 'Frontend - typescript'
    Add-Result 'tsc --noEmit' (Invoke-Native -File $npmExe -Arguments @('run', 'typecheck') -WorkingDirectory $webDir -AllowFailure)

    Write-Section 'Frontend - vitest'
    Add-Result 'vitest' (Invoke-Native -File $npmExe -Arguments @('run', 'test') -WorkingDirectory $webDir -AllowFailure)

    Write-Section 'Frontend - browser security gate'
    Add-Result 'playwright chromium' (Invoke-Native -File $npmExe -Arguments @('run', 'test:browser') -WorkingDirectory $webDir -AllowFailure)

    Write-Section 'Frontend - production build'
    Add-Result 'vite build' (Invoke-Native -File $npmExe -Arguments @('run', 'build') -WorkingDirectory $webDir -AllowFailure)

    Write-Section 'Database - role separation'
    $psqlExe = Resolve-PsqlPath
    if (-not $psqlExe) {
        Write-Fail 'psql.exe was not found; the role gates cannot run.'
        Add-Result 'app role cannot bypass RLS' 1
        Add-Result 'app role owns nothing' 1
    }
    elseif (-not ($databasePort -and (Test-TcpPort -Port $databasePort))) {
        Write-Fail 'PostgreSQL is not reachable; the role gates cannot run.'
        Add-Result 'app role cannot bypass RLS' 1
        Add-Result 'app role owns nothing' 1
    }
    else {
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
            Add-Result 'app role cannot bypass RLS' 1
            Add-Result 'app role owns nothing' 1
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
                Add-Result 'app role cannot bypass RLS' $bypassExit

                $owned = Invoke-NativeCapture -File $psqlExe -Arguments @(
                    '-tAX', '-h', $appHost, '-p', "$databasePort", '-U', $appUser, '-d', $appDatabase, '-c',
                    ("SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner WHERE r.rolname = '" + $appUser + "' AND c.relkind IN ('r','p','v','m','S');")
                )
                Write-Info ('objects owned by ' + $appUser + ': ' + $owned.Text.Trim())
                $ownedExit = 1
                if ($owned.ExitCode -eq 0 -and $owned.Text.Trim() -eq '0') { $ownedExit = 0 }
                Add-Result 'app role owns nothing' $ownedExit
            }
            finally {
                Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
            }
        }
    }

    Write-Section 'Frontend - prettier (format check)'
    Add-Result 'prettier --check' (Invoke-Native -File $npmExe -Arguments @('run', 'format:check') -WorkingDirectory $webDir -AllowFailure)
}
catch {
    Add-Result 'script exception' 1
    Write-Host ('  [X] ' + $_.Exception.Message)
}
finally {
    # Even failures outside an individual command must produce a failed process.
    try {
        if ($logStarted -and $root) { Write-GitState -Stage 'after gates' }
    }
    catch {
        Add-Result 'final Git state' 1
        Write-Host ('  [X] ' + $_.Exception.Message)
    }

    Write-Host ''
    Write-Host '=========== Summary ==========='
    foreach ($result in $results) {
        $label = if ($result.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }
        Write-Host ("  {0,-6} {1,-38} exit={2}" -f $label, $result.Gate, $result.ExitCode)
    }
    $failures = @($results | Where-Object { $_.ExitCode -ne 0 })
    if ($results.Count -gt 0 -and $failures.Count -eq 0) {
        $exitCode = 0
        Write-Host 'All blocking quality gates passed.'
    }
    else {
        Write-Host ('Blocking failures: ' + ($failures.Gate -join ', '))
    }
    Write-Host ('Final exit code: ' + $exitCode)
    if ($logStarted) { Stop-SahlLog }
}

exit $exitCode
