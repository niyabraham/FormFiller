"""Renderer for the Phase 2 RFI benchmark.

A benchmark case is declared once as a list of `Q` objects (what the form
shows + what the *correct* outcome is). This module turns that declaration
into (a) a local HTML fixture and (b) a ground-truth record.

Ground truth is written from the correct answer to the question, never from
what the pipeline happens to do. The evaluator reads only the generated
files, so it cannot see this module.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Any

YN = [("yes", "Yes"), ("no", "No")]

CUSTOM_KINDS = {"custom_radio", "custom_combobox", "custom_switch", "custom_editable", "shadow_text"}


@dataclass
class Q:
    # ---- what the page shows
    name: str  # html name; also the truth key
    label: str  # the question text exactly as a person reads it
    kind: str = "text"  # text|number|date|email|url|tel|textarea|select|multiselect|radio|checkbox|checkbox_group|file|custom_*
    options: list = field(default_factory=list)  # [(value, label)]
    required: bool = False
    style: str = "label_for"  # how the label is attached (see _wrap)
    attrs: dict = field(default_factory=dict)  # html constraint attributes
    section: str | None = None  # <h2> emitted when it changes
    when: tuple | None = None  # (trigger_name, trigger_value): hidden until then
    enable_when: tuple | None = None  # (trigger_name, trigger_value): disabled until then
    step: int = 1  # multi-step forms: panel number
    # ---- ground truth (the correct outcome)
    expect: str = "REVIEW"  # ANSWER | REVIEW | ABSENT (hidden control that must stay unasked)
    answer: Any = None  # what the control should hold afterwards
    source: str | None = None  # JSON path the answer comes from
    tags: list = field(default_factory=list)
    trap: str | None = None  # negation | compound | polarity ... (question-understanding hazard)
    invalid_source: str | None = None  # JSON path whose value violates this control's constraints
    note: str = ""  # why this is the correct outcome


def A(name, label, kind="text", answer=None, source=None, **kw):
    return Q(name=name, label=label, kind=kind, expect="ANSWER", answer=answer, source=source, **kw)


def R(name, label, kind="text", **kw):
    return Q(name=name, label=label, kind=kind, expect="REVIEW", **kw)


def H(name, label, kind="text", **kw):
    return Q(name=name, label=label, kind=kind, expect="ABSENT", **kw)


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


# --------------------------------------------------------------------- controls


def _attr_string(q: Q, extra: str = "") -> str:
    parts = [f'name="{esc(q.name)}"']
    if q.required:
        parts.append("required")
    if q.enable_when:
        parts.append(f'disabled data-enable-when="{esc(q.enable_when[0])}" data-enable-eq="{esc(q.enable_when[1])}"')
    for k, v in q.attrs.items():
        parts.append(k if v is True else f'{k}="{esc(v)}"')
    if extra:
        parts.append(extra)
    return " ".join(parts)


def _control(q: Q, extra: str = "") -> str:
    a = _attr_string(q, extra)
    if q.kind == "textarea":
        return f"<textarea {a} rows=3></textarea>"
    if q.kind in ("select", "multiselect"):
        multi = " multiple" if q.kind == "multiselect" else ""
        first = "" if multi else '<option value="">Select...</option>'
        opts = "" if "data-async" in q.attrs else "".join(f'<option value="{esc(v)}">{esc(t)}</option>' for v, t in q.options)
        return f"<select {a}{multi}>{first}{opts}</select>"
    return f'<input type="{q.kind}" {a}>'


def _group(q: Q) -> str:
    kind = "radio" if q.kind == "radio" else "checkbox"
    req = " required" if (q.required and kind == "radio") else ""
    boxes = "".join(
        f'<label class="opt"><input type="{kind}" name="{esc(q.name)}" value="{esc(v)}"{req}> {esc(t)}</label>'
        for v, t in q.options
    )
    if q.style == "div_label":  # question is plain text above the options, no legend
        return f'<div class="q">{esc(q.label)}</div><div>{boxes}</div>'
    if q.style == "aria_group":
        return f'<div role="radiogroup" aria-label="{esc(q.label)}">{boxes}</div>'
    return f"<fieldset><legend>{esc(q.label)}</legend>{boxes}</fieldset>"


def _custom(q: Q) -> str:
    L = esc(q.label)
    if q.kind == "custom_radio":
        opts = "".join(f'<div role="radio" aria-checked="false" tabindex="0" class="fake">{esc(t)}</div>' for _, t in q.options)
        return f'<div role="radiogroup" aria-label="{L}" data-qname="{esc(q.name)}">{opts}</div>'
    if q.kind == "custom_combobox":
        return (f'<div role="combobox" aria-label="{L}" aria-expanded="false" tabindex="0" class="fake" '
                f'data-qname="{esc(q.name)}">Select...</div>')
    if q.kind == "custom_switch":
        return f'<button type="button" role="switch" aria-checked="false" aria-label="{L}" data-qname="{esc(q.name)}">Off</button>'
    if q.kind == "custom_editable":
        return (f'<div role="textbox" aria-label="{L}" aria-multiline="true" contenteditable="true" class="fake box" '
                f'data-qname="{esc(q.name)}"></div>')
    if q.kind == "shadow_text":
        return f'<acme-field label="{L}" qname="{esc(q.name)}"></acme-field>'
    raise ValueError(q.kind)


def render_question(q: Q, idx: int) -> str:
    cid = f"q{idx}"
    if q.kind in CUSTOM_KINDS:
        return f'<div class="row">{_custom(q)}</div>'
    if q.kind in ("radio", "checkbox_group"):
        return f'<div class="row">{_group(q)}</div>'
    if q.kind == "checkbox":
        a = _attr_string(q)
        return f'<div class="row"><label class="opt"><input type="checkbox" {a} value="yes"> {esc(q.label)}</label></div>'
    L = esc(q.label)
    st = q.style
    if st == "wrap":
        body = f"<label>{L} {_control(q)}</label>"
    elif st == "aria_label":
        body = _control(q, f'aria-label="{L}"')
    elif st == "aria_labelledby":
        body = f'<span id="{cid}_l">{L}</span>{_control(q, f"aria-labelledby={chr(34)}{cid}_l{chr(34)}")}'
    elif st == "placeholder":
        body = _control(q, f'placeholder="{L}"')
    elif st == "div_label":
        body = f'<div class="q">{L}</div>{_control(q)}'
    elif st == "table":
        body = f"<table><tr><td>{L}</td><td>{_control(q)}</td></tr></table>"
    elif st == "bad_for":  # label points at an id that does not exist (a common real-world bug)
        body = f'<label for="{cid}_missing">{L}</label>{_control(q, f"id={chr(34)}{cid}{chr(34)}")}'
    else:  # label_for
        body = f'<label for="{cid}">{L}</label>{_control(q, f"id={chr(34)}{cid}{chr(34)}")}'
    return f'<div class="row">{body}</div>'


# ------------------------------------------------------------------------ page

_CSS = """
body{font:15px system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#222}
h1{font-size:20px} h2{font-size:16px;margin-top:26px;border-bottom:1px solid #ccc}
.row{margin:12px 0} label,.q{display:block;font-weight:600;margin-bottom:4px}
label.opt{display:inline-block;font-weight:400;margin-right:14px} fieldset{border:1px solid #ccc}
input[type=text],input[type=email],input[type=url],input[type=tel],input[type=number],input[type=date],select,textarea{width:100%;box-sizing:border-box;padding:6px}
.fake{border:1px solid #888;padding:6px;margin:2px;display:inline-block;min-width:60px} .box{display:block;min-height:50px}
[hidden]{display:none!important} #msg{margin-top:14px;font-weight:600} .err{color:#b00020}
"""

_ENABLE_JS = """
function syncEnable(){document.querySelectorAll('[data-enable-when]').forEach(e=>{e.disabled=val(e.dataset.enableWhen)!==e.dataset.enableEq})}
document.addEventListener('change',syncEnable);document.addEventListener('input',syncEnable);syncEnable();
"""

_MASK_JS = """
document.querySelectorAll('input[data-mask]').forEach(i=>i.addEventListener('input',()=>{
 const d=i.value.replace(/\\D/g,'').slice(0,10);
 i.value=d.length>6?d.slice(0,3)+'-'+d.slice(3,6)+'-'+d.slice(6):d.length>3?d.slice(0,3)+'-'+d.slice(3):d}));
"""

_COND_JS = """
function val(n){const e=[...document.querySelectorAll('[name="'+n+'"]')];if(!e.length)return null;
 const t=e[0].type;if(t==='radio'){const c=e.find(x=>x.checked);return c?c.value:null}
 if(t==='checkbox')return e[0].checked?'yes':'no';return e[0].value}
function sync(){document.querySelectorAll('.cond').forEach(w=>{w.hidden=val(w.dataset.when)!==w.dataset.eq})}
document.addEventListener('change',sync);document.addEventListener('input',sync);sync();
"""

_STEP_JS = """
document.addEventListener('click',e=>{const b=e.target.closest('.next');if(!b)return;const n=b.dataset.next;
 let s=document.querySelector('section[data-step="'+n+'"]');
 if(!s){const t=document.getElementById('tpl'+n);s=document.createElement('section');s.dataset.step=n;
  s.appendChild(t.content.cloneNode(true));document.getElementById('steps').appendChild(s)}
 s.hidden=false});
"""

_SHADOW_JS = """
customElements.define('acme-field',class extends HTMLElement{connectedCallback(){
 const r=this.attachShadow({mode:'open'});r.innerHTML='<label>'+this.getAttribute('label')+
 '<input type="text" name="'+this.getAttribute('qname')+'"></label>'}});
"""

_SUBMIT_JS = {
    "success": "form.addEventListener('submit',e=>{e.preventDefault();msg.textContent='Thank you, your response was received'});",
    "reject": ("form.addEventListener('submit',e=>{e.preventDefault();msg.className='err';msg.setAttribute('role','alert');"
               "msg.textContent='Registration code already in use. Submission rejected.'});"),
    "delay": ("form.addEventListener('submit',e=>{e.preventDefault();msg.textContent='Submitting...';"
              "setTimeout(()=>{msg.textContent='Thank you, your response was received'},1200)});"),
}


def render_form(title: str, qs: list[Q], *, submit: str | None = None, dynamic_steps: set[int] = frozenset(),
                intro: str = "") -> str:
    steps = sorted({q.step for q in qs})
    multi = len(steps) > 1
    out: list[str] = []
    idx = 0
    last_section: str | None = None

    def emit(group: list[Q]) -> str:
        nonlocal idx, last_section
        chunk: list[str] = []
        for q in group:
            if q.section and q.section != last_section:
                chunk.append(f"<h2>{esc(q.section)}</h2>")
                last_section = q.section
            idx += 1
            block = render_question(q, idx)
            if q.when:
                block = (f'<div class="cond" data-when="{esc(q.when[0])}" data-eq="{esc(q.when[1])}" hidden>{block}</div>')
            chunk.append(block)
        return "\n".join(chunk)

    if not multi:
        out.append(emit(qs))
    else:
        out.append('<div id="steps">')
        for s in steps:
            body = emit([q for q in qs if q.step == s])
            nxt = (f'<button type="button" class="next" data-next="{s + 1}">Next</button>' if s != steps[-1] else "")
            if s in dynamic_steps:
                out.append(f'<template id="tpl{s}">{body}{nxt}</template>')
            else:
                hid = "" if s == steps[0] else " hidden"
                out.append(f'<section data-step="{s}"{hid}>{body}{nxt}</section>')
        out.append("</div>")

    action = ' action="thanks.html" method="get"' if submit == "navigate" else ""
    button = '<div class="row"><button type="submit">Submit</button></div><div id="msg"></div>' if submit else ""
    scripts = []
    if any(q.when for q in qs) or any(q.enable_when for q in qs):
        scripts.append(_COND_JS if any(q.when for q in qs) else _COND_JS.split("function sync()")[0])
    if any(q.enable_when for q in qs):
        scripts.append(_ENABLE_JS)
    if any("data-mask" in q.attrs for q in qs):
        scripts.append(_MASK_JS)
    async_sel = [(q.name, q.options) for q in qs if "data-async" in q.attrs]
    if async_sel:
        scripts.append("const ASYNC=" + json.dumps(async_sel) + ";setTimeout(()=>{for(const [n,o] of ASYNC){"
                       "const s=document.querySelector('[name=\"'+n+'\"]');for(const [v,t] of o){"
                       "const x=document.createElement('option');x.value=v;x.textContent=t;s.appendChild(x)}}},600);")
    if multi:
        scripts.append(_STEP_JS)
    if any(q.kind == "shadow_text" for q in qs):
        scripts.append(_SHADOW_JS)
    if submit in _SUBMIT_JS:
        scripts.append("const form=document.forms[0],msg=document.getElementById('msg');" + _SUBMIT_JS[submit])
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{esc(title)}</title><style>{_CSS}</style></head>"
            f"<body><h1>{esc(title)}</h1>{intro}<form{action}>\n" + "\n".join(out) + f"\n{button}</form>"
            f"<script>{''.join(scripts)}</script></body></html>")


def truth_record(case_id: str, description: str, source_style: str, qs: list[Q]) -> dict:
    items = []
    for q in qs:
        items.append({
            "control": q.name, "question": q.label, "kind": q.kind, "expect": q.expect,
            "answer": q.answer, "source": q.source, "tags": q.tags, "trap": q.trap,
            "invalid_source": q.invalid_source, "required": q.required,
            "when": list(q.when) if q.when else None, "enable_when": list(q.enable_when) if q.enable_when else None, "step": q.step, "note": q.note,
        })
    return {"case": case_id, "description": description, "source_style": source_style, "questions": items}
