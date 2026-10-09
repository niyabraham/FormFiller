"""Generate the Phase 2 RFI benchmark into benchmarks/rfi/.

    python tools/build_benchmark.py

Output per case: form.html, source.json, truth.json (+ thanks.html for the
navigate-away submission scenario) and a top-level manifest.json. The files
are committed so reviewers can read them; this script is the single source
they are generated from.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_cases import ALL_CASES, OK_TEXT, submission_scenarios
from benchmark_render import render_form, truth_record

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_VERSION = "1.0.0"
SPLIT = "dev"  # development set: its failures have been inspected; never use it as a held-out estimate
OUT = ROOT / "benchmarks" / "rfi"


def write_case(c: dict, kind: str) -> dict:
    d = OUT / c["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "form.html").write_text(
        render_form(c["id"], c["qs"], submit=c.get("submit"), dynamic_steps=c.get("dynamic_steps", set())), encoding="utf-8")
    (d / "source.json").write_text(json.dumps(c["source"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "truth.json").write_text(
        json.dumps(truth_record(c["id"], c["description"], c.get("source_style", "form-aligned"), c["qs"]), indent=2,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    if c.get("submit") == "navigate":
        (d / "thanks.html").write_text(f"<!doctype html><meta charset=utf-8><title>Thanks</title><p>{OK_TEXT}</p>", encoding="utf-8")
    entry = {"id": c["id"], "kind": kind, "description": c["description"], "source_style": c.get("source_style", "form-aligned")}
    if kind == "submission":
        entry.update({k: c[k] for k in ("success_text", "expected_outcome", "expected_status")})
        if c.get("note"):
            entry["note"] = c["note"]
    return entry


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    manifest = [write_case(f(), "extraction") for f in ALL_CASES]
    for s in submission_scenarios():
        s.setdefault("source_style", "form-aligned")
        manifest.append(write_case(s, "submission"))
    (OUT / "manifest.json").write_text(json.dumps({"benchmark_version": BENCHMARK_VERSION, "split": SPLIT, "cases": manifest}, indent=2) + "\n", encoding="utf-8")
    n = sum(len(json.loads((OUT / e["id"] / "truth.json").read_text())["questions"]) for e in manifest)
    print(f"wrote {len(manifest)} cases, {n} questions -> {OUT}")


if __name__ == "__main__":
    main()
