"""Browser layer, step 1: discover the form's controls from the live DOM.

Why DOM extraction and not only the ARIA snapshot: Playwright's
`aria_snapshot()` gives role + accessible name (great for labels) but does
not expose `required`, `maxlength`, `pattern`, `min/max`, `name`, `id` or
option *values*. Those come from the DOM / HTML constraint-validation
properties. So: DOM extraction is the source of truth, accessibility
semantics (aria-labelledby, aria-label, <label>, <legend>) are used inside
the extractor for naming.

Each discovered control is tagged with a `data-ff-id` attribute so the
executor can find it again without brittle CSS paths. Re-discovery keeps
existing ids (needed for conditional fields that appear later).

Known limits (documented in docs/ARCHITECTURE_RESEARCH.md): closed shadow
DOM, open shadow DOM is not traversed by this extractor, cross-origin
iframes that Playwright cannot evaluate in are skipped, custom widgets
without native inputs or ARIA roles are not seen.
"""

from __future__ import annotations

from playwright.sync_api import Frame, Page

from formfill.web.models import Control, FormSchema, Option

_EXTRACT_JS = r"""
(frameIndex) => {
  const SKIP = new Set(['hidden','submit','button','reset','image','file','password']);
  const txt = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    try { return el.checkVisibility ? el.checkVisibility() : !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
    catch (e) { return true; }
  };
  const byIds = ids => (ids || '').split(/\s+/).filter(Boolean).map(i => document.getElementById(i)).filter(Boolean);
  const labelText = lab => { const c = lab.cloneNode(true); c.querySelectorAll('input,select,textarea,button').forEach(x => x.remove()); return txt(c); };
  const labelOf = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = byIds(lb).map(txt).join(' ').trim(); if (t) return t; }
    const al = el.getAttribute('aria-label'); if (al && al.trim()) return al.trim();
    if (el.labels && el.labels.length) { const t = Array.from(el.labels).map(labelText).join(' ').trim(); if (t) return t; }
    return '';
  };
  const groupLabel = el => {
    const rg = el.closest('[role=radiogroup],[role=group]');
    if (rg) { const t = labelOf(rg); if (t) return t; }
    const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend');
    return lg ? txt(lg) : '';
  };
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'));
  const sectionOf = el => {
    const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend');
    if (lg && !el.matches('input[type=radio],input[type=checkbox]')) return txt(lg);
    let cur = null;
    for (const h of headings) { if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) cur = h; else break; }
    return cur ? txt(cur) : '';
  };
  const formIndex = f => f ? Array.from(document.forms).indexOf(f) : -1;

  let counter = 0;
  document.querySelectorAll('[data-ff-id]').forEach(e => { const m = /c(\d+)$/.exec(e.dataset.ffId); if (m) counter = Math.max(counter, +m[1]); });

  const els = Array.from(document.querySelectorAll('input,select,textarea')).filter(e => !SKIP.has((e.type || '').toLowerCase()));
  const seen = new Set(); const out = [];
  for (const el of els) {
    const type = (el.type || '').toLowerCase(); const tag = el.tagName.toLowerCase();
    let members = [el];
    if ((type === 'radio' || type === 'checkbox') && el.name) {
      const key = type + '|' + el.name + '|' + formIndex(el.form);
      if (seen.has(key)) continue;
      seen.add(key);
      members = els.filter(x => x.type === el.type && x.name === el.name && x.form === el.form);
    }
    let id = members[0].dataset.ffId;
    if (!id) { counter += 1; id = 'f' + frameIndex + '-c' + counter; }
    members.forEach(m => { m.dataset.ffId = id; });

    let kind, label, options = [], value = null;
    if (tag === 'textarea') { kind = 'textarea'; label = labelOf(el); value = el.value; }
    else if (tag === 'select') {
      kind = el.multiple ? 'multiselect' : 'select'; label = labelOf(el);
      options = Array.from(el.options).filter(o => !o.disabled && o.value !== '').map(o => ({ value: o.value, label: txt(o) }));
      value = el.multiple ? Array.from(el.selectedOptions).map(o => o.value) : el.value;
    } else if (type === 'radio') {
      kind = 'radio'; label = groupLabel(el) || '';
      options = members.map(m => ({ value: m.value, label: labelOf(m) || m.value }));
      const c = members.find(m => m.checked); value = c ? c.value : null;
    } else if (type === 'checkbox') {
      if (members.length > 1) {
        kind = 'checkbox_group'; label = groupLabel(el) || '';
        options = members.map(m => ({ value: m.value, label: labelOf(m) || m.value }));
        value = members.filter(m => m.checked).map(m => m.value);
      } else { kind = 'checkbox'; label = labelOf(el); value = el.checked; }
    } else {
      kind = ['number','range'].includes(type) ? 'number' : (['date','email','url','tel'].includes(type) ? type : (['text','search',''].includes(type) ? 'text' : type));
      label = labelOf(el); value = el.value;
    }
    if (!label) label = el.placeholder || el.title || el.name || el.id || '';
    const num = a => { const v = el.getAttribute(a); return v === null || v === '' ? null : Number(v); };
    out.push({
      control_id: id, kind, label, name: el.name || null, html_id: el.id || null,
      help_text: byIds(el.getAttribute('aria-describedby')).map(txt).join(' ').trim(),
      section: sectionOf(el), placeholder: el.getAttribute('placeholder') || '',
      required: members.some(m => m.required || m.getAttribute('aria-required') === 'true'),
      visible: members.some(visible), disabled: members.every(m => m.disabled),
      options, min: el.getAttribute('min'), max: el.getAttribute('max'), step: el.getAttribute('step'),
      minlength: num('minlength'), maxlength: num('maxlength'), pattern: el.getAttribute('pattern'),
      value, frame_index: frameIndex,
    });
  }
  return out;
}
"""


def _extract(frame: Frame, index: int) -> list[Control]:
    try:
        raw = frame.evaluate(_EXTRACT_JS, index)
    except Exception:  # detached / inaccessible frame
        return []
    controls = []
    for r in raw:
        r["options"] = [Option(**o) for o in r["options"]]
        controls.append(Control(**r))
    return controls


def discover(page: Page) -> FormSchema:
    """Return every fillable control in the page and its same-process iframes,
    in document order. Hidden controls are included with `visible=False` so
    callers can tell "not asked" from "not present"."""
    controls: list[Control] = []
    for i, frame in enumerate(page.frames):
        controls.extend(_extract(frame, i))
    return FormSchema(url=page.url, title=page.title(), controls=controls)
