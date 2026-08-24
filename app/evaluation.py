from __future__ import annotations

from typing import Any


TARGET_FPS = 60.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _grade(score: float) -> tuple[str, str]:
    if score >= 95:
        return "S", "极佳"
    if score >= 90:
        return "A", "优秀"
    if score >= 80:
        return "B", "良好"
    if score >= 70:
        return "C", "一般"
    return "D", "需要优化"


def _low_frame_penalty(fps: float) -> float:
    if fps >= 45:
        return 0.0
    if fps >= 30:
        return (45 - fps) / 15 * 0.20
    if fps >= 24:
        return 0.20 + (30 - fps) / 6 * 0.25
    if fps >= 20:
        return 0.45 + (24 - fps) / 4 * 0.20
    if fps >= 15:
        return 0.65 + (20 - fps) / 5 * 0.20
    return 0.85 + (15 - max(0.0, fps)) / 15 * 0.15


def _percentage_below(points: list[float], threshold: float) -> float:
    if not points:
        return 0.0
    return round(sum(value < threshold for value in points) * 100.0 / len(points), 2)


def _longest_below(points: list[float], threshold: float) -> int:
    longest = 0
    current = 0
    for value in points:
        if value < threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _absolute_experience(
    average_fps: float,
    below: dict[int, float],
) -> str:
    if average_fps < 15 or below[15] >= 10:
        return "接近不可玩"
    if average_fps < 20 or below[20] >= 20:
        return "严重卡顿"
    if average_fps < 24 or below[24] >= 20:
        return "明显不流畅"
    if average_fps < 30 or below[30] >= 20:
        return "基本可玩"
    if average_fps < 45:
        return "正常可玩"
    if average_fps < 60:
        return "流畅"
    return "高帧流畅"


def evaluate_frame_performance(
    frame: dict[str, Any],
    target_fps: float = TARGET_FPS,
) -> dict[str, Any]:
    raw_points = frame.get("fps_by_second") or []
    points = [float(value) for value in raw_points if value is not None]
    if not points:
        return {
            "available": False,
            "target_fps": target_fps,
            "error": "没有可用于评价的每秒FPS点。",
        }

    average_fps = float(frame.get("average_fps") or sum(points) / len(points))
    p5_fps = float(frame.get("p5_low_fps") or min(points))
    std_fps = float(frame.get("fps_standard_deviation") or 0.0)
    fps_drop_events = int(frame.get("fps_drop_events") or 0)
    duration_seconds = float(
        frame.get("trace_duration_seconds") or max(1, len(points))
    )

    average_attainment = _clamp(average_fps * 100.0 / target_fps)
    p5_attainment = _clamp(p5_fps * 100.0 / target_fps)
    target_score = 0.65 * average_attainment + 0.35 * p5_attainment

    average_penalty = sum(_low_frame_penalty(value) for value in points) / len(points)
    low_frame_score = _clamp((1.0 - average_penalty) * 100.0)

    coefficient_of_variation = std_fps / average_fps if average_fps > 0 else 1.0
    variation_score = _clamp(100.0 * (1.0 - coefficient_of_variation / 0.40))
    tail_score = _clamp(p5_fps * 100.0 / average_fps) if average_fps > 0 else 0.0
    drop_ratio = fps_drop_events / max(1, len(points) - 1)
    drop_score = _clamp(100.0 - drop_ratio * 250.0)
    stability_score = (
        0.45 * variation_score + 0.40 * tail_score + 0.15 * drop_score
    )

    duration_minutes = max(duration_seconds / 60.0, 1.0 / 60.0)
    jank_count = int(frame.get("janky_frames") or 0)
    big_jank_count = int(frame.get("big_jank_frames") or 0)
    jank_per_minute = jank_count / duration_minutes
    big_jank_per_minute = big_jank_count / duration_minutes
    over_100ms_percent = float(frame.get("frame_time_over_100ms_percent") or 0.0)
    jank_time_ms = float(frame.get("jank_time_ms") or 0.0)
    stutter_percent = (
        jank_time_ms * 100.0 / (duration_seconds * 1000.0)
        if duration_seconds > 0
        else 0.0
    )
    jank_score = 100.0 / (1.0 + jank_per_minute / 4.0)
    big_jank_score = 100.0 / (1.0 + big_jank_per_minute / 1.5)
    long_frame_score = _clamp(100.0 - over_100ms_percent * 12.5)
    stutter_score = _clamp(100.0 - stutter_percent * 20.0)
    jank_dimension_score = (
        0.25 * jank_score
        + 0.25 * big_jank_score
        + 0.25 * long_frame_score
        + 0.25 * stutter_score
    )

    dimension_scores = {
        "target_attainment": round(target_score, 2),
        "low_frame": round(low_frame_score, 2),
        "stability": round(stability_score, 2),
        "jank": round(jank_dimension_score, 2),
    }
    overall_score = round(
        dimension_scores["target_attainment"] * 0.30
        + dimension_scores["low_frame"] * 0.30
        + dimension_scores["stability"] * 0.25
        + dimension_scores["jank"] * 0.15,
        2,
    )
    overall_grade, overall_label = _grade(overall_score)

    below = {
        threshold: _percentage_below(points, threshold)
        for threshold in (30, 24, 20, 15)
    }
    longest = {
        threshold: _longest_below(points, threshold)
        for threshold in (30, 24, 20, 15)
    }
    absolute_experience = _absolute_experience(average_fps, below)
    dimensions = {}
    dimension_labels = {
        "target_attainment": "目标帧率达成度",
        "low_frame": "低帧表现",
        "stability": "帧率稳定性",
        "jank": "卡顿表现",
    }
    for key, score in dimension_scores.items():
        grade, label = _grade(score)
        dimensions[key] = {
            "name": dimension_labels[key],
            "score": score,
            "grade": grade,
            "label": label,
        }

    attainment_ratio = average_fps * 100.0 / target_fps
    conclusion = [
        f"平均FPS为{average_fps:.1f}，达到{target_fps:.0f} FPS目标的{attainment_ratio:.1f}%。",
        (
            f"低于30 FPS的时间占比为{below[30]:.1f}%，"
            f"低于24 FPS的时间占比为{below[24]:.1f}%。"
        ),
        (
            f"FPS标准差为{std_fps:.2f}，P5 Low为{p5_fps:.1f} FPS；"
            f"检测到{jank_count}次Jank和{big_jank_count}次BigJank。"
        ),
        f"绝对体验判断为“{absolute_experience}”。",
    ]
    reliable = duration_seconds >= 30 and len(points) >= 30
    if not reliable:
        conclusion.append("采集时间少于30秒或FPS点不足30个，本次评价仅供参考。")

    return {
        "available": True,
        "target_fps": target_fps,
        "overall_score": overall_score,
        "grade": overall_grade,
        "label": overall_label,
        "absolute_experience": absolute_experience,
        "reliable": reliable,
        "sample_seconds": len(points),
        "dimensions": dimensions,
        "low_frame": {
            "below_30_percent": below[30],
            "below_24_percent": below[24],
            "below_20_percent": below[20],
            "below_15_percent": below[15],
            "longest_below_30_seconds": longest[30],
            "longest_below_24_seconds": longest[24],
            "longest_below_20_seconds": longest[20],
            "longest_below_15_seconds": longest[15],
        },
        "inputs": {
            "average_fps": round(average_fps, 3),
            "p5_low_fps": round(p5_fps, 3),
            "std_fps": round(std_fps, 3),
            "jank_count": jank_count,
            "big_jank_count": big_jank_count,
            "stutter_percent": round(stutter_percent, 3),
        },
        "conclusion": conclusion,
        "method": "Android Perf Lab自定义透明四维评分（非PerfDog官方总分）",
    }
