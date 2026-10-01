"""Reads source data (JSON) into a simple flat lookup: dotted-path key ->
value. That's the entire representation -- no separate fact/evidence
objects. For this PoC, "where did this value come from" is just the key
itself, and the flat dict gives us that for free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_source(path: str | Path) -> dict[str, Any]:
    """Loads a JSON file and flattens nested objects/lists into dotted
    paths, e.g. {"applicant": {"name": "Jane"}} -> {"applicant.name": "Jane"}.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return dict(_flatten(data))


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            items.extend(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            items.extend(_flatten(value, f"{prefix}.{i}" if prefix else str(i)))
    elif obj is not None:
        items.append((prefix, obj))
    return items
