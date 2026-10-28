"""<input type=color> was discovered as kind 'color', planned as ANSWER, then failed at fill time ("unsupported control kind"),
ending the run FAILED. It is now validated as a hex colour (normalised to the lower-case #rrggbb a colour input holds) and filled."""

import pytest

from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

HTML = ("<form onsubmit='return false'><label>Brand colour <input type=color name=brand value='#563d7c'></label></form>")


@pytest.mark.parametrize("given, held", [("#ff0000", "#ff0000"), ("#FF8800", "#ff8800"), ("#0af", "#00aaff")])
def test_color_input_is_filled_and_verified(page, given, held):
    page.set_content(HTML)
    res = run_form(page, {"brand_colour": given}, confirm_ms=0)
    item = res.items[0]
    assert item.plan.status == "ANSWER" and item.filled and item.verified is True
    assert page.input_value("input") == held and res.status == "FILLED"


@pytest.mark.parametrize("bad", ["red", "#12", "#gggggg", "rgb(1,2,3)"])
def test_non_hex_color_goes_to_review_and_leaves_the_default(page, bad):
    page.set_content(HTML)
    res = run_form(page, {"brand_colour": bad}, confirm_ms=0)
    assert res.items[0].plan.status == "REVIEW" and page.input_value("input") == "#563d7c"
    assert res.status == "NEEDS_REVIEW"
