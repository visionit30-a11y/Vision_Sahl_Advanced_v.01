# ---------------------------------------------------------------
#  00-check.ps1  -  read only environment report
#  Changes nothing. Writes the report to _logs\00-check-<stamp>.log
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '00-check'
$root = Get-ProjectRoot

try {
    Write-Section 'Host'
    Write-Info ('Project root  : ' + $root)
    Write-Info ('PowerShell    : ' + $PSVersionTable.PSVersion.ToString())
    Write-Info ('OS            : ' + [System.Environment]::OSVersion.VersionString)
    Write-Info ('Date          : ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

    Write-Section 'Required tools'
    foreach ($tool in @('git', 'node', 'npm', 'py', 'python')) {
        if (Test-CommandExists $tool) {
            $version = Get-ToolVersion -File $tool
            if (-not $version) { $version = '(version unavailable)' }
            Write-Ok ("{0,-8} {1}" -f $tool, $version)
        }
        else {
            Write-Fail ("{0,-8} NOT FOUND in PATH" -f $tool)
        }
    }

    Write-Section 'Baseline versions'
    # The baseline lives in one file per runtime, and this compares the machine
    # against it. A silent drift between the local machine and CI is how a build
    # passes in one place and fails in the other.
    $nvmrc = Join-Path $root 'apps\web\.nvmrc'
    if (Test-Path $nvmrc) {
        $nodeBaseline = (Get-Content $nvmrc -Raw).Trim()
        $nodeActual = Get-ToolVersion -File 'node'
        $nodeMajor = if ($nodeActual -match 'v?(\d+)\.') { $Matches[1] } else { $null }
        if ($nodeMajor -eq $nodeBaseline) {
            Write-Ok ("Node baseline {0} matches installed {1}" -f $nodeBaseline, $nodeActual)
        }
        else {
            Write-Fail ("Node baseline is {0} (apps\web\.nvmrc) but {1} is installed" -f $nodeBaseline, $nodeActual)
        }
    }
    else {
        Write-Warn 'apps\web\.nvmrc is missing; the Node baseline cannot be checked.'
    }

    $pythonVersionFile = Join-Path $root 'apps\api\.python-version'
    if (Test-Path $pythonVersionFile) {
        $pythonBaseline = (Get-Content $pythonVersionFile -Raw).Trim()
        $baselineVersion = Get-ToolVersion -File 'py' -Arguments @(('-' + $pythonBaseline), '--version')
        if ($baselineVersion) {
            Write-Ok ("Python baseline {0} available: {1}" -f $pythonBaseline, $baselineVersion)
        }
        else {
            Write-Fail ("Python baseline is {0} (apps\api\.python-version) but 'py -{0}' did not answer" -f $pythonBaseline)
        }

        $venvDir = Join-Path $root 'apps\api\.venv'
        if (Test-Path $venvDir) {
            # Both sources are reported, because a report that shows only one of
            # them cannot tell a matching environment from a half-rebuilt one.
            $venvState = Get-VirtualEnvironmentState -VenvPath $venvDir -Baseline $pythonBaseline
            if ($venvState.ExecutableVersion) {
                Write-Info ('Project virtualenv interpreter: Python ' + $venvState.ExecutableVersion)
            }
            else {
                Write-Fail ('Project virtualenv interpreter: ' + $venvState.ExecutableError)
            }
            if ($venvState.ConfigVersion) {
                Write-Info ('Project virtualenv pyvenv.cfg: ' + $venvState.ConfigKey + ' = ' + $venvState.ConfigVersion)
            }
            else {
                Write-Fail ('Project virtualenv pyvenv.cfg: ' + $venvState.ConfigError)
            }

            if ($venvState.Status -eq 'matches') {
                Write-Ok ('Project virtualenv matches the baseline ' + $pythonBaseline)
            }
            else {
                Write-Fail ('Project virtualenv does not match the baseline: ' + $venvState.Reason)
                if ($venvState.Status -ne 'inconsistent') {
                    Write-Info 'Run scripts\01-setup.ps1 to rebuild it.'
                }
            }
        }
        else {
            Write-Info 'Project virtualenv not created yet'
        }
    }
    else {
        Write-Warn 'apps\api\.python-version is missing; the Python baseline cannot be checked.'
    }

    $uvPresent = Test-CommandExists 'uv'
    if ($uvPresent) {
        $uvVersion = Get-ToolVersion -File 'uv'
        Write-Ok ('uv found: ' + $uvVersion)
    }
    else {
        Write-Fail 'uv was not found in PATH; the backend dependency lock cannot be used.'
    }

    Write-Section 'Python interpreters'
    if (Test-CommandExists 'py') {
        $interpreters = Invoke-NativeCapture -File 'py' -Arguments @('-0p')
        foreach ($line in $interpreters.Output) { Write-Host ('    ' + $line) }
    }
    foreach ($candidate in @(@('py', @('-3.13')), @('py', @('-3.12')), @('python', @()))) {
        $version = Get-ToolVersion -File $candidate[0] -Arguments ($candidate[1] + @('--version'))
        if ($version) { Write-Info (($candidate[0] + ' ' + ($candidate[1] -join ' ')).Trim() + ' -> ' + $version) }
    }

    Write-Section 'PostgreSQL'
    $psql = Resolve-PsqlPath
    if ($psql) {
        Write-Ok ('psql found: ' + $psql)
        $psqlVersion = Get-ToolVersion -File $psql
        if ($psqlVersion) { Write-Info ('psql version: ' + $psqlVersion) }
    }
    else {
        Write-Fail 'psql.exe was not found (searched PATH, Program Files\PostgreSQL and bundled Odoo installations)'
    }

    $services = Get-Service -Name 'postgres*' -ErrorAction SilentlyContinue
    if ($services) {
        foreach ($service in $services) { Write-Info ('service ' + $service.Name + ' : ' + $service.Status) }
    }
    else {
        Write-Warn 'No PostgreSQL service found by name.'
    }

    foreach ($port in @(5432, 5433, 5434)) {
        if (Test-TcpPort -Port $port) { Write-Ok ('a server is listening on 127.0.0.1:' + $port) }
        else { Write-Info ('nothing listening on 127.0.0.1:' + $port) }
    }

    Write-Section 'Optional tools (not required for Phase 0)'
    foreach ($tool in @('docker', 'redis-cli')) {
        if (Test-CommandExists $tool) { Write-Ok ($tool + ' present') }
        else { Write-Info ($tool + ' not present - expected in Phase 0') }
    }

    Write-Section 'Project state'
    $items = [ordered]@{
        'Git repository'   = (Join-Path $root '.git')
        '.env file'        = (Join-Path $root '.env')
        'API virtualenv'   = (Join-Path $root 'apps\api\.venv')
        'Web node_modules' = (Join-Path $root 'apps\web\node_modules')
    }
    foreach ($key in $items.Keys) {
        if (Test-Path $items[$key]) { Write-Ok ($key + ' present') } else { Write-Info ($key + ' missing') }
    }

    Write-Section 'Result'
    Write-Host 'Environment check finished. Nothing was modified.'
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
