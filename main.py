"""Backwards-compatible entry point.

The real implementation lives in :mod:`strom.cli`; this shim only exists so
existing cron jobs running ``python main.py`` keep working.
"""

import sys

from strom.cli import run

if __name__ == "__main__":
    sys.exit(run())
