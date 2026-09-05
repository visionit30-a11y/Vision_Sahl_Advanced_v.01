# ---------------------------------------------------------------
#  Sahl Developer Platform - shared script helpers
#  Safety rules (ADR-0004):
#    * never delete anything outside the project folder
#    * never change Windows system settings
#    * never install machine wide software
#    * never write a password into a log file
# ---------------------------------------------------------------

$ErrorActionPreference = 'Stop'

function Get-ProjectRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Start-SahlLog {
    param([Parameter(Mandatory = $true)][string] $Name)

    $logDir = Join-Path (Get-ProjectRoot) '_logs'
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $path = Join-Path $logDir ("{0}-{1}.log" -f $Name, $stamp)
    Start-Transcript -Path $path -Force | Out-Null
    Write-Host ("Log file: " + $path)
    return $path
}

function Stop-SahlLog {
    try { Stop-Transcript | Out-Null } catch { }
}

function Write-Section {
    param([Parameter(Mandatory = $true)][string] $Title)
    Write-Host ''
    Write-Host ('=========== ' + $Title + ' ===========')
}

function Write-Info  { param([string] $Message) Write-Host ('  [i] ' + $Message) }
function Write-Ok    { param([string] $Message) Write-Host ('  [OK] ' + $Message) }
function Write-Warn  { param([string] $Message) Write-Host ('  [!] ' + $Message) }
function Write-Fail  { param([string] $Message) Write-Host ('  [X] ' + $Message) }

function Test-CommandExists {
    param([Parameter(Mandatory = $true)][string] $Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function ConvertTo-NativeLine {
    <#
        Many command line tools write progress and INFO messages to stderr.
        PowerShell 5.1 turns those into ErrorRecord objects and renders them
        with a NativeCommandError banner, which makes successful runs look like
        failures in the log. This flattens such a record back to its plain
        message. Tool behaviour is untouched; only the rendering changes -
        success or failure is decided by the exit code alone.
    #>
    param($Item)

    if ($null -eq $Item) { return '' }
    if ($Item -is [System.Management.Automation.ErrorRecord]) {
        return $Item.Exception.Message
    }
    return [string]$Item
}

function Invoke-Native {
    <#
        Runs an external program, echoes stdout and stderr into the transcript
        and returns the exit code. Throws on failure unless -AllowFailure is set.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $File,
        [string[]] $Arguments = @(),
        [string] $WorkingDirectory,
        [switch] $AllowFailure
    )

    $previousLocation = $null
    if ($WorkingDirectory) {
        $previousLocation = (Get-Location).Path
        Set-Location $WorkingDirectory
    }

    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $code = 0
    try {
        Write-Host ('  $ ' + $File + ' ' + ($Arguments -join ' '))
        # Captured, not streamed, so stderr records are not rendered as errors.
        $raw = & $File @Arguments 2>&1
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        foreach ($item in @($raw)) {
            $line = (ConvertTo-NativeLine $item).TrimEnd()
            if ($line -ne '') { Write-Host ('    ' + $line) }
        }
    }
    finally {
        $ErrorActionPreference = $previousEap
        if ($previousLocation) { Set-Location $previousLocation }
    }

    if ($code -ne 0 -and -not $AllowFailure) {
        throw ("Command failed with exit code {0}: {1} {2}" -f $code, $File, ($Arguments -join ' '))
    }
    return $code
}

function Invoke-NativeCapture {
    <#
        Runs an external program and returns its output plus exit code without
        letting native stderr become a terminating error or an error banner.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $File,
        [string[]] $Arguments = @()
    )

    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $lines = @()
    $code = 0
    try {
        $raw = & $File @Arguments 2>&1
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        $lines = @(foreach ($item in @($raw)) { (ConvertTo-NativeLine $item).TrimEnd() })
    }
    catch {
        $lines = @($_.Exception.Message)
        $code = -1
    }
    finally {
        $ErrorActionPreference = $previousEap
    }

    $lines = @($lines | Where-Object { $_ -ne '' })

    return [pscustomobject]@{
        Output   = $lines
        ExitCode = $code
        Text     = ($lines -join [Environment]::NewLine)
    }
}

function Get-ToolVersion {
    param(
        [Parameter(Mandatory = $true)][string] $File,
        [string[]] $Arguments = @('--version')
    )

    $result = Invoke-NativeCapture -File $File -Arguments $Arguments
    if ($result.ExitCode -ne 0 -or -not $result.Text) { return $null }
    return (($result.Text -split "`n")[0]).Trim()
}

function Resolve-PsqlPath {
    <#
        Finds psql.exe without changing the machine PATH.
        A standalone PostgreSQL installation is always preferred; a psql that
        ships inside an Odoo installation is only a last resort client and is
        reported as such (ADR-0006).
    #>
    $standalone = @()
    foreach ($pattern in @(
            'C:\Program Files\PostgreSQL\*\bin\psql.exe',
            'C:\Program Files (x86)\PostgreSQL\*\bin\psql.exe')) {
        $standalone += @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName)
    }
    if ($standalone.Count -gt 0) {
        return @(@($standalone) | Sort-Object -Descending)[0]
    }

    $command = Get-Command 'psql' -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'Odoo') { return $command.Source }

    $bundled = @()
    foreach ($pattern in @(
            'C:\Program Files\Odoo*\PostgreSQL\bin\psql.exe',
            'C:\Program Files (x86)\Odoo*\PostgreSQL\bin\psql.exe')) {
        $bundled += @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName)
    }
    if ($bundled.Count -gt 0) {
        Write-Warn 'Only an Odoo bundled psql client was found. It is used as a client only; the Sahl server must still be an independent instance.'
        return @(@($bundled) | Sort-Object -Descending)[0]
    }

    return $null
}

function Test-TcpPort {
    param(
        [string] $ComputerName = '127.0.0.1',
        [Parameter(Mandatory = $true)][int] $Port,
        [int] $TimeoutMs = 1500
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($ComputerName, $Port, $null, $null)
        $completed = $async.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($completed -and $client.Connected) {
            $client.EndConnect($async)
            return $true
        }
        return $false
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Get-VenvPython {
    $python = Join-Path (Get-ProjectRoot) 'apps\api\.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw 'Virtual environment not found. Run scripts\01-setup.ps1 first.'
    }
    return $python
}

function Get-EnvValue {
    param([Parameter(Mandatory = $true)][string] $Key)

    $envFile = Join-Path (Get-ProjectRoot) '.env'
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim()
        }
    }
    return $null
}
