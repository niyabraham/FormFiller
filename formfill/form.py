"""Reads a fillable PDF's native AcroForm fields into simple FormField
objects. Native structure only -- no OCR, no layout detection. A PDF
without AcroForm fields (a scanned/static form) isn't supported by this PoC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

_REQUIRED_FLAG = 1 << 1  # PDF spec: bit 2 of /Ff on a field is "Required"
_MULTILINE_FLAG = 1 << 12
_DATE_FORMAT_HINT_RE = re.compile(r"\(([DMY/\-]{4,})\)", re.IGNORECASE)


@dataclass
class FormField:
    name: str  # the PDF's own field name -- also used to write values back
    label: str  # human-readable label/tooltip, used for matching
    kind: str  # "text" | "date" | "radio" | "checkbox" | "dropdown"
    required: bool = False
    options: list[str] = field(default_factory=list)  # allowed values for radio/checkbox/dropdown
    date_format: str | None = None  # e.g. "DD/MM/YYYY", parsed from the label if present


def read_form_fields(path: str | Path) -> list[FormField]:
    reader = PdfReader(path)
    acroform = reader.trailer.get("/Root", {}).get("/AcroForm")
    if not acroform or not acroform.get("/Fields"):
        raise ValueError(f"{path} has no fillable AcroForm fields")

    fields: list[FormField] = []
    for name, raw in (reader.get_fields() or {}).items():
        if raw.get("/Kids") and raw.get("/FT") != "/Btn":
            continue  # a table/repeating field -- out of scope for this PoC

        label = str(raw.get("/TU") or name)
        flags = int(raw.get("/Ff") or 0)
        required = bool(flags & _REQUIRED_FLAG)
        ft = raw.get("/FT")

        if ft == "/Tx":
            if flags & _MULTILINE_FLAG:
                kind, date_format = "text", None
            elif "date" in label.lower():
                kind = "date"
                match = _DATE_FORMAT_HINT_RE.search(label)
                date_format = match.group(1).upper() if match else None
            else:
                kind, date_format = "text", None
            fields.append(FormField(name, label, kind, required, date_format=date_format))

        elif ft == "/Btn":
            states = _states(raw)
            if raw.get("/Kids"):
                fields.append(FormField(name, label, "radio", required, [s for s in states if s != "/Off"]))
            else:
                fields.append(FormField(name, label, "checkbox", required, states or ["/Yes", "/Off"]))

        elif ft == "/Ch":
            fields.append(FormField(name, label, "dropdown", required, _states(raw)))

    return fields


def _states(raw) -> list[str]:
    """pypdf's /_States_ holds either plain strings or [value, text] pairs."""
    return [str(s[0]) if isinstance(s, list) else str(s) for s in (raw.get("/_States_") or [])]
