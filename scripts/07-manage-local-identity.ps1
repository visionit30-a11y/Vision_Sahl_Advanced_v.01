[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

$root = Get-ProjectRoot
$appEnv = Get-EnvValue -Key 'APP_ENV'
if ($appEnv -ne 'development') {
    throw 'This command is restricted to APP_ENV=development.'
}

$python = Get-VenvPython
$psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $psql) {
    $candidate = 'C:\Program Files\PostgreSQL\17\bin\psql.exe'
    if (Test-Path -LiteralPath $candidate) { $psql = $candidate }
}
if (-not $psql) { throw 'PostgreSQL 17 psql was not found.' }

$choice = Read-Host 'Action: 1=bootstrap Tenant Admin, 2=reset password'
$action = if ($choice -eq '1') { 'bootstrap-admin' } elseif ($choice -eq '2') { 'reset-password' } else { throw 'Invalid action.' }
$force = Read-Host 'Force password change at next login? (y/N)'

$secure = Read-Host 'PostgreSQL local administrator password' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$adminPassword = $null
$operatorPassword = $null
$operatorPasswordBytes = New-Object byte[] 36
$operator = 'sahl_identity_bootstrap_' + ([guid]::NewGuid().ToString('N').Substring(0, 12))
$operatorCreated = $false
try {
    $adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($operatorPasswordBytes) }
    finally { $random.Dispose() }
    $operatorPassword = [Convert]::ToBase64String($operatorPasswordBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $env:PGPASSWORD = $adminPassword
    $create = @"
CREATE ROLE $operator LOGIN PASSWORD '$operatorPassword'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT sahl_identity_bootstrap TO $operator;
GRANT CONNECT ON DATABASE sahl_dev TO $operator;
"@
    $create | & $psql -v ON_ERROR_STOP=1 -q -h 127.0.0.1 -p 5433 -U postgres -d postgres
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the temporary identity operator.' }
    $operatorCreated = $true

    $env:IDENTITY_BOOTSTRAP_DATABASE_URL = "postgresql+psycopg://$operator`:$operatorPassword@127.0.0.1:5433/sahl_dev"
    Push-Location (Join-Path $root 'apps\api')
    try {
        $arguments = @('-m', 'app.maintenance.identity_bootstrap', $action)
        if ($force -match '^[Yy]$') { $arguments += '--force-password-change' }
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Identity administration failed.' }
    }
    finally { Pop-Location }
}
finally {
    Remove-Item Env:IDENTITY_BOOTSTRAP_DATABASE_URL -ErrorAction SilentlyContinue
    if ($operatorCreated) {
        $env:PGPASSWORD = $adminPassword
        $cleanup = @"
REVOKE CONNECT ON DATABASE sahl_dev FROM $operator;
REVOKE sahl_identity_bootstrap FROM $operator;
DROP ROLE IF EXISTS $operator;
"@
        $cleanup | & $psql -v ON_ERROR_STOP=1 -q -h 127.0.0.1 -p 5433 -U postgres -d postgres
    }
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $adminPassword = $null
    $operatorPassword = $null
    [Array]::Clear($operatorPasswordBytes, 0, $operatorPasswordBytes.Length)
}
