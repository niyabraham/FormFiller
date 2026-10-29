"""Requirement F: a small local web page for reviewing answers (standard library only; no frontend framework).

    python -m formfill.web.review_server output/run1/review.json          # prints http://127.0.0.1:<port>/?token=...
    python -m formfill.web.review_server output/run1/result.json --build  # make review.json from a result first

Protection, because a review file holds confidential answers:
* it listens on 127.0.0.1 only (any other bind address is refused) and checks the Host header (no DNS-rebinding access);
* every request needs the random token printed at start (query `?token=` for the page, header `X-Review-Token` for the API);
* no cross-origin headers, a strict Content-Security-Policy with a per-start nonce, no caching, no referrer;
* page content is inserted as text, never as HTML.
Decisions are re-validated on the server against the field's own constraints and saved atomically (review.py).

The page says, and the server enforces, that reviewing is not submitting and approving is not a signature: there is no submit
control, and attestations can only be acknowledged (completed by the person in the portal).
"""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from formfill.web.result import ItemResult, RunResult
from formfill.web.review import NOT_A_SIGNATURE, ReviewError, build_review, decide, load_review, save_review

LOOPBACK = "127.0.0.1"

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FormFiller review</title>
<style nonce="{nonce}">
body{{font:15px system-ui,sans-serif;margin:1.5rem;max-width:72rem}} .banner{{background:#fff3cd;border:1px solid #c9a227;padding:.8rem;margin-bottom:1rem}}
.item{{border:1px solid #ccc;border-radius:6px;padding:.8rem;margin:.6rem 0}} .item h3{{margin:.2rem 0}} .meta{{color:#444;font-size:13px}}
.state{{font-weight:bold}} .err{{color:#a00}} .ok{{color:#060}} button{{margin-right:.4rem}} code{{background:#f4f4f4;padding:0 .2rem}}
</style></head><body>
<h1>FormFiller review</h1>
<div class="banner" id="notice"></div>
<p class="meta" id="summary"></p>
<div id="items"></div>
<script nonce="{nonce}">
const TOKEN = {token_json};
const api = (path, opts = {{}}) => fetch(path, Object.assign({{headers: {{'X-Review-Token': TOKEN, 'Content-Type': 'application/json'}}}}, opts))
  .then(async r => {{ const body = await r.json(); if (!r.ok) throw new Error(body.error || r.statusText); return body; }});
const el = (tag, text, cls) => {{ const e = document.createElement(tag); if (text !== undefined && text !== null) e.textContent = String(text); if (cls) e.className = cls; return e; }};
function row(label, value) {{ const p = el('div', null, 'meta'); p.append(el('strong', label + ': ')); p.append(el('span', value === null || value === undefined || value === '' ? '-' : (typeof value === 'object' ? JSON.stringify(value) : value))); return p; }}
function render(doc) {{
  document.getElementById('notice').textContent = doc.notice;
  const box = document.getElementById('items'); box.textContent = '';
  const counts = {{}}; doc.items.forEach(i => counts[i.decision.action] = (counts[i.decision.action] || 0) + 1);
  document.getElementById('summary').textContent = `Page ${{doc.page}} - run status ${{doc.status}} - decisions: ${{JSON.stringify(counts)}}`;
  for (const it of doc.items) {{
    const d = el('div', null, 'item'); d.dataset.qid = it.question_id;
    d.append(el('h3', it.question + (it.required ? ' *' : '')));
    d.append(row('Section', it.section));
    d.append(row('Proposed answer', it.proposed));
    d.append(row('Evidence', it.source ? `${{it.source}} = ${{JSON.stringify(it.raw_value)}}` : null));
    d.append(row('Method / confidence', `${{it.method}} / ${{it.confidence_category || 'n/a'}}`));
    d.append(row('State', `${{it.state}} (${{it.state_detail}})`));
    d.append(row('Filled on the page', it.filled ? 'yes' : 'no'));
    d.append(row('Why review', it.reason));
    if (it.conflicts && it.conflicts.length) d.append(row('Conflicting evidence', it.conflicts.map(c => `${{c.source}} = ${{JSON.stringify(c.value)}}`).join('; ')));
    d.append(row('Decision', it.decision.action + (it.decision.value !== null ? ` (${{JSON.stringify(it.decision.value)}})` : '')));
    const msg = el('div', '', 'msg'); const buttons = el('div');
    const send = (action, value) => api('/api/decision', {{method: 'POST', body: JSON.stringify({{question_id: it.question_id, action, value}})}})
      .then(() => load()).catch(e => {{ msg.className = 'msg err'; msg.textContent = e.message; }});
    if (it.attestation) {{
      d.append(el('p', 'This is an attestation, consent or declaration. FormFiller never answers it: complete it yourself in the portal.', 'err'));
      const b = el('button', 'Acknowledge (I will complete it in the portal)'); b.dataset.action = 'acknowledge'; b.onclick = () => send('acknowledge'); buttons.append(b);
    }} else {{
      if (it.proposed !== null) {{ const a = el('button', 'Approve proposed answer'); a.dataset.action = 'approve'; a.onclick = () => send('approve'); buttons.append(a); }}
      const input = el('input'); input.placeholder = 'your answer'; input.className = 'edit';
      const e = el('button', 'Use my answer'); e.dataset.action = 'edit'; e.onclick = () => send('edit', input.value); buttons.append(input, e);
      const r = el('button', 'Reject (leave for the portal)'); r.dataset.action = 'reject'; r.onclick = () => send('reject'); buttons.append(r);
    }}
    d.append(buttons, msg); box.append(d);
  }}
}}
function load() {{ return api('/api/review').then(render).catch(e => {{ document.getElementById('summary').textContent = e.message; }}); }}
load();
</script></body></html>"""


class ReviewServer:
    """Serve one review file. `start()` runs it in a background thread; `url` includes the token."""

    def __init__(self, review_path: str | Path, host: str = LOOPBACK, port: int = 0):
        if host != LOOPBACK:
            raise ValueError("the review server listens on 127.0.0.1 only; review files hold confidential answers")
        self.path = Path(review_path)
        load_review(self.path)  # refuse a broken file before listening
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.port = self.httpd.server_address[1]
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}/?token={self.token}"

    def start(self) -> ReviewServer:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, data) -> None:
                self._send(status, json.dumps(data, default=str).encode("utf-8"), "application/json")

            def _allowed(self, token: str | None) -> bool:
                host = (self.headers.get("Host") or "").lower()
                if host not in (f"{LOOPBACK}:{server.port}", f"localhost:{server.port}"):
                    return False
                return bool(token) and hmac.compare_digest(token, server.token)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/":
                    token = parse_qs(url.query).get("token", [None])[0]
                    if not self._allowed(token):
                        return self._json(403, {"error": "forbidden"})
                    nonce = secrets.token_urlsafe(12)
                    page = _PAGE.format(nonce=nonce, token_json=json.dumps(server.token))
                    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
                           "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                    return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", {"Content-Security-Policy": csp})
                if url.path == "/api/review":
                    if not self._allowed(self.headers.get("X-Review-Token")):
                        return self._json(403, {"error": "forbidden"})
                    with server.lock:
                        return self._json(200, load_review(server.path))
                return self._json(404, {"error": "not found"})

            def do_POST(self):
                if urlparse(self.path).path != "/api/decision":
                    return self._json(404, {"error": "not found"})
                if not self._allowed(self.headers.get("X-Review-Token")):
                    return self._json(403, {"error": "forbidden"})
                if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                    return self._json(415, {"error": "JSON only"})
                length = int(self.headers.get("Content-Length") or 0)
                if length > 100_000:
                    return self._json(413, {"error": "too large"})
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                    with server.lock:
                        doc = load_review(server.path)
                        item = decide(doc, str(body.get("question_id")), str(body.get("action")), body.get("value"), body.get("note", ""))
                        save_review(doc, server.path)
                except (ReviewError, ValueError) as exc:
                    return self._json(400, {"error": str(exc)})
                return self._json(200, {"item": item})

            def log_message(self, *args):  # no request log: URLs carry the token
                pass

        return Handler


def _build_from_result(result_path: Path, review_path: Path) -> None:
    from formfill.web.models import AnswerPlanItem

    raw = json.loads(result_path.read_text(encoding="utf-8"))
    plan_fields = set(AnswerPlanItem.__dataclass_fields__)
    item_fields = set(ItemResult.__dataclass_fields__) - {"plan"}
    items = [ItemResult(plan=AnswerPlanItem(**{k: v for k, v in i["plan"].items() if k in plan_fields}),
                        **{k: v for k, v in i.items() if k in item_fields}) for i in raw["items"]]
    result = RunResult(url=raw["url"], status=raw["status"], items=items, controls=raw.get("controls", []),
                       run_id=raw.get("run_id", ""), navigation=raw.get("navigation", {}), unsupported=raw.get("unsupported", []))
    save_review(build_review(result), review_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Review FormFiller answers in a local, token-protected page (127.0.0.1 only).")
    ap.add_argument("path", type=Path, help="review.json (or result.json with --build)")
    ap.add_argument("--build", action="store_true", help="create review.json next to the given result.json first")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)
    review_path = args.path
    if args.build:
        review_path = args.path.with_name("review.json")
        _build_from_result(args.path, review_path)
    srv = ReviewServer(review_path, port=args.port).start()
    assert srv.thread is not None
    print(NOT_A_SIGNATURE)
    print(f"Review page (local only; keep the token private): {srv.url}")
    try:
        srv.thread.join()
    except KeyboardInterrupt:
        srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
