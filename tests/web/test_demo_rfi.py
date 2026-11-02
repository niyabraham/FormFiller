"""The portfolio demo (docs/demo/DEMO_GUIDE.md): a fictional eight-section vendor security questionnaire filled from a fictional source.

The guide states what happens at each stage. These tests pin those statements against the real pipeline, so the documentation cannot
drift from the behaviour: which questions are answered and verified, which go to review and why, what is left untouched, that nothing
is ever submitted, and what a person's decisions in the review step change. The questionnaire and the source are demo data written
for this project; they are an illustration, not an accuracy measurement (the benchmarks are).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from formfill.web.pipeline import run_form
from formfill.web.result import FieldState, field_state
from formfill.web.review import ReviewError, build_review, decide, decisions_planner, save_review

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "docs" / "demo"
FORM = DEMO / "security_questionnaire.html"
SOURCE_PATH = DEMO / "company_source.json"
SOURCE = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))

# question -> what the page holds after the run (read back), for the 22 answers the pipeline enters and verifies
VERIFIED = {
    "Legal company name": "Brightwave Systems Ltd",
    "Date founded": "2014-06-02",
    "Number of employees": "180",
    "Number of full-time employees": "156",
    "Headquarters country": "GB",
    "Company website": "https://brightwave.example",
    "Security contact email": "security@brightwave.example",
    "Does GDPR apply to your organization?": "yes",
    "Data Protection Officer name": "R. Okafor",  # revealed by the GDPR answer: found in the next discovery round
    "Customer data retention after contract termination (days)": "90",
    "Is customer data encrypted at rest?": "yes",
    "Is customer data encrypted in transit?": "yes",
    "Minimum TLS version supported": "tls12",
    "Is multi-factor authentication enforced for all staff?": "yes",
    "Do you have a documented incident response plan?": "yes",
    "Do you maintain a business continuity plan?": "yes",
    "Recovery time objective (RTO) in hours": "8",
    "Recovery point objective (RPO) in hours": "1",
    "How often do you rehearse your disaster recovery procedures?": "annually",
    "Are you ISO 27001 certified?": "yes",
    "Do you perform security assessments of your suppliers?": "yes",
    "Link to your list of subprocessors": "https://brightwave.example/subprocessors",
}

# question -> (why it is not answered, proposal that is shown to a person but never entered)
IN_REVIEW = {
    "Number of employees working remotely": ("too weak", 180),  # the scope guard: a headcount of "remote" staff is not the total
    "Primary data hosting region": ("too weak", "eu"),
    "Who manages your encryption keys?": ("not of a kind", "AES-256"),  # a similarity hint that does not answer the question
    "Minimum password length (characters)": ("contradicts itself", None),  # two facts disagree: 12 and 8
    "How often are user access rights reviewed?": ("too weak", "quarterly"),
    "Customer notification time after a security breach (hours)": ("too weak", 72),
    "Describe your incident response process": ("no matching value", "72"),  # another hint that does not answer the question
    "Date of your last incident response exercise": ("no matching value", None),  # the source has no such fact
    "Are you SOC 2 Type II certified?": ("in progress", None),  # a certification claim needs a stated status; "in progress" is not "yes"
    "Are you PCI DSS compliant?": ("no evidence", None),
    "I confirm that the information provided is accurate and complete": ("attestation/consent", None),
}

COUNTERS = """
() => { window.__submits = 0; document.addEventListener('submit', () => { window.__submits++; }, true); }
"""

PAGE_STATE_JS = """
() => ({
  ids: Object.fromEntries(['remote', 'hosting', 'keys', 'pw_len', 'access_review', 'notify', 'ir_process', 'ir_exercise']
                          .map(i => [i, document.getElementById(i).value])),
  files: document.getElementById('audit_report').files.length,
  soc2: !!document.querySelector('input[name=soc2]:checked'), pci: !!document.querySelector('input[name=pci]:checked'),
  accurate: document.querySelector('input[name=accurate]').checked,
  submits: window.__submits, done_visible: !document.getElementById('done').hidden,
})
"""


def open_form(page):
    page.goto(FORM.as_uri())
    page.evaluate(COUNTERS)


def by_question(result):
    return {i.plan.question: i for i in result.items}


class FirstRun:
    """One run of the demo (what `python demo_web.py --form ...` does), kept with what the page looked like before and after."""

    def __init__(self, browser):
        context = browser.new_context()
        try:
            page = context.new_page()
            page.set_default_timeout(4000)
            open_form(page)
            self.dpo_hidden_before = page.evaluate("document.getElementById('dpo-wrap').hidden")
            self.result = run_form(page, SOURCE, confirm_ms=0)
            self.items = by_question(self.result)
            self.state = page.evaluate(PAGE_STATE_JS)
            self.dpo_hidden_after = page.evaluate("document.getElementById('dpo-wrap').hidden")
            self.upload_files = page.evaluate("document.getElementById('audit_report').files.length")
        finally:
            context.close()


@pytest.fixture(scope="module")
def first(browser):
    return FirstRun(browser)


# ---- stage by stage: what the guide says ------------------------------------------------------------------------------------------------


def test_the_questionnaire_has_exactly_the_questions_the_guide_describes(first):
    assert set(first.items) == set(VERIFIED) | set(IN_REVIEW)
    assert len(VERIFIED) == 22 and len(IN_REVIEW) == 11


def test_confident_matches_are_entered_and_confirmed_by_reading_the_page_back(first):
    for question, held in VERIFIED.items():
        item = first.items[question]
        assert item.plan.status == "ANSWER" and item.filled and item.verified is True, question
        assert field_state(item)[0] is FieldState.VERIFIED, question
        assert item.observed == held, f"{question}: the page holds {item.observed!r}"
        assert item.plan.source and item.plan.confidence_category in ("high", "medium"), question  # provenance on every answer


def test_sibling_concepts_use_their_own_facts(first):
    """RTO and RPO differ by one word. Each has its own fact in the demo source, so each is answered from its own."""
    items = first.items
    assert items["Recovery time objective (RTO) in hours"].plan.source == "business_continuity.rto_hours"
    assert items["Recovery point objective (RPO) in hours"].plan.source == "business_continuity.rpo_hours"
    assert items["Number of employees"].plan.source == "company.employees"
    assert items["Number of full-time employees"].plan.source == "company.full_time_employees"


def test_removing_the_rpo_fact_sends_the_rpo_question_to_review_instead_of_answering_it_with_the_rto_value(page):
    """DEMO_GUIDE section 7: before PR #27 the RPO question was answered with the RTO value (8) once `rpo_hours` was deleted from the
    source, because the two questions share most of their words. The two differ by one word, which is now a reason to abstain."""
    source = json.loads(json.dumps(SOURCE))
    del source["business_continuity"]["rpo_hours"]
    open_form(page)
    result = run_form(page, source, confirm_ms=0)
    items = by_question(result)
    rpo = items["Recovery point objective (RPO) in hours"]
    assert rpo.plan.status == "REVIEW" and not rpo.filled and rpo.plan.answer is None
    assert rpo.plan.proposed_answer is None  # the RTO value is not even offered as a proposal
    assert "different concept" in (rpo.plan.reason or "")
    assert items["Recovery time objective (RTO) in hours"].plan.source == "business_continuity.rto_hours"
    assert sum(1 for i in result.items if field_state(i)[0] is FieldState.VERIFIED) == 21  # 22 minus the RPO question


def test_the_conditional_field_is_found_and_filled_after_its_trigger_is_answered(first):
    assert first.dpo_hidden_before  # hidden until the GDPR question is answered
    assert first.items["Data Protection Officer name"].verified is True
    assert not first.dpo_hidden_after


@pytest.mark.parametrize("question", sorted(IN_REVIEW))
def test_every_uncertain_question_goes_to_review_with_a_reason_and_is_not_entered(first, question):
    item = first.items[question]
    reason, proposal = IN_REVIEW[question]
    assert item.plan.status == "REVIEW" and not item.filled and item.plan.answer is None, question
    assert reason in (item.plan.reason or ""), f"{question}: {item.plan.reason!r}"
    assert item.plan.proposed_answer == proposal  # a proposal is shown to a person, never entered
    assert field_state(item)[0] is FieldState.NEEDS_REVIEW


def test_a_source_that_contradicts_itself_shows_both_facts(first):
    item = first.items["Minimum password length (characters)"]
    assert item.plan.conflicts and "password_policy.min_length" in json.dumps(item.plan.conflicts)
    assert "password_min_length" in item.plan.reason


def test_nothing_uncertain_is_on_the_page_and_nothing_is_submitted(first):
    result, state = first.result, first.state
    assert all(v == "" for v in state["ids"].values()), state["ids"]  # no proposal was typed into a field
    assert state["files"] == 0 and not state["soc2"] and not state["pci"] and not state["accurate"]
    assert state["submits"] == 0 and not state["done_visible"]
    assert result.status == "NEEDS_REVIEW" and result.submission == {}


def test_the_file_upload_is_reported_and_never_touched(first):
    assert [(u["kind"], u["required"]) for u in first.result.unsupported] == [("file_upload", False)]
    assert first.upload_files == 0


def test_asking_to_submit_is_refused_while_an_attestation_and_an_unacknowledged_upload_are_open(page):
    """The guard behind "a person submits": with submit=True, nothing is pressed while an attestation is open (software never answers
    one) and an unsupported control has no explicit human decision. Optional questions left in review do not block it by themselves;
    required ones, failed answers and unsupported required controls do."""
    open_form(page)
    result = run_form(page, SOURCE, submit=True, confirm_ms=0)
    assert result.submission["outcome"] == "SKIPPED" and result.submission["attempted"] is False
    assert "1 item(s) require human review" in result.submission["detail"]  # the attestation
    assert "1 optional unsupported control(s) lack an explicit human decision" in result.submission["detail"]  # the upload
    assert result.status == "NEEDS_REVIEW"
    state = page.evaluate(PAGE_STATE_JS)
    assert state["submits"] == 0 and not state["done_visible"]


# ---- the review step ---------------------------------------------------------------------------------------------------------------------

DECISIONS = [  # (question, action, value typed by the reviewer for "edit")
    ("Primary data hosting region", "approve", None),
    ("How often are user access rights reviewed?", "approve", None),
    ("Customer notification time after a security breach (hours)", "approve", None),
    ("Who manages your encryption keys?", "reject", None),
    ("Number of employees working remotely", "edit", "62"),
    ("Minimum password length (characters)", "edit", "12"),
    ("Describe your incident response process", "edit", "Documented plan with 24x7 on-call triage; customers are told within 72 hours."),
    ("Date of your last incident response exercise", "edit", "2026-03-10"),
    ("Are you SOC 2 Type II certified?", "reject", None),
    ("Are you PCI DSS compliant?", "reject", None),
    ("I confirm that the information provided is accurate and complete", "acknowledge", None),
]


def decided_review(result):
    doc = build_review(result)
    ids = {it["question"]: it["question_id"] for it in doc["items"]}
    for question, action, value in DECISIONS:
        decide(doc, ids[question], action, value)
    return doc


def test_a_persons_decisions_are_entered_and_read_back_and_the_rest_stays_with_the_person(page, first):
    doc = decided_review(first.result)

    open_form(page)  # a fresh page, as the second run in the guide opens
    second = run_form(page, SOURCE, planner=decisions_planner(doc), confirm_ms=0)
    items = by_question(second)

    typed = {"Number of employees working remotely": "62", "Minimum password length (characters)": "12",
             "Describe your incident response process": "Documented plan with 24x7 on-call triage; customers are told within 72 hours.",
             "Date of your last incident response exercise": "2026-03-10"}
    approved = {"Primary data hosting region": "eu", "How often are user access rights reviewed?": "quarterly",
                "Customer notification time after a security breach (hours)": "72"}
    for question, held in {**typed, **approved}.items():
        assert items[question].verified is True and str(items[question].observed) == held, question
    assert all(items[q].plan.method == "human_edited" for q in typed)
    assert all(items[q].plan.method == "human_approved" for q in approved)

    still_open = {"Who manages your encryption keys?", "Are you SOC 2 Type II certified?", "Are you PCI DSS compliant?",
                  "I confirm that the information provided is accurate and complete"}
    for question in still_open:
        assert items[question].plan.status == "REVIEW" and not items[question].filled, question
    assert sum(1 for i in second.items if field_state(i)[0] is FieldState.VERIFIED) == 29
    assert {q for q, i in items.items() if i.plan.status == "REVIEW"} == still_open

    state = page.evaluate(PAGE_STATE_JS)
    assert state["ids"]["keys"] == "" and state["files"] == 0 and not state["soc2"] and not state["pci"] and not state["accurate"]
    assert state["submits"] == 0 and not state["done_visible"]
    assert second.status == "NEEDS_REVIEW" and second.submission == {}  # a person still completes and submits it in the portal


def test_an_attestation_can_only_be_acknowledged_never_approved_or_edited(first):
    doc = build_review(first.result)
    qid = next(it["question_id"] for it in doc["items"] if it["question"].startswith("I confirm that the information"))
    for action, value in (("approve", None), ("edit", "yes")):
        with pytest.raises(ReviewError, match="never answered by FormFiller"):
            decide(doc, qid, action, value)
    assert decide(doc, qid, "acknowledge")["decision"]["action"] == "acknowledge"


def test_a_value_that_does_not_fit_the_field_is_refused_in_review(first):
    doc = build_review(first.result)
    qid = next(it["question_id"] for it in doc["items"] if it["question"] == "Date of your last incident response exercise")
    with pytest.raises(ReviewError, match="not a valid answer"):
        decide(doc, qid, "edit", "next Tuesday")


# ---- the command-line script the guide uses ----------------------------------------------------------------------------------------------


def run_demo_script(*args):
    """Run `python demo_web.py ...` the way a person does (its own process and Chromium; the test session already owns a Playwright)."""
    done = subprocess.run([sys.executable, str(ROOT / "demo_web.py"), *map(str, args)], capture_output=True, text=True, timeout=180,
                          cwd=ROOT, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.isascii()  # ASCII only: the report must not crash a redirected Windows console
    return done.stdout


def test_the_demo_script_prints_the_counts_the_guide_quotes_and_writes_its_artifacts(browser, tmp_path):
    out = run_demo_script("--form", FORM, "--source", SOURCE_PATH, "--out", tmp_path / "run1")
    assert "22 verified | 11 needs review | 1 unsupported control(s)" in out
    assert "Run status: NEEDS_REVIEW" in out and "Submission: not attempted" in out
    assert "[Company profile]" in out and "[Business continuity]" in out and "UNSUPPORTED" in out
    for name in ("result.json", "audit_report.md", "filled.png"):
        assert (tmp_path / "run1" / name).is_file(), name
    assert not (tmp_path / "run1" / "trace.zip").exists()  # a trace holds page content and answers: only with --trace
    saved = json.loads((tmp_path / "run1" / "result.json").read_text(encoding="utf-8"))
    assert saved["submission"] == {} and saved["status"] == "NEEDS_REVIEW"


def test_the_demo_script_applies_a_review_file(first, tmp_path):
    review_path = tmp_path / "review.json"
    save_review(decided_review(first.result), review_path)
    out = run_demo_script("--form", FORM, "--source", SOURCE_PATH, "--out", tmp_path / "run2", "--review", review_path)
    assert "29 verified | 4 needs review | 1 unsupported control(s)" in out
    assert "approved by the reviewer" in out and "typed by the reviewer" in out and "rejected by the reviewer" in out
    assert "Submission: not attempted" in out


def test_the_default_example_is_unchanged_by_the_new_options(browser, tmp_path):
    """`python demo_web.py` with no options still runs the small example page and reaches the outcome the README describes."""
    out = run_demo_script("--out", tmp_path / "web")
    assert "9 verified | 2 needs review" in out and "Run status: NEEDS_REVIEW" in out
