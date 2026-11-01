"""demo.py pairs each mapping with its form field by position. That is only correct while match_fields returns exactly one mapping
per field, in order; a length mismatch is a bug and must fail loudly instead of silently leaving fields unvalidated and unfilled."""

import importlib.util
from pathlib import Path

import pytest

from formfill.form import read_form_fields
from formfill.source import load_source

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def _load_demo():
    spec = importlib.util.spec_from_file_location("formfill_demo", ROOT / "demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


demo = _load_demo()


def test_map_and_validate_returns_one_validated_mapping_per_field_in_order():
    fields = read_form_fields(EXAMPLES / "form.pdf")
    mappings = demo.map_and_validate(fields, load_source(EXAMPLES / "source.json"))
    assert [m.field_name for m in mappings] == [f.name for f in fields]
    assert next(m for m in mappings if m.field_name == "gender").status == "REVIEW"  # still flagged, never guessed


def test_a_mapping_list_of_the_wrong_length_fails_loudly(monkeypatch):
    fields = read_form_fields(EXAMPLES / "form.pdf")
    real = demo.match_fields
    monkeypatch.setattr(demo, "match_fields", lambda f, s: real(f, s)[:-1])  # one mapping missing
    with pytest.raises(ValueError):
        demo.map_and_validate(fields, load_source(EXAMPLES / "source.json"))
