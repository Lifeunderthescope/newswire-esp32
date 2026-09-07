# Run from PowerShell to publish the prepared snapshot using your GitHub account.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$repoPath = $PSScriptRoot.Replace('\', '/')
function Invoke-RepoGit {
    & git -c "safe.directory=$repoPath" @args
    if ($LASTEXITCODE -ne 0) { throw 'Git command failed; publishing stopped.' }
}
gh auth status
if ($LASTEXITCODE -ne 0) {
    gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { throw 'GitHub sign-in did not complete.' }
}
$accountJson = gh api user
if ($LASTEXITCODE -ne 0) { throw 'Could not identify the signed-in account.' }
$account = $accountJson | ConvertFrom-Json
$repo = "$($account.login)/newswire-esp32"
Write-Host "Publishing private repository: $repo"

# Use the account's private noreply address for this repository only.
Invoke-RepoGit config user.name $account.login
Invoke-RepoGit config user.email "$($account.id)+$($account.login)@users.noreply.github.com"
$files = @(Invoke-RepoGit diff --cached --name-only)
if ($files -match '(^|/)(secrets\.h|\.env[^/]*|\.venv|\.pio)(/|$)|\.(bin|elf|key|pem)$') {
    throw 'Unexpected sensitive/build file staged. Review before publishing.'
}
if ($files.Count -gt 0) {
    Invoke-RepoGit commit -m 'Document working NEWSWIRE firmware and terminal dashboard'
}
& git -c "safe.directory=$repoPath" remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) {
    gh repo create $repo --private --description 'Headless ESP32-S3 tech news broadcaster and live Textual terminal dashboard'
    if ($LASTEXITCODE -ne 0) { throw 'Repository creation failed; no code was pushed. Check whether the name already exists.' }
    Invoke-RepoGit remote add origin "https://github.com/$repo.git"
}
$origin = Invoke-RepoGit remote get-url origin
if ($origin -ne "https://github.com/$repo.git") { throw 'Origin does not match the intended repository.' }
$visibility = gh repo view $repo --json visibility --jq '.visibility'
if ($LASTEXITCODE -ne 0 -or $visibility -ne 'PRIVATE') { throw 'Private visibility could not be verified. No code was pushed.' }
Invoke-RepoGit -c credential.helper= -c 'credential.helper=!gh auth git-credential' push -u origin main
gh repo view $repo --json url,visibility
if ($LASTEXITCODE -ne 0) { throw 'Push finished, but final repository lookup failed.' }
