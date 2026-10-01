param([string]$OutputDirectory = "dist", [string]$WorkDirectory = "build", [string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PythonExe) { $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe" }

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Project virtual environment not found. Follow the setup instructions in README.md."
}

Push-Location $ProjectRoot
try {
    & $PythonExe -m PyInstaller --noconfirm --clean --distpath $OutputDirectory --workpath $WorkDirectory helppack.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    Write-Host "Built: $OutputDirectory\HelpPack-English.exe"
}
finally {
    Pop-Location
}
