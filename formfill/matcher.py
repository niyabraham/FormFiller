"""Matches source data to form fields: exact key match, then a small alias
table. That's the whole matching strategy for this PoC -- no embeddings, no
vector search, no LLM. See README for where those would plug in later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from formfill.form import FormField

# Each set is one "concept" -- a label slug or source key matching any
# member of the same set is considered the same thing.
ALIASES: list[set[str]] = [
    {"full_name", "name", "applicant_name", "legal_name"},
    {"date_of_birth", "dob", "birth_date", "birthdate"},
    {"email", "email_address", "contact_email"},
    {"gender", "sex"},
]


@dataclass
class Mapping:
    field_name: str
    source_key: str | None
    value: Any
    status: str  # "APPROVED" | "REVIEW"
    reason: str | None = None  # set when status == "REVIEW"


def _slug(text: str) -> str:
    text = re.sub(r"\([^)]*\)", "", text)  # strip parenthetical hints, e.g. "(DD/MM/YYYY)"
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _alias_group(slug: str) -> set[str] | None:
    return next((group for group in ALIASES if slug in group), None)


def match_fields(fields: list[FormField], source: dict[str, Any]) -> list[Mapping]:
    """For each field: try an exact concept match first, then an alias
    match. First hit wins. No match at all -> REVIEW, never a guess.
    """
    source_slugs = {key: _slug(key.split(".")[-1]) for key in source}

    mappings = []
    for f in fields:
        label_slug = _slug(f.label)

        match_key = next((k for k, s in source_slugs.items() if s == label_slug), None)
        if match_key is None:
            group = _alias_group(label_slug)
            if group:
                match_key = next((k for k, s in source_slugs.items() if s in group), None)

        if match_key is None:
            mappings.append(Mapping(f.name, None, None, "REVIEW", "no matching source field"))
        else:
            mappings.append(Mapping(f.name, match_key, source[match_key], "APPROVED"))
    return mappings
