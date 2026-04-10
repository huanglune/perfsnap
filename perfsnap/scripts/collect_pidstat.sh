#!/usr/bin/env bash
# Usage: collect_pidstat.sh <output-dir> <prefix> -- <command...>
#
# Launches <command> in the background, monitors it and all its descendant
# processes with pidstat, then generates CSV + SVG when it finishes.
#
# Environment variables:
#   PIDSTAT_INTERVAL  — sample interval in seconds (default: 1)
#   PIDSTAT_THREAD    — set to 1 for thread-level collection (-t flag)
#   PIDSTAT_KEEP_RAW  — set to 1 to keep the raw .pidstat file
set -euo pipefail

usage() {
  echo "Usage: $0 <output-dir> <prefix> -- <command...>" >&2
  echo "Example: $0 /tmp/perf gist_vamana -- ./build/apps/build_memory_index --data_type float" >&2
}

if [[ $# -lt 4 ]]; then
  usage
  exit 1
fi

output_dir=$1
prefix=$2
shift 2

if [[ $1 != "--" ]]; then
  usage
  exit 1
fi
shift

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

# Prerequisites
if ! command -v pidstat >/dev/null 2>&1; then
  echo "ERROR: pidstat not found; install sysstat first." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found." >&2
  exit 1
fi

mkdir -p "$output_dir"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
interval=${PIDSTAT_INTERVAL:-1}
thread_flag=${PIDSTAT_THREAD:-0}
keep_raw=${PIDSTAT_KEEP_RAW:-0}

pidstat_log="$output_dir/$prefix.pidstat"
stdout_log="$output_dir/$prefix.stdout.log"
csv_path="$output_dir/$prefix.csv"
svg_path="$output_dir/$prefix.svg"
pids_file="$output_dir/$prefix.pids"

# Force epoch timestamps and English headers across all sysstat versions
export LC_ALL=C

pidstat_flags="-r -u -h"
if [[ "$thread_flag" == "1" ]]; then
  pidstat_flags="-t -r -u -h"
fi

echo "=== Collecting pidstat metrics ==="
echo "  Command:  $*"
echo "  Output:   $output_dir/$prefix.*"
echo "  Interval: ${interval}s"
echo "  Thread:   $([[ $thread_flag == 1 ]] && echo yes || echo no)"

start_ts=$(date +%s.%N)

# Launch the target command in the background, capturing stdout+stderr
"$@" > "$stdout_log" 2>&1 &
cmd_pid=$!
echo "  PID:      $cmd_pid"

# Sidecar: periodically collect the entire descendant process tree.
# This runs alongside pidstat so we know which PIDs belong to our command.
collect_tree() {
  local parent=$1
  echo "$parent"
  local children
  children=$(pgrep -P "$parent" 2>/dev/null) || true
  for child in $children; do
    collect_tree "$child"
  done
}
(
  while kill -0 "$cmd_pid" 2>/dev/null; do
    collect_tree "$cmd_pid"
    sleep "${interval}"
  done
  # Final sweep after command exits — catch short-lived children
  collect_tree "$cmd_pid" 2>/dev/null || true
) > "$pids_file" 2>/dev/null &
tracker_pid=$!

# Monitor ALL processes; we filter by our PID list in post-processing.
# shellcheck disable=SC2086
pidstat $pidstat_flags -p ALL "$interval" > "$pidstat_log" 2>/dev/null &
pidstat_pid=$!

# Wait for the target command to finish
set +e
wait "$cmd_pid"
command_status=$?
set -e

# Stop sidecar and pidstat
sleep 1
kill "$tracker_pid" 2>/dev/null || true
kill "$pidstat_pid" 2>/dev/null || true
wait "$tracker_pid" 2>/dev/null || true
wait "$pidstat_pid" 2>/dev/null || true

end_ts=$(date +%s.%N)

echo "  Exit:     $command_status"

# Deduplicate the collected PIDs
sort -un "$pids_file" -o "$pids_file"

# Generate CSV (filtered to our process tree) and SVG
python3 "$script_dir/pidstat_to_csv.py" "$pidstat_log" "$csv_path" \
  --pid-filter "$pids_file"
python3 "$script_dir/plot_pidstat_svg.py" "$csv_path" "$svg_path" --title "$prefix"

# Print summary
summary_json=$(python3 - "$csv_path" <<'PY'
import csv
import json
import sys

path = sys.argv[1]
sample_count = 0
peak_rss_kb = 0.0
peak_cpu_pct = 0.0
avg_rss_kb = 0.0
avg_cpu_pct = 0.0

with open(path, newline="", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        sample_count += 1
        rss = float(row.get("rss_kb", 0))
        cpu = float(row.get("cpu_pct", 0))
        peak_rss_kb = max(peak_rss_kb, rss)
        peak_cpu_pct = max(peak_cpu_pct, cpu)
        avg_rss_kb += rss
        avg_cpu_pct += cpu

if sample_count:
    avg_rss_kb /= sample_count
    avg_cpu_pct /= sample_count

print(json.dumps({
    "sample_count": sample_count,
    "peak_rss_kb": peak_rss_kb,
    "peak_cpu_pct": peak_cpu_pct,
    "avg_rss_kb": avg_rss_kb,
    "avg_cpu_pct": avg_cpu_pct,
}))
PY
)

elapsed_sec=$(awk -v s="$start_ts" -v e="$end_ts" 'BEGIN { printf "%.2f", e - s }')
elapsed_hms=$(awk -v s="$start_ts" -v e="$end_ts" 'BEGIN { elapsed = e - s; m = int(elapsed / 60); sec = elapsed - m * 60; printf "%d:%05.2f", m, sec }')

# Clean up intermediate files unless asked to keep them
if [[ "$keep_raw" != "1" ]]; then
  rm -f "$pidstat_log" "$pids_file"
fi

# Print structured summary
SUMMARY_JSON="$summary_json" ELAPSED_SEC="$elapsed_sec" ELAPSED_HMS="$elapsed_hms" \
EXIT_CODE="$command_status" INTERVAL="$interval" \
CSV_PATH="$csv_path" SVG_PATH="$svg_path" STDOUT_LOG="$stdout_log" \
python3 - <<'PY'
import json
import os

summary = json.loads(os.environ["SUMMARY_JSON"])
print(f"csv={os.environ['CSV_PATH']}")
print(f"svg={os.environ['SVG_PATH']}")
print(f"stdout_log={os.environ['STDOUT_LOG']}")
print(f"elapsed_sec={os.environ['ELAPSED_SEC']}")
print(f"elapsed_hms={os.environ['ELAPSED_HMS']}")
print(f"exit_code={os.environ['EXIT_CODE']}")
print(f"sample_interval_sec={os.environ['INTERVAL']}")
print(f"sample_count={summary['sample_count']}")
print(f"peak_rss_kb={int(round(summary['peak_rss_kb']))}")
print(f"peak_rss_mib={summary['peak_rss_kb'] / 1024:.2f}")
print(f"avg_rss_kb={summary['avg_rss_kb']:.2f}")
print(f"avg_rss_mib={summary['avg_rss_kb'] / 1024:.2f}")
print(f"peak_cpu_pct={summary['peak_cpu_pct']:.2f}")
print(f"avg_cpu_pct={summary['avg_cpu_pct']:.2f}")
PY

exit "$command_status"
