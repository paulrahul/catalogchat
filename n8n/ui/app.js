// CatalogChat UI for the n8n workflows.
// Each user action is one POST to an n8n webhook; the FastAPI server keeps
// discovery state, so this page only tracks what to show.
//
// Override the n8n base URL with ?n8n=http://host:port

const N8N = new URLSearchParams(location.search).get('n8n') || 'http://localhost:5678';

const STEPS = ['URL', 'Navigate', 'Review', 'Verify', 'Extract'];

const DECISION_PROMPTS = {
  confirm_drilling: 'Go deeper into the detail pages, or extract from this level?',
  confirm_final_level: 'This looks like the final detail level. Proceed with these fields?',
  select_link: 'Extract from this level, or drill into a detail page?',
};

const OPTION_LABELS = {
  continue: 'Go deeper',
  drill: 'Go deeper',
  final: 'Extract from this level',
  confirm: 'Looks good, continue',
  reuse: 'Use saved plan',
  rediscover: 'Discover again',
};

const initialState = () => ({
  step: 0,
  url: '',
  busy: null,          // {label, startedAt} while a request is running
  error: null,
  reuse: null,         // reuse_existing_plan decision from the cache check
  decision: null,      // current discovery decision
  trail: [],           // levels already drilled through
  selectedUrl: null,   // link chosen for the next drill
  plan: null,
  showSelectors: false,
  editing: null,       // {level, field} being renamed
  needsRebuild: true,  // rebuild extraction plan before the next sample
  numRows: 3,
  sample: null,        // {rows, field_names, errors, ...}
  sampleIssue: null,   // fix_field decision from sample analysis
  fixer: null,         // {field, expected, feedback, suggestion}
  maxRows: 100,
  result: null,        // {rows, count}
});

let state = initialState();
let busyTimer = null;

// ---------------------------------------------------------------- API

async function call(path, body, label) {
  setState({ busy: { label, startedAt: Date.now() }, error: null });
  busyTimer = setInterval(render, 1000);
  try {
    const res = await fetch(`${N8N}/webhook/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON body */ }
    if (Array.isArray(data)) data = data[0];
    if (!res.ok || !data || data.type === 'error') {
      let message = data?.message || `${res.status} ${res.statusText}`;
      if (res.status === 404 && /not registered/i.test(message)) {
        message += ' Import the CatalogChat workflows into n8n and activate them.';
      }
      throw new Error(message);
    }
    return data;
  } catch (err) {
    const message = err instanceof TypeError
      ? `Could not reach n8n at ${N8N}. Is it running?`
      : err.message;
    setState({ error: message });
    return null;
  } finally {
    clearInterval(busyTimer);
    setState({ busy: null });
  }
}

// ---------------------------------------------------------------- Actions

async function start(url) {
  setState({ ...initialState(), url });
  const data = await call('catalogchat/start', { url }, 'Checking for a saved plan');
  if (!data) return;
  if (data.type === 'decision_required') setState({ reuse: data });
  else goToDiscover();
}

function reuseChoice(choice) {
  if (choice === 'reuse') {
    setState({ plan: state.reuse.context.plan, reuse: null, needsRebuild: true, step: 2 });
  } else {
    setState({ reuse: null });
    goToDiscover();
  }
}

async function goToDiscover() {
  setState({ step: 1, decision: null, trail: [], plan: null, sample: null, result: null });
  handleDiscovery(await call('catalogchat/discover', { url: state.url }, 'Analyzing the page'));
}

async function discoveryChoice(choice) {
  const d = state.decision;
  const userInput = { choice };
  const drilling = choice === 'continue' || choice === 'drill';
  if (drilling && state.selectedUrl) userInput.selected_url = state.selectedUrl;

  const trail = drilling
    ? [...state.trail, {
        level: d.state?.current_level,
        name: d.context.schema_summary?.item_name || `Level ${d.state?.current_level}`,
        url: d.state?.current_url,
      }]
    : state.trail;

  const data = await call('catalogchat/discover', { url: state.url, user_input: userInput },
    drilling ? 'Analyzing the next level' : 'Finishing discovery');
  if (data) setState({ trail });
  handleDiscovery(data);
}

function handleDiscovery(data) {
  if (!data) return;
  if (data.type === 'result' && data.plan) {
    setState({ plan: data.plan, decision: null, needsRebuild: true, step: 2 });
  } else if (data.type === 'decision_required') {
    const candidates = data.context.ranked_candidates || [];
    const selectedUrl = data.context.recommended_url || candidates[0]?.url || null;
    setState({ decision: data, selectedUrl });
  }
}

async function editSchema(edit) {
  const data = await call('catalogchat/schema', { url: state.url, edits: [edit] }, 'Updating the schema');
  if (data) setState({ plan: data.plan, editing: null, needsRebuild: true, sample: null });
}

async function fetchSample() {
  const data = await call('catalogchat/sample',
    { url: state.url, num_rows: state.numRows, rebuild: state.needsRebuild },
    state.needsRebuild ? 'Building the extraction plan and fetching samples' : 'Fetching samples');
  if (data) setState({ sample: data.sample, sampleIssue: data.decision, needsRebuild: false });
}

async function suggestFix() {
  const f = state.fixer;
  const data = await call('catalogchat/fix/suggest', {
    url: state.url,
    field_name: f.field,
    expected_value: f.expected,
    user_feedback: f.feedback,
  }, 'Asking the AI for a better selector');
  if (data) setState({ fixer: { ...state.fixer, suggestion: data } });
}

async function applyFix() {
  const f = state.fixer;
  const c = f.suggestion.correction;
  const data = await call('catalogchat/fix/apply', {
    url: state.url,
    num_rows: state.numRows,
    fixes: [{
      field: f.field,
      selector: c.selector,
      attribute: c.attribute || 'text',
      container_selector: c.container_selector,
    }],
  }, 'Applying the fix and refetching samples');
  if (data) setState({ sample: data.sample, sampleIssue: data.decision, fixer: null });
}

async function extract() {
  const data = await call('catalogchat/scrape',
    { url: state.url, max_rows: state.maxRows > 0 ? state.maxRows : null },
    'Extracting all rows');
  if (data) setState({ result: { rows: data.rows, count: data.count } });
}

function download(kind) {
  const rows = state.result.rows;
  let blob;
  if (kind === 'json') {
    blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' });
  } else {
    const cols = columnsOf(rows);
    const esc = v => {
      const s = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [cols.map(esc).join(','), ...rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\n');
    blob = new Blob([csv], { type: 'text/csv' });
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `catalog_data.${kind}`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------------------------------------------------------- Rendering

function setState(patch) {
  state = { ...state, ...patch };
  render();
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const label = opt => OPTION_LABELS[opt] || opt.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());

function columnsOf(rows, preferred = []) {
  const cols = [...preferred];
  rows.forEach(r => Object.keys(r).forEach(k => { if (!cols.includes(k)) cols.push(k); }));
  return cols;
}

function dataTable(rows, preferred) {
  const cols = columnsOf(rows, preferred);
  if (!rows.length) return '<p class="muted">No rows.</p>';
  const cell = v => {
    const s = v == null || v === '' ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
    return s ? `<td class="cell" title="${esc(s)}">${esc(s)}</td>` : '<td class="cell empty">empty</td>';
  };
  return `<div class="table-wrap"><table>
    <thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr>${cols.map(c => cell(r[c])).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
}

function renderStepper() {
  document.getElementById('stepper').innerHTML = STEPS.map((name, i) => {
    const cls = i === state.step ? 'current' : i < state.step && canJumpTo(i) ? 'done' : '';
    return `<li class="${cls}" data-step="${i}"><span class="num">${i + 1}</span>${name}</li>`;
  }).join('');
}

// Navigate can't be revisited without restarting discovery; use "Discover again" instead.
const canJumpTo = i => !state.busy && i !== 1 && (i === 0 || state.plan);

function statusLine() {
  if (!state.busy) return '';
  const secs = Math.floor((Date.now() - state.busy.startedAt) / 1000);
  return `<p class="status">${esc(state.busy.label)}… ${secs}s</p>`;
}

function errorLine() {
  return state.error ? `<div class="notice error">${esc(state.error)}</div>` : '';
}

function viewUrl() {
  const r = state.reuse;
  let reusePanel = '';
  if (r) {
    const chain = r.context.plan.schema_chain || [];
    const fields = [...new Set(chain.flatMap(l => (l.fields || []).map(f => f.name)))];
    reusePanel = `<div class="section">
      <h2>A saved plan exists for this URL</h2>
      <p class="muted">${chain.length} level(s), ${fields.length} field(s)${fields.length ? ': ' + esc(fields.slice(0, 12).join(', ')) + (fields.length > 12 ? '…' : '') : ''}</p>
      <div class="actions">
        ${r.options.map((o, i) => `<button class="${i === 0 ? 'primary' : ''}" data-action="reuse" data-choice="${esc(o)}">${esc(label(o))}</button>`).join('')}
      </div>
    </div>`;
  }
  return `
    <h1>Paste a catalog URL</h1>
    <p class="hint">A product listing, directory, or search results page.</p>
    <form id="url-form" class="row">
      <div class="grow"><input type="url" name="url" required placeholder="https://example.com/products" value="${esc(state.url)}" ${state.busy ? 'disabled' : ''}></div>
      <button class="primary" type="submit" ${state.busy ? 'disabled' : ''}>Start</button>
    </form>
    ${statusLine()}${errorLine()}${reusePanel}`;
}

function viewNavigate() {
  const d = state.decision;
  const current = d?.state;
  const trail = [...state.trail.map(t => ({ ...t, cls: '' })),
    ...(current ? [{ level: current.current_level, name: d.context.schema_summary?.item_name || 'Current page', url: current.current_url, cls: 'current' }] : [])];

  let decisionHtml = '';
  if (d && !state.busy) {
    const ctx = d.context || {};
    const summary = ctx.schema_summary || {};
    const facts = [
      summary.item_name && `Items: ${esc(summary.item_name)}`,
      summary.field_count && `Fields detected: ${summary.field_count}`,
    ].filter(Boolean).join(' · ');
    const candidates = ctx.ranked_candidates || [];
    const canDrill = d.options.some(o => o === 'continue' || o === 'drill');
    const picker = canDrill && candidates.length ? `
      <div class="field">
        <label for="next-link">Page to open next</label>
        <select id="next-link">
          ${candidates.map(c => `<option value="${esc(c.url)}" ${c.url === state.selectedUrl ? 'selected' : ''}>${esc(c.label || c.url)} (${esc(c.url)})</option>`).join('')}
        </select>
      </div>` : '';
    decisionHtml = `
      ${ctx.reasoning ? `<p class="reasoning">${esc(ctx.reasoning)}</p>` : ''}
      ${facts ? `<p class="muted">${facts}</p>` : ''}
      <p class="question">${esc(DECISION_PROMPTS[d.id] || d.question)}</p>
      ${picker}
      <div class="actions">
        ${d.options.map((o, i) => `<button class="${i === 0 ? 'primary' : ''}" data-action="discover" data-choice="${esc(o)}">${esc(label(o))}</button>`).join('')}
      </div>`;
  }

  return `
    <h1>Discovering the navigation route</h1>
    <p class="hint">${esc(state.url)}</p>
    ${trail.length ? `<ol class="trail">${trail.map(t => `
      <li class="${t.cls}"><span class="lvl">Level ${esc(t.level)}</span><span class="name">${esc(t.name)}</span><span class="url mono">${esc(t.url)}</span></li>`).join('')}</ol>` : ''}
    ${statusLine()}${errorLine()}${decisionHtml}
    ${state.error && !d ? '<div class="actions"><button class="primary" data-action="retry-discover">Retry</button></div>' : ''}
    <div class="section"><button class="link" data-action="restart" ${state.busy ? 'disabled' : ''}>Cancel and start over</button></div>`;
}

function viewReview() {
  const chain = state.plan?.schema_chain || [];
  const total = chain.reduce((n, l) => n + (l.fields || []).length, 0);
  const route = chain.map((l, i) => l.item_name || `Level ${i + 1}`).join(' → ') || 'Single page';
  const sel = state.showSelectors;
  const disabled = state.busy ? 'disabled' : '';

  const levels = chain.map((level, li) => {
    const rows = (level.fields || []).map(f => {
      const editing = state.editing && state.editing.level === li && state.editing.field === f.name;
      const nameCell = editing
        ? `<form class="inline-edit" data-action="rename-save" data-level="${li}" data-field="${esc(f.name)}">
             <input type="text" name="new_name" value="${esc(f.name)}" required>
             <button class="primary" type="submit" ${disabled}>Save</button>
             <button type="button" data-action="rename-cancel">Cancel</button>
           </form>`
        : esc(f.name);
      const sample = f.sample_value == null ? '' : String(f.sample_value);
      return `<tr>
        <td>${nameCell}</td>
        <td class="muted">${esc(f.type)}</td>
        <td class="cell ${sample ? '' : 'empty'}" title="${esc(sample)}">${esc(sample) || 'empty'}</td>
        ${sel ? `<td class="mono">${esc([f.container_selector, f.selector].filter(Boolean).join(' › '))}${f.attribute && f.attribute !== 'text' ? ` @${esc(f.attribute)}` : ''}</td>` : ''}
        <td class="nowrap">${editing ? '' : `
          <button class="link" data-action="rename" data-level="${li}" data-field="${esc(f.name)}" ${disabled}>Rename</button>
          &nbsp;&nbsp;<button class="link danger" data-action="delete" data-level="${li}" data-field="${esc(f.name)}" ${disabled}>Delete</button>`}</td>
      </tr>`;
    }).join('');
    return `
      <h2>Level ${li + 1}: ${esc(level.item_name || 'Items')}</h2>
      <p class="muted mono">${esc(level.url)}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Field</th><th>Type</th><th>Sample value</th>${sel ? '<th>Selector</th>' : ''}<th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="${sel ? 5 : 4}" class="muted">No fields at this level.</td></tr>`}</tbody>
      </table></div>`;
  }).join('');

  return `
    <h1>Review the extraction schema</h1>
    <p class="hint">${total} field(s) across ${chain.length} level(s): ${esc(route)}</p>
    <label class="toggle"><input type="checkbox" id="toggle-selectors" ${sel ? 'checked' : ''}> Show CSS selectors</label>
    ${statusLine()}${errorLine()}
    ${levels || '<div class="notice warn">This plan has no levels. Discover the route again.</div>'}
    <div class="actions">
      <button class="primary" data-action="to-verify" ${disabled || (chain.length ? '' : 'disabled')}>Verify with sample data</button>
      <button data-action="rediscover" ${disabled}>Discover again</button>
      <button data-action="restart" ${disabled}>Start over</button>
    </div>`;
}

function viewVerify() {
  const s = state.sample;
  const disabled = state.busy ? 'disabled' : '';
  const issue = state.sampleIssue;
  const issues = issue?.context?.issues || [];

  let fixer = '';
  if (state.fixer && s) {
    const f = state.fixer;
    const sug = f.suggestion;
    let sugHtml = '';
    if (sug) {
      const c = sug.correction;
      sugHtml = `
        ${(sug.found_elements || []).length ? `<p class="muted">Matching elements on the page</p>
          ${sug.found_elements.slice(0, 5).map(e => `<pre class="snippet">${esc(typeof e === 'string' ? e : JSON.stringify(e, null, 2))}</pre>`).join('')}` : ''}
        ${c ? `<h2>Suggested fix</h2>
          <dl class="kv">${Object.entries(c).map(([k, v]) => `<dt>${esc(k)}</dt><dd class="${/selector|attribute/.test(k) ? 'mono' : ''}">${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</dd>`).join('')}</dl>
          <div class="actions"><button class="primary" data-action="fix-apply" ${disabled}>Apply fix</button></div>`
        : '<div class="notice warn">No suggestion came back. Try a more specific expected value or add context.</div>'}`;
    }
    fixer = `<div class="section">
      <h2>Fix a field</h2>
      <p class="muted">Pick the field that looks wrong and give an example of the correct value.</p>
      <form id="fix-form">
        <div class="field"><label for="fix-field">Field</label>
          <select id="fix-field" name="field">${(s.field_names || []).map(n => `<option ${n === f.field ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
        <div class="field"><label for="fix-expected">Expected value</label>
          <input type="text" id="fix-expected" name="expected" required value="${esc(f.expected)}"></div>
        <div class="field"><label for="fix-feedback">What's wrong (optional)</label>
          <textarea id="fix-feedback" name="feedback">${esc(f.feedback)}</textarea></div>
        <div class="actions" style="margin-top:0">
          <button class="primary" type="submit" ${disabled}>Get suggestion</button>
          <button type="button" data-action="fix-cancel" ${disabled}>Cancel</button>
        </div>
      </form>
      ${sugHtml}
    </div>`;
  }

  return `
    <h1>Verify sample data</h1>
    <p class="hint">A quick preview before the full extraction.</p>
    <div class="row">
      <div><label for="num-rows">Sample rows</label>
        <select id="num-rows">${[1, 2, 3, 5, 10].map(n => `<option ${n === state.numRows ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
      <button data-action="fetch-sample" ${disabled}>${s ? 'Refetch' : 'Fetch sample'}</button>
    </div>
    ${statusLine()}${errorLine()}
    ${issues.length ? `<div class="notice warn">Some fields may need fixing<ul>${issues.map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>` : ''}
    ${(s?.errors || []).length ? `<div class="notice error">Errors while scraping<ul>${s.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
    ${s ? `<div style="margin-top:20px">${dataTable(s.rows || [], s.field_names || [])}</div>
      <div class="actions">
        <button class="primary" data-action="to-extract" ${disabled}>Looks right, extract</button>
        ${state.fixer ? '' : `<button data-action="fix-open" ${disabled || ((s.field_names || []).length ? '' : 'disabled')}>Fix a field</button>`}
        <button data-action="to-review" ${disabled}>Back to schema</button>
      </div>` : ''}
    ${fixer}`;
}

function viewExtract() {
  const r = state.result;
  const disabled = state.busy ? 'disabled' : '';
  return `
    <h1>Extract the data</h1>
    <p class="hint">Set a row limit, or 0 for every row. Large catalogs can take a while.</p>
    <div class="row">
      <div><label for="max-rows">Maximum rows</label>
        <input type="number" id="max-rows" min="0" step="10" value="${state.maxRows}" style="width:140px" ${disabled}></div>
      <button class="primary" data-action="extract" ${disabled}>${r ? 'Extract again' : 'Start extraction'}</button>
    </div>
    ${statusLine()}${errorLine()}
    ${r ? `<div class="section">
      <h2>${r.count} row(s) extracted</h2>
      ${r.rows.length > 100 ? '<p class="muted">Showing the first 100 rows. Downloads include all of them.</p>' : ''}
      ${dataTable(r.rows.slice(0, 100))}
      <div class="actions">
        <button class="primary" data-action="download" data-kind="csv" ${r.rows.length ? '' : 'disabled'}>Download CSV</button>
        <button data-action="download" data-kind="json" ${r.rows.length ? '' : 'disabled'}>Download JSON</button>
        <button data-action="restart">New extraction</button>
      </div>
    </div>` : ''}`;
}

function render() {
  renderStepper();
  const views = [viewUrl, viewNavigate, viewReview, viewVerify, viewExtract];
  document.getElementById('app').innerHTML = views[state.step]();
}

// ---------------------------------------------------------------- Events

document.addEventListener('submit', e => {
  e.preventDefault();
  const form = e.target;
  if (form.id === 'url-form') {
    start(form.url.value.trim());
  } else if (form.id === 'fix-form') {
    setState({ fixer: { field: form.field.value, expected: form.expected.value, feedback: form.feedback.value, suggestion: null } });
    suggestFix();
  } else if (form.dataset.action === 'rename-save') {
    const newName = form.new_name.value.trim();
    if (newName && newName !== form.dataset.field) {
      editSchema({ action: 'rename', level: Number(form.dataset.level), field: form.dataset.field, new_name: newName });
    } else {
      setState({ editing: null });
    }
  }
});

document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'next-link') state.selectedUrl = t.value;
  else if (t.id === 'toggle-selectors') setState({ showSelectors: t.checked });
  else if (t.id === 'num-rows') state.numRows = Number(t.value);
  else if (t.id === 'max-rows') state.maxRows = Math.max(0, Number(t.value) || 0);
});

document.addEventListener('click', e => {
  const stepEl = e.target.closest('#stepper li.done');
  if (stepEl) {
    setState({ step: Number(stepEl.dataset.step), error: null });
    return;
  }
  const el = e.target.closest('[data-action]');
  if (!el || el.tagName === 'FORM' || el.disabled) return;
  const { action, choice, level, field, kind } = el.dataset;
  switch (action) {
    case 'reuse': return reuseChoice(choice);
    case 'discover': return discoveryChoice(choice);
    case 'retry-discover': return goToDiscover();
    case 'rediscover': return goToDiscover();
    case 'restart': return setState(initialState());
    case 'rename': return setState({ editing: { level: Number(level), field } });
    case 'rename-cancel': return setState({ editing: null });
    case 'delete':
      if (confirm(`Delete the field "${field}"?`)) editSchema({ action: 'delete', level: Number(level), field });
      return;
    case 'to-review': return setState({ step: 2, error: null });
    case 'to-verify':
      setState({ step: 3, error: null, fixer: null });
      if (!state.sample || state.needsRebuild) fetchSample();
      return;
    case 'fetch-sample': return fetchSample();
    case 'fix-open': return setState({ fixer: { field: state.sample.field_names[0], expected: '', feedback: '', suggestion: null } });
    case 'fix-cancel': return setState({ fixer: null });
    case 'fix-apply': return applyFix();
    case 'to-extract': return setState({ step: 4, error: null });
    case 'extract': return extract();
    case 'download': return download(kind);
  }
});

render();
