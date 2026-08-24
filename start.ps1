$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}
Push-Location $ProjectRoot
try {
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
}
finally {
    Pop-Location
}

