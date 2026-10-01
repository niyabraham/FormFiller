from formfill.form import FormField
from formfill.matcher import match_fields


def test_exact_match():
    fields = [FormField(name="email", label="Email", kind="text")]
    mappings = match_fields(fields, {"email": "jane@example.com"})
    assert mappings[0].status == "APPROVED"
    assert mappings[0].value == "jane@example.com"
    assert mappings[0].source_key == "email"


def test_alias_match():
    fields = [FormField(name="full_name", label="Name", kind="text")]
    mappings = match_fields(fields, {"applicant.full_name": "Jane Doe"})
    assert mappings[0].status == "APPROVED"
    assert mappings[0].source_key == "applicant.full_name"


def test_no_match_is_review_not_a_guess():
    fields = [FormField(name="gender", label="Gender", kind="radio", options=["/Male", "/Female"])]
    mappings = match_fields(fields, {"full_name": "Jane Doe"})
    assert mappings[0].status == "REVIEW"
    assert mappings[0].value is None
    assert "no matching" in mappings[0].reason


def test_date_format_hint_does_not_break_matching():
    """A label like 'Date of Birth (DD/MM/YYYY)' must still match the
    source key 'date_of_birth' -- the parenthetical hint shouldn't leak
    into the concept the matcher compares against."""
    fields = [FormField(name="dob", label="Date of Birth (DD/MM/YYYY)", kind="date")]
    mappings = match_fields(fields, {"date_of_birth": "1998-04-15"})
    assert mappings[0].status == "APPROVED"
