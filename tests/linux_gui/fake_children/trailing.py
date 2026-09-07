"""Fake child: writes one line without a trailing newline, exits 0."""

import sys

sys.stdout.write("no trailing newline")
sys.stdout.flush()
sys.exit(0)
