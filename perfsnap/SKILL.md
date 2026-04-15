---
name: perfsnap
description: >-
  Collect RSS memory, CPU usage, and optional thread-level metrics for any local
  command by sampling /proc directly, then export CSV and render an SVG chart.
  Use this skill whenever the user wants to profile a build, benchmark, index
  construction, search workload, or any long-running process -- even if they
  just say "how much memory does this use" or "track performance while it runs".
  Also use when the user mentions performance chart, RSS tracking, CPU profiling,
  or memory monitoring for a local command. Supports sub-second sample intervals.
---

# Perfsnap

Collect per-sample performance data (RSS, CPU, faults, thread detail) for a
command by reading `/proc/<pid>/stat`, write to CSV, and render a two-panel
SVG chart (RSS MiB + CPU %).

## Workflow

1. **Confirm inputs** with the user:
   - The target command to profile
   - Output directory and file prefix (suggest sensible defaults like `/tmp/perf` and a descriptive name)
   - Sample interval (default `1s`; fractional values like `0.1` are supported)
   - Collection mode: process-level (default) or thread-level (`PERFSNAP_THREAD=1`)

2. **Check prerequisites**:
   - `python3` must be available (no third-party packages needed)
   - Kernel exposes `/proc/<pid>/task/<tid>/children` — standard on any Linux
     with `CONFIG_PROC_CHILDREN=y`, which is the default on modern distros

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
   "$SKILL_DIR/scripts/collect.sh" \
     <output-dir> <prefix> -- <command...>

   # Sub-second interval:
   PERFSNAP_INTERVAL=0.1 "$SKILL_DIR/scripts/collect.sh" \
     <output-dir> <prefix> -- <command...>

   # Thread-level collection:
   PERFSNAP_THREAD=1 "$SKILL_DIR/scripts/collect.sh" \
     <output-dir> <prefix> -- <command...>
   ```

   The collector launches the target command, starts `sampler.py` to read
   `/proc/<pid>/stat` at the requested interval for the full process tree,
   then automatically runs the SVG renderer when the command finishes.

   Environment variables:
   - `PERFSNAP_INTERVAL` — sample interval in seconds, floats allowed (default: `1`).
     The practical lower bound is ~`0.05`s: CPU accounting is quantized at
     the kernel clock tick (usually 10 ms), so intervals smaller than a few
     ticks produce noisy or binary-looking CPU%.
   - `PERFSNAP_THREAD` — set to `1` for thread-level collection. In thread mode
     the CSV contains one process-level row per sample per process (with
     aggregated CPU) plus one row per live thread.

5. **Report results** — after the collector finishes, tell the user:
   - Which files were generated (`.stdout.log`, `.csv`, `.svg`)
   - Key metrics from the summary: elapsed time, peak RSS, peak CPU, sample count
   - The exit code of the profiled command

6. **Verify output** — check the CSV for real data, not just headers:
   - The CSV always writes headers even with zero samples. Verify `sample_count > 0`
     in the collector's summary output, or count non-header rows in the CSV.
   - If the user asked for thread data, verify the `tid` column has non-empty values
     (not just that the column exists).
   - If `sample_count` is 0, the workload finished before the sampler could
     take two observations. Suggest lowering `PERFSNAP_INTERVAL` (e.g. to
     `0.1`) or extending the workload. The sampler intentionally drops the
     first observation of each PID because it has no baseline yet — so the
     minimum useful workload duration is roughly `2 × PERFSNAP_INTERVAL`.

## Output Files

| File | Contents |
|------|----------|
| `<prefix>.stdout.log` | Target command's stdout + stderr |
| `<prefix>.csv` | Per-sample rows with timestamps, CPU %, RSS, VSZ, faults, and tid (if thread mode) |
| `<prefix>.svg` | Two-panel chart: RSS (MiB) top, CPU (%) bottom |

## Scripts Reference

All script paths below are relative to `$SKILL_DIR` (resolved in step 3).

### `$SKILL_DIR/scripts/collect.sh`

Orchestrator. Launches the command in the background, starts `sampler.py`
to monitor the full process tree, waits for the command to finish, signals
the sampler to shut down, then runs `plot.py`.

### `$SKILL_DIR/scripts/sampler.py`

Reads `/proc/<pid>/stat` for the root process and every descendant at the
requested interval, writing CSV rows directly. Process-tree discovery uses
`/proc/<pid>/task/<tid>/children` (walked across all threads of each process).
Keys its delta-tracking state by `(pid, starttime)` so PID reuse within a
run is handled correctly. In thread mode, also reads
`/proc/<pid>/task/<tid>/stat` for each thread.

```bash
python3 "$SKILL_DIR/scripts/sampler.py" \
  --root-pid 12345 --interval 0.5 --output out.csv [--thread]
```

Normally invoked via `collect.sh`; direct invocation is useful when attaching
to an already-running process.

### `$SKILL_DIR/scripts/plot.py`

Renders a two-panel SVG from the CSV. Top panel = RSS in MiB, bottom panel = CPU %.

```bash
python3 "$SKILL_DIR/scripts/plot.py" input.csv output.svg --title "My Build"
python3 "$SKILL_DIR/scripts/plot.py" input.csv output.svg --title "My Build" \
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

- The sampler monitors the entire process tree (parent + all descendants), not
  just a single PID. Each sample re-discovers the tree via
  `/proc/<pid>/task/<tid>/children` on every known process — new children
  appear in the next sample automatically.
- If the repo has a required wrapper script (like `run_and_log.sh`), build the
  command so that `collect.sh` wraps the real workload command, and any
  repo wrapper wraps the entire `collect.sh` invocation — not the other way
  around.
- The target command's stdout/stderr goes to `<prefix>.stdout.log`, completely
  separated from the sampler's bookkeeping. This prevents interleaving.
- CPU% is computed from utime+stime deltas divided by wall-clock elapsed
  (measured, not requested) and the kernel clock tick rate — so it reports
  honest values even when `time.sleep()` overshoots.
- Short-lived children (spawned and exited within a single sample interval)
  are still a blind spot — same trade-off as any sampling profiler. Lower
  `PERFSNAP_INTERVAL` to narrow the window.
