from pathlib import Path

from pypdf import PdfReader

from formfill.filler import fill_form
from formfill.form import read_form_fields
from formfill.matcher import match_fields
from formfill.source import load_source
from formfill.validator import validate_and_transform
from formfill.verifier import verify

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_full_pipeline_fills_three_fields_and_flags_gender_for_review(tmp_path):
    source = load_source(EXAMPLES / "source.json")
    fields = read_form_fields(EXAMPLES / "form.pdf")
    mappings = [validate_and_transform(m, f) for m, f in zip(match_fields(fields, source), fields)]

    by_name = {m.field_name: m for m in mappings}
    assert by_name["full_name"].status == "APPROVED"
    assert by_name["date_of_birth"].value == "15/04/1998"
    assert by_name["email"].status == "APPROVED"
    assert by_name["gender"].status == "REVIEW"

    output = tmp_path / "filled.pdf"
    fill_form(EXAMPLES / "form.pdf", output, fields, mappings)
    results = verify(output, mappings)
    assert not all(r.passed for r in results)  # gender is still unresolved

    written = PdfReader(output).get_fields()
    assert written["full_name"]["/V"] == "Jane Doe"
    assert written["gender"]["/V"] == "/Off"  # never guessed


def test_resolving_review_then_rerendering_reaches_full_pass(tmp_path):
    source = load_source(EXAMPLES / "source.json")
    fields = read_form_fields(EXAMPLES / "form.pdf")
    mappings = [validate_and_transform(m, f) for m, f in zip(match_fields(fields, source), fields)]

    gender = next(m for m in mappings if m.field_name == "gender")
    gender.source_key, gender.value, gender.status, gender.reason = "human_review", "Female", "APPROVED", None
    field_by_name = {f.name: f for f in fields}
    validate_and_transform(gender, field_by_name["gender"])

    output = tmp_path / "filled_final.pdf"
    fill_form(EXAMPLES / "form.pdf", output, fields, mappings)
    results = verify(output, mappings)
    assert all(r.passed for r in results)

    written = PdfReader(output).get_fields()
    assert written["gender"]["/V"] == "/Female"
