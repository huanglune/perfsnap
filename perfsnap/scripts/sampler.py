#!/usr/bin/env python3
"""Sample /proc/<pid>/stat for a process tree and write CSV.

Reads /proc directly so any positive float interval is supported (unlike
sysstat's pidstat, which rejects fractional intervals). Discovers the full
process tree via /proc/<pid>/task/<tid>/children and supports thread-level
collection. Output CSV schema is consumed by perfsnap/scripts/plot.py.

The first observation of any (pid, starttime) key is used only to seed the
delta baseline — no row is emitted for it, so cpu%/fault rates are honest
from the very first CSV row.
"""

import argparse
import csv
import os
import signal
import sys
import time
from typing import IO

CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGESIZE")

CSV_FIELDS = [
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


def read_mem_total_kb() -> float:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemTotal:"):
                return float(line.split()[1])
    return 0.0


class StatRow:
    __slots__ = (
        "comm",
        "minflt",
        "majflt",
        "utime",
        "stime",
        "starttime",
        "vsize_bytes",
        "rss_pages",
        "processor",
        "blkio_ticks",
        "guest_time",
    )

    def __init__(
        self,
        comm: str,
        minflt: int,
        majflt: int,
        utime: int,
        stime: int,
        starttime: int,
        vsize_bytes: int,
        rss_pages: int,
        processor: int,
        blkio_ticks: int,
        guest_time: int,
    ) -> None:
        self.comm = comm
        self.minflt = minflt
        self.majflt = majflt
        self.utime = utime
        self.stime = stime
        self.starttime = starttime
        self.vsize_bytes = vsize_bytes
        self.rss_pages = rss_pages
        self.processor = processor
        self.blkio_ticks = blkio_ticks
        self.guest_time = guest_time


def parse_stat(path: str) -> StatRow | None:
    """Parse a /proc/<pid>/stat or /proc/<pid>/task/<tid>/stat file.

    Returns None when the file is gone, unreadable, or malformed — callers
    treat that as "process disappeared, move on".
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None

    # comm is enclosed in parens and may contain spaces or ')'. The safe way
    # to split it out is to find the LAST ')' — everything after it is
    # whitespace-separated fields.
    try:
        lparen = data.index(b"(")
        rparen = data.rindex(b")")
    except ValueError:
        return None

    comm = data[lparen + 1 : rparen].decode("utf-8", errors="replace")
    rest = data[rparen + 2 :].split()

    # `rest` is the tail starting at field 3 (state) of the stat file.
    # 0-indexed positions (= 1-indexed stat field number - 3):
    #   0=state, 1=ppid, 7=minflt, 9=majflt, 11=utime, 12=stime,
    #   19=starttime, 20=vsize, 21=rss, 36=processor, 39=blkio_ticks,
    #   40=guest_time.
    if len(rest) < 22:
        return None

    try:
        return StatRow(
            comm=comm,
            minflt=int(rest[7]),
            majflt=int(rest[9]),
            utime=int(rest[11]),
            stime=int(rest[12]),
            starttime=int(rest[19]),
            vsize_bytes=int(rest[20]),
            rss_pages=int(rest[21]),
            processor=int(rest[36]) if len(rest) > 36 else 0,
            blkio_ticks=int(rest[39]) if len(rest) > 39 else 0,
            guest_time=int(rest[40]) if len(rest) > 40 else 0,
        )
    except (ValueError, IndexError):
        return None


def list_children(pid: int) -> list[int]:
    """Return direct children of pid, across all its threads.

    Any thread of a process can fork/clone, so /proc/<pid>/task/<pid>/children
    alone misses children spawned from non-main threads. Iterate all tasks.
    """
    children: list[int] = []
    task_dir = f"/proc/{pid}/task"
    try:
        tids = os.listdir(task_dir)
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return children

    for tid in tids:
        try:
            with open(f"{task_dir}/{tid}/children") as fh:
                for tok in fh.read().split():
                    children.append(int(tok))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue
    return children


def discover_tree(root: int) -> list[int]:
    """DFS all descendants of root (inclusive)."""
    tree: list[int] = [root]
    seen: set[int] = {root}
    stack = [root]
    while stack:
        pid = stack.pop()
        for child in list_children(pid):
            if child not in seen:
                seen.add(child)
                tree.append(child)
                stack.append(child)
    return tree


def list_threads(pid: int) -> list[int]:
    try:
        return sorted(int(tid) for tid in os.listdir(f"/proc/{pid}/task"))
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        return []


# Key into the prev-state dict. Tagged so proc and thread rows for the same
# (pid, tid) don't collide. starttime guards against PID reuse.
PrevKey = tuple[str, int, int, int]  # (kind, pid, tid_or_zero, starttime)


class Sampler:
    def __init__(
        self,
        root_pid: int,
        interval: float,
        output_path: str,
        thread_mode: bool,
    ) -> None:
        self.root_pid = root_pid
        self.interval = interval
        self.thread_mode = thread_mode
        self.mem_total_kb = read_mem_total_kb() or 1.0
        self.sample_index = 0
        self.prev: dict[PrevKey, tuple[float, int, int, int, int, int, int]] = {}

        self.csv_file: IO[str] = open(output_path, "w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(
            self.csv_file, fieldnames=CSV_FIELDS, extrasaction="ignore"
        )
        self.writer.writeheader()
        self.csv_file.flush()

        self._stop = False

    def request_stop(self, *_: object) -> None:
        self._stop = True

    def close(self) -> None:
        try:
            self.csv_file.flush()
        finally:
            self.csv_file.close()

    def _emit(
        self,
        pid: int,
        tid_str: str,
        key: PrevKey,
        now: float,
        row: StatRow,
    ) -> None:
        rss_kb = row.rss_pages * PAGE_SIZE / 1024
        vsz_kb = row.vsize_bytes / 1024

        prev = self.prev.get(key)
        self.prev[key] = (
            now,
            row.utime,
            row.stime,
            row.minflt,
            row.majflt,
            row.blkio_ticks,
            row.guest_time,
        )
        if prev is None:
            return

        (
            prev_ts,
            prev_utime,
            prev_stime,
            prev_minflt,
            prev_majflt,
            prev_blkio,
            prev_guest,
        ) = prev
        dt = now - prev_ts
        if dt <= 0:
            return

        dt_ticks = dt * CLOCK_TICKS
        user_pct = max(0.0, (row.utime - prev_utime)) / dt_ticks * 100
        system_pct = max(0.0, (row.stime - prev_stime)) / dt_ticks * 100
        guest_pct = max(0.0, (row.guest_time - prev_guest)) / dt_ticks * 100
        wait_pct = max(0.0, (row.blkio_ticks - prev_blkio)) / dt_ticks * 100
        cpu_pct = user_pct + system_pct
        minflt_s = max(0.0, (row.minflt - prev_minflt)) / dt
        majflt_s = max(0.0, (row.majflt - prev_majflt)) / dt
        mem_pct = rss_kb / self.mem_total_kb * 100

        self.writer.writerow(
            {
                "sample_index": self.sample_index,
                "timestamp_s": f"{now:.3f}",
                "pid": pid,
                "tid": tid_str,
                "user_pct": f"{user_pct:.2f}",
                "system_pct": f"{system_pct:.2f}",
                "guest_pct": f"{guest_pct:.2f}",
                "wait_pct": f"{wait_pct:.2f}",
                "cpu_pct": f"{cpu_pct:.2f}",
                "cpu_core": row.processor,
                "minflt_s": f"{minflt_s:.2f}",
                "majflt_s": f"{majflt_s:.2f}",
                "vsz_kb": f"{vsz_kb:.0f}",
                "rss_kb": f"{rss_kb:.0f}",
                "rss_mib": f"{rss_kb / 1024:.2f}",
                "mem_pct": f"{mem_pct:.2f}",
                "command": row.comm,
            }
        )

    def _sample_tree(self) -> None:
        tree = discover_tree(self.root_pid)
        now = time.time()

        for pid in tree:
            proc_row = parse_stat(f"/proc/{pid}/stat")
            if proc_row is None:
                continue
            self._emit(
                pid,
                "",
                ("proc", pid, 0, proc_row.starttime),
                now,
                proc_row,
            )

            if self.thread_mode:
                for tid in list_threads(pid):
                    thread_row = parse_stat(f"/proc/{pid}/task/{tid}/stat")
                    if thread_row is None:
                        continue
                    self._emit(
                        pid,
                        str(tid),
                        ("thread", pid, tid, thread_row.starttime),
                        now,
                        thread_row,
                    )

        self.sample_index += 1
        self.csv_file.flush()

    def run(self) -> None:
        while not self._stop:
            if not os.path.exists(f"/proc/{self.root_pid}"):
                break
            self._sample_tree()
            # Coarse sleep: OS scheduling jitter is fine because dt is measured
            # from actual wall clock, not from the requested interval.
            time.sleep(self.interval)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--thread", action="store_true")
    args = parser.parse_args()

    if args.interval <= 0:
        print("ERROR: --interval must be positive", file=sys.stderr)
        return 2

    sampler = Sampler(
        root_pid=args.root_pid,
        interval=args.interval,
        output_path=args.output,
        thread_mode=args.thread,
    )
    signal.signal(signal.SIGTERM, sampler.request_stop)
    signal.signal(signal.SIGINT, sampler.request_stop)
    try:
        sampler.run()
    finally:
        sampler.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
