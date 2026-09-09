"""Fake child: emits bytes that are not valid UTF-8, exits 0."""

import sys

sys.stdout.buffer.write(b"\xff\xfe")
sys.stdout.buffer.write(b"after invalid bytes\n")
sys.stdout.flush()
sys.exit(0)
