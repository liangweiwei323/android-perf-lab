from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db as db_module
from app import report as report_module
from app.adb import (
    CpuSnapshot,
    cpu_usage_metrics,
    parse_kgsl_gpu_busy,
    parse_timestats_fps,
    parse_uid_memory_output,
    read_cpu_snapshot,
)
from app.evaluation import evaluate_frame_performance
from app.perfetto import (
    apply_perfdog_fps_points,
    compute_perfdog_metrics,
    percentile,
)
from app.report import _line_svg, generate_report, summarize_samples


class PercentileTests(unittest.TestCase):
    def test_linear_percentile(self) -> None:
        self.assertEqual(percentile([0, 10, 20, 30, 40], 50), 20)
        self.assertEqual(percentile([0, 10, 20, 30, 40], 5), 2)

    def test_empty_percentile(self) -> None:
        self.assertIsNone(percentile([], 95))

    def test_perfdog_jank_and_big_jank_thresholds(self) -> None:
        intervals_ms = [16, 16, 16, 100, 16, 16, 16, 140]
        timestamps = [0]
        for interval in intervals_ms:
            timestamps.append(timestamps[-1] + int(interval * 1_000_000))
        result = compute_perfdog_metrics(timestamps, [60, 40, 30], 3.0)
        self.assertEqual(result["jank_count"], 2)
        self.assertEqual(result["big_jank_count"], 1)
        self.assertEqual(result["fps_drop_events"], 2)
        self.assertEqual(result["frame_time_over_100ms_count"], 1)

    def test_one_second_points_are_authoritative_for_average_fps(self) -> None:
        result = apply_perfdog_fps_points(
            {"average_fps": 13.66, "presented_frames": 297, "semantics": {}},
            [120, 140, 160],
            3.0,
        )
        self.assertEqual(result["average_fps"], 140.0)
        self.assertEqual(result["trace_average_fps"], 13.66)
        self.assertEqual(result["fps_source"], "SurfaceFlinger TimeStats 1秒点（PerfDog公开口径）")


class SampleSummaryTests(unittest.TestCase):
    def test_ignores_missing_values(self) -> None:
        summary = summarize_samples(
            [
                {"app_cpu_percent": 10, "memory_mb": 100},
                {"app_cpu_percent": None, "memory_mb": 150},
                {"app_cpu_percent": 30, "memory_mb": None},
            ]
        )
        self.assertEqual(summary["app_cpu"]["average"], 20)
        self.assertEqual(summary["app_cpu"]["maximum"], 30)
        self.assertEqual(summary["memory_mb"]["average"], 125)

    def test_report_chart_contains_axes_and_hover_data(self) -> None:
        chart = _line_svg(
            [10, 20, 15],
            title="测试曲线",
            color="#fff",
            suffix=" FPS",
            x_values=[1.25, 2.5, 5.0],
        )
        self.assertIn('class="interactive-chart"', chart)
        self.assertIn('class="chart-hitbox"', chart)
        self.assertEqual(chart.count('class="axis-label"'), 11)
        self.assertIn("1.25", chart)
        self.assertIn(">5s</text>", chart)

    def test_report_contains_normalized_app_and_total_cpu(self) -> None:
        samples = [
            {
                "elapsed_seconds": 1.0,
                "app_cpu_percent": 160.0,
                "app_cpu_normalized_percent": 20.0,
                "system_cpu_non_normalized_percent": 400.0,
                "system_cpu_percent": 50.0,
                "gpu_usage_percent": 37.5,
                "gpu_usage_source": "qualcomm_kgsl_gpubusy",
                "gpu_sample_window_us": 1000000,
                "gpu_sample_status": "valid",
            }
        ]
        result = {
            "frame": {},
            "evaluation": {"available": False},
            "sample_summary": summarize_samples(samples),
            "metadata": {},
        }
        session = {
            "id": "cpu-report-test",
            "package_name": "com.example.app",
            "serial": "test-device",
            "started_at": "2026-08-24T00:00:00+00:00",
            "trace_path": "",
        }

        with tempfile.TemporaryDirectory() as directory:
            original_report_dir = report_module.REPORT_DIR
            report_module.REPORT_DIR = Path(directory)
            try:
                report_path = generate_report(session, samples, result)
                html_text = report_path.read_text(encoding="utf-8")
            finally:
                report_module.REPORT_DIR = original_report_dir

        self.assertIn("App CPU（整机归一化，SoloX同口径）", html_text)
        self.assertIn("Total CPU（整机归一化）", html_text)
        self.assertIn("App CPU 单核累加", html_text)
        self.assertIn("GPU占用（Qualcomm KGSL驱动窗口）", html_text)
        self.assertIn("GPU占用 平均/峰值", html_text)


class CpuUsageTests(unittest.TestCase):
    @patch("app.adb.run_adb")
    def test_snapshot_uses_solox_proc_stat_fields(self, run_adb_mock) -> None:
        run_adb_mock.return_value = """cpu 100 10 20 300 40 5 5 999 0 0
PIDS:123
123 (app process) R 1 1 1 0 0 0 0 0 0 0 10 20 30 40 0
CORES:8
"""

        snapshot = read_cpu_snapshot("device", "com.example.app", 10001)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.total, 480)
        self.assertEqual(snapshot.idle, 300)
        self.assertEqual(snapshot.app, 100)
        self.assertEqual(snapshot.core_count, 8)

    def test_solox_normalized_and_core_aggregate_cpu_are_both_available(self) -> None:
        previous = CpuSnapshot(total=1000, idle=500, app=100, core_count=8)
        current = CpuSnapshot(total=1800, idle=900, app=260, core_count=8)

        metrics = cpu_usage_metrics(previous, current)

        self.assertEqual(metrics["app_normalized"], 20.0)
        self.assertEqual(metrics["app_non_normalized"], 160.0)
        self.assertEqual(metrics["system_normalized"], 50.0)
        self.assertEqual(metrics["system_non_normalized"], 400.0)

    def test_normalized_app_cpu_is_capped_at_physical_limit(self) -> None:
        previous = CpuSnapshot(total=1000, idle=500, app=100, core_count=8)
        current = CpuSnapshot(total=1800, idle=900, app=1000, core_count=8)

        metrics = cpu_usage_metrics(previous, current)

        self.assertEqual(metrics["app_normalized"], 100.0)
        self.assertEqual(metrics["app_non_normalized"], 800.0)


class GpuUsageTests(unittest.TestCase):
    def test_parses_qualcomm_kgsl_busy_window(self) -> None:
        sample = parse_kgsl_gpu_busy("250000 1000000\n")

        self.assertEqual(sample["gpu_usage_percent"], 25.0)
        self.assertEqual(sample["gpu_sample_window_us"], 1000000)
        self.assertEqual(sample["gpu_sample_status"], "valid")
        self.assertEqual(sample["gpu_usage_source"], "qualcomm_kgsl_gpubusy")

    def test_zero_window_is_not_claimed_as_verified_idle(self) -> None:
        sample = parse_kgsl_gpu_busy("0 0\n")

        self.assertEqual(sample["gpu_usage_percent"], 0.0)
        self.assertEqual(sample["gpu_sample_status"], "idle_or_counter_consumed")

    def test_rejects_physically_invalid_window(self) -> None:
        sample = parse_kgsl_gpu_busy("110 100\n")

        self.assertIsNone(sample["gpu_usage_percent"])
        self.assertEqual(sample["gpu_sample_status"], "invalid")

    def test_gpu_columns_round_trip_through_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_db_path = db_module.DB_PATH
            db_module.DB_PATH = Path(directory) / "test.db"
            try:
                db_module.init_db()
                db_module.create_session(
                    {
                        "id": "gpu-db-test",
                        "serial": "device",
                        "package_name": "com.example.app",
                        "requested_duration": 5,
                        "status": "capturing",
                        "started_at": "2026-08-24T00:00:00+00:00",
                    }
                )
                db_module.insert_sample(
                    "gpu-db-test",
                    {
                        "captured_at": "2026-08-24T00:00:01+00:00",
                        "elapsed_seconds": 1.0,
                        "gpu_usage_percent": 42.5,
                        "gpu_usage_source": "qualcomm_kgsl_gpubusy",
                        "gpu_sample_window_us": 1000000,
                        "gpu_sample_status": "valid",
                    },
                )
                row = db_module.get_latest_sample("gpu-db-test")
            finally:
                db_module.DB_PATH = original_db_path

        self.assertEqual(row["gpu_usage_percent"], 42.5)
        self.assertEqual(row["gpu_sample_status"], "valid")


class UidMemoryTests(unittest.TestCase):
    def test_sums_pss_for_all_uid_processes_and_calculates_rate(self) -> None:
        result = parse_uid_memory_output(
            """
MEMTOTAL:8192000
PROC:101:com.example.game
TOTAL PSS: 204800 TOTAL RSS: 300000 TOTAL SWAP PSS: 10240
PROC:102:game.exe
TOTAL PSS: 1048576 TOTAL RSS: 1200000 TOTAL SWAP (KB): 0
PROC:103:wine
TOTAL PSS: 51200 TOTAL RSS: 70000 TOTAL SWAP PSS: 2048
"""
        )
        self.assertEqual(result["memory_mb"], 1274.0)
        self.assertEqual(result["memory_usage_percent"], 15.93)
        self.assertEqual(result["memory_swap_mb"], 12.0)
        self.assertEqual(result["memory_process_count"], 3)
        self.assertEqual(result["memory_processes"][0]["name"], "game.exe")


class FrameEvaluationTests(unittest.TestCase):
    @staticmethod
    def frame(points: list[float]) -> dict[str, object]:
        average = sum(points) / len(points)
        return {
            "fps_by_second": points,
            "average_fps": average,
            "p5_low_fps": min(points),
            "fps_standard_deviation": 0.0,
            "fps_drop_events": 0,
            "trace_duration_seconds": len(points),
            "janky_frames": 0,
            "big_jank_frames": 0,
            "frame_time_over_100ms_percent": 0.0,
            "jank_time_ms": 0.0,
        }

    def test_stable_60_fps_is_high_frame_smooth(self) -> None:
        result = evaluate_frame_performance(self.frame([60.0] * 60))
        self.assertGreaterEqual(result["overall_score"], 95)
        self.assertEqual(result["grade"], "S")
        self.assertEqual(result["absolute_experience"], "高帧流畅")
        self.assertTrue(result["reliable"])

    def test_stable_30_fps_is_playable_but_misses_60_target(self) -> None:
        result = evaluate_frame_performance(self.frame([30.0] * 60))
        self.assertEqual(
            result["dimensions"]["target_attainment"]["score"],
            50.0,
        )
        self.assertEqual(result["absolute_experience"], "正常可玩")
        self.assertLess(result["overall_score"], 80)

    def test_below_30_buckets_and_longest_streak(self) -> None:
        points = [60.0, 29.0, 23.0, 19.0, 14.0, 60.0] * 5
        result = evaluate_frame_performance(self.frame(points))
        low = result["low_frame"]
        self.assertEqual(low["below_30_percent"], 66.67)
        self.assertEqual(low["below_24_percent"], 50.0)
        self.assertEqual(low["below_20_percent"], 33.33)
        self.assertEqual(low["below_15_percent"], 16.67)
        self.assertEqual(low["longest_below_30_seconds"], 4)


class TimeStatsTests(unittest.TestCase):
    def test_prefers_game_surface(self) -> None:
        output = """
layerName = com.xiaoji.egggame/com.xiaoji.egggame.MainActivity#1
totalFrames = 120
averageFPS = 60.000
layerName = SurfaceView[com.xiaoji.egggame/.plugin.pcengine.host.PcEnginePluginHostActivity]#2
totalFrames = 90
averageFPS = 47.500
"""
        self.assertEqual(parse_timestats_fps(output, "com.xiaoji.egggame"), 47.5)

    def test_falls_back_to_global_present_rate(self) -> None:
        output = """
statsStart = 100
statsEnd = 103
totalFrames = 180
totalP2PTime = 3000 ms
layerName = none
totalFrames = 0
"""
        self.assertEqual(parse_timestats_fps(output, "com.xiaoji.egggame"), 60.0)

    def test_global_rate_uses_full_window_not_short_p2p_span(self) -> None:
        output = """
statsStart = 100
statsEnd = 101
totalFrames = 2
totalP2PTime = 3 ms
displayRefreshRate = 120 fps
layerName = none
totalFrames = 0
"""
        self.assertEqual(parse_timestats_fps(output, "com.xiaoji.egggame"), 2.0)

    def test_app_rate_is_capped_by_display_refresh_rate(self) -> None:
        output = """
displayRefreshRate = 165 fps
layerName = com.xiaoji.egggame/GameSurface#1
totalFrames = 170
averageFPS = 166.670
"""
        self.assertEqual(parse_timestats_fps(output, "com.xiaoji.egggame"), 165.0)


if __name__ == "__main__":
    unittest.main()
