"""48 CPU-bound processes, each pinning ~100% of one core for 8s."""

import multiprocessing
import time


def burn_cpu(duration):
    end = time.time() + duration
    while time.time() < end:
        sum(range(500000))


if __name__ == "__main__":
    procs = []
    for i in range(48):
        p = multiprocessing.Process(target=burn_cpu, args=(8,))
        p.start()
        procs.append(p)
    time.sleep(0.5)
    for p in procs:
        p.join()
