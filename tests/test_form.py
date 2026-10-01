from pathlib import Path

import pytest

from formfill.form import read_form_fields

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "form.pdf"


def test_reads_all_fields_with_correct_kinds_and_required_flags():
    fields = {f.name: f for f in read_form_fields(FIXTURE)}
    assert set(fields) == {"full_name", "date_of_birth", "email", "gender"}

    assert fields["full_name"].kind == "text"
    assert fields["full_name"].required is True

    assert fields["date_of_birth"].kind == "date"
    assert fields["date_of_birth"].date_format == "DD/MM/YYYY"

    assert fields["email"].required is False

    assert fields["gender"].kind == "radio"
    assert set(fields["gender"].options) == {"/Male", "/Female"}


def test_raises_a_clear_error_for_a_pdf_with_no_form_fields(tmp_path):
    from reportlab.pdfgen import canvas

    plain = tmp_path / "plain.pdf"
    c = canvas.Canvas(str(plain))
    c.drawString(100, 700, "no form fields here")
    c.save()

    with pytest.raises(ValueError, match="AcroForm"):
        read_form_fields(plain)
