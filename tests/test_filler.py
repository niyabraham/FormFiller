from pathlib import Path

import pytest
from pypdf import PdfReader

from formfill.filler import fill_form
from formfill.form import read_form_fields
from formfill.matcher import Mapping

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "form.pdf"


def test_fills_approved_values_into_a_copy(tmp_path):
    fields = read_form_fields(FIXTURE)
    mappings = [
        Mapping("full_name", "full_name", "Jane Doe", "APPROVED"),
        Mapping("date_of_birth", "date_of_birth", "15/04/1998", "APPROVED"),
        Mapping("email", None, None, "REVIEW", "no matching source field"),
        Mapping("gender", None, None, "REVIEW", "no matching source field"),
    ]
    output = tmp_path / "filled.pdf"
    fill_form(FIXTURE, output, fields, mappings)

    written = PdfReader(output).get_fields()
    assert written["full_name"]["/V"] == "Jane Doe"
    assert written["date_of_birth"]["/V"] == "15/04/1998"


def test_unresolved_radio_is_neutralized_not_left_at_template_default(tmp_path):
    """form.pdf's gender radio ships with Male pre-selected in the template
    itself (a pypdf/viewer quirk requires one option to start selected --
    see filler.py). An unresolved gender must not silently show that
    template default as if it were a real answer."""
    fields = read_form_fields(FIXTURE)
    mappings = [Mapping(f.name, None, None, "REVIEW", "no matching source field") for f in fields]
    output = tmp_path / "filled.pdf"
    fill_form(FIXTURE, output, fields, mappings)

    written = PdfReader(output).get_fields()
    assert written["gender"]["/V"] == "/Off"


def test_never_writes_to_the_template(tmp_path):
    original = FIXTURE.read_bytes()
    fields = read_form_fields(FIXTURE)
    mappings = [Mapping("full_name", "full_name", "Someone Else", "APPROVED")]
    fill_form(FIXTURE, tmp_path / "out.pdf", fields, mappings)
    assert FIXTURE.read_bytes() == original


def test_rejects_output_path_equal_to_template():
    fields = read_form_fields(FIXTURE)
    with pytest.raises(ValueError):
        fill_form(FIXTURE, FIXTURE, fields, [])
