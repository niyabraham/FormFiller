"""Reopens the filled PDF independently and checks it actually contains
what the mapping claims -- a successful write isn't the same thing as a
successful fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from formfill.matcher import Mapping


@dataclass
class VerificationResult:
    field_name: str
    passed: bool
    detail: str


def verify(output_path: str | Path, mappings: list[Mapping]) -> list[VerificationResult]:
    fields_in_pdf = PdfReader(output_path).get_fields() or {}

    results = []
    for m in mappings:
        if m.status != "APPROVED":
            results.append(VerificationResult(m.field_name, False, "unresolved -- needs human review"))
            continue
        actual = fields_in_pdf.get(m.field_name, {}).get("/V")
        if str(actual) == str(m.value):
            results.append(VerificationResult(m.field_name, True, "matches the approved value"))
        else:
            results.append(VerificationResult(m.field_name, False, f"expected {m.value!r}, found {actual!r}"))
    return results
