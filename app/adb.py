from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ADB_PATH


class AdbError(RuntimeError):
    pass


def run_adb(
    args: list[str],
    *,
    serial: str | None = None,
    timeout: float = 20,
    check: bool = True,
) -> str:
    command = [str(ADB_PATH)]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"ADB命令超时：{' '.join(args)}") from exc
    except OSError as exc:
        raise AdbError(f"无法启动ADB：{exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "未知错误").strip()
        raise AdbError(detail)
    return result.stdout.replace("\r\n", "\n")


def list_devices() -> list[dict[str, Any]]:
    output = run_adb(["devices", "-l"])
    devices: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        details = {}
        for field in parts[2:]:
            if ":" in field:
                key, value = field.split(":", 1)
                details[key] = value
        device = {
            "serial": serial,
            "state": state,
            "model": details.get("model", ""),
            "product": details.get("product", ""),
            "device": details.get("device", ""),
        }
        if state == "device":
            props = get_device_properties(serial)
            device.update(props)
        devices.append(device)
    return devices


def get_device_properties(serial: str) -> dict[str, str]:
    command = (
        "getprop ro.product.manufacturer; "
        "getprop ro.product.model; "
        "getprop ro.build.version.release; "
        "getprop ro.build.version.sdk; "
        "getprop ro.product.cpu.abi; "
        "getprop ro.soc.model"
    )
    output = run_adb(["shell", command], serial=serial)
    values = output.splitlines()
    values += [""] * (6 - len(values))
    return {
        "manufacturer": values[0].strip(),
        "model": values[1].strip(),
        "android_version": values[2].strip(),
        "api_level": values[3].strip(),
        "abi": values[4].strip(),
        "soc": values[5].strip(),
    }


def list_packages(serial: str) -> list[dict[str, str]]:
    output = run_adb(["shell", "pm", "list", "packages", "-3"], serial=serial)
    packages = sorted(
        line.removeprefix("package:").strip()
        for line in output.splitlines()
        if line.startswith("package:")
    )
    return [{"package_name": package, "label": package} for package in packages]


def package_exists(serial: str, package_name: str) -> bool:
    output = run_adb(
        ["shell", "pm", "path", package_name],
        serial=serial,
        check=False,
    )
    return output.strip().startswith("package:")


def read_package_uid(serial: str, package_name: str) -> int | None:
    output = run_adb(
        ["shell", "cmd", "package", "list", "packages", "-U", package_name],
        serial=serial,
        timeout=10,
        check=False,
    )
    match = re.search(
        rf"^package:{re.escape(package_name)}\s+uid:(\d+)\s*$",
        output,
        re.MULTILINE,
    )
    return int(match.group(1)) if match else None


def ensure_reverse(serial: str, port: int = 8765) -> None:
    run_adb(
        ["reverse", f"tcp:{port}", f"tcp:{port}"],
        serial=serial,
        timeout=10,
    )


@dataclass
class CpuSnapshot:
    total: int
    idle: int
    app: int
    core_count: int


def read_cpu_snapshot(
    serial: str,
    package_name: str,
    app_uid: int | None = None,
) -> CpuSnapshot | None:
    if app_uid is not None:
        pid_query = (
            "ps -A -o PID,UID | "
            f"awk -v target={int(app_uid)} '$2 == target {{print $1}}'"
        )
    else:
        package_pattern = "^" + re.escape(package_name)
        pid_query = (
            "ps -A -o PID,NAME | "
            f"awk '$2 ~ /{package_pattern}/ {{print $1}}'"
        )
    remote = (
        "head -n 1 /proc/stat; "
        f"pids=$({pid_query}); "
        "echo PIDS:$pids; "
        "for p in $pids; do cat /proc/$p/stat 2>/dev/null; done; "
        "echo CORES:$(grep -c '^cpu[0-9]' /proc/stat)"
    )
    output = run_adb(["shell", remote], serial=serial, timeout=10)
    lines = output.splitlines()
    cpu_line = next((line for line in lines if line.startswith("cpu ")), None)
    if not cpu_line:
        return None
    values = [int(value) for value in cpu_line.split()[1:] if value.isdigit()]
    if len(values) < 5:
        return None
    # Match SoloX's Android CPU denominator: user + nice + system + idle +
    # iowait + irq + softirq. SoloX treats only the idle field as idle, so
    # iowait remains part of Total CPU usage and steal is excluded.
    total = sum(values[:7])
    idle = values[3]
    app_ticks = 0
    for line in lines:
        if not re.match(r"^\d+ \(.+\) ", line):
            continue
        closing = line.rfind(")")
        suffix = line[closing + 2 :].split()
        if len(suffix) > 14:
            try:
                # /proc/<pid>/stat fields 14-17: utime, stime, cutime, cstime.
                # SoloX includes all four fields in its application CPU time.
                app_ticks += sum(int(value) for value in suffix[11:15])
            except ValueError:
                continue
    core_line = next((line for line in lines if line.startswith("CORES:")), "CORES:1")
    try:
        cores = max(1, int(core_line.split(":", 1)[1]))
    except ValueError:
        cores = 1
    return CpuSnapshot(total=total, idle=idle, app=app_ticks, core_count=cores)


def cpu_percentages(
    previous: CpuSnapshot | None, current: CpuSnapshot | None
) -> tuple[float | None, float | None]:
    metrics = cpu_usage_metrics(previous, current)
    return metrics["system_normalized"], metrics["app_non_normalized"]


def cpu_usage_metrics(
    previous: CpuSnapshot | None, current: CpuSnapshot | None
) -> dict[str, float | None]:
    empty = {
        "system_normalized": None,
        "system_non_normalized": None,
        "app_normalized": None,
        "app_non_normalized": None,
    }
    if previous is None or current is None:
        return empty
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    app_delta = current.app - previous.app
    if total_delta <= 0:
        return empty
    system = max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))
    app = max(0.0, app_delta * current.core_count * 100.0 / total_delta)
    # A UID can gain or lose processes between the two ADB snapshots. That can
    # briefly make the aggregate lifetime ticks exceed the measurement window.
    # Such a value is a sampling artefact: an app cannot consume more CPU time
    # than all logical cores combined during the same interval.
    app = min(current.core_count * 100.0, app)
    return {
        "system_normalized": round(system, 2),
        "system_non_normalized": round(system * current.core_count, 2),
        "app_normalized": round(app / current.core_count, 2),
        "app_non_normalized": round(app, 2),
    }


def read_memory_mb(serial: str, package_name: str) -> float | None:
    output = run_adb(
        ["shell", "dumpsys", "meminfo", package_name],
        serial=serial,
        timeout=15,
        check=False,
    )
    patterns = (
        r"TOTAL PSS:\s*(\d+)",
        r"^\s*TOTAL\s+(\d+)\s+",
    )
    for pattern in patterns:
        match = re.search(pattern, output, re.MULTILINE)
        if match:
            return round(int(match.group(1)) / 1024.0, 2)
    return None


def parse_uid_memory_output(output: str) -> dict[str, Any]:
    mem_total_match = re.search(r"^MEMTOTAL:(\d+)\s*$", output, re.MULTILINE)
    mem_total_kb = int(mem_total_match.group(1)) if mem_total_match else 0
    current_pid: int | None = None
    current_name = ""
    processes: list[dict[str, Any]] = []
    total_pss_kb = 0
    total_swap_pss_kb = 0
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("PROC:"):
            parts = line.split(":", 2)
            try:
                current_pid = int(parts[1])
            except (IndexError, ValueError):
                current_pid = None
            current_name = parts[2] if len(parts) > 2 else ""
            continue
        if current_pid is None or "TOTAL PSS:" not in line:
            continue
        pss_match = re.search(r"TOTAL PSS:\s*(\d+)", line)
        swap_match = re.search(r"TOTAL SWAP(?: PSS| \(KB\))?:\s*(\d+)", line)
        if not pss_match:
            continue
        pss_kb = int(pss_match.group(1))
        swap_pss_kb = int(swap_match.group(1)) if swap_match else 0
        total_pss_kb += pss_kb
        total_swap_pss_kb += swap_pss_kb
        processes.append(
            {
                "pid": current_pid,
                "name": current_name,
                "pss_mb": round(pss_kb / 1024.0, 2),
                "swap_pss_mb": round(swap_pss_kb / 1024.0, 2),
            }
        )
        current_pid = None
        current_name = ""
    processes.sort(key=lambda row: row["pss_mb"], reverse=True)
    memory_mb = round(total_pss_kb / 1024.0, 2) if processes else None
    usage_percent = (
        round(total_pss_kb * 100.0 / mem_total_kb, 2)
        if processes and mem_total_kb > 0
        else None
    )
    return {
        "memory_mb": memory_mb,
        "memory_usage_percent": usage_percent,
        "memory_swap_mb": round(total_swap_pss_kb / 1024.0, 2)
        if processes
        else None,
        "memory_process_count": len(processes),
        "memory_processes": processes,
        "device_memory_mb": round(mem_total_kb / 1024.0, 2)
        if mem_total_kb > 0
        else None,
    }


def read_uid_memory(serial: str, app_uid: int) -> dict[str, Any]:
    remote = (
        "echo MEMTOTAL:$(awk '/^MemTotal:/ {print $2}' /proc/meminfo); "
        "pids=$(ps -A -o PID,UID | "
        f"awk -v target={int(app_uid)} '$2 == target {{print $1}}'); "
        "for p in $pids; do "
        "name=$(cat /proc/$p/comm 2>/dev/null); "
        'echo "PROC:$p:$name"; '
        'dumpsys meminfo --local -S "$p" 2>/dev/null | '
        'grep -m 1 "TOTAL PSS:"; '
        "done"
    )
    output = run_adb(
        ["shell", remote],
        serial=serial,
        timeout=30,
        check=False,
    )
    return parse_uid_memory_output(output)


def _max_temperature(text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)} temperatures:\s*\[([^\]]*)\]", text)
    if not match:
        return None
    values = []
    for raw in match.group(1).split(","):
        try:
            value = float(raw.strip())
        except ValueError:
            continue
        if -50 < value < 200:
            values.append(value)
    return round(max(values), 1) if values else None


def read_power_and_thermal(serial: str) -> dict[str, float | None]:
    output = run_adb(
        ["shell", "dumpsys battery; echo __THERMAL__; dumpsys hardware_properties"],
        serial=serial,
        timeout=15,
        check=False,
    )
    battery_text, _, thermal_text = output.partition("__THERMAL__")

    def field(name: str) -> float | None:
        match = re.search(rf"^\s*{re.escape(name)}:\s*(-?\d+(?:\.\d+)?)", battery_text, re.MULTILINE)
        return float(match.group(1)) if match else None

    level = field("level")
    voltage_mv = field("voltage")
    battery_temp_tenths = field("temperature")
    hardware_battery_temp = _max_temperature(thermal_text, "Battery")
    return {
        "cpu_temperature_c": _max_temperature(thermal_text, "CPU"),
        "gpu_temperature_c": _max_temperature(thermal_text, "GPU"),
        "battery_temperature_c": hardware_battery_temp
        if hardware_battery_temp is not None
        else (round(battery_temp_tenths / 10.0, 1) if battery_temp_tenths is not None else None),
        "battery_level_percent": level,
        "battery_voltage_v": round(voltage_mv / 1000.0, 3) if voltage_mv is not None else None,
    }


def parse_kgsl_gpu_busy(output: str) -> dict[str, Any]:
    """Parse Qualcomm KGSL's busy/total microsecond sampling window.

    On the tested SM8550 kernel, reading ``gpubusy`` consumes the current
    driver window. A 0/0 window therefore means either that the GPU stayed
    powered down or another monitor consumed the counter first. Preserve that
    distinction in the status instead of silently presenting it as a verified
    zero-load sample.
    """
    values = re.findall(r"\d+", output)
    if len(values) < 2:
        return {
            "gpu_usage_percent": None,
            "gpu_usage_source": None,
            "gpu_sample_window_us": None,
            "gpu_sample_status": "unavailable",
        }
    busy_us, total_us = int(values[0]), int(values[1])
    if total_us == 0:
        return {
            "gpu_usage_percent": 0.0 if busy_us == 0 else None,
            "gpu_usage_source": "qualcomm_kgsl_gpubusy",
            "gpu_sample_window_us": 0,
            "gpu_sample_status": "idle_or_counter_consumed"
            if busy_us == 0
            else "invalid",
        }
    if busy_us > total_us:
        return {
            "gpu_usage_percent": None,
            "gpu_usage_source": "qualcomm_kgsl_gpubusy",
            "gpu_sample_window_us": total_us,
            "gpu_sample_status": "invalid",
        }
    return {
        "gpu_usage_percent": round(busy_us * 100.0 / total_us, 2),
        "gpu_usage_source": "qualcomm_kgsl_gpubusy",
        "gpu_sample_window_us": total_us,
        "gpu_sample_status": "valid",
    }


def read_gpu_usage(serial: str) -> dict[str, Any]:
    """Read a validated GPU utilization source, or return explicit N/A.

    Do not guess across vendor-specific nodes. Qualcomm KGSL is currently the
    only implemented source because its busy/total semantics were verified on
    the connected SM8550 device and against the upstream KGSL driver.
    """
    path = "/sys/class/kgsl/kgsl-3d0/gpubusy"
    try:
        output = run_adb(
            ["shell", f"if [ -r {path} ]; then cat {path}; fi"],
            serial=serial,
            timeout=10,
            check=False,
        )
    except AdbError:
        output = ""
    return parse_kgsl_gpu_busy(output)


def start_realtime_fps(serial: str) -> None:
    run_adb(
        ["shell", "dumpsys SurfaceFlinger --timestats -enable"],
        serial=serial,
        timeout=10,
        check=False,
    )
    run_adb(
        ["shell", "dumpsys SurfaceFlinger --timestats -clear"],
        serial=serial,
        timeout=10,
        check=False,
    )


def stop_realtime_fps(serial: str) -> None:
    run_adb(
        ["shell", "dumpsys SurfaceFlinger --timestats -disable"],
        serial=serial,
        timeout=10,
        check=False,
    )


def parse_timestats_fps(output: str, package_name: str) -> float | None:
    candidates: list[tuple[int, int, float]] = []
    current_layer = ""
    current_frames = 0
    global_total_frames: int | None = None
    global_p2p_ms: float | None = None
    display_refresh_rate: float | None = None
    stats_start: float | None = None
    stats_end: float | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("statsStart ="):
            try:
                stats_start = float(line.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("statsEnd ="):
            try:
                stats_end = float(line.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("totalP2PTime =") and current_layer == "":
            match = re.search(r"([0-9.]+)\s*ms", line)
            if match:
                global_p2p_ms = float(match.group(1))
        elif line.startswith("displayRefreshRate =") and display_refresh_rate is None:
            match = re.search(r"([0-9.]+)\s*fps", line)
            if match:
                display_refresh_rate = float(match.group(1))
        elif line.startswith("layerName ="):
            current_layer = line.split("=", 1)[1].strip()
            current_frames = 0
        elif line.startswith("totalFrames ="):
            try:
                current_frames = int(line.split("=", 1)[1].strip())
                if current_layer == "" and global_total_frames is None:
                    global_total_frames = current_frames
            except ValueError:
                current_frames = 0
        elif line.startswith("averageFPS ="):
            try:
                fps = float(line.split("=", 1)[1].strip())
            except ValueError:
                continue
            if package_name.lower() not in current_layer.lower() or current_frames <= 0:
                continue
            priority = 2 if ("surfaceview" in current_layer.lower() or "pcengine" in current_layer.lower()) else 1
            candidates.append((priority, current_frames, fps))
    if candidates:
        _, _, fps = max(candidates, key=lambda item: (item[0], item[1]))
        if display_refresh_rate is not None and display_refresh_rate > 0:
            fps = min(fps, display_refresh_rate)
        return round(max(0.0, fps), 2)
    if global_total_frames is None or global_total_frames <= 0:
        return None
    duration_seconds = 0.0
    if stats_start is not None and stats_end is not None and stats_end > stats_start:
        duration_seconds = stats_end - stats_start
    elif global_p2p_ms is not None and global_p2p_ms > 0:
        duration_seconds = global_p2p_ms / 1000.0
    if duration_seconds <= 0:
        return None
    fps = global_total_frames / duration_seconds
    if display_refresh_rate is not None and display_refresh_rate > 0:
        fps = min(fps, display_refresh_rate)
    return round(fps, 2)


def read_realtime_fps(serial: str, package_name: str) -> float | None:
    output = run_adb(
        [
            "shell",
            "dumpsys SurfaceFlinger --timestats -dump; "
            "dumpsys SurfaceFlinger --timestats -clear",
        ],
        serial=serial,
        timeout=15,
        check=False,
    )
    fps = parse_timestats_fps(output, package_name)
    return fps
