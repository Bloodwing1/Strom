"""Fake child: writes 40 KiB without any newline, exits 0."""

import sys

for _ in range(10):
    sys.stdout.write("y" * 4096)
    sys.stdout.flush()
sys.exit(0)
