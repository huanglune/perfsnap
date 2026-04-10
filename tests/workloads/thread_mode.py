"""4 threads: each allocates 20 MiB and burns CPU."""

import threading
import time


def worker(n):
    data = bytearray(20 * 1024 * 1024)
    for _ in range(15):
        sum(range(3000000))
        time.sleep(0.5)


threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
