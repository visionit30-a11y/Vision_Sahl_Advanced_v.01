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

function Get-RunPidFile {
    return (Join-Path (Get-ProjectRoot) '_logs\run-pids.json')
}

function Stop-SahlServices {
    <#
        Stops only the processes a previous 02-run recorded. Safe to call when
        nothing is running.

        Windows reuses process ids, so a recorded id can point at a stranger by
        the time this runs. Before anything is stopped the id is checked against
        the run it was recorded in: a process that started before that run, or
        that is not one of the runtimes 02-run starts, is reported and left
        alone rather than killed on the strength of a stale number.
    #>
    $pidFile = Get-RunPidFile
    if (-not (Test-Path $pidFile)) {
        return
    }

    $recorded = Get-Content $pidFile -Raw | ConvertFrom-Json
    $runStart = [datetime]::MinValue
    if ($recorded.started) {
        $parsed = [datetime]::MinValue
        $invariant = [System.Globalization.CultureInfo]::InvariantCulture
        $noStyle = [System.Globalization.DateTimeStyles]::None
        if ([datetime]::TryParseExact([string]$recorded.started, 'yyyyMMdd-HHmmss', $invariant, $noStyle, [ref]$parsed)) {
            # One minute of slack: the stamp is taken before the processes start.
            $runStart = $parsed.AddMinutes(-1)
        }
    }

    foreach ($name in @('api', 'web')) {
        $processId = $recorded.$name
        if (-not $processId) { continue }

        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) { continue }

        if (@('python', 'cmd', 'node') -notcontains $process.ProcessName) {
            Write-Warn ('Recorded ' + $name + ' pid ' + $processId + ' is now ' + $process.ProcessName +
                ', which this project does not start. Left running.')
            continue
        }
        $startedAt = $null
        try { $startedAt = $process.StartTime } catch { $startedAt = $null }
        if ($null -eq $startedAt) {
            Write-Warn ('Recorded ' + $name + ' pid ' + $processId + ' does not disclose its start time, so ownership cannot be proven. Left running.')
            continue
        }
        if ($startedAt -lt $runStart) {
            Write-Warn ('Recorded ' + $name + ' pid ' + $processId + ' started before the run that recorded it. Left running.')
            continue
        }

        Invoke-Native -File 'taskkill' -Arguments @('/PID', "$processId", '/T', '/F') -AllowFailure | Out-Null
        Write-Info ($name + ' from an earlier run stopped (pid ' + $processId + ')')
    }

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

function Get-PortOwner {
    param([Parameter(Mandatory = $true)][int] $Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $connection) { return $null }
    return (Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue)
}

function Get-OwnedTreeRoot {
    <#
        Walks up from a process while its parent is still one of this project's
        runtimes, and returns the topmost one. Killing a worker on its own is
        useless when a reloader parent survives to spawn a replacement.
        The walk stops at anything else, so a shell is never a candidate.
    #>
    param(
        [Parameter(Mandatory = $true)][int] $ProcessId,
        [Parameter(Mandatory = $true)][string[]] $OwnedProcessNames
    )

    $currentId = $ProcessId
    for ($step = 0; $step -lt 6; $step += 1) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $currentId" -ErrorAction SilentlyContinue
        if ($null -eq $info) { break }

        $parentId = [int]$info.ParentProcessId
        if ($parentId -le 0) { break }

        $parent = Get-Process -Id $parentId -ErrorAction SilentlyContinue
        if ($null -eq $parent) { break }
        if ($OwnedProcessNames -notcontains $parent.ProcessName) { break }

        $currentId = $parentId
    }

    return $currentId
}

function Clear-DevelopmentPort {
    <#
        Frees a development port that an orphaned run of this project left
        behind. Only the runtimes this project starts are stopped; anything
        else is reported and left untouched. A uvicorn reloader restarts its
        worker, so the whole owned tree is killed and the port re-checked.
    #>
    param(
        [Parameter(Mandatory = $true)][int] $Port,
        [string[]] $OwnedProcessNames = @('node', 'python', 'cmd'),
        [int] $Attempts = 6
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt += 1) {
        $owner = Get-PortOwner -Port $Port
        if ($null -eq $owner) {
            return $true
        }

        if ($OwnedProcessNames -notcontains $owner.ProcessName) {
            Write-Fail ("Port {0} is held by {1} (pid {2}), which this project did not start." -f $Port, $owner.ProcessName, $owner.Id)
            Write-Warn 'Close that program yourself, then run this script again. Nothing was stopped.'
            return $false
        }

        $rootId = Get-OwnedTreeRoot -ProcessId $owner.Id -OwnedProcessNames $OwnedProcessNames
        Write-Info ("Port {0} is held by an orphaned {1} (pid {2}); stopping its process tree from pid {3}." -f $Port, $owner.ProcessName, $owner.Id, $rootId)
        Invoke-Native -File 'taskkill' -Arguments @('/PID', "$rootId", '/T', '/F') -AllowFailure | Out-Null
        Start-Sleep -Seconds 2
    }

    $remaining = Get-PortOwner -Port $Port
    if ($null -eq $remaining) {
        return $true
    }

    Write-Fail ("Port {0} is still held by {1} (pid {2}) after {3} attempts." -f $Port, $remaining.ProcessName, $remaining.Id, $Attempts)
    return $false
}

function Get-ProcessesUsingPath {
    <#
        Returns every process that this project provably owns because it runs
        from $Path or was started with $Path on its command line. Nothing is
        matched by process name: a python.exe belonging to another project has
        neither its executable nor its command line inside this directory, so
        it can never appear here.
    #>
    param([Parameter(Mandatory = $true)][string] $Path)

    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $prefix = $full + '\'
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    $found = @()

    foreach ($info in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        $executable = $info.ExecutablePath
        $commandLine = $info.CommandLine
        $runsFromPath = $executable -and $executable.StartsWith($prefix, $comparison)
        $namesPath = $commandLine -and ($commandLine.IndexOf($full, $comparison) -ge 0)
        if (-not ($runsFromPath -or $namesPath)) { continue }
        if ([int]$info.ProcessId -eq $PID) { continue }

        $found += [pscustomobject]@{
            Id             = [int]$info.ProcessId
            Name           = $info.Name
            ExecutablePath = $executable
            CommandLine    = $commandLine
            RunsFromPath   = [bool]$runsFromPath
        }
    }

    return , $found
}

function Stop-ProcessesUsingPath {
    <#
        Stops the processes that hold files inside $Path open, and only those.
        Each pid handed to taskkill is individually proven to belong to this
        project by Get-ProcessesUsingPath; /T then takes the descendants a
        reloader would otherwise respawn. Returns $true when nothing owned by
        this project is left running under $Path.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [int] $Attempts = 5
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt += 1) {
        $holders = Get-ProcessesUsingPath -Path $Path
        if ($holders.Count -eq 0) {
            return $true
        }

        foreach ($holder in $holders) {
            Write-Info ('Stopping {0} (pid {1}) started from this environment: {2}' -f $holder.Name, $holder.Id, $holder.ExecutablePath)
            Invoke-Native -File 'taskkill' -Arguments @('/PID', "$($holder.Id)", '/T', '/F') -AllowFailure | Out-Null
        }

        # A uvicorn reloader can be mid-respawn, so the result is re-checked
        # rather than assumed from the exit code of taskkill.
        Start-Sleep -Seconds 2
    }

    $remaining = Get-ProcessesUsingPath -Path $Path
    if ($remaining.Count -eq 0) {
        return $true
    }

    Write-Fail ('{0} process(es) are still running from {1} after {2} attempts:' -f $remaining.Count, $Path, $Attempts)
    foreach ($holder in $remaining) {
        Write-Host ('    pid ' + $holder.Id + '  ' + $holder.ExecutablePath)
        if ($holder.CommandLine) { Write-Host ('      command: ' + $holder.CommandLine) }
    }
    return $false
}

function Remove-ProjectDirectory {
    <#
        Deletes a directory that must sit at an exact, expected location, after
        the processes running from it have been stopped. Windows keeps a loaded
        .pyd locked for a moment after its process dies, so the delete is
        retried a bounded number of times. It never falls back to a rename, a
        scheduled delete or a kill by process name: if the directory cannot be
        removed cleanly the caller is told which file is locked and stops.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $ExpectedPath,
        [int] $Attempts = 5
    )

    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $expected = [System.IO.Path]::GetFullPath($ExpectedPath).TrimEnd('\')
    if ($full -ne $expected) {
        throw ('Refusing to delete ' + $full + ' because it is not ' + $expected)
    }
    if (-not (Test-Path -LiteralPath $full)) {
        return $true
    }

    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt += 1) {
        try {
            Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            return $true
        }
        catch {
            $lastError = $_.Exception.Message
            if (-not (Test-Path -LiteralPath $full)) { return $true }
            Write-Info ('Delete attempt {0} of {1} did not finish: {2}' -f $attempt, $Attempts, $lastError)
            Start-Sleep -Seconds 2
        }
    }

    Write-Fail ('Could not remove ' + $full)
    if ($lastError) { Write-Fail $lastError }
    return $false
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
