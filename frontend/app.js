// Topic Coverage frontend controller.
// Loads a /runs/{id}/map payload (or the bundled sample for offline dev),
// renders the radial map, and on topic click loads /runs/{id}/topics/{tid}
// into the detail panel.

const STATE_LABEL = {
  only_you: 'Only you', you_lead: 'You lead', even: 'Even',
  comp_lead: 'Competitor leads', only_comp: 'Only competitor',
};
// STATE_COLOR is defined globally by radial-map.js (loaded first).

const mapEl = document.getElementById('map');
const detailEl = document.getElementById('detail');
const statusEl = document.getElementById('status');
const progressEl = document.getElementById('progress');
const analyzeBtn = document.getElementById('analyzeBtn');

let currentRunId = null;
let usingSample = false;       // sample mode: no /topics endpoint
let topicsById = {};           // cache nodes from the map for sample-mode detail
let pollTimer = null;

function apiBase() {
  // When served by FastAPI we share its origin; over file:// there's no API.
  return location.protocol === 'file:' ? null : location.origin;
}

// --- starting a new analysis (crawl + categorise) ---------------------------

// Pipeline stages, in order, mapped to the backend's run status values.
const STAGES = [
  { status: 'running',  label: 'Crawling pages' },
  { status: 'crawled',  label: 'Embedding content' },
  { status: 'embedded', label: 'Discovering topics' },
  { status: 'topiced',  label: 'Scoring coverage' },
  { status: 'done',     label: 'Done' },
];

function stageIndex(status) {
  const i = STAGES.findIndex(s => s.status === status);
  return i < 0 ? 0 : i;
}

async function startAnalysis(ownDomain, competitors, maxPages) {
  const base = apiBase();
  if (!base) {
    statusEl.textContent = 'Open this page via the running server (make dev), not as a file.';
    return;
  }
  analyzeBtn.disabled = true;
  detailEl.innerHTML = '<div class="empty">Analyzing… the map appears when the run finishes.</div>';
  mapEl.innerHTML = '<div class="muted">Crawling and categorising content…</div>';
  statusEl.textContent = '';
  try {
    const res = await fetch(`${base}/runs`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        own_domain: ownDomain,
        competitor_domains: competitors,
        max_pages_per_domain: maxPages,
      }),
    });
    if (!res.ok) throw new Error(`start failed (${res.status})`);
    const { run_id } = await res.json();
    currentRunId = run_id;
    history.replaceState(null, '', `?run=${run_id}`);
    pollRun(run_id);
  } catch (err) {
    analyzeBtn.disabled = false;
    statusEl.textContent = err.message;
    mapEl.innerHTML = `<div class="muted">Could not start the run.<br>${esc(err.message)}</div>`;
  }
}

function renderProgress(status, counts, domains, errored) {
  const idx = stageIndex(status);
  const pct = errored ? 100 : Math.round((idx / (STAGES.length - 1)) * 100);
  progressEl.hidden = false;
  progressEl.classList.toggle('error', !!errored);
  const steps = STAGES.slice(0, -1).map((s, i) => {
    const cls = errored ? '' : i < idx ? 'done' : i === idx ? 'active' : '';
    return `<span class="${cls}">${s.label}</span>`;
  }).join('');
  const c = counts || {};
  const dchips = (domains || []).map(d =>
    `<span class="dchip ${d.is_own ? 'own' : ''}">${esc(d.domain)} <b>${d.pages}</b> pages</span>`
  ).join('');
  progressEl.innerHTML = `
    <div class="bar"><span style="width:${pct}%"></span></div>
    <div class="steps">${steps}</div>
    <div class="counts">${errored ? '⚠ run failed — check the server logs'
      : `${c.pages || 0} pages · ${c.chunks || 0} chunks · ${c.topics || 0} topics`}</div>
    <div class="domains">${dchips}</div>`;
}

async function pollRun(runId) {
  const base = apiBase();
  if (pollTimer) clearTimeout(pollTimer);
  try {
    const r = await fetch(`${base}/runs/${runId}`);
    if (!r.ok) throw new Error(`run ${r.status}`);
    const info = await r.json();
    if (info.status === 'error') {
      renderProgress(info.status, info.counts, info.domains, true);
      analyzeBtn.disabled = false;
      return;
    }
    renderProgress(info.status, info.counts, info.domains, false);
    if (info.status === 'done') {
      analyzeBtn.disabled = false;
      await loadMap(runId);
      setTimeout(() => { progressEl.hidden = true; }, 1500);
      return;
    }
  } catch (err) {
    statusEl.textContent = err.message;
  }
  pollTimer = setTimeout(() => pollRun(runId), 2000);
}

async function loadMap(runId) {
  statusEl.textContent = 'Loading…';
  topicsById = {};
  const base = apiBase();
  try {
    let map;
    if (base) {
      const res = await fetch(`${base}/runs/${runId}/map`);
      if (!res.ok) throw new Error(`map ${res.status}`);
      map = await res.json();
      usingSample = false;
    } else {
      map = await (await fetch('sample-map.json')).json();
      usingSample = true;
    }
    currentRunId = runId;
    indexTopics(map);
    renderRadialMap(mapEl, map, onTopicClick);
    const n = Object.keys(topicsById).length;
    statusEl.textContent = `${map.own_domain} vs ${(map.competitors || []).join(', ')} · ${n} topics`
      + (usingSample ? ' · sample data' : '');
  } catch (err) {
    // Fall back to the bundled sample if the API isn't reachable.
    try {
      const map = await (await fetch('sample-map.json')).json();
      usingSample = true;
      indexTopics(map);
      renderRadialMap(mapEl, map, onTopicClick);
      statusEl.textContent = 'API unavailable — showing sample data';
    } catch (e2) {
      mapEl.innerHTML = `<div class="muted">Could not load a map.<br>${err.message}</div>`;
      statusEl.textContent = '';
    }
  }
}

function indexTopics(map) {
  (map.categories || []).forEach(cat =>
    (cat.topics || []).forEach(t => { topicsById[String(t.id)] = { ...t, category: cat.label }; }));
}

async function onTopicClick(topicId) {
  highlightSelected(mapEl, topicId);
  const base = apiBase();
  if (base && !usingSample) {
    detailEl.innerHTML = '<div class="empty">Loading…</div>';
    try {
      const res = await fetch(`${base}/runs/${currentRunId}/topics/${topicId}`);
      if (!res.ok) throw new Error(`topic ${res.status}`);
      renderDetail(await res.json());
      return;
    } catch (e) { /* fall through to node-only detail */ }
  }
  // Sample / offline mode: render from the node we already have (no evidence).
  const node = topicsById[String(topicId)];
  if (node) {
    renderDetail({
      label: node.label, category: node.category, state: node.state,
      you_pct: node.you_pct, competitors_pct: node.competitors_pct,
      detected: { own: [], competitors: [] },
    }, true);
  }
}

function renderDetail(d, sampleMode) {
  const color = STATE_COLOR[d.state] || '#94a3b8';
  const terms = labelTerms(d.label);
  const own = d.detected && d.detected.own ? d.detected.own : [];
  const comps = d.detected && d.detected.competitors ? d.detected.competitors : [];

  detailEl.innerHTML = `
    <span class="chip" style="background:${color}">${STATE_LABEL[d.state] || d.state}</span>
    <h2>${esc(d.label)}</h2>
    <div class="cat">${esc(d.category || '')}</div>

    <div class="sharebar">
      ${d.you_pct > 0 ? `<div class="you" style="width:${d.you_pct}%">${d.you_pct}%</div>` : ''}
      ${d.competitors_pct > 0 ? `<div class="comp" style="width:${d.competitors_pct}%">${d.competitors_pct}%</div>` : ''}
    </div>
    <div class="sharelabels"><span>You</span><span>Competitors</span></div>

    <div class="section-title">Content detected on this topic</div>
    ${sampleMode ? '<p class="col-empty">Sample data — connect the API to see detected sentences.</p>' : ''}
    <div class="cols">
      <div>
        <h3>On your domain</h3>
        ${own.length ? own.map(e => evidence(e, terms)).join('')
          : '<p class="col-empty">No content detected on your domain for this topic.</p>'}
      </div>
      <div>
        <h3>On competitors</h3>
        ${comps.length ? comps.map(e => evidence(e, terms, true)).join('')
          : '<p class="col-empty">No content detected on competitors for this topic.</p>'}
      </div>
    </div>`;
}

function evidence(e, terms, showDomain) {
  return `<div class="ev">
    ${showDomain && e.domain ? `<div class="ev-domain">${esc(e.domain)}</div>` : ''}
    ${e.title ? `<div class="ev-title">${esc(e.title)}</div>` : ''}
    <p>${highlight(e.sentence || '', terms)}</p>
    ${e.url ? `<a class="ev-url" href="${esc(e.url)}" target="_blank" rel="noopener"
      title="${esc(e.url)}">${esc(prettyUrl(e.url))}</a>
      <a class="ev-more" href="${esc(e.url)}" target="_blank" rel="noopener">See more →</a>` : ''}
  </div>`;
}

// A compact, readable form of a URL (drop scheme + www, trim length).
function prettyUrl(url) {
  let u = String(url).replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '');
  return u.length > 60 ? u.slice(0, 57) + '…' : u;
}

// --- term highlighting ------------------------------------------------------

const STOP = new Set(['the', 'and', 'for', 'with', 'your', 'guide', 'part', 'topic']);
function labelTerms(label) {
  return (label || '').split(/[^A-Za-z0-9]+/)
    .map(w => w.toLowerCase()).filter(w => w.length > 2 && !STOP.has(w));
}
function highlight(sentence, terms) {
  let out = esc(sentence);
  terms.forEach(t => {
    out = out.replace(new RegExp(`\\b(${escapeRe(t)}\\w*)\\b`, 'gi'), '<mark>$1</mark>');
  });
  return out;
}
function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

// --- boot -------------------------------------------------------------------

document.getElementById('analyzeForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const own = document.getElementById('ownDomain').value.trim();
  if (!own) return;
  const comps = document.getElementById('compDomains').value
    .split(',').map(s => s.trim()).filter(Boolean);
  // Blank -> 0 means "all pages" (bounded server-side by the crawl time budget).
  const maxPages = parseInt(document.getElementById('maxPages').value, 10) || 0;
  startAnalysis(own, comps, maxPages);
});

// Deep-link: ?run=N loads (or resumes polling for) that run. Otherwise wait
// for the user to enter a domain and click Analyze.
const qsRun = new URLSearchParams(location.search).get('run');
if (qsRun) {
  resumeOrLoad(parseInt(qsRun, 10));
} else {
  mapEl.innerHTML = '<div class="muted">Enter your domain and competitors above, then click Analyze.</div>';
}

// If the linked run is still processing, show progress; if done, show the map.
async function resumeOrLoad(runId) {
  const base = apiBase();
  if (!base) { loadMap(runId); return; }
  try {
    const info = await (await fetch(`${base}/runs/${runId}`)).json();
    if (info.status && info.status !== 'done' && info.status !== 'error') {
      currentRunId = runId;
      pollRun(runId);
      return;
    }
  } catch (e) { /* fall through to a plain map load */ }
  loadMap(runId);
}
