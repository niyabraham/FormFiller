"""Reasoning layer, step 4: deterministic validation + transformation of a
candidate value against the control that will receive it -- before the
browser is touched.

Plain functions over the Control's own HTML constraints (type, options,
min/max, maxlength, pattern, required). No schema framework: the
constraints are already on the Control, and a failure here means REVIEW,
never a coerced guess. Values are never truncated to fit maxlength.

Note: `pattern` is evaluated with Python's `re`, the browser with
JavaScript's; the post-fill browser validity check (`checkValidity`) is the
authority and catches any difference.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

from formfill.web.models import Control

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Validated:
    ok: bool
    value: Any = None
    reason: str | None = None


def _fail(reason: str) -> Validated:
    return Validated(False, None, reason)


def _to_number(v: Any) -> int | float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    elif isinstance(v, str):
        try:
            n = float(v.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return int(n) if n.is_integer() else n


def _to_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in _TRUE | _FALSE:
        return v.strip().lower() in _TRUE
    return None


def _match_option(value: Any, control: Control) -> str | None:
    """Option value whose value or label equals `value` (case-insensitive).
    A JSON boolean matches a yes/no style option."""
    candidates = [str(value).strip().lower()]
    b = _to_bool(value) if isinstance(value, bool) else None
    if b is not None:
        candidates += ["yes", "true"] if b else ["no", "false"]
    for want in candidates:
        for o in control.options:
            if want in (o.value.strip().lower(), o.label.strip().lower()):
                return o.value
    return None


def validate_answer(value: Any, control: Control) -> Validated:
    if value is None or (isinstance(value, str) and not value.strip()):
        return _fail("source value is empty")
    kind = control.kind

    if kind == "number":
        n = _to_number(value)
        if n is None:
            return _fail(f"{value!r} is not a number")
        if control.step in (None, "1") and not float(n).is_integer():
            return _fail(f"{value!r} is not a whole number (field step is 1)")
        if control.min not in (None, "") and n < float(control.min):
            return _fail(f"{n} is below the minimum {control.min}")
        if control.max not in (None, "") and n > float(control.max):
            return _fail(f"{n} is above the maximum {control.max}")
        return Validated(True, n)

    if kind == "date":
        try:
            d = date.fromisoformat(str(value).strip())
        except ValueError:
            return _fail(f"{value!r} is not an ISO date (YYYY-MM-DD)")
        for bound, cmp in ((control.min, lambda a, b: a < b), (control.max, lambda a, b: a > b)):
            if bound:
                try:
                    if cmp(d, date.fromisoformat(bound)):
                        return _fail(f"{d} is outside the allowed range ({control.min}..{control.max})")
                except ValueError:
                    pass
        return Validated(True, d.isoformat())

    if kind in ("select", "radio"):
        if isinstance(value, (list, dict)):
            return _fail("a single value is required but the source has a list")
        matched = _match_option(value, control)
        if matched is None:
            return _fail(f"{value!r} is not one of the allowed options {[o.value for o in control.options]}")
        return Validated(True, matched)

    if kind in ("multiselect", "checkbox_group"):
        items = value if isinstance(value, list) else [value]
        chosen: list[str] = []
        for item in items:
            m = _match_option(item, control)
            if m is None:
                return _fail(f"{item!r} is not one of the allowed options {[o.value for o in control.options]}")
            if m not in chosen:
                chosen.append(m)
        return Validated(True, chosen)

    if kind == "checkbox":
        b = _to_bool(value)
        return Validated(True, b) if b is not None else _fail(f"{value!r} is not a yes/no value")

    # text-like: text, textarea, email, url, tel, anything else
    if isinstance(value, (list, dict)) or isinstance(value, bool):
        return _fail(f"{value!r} cannot be entered as text")
    text = str(value).strip()
    if kind == "email" and not _EMAIL.match(text):
        return _fail(f"{text!r} is not a valid email address")
    if kind == "url":
        p = urlparse(text)
        if p.scheme not in ("http", "https") or not p.netloc:
            return _fail(f"{text!r} is not a valid http(s) URL")
    if control.maxlength is not None and len(text) > control.maxlength:
        return _fail(f"value is {len(text)} characters; the field allows {control.maxlength}")
    if control.minlength is not None and len(text) < control.minlength:
        return _fail(f"value is {len(text)} characters; the field needs at least {control.minlength}")
    if control.pattern:
        try:
            if not re.fullmatch(control.pattern, text):
                return _fail(f"{text!r} does not match the field pattern {control.pattern!r}")
        except re.error:
            pass  # JS-only regex syntax: leave it to the browser's checkValidity
    return Validated(True, text)
