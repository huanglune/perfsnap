#!/usr/bin/env python3
"""Render a two-panel SVG chart (RSS MiB + CPU %) from a pidstat CSV file.

Handles multi-process and multi-thread data by:
- Aggregating RSS and CPU per timestamp across all PIDs (total line)
- Drawing per-PID breakdown lines when multiple PIDs are present

Usage:
    python3 plot_pidstat_svg.py input.csv output.svg [--title "My Build"]
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

# Color palette for per-PID lines
PID_COLORS = [
    "#3b82f6",
    "#ef4444",
    "#22c55e",
    "#f59e0b",
    "#8b5cf6",
    "#ec4899",
    "#06b6d4",
    "#f97316",
]
TOTAL_RSS_COLOR = "#1d4ed8"
TOTAL_CPU_COLOR = "#b91c1c"


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def aggregate_by_timestamp(
    rows: list[dict],
) -> tuple[
    list[tuple[float, float, float]], dict[str, list[tuple[float, float, float]]]
]:
    """Group rows by timestamp, aggregate RSS and CPU across PIDs.

    For thread mode: process-level rows (tid empty) carry aggregate data per PID.
    Thread rows (tid non-empty) are skipped for RSS (shared address space) but
    their CPU is already included in the process-level aggregate.

    Returns:
        totals: [(relative_t, total_rss_mib, total_cpu_pct), ...]
        per_pid: {pid: [(relative_t, rss_mib, cpu_pct), ...]}
    """
    has_threads = any(r.get("tid", "").strip() for r in rows)

    # Group: timestamp -> pid -> best row (prefer process-level over thread rows)
    ts_pid_rows: dict[float, dict[str, dict]] = defaultdict(dict)

    for r in rows:
        ts = float(r.get("timestamp_s", 0))
        pid = r.get("pid", "unknown")
        tid = r.get("tid", "").strip()

        if has_threads:
            # In thread mode: keep only process-level rows (tid empty) per PID,
            # they already have aggregate CPU and correct RSS.
            if tid:
                continue

        # Keep first row per (timestamp, pid) — dedup
        if pid not in ts_pid_rows[ts]:
            ts_pid_rows[ts][pid] = r

    if not ts_pid_rows:
        return [], {}

    sorted_ts = sorted(ts_pid_rows.keys())
    t0 = sorted_ts[0]

    totals: list[tuple[float, float, float]] = []
    per_pid: dict[str, list[tuple[float, float, float]]] = defaultdict(list)

    for ts in sorted_ts:
        t_rel = ts - t0
        total_rss = 0.0
        total_cpu = 0.0
        for pid, r in ts_pid_rows[ts].items():
            rss = (
                float(r["rss_mib"])
                if r.get("rss_mib")
                else float(r.get("rss_kb", 0)) / 1024
            )
            cpu = float(r.get("cpu_pct", 0))
            total_rss += rss
            total_cpu += cpu
            per_pid[pid].append((t_rel, rss, cpu))
        totals.append((t_rel, total_rss, total_cpu))

    return totals, dict(per_pid)


def svg_polyline(
    points: list[tuple[float, float]],
    color: str,
    stroke_width: float = 1.5,
    dash: str = "",
) -> str:
    if not points:
        return ""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width}"{extra}/>'
    )


def svg_filled_area(
    points: list[tuple[float, float]],
    baseline_y: float,
    color: str,
    opacity: float = 0.15,
) -> str:
    if not points:
        return ""
    pts = [f"{points[0][0]:.1f},{baseline_y:.1f}"]
    pts += [f"{x:.1f},{y:.1f}" for x, y in points]
    pts.append(f"{points[-1][0]:.1f},{baseline_y:.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{color}" opacity="{opacity}"/>'


def _time_ticks(duration: float, max_ticks: int = 8) -> tuple[list[float], float]:
    """Generate round tick values for a time axis spanning `duration` seconds.

    Returns (tick_values, step). The step determines the display unit so all
    labels use a consistent unit with no fractional values.
    """
    nice_steps = [
        1,
        2,
        5,
        10,
        15,
        30,  # seconds
        60,
        120,
        300,
        600,
        900,
        1800,  # minutes
        3600,
        7200,
        14400,
        28800,
        86400,  # hours / day
    ]
    raw_step = duration / max_ticks
    chosen = nice_steps[-1]
    for ns in nice_steps:
        if ns >= raw_step:
            chosen = ns
            break

    ticks = []
    t = 0.0
    while t <= duration + 1e-9:
        ticks.append(t)
        t += chosen
    # Include endpoint if not already covered
    if ticks and abs(ticks[-1] - duration) > chosen * 0.1:
        ticks.append(duration)
    return ticks, chosen


def _fmt_tick(seconds: float, step: float) -> str:
    """Format a tick value using a unit consistent with the step size.

    step < 60  → all labels in seconds (e.g. 0s, 15s, 30s, ..., 120s)
    step < 3600 → all labels in minutes (e.g. 0m, 5m, 10m, ..., 120m)
    step >= 3600 → all labels in hours  (e.g. 0h, 1h, 2h, ..., 8h)
    """
    if step < 60:
        return f"{seconds:.0f}s"
    if step < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.0f}h"


def _nice_y_ticks(raw_max: float, target_ticks: int = 5) -> list[float]:
    """Generate round Y-axis tick values that cover raw_max with some headroom.

    Picks a step from powers-of-10 scaled by 1, 2, or 5 (the classic
    "nice numbers" algorithm), so ticks read as 0, 100, 200... or
    0, 50, 100... or 0, 0.5, 1.0... depending on scale.
    """
    if raw_max <= 0:
        return [0.0, 1.0]

    rough_step = raw_max / target_ticks
    # Find the magnitude
    import math

    mag = 10 ** math.floor(math.log10(rough_step))
    residual = rough_step / mag  # 1.0 <= residual < 10.0

    if residual <= 1.5:
        nice_step = 1 * mag
    elif residual <= 3.5:
        nice_step = 2 * mag
    elif residual <= 7.5:
        nice_step = 5 * mag
    else:
        nice_step = 10 * mag

    # Build ticks from 0 up to (and just past) raw_max
    ticks = []
    v = 0.0
    while v <= raw_max + nice_step * 0.01:
        ticks.append(v)
        v += nice_step
    # Ensure we have at least one tick above raw_max (headroom)
    if ticks[-1] < raw_max:
        ticks.append(ticks[-1] + nice_step)

    return ticks


def render_panel(
    total_series: list[tuple[float, float]],
    pid_series: dict[str, list[tuple[float, float]]],
    x_offset: float,
    y_offset: float,
    width: float,
    height: float,
    total_color: str,
    y_label: str,
    y_unit: str,
) -> str:
    if not total_series:
        return ""

    margin_left = 70
    margin_right = 20
    margin_top = 30
    margin_bottom = 35
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    px = x_offset + margin_left
    py = y_offset + margin_top

    times = [s[0] for s in total_series]
    values = [s[1] for s in total_series]
    t_min, t_max = min(times), max(times)

    # Y-axis: snap to nice round ticks
    raw_max = max(values) if max(values) > 0 else 1
    y_ticks = _nice_y_ticks(raw_max)
    v_max = y_ticks[-1]

    def map_x(t: float) -> float:
        if t_max == t_min:
            return px + plot_w / 2
        return px + (t - t_min) / (t_max - t_min) * plot_w

    def map_y(v: float) -> float:
        return py + plot_h - v / v_max * plot_h

    parts: list[str] = []

    # Background
    parts.append(
        f'<rect x="{px}" y="{py}" width="{plot_w}" height="{plot_h}" '
        f'fill="#fafafa" stroke="#ddd"/>'
    )

    # Y gridlines
    y_step = y_ticks[1] - y_ticks[0] if len(y_ticks) > 1 else v_max
    if y_step < 1:
        y_fmt = ".2f"
    elif y_step < 10:
        y_fmt = ".1f"
    else:
        y_fmt = ".0f"

    for val in y_ticks:
        yy = map_y(val)
        parts.append(
            f'<line x1="{px}" y1="{yy:.1f}" x2="{px + plot_w}" y2="{yy:.1f}" '
            f'stroke="#eee" stroke-width="0.5"/>'
        )
        parts.append(
            f'<text x="{px - 8}" y="{yy + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#666">{val:{y_fmt}}</text>'
        )

    # X-axis labels — auto-select unit and snap to round tick values
    duration = t_max - t_min
    if duration > 0:
        ticks, step = _time_ticks(duration)
        for tick_sec in ticks:
            label = _fmt_tick(tick_sec, step)
            parts.append(
                f'<text x="{map_x(t_min + tick_sec):.1f}" y="{py + plot_h + 20}" '
                f'text-anchor="middle" font-size="11" fill="#666">{label}</text>'
            )

    n_pids = len(pid_series)
    multi_pid = n_pids > 1
    # Only draw per-PID breakdown when the count is manageable
    max_pid_lines = 8
    show_breakdown = multi_pid and n_pids <= max_pid_lines

    # Per-PID lines (lighter, dashed) — only for small PID counts
    if show_breakdown:
        for idx, (pid, series) in enumerate(sorted(pid_series.items())):
            color = PID_COLORS[idx % len(PID_COLORS)]
            pts = [(map_x(t), map_y(v)) for t, v in series]
            parts.append(svg_polyline(pts, color, stroke_width=1.0, dash="4,3"))

    # Total line + filled area (bold, solid)
    pts = [(map_x(t), map_y(v)) for t, v in total_series]
    parts.append(svg_filled_area(pts, py + plot_h, total_color, 0.12))
    parts.append(svg_polyline(pts, total_color, stroke_width=2.0 if multi_pid else 1.5))

    # Panel title
    if multi_pid:
        label_suffix = f" total ({n_pids} pids)"
    else:
        label_suffix = ""
    parts.append(
        f'<text x="{px + plot_w / 2}" y="{y_offset + 18}" text-anchor="middle" '
        f'font-size="13" font-weight="bold" fill="#333">{y_label}{label_suffix} ({y_unit})</text>'
    )

    # Legend — only for breakdown view
    if show_breakdown:
        legend_x = px + plot_w - 10
        legend_y = py + 14
        for idx, (pid, _) in enumerate(sorted(pid_series.items())):
            color = PID_COLORS[idx % len(PID_COLORS)]
            ly = legend_y + idx * 14
            parts.append(
                f'<line x1="{legend_x - 40}" y1="{ly}" x2="{legend_x - 20}" '
                f'y2="{ly}" stroke="{color}" stroke-width="1.5" stroke-dasharray="4,3"/>'
            )
            parts.append(
                f'<text x="{legend_x - 16}" y="{ly + 4}" font-size="9" '
                f'fill="#666">pid {pid}</text>'
            )

    return "\n".join(parts)


def render_no_data(title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="200" '
        f'font-family="monospace">\n'
        f'  <rect width="100%" height="100%" fill="white"/>\n'
        f'  <text x="40" y="60" font-size="24" fill="#111827">{title}</text>\n'
        f'  <text x="40" y="100" font-size="14" fill="#6b7280">'
        f"No pidstat samples found.</text>\n"
        f"</svg>"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("output_svg")
    parser.add_argument("--title", default="Performance Metrics")
    parser.add_argument(
        "--subtitle", default="", help="Scenario description shown below the title"
    )
    args = parser.parse_args()

    rows = read_csv(args.input_csv)
    if not rows:
        Path(args.output_svg).write_text(render_no_data(args.title))
        print("  SVG: no data, wrote placeholder", file=sys.stderr)
        return 0

    totals, per_pid = aggregate_by_timestamp(rows)
    if not totals:
        Path(args.output_svg).write_text(render_no_data(args.title))
        print("  SVG: no data after aggregation, wrote placeholder", file=sys.stderr)
        return 0

    # Build per-metric series
    rss_total = [(t, rss) for t, rss, _ in totals]
    cpu_total = [(t, cpu) for t, _, cpu in totals]
    rss_per_pid = {pid: [(t, rss) for t, rss, _ in s] for pid, s in per_pid.items()}
    cpu_per_pid = {pid: [(t, cpu) for t, _, cpu in s] for pid, s in per_pid.items()}

    width = 900
    panel_height = 250
    subtitle = args.subtitle
    # Extra space for subtitle line if present
    subtitle_height = 18 if subtitle else 0
    title_height = 50 + subtitle_height
    gap = 20
    total_height = title_height + panel_height * 2 + gap * 2

    # Summary
    rss_vals = [rss for _, rss in rss_total]
    cpu_vals = [cpu for _, cpu in cpu_total]
    n_pids = len(per_pid)
    pid_info = f"  pids={n_pids}" if n_pids > 1 else ""
    summary = (
        f"samples={len(rows)}{pid_info}  "
        f"peak_rss={max(rss_vals):.1f} MiB  "
        f"avg_rss={mean(rss_vals):.1f} MiB  "
        f"peak_cpu={max(cpu_vals):.1f}%  "
        f"avg_cpu={mean(cpu_vals):.1f}%"
    )

    # Header: title, optional subtitle, summary
    header_parts: list[str] = [
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="16" '
        f'font-weight="bold" fill="#222">{args.title}</text>',
    ]
    if subtitle:
        header_parts.append(
            f'<text x="{width / 2}" y="42" text-anchor="middle" font-size="11" '
            f'fill="#666" font-style="italic">{subtitle}</text>'
        )
    header_parts.append(
        f'<text x="{width / 2}" y="{42 + subtitle_height}" text-anchor="middle" '
        f'font-size="11" fill="#888">{summary}</text>'
    )

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{total_height}" font-family="monospace">',
        f'<rect width="{width}" height="{total_height}" fill="white"/>',
        *header_parts,
        render_panel(
            rss_total,
            rss_per_pid,
            0,
            title_height,
            width,
            panel_height,
            TOTAL_RSS_COLOR,
            "RSS",
            "MiB",
        ),
        render_panel(
            cpu_total,
            cpu_per_pid,
            0,
            title_height + panel_height + gap,
            width,
            panel_height,
            TOTAL_CPU_COLOR,
            "CPU",
            "%",
        ),
        "</svg>",
    ]

    svg_content = "\n".join(parts)
    Path(args.output_svg).write_text(svg_content, encoding="utf-8")
    print(f"  SVG: {args.output_svg} ({len(rss_total)} timestamps, {n_pids} pid(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
