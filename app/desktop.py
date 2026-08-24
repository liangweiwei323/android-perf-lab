from __future__ import annotations

import ctypes
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import uvicorn
import webview

from .config import (
    ADB_PATH,
    APP_HOME,
    DATA_DIR,
    OVERLAY_APK_PATH,
    REPORT_DIR,
    ensure_runtime_paths,
)
from .main import app


APP_NAME = "Android Perf Lab"
APP_VERSION = "0.3.9"
HOST = "127.0.0.1"
PORT = 8765
MUTEX_NAME = "Local\\AndroidPerfLab.Desktop.Client"


def _show_error(title: str, message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    else:
        print(f"{title}: {message}")


def _acquire_single_instance() -> Any | None:
    if os.name != "nt":
        return object()
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def _wait_for_service(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"http://{HOST}:{PORT}/api/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"本地服务启动超时：{last_error or '端口未响应'}")


class DesktopApi:
    def client_info(self) -> dict[str, Any]:
        return {
            "desktop": True,
            "version": APP_VERSION,
            "data_dir": str(DATA_DIR),
            "overlay_apk_available": OVERLAY_APK_PATH.is_file(),
        }

    def open_reports_folder(self) -> dict[str, Any]:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(REPORT_DIR)  # type: ignore[attr-defined]
        return {"ok": True, "message": "已打开报告目录"}

    def open_data_folder(self) -> dict[str, Any]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(DATA_DIR)  # type: ignore[attr-defined]
        return {"ok": True, "message": "已打开数据目录"}

    def install_overlay(self, serial: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", serial or ""):
            return {"ok": False, "message": "请先选择有效的ADB设备"}
        if not OVERLAY_APK_PATH.is_file():
            return {
                "ok": False,
                "message": f"悬浮窗APK不存在：{OVERLAY_APK_PATH}",
            }
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        command = [str(ADB_PATH), "-s", serial, "install", "-r", str(OVERLAY_APK_PATH)]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=creationflags,
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()
        if completed.returncode != 0 or "Success" not in output:
            return {"ok": False, "message": output or "APK安装失败"}
        subprocess.run(
            [str(ADB_PATH), "-s", serial, "reverse", "tcp:8765", "tcp:8765"],
            capture_output=True,
            timeout=15,
            creationflags=creationflags,
        )
        subprocess.run(
            [
                str(ADB_PATH),
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-n",
                "com.codex.androidperflab.overlay/.MainActivity",
            ],
            capture_output=True,
            timeout=15,
            creationflags=creationflags,
        )
        return {
            "ok": True,
            "message": "悬浮窗已安装并打开，请在手机上授予悬浮窗权限。",
        }


def _configure_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(DATA_DIR / "client.log", encoding="utf-8"),
        ],
    )


def main() -> None:
    mutex = _acquire_single_instance()
    if mutex is None:
        _show_error(APP_NAME, "Android Perf Lab 已经在运行。")
        return
    server: uvicorn.Server | None = None
    server_thread: threading.Thread | None = None
    try:
        _configure_logging()
        ensure_runtime_paths()
        config = uvicorn.Config(
            app,
            host=HOST,
            port=PORT,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(
            target=server.run,
            name="android-perf-lab-server",
            daemon=True,
        )
        server_thread.start()
        _wait_for_service()
        window = webview.create_window(
            f"{APP_NAME}  v{APP_VERSION}",
            f"http://{HOST}:{PORT}",
            js_api=DesktopApi(),
            width=1380,
            height=900,
            min_size=(1060, 700),
            background_color="#07111d",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("无法创建客户端窗口")

        def stop_server() -> None:
            if server is not None:
                server.should_exit = True

        window.events.closed += stop_server
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(APP_HOME / "webview-data"),
        )
    except Exception as exc:
        logging.exception("Desktop client failed")
        _show_error(APP_NAME, f"客户端启动失败：\n{exc}")
    finally:
        if server is not None:
            server.should_exit = True
        if server_thread is not None and server_thread.is_alive():
            server_thread.join(timeout=5)
        if os.name == "nt" and mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
