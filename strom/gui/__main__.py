"""Module launcher for the Strom GUI: ``python -m strom.gui``."""

import sys

from strom.gui.app import run

if __name__ == "__main__":
    sys.exit(run())
