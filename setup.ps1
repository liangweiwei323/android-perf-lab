$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Uv = "D:\codex\perfetto-tools\.bin\uv\uv.exe"
$Python = "D:\codex\perfetto-tools\.bin\python\cpython-3.13.14-windows-x86_64-none\python.exe"

if (-not (Test-Path -LiteralPath $Uv)) {
    throw "Perfetto Tools uv runtime not found: $Uv"
}

Push-Location $ProjectRoot
try {
    & $Uv venv --python $Python .venv
    & $Uv sync --project $ProjectRoot
    & ".\.venv\Scripts\python.exe" -m compileall app
}
finally {
    Pop-Location
}

Write-Host "Setup complete. Run .\start.ps1"

