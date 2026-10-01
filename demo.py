"""Run with:

    python demo.py

Demonstrates the core idea: source data and a form template are matched,
validated, filled, and verified -- and whatever can't be confidently
resolved is marked for human review instead of guessed. Simulates a human
resolving the one unresolved field, then re-fills and re-verifies.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from formfill.filler import fill_form
from formfill.form import read_form_fields
from formfill.matcher import Mapping, match_fields
from formfill.source import load_source
from formfill.validator import validate_and_transform
from formfill.verifier import verify

ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "examples" / "source.json"
FORM_PATH = ROOT / "examples" / "form.pdf"
OUTPUT_DIR = ROOT / "output"

# What a human reviewer would type in for the one field the source data
# doesn't have. Hardcoded here because this is a demo, not a review UI --
# see README for what a real review step would look like.
HUMAN_REVIEW_ANSWERS = {"gender": "Female"}


def map_and_validate(fields, source):
    mappings = match_fields(fields, source)
    return [validate_and_transform(m, f) for m, f in zip(mappings, fields)]


def print_mapping_table(mappings: list[Mapping]) -> None:
    print("FIELD MAPPING")
    print("-" * 50)
    for m in mappings:
        value = "" if m.value is None else str(m.value)
        mark = "REVIEW" if m.status == "REVIEW" else "\u2713"
        print(f"{m.field_name:<16}\u2192 {value:<20}{mark}")


def print_verification(results) -> None:
    print("\nVERIFICATION")
    print("-" * 50)
    for r in results:
        mark = "\u2713 PASS" if r.passed else "! REVIEW REQUIRED" if "review" in r.detail.lower() else f"\u2717 FAIL ({r.detail})"
        print(f"{r.field_name:<16}{mark}")


def write_report(path: Path, mappings: list[Mapping], results, overall: str) -> None:
    report = {
        "overall_status": overall,
        "fields": [
            {**asdict(m), "verification": next((asdict(r) for r in results if r.field_name == m.field_name), None)}
            for m in mappings
        ],
    }
    path.write_text(json.dumps(report, indent=2))


def main() -> None:
    print("FORM FILL PoC")
    print("=============\n")
    print(f"Source: examples/{SOURCE_PATH.name}")
    print(f"Form:   examples/{FORM_PATH.name}\n")

    OUTPUT_DIR.mkdir(exist_ok=True)

    source = load_source(SOURCE_PATH)
    fields = read_form_fields(FORM_PATH)
    mappings = map_and_validate(fields, source)

    print_mapping_table(mappings)

    print("\nFilling form...")
    output_1 = OUTPUT_DIR / "filled_form.pdf"
    fill_form(FORM_PATH, output_1, fields, mappings)
    print(f"Output: output/{output_1.name}")

    results = verify(output_1, mappings)
    print_verification(results)

    overall = "PASS" if all(r.passed for r in results) else "REVIEW REQUIRED"
    print(f"\nOverall status: {overall}")
    write_report(OUTPUT_DIR / "report.json", mappings, results, overall)

    if overall == "PASS":
        return

    # --- Simulate a human resolving the unresolved field(s) ---
    fields_by_name = {f.name: f for f in fields}
    for m in mappings:
        if m.status != "REVIEW" or m.field_name not in HUMAN_REVIEW_ANSWERS:
            continue
        answer = HUMAN_REVIEW_ANSWERS[m.field_name]
        print(f"\nHuman review:\n{m.field_name} \u2192 {answer}\n")
        m.source_key, m.value, m.status, m.reason = "human_review", answer, "APPROVED", None
        validate_and_transform(m, fields_by_name[m.field_name])

    print("Re-generating...")
    output_2 = OUTPUT_DIR / "filled_form_final.pdf"
    fill_form(FORM_PATH, output_2, fields, mappings)

    final_results = verify(output_2, mappings)
    final_overall = "PASS" if all(r.passed for r in final_results) else "REVIEW REQUIRED"
    print(f"\nFinal verification: {final_overall}")
    print(f"Output: output/{output_2.name}")
    write_report(OUTPUT_DIR / "report.json", mappings, final_results, final_overall)


if __name__ == "__main__":
    main()
