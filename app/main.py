from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db
from .adb import AdbError, ensure_reverse, list_devices, list_packages
from .collector import SessionBusyError, manager
from .config import REPORT_DIR, STATIC_DIR, ensure_runtime_paths


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_paths()
    db.init_db()
    yield


REPORT_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Android Perf Lab", version="0.3.9", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=REPORT_DIR), name="reports")


class StartSessionRequest(BaseModel):
    serial: str = Field(min_length=1, max_length=128)
    package_name: str = Field(min_length=3, max_length=255)
    duration: int = Field(default=60, ge=5, le=3600)

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            raise ValueError("设备序列号格式无效")
        return value

    @field_validator("package_name")
    @classmethod
    def validate_package(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.]+", value):
            raise ValueError("包名格式无效")
        return value


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.9"}


@app.get("/api/devices")
def devices() -> dict[str, object]:
    try:
        return {"devices": list_devices()}
    except AdbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/packages")
def packages(serial: str = Query(min_length=1, max_length=128)) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", serial):
        raise HTTPException(status_code=400, detail="设备序列号格式无效")
    try:
        return {"packages": list_packages(serial)}
    except AdbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/sessions")
def sessions() -> dict[str, object]:
    return {"sessions": db.list_sessions()}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict[str, object]:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="任务不存在")
    session["samples"] = db.get_samples(session_id)
    session["fps_samples"] = db.get_fps_samples(session_id)
    session["live"] = manager.live_snapshot(session_id)
    if session.get("report_path"):
        session["report_url"] = f"/reports/{Path(session['report_path']).name}"
    return session


@app.post("/api/sessions", status_code=201)
def start_session(request: StartSessionRequest) -> dict[str, object]:
    try:
        ensure_reverse(request.serial, 8765)
        return manager.start(request.serial, request.package_name, request.duration)
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, AdbError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/stop")
def stop_session(session_id: str) -> dict[str, object]:
    try:
        return manager.stop(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


def _overlay_payload() -> dict[str, object]:
    sessions = db.list_sessions(limit=1)
    if not sessions:
        return {
            "status": "idle",
            "status_text": "等待测试任务",
            "fps": None,
            "elapsed_seconds": 0,
        }
    session = sessions[0]
    latest = db.get_latest_sample(session["id"]) or {}
    live = manager.live_snapshot(session["id"])
    frame = (session.get("result") or {}).get("frame") or {}
    status_text = {
        "starting": "准备采集",
        "capturing": "正在采集",
        "stopping": "正在停止",
        "analyzing": "正在计算FPS",
        "completed": "任务已完成",
        "failed": "任务失败",
    }.get(session["status"], session["status"])
    capture_active = session["status"] in {"starting", "capturing", "stopping"}
    started_monotonic = live.get("started_monotonic")
    elapsed_seconds = latest.get("elapsed_seconds", 0)
    if capture_active and isinstance(started_monotonic, (int, float)):
        actual_elapsed = max(0.0, time.monotonic() - started_monotonic)
        elapsed_seconds = round(
            actual_elapsed
            if session.get("stop_requested")
            else min(actual_elapsed, session["requested_duration"]),
            3,
        )
    elif session["status"] == "analyzing":
        elapsed_seconds = live.get("capture_elapsed_seconds", elapsed_seconds)
    elif session["status"] == "completed" and not session.get("stop_requested"):
        elapsed_seconds = session["requested_duration"]
    return {
        "session_id": session["id"],
        "status": session["status"],
        "status_text": status_text,
        "package_name": session["package_name"],
        "requested_duration": session["requested_duration"],
        "elapsed_seconds": elapsed_seconds,
        "fps": live.get("realtime_fps", latest.get("realtime_fps"))
        if capture_active
        else frame.get("active_average_fps", frame.get("average_fps")),
        "realtime_fps": live.get("realtime_fps", latest.get("realtime_fps")),
        "fps_window_seconds": live.get("fps_window_seconds", 1.0),
        "average_fps": live.get("running_average_fps")
        if capture_active
        else frame.get("average_fps"),
        "fps_sample_token": live.get("updated_monotonic"),
        "presented_frames": frame.get("presented_frames"),
        "system_cpu_percent": live.get("system_cpu_percent", latest.get("system_cpu_percent")),
        "app_cpu_percent": live.get("app_cpu_percent", latest.get("app_cpu_percent")),
        "app_cpu_normalized_percent": live.get(
            "app_cpu_normalized_percent",
            latest.get("app_cpu_normalized_percent"),
        ),
        "gpu_usage_percent": live.get(
            "gpu_usage_percent", latest.get("gpu_usage_percent")
        ),
        "gpu_usage_source": live.get(
            "gpu_usage_source", latest.get("gpu_usage_source")
        ),
        "gpu_sample_status": live.get(
            "gpu_sample_status", latest.get("gpu_sample_status")
        ),
        "memory_mb": live.get("memory_mb", latest.get("memory_mb")),
        "memory_usage_percent": live.get(
            "memory_usage_percent", latest.get("memory_usage_percent")
        ),
        "memory_process_count": live.get(
            "memory_process_count", latest.get("memory_process_count")
        ),
        "cpu_temperature_c": live.get("cpu_temperature_c", latest.get("cpu_temperature_c")),
        "gpu_temperature_c": live.get("gpu_temperature_c", latest.get("gpu_temperature_c")),
        "battery_temperature_c": live.get(
            "battery_temperature_c", latest.get("battery_temperature_c")
        ),
        "battery_level_percent": live.get(
            "battery_level_percent", latest.get("battery_level_percent")
        ),
        "error": session.get("error"),
    }


@app.get("/api/overlay/stream")
async def overlay_stream() -> StreamingResponse:
    async def events():
        while True:
            payload = json.dumps(_overlay_payload(), ensure_ascii=False, separators=(",", ":"))
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
