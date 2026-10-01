"""Deterministic validation and transformation -- just the two checks this
PoC actually needs: reformatting an ISO date, and making sure a value is
one of a field's allowed options. No generic rule framework. If a value
can't be made to satisfy the field, it's sent to review, never guessed.
"""

from __future__ import annotations

from datetime import date

from formfill.form import FormField
from formfill.matcher import Mapping


def validate_and_transform(mapping: Mapping, field: FormField) -> Mapping:
    if mapping.status != "APPROVED":
        return mapping

    value = mapping.value

    if field.kind == "date" and field.date_format:
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError:
            return _reject(mapping, f"'{value}' is not a valid ISO date (YYYY-MM-DD)")
        pattern = field.date_format.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
        value = parsed.strftime(pattern)

    if field.options:
        normalized = str(value).strip().lstrip("/").lower()
        matched = next((o for o in field.options if o.lstrip("/").lower() == normalized), None)
        if matched is None:
            return _reject(mapping, f"'{value}' is not one of the allowed options: {field.options}")
        value = matched

    if field.required and (value is None or str(value).strip() == ""):
        return _reject(mapping, "required but resolved to an empty value")

    mapping.value = value
    return mapping


def _reject(mapping: Mapping, reason: str) -> Mapping:
    mapping.status = "REVIEW"
    mapping.reason = reason
    return mapping
