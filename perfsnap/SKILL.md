---
name: perfsnap
description: >-
  Collect RSS memory, CPU usage, and optional thread-level metrics for any local
  command using pidstat, then export CSV and render an SVG chart. Use this skill
  whenever the user wants to profile a build, benchmark, index construction, search
  workload, or any long-running process -- even if they just say "how much memory
  does this use" or "track performance while it runs". Also use when the user
  mentions pidstat, performance chart, RSS tracking, CPU profiling, or memory
  monitoring for a local command.
---

# Perfsnap

Collect `pidstat`-based performance data for a command, convert to CSV, and render a two-panel SVG chart (RSS MiB + CPU %).

## Workflow

1. **Confirm inputs** with the user:
   - The target command to profile
   - Output directory and file prefix (suggest sensible defaults like `/tmp/perf` and a descriptive name)
   - Collection mode: process-level (default) or thread-level (`-t`)

2. **Check prerequisites**:
   - `pidstat` (from sysstat), `pgrep` (from procps), and `python3` must be available
   - If `pidstat` is missing, ask the user before installing sysstat

3. **Resolve the skill's script directory** — the scripts live in this skill's `scripts/` subdirectory. Locate this SKILL.md first, then derive the scripts path:

   ```bash
   SKILL_DIR="$(dirname "$(find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" ~/.codex ~/.agents -path '*/perfsnap/SKILL.md' -print -quit 2>/dev/null)")"
   if [ -z "$SKILL_DIR" ] || [ "$SKILL_DIR" = "." ]; then
     echo "ERROR: perfsnap skill not found" >&2
     # Fall back: the skill might be in the current project
     SKILL_DIR="$(find . -path '*/perfsnap/SKILL.md' -print -quit 2>/dev/null | xargs dirname 2>/dev/null)"
   fi
   ```

   If the find fails, ask the user for the install path. Do NOT proceed with `SKILL_DIR="."`.

4. **Run the collector** — the skill bundles three scripts that form a pipeline:

   ```bash
   # Basic usage:
   "$SKILL_DIR/scripts/collect_pidstat.sh" \
     <output-dir> <prefix> -- <command...>

   # Thread-level collection:
   PIDSTAT_THREAD=1 "$SKILL_DIR/scripts/collect_pidstat.sh" \
     <output-dir> <prefix> -- <command...>
   ```

   The collector launches the target command, monitors it and all its descendant
   processes with pidstat (`-r -u -h` flags for RSS, CPU, and machine-readable
   output), then automatically runs the CSV converter and SVG renderer when the
   command finishes.

   Environment variables:
   - `PIDSTAT_INTERVAL` — sample interval in seconds (default: `1`)
   - `PIDSTAT_THREAD` — set to `1` for thread-level collection (`pidstat -t`)
   - `PIDSTAT_KEEP_RAW` — set to `1` to keep the raw `.pidstat` and `.pids` files

5. **Report results** — after the collector finishes, tell the user:
   - Which files were generated (`.stdout.log`, `.csv`, `.svg`)
   - Key metrics from the summary: elapsed time, peak RSS, peak CPU, sample count
   - The exit code of the profiled command

6. **Verify output** — check the CSV for real data, not just headers:
   - The CSV always writes headers even with zero samples. Verify `sample_count > 0`
     in the collector's summary output, or count non-header rows in the CSV.
   - If the user asked for thread data, verify the `tid` column has non-empty values
     (not just that the column exists).
   - If `sample_count` is 0, the workload may have been too short for the sampling
     interval. Suggest lowering `PIDSTAT_INTERVAL` or extending the workload.

## Output Files

| File | Contents |
|------|----------|
| `<prefix>.stdout.log` | Target command's stdout + stderr |
| `<prefix>.csv` | Parsed pidstat samples with timestamps, CPU %, RSS, VSZ, and tid (if thread mode) |
| `<prefix>.svg` | Two-panel chart: RSS (MiB) top, CPU (%) bottom |
| `<prefix>.pidstat` | Raw pidstat output (deleted unless `PIDSTAT_KEEP_RAW=1`) |
| `<prefix>.pids` | Collected descendant PIDs (deleted unless `PIDSTAT_KEEP_RAW=1`) |

## Scripts Reference

All script paths below are relative to `$SKILL_DIR` (resolved in step 3).

### `$SKILL_DIR/scripts/collect_pidstat.sh`

Orchestrator script. Launches the command in the background, runs a sidecar to
track all descendant PIDs via `pgrep`, attaches `pidstat -r -u -h` to monitor
the full process tree, waits for completion, then chains the CSV and SVG scripts.

### `$SKILL_DIR/scripts/pidstat_to_csv.py`

Parses raw pidstat output into CSV. Uses header-based column detection so it
works across different sysstat versions. Supports `--pid-filter` to keep only
rows matching a set of PIDs (used for process-tree filtering).

```bash
python3 "$SKILL_DIR/scripts/pidstat_to_csv.py" input.pidstat output.csv
python3 "$SKILL_DIR/scripts/pidstat_to_csv.py" input.pidstat output.csv --pid-filter pids.txt
```

### `$SKILL_DIR/scripts/plot_pidstat_svg.py`

Renders a two-panel SVG from the CSV. Top panel = RSS in MiB, bottom panel = CPU %.

```bash
python3 "$SKILL_DIR/scripts/plot_pidstat_svg.py" input.csv output.svg --title "My Build"
python3 "$SKILL_DIR/scripts/plot_pidstat_svg.py" input.csv output.svg --title "My Build" \
  --subtitle "4 CPU-bound processes, 8s each"
```

Chart features:
- **Multi-PID aggregation**: when multiple PIDs are present, shows a bold total
  line plus per-PID dashed breakdown lines (up to 8 PIDs; suppressed above 8).
- **Dynamic time axis**: X-axis labels auto-switch between seconds, minutes, and
  hours depending on duration.
- **Nice Y-axis ticks**: Y-axis snaps to round values (e.g. 0, 100, 200 for CPU %).
- **No-data placeholder**: generates a placeholder SVG instead of failing when the
  CSV has zero samples.

## Important Context

- The collector monitors the entire process tree (parent + all descendants), not
  just a single PID. A sidecar periodically discovers child processes via `pgrep`
  and records them. After collection, only rows matching those PIDs are kept in
  the CSV. This ensures builds, benchmarks, and multi-process workloads are
  fully captured.
- If the repo has a required wrapper script (like `run_and_log.sh`), build the
  command so that `collect_pidstat.sh` wraps the real workload command, and any
  repo wrapper wraps the entire `collect_pidstat.sh` invocation — not the other
  way around.
- The target command's stdout/stderr goes to `<prefix>.stdout.log`, completely
  separated from pidstat's output. This prevents interleaving.
- The collector sets `LC_ALL=C` to force consistent timestamps and English headers
  from pidstat across locales. The parser also handles `HH:MM:SS` wall-clock
  timestamps as a fallback.
