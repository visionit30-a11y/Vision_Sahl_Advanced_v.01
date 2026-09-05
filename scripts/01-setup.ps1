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
#    4. Python virtual environment and API packages   (skipped if present)
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

function Resolve-PythonLauncher {
    $candidates = @()
    if (Test-CommandExists 'py') {
        $candidates += , @{ File = 'py'; Args = @('-3.13') }
        $candidates += , @{ File = 'py'; Args = @('-3.12') }
        $candidates += , @{ File = 'py'; Args = @('-3') }
    }
    if (Test-CommandExists 'python') {
        $candidates += , @{ File = 'python'; Args = @() }
    }

    foreach ($candidate in $candidates) {
        $label = ($candidate.File + ' ' + ($candidate.Args -join ' ')).Trim()
        $version = Get-ToolVersion -File $candidate.File -Arguments ($candidate.Args + @('--version'))
        if (-not $version) { continue }
        if ($version -match 'Python\s+(\d+)\.(\d+)') {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 12) {
                Write-Ok ('Using ' + $version + ' via: ' + $label)
                return $candidate
            }
        }
    }
    throw 'Python 3.12 or newer was not found. Install it, then run scripts\00-check.ps1 again.'
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
    $python = Resolve-PythonLauncher

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
    if (-not (Test-Path $venvPython)) {
        Invoke-Native -File $python.File -Arguments ($python.Args + @('-m', 'venv', $venvDir)) | Out-Null
        Write-Ok 'Virtual environment created'
    }
    else {
        Write-Info 'Virtual environment already present'
    }

    $apiPackagesPresent = $false
    if (Test-Path $venvPython) {
        $importProbe = Invoke-NativeCapture -File $venvPython -Arguments @(
            '-c', 'import fastapi, sqlalchemy, alembic, psycopg, redis, structlog, pytest, httpx'
        )
        $apiPackagesPresent = ($importProbe.ExitCode -eq 0)
    }

    if ($apiPackagesPresent -and -not $ReinstallPackages) {
        Write-Info 'API packages already installed - skipped'
    }
    else {
        Invoke-Native -File $venvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip') | Out-Null
        Invoke-Native -File $venvPython -Arguments @('-m', 'pip', 'install', '-e', '.[dev]') -WorkingDirectory $apiDir | Out-Null
        Write-Ok 'API packages installed'
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
