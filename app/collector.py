from __future__ import annotations

import threading
import time
import uuid
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db
from .adb import (
    cpu_usage_metrics,
    package_exists,
    read_cpu_snapshot,
    read_gpu_usage,
    read_memory_mb,
    read_package_uid,
    read_power_and_thermal,
    read_realtime_fps,
    read_uid_memory,
    start_realtime_fps,
    stop_realtime_fps,
)
from .config import (
    JANK_CONFIG,
    TRACE_DIR,
)
from .capture import capture_trace
from .evaluation import evaluate_frame_performance
from .perfetto import analyze_trace, apply_perfdog_fps_points
from .report import generate_report, summarize_samples


class SessionBusyError(RuntimeError):
    pass


class SessionManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._live_metrics: dict[str, dict[str, Any]] = {}

    def start(self, serial: str, package_name: str, duration: int) -> dict[str, Any]:
        with self._lock:
            active = [
                session
                for session in db.list_sessions()
                if session["status"] in {"starting", "capturing", "stopping", "analyzing"}
            ]
            if active:
                raise SessionBusyError(f"已有任务正在运行：{active[0]['id']}")
            if not package_exists(serial, package_name):
                raise RuntimeError(f"设备上不存在应用：{package_name}")
            app_uid = read_package_uid(serial, package_name)
            now = datetime.now(timezone.utc)
            session_id = now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            trace_path = TRACE_DIR / f"{session_id}.perfetto-trace"
            record = {
                "id": session_id,
                "serial": serial,
                "package_name": package_name,
                "app_name": package_name,
                "requested_duration": duration,
                "status": "starting",
                "started_at": now.isoformat(),
                "trace_path": str(trace_path),
                "app_uid": app_uid,
            }
            db.create_session(record)
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_session,
                args=(record, stop_event),
                name=f"capture-{session_id}",
                daemon=True,
            )
            self._threads[session_id] = thread
            self._stop_events[session_id] = stop_event
            self._live_metrics[session_id] = {
                "realtime_fps": None,
                "running_average_fps": None,
                "fps_window_seconds": 1.0,
                "updated_monotonic": None,
                "started_monotonic": time.monotonic(),
                "app_uid": app_uid,
            }
            thread.start()
            return db.get_session(session_id) or record

    def live_snapshot(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._live_metrics.get(session_id, {}))

    def stop(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = db.get_session(session_id)
            if not session:
                raise KeyError(session_id)
            if session["status"] not in {"starting", "capturing"}:
                return session
            db.update_session(session_id, status="stopping", stop_requested=1)
            event = self._stop_events.get(session_id)
            if event:
                event.set()
            return db.get_session(session_id) or session

    def _run_session(self, record: dict[str, Any], stop_event: threading.Event) -> None:
        session_id = record["id"]
        sampler = threading.Thread(
            target=self._sample_loop,
            args=(record, stop_event),
            name=f"sampler-{session_id}",
            daemon=True,
        )
        fps_sampler = threading.Thread(
            target=self._fps_loop,
            args=(record, stop_event),
            name=f"fps-{session_id}",
            daemon=True,
        )
        memory_sampler = threading.Thread(
            target=self._memory_loop,
            args=(record, stop_event),
            name=f"memory-{session_id}",
            daemon=True,
        )
        try:
            db.update_session(session_id, status="capturing")
            sampler.start()
            fps_sampler.start()
            memory_sampler.start()
            trace_path = Path(record["trace_path"])
            config_path = TRACE_DIR / f"{session_id}.pbtx"
            config_text = JANK_CONFIG.read_text(encoding="utf-8")
            duration_ms = record["requested_duration"] * 1000
            config_text, count = re.subn(
                r"^\s*duration_ms\s*:\s*\d+\s*$",
                f"duration_ms: {duration_ms}",
                config_text,
                count=1,
                flags=re.MULTILINE,
            )
            if count == 0:
                config_text = f"duration_ms: {duration_ms}\n{config_text}"
            config_path.write_text(config_text, encoding="utf-8", newline="\n")
            try:
                output = capture_trace(
                    record["serial"],
                    config_path,
                    trace_path,
                    stop_event,
                    record["requested_duration"],
                )
            finally:
                stop_event.set()
                sampler.join(timeout=20)
                fps_sampler.join(timeout=20)
                memory_sampler.join(timeout=20)
                try:
                    config_path.unlink(missing_ok=True)
                except OSError:
                    pass

            current_session = db.get_session(session_id) or record
            with self._lock:
                live = self._live_metrics.get(session_id)
                if live is not None:
                    actual_elapsed = max(
                        0.0,
                        time.monotonic() - live["started_monotonic"],
                    )
                    live["capture_elapsed_seconds"] = round(
                        actual_elapsed
                        if current_session.get("stop_requested")
                        else min(actual_elapsed, record["requested_duration"]),
                        3,
                    )
            db.update_session(session_id, status="analyzing")
            frame_result = analyze_trace(trace_path, record["package_name"])
            samples = db.get_samples(session_id)
            fps_samples = db.get_fps_samples(session_id)
            fps_values = [row["fps"] for row in fps_samples]
            fps_duration = (
                fps_samples[-1]["elapsed_seconds"] if fps_samples else 0.0
            )
            frame_result = apply_perfdog_fps_points(
                frame_result,
                fps_values,
                fps_duration or frame_result.get("trace_duration_seconds", 0.0),
            )
            result = {
                "frame": frame_result,
                "evaluation": evaluate_frame_performance(frame_result, target_fps=60.0),
                "sample_summary": summarize_samples(samples),
                "metadata": {
                    "capture_output_tail": output[-1000:].strip(),
                    "sample_count": len(samples),
                    "tool_version": "0.3.9",
                    "metric_profile": "PerfDog-public-v1",
                    "memory_scope": "uid_total_pss"
                    if record.get("app_uid") is not None
                    else "package_main_process_pss",
                    "app_uid": record.get("app_uid"),
                    "gpu_usage_source": self.live_snapshot(session_id).get(
                        "gpu_usage_source"
                    ),
                    "gpu_counter_semantics": (
                        "Qualcomm KGSL gpubusy busy/total window; reading can "
                        "consume the window, so concurrent GPU monitors may interfere."
                    )
                    if self.live_snapshot(session_id).get("gpu_usage_source")
                    == "qualcomm_kgsl_gpubusy"
                    else None,
                    "memory_process_count": self.live_snapshot(session_id).get(
                        "memory_process_count"
                    ),
                    "memory_processes": self.live_snapshot(session_id).get(
                        "memory_processes", []
                    ),
                },
            }
            session = db.get_session(session_id) or record
            session["trace_path"] = str(trace_path)
            report_path = generate_report(session, samples, result)
            db.update_session(
                session_id,
                status="completed",
                finished_at=db.utc_now(),
                result_json=result,
                report_path=str(report_path),
                error=None,
            )
        except Exception as exc:
            stop_event.set()
            if sampler.is_alive():
                sampler.join(timeout=5)
            if fps_sampler.is_alive():
                fps_sampler.join(timeout=5)
            if memory_sampler.is_alive():
                memory_sampler.join(timeout=5)
            db.update_session(
                session_id,
                status="failed",
                finished_at=db.utc_now(),
                error=str(exc),
            )
        finally:
            with self._lock:
                self._stop_events.pop(session_id, None)
                self._threads.pop(session_id, None)
                self._live_metrics.pop(session_id, None)

    def _sample_loop(self, record: dict[str, Any], stop_event: threading.Event) -> None:
        session_id = record["id"]
        serial = record["serial"]
        package_name = record["package_name"]
        app_uid = record.get("app_uid")
        started = time.monotonic()
        previous_cpu = read_cpu_snapshot(serial, package_name, app_uid)
        # Prime/reset the Qualcomm KGSL window so the first recorded value does
        # not contain GPU activity from before this test session.
        read_gpu_usage(serial)
        next_sample_at = time.monotonic() + 1.0
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="adb-metric") as executor:
            while True:
                wait_seconds = max(0.0, next_sample_at - time.monotonic())
                if stop_event.wait(wait_seconds):
                    break
                try:
                    cpu_future = executor.submit(
                        read_cpu_snapshot,
                        serial,
                        package_name,
                        app_uid,
                    )
                    power_future = executor.submit(read_power_and_thermal, serial)
                    gpu_future = executor.submit(read_gpu_usage, serial)
                    current_cpu = cpu_future.result()
                    cpu = cpu_usage_metrics(previous_cpu, current_cpu)
                    previous_cpu = current_cpu
                    power = power_future.result()
                    gpu = gpu_future.result()
                    live = self.live_snapshot(session_id)
                    realtime_fps = live.get("realtime_fps")
                    sample = {
                        "captured_at": db.utc_now(),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "realtime_fps": realtime_fps,
                        "system_cpu_percent": cpu["system_normalized"],
                        "system_cpu_non_normalized_percent": cpu[
                            "system_non_normalized"
                        ],
                        "app_cpu_percent": cpu["app_non_normalized"],
                        "app_cpu_normalized_percent": cpu["app_normalized"],
                        "memory_mb": live.get("memory_mb"),
                        "memory_usage_percent": live.get("memory_usage_percent"),
                        "memory_process_count": live.get("memory_process_count"),
                        **gpu,
                        **power,
                    }
                    db.insert_sample(session_id, sample)
                    with self._lock:
                        if session_id in self._live_metrics:
                            self._live_metrics[session_id].update(sample)
                except Exception:
                    # A transient vendor/ADB metric failure must not abort the trace.
                    pass
                next_sample_at += 1.0
                if next_sample_at < time.monotonic():
                    next_sample_at = time.monotonic()

    def _memory_loop(self, record: dict[str, Any], stop_event: threading.Event) -> None:
        session_id = record["id"]
        serial = record["serial"]
        package_name = record["package_name"]
        app_uid = record.get("app_uid")
        while True:
            try:
                if app_uid is not None:
                    snapshot = read_uid_memory(serial, app_uid)
                else:
                    snapshot = {
                        "memory_mb": read_memory_mb(serial, package_name),
                        "memory_usage_percent": None,
                        "memory_swap_mb": None,
                        "memory_process_count": None,
                        "memory_processes": [],
                        "device_memory_mb": None,
                    }
                with self._lock:
                    if session_id in self._live_metrics:
                        self._live_metrics[session_id].update(snapshot)
            except Exception:
                # Keep the most recent valid PSS when a process exits mid-scan.
                pass
            if stop_event.wait(5.0):
                break

    def _fps_loop(self, record: dict[str, Any], stop_event: threading.Event) -> None:
        session_id = record["id"]
        serial = record["serial"]
        package_name = record["package_name"]
        started = time.monotonic()
        fps_sum = 0.0
        fps_count = 0
        try:
            start_realtime_fps(serial)
            # PerfDog's published FPS point is the average number of actual
            # screen refreshes in one second. Keep this window independent from
            # slower CPU/memory/thermal ADB calls.
            while not stop_event.wait(1.0):
                try:
                    fps = read_realtime_fps(serial, package_name)
                    if fps is not None:
                        fps_sum += fps
                        fps_count += 1
                    with self._lock:
                        if session_id in self._live_metrics:
                            self._live_metrics[session_id].update(
                                {
                                    "realtime_fps": fps,
                                    "running_average_fps": round(
                                        fps_sum / fps_count, 3
                                    ) if fps_count else None,
                                    "fps_window_seconds": 1.0,
                                    "updated_monotonic": time.monotonic(),
                                }
                            )
                    if fps is not None:
                        db.insert_fps_sample(
                            session_id,
                            {
                                "captured_at": db.utc_now(),
                                "elapsed_seconds": round(
                                    time.monotonic() - started, 3
                                ),
                                "fps": fps,
                            },
                        )
                except Exception:
                    continue
        finally:
            try:
                stop_realtime_fps(serial)
            except Exception:
                pass


manager = SessionManager()
