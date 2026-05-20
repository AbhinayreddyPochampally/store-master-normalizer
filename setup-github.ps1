# Run this in PowerShell from the project folder:
#   cd "$HOME\Desktop\Store Master Normalizer - Attempt 4"
#   powershell -ExecutionPolicy Bypass -File .\setup-github.ps1
#
# Creates a clean git repo and pushes it to GitHub as "store-master-normalizer".

$ErrorActionPreference = "Stop"
$RepoName = "store-master-normalizer"

# 1. Remove any partial .git left from earlier attempts
if (Test-Path ".git") { Remove-Item -Recurse -Force ".git" }

# 2. Initialise and make the first commit
git init -b main
git config user.name  "Abhinay Reddy"
git config user.email "abhinay3pochampally@gmail.com"
git add -A
git commit -m "Store Master Normalizer: engine, prototype, and v3 reconciliation doc"

# 3. Create the GitHub repo and push.
#    Option A - GitHub CLI (recommended; run `gh auth login` once beforehand):
if (Get-Command gh -ErrorAction SilentlyContinue) {
    gh repo create $RepoName --public --source . --remote origin --push
} else {
    Write-Host ""
    Write-Host "GitHub CLI (gh) not found. Either install it from https://cli.github.com/"
    Write-Host "or create an empty repo named '$RepoName' on github.com, then run:"
    Write-Host ""
    Write-Host "    git remote add origin https://github.com/<your-username>/$RepoName.git"
    Write-Host "    git push -u origin main"
}
