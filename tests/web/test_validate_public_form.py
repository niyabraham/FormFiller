"""tools/validate_public_form.py: runs the pipeline against a page and can never submit. Local loopback fixtures only."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "validate_public_form.py"
sys.path.insert(0, str(ROOT))
from benchmarks.spa.server import serve


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=180, cwd=ROOT, check=False)


def test_tool_has_no_way_to_submit():
    text = TOOL.read_text(encoding="utf-8")
    assert "submit=True" not in text and "--submit" not in text
    assert '"submit": False' in text


def test_rejects_non_http_urls(tmp_path):
    done = _run("--url", "file:///etc/passwd", "--source", str(tmp_path / "s.json"))
    assert done.returncode != 0 and "http" in done.stderr


@pytest.mark.browser
def test_runs_a_local_wizard_without_submitting(browser, tmp_path):  # `browser` only skips cleanly without Chromium
    with serve() as base:
        done = _run("--url", f"{base}/wiz_hidden.html", "--source", str(ROOT / "benchmarks/spa/source.json"),
                    "--policy", "--confirm-ms", "0", "--out-dir", str(tmp_path))
    assert done.returncode == 0, done.stderr
    data = json.loads((tmp_path / "result.json").read_text())
    assert "Run status:" in done.stdout and "Submission attempted: False" in done.stdout
    assert data["submission"] == {} and data["items"]
    assert not (tmp_path / "trace.zip").exists()  # no trace unless --trace


@pytest.mark.browser
def test_a_requested_trace_keeps_no_session_cookie(browser, tmp_path):
    """Playwright records every request's and response's headers in a trace, so a portal's session cookie would be stored in
    trace.zip (measured: 14 copies for two page loads). --trace saves a trace with those values removed."""
    import threading
    import zipfile
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    secret = "sessid-TRACE-PROBE-7f3a9c"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = (b"<!doctype html><title>t</title><link rel=icon href='data:,'><label>Legal company name <input id=n></label>"
                    b"<script>fetch('/ping')</script>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", f"sid={secret}; Path=/; HttpOnly")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"company": {"legal_name": "Fictional Vendor LLC"}}), encoding="utf-8")
    try:
        done = _run("--url", f"http://127.0.0.1:{httpd.server_address[1]}/", "--source", str(source), "--confirm-ms", "0",
                    "--out-dir", str(tmp_path / "out"), "--trace")
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert done.returncode == 0, done.stderr
    trace = tmp_path / "out" / "trace.zip"
    with zipfile.ZipFile(trace) as z:
        names = z.namelist()
        assert "trace.network" in names
        assert all(secret.encode() not in z.read(n) for n in names)
        records = [json.loads(line) for line in z.read("trace.network").decode().splitlines() if line]
    set_cookies = [h for r in records for h in r.get("snapshot", {}).get("response", {}).get("headers", [])
                   if h["name"].lower() == "set-cookie"]
    assert set_cookies and all(h["value"] == "[redacted]" for h in set_cookies)  # the header was there and is now empty
