"""Explicit network policy for a guarded wizard walk.

The default policy (no rules) blocks every request the browser makes during a walk; this is what `run_form` has always done.
Some portals cannot be walked that way: they load the next section from their server, or move from step to step with a form
POST. For those, a caller may list exactly which requests are needed. Nothing is permitted implicitly:

* a request is allowed only when an `AllowRule` names its origin, path, method and (optionally) resource type;
* a request that carries a value FormFiller entered into the form (in its URL or body) is blocked unless the matching rule
  says `answer_data=True`, so a background autosave or a step POST is never sent by accident;
* a Next button that submits a form may be pressed only when a rule with `form_navigation=True` covers the form's action;
* every other request, every other origin, and every unknown operation is blocked and recorded, and the walk stops.

Allowed requests are not let through the browser: the context stays offline, and the guard replays the request with
Playwright's own request client, one redirect hop at a time, checking each hop against this policy (see `guard.py`). So the
channels that request routing cannot see (prefetch hints, WebSockets in workers, WebRTC) stay blocked in every mode.

This module is pure: no Playwright import, so the decisions can be tested on their own.
"""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from urllib.parse import parse_qsl, unquote_plus, urlsplit

_READ_METHODS = frozenset({"GET", "HEAD"})


def origin_of(url: str) -> str:
    """scheme://host[:port] in lower case; '' for a URL that has no network origin (data:, blob:, about:)."""
    try:
        p = urlsplit(url)
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}".lower()


@dataclass(frozen=True)
class AllowRule:
    """One permitted kind of request. `origin` must be exact (scheme://host[:port]); `path` is a glob on the URL path
    (`/api/section/*`). Methods are upper case. `resource_types` (Playwright names: document, fetch, xhr, script, stylesheet,
    image, font, ...) narrows the rule; None means any. `note` is shown in the audit record."""

    origin: str
    path: str = "/*"
    methods: frozenset[str] = frozenset({"GET"})
    resource_types: frozenset[str] | None = None
    answer_data: bool = False  # may the request carry answers FormFiller entered (a background save, a step POST)?
    form_navigation: bool = False  # may a Next button that submits a form to this endpoint be pressed?
    note: str = ""

    def __post_init__(self) -> None:
        if not origin_of(self.origin) or origin_of(self.origin) != self.origin.lower().rstrip("/"):
            raise ValueError(f"AllowRule.origin must be scheme://host[:port], got {self.origin!r}")
        object.__setattr__(self, "origin", self.origin.lower().rstrip("/"))
        object.__setattr__(self, "methods", frozenset(m.upper() for m in self.methods))
        if not self.path.startswith("/"):
            raise ValueError(f"AllowRule.path must start with '/', got {self.path!r}")
        if self.form_navigation and not self.answer_data:
            raise ValueError("a form_navigation rule sends the form's answers, so it must also set answer_data=True")

    def matches(self, url: str, method: str, resource_type: str | None = None) -> bool:
        if origin_of(url) != self.origin or method.upper() not in self.methods:
            return False
        if self.resource_types is not None and (resource_type or "") not in self.resource_types:
            return False
        try:
            path = urlsplit(url).path or "/"
        except ValueError:
            return False
        return fnmatch.fnmatchcase(path, self.path)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["methods"] = sorted(self.methods)
        d["resource_types"] = sorted(self.resource_types) if self.resource_types is not None else None
        return d


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    rule: AllowRule | None = None
    carries_answers: bool = False


def _decoded_texts(url: str, body: bytes | None) -> list[str]:
    """Every readable form of the URL and body in which an entered value could appear."""
    texts = [url, unquote_plus(url)]
    try:
        q = urlsplit(url).query
        texts += [v for _, v in parse_qsl(q, keep_blank_values=True)]
    except ValueError:
        pass
    if body:
        raw = body.decode("utf-8", errors="replace")
        texts += [raw, unquote_plus(raw)]
        try:
            texts.append(json.dumps(json.loads(raw), ensure_ascii=False))
        except (ValueError, TypeError):
            pass
    return texts


def entered_values_in(url: str, body: bytes | None, entered: Iterable[str], min_length: int = 4) -> list[str]:
    """Entered answers that appear in the URL or body of a request (case-insensitive). Values shorter than `min_length` and
    yes/no style values are ignored: "Yes" or "12" occur in ordinary requests and say nothing about the questionnaire.
    A match blocks the request unless a rule allows answer data, so a false match fails closed."""
    candidates = {str(v).strip() for v in entered if v is not None}
    candidates = {v for v in candidates if len(v) >= min_length and v.casefold() not in {"true", "false", "yes", "no", "none"}}
    if not candidates:
        return []
    haystack = "\n".join(_decoded_texts(url, body)).casefold()
    return sorted(v for v in candidates if v.casefold() in haystack)


@dataclass(frozen=True)
class NetworkPolicy:
    """What a guarded walk may send. `NetworkPolicy()` blocks everything (the default). See the module docstring."""

    rules: tuple[AllowRule, ...] = ()
    relay_timeout_ms: int = 10_000
    max_redirects: int = 5
    max_response_bytes: int = 5_000_000
    min_tainted_length: int = 4

    @property
    def blocks_everything(self) -> bool:
        return not self.rules

    def decide(self, url: str, method: str, resource_type: str | None = None, body: bytes | None = None,
               entered: Iterable[str] = ()) -> Decision:
        method = method.upper()
        if not origin_of(url):
            return Decision(False, "not an http(s) request")
        rule = next((r for r in self.rules if r.matches(url, method, resource_type)), None)
        if rule is None:
            if not self.rules:
                return Decision(False, "all requests are blocked during a guarded walk")
            return Decision(False, f"no allow rule covers {method} {origin_of(url)}{_path(url)} ({resource_type or 'unknown type'})")
        tainted = entered_values_in(url, body, entered, self.min_tainted_length)
        if tainted and not rule.answer_data:
            return Decision(False, f"the request carries {len(tainted)} value(s) FormFiller entered, and the matching rule does not allow answer data",
                            rule, carries_answers=True)
        if method not in _READ_METHODS and not rule.answer_data:
            # a write that does not carry an entered value can still change server state; the rule must say writes are expected
            return Decision(False, f"{method} changes server state and the matching rule does not allow answer data", rule)
        return Decision(True, rule.note or "allowed by rule", rule, carries_answers=bool(tainted))

    def form_navigation_rule(self, action_url: str, method: str = "POST") -> AllowRule | None:
        """The rule that lets a Next button submit a form to `action_url`, if any."""
        return next((r for r in self.rules if r.form_navigation and r.matches(action_url, method, "document")), None)

    def to_dict(self) -> dict:
        return {"rules": [r.to_dict() for r in self.rules], "relay_timeout_ms": self.relay_timeout_ms,
                "max_redirects": self.max_redirects, "max_response_bytes": self.max_response_bytes}

    @classmethod
    def from_dict(cls, data: dict) -> NetworkPolicy:
        """Build a policy from configuration (JSON). Unknown keys are refused rather than ignored."""
        known = {"rules", "relay_timeout_ms", "max_redirects", "max_response_bytes", "min_tainted_length"}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown network policy keys: {sorted(unknown)}")
        rule_keys = {"origin", "path", "methods", "resource_types", "answer_data", "form_navigation", "note"}
        rules = []
        for r in data.get("rules", []):
            bad = set(r) - rule_keys
            if bad:
                raise ValueError(f"unknown allow-rule keys: {sorted(bad)}")
            r = dict(r)
            r["methods"] = frozenset(r.get("methods", ["GET"]))
            if r.get("resource_types") is not None:
                r["resource_types"] = frozenset(r["resource_types"])
            rules.append(AllowRule(**r))
        return cls(rules=tuple(rules), **{k: data[k] for k in known - {"rules"} if k in data})


def redact_url(url: str) -> str:
    """scheme://host/path of a URL: the query string and fragment are dropped because they may carry tokens or form data."""
    try:
        p = urlsplit(url)
    except ValueError:
        return url.split("?", 1)[0].split("#", 1)[0]
    if not p.scheme:
        return url.split("?", 1)[0].split("#", 1)[0]
    if p.netloc or p.scheme == "file":
        return f"{p.scheme}://{p.netloc}{p.path}"
    return f"{p.scheme}:{p.path}"


def _path(url: str) -> str:
    try:
        return urlsplit(url).path
    except ValueError:
        return ""
