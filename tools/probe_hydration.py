"""Diagnostic probe (read-only): does a page wipe or replace an input shortly after it is filled, when, and what was the page doing?

    python tools/probe_hydration.py [--url URL] [--selector CSS] [--delay-ms 0] [--duration-ms 25000]
        [--ready-js EXPR [--ready-timeout-ms 60000]] [--signal NAME=EXPR ...] [--collect EXPR]
        [--trace-setters] [--no-second-fill] [--second-wait-ms 3000] [--out-dir output/hydration_probe] [--headed]

Why: on a public template page a value typed into fields right after the `load` event was gone at the final read-back, while
a field filled seconds later kept its value. The suspicion is that the single-page app was still booting. This probe measures
it instead of inferring it. It is not part of the pipeline and adds nothing to it.

WHAT IT DOES (and nothing else)
  1. opens the URL and waits for `load`; optionally waits for `--ready-js` (a JS expression that must become truthy) and/or
     `--delay-ms`;
  2. types ONE fictional marker string into ONE field (`--selector`, first match). It never clicks, presses a key, touches a
     button or submits a form (a test checks this file for such calls);
  3. watches that field and the page for `--duration-ms`, then types the marker again and watches `--second-wait-ms` to show
     whether a late fill sticks. It never retries anything on the page's behalf.

TWO TIERS OF INSTRUMENTATION
  Observation only (always on). Nothing here calls into, wraps or replaces a page object, so it cannot change what the page does:
    - capture-phase, passive listeners for beforeinput/input/change/focusin/focusout/reset;
    - a MutationObserver (the field's value/disabled/readonly attributes; removal of the field or an ancestor);
    - PerformanceObservers: longtask, long-animation-frame (which scripts ran), resource (fetch/XHR/beacon, script count), paint;
    - a 50 ms sampler that READS the field (value, value attribute, attached, same node) and page signals (readyState, the
      TanStack Router bootstrap flag `self.$_TSR`, framework keys on the element such as React's `__reactProps$...`, focus,
      plus any `--signal NAME=EXPR`). It logs a row only when a value changes.
  Setter hook (opt-in `--trace-setters`, INTRUSIVE). Wraps `HTMLInputElement.prototype.value/defaultValue` setters so that when
  page code assigns the probed field it records the caller's stack. It passes every call straight through, but it is a patched
  page object: results are written to a separate file (`..._setters.json`) and flagged, so run it AFTER the observation-only
  run and compare `fill_to_reset_ms` between the two. Use it only to name the code that clears the field.

HOW TO READ THE TIMING (page clock = performance.now(), ms since navigation start)
  value_set_ms           when the typed text actually landed: the page's own `input` event for the field. This is the fill
                         operation. (Not when the probe called fill, and not when the sampler first noticed it: a busy page
                         delays both.)
  reset_observed_ms      the first sample that no longer shows the text.
  last_marker_tick_ms    the last sampler tick that still showed it.
  fill_to_reset_ms       reset_observed_ms - value_set_ms: an UPPER bound on how long the text survived.
  fill_to_reset_min_ms   last_marker_tick_ms - value_set_ms: a LOWER bound.
  The sampler is a page timer, so a long task starves it: when one overlaps the reset window the reset happened during or right
  after it (`reset_window_blocked_by`). With the setter hook the reset time is exact (`exact_reset_ms`).
  after_first_observation_ms is the OLD calculation (from the first sample that saw the text). It under-reports by however long
  the sampler was blocked before its first look; kept only so earlier numbers can be compared.

VERDICTS for a fill:  HELD (the value stayed) | VALUE_RESET (same element, value changed) | ELEMENT_REPLACED (detached or the
selector now resolves to another node) | MARKER_NEVER_OBSERVED.
`clear_mechanism` is inferred from what was observed: element_replaced, form_reset_event, value_attribute_changed,
input_event_with_empty_value, setter_hook:<property> (with `culprits`), or property_assignment_without_event (a script assigned
`.value`: run with --trace-setters to name it).
`readiness` lists, per signal, its value when the reset window began and any change after it (relation: within / after), which
is how to tell whether the reset coincided with, preceded or followed a readiness signal.

Fictional data only. FORMFILL_CHROMIUM may point at a Chromium executable.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://helloforms.net/templates/security-questionnaire-vendor-form"
DEFAULT_SELECTOR = "#try-it input[type='text']"
MARKER = "probe-marker-FICTIONAL"
SAMPLE_MS = 50
STALL_MS = 250

# Runs in every document before the page's own scripts. __CFG__ is replaced by a JSON object.
_INIT = r"""
(() => {
  if (window !== window.top || window.__probe) return;
  const CFG = __CFG__;
  const P = window.__probe = {ticks: [], samples: [], signals: [], events: [], longtasks: [], loafs: [], resources: [],
                              setters: [], scriptCount: 0, lastScriptEnd: 0, unsupported: [], sigLast: {}};
  const T = () => Math.round(performance.now() * 10) / 10;
  const short = (s, n) => String(s == null ? '' : s).slice(0, n);
  let el = null, prevKey = null;

  // ---- observation only: nothing below wraps or replaces a page object --------------------------------------------
  const watch = (type, cb) => { try { new PerformanceObserver(l => l.getEntries().forEach(cb)).observe({type, buffered: true}); } catch (e) { P.unsupported.push(type); } };
  watch('longtask', e => P.longtasks.push([Math.round(e.startTime), Math.round(e.duration)]));
  watch('long-animation-frame', e => P.loafs.push([Math.round(e.startTime), Math.round(e.duration), Math.round(e.blockingDuration || 0),
    (e.scripts || []).slice().sort((a, b) => b.duration - a.duration).slice(0, 3).map(s =>
      [s.invokerType || '', short(s.invoker, 70), short(String(s.sourceURL || '').split('/').pop().split('?')[0], 50), short(s.sourceFunctionName, 40), Math.round(s.duration)])]));
  watch('resource', e => {
    if (['fetch', 'xmlhttprequest', 'beacon'].includes(e.initiatorType))
      P.resources.push([Math.round(e.startTime), Math.round(e.responseEnd), e.initiatorType, short(String(e.name).replace(/^https?:\/\/[^/]+/, ''), 80)]);
    else if (/\.m?js(\?|$)/.test(e.name)) { P.scriptCount++; P.lastScriptEnd = Math.max(P.lastScriptEnd, Math.round(e.responseEnd)); }
  });
  watch('paint', e => P.signals.push([Math.round(e.startTime), 'paint:' + e.name, 'seen']));

  const onEvent = e => {
    const cur = el || document.querySelector(CFG.selector), t = e.target;
    if (cur && t === cur) P.events.push([T(), e.type, {trusted: e.isTrusted, inputType: e.inputType || null, len: String(t.value || '').length}]);
    else if (e.type === 'reset') P.events.push([T(), 'form-reset', {target: short((t && (t.id || t.tagName)) || '', 30), containsField: !!(cur && t.contains && t.contains(cur))}]);
  };
  for (const type of ['beforeinput', 'input', 'change', 'focusin', 'focusout', 'reset'])
    window.addEventListener(type, onEvent, {capture: true, passive: true});

  try {
    new MutationObserver(recs => {
      if (!el) return;
      for (const r of recs) {
        if (r.type === 'attributes' && r.target === el)
          P.events.push([T(), 'attr', {name: r.attributeName, old: short(r.oldValue, 40), now: short(el.getAttribute(r.attributeName), 40)}]);
        else if (r.type === 'childList')
          for (const n of r.removedNodes) if (n === el || (n.contains && n.contains(el))) P.events.push([T(), 'field-removed', {from: short((r.target && (r.target.id || r.target.tagName)) || '', 30)}]);
      }
    }).observe(document, {subtree: true, childList: true, attributes: true, attributeOldValue: true, attributeFilter: ['value', 'disabled', 'readonly']});
  } catch (e) { P.unsupported.push('MutationObserver'); }

  // page signals: readers only. `self.$_TSR` is the TanStack Router bootstrap object; the page deletes it when hydration and
  // the stream have both finished.
  const SIGNALS = {
    readyState: () => document.readyState,
    tanstack_bootstrap: () => self.$_TSR ? 'present(hydrated=' + !!self.$_TSR.hydrated + ',streamEnded=' + !!self.$_TSR.streamEnded + ')' : 'absent',
  };
  for (const [name, expr] of CFG.signals) { try { const f = new Function('return (' + expr + ')'); SIGNALS[name] = () => f(); } catch (e) { SIGNALS[name] = () => 'bad-expression'; } }
  const sig = (name, v) => { v = short(v, 120); if (P.sigLast[name] !== v) { P.sigLast[name] = v; P.signals.push([T(), name, v]); } };

  const tick = () => {
    const now = T();
    P.ticks.push(now);  // the same value a sample logged on this tick carries (a rounded tick could sort before its own sample)
    for (const name in SIGNALS) { try { sig(name, SIGNALS[name]()); } catch (e) { sig(name, 'error:' + short(e && e.message, 40)); } }
    if (!el) { const f = document.querySelector(CFG.selector); if (f) { el = f; P.events.push([now, 'field-found', {connected: f.isConnected}]); } }
    if (el) {
      const cur = document.querySelector(CFG.selector);
      sig('field_framework_keys', Object.getOwnPropertyNames(el).filter(k => /^__(react|vue|svelte|ember)|^_x_|^jQuery/.test(k)).map(k => k.replace(/\$.*$/, '')).sort().join(',') || 'none');
      sig('field_focused', document.activeElement === el);
      const state = [el.value, el.getAttribute('value'), el.isConnected, cur === el, cur ? cur.value : null];
      const key = JSON.stringify(state);
      if (key !== prevKey) { P.samples.push([now].concat(state)); prevKey = key; }
    }
  };
  setInterval(tick, CFG.sampleMs); tick();

  // ---- opt-in, INTRUSIVE: record who assigns the probed field's value ---------------------------------------------
  if (CFG.traceSetters) {
    for (const prop of ['value', 'defaultValue']) {
      const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, prop);
      if (!d || !d.set) continue;
      Object.defineProperty(HTMLInputElement.prototype, prop, {configurable: true, enumerable: d.enumerable, get: d.get, set(v) {
        if (el === null || this !== el) return d.set.call(this, v);
        const before = d.get.call(this), lim = Error.stackTraceLimit;
        let stack = ''; try { Error.stackTraceLimit = 40; stack = new Error().stack || ''; } catch (e) {} finally { Error.stackTraceLimit = lim; }
        const out = d.set.call(this, v);
        P.setters.push([T(), prop, short(before, 40), short(v, 40), short(d.get.call(this), 40),
          stack.split('\n').slice(2, 18).map(l => l.trim().replace(/https?:\/\/[^/ )]+/g, '')).join(' | ')]);
        return out;
      }});
    }
  }
})();
"""


def _pw_version():
    try:
        from importlib.metadata import version
        return version("playwright")
    except Exception:  # noqa: BLE001 - diagnostic metadata only
        return "unknown"


def _now(page) -> float:
    return round(float(page.evaluate("performance.now()")), 1)


def _fill_and_wait(page, loc, wait_ms: int, label: str) -> dict:
    """Type the marker. `start_ms` and `first_eval_after_ms` are page-clock readings taken by evaluate calls, which a busy page
    delays; neither is when the text landed (that is the page's own `input` event, see analyse)."""
    start = _now(page)
    loc.fill(MARKER)
    after = _now(page)
    page.wait_for_timeout(wait_ms)
    return {"label": label, "call_start_ms": start, "first_eval_after_ms": after}


def _wait_ready(page, expr: str, timeout_ms: int) -> dict:
    t0 = _now(page)
    try:
        page.wait_for_function(f"() => ({expr})", timeout=timeout_ms, polling=100)
        met = True
    except PlaywrightTimeout:
        met = False
    t1 = _now(page)
    return {"expr": expr, "met": met, "waited_ms": round(t1 - t0), "page_ms": t1}


# ---- analysis (pure functions: unit-tested without a browser) ---------------------------------------------------


def _verdict(samples: list, start: float, until: float | None, by_selector: bool) -> tuple[str, float | None, list | None]:
    """(verdict, time the text was first seen in place, the sample that ended it). Samples are
    [t, value, value-attr, attached, same-node, selector-value] and are logged only on change, so the state from before the
    window carries into it. A sample taken between the call starting and the value landing is not a reset."""
    col = 5 if by_selector else 1
    ok = (lambda s: s[col] == MARKER) if by_selector else (lambda s: s[col] == MARKER and s[3] and s[4])
    prior = [s for s in samples if s[0] < start]
    window = [s for s in samples if s[0] >= start and (until is None or s[0] < until)]
    seen_at: float | None = start if prior and ok(prior[-1]) else None
    for s in window:
        if seen_at is None:
            if ok(s):
                seen_at = s[0]
            continue
        if not by_selector and (not s[3] or not s[4]):
            return "ELEMENT_REPLACED", seen_at, s
        if s[col] != MARKER:
            return "VALUE_RESET", seen_at, s
    return ("HELD" if seen_at is not None else "MARKER_NEVER_OBSERVED"), seen_at, None


def _mechanism(reset: list, events: list, lo: float, hi: float, culprits: list) -> str:
    if reset[3] is False or reset[4] is False:
        return "element_replaced"
    inside = [e for e in events if lo - 1 <= e[0] <= hi + 1]
    if culprits:
        return f"setter_hook:{culprits[0][1]}"
    if any(e[1] == "form-reset" and e[2].get("containsField") for e in inside):
        return "form_reset_event"
    if any(e[1] == "attr" and e[2].get("name") == "value" and e[2].get("now") in ("", None) for e in inside):
        return "value_attribute_changed"
    if any(e[1] in ("input", "change") and e[2].get("len") == 0 for e in inside):
        return "input_event_with_empty_value"
    return "property_assignment_without_event"


def analyse(samples: list, fill_start_ms: float, until_ms: float | None = None, by_selector: bool = False, *,
            events: list | tuple = (), ticks: list | tuple = (), setters: list | tuple = (), longtasks: list | tuple = ()) -> dict:
    """Verdict and timing for one fill. The fill operation is the page's own `input` event for the field (`value_set_ms`);
    if there is none, the first sample that shows the text (`value_set_source` says which)."""
    verdict, seen_at, reset = _verdict(samples, fill_start_ms, until_ms, by_selector)
    inputs = [e[0] for e in events if e[1] == "input" and e[0] >= fill_start_ms and (until_ms is None or e[0] < until_ms)
              and e[2].get("len", 1) > 0]
    value_set = inputs[0] if inputs else seen_at
    early = False
    if verdict == "MARKER_NEVER_OBSERVED" and inputs and ticks:
        # The page's own input event proves the text landed, yet no sample ever showed it. Samples are logged on change, so
        # if the text had still been there at the first tick after the input, that tick would have logged it: it was
        # already gone by then (the page cleared it inside the same busy stretch). The reset time is bounded, not exact.
        nxt = [t for t in ticks if t > inputs[0] and (until_ms is None or t < until_ms)]
        known = [x for x in samples if nxt and x[0] <= nxt[0] + 1]  # +1: results saved with ticks rounded to whole ms
        if nxt and known:
            verdict, early = "VALUE_RESET", True
            seen_at = None
            reset = [nxt[0], *known[-1][1:]]
    out: dict = {"verdict": verdict, "value_set_ms": value_set,
                 "value_set_source": "input-event" if inputs else ("first-sample" if seen_at is not None else None)}
    if early:
        out["reset_before_first_observation"] = True
    if reset is None:
        return out
    reset_t = reset[0]
    base = value_set if value_set is not None else reset_t
    held = [t for t in ticks if base <= t < reset_t]
    lo = float(max(held)) if held else float(base)
    # a culprit is a setter call that actually took the typed text away (before == marker, after != marker); calls that
    # rewrote the same value (e.g. React's hydration pass writing defaultValue) are not.
    culprits = [list(s) for s in setters if base <= s[0] <= reset_t + 100 and s[2] == MARKER and s[4] != MARKER]
    out.update({
        "reset_observed_ms": reset_t,
        "last_marker_tick_ms": lo,
        "fill_to_reset_ms": round(reset_t - base, 1),
        "fill_to_reset_min_ms": round(lo - base, 1),
        "after_first_observation_ms": round(reset_t - seen_at, 1) if seen_at is not None else None,
        "reset_window_blocked_by": [list(t) for t in longtasks if t[0] < reset_t and t[0] + t[1] > lo],
        "value_now": reset[1] if not by_selector else reset[5],
        "clear_mechanism": _mechanism(reset, list(events), lo, reset_t, culprits),
        "culprits": culprits,
        "setter_calls_that_changed_nothing": [list(s) for s in setters if base <= s[0] <= reset_t + 100 and s[2] == s[4]][:10],
    })
    if culprits:
        out["exact_reset_ms"] = culprits[0][0]
        out["fill_to_reset_exact_ms"] = round(culprits[0][0] - base, 1)
    return out


def readiness(signals: list, first: dict) -> dict | None:
    """Per signal: its value when the reset window began, and every change after it (within the window, or after it)."""
    if first.get("reset_observed_ms") is None:
        return None
    lo, hi = first["last_marker_tick_ms"], first["reset_observed_ms"]
    by: dict[str, list] = {}
    for t, name, val in signals:
        by.setdefault(name, []).append((t, val))
    out = {}
    for name, seq in by.items():
        at = None
        later = []
        for t, val in seq:
            if t <= lo:
                at = val
            else:
                later.append([t, val, "within" if t < hi else "after"])
        out[name] = {"at_start_of_reset_window": at, "changes_after": later[:6]}
    return out


def build_timeline(data: dict, nav: dict | None, analyses: list[tuple[str, dict]]) -> list:
    rows: list = []

    def add(t, kind, text):
        rows.append([round(float(t), 1), kind, text])

    if nav:
        add(nav["ttfb"], "nav", "first byte")
        add(nav["dcl"], "nav", "DOMContentLoaded finished")
        add(nav["load"], "nav", "load event finished")
    for t, name, val in data["signals"]:
        add(t, "signal", f"{name} = {val}")
    for t, kind, detail in data["events"]:
        add(t, "event", f"{kind} {json.dumps(detail, separators=(',', ':'))}")
    for s, d in data["longtasks"]:
        add(s, "longtask", f"long task {d} ms (ends {s + d})")
    for s, d, b, scripts in data["loafs"]:
        who = "; ".join(f"{x[0]} {x[2] or x[1]} {x[3]} {x[4]}ms".strip() for x in scripts)
        add(s, "frame", f"long animation frame {d} ms (blocking {b}); {who}")
    for s, e, kind, name in data["resources"]:
        add(s, "network", f"{kind} {name} ({e - s} ms)")
    for t, prop, before, to, _after, stack in data["setters"]:
        add(t, "setter", f"{prop}: {before!r} -> {to!r} by {stack.split(' | ')[0]}")
    for label, a in analyses:
        if a.get("value_set_ms") is not None:
            add(a["value_set_ms"], "PROBE", f"{label}: text landed ({a.get('value_set_source')})")
        if a.get("reset_observed_ms") is not None:
            add(a["last_marker_tick_ms"], "PROBE", f"{label}: last tick that still held the text")
            add(a["reset_observed_ms"], "PROBE", f"{label}: reset observed ({a.get('clear_mechanism')})")
    rows.sort(key=lambda r: r[0])
    return rows


def probe(url: str, selector: str, delay_ms: int = 0, duration_ms: int = 25000, second_fill: bool = True, headed: bool = False, *,
          trace_setters: bool = False, signals: list | tuple = (), collect: str | None = None, ready_js: str | None = None,
          ready_timeout_ms: int = 60000, second_wait_ms: int = 3000) -> dict:
    cfg = {"selector": selector, "sampleMs": SAMPLE_MS, "traceSetters": bool(trace_setters), "signals": [list(s) for s in signals]}
    init = _INIT.replace("__CFG__", json.dumps(cfg))
    exe = os.environ.get("FORMFILL_CHROMIUM") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, executable_path=exe)
        try:
            context = browser.new_context()
            context.add_init_script(init)
            page = context.new_page()
            page.goto(url, wait_until="load")
            loaded_ms = _now(page)
            ready = _wait_ready(page, ready_js, ready_timeout_ms) if ready_js else None
            if delay_ms:
                page.wait_for_timeout(delay_ms)
            loc = page.locator(selector).first
            loc.wait_for(state="attached", timeout=15000)
            first = _fill_and_wait(page, loc, duration_ms, "first")
            second = _fill_and_wait(page, loc, second_wait_ms, "second") if second_fill else None
            data = page.evaluate("window.__probe")
            nav = page.evaluate("""(() => { const n = performance.getEntriesByType('navigation')[0];
                return n ? {ttfb: n.responseStart, dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd} : null; })()""")
            collected = None
            if collect:
                try:
                    collected = page.evaluate(f"() => ({collect})")
                except Exception as exc:  # noqa: BLE001 - reported, not raised
                    collected = {"error": str(exc).splitlines()[0]}
            env = {"browser": browser.version, "user_agent": page.evaluate("navigator.userAgent"), "platform": sys.platform,
                   "headless": not headed, "playwright_python": _pw_version()}
        finally:
            browser.close()

    ticks = data["ticks"]
    stalls = [[a, b - a] for a, b in itertools.pairwise(ticks) if b - a > STALL_MS]
    extras = {"events": data["events"], "ticks": ticks, "setters": data["setters"], "longtasks": data["longtasks"]}
    a1 = analyse(data["samples"], first["call_start_ms"], second["call_start_ms"] if second else None, **extras)
    a2 = analyse(data["samples"], second["call_start_ms"], by_selector=True, **extras) if second else None
    analyses = [("fill 1", a1)] + ([("fill 2", a2)] if a2 else [])
    return {
        "url": url, "selector": selector, "delay_ms": delay_ms, "load_event_ms": loaded_ms, "ready": ready,
        "instrumentation": {
            "observation_only": ["input/change/focus/reset listeners (capture, passive)", "MutationObserver", "PerformanceObserver",
                                 f"{SAMPLE_MS} ms read-only sampler"],
            "setter_hook": bool(trace_setters),
            "setter_hook_note": "INTRUSIVE: patches HTMLInputElement.prototype value/defaultValue setters (pass-through); compare with an "
                                "observation-only run" if trace_setters else None,
            "unsupported_in_this_browser": data["unsupported"],
        },
        "environment": env,
        "first_fill": {**first, **a1},
        "second_fill": {**second, **a2} if second and a2 else None,
        "readiness": readiness(data["signals"], a1),
        "page_activity": {"script_resources": data["scriptCount"], "last_script_response_end_ms": data["lastScriptEnd"],
                          "fetch_xhr_beacon": data["resources"], "long_task_total_ms": sum(d for _, d in data["longtasks"]),
                          "long_task_max_ms": max((d for _, d in data["longtasks"]), default=0)},
        "longtasks": data["longtasks"],
        "long_animation_frames": data["loafs"],
        f"stalls_over_{STALL_MS}ms": stalls,
        "signals": data["signals"], "events": data["events"], "setters": data["setters"],
        "collected": collected,
        "timeline": build_timeline(data, nav, analyses),
        "samples": data["samples"],
        "note": "times are page performance.now() (ms since navigation start). samples are [t, value, value-attr, attached, "
                "same-node, selector-value], logged only when something changed. See the module docstring for how to read the timing.",
    }


def _print_summary(res: dict, path: Path) -> None:
    f = res["first_fill"]
    print(f"load event at {res['load_event_ms']} ms; delay {res['delay_ms']} ms"
          + (f"; ready-js {'met' if res['ready']['met'] else 'NOT met'} after {res['ready']['waited_ms']} ms" if res["ready"] else ""))
    if res["instrumentation"]["setter_hook"]:
        print("NOTE: setter hook enabled (intrusive); compare with an observation-only run.")
    print(f"FIRST FILL: {f['verdict']}")
    if f.get("value_set_ms") is not None:
        print(f"  text landed at {f['value_set_ms']} ms (source: {f['value_set_source']})")
    if f.get("reset_observed_ms") is not None:
        print(f"  reset observed at {f['reset_observed_ms']} ms; last tick that held the text: {f['last_marker_tick_ms']} ms")
        print(f"  fill -> reset: between {f['fill_to_reset_min_ms']} and {f['fill_to_reset_ms']} ms"
              + (f" (exact {f['fill_to_reset_exact_ms']} ms)" if "fill_to_reset_exact_ms" in f else ""))
        legacy = f["after_first_observation_ms"]
        print("  (the old calculation, from first observation, "
              + (f"would say {legacy} ms)" if legacy is not None else "has no value: the text was never sampled)"))
        if f["reset_window_blocked_by"]:
            print(f"  resolution limited: the reset happened during/right after long task(s) {f['reset_window_blocked_by']}")
        print(f"  clear mechanism: {f['clear_mechanism']}")
        for c in f["culprits"][:3]:
            print(f"  culprit @ {c[0]} ms: .{c[1]} {c[2]!r} -> {c[3]!r}\n      {c[5][:400]}")
        for name, info in (res["readiness"] or {}).items():
            if info["changes_after"] or name in ("tanstack_bootstrap", "field_framework_keys"):
                print(f"  signal {name}: at start of reset window = {info['at_start_of_reset_window']}; later changes = {info['changes_after']}")
    if res["second_fill"]:
        print(f"SECOND (late) FILL: {res['second_fill']['verdict']}")
    st = res[f"stalls_over_{STALL_MS}ms"]
    pa = res["page_activity"]
    print(f"timer stalls > {STALL_MS} ms: {len(st)}" + (f", longest {max(d for _, d in st)} ms" if st else "")
          + f"; long tasks: {len(res['longtasks'])}, total {pa['long_task_total_ms']} ms, longest {pa['long_task_max_ms']} ms")
    lo = (f.get("value_set_ms") or 0) - 300
    hi = (f.get("reset_observed_ms") or (f.get("value_set_ms") or 0)) + 300
    rows = [r for r in res["timeline"] if lo <= r[0] <= hi]
    print(f"timeline around the fill/reset ({len(rows)} of {len(res['timeline'])} rows):")
    for t, kind, text in rows[:60]:
        print(f"  {t:>9.1f}  {kind:<9} {text[:150]}")
    if len(rows) > 60:
        print(f"  ... {len(rows) - 60} more rows in the JSON")
    print(f"details: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--selector", default=DEFAULT_SELECTOR, help="CSS selector of one text input (first match is used)")
    ap.add_argument("--delay-ms", type=int, default=0, help="extra wait after `load` (and --ready-js) before typing")
    ap.add_argument("--duration-ms", type=int, default=25000, help="how long to watch after the first fill")
    ap.add_argument("--second-wait-ms", type=int, default=3000, help="how long to watch after the late second fill")
    ap.add_argument("--no-second-fill", action="store_true")
    ap.add_argument("--ready-js", help="JS expression that must be truthy before typing (bounded by --ready-timeout-ms); "
                                       "the probe types anyway on timeout and records ready.met=false")
    ap.add_argument("--ready-timeout-ms", type=int, default=60000)
    ap.add_argument("--signal", action="append", default=[], metavar="NAME=EXPR", help="sample a JS expression every 50 ms (repeatable)")
    ap.add_argument("--collect", help="JS expression evaluated at the end and stored under `collected` (e.g. a page-side log)")
    ap.add_argument("--trace-setters", action="store_true", help="INTRUSIVE: record the stack of page code that assigns the field's value")
    ap.add_argument("--out-dir", default="output/hydration_probe")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)

    signals = []
    for s in a.signal:
        name, sep, expr = s.partition("=")
        if not sep or not name.strip() or not expr.strip():
            ap.error(f"--signal expects NAME=EXPR, got {s!r}")
        signals.append((name.strip(), expr.strip()))

    res = probe(a.url, a.selector, a.delay_ms, a.duration_ms, not a.no_second_fill, a.headed, trace_setters=a.trace_setters,
                signals=signals, collect=a.collect, ready_js=a.ready_js, ready_timeout_ms=a.ready_timeout_ms,
                second_wait_ms=a.second_wait_ms)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = (f"probe_delay{a.delay_ms}{'_ready' if a.ready_js else ''}{'_setters' if a.trace_setters else ''}"
            f"_{time.strftime('%H%M%S')}.json")
    path = out / name
    path.write_text(json.dumps(res, indent=2))
    _print_summary(res, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
