#!/usr/bin/env bash
# Usage: collect.sh <output-dir> <prefix> -- <command...>
#
# Launches <command> in the background, samples its full process tree via
# sampler.py (which reads /proc directly), then generates a two-panel SVG
# from the CSV when the command exits.
#
# Environment variables:
#   PERFSNAP_INTERVAL  — sample interval in seconds, float allowed (default: 1)
#                        Practical floor is ~0.05s; CPU% quantizes at the
#                        kernel clock tick (usually 10ms).
#   PERFSNAP_THREAD    — set to 1 for thread-level collection
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

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found." >&2
  exit 1
fi

interval=${PERFSNAP_INTERVAL:-1}
thread_flag=${PERFSNAP_THREAD:-0}

# Validate interval as a positive float. Reject negatives, zero, non-numeric.
if ! awk -v v="$interval" 'BEGIN { exit !(v+0 > 0 && v == v+0) }'; then
  echo "ERROR: PERFSNAP_INTERVAL must be a positive number, got: $interval" >&2
  exit 1
fi

mkdir -p "$output_dir"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

stdout_log="$output_dir/$prefix.stdout.log"
csv_path="$output_dir/$prefix.csv"
svg_path="$output_dir/$prefix.svg"

echo "=== Collecting perfsnap metrics ==="
echo "  Command:  $*"
echo "  Output:   $output_dir/$prefix.*"
echo "  Interval: ${interval}s"
echo "  Thread:   $([[ $thread_flag == 1 ]] && echo yes || echo no)"

start_ts=$(date +%s.%N)

# Launch the target command. Stdout+stderr go to a separate log so they
# don't mix with sampler output.
"$@" > "$stdout_log" 2>&1 &
cmd_pid=$!
echo "  PID:      $cmd_pid"

sampler_args=(--root-pid "$cmd_pid" --interval "$interval" --output "$csv_path")
if [[ "$thread_flag" == "1" ]]; then
  sampler_args+=(--thread)
fi
python3 "$script_dir/sampler.py" "${sampler_args[@]}" &
sampler_pid=$!

# Wait for the target command; capture its exit code.
set +e
wait "$cmd_pid"
command_status=$?
set -e

# Ask the sampler to wrap up. It polls /proc/<cmd_pid> so it would notice
# on its own shortly — SIGTERM just makes shutdown deterministic.
kill -TERM "$sampler_pid" 2>/dev/null || true
wait "$sampler_pid" 2>/dev/null || true

end_ts=$(date +%s.%N)

echo "  Exit:     $command_status"

python3 "$script_dir/plot.py" "$csv_path" "$svg_path" --title "$prefix"

# Print structured summary
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
        rss = float(row.get("rss_kb", 0) or 0)
        cpu = float(row.get("cpu_pct", 0) or 0)
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
