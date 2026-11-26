"""A server-rendered page whose JavaScript framework attaches to the controls AFTER load: an answer entered before that is not
recorded by the framework, and its next re-render (caused by a LATER answer) clears it. Measured on a public template (HelloForms'
conditional-logic demo, TanStack Router + React): an early radio click survived on its own, was cleared once a second question was
answered, and stayed when both were entered after the framework attached.

The fixture below models exactly that: a hint that a framework is booting (`self.$_TSR`), controls that gain a framework key
(`__reactProps$...`) after DELAY_MS, and, from then on, a controlled re-render on every change that keeps only the choices the
framework itself recorded. The page here is a deterministic local fixture, not the public page."""

import time

import pytest

from formfill.web.pipeline import run_form

pytestmark = pytest.mark.browser

DELAY_MS = 700

FORM = ('<form onsubmit="return false">'
        '<fieldset><legend>Colour</legend><label><input type=radio name=colour value=red> Red</label>'
        '<label><input type=radio name=colour value=blue> Blue</label></fieldset>'
        '<fieldset><legend>Size</legend><label><input type=radio name=size value=s> Small</label>'
        '<label><input type=radio name=size value=l> Large</label></fieldset></form>')

HYDRATE = """<script>
self.$_TSR = {};
// A busy main thread: a change made BEFORE the framework attaches blocks the page for longer than the attach delay, so the attach
// lands between the first and second answer on every run (without this the fills could all finish before it, and the test would pass vacuously).
document.addEventListener('change', () => { if (!window.__attached) { const t = performance.now(); while (performance.now() - t < %d); } }, true);
setTimeout(() => {
  window.__attached = true;
  const state = {};                                   // what the framework itself has recorded: nothing entered earlier
  document.querySelectorAll('input').forEach(el => { el['__reactProps$fixture'] = {}; });
  delete self.$_TSR;
  document.addEventListener('change', e => {          // a controlled re-render: the DOM follows the framework's state
    state[e.target.name] = e.target.value;
    document.querySelectorAll('input[type=radio]').forEach(r => { r.checked = state[r.name] === r.value; });
  }, true);
}, %d);
</script>""" % (DELAY_MS + 200, DELAY_MS)

SOURCE = {"colour": "Blue", "size": "Large"}
CHECKED = "()=>[...document.querySelectorAll('input:checked')].map(i=>i.value)"


def test_the_fixture_reproduces_the_problem_for_an_early_answer(page):
    """Guards the premise: without the gate's wait, an answer entered before the framework attaches is lost on the next change."""
    page.set_content(FORM + HYDRATE)
    page.check("input[value=blue]")
    page.wait_for_function("()=>Object.getOwnPropertyNames(document.querySelector('input')).some(k=>k.startsWith('__react'))")
    page.check("input[value=l]")
    assert page.evaluate(CHECKED) == ["l"]  # "blue" was wiped


def test_the_run_waits_for_the_framework_and_both_answers_are_kept_and_verified(page):
    page.set_content(FORM + HYDRATE)
    res = run_form(page, SOURCE, confirm_ms=0)
    assert [i.verified for i in res.items] == [True, True]
    assert res.status == "FILLED" and not any("framework" in w for w in res.warnings)
    assert sorted(page.evaluate(CHECKED)) == ["blue", "l"]


def test_a_framework_that_never_attaches_is_reported_after_the_cap_not_waited_for_forever(page):
    page.set_content(FORM + "<script>self.$_TSR = {};</script>")
    t0 = time.monotonic()
    res = run_form(page, SOURCE, confirm_ms=0, hydration_timeout_ms=400)
    assert time.monotonic() - t0 < 8
    assert any("framework app" in w and "400 ms" in w for w in res.warnings)


def test_a_page_with_no_framework_hint_is_not_delayed_and_has_no_warning(page):
    page.set_content(FORM)
    t0 = time.monotonic()
    res = run_form(page, SOURCE, confirm_ms=0, hydration_timeout_ms=30000)  # a wait of that length would be unmistakable
    assert time.monotonic() - t0 < 15
    assert not any("framework" in w for w in res.warnings) and [i.verified for i in res.items] == [True, True]


def test_the_wait_can_be_switched_off(page):
    page.set_content(FORM + "<script>self.$_TSR = {};</script>")
    t0 = time.monotonic()
    res = run_form(page, SOURCE, confirm_ms=0, hydration_timeout_ms=0)
    assert time.monotonic() - t0 < 8 and not any("framework" in w for w in res.warnings)
