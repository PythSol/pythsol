<#
Publish the built sdist and wheel to PyPI.

Run from anywhere:

    powershell -NoProfile -ExecutionPolicy Bypass -File tools\publish_pypi.ps1

It prompts for the API token with hidden input, keeps it only in this
process, uploads, and verifies. Get a token at
https://pypi.org/manage/account/token/ ("Add API token", scope "Entire
account" for the first upload). Do not paste the token into chat or commit it.
#>
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$dist = Join-Path $root "target\dist"

if (-not (Test-Path $python)) {
    throw "Missing .venv. Create it and install build + twine first (docs/guides/release.md)."
}

$wheel = Get-ChildItem $dist -Filter "pythsol-*.whl" -ErrorAction SilentlyContinue
if (-not $wheel) {
    Write-Host "No wheel in target\dist; building sdist and wheel..."
    & $python -m build --outdir $dist
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
}

$files = @(Get-ChildItem $dist -File | Where-Object { $_.Name -like "pythsol-*" } | ForEach-Object { $_.FullName })
if ($files.Count -eq 0) { throw "No pythsol artifacts in $dist" }

Write-Host "Checking artifacts..."
& $python -m twine check $files
if ($LASTEXITCODE -ne 0) { throw "twine check failed" }

$secure = Read-Host "Paste the PyPI API token (pypi-..., input is hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if (-not $token.StartsWith("pypi-")) {
    throw "That does not look like a PyPI API token (it should start with pypi-)."
}

$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = $token
try {
    Write-Host "Uploading $($files.Count) files to PyPI..."
    & $python -m twine upload $files
    if ($LASTEXITCODE -ne 0) { throw "twine upload failed" }
} finally {
    Remove-Item Env:TWINE_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:TWINE_PASSWORD -ErrorAction SilentlyContinue
    $token = $null
}

Write-Host ""
Write-Host "Upload finished. Checking the public index..."
& $python -m pip index versions pythsol
Write-Host ""
Write-Host "Next: create a project-scoped token for future releases, then verify"
Write-Host 'a fresh install with: python -m pip install "pythsol[test]"'
