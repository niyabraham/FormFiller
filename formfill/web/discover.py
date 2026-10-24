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

Known limits (documented in docs/ARCHITECTURE_RESEARCH.md and
docs/PHASE3C_SPA_EVALUATION.md): closed shadow DOM is not readable (reported
as an `opaque_custom_element` note), cross-origin iframes that Playwright
cannot evaluate in are skipped, custom widgets without native inputs or ARIA
roles are not seen. Open shadow roots and ARIA comboboxes are traversed.
"""

from __future__ import annotations

from playwright.sync_api import Frame, Page

from formfill.web.models import Control, FormSchema, Option

_EXTRACT_JS = r"""
(frameIndex) => {
  const SKIP = new Set(['hidden','submit','button','reset','image','file','password']);
  const txt = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  // aria-hidden="true" / inert: the page itself says nobody is meant to use this subtree (a scaled preview thumbnail of the
  // form, a CSS-only menu toggle, a backgrounded modal). Such a control is not a question. Walks the composed tree, so a
  // control inside an open shadow root is judged by the ancestors of its host as well.
  const hiddenByPage = el => {
    for (let n = el; n; n = n.parentElement || (n.getRootNode && n.getRootNode().host)) {
      if (n.nodeType === 1 && (n.getAttribute('aria-hidden') === 'true' || n.hasAttribute('inert'))) return true;
    }
    return false;
  };
  const visible = el => {
    try {
      if (hiddenByPage(el)) return false;
      return el.checkVisibility ? el.checkVisibility() : !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    } catch (e) { return true; }
  };
  const byIds = (ids, el) => { const root = (el && el.getRootNode && el.getRootNode().getElementById) ? el.getRootNode() : document; return (ids || '').split(/\s+/).filter(Boolean).map(i => root.getElementById(i)).filter(Boolean); };
  const labelText = lab => { const c = lab.cloneNode(true); c.querySelectorAll('input,select,textarea,button').forEach(x => x.remove()); return txt(c); };
  const labelOf = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = byIds(lb, el).map(txt).join(' ').trim(); if (t) return t; }
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
    let cur = null; const rn = el.getRootNode(); const anchor = rn && rn.host ? rn.host : el;  // a control inside a shadow root sits where its host sits
    for (const h of headings) { if (h.compareDocumentPosition(anchor) & Node.DOCUMENT_POSITION_FOLLOWING) cur = h; else break; }
    return cur ? txt(cur) : '';
  };
  const formIndex = f => f ? Array.from(document.forms).indexOf(f) : -1;

  // ids must stay unique for the life of the page: a single-page app that unmounts one step and mounts the next
  // would otherwise hand the same id to a different control.
  const all = [];
  const walk = root => { for (const e of root.children) { all.push(e); if (e.shadowRoot) walk(e.shadowRoot); walk(e); } };  // open shadow roots, in document order
  walk(document);
  let counter = window.__ffCounter || 0;
  all.forEach(e => { const m = e.dataset && /c(\d+)$/.exec(e.dataset.ffId || ''); if (m) counter = Math.max(counter, +m[1]); });

  const isCombo = e => e.getAttribute('role') === 'combobox';
  const els = all.filter(e => (e.matches('input,select,textarea') && !SKIP.has((e.type || '').toLowerCase())) || (isCombo(e) && !e.matches('select,textarea')));
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
    if (isCombo(el) && tag !== 'select') {  // ARIA combobox: options live in a popup, so the answer is picked, not typed
      kind = 'combobox'; label = labelOf(el); value = tag === 'input' ? el.value : txt(el);
    } else if (tag === 'textarea') { kind = 'textarea'; label = labelOf(el); value = el.value; }
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
    // A bare format hint ("YYYY-MM-DD", "dd/mm/yyyy") describes how to write the answer, not what is asked: it must not
    // outrank the control's own name/id as its identity. It is used as a label only when nothing else exists.
    const hint = /^[ymdhs]{1,4}([\/.\-: ][ymdhs]{1,4}){1,3}$/i.test((el.placeholder || '').trim());
    if (!label) label = (hint ? '' : el.placeholder) || el.title || el.name || el.id || el.placeholder || '';
    const num = a => { const v = el.getAttribute(a); return v === null || v === '' ? null : Number(v); };
    out.push({
      control_id: id, kind, label, name: el.name || null, html_id: el.id || null,
      help_text: byIds(el.getAttribute('aria-describedby'), el).map(txt).join(' ').trim(),
      section: sectionOf(el), placeholder: el.getAttribute('placeholder') || '',
      required: members.some(m => m.required || m.getAttribute('aria-required') === 'true'),
      visible: members.some(visible), disabled: members.every(m => m.disabled || m.getAttribute('aria-disabled') === 'true'),
      options, min: el.getAttribute('min'), max: el.getAttribute('max'), step: el.getAttribute('step'),
      minlength: num('minlength'), maxlength: num('maxlength'), pattern: el.getAttribute('pattern'),
      value, frame_index: frameIndex,
    });
  }
  window.__ffCounter = counter;
  return out;
}
"""

# Elements that look like encapsulated widgets whose inside we cannot read (a custom element with no open shadow
# root and no light children: closed shadow root, or an empty component). Reported, never guessed at.
_OPAQUE_JS = """
() => {
  const out = []; const walk = root => { for (const e of root.children) {
    if (e.tagName.includes('-') && !e.shadowRoot && !e.children.length && !(e.textContent || '').trim()) out.push(e.tagName.toLowerCase());
    if (e.shadowRoot) walk(e.shadowRoot); walk(e); } };
  walk(document); return out;
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
    callers can tell "not asked" from "not present". "Hidden" includes controls
    inside an `aria-hidden="true"` or `inert` subtree, which the page has marked
    as not for use (preview thumbnails, menu toggles): they are never questions."""
    controls: list[Control] = []
    notes: list[dict] = []
    for i, frame in enumerate(page.frames):
        controls.extend(_extract(frame, i))
        try:
            for tag in frame.evaluate(_OPAQUE_JS):
                notes.append({"kind": "opaque_custom_element", "frame_index": i, "element": tag,
                              "reason": "custom element exposes no readable shadow root (closed, or empty): its inner controls cannot be discovered"})
        except Exception:  # noqa: BLE001 - detached / inaccessible frame
            pass
    return FormSchema(url=page.url, title=page.title(), controls=controls, notes=notes)
