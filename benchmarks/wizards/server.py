"""Local server for the multi-step wizard fixtures (127.0.0.1 only; nothing is contacted outside the machine).

* static fixtures from ./fixtures (client_wizard.html, server_spa.html)
* a server-backed SPA API: GET /api/section/<n> returns a section definition; POST /api/answers stores an autosave;
  POST /api/submit records a final submission (which the tool must never trigger)
* a server-rendered wizard with real form POSTs: GET /classic/start, POST /classic/step/<n> (answers kept per session cookie),
  a final page whose "Submit questionnaire" button posts to /classic/submit (must never be triggered). ?prg=1 on the start URL
  answers each step POST with a 303 redirect to a GET of the next step (post/redirect/get).

Every request is recorded in `Recorder.requests` (method, path, body) so a test can check what actually arrived.
"""

from __future__ import annotations

import contextlib
import functools
import html
import json
import threading
import uuid
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SECTIONS = {
    1: {"n": 1, "title": "Organisation", "fields": [{"key": "org_name", "label": "Legal company name", "type": "text"},
                                                    {"key": "org_site", "label": "Company website", "type": "url"}]},
    2: {"n": 2, "title": "Security contact", "fields": [{"key": "sec_email", "label": "Security contact email", "type": "email"}]},
    3: {"n": 3, "title": "Location", "fields": [{"key": "hq_city", "label": "Headquarters city", "type": "text"}], "last": True},
}

CLASSIC_STEPS = {
    1: ("Organisation", [("org_name", "Legal company name", "text"), ("org_site", "Company website", "url")]),
    2: ("Security contact", [("sec_email", "Security contact email", "email")]),
    3: ("Location", [("hq_city", "Headquarters city", "text")]),
}


@dataclass
class Recorder:
    requests: list[tuple[str, str, str]] = field(default_factory=list)
    autosaves: list[dict] = field(default_factory=list)
    final_submissions: int = 0
    sessions: dict[str, dict] = field(default_factory=dict)

    def paths(self, method: str | None = None) -> list[str]:
        return [p for m, p, _ in self.requests if method is None or m == method]


def _classic_page(step: int, answers: dict, prg: bool) -> bytes:
    title, fields = CLASSIC_STEPS[step]
    rows = "".join(
        f'<div><label for="{k}">{html.escape(label)}</label><input id="{k}" name="{k}" type="{t}" value="{html.escape(answers.get(k, ""))}"></div>'
        for k, label, t in fields)
    q = "?prg=1" if prg else ""
    if step < len(CLASSIC_STEPS):
        actions = '<button type="submit">Next</button>'
        action = f"/classic/step/{step}{q}"
    else:
        actions = '<button type="submit">Submit questionnaire</button>'
        action = "/classic/submit"
    body = (f'<!doctype html><html><head><meta charset="utf-8"><title>Classic wizard</title><link rel="icon" href="data:,"></head><body>'
            f'<h1>Supplier registration</h1><h2>Step {step} of {len(CLASSIC_STEPS)}: {title}</h2>'
            f'<form method="post" action="{action}">{rows}{actions}</form></body></html>')
    return body.encode("utf-8")


def make_handler(rec: Recorder):
    class Handler(SimpleHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _session(self) -> tuple[str, dict, dict]:
            cookie = self.headers.get("Cookie", "")
            sid = next((c.split("=", 1)[1] for c in cookie.split("; ") if c.startswith("wiz=")), None)
            headers = {}
            if sid is None or sid not in rec.sessions:
                sid = uuid.uuid4().hex[:12]
                rec.sessions[sid] = {}
                headers["Set-Cookie"] = f"wiz={sid}; Path=/; HttpOnly"
            return sid, rec.sessions[sid], headers

        def do_GET(self):
            url = urlparse(self.path)
            rec.requests.append(("GET", url.path, ""))
            prg = "prg=1" in url.query
            if url.path.startswith("/api/section/"):
                n = int(url.path.rsplit("/", 1)[1])
                if n not in SECTIONS:
                    return self._send(404, b"{}", "application/json")
                return self._send(200, json.dumps(SECTIONS[n]).encode(), "application/json")
            if url.path == "/classic/start":
                _, answers, headers = self._session()
                return self._send(200, _classic_page(1, answers, prg), headers=headers)
            if url.path.startswith("/classic/step/"):
                _, answers, headers = self._session()
                n = int(url.path.rsplit("/", 1)[1])
                return self._send(200, _classic_page(n, answers, prg), headers=headers)
            return super().do_GET()

        def do_POST(self):
            url = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)).decode("utf-8", errors="replace")
            rec.requests.append(("POST", url.path, body))
            prg = "prg=1" in url.query
            if url.path == "/api/answers":
                rec.autosaves.append(json.loads(body or "{}"))
                return self._send(200, b'{"ok": true}', "application/json")
            if url.path in ("/api/submit", "/classic/submit"):
                rec.final_submissions += 1
                return self._send(200, b"<p>Thank you, submitted.</p>")
            if url.path.startswith("/classic/step/"):
                _, answers, headers = self._session()
                n = int(url.path.rsplit("/", 1)[1])
                answers.update({k: v[0] for k, v in parse_qs(body).items()})
                if prg:
                    return self._send(303, b"", headers={**headers, "Location": f"/classic/step/{n + 1}?prg=1"})
                return self._send(200, _classic_page(min(n + 1, len(CLASSIC_STEPS)), answers, prg), headers=headers)
            return self._send(404, b"not found")

        def log_message(self, *args):  # silence
            pass

    return Handler


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # a client that went away mid-response is not news
        pass


@contextlib.contextmanager
def serve():
    """Yield (base_url, recorder) for a throw-away 127.0.0.1 server."""
    rec = Recorder()
    handler = functools.partial(make_handler(rec), directory=str(FIXTURES))
    httpd = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", rec
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
