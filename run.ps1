param([string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PythonExe) { $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe" }

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Project virtual environment not found. Follow the setup instructions in README.md."
}

Push-Location $ProjectRoot
try {
    $OriginalPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    & $PythonExe -m helppack
    if ($LASTEXITCODE -ne 0) { throw "HelpPack could not start." }
}
finally { $env:PYTHONPATH = $OriginalPythonPath; Pop-Location }
