param([Parameter(Mandatory=$true)][string]$RepoUrl)
$ErrorActionPreference = "Stop"

if (!(Get-Command git -ErrorAction SilentlyContinue)) { throw "git is not installed or not available in PATH." }
if (!(Get-Command python -ErrorAction SilentlyContinue)) { throw "python is required for the pre-push repository checks." }

python .\scripts\public_repo_check.py
if ($LASTEXITCODE -ne 0) { throw "Public repository check failed. Push cancelled." }
python .\scripts\validate_evidence.py
if ($LASTEXITCODE -ne 0) { throw "Dataset/evaluation evidence check failed. Push cancelled." }

if (!(Test-Path ".git")) { git init }
git add .

$staged = git diff --cached --name-only
if (!$staged) { Write-Host "No staged changes to commit." } else { git commit -m "Publish NEXis end-of-line spin inspection" }

git branch -M main
$remote = git remote 2>$null
if ($remote -contains "origin") { git remote set-url origin $RepoUrl } else { git remote add origin $RepoUrl }
git push -u origin main
