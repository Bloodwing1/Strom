"""Module launcher for the Strom GUI: ``python -m strom.linux_gui``."""

import sys

from strom.linux_gui.app import run

if __name__ == "__main__":
    sys.exit(run())
