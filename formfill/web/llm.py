"""Requirement C, optional LLM layer: a second opinion on which source fact, if any, answers a question that the deterministic
and evidence layers left in REVIEW.

OFF unless explicitly configured, and never automatic:

* it runs only when a reranker is passed in `MatcherConfig(reranker=...)` (or built by `reranker_from_env()`, which requires
  FORMFILL_LLM=anthropic AND FORMFILL_LLM_ALLOW_EXTERNAL=1, the informed confirmation that questionnaire text may be sent to
  Anthropic's API);
* by default it sends only the question text and the candidate key PATHS; the values themselves (company data) are sent only
  when FORMFILL_LLM_SEND_VALUES=1 / `send_values=True` is also set;
* its choice becomes a PROPOSAL for the reviewer (method "llm"), never an answer. It may only pick one of the candidates it was
  shown (anything else is ignored), and it may say that none fits;
* a refusal, an API error, a timeout, or output that does not match the schema changes nothing.

The `anthropic` package is optional (not a dependency of FormFiller); it is imported only when the Anthropic reranker is built.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

MODEL = "claude-opus-5-5"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = ("You help a person review answers to a business questionnaire. You are given one question and a numbered list of "
          "candidate facts from the company's own records (each is a key path, sometimes with its value). Pick the single "
          "candidate that directly answers the question, or none if no candidate states what is asked. A fact that only mentions "
          "a topic, belongs to another company (a subsidiary, affiliate or parent), or would require an inference does not answer "
          "it. Your choice is shown to a person as a suggestion; it is never entered automatically.")

SCHEMA = {
    "type": "object",
    "properties": {
        "candidate": {"type": ["integer", "null"], "description": "the id of the candidate that answers the question, or null"},
        "reason": {"type": "string", "description": "one short sentence for the reviewer"},
    },
    "required": ["candidate", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LLMChoice:
    candidate: int | None  # index into the candidates shown, or None ("no candidate answers it")
    reason: str


class Reranker(Protocol):
    name: str

    def choose(self, question: str, candidates: list[dict]) -> LLMChoice | None:
        """None when it could not decide (error, refusal, invalid output): the caller then changes nothing."""


class AnthropicReranker:
    """Claude, through the official `anthropic` SDK. `client` may be injected (tests use a fake; nothing is sent then)."""

    def __init__(self, client: Any = None, model: str = MODEL, send_values: bool = False, timeout_s: float = 30.0,
                 effort: str = "low"):
        if client is None:
            import anthropic  # optional dependency

            client = anthropic.Anthropic(timeout=timeout_s, max_retries=2)
        self.client = client
        self.model = model
        self.send_values = send_values
        self.effort = effort
        self.name = f"anthropic:{model}"

    def request(self, question: str, candidates: list[dict]) -> dict:
        shown = [{"id": i, "key": c["source"], **({"value": c.get("value")} if self.send_values else {})} for i, c in enumerate(candidates)]
        return dict(
            model=self.model,
            max_tokens=2048,  # a short JSON object; room for the model's own (adaptive) thinking at low effort
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps({"question": question, "candidates": shown}, ensure_ascii=False)}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=[_FALLBACK_BETA],
            fallbacks="default",  # a safety decline is retried server-side on a suitable model; a final refusal changes nothing
        )

    def choose(self, question: str, candidates: list[dict]) -> LLMChoice | None:
        if not candidates:
            return None
        try:
            response = self.client.beta.messages.create(**self.request(question, candidates))
        except Exception:  # noqa: BLE001 - any API, network or timeout error: no opinion
            return None
        if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
            return None
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        try:
            data = json.loads(text or "")
        except (TypeError, ValueError):
            return None
        pick = data.get("candidate") if isinstance(data, dict) else None
        if pick is not None and (isinstance(pick, bool) or not isinstance(pick, int) or not 0 <= pick < len(candidates)):
            return None  # not one of the candidates it was shown
        return LLMChoice(pick, str(data.get("reason", ""))[:300])


def reranker_from_env(env: Mapping[str, str] | None = None, client: Any = None) -> AnthropicReranker | None:
    """The Anthropic reranker when FORMFILL_LLM=anthropic and FORMFILL_LLM_ALLOW_EXTERNAL=1; else None (the default).
    FORMFILL_LLM=anthropic without the confirmation is refused rather than silently ignored."""
    if env is None:
        env = os.environ
    if env.get("FORMFILL_LLM", "").strip().lower() != "anthropic":
        return None
    if env.get("FORMFILL_LLM_ALLOW_EXTERNAL") != "1":
        raise ValueError("FORMFILL_LLM=anthropic sends questionnaire text to Anthropic's API; set FORMFILL_LLM_ALLOW_EXTERNAL=1 "
                         "to confirm that this is allowed for this questionnaire")
    return AnthropicReranker(client=client, model=env.get("FORMFILL_LLM_MODEL", MODEL),
                             send_values=env.get("FORMFILL_LLM_SEND_VALUES") == "1")
