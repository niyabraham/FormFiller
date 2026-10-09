"""Reasoning layer, step 1: turn each discovered control into a Question --
what is being asked, what type of answer is expected, and what shape it has.

MVP approach is deterministic: the expected type comes from the control
itself (an <input type=date> asks for a date no matter how the label is
worded), and the "concept" is the normalised token set of the label.
`semantic_type` is deliberately left empty: inventing a hand-written
ontology (employee_count, ...) is not justified until retrieval is shown to
need it; a classifier or LLM can fill it later without changing callers.
"""

from __future__ import annotations

import re

from formfill.web.models import Control, FormSchema, Question
from formfill.web.tokens import tokenize

_EXPECTED = {
    "text": "string", "textarea": "string", "number": "number", "date": "date",
    "email": "email", "url": "url", "tel": "phone", "checkbox": "boolean",
    "select": "choice", "radio": "choice", "multiselect": "multi_choice",
    "checkbox_group": "multi_choice",
}
_MODE = {
    "textarea": "narrative", "checkbox": "boolean", "select": "single_choice",
    "radio": "single_choice", "multiselect": "multi_value", "checkbox_group": "multi_value",
}


def clean_question_text(label: str) -> str:
    text = re.sub(r"\s+", " ", label).strip()
    text = re.sub(r"\s*\*+\s*$", "", text)  # trailing required-asterisk
    text = re.sub(r"\s*\((required|optional)\)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip(" :")


_ENUMERATOR = re.compile(r"^\s*(?:[A-Za-z]\.\d+(?:\.\d+)*|\d+(?:\.\d+)*)[.):]?\s+(?=\S)|^\s*[A-Za-z]\d+\.\s+(?=\S)")
_DECORATION = re.compile(r"\s*[\[(]\s*(?:optional|required)\s*[\])]\s*|\s*[-\u2013\u2014:]\s*(?:optional|required)\s*$|^\s*(?:optional|required)\s*[-\u2013\u2014:]\s*", re.IGNORECASE)


def concept_text(text: str) -> str:
    """Question text minus form furniture that is not part of the question: leading
    enumerators ("C.3", "1.2.1.") and optional/required decorations ("Phone - optional",
    "Optional: Phone"). "Is MFA optional?" is a question and is left alone."""
    text = _ENUMERATOR.sub("", text, count=1)
    return _DECORATION.sub(" ", text).strip()


def understand_control(control: Control) -> Question:
    text = clean_question_text(control.label) or control.name or control.control_id
    return Question(
        question_id=control.control_id,
        text=text,
        control=control,
        expected_type=_EXPECTED.get(control.kind, "string"),
        answer_mode=_MODE.get(control.kind, "single_value"),
        concept_tokens=tokenize(concept_text(text)),
    )


def understand(controls: list[Control] | FormSchema) -> list[Question]:
    items = controls.controls if isinstance(controls, FormSchema) else controls
    return [understand_control(c) for c in items]
