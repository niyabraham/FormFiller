"""tools/validate_public_form.py: runs the pipeline against a page and can never submit. Local loopback fixtures only."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "validate_public_form.py"
sys.path.insert(0, str(ROOT))
from benchmarks.spa.server import serve


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=180, cwd=ROOT, check=False)


def test_tool_has_no_way_to_submit():
    text = TOOL.read_text(encoding="utf-8")
    assert "submit=True" not in text and "--submit" not in text
    assert '"submit": False' in text


def test_rejects_non_http_urls(tmp_path):
    done = _run("--url", "file:///etc/passwd", "--source", str(tmp_path / "s.json"))
    assert done.returncode != 0 and "http" in done.stderr


@pytest.mark.browser
def test_runs_a_local_wizard_without_submitting(browser, tmp_path):  # `browser` only skips cleanly without Chromium
    with serve() as base:
        done = _run("--url", f"{base}/wiz_hidden.html", "--source", str(ROOT / "benchmarks/spa/source.json"),
                    "--policy", "--confirm-ms", "0", "--out-dir", str(tmp_path))
    assert done.returncode == 0, done.stderr
    data = json.loads((tmp_path / "result.json").read_text())
    assert "Run status:" in done.stdout and "Submission attempted: False" in done.stdout
    assert data["submission"] == {} and data["items"]
