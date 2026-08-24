from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

from perfetto.trace_processor import TraceProcessor, TraceProcessorConfig

from .config import TRACE_PROCESSOR_PATH


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        value = ordered[lower]
    else:
        weight = position - lower
        value = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(value, 3)


def compute_perfdog_metrics(
    presented_timestamps_ns: list[int],
    fps_by_second: list[float],
    duration_seconds: float,
) -> dict[str, Any]:
    """Compute metrics whose public definitions are documented by PerfDog.

    FTime is the display interval between adjacent presented frames. A Jank is
    counted when the current FTime is both greater than twice the mean of the
    previous three FTimes and greater than two 24fps movie-frame intervals.
    BigJank uses three movie-frame intervals. Smooth/SmallJank are intentionally
    excluded because their complete formulas are not public.
    """
    frame_times_ms = [
        (current - previous) / 1e6
        for previous, current in zip(
            presented_timestamps_ns, presented_timestamps_ns[1:]
        )
        if current > previous
    ]
    jank_times_ms: list[float] = []
    big_jank_times_ms: list[float] = []
    jank_threshold_ms = 1000.0 / 24.0 * 2.0
    big_jank_threshold_ms = 1000.0 / 24.0 * 3.0
    for index in range(3, len(frame_times_ms)):
        current = frame_times_ms[index]
        previous_mean = statistics.fmean(frame_times_ms[index - 3 : index])
        if current > previous_mean * 2.0 and current > jank_threshold_ms:
            jank_times_ms.append(current)
            if current > big_jank_threshold_ms:
                big_jank_times_ms.append(current)

    fps_drop_events = sum(
        1
        for previous, current in zip(fps_by_second, fps_by_second[1:])
        if previous - current > 8.0
    )
    frame_time_over_100_count = sum(1 for value in frame_times_ms if value > 100.0)
    safe_duration = max(duration_seconds, 0.001)
    fps_variance = statistics.pvariance(fps_by_second) if len(fps_by_second) > 1 else 0.0
    ftime_variance = statistics.pvariance(frame_times_ms) if len(frame_times_ms) > 1 else 0.0
    return {
        "fps_variance": round(fps_variance, 3),
        "fps_standard_deviation": round(math.sqrt(fps_variance), 3),
        "fps_drop_events": fps_drop_events,
        "fps_drop_per_hour": round(fps_drop_events * 3600.0 / safe_duration, 3),
        "jank_count": len(jank_times_ms),
        "big_jank_count": len(big_jank_times_ms),
        "jank_per_10_minutes": round(len(jank_times_ms) * 600.0 / safe_duration, 3),
        "big_jank_per_10_minutes": round(
            len(big_jank_times_ms) * 600.0 / safe_duration, 3
        ),
        "jank_time_ms": round(sum(jank_times_ms), 3),
        "frame_time_over_100ms_count": frame_time_over_100_count,
        "frame_time_over_100ms_percent": round(
            frame_time_over_100_count * 100.0 / max(1, len(frame_times_ms)), 3
        ),
        "frame_time_ms": {
            "average": round(statistics.fmean(frame_times_ms), 3)
            if frame_times_ms
            else None,
            "variance": round(ftime_variance, 3) if frame_times_ms else None,
            "standard_deviation": round(math.sqrt(ftime_variance), 3)
            if frame_times_ms
            else None,
            "p50": percentile(frame_times_ms, 50),
            "p90": percentile(frame_times_ms, 90),
            "p95": percentile(frame_times_ms, 95),
            "p99": percentile(frame_times_ms, 99),
            "maximum": round(max(frame_times_ms), 3) if frame_times_ms else None,
        },
    }


def apply_perfdog_fps_points(
    frame_result: dict[str, Any],
    fps_points: list[float],
    duration_seconds: float,
) -> dict[str, Any]:
    """Make 1-second TimeStats points authoritative for PerfDog FPS metrics."""
    points = [round(float(value), 3) for value in fps_points if value is not None and value >= 0]
    if not points:
        return frame_result
    result = dict(frame_result)
    result["trace_average_fps"] = frame_result.get("average_fps")
    result["trace_fps_by_second"] = frame_result.get("fps_by_second", [])
    result["trace_presented_frames"] = frame_result.get("presented_frames", 0)
    result["average_fps"] = round(statistics.fmean(points), 3)
    result["minimum_1s_fps"] = round(min(points), 3)
    result["maximum_1s_fps"] = round(max(points), 3)
    result["median_1s_fps"] = percentile(points, 50)
    result["p5_low_fps"] = percentile(points, 5)
    result["p1_low_fps"] = percentile(points, 1)
    variance = statistics.pvariance(points) if len(points) > 1 else 0.0
    result["fps_variance"] = round(variance, 3)
    result["fps_standard_deviation"] = round(math.sqrt(variance), 3)
    drops = sum(
        1
        for previous, current in zip(points, points[1:])
        if previous - current > 8.0
    )
    safe_duration = max(float(duration_seconds), 0.001)
    result["fps_drop_events"] = drops
    result["fps_drop_per_hour"] = round(drops * 3600.0 / safe_duration, 3)
    result["fps_by_second"] = points
    result["presented_frames"] = int(round(sum(points)))
    result["fps_source"] = "SurfaceFlinger TimeStats 1秒点（PerfDog公开口径）"
    result.setdefault("semantics", {})["fps"] = (
        "Avg/Var/Std/Drop(FPS)由采集期间SurfaceFlinger TimeStats的1秒FPS点计算；"
        "Perfetto用于Display FTime和Jank证据。"
    )
    return result


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    value = getattr(row, name, default)
    return default if value is None else value


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _trace_bounds(tp: TraceProcessor) -> tuple[int, int]:
    try:
        row = next(iter(tp.query("SELECT start_ts, end_ts FROM trace_bounds")))
        start = int(_row_value(row, "start_ts", 0))
        end = int(_row_value(row, "end_ts", 0))
        if end > start:
            return start, end
    except Exception:
        pass
    row = next(
        iter(
            tp.query(
                "SELECT MIN(ts) AS start_ts, MAX(ts + dur) AS end_ts "
                "FROM actual_frame_timeline_slice WHERE dur > 0"
            )
        )
    )
    return int(_row_value(row, "start_ts", 0)), int(_row_value(row, "end_ts", 0))


def analyze_trace(trace_path: str | Path, package_name: str) -> dict[str, Any]:
    trace_path = Path(trace_path).resolve()
    if not trace_path.is_file():
        raise RuntimeError(f"Trace文件不存在：{trace_path}")
    config = TraceProcessorConfig(
        bin_path=str(TRACE_PROCESSOR_PATH),
        unique_port=True,
        load_timeout=15,
    )
    tp = TraceProcessor(trace=str(trace_path), config=config)
    try:
        start_ns, end_ns = _trace_bounds(tp)
        duration_s = max(0.001, (end_ns - start_ns) / 1e9)
        source_rows = list(
            tp.query(
                """
                SELECT
                  CASE WHEN layer_name IS NULL OR layer_name = ''
                       THEN 'display' ELSE layer_name END AS source,
                  COUNT(*) AS total,
                  SUM(CASE WHEN present_type = 'Dropped Frame' THEN 0 ELSE 1 END) AS presented,
                  SUM(CASE WHEN present_type = 'Dropped Frame' THEN 1 ELSE 0 END) AS dropped,
                  SUM(CASE WHEN jank_type IS NOT NULL AND jank_type != 'None'
                                AND present_type != 'Dropped Frame'
                           THEN 1 ELSE 0 END) AS janky
                FROM actual_frame_timeline_slice
                WHERE dur > 0
                GROUP BY source
                ORDER BY presented DESC
                """
            )
        )
        if not source_rows:
            return {
                "available": False,
                "error": "测试区间内没有FrameTimeline帧；可能是画面静止、应用未在前台或设备未开放该数据源。",
                "trace_duration_seconds": round(duration_s, 3),
                "primary_source": None,
                "primary_source_reason": "无可用FrameTimeline来源",
                "quality_source": None,
                "average_fps": None,
                "minimum_1s_fps": None,
                "maximum_1s_fps": None,
                "median_1s_fps": None,
                "p5_low_fps": None,
                "p1_low_fps": None,
                "fps_standard_deviation": None,
                "fps_variance": None,
                "fps_drop_events": 0,
                "fps_drop_per_hour": None,
                "presented_frames": 0,
                "dropped_frames": 0,
                "janky_frames": 0,
                "big_jank_frames": 0,
                "jank_per_10_minutes": None,
                "big_jank_per_10_minutes": None,
                "frame_time_over_100ms_percent": None,
                "drop_rate_percent": None,
                "jank_rate_percent": None,
                "frame_time_ms": {
                    "average": None,
                    "p50": None,
                    "p90": None,
                    "p95": None,
                    "p99": None,
                    "maximum": None,
                },
                "fps_by_second": [],
                "sources": [],
                "semantics": {
                    "fps": "本次Trace没有可用于计算FPS的FrameTimeline帧。"
                },
            }

        sources: list[dict[str, Any]] = []
        for row in source_rows:
            source = str(_row_value(row, "source", "unknown"))
            total = int(_row_value(row, "total", 0))
            presented = int(_row_value(row, "presented", 0))
            dropped = int(_row_value(row, "dropped", 0))
            janky = int(_row_value(row, "janky", 0))
            sources.append(
                {
                    "source": source,
                    "total_frames": total,
                    "presented_frames": presented,
                    "dropped_frames": dropped,
                    "janky_frames": janky,
                    "fps": round(presented / duration_s, 3),
                }
            )

        matches = [
            source
            for source in sources
            if package_name.lower() in source["source"].lower()
            and source["presented_frames"] > 0
        ]
        display_source = next(
            (source for source in sources if source["source"] == "display"), None
        )
        primary = max(
            matches,
            key=lambda item: (
                1
                if (
                    "surfaceview" in item["source"].lower()
                    or "(blast)" in item["source"].lower()
                )
                else 0,
                item["presented_frames"],
            ),
            default=None,
        )
        selection_reason = "PerfDog游戏口径：包名匹配的SurfaceView/主要应用Surface"
        has_explicit_surface = primary is not None and (
            "surfaceview" in primary["source"].lower()
            or "(blast)" in primary["source"].lower()
        )
        if (
            primary is not None
            and display_source is not None
            and not has_explicit_surface
            and primary["fps"] < display_source["fps"] * 0.5
        ):
            primary = display_source
            selection_reason = (
                "包名层帧率显著低于display，判定为外壳层；"
                "使用SurfaceFlinger最终显示输出计算FTime/Jank"
            )
        if primary is None:
            primary = display_source
            selection_reason = "未找到应用Surface，回退到SurfaceFlinger最终显示输出"
        if primary is None:
            primary = max(sources, key=lambda item: item["presented_frames"])
            selection_reason = "帧数最多的Surface（未找到display或包名匹配）"

        quality_source = primary

        source_literal = _sql_literal(primary["source"])
        frames = list(
            tp.query(
                f"""
                SELECT ts, dur,
                       CASE WHEN present_type = 'Dropped Frame' THEN 1 ELSE 0 END AS dropped,
                       CASE WHEN jank_type IS NOT NULL AND jank_type != 'None'
                                  AND present_type != 'Dropped Frame'
                            THEN 1 ELSE 0 END AS janky
                FROM actual_frame_timeline_slice
                WHERE dur > 0
                  AND (CASE WHEN layer_name IS NULL OR layer_name = ''
                            THEN 'display' ELSE layer_name END) = {source_literal}
                ORDER BY ts
                """
            )
        )

        presented_timestamps_ns = [
            int(_row_value(row, "ts", 0))
            for row in frames
            if not bool(_row_value(row, "dropped", 0))
        ]
        bucket_count = max(1, math.ceil(duration_s))
        fps_by_second = [0.0] * bucket_count
        for row in frames:
            if bool(_row_value(row, "dropped", 0)):
                continue
            index = int((int(_row_value(row, "ts", start_ns)) - start_ns) / 1e9)
            if 0 <= index < bucket_count:
                fps_by_second[index] += 1.0

        valid_fps = fps_by_second
        perfdog = compute_perfdog_metrics(
            presented_timestamps_ns, fps_by_second, duration_s
        )
        presented = primary["presented_frames"]
        dropped = quality_source["dropped_frames"]
        android_janky = quality_source["janky_frames"]
        total = quality_source["total_frames"]
        return {
            "available": True,
            "trace_duration_seconds": round(duration_s, 3),
            "primary_source": primary["source"],
            "primary_source_reason": selection_reason,
            "quality_source": quality_source["source"],
            "average_fps": round(presented / duration_s, 3),
            "minimum_1s_fps": round(min(valid_fps), 3) if valid_fps else None,
            "maximum_1s_fps": round(max(valid_fps), 3) if valid_fps else None,
            "median_1s_fps": percentile(valid_fps, 50),
            "p5_low_fps": percentile(valid_fps, 5),
            "p1_low_fps": percentile(valid_fps, 1),
            "fps_variance": perfdog["fps_variance"],
            "fps_standard_deviation": perfdog["fps_standard_deviation"],
            "fps_drop_events": perfdog["fps_drop_events"],
            "fps_drop_per_hour": perfdog["fps_drop_per_hour"],
            "presented_frames": presented,
            "dropped_frames": dropped,
            "janky_frames": perfdog["jank_count"],
            "big_jank_frames": perfdog["big_jank_count"],
            "android_janky_frames": android_janky,
            "jank_per_10_minutes": perfdog["jank_per_10_minutes"],
            "big_jank_per_10_minutes": perfdog["big_jank_per_10_minutes"],
            "jank_time_ms": perfdog["jank_time_ms"],
            "frame_time_over_100ms_count": perfdog[
                "frame_time_over_100ms_count"
            ],
            "frame_time_over_100ms_percent": perfdog[
                "frame_time_over_100ms_percent"
            ],
            "drop_rate_percent": round(dropped * 100.0 / total, 3) if total else 0.0,
            "jank_rate_percent": round(
                perfdog["jank_count"]
                * 100.0
                / max(1, quality_source["presented_frames"]),
                3,
            ),
            "frame_time_ms": perfdog["frame_time_ms"],
            "fps_by_second": [round(value, 3) for value in fps_by_second],
            "sources": sources[:30],
            "semantics": {
                "fps": "游戏优先使用包名匹配的SurfaceView/应用Surface；每秒统计真实呈现帧数。",
                "jank": "PerfDog公开口径：当前Display FrameTime大于前三帧均值2倍，且大于84ms；BigJank阈值125ms。",
                "low_fps": "P5/P1 Low基于1秒FPS桶的分位数。",
                "frame_time": "相邻两个呈现帧时间戳的间隔（Display FrameTime）。",
            },
        }
    finally:
        tp.close()
