"""Local HTTP server for the SPA fixtures (no third-party sites). Serves benchmarks/spa/fixtures and one
endpoint, /api/delay?ms=N, that answers after N milliseconds so a page can render content asynchronously."""

from __future__ import annotations

import contextlib
import functools
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/delay":
            time.sleep(min(int(parse_qs(url.query).get("ms", ["0"])[0]), 3000) / 1000)
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):  # silence
        pass


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # a client that went away mid-response is not news
        pass


@contextlib.contextmanager
def serve():
    """Yield the base URL of a throw-away localhost server."""
    handler = functools.partial(_Handler, directory=str(FIXTURES))
    httpd = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
