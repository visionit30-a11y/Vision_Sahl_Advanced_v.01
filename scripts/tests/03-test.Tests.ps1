# Regression tests for quality-gate orchestration, not database/security tests.
# Native command results are simulated here; 03-test.ps1 still proves database
# behavior separately against real PostgreSQL. No packages or schemas are changed.
[CmdletBinding()]
param([string] $Scenario)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$gatePath = Join-Path $projectRoot 'scripts\03-test.ps1'

if ($Scenario) {
    $script:upgradeCount = 0
    $script:currentCount = 0
    $script:gitCount = 0

    function Start-SahlLog { param([string] $Name) return '(simulated transcript)' }
    function Stop-SahlLog { }
    function Get-ProjectRoot { return $projectRoot }
    function Get-VenvPython {
        if ($Scenario -eq 'exception') { throw 'Simulated missing interpreter.' }
        return 'simulated-python'
    }
    function Test-CommandExists { param([string] $Name) return $true }
    function Write-Section { param([string] $Title) Write-Host $Title }
    function Write-Info { param([string] $Message) Write-Host $Message }
    function Write-Fail { param([string] $Message) Write-Host ('FAIL: ' + $Message) }
    function Get-EnvValue {
        param([string] $Key)
        return 'postgresql+psycopg://sahl_app:unused@127.0.0.1:5433/simulated_gate'
    }
    function Test-TcpPort { param([int] $Port) return ($Scenario -ne 'database_unavailable') }
    function Resolve-PsqlPath { return 'simulated-psql' }

    function Invoke-Native {
        param([string] $File, [string[]] $Arguments, [string] $WorkingDirectory, [switch] $AllowFailure)
        $command = $Arguments -join ' '
        Write-Host ('SIMULATED native: ' + $command)
        if ($Scenario -eq 'sync_failure' -and $command -eq 'sync --frozen') { return 1 }
        if ($Scenario -eq 'lock_failure' -and $command -eq 'lock --check') { return 1 }
        if ($Scenario -eq 'pytest_failure' -and $command -eq '-m pytest') { return 1 }
        if ($Scenario -eq 'format_failure' -and $command -eq '-m ruff format --check .') { return 1 }
        if ($Scenario -eq 'autoformat_failure' -and $command -eq 'run format') { return 1 }
        if ($Scenario -eq 'prettier_failure' -and $command -eq 'run format:check') { return 1 }
        return 0
    }

    function New-SimulatedResult {
        param([string[]] $Lines = @(), [int] $Code = 0)
        return [pscustomobject]@{ Output = $Lines; Text = ($Lines -join [Environment]::NewLine); ExitCode = $Code }
    }

    function Invoke-NativeCapture {
        param([string] $File, [string[]] $Arguments)
        if ($File -eq 'git') {
            $script:gitCount++
            if ($Scenario -eq 'git_failure' -or ($Scenario -eq 'final_git_failure' -and $script:gitCount -ge 5)) {
                return (New-SimulatedResult -Code 1 -Lines @('Simulated Git failure.'))
            }
            if ($Arguments -contains 'rev-parse') { return (New-SimulatedResult -Lines @('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')) }
            return (New-SimulatedResult -Lines @(' M simulated_worktree.py'))
        }
        if ($File -eq 'simulated-psql') {
            if (($Arguments -join ' ') -match 'rolsuper') {
                $flags = if ($Scenario -eq 'role_failure') { 'true false' } else { 'false false' }
                return (New-SimulatedResult -Lines @($flags))
            }
            return (New-SimulatedResult -Lines @('0'))
        }
        if ($File -ne 'simulated-python' -or $Arguments[1] -ne 'alembic') {
            throw 'Unexpected native command in gate regression test.'
        }
        $command = $Arguments[2..($Arguments.Length - 1)] -join ' '
        Write-Host ('SIMULATED alembic: ' + $command)
        switch ($command) {
            'heads' {
                if ($Scenario -eq 'heads_failure') { return (New-SimulatedResult -Code 1) }
                if ($Scenario -eq 'multiple_heads') {
                    return (New-SimulatedResult -Lines @('0002_tenant_foundation (head)', '0003_other_branch (head)'))
                }
                return (New-SimulatedResult -Lines @('0002_tenant_foundation (head)'))
            }
            'upgrade head' {
                $script:upgradeCount++
                if (($Scenario -eq 'initial_upgrade_failure' -and $script:upgradeCount -eq 1) -or
                    ($Scenario -eq 'final_upgrade_failure' -and $script:upgradeCount -eq 2)) {
                    return (New-SimulatedResult -Code 1)
                }
                return (New-SimulatedResult)
            }
            'downgrade base' {
                if ($Scenario -eq 'downgrade_failure') { return (New-SimulatedResult -Code 1) }
                return (New-SimulatedResult)
            }
            'current' {
                $script:currentCount++
                if ($Scenario -eq 'current_failure') { return (New-SimulatedResult -Code 1) }
                if ($Scenario -eq 'empty_revision') { return (New-SimulatedResult) }
                if (($Scenario -eq 'initial_stale_revision' -and $script:currentCount -eq 1) -or
                    ($Scenario -eq 'final_stale_revision' -and $script:currentCount -eq 3)) {
                    return (New-SimulatedResult -Lines @('0001_baseline'))
                }
                if ($Scenario -eq 'wrong_head_annotation') {
                    return (New-SimulatedResult -Lines @('0001_baseline (head)'))
                }
                if ($script:currentCount -eq 2) {
                    if ($Scenario -eq 'base_current_failure') { return (New-SimulatedResult -Code 1) }
                    if ($Scenario -eq 'downgrade_no_effect') {
                        return (New-SimulatedResult -Lines @('0002_tenant_foundation (head)'))
                    }
                    return (New-SimulatedResult -Lines @('INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.'))
                }
                return (New-SimulatedResult -Lines @(
                        'INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.',
                        '0002_tenant_foundation (head)'))
            }
            default { throw ('Unexpected Alembic command: ' + $command) }
        }
    }

    # Replace only bootstrap helper loading. Execute the production script,
    # including its actual exit, branching, summary and revision comparisons.
    $source = Get-Content -LiteralPath $gatePath -Raw
    # Literal single quoting avoids interpolating the tested script's PSScriptRoot.
    $bootstrap = '. (Join-Path $PSScriptRoot ''_common.ps1'')'
    if (-not $source.Contains($bootstrap)) { throw 'Cannot locate the quality gate bootstrap.' }
    $source = $source.Replace($bootstrap, '# Test doubles already loaded.')
    & ([scriptblock]::Create($source))
    throw 'The quality script returned without an explicit process exit.'
}

$scenarios = @(
    'pass', 'initial_stale_revision', 'final_stale_revision', 'wrong_head_annotation',
    'empty_revision', 'multiple_heads', 'heads_failure', 'current_failure',
    'initial_upgrade_failure', 'downgrade_failure', 'downgrade_no_effect',
    'base_current_failure', 'final_upgrade_failure',
    'database_unavailable', 'sync_failure', 'lock_failure', 'pytest_failure',
    'format_failure', 'autoformat_failure', 'prettier_failure', 'role_failure',
    'exception', 'git_failure', 'final_git_failure'
)
$noPytest = @(
    'initial_stale_revision', 'final_stale_revision', 'wrong_head_annotation',
    'empty_revision', 'multiple_heads', 'heads_failure', 'current_failure',
    'initial_upgrade_failure', 'downgrade_failure', 'downgrade_no_effect',
    'base_current_failure', 'final_upgrade_failure',
    'database_unavailable', 'sync_failure', 'exception', 'git_failure'
)
$hostExecutable = (Get-Process -Id $PID).Path
$failures = @()
foreach ($case in $scenarios) {
    $output = & $hostExecutable -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Scenario $case 2>&1
    $code = $LASTEXITCODE
    $text = $output -join [Environment]::NewLine
    $expectedCode = if ($case -eq 'pass') { 0 } else { 1 }
    $problems = @()
    if ($code -ne $expectedCode) { $problems += ('expected exit ' + $expectedCode + ', got ' + $code) }
    if ($text -notmatch ('Final exit code: ' + $expectedCode)) { $problems += 'final result was not logged' }
    if ($noPytest -contains $case -and $text -match 'SIMULATED native: -m pytest') {
        $problems += 'pytest ran without a verified current schema'
    }
    if ($text -match 'SKIP|WARN') { $problems += 'a gate was downgraded to skip/warning' }
    if ($case -eq 'pass') {
        $sequence = @($output | Where-Object { "$_" -match '^SIMULATED (alembic:|native: -m pytest)' })
        $expectedSequence = @(
            'SIMULATED alembic: heads',
            'SIMULATED alembic: upgrade head',
            'SIMULATED alembic: current',
            'SIMULATED alembic: downgrade base',
            'SIMULATED alembic: current',
            'SIMULATED alembic: upgrade head',
            'SIMULATED alembic: current',
            'SIMULATED native: -m pytest'
        )
        if (($sequence -join '|') -ne ($expectedSequence -join '|')) { $problems += 'migration/pytest sequence was wrong' }
        if ($text -notmatch 'Actual Alembic revision: \(base / no revision\)') { $problems += 'downgrade state evidence was absent' }
        if ($text -notmatch 'Git HEAD: a{40}' -or $text -notmatch 'Git worktree:') { $problems += 'Git provenance was absent' }
        if ($text -notmatch 'Expected Alembic revision: 0002_tenant_foundation' -or
            $text -notmatch 'Actual Alembic revision: 0002_tenant_foundation') { $problems += 'revision evidence was absent' }
    }
    if ($problems.Count) {
        $failures += $case
        Write-Host ('FAIL ' + $case + ': ' + ($problems -join '; '))
        Write-Host $text
    }
    else {
        Write-Host ('PASS ' + $case)
    }
}
if ($failures.Count) { throw ('Quality gate regression failures: ' + ($failures -join ', ')) }
Write-Host ($scenarios.Count.ToString() + ' quality gate orchestration scenarios passed. No database or package commands were executed.')
