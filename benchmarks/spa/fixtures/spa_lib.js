/* Minimal SPA used by the Phase 3C fixtures. Not a framework: just enough moving parts (state, re-render,
   controlled inputs, async steps, conditional fields, popups, shadow DOM, iframes) to reproduce what DOM-based
   RFI forms do. Everything the app "knows" is in window.__state, so a test can compare what the page *shows*
   with what the app *holds*. window.__submitted counts real submissions (must stay 0 in every run). */
(function () {
  const cfg = Object.assign({mount: 'hidden', retain: true, route: false, guard: false, validateOn: 'input', loadMs: 0,
    nextLabel: 'Next', nextType: 'button', onNext: 'normal', resetKeys: [], back: false}, window.FORM_CONFIG);
  const state = (window.__state = {});
  window.__submitted = 0; window.__confirms = 0;
  const touched = {};
  const app = document.getElementById('app');
  const steps = cfg.steps;
  let cur = Number(new URLSearchParams(location.search).get('step')) || 1;
  const panels = {};
  const fields = steps.flatMap(s => s.fields);
  const fetchDelay = ms => ms > 0 ? fetch('/api/delay?ms=' + ms).then(r => r.text()) : Promise.resolve();
  const truthy = v => v === true || v === 'yes' || v === 'true' || (v !== undefined && v !== '' && v !== false && v !== 'no');
  const el = (tag, props = {}, kids = []) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) { if (k === 'text') e.textContent = v; else if (k in e && k !== 'list') e[k] = v; else e.setAttribute(k, v); }
    kids.forEach(c => e.append(c)); return e;
  };
  const idOf = f => 'f_' + f.key;
  let churning = false;  // a ticker that re-renders every 40 ms: the DOM is never quiet (cfg.churn from the start, cfg.churnFrom from that step on)
  const startChurn = () => { if (churning) return; churning = true; const tick = el('p', {id: 'ticker'}); document.getElementById('app').append(tick); setInterval(() => { tick.textContent = String(performance.now()); }, 40); };
  if (cfg.churn) startChurn();

  function popup(owner, f, items) {
    document.querySelectorAll('ul[data-popup]').forEach(u => u.remove());
    const ul = el('ul', {role: 'listbox', id: idOf(f) + '_lb'}); ul.dataset.popup = f.key;
    items.forEach(o => { const li = el('li', {role: 'option', text: o.label || o}); li.dataset.value = o.value || o;
      li.addEventListener('click', () => { state[f.key] = li.dataset.value; owner.dataset.committed = state[f.key];
        if (owner.tagName === 'INPUT') owner.value = o.label || o; else owner.textContent = o.label || o;
        owner.setAttribute('aria-expanded', 'false'); ul.remove(); refresh(); });
      ul.append(li); });
    document.body.append(ul); owner.setAttribute('aria-expanded', 'true'); owner.setAttribute('aria-controls', ul.id);
  }

  function control(f) {
    const id = idOf(f), opts = (f.options || []).map(o => typeof o === 'string' ? {value: o, label: o} : o);
    const onVal = v => { state[f.key] = v; touched[f.key] = touched[f.key] || false; refresh(); };
    if (f.widget === 'combobox_button') {
      const lab = el('label', {id: id + '_l', text: f.label});
      const cb = el('div', {id, role: 'combobox', tabIndex: 0, 'aria-labelledby': id + '_l', 'aria-haspopup': 'listbox', 'aria-expanded': 'false', text: 'Select…'});
      cb.addEventListener('click', () => { if (cb.getAttribute('aria-expanded') === 'true') { document.querySelectorAll('ul[data-popup]').forEach(u => u.remove()); cb.setAttribute('aria-expanded', 'false'); } else setTimeout(() => popup(cb, f, opts), 80); });
      return [lab, cb];
    }
    if (f.widget === 'combobox_input') {
      const lab = el('label', {htmlFor: id, text: f.label});
      const inp = el('input', {id, type: 'text', role: 'combobox', autocomplete: 'off', 'aria-autocomplete': 'list', 'aria-expanded': 'false'});
      inp.addEventListener('input', () => { const q = inp.value.toLowerCase(); setTimeout(() => popup(inp, f, opts.filter(o => o.label.toLowerCase().includes(q))), 60); });
      return [lab, inp];
    }
    if (f.widget === 'shadow' || f.widget === 'closed_shadow') {
      const host = el('x-field', {});
      const root = host.attachShadow({mode: f.widget === 'shadow' ? 'open' : 'closed'});
      const lab = el('label', {htmlFor: id, text: f.label}); const inp = el('input', {id, type: f.type || 'text'});
      inp.addEventListener('input', () => onVal(inp.value)); root.append(lab, inp); return [host];
    }
    if (f.widget === 'iframe') {
      const fr = el('iframe', {title: f.label, height: 60});
      fr.srcdoc = '<label for="i">' + f.label + '</label><input id="i" type="' + (f.type || 'text') + '"><script>document.getElementById("i").addEventListener("input",e=>parent.__state[' + JSON.stringify(f.key) + ']=e.target.value)<\/script>';
      return [fr];
    }
    if (f.type === 'radio') {
      const fs = el('fieldset', {id}, [el('legend', {text: f.label})]);
      opts.forEach(o => { const r = el('input', {type: 'radio', name: f.key, value: o.value}); r.addEventListener('change', () => onVal(o.value)); fs.append(el('label', {}, [r, ' ' + o.label])); });
      return [fs];
    }
    if (f.type === 'checkbox') {
      const c = el('input', {id, type: 'checkbox', name: f.key}); c.addEventListener('change', () => onVal(c.checked)); return [c, el('label', {htmlFor: id, text: f.label})];
    }
    const lab = el('label', {htmlFor: id, text: f.label + (f.required ? ' *' : '')});
    let inp;
    if (f.type === 'select') { inp = el('select', {id, name: f.key}, [el('option', {value: '', text: 'Select…'}), ...opts.map(o => el('option', {value: o.value, text: o.label}))]); inp.addEventListener('change', () => onVal(inp.value)); }
    else { inp = el('input', {id, name: f.key, type: f.type || 'text'}); if (f.required) inp.required = true;
      inp.addEventListener('input', () => { if (cfg.validateOn === 'input') touched[f.key] = true; onVal(inp.value); });
      inp.addEventListener('blur', () => { touched[f.key] = true; refresh(); }); }
    return [lab, inp];
  }

  function fieldNode(f) {
    const w = el('div', {class: 'field'}); w.dataset.key = f.key; control(f).forEach(c => w.append(c)); return w;
  }

  function buildStep(n) {
    const s = steps[n - 1]; const p = el('section', {id: 'step' + n}); p.dataset.step = n; p.append(el('h2', {text: s.title}));
    s.fields.forEach(f => {
      if (f.showIf && f.revealMs) { f._pending = p; return; }  // inserted later, when its trigger is answered
      const w = fieldNode(f); if (f.showIf) w.hidden = true; p.append(w);
    });
    if (n < steps.length) {
      // nextType: 'button' = <button type=button> outside a form; 'submit' = <button type=submit> in a form;
      // 'default' = <button> with no type in a form (a submit button by HTML rules); 'input' = <input type=submit> in a form.
      // With cfg.trap the click is NOT intercepted, so the form really submits (window.__submitted++).
      const t = cfg.nextType, form = t !== 'button';
      const nb = t === 'image' ? el('input', {type: 'image', alt: cfg.nextLabel, class: 'next', src: 'data:image/gif;base64,R0lGODlhAQABAAAAACw='})
        : t === 'input' ? el('input', {type: 'submit', value: cfg.nextLabel, class: 'next'})
        : el('button', {class: 'next', text: cfg.nextLabel});
      if (t === 'button' || t === 'submit') nb.setAttribute('type', t);
      nb.addEventListener('click', e => { if (cfg.trap) return; if (form) e.preventDefault(); next(); });
      if (form) { const fm = el('form', {}, [nb]); fm.addEventListener('submit', e => { e.preventDefault(); window.__submitted++; app.append(el('p', {text: 'Thank you, submitted', id: 'thanks'})); }); p.append(fm); } else p.append(nb);
    } else {
      const fm = el('form', {}, [el('button', {type: 'submit', id: 'submit', text: 'Submit application'})]);
      fm.addEventListener('submit', e => { e.preventDefault(); window.__submitted++; app.append(el('p', {text: 'Application submitted', id: 'thanks'})); }); p.append(fm);
    }
    if (cfg.earlySubmit && n < steps.length) {  // a real, visible submit button on every non-final step (the danger a mis-detected 'final step' would walk into)
      const fm = el('form', {}, [el('button', {type: 'submit', id: 'submit', text: 'Submit application'})]);
      fm.addEventListener('submit', e => { e.preventDefault(); window.__submitted++; app.append(el('p', {text: 'Application submitted', id: 'thanks'})); }); p.append(fm);
    }
    if (cfg.back && n > 1) { const bb = el('button', {type: 'button', class: 'back', text: 'Back'}); bb.addEventListener('click', () => go(n - 1)); p.append(bb); }
    return p;
  }

  function sync() {  // controlled inputs: the DOM always shows the app state, so a programmatic .value=... without an input event is undone
    document.querySelectorAll('[data-key] input[name],[data-key] select').forEach(i => {
      const v = state[i.name];
      if (i.type === 'radio') i.checked = v === i.value; else if (i.type === 'checkbox') i.checked = !!v;
      else if (i.value !== String(v ?? '')) i.value = v ?? '';
    });
  }

  function refresh() {
    fields.forEach(f => {
      const w = document.querySelector('[data-key="' + f.key + '"]');
      if (f.showIf && !w && f._pending && state[f.showIf.key] === f.showIf.eq && !f._inserting) {
        f._inserting = true; fetchDelay(f.revealMs).then(() => { const p = document.querySelector('#step' + f.step) || f._pending; const nw = fieldNode(f); p.insertBefore(nw, p.querySelector('.next,form') || null); refresh(); });
      }
      if (w && f.showIf && !f.revealMs) w.hidden = state[f.showIf.key] !== f.showIf.eq;
      if (w && f.enabledIf) w.querySelectorAll('input,select').forEach(i => { i.disabled = !truthy(state[f.enabledIf.key]); });
    });
    if (cfg.controlled) sync();
    document.querySelectorAll('button.next').forEach(b => { b.disabled = cfg.guard && !stepValid(cur); });
  }
  function stepValid(n) { return steps[n - 1].fields.every(f => !f.required || (state[f.key] !== undefined && state[f.key] !== '' && (cfg.validateOn !== 'blur' || touched[f.key]))); }
  steps.forEach((s, i) => s.fields.forEach(f => { f.step = i + 1; }));

  function show(n) {
    cur = n; if (cfg.churnFrom && n >= cfg.churnFrom) startChurn();
    Object.values(panels).forEach(p => { p.hidden = true; });
    const mountNow = () => {
      if (cfg.mount === 'unmount') { Object.values(panels).forEach(p => p.remove()); for (const k in panels) delete panels[k]; }
      if (!panels[n]) { panels[n] = buildStep(n); app.append(panels[n]); if (cfg.mount === 'unmount' && cfg.retain) sync2(); }
      panels[n].hidden = false; refresh(); app.querySelector('.loading')?.remove();
    };
    if (cfg.loadMs) { Object.values(panels).forEach(p => { p.hidden = true; }); app.append(el('div', {class: 'loading', role: 'status', 'aria-busy': 'true', text: 'Loading…'})); fetchDelay(cfg.loadMs).then(mountNow); } else mountNow();
  }
  function sync2() { document.querySelectorAll('[data-key] input[name],[data-key] select').forEach(i => { const v = state[i.name]; if (v === undefined) return; if (i.type === 'radio') i.checked = v === i.value; else if (i.type === 'checkbox') i.checked = !!v; else i.value = v; }); }

  function go(n) { if (cfg.route) history.pushState({n}, '', '?step=' + n); show(n); }
  function next() {
    if (cfg.onNext === 'confirm') { window.__confirms++; if (!confirm('Discard draft?')) return; }
    if (cfg.onNext === 'reload') { setTimeout(() => location.reload(), 30); return; }
    go(cur + 1);
    if (cfg.onNext === 'resetPrev') setTimeout(() => { cfg.resetKeys.forEach(k => { state[k] = ''; }); sync(); }, 60);
  }
  window.addEventListener('popstate', e => show((e.state && e.state.n) || 1));
  if (cfg.loadMs) { show(cur); } else show(cur);
  if (cfg.mount === 'hidden') { for (let n = 1; n <= steps.length; n++) if (!panels[n]) { panels[n] = buildStep(n); panels[n].hidden = n !== cur; app.append(panels[n]); } refresh(); }
})();
