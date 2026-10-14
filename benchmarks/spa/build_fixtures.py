"""Generate the Phase 3C SPA fixtures and their ground truth from one declaration, so the two cannot drift.

    python benchmarks/spa/build_fixtures.py

Writes benchmarks/spa/fixtures/<id>.html and benchmarks/spa/ground_truth.json.

Ground truth per fixture:
  stages      list of {step, discoverable: [field keys that exist in the DOM and are usable at that stage]}
              Order matters: a control listed at stage N must NOT be discoverable before stage N is reached.
  expected    field key -> value the pipeline should enter (None = no JSON support, must end as REVIEW)
  unsupported field key -> reason it cannot be discovered/filled (recorded, not a failure)
  stop        expected safe-stop reason, or null when the whole form should be traversed
  resets      field keys the app clears on navigation (planted); a run must detect them
Labels are chosen so existing retrieval returns ANSWER for the keys in `expected`; retrieval is not tuned.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

# value the source JSON supports, by field key
ANS = {
    "name": "Acme Robotics Ltd", "website": "https://acme-robotics.example", "email": "info@acme-robotics.example",
    "phone": "+44 20 7946 0000", "city": "Leeds", "country": "United Kingdom", "year": "2011", "industry": "Manufacturing",
}


def F(key, label, type="text", **kw):
    return {"key": key, "label": label, "type": type, **kw}


LABEL = {
    "name": "Legal company name", "website": "Company website", "email": "Contact email", "phone": "Contact phone number",
    "city": "Headquarters city", "country": "Headquarters country", "year": "Year founded", "industry": "Industry sector",
}
EMAIL = {"email": "email"}


def f(key, **kw):
    return F(key, LABEL[key], EMAIL.get(key, "text"), **kw)


WIZ3 = [
    {"title": "Company", "fields": [f("name"), f("website")]},
    {"title": "Contact", "fields": [f("email"), f("phone")]},
    {"title": "Location", "fields": [f("city"), f("country")]},
]

FIXTURES: dict[str, dict] = {}


def add(fid, desc, config, *, expected=None, stop=None, resets=(), unsupported=None, stages=None, extra_html="", policy=None):
    steps = config["steps"]
    if stages is None:
        stages = [{"step": i + 1, "discoverable": [x["key"] for x in s["fields"] if "showIf" not in x]} for i, s in enumerate(steps)]
    if expected is None:
        expected = {x["key"]: ANS.get(x["key"]) for s in steps for x in s["fields"] if x["key"] in ANS}
    FIXTURES[fid] = {"desc": desc, "config": config, "stages": stages, "expected": expected,
                     "unsupported": unsupported or {}, "stop": stop, "resets": list(resets), "extra_html": extra_html,
                     "policy": policy or {}}


add("wiz_hidden", "3-step wizard, later steps present but hidden in the DOM (control: the easy case)", {"mount": "hidden", "steps": WIZ3})
add("wiz_unmount", "3-step wizard; each step is mounted on demand and the previous one removed, answers kept in app state",
    {"mount": "unmount", "steps": WIZ3})
add("wiz_async", "3-step wizard; each step renders after an async fetch (400 ms) behind a loading placeholder",
    {"mount": "unmount", "loadMs": 400, "steps": WIZ3})
add("wiz_route", "3-step wizard with URL routing (?step=N) and a Back button; same document, history API",
    {"mount": "unmount", "route": True, "back": True, "steps": WIZ3})
add("wiz_guard", "Next stays disabled until the step's required fields are valid (guard); validation fires on input",
    {"mount": "unmount", "guard": True, "steps": [
        {"title": "Company", "fields": [f("name", required=True), f("website", required=True)]},
        {"title": "Contact", "fields": [f("email", required=True), f("phone")]},
        {"title": "Location", "fields": [f("city"), f("country")]}]})
add("wiz_labels", "Step button is labelled 'Continue' in a nav, not 'Next' (safe-label allow list must cover it)",
    {"mount": "unmount", "nextLabel": "Continue", "steps": WIZ3})

add("cond_sync", "Follow-up question appears immediately after an earlier answer (hidden attr toggled)",
    {"mount": "hidden", "steps": [{"title": "Company", "fields": [
        f("name"),
        F("sub", "Is the company a subsidiary of another company?", "radio", options=[{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]),
        F("parent", "Parent company name", showIf={"key": "sub", "eq": "yes"})]}]},
    expected={"name": ANS["name"], "sub": None, "parent": None},
    stages=[{"step": 1, "discoverable": ["name", "sub"]}], extra_html="")
add("cond_async", "Industry follow-up is rendered 350 ms after the trigger answer (async-created control)",
    {"mount": "hidden", "steps": [{"title": "Company", "fields": [
        f("name"),
        F("sector", "Industry sector", "select", options=[{"value": "Manufacturing", "label": "Manufacturing"}, {"value": "Retail", "label": "Retail"}]),
        F("detail", "Headquarters city", showIf={"key": "sector", "eq": "Manufacturing"}, revealMs=350)]}]},
    expected={"name": ANS["name"], "sector": ANS["industry"], "detail": ANS["city"]},
    stages=[{"step": 1, "discoverable": ["name", "sector"]}, {"step": 1, "after": "sector", "discoverable": ["detail"]}])
add("controlled", "React-style controlled inputs: the DOM value is overwritten from app state unless a real input event fires",
    {"mount": "hidden", "controlled": True, "steps": [{"title": "Company", "fields": [f("name"), f("email"), f("city")]}]})
add("enable_after", "Phone field is disabled until a contact email has been entered",
    {"mount": "hidden", "steps": [{"title": "Contact", "fields": [
        f("email"), f("phone", enabledIf={"key": "email", "truthy": True})]}]},
    stages=[{"step": 1, "discoverable": ["email", "phone"]}])
add("combobox", "ARIA comboboxes: a button-style listbox and a typeahead input whose options live in a body-level popup",
    {"mount": "hidden", "steps": [{"title": "Company", "fields": [
        f("name"),
        F("country", LABEL["country"], "text", widget="combobox_button",
          options=["France", "Germany", "United Kingdom", "United States"]),
        F("industry", LABEL["industry"], "text", widget="combobox_input",
          options=["Manufacturing", "Retail", "Software"])]}]})
add("shadow_iframe", "Open shadow DOM, same-origin iframe and a closed shadow root (the closed one cannot be seen)",
    {"mount": "hidden", "steps": [{"title": "Company", "fields": [
        f("name"),
        f("website", widget="shadow"),
        f("email", widget="iframe"),
        f("phone", widget="closed_shadow")]}]},
    expected={"name": ANS["name"], "website": ANS["website"], "email": ANS["email"], "phone": ANS["phone"]},
    unsupported={"phone": "closed shadow root: the DOM is not reachable by any script outside the component"})

add("trap_submit", "A non-final step's only button is 'Submit application' (type=submit) - discovery must not press it",
    {"mount": "unmount", "nextLabel": "Submit application", "nextType": "submit", "trap": True, "steps": WIZ3},
    stages=[{"step": 1, "discoverable": ["name", "website"]}], stop="no_safe_next_control")  # indistinguishable from a real last step: the check is that nothing is pressed
add("nav_dialog", "Next opens a confirm() dialog ('Discard draft?'); the run must stop, not accept it",
    {"mount": "unmount", "onNext": "confirm", "steps": WIZ3},
    stages=[{"step": 1, "discoverable": ["name", "website"]}], stop="dialog_on_navigation")
add("nav_reload", "Next triggers a full document reload that discards the page (answers are not persisted)",
    {"mount": "unmount", "onNext": "reload", "steps": WIZ3},
    stages=[{"step": 1, "discoverable": ["name", "website"]}], stop="document_navigation", resets=["name", "website"])
add("nav_reset", "Moving to step 2 silently clears step 1's website answer (planted reset); must be detected",
    {"mount": "hidden", "onNext": "resetPrev", "resetKeys": ["website"], "steps": WIZ3},
    resets=["website"])
add("attest", "Last step carries a certification checkbox and a signature name; both must stay REVIEW",
    {"mount": "unmount", "steps": [
        {"title": "Company", "fields": [f("name"), f("city")]},
        {"title": "Declaration", "fields": [
            F("certify", "I certify that the information provided is true and accurate", "checkbox"),
            F("signer", "Authorised signatory full name")]}]},
    expected={"name": ANS["name"], "city": ANS["city"], "certify": None, "signer": None})


# --- Phase 3C review round 2: submit-type controls and unstable pages ---------------------------------------------------
STEP1_ONLY = [{"step": 1, "discoverable": ["name", "website"]}]
add("trap_submit_button", "Non-final step's Next is <button type=submit>Next</button> in a form; clicking it really submits (side effect counted)",
    {"mount": "unmount", "nextType": "submit", "nextLabel": "Next", "trap": True, "steps": WIZ3}, stages=STEP1_ONLY, stop="submit_type_next_refused")
add("trap_submit_input", "Non-final step's Next is <input type=submit value=Continue> in a form; clicking it really submits",
    {"mount": "unmount", "nextType": "input", "nextLabel": "Continue", "trap": True, "steps": WIZ3}, stages=STEP1_ONLY, stop="submit_type_next_refused")
add("trap_submit_default", "Next is a <button> with no type attribute inside a form (a submit button by HTML rules); clicking it really submits",
    {"mount": "unmount", "nextType": "default", "nextLabel": "Next", "trap": True, "steps": WIZ3}, stages=STEP1_ONLY, stop="submit_type_next_refused")
add("spa_submit_type_intercepted", "Next is <button type=submit> but the app intercepts it (preventDefault) and navigates: default policy still refuses; opt-in policy may navigate",
    {"mount": "unmount", "nextType": "submit", "nextLabel": "Next", "steps": WIZ3}, stages=STEP1_ONLY, stop="submit_type_next_refused")
add("wiz_loading_forever", "First paint is a 'Loading...' placeholder (aria-busy, 3 s fetch); with a 600 ms settle timeout the page never settles",
    {"mount": "unmount", "loadMs": 3000, "steps": WIZ3}, expected={}, stages=[], stop="page_not_settled", policy={"settle_timeout_ms": 600})
add("wiz_churn", "A live ticker re-renders every 40 ms, so the DOM is never quiet; with a 600 ms settle timeout the page never settles",
    {"mount": "unmount", "churn": True, "steps": WIZ3}, expected={}, stages=[], stop="page_not_settled", policy={"settle_timeout_ms": 600})
add("wiz_churn_step2", "Step 1 is calm; after Next, step 2 starts a 40 ms ticker so the page never settles again: stop after Next, step 2 untouched",
    {"mount": "unmount", "churnFrom": 2, "steps": WIZ3}, expected={"name": ANS["name"], "website": ANS["website"]}, stages=STEP1_ONLY,
    stop="page_not_settled", policy={"settle_timeout_ms": 600})
add("trap_submit_image", "Next is <input type=image alt=Next> in a form (an image submit button); clicking it really submits",
    {"mount": "unmount", "nextType": "image", "nextLabel": "Next", "trap": True, "steps": WIZ3}, stages=STEP1_ONLY, stop="submit_type_next_refused")
add("wiz_unfamiliar_next", "Non-final step's Next is labelled 'Onward' (not on the allow list) and a real 'Submit application' button is visible on the same page",
    {"mount": "unmount", "nextLabel": "Onward", "earlySubmit": True, "steps": WIZ3}, stages=STEP1_ONLY, stop="no_safe_next_control")


def html(fid, fx):
    cfg = json.dumps(fx["config"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{fid}</title>
<style>body{{font:15px sans-serif;margin:2rem}} .field{{margin:.6rem 0}} label{{display:block}} ul[data-popup]{{border:1px solid #888;list-style:none;padding:0;width:14rem}} li{{padding:.3rem;cursor:pointer}}</style></head>
<body><h1>RFI supplier questionnaire</h1><div id="app"></div>
<script>window.FORM_CONFIG = {cfg};</script>
<script src="spa_lib.js"></script></body></html>
"""


def main() -> None:
    gt = {}
    for fid, fx in FIXTURES.items():
        (HERE / "fixtures" / f"{fid}.html").write_text(html(fid, fx))
        labels = {x["key"]: x["label"] for s in fx["config"]["steps"] for x in s["fields"]}
        gt[fid] = {k: fx[k] for k in ("desc", "stages", "expected", "unsupported", "stop", "resets", "policy")} | {"labels": labels}
    (HERE / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")
    (HERE / "source.json").write_text(json.dumps({
        "company": {"legal_name": ANS["name"], "website": ANS["website"], "industry_sector": ANS["industry"], "year_founded": int(ANS["year"])},
        "contact": {"email": ANS["email"], "phone": ANS["phone"]},
        "headquarters": {"city": ANS["city"], "country": ANS["country"]},
    }, indent=2) + "\n")
    print(f"{len(FIXTURES)} fixtures")


if __name__ == "__main__":
    main()
