#!/usr/bin/env python3
"""End-to-end test runner for perfsnap.

Runs real workloads through collect_pidstat.sh, generates synthetic CSVs for
edge cases, then validates the output. All SVGs are saved to examples/ for
visual review.

Usage:
    python3 tests/run_tests.py                # run all tests
    python3 tests/run_tests.py single_proc    # run one test by name
"""
import csv
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "perfsnap" / "scripts"
WORKLOADS = REPO / "tests" / "workloads"
OUTPUT = REPO / "tests" / "output"
EXAMPLES = REPO / "examples"

COLLECTOR = SCRIPTS / "collect_pidstat.sh"
PARSER = SCRIPTS / "pidstat_to_csv.py"
PLOTTER = SCRIPTS / "plot_pidstat_svg.py"

passed = 0
failed = 0


def check(desc: str, condition: bool):
    global passed, failed
    if condition:
        print(f"  PASS: {desc}")
        passed += 1
    else:
        print(f"  FAIL: {desc}")
        failed += 1


def read_csv_rows(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run_collector(name: str, workload_args: list[str],
                  env_vars: dict[str, str] | None = None) -> Path:
    """Run collect_pidstat.sh with a workload and return CSV path."""
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    cmd = [str(COLLECTOR), str(OUTPUT), name, "--"] + workload_args
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"  WARN: collector exited {result.returncode}", file=sys.stderr)
    return OUTPUT / f"{name}.csv"


def run_plotter(csv_path: Path, svg_path: Path, title: str,
                subtitle: str = ""):
    cmd = [sys.executable, str(PLOTTER), str(csv_path), str(svg_path),
           "--title", title]
    if subtitle:
        cmd += ["--subtitle", subtitle]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


# ── Test cases ──────────────────────────────────────────────────────


def test_single_proc():
    """Single process: RSS should ramp then drop."""
    print("\n── single_proc: Single Process Memory Ramp ──")
    csv_path = run_collector(
        "single_proc",
        [sys.executable, str(WORKLOADS / "single_proc.py")],
    )
    rows = read_csv_rows(csv_path)
    check("has samples", len(rows) > 5)

    rss_values = [float(r["rss_mib"]) for r in rows]
    check(f"peak RSS > 50 MiB (got {max(rss_values):.1f})", max(rss_values) > 50)
    check("RSS drops at end", rss_values[-1] < max(rss_values) * 0.5)

    svg = EXAMPLES / "single_proc.svg"
    run_plotter(csv_path, svg, "Single Process (Memory Ramp)",
                "Allocates 10 MiB/s for 10s, then frees everything")
    check("SVG generated", svg.exists() and svg.stat().st_size > 100)


def test_multi_proc():
    """Multiple processes: should see multiple PIDs, RSS aggregated."""
    print("\n── multi_proc: Multi-Process Tree ──")
    csv_path = run_collector(
        "multi_proc",
        [sys.executable, str(WORKLOADS / "multi_proc.py")],
    )
    rows = read_csv_rows(csv_path)
    pids = {r["pid"] for r in rows}
    check(f"captured multiple PIDs (got {len(pids)})", len(pids) >= 3)

    svg = EXAMPLES / "multi_proc.svg"
    run_plotter(csv_path, svg, "Multi-Process Tree",
                "Parent spawns 3 children (staggered), each ~30 MiB RSS + CPU burn")
    svg_text = svg.read_text()
    check("SVG has per-PID legend", "pid " in svg_text)
    check("SVG title says 'total'", "total" in svg_text)


def test_thread_mode():
    """Thread-level: tid column should be populated."""
    print("\n── thread_mode: Thread-Level Collection ──")
    csv_path = run_collector(
        "thread_mode",
        [sys.executable, str(WORKLOADS / "thread_mode.py")],
        env_vars={"PIDSTAT_THREAD": "1"},
    )
    rows = read_csv_rows(csv_path)
    check("has samples", len(rows) > 0)

    tids = [r["tid"] for r in rows if r["tid"].strip()]
    check(f"tid column populated (got {len(tids)} thread rows)", len(tids) > 0)

    rss_values = [float(r["rss_mib"]) for r in rows if float(r["rss_mib"]) > 0]
    if rss_values:
        check(f"RSS > 50 MiB (got {max(rss_values):.1f})", max(rss_values) > 50)

    svg = EXAMPLES / "thread_mode.svg"
    run_plotter(csv_path, svg, "Thread-Level Mode",
                "4 threads, each 20 MiB + CPU burn (GIL limits parallelism)")
    check("SVG generated", svg.exists() and svg.stat().st_size > 100)


def test_cpu_multicore():
    """4 CPU-bound processes: total CPU should approach 400%."""
    print("\n── cpu_multicore: Multi-Core CPU ──")
    csv_path = run_collector(
        "cpu_multicore",
        [sys.executable, str(WORKLOADS / "cpu_multicore.py")],
    )
    rows = read_csv_rows(csv_path)
    pids = {r["pid"] for r in rows}
    check(f"captured 5 PIDs (got {len(pids)})", len(pids) >= 4)

    # Aggregate CPU per timestamp
    from collections import defaultdict
    ts_cpu: dict[str, float] = defaultdict(float)
    for r in rows:
        ts_cpu[r["timestamp_s"]] += float(r["cpu_pct"])
    peak_total_cpu = max(ts_cpu.values()) if ts_cpu else 0
    check(f"peak total CPU > 300% (got {peak_total_cpu:.0f}%)", peak_total_cpu > 300)

    svg = EXAMPLES / "cpu_multicore.svg"
    run_plotter(csv_path, svg, "Multi-Core CPU (4 Processes)",
                "4 CPU-bound processes, each pinning ~100% of one core for 8s")
    check("SVG generated", svg.exists())


def test_cpu_48core():
    """48 CPU-bound processes: total CPU should approach 4800%."""
    print("\n── cpu_48core: 48-Core CPU ──")
    csv_path = run_collector(
        "cpu_48core",
        [sys.executable, str(WORKLOADS / "cpu_48core.py")],
    )
    rows = read_csv_rows(csv_path)
    pids = {r["pid"] for r in rows}
    check(f"captured many PIDs (got {len(pids)})", len(pids) >= 40)

    from collections import defaultdict
    ts_cpu: dict[str, float] = defaultdict(float)
    for r in rows:
        ts_cpu[r["timestamp_s"]] += float(r["cpu_pct"])
    peak_total_cpu = max(ts_cpu.values()) if ts_cpu else 0
    check(f"peak total CPU > 4000% (got {peak_total_cpu:.0f}%)", peak_total_cpu > 4000)

    svg = EXAMPLES / "cpu_48core.svg"
    run_plotter(csv_path, svg, "48-Core CPU",
                "48 CPU-bound processes, each pinning ~100% of one core for 8s")
    svg_text = svg.read_text()
    check("SVG generated", svg.exists())
    check("no per-PID legend (too many PIDs)", "pid " not in svg_text)
    check("title shows pid count", "48 pids" in svg_text or "49 pids" in svg_text)


def test_interval_2s():
    """Non-default interval: timestamps should be 2s apart."""
    print("\n── interval_2s: Custom Sample Interval ──")
    csv_path = run_collector(
        "interval_2s",
        [sys.executable, str(WORKLOADS / "single_proc.py")],
        env_vars={"PIDSTAT_INTERVAL": "2"},
    )
    rows = read_csv_rows(csv_path)
    check("has samples", len(rows) > 2)

    timestamps = [float(r["timestamp_s"]) for r in rows]
    if len(timestamps) >= 2:
        gap = timestamps[1] - timestamps[0]
        check(f"timestamp gap ~2s (got {gap:.0f}s)", 1.5 <= gap <= 3.0)

    svg = EXAMPLES / "interval_2s.svg"
    run_plotter(csv_path, svg, "Custom Interval (2s)",
                "Same single-process workload, sampled every 2s instead of 1s")
    check("SVG generated", svg.exists())


def test_sim_long_duration():
    """Synthetic 2h CSV: tests X-axis formatting with minute labels."""
    print("\n── sim_long_duration: Simulated 2h Build ──")
    csv_path = OUTPUT / "sim_2h.csv"
    subprocess.run(
        [sys.executable, str(WORKLOADS / "sim_long_duration.py"), str(csv_path)],
        check=True, capture_output=True,
    )
    rows = read_csv_rows(csv_path)
    check(f"has 1440 samples (got {len(rows)})", len(rows) == 1440)

    rss_values = [float(r["rss_mib"]) for r in rows]
    check(f"peak RSS ~2048 MiB (got {max(rss_values):.0f})", max(rss_values) > 2000)

    svg = EXAMPLES / "sim_2h.svg"
    run_plotter(csv_path, svg, "Simulated 2h Build",
                "Synthetic: RSS ramps during compile, plateaus, drops at cleanup. CPU ~350% multi-core.")
    svg_text = svg.read_text()
    check("X-axis uses minute labels", "15m" in svg_text)
    check("no raw seconds in labels", "900s" not in svg_text)


# ── Main ────────────────────────────────────────────────────────────

ALL_TESTS = {
    "single_proc": test_single_proc,
    "multi_proc": test_multi_proc,
    "thread_mode": test_thread_mode,
    "cpu_multicore": test_cpu_multicore,
    "cpu_48core": test_cpu_48core,
    "interval_2s": test_interval_2s,
    "sim_long_duration": test_sim_long_duration,
}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    EXAMPLES.mkdir(parents=True, exist_ok=True)

    selected = sys.argv[1:] if len(sys.argv) > 1 else list(ALL_TESTS.keys())
    for name in selected:
        if name not in ALL_TESTS:
            print(f"Unknown test: {name}")
            print(f"Available: {', '.join(ALL_TESTS.keys())}")
            return 1
        ALL_TESTS[name]()

    print(f"\n{'=' * 50}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    if failed:
        print("  SOME TESTS FAILED")
        return 1
    print("  All tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
