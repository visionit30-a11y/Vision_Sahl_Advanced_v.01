# ---------------------------------------------------------------
#  04-git-sync.ps1  -  push the local branches to GitHub
#
#  Pushes main, develop and the current feature branch to the official
#  repository. It never rewrites history and never force pushes.
#  The first push may open a GitHub sign-in window; that sign-in is
#  performed by the repository owner, not by any script.
# ---------------------------------------------------------------

. (Join-Path $PSScriptRoot '_common.ps1')

$log = Start-SahlLog -Name '04-git-sync'
$root = Get-ProjectRoot
$expectedRemote = 'https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01'

try {
    if (-not (Test-CommandExists 'git')) { throw 'git was not found in PATH.' }

    Write-Section 'Repository state'
    Invoke-Native -File 'git' -Arguments @('status', '--short', '--branch') -WorkingDirectory $root -AllowFailure | Out-Null
    Invoke-Native -File 'git' -Arguments @('log', '--oneline', '-n', '12') -WorkingDirectory $root -AllowFailure | Out-Null

    Write-Section 'Remote'
    $remote = (& git -C $root remote get-url origin 2>$null)
    if (-not $remote) {
        Invoke-Native -File 'git' -Arguments @('remote', 'add', 'origin', $expectedRemote) -WorkingDirectory $root | Out-Null
        Write-Ok ('origin added: ' + $expectedRemote)
    }
    elseif ($remote.Trim() -ne $expectedRemote) {
        throw ('origin points to an unexpected repository: ' + $remote.Trim())
    }
    else {
        Write-Ok ('origin: ' + $remote.Trim())
    }

    $currentBranch = (& git -C $root rev-parse --abbrev-ref HEAD).Trim()
    Write-Info ('Current branch: ' + $currentBranch)

    Write-Section 'Push'
    $branches = @('main', 'develop')
    if ($branches -notcontains $currentBranch) { $branches += $currentBranch }

    $failed = @()
    foreach ($branch in $branches) {
        $exists = (& git -C $root rev-parse --verify --quiet ("refs/heads/" + $branch))
        if (-not $exists) { Write-Info ('branch ' + $branch + ' does not exist locally - skipped'); continue }
        $code = Invoke-Native -File 'git' -Arguments @('push', '-u', 'origin', $branch) -WorkingDirectory $root -AllowFailure
        if ($code -eq 0) { Write-Ok ($branch + ' pushed') } else { $failed += $branch }
    }

    Write-Section 'Result'
    if ($failed.Count -eq 0) {
        Write-Host 'All branches are in sync with GitHub.'
    }
    else {
        Write-Host ('Could not push: ' + ($failed -join ', '))
        Write-Host 'If GitHub asked for a sign-in, complete it once in the window that opened and run this script again.'
    }
}
catch {
    Write-Fail $_.Exception.Message
}
finally {
    Stop-SahlLog
}
