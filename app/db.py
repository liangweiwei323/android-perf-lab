from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                serial TEXT NOT NULL,
                package_name TEXT NOT NULL,
                app_name TEXT,
                requested_duration INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                trace_path TEXT,
                report_path TEXT,
                result_json TEXT,
                error TEXT,
                stop_requested INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL,
                realtime_fps REAL,
                system_cpu_percent REAL,
                system_cpu_non_normalized_percent REAL,
                app_cpu_percent REAL,
                app_cpu_normalized_percent REAL,
                gpu_usage_percent REAL,
                gpu_usage_source TEXT,
                gpu_sample_window_us INTEGER,
                gpu_sample_status TEXT,
                memory_mb REAL,
                memory_usage_percent REAL,
                memory_process_count INTEGER,
                cpu_temperature_c REAL,
                gpu_temperature_c REAL,
                battery_temperature_c REAL,
                battery_level_percent REAL,
                battery_voltage_v REAL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_samples_session
            ON samples(session_id, elapsed_seconds);

            CREATE TABLE IF NOT EXISTS fps_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL,
                fps REAL NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_fps_samples_session
            ON fps_samples(session_id, elapsed_seconds);
            """
        )
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(samples)").fetchall()
        }
        if "realtime_fps" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN realtime_fps REAL")
        if "system_cpu_non_normalized_percent" not in columns:
            db.execute(
                "ALTER TABLE samples ADD COLUMN system_cpu_non_normalized_percent REAL"
            )
        if "app_cpu_normalized_percent" not in columns:
            db.execute(
                "ALTER TABLE samples ADD COLUMN app_cpu_normalized_percent REAL"
            )
        if "gpu_usage_percent" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN gpu_usage_percent REAL")
        if "gpu_usage_source" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN gpu_usage_source TEXT")
        if "gpu_sample_window_us" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN gpu_sample_window_us INTEGER")
        if "gpu_sample_status" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN gpu_sample_status TEXT")
        if "memory_usage_percent" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN memory_usage_percent REAL")
        if "memory_process_count" not in columns:
            db.execute("ALTER TABLE samples ADD COLUMN memory_process_count INTEGER")


def create_session(record: dict[str, Any]) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO sessions (
                id, serial, package_name, app_name, requested_duration,
                status, started_at, trace_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["serial"],
                record["package_name"],
                record.get("app_name"),
                record["requested_duration"],
                record["status"],
                record["started_at"],
                record.get("trace_path"),
            ),
        )


def update_session(session_id: str, **fields: Any) -> None:
    allowed = {
        "status",
        "finished_at",
        "trace_path",
        "report_path",
        "result_json",
        "error",
        "stop_requested",
        "app_name",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return
    if "result_json" in values and not isinstance(values["result_json"], str):
        values["result_json"] = json.dumps(values["result_json"], ensure_ascii=False)
    assignments = ", ".join(f"{key} = ?" for key in values)
    with connect() as db:
        db.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?",
            (*values.values(), session_id),
        )


def insert_sample(session_id: str, sample: dict[str, Any]) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO samples (
                session_id, captured_at, elapsed_seconds,
                realtime_fps,
                system_cpu_percent, system_cpu_non_normalized_percent,
                app_cpu_percent, app_cpu_normalized_percent,
                gpu_usage_percent, gpu_usage_source,
                gpu_sample_window_us, gpu_sample_status, memory_mb,
                memory_usage_percent, memory_process_count,
                cpu_temperature_c, gpu_temperature_c,
                battery_temperature_c, battery_level_percent,
                battery_voltage_v
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                sample["captured_at"],
                sample["elapsed_seconds"],
                sample.get("realtime_fps"),
                sample.get("system_cpu_percent"),
                sample.get("system_cpu_non_normalized_percent"),
                sample.get("app_cpu_percent"),
                sample.get("app_cpu_normalized_percent"),
                sample.get("gpu_usage_percent"),
                sample.get("gpu_usage_source"),
                sample.get("gpu_sample_window_us"),
                sample.get("gpu_sample_status"),
                sample.get("memory_mb"),
                sample.get("memory_usage_percent"),
                sample.get("memory_process_count"),
                sample.get("cpu_temperature_c"),
                sample.get("gpu_temperature_c"),
                sample.get("battery_temperature_c"),
                sample.get("battery_level_percent"),
                sample.get("battery_voltage_v"),
            ),
        )


def insert_fps_sample(session_id: str, sample: dict[str, Any]) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO fps_samples (
                session_id, captured_at, elapsed_seconds, fps
            ) VALUES (?, ?, ?, ?)
            """,
            (
                session_id,
                sample["captured_at"],
                sample["elapsed_seconds"],
                sample["fps"],
            ),
        )


def _decode_session(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    raw_result = record.pop("result_json", None)
    record["result"] = json.loads(raw_result) if raw_result else None
    record["stop_requested"] = bool(record["stop_requested"])
    return record


def get_session(session_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _decode_session(row)


def list_sessions(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_decode_session(row) for row in rows if row is not None]


def get_samples(session_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM samples WHERE session_id = ? ORDER BY elapsed_seconds",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_sample(session_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT * FROM samples
            WHERE session_id = ?
            ORDER BY elapsed_seconds DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_fps_samples(session_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM fps_samples WHERE session_id = ? ORDER BY elapsed_seconds",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]
