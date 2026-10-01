from formfill.form import FormField
from formfill.matcher import Mapping
from formfill.validator import validate_and_transform


def test_date_gets_reformatted():
    field = FormField(name="dob", label="DOB", kind="date", date_format="DD/MM/YYYY")
    mapping = Mapping("dob", "date_of_birth", "1998-04-15", "APPROVED")
    result = validate_and_transform(mapping, field)
    assert result.status == "APPROVED"
    assert result.value == "15/04/1998"


def test_unparseable_date_goes_to_review():
    field = FormField(name="dob", label="DOB", kind="date", date_format="DD/MM/YYYY")
    mapping = Mapping("dob", "date_of_birth", "not-a-date", "APPROVED")
    result = validate_and_transform(mapping, field)
    assert result.status == "REVIEW"


def test_value_not_in_allowed_options_is_review_not_guessed():
    """Directly implements the project's core rule: target only accepts
    Male/Female, source says Unknown -- must not silently pick one."""
    field = FormField(name="gender", label="Gender", kind="radio", options=["/Male", "/Female"])
    mapping = Mapping("gender", "gender", "Unknown", "APPROVED")
    result = validate_and_transform(mapping, field)
    assert result.status == "REVIEW"
    assert "Unknown" in result.reason


def test_value_matching_an_option_is_normalized():
    field = FormField(name="gender", label="Gender", kind="radio", options=["/Male", "/Female"])
    mapping = Mapping("gender", "gender", "Female", "APPROVED")
    result = validate_and_transform(mapping, field)
    assert result.status == "APPROVED"
    assert result.value == "/Female"


def test_required_field_resolving_to_blank_is_review():
    field = FormField(name="full_name", label="Name", kind="text", required=True)
    mapping = Mapping("full_name", "full_name", "   ", "APPROVED")
    result = validate_and_transform(mapping, field)
    assert result.status == "REVIEW"


def test_review_mappings_pass_through_untouched():
    field = FormField(name="gender", label="Gender", kind="radio", options=["/Male", "/Female"])
    mapping = Mapping("gender", None, None, "REVIEW", "no matching source field")
    result = validate_and_transform(mapping, field)
    assert result.status == "REVIEW"
    assert result.reason == "no matching source field"
