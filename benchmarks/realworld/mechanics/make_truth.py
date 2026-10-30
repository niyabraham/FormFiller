"""Ground truth for the mechanics-only evaluation: every fact in source_mechanics.json is keyed to a question on these four demo
forms, so the expected outcome is "answer with that value"; every other question is expected to stay in review. Written from the
question lists of the earlier runs (labels only) before the first mechanics run."""
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
ANY_TRUE = ["true", "yes", "on", "checked"]

def a(m, accept, why="mechanics fact"):
    return {"match": m, "expect": "answer", "accept": accept, "why": why}


def r(m, why):
    return {"match": m, "expect": "review", "accept": [], "why": why}

SPEC = {
 "mech_surveyjs_dropdown": [a("Which is the brand of your car?", ["Toyota"])],
 "mech_surveyjs_conditional": [a("On a scale from 0 to 10, how likely are you to recommend us to a friend or colleague?", ["9"])],
 "mech_demoqa_practice": [
   a("First Name", ["Test"]), a("Last Name", ["User"]), a("name@example.com", ["test.user@example.test"]), a("gender", ["Other"]),
   a("Mobile Number", ["5551234567"]), a("dateOfBirthInput", ["15 Mar 1990"]), a("subjectsInput", ["Maths"]),
   a("Sports", ANY_TRUE + ["sports"]), a("Reading", ANY_TRUE + ["reading"]), r("Music", "no fact for it"),
   a("Current Address", ["1 Example Street, Testville"]), a("react-select-3-input", ["NCR"]), a("react-select-4-input", ["Delhi"])],
 "mech_selenium_webform": [
   a("Text input", ["Mechanics text"]), a("Textarea", ["Mechanics notes"]), r("Readonly input", "read-only, no fact"),
   a("Dropdown (select)", ["Two", "2"]), a("Dropdown (datalist)", ["Seattle"]), r("my-check", "no fact"), r("my-radio", "no fact"),
   a("Color picker", ["#336699"]), a("Date picker", ["03/14/2026"]), a("Example range", ["7"])],
}
for form, rows in SPEC.items():
    (out / f"{form}.mechanics.json").write_text(json.dumps({"form": form, "source": "mechanics", "questions": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(len(SPEC), "mechanics truth files;", sum(1 for rows in SPEC.values() for x in rows if x["expect"] == "answer"), "expected-answerable questions")
