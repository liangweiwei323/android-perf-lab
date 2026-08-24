from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .config import ADB_PATH


class CaptureError(RuntimeError):
    pass


def _run_adb(
    serial: str,
    *args: str,
    input_text: str | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.run(
            [str(ADB_PATH), "-s", serial, *args],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"ADB命令超时：{' '.join(args[:3])}") from exc


def _device_process_running(serial: str, pid: str) -> bool:
    result = _run_adb(
        serial,
        "shell",
        f"if [ -d /proc/{pid} ]; then echo RUN; else echo TERM; fi",
        timeout=10,
    )
    if result.returncode != 0:
        raise CaptureError((result.stderr or result.stdout or "ADB连接中断").strip())
    return "RUN" in result.stdout.split()


def capture_trace(
    serial: str,
    config_path: Path,
    trace_path: Path,
    stop_event: threading.Event,
    duration_seconds: int,
) -> str:
    """Capture a device Perfetto trace without a visible helper console.

    Stopping only terminates the device-side producer. Pulling the finished trace
    is deliberately non-interruptible so an early stop cannot corrupt the file.
    """

    config_text = config_path.read_text(encoding="utf-8")
    remote_path = f"/data/misc/perfetto-traces/{trace_path.stem}.pftrace"
    started = _run_adb(
        serial,
        "shell",
        "perfetto",
        "--background",
        "--txt",
        "-o",
        remote_path,
        "-c",
        "-",
        input_text=config_text,
        timeout=30,
    )
    combined_start = (started.stdout + "\n" + started.stderr).strip()
    if started.returncode != 0:
        raise CaptureError(f"无法启动设备端Perfetto：{combined_start}")
    pid_match = re.search(r"(?m)^\s*(\d+)\s*$", started.stdout)
    if not pid_match:
        raise CaptureError(f"Perfetto未返回进程号：{combined_start}")
    pid = pid_match.group(1)
    messages = [f"device perfetto pid={pid}", combined_start]
    deadline = time.monotonic() + duration_seconds + 90
    stop_sent = False
    while True:
        if stop_event.is_set() and not stop_sent:
            stopped = _run_adb(serial, "shell", "kill", "-TERM", pid, timeout=15)
            messages.append((stopped.stdout + "\n" + stopped.stderr).strip())
            stop_sent = True
        if not _device_process_running(serial, pid):
            break
        if time.monotonic() >= deadline:
            _run_adb(serial, "shell", "kill", "-KILL", pid, timeout=15)
            raise CaptureError("设备端Perfetto超过预期时间仍未结束。")
        time.sleep(0.5)

    trace_path.parent.mkdir(parents=True, exist_ok=True)
    pulled = _run_adb(serial, "pull", remote_path, str(trace_path), timeout=180)
    pull_output = (pulled.stdout + "\n" + pulled.stderr).strip()
    messages.append(pull_output)
    if pulled.returncode != 0:
        raise CaptureError(
            f"Trace已在设备生成，但拉取失败；设备文件保留在 {remote_path}：{pull_output}"
        )
    _run_adb(serial, "shell", "rm", "-f", remote_path, timeout=15)
    if not trace_path.is_file() or trace_path.stat().st_size < 1024:
        raise CaptureError("采集结束但没有生成有效Trace文件。")
    return "\n".join(message for message in messages if message)
