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
    foreach ($tool in @('git', 'node', 'npm', 'python', 'py', 'psql')) {
        if (Test-CommandExists $tool) {
            $version = ''
            try { $version = (& $tool --version 2>&1 | Select-Object -First 1) } catch { $version = '(version unavailable)' }
            Write-Ok ("{0,-8} {1}" -f $tool, $version)
        }
        else {
            Write-Fail ("{0,-8} NOT FOUND in PATH" -f $tool)
        }
    }

    Write-Section 'Optional tools (not required for Phase 0)'
    foreach ($tool in @('docker', 'redis-cli')) {
        if (Test-CommandExists $tool) { Write-Ok ($tool + ' present') } else { Write-Info ($tool + ' not present - expected in Phase 0') }
    }

    Write-Section 'Python interpreters'
    if (Test-CommandExists 'py') {
        Invoke-Native -File 'py' -Arguments @('-0p') -AllowFailure | Out-Null
    }

    Write-Section 'PostgreSQL service'
    $services = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue
    if ($services) {
        foreach ($service in $services) { Write-Info ($service.Name + ' : ' + $service.Status) }
    }
    else {
        Write-Warn 'No service named postgresql* found. PostgreSQL may be installed under another service name.'
    }

    Write-Section 'Project state'
    $items = @{
        '.env file'            = (Join-Path $root '.env')
        'API virtualenv'       = (Join-Path $root 'apps\api\.venv')
        'Web node_modules'     = (Join-Path $root 'apps\web\node_modules')
        'Git repository'       = (Join-Path $root '.git')
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
