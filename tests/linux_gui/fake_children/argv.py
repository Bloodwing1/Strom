"""Fake child: prints its argument list as JSON, exits 0."""

import json
import sys

print(json.dumps(sys.argv[1:]), flush=True)
sys.exit(0)
