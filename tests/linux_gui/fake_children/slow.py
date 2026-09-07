"""Fake child: emits output, stays alive briefly, then exits 0."""

import sys
import time

print("started", flush=True)
time.sleep(2)
print("done", flush=True)
sys.exit(0)
