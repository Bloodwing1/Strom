"""Fake child: prints an error line, exits nonzero."""

import sys

print("something went wrong", flush=True)
sys.exit(3)
