"""Run artifacts must not keep a portal's session cookies or credentials (formfill/web/artifacts.py). No browser needed here;
the end-to-end check through the validation tool is in test_validate_public_form.py."""

from __future__ import annotations

import inspect
import json
import zipfile

from formfill.web.artifacts import REDACTED, scrub_trace, write_text_atomic
from formfill.web.pipeline import run_url

SESSION = "SESSION-VALUE-1234567"
TOKEN = "TOKEN-VALUE-7654321"


def har(url: str) -> dict:
    return {"type": "resource-snapshot", "snapshot": {
        "request": {"method": "GET", "url": url, "cookies": [{"name": "sid", "value": SESSION}],
                    "headers": [{"name": "Accept", "value": "text/html"}, {"name": "Cookie", "value": f"sid={SESSION}; theme=dark"},
                                {"name": "authorization", "value": f"Bearer {TOKEN}"}]},
        "response": {"status": 200, "cookies": [{"name": "sid", "value": SESSION, "path": "/"}],
                     "headers": [{"name": "Content-Type", "value": "text/html"},
                                 {"name": "Set-Cookie", "value": f"sid={SESSION}; Path=/; HttpOnly"}],
                     "content": {"_file": "resources/page.html"}}}}


def make_trace(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("trace.network", "\n".join(json.dumps(har(u)) for u in ("http://127.0.0.1:1/", "http://127.0.0.1:1/api")) + "\n")
        z.writestr("trace.trace", json.dumps({"type": "action", "params": {"note": f"page echoed {TOKEN}"}}) + "\n")
        z.writestr("resources/page.html", f'<meta name="csrf" content="{SESSION}"><label>Name <input></label>')


def test_scrub_trace_removes_cookie_and_authorization_values_everywhere(tmp_path):
    trace = tmp_path / "trace.zip"
    make_trace(trace)
    removed = scrub_trace(trace)
    assert removed >= 8
    with zipfile.ZipFile(trace) as z:
        for name in z.namelist():
            data = z.read(name).decode("utf-8")
            assert SESSION not in data and TOKEN not in data, name
        records = [json.loads(line) for line in z.read("trace.network").decode().splitlines()]  # still valid JSON lines
    request = records[0]["snapshot"]["request"]
    headers = {h["name"]: h["value"] for h in request["headers"]}
    assert headers == {"Accept": "text/html", "Cookie": REDACTED, "authorization": REDACTED}  # names kept, other values untouched
    assert request["cookies"] == [{"name": "sid", "value": REDACTED}]
    assert scrub_trace(trace) == 0  # idempotent


def test_scrub_trace_keeps_a_trace_without_secrets_unchanged_in_content(tmp_path):
    trace = tmp_path / "trace.zip"
    with zipfile.ZipFile(trace, "w") as z:
        z.writestr("trace.network", json.dumps({"type": "resource-snapshot", "snapshot": {"request": {"headers": [
            {"name": "Accept", "value": "*/*"}], "cookies": []}}}) + "\n")
        z.writestr("resources/a.html", "<p>Fictional Vendor LLC</p>")
    assert scrub_trace(trace) == 0
    with zipfile.ZipFile(trace) as z:
        assert z.read("resources/a.html") == b"<p>Fictional Vendor LLC</p>"


def test_run_url_records_no_trace_unless_asked():
    assert inspect.signature(run_url).parameters["trace"].default is False


def test_atomic_write_replaces_the_whole_file(tmp_path):
    target = tmp_path / "sub" / "result.json"
    write_text_atomic(target, "first version, longer than the second")
    write_text_atomic(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    assert [p.name for p in target.parent.iterdir()] == ["result.json"]  # no temporary file left behind
