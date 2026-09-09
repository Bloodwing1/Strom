"""Fake child: reports its argument list and parent process as JSON, exits 0.

The parent pid proves whether a shell sits between the runner and the child.
"""

import json
import os
import sys

print(
    json.dumps({"argv": sys.argv[1:], "ppid": os.getppid()}),
    flush=True,
)
sys.exit(0)
