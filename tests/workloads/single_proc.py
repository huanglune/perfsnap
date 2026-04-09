"""Single process: ramp RSS 10 MiB/s for 10s, then free."""
import time

data = []
for i in range(10):
    data.append(bytearray(10 * 1024 * 1024))
    time.sleep(1)
del data
time.sleep(2)
