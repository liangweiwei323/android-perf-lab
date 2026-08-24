from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_HOME = Path(sys.executable).resolve().parent if IS_FROZEN else SOURCE_ROOT
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()
PROJECT_ROOT = APP_HOME
DATA_DIR = Path(
    os.environ.get("ANDROID_PERF_LAB_DATA", str(APP_HOME / "data"))
).resolve()
TRACE_DIR = DATA_DIR / "traces"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "sessions.db"
STATIC_DIR = RESOURCE_ROOT / "static"

if IS_FROZEN:
    PERFETTO_TOOLS_ROOT = Path(
        os.environ.get("ANDROID_PERF_LAB_RUNTIME", str(APP_HOME / "runtime"))
    ).resolve()
    CAPTURE_SCRIPT = PERFETTO_TOOLS_ROOT / "capture.bat"
    CAPTURE_ENTRY = PERFETTO_TOOLS_ROOT / "perfetto_capture.py"
    CAPTURE_PYTHON = APP_HOME / "AndroidPerfLabCapture.exe"
    CAPTURE_HELPER = APP_HOME / "AndroidPerfLabCapture.exe"
    OFFICIAL_CAPTURE = PERFETTO_TOOLS_ROOT / "official" / "record_android_trace"
    JANK_CONFIG = PERFETTO_TOOLS_ROOT / "configs" / "02_jank_frame.pbtx"
    ADB_PATH = PERFETTO_TOOLS_ROOT / "platform-tools" / "adb.exe"
    TRACE_PROCESSOR_PATH = PERFETTO_TOOLS_ROOT / "trace_processor_shell.exe"
    OVERLAY_APK_PATH = APP_HOME / "apk" / "PerfLabOverlay.apk"
else:
    PERFETTO_TOOLS_ROOT = Path(
        os.environ.get(
            "ANDROID_PERF_LAB_PERFETTO_TOOLS", r"D:\codex\perfetto-tools"
        )
    ).resolve()
    CAPTURE_SCRIPT = PERFETTO_TOOLS_ROOT / "capture" / "capture.bat"
    CAPTURE_ENTRY = PERFETTO_TOOLS_ROOT / "capture" / "perfetto_capture.py"
    CAPTURE_PYTHON = PERFETTO_TOOLS_ROOT / ".venv" / "Scripts" / "python.exe"
    CAPTURE_HELPER = None
    OFFICIAL_CAPTURE = PERFETTO_TOOLS_ROOT / "official" / "record_android_trace"
    JANK_CONFIG = PERFETTO_TOOLS_ROOT / "configs" / "02_jank_frame.pbtx"
    ADB_PATH = PERFETTO_TOOLS_ROOT / ".bin" / "platform-tools" / "adb.exe"
    TRACE_PROCESSOR_PATH = (
        PERFETTO_TOOLS_ROOT
        / "tools"
        / "trace_processor_shell"
        / "windows-amd64.exe"
    )
    OVERLAY_APK_PATH = SOURCE_ROOT / "dist" / "PerfLabOverlay-v0.2.5-debug.apk"


def ensure_runtime_paths() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    required = [
        path
        for path in (
            JANK_CONFIG,
            ADB_PATH,
            TRACE_PROCESSOR_PATH,
        )
        if path is not None
    ]
    missing = [
        path
        for path in required
        if not path.is_file()
    ]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise RuntimeError(f"Perfetto Tools runtime is incomplete: {joined}")
