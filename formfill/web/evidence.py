"""Requirement C: evidence-based validation. A candidate value is an answer only if the source fact *states* what the question
asks. Each check either confirms the answer or sends the question to REVIEW with the reason and the facts involved.

1. Claims of certification / compliance / authorisation of a named standard ("Are you SOC 2 certified?", "Are you GDPR
   compliant?") are decided by STATUS EVIDENCE only: a fact that states the status (`soc2_certified: true`,
   `certifications.soc2.status: "certified"`, `hipaa_compliant: false`). A fact that only mentions the standard
   (`soc2_controls_mapped`, `regulations_in_scope: ["GDPR"]`, a readiness or gap assessment) is not evidence; an in-progress,
   planned, pending, or expired status is not "yes"; facts that disagree are a conflict. A fact under a subsidiary, affiliate
   or parent the question does not name is skipped (formfill.web.retrieve.foreign_entity).
2. Conflicts for ordinary answers: another fact about the same measure with a different value (`password_min_length: 12` and
   `password_policy.min_length: 8`), or, for a "yes", a status of the same subject that says draft / planned / in progress.

Everything here is deterministic and reads only the source JSON (the authoritative knowledge base). Similar wording is never
treated as proof that a fact is true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from formfill.web.models import Candidate, Question
from formfill.web.retrieve import Leaf, foreign_entity
from formfill.web.tokens import tokenize

STANDARDS = frozenset({"soc1", "soc2", "iso27001", "iso27017", "iso27018", "iso27701", "iso22301", "iso9001", "iso14001", "iso20000",
                       "pcidss", "hipaa", "gdpr", "ccpa", "cpra", "fedramp", "cyberessentials", "tisax", "hitrust", "sox", "ferpa", "coppa"})
CLAIM_WORDS = frozenset({"certified", "certification", "certificate", "compliant", "compliance", "accredited", "accreditation",
                         "authorized", "authorised", "authorization", "authorisation", "attested", "attestation", "audited",
                         "report", "registered"})
# Key words, in the token form tokens.tokenize produces for keys and questions alike ("status" becomes "statu").
_CLAIM_KEYS = frozenset(tokenize("certified compliant accredited authorized authorised attested registered"))
_STATUS_KEYS = frozenset(tokenize("status state stage"))
_UNCERTAIN_KEYS = frozenset(tokenize("progress planned pending readiness gap draft scheduled underway target roadmap"))
# Containers whose children are statuses: `certifications.iso_27001: true` states a certification as plainly as `iso27001_certified`.
_CLAIM_CONTAINERS = frozenset(tokenize("certifications certified accreditations attestations compliance"))
_TYPES = frozenset({"type1", "type2"})
_AFFIRMATIVE = {"yes", "true", "y", "certified", "compliant", "accredited", "authorized", "authorised", "attested", "active", "valid",
                "current", "granted", "achieved", "approved", "in place", "implemented", "registered"}
_NEGATIVE = {"no", "false", "n", "not certified", "non compliant", "noncompliant", "not compliant", "expired", "lapsed", "revoked",
             "withdrawn", "suspended", "none", "not applicable"}
_UNCERTAIN = ("progress", "planned", "plan to", "pending", "draft", "readiness", "gap", "scheduled", "underway", "partial", "not started",
              "applying", "applied", "preparing", "in review", "under review", "target", "roadmap", "aligned", "mapped")
# Words that name the kind of thing a fact is, not the subject it is about (subject of "incident_response_plan" = incident response)
_GENERIC = frozenset(tokenize("plan policy process procedure program programme documented document formal maintain place require "
                               "enforced enforce status state stage all employee"))
CONFLICT_MIN_SCORE = 0.45  # a rival fact this relevant that disagrees is a contradiction, not noise (dev set, see docs/MATCHING.md)
# Path words that only say where a fact is filed, not what it is: two keys that differ only in these (and in words the question
# itself uses) are the same fact stored twice. Any other difference (billing vs headquarters, start vs end, employer's vs public
# liability, a list of locations vs the total) makes them different facts, which are never a contradiction.
_CONTAINERS = frozenset(tokenize("security infosec policy policies governance compliance privacy operations operation it settings "
                                 "general details detail info information profile data hr people company organisation organization "
                                 "org controls control program programme standards standard"))


def status_word(value: Any) -> bool | None | str:
    """True / False for a stated status, "uncertain" for in-progress style values, None when it is not a status at all."""
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    v = " ".join(value.casefold().replace("-", " ").replace("_", " ").split())
    if v in _AFFIRMATIVE:
        return True
    if v in _NEGATIVE:
        return False
    if any(u in v for u in _UNCERTAIN):
        return "uncertain"
    return None


@dataclass
class ClaimVerdict:
    """The outcome for a claim question. `answer` is True/False when the status evidence is clear, else None (REVIEW)."""

    standards: list[str]
    answer: bool | None
    reason: str
    evidence: list[dict] = field(default_factory=list)  # {"source": path, "value": ..., "reads_as": ...}
    conflicts: list[dict] = field(default_factory=list)

    @property
    def source(self) -> str | None:
        return self.evidence[0]["source"] if self.evidence else None


def _yes_no_capable(question: Question) -> bool:
    c = question.control
    if c.kind == "checkbox":
        return True
    vals = {(o.label or "").strip().casefold() for o in c.options} | {(o.value or "").strip().casefold() for o in c.options}
    return c.kind in ("radio", "select") and bool(vals & {"yes", "true", "y"}) and bool(vals & {"no", "false", "n"})


def claim_standards(question: Question) -> list[str]:
    """Standards a yes/no question asks a certification/compliance claim about ([] when it is not such a question)."""
    q = set(question.concept_tokens)
    stds = sorted(q & STANDARDS)
    if stds and q & CLAIM_WORDS and _yes_no_capable(question):
        return stds
    return []


def _siblings(leaves: list[Leaf]) -> dict[tuple[str, ...], list[Leaf]]:
    by_parent: dict[tuple[str, ...], list[Leaf]] = {}
    for leaf in leaves:
        by_parent.setdefault(tuple(leaf.path.split(".")[:-1]), []).append(leaf)
    return by_parent


def _scope_tokens(leaf: Leaf, siblings: list[Leaf]) -> set[str]:
    """Path tokens plus the words of short sibling values (`type: "Type 2"` beside `status`)."""
    toks = set(leaf.leaf_tokens | leaf.parent_tokens)
    for s in siblings:
        if s is not leaf and isinstance(s.value, str) and len(s.value) <= 40 and s.leaf_tokens & {"type", "kind", "level", "name", "standard", "framework"}:
            toks |= set(tokenize(s.value))
    return toks


def assess_claim(question: Question, leaves: list[Leaf]) -> ClaimVerdict | None:
    """None when the question is not a certification/compliance claim; else the verdict from status evidence only."""
    stds = claim_standards(question)
    if not stds:
        return None
    q = set(question.concept_tokens)
    section = set(tokenize(question.control.section))
    asked_type = q & _TYPES
    by_parent = _siblings(leaves)
    evidence: list[dict] = []
    mentions: list[str] = []
    for leaf in leaves:
        sibs = by_parent.get(tuple(leaf.path.split(".")[:-1]), [])
        scope = _scope_tokens(leaf, sibs)
        values = leaf.value if isinstance(leaf.value, list) else [leaf.value]
        mentioned_in_value = any(isinstance(v, str) and set(tokenize(v)) & set(stds) for v in values)
        if not set(stds) <= scope:
            if mentioned_in_value:
                mentions.append(leaf.path)
            continue
        if foreign_entity(leaf, q, section):
            mentions.append(f"{leaf.path} (belongs to another entity)")
            continue
        if asked_type and (scope & _TYPES) and not asked_type <= scope:
            mentions.append(f"{leaf.path} (a different report type)")
            continue
        keys = leaf.leaf_tokens
        if keys & _CLAIM_KEYS:
            reads = status_word(leaf.value)
            reads = "uncertain" if reads is None else reads
        elif keys & _STATUS_KEYS:
            reads = status_word(leaf.value)
            if reads is None:
                mentions.append(leaf.path)
                continue
        elif leaf.parent_tokens & _CLAIM_CONTAINERS and (isinstance(leaf.value, bool) or status_word(leaf.value) is not None):
            reads = status_word(leaf.value)
        elif keys & _UNCERTAIN_KEYS and leaf.value not in (False, None, "", "no"):
            reads = "uncertain"
        else:
            mentions.append(leaf.path)
            continue
        if asked_type and not (scope & _TYPES):
            reads = "uncertain" if reads is True else reads  # "certified" without saying which SOC 2 type is not a Type II answer
        evidence.append({"source": leaf.path, "value": leaf.value, "reads_as": reads})

    label = "/".join(s.upper() for s in stds)
    if not evidence:
        if mentions:
            return ClaimVerdict(stds, None, f"the source mentions {label} ({', '.join(mentions[:3])}) but does not state the "
                                            "organisation's certification or compliance status; a mention is not evidence")
        return ClaimVerdict(stds, None, f"no evidence about {label} status in the source data")
    readings = {str(e["reads_as"]) for e in evidence}
    if "uncertain" in readings:
        e = next(x for x in evidence if x["reads_as"] == "uncertain")
        return ClaimVerdict(stds, None, f"{e['source']!r} = {e['value']!r} is not a completed {label} status (in progress, planned, "
                                        "or not clearly stated)", evidence)
    if readings == {"True", "False"}:
        return ClaimVerdict(stds, None, f"the source contradicts itself about {label}", evidence,
                            conflicts=[{"source": e["source"], "value": e["value"]} for e in evidence])
    answer = readings == {"True"}
    return ClaimVerdict(stds, answer, f"stated {label} status: " + "; ".join(f"{e['source']} = {e['value']!r}" for e in evidence), evidence)


def _norm(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v).strip().casefold()
    try:
        f = float(s.replace(",", ""))
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return s


def _kind(v: Any) -> str:
    """Only values of the same kind can contradict each other (a count and a name are different facts)."""
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, list):
        return "list"
    try:
        float(str(v).replace(",", ""))
        return "number"
    except ValueError:
        return "text"


def find_conflicts(question: Question, top: Candidate, cands: list[Candidate], leaves: list[Leaf]) -> list[dict]:
    """Facts that contradict the chosen candidate (see the module docstring, check 2)."""
    by_path = {leaf.path: leaf for leaf in leaves}
    top_leaf = by_path.get(top.path)
    if top_leaf is None:
        return []
    q = set(question.concept_tokens)
    hit_top = q & (top_leaf.leaf_tokens | top_leaf.parent_tokens)
    out: list[dict] = []
    for r in cands[1:]:
        leaf = by_path.get(r.path)
        if leaf is None or r.score < CONFLICT_MIN_SCORE or r.foreign_entity:
            continue
        shared = hit_top & (leaf.leaf_tokens | leaf.parent_tokens)
        differs = ((leaf.leaf_tokens | leaf.parent_tokens) ^ (top_leaf.leaf_tokens | top_leaf.parent_tokens)) - q - _CONTAINERS
        if differs or leaf.item_id != top_leaf.item_id and (leaf.item_id or top_leaf.item_id):
            continue  # a different fact (or another list item), not the same one said twice
        if len(shared) >= 2 and _kind(r.value) == _kind(top.value) and _norm(r.value) != _norm(top.value):
            out.append({"source": r.path, "value": r.value, "why": f"also about {sorted(shared)} but says {r.value!r}"})
    affirmative = top.value is True or (isinstance(top.value, str) and status_word(top.value) is True)
    subject = hit_top - _GENERIC
    if affirmative and subject:
        for leaf in leaves:
            if leaf.path == top.path or not (leaf.leaf_tokens & _STATUS_KEYS):
                continue
            if subject <= (leaf.leaf_tokens | leaf.parent_tokens) and status_word(leaf.value) in ("uncertain", False):
                out.append({"source": leaf.path, "value": leaf.value, "why": f"the status of {' '.join(sorted(subject))} is {leaf.value!r}"})
    return out
