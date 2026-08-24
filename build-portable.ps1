$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PerfettoTools = "D:\codex\perfetto-tools"
$ReleaseRoot = Join-Path $ProjectRoot "release\AndroidPerfLab-0.3.9-win64"
$PyInstallerDist = Join-Path $ProjectRoot "build\pyinstaller-dist"
$PyInstallerWork = Join-Path $ProjectRoot "build\pyinstaller-work"
$SpecRoot = Join-Path $ProjectRoot "build\spec"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment is missing. Run .\setup.ps1 first."
}
if (Test-Path -LiteralPath $ReleaseRoot) {
    throw "Release directory already exists: $ReleaseRoot"
}

New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
New-Item -ItemType Directory -Path $PyInstallerDist -Force | Out-Null
New-Item -ItemType Directory -Path $PyInstallerWork -Force | Out-Null
New-Item -ItemType Directory -Path $SpecRoot -Force | Out-Null

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name AndroidPerfLab `
        --icon "$ProjectRoot\assets\android-perf-lab.ico" `
        --distpath $PyInstallerDist `
        --workpath $PyInstallerWork `
        --specpath $SpecRoot `
        --add-data "$ProjectRoot\static;static" `
        --collect-all webview `
        --collect-all perfetto `
        --hidden-import uvicorn.logging `
        --hidden-import uvicorn.loops.auto `
        --hidden-import uvicorn.loops.asyncio `
        --hidden-import uvicorn.protocols.http.auto `
        --hidden-import uvicorn.protocols.http.h11_impl `
        --hidden-import uvicorn.protocols.websockets.auto `
        --hidden-import uvicorn.lifespan.on `
        "$ProjectRoot\desktop_launcher.py"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with code $LASTEXITCODE"
    }

    Copy-Item -Path "$PyInstallerDist\AndroidPerfLab\*" -Destination $ReleaseRoot -Recurse

    $RuntimeRoot = Join-Path $ReleaseRoot "runtime"
    $PlatformToolsTarget = Join-Path $RuntimeRoot "platform-tools"
    $ConfigTarget = Join-Path $RuntimeRoot "configs"
    $ApkTarget = Join-Path $ReleaseRoot "apk"
    New-Item -ItemType Directory -Path $PlatformToolsTarget,$ConfigTarget,$ApkTarget -Force | Out-Null

    foreach ($name in @("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt")) {
        Copy-Item -LiteralPath "$PerfettoTools\.bin\platform-tools\$name" -Destination $PlatformToolsTarget
    }
    Copy-Item -LiteralPath "$PerfettoTools\tools\trace_processor_shell\windows-amd64.exe" -Destination "$RuntimeRoot\trace_processor_shell.exe"
    Copy-Item -LiteralPath "$PerfettoTools\configs\02_jank_frame.pbtx" -Destination $ConfigTarget
    Copy-Item -LiteralPath "$ProjectRoot\dist\PerfLabOverlay-v0.2.5-debug.apk" -Destination "$ApkTarget\PerfLabOverlay.apk"
    Copy-Item -LiteralPath "$PerfettoTools\LICENSE" -Destination "$ReleaseRoot\PERFETTO-TOOLS-LICENSE.txt"
    Copy-Item -LiteralPath "$ProjectRoot\CLIENT-README.md" -Destination $ReleaseRoot
}
finally {
    Pop-Location
}

$size = (Get-ChildItem -LiteralPath $ReleaseRoot -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host "Portable client built: $ReleaseRoot"
Write-Host ("Size: {0:N1} MB" -f ($size / 1MB))
