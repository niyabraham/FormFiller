"""tools/probe_hydration.py: the diagnostic that tells a reset-after-fill apart from a value that held, and says when and why.

The probe is read-only evidence for "does this page wipe an input shortly after it is filled (e.g. while a single-page app
hydrates)?". It is not part of the pipeline and nothing here adds a retry to the pipeline. The browser tests run it as a
subprocess (it owns its own Playwright) against local, fictional fixtures whose own logs give the true timings.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "probe_hydration.py"
FIXTURES = ROOT / "tests" / "web" / "fixtures"


def _load_tool():
    spec = importlib.util.spec_from_file_location("probe_hydration", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load_tool()
M = probe.MARKER


def S(t, value=""):  # one sample: [t, value, value-attr, attached, same-node, selector-value]
    return [t, value, "", True, True, value]


# ---- verdict and timing logic (no browser) --------------------------------------------------


def test_value_that_stays_is_held():
    assert probe.analyse([S(0), S(100, M)], 90)["verdict"] == "HELD"


def test_value_wiped_on_the_same_element_is_a_reset():
    got = probe.analyse([S(0), S(100, M), S(700)], 90)
    assert got["verdict"] == "VALUE_RESET" and got["reset_observed_ms"] == 700


def test_fill_to_reset_is_measured_from_the_input_event_not_the_first_observation():
    # the sampler was starved: the text landed at 100 (input event) but was only seen at 1900; the reset was seen at 2400.
    samples = [S(0), S(1900, M), S(2400)]
    events = [[100, "input", {"len": 22}]]
    ticks = [0, 50, 1900, 2000, 2400]
    got = probe.analyse(samples, 90, events=events, ticks=ticks)
    assert got["value_set_ms"] == 100 and got["value_set_source"] == "input-event"
    assert got["fill_to_reset_ms"] == 2300  # upper bound: fill operation -> reset observed
    assert got["fill_to_reset_min_ms"] == 1900.0  # lower bound: fill operation -> last tick that held the text
    assert got["after_first_observation_ms"] == 500  # the old calculation, kept for comparison, under-reports
    assert got["fill_to_reset_min_ms"] <= got["fill_to_reset_ms"]


def test_without_an_input_event_the_first_sample_is_the_fallback():
    got = probe.analyse([S(0), S(100, M), S(700)], 90)
    assert got["value_set_source"] == "first-sample" and got["value_set_ms"] == 100


def test_text_that_was_never_sampled_but_was_typed_is_a_reset_with_wide_bounds():
    # input event proves the text landed; the next tick already shows it gone (the page cleared it in the same busy stretch)
    got = probe.analyse([S(0)], 90, events=[[100, "input", {"len": 22}]], ticks=[0, 50, 1700, 1750],
                        longtasks=[[105, 1500]])
    assert got["verdict"] == "VALUE_RESET" and got["reset_before_first_observation"] is True
    assert got["fill_to_reset_min_ms"] == 0 and got["fill_to_reset_ms"] == 1600
    assert got["reset_window_blocked_by"] == [[105, 1500]]


def test_an_empty_input_event_is_not_a_fill():
    assert probe.analyse([S(0)], 90, events=[[100, "input", {"len": 0}]], ticks=[0, 200])["verdict"] == "MARKER_NEVER_OBSERVED"


def test_detached_or_replaced_element_is_a_remount():
    detached = [S(100, M), [700, M, "", False, False, ""]]
    got = probe.analyse(detached, 90)
    assert got["verdict"] == "ELEMENT_REPLACED" and got["clear_mechanism"] == "element_replaced"
    assert probe.analyse([S(100, M), [700, M, "", True, False, ""]], 90)["verdict"] == "ELEMENT_REPLACED"


def test_a_sample_taken_before_the_value_was_set_is_not_a_reset():
    assert probe.analyse([S(95), S(110, M)], 90)["verdict"] == "HELD"


def test_the_marker_never_appearing_is_reported_not_assumed_held():
    assert probe.analyse([S(0)], 90)["verdict"] == "MARKER_NEVER_OBSERVED"
    assert probe.analyse([], 90)["verdict"] == "MARKER_NEVER_OBSERVED"


def test_a_late_fill_is_judged_on_the_selector_and_carries_state_over():
    s = [S(100, M), [700, M, "", False, False, ""], [5000, M, "", False, False, M]]
    assert probe.analyse(s, 4990, by_selector=True)["verdict"] == "HELD"
    assert probe.analyse([S(100, M)], 4990, by_selector=True)["verdict"] == "HELD"
    again = [[5000, M, "", False, False, M], [5600, M, "", False, False, ""]]
    assert probe.analyse(again, 4990, by_selector=True)["verdict"] == "VALUE_RESET"


def test_the_first_fill_window_ends_where_the_second_begins():
    assert probe.analyse([S(100, M), S(5000)], 90, until_ms=4990)["verdict"] == "HELD"


def test_clear_mechanism_is_inferred_from_what_was_observed():
    base = [S(100, M), S(700)]
    kw = {"ticks": [100, 650, 700]}
    assert probe.analyse(base, 90, events=[], **kw)["clear_mechanism"] == "property_assignment_without_event"
    assert probe.analyse(base, 90, events=[[690, "form-reset", {"containsField": True}]], **kw)["clear_mechanism"] == "form_reset_event"
    assert probe.analyse(base, 90, events=[[690, "attr", {"name": "value", "now": ""}]], **kw)["clear_mechanism"] == "value_attribute_changed"
    assert probe.analyse(base, 90, events=[[690, "input", {"len": 0}]], **kw)["clear_mechanism"] == "input_event_with_empty_value"


def test_a_setter_trace_names_the_culprit_and_the_exact_time():
    setters = [[100, "value", "", M, M, "x"], [640, "value", M, "", "", "renderControlled@page | other"]]
    got = probe.analyse(base := [S(100, M), S(700)], 90, setters=setters, ticks=[100, 650, 700])
    assert base and got["clear_mechanism"] == "setter_hook:value"
    assert got["exact_reset_ms"] == 640 and got["fill_to_reset_exact_ms"] == 540  # no marker-typing setter counted as culprit


def test_readiness_relates_a_signal_change_to_the_reset_window():
    first = {"reset_observed_ms": 1600, "last_marker_tick_ms": 100}
    sig = [[10, "boot", "present"], [1850, "boot", "absent"], [1550, "other", "x"]]
    got = probe.readiness(sig, first)
    assert got["boot"]["at_start_of_reset_window"] == "present"
    assert got["boot"]["changes_after"] == [[1850, "absent", "after"]]
    assert got["other"]["changes_after"] == [[1550, "x", "within"]]
    assert probe.readiness(sig, {"reset_observed_ms": None}) is None


def test_the_probe_source_never_clicks_presses_or_submits():
    src = TOOL.read_text()
    assert not re.search(r"\.(click|press|dispatch_event|check|select_option)\(|requestSubmit|\.submit\(|form\.reset", src)
    assert "submit_selector" not in src


# ---- against local fixtures (browser, subprocess) --------------------------------------------


def run_probe(tmp_path, fixture, query="", *extra, duration=2500, second_wait=600, selector="#a"):
    url = (FIXTURES / fixture).as_uri() + (("?" + query) if query else "")
    done = subprocess.run(
        [sys.executable, str(TOOL), "--url", url, "--selector", selector, "--delay-ms", "0", "--duration-ms", str(duration),
         "--second-wait-ms", str(second_wait), "--out-dir", str(tmp_path), *extra],
        capture_output=True, text=True, timeout=180, cwd=ROOT, check=False,
    )
    assert done.returncode == 0, done.stderr
    files = sorted(tmp_path.glob("probe_*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(files[-1].read_text()), done.stdout


@pytest.mark.browser
@pytest.mark.parametrize("mode, verdict", [("reset", "VALUE_RESET"), ("replace", "ELEMENT_REPLACED"), ("none", "HELD")])
def test_probe_tells_the_three_outcomes_apart(browser, tmp_path, mode, verdict):
    res, out = run_probe(tmp_path, "late_reset.html", f"mode={mode}", duration=1500, selector="#v")
    first = res["first_fill"]
    assert first["verdict"] == verdict and f"FIRST FILL: {verdict}" in out
    if verdict != "HELD":
        assert first["fill_to_reset_min_ms"] <= 500 + 150 and 400 <= first["fill_to_reset_ms"] <= 1400  # fixture: 500 ms after input
    assert res["second_fill"]["verdict"] == "HELD"  # the fixture only acts on the first input


@pytest.mark.browser
def test_probe_only_types_the_fictional_marker(browser, tmp_path):
    res, _ = run_probe(tmp_path, "late_reset.html", "mode=none", duration=1200, selector="#v")
    assert {s[1] for s in res["samples"]} <= {"", M}
    assert res["instrumentation"]["setter_hook"] is False and "playwright_python" in res["environment"]


@pytest.mark.browser
def test_interval_bounds_contain_the_pages_own_true_interval(browser, tmp_path):
    # the page cleared the field inside the same busy stretch; its own log says when the block began and the reset happened
    res, out = run_probe(tmp_path, "diag_boot.html", "block=1200&gap=250", "--collect", "window.__bootLog")
    log = {e["e"]: e["t"] for e in res["collected"]}
    true_interval = log["reset"] - log["block-start"]
    first = res["first_fill"]
    assert first["verdict"] == "VALUE_RESET" and first["value_set_source"] == "input-event"
    assert first["fill_to_reset_min_ms"] <= true_interval + 50
    assert true_interval - 50 <= first["fill_to_reset_ms"] <= true_interval + 400
    assert first["reset_window_blocked_by"], "the long task that hid the reset must be named"
    assert "resolution limited" in out
    # the readiness signal places the reset BEFORE the bootstrap flag object disappeared
    boot = res["readiness"]["tanstack_bootstrap"]
    assert boot["at_start_of_reset_window"].startswith("present")
    assert boot["changes_after"] and boot["changes_after"][0][2] == "after"


@pytest.mark.browser
def test_the_legacy_calculation_under_reports_a_starved_window(browser, tmp_path):
    res, _ = run_probe(tmp_path, "diag_boot.html", "block=1200&gap=250&order=ready-then-reset", "--collect", "window.__bootLog")
    log = {e["e"]: e["t"] for e in res["collected"]}
    first = res["first_fill"]
    # here the reset follows readiness by 250 ms, so the sampler gets a tick in between and can see the text
    assert first["verdict"] == "VALUE_RESET"
    legacy = first["after_first_observation_ms"]
    assert log["ready"] < log["reset"]
    assert legacy is None or legacy < first["fill_to_reset_ms"]
    assert res["readiness"]["tanstack_bootstrap"]["at_start_of_reset_window"] == "absent"  # ready first, then the reset


@pytest.mark.browser
def test_observation_only_default_cannot_name_the_culprit_but_says_so(browser, tmp_path):
    res, _ = run_probe(tmp_path, "diag_controlled.html", "mode=clear")
    first = res["first_fill"]
    assert first["verdict"] == "VALUE_RESET" and first["clear_mechanism"] == "property_assignment_without_event"
    assert first["culprits"] == [] and res["instrumentation"]["setter_hook"] is False
    assert 400 <= first["fill_to_reset_ms"] <= 900 and first["fill_to_reset_min_ms"] <= first["fill_to_reset_ms"]
    assert res["second_fill"]["verdict"] == "HELD"


@pytest.mark.browser
def test_setter_trace_names_the_function_that_cleared_the_field_without_changing_the_outcome(browser, tmp_path):
    plain, _ = run_probe(tmp_path / "a", "diag_controlled.html", "mode=clear")
    traced, out = run_probe(tmp_path / "b", "diag_controlled.html", "mode=clear", "--trace-setters")
    first = traced["first_fill"]
    assert first["verdict"] == plain["first_fill"]["verdict"] == "VALUE_RESET"
    assert first["clear_mechanism"].startswith("setter_hook:")
    assert first["culprits"] and "renderControlled" in first["culprits"][0][5]
    assert abs(first["fill_to_reset_ms"] - plain["first_fill"]["fill_to_reset_ms"]) < 200  # instrumentation did not move it
    assert traced["instrumentation"]["setter_hook"] is True and "intrusive" in out.lower()
    assert list((tmp_path / "b").glob("*_setters_*.json"))


@pytest.mark.browser
def test_a_controlled_field_that_adopts_the_typed_text_holds(browser, tmp_path):
    res, _ = run_probe(tmp_path, "diag_controlled.html", "mode=adopt")
    assert res["first_fill"]["verdict"] == "HELD"


@pytest.mark.browser
def test_ready_js_gates_typing_and_a_custom_signal_is_logged(browser, tmp_path):
    res, _ = run_probe(tmp_path, "diag_boot.html", "trigger=load&block=600&gap=100&order=reset-then-ready",
                       "--ready-js", "window.__booted === true", "--ready-timeout-ms", "5000",
                       "--signal", "booted=String(window.__booted)", "--collect", "window.__bootLog", duration=1500)
    log = {e["e"]: e["t"] for e in res["collected"]}
    assert res["ready"]["met"] is True and log["ready"] < res["first_fill"]["value_set_ms"]
    names = {s[1] for s in res["signals"]}
    assert "booted" in names
    # the page booted (and finished its one reset) before anything was typed, so the typed text holds
    assert res["first_fill"]["verdict"] == "HELD"


@pytest.mark.browser
def test_ready_js_that_never_comes_true_is_recorded_not_hidden(browser, tmp_path):
    res, out = run_probe(tmp_path, "late_reset.html", "mode=none", "--ready-js", "window.__never === true",
                         "--ready-timeout-ms", "700", duration=800, selector="#v")
    assert res["ready"]["met"] is False and "NOT met" in out


def test_a_setter_call_that_rewrote_the_same_value_is_not_the_culprit():
    setters = [[300, "defaultValue", "", "", "", "postMountWrapper | diffHydratedProperties"],
               [640, "value", M, "", "", "updateWrapper | commitUpdate"]]
    got = probe.analyse([S(100, M), S(700)], 90, setters=setters, ticks=[100, 650, 700])
    assert [c[5].split(" | ")[0] for c in got["culprits"]] == ["updateWrapper"]
    assert got["clear_mechanism"] == "setter_hook:value" and got["exact_reset_ms"] == 640
    assert [c[1] for c in got["setter_calls_that_changed_nothing"]] == ["defaultValue"]
