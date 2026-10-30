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

import contextlib

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
  // Page furniture is not a question (RW-2): the site's own search / filter box. A control in a navigation landmark, outside any form,
  // that is a search-type box or the only fillable control in that landmark. A questionnaire placed in a side panel or header has a
  // form element or several controls, so it is still asked. <header>/<footer> are page landmarks only when not inside an
  // article/aside/main/nav/section.
  const LANDMARK = 'nav,header,footer,aside,[role=search],[role=navigation],[role=banner],[role=contentinfo],[role=complementary]';
  const pageFurniture = el => {
    try {
      if (el.form || el.closest('form,[role=form]')) return false;
      const lm = el.closest(LANDMARK);
      if (!lm) return false;
      if (lm.matches('header,footer') && !lm.hasAttribute('role') && lm.parentElement && lm.parentElement.closest('article,aside,main,nav,section')) return false;
      if ((el.type || '').toLowerCase() === 'search' || el.getAttribute('role') === 'searchbox' || lm.matches('[role=search]')) return true;
      return Array.from(lm.querySelectorAll('input,select,textarea')).filter(e => !SKIP.has((e.type || '').toLowerCase())).length === 1;
    } catch (e) { return false; }
  };
  const visible = el => {
    try {
      if (hiddenByPage(el) || pageFurniture(el)) return false;
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


# Visible controls this pipeline can neither fill nor verify. They are never touched; they are listed so a person sees them and so a
# run that left one behind cannot be reported as FILLED. Native text/select/radio/checkbox controls and ARIA comboboxes are handled by
# _EXTRACT_JS and are not repeated here.
_UNSUPPORTED_JS = r"""
(frameIndex) => {
  const txt = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const hiddenByPage = el => { for (let n = el; n; n = n.parentElement || (n.getRootNode && n.getRootNode().host)) {
    if (n.nodeType === 1 && (n.getAttribute('aria-hidden') === 'true' || n.hasAttribute('inert'))) return true; } return false; };
  const shown = el => { try { if (hiddenByPage(el)) return false;
    return el.checkVisibility ? el.checkVisibility() : !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); } catch (e) { return true; } };
  const all = []; const walk = root => { for (const e of root.children) { all.push(e); if (e.shadowRoot) walk(e.shadowRoot); walk(e); } };
  walk(document);
  const root = e => (e.getRootNode && e.getRootNode().getElementById) ? e.getRootNode() : document;
  const byIds = (ids, e) => (ids || '').split(/\s+/).filter(Boolean).map(i => root(e).getElementById(i)).filter(Boolean);
  const comboPopups = new Set(all.filter(e => e.getAttribute('role') === 'combobox').flatMap(e => byIds((e.getAttribute('aria-controls') || '') + ' ' + (e.getAttribute('aria-owns') || ''), e).map(x => x)));
  const label = e => {
    const lb = e.getAttribute('aria-labelledby'); if (lb) { const t = byIds(lb, e).map(txt).join(' ').trim(); if (t) return t; }
    const al = e.getAttribute('aria-label'); if (al && al.trim()) return al.trim();
    if (e.labels && e.labels.length) { const t = Array.from(e.labels).map(txt).join(' ').trim(); if (t) return t; }
    const lg = e.closest('fieldset') && e.closest('fieldset').querySelector('legend'); if (lg && txt(lg)) return txt(lg);
    const wl = e.closest('label'); if (wl && txt(wl)) return txt(wl);
    const prev = e.previousElementSibling; if (prev && /^(LABEL|LEGEND|H[1-6]|P|SPAN|DIV)$/.test(prev.tagName) && txt(prev) && txt(prev).length <= 120) return txt(prev);
    return e.getAttribute('title') || e.getAttribute('data-placeholder') || e.getAttribute('placeholder') || e.name || e.id || '';
  };
  const REQ = /\*|\(required\)|\brequired\b/i;
  const found = []; const flagged = [];
  const add = (e, kind, reason) => {
    if (flagged.some(f => f === e || f.contains(e))) return;   // one entry per widget: nested pieces of a flagged widget are part of it
    flagged.push(e);
    const lab = label(e).slice(0, 160);
    const attr = e.required === true || e.getAttribute('aria-required') === 'true';
    found.push({ kind, label: lab, tag: e.tagName.toLowerCase(), html_id: e.id || null, name: e.getAttribute('name'),
      input_type: (e.type || '') || null, role: e.getAttribute('role'),
      required: attr || REQ.test(lab), required_basis: attr ? 'attribute' : (REQ.test(lab) ? 'label text' : null),
      reason, frame_index: frameIndex });
  };
  const off = e => e.disabled === true || e.getAttribute('aria-disabled') === 'true';
  for (const e of all) {
    const tag = e.tagName.toLowerCase(), type = (e.type || '').toLowerCase(), role = e.getAttribute('role');
    if (off(e)) continue;
    if (tag === 'input' && type === 'file') {
      // a styled upload button is often a visible <label> for a visually hidden file input: the label is what a person sees
      const vis = shown(e) || (e.labels && Array.from(e.labels).some(l => shown(l)));
      if (vis) add(e, 'file_upload', 'file upload: a person must attach the file; FormFiller never uploads files');
    } else if (tag === 'input' && type === 'password') {
      if (shown(e)) add(e, 'password', 'password field: never filled by FormFiller');
    } else if (e.isContentEditable && e.getAttribute('contenteditable') !== null && e.getAttribute('contenteditable') !== 'false' && e !== document.body) {
      if (shown(e)) add(e, 'contenteditable', 'editable text region: not a supported control; the answer must be entered by a person');
    } else if (tag === 'canvas') {
      const r = e.getBoundingClientRect();
      const ctx = [e.getAttribute('aria-label'), e.getAttribute('title'), e.id, e.className && e.className.baseVal === undefined ? e.className : '', label(e)].join(' ');
      if (shown(e) && r.width >= 40 && r.height >= 20 && /sign|draw/i.test(ctx)) add(e, 'canvas_signature', 'signature/drawing canvas: must be completed by a person');
    } else if (role && !['INPUT', 'SELECT', 'TEXTAREA'].includes(tag.toUpperCase()) && !comboPopups.has(e)) {
      const r = role.toLowerCase();
      if (['textbox', 'searchbox', 'listbox', 'radiogroup', 'checkbox', 'switch', 'slider', 'spinbutton', 'radio'].includes(r)) {
        if (r === 'radio' && e.closest('[role=radiogroup]')) continue;   // reported once, as the group
        if (shown(e)) add(e, 'aria_' + r, 'custom ARIA ' + r + ' control: there is no supported way to read or set it');
      }
    }
  }
  return found;
}
"""


def find_unsupported(page: Page) -> list[dict]:
    """Visible controls that cannot be filled or verified (file/password inputs, contenteditable regions, custom ARIA widgets,
    signature canvases), in every same-process frame. Hidden, disabled and aria-hidden/inert controls are not reported."""
    out: list[dict] = []
    for i, frame in enumerate(page.frames):
        with contextlib.suppress(Exception):  # a detached / inaccessible frame has nothing to report
            out.extend(frame.evaluate(_UNSUPPORTED_JS, i))
    return out


def _extract(frame: Frame, index: int) -> list[Control]:
    try:
        raw = frame.evaluate(_EXTRACT_JS, index)
    except Exception:  # noqa: BLE001 - a detached / inaccessible frame has no controls
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
    as not for use (preview thumbnails, menu toggles): they are never questions. So is page furniture: the site's own search
    or filter box in a navigation landmark, outside any form (see `pageFurniture` in _EXTRACT_JS)."""
    controls: list[Control] = []
    notes: list[dict] = []
    for i, frame in enumerate(page.frames):
        controls.extend(_extract(frame, i))
        with contextlib.suppress(Exception):  # a detached / inaccessible frame has nothing to note
            for tag in frame.evaluate(_OPAQUE_JS):
                notes.append({"kind": "opaque_custom_element", "frame_index": i, "element": tag,
                              "reason": "custom element exposes no readable shadow root (closed, or empty): its inner controls cannot be discovered"})
    return FormSchema(url=page.url, title=page.title(), controls=controls, notes=notes)
