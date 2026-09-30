param([string]$OutputDirectory = "dist", [string]$WorkDirectory = "build")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "未找到项目虚拟环境。请先按照 README.md 完成开发环境搭建。"
}

Push-Location $ProjectRoot
try {
    & $PythonExe -m PyInstaller --noconfirm --clean --distpath $OutputDirectory --workpath $WorkDirectory helppack.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }
    Write-Host "打包完成：$OutputDirectory\HelpPack.exe"
}
finally {
    Pop-Location
}
