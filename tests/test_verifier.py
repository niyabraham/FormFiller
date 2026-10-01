from pathlib import Path

from formfill.filler import fill_form
from formfill.form import read_form_fields
from formfill.matcher import Mapping
from formfill.verifier import verify

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "form.pdf"


def test_verify_passes_when_rendered_values_match(tmp_path):
    fields = read_form_fields(FIXTURE)
    mappings = [Mapping("full_name", "full_name", "Jane Doe", "APPROVED")]
    output = tmp_path / "filled.pdf"
    fill_form(FIXTURE, output, fields, mappings)

    results = verify(output, mappings)
    assert results[0].passed is True


def test_verify_fails_a_review_status_field():
    mappings = [Mapping("gender", None, None, "REVIEW", "no matching source field")]
    results = verify(FIXTURE, mappings)  # unfilled template -- gender was never approved anyway
    assert results[0].passed is False
    assert "review" in results[0].detail.lower()


def test_verify_catches_a_mismatch(tmp_path):
    fields = read_form_fields(FIXTURE)
    fill_form(FIXTURE, tmp_path / "filled.pdf", fields, [Mapping("full_name", "full_name", "Jane Doe", "APPROVED")])

    tampered = [Mapping("full_name", "full_name", "Someone Else", "APPROVED")]
    results = verify(tmp_path / "filled.pdf", tampered)
    assert results[0].passed is False
