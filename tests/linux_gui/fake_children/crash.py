"""Fake child: dies with SIGKILL so QProcess reports CrashExit."""

import os
import signal

print("about to die", flush=True)
os.kill(os.getpid(), signal.SIGKILL)
