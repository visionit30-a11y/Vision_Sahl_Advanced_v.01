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
        & $File @Arguments 2>&1 | ForEach-Object { Write-Host ('    ' + (($_ | Out-String).TrimEnd())) }
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
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
