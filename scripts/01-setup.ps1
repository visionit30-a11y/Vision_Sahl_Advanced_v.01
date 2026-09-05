# ---------------------------------------------------------------
#  01-setup.ps1  -  prepare the local development environment
#
#  What it does (idempotent, safe to re-run):
#    1. verifies the required tools
#    2. creates .env from .env.example and generates a database password
#    3. creates the Python virtual environment and installs the API packages
#    4. installs the frontend packages
#    5. creates the PostgreSQL role and database (asks once for the
#       PostgreSQL superuser password - it is never written to the log)
#    6. applies the Alembic baseline migration
#
#  What it never does: install machine wide software, change Windows
#  settings, or delete anything outside this project.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

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
        try {
            $probe = $candidate.Args + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
            $version = & $candidate.File @probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $version) {
                $parts = ($version.Trim()).Split('.')
                if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 12) {
                    Write-Ok ('Using Python ' + $version.Trim() + ' via: ' + $candidate.File + ' ' + ($candidate.Args -join ' '))
                    return $candidate
                }
            }
        }
        catch { }
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
    $result = foreach ($line in $lines) {
        if ($line -match $pattern) { $found = $true; ($Key + '=' + $Value) } else { $line }
    }
    if (-not $found) { $result = $result + ($Key + '=' + $Value) }
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

    Write-Section '2. Environment file'
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
        $databaseUrl = 'postgresql+psycopg://sahl_app:' + $generated + '@127.0.0.1:5432/sahl_dev'
        Set-EnvLine -Key 'DATABASE_URL' -Value $databaseUrl
        Write-Ok 'Generated a local database password and stored it in .env (never logged, never committed)'
    }

    if ($databaseUrl -notmatch '^postgresql\+psycopg://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)$') {
        throw 'DATABASE_URL in .env is not in the expected format.'
    }
    $dbUser = $Matches[1]
    $dbPassword = $Matches[2]
    $dbHost = $Matches[3]
    $dbPort = $Matches[4]
    $dbName = $Matches[5]
    Write-Info ('Database target: ' + $dbUser + '@' + $dbHost + ':' + $dbPort + '/' + $dbName)

    Write-Section '3. Python virtual environment'
    $venvDir = Join-Path $apiDir '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        Invoke-Native -File $python.File -Arguments ($python.Args + @('-m', 'venv', $venvDir)) | Out-Null
        Write-Ok 'Virtual environment created'
    }
    else {
        Write-Info 'Virtual environment already present'
    }
    Invoke-Native -File $venvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip') | Out-Null
    Invoke-Native -File $venvPython -Arguments @('-m', 'pip', 'install', '-e', '.[dev]') -WorkingDirectory $apiDir | Out-Null
    Write-Ok 'API packages installed'

    Write-Section '4. Frontend packages'
    Invoke-Native -File $npmExe -Arguments @('install', '--no-fund', '--no-audit') -WorkingDirectory $webDir | Out-Null
    Write-Ok 'Frontend packages installed'

    Write-Section '5. PostgreSQL role and database'
    if (-not (Test-CommandExists 'psql')) {
        Write-Warn 'psql was not found in PATH, so the database could not be provisioned automatically.'
        Write-Warn 'Add the PostgreSQL bin folder to PATH and run this script again.'
    }
    else {
        $superUser = Read-Host 'PostgreSQL superuser name (press Enter for "postgres")'
        if ([string]::IsNullOrWhiteSpace($superUser)) { $superUser = 'postgres' }
        $securePassword = Read-Host ('Password for PostgreSQL user "' + $superUser + '"') -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        $sqlPath = Join-Path $env:TEMP ('sahl-provision-' + [guid]::NewGuid().ToString('N') + '.sql')
        try {
            $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)

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

            Invoke-Native -File 'psql' -Arguments @(
                '-v', 'ON_ERROR_STOP=1', '-q',
                '-h', $dbHost, '-p', $dbPort, '-U', $superUser, '-d', 'postgres',
                '-f', $sqlPath
            ) | Out-Null
            Write-Ok ('Role "' + $dbUser + '" and database "' + $dbName + '" are ready')

            Write-Info 'Verifying that the application role has no elevated privileges:'
            Invoke-Native -File 'psql' -Arguments @(
                '-h', $dbHost, '-p', $dbPort, '-U', $superUser, '-d', 'postgres', '-c',
                ("SELECT rolname, rolsuper AS is_superuser, rolbypassrls AS bypasses_rls FROM pg_roles WHERE rolname = '" + $dbUser + "';")
            ) | Out-Null
            $databaseReady = $true
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
            if (Test-Path $sqlPath) { Remove-Item $sqlPath -Force -ErrorAction SilentlyContinue }
        }
    }

    Write-Section '6. Database migrations'
    if ($databaseReady) {
        Invoke-Native -File $venvPython -Arguments @('-m', 'alembic', 'upgrade', 'head') -WorkingDirectory $apiDir | Out-Null
        Write-Ok 'Baseline migration applied'
    }
    else {
        Write-Warn 'Skipped: the database was not provisioned in this run.'
    }

    Write-Section 'Result'
    Write-Host 'Setup finished. Next step: scripts\02-run.ps1'
}
catch {
    Write-Fail $_.Exception.Message
    Write-Host 'Setup did not finish. The full log is in the _logs folder.'
}
finally {
    Stop-SahlLog
}
