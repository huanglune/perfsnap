#!/usr/bin/env python3
"""Convert pidstat -r -u -h output to a clean CSV file.

Uses header-based column detection so it works across sysstat versions.
Supports optional PID filtering (--pid-filter) for process-tree monitoring
and preserves thread identity (tid) when pidstat -t data is present.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

# Canonical output columns (always written, even if some are 0).
# tid is included so thread-level data is preserved when collected.
OUTPUT_FIELDS = [
    "sample_index",
    "timestamp_s",
    "pid",
    "tid",
    "user_pct",
    "system_pct",
    "guest_pct",
    "wait_pct",
    "cpu_pct",
    "cpu_core",
    "minflt_s",
    "majflt_s",
    "vsz_kb",
    "rss_kb",
    "rss_mib",
    "mem_pct",
    "command",
]

# Map lowercased pidstat header names to our canonical field names.
# pidstat headers vary by version; this covers the common variants.
HEADER_MAP = {
    "time": "timestamp_s",
    "pid": "pid",
    "tgid": "pid",  # pidstat -t uses TGID instead of PID
    "tid": "tid",
    "%usr": "user_pct",
    "%user": "user_pct",
    "%system": "system_pct",
    "%sys": "system_pct",
    "%guest": "guest_pct",
    "%wait": "wait_pct",
    "%cpu": "cpu_pct",
    "cpu": "cpu_core",
    "minflt/s": "minflt_s",
    "majflt/s": "majflt_s",
    "vsz": "vsz_kb",
    "rss": "rss_kb",
    "%mem": "mem_pct",
    "command": "command",
}

FLOAT_FIELDS = {
    "user_pct",
    "system_pct",
    "guest_pct",
    "wait_pct",
    "cpu_pct",
    "minflt_s",
    "majflt_s",
    "vsz_kb",
    "rss_kb",
    "mem_pct",
}


def load_pid_filter(path: str) -> set[str] | None:
    """Load a set of PIDs from a file (one per line). Returns None if no filter."""
    if not path:
        return None
    try:
        pids = set()
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line:
                pids.add(line)
        return pids if pids else None
    except FileNotFoundError:
        print(f"WARNING: pid filter file not found: {path}", file=sys.stderr)
        return None


def parse_timestamp(token: str) -> float | None:
    """Parse a timestamp token. Returns epoch float or None if unparseable."""
    # Epoch seconds (most common with LC_ALL=C + pidstat -h)
    try:
        return float(token)
    except ValueError:
        pass
    # HH:MM:SS wall-clock format — cannot convert to absolute time,
    # but we can convert to seconds-since-midnight for relative offsets.
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})", token)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return float(h * 3600 + m * 60 + s)
    return None


def parse_pidstat(input_path: str, pid_filter: set[str] | None = None) -> list[dict]:
    """Parse pidstat -h output using dynamic header detection.

    Handles two timestamp formats:
    - Epoch seconds: "1717000000 ..." (one token)
    - 12-hour clock: "05:46:40 AM ..." (two tokens — AM/PM shifts columns by 1)
    """
    samples: list[dict] = []
    col_map: dict[int, str] = {}  # column index -> canonical field name
    current_tgid: str = ""  # track TGID for thread rows where TGID is "-"

    with open(input_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue

            # Header line: starts with '#'
            if line.startswith("#"):
                cols = line.lstrip("#").split()
                col_map = {}
                for i, col in enumerate(cols):
                    canonical = HEADER_MAP.get(col.lower(), HEADER_MAP.get(col, None))
                    if canonical:
                        col_map[i] = canonical
                continue

            if not col_map:
                continue

            parts = line.split()
            if len(parts) < len(col_map):
                continue

            # Detect AM/PM offset: if second token is AM/PM, data columns
            # are shifted by 1 compared to the header indices.
            offset = 0
            if len(parts) > 1 and parts[1].upper() in ("AM", "PM"):
                offset = 1

            timestamp = parse_timestamp(parts[0])
            if timestamp is None:
                continue

            row: dict = {"timestamp_s": timestamp}
            for i, field in col_map.items():
                actual_i = i + offset
                if actual_i >= len(parts):
                    continue
                if field == "timestamp_s":
                    continue
                val = parts[actual_i]
                # In thread mode, pidstat uses "-" for TGID on thread rows
                # and "-" for TID on process rows. Skip dash values.
                if val == "-":
                    continue
                if field in FLOAT_FIELDS:
                    try:
                        row[field] = float(val)
                    except ValueError:
                        row[field] = 0.0
                else:
                    row[field] = val

            # In thread mode (TGID/TID columns present):
            # - Process rows have pid set (from TGID), tid absent
            # - Thread rows have tid set, pid absent — inherit from last process row
            if "pid" in row and row["pid"] != "-":
                current_tgid = row["pid"]
            elif "pid" not in row and current_tgid:
                row["pid"] = current_tgid

            # Strip |__ prefix from thread command names
            cmd = row.get("command", "")
            if cmd.startswith("|__"):
                row["command"] = cmd[3:]

            # Need at least one metric to be useful
            if "cpu_pct" not in row and "rss_kb" not in row:
                continue

            # Apply PID filter if provided
            if pid_filter is not None:
                pid_val = str(row.get("pid", ""))
                if pid_val not in pid_filter:
                    continue

            samples.append(row)

    return samples


def write_csv(samples: list[dict], output_path: str) -> None:
    """Write samples to CSV with consistent schema."""
    if not samples:
        print("WARNING: no samples parsed from pidstat output", file=sys.stderr)
        Path(output_path).write_text(",".join(OUTPUT_FIELDS) + "\n")
        return

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for idx, raw in enumerate(samples):
            rss_kb = raw.get("rss_kb", 0.0)
            row = {
                "sample_index": idx,
                "timestamp_s": f"{raw.get('timestamp_s', 0):.0f}",
                "pid": raw.get("pid", ""),
                "tid": raw.get("tid", ""),
                "user_pct": f"{raw.get('user_pct', 0):.2f}",
                "system_pct": f"{raw.get('system_pct', 0):.2f}",
                "guest_pct": f"{raw.get('guest_pct', 0):.2f}",
                "wait_pct": f"{raw.get('wait_pct', 0):.2f}",
                "cpu_pct": f"{raw.get('cpu_pct', 0):.2f}",
                "cpu_core": raw.get("cpu_core", ""),
                "minflt_s": f"{raw.get('minflt_s', 0):.2f}",
                "majflt_s": f"{raw.get('majflt_s', 0):.2f}",
                "vsz_kb": f"{raw.get('vsz_kb', 0):.0f}",
                "rss_kb": f"{rss_kb:.0f}",
                "rss_mib": f"{rss_kb / 1024:.2f}",
                "mem_pct": f"{raw.get('mem_pct', 0):.2f}",
                "command": raw.get("command", ""),
            }
            writer.writerow(row)

    print(f"  CSV: {len(samples)} samples -> {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pidstat", help="Raw pidstat output file")
    parser.add_argument("output_csv", help="Output CSV path")
    parser.add_argument(
        "--pid-filter",
        default="",
        help="File containing PIDs to keep (one per line)",
    )
    args = parser.parse_args()

    pid_filter = load_pid_filter(args.pid_filter)
    samples = parse_pidstat(args.input_pidstat, pid_filter)
    write_csv(samples, args.output_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
