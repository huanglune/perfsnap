"""Parent spawns 3 children (staggered), each ~30 MiB RSS + CPU burn."""
import subprocess
import sys
import time

CHILD_CODE = """
import time
data = bytearray(30 * 1024 * 1024)
for _ in range(5):
    sum(range(2000000))
    time.sleep(1)
"""

procs = []
for i in range(3):
    p = subprocess.Popen([sys.executable, "-c", CHILD_CODE])
    procs.append(p)
    time.sleep(1)
for p in procs:
    p.wait()
