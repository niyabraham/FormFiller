"""Loading and describing the JSON source.

`load_source` is the only way the CLI and `run_url` read a source file. It fails with a message a person can act on
(missing file, invalid JSON with line/column, a top-level value that is not an object, nothing answerable inside).

Normalisation is `retrieve.index_source`: nested objects and arrays are flattened to dotted paths ("a.b.0.c"), a list
of scalars stays one answerable leaf (multi-select questions), nulls and empty strings are not answers and are skipped,
and every key becomes tokens by the same function the questions use (snake_case / camelCase / spaces, stemmed, with
the closed vocabulary in lexicon.json). `describe` reports what that produced, so a source can be checked before a run.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from formfill.web.retrieve import index_source
from formfill.web.validate import is_placeholder


class SourceError(ValueError):
    """The source file cannot be used. The message says why and where."""


def load_source(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file():
        raise SourceError(f"source file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise SourceError(f"{p}: not UTF-8 text ({exc.reason})") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"{p}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SourceError(f"{p}: the top level must be a JSON object (company data), not {type(data).__name__}")
    if not index_source(data):
        raise SourceError(f"{p}: contains no answerable values (every field is null, empty or an empty list)")
    return data


def describe(data: Any) -> dict:
    """What the pipeline will be able to answer from, and what it will ignore."""
    leaves = index_source(data)
    kinds = Counter(type(leaf.value).__name__ for leaf in leaves)
    placeholders = [leaf.path for leaf in leaves if is_placeholder(leaf.value)]
    seen: dict[tuple, list[str]] = {}
    for leaf in leaves:
        seen.setdefault(tuple(sorted(leaf.leaf_tokens)), []).append(leaf.path)
    repeated = {" ".join(k): v for k, v in seen.items() if len({p.rsplit(".", 1)[0] for p in v}) > 1}
    return {"answerable_values": len(leaves), "value_types": dict(sorted(kinds.items())), "placeholder_values": placeholders,
            "same_field_name_under_different_parents": repeated, "paths": [leaf.path for leaf in leaves]}
