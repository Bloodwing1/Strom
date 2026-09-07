"""Fake child: two ordered output lines, exits 0."""

import sys

print("cycle line 1", flush=True)
print("cycle line 2", flush=True)
sys.exit(0)
