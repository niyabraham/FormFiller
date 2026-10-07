"""Data model for the web-form pipeline.

Three layers, deliberately separate (see docs/ARCHITECTURE_RESEARCH.md):

    FormSchema / Control   what the page *contains*      (browser layer output)
    Question               what each control *asks*       (understanding layer)
    AnswerPlanItem         what should be *entered*       (reasoning layer output)

Nothing in the reasoning layer imports Playwright; it only sees these objects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Control kinds produced by discovery.
TEXT_KINDS = {"text", "textarea", "email", "url", "tel", "number", "date"}
CHOICE_KINDS = {"select", "radio"}
MULTI_KINDS = {"multiselect", "checkbox_group"}


@dataclass
class Option:
    value: str
    label: str


@dataclass
class Control:
    control_id: str  # stable id; also written to the DOM as data-ff-id
    kind: str  # text|textarea|email|url|tel|number|date|select|multiselect|radio|checkbox|checkbox_group|<other input type>
    label: str  # the question text as the user sees it
    name: str | None = None
    html_id: str | None = None
    help_text: str = ""
    section: str = ""
    placeholder: str = ""
    required: bool = False
    visible: bool = True
    disabled: bool = False
    options: list[Option] = field(default_factory=list)
    min: str | None = None
    max: str | None = None
    step: str | None = None
    minlength: int | None = None
    maxlength: int | None = None
    pattern: str | None = None
    value: Any = None  # value present on the page at discovery time
    frame_index: int = 0


@dataclass
class FormSchema:
    url: str
    title: str
    controls: list[Control]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Question:
    question_id: str
    text: str
    control: Control
    expected_type: str  # string|number|date|email|url|phone|boolean|choice|multi_choice
    answer_mode: str  # single_value|narrative|boolean|single_choice|multi_value
    concept_tokens: list[str] = field(default_factory=list)
    semantic_type: str | None = None  # reserved for a later classifier/LLM stage


@dataclass
class Candidate:
    path: str
    value: Any
    score: float


@dataclass
class AnswerPlanItem:
    question_id: str
    question: str
    field_type: str
    required: bool
    status: str  # "ANSWER" | "REVIEW"
    source: str | None = None  # dotted JSON path the answer came from
    raw_value: Any = None  # value as found in the JSON
    answer: Any = None  # value after validation/transformation -- what the browser will enter
    confidence: float = 0.0
    reason: str | None = None  # why REVIEW
    alternatives: list[dict] = field(default_factory=list)  # other candidates, for the reviewer

    def to_dict(self) -> dict:
        return asdict(self)
