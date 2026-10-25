"""Visible controls FormFiller cannot fill or verify (file/password inputs, contenteditable regions, custom ARIA widgets, signature
canvases) must be reported, never touched, and must stop a run from being reported FILLED. A required one blocks submission.
Before this existed they were skipped without a word: a form with one answerable text field and a required upload ended FILLED.
"""

import pytest

from formfill.web.discover import find_unsupported
from formfill.web.pipeline import run_form
from formfill.web.steps import DiscoveryPolicy

pytestmark = pytest.mark.browser

SRC = {"company": {"legal_name": "Northwind Ltd"}}
TEXT = "<label for=a>Legal name</label><input id=a name=a>"


def page_with(page, html):
    page.set_content("<body><form onsubmit='return false'>" + TEXT + html + "</form></body>")
    return page


def kinds(res):
    return sorted((u["kind"], u["required"]) for u in res.unsupported)


# ---- the four reported cases ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("html, kind", [
    ("<label for=c>Upload certificate (required)</label><input id=c name=c type=file required>", "file_upload"),
    ("<div role=textbox contenteditable=true aria-label='Signatory statement' aria-required=true></div>", "contenteditable"),
    ("<div role=listbox aria-label='Sector' aria-required=true tabindex=0><div role=option>A</div></div>", "aria_listbox"),
])
def test_required_unsupported_control_is_reported_and_blocks_a_filled_status(page, html, kind):
    res = run_form(page_with(page, html), SRC, confirm_ms=0)
    assert res.items[0].verified is True  # the supported field was filled and verified ...
    assert kinds(res) == [(kind, True)]  # ... and the unsupported one is on the record, as required
    assert res.status == "NEEDS_REVIEW" and any("cannot be filled" in w for w in res.warnings)


def test_signature_canvas_is_reported_as_optional_unless_marked_required(page):
    res = run_form(page_with(page, "<canvas id=sig width=200 height=60 aria-label='Sign here'></canvas>"), SRC, confirm_ms=0)
    assert kinds(res) == [("canvas_signature", False)] and res.status == "NEEDS_REVIEW"


def test_record_identifies_the_control_and_says_why_it_was_skipped(page):
    res = run_form(page_with(page, "<label for=c>Upload certificate *</label><input id=c name=cert type=file>"), SRC, confirm_ms=0)
    u = res.unsupported[0]
    assert (u["label"], u["tag"], u["html_id"], u["name"], u["input_type"]) == ("Upload certificate *", "input", "c", "cert", "file")
    assert u["required"] is True and u["required_basis"] == "label text" and "never uploads" in u["reason"] and u["frame_index"] == 0
    assert res.to_dict()["unsupported"][0]["kind"] == "file_upload"


def test_password_field_is_reported_and_never_filled(page):
    res = run_form(page_with(page, "<label for=p>Portal password</label><input id=p type=password>"), SRC, confirm_ms=0)
    assert kinds(res) == [("password", False)] and page.input_value("#p") == "" and res.status == "NEEDS_REVIEW"


# ---- required versus optional, and the submission gate ---------------------------------------------------------------

def test_required_basis_attribute_aria_and_label_text(page):
    html = ("<input type=file id=f1 aria-label='A' required><input type=file id=f2 aria-label='B' aria-required=true>"
            "<input type=file id=f3 aria-label='C (required)'><input type=file id=f4 aria-label='D'>")
    res = run_form(page_with(page, html), SRC, confirm_ms=0)
    got = {u["html_id"]: (u["required"], u["required_basis"]) for u in res.unsupported}
    assert got == {"f1": (True, "attribute"), "f2": (True, "attribute"), "f3": (True, "label text"), "f4": (False, None)}


def test_required_unsupported_control_blocks_submission(page):
    html = "<input type=file id=c aria-label='Certificate' required><button id=go type=submit>Send</button>"
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go")
    assert res.submission["attempted"] is False and res.submission["outcome"] == "SKIPPED"
    assert "required control(s) cannot be filled" in res.submission["detail"] and res.status == "NEEDS_REVIEW"


OPT = "<input type=file id=c aria-label='Optional attachment'><button id=go type=submit>Send</button>"


def test_optional_unsupported_control_blocks_submission_without_an_explicit_decision(page):
    res = run_form(page_with(page, OPT), SRC, confirm_ms=0, submit=True, submit_selector="#go")
    assert res.submission["outcome"] == "SKIPPED" and res.submission["attempted"] is False
    assert "optional unsupported" in res.submission["detail"] and "acknowledge_unsupported" in res.submission["detail"]
    assert res.status == "NEEDS_REVIEW" and kinds(res) == [("file_upload", False)]


def test_acknowledging_every_optional_unsupported_control_allows_submission_but_never_filled(page):
    page_with(page, OPT)
    page.evaluate("document.forms[0].addEventListener('submit', () => { window.__sent = (window.__sent||0)+1 })")
    res = run_form(page, SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["c"])
    assert res.submission["attempted"] is True and page.evaluate("window.__sent") == 1
    assert page.eval_on_selector("#c", "e => e.files.length") == 0  # still never touched


def test_acknowledging_an_unrelated_id_does_not_help(page):
    res = run_form(page_with(page, OPT), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["other"])
    assert res.submission["outcome"] == "SKIPPED"


def test_partial_acknowledgement_still_blocks(page):
    html = OPT + "<input type=password id=pw aria-label='Pass'>"
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["c"])
    assert res.submission["outcome"] == "SKIPPED"


def test_required_unsupported_control_blocks_even_when_acknowledged(page):
    html = "<input type=file id=c required aria-label='Cert'><button id=go type=submit>Send</button>"
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["c"])
    assert res.submission["outcome"] == "SKIPPED" and "required control(s)" in res.submission["detail"]


def test_conditional_unsupported_control_revealed_by_answering_blocks_submission(page):
    page.set_content("<body><form onsubmit='return false'>" + TEXT +
                     "<div id=slot hidden><input type=file id=c aria-label='Extra evidence'></div>"
                     "<button id=go type=submit>Send</button></form>"
                     "<script>a.addEventListener('input',()=>slot.hidden=false)</script></body>")
    res = run_form(page, SRC, confirm_ms=0, submit=True, submit_selector="#go")
    assert kinds(res) == [("file_upload", False)]
    assert res.submission["outcome"] == "SKIPPED" and res.status != "FILLED"


def test_runresult_is_backward_compatible(page):
    from formfill.web.result import RunResult
    r = RunResult("u", "FILLED", [], {}, {}, [], {}, {}, "rid", "t0", "t1")  # old positional order is still honoured
    assert (r.run_id, r.started_at, r.finished_at) == ("rid", "t0", "t1") and r.controls == {}
    d = RunResult("u", "FILLED", []).to_dict()
    assert {"url", "status", "items", "submission", "artifacts", "warnings", "navigation", "run_id", "started_at", "finished_at",
            "review_items"} <= set(d)
    assert d["unsupported"] == []
    res = run_form(page_with(page, ""), SRC, confirm_ms=0)
    assert res.unsupported == [] and res.status == "FILLED"


def test_nothing_is_uploaded_typed_or_changed_on_unsupported_controls(page):
    html = ("<input type=file id=c aria-label='File'><div id=ce contenteditable=true aria-label='Notes'></div>"
            "<div id=sw role=switch aria-checked=false aria-label='Opt in' tabindex=0></div>")
    res = run_form(page_with(page, html), SRC, confirm_ms=0)
    assert len(res.unsupported) == 3
    assert page.eval_on_selector("#c", "e => e.files.length") == 0
    assert page.inner_text("#ce") == "" and page.get_attribute("#sw", "aria-checked") == "false"


# ---- visibility ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("html", [
    "<input type=file aria-label='x' style='display:none'>",
    "<input type=file aria-label='x' hidden>",
    "<div aria-hidden=true><input type=file aria-label='x'></div>",
    "<div inert><div contenteditable=true aria-label='x'></div></div>",
    "<div style='display:none'><canvas width=200 height=60 aria-label='Sign here'></canvas></div>",
    "<input type=file aria-label='x' disabled>",
    "<div role=textbox aria-label='x' aria-disabled=true></div>",
    "<input type=file id=f style='display:none'><label for=f style='display:none'>Upload</label>",
])
def test_hidden_or_disabled_controls_are_not_reported(page, html):
    res = run_form(page_with(page, html), SRC, confirm_ms=0)
    assert res.unsupported == [] and res.status == "FILLED"


def test_visually_hidden_file_input_with_a_visible_label_is_reported(page):
    res = run_form(page_with(page, "<input type=file id=f style='display:none'><label for=f>Upload your report (required)</label>"),
                   SRC, confirm_ms=0)
    assert kinds(res) == [("file_upload", True)] and res.unsupported[0]["label"] == "Upload your report (required)"


def test_control_revealed_by_the_page_after_load_is_reported(page):
    page_with(page, "<div id=slot hidden><input type=file aria-label='Late upload'></div>"
                    "<script>setTimeout(()=>slot.hidden=false,100)</script>")
    page.wait_for_timeout(250)
    res = run_form(page, SRC, confirm_ms=0)
    assert kinds(res) == [("file_upload", False)]


# ---- false positives ------------------------------------------------------------------------------------------------------

def test_supported_controls_are_not_reported_as_unsupported(page):
    html = ("<select id=s aria-label='Sector'><option>A</option></select><textarea id=t aria-label='Notes'></textarea>"
            "<label><input type=radio name=r value=y> Yes</label><label><input type=checkbox name=c> Tick</label>"
            "<input type=checkbox role=switch aria-label='Native switch'><input type=text role=textbox aria-label='Native with role'>")
    assert find_unsupported(page_with(page, html)) == []


def test_unrelated_canvases_and_noncontrols_are_not_reported(page):
    html = ("<canvas id=chart width=400 height=200 aria-label='Revenue by quarter'></canvas>"
            "<canvas id=px width=2 height=2 aria-label='Sign tracker'></canvas>"
            "<canvas id=sig2 width=400 height=200></canvas>"
            "<div contenteditable=false aria-label='Static'></div><div role=img aria-label='Logo'></div>")
    assert find_unsupported(page_with(page, html)) == []


def test_popup_of_an_aria_combobox_is_not_reported(page):
    html = ("<div role=combobox aria-controls=pop aria-expanded=true aria-label='Country' tabindex=0></div>"
            "<div id=pop role=listbox><div role=option>India</div></div>")
    assert [u for u in find_unsupported(page_with(page, html)) if u["kind"] == "aria_listbox"] == []


def test_a_widget_is_reported_once_even_when_it_has_nested_parts(page):
    html = ("<div role=radiogroup aria-label='Plan'><div role=radio aria-checked=false tabindex=0>Free</div>"
            "<div role=radio aria-checked=false tabindex=0>Paid</div></div>"
            "<div id=ed contenteditable=true aria-label='Rich'><div contenteditable=true>inner</div></div>")
    assert kinds(page_with(page, html) and run_form(page, SRC, confirm_ms=0)) == [("aria_radiogroup", False), ("contenteditable", False)]


def test_a_form_with_only_supported_controls_is_still_filled(page):
    res = run_form(page_with(page, ""), SRC, confirm_ms=0)
    assert res.unsupported == [] and res.status == "FILLED" and not res.warnings


# ---- a wizard step that is left behind ------------------------------------------------------------------------------

_WIZARD = """<!doctype html><html><body><div id="app"></div><script>
  const step1 = '<label for="co">Legal name</label><input id="co" name="co" type="text">' +
                '<label for="up">Upload the certificate (required)</label><input id="up" type="file" required>' +
                '<button type="button" id="nx">Next</button>';
  const step2 = '<label for="site">Company website</label><input id="site" name="site" type="text">';
  const app = document.getElementById('app'); app.innerHTML = step1;
  document.getElementById('nx').addEventListener('click', () => { app.innerHTML = step2; });
</script></body></html>"""


def test_unsupported_control_on_an_earlier_wizard_step_is_still_reported(page):
    page.route("http://wiz.test/w.html", lambda r: r.fulfill(status=200, content_type="text/html", body=_WIZARD))
    page.goto("http://wiz.test/w.html")
    res = run_form(page, {"company": {"legal_name": "Northwind Ltd", "website": "https://n.example"}}, policy=DiscoveryPolicy(), confirm_ms=0)
    assert [(u["kind"], u["required"]) for u in res.unsupported] == [("file_upload", True)]
    assert res.status in ("NEEDS_REVIEW", "FAILED") and res.status != "FILLED"
    assert page.query_selector("#site") is not None  # the walk did move on to step 2


_WIZ_LATE = """<!doctype html><html><body><div id="app"></div><script>
  const s1 = '<label for="co">Legal name</label><input id="co" name="co" type="text"><button type="button" id="nx">Next</button>';
  const s2 = '<label for="site">Company website</label><input id="site" name="site" type="text">' +
             '<label for="up">Upload the certificate (required)</label><input id="up" type="file" required>';
  const app = document.getElementById('app'); app.innerHTML = s1;
  document.getElementById('nx').addEventListener('click', () => { app.innerHTML = s2; });
</script></body></html>"""


def test_unsupported_control_on_a_later_wizard_step_is_reported_and_submission_refused(page):
    page.route("http://wiz.test/l.html", lambda r: r.fulfill(status=200, content_type="text/html", body=_WIZ_LATE))
    page.goto("http://wiz.test/l.html")
    res = run_form(page, {"company": {"legal_name": "Northwind Ltd", "website": "https://n.example"}}, policy=DiscoveryPolicy(),
                   confirm_ms=0, submit=True)
    assert [(u["kind"], u["required"]) for u in res.unsupported] == [("file_upload", True)]
    assert res.status != "FILLED" and res.submission["attempted"] is False


_WIZ_SUBMIT = """<!doctype html><html><body><form id="f"><label for="co">Legal name</label><input id="co" name="co">
  <input type="file" id="up" aria-label="Optional attachment"><button type="submit" id="nx">Next</button></form>
  <script>window.__sent=0; f.addEventListener('submit', e => { e.preventDefault(); window.__sent++; });</script></body></html>"""


@pytest.mark.parametrize("opt_in", [False, True])
def test_submit_type_next_is_refused_even_with_the_deprecated_opt_in(page, opt_in):
    page.route("http://wiz.test/s.html", lambda r: r.fulfill(status=200, content_type="text/html", body=_WIZ_SUBMIT))
    page.goto("http://wiz.test/s.html")
    res = run_form(page, SRC, policy=DiscoveryPolicy(allow_submit_type_navigation=opt_in), confirm_ms=0, submit=True)
    assert res.navigation["stop_reason"] == "submit_type_next_refused"
    assert page.evaluate("window.__sent") == 0 and res.submission["attempted"] is False


# ---- acknowledgement identity ---------------------------------------------------------------------------------------------

def _ack_ids(res):
    return [u["ack_id"] for u in res.unsupported]


def test_duplicate_ids_cannot_be_acknowledged(page):
    html = ("<input type=file id=dup aria-label='A'><input type=file id=dup aria-label='B'>"
            "<button id=go type=submit>Send</button>")
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["dup"])
    assert _ack_ids(res) == [None, None] and res.submission["outcome"] == "SKIPPED"


def test_empty_identifier_cannot_be_acknowledged(page):
    html = "<input type=file><button id=go type=submit>Send</button>"
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["", None])
    assert _ack_ids(res) == [None] and res.submission["outcome"] == "SKIPPED"


def test_name_shared_with_another_controls_id_is_ambiguous(page):
    html = ("<input type=file id=x aria-label='A'><input type=file name=x aria-label='B'>"
            "<button id=go type=submit>Send</button>")
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["x"])
    assert _ack_ids(res) == [None, None] and res.submission["outcome"] == "SKIPPED"


def test_unique_ids_each_acknowledge_only_their_own_control(page):
    html = ("<input type=file id=one aria-label='A'><input type=file id=two aria-label='B'>"
            "<button id=go type=submit>Send</button>")
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["one"])
    assert sorted(_ack_ids(res)) == ["one", "two"] and res.submission["outcome"] == "SKIPPED"
    page_with(page, html)
    res = run_form(page, SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported=["one", "two"])
    assert res.submission["attempted"] is True


def test_a_bare_string_acknowledgement_is_one_id_not_its_characters(page):
    html = "<input type=file id=c aria-label='A'><button id=go type=submit>Send</button>"
    res = run_form(page_with(page, html), SRC, confirm_ms=0, submit=True, submit_selector="#go", acknowledge_unsupported="cc")
    assert res.submission["outcome"] == "SKIPPED"  # 'cc' is not 'c'; iterating its characters would have matched
