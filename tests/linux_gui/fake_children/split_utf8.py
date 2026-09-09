"""Fake child: writes one multibyte character split across two writes."""

import sys

payload = "héllo 雪 ✅ end".encode("utf-8")
split = len(payload) // 2
sys.stdout.buffer.write(payload[:split])
sys.stdout.flush()
sys.stdout.buffer.write(payload[split:])
sys.stdout.flush()
sys.stdout.buffer.write(b"\n")
sys.exit(0)
