"""Network policy decisions (no browser): what a guarded walk may send, and why everything else is refused."""

from __future__ import annotations

import json

import pytest

from formfill.web.netpolicy import AllowRule, NetworkPolicy, entered_values_in, origin_of

BASE = "https://portal.example"
SECTIONS = AllowRule(origin=BASE, path="/api/section/*", methods=frozenset({"GET"}), resource_types=frozenset({"fetch"}))
SAVE = AllowRule(origin=BASE, path="/api/answers", methods=frozenset({"POST"}), answer_data=True, note="autosave")
STEP = AllowRule(origin=BASE, path="/wizard/step/*", methods=frozenset({"POST", "GET"}), resource_types=frozenset({"document"}),
                 answer_data=True, form_navigation=True)


def test_the_default_policy_blocks_everything():
    p = NetworkPolicy()
    assert p.blocks_everything
    d = p.decide(f"{BASE}/api/section/2", "GET", "fetch")
    assert not d.allowed and "blocked" in d.reason


@pytest.mark.parametrize(("url", "method", "rtype", "allowed"), [
    (f"{BASE}/api/section/2", "GET", "fetch", True),
    (f"{BASE}/api/section/2", "GET", "xhr", False),  # resource type not in the rule
    (f"{BASE}/api/section/2", "POST", "fetch", False),  # method not in the rule
    (f"{BASE}/api/other", "GET", "fetch", False),  # path not covered
    ("https://portal.example.evil/api/section/2", "GET", "fetch", False),  # look-alike origin
    ("http://portal.example/api/section/2", "GET", "fetch", False),  # scheme is part of the origin
    ("https://portal.example:8443/api/section/2", "GET", "fetch", False),  # so is the port
    ("data:text/plain,hi", "GET", "fetch", False),
])
def test_a_rule_matches_only_its_exact_origin_path_method_and_type(url, method, rtype, allowed):
    assert NetworkPolicy(rules=(SECTIONS,)).decide(url, method, rtype).allowed is allowed


def test_a_request_carrying_an_entered_answer_is_refused_unless_the_rule_allows_answer_data():
    p = NetworkPolicy(rules=(SECTIONS, SAVE))
    leak = p.decide(f"{BASE}/api/section/2?draft=Fictional%20Vendor%20LLC", "GET", "fetch", entered={"Fictional Vendor LLC"})
    assert not leak.allowed and leak.carries_answers and "entered" in leak.reason
    save = p.decide(f"{BASE}/api/answers", "POST", "fetch", body=json.dumps({"org": "Fictional Vendor LLC"}).encode(),
                    entered={"Fictional Vendor LLC"})
    assert save.allowed and save.carries_answers and save.rule is SAVE


def test_a_write_without_answer_data_permission_is_refused_even_when_it_carries_no_answer():
    rule = AllowRule(origin=BASE, path="/api/*", methods=frozenset({"GET", "POST"}))
    d = NetworkPolicy(rules=(rule,)).decide(f"{BASE}/api/ping", "POST", "fetch", body=b"{}")
    assert not d.allowed and "changes server state" in d.reason


@pytest.mark.parametrize(("url", "body", "found"), [
    ("https://x.example/a?q=Fictional+Vendor+LLC", None, ["Fictional Vendor LLC"]),  # form-encoded query
    ("https://x.example/a", b"org=Fictional%20Vendor%20LLC", ["Fictional Vendor LLC"]),  # urlencoded body
    ("https://x.example/a", json.dumps({"o": "fictional vendor llc"}).encode(), ["Fictional Vendor LLC"]),  # case-insensitive
    ("https://x.example/a?q=Yes", None, []),  # yes/no and short values say nothing about the questionnaire
    ("https://x.example/a?n=120", None, []),
])
def test_entered_answers_are_found_in_every_readable_encoding(url, body, found):
    assert entered_values_in(url, body, {"Fictional Vendor LLC", "Yes", "120"}) == found


def test_form_navigation_needs_answer_data_and_is_looked_up_by_action():
    with pytest.raises(ValueError):
        AllowRule(origin=BASE, path="/wizard/*", methods=frozenset({"POST"}), form_navigation=True)
    p = NetworkPolicy(rules=(SECTIONS, STEP))
    assert p.form_navigation_rule(f"{BASE}/wizard/step/2", "POST") is STEP
    assert p.form_navigation_rule(f"{BASE}/wizard/submit", "POST") is None
    assert NetworkPolicy(rules=(SECTIONS,)).form_navigation_rule(f"{BASE}/api/section/2", "GET") is None


@pytest.mark.parametrize("origin", ["portal.example", "https://portal.example/path", "ftp://portal.example", ""])
def test_a_rule_origin_must_be_scheme_host_and_port_only(origin):
    with pytest.raises(ValueError):
        AllowRule(origin=origin)


def test_policy_configuration_round_trips_and_unknown_keys_are_refused():
    p = NetworkPolicy(rules=(SECTIONS, SAVE, STEP), relay_timeout_ms=5000)
    again = NetworkPolicy.from_dict(p.to_dict())
    assert again == p
    with pytest.raises(ValueError, match="unknown network policy keys"):
        NetworkPolicy.from_dict({"rules": [], "allow_everything": True})
    with pytest.raises(ValueError, match="unknown allow-rule keys"):
        NetworkPolicy.from_dict({"rules": [{"origin": BASE, "wildcard": True}]})


def test_origin_helper():
    assert origin_of("HTTPS://Portal.Example:8443/x?y") == "https://portal.example:8443"
    assert origin_of("blob:https://portal.example/abc") == ""
