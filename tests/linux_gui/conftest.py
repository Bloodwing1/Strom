"""Shared test environment for the Linux GUI suite.

Tests that require Qt perform their dependency skips at module scope before
importing GUI modules. This file only selects Qt's headless platform; an
explicit value supplied by the caller wins.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
