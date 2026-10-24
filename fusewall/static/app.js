const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', minimumFractionDigits:2, maximumFractionDigits:6}).format((n || 0) / 1e6);
const number = n => new Intl.NumberFormat('en-US').format(n || 0);
const time = n => new Date(n * 1000).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit'});
const dollarInput = n => String(n / 1e6);
function micros(value) {
  if (!/^\d{1,6}(\.\d{1,6})?$/.test(value)) throw Error('Use a nonnegative dollar amount with up to six decimal places.');
  const [whole, fraction = ''] = value.split('.');
  const result = Number(whole) * 1_000_000 + Number(fraction.padEnd(6, '0'));
  if (result > 1_000_000_000_000) throw Error('Amount exceeds the supported limit.');
  return result;
}
let state, page = 'overview', requestFilter = '', requestKey = '', requestSearch = '', requestOffset = 0, requestData, toastTimer, polling = false, lastReceipt, lastReplay, refreshSequence = 0;
const paths = {
  overview: ['Overview','M3 3h6v6H3z M13 3h6v6h-6z M3 13h6v6H3z M13 13h6v6h-6z'],
  insights: ['Usage insights','M4 18V9 M10 18V4 M16 18v-6 M2 20h18'],
  keys: ['API keys','M13 7a5 5 0 1 0 0 6l6-6-3-3-2 2 M6 8h.01'],
  sessions: ['Sessions','M11 3a8 8 0 1 0 8 8 M11 6v6l4 2 M15 3h4v4'],
  requests: ['Request log','M5 3h12v16H5z M8 7h6 M8 11h6 M8 15h4'],
  lab: ['Traffic lab','M8 3h6 M9 3v6L4 17q-1 2 2 2h10q3 0 2-2l-5-8V3 M7 13h9'],
  replay: ['Policy replay','M6 4v14l12-7z'],
  reliability: ['Reliability','M11 2l8 3v6q0 6-8 9-8-3-8-9V5z M7 11l3 3 5-6'],
  settings: ['Settings','M3 6h16 M3 16h16 M7 3v6 M15 13v6']
};
function icon(path) { return `<span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 22 22"><path d="${path}"/></svg></span>`; }
function pill(status) { return `<span class="pill ${esc(status)}">${esc(status.replaceAll('_',' '))}</span>`; }
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 5000); }
async function api(path, method = 'GET', data) {
  const response = await fetch(path, {method, headers: {'Content-Type':'application/json', 'X-Fusewall-Request':'dashboard'}, body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/login') locked();
    const failure=Error(result.error?.message || `Request failed (${response.status}).`); failure.status=response.status; throw failure;
  }
  return result;
}
function locked() { refreshSequence++; $('#skip-link').hidden=true; $('#shell').hidden = true; $('#login').hidden = false; state = undefined; requestData = undefined; lastReceipt = lastReplay = undefined; $('#modal').close(); $('#modal-content').replaceChildren(); $('#owner-token').value = ''; }
async function refresh(render = true) {
  const sequence = ++refreshSequence;
  const route = location.hash.slice(1);
  const next = await api('/api/state');
  if (route === 'insights') next.insights = await api('/api/insights');
  let nextRequests;
  if (route === 'requests') {
    const query = new URLSearchParams({limit:'50', offset:String(requestOffset), search:requestSearch});
    if (requestFilter) query.set('status',requestFilter);
    if (requestKey) query.set('key_id',requestKey);
    nextRequests = await api('/api/requests?'+query);
  }
  if (sequence !== refreshSequence) return;
  state = next;
  if (nextRequests) requestData = nextRequests;
  $('#login').hidden = true; $('#shell').hidden = false; $('#skip-link').hidden=false;
  $('#connection-state').textContent = state.installation?.hosted?'Connected · shared database':'Connected locally';
  $('.sidebar-bottom p').innerHTML = state.installation?.hosted?'No paid inference.<br>Synthetic usage only.':'No cloud accounts.<br>No paid upstreams.';
  $('.workspace strong').textContent = state.installation?.hosted?'Hosted workspace':'Local workspace';
  $('.local-badge').innerHTML = '<span class="live-dot"></span> '+(state.installation?.hosted?'Hosted prototype':'Local instance');
  if (render) renderPage();
}
function heading(title, subtitle, actions = '') {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`;
}
const button = (label, action, cls = '') => `<button class="button ${cls}" data-action="${action}">${label}</button>`;
const empty = (title, text, action = '') => `<div class="empty"><h3>${title}</h3><p>${text}</p>${action}</div>`;
function requestsTable(rows, compact = false) {
  if (!rows.length) return empty('No matching requests', 'Try another filter, or run synthetic traffic in the laboratory.', '<a class="button" href="#lab">Open traffic lab →</a>');
  return `<div class="table-wrap"><table><thead><tr><th>WORKLOAD / RECEIPT</th><th>MODEL</th><th>STATUS</th><th>SIMULATED COST</th><th>LOCAL DATE / TIME</th>${compact ? '' : '<th>REASON</th>'}</tr></thead><tbody>${rows.map(r => `<tr data-request="${esc(r.id)}"><td><button class="receipt-button" data-action="receipt:${esc(r.id)}" aria-label="Inspect receipt for ${esc(r.key_name)} ${esc(r.id)}">${esc(r.key_name)} ↗</button><div class="table-secondary">${esc(r.client)} · ${esc(r.external_id)}</div></td><td>${esc(r.model.split('/')[1])}<div class="table-secondary">${esc(r.input_tokens + r.output_tokens)} synthetic tokens</div></td><td>${pill(r.status)}</td><td>${money(r.actual)}${['reserved','dispatching','outcome_unknown'].includes(r.status) ? `<div class="table-secondary">${money(r.reserved)} reserved</div>` : ''}</td><td>${time(r.created)}</td>${compact ? '' : `<td class="muted">${esc(r.reason.replaceAll('_',' '))}</td>`}</tr>`).join('')}</tbody></table></div>`;
}
function chart() {
  const rows = [...state.requests].reverse().slice(-16), w = innerWidth < 600 ? Math.max(280, innerWidth - 70) : 540, h = 170, left = 60, right = 16, top = 16, bottom = 32;
  if (!rows.length) return empty('Your usage curve starts here', 'Each completed synthetic request adds an accounting record.');
  const max = Math.max(...rows.map(r => r.actual), 1000);
  const points = rows.map((r,i) => [left + i * (w-left-right) / Math.max(1, rows.length-1), top + (1-r.actual/max)*(h-top-bottom)]);
  const path = points.map((p,i) => `${i?'L':'M'}${p[0]},${p[1]}`).join(' ');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Simulated cost in USD for the last ${rows.length} requests. No real provider spending.">${[0,.5,1].map(f => `<line class="gridline" x1="${left}" x2="${w-right}" y1="${top+f*(h-top-bottom)}" y2="${top+f*(h-top-bottom)}"/><text x="${left-8}" y="${top+f*(h-top-bottom)+3}" text-anchor="end">${money(max*(1-f))}</text>`).join('')}<path class="area" d="${path} L${points.at(-1)[0]},${h-bottom} L${left},${h-bottom} Z"/><path class="line" d="${path}"/>${points.map((p,i) => `<circle class="point" cx="${p[0]}" cy="${p[1]}" r="3"><title>Request ${i+1}: ${money(rows[i].actual)}, ${esc(rows[i].status)}</title></circle>`).join('')}<text x="${left}" y="${h-10}">Earlier requests</text><text x="${w-right}" y="${h-10}" text-anchor="end">Latest request</text></svg>`;
}
function overview() {
  const o = state.overview;
  return heading('Your agents. Your limits.', 'A clear view of what ran, what it used, and what the fuse stopped.', `<span class="date-label">${esc(o.period)} · UTC</span>${button('<span class="plus">＋</span> Create key', 'create-key', 'primary')}`) +
  (o.paused ? `<div class="status-banner"><p><strong>Emergency pause is active.</strong> New requests are blocked before dispatch. Existing reservations remain accounted for.</p>${button('Resume','toggle-pause','small')}</div>` : '') +
  `<div class="stats"><article class="stat"><div class="stat-top">Simulated spend <span class="stat-symbol">↗</span></div><div class="stat-value">${money(o.spent_micro)}</div><div class="stat-foot">Reference rates · ${esc(o.period)}</div></article><article class="stat"><div class="stat-top">Budget remaining <span class="stat-symbol">◷</span></div><div class="stat-value">${money(o.remaining_micro)}</div><div class="stat-foot good">After spent and reserved usage</div></article><article class="stat"><div class="stat-top">Requests evaluated <span class="stat-symbol">⇄</span></div><div class="stat-value">${number(o.requests)}</div><div class="stat-foot">${number(o.states.settled)} settled · ${number(o.states.failed)} failed</div></article><article class="stat"><div class="stat-top">Fuse interventions <span class="stat-symbol">◇</span></div><div class="stat-value">${number(o.blocked)}</div><div class="stat-foot orange">Blocked before the provider call</div></article></div>
  <div class="grid-main"><section class="panel"><div class="panel-header"><div><h2>Usage by request</h2><p class="panel-subtitle">Last ${Math.min(16,state.requests.length)} requests · simulated USD</p></div><span class="pill active">Accounting records</span></div><div class="panel-body">${chart()}</div><div class="chart-legend"><span class="legend-key"><span class="legend-line"></span>Settled cost per request</span></div></section><section class="panel"><div class="panel-header"><h2>Organization budget</h2><a href="#settings" class="arrow-link">Manage ↗</a></div><div class="panel-body"><span class="eyebrow">AVAILABLE THIS MONTH</span><div class="budget-number">${money(o.remaining_micro)}</div><div class="budget-sub">of ${money(o.budget_micro)} authorized allowance</div><div class="progress" id="budget-progress" aria-label="Organization budget usage"><span class="progress-spent"></span><span class="progress-held"></span></div><div class="budget-row"><span>Spent</span><strong>${money(o.spent_micro)}</strong></div><div class="budget-row"><span>Reserved in flight</span><strong>${money(o.held_micro)}</strong></div><div class="budget-note">Funds are reserved before dispatch.<br>Unused allowance returns after settlement.</div></div></section></div>
  <section class="panel"><div class="panel-header"><div><h2>Recent activity</h2><p class="panel-subtitle">Every decision has a receipt.</p></div><a href="#requests" class="arrow-link">View request log →</a></div>${requestsTable(state.requests.slice(0,6),true)}</section>
  ${!o.requests ? `<div class="notice" style="margin-top:20px">Start with a guided demonstration. It creates a demo key and sends synthetic traffic through the real budget engine. ${button('Run guided demo','demo','small')}</div>` : ''}`;
}
function keys() {
  return heading('Keys with boundaries.', 'Give each client or workload its own models, budget, and session policy.', button('＋ Create key','create-key','primary')) +
  `<section class="panel"><div class="panel-header"><h2>Workload keys</h2><span class="muted">${state.keys.length} keys</span></div>${!state.keys.length ? empty('Create your first workload key','Keys are shown once, stored as hashes, and separate from owner access.',button('Create key','create-key','primary')) : `<div class="table-wrap"><table><thead><tr><th>NAME / CLIENT</th><th>STATUS</th><th>MONTHLY SPENT</th><th>MONTHLY LIMIT</th><th>SESSION LIMIT</th><th>MODELS</th><th></th></tr></thead><tbody>${state.keys.map(k=>`<tr><td><strong>${esc(k.name)}</strong><div class="table-secondary">${esc(k.client)}</div></td><td>${pill(k.active?'active':'revoked')}</td><td>${money(k.spent_micro)}<div class="table-secondary">${money(k.held_micro)} held</div></td><td>${money(k.budget_micro)}</td><td>${money(k.session_budget_micro)}<div class="table-secondary">${k.max_calls} calls · ${Math.round(k.duration_seconds/60)} min</div></td><td>${k.allowed_models.map(m=>esc(m.split('/')[1])).join(', ')}</td><td>${button(k.active?'Revoke':'Enable',`key-status:${k.id}`,`small ${k.active?'danger':''}`)}</td></tr>`).join('')}</tbody></table></div>`}</section><p class="help" style="margin-top:15px">Policies are immutable for a key in this release. Create a replacement key to change its limits. Revocation is checked again immediately before dispatch.</p>`;
}
function sessions() {
  return heading('Every run has a ceiling.', 'Session policies are snapshotted at creation. Starting another session does not bypass parent budgets.') + `<section class="panel"><div class="panel-header"><h2>Recent sessions</h2><span class="muted">Latest 200</span></div>${state.sessions.length ? `<div class="table-wrap"><table><thead><tr><th>SESSION</th><th>KEY</th><th>STATUS</th><th>CALLS</th><th>SPENT</th><th>HELD</th><th>CEILING</th></tr></thead><tbody>${state.sessions.map(s=>`<tr><td><strong>${esc(s.external_id)}</strong><div class="table-secondary">${time(s.started)}</div></td><td>${esc(s.key_name)}</td><td>${pill(s.status)}</td><td>${s.calls} / ${JSON.parse(s.policy).max_calls}</td><td>${money(s.spent)}</td><td>${money(s.held)}</td><td>${money(s.ceiling)}</td></tr>`).join('')}</tbody></table></div>` : empty('No sessions yet','Run traffic with a session ID to begin tracking a protected workload.','<a href="#lab" class="button">Open traffic lab →</a>')}</section>`;
}
function requestPage() {
  const data = requestData || {requests:[],total:0,offset:0,limit:50};
  return heading('The decision log.', 'Search all retained records. Inspect authorization, settlement, and exceptional outcomes.', '<a href="/api/export" class="button">Export all CSV ↗</a>') + `<section class="panel"><div class="panel-header"><h2>${number(data.total)} matching requests</h2></div><form id="request-search-form" class="request-controls"><div class="field"><label for="request-search">Name, client, session or request ID</label><input id="request-search" name="search" value="${esc(requestSearch)}" maxlength="100" type="search"></div><div class="field"><label for="request-filter">Status</label><select id="request-filter"><option value="">All statuses</option>${['settled','blocked','failed','canceled','outcome_unknown','reserved','dispatching'].map(s=>`<option value="${s}" ${requestFilter===s?'selected':''}>${s.replaceAll('_',' ')}</option>`).join('')}</select></div><div class="field"><label for="request-key">Workload</label><select id="request-key"><option value="">All workloads</option>${state.keys.map(k=>`<option value="${k.id}" ${requestKey===k.id?'selected':''}>${esc(k.name)}</option>`).join('')}</select></div><button class="button" type="submit">Search</button></form>${requestsTable(data.requests)}<div class="pagination"><span>${data.total?`${data.offset+1}–${Math.min(data.offset+data.limit,data.total)} of ${number(data.total)}`:'0 results'}</span><div><button class="button small" data-action="requests-prev" ${data.offset===0?'disabled':''}>Previous</button> <button class="button small" data-action="requests-next" ${data.offset+data.limit>=data.total?'disabled':''}>Next</button></div></div></section><p class="help" style="margin-top:15px">All-history filters; CSV exports all retained records. Receipt buttons support keyboard access. Prompts and completion bodies are not stored.</p>`;
}

function insights() {
  const i = state.insights;
  if (!i) return heading('Usage insights.', 'Load the current UTC admission month.') + button('Refresh insights','refresh');
  const breakdown = (title, records) => `<section class="panel"><div class="panel-header"><h2>${title}</h2></div>${records.length?`<div class="table-wrap"><table><thead><tr><th>NAME</th><th>REQUESTS</th><th>SIMULATED COST</th><th>BLOCKED</th></tr></thead><tbody>${records.map(r=>`<tr><td>${esc(r.name)}</td><td>${number(r.requests)}</td><td>${money(r.actual_micro)}</td><td>${r.blocked}</td></tr>`).join('')}</tbody></table></div>`:empty('No usage this month','Run a labeled synthetic workload to populate this breakdown.')}</section>`;
  return heading('Understand the allowance.', `Attribution and next steps · ${esc(i.period)} UTC admission month`,button('Refresh','refresh')) + `<div class="stats"><article class="stat"><div class="stat-top">Recorded requests</div><div class="stat-value">${number(i.totals.requests)}</div><div class="stat-foot">Current admission month only</div></article><article class="stat"><div class="stat-top">Simulated cost</div><div class="stat-value">${money(i.totals.actual_micro)}</div><div class="stat-foot">No real provider charges</div></article><article class="stat"><div class="stat-top">Failed / canceled cost</div><div class="stat-value">${money(i.totals.failed_cost_micro)}</div><div class="stat-foot">Inspect partial synthetic generation</div></article><article class="stat"><div class="stat-top">Unused holds released</div><div class="stat-value">${money(i.totals.released_micro)}</div><div class="stat-foot">Allowance returned · not savings</div></article></div><div class="two-col">${breakdown('By client / team',i.clients)}${breakdown('By simulated model',i.models)}</div>${breakdown('By workload',i.workloads)}<section class="panel" style="margin-top:20px"><div class="panel-header"><h2>Suggested checks</h2><span class="muted">Rules derived from your records</span></div>${i.actions.map(a=>`<div class="reliability-item"><div><strong>${esc(a.title)}</strong><small>${esc(a.detail)}</small></div><a class="button small" href="#${a.route}">Inspect →</a></div>`).join('')}</section><div class="notice" style="margin-top:20px">${esc(i.assumption)} History capacity: ${number(i.history_used)} / ${number(i.history_limit)} records.</div>`;
}
function lab() {
  const activeKeys = state.keys.filter(k=>k.active);
  return heading('Break the loop. Safely.', 'Exercise the real budget engine with a deterministic synthetic provider.') + `<div class="status-banner"><p><strong>Simulation environment.</strong> Requests use synthetic reference rates, not paid provider APIs. Failure scenarios are controlled fixtures.</p></div><div class="two-col"><section class="panel"><div class="panel-header"><h2>Configure a workload</h2><span class="pill active">Simulation</span></div><div class="panel-body">${activeKeys.length ? `<form id="lab-form"><div class="form-grid"><div class="field"><label for="lab-key">Workload key</label><select id="lab-key" name="key_id">${activeKeys.map(k=>`<option value="${k.id}">${esc(k.name)}</option>`).join('')}</select></div><div class="field"><label for="lab-session">Session ID</label><input id="lab-session" name="session_id" value="run-${Date.now().toString(36)}" pattern="(?:[a-zA-Z0-9_]|-){1,80}" required maxlength="80"></div><div class="field"><label for="lab-scenario">Scenario</label><select id="lab-scenario" name="scenario"><option value="normal">Normal completion</option><option value="slow">Slow generation</option><option value="provider_error">Provider failure · no output</option><option value="interrupted">Interrupted · partial usage</option></select></div><div class="field"><label for="lab-model">Simulated model</label><select id="lab-model" name="model"><option>fusewall/mini</option><option>fusewall/pro</option></select></div><div class="field"><label for="lab-calls">Number of calls</label><input id="lab-calls" name="calls" type="number" min="1" max="${state.installation?.hosted?20:50}" value="8" required></div><div class="field"><label for="lab-parallel">Parallel requests</label><input id="lab-parallel" name="parallel" type="number" min="1" max="${state.installation?.hosted?4:8}" value="2" required></div><div class="field"><label for="lab-output">Maximum output tokens</label><input id="lab-output" name="max_tokens" type="number" min="1" max="1024" value="64" required><small>Reserved before dispatch; unused allowance is released.</small></div><div class="field wide"><label for="lab-prompt">Synthetic prompt</label><textarea id="lab-prompt" name="prompt" maxlength="4000">Summarize this week's support requests.</textarea><small>Used in memory for this run; prompt text is not stored.</small></div></div><div class="form-actions"><button type="button" class="button" data-action="preview">Preview one request</button><button type="submit" class="button primary">Run workload →</button></div></form>` : empty('A workload needs a key','Create one with a budget before running the laboratory.',button('Create key','create-key','primary'))}</div></section><section class="panel"><div class="panel-header"><h2>Preview and run result</h2></div><div class="panel-body"><div id="preview-result" aria-live="polite"></div><div id="lab-result">${lastReceipt ? labResult(lastReceipt) : empty('Ready when you are','Allowed requests generate synthetic output. Blocked requests stop before the provider. Failures retain their decision receipts.')}</div></div></section></div>`;
}
function labResult(result) {
  return `<div class="notice success">Workload complete. No paid upstream was contacted.</div><div class="result-grid"><div class="result"><strong>${result.summary.settled}</strong><small>Settled</small></div><div class="result"><strong>${result.summary.blocked}</strong><small>Blocked</small></div><div class="result"><strong>${result.summary.failed}</strong><small>Failed</small></div></div><div class="event-list">${result.results.slice(0,12).map(r=>`<div class="event-row"><span class="event-marker"></span><div>Call ${r.index+1} · ${esc(r.status)}<small>${esc(r.code?.replaceAll('_',' ') || money(r.actual_micro))}</small></div></div>`).join('')}</div><div class="form-actions"><a href="#requests" class="button">Inspect receipts →</a></div>`;
}
function replay() {
  return heading('Try a policy before it matters.', 'Replay saved usage locally. No provider calls, no changed policies, no new charges.') + `<div class="two-col"><section class="panel"><div class="panel-header"><h2>What-if budget</h2></div><div class="panel-body"><form id="replay-form"><div class="form-grid"><div class="field"><label for="replay-budget">Proposed budget · USD</label><input id="replay-budget" name="budget" value="0.02" inputmode="decimal" required></div><div class="field"><label for="replay-limit">Recorded requests</label><input id="replay-limit" name="limit" type="number" value="100" min="1" max="1000"></div></div><div class="notice" style="margin-top:20px">Sequential replay of the earliest recorded non-blocked requests. Each request must fit its original reservation. Uncertain outcomes retain full exposure.</div><div class="form-actions"><button class="button primary" type="submit">Evaluate policy →</button></div></form></div></section><section class="panel"><div class="panel-header"><h2>Policy result</h2></div><div class="panel-body" id="replay-result">${lastReplay ? replayResult(lastReplay) : empty('Use your own recorded traffic','A what-if result is an estimate under the stated replay assumptions, not measured savings.')}</div></section></div>`;
}
function replayResult(r) { return `<div class="result-grid"><div class="result"><strong>${r.allowed}</strong><small>Would allow</small></div><div class="result"><strong>${r.blocked}</strong><small>Would block</small></div><div class="result"><strong>${money(r.exposure_micro)}</strong><small>Simulated exposure</small></div></div><p class="help">${esc(r.assumption)}</p><div class="event-list">${r.decisions.slice(0,10).map(d=>`<div class="event-row"><span class="event-marker"></span><div>${d.allowed?'Would allow':'Would block'}<small>${esc(d.request_id)} · ${money(d.reserved_micro)} required</small></div></div>`).join('')}</div>`; }
function reliability() {
  return heading('Trust the records.', 'Inspect accounting consistency, retain backups, and review exceptional outcomes.', button('Check integrity','integrity','primary')) + `<div id="integrity-result"></div><div class="two-col"><section class="panel"><div class="panel-header"><h2>Local safeguards</h2></div>${[['Atomic budget reservations','Organization, key, and session checked in one transaction.'],['Append-only usage ledger','Database triggers reject ledger updates and deletes.'],['Conservative recovery',state.installation?.hosted?'Only expired request leases are recovered; live peers remain untouched.':'Undispatched reservations are released; uncertain dispatched work retains its hold.'],['Owner / workload separation','Workload keys cannot change policies or unlock the dashboard.'],['Network-free simulator','No provider SDK, external URL, or paid upstream is enabled.']].map(([a,b])=>`<div class="reliability-item"><div>${a}<small>${b}</small></div><span class="pill active">Enabled</span></div>`).join('')}<div class="panel-body">${button(state.installation?.hosted?'Export metadata JSON':'Download consistent backup','backup')}${state.installation?.hosted?button('Recover expired leases','recover','small'):''}<p class="help" style="margin-top:10px">Contains sensitive metadata and hashed keys. Hosted exports use cloud-admin restore into a newly migrated empty schema; owner/fingerprint secrets are backed up separately. Local backups restore into a stopped separate installation.</p></div></section><section class="panel"><div class="panel-header"><h2>Event inbox</h2><span class="muted">Latest 80</span></div><div class="event-list">${state.events.length ? state.events.slice(0,12).map(e=>`<div class="event-row"><span class="event-marker"></span><div>${esc(e.message)}<small>${esc(e.kind)} · ${time(e.created)}</small></div></div>`).join('') : empty('No alerts','Policy changes, blocked requests, and recovery events appear here.')}</div></section></div>${state.overview.uncertain ? `<div class="notice error" style="margin-top:20px">${state.overview.uncertain} uncertain request(s) retain budget. Open their receipts in the request log and reconcile them using owner access.</div>` : ''}`;
}
function settings() {
  const o = state.overview;
  return heading('Set the outer boundary.', 'Organization policy is the parent ceiling for every key and session.') + `<div class="two-col"><section class="panel"><div class="panel-header"><h2>Organization policy</h2><span class="pill ${o.paused?'blocked':'active'}">${o.paused?'Paused':'Enforcing'}</span></div><div class="panel-body"><form id="settings-form"><div class="field"><label for="org-budget">Monthly allowance · USD</label><input id="org-budget" name="budget" value="${dollarInput(o.budget_micro)}" inputmode="decimal" required><small>UTC calendar month. Cannot be lower than current spent + held exposure.</small></div><div class="form-divider"></div><label class="checklabel"><input name="paused" type="checkbox" ${o.paused?'checked':''}> Emergency pause: reject new work before dispatch</label><div class="form-actions"><button class="button primary" type="submit">Save policy</button></div></form></div></section><section class="panel"><div class="panel-header"><h2>Installation</h2></div><div class="panel-body"><div class="budget-row"><span>Provider mode</span><strong>${state.installation?.hosted?'Hosted simulation':'Local simulation only'}</strong></div><div class="budget-row"><span>Real API spending</span><strong>Disabled</strong></div><div class="budget-row"><span>Runtime</span><strong>${state.installation?.hosted?'Hosted prototype':'Local process'}</strong></div><div class="budget-row"><span>Rate card</span><strong>${esc(state.rate_version)}</strong></div><div class="budget-row"><span>Version</span><strong>${esc(state.version)}</strong></div><div class="notice" style="margin-top:20px">${state.installation?.hosted?'This is a single-owner hosted prototype with persistent PostgreSQL storage.':'This is a single-owner local prototype.'} Real provider adapters, multi-user company access and prepaid funds are not enabled.</div></div></section></div>`;
}
function renderPage() {
  if (!state) return;
  page = location.hash.slice(1) in paths ? location.hash.slice(1) : 'overview';
  $('#current-page').textContent = paths[page][0];
  $('#navigation').innerHTML = Object.entries(paths).map(([id,[label,path]])=>`<a class="nav-link ${page===id?'active':''}" href="#${id}" ${page===id?'aria-current="page"':''}>${icon(path)}${label}${id==='reliability' && state.overview.uncertain ? `<span class="nav-counter">${state.overview.uncertain}</span>`:''}</a>`).join('');
  $('#content').innerHTML = ({overview, insights, keys, sessions, requests:requestPage, lab, replay, reliability, settings}[page])();
  if (page === 'overview') {
    const budget = state.overview.budget_micro || 1;
    $('.progress-spent').style.width = `${Math.min(100,state.overview.spent_micro/budget*100)}%`;
    $('.progress-held').style.width = `${Math.min(100,state.overview.held_micro/budget*100)}%`;
  }
  $('#refresh-state').textContent = `Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})} · ${state.installation?.hosted?'Shared PostgreSQL':'Local storage'}`;
}
function showModal(html) { $('#modal-content').innerHTML = html; const title=$('h2',$('#modal-content')); if(title) title.id='dialog-title'; if (!$('#modal').open) $('#modal').showModal(); }
function createKey() {
  showModal(`<h2>Create a workload key</h2><p class="modal-intro">Set its boundaries before the first request. All rates are simulated USD.</p><form id="key-form"><div class="form-grid"><div class="field"><label for="key-name">Key name</label><input name="name" id="key-name" placeholder="Support triage" required maxlength="80"></div><div class="field"><label for="key-client">Client / team</label><input name="client" id="key-client" value="Internal" required maxlength="80"></div><div class="field"><label for="key-budget">Monthly budget · USD</label><input name="budget" id="key-budget" value="1.00" inputmode="decimal" required></div><div class="field"><label for="key-session-budget">Session budget · USD</label><input name="session_budget" id="key-session-budget" value="0.02" inputmode="decimal" required></div><div class="field"><label for="key-calls">Maximum calls / session</label><input id="key-calls" name="max_calls" type="number" value="25" min="1" max="10000" required></div><div class="field"><label for="key-concurrent">Concurrent requests</label><input id="key-concurrent" name="max_concurrent" type="number" value="4" min="1" max="32" required></div><div class="field"><label for="key-repeat">Repeat guard threshold</label><input id="key-repeat" name="loop_threshold" type="number" value="0" min="0" max="100" required><small>0 disables it. Repeated prompts may be legitimate.</small></div><div class="field"><label for="key-duration">Session duration · seconds</label><input id="key-duration" name="duration_seconds" type="number" value="1800" min="1" max="86400" required></div><div class="field wide"><label>Allowed simulated models</label><label class="checklabel"><input name="mini" type="checkbox" checked> fusewall/mini · standard fixture rates</label><label class="checklabel"><input name="pro" type="checkbox"> fusewall/pro · higher fixture rates</label></div></div><div class="form-actions"><button class="button primary" type="submit">Create key</button></div></form>`);
}
function showKey(k) {
  showModal(`<h2>Your key is ready.</h2><p class="modal-intro">Copy it now. The application stores only its hash and cannot show it again.</p><div class="secret-box" id="new-token"></div><div class="notice">This is a workload credential, not an owner token. Never place it in a public repository.</div><div class="form-actions">${button('Copy key','copy-key','primary')}<a href="#lab" class="button" data-action="close-dialog">Open traffic lab →</a></div>`);
  $('#new-token').textContent = k.token;
}
async function showReceipt(id) {
  const r = await api('/api/requests/'+encodeURIComponent(id));
  const pending = ['reserved','dispatching','outcome_unknown'].includes(r.status);
  const disposition = r.status==='outcome_unknown'?'Hold retained for owner reconciliation':r.status==='reserved'?'Reserved; not dispatched':r.status==='dispatching'?'Generation in progress; hold retained':r.status==='blocked'?'Blocked; no hold or upstream dispatch':r.reason==='authority_changed'||['restart_before_dispatch','lease_expired_before_dispatch'].includes(r.reason)?'Canceled before dispatch; hold released':'Observed synthetic usage settled; unused hold released';
  showModal(`<h2 id="dialog-title">Decision receipt</h2><p class="detail-id">${esc(r.id)}</p><div class="detail-grid"><div><small>Workload</small><span>${esc(r.key_name)} / ${esc(r.client)}</span></div><div><small>Outcome</small>${pill(r.status)}</div><div><small>Session</small><span>${esc(r.external_id)}</span></div><div><small>Rule / result</small><span>${esc(r.reason.replaceAll('_',' '))}</span></div><div><small>Initial reservation</small><span>${money(r.reserved)}</span></div><div><small>Settled synthetic cost</small><span>${money(r.actual)}</span></div><div><small>Rate card</small><span>${esc(r.rate_version)}</span></div><div><small>Policy version</small><span>${r.policy_version}</span></div><div><small>Created · local time</small><span>${time(r.created)}</span></div><div><small>Retained hold</small><span>${money(pending?r.reserved:0)}</span></div></div><div class="notice ${pending?'':'success'}">${disposition}</div><p class="help" style="margin-top:12px">Provenance: simulated. No paid API was contacted. A blocked request never had an authorized hold.</p>${r.events.length?`<div class="event-list">${r.events.map(e=>`<div class="event-row"><div>${esc(e.message)}<small>${esc(e.kind)} · ${time(e.created)}</small></div></div>`).join('')}</div>`:''}${r.status==='outcome_unknown'?`<form id="resolve-form" data-id="${esc(r.id)}"><div class="field"><label for="resolve-cost">Confirmed synthetic cost · USD</label><input id="resolve-cost" name="cost" value="${dollarInput(r.reserved)}" required></div><div class="field" style="margin-top:12px"><label for="resolve-reason">Reconciliation evidence / reason</label><input id="resolve-reason" name="reason" minlength="8" maxlength="300" required></div><div class="form-actions"><button class="button danger" type="submit">Resolve retained hold</button></div></form>`:''}`);
}
async function previewLab() {
  const form = $('#lab-form');
  if (!form?.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  const r = await api('/api/preview','POST',{key_id:data.key_id,session_id:data.session_id,completion:{model:data.model,messages:[{role:'user',content:data.prompt}],max_tokens:Number(data.max_tokens),stream:false}});
  const target = $('#preview-result');
  if (!target) return;
  target.innerHTML = `<div class="notice ${r.allowed?'success':'error'}"><strong>${r.allowed?'Would allow':'Would block'} one request</strong> · ${esc(r.reason.replaceAll('_',' '))}<br>Required hold: ${money(r.required_micro)} · ${r.input_tokens} synthetic input units + up to ${r.max_output_tokens} output units.</div><div class="table-wrap"><table><thead><tr><th>SCOPE</th><th>REMAINING</th><th>HOLD FITS</th></tr></thead><tbody>${r.scopes.map(b=>`<tr><td>${esc(b.kind)}</td><td>${money(b.remaining)}</td><td>${b.fits?'Yes':'No'}</td></tr>`).join('')}</tbody></table></div><p class="help" style="margin:12px 0 20px">${esc(r.assumption)}</p>`;
}

async function demo() {
  const existing = state.keys.find(k=>k.name==='Demo · Support triage' && k.active);
  const k = existing || await api('/api/keys','POST',{name:'Demo · Support triage',client:'Demo workspace',budget_micro:150000,session_budget_micro:18000,max_calls:25,loop_threshold:0,allowed_models:['fusewall/mini']});
  const run = await api('/api/lab','POST',{key_id:k.id,session_id:`demo-${Date.now().toString(36)}`,calls:10,parallel:2,max_tokens:64,scenario:'normal',prompt:'Summarize the support queue.'});
  lastReceipt=run; await refresh(); toast(`${run.summary.settled} requests settled; ${run.summary.blocked} stopped by the fuse. All traffic was simulated.`);
}
document.addEventListener('click', async e => {
  if(e.target.closest('.skip-link')) { e.preventDefault(); $('#content').focus(); return; }
  const action = e.target.closest('[data-action]')?.dataset.action;
  const row = e.target.closest('[data-request]');
  if (row) { try { await showReceipt(row.dataset.request); } catch(err) { toast(err.message); } return; }
  if (!action) return;
  const target = e.target.closest('[data-action]');
  try {
    if(action==='create-key') createKey();
    if(action==='preview') { target.disabled=true; await previewLab(); }
    if(action==='refresh') { target.disabled=true; await refresh(); }
    if(action==='requests-prev'||action==='requests-next') { requestOffset=Math.max(0,requestOffset+(action==='requests-next'?50:-50)); target.disabled=true; await refresh(); }
    if(action==='copy-key') { await navigator.clipboard.writeText($('#new-token').textContent); toast('Key copied. Store it securely.'); }
    if(action==='close-dialog') $('#modal').close();
    if(action.startsWith('key-status:')) { const id=action.split(':')[1], k=state.keys.find(k=>k.id===id); if(k.active && !confirm('Revoke this key? New requests will be rejected. Existing exposure remains accounted for.')) return; await api(`/api/keys/${id}`,'PATCH',{active:!k.active}); await refresh(); toast(k.active?'Key revoked.':'Key enabled.'); }
    if(action==='toggle-pause') { await api('/api/settings','PATCH',{budget_micro:state.overview.budget_micro,paused:!state.overview.paused}); await refresh(); }
    if(action==='demo') { target.disabled=true; target.textContent='Running demo…'; await demo(); }
    if(action==='recover') { target.disabled=true; const r=await api('/api/recovery','POST'); await refresh(); toast(`${r.canceled} undispatched holds released; ${r.unknown} uncertain holds retained.`); }
    if(action==='integrity') { const r=await api('/api/integrity','POST'); $('#integrity-result').innerHTML=`<div class="notice ${r.ok?'success':'error'}" style="margin-bottom:20px">${r.ok?'Accounting checks passed. Ledger, request costs, and all budget holds agree.':'Accounting mismatch found. Stop traffic and inspect the accounting records.'}</div>`; toast(r.ok?'Integrity check passed.':'Integrity check failed.'); }
    if(action==='backup') { target.disabled=true; const r=await fetch('/api/backup',{method:'POST',headers:{'X-Fusewall-Request':'dashboard'}}); if(!r.ok) throw Error('Backup failed.'); const blob=await r.blob(), url=URL.createObjectURL(blob), a=document.createElement('a'); a.href=url; a.download=state.installation?.hosted?`fusewall-metadata-${Date.now()}.json`:`fusewall-backup-${Date.now()}.db`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),30000); toast('Consistent backup created. Protect the downloaded file.'); }
  } catch(err) { toast(err.message); } finally { if(target.isConnected) target.disabled=false; }
});
document.addEventListener('submit', async e => {
  const form=e.target; e.preventDefault();
  const data=Object.fromEntries(new FormData(form)), submit=$('button[type=submit]',form); if(submit) submit.disabled=true;
  try {
    if(form.id==='request-search-form') { requestSearch=data.search; requestOffset=0; await refresh(); }
    if(form.id==='unlock-form') { await api('/api/login','POST',{token:$('#owner-token').value}); $('#owner-token').value=''; $('#login-error').textContent=''; await refresh(); }
    if(form.id==='key-form') { const allowed_models=[data.mini?'fusewall/mini':null,data.pro?'fusewall/pro':null].filter(Boolean); if(!allowed_models.length) throw Error('Allow at least one model.'); const k=await api('/api/keys','POST',{name:data.name,client:data.client,budget_micro:micros(data.budget),session_budget_micro:micros(data.session_budget),max_calls:Number(data.max_calls),max_concurrent:Number(data.max_concurrent),loop_threshold:Number(data.loop_threshold),duration_seconds:Number(data.duration_seconds),allowed_models}); await refresh(); showKey(k); }
    if(form.id==='lab-form') { $('#lab-result').innerHTML='<div class="notice" role="status">Running the synthetic workload. Reservations and outcomes are being recorded…</div>'; lastReceipt=await api('/api/lab','POST',{...data,calls:Number(data.calls),parallel:Number(data.parallel),max_tokens:Number(data.max_tokens)}); await refresh(false); if($('#lab-result')) { $('#lab-result').innerHTML=labResult(lastReceipt); $('#preview-result').replaceChildren(); } }
    if(form.id==='replay-form') { lastReplay=await api('/api/replay','POST',{budget_micro:micros(data.budget),limit:Number(data.limit)}); $('#replay-result').innerHTML=replayResult(lastReplay); }
    if(form.id==='settings-form') { await api('/api/settings','PATCH',{budget_micro:micros(data.budget),paused:data.paused==='on'}); await refresh(); toast('Organization policy updated.'); }
    if(form.id==='resolve-form') { await api(`/api/requests/${form.dataset.id}/resolve`,'POST',{actual_micro:micros(data.cost),reason:data.reason}); $('#modal').close(); await refresh(); toast('Hold reconciled and owner action recorded.'); }
  } catch(err) { if(form.id==='unlock-form') $('#login-error').textContent=err.message; else toast(err.message); if(form.id==='lab-form' && $('#lab-result')) $('#lab-result').innerHTML=`<div class="notice error">${esc(err.message)}</div>`; } finally { if(submit?.isConnected) submit.disabled=false; }
});
$('#close-modal').addEventListener('click',()=>$('#modal').close());
$('#modal').addEventListener('click',e=>{ if(e.target===$('#modal')) { const r=e.target.getBoundingClientRect(); if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom) $('#modal').close(); } });
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout','POST');locked();}catch(e){toast(e.message);}});
$('#mobile-menu').addEventListener('click',()=>{ const open=$('.sidebar').classList.toggle('open'); $('#mobile-menu').setAttribute('aria-expanded',String(open)); });
document.addEventListener('keydown',e=>{if(e.key==='Escape'){ $('.sidebar').classList.remove('open'); $('#mobile-menu').setAttribute('aria-expanded','false'); }});
document.addEventListener('input',e=>{if(e.target.closest('#lab-form') && $('#preview-result')?.textContent) $('#preview-result').textContent='Inputs changed. Preview again before using this estimate.';});
document.addEventListener('change',async e=>{if(e.target.closest('#lab-form') && $('#preview-result')?.textContent) $('#preview-result').textContent='Inputs changed. Preview again before using this estimate.';if(['request-filter','request-key'].includes(e.target.id)){ requestFilter=$('#request-filter').value; requestKey=$('#request-key').value; requestSearch=$('#request-search').value; requestOffset=0; try{await refresh();}catch(err){toast(err.message);} }});
addEventListener('hashchange',async()=>{ $('.sidebar').classList.remove('open'); $('#mobile-menu').setAttribute('aria-expanded','false'); try{await refresh(); $('#content').focus();}catch(err){toast(err.message);} });
setInterval(async()=>{if(!state||polling||$('#modal').open||!['overview','sessions','requests'].includes(page)||document.hidden||document.activeElement?.matches('input,select,textarea,button,a,[contenteditable=true]'))return;polling=true;try{await refresh();}catch{ $('#connection-state').textContent='Connection lost · data may be stale'; }finally{polling=false;}},4000);
async function bootstrap() {
  const health=await api('/health/live');
  if(health.storage==='postgres') {
    $('.unlock-panel .eyebrow').textContent='YOUR HOSTED CONTROL ROOM';
    $('.mode-note').textContent='Hosted simulation · No paid API calls';
    $('.unlock-help').innerHTML='<strong>Owner access</strong><p>Use the private owner token configured for this workspace. A workload API key cannot unlock owner controls.</p>';
    $('.unlock-aside small').textContent='Persistent shared accounting. Simulated inference only.';
  }
  await refresh();
}
bootstrap().catch(err=>{locked(); if(err.status!==401) $('#login-error').textContent=err.message;}).finally(()=>{
  // Initial session validation must finish before accepting an owner credential.
  $('#owner-token').disabled=false;
  const submit=$('#unlock-form button[type="submit"]');
  submit.disabled=false;
  submit.innerHTML='Unlock workspace <span aria-hidden="true">→</span>';
});
