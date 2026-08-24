from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any
from datetime import datetime

from .config import REPORT_DIR


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{suffix}"
    return html.escape(str(value))


def _metric_card(label: str, value: str, description: str) -> str:
    """Render one accessible metric card with an offline tooltip."""
    safe_label = html.escape(label)
    safe_description = html.escape(description)
    return (
        '<div class="metric">'
        '<div class="metric-title">'
        f'<span>{safe_label}</span>'
        f'<button class="metric-help" type="button" aria-label="{safe_label}：{safe_description}">?</button>'
        f'<span class="metric-tooltip" role="tooltip"><strong>{safe_label}</strong>{safe_description}</span>'
        '</div>'
        f'<b>{value}</b>'
        '</div>'
    )


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"average": None, "maximum": None, "minimum": None}
    return {
        "average": round(sum(values) / len(values), 3),
        "maximum": round(max(values), 3),
        "minimum": round(min(values), 3),
    }


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "system_cpu_percent": "system_cpu",
        "system_cpu_non_normalized_percent": "system_cpu_non_normalized",
        "app_cpu_percent": "app_cpu",
        "app_cpu_normalized_percent": "app_cpu_normalized",
        "gpu_usage_percent": "gpu_usage",
        "memory_mb": "memory_mb",
        "memory_usage_percent": "memory_usage_percent",
        "cpu_temperature_c": "cpu_temperature_c",
        "gpu_temperature_c": "gpu_temperature_c",
        "battery_temperature_c": "battery_temperature_c",
        "battery_level_percent": "battery_level_percent",
    }
    result: dict[str, Any] = {}
    for field, output_name in fields.items():
        values = [float(row[field]) for row in samples if row.get(field) is not None]
        result[output_name] = _summary(values)
    return result


def _line_svg(
    values: list[float | None],
    *,
    title: str,
    color: str,
    suffix: str = "",
    x_values: list[float] | None = None,
    width: int = 920,
    height: int = 270,
) -> str:
    times = x_values if x_values is not None else [float(index) for index in range(len(values))]
    valid = [
        (float(times[index]), float(value))
        for index, value in enumerate(values)
        if value is not None and index < len(times)
    ]
    if not valid:
        return f'<div class="empty">{html.escape(title)}：暂无数据</div>'
    y_values = [value for _, value in valid]
    low, high = min(y_values), max(y_values)
    if math.isclose(low, high):
        low -= 1
        high += 1
    x_low = 0.0
    x_high = max(1.0, max(time_value for time_value, _ in valid))
    padding_left, padding_right, padding_top, padding_bottom = 66, 24, 28, 48
    inner_w = width - padding_left - padding_right
    inner_h = height - padding_top - padding_bottom
    points = []
    point_data = []
    for time_value, value in valid:
        x = padding_left + inner_w * (time_value - x_low) / (x_high - x_low)
        y = padding_top + inner_h * (high - value) / (high - low)
        points.append(f"{x:.2f},{y:.2f}")
        point_data.append(
            {
                "time": round(time_value, 3),
                "value": round(value, 4),
                "x": round(x, 2),
                "y": round(y, 2),
            }
        )
    y_ticks = []
    for index in range(5):
        y = padding_top + inner_h * index / 4
        value = high - (high - low) * index / 4
        y_ticks.append(
            f'<line x1="{padding_left}" y1="{y:.2f}" x2="{width-padding_right}" y2="{y:.2f}" class="grid-line"/>'
            f'<text x="{padding_left-9}" y="{y+4:.2f}" class="axis-label" text-anchor="end">{value:.2f}</text>'
        )
    x_ticks = []
    for index in range(6):
        x = padding_left + inner_w * index / 5
        value = x_low + (x_high - x_low) * index / 5
        label = f"{value:.1f}s" if not math.isclose(value, round(value)) else f"{int(round(value))}s"
        x_ticks.append(
            f'<line x1="{x:.2f}" y1="{padding_top}" x2="{x:.2f}" y2="{height-padding_bottom}" class="grid-line vertical"/>'
            f'<text x="{x:.2f}" y="{height-padding_bottom+20}" class="axis-label" text-anchor="middle">{label}</text>'
        )
    data_json = html.escape(json.dumps(point_data, ensure_ascii=False), quote=True)
    safe_title = html.escape(title)
    safe_suffix = html.escape(suffix.strip())
    return f"""
    <section class="chart-card">
      <div class="chart-head"><strong>{safe_title}</strong>
        <span>{low:.1f}{html.escape(suffix)} – {high:.1f}{html.escape(suffix)}</span></div>
      <div class="chart-stage">
      <svg class="interactive-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{safe_title}" data-title="{safe_title}" data-suffix="{safe_suffix}" data-points="{data_json}">
        {''.join(y_ticks)}
        {''.join(x_ticks)}
        <line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{height-padding_bottom}" class="axis"/>
        <line x1="{padding_left}" y1="{height-padding_bottom}" x2="{width-padding_right}" y2="{height-padding_bottom}" class="axis"/>
        <text x="{padding_left}" y="15" class="axis-name">{safe_suffix or '数值'}</text>
        <text x="{width-padding_right}" y="{height-7}" class="axis-name" text-anchor="end">时间</text>
        <polyline points="{' '.join(points)}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
        <line class="hover-line hover-x" x1="0" y1="{padding_top}" x2="0" y2="{height-padding_bottom}"/>
        <line class="hover-line hover-y" x1="{padding_left}" y1="0" x2="{width-padding_right}" y2="0"/>
        <circle class="hover-point" cx="0" cy="0" r="5" fill="{color}"/>
        <rect class="chart-hitbox" x="{padding_left}" y="{padding_top}" width="{inner_w}" height="{inner_h}"/>
      </svg>
      <div class="chart-value-tooltip" aria-live="polite"></div>
      </div>
    </section>
    """


def generate_report(
    session: dict[str, Any],
    samples: list[dict[str, Any]],
    result: dict[str, Any],
) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{session['id']}.html"
    sample_summary = result.get("sample_summary", {})
    frame = result.get("frame", {})
    frame_time = frame.get("frame_time_ms", {})
    source_rows = "".join(
        f"<tr><td>{html.escape(str(source.get('source', '')))}</td>"
        f"<td>{_fmt(source.get('fps'))}</td>"
        f"<td>{source.get('presented_frames', 0)}</td>"
        f"<td>{source.get('dropped_frames', 0)}</td>"
        f"<td>{source.get('janky_frames', 0)}</td></tr>"
        for source in frame.get("sources", [])
    )
    fps_values = frame.get("fps_by_second", [])
    sample_times = [float(row.get("elapsed_seconds", index)) for index, row in enumerate(samples)]
    app_cpu_core_aggregate = sample_summary.get("app_cpu", {})
    app_cpu = sample_summary.get("app_cpu_normalized", {})
    total_cpu = sample_summary.get("system_cpu", {})
    total_cpu_core_aggregate = sample_summary.get(
        "system_cpu_non_normalized", {}
    )
    gpu_usage = sample_summary.get("gpu_usage", {})
    gpu_source = next(
        (str(row["gpu_usage_source"]) for row in samples if row.get("gpu_usage_source")),
        None,
    )
    gpu_valid_samples = sum(
        1 for row in samples if row.get("gpu_sample_status") == "valid"
    )
    gpu_ambiguous_samples = sum(
        1
        for row in samples
        if row.get("gpu_sample_status") == "idle_or_counter_consumed"
    )
    if gpu_source == "qualcomm_kgsl_gpubusy":
        gpu_quality_note = (
            f"GPU来源：Qualcomm KGSL gpubusy；有效忙碌窗口 {gpu_valid_samples} 个，"
            f"GPU休眠或计数器被其他软件提前读取的0/0窗口 {gpu_ambiguous_samples} 个。"
            "该节点读取后会消费当前统计窗口；与SoloX等软件同时采集GPU时可能互相干扰，"
            "因此同机对比建议只让一个软件记录GPU。"
        )
    else:
        gpu_quality_note = (
            "本设备没有开放已验证的Qualcomm KGSL GPU占用节点，本次GPU占用显示为N/A；"
            "工具不会用频率或温度推算占用率。"
        )
    memory_summary = sample_summary.get("memory_mb", {})
    memory_usage_summary = sample_summary.get("memory_usage_percent", {})
    cpu_temperature = sample_summary.get("cpu_temperature_c", {})
    metadata = result.get("metadata", {})
    metadata_json = json.dumps(metadata, ensure_ascii=False)
    memory_process_rows = "".join(
        f"<tr><td>{process.get('pid', '')}</td>"
        f"<td>{html.escape(str(process.get('name', '')))}</td>"
        f"<td>{_fmt(process.get('pss_mb'), 2)} MB</td>"
        f"<td>{_fmt(process.get('swap_pss_mb'), 2)} MB</td></tr>"
        for process in metadata.get("memory_processes", [])
    )
    evaluation = result.get("evaluation", {})
    if evaluation.get("available"):
        evaluation_dimension_cards = "".join(
            _metric_card(
                str(dimension.get("name", key)),
                f'{_fmt(dimension.get("score"), 1)}分 · {html.escape(str(dimension.get("grade", "")))}',
                f'{dimension.get("name", key)}子评分：{dimension.get("label", "")}。综合分权重分别为目标达成30%、低帧30%、稳定性25%、卡顿15%。',
            )
            for key, dimension in evaluation.get("dimensions", {}).items()
        )
        low_frame = evaluation.get("low_frame", {})
        evaluation_conclusion = "".join(
            f"<p>{html.escape(str(paragraph))}</p>"
            for paragraph in evaluation.get("conclusion", [])
        )
        evaluation_html = f"""
  <h2>帧率综合评价</h2>
  <div class="evaluation-hero">
    <div><span class="evaluation-grade">{html.escape(str(evaluation.get('grade', 'N/A')))}</span></div>
    <div><strong>{_fmt(evaluation.get('overall_score'), 1)}分 · {html.escape(str(evaluation.get('label', '')))}</strong>
      <p>目标 {evaluation.get('target_fps', 60):.0f} FPS · 绝对体验：{html.escape(str(evaluation.get('absolute_experience', 'N/A')))}</p>
      <small>{html.escape(str(evaluation.get('method', '')))}</small>
    </div>
  </div>
  <div class="grid">{evaluation_dimension_cards}</div>
  <div class="table-card"><table><thead><tr><th>低帧区间</th><th>时间占比</th><th>最长连续时长</th></tr></thead><tbody>
    <tr><td>&lt;30 FPS</td><td>{_fmt(low_frame.get('below_30_percent'), 2)}%</td><td>{low_frame.get('longest_below_30_seconds', 0)}秒</td></tr>
    <tr><td>&lt;24 FPS</td><td>{_fmt(low_frame.get('below_24_percent'), 2)}%</td><td>{low_frame.get('longest_below_24_seconds', 0)}秒</td></tr>
    <tr><td>&lt;20 FPS</td><td>{_fmt(low_frame.get('below_20_percent'), 2)}%</td><td>{low_frame.get('longest_below_20_seconds', 0)}秒</td></tr>
    <tr><td>&lt;15 FPS</td><td>{_fmt(low_frame.get('below_15_percent'), 2)}%</td><td>{low_frame.get('longest_below_15_seconds', 0)}秒</td></tr>
  </tbody></table></div>
  <div class="note">{evaluation_conclusion}</div>
"""
    else:
        evaluation_html = '<h2>帧率综合评价</h2><div class="empty">暂无足够FPS数据生成评价。</div>'
    try:
        displayed_started_at = (
            datetime.fromisoformat(session["started_at"])
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S %Z")
        )
    except (KeyError, TypeError, ValueError):
        displayed_started_at = str(session.get("started_at", ""))
    fps_metric_cards = "".join(
        [
            _metric_card(
                "平均FPS",
                _fmt(frame.get("average_fps")),
                "采集时间段内每个1秒FPS点的算术平均值。越高且越接近目标刷新率通常越流畅；启动、加载、菜单和静止画面也会计入当前时间段。",
            ),
            _metric_card(
                "Var(FPS)",
                _fmt(frame.get("fps_variance")),
                "FPS方差，即每秒FPS与平均FPS偏差平方的平均值，单位为FPS²。它衡量波动幅度，越低表示帧率越稳定。",
            ),
            _metric_card(
                "Std(FPS)",
                _fmt(frame.get("fps_standard_deviation")),
                "FPS标准差，是方差的平方根，单位为FPS。越低表示每秒FPS越集中、稳定性越好，比方差更容易与平均FPS直接比较。",
            ),
            _metric_card(
                "Drop(FPS)/小时",
                _fmt(frame.get("fps_drop_per_hour")),
                "相邻两个1秒FPS点下降超过8帧记为一次Drop，再按每小时折算。越低越好；测试时间很短时，折算结果会被放大，需结合原始事件数和曲线判断。",
            ),
            _metric_card(
                "Jank / BigJank",
                f'{frame.get("janky_frames", 0)} / {frame.get("big_jank_frames", 0)}',
                "卡顿事件数。Jank：当前显示帧间隔大于前三帧均值的2倍且超过84ms；BigJank使用相同动态条件且超过125ms。数值越低越好。",
            ),
            _metric_card(
                "Jank/10min",
                _fmt(frame.get("jank_per_10_minutes")),
                "Jank事件数按10分钟折算，便于比较不同时长的测试。越低越好；短测试的折算值波动较大。",
            ),
            _metric_card(
                "BigJank/10min",
                _fmt(frame.get("big_jank_per_10_minutes")),
                "BigJank事件数按10分钟折算，反映严重卡顿密度。越低越好；应同时查看原始BigJank数和FPS曲线。",
            ),
            _metric_card(
                "Avg(FTime)",
                _fmt(frame_time.get("average"), 2, " ms"),
                "相邻两个最终呈现帧之间显示间隔的平均值，单位毫秒，越低越好。参考值：60FPS约16.67ms、120FPS约8.33ms、144FPS约6.94ms、165FPS约6.06ms。",
            ),
            _metric_card(
                "Std(FTime)",
                _fmt(frame_time.get("standard_deviation"), 2, " ms"),
                "显示帧间隔的标准差，单位毫秒。越低表示帧间隔越均匀；平均FPS相同的情况下，此值更低通常体感更平滑。",
            ),
            _metric_card(
                "FrameTime>100ms",
                _fmt(frame.get("frame_time_over_100ms_percent"), 2, "%"),
                "显示帧间隔超过100ms的帧占比。100ms意味着画面至少约0.1秒未更新，越低越好。",
            ),
            _metric_card(
                "P5 / P1 Low",
                f'{_fmt(frame.get("p5_low_fps"))} / {_fmt(frame.get("p1_low_fps"))}',
                "每秒FPS分布的第5和第1百分位数，用于观察低帧尾部表现。P5表示约95%的1秒点不低于该值，P1更关注最差的约1%；两者越高越好。",
            ),
            _metric_card(
                "FPS范围（1秒）",
                f'{_fmt(frame.get("minimum_1s_fps"), 0)}–{_fmt(frame.get("maximum_1s_fps"), 0)}',
                "采集期间所有1秒FPS点的最小值到最大值。范围跨度越小通常越稳定，但需结合平均FPS、标准差和曲线判断。",
            ),
        ]
    )
    resource_metric_cards = "".join(
        [
            _metric_card(
                "App CPU 平均/峰值",
                f'{_fmt(app_cpu.get("average"))}% / {_fmt(app_cpu.get("maximum"))}%',
                "SoloX同口径：目标应用CPU时间占整机全部逻辑核心总时间的比例，范围0–100%；显示采集期平均值和峰值。",
            ),
            _metric_card(
                "Total CPU 平均/峰值",
                f'{_fmt(total_cpu.get("average"))}% / {_fmt(total_cpu.get("maximum"))}%',
                "SoloX同口径：整机非空闲CPU时间占全部逻辑核心总时间的比例，范围0–100%，包含目标应用和系统进程。",
            ),
            _metric_card(
                "GPU占用 平均/峰值",
                f'{_fmt(gpu_usage.get("average"))}% / {_fmt(gpu_usage.get("maximum"))}%',
                "整机GPU忙碌时间占驱动统计窗口的比例。当前仅在已验证的Qualcomm KGSL gpubusy节点上采集；不支持时显示N/A，不以GPU频率或温度代替占用率。",
            ),
            _metric_card(
                "App CPU 单核累加 平均/峰值",
                f'{_fmt(app_cpu_core_aggregate.get("average"))}% / {_fmt(app_cpu_core_aggregate.get("maximum"))}%',
                "诊断口径：应用在所有逻辑核心上的占用率相加。单核满载为100%，多核并行时可超过100%，不作为默认App CPU口径。",
            ),
            _metric_card(
                "Total CPU 单核累加 平均/峰值",
                f'{_fmt(total_cpu_core_aggregate.get("average"))}% / {_fmt(total_cpu_core_aggregate.get("maximum"))}%',
                "诊断口径：整机各逻辑核心占用率相加，理论上限为逻辑核心数×100%。用于分析用了多少个核心的算力。",
            ),
            _metric_card(
                "内存平均/峰值",
                f'{_fmt(memory_summary.get("average"))} / {_fmt(memory_summary.get("maximum"))} MB · '
                f'{_fmt(memory_usage_summary.get("maximum"))}%峰值',
                "目标应用UID下全部进程Total PSS的平均值和峰值，以及占设备物理内存的峰值比例；包含模拟器核心、Wine和PC游戏进程。",
            ),
            _metric_card(
                "CPU最高温度",
                _fmt(cpu_temperature.get("maximum"), 1, "°C"),
                "采集期间设备上可读取CPU温度传感器中的最高值。持续高温可能触发降频并导致FPS下降；不同厂商传感器口径可能不同。",
            ),
        ]
    )
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Android性能测试报告 - {html.escape(session['package_name'])}</title>
<style>
:root{{--bg:#07111f;--panel:#0d1b2d;--panel2:#12243a;--text:#eef6ff;--muted:#8ca3bb;--line:#223b55;--cyan:#4bd6d0;--blue:#5a8cff;--orange:#ffb45c;--red:#ff6b73}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(145deg,#06101c,#0a1728 55%,#08121f);color:var(--text);font:14px/1.55 "Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:34px 24px 70px}} h1{{margin:0;font-size:30px}} h2{{margin:38px 0 14px;font-size:19px}} .sub{{color:var(--muted);margin-top:8px}}
.badge{{display:inline-block;padding:4px 10px;border:1px solid #2b506c;border-radius:99px;color:var(--cyan);margin-right:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin-top:22px}} .metric{{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:14px;padding:16px}}
.metric b{{display:block;font-size:24px;margin-top:7px}} .metric-title{{position:relative;display:flex;align-items:center;gap:7px;color:var(--muted)}}
.metric-help{{display:inline-grid;place-items:center;width:17px;height:17px;padding:0;border:1px solid #476988;border-radius:50%;background:#142b43;color:#a9c9e8;font:700 11px/1 "Segoe UI",sans-serif;cursor:help;transition:.15s ease}}
.metric-help:hover,.metric-help:focus-visible{{outline:none;border-color:var(--cyan);color:#061827;background:var(--cyan);box-shadow:0 0 0 3px rgba(75,214,208,.15)}}
.metric-tooltip{{position:fixed;z-index:20;display:block;padding:12px 13px;border:1px solid #3a6686;border-radius:10px;background:#071522;color:#c8d9e8!important;font-size:13px;line-height:1.6;box-shadow:0 14px 34px rgba(0,0,0,.45);opacity:0;visibility:hidden;pointer-events:none;transition:opacity .12s ease}}
.metric-tooltip strong{{display:block;margin-bottom:4px;color:#fff}}
.metric-help:hover + .metric-tooltip,.metric-help:focus + .metric-tooltip{{opacity:1;visibility:visible}}
.chart-card,.table-card,.note{{background:rgba(13,27,45,.9);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}} .chart-head{{display:flex;justify-content:space-between;color:var(--muted)}} .chart-head strong{{color:var(--text)}}
.evaluation-hero{{display:flex;align-items:center;gap:18px;padding:18px 20px;border:1px solid #2a5871;border-radius:14px;background:linear-gradient(135deg,#102a3c,#0d1b2d)}} .evaluation-grade{{display:grid;place-items:center;width:66px;height:66px;border-radius:50%;background:var(--cyan);color:#06131f;font-size:34px;font-weight:800}} .evaluation-hero strong{{font-size:24px}} .evaluation-hero p{{margin:3px 0;color:#c4d7e7}} .evaluation-hero small{{color:var(--muted)}}
.chart-stage{{position:relative}} .interactive-chart{{display:block;width:100%;height:auto;margin-top:8px;cursor:crosshair;touch-action:none}} .axis{{stroke:#48627b;stroke-width:1.2}} .grid-line{{stroke:#203a52;stroke-width:1}} .grid-line.vertical{{stroke:#182f45}} .axis-label{{fill:#8ca3bb;font-size:12px}} .axis-name{{fill:#9bb0c4;font-size:12px;font-weight:600}}
.hover-line{{stroke:#a9c4dc;stroke-width:1;stroke-dasharray:4 4;opacity:0;pointer-events:none}} .hover-point{{stroke:#fff;stroke-width:2;opacity:0;pointer-events:none}} .interactive-chart.chart-active .hover-line,.interactive-chart.chart-active .hover-point{{opacity:1}} .chart-hitbox{{fill:transparent;pointer-events:all}}
.chart-value-tooltip{{position:absolute;z-index:8;min-width:164px;padding:9px 11px;border:1px solid #3a6686;border-radius:9px;background:rgba(5,18,31,.96);color:#d9e9f6;font-size:12px;line-height:1.55;box-shadow:0 10px 28px rgba(0,0,0,.4);opacity:0;visibility:hidden;pointer-events:none;transform:translate(10px,-50%)}} .chart-value-tooltip strong{{display:block;color:#fff;font-size:13px}} .chart-stage.chart-hovering .chart-value-tooltip{{opacity:1;visibility:visible}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:10px;border-bottom:1px solid var(--line)}} th{{color:var(--muted)}} .empty{{padding:28px;color:var(--muted);border:1px dashed var(--line);border-radius:12px}}
.foot{{margin-top:38px;color:var(--muted);font-size:12px}} code{{color:var(--cyan)}}
</style>
</head>
<body><main class="wrap">
    <span class="badge">Android Perf Lab v0.3.9</span><span class="badge">PerfDog公开口径</span>
  <h1>Android性能测试报告</h1>
  <div class="sub">{html.escape(session['package_name'])} · 设备 {html.escape(session['serial'])} · {html.escape(displayed_started_at)}</div>

  {evaluation_html}

  <div class="grid">
    {fps_metric_cards}
  </div>

  <h2>FPS与资源曲线</h2>
  {_line_svg(fps_values,title='最终呈现FPS（每秒）',color='#4bd6d0',suffix=' FPS')}
  {_line_svg([row.get('app_cpu_normalized_percent') for row in samples],title='App CPU（整机归一化，SoloX同口径）',color='#5a8cff',suffix='%',x_values=sample_times)}
  {_line_svg([row.get('system_cpu_percent') for row in samples],title='Total CPU（整机归一化）',color='#a979ff',suffix='%',x_values=sample_times)}
  {_line_svg([row.get('gpu_usage_percent') for row in samples],title='GPU占用（Qualcomm KGSL驱动窗口）',color='#42d891',suffix='%',x_values=sample_times)}
  {_line_svg([row.get('memory_mb') for row in samples],title='内存 Total PSS',color='#ffb45c',suffix=' MB',x_values=sample_times)}
  {_line_svg([row.get('cpu_temperature_c') for row in samples],title='CPU最高温度',color='#ff6b73',suffix='°C',x_values=sample_times)}

  <h2>资源汇总</h2>
  <div class="grid">
    {resource_metric_cards}
  </div>

  {f'<h2>UID内存进程明细（最后一次采样）</h2><div class="table-card"><table><thead><tr><th>PID</th><th>进程</th><th>PSS</th><th>Swap PSS</th></tr></thead><tbody>{memory_process_rows}</tbody></table></div>' if memory_process_rows else ''}

  <h2>Surface来源</h2>
  <div class="table-card"><table><thead><tr><th>来源</th><th>FPS</th><th>呈现帧</th><th>丢弃帧</th><th>Android Jank</th></tr></thead><tbody>{source_rows}</tbody></table></div>

  <h2>口径说明</h2>
  <div class="note">
    {f'<p><strong>FPS数据提示：</strong>{html.escape(str(frame.get("error")))}</p>' if frame.get('error') else ''}
    <p>主要来源：<code>{html.escape(str(frame.get('primary_source','N/A')))}</code>（{html.escape(str(frame.get('primary_source_reason','')))}）。</p>
    <p>质量信号来源：<code>{html.escape(str(frame.get('quality_source','N/A')))}</code>。</p>
    <p>FPS为1秒真实呈现帧数；FTime为相邻呈现帧的显示间隔。Jank/BigJank使用PerfDog公开阈值公式计算。Android FrameTimeline原生Jank保留在API字段 <code>android_janky_frames</code> 中用于交叉核验。</p>
    <p>CPU默认采用整机归一化口径：App CPU = 应用CPU时间增量 ÷ 全部逻辑核心总CPU时间增量；Total CPU = 整机非空闲时间增量 ÷ 总CPU时间增量，二者范围均为0–100%。报告同时保留“单核累加”诊断值，因此该诊断值在多核并行时可以超过100%。</p>
    <p>{html.escape(gpu_quality_note)}</p>
    <p>盖世游戏开启插帧时，Android最终呈现FPS可能包含生成帧；原始PC游戏渲染FPS需要DXVK/VKD3D侧遥测才能严格区分。</p>
  </div>
  <div class="foot">原始Trace：{html.escape(str(session.get('trace_path','')))}<br>报告数据：{html.escape(metadata_json)}</div>
</main>
<script>
document.querySelectorAll('.metric-help').forEach((button) => {{
  const tooltip = button.nextElementSibling;
  const placeTooltip = () => {{
    const rect = button.getBoundingClientRect();
    const width = Math.min(330, window.innerWidth - 24);
    tooltip.style.width = `${{width}}px`;
    tooltip.style.left = `${{Math.max(12, Math.min(window.innerWidth - width - 12, rect.left + rect.width / 2 - width / 2))}}px`;
    tooltip.style.top = `${{rect.bottom + 9}}px`;
    requestAnimationFrame(() => {{
      if (tooltip.getBoundingClientRect().bottom > window.innerHeight - 12) {{
        tooltip.style.top = `${{Math.max(12, rect.top - tooltip.offsetHeight - 9)}}px`;
      }}
    }});
  }};
  button.addEventListener('mouseenter', placeTooltip);
  button.addEventListener('focus', placeTooltip);
  button.addEventListener('touchstart', placeTooltip, {{passive:true}});
}});
document.querySelectorAll('.interactive-chart').forEach((svg) => {{
  const points = JSON.parse(svg.dataset.points || '[]');
  if (!points.length) return;
  const stage = svg.closest('.chart-stage');
  const tooltip = stage.querySelector('.chart-value-tooltip');
  const hitbox = svg.querySelector('.chart-hitbox');
  const crossX = svg.querySelector('.hover-x');
  const crossY = svg.querySelector('.hover-y');
  const marker = svg.querySelector('.hover-point');
  const unit = svg.dataset.suffix || '';
  const svgPoint = svg.createSVGPoint();
  const showPoint = (event) => {{
    svgPoint.x = event.clientX;
    svgPoint.y = event.clientY;
    const local = svgPoint.matrixTransform(svg.getScreenCTM().inverse());
    const nearest = points.reduce((best, point) =>
      Math.abs(point.x - local.x) < Math.abs(best.x - local.x) ? point : best
    );
    crossX.setAttribute('x1', nearest.x);
    crossX.setAttribute('x2', nearest.x);
    crossY.setAttribute('y1', nearest.y);
    crossY.setAttribute('y2', nearest.y);
    marker.setAttribute('cx', nearest.x);
    marker.setAttribute('cy', nearest.y);
    tooltip.innerHTML = `<strong>${{svg.dataset.title}}</strong><span>时间：${{Number(nearest.time).toFixed(3)}} s</span><br><span>数值：${{Number(nearest.value).toFixed(2)}}${{unit ? ' ' + unit : ''}}</span>`;
    svg.classList.add('chart-active');
    stage.classList.add('chart-hovering');
    const screen = svg.createSVGPoint();
    screen.x = nearest.x;
    screen.y = nearest.y;
    const viewportPoint = screen.matrixTransform(svg.getScreenCTM());
    const stageRect = stage.getBoundingClientRect();
    const desiredLeft = viewportPoint.x - stageRect.left;
    tooltip.style.left = `${{Math.max(4, Math.min(stageRect.width - tooltip.offsetWidth - 14, desiredLeft))}}px`;
    tooltip.style.top = `${{viewportPoint.y - stageRect.top}}px`;
  }};
  const hidePoint = () => {{
    svg.classList.remove('chart-active');
    stage.classList.remove('chart-hovering');
  }};
  hitbox.addEventListener('pointermove', showPoint);
  hitbox.addEventListener('pointerdown', showPoint);
  hitbox.addEventListener('pointerleave', hidePoint);
}});
</script>
</body></html>"""
    report_path.write_text(html_text, encoding="utf-8")
    return report_path
