"""Shared test environment for the Linux GUI suite.

Tests that require Qt perform their dependency skips at module scope before
importing GUI modules. This file selects Qt's headless platform (an explicit
value supplied by the caller wins) and provides a local fake HTTP service the
updater tests can point at, so no test ever contacts GitHub.
"""

import http.server
import threading
import time

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeRouteHandler(http.server.BaseHTTPRequestHandler):
    """Class-level route tables a test fills in before requests arrive."""

    routes: dict = {}
    redirects: dict = {}
    slow_paths: set = set()
    delay_paths: dict = {}
    chunk = 256
    chunk_delay = 0.1

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        target = _FakeRouteHandler.redirects.get(self.path)
        if target is not None:
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        delay = _FakeRouteHandler.delay_paths.get(self.path)
        if delay is not None:
            time.sleep(delay)
        route = _FakeRouteHandler.routes.get(self.path)
        if route is None:
            self.send_error(404)
            return
        status, body = route
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.path in _FakeRouteHandler.slow_paths:
            for start in range(0, len(body), _FakeRouteHandler.chunk):
                self.wfile.write(body[start:start + _FakeRouteHandler.chunk])
                self.wfile.flush()
                time.sleep(_FakeRouteHandler.chunk_delay)
            return
        self.wfile.write(body)

    def log_message(self, *_args):  # silence test output
        return


def reset_fake_routes() -> None:
    """Give each test clean class-level route tables."""
    _FakeRouteHandler.routes = {}
    _FakeRouteHandler.redirects = {}
    _FakeRouteHandler.slow_paths = set()
    _FakeRouteHandler.delay_paths = {}


FakeRouteHandler = _FakeRouteHandler


import pytest  # noqa: E402


@pytest.fixture()
def fake_service():
    """A local HTTP service; yields its handler class with ``base`` set.

    Tests set ``handler.routes``/``redirects``/``slow_paths``/``delay_paths``
    and use ``handler.base`` for URLs, so every request stays local.
    """
    reset_fake_routes()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeRouteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _FakeRouteHandler.base = f"http://127.0.0.1:{server.server_address[1]}"
    yield _FakeRouteHandler
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    reset_fake_routes()
