"""Writing run artifacts without leaving them readable by other users, and without half-written files.

Run artifacts (result.json, progress files, audit reports, review files, screenshots, Playwright traces) contain the answers
FormFiller entered and what the portal showed: confidential company data. So:

* files are written to a temporary file in the same directory and moved into place (`os.replace`), so a crash never leaves a
  truncated result or progress file behind;
* on POSIX systems files get mode 0600 and directories 0700. On Windows `os.chmod` cannot set access-control lists; files
  inherit the permissions of the folder they are written to, so write them under the user's own profile (the default
  `output/` folder of a checkout in the user's home qualifies). `posix_permissions()` says which case applies.

Retention: nothing is deleted automatically. `output/` is git-ignored; delete a run's folder when its review is finished.

Playwright traces are written only on request (`run_url(trace=True)`, `validate_public_form.py --trace`) and are scrubbed of
cookie and authorization values (`scrub_trace`); they still hold the page content and the answers entered.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

FILE_MODE = 0o600
DIR_MODE = 0o700


def posix_permissions() -> bool:
    """True where file modes restrict access (POSIX). On Windows they do not; see the module docstring."""
    return os.name == "posix"


def secure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    if posix_permissions():
        with contextlib.suppress(OSError):  # a directory we do not own: leave it as it is
            os.chmod(p, DIR_MODE)
    return p


def restrict(path: str | Path) -> None:
    """Make an existing file owner-only (POSIX). Used for files a library writes itself (screenshots, traces)."""
    if posix_permissions():
        with contextlib.suppress(OSError):
            os.chmod(path, FILE_MODE)


def write_bytes_atomic(path: str | Path, data: bytes) -> Path:
    p = Path(path)
    secure_dir(p.parent)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
    try:
        if posix_permissions():
            os.chmod(tmp, FILE_MODE)  # before any content is written
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    restrict(p)
    return p


def write_text_atomic(path: str | Path, text: str) -> Path:
    return write_bytes_atomic(path, text.encode("utf-8"))


# ---- Playwright traces ----------------------------------------------------------------------------------------------------------
# A trace records every request and response with full headers, so a portal's session cookie ends up in it (measured: 14 copies
# of one cookie value in trace.network for two page loads). `scrub_trace` removes those values; the rest of the trace (page
# snapshots, response bodies, entered answers) is the run's own content and stays, which is why traces are opt-in.

SENSITIVE_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization", "x-api-key", "x-auth-token",
                               "x-csrf-token", "x-xsrf-token"})
REDACTED = "[redacted]"
_MIN_SECRET = 8  # shorter values are removed from the headers but not searched for elsewhere (too likely to hit other text)
_BINARY = (".jpeg", ".jpg", ".png", ".webp", ".gif", ".woff", ".woff2", ".ttf")


def _secret_parts(name: str, value: str) -> set[str]:
    """The values worth searching for elsewhere in the trace: the whole header value and each cookie / credential in it."""
    parts = {value}
    if name in ("cookie", "set-cookie"):
        pairs = value.split(";") if name == "cookie" else value.split(";", 1)[:1]
        parts |= {p.split("=", 1)[1].strip() for p in pairs if "=" in p}
    elif " " in value:  # "Bearer abc", "Basic ..."
        parts.add(value.split(" ", 1)[1].strip())
    return {p for p in parts if len(p) >= _MIN_SECRET}


def _scrub_node(node: object, secrets: set[str]) -> int:
    count = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "headers" and isinstance(value, list):
                for h in value:
                    name = str(h.get("name", "")).lower() if isinstance(h, dict) else ""
                    if name in SENSITIVE_HEADERS and h.get("value") not in (None, "", REDACTED):
                        secrets |= _secret_parts(name, str(h["value"]))
                        h["value"] = REDACTED
                        count += 1
            elif key == "cookies" and isinstance(value, list):
                for c in value:
                    if isinstance(c, dict) and c.get("value") not in (None, "", REDACTED):
                        if len(str(c["value"])) >= _MIN_SECRET:
                            secrets.add(str(c["value"]))
                        c["value"] = REDACTED
                        count += 1
            else:
                count += _scrub_node(value, secrets)
    elif isinstance(node, list):
        for item in node:
            count += _scrub_node(item, secrets)
    return count


def scrub_trace(path: str | Path) -> int:
    """Remove cookie, Set-Cookie, Authorization and similar header values (and HAR cookie values) from a Playwright trace zip,
    then remove those values wherever else they appear in its text entries (snapshots, response bodies). Rewrites the file
    atomically; returns how many values were removed. Idempotent."""
    import io
    import json
    import zipfile

    p = Path(path)
    with zipfile.ZipFile(p) as zin:
        entries = [(info, zin.read(info.filename)) for info in zin.infolist()]
    secrets: set[str] = set()
    count = 0
    scrubbed: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, data in entries:  # first pass: the network log, where headers and cookies are recorded
        if info.filename.endswith(".network"):
            lines = []
            for line in data.decode("utf-8", errors="replace").splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    lines.append(line)
                    continue
                count += _scrub_node(record, secrets)
                lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            data = ("\n".join(lines) + "\n").encode("utf-8")
        scrubbed.append((info, data))
    needles = sorted((s.encode("utf-8") for s in secrets), key=len, reverse=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info, data in scrubbed:  # second pass: the same values anywhere else (a page that echoes its token, ...)
            if not info.filename.lower().endswith(_BINARY):
                for needle in needles:
                    hits = data.count(needle)
                    if hits:
                        data = data.replace(needle, REDACTED.encode())
                        count += hits
            zout.writestr(info.filename, data)
    write_bytes_atomic(p, out.getvalue())
    return count
