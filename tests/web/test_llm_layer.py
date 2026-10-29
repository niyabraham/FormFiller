"""Requirement C: the optional LLM layer. A fake client stands in for the Anthropic SDK: nothing is ever sent anywhere here."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from formfill.web.llm import MODEL, AnthropicReranker, reranker_from_env
from formfill.web.matching import MatcherConfig
from formfill.web.models import Control, Option
from formfill.web.plan import plan_question
from formfill.web.retrieve import index_source
from formfill.web.understand import understand_control

SOURCE = {"security": {"incident_response_plan": True, "siem_tool": "Fictional SIEM", "mfa_enforced": True},
          "company": {"subsidiaries": [{"soc2_certified": True}]}}


class FakeClient:
    """Records each request and answers with a canned response, like client.beta.messages.create would."""

    def __init__(self, text=None, stop_reason="end_turn", error=None):
        self.requests = []
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)])


def ask(question, client, kind="radio", **reranker_kw):
    options = [Option("yes", "Yes"), Option("no", "No")] if kind == "radio" else []
    c = Control(control_id="q", kind=kind, label=question, options=options)
    config = MatcherConfig(reranker=AnthropicReranker(client=client, **reranker_kw))
    return plan_question(understand_control(c), index_source(SOURCE), config)


def test_the_llm_layer_is_off_unless_explicitly_configured():
    assert reranker_from_env({}) is None
    assert reranker_from_env({"FORMFILL_LLM": "none"}) is None
    with pytest.raises(ValueError, match="FORMFILL_LLM_ALLOW_EXTERNAL=1"):
        reranker_from_env({"FORMFILL_LLM": "anthropic"})
    built = reranker_from_env({"FORMFILL_LLM": "anthropic", "FORMFILL_LLM_ALLOW_EXTERNAL": "1"}, client=FakeClient("{}"))
    assert built.model == MODEL and built.send_values is False
    assert MatcherConfig().reranker is None  # the default matcher never calls an LLM


def test_an_llm_choice_is_only_ever_a_proposal_for_a_reviewer():
    fake = FakeClient(json.dumps({"candidate": 0, "reason": "the plan exists"}))
    item = ask("Is there a written plan for handling security incidents?", fake)
    assert item.status == "REVIEW" and item.answer is None
    assert item.method == "llm" and item.proposed_answer == "yes" and item.confidence_category == "low"
    assert "not entered automatically" in item.reason


def test_by_default_only_key_paths_are_sent_never_values_and_the_request_is_well_formed():
    fake = FakeClient(json.dumps({"candidate": None, "reason": "none fits"}))
    ask("Which SIEM product do you use?", fake, kind="text")
    req = fake.requests[0]
    sent = json.loads(req["messages"][0]["content"])
    assert all(set(c) == {"id", "key"} for c in sent["candidates"])
    assert "Fictional SIEM" not in json.dumps(req)
    assert req["model"] == "claude-opus-5-5" and req["output_config"]["format"]["type"] == "json_schema"
    assert req["output_config"]["effort"] == "low" and req["fallbacks"] == "default"
    assert req["betas"] == ["server-side-fallback-2026-07-01"] and "stream" not in req
    with_values = FakeClient(json.dumps({"candidate": None, "reason": "none"}))
    ask("Which SIEM product do you use?", with_values, kind="text", send_values=True)
    assert "Fictional SIEM" in with_values.requests[0]["messages"][0]["content"]


@pytest.mark.parametrize("fake", [
    FakeClient(json.dumps({"candidate": 7, "reason": "invented"})),  # not one of the candidates shown
    FakeClient("not json"),
    FakeClient(json.dumps({"candidate": 0, "reason": "x"}), stop_reason="refusal"),
    FakeClient(error=TimeoutError("timed out")),
])
def test_an_unusable_llm_response_changes_nothing(fake):
    plain = plan_question(understand_control(Control(control_id="q", kind="text", label="Which SIEM product do you use?")),
                          index_source(SOURCE))
    item = ask("Which SIEM product do you use?", fake, kind="text")
    assert (item.status, item.proposed_answer, item.method) == (plain.status, plain.proposed_answer, plain.method)


def test_the_llm_never_sees_another_entitys_fact_or_an_attestation():
    fake = FakeClient(json.dumps({"candidate": 0, "reason": "x"}))
    item = ask("Are you SOC 2 certified?", fake)  # a claim: decided by stated status only
    assert item.status == "REVIEW" and fake.requests == []
    att = Control(control_id="a", kind="checkbox", label="I agree to the terms and conditions")
    assert plan_question(understand_control(att), index_source(SOURCE), MatcherConfig(reranker=AnthropicReranker(client=fake))).proposed_answer is None
    assert fake.requests == []
