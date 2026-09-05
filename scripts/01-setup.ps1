[CmdletBinding()]
param(
    # Set automatically when the script re-launches itself in an interactive console.
    [switch] $Relaunched,
    # Force a dependency install even when the packages are already present.
    [switch] $ReinstallPackages
)

# ---------------------------------------------------------------
#  01-setup.ps1  -  prepare the local development environment
#
#  Idempotent and safe to re-run. Steps already completed are skipped.
#
#    1. tool check (psql is located without touching PATH)
#    2. detect the independent PostgreSQL port (never 5432 - that is Odoo)
#    3. .env file and the generated application database password
#    4. Python virtual environment and API packages   (uv, from uv.lock)
#    5. frontend packages                             (skipped if present)
#    6. verify the server identity through data_directory BEFORE any change
#    7. create the sahl_app role and the sahl_dev database
#    8. verify that the application role can connect
#    9. apply the Alembic baseline migration
#
#  The PostgreSQL superuser password is typed masked, held in memory only for
#  the psql child process, and is never logged, printed or written to any file.
#  It never goes into .env.
#
#  It never installs machine wide software, never changes Windows settings,
#  never touches Odoo, and never deletes anything outside this project.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

# Launching a .ps1 by clicking it does not always give the script a console
# that can read typed input. Re-launch once into a real console window that
# stays open, so the prompts below always work and the output stays visible.
if (-not $Relaunched) {
    $powershell = Join-Path $PSHOME 'powershell.exe'
    $arguments = @(
        '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"'), '-Relaunched'
    )
    if ($ReinstallPackages) { $arguments += '-ReinstallPackages' }
    Start-Process -FilePath $powershell -ArgumentList $arguments | Out-Null
    Write-Host 'Continuing in a new PowerShell window...'
    Start-Sleep -Seconds 2
    return
}

Write-Host ''
Write-Host '  Sahl Developer Platform - local setup'
Write-Host '  ------------------------------------'
Write-Host '  The PostgreSQL superuser password is needed once, to create an isolated'
Write-Host '  role and database for Sahl. It is typed masked, kept in memory only for'
Write-Host '  the psql process, and is never logged or written to any file.'
Write-Host ''

$superUserInput = Read-Host '  PostgreSQL superuser name [postgres]'
$superUser = if ([string]::IsNullOrWhiteSpace($superUserInput)) { 'postgres' } else { $superUserInput.Trim() }

$securePassword = Read-Host ('  Password for "' + $superUser + '"') -AsSecureString
if ($null -eq $securePassword -or $securePassword.Length -eq 0) {
    Write-Host ''
    Write-Host '  [X] No password was entered. Nothing was changed.'
    Write-Host '      Run the script again and type the password you set during the'
    Write-Host '      PostgreSQL 17 installation.'
    Write-Host ''
    return
}
Write-Host ''

$log = Start-SahlLog -Name '01-setup'
$root = Get-ProjectRoot
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$databaseReady = $false

function Get-PythonBaseline {
    # One source for the version: the same file uv reads and CI reads.
    $file = Join-Path (Get-ProjectRoot) 'apps\api\.python-version'
    if (-not (Test-Path $file)) { throw 'apps\api\.python-version is missing; the Python baseline is unknown.' }
    return (Get-Content $file -Raw).Trim()
}

function Resolve-PythonLauncher {
    param([string] $Baseline)

    if (Test-CommandExists 'py') {
        $version = Get-ToolVersion -File 'py' -Arguments @(('-' + $Baseline), '--version')
        if ($version) {
            Write-Ok ('Using ' + $version + ' via: py -' + $Baseline)
            return @{ File = 'py'; Args = @('-' + $Baseline) }
        }
    }

    $version = Get-ToolVersion -File 'python'
    if ($version -and $version -match ('Python\s+' + [regex]::Escape($Baseline) + '\.')) {
        Write-Ok ('Using ' + $version + ' via: python')
        return @{ File = 'python'; Args = @() }
    }

    throw ("Python $Baseline was not found. Install it from python.org, then run scripts\00-check.ps1 again. " +
        'Nothing is installed automatically.')
}

function New-DatabasePassword {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $raw = [Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', ''
    return $raw.Substring(0, 24)
}

function Set-EnvLine {
    param([string] $Key, [string] $Value)

    $envFile = Join-Path (Get-ProjectRoot) '.env'
    $lines = @(Get-Content $envFile)
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $found = $false
    $result = @(foreach ($line in $lines) {
            if ($line -match $pattern) { $found = $true; ($Key + '=' + $Value) } else { $line }
        })
    if (-not $found) { $result += ($Key + '=' + $Value) }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envFile, $result, $utf8NoBom)
}

try {
    Write-Section '1. Tool check'
    foreach ($tool in @('git', 'node')) {
        if (-not (Test-CommandExists $tool)) { throw ($tool + ' was not found in PATH.') }
        Write-Ok ($tool + ' found')
    }
    $npmExe = if (Test-CommandExists 'npm.cmd') { 'npm.cmd' } elseif (Test-CommandExists 'npm') { 'npm' } else { throw 'npm was not found in PATH.' }
    $pythonBaseline = Get-PythonBaseline
    $python = Resolve-PythonLauncher -Baseline $pythonBaseline
    if (-not (Test-CommandExists 'uv')) {
        throw ('uv was not found in PATH. Install it from https://docs.astral.sh/uv/ , then run this script again. ' +
            'Nothing is installed automatically.')
    }
    Write-Ok ('uv found: ' + (Get-ToolVersion -File 'uv'))

    $psqlExe = Resolve-PsqlPath
    if ($psqlExe) { Write-Ok ('psql: ' + $psqlExe) } else { Write-Warn 'psql.exe was not found; the database steps will be skipped.' }

    Write-Section '2. PostgreSQL port'
    # Port 5432 belongs to the Odoo installation and is never used (ADR-0006).
    $detectedPort = $null
    foreach ($port in @(5433, 5434, 5435)) {
        if (Test-TcpPort -Port $port) { $detectedPort = $port; break }
    }
    if ($detectedPort) {
        Write-Ok ('An independent PostgreSQL server is listening on 127.0.0.1:' + $detectedPort)
    }
    else {
        Write-Warn 'No independent PostgreSQL server answered on 5433, 5434 or 5435.'
        if (Test-TcpPort -Port 5432) {
            Write-Warn 'Port 5432 is in use by the Odoo installation and is deliberately ignored.'
        }
    }

    Write-Section '3. Environment file'
    $envFile = Join-Path $root '.env'
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $root '.env.example') $envFile
        Write-Ok '.env created from .env.example'
    }
    else {
        Write-Info '.env already exists and is kept as is'
    }

    $databaseUrl = Get-EnvValue 'DATABASE_URL'
    if (-not $databaseUrl -or $databaseUrl -match 'CHANGE_ME') {
        $generated = New-DatabasePassword
        $port = if ($detectedPort) { $detectedPort } else { 5433 }
        $databaseUrl = 'postgresql+psycopg://sahl_app:' + $generated + '@127.0.0.1:' + $port + '/sahl_dev'
        Set-EnvLine -Key 'DATABASE_URL' -Value $databaseUrl
        Write-Ok 'Generated the application database password and stored it in .env (never logged, never committed)'
    }

    if ($databaseUrl -notmatch '^postgresql\+psycopg://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)$') {
        throw 'DATABASE_URL in .env is not in the expected format.'
    }
    $dbUser = $Matches[1]
    $dbPassword = $Matches[2]
    $dbHost = $Matches[3]
    $dbPort = $Matches[4]
    $dbName = $Matches[5]

    if ([int]$dbPort -eq 5432) {
        throw 'DATABASE_URL points at port 5432, which belongs to the Odoo PostgreSQL instance. Sahl must use its own server (ADR-0006).'
    }
    if ($detectedPort -and [int]$dbPort -ne [int]$detectedPort) {
        $databaseUrl = 'postgresql+psycopg://' + $dbUser + ':' + $dbPassword + '@' + $dbHost + ':' + $detectedPort + '/' + $dbName
        Set-EnvLine -Key 'DATABASE_URL' -Value $databaseUrl
        $dbPort = "$detectedPort"
        Write-Ok ('DATABASE_URL port updated to the detected port ' + $detectedPort)
    }
    Write-Info ('Database target: ' + $dbUser + '@' + $dbHost + ':' + $dbPort + '/' + $dbName)

    Write-Section '4. Python virtual environment and API packages'
    $venvDir = Join-Path $apiDir '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'

    # An environment built on another Python is rebuilt rather than patched.
    # Only apps\api\.venv is ever removed, and the path is asserted twice - here
    # and again inside Remove-ProjectDirectory - so a future edit cannot widen
    # what this deletes.
    $expectedVenvDir = Join-Path $apiDir '.venv'
    $rebuildReason = $null

    # Two independent sources decide this: the interpreter that actually runs,
    # and pyvenv.cfg. They are only allowed to send us down the destructive path
    # when they agree; a disagreement stops the script instead of deleting on a
    # reading nobody can explain.
    $venvState = Get-VirtualEnvironmentState -VenvPath $venvDir -Baseline $pythonBaseline
    switch ($venvState.Status) {
        'matches' { Write-Ok ('old venv already matches the baseline: ' + $venvState.Reason) }
        'mismatch' { $rebuildReason = 'old venv = Python ' + $venvState.ExecutableVersion + ' but the baseline is ' + $pythonBaseline }
        'incomplete' {
            if (Test-Path $venvDir) {
                # Wreckage of an interrupted rebuild. Installing into it would
                # hide the damage, so it is replaced.
                $rebuildReason = 'old venv is unusable (' + $venvState.Reason + ') and is replaced'
            }
        }
        'inconsistent' {
            throw ('The existing virtual environment cannot be classified: ' + $venvState.Reason +
                ' Nothing was deleted. Inspect apps\api\.venv yourself, then run this script again.')
        }
    }

    if ($rebuildReason) {
        if ($venvDir -ne $expectedVenvDir) {
            throw 'Refusing to remove a directory that is not apps\api\.venv'
        }
        Write-Info $rebuildReason

        # Deleting a virtual environment while something runs from it fails on
        # Windows: a loaded .pyd stays locked, and a uvicorn reloader answers the
        # half-deleted directory by respawning its worker. So the processes are
        # stopped first - the ones an earlier 02-run recorded, then any orphan
        # still running from this exact environment - and only then is it removed.
        Stop-SahlServices
        if (-not (Stop-ProcessesUsingPath -Path $venvDir)) {
            throw ('The old virtual environment is still in use. Close the processes listed above, ' +
                'then run this script again. Nothing was deleted.')
        }
        Write-Ok 'project-owned processes stopped safely'

        if (-not (Remove-ProjectDirectory -Path $venvDir -ExpectedPath $expectedVenvDir)) {
            throw ('The old virtual environment could not be removed. The file named above is still locked. ' +
                'Close whatever holds it, then run this script again. Nothing outside apps\api\.venv was touched.')
        }
        Write-Ok 'old venv removed - nothing outside apps\api\.venv was touched'
    }

    $lockFile = Join-Path $apiDir 'uv.lock'
    if (Test-Path $lockFile) {
        Invoke-Native -File 'uv' -Arguments @('sync', '--frozen') -WorkingDirectory $apiDir | Out-Null
        Write-Ok 'API packages installed from uv.lock (frozen)'
    }
    else {
        # The only path that resolves versions. Every later run is frozen.
        Write-Info 'uv.lock is missing - generating it once from pyproject.toml'
        Invoke-Native -File 'uv' -Arguments @('lock') -WorkingDirectory $apiDir | Out-Null
        Write-Ok 'uv.lock generated'
        Invoke-Native -File 'uv' -Arguments @('sync', '--frozen') -WorkingDirectory $apiDir | Out-Null
        Write-Ok 'uv sync --frozen succeeded'
    }

    # uv builds the environment, so what it produced is read back from disk
    # rather than assumed from the baseline file - and from both sources, since
    # an interpreter and the file that describes it can drift apart.
    $builtState = Get-VirtualEnvironmentState -VenvPath $venvDir -Baseline $pythonBaseline
    if ($builtState.Status -ne 'matches') {
        if ($builtState.ExecutableError) { Write-Fail ('interpreter: ' + $builtState.ExecutableError) }
        if ($builtState.ConfigError) { Write-Fail ('pyvenv.cfg: ' + $builtState.ConfigError) }
        throw ('The virtual environment does not match the baseline ' + $pythonBaseline + ': ' + $builtState.Reason)
    }
    Write-Info ('interpreter reports Python ' + $builtState.ExecutableVersion)
    Write-Info ('pyvenv.cfg records ' + $builtState.ConfigKey + ' = ' + $builtState.ConfigVersion)
    if ($rebuildReason) {
        Write-Ok ('new venv created with Python ' + $builtState.ExecutableVersion)
    }
    else {
        Write-Ok ('virtual environment runs Python ' + $builtState.ExecutableVersion + ' - matches the baseline')
    }

    Write-Section '5. Frontend packages'
    $nodeModulesMarker = Join-Path $webDir 'node_modules\.package-lock.json'
    if ((Test-Path $nodeModulesMarker) -and -not $ReinstallPackages) {
        Write-Info 'Frontend packages already installed - skipped'
    }
    else {
        Invoke-Native -File $npmExe -Arguments @('install', '--no-fund', '--no-audit') -WorkingDirectory $webDir | Out-Null
        Write-Ok 'Frontend packages installed'
    }

    Write-Section '6. PostgreSQL server identity'
    if (-not $psqlExe) { throw 'psql.exe was not found, so the database cannot be prepared.' }
    if (-not $detectedPort) { throw 'No independent PostgreSQL server is listening. Start the postgresql-x64-17 service and run this script again.' }

    Write-Info ('Connecting as: ' + $superUser)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    $sqlPath = Join-Path $env:TEMP ('sahl-provision-' + [guid]::NewGuid().ToString('N') + '.sql')
    try {
        $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        if ([string]::IsNullOrEmpty($env:PGPASSWORD)) {
            throw 'The password came through empty. Nothing was changed.'
        }

        $probe = Invoke-NativeCapture -File $psqlExe -Arguments @(
            '-h', $dbHost, '-p', $dbPort, '-U', $superUser, '-d', 'postgres', '-tAc', 'SELECT version()'
        )
        if ($probe.ExitCode -ne 0) {
            Write-Fail ('Could not connect to ' + $dbHost + ':' + $dbPort + ' as "' + $superUser + '". psql reported:')
            foreach ($line in $probe.Output) { Write-Host ('    ' + $line) }
            Write-Warn 'Use the password you set during the PostgreSQL 17 installation.'
            throw 'Superuser connection failed. Nothing was changed.'
        }
        Write-Ok ('Server: ' + $probe.Text)

        $dataDir = Invoke-NativeCapture -File $psqlExe -Arguments @(
            '-h', $dbHost, '-p', $dbPort, '-U', $superUser, '-d', 'postgres', '-tAc', 'SHOW data_directory'
        )
        if ($dataDir.ExitCode -ne 0) {
            throw 'Unable to read the server data directory, so its independence cannot be confirmed. Nothing was changed.'
        }
        Write-Ok ('data_directory: ' + $dataDir.Text)
        if ($dataDir.Text -match 'Odoo') {
            throw 'This server belongs to the Odoo installation. Nothing was changed. Sahl requires its own PostgreSQL instance (ADR-0006).'
        }
        Write-Ok 'Confirmed: this is an independent PostgreSQL instance, not the Odoo one.'

        Write-Section '7. Role and database'
        $sql = @"
DO `$`$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$dbUser') THEN
      EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', '$dbUser', '$dbPassword');
   ELSE
      EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', '$dbUser', '$dbPassword');
   END IF;
END
`$`$;

SELECT 'CREATE DATABASE $dbName OWNER $dbUser'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$dbName')
\gexec
"@
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($sqlPath, ($sql -replace "`r`n", "`n"), $utf8NoBom)

        Invoke-Native -File $psqlExe -Arguments @(
            '-v', 'ON_ERROR_STOP=1', '-q',
            '-h', $dbHost, '-p', $dbPort, '-U', $superUser, '-d', 'postgres', '-f', $sqlPath
        ) | Out-Null
        Write-Ok ('Role "' + $dbUser + '" and database "' + $dbName + '" are ready')

        Write-Info 'Application role privileges (both must be f):'
        Invoke-Native -File $psqlExe -Arguments @(
            '-h', $dbHost, '-p', $dbPort, '-U', $superUser, '-d', 'postgres', '-c',
            ("SELECT rolname, rolsuper AS is_superuser, rolbypassrls AS bypasses_rls FROM pg_roles WHERE rolname = '" + $dbUser + "';")
        ) -AllowFailure | Out-Null

        Write-Section '8. Application connection'
        $env:PGPASSWORD = $dbPassword
        $appProbe = Invoke-NativeCapture -File $psqlExe -Arguments @(
            '-h', $dbHost, '-p', $dbPort, '-U', $dbUser, '-d', $dbName, '-tAc', 'SELECT current_user'
        )
        if ($appProbe.ExitCode -eq 0) {
            Write-Ok ('The application role connected as: ' + $appProbe.Text)
            $databaseReady = $true
        }
        else {
            Write-Fail 'The application role could not connect. psql reported:'
            foreach ($line in $appProbe.Output) { Write-Host ('    ' + $line) }
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        if (Test-Path $sqlPath) { Remove-Item $sqlPath -Force -ErrorAction SilentlyContinue }
    }

    Write-Section '9. Database migrations'
    if ($databaseReady) {
        Invoke-Native -File $venvPython -Arguments @('-m', 'alembic', 'upgrade', 'head') -WorkingDirectory $apiDir | Out-Null
        Invoke-Native -File $venvPython -Arguments @('-m', 'alembic', 'current') -WorkingDirectory $apiDir -AllowFailure | Out-Null
        Write-Ok 'Baseline migration applied'
    }
    else {
        Write-Warn 'Skipped: the database is not ready.'
    }

    Write-Section 'Result'
    if ($databaseReady) {
        Write-Host '  Setup finished successfully. Next step: scripts\03-test.ps1'
    }
    else {
        Write-Host '  Setup finished with warnings. Review the sections above.'
    }
}
catch {
    Write-Fail $_.Exception.Message
    Write-Host '  Setup did not finish. The full log is in the _logs folder.'
}
finally {
    Stop-SahlLog
    Write-Host ''
    Write-Host '  This window stays open so you can read the result.'
}
