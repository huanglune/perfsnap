"""Generate a synthetic 2-hour CSV directly (no real workload needed).

This creates a CSV that looks like it came from a 2h build: RSS ramps up,
plateaus during compilation, then drops during cleanup. CPU shows ~350%
multi-core usage with periodic bursts.

Usage: python3 sim_long_duration.py <output.csv>
"""
import csv
import math
import random
import sys

random.seed(42)

FIELDS = [
    "sample_index", "timestamp_s", "pid", "tid", "user_pct", "system_pct",
    "guest_pct", "wait_pct", "cpu_pct", "cpu_core", "minflt_s", "majflt_s",
    "vsz_kb", "rss_kb", "rss_mib", "mem_pct", "command",
]

DURATION = 7200  # 2 hours
INTERVAL = 5


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout"
    n_samples = DURATION // INTERVAL

    with open(output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i in range(n_samples):
            t = i * INTERVAL
            if t < 3600:
                rss_mib = 200 + 1848 * (t / 3600) ** 0.7
            elif t < 6000:
                rss_mib = 2048 + random.uniform(-20, 20)
            else:
                rss_mib = 2048 * max(0.1, 1 - (t - 6000) / 1200)

            phase = (t % 600) / 600
            cpu_base = 350 if t < 5400 else 80
            cpu = cpu_base + 50 * math.sin(phase * math.pi)
            cpu += random.uniform(-15, 15)
            cpu = max(0, cpu)
            rss_kb = rss_mib * 1024

            w.writerow({
                "sample_index": i, "timestamp_s": 1000 + t,
                "pid": "99999", "tid": "",
                "user_pct": f"{cpu * 0.85:.2f}",
                "system_pct": f"{cpu * 0.15:.2f}",
                "guest_pct": "0.00", "wait_pct": "0.00",
                "cpu_pct": f"{cpu:.2f}", "cpu_core": "0",
                "minflt_s": "0.00", "majflt_s": "0.00",
                "vsz_kb": f"{rss_kb * 1.3:.0f}",
                "rss_kb": f"{rss_kb:.0f}",
                "rss_mib": f"{rss_mib:.2f}",
                "mem_pct": f"{rss_mib / 32768 * 100:.2f}",
                "command": "make",
            })

    print(f"Generated {n_samples} samples -> {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
