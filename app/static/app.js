'use strict';

const app = document.getElementById('app');
const toastRegion = document.getElementById('toast-region');

const state = {
  me: null,
  csrf: null,
  prospects: [],
  prospect: null,
  report: null,
  users: [],
  templates: [],
  capabilities: [],
  aiStatus: null,
  storageStatus: null,
  validation: null,
  activeProspectTab: 'reports',
  reportNavScroll: 0,
  saveTimers: new Map(),
  route: null,
  aiEnhancementPollToken: 0,
};

const esc = value => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
const fmtDate = value => value ? new Intl.DateTimeFormat(undefined, {year:'numeric', month:'short', day:'numeric'}).format(new Date(value)) : 'Not set';
const fmtDateTime = value => value ? new Intl.DateTimeFormat(undefined, {year:'numeric', month:'short', day:'numeric', hour:'numeric', minute:'2-digit'}).format(new Date(value)) : 'Not set';
const bytes = n => !n ? '0 B' : `${(n / (n > 1048576 ? 1048576 : 1024)).toFixed(1)} ${n > 1048576 ? 'MB' : 'KB'}`;
const uid = () => crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;

const FALLBACK_TIMEZONES = [
  'America/Anchorage','America/Chicago','America/Denver','America/Detroit','America/Indiana/Indianapolis',
  'America/Los_Angeles','America/New_York','America/Phoenix','America/Puerto_Rico','America/Toronto','America/Vancouver',
  'Australia/Adelaide','Australia/Brisbane','Australia/Darwin','Australia/Hobart','Australia/Melbourne','Australia/Perth','Australia/Sydney',
  'Europe/Guernsey','Europe/Isle_of_Man','Europe/Jersey','Europe/London',
  'Pacific/Auckland','UTC',
];
function browserTimezone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; }
  catch { return ''; }
}
function availableTimezones() {
  let zones = [];
  try {
    zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
  } catch { zones = []; }
  const browser = browserTimezone();
  return [...new Set([...zones, ...FALLBACK_TIMEZONES, ...(browser ? [browser] : [])])].sort((a,b) => a.localeCompare(b));
}
function timezoneOptions(selected = browserTimezone()) {
  return `<option value="">Select timezone</option>${availableTimezones().map(zone => `<option value="${esc(zone)}" ${zone === selected ? 'selected' : ''}>${esc(zone.replaceAll('_',' '))}</option>`).join('')}`;
}
function setOnboardingSectionEnabled(checkbox) {
  const target = document.getElementById(checkbox.dataset.target);
  if (!target) return;
  target.classList.toggle('hidden', !checkbox.checked);
  for (const field of target.querySelectorAll('input, textarea, select')) {
    field.disabled = !checkbox.checked;
    if (field.dataset.onboardingRequired === 'true') field.required = checkbox.checked;
  }
}



const QUICK_ENTRY_AREAS = [
  {value:'RECEIVING', label:'Receiving'},
  {value:'PUTAWAY', label:'Putaway'},
  {value:'TRANSFER', label:'Transfer'},
  {value:'ORDER_MANAGEMENT', label:'Order Management'},
  {value:'PICKING', label:'Picking'},
  {value:'PACKING', label:'Packing'},
  {value:'SHIPPING', label:'Shipping'},
  {value:'CYCLE_COUNT', label:'Cycle Count'},
  {value:'WORK_ORDERS', label:'Work Orders'},
  {value:'PRINTING', label:'Printing'},
  {value:'OTHER', label:'Other'},
];
const QUICK_ENTRY_FILE_ACCEPT = 'image/*,.pdf,.docx,.xlsx,.csv,.txt,.md,.json,.xml';

function quickEntryStorageKey(reportId) { return `ci-discovery:${reportId}:quick-entry-area`; }
function getQuickEntryArea(reportId) {
  try { return localStorage.getItem(quickEntryStorageKey(reportId)) || ''; }
  catch { return ''; }
}
function setQuickEntryArea(reportId, value) {
  try { localStorage.setItem(quickEntryStorageKey(reportId), value); }
  catch { /* Storage may be blocked; the current form selection still works. */ }
}
function quickEntryAreaLabel(value) {
  return QUICK_ENTRY_AREAS.find(area => area.value === value)?.label || value;
}
function quickEntrySection(value) {
  if (!state.report || !value) return null;
  if (value === 'OTHER') return state.report.sections.find(section => section.stable_key === 'general-observations' && section.state !== 'REMOVED') || null;
  return state.report.sections.find(section => section.process_module === value && section.state !== 'REMOVED') || null;
}
function reportSectionOptions(selectedId = '') {
  const sections = state.report.sections.filter(section => section.state !== 'REMOVED');
  return `<option value="quick-entry" ${selectedId === 'quick-entry' ? 'selected' : ''}>Quick Entry</option>${sections.map(section => `<option value="${section.id}" ${section.id === selectedId ? 'selected' : ''}>${esc(section.title)}</option>`).join('')}<option value="report-preview" ${selectedId === 'report-preview' ? 'selected' : ''}>Report</option>`;
}

function rememberReportNavScroll() {
  const sidebar = document.querySelector('.report-sidebar');
  if (sidebar) state.reportNavScroll = sidebar.scrollTop;
}
function navigateReportScreen(screenId) {
  rememberReportNavScroll();
  location.hash = `#/report/${state.report.report.id}/${screenId}`;
}
function restoreReportNavPosition(screenId) {
  const sidebar = document.querySelector('.report-sidebar');
  const active = sidebar?.querySelector('.section-nav button.active');
  if (!sidebar || !active) return;
  sidebar.scrollTop = state.reportNavScroll || 0;
  const top = active.offsetTop;
  const bottom = top + active.offsetHeight;
  const viewportTop = sidebar.scrollTop;
  const viewportBottom = viewportTop + sidebar.clientHeight;
  if (top < viewportTop + 18 || bottom > viewportBottom - 70) {
    sidebar.scrollTop = Math.max(0, top - Math.round(sidebar.clientHeight * 0.35));
  }
  state.reportNavScroll = sidebar.scrollTop;
}

function toast(message, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  toastRegion.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function setLoading() {
  app.innerHTML = '<div class="loading"><div class="spinner" aria-label="Loading"></div></div>';
}

function parseErrorBody(body, status) {
  if (!body) return `Request failed (${status})`;
  const detail = body.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail)) return detail.map(x => x.msg).join('; ');
  return `Request failed (${status})`;
}

async function api(url, options = {}, allowQueue = true) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData) && options.body != null && typeof options.body !== 'string') {
    headers.set('Content-Type', 'application/json');
    options.body = JSON.stringify(options.body);
  }
  if (!['GET','HEAD','OPTIONS'].includes(method) && state.csrf) headers.set('X-CSRF-Token', state.csrf);
  options.headers = headers;
  options.credentials = 'same-origin';
  try {
    const response = await fetch(url, options);
    let body = null;
    const type = response.headers.get('content-type') || '';
    if (type.includes('json')) body = await response.json();
    else if (response.status !== 204) body = await response.text();
    if (!response.ok) {
      if (response.status === 401) {
        state.me = null; state.csrf = null; renderLogin();
      }
      if (response.status === 428) showPasswordModal();
      const error = new Error(parseErrorBody(body, response.status));
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  } catch (error) {
    const queueable = allowQueue && !navigator.onLine && !['GET','HEAD','OPTIONS'].includes(method) && !(options.body instanceof FormData);
    if (queueable) {
      await queueMutation({url, method, body: options.body || null, headers: Object.fromEntries(headers.entries())});
      updateConnection();
      toast('Saved offline. The change will sync when a connection returns.', 'success');
      return {offlineQueued: true};
    }
    throw error;
  }
}

function hasRole(role) { return state.me?.roles?.includes('ADMIN') || state.me?.roles?.includes(role); }
function canReview(scope) { return ['ADMIN','OWNER','REVIEWER'].includes(scope); }
function canOwn(scope) { return ['ADMIN','OWNER'].includes(scope); }

function shell(content, active = 'prospects') {
  const admin = hasRole('ADMIN');
  return `
  <div class="app-shell">
    <header class="topbar">
      <div class="brand" data-action="go" data-route="#/prospects" role="button" tabindex="0">
        <img class="logo-on-dark" src="/static/cloud-inventory-logo-for-dark-background-v0.4.1.png" alt="Cloud Inventory">
        <span class="brand-title">Site Discovery</span>
      </div>
      <nav class="topnav" aria-label="Primary navigation">
        <button class="nav-link ${active==='prospects'?'active':''}" data-action="go" data-route="#/prospects">Prospects</button>
        ${admin ? `<button class="nav-link ${active==='admin'?'active':''}" data-action="go" data-route="#/admin">Administration</button>` : ''}
      </nav>
      <div class="top-actions">
        <span id="connection-pill" class="connection-pill">Online</span>
        <button class="user-menu" data-action="user-menu">${esc(state.me?.display_name || state.me?.username || 'User')}</button>
      </div>
    </header>
    <main>${content}</main>
    <nav class="mobile-actionbar" aria-label="Mobile navigation">
      <button data-action="go" data-route="#/prospects">Prospects</button>
      <button data-action="new-prospect">New</button>
      <button data-action="sync-now">Sync</button>
      <button data-action="user-menu">Account</button>
    </nav>
  </div>`;
}

function renderLogin(message = '') {
  app.innerHTML = `
    <main class="login-page">
      <section class="login-card">
        <img class="login-logo logo-on-light" src="/static/cloud-inventory-logo-for-light-background-v0.4.1.png" alt="Cloud Inventory">
        <h1>Site Discovery Platform</h1>
        <p class="subhead">Secure internal discovery capture and report generation</p>
        ${message ? `<div class="validation-item ERROR">${esc(message)}</div>` : ''}
        <form id="login-form">
          <div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" required autofocus></div>
          <div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required></div>
          <button class="btn btn-primary btn-wide" type="submit">Sign in</button>
        </form>
      </section>
    </main>`;
}

async function loadMe() {
  try {
    const me = await api('/api/auth/me', {}, false);
    state.me = me; state.csrf = me.csrf_token;
    if (me.force_password_change) showPasswordModal();
    return true;
  } catch (error) {
    if (error.status !== 401) console.error(error);
    return false;
  }
}

function showModal(title, body, actions = '') {
  closeModal();
  const wrap = document.createElement('div');
  wrap.id = 'modal-root';
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `<section class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><h2>${esc(title)}</h2>${body}<div class="modal-actions">${actions || '<button class="btn btn-ghost" data-action="close-modal">Close</button>'}</div></section>`;
  document.body.appendChild(wrap);
}
function closeModal() { state.aiEnhancementPollToken += 1; if ('speechSynthesis' in window) window.speechSynthesis.cancel(); document.getElementById('modal-root')?.remove(); }

function showPasswordModal() {
  showModal('Change your password', `
    <p>The initial or temporary password must be replaced before the workspace can be used.</p>
    <form id="password-form">
      <div class="field"><label>Current password</label><input name="current_password" type="password" autocomplete="current-password" required></div>
      <div class="field"><label>New password</label><input name="new_password" type="password" autocomplete="new-password" minlength="14" required><small>At least 14 characters and three character groups.</small></div>
      <div class="field"><label>Confirm new password</label><input name="confirm_password" type="password" autocomplete="new-password" minlength="14" required></div>
      <button class="btn btn-primary btn-wide" type="submit">Update password</button>
    </form>`, '');
}

function showUserMenu() {
  showModal('Account', `
    <p><strong>${esc(state.me.display_name || state.me.username)}</strong><br>${esc(state.me.email)}</p>
    <p>${state.me.roles.map(r => `<span class="badge">${esc(r)}</span>`).join(' ')}</p>
    <button class="btn btn-ghost btn-wide" data-action="change-password">Change password</button>`,
    `<button class="btn btn-ghost" data-action="close-modal">Close</button><button class="btn btn-danger" data-action="logout">Sign out</button>`);
}

async function renderProspects() {
  setLoading();
  state.prospects = await api('/api/prospects');
  const active = state.prospects.filter(p => p.status === 'ACTIVE').length;
  const due = state.prospects.filter(p => p.retention_due_at && new Date(p.retention_due_at) < new Date(Date.now() + 90*86400000)).length;
  const cards = state.prospects.map(p => `
    <article class="card card-click" data-action="go" data-route="#/prospect/${p.id}" tabindex="0">
      <div class="card-meta"><span class="badge badge-cyan">${esc(p.status)}</span><span>${esc(p.industry || 'Industry not set')}</span></div>
      <h2>${esc(p.name)}</h2>
      <p>${esc(p.opportunity || 'No opportunity summary has been entered.')}</p>
      <div class="card-meta"><span>Retention: ${fmtDate(p.retention_due_at)}</span><span>Updated: ${fmtDate(p.updated_at)}</span></div>
    </article>`).join('');
  app.innerHTML = shell(`
    <div class="page">
      <header class="page-header"><div><h1>Prospect Discovery</h1><p>Create, collaborate on, consolidate, and publish site discovery reports.</p></div><div class="toolbar"><button class="btn btn-primary" data-action="new-prospect">Create prospect</button></div></header>
      <section class="stats"><div class="stat"><strong>${state.prospects.length}</strong><span>Prospects</span></div><div class="stat"><strong>${active}</strong><span>Active workspaces</span></div><div class="stat"><strong>${due}</strong><span>Retention reviews due soon</span></div><div class="stat"><strong id="queued-stat">0</strong><span>Offline changes queued</span></div></section>
      <section class="grid grid-3">${cards || `<div class="card empty"><h2>No prospect workspaces</h2><p>Create the first workspace to begin a discovery.</p><button class="btn btn-primary" data-action="new-prospect">Create prospect</button></div>`}</section>
    </div>`, 'prospects');
  updateConnection();
  updateQueueCount();
}

function showNewProspect() {
  const timezone = browserTimezone();
  showModal('Create prospect workspace', `
    <form id="prospect-onboarding-form" class="onboarding-form">
      <fieldset class="onboarding-section">
        <legend>1. Prospect details</legend>
        <div class="field"><label>Prospect name</label><input name="prospect_name" required maxlength="200" autofocus></div>
        <div class="field"><label>Industry</label><input name="prospect_industry" maxlength="150"></div>
        <div class="field"><label>Opportunity overview</label><textarea name="prospect_opportunity" placeholder="Why is Cloud Inventory being evaluated and what operations are in scope?"></textarea></div>
      </fieldset>
      <fieldset class="onboarding-section">
        <div class="onboarding-section-head"><strong class="onboarding-section-title">2. Site details</strong><label class="toggle-label"><input type="checkbox" name="create_site" data-action="onboarding-toggle" data-target="onboarding-site-fields" checked> Add a site now</label></div>
        <div id="onboarding-site-fields">
          <div class="field"><label>Site name</label><input name="site_name" data-onboarding-required="true" required maxlength="200"></div>
          <div class="field"><label>Address</label><textarea name="site_address"></textarea></div>
          <div class="field"><label>Timezone</label><select name="site_timezone">${timezoneOptions(timezone)}</select><small>Defaults to the timezone reported by this browser.</small></div>
        </div>
      </fieldset>
      <fieldset class="onboarding-section">
        <div class="onboarding-section-head"><strong class="onboarding-section-title">3. Engagement details</strong><label class="toggle-label"><input type="checkbox" name="create_engagement" data-action="onboarding-toggle" data-target="onboarding-engagement-fields" checked> Add an engagement now</label></div>
        <div id="onboarding-engagement-fields">
          <div class="field"><label>Engagement name</label><input name="engagement_name" data-onboarding-required="true" required maxlength="200" placeholder="Onsite site survey"></div>
          <div class="field"><label>Survey date</label><input name="engagement_survey_date" type="date"></div>
          <div class="field"><label>Objectives</label><textarea name="engagement_objectives" placeholder="What should this discovery engagement establish?"></textarea></div>
          <p class="help">When a site is created above, this engagement is linked to it automatically.</p>
        </div>
      </fieldset>
      <button class="btn btn-primary btn-wide" type="submit">Create workspace</button>
    </form>`, '');
}

async function renderProspect(id, tab = state.activeProspectTab) {
  setLoading();
  state.activeProspectTab = tab;
  state.prospect = await api(`/api/prospects/${id}`);
  const data = state.prospect;
  const p = data.prospect;
  let panel = '';
  if (tab === 'reports') {
    panel = `<div class="page-header"><div><h2>Reports</h2><p>Individual capture reports can be merged into a consolidated owner report.</p></div><button class="btn btn-primary" data-action="new-report">Create report</button></div>
      <div class="grid grid-2">${data.reports.map(r => `<article class="card card-click" data-action="go" data-route="#/report/${r.id}" tabindex="0"><div class="card-meta"><span class="badge ${r.state==='FINALIZED'?'badge-success':r.state==='MERGED'?'badge-warning':'badge-cyan'}">${esc(r.state)}</span><span>${esc(r.report_kind)}</span><span>Revision ${r.revision}</span></div><h3>${esc(r.title)}</h3><p>Updated ${fmtDate(r.updated_at)}</p>${r.merged_into_report_id?'<p class="help">This report has been merged into another report.</p>':''}</article>`).join('') || '<div class="card empty"><h2>No reports</h2><p>Create individual capture reports for onsite contributors or a consolidated report for the owner.</p></div>'}</div>`;
  } else if (tab === 'sites') {
    panel = `<div class="page-header"><div><h2>Sites</h2><p>Physical locations included in the discovery.</p></div><button class="btn btn-primary" data-action="new-site">Add site</button></div><div class="grid grid-3">${data.sites.map(s => `<article class="card"><h3>${esc(s.name)}</h3><p>${esc(s.address || 'Address not provided')}</p><div class="card-meta">${esc(s.timezone || 'Timezone not set')}</div></article>`).join('') || '<div class="card empty">No sites have been added.</div>'}</div>`;
  } else if (tab === 'engagements') {
    panel = `<div class="page-header"><div><h2>Discovery engagements</h2><p>Onsite surveys, workshops, and follow-up engagements.</p></div><button class="btn btn-primary" data-action="new-engagement">Add engagement</button></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Survey date</th><th>Site</th><th>Status</th></tr></thead><tbody>${data.engagements.map(e => `<tr><td>${esc(e.name)}</td><td>${fmtDate(e.survey_date)}</td><td>${esc(data.sites.find(s=>s.id===e.site_id)?.name || 'Not assigned')}</td><td><span class="badge">${esc(e.status)}</span></td></tr>`).join('') || '<tr><td colspan="4">No engagements have been created.</td></tr>'}</tbody></table></div>`;
  } else if (tab === 'team') {
    panel = `<div class="page-header"><div><h2>Prospect team</h2><p>Membership establishes the isolation boundary and default collaboration scope.</p></div>${canOwn(data.access_scope)?'<button class="btn btn-primary" data-action="add-prospect-member">Add member</button>':''}</div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Scope</th></tr></thead><tbody>${data.members.map(m => `<tr><td>${esc(m.display_name)}</td><td>${esc(m.email)}</td><td><span class="badge">${esc(m.role_scope)}</span></td></tr>`).join('')}</tbody></table></div>`;
  }
  app.innerHTML = shell(`
    <div class="page">
      <div class="breadcrumbs"><button data-action="go" data-route="#/prospects">Prospects</button><span>/</span><span>${esc(p.name)}</span></div>
      <header class="page-header prospect-header"><div class="prospect-identity">${p.logo_url?`<img class="prospect-logo" src="${esc(p.logo_url)}" alt="${esc(p.name)} logo">`:'<div class="prospect-logo-placeholder" aria-hidden="true">Logo</div>'}<div><h1>${esc(p.name)}</h1><p>${esc(p.opportunity || 'No opportunity overview has been entered.')}</p><p class="help">Last export: ${fmtDate(p.last_exported_at)}</p></div></div><div class="toolbar"><span class="badge badge-cyan">${esc(data.access_scope)}</span><span class="badge">Retention ${fmtDate(p.retention_due_at)}</span>${canOwn(data.access_scope)?`<button class="btn btn-ghost" data-action="upload-prospect-logo">${p.logo_url?'Change logo':'Upload logo'}</button><a class="btn btn-ghost" href="/api/prospects/${p.id}/export">Export workspace</a><button class="btn btn-secondary" data-action="archive-prospect">Archive</button>`:''}</div></header>
      <nav class="tabs"><button class="tab ${tab==='reports'?'active':''}" data-action="prospect-tab" data-tab="reports">Reports</button><button class="tab ${tab==='sites'?'active':''}" data-action="prospect-tab" data-tab="sites">Sites</button><button class="tab ${tab==='engagements'?'active':''}" data-action="prospect-tab" data-tab="engagements">Engagements</button><button class="tab ${tab==='team'?'active':''}" data-action="prospect-tab" data-tab="team">Team</button></nav>
      ${panel}
    </div>`, 'prospects');
  updateConnection();
}

async function ensureProspectSupport() {
  const [users, templates] = await Promise.all([api('/api/users'), api('/api/report-templates')]);
  state.users = users; state.templates = templates;
}

function showNewSite() {
  const timezone = browserTimezone();
  showModal('Add site', `<form id="site-form"><div class="field"><label>Site name</label><input name="name" required></div><div class="field"><label>Address</label><textarea name="address"></textarea></div><div class="field"><label>Timezone</label><select name="timezone">${timezoneOptions(timezone)}</select><small>Defaults to the timezone reported by this browser.</small></div><button class="btn btn-primary btn-wide" type="submit">Add site</button></form>`, '');
}
function showNewEngagement() {
  const sites = state.prospect.sites.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  showModal('Add discovery engagement', `<form id="engagement-form"><div class="field"><label>Engagement name</label><input name="name" required placeholder="Onsite site survey"></div><div class="field"><label>Site</label><select name="site_id"><option value="">Not assigned</option>${sites}</select></div><div class="field"><label>Survey date</label><input name="survey_date" type="date"></div><div class="field"><label>Objectives</label><textarea name="objectives"></textarea></div><button class="btn btn-primary btn-wide" type="submit">Add engagement</button></form>`, '');
}
async function showNewReport() {
  await ensureProspectSupport();
  if (!state.prospect.engagements.length) { toast('Create an engagement before creating a report.', 'error'); return; }
  const engagements = state.prospect.engagements.map(e => `<option value="${e.id}">${esc(e.name)} - ${fmtDate(e.survey_date)}</option>`).join('');
  const templates = state.templates.map(t => `<option value="${t.id}">${esc(t.name)} v${t.version}</option>`).join('');
  showModal('Create discovery report', `<form id="report-form"><div class="field"><label>Report title</label><input name="title" required value="${esc(state.prospect.prospect.name)} - Site Discovery Report"></div><div class="field"><label>Engagement</label><select name="engagement_id" required>${engagements}</select></div><div class="field"><label>Template</label><select name="report_template_id">${templates}</select></div><div class="field"><label>Report type</label><select name="report_kind"><option value="CAPTURE">Contributor capture report</option><option value="CONSOLIDATED">Consolidated owner report</option></select></div><button class="btn btn-primary btn-wide" type="submit">Create report</button></form>`, '');
}
async function showAddProspectMember() {
  await ensureProspectSupport();
  const existing = new Set(state.prospect.members.map(m => m.user_id));
  const users = state.users.filter(u => !existing.has(u.id)).map(u => `<option value="${u.id}">${esc(u.display_name || u.username)} - ${esc(u.email)}</option>`).join('');
  showModal('Add prospect team member', `<form id="prospect-member-form"><div class="field"><label>User</label><select name="user_id" required>${users}</select></div><div class="field"><label>Scope</label><select name="role_scope"><option>CONTRIBUTOR</option><option>REVIEWER</option><option>OWNER</option></select></div><button class="btn btn-primary btn-wide" type="submit">Add or update member</button></form>`, '');
}

function showProspectLogoUpload() {
  const p = state.prospect.prospect;
  showModal('Upload prospect logo', `<p>Upload a PNG, JPG, or other browser-supported image. The logo will appear in this prospect header.</p><form id="prospect-logo-form"><input type="hidden" name="prospect_id" value="${p.id}"><div class="field"><label>Logo image</label><input name="file" type="file" accept="image/*" required></div><button class="btn btn-primary btn-wide" type="submit">Upload logo</button></form>`, '');
}

function showArchiveProspect() {
  const p=state.prospect.prospect;
  showModal('Archive prospect workspace', `<p>Archiving removes the workspace from active work while preserving its reports, evidence, and audit history.</p><form id="archive-prospect-form"><div class="field"><label>Reason</label><textarea name="reason"></textarea></div><button class="btn btn-secondary btn-wide" type="submit">Archive ${esc(p.name)}</button></form>`, '');
}
function showDeleteReport() {
  const report=state.report.report;
  showModal('Permanently delete report', `<p>This action is restricted to draft or merged source reports. Stored evidence and generated documents linked only to this report will also be deleted.</p><form id="delete-report-form"><div class="field"><label>Type the report title to confirm</label><input name="confirm_title" required></div><button class="btn btn-danger btn-wide" type="submit">Permanently delete report</button></form>`, '');
}

function reportStatusBadge(value) {
  const cls = value === 'FINALIZED' ? 'badge-success' : value === 'READY_FOR_REVIEW' ? 'badge-warning' : value === 'MERGED' ? 'badge-warning' : 'badge-cyan';
  return `<span class="badge ${cls}">${esc(value.replaceAll('_',' '))}</span>`;
}

function reportStatusControl(report) {
  const stateValue = report.report.state;
  if (canReview(report.access_scope) && ['DRAFT','READY_FOR_REVIEW'].includes(stateValue)) {
    return `<label class="report-status-control"><span>Report status</span><select data-action="report-status" aria-label="Report status"><option value="DRAFT" ${stateValue==='DRAFT'?'selected':''}>Draft</option><option value="READY_FOR_REVIEW" ${stateValue==='READY_FOR_REVIEW'?'selected':''}>Ready for review</option></select></label>`;
  }
  return reportStatusBadge(stateValue);
}

async function loadReport(id) {
  const requests = [api(`/api/reports/${id}`), api('/api/capabilities')];
  if (!state.users.length) requests.push(api('/api/users'));
  const results = await Promise.all(requests);
  state.report = results[0]; state.capabilities = results[1];
  if (results[2]) state.users = results[2];
  try { state.aiStatus = await api('/api/ai/status'); } catch { state.aiStatus = null; }
  try { state.storageStatus = await api('/api/storage/status'); } catch { state.storageStatus = null; }
}

function getActiveSection(sectionId) {
  const sections = state.report.sections.filter(s => s.state !== 'REMOVED');
  return state.report.sections.find(s => s.id === sectionId) || sections[0] || state.report.sections[0];
}

function quickEntryContent() {
  const reportId = state.report.report.id;
  const selectedArea = getQuickEntryArea(reportId);
  const areaOptions = QUICK_ENTRY_AREAS.map(area => `<option value="${area.value}" ${area.value === selectedArea ? 'selected' : ''}>${esc(area.label)}</option>`).join('');
  return `
    <div class="mobile-section-select"><label class="sr-only" for="mobile-section">Screen or section</label><select id="mobile-section" data-action="mobile-section">${reportSectionOptions('quick-entry')}</select></div>
    <section class="card quick-entry-card quick-entry-area-card">
      <div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">FIELD CAPTURE</span></div><h2>Quick Entry</h2><p class="help">Choose an operational area once, then capture multiple notes, photographs, and attachments directly into that report section.</p></div></div>
      <div class="field quick-entry-area"><label for="quick-entry-area">Area of operation</label><select id="quick-entry-area" data-action="quick-entry-area" required><option value="">Select area of operation</option>${areaOptions}</select></div>
    </section>
    <section class="card quick-entry-card">
      <div class="section-head"><div><h2>Quick Field Capture</h2><p class="help">Capture a field observation now and refine it later in the destination report section.</p></div></div>
      <form id="quick-entry-note-form">
        <div class="field"><label for="quick-entry-finding-type">Type</label><select id="quick-entry-finding-type" name="finding_type"><option>OBSERVATION</option><option>PAIN_POINT</option><option>RISK</option><option>GAP</option><option>STRENGTH</option><option>OPPORTUNITY</option></select></div>
        <div class="field"><label for="quick-entry-note">Note</label><textarea id="quick-entry-note" class="quick-entry-note" name="note" required placeholder="Capture the observation, issue, strength, risk, or opportunity."></textarea></div>
        <div class="quick-entry-submit"><button class="btn btn-primary" type="submit">Capture Note</button></div>
      </form>
    </section>
    <section class="card quick-entry-card">
      <div class="section-head"><div><h2>Photographs and Attachments</h2><p class="help">Use the device camera for live capture or select an existing photograph or supported document.</p></div></div>
      <div class="field"><label for="quick-entry-caption">Optional caption</label><input id="quick-entry-caption" name="caption" placeholder="What does this photograph or attachment show?"></div>
      <input id="quick-entry-camera" class="hidden-file-input" type="file" accept="image/*" capture="environment">
      <input id="quick-entry-file" class="hidden-file-input" type="file" accept="${QUICK_ENTRY_FILE_ACCEPT}" multiple>
      <div class="quick-entry-actions"><button class="btn btn-primary" type="button" data-action="quick-take-photo">Take Photo</button><button class="btn btn-secondary" type="button" data-action="quick-choose-file">Choose File</button></div>
    </section>`;
}

function sectionOriginalInputSummary(section) {
  const report = state.report;
  const parts = [];
  if (section.narrative?.trim()) parts.push(`SECTION NARRATIVE\n${section.narrative.trim()}`);
  const answered = (section.responses || []).filter(item => (item.narrative || '').trim() || item.payload);
  if (answered.length) parts.push(`GUIDED DISCOVERY RESPONSES\n${answered.map(item => `${item.question}\n${item.narrative || JSON.stringify(item.payload || {})}`).join('\n\n')}`);
  const findings = report.findings.filter(item => item.section_id === section.id && item.status !== 'REJECTED');
  if (findings.length) parts.push(`FINDINGS\n${findings.map(item => `${item.finding_type.replaceAll('_',' ')}: ${item.statement}${item.impact ? `\nImpact noted: ${item.impact}` : ''}`).join('\n\n')}`);
  const metrics = report.metrics.filter(item => item.section_id === section.id);
  if (metrics.length) parts.push(`METRICS\n${metrics.map(item => `${item.name}: ${item.value_text ?? item.value_numeric ?? ''}${item.unit ? ` ${item.unit}` : ''}${item.period ? ` (${item.period})` : ''}`).join('\n')}`);
  return parts.join('\n\n') || 'No written observations have been entered yet. You can still use selected photographs as evidence.';
}


function sectionObservationSources(section) {
  const sources = [];
  if (section.narrative?.trim()) {
    sources.push({ref:'section:narrative', type:'OBSERVATION', label:'Observation — Current operations narrative', statement:section.narrative.trim(), general:true});
  }
  for (const response of section.responses || []) {
    const text = (response.narrative || '').trim() || (response.payload ? JSON.stringify(response.payload) : '');
    if (!text) continue;
    sources.push({ref:`response:${response.id}`, type:'OBSERVATION', label:`Observation — ${response.question}`, statement:text, general:true});
  }
  for (const finding of state.report.findings.filter(item => item.section_id === section.id && item.status !== 'REJECTED')) {
    sources.push({ref:`finding:${finding.id}`, type:finding.finding_type, label:`${finding.finding_type.replaceAll('_',' ')} — ${finding.statement}`, statement:finding.statement, general:false, findingId:finding.id});
  }
  return sources;
}


function benefitCategoryLabel(value) {
  return String(value || 'OPERATIONAL_EFFICIENCY').replaceAll('_',' ').toLowerCase().replace(/\b\w/g, char => char.toUpperCase());
}

function sectionBenefitSources(section) {
  const sources = sectionObservationSources(section).map(item => ({
    ref:item.ref,
    label:item.label,
    statement:item.statement,
    type:item.general ? 'GENERAL_OBSERVATION' : 'FINDING',
  }));
  for (const mapping of state.report.capability_mappings.filter(item => item.section_id === section.id && item.approval_state === 'APPROVED')) {
    sources.push({ref:`mapping:${mapping.id}`, label:`${mapping.capability_code} — ${mapping.capability_name}`, statement:mapping.rationale, type:'CAPABILITY_MAPPING'});
  }
  if (section.cloud_inventory_approach?.id) {
    sources.push({ref:`solution:${section.cloud_inventory_approach.id}`, label:'Accepted Cloud Inventory approach', statement:section.cloud_inventory_approach.text, type:'SOLUTION_APPROACH'});
  }
  for (const metric of state.report.metrics.filter(item => item.section_id === section.id)) {
    const value = metric.value_text ?? metric.value_numeric ?? '';
    sources.push({ref:`metric:${metric.id}`, label:metric.name, statement:`${metric.name}: ${value}${metric.unit ? ` ${metric.unit}` : ''}`, type:'METRIC'});
  }
  return sources;
}

function demoPriorityForSection(sectionId) {
  return state.report.demo_section_priorities?.find(item => item.section_id === sectionId) || null;
}

function sectionAiPhotos(section) {
  return state.report.evidence.filter(item => item.section_id === section.id && item.file?.mime_type?.startsWith('image/'));
}

function aiSourceRefLabel(ref, section) {
  if (!ref) return '';
  if (typeof ref === 'object') return ref.label || ref.ref || '';
  if (ref === 'section:narrative') return 'Section narrative';
  const [kind,id] = String(ref).split(':',2);
  if (kind === 'response') return section.responses.find(item => item.id === id)?.question || ref;
  if (kind === 'finding') return state.report.findings.find(item => item.id === id)?.statement || ref;
  if (kind === 'metric') return state.report.metrics.find(item => item.id === id)?.name || ref;
  if (kind === 'mapping') { const item=state.report.capability_mappings.find(row=>row.id===id); return item ? `${item.capability_code} — ${item.capability_name}` : ref; }
  if (kind === 'solution') return 'Accepted Cloud Inventory approach';
  if (kind === 'benefit') return state.report.benefits.find(item => item.id === id)?.statement || ref;
  if (kind === 'evidence') return state.report.evidence.find(item => item.id === id)?.caption || 'Section photograph';
  return ref;
}

function renderAiEnhancementResult(job, section) {
  const result = job?.suggestion?.content || {};
  const enhancedText = result.enhanced_text || result.suggested_text || '';
  const target = document.getElementById('ai-enhanced-output');
  if (!target) return;
  const passed = result.verification_status === 'PASSED' && result.accept_allowed !== false;
  const sources = result.source_refs || [];
  const gaps = result.gaps || [];
  const unsupported = result.unsupported_claims || [];
  target.innerHTML = `
    <div class="ai-result-head"><span class="badge ${passed ? 'badge-success' : 'badge-danger'}">${esc(result.verification_status || 'REVIEW REQUIRED')}</span><button class="btn btn-ghost btn-small" type="button" data-action="speak-ai-text" ${enhancedText ? '' : 'disabled'}>🔊 Read aloud</button></div>
    <textarea id="ai-enhanced-text" class="ai-comparison-text" readonly>${esc(enhancedText)}</textarea>
    ${sources.length ? `<div class="ai-trace"><strong>Sources used</strong><ul>${sources.map(item => `<li>${esc(aiSourceRefLabel(item, section))}</li>`).join('')}</ul></div>` : ''}
    ${gaps.length ? `<div class="ai-trace"><strong>Information gaps retained</strong><ul>${gaps.map(item => `<li>${esc(typeof item === 'string' ? item : JSON.stringify(item))}</li>`).join('')}</ul></div>` : ''}
    ${unsupported.length ? `<div class="validation-item ERROR"><strong>Unsupported claims detected.</strong><ul>${unsupported.map(item => `<li>${esc(item.text || JSON.stringify(item))}${item.reason ? ` — ${esc(item.reason)}` : ''}</li>`).join('')}</ul><p>Acceptance is disabled until the text is regenerated or refined without unsupported claims.</p></div>` : ''}
    <div class="field ai-refinement-field"><label for="ai-refinement-instruction">Refine the AI wording</label><textarea id="ai-refinement-instruction" placeholder="For example: Make this more concise, use a neutral customer-facing tone, or emphasize the manual handoffs without adding new facts."></textarea></div>
    <div class="card-actions"><button class="btn btn-secondary" type="button" data-action="refine-ai-enhancement" data-suggestion-id="${esc(job.suggestion.id)}">Refine</button><button class="btn btn-primary" type="button" data-action="accept-ai-enhancement" data-suggestion-id="${esc(job.suggestion.id)}" ${passed ? '' : 'disabled'}>Accept enhanced text</button></div>`;
  target.dataset.enhancedText = enhancedText;
}

async function pollAiEnhancement(jobId, section, token) {
  const output = document.getElementById('ai-enhanced-output');
  for (let attempt = 0; attempt < 90; attempt += 1) {
    if (token !== state.aiEnhancementPollToken || !document.getElementById('ai-enhancement-modal')) return;
    const job = await api(`/api/ai-jobs/${jobId}`, {}, false);
    if (job.status === 'COMPLETED' && job.suggestion) {
      renderAiEnhancementResult(job, section);
      return;
    }
    if (['FAILED','BLOCKED'].includes(job.status)) {
      if (output) output.innerHTML = `<div class="validation-item ERROR"><strong>AI enhancement failed.</strong><p>${esc(job.error || job.policy_decision?.reason || 'The AI job could not be completed.')}</p></div>`;
      return;
    }
    if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Analyzing entered observations and selected photographs…</p></div>';
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (output) output.innerHTML = '<div class="validation-item ERROR">AI enhancement timed out. You can close this window and try again.</div>';
}

async function requestAiEnhancement(section, parentSuggestionId = null) {
  const selectedEvidence = Array.from(document.querySelectorAll('#ai-photo-picker input[type="checkbox"]:checked')).map(item => item.value);
  const instruction = document.getElementById('ai-refinement-instruction')?.value?.trim() || null;
  const output = document.getElementById('ai-enhanced-output');
  if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Analyzing entered observations and selected photographs…</p></div>';
  const result = await api(`/api/reports/${state.report.report.id}/ai`, {
    method:'POST',
    body:{
      section_id:section.id,
      purpose:'OBSERVATION_ENHANCEMENT',
      instructions:instruction,
      evidence_ids:selectedEvidence,
      parent_suggestion_id:parentSuggestionId,
    },
  }, false);
  const token = ++state.aiEnhancementPollToken;
  await pollAiEnhancement(result.ai_job_id, section, token);
}

async function showAiEnhancement(section) {
  if (!navigator.onLine) throw new Error('AI enhancement requires an online connection. Your captured observations remain available offline.');
  if (!state.aiStatus?.policy?.allowed) throw new Error(state.aiStatus?.policy?.reason || 'AI enhancement is not configured for this environment.');
  const photos = sectionAiPhotos(section);
  closeModal();
  const wrap = document.createElement('div');
  wrap.id = 'modal-root';
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `<section id="ai-enhancement-modal" class="modal ai-enhancement-modal" role="dialog" aria-modal="true" aria-label="AI enhance ${esc(section.title)}">
    <div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">AI OBSERVATION ENHANCEMENT</span><span>${esc(section.title)}</span></div><h2>Compare and refine current-operations wording</h2><p class="help">AI is restricted to the entered observations and selected photographs. Original input is retained and the accepted result remains subject to human review.</p></div><button class="btn btn-ghost btn-small" data-action="close-modal">Close</button></div>
    <div id="ai-photo-picker" class="ai-photo-picker"><strong>Photographs available to AI</strong>${photos.length ? `<div class="ai-photo-grid">${photos.map(item => `<label class="ai-photo-option"><input type="checkbox" value="${item.id}" checked><span>${item.file ? `<img src="/api/files/${item.file.id}?inline=true" alt="${esc(item.caption || item.file.file_name)}">` : ''}<small>${esc(item.caption || item.file?.file_name || 'Photograph')}</small></span></label>`).join('')}</div>` : '<p class="help">No photographs are attached to this section. The enhancement will use written observations only.</p>'}</div>
    <div class="ai-comparison-grid">
      <section class="ai-comparison-panel"><div class="ai-panel-title"><h3>Original entered content</h3><span class="badge">Retained</span></div><textarea class="ai-comparison-text" readonly>${esc(sectionOriginalInputSummary(section))}</textarea></section>
      <section class="ai-comparison-panel"><div class="ai-panel-title"><h3>AI-enhanced wording</h3><span class="help">Human approval required</span></div><div id="ai-enhanced-output"><div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Preparing enhancement…</p></div></div></section>
    </div>
  </section>`;
  document.body.appendChild(wrap);
  await requestAiEnhancement(section);
}

async function showSectionContentHistory(section) {
  const versions = await api(`/api/reports/${state.report.report.id}/sections/${section.id}/content-versions`);
  showModal('Current Operations Version History', versions.length ? `<div class="version-history">${versions.map(item => `<article class="finding"><div class="section-head"><div><strong>Version ${item.version}</strong><div class="card-meta"><span>${esc(item.source_type.replaceAll('_',' '))}</span><span>${esc(fmtDateTime(item.created_at))}</span></div></div>${item.is_current ? '<span class="badge badge-success">CURRENT</span>' : ''}</div><p class="version-text">${esc(item.text || '(blank original narrative)').replaceAll('\n','<br>')}</p></article>`).join('')}</div>` : '<p>No accepted AI enhancement history exists for this section yet.</p>', '');
}


function renderSolutionApproachResult(job, section) {
  const result = job?.suggestion?.content || {};
  const solutionText = result.solution_text || result.suggested_text || '';
  const target = document.getElementById('ai-solution-output');
  if (!target) return;
  const passed = result.verification_status === 'PASSED' && result.accept_allowed !== false;
  const mappings = result.capability_mappings || [];
  const sources = result.source_refs || [];
  const gaps = result.gaps || [];
  const unsupported = result.unsupported_claims || [];
  const canAccept = passed && canReview(state.report.access_scope);
  target.innerHTML = `
    <div class="ai-result-head"><span class="badge ${passed ? 'badge-success' : 'badge-danger'}">${esc(result.verification_status || 'REVIEW REQUIRED')}</span><button class="btn btn-ghost btn-small" type="button" data-action="speak-ai-text" ${solutionText ? '' : 'disabled'}>🔊 Read aloud</button></div>
    <textarea id="ai-solution-text" class="ai-comparison-text" readonly>${esc(solutionText)}</textarea>
    ${mappings.length ? `<div class="ai-trace"><strong>Proposed capability mappings</strong><ul>${mappings.map(item => { const cap=state.capabilities.find(c=>c.id===item.capability_id); return `<li><strong>${esc(cap ? `${cap.capability_code} — ${cap.name}` : item.capability_id)}</strong><br>${esc(aiSourceRefLabel(item.source_ref, section))}<br><span class="help">${esc(item.rationale || '')}</span></li>`; }).join('')}</ul></div>` : ''}
    ${sources.length ? `<div class="ai-trace"><strong>Grounding sources</strong><ul>${sources.map(item => `<li>${esc(aiSourceRefLabel(item, section))}</li>`).join('')}</ul></div>` : ''}
    ${gaps.length ? `<div class="ai-trace"><strong>Gaps or confirmations required</strong><ul>${gaps.map(item => `<li>${esc(typeof item === 'string' ? item : JSON.stringify(item))}</li>`).join('')}</ul></div>` : ''}
    ${unsupported.length ? `<div class="validation-item ERROR"><strong>Unsupported product claims or mappings detected.</strong><ul>${unsupported.map(item => `<li>${esc(item.text || JSON.stringify(item))}${item.reason ? ` — ${esc(item.reason)}` : ''}</li>`).join('')}</ul><p>Acceptance is disabled until the approach is regenerated or refined.</p></div>` : ''}
    ${!canReview(state.report.access_scope) ? '<div class="validation-item WARNING">A Reviewer or Owner must approve customer-facing Cloud Inventory solution wording.</div>' : ''}
    <div class="field ai-refinement-field"><label for="ai-solution-refinement">Refine the Cloud Inventory approach</label><textarea id="ai-solution-refinement" placeholder="For example: Emphasize directed picking, explain the ERP dependency, or make this more concise without adding unsupported capability claims."></textarea></div>
    <div class="card-actions"><button class="btn btn-secondary" type="button" data-action="refine-solution-approach" data-suggestion-id="${esc(job.suggestion.id)}">Refine</button><button class="btn btn-primary" type="button" data-action="accept-solution-approach" data-suggestion-id="${esc(job.suggestion.id)}" ${canAccept ? '' : 'disabled'}>Accept Cloud Inventory approach</button></div>`;
  target.dataset.enhancedText = solutionText;
}

async function pollSolutionApproach(jobId, section, token) {
  const output = document.getElementById('ai-solution-output');
  for (let attempt = 0; attempt < 90; attempt += 1) {
    if (token !== state.aiEnhancementPollToken || !document.getElementById('ai-solution-modal')) return;
    const job = await api(`/api/ai-jobs/${jobId}`, {}, false);
    if (job.status === 'COMPLETED' && job.suggestion) {
      renderSolutionApproachResult(job, section);
      return;
    }
    if (['FAILED','BLOCKED'].includes(job.status)) {
      if (output) output.innerHTML = `<div class="validation-item ERROR"><strong>Cloud Inventory approach generation failed.</strong><p>${esc(job.error || job.policy_decision?.reason || 'The AI job could not be completed.')}</p></div>`;
      return;
    }
    if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Assessing operational observations against approved Cloud Inventory capabilities and knowledge…</p></div>';
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (output) output.innerHTML = '<div class="validation-item ERROR">Cloud Inventory approach generation timed out. You can close this window and try again.</div>';
}

async function requestSolutionApproach(section, parentSuggestionId = null) {
  const instruction = document.getElementById('ai-solution-refinement')?.value?.trim() || null;
  const output = document.getElementById('ai-solution-output');
  if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Assessing operational observations against approved Cloud Inventory capabilities and knowledge…</p></div>';
  const result = await api(`/api/reports/${state.report.report.id}/ai`, {
    method:'POST',
    body:{
      section_id:section.id,
      purpose:'SOLUTION_APPROACH',
      instructions:instruction,
      parent_suggestion_id:parentSuggestionId,
    },
  }, false);
  const token = ++state.aiEnhancementPollToken;
  await pollSolutionApproach(result.ai_job_id, section, token);
}

async function showSolutionApproach(section) {
  if (!navigator.onLine) throw new Error('Cloud Inventory approach generation requires an online connection.');
  if (!state.aiStatus?.policy?.allowed) throw new Error(state.aiStatus?.policy?.reason || 'AI enhancement is not configured for this environment.');
  const approvedCapabilities = state.capabilities.filter(item => item.status === 'APPROVED');
  if (!approvedCapabilities.length) throw new Error('No approved Cloud Inventory capabilities are available. Review the capability catalog in Administration first.');
  const sources = sectionObservationSources(section);
  if (!sources.length) throw new Error('Enter current operations notes, guided responses, or findings before generating a Cloud Inventory approach.');
  const current = section.cloud_inventory_approach?.text || '';
  closeModal();
  const wrap = document.createElement('div');
  wrap.id = 'modal-root';
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `<section id="ai-solution-modal" class="modal ai-enhancement-modal" role="dialog" aria-modal="true" aria-label="Generate Cloud Inventory approach for ${esc(section.title)}">
    <div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">CLOUD INVENTORY SOLUTION INTELLIGENCE</span><span>${esc(section.title)}</span></div><h2>Generate and refine the Cloud Inventory approach</h2><p class="help">The AI is restricted to approved Cloud Inventory capabilities, approved knowledge, and the observations captured in this section. General notes and guided responses are treated as Observations for functionality mapping.</p></div><button class="btn btn-ghost btn-small" data-action="close-modal">Close</button></div>
    <div class="ai-comparison-grid">
      <section class="ai-comparison-panel"><div class="ai-panel-title"><h3>Operational context and current approach</h3><span class="badge">Source controlled</span></div><textarea class="ai-comparison-text" readonly>${esc(sectionOriginalInputSummary(section))}</textarea>${current ? `<div class="ai-trace"><strong>Current accepted Cloud Inventory approach</strong><p>${esc(current)}</p></div>` : '<p class="help">No Cloud Inventory approach has been accepted for this section yet.</p>'}</section>
      <section class="ai-comparison-panel"><div class="ai-panel-title"><h3>AI-proposed Cloud Inventory approach</h3><span class="help">Reviewer approval required</span></div><div id="ai-solution-output"><div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Preparing solution assessment…</p></div></div></section>
    </div>
  </section>`;
  document.body.appendChild(wrap);
  await requestSolutionApproach(section);
}

async function showSolutionContentHistory(section) {
  const versions = await api(`/api/reports/${state.report.report.id}/sections/${section.id}/content-versions?content_type=CLOUD_INVENTORY_APPROACH`);
  showModal('Cloud Inventory Approach Version History', versions.length ? `<div class="version-history">${versions.map(item => `<article class="finding"><div class="section-head"><div><strong>Version ${item.version}</strong><div class="card-meta"><span>${esc(item.source_type.replaceAll('_',' '))}</span><span>${esc(fmtDateTime(item.created_at))}</span></div></div>${item.is_current ? '<span class="badge badge-success">CURRENT</span>' : ''}</div><p class="version-text">${esc(item.text || '(blank)').replaceAll('\n','<br>')}</p></article>`).join('')}</div>` : '<p>No saved Cloud Inventory approach history exists for this section yet.</p>', '');
}


function renderTargetedBenefitsResult(job, section) {
  const result = job?.suggestion?.content || {};
  const benefits = result.benefits || result.benefit_statements || [];
  const target = document.getElementById('ai-benefits-output');
  if (!target) return;
  const passed = result.verification_status === 'PASSED' && result.accept_allowed !== false;
  const unsupported = result.unsupported_claims || [];
  const gaps = result.gaps || [];
  const readText = benefits.map(item => item.statement || item.text || '').filter(Boolean).join('. ');
  target.innerHTML = `
    <div class="ai-result-head"><span class="badge ${passed ? 'badge-success' : 'badge-danger'}">${esc(result.verification_status || 'REVIEW REQUIRED')}</span><button class="btn btn-ghost btn-small" type="button" data-action="speak-ai-text" ${readText ? '' : 'disabled'}>🔊 Read aloud</button></div>
    ${benefits.length ? `<div class="benefit-selection-list">${benefits.map((item,index)=>`<label class="benefit-selection-item"><input type="checkbox" data-benefit-index="${index}" checked ${passed?'':'disabled'}><span><strong>${esc(benefitCategoryLabel(item.category))}</strong><p>${esc(item.statement || item.text || '')}</p><div class="card-meta"><span>${esc(item.measure_type || 'QUALITATIVE')}</span><span>Confidence: ${esc(item.confidence || 'MEDIUM')}</span></div>${(item.source_refs||[]).length?`<small>Based on: ${(item.source_refs||[]).map(ref=>esc(aiSourceRefLabel(ref,section))).join('; ')}</small>`:''}</span></label>`).join('')}</div>` : '<p class="help">No targeted benefits were returned.</p>'}
    ${gaps.length ? `<div class="ai-trace"><strong>Information gaps retained</strong><ul>${gaps.map(item=>`<li>${esc(typeof item==='string'?item:JSON.stringify(item))}</li>`).join('')}</ul></div>` : ''}
    ${unsupported.length ? `<div class="validation-item ERROR"><strong>Unsupported benefit claims detected.</strong><ul>${unsupported.map(item=>`<li>${esc(item.text || JSON.stringify(item))}${item.reason?` — ${esc(item.reason)}`:''}</li>`).join('')}</ul><p>Acceptance is disabled until the benefits are regenerated or refined.</p></div>` : ''}
    <div class="field ai-refinement-field"><label for="ai-benefits-refinement">Refine the targeted benefits</label><textarea id="ai-benefits-refinement" placeholder="For example: Make these less generic, focus on reducing manual prioritization, or keep all statements qualitative."></textarea></div>
    <div class="card-actions"><button class="btn btn-secondary" type="button" data-action="refine-targeted-benefits" data-suggestion-id="${esc(job.suggestion.id)}">Refine</button><button class="btn btn-primary" type="button" data-action="accept-targeted-benefits" data-suggestion-id="${esc(job.suggestion.id)}" ${passed?'':'disabled'}>Add selected benefits for review</button></div>`;
  target.dataset.enhancedText = readText;
}

async function pollTargetedBenefits(jobId, section, token) {
  const output = document.getElementById('ai-benefits-output');
  for (let attempt = 0; attempt < 90; attempt += 1) {
    if (token !== state.aiEnhancementPollToken || !document.getElementById('ai-benefits-modal')) return;
    const job = await api(`/api/ai-jobs/${jobId}`, {}, false);
    if (job.status === 'COMPLETED' && job.suggestion) { renderTargetedBenefitsResult(job, section); return; }
    if (['FAILED','BLOCKED'].includes(job.status)) {
      if (output) output.innerHTML = `<div class="validation-item ERROR"><strong>Targeted benefit generation failed.</strong><p>${esc(job.error || job.policy_decision?.reason || 'The AI job could not be completed.')}</p></div>`;
      return;
    }
    if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Assessing operational context, approved functionality, and measurable evidence…</p></div>';
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (output) output.innerHTML = '<div class="validation-item ERROR">Targeted benefit generation timed out. You can close this window and try again.</div>';
}

async function requestTargetedBenefits(section, parentSuggestionId = null) {
  const instruction = document.getElementById('ai-benefits-refinement')?.value?.trim() || null;
  const output = document.getElementById('ai-benefits-output');
  if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Assessing operational context, approved functionality, and measurable evidence…</p></div>';
  const result = await api(`/api/reports/${state.report.report.id}/ai`, {method:'POST',body:{section_id:section.id,purpose:'TARGETED_BENEFITS',instructions:instruction,parent_suggestion_id:parentSuggestionId}}, false);
  const token = ++state.aiEnhancementPollToken;
  await pollTargetedBenefits(result.ai_job_id, section, token);
}

async function showTargetedBenefits(section) {
  if (!navigator.onLine) throw new Error('Targeted benefit generation requires an online connection.');
  if (!state.aiStatus?.policy?.allowed) throw new Error(state.aiStatus?.policy?.reason || 'AI enhancement is not configured for this environment.');
  if (!sectionObservationSources(section).length) throw new Error('Enter current operations notes or findings before generating targeted benefits.');
  const approvedMappings = state.report.capability_mappings.filter(item=>item.section_id===section.id && item.approval_state==='APPROVED');
  if (!section.cloud_inventory_approach?.text && !approvedMappings.length) throw new Error('Enter or accept a Cloud Inventory approach, or approve a capability mapping, before generating targeted benefits.');
  const existing = state.report.benefits.filter(item=>item.section_id===section.id && item.approval_state!=='REJECTED');
  closeModal();
  const wrap=document.createElement('div'); wrap.id='modal-root'; wrap.className='modal-backdrop';
  wrap.innerHTML=`<section id="ai-benefits-modal" class="modal ai-enhancement-modal" role="dialog" aria-modal="true" aria-label="Generate targeted benefits for ${esc(section.title)}">
    <div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">TARGETED BENEFITS</span><span>${esc(section.title)}</span></div><h2>Generate evidence-based operational benefits</h2><p class="help">AI uses only the accepted current operation, Cloud Inventory approach, approved mappings, and recorded metrics. Unsupported numeric improvements and guarantees are blocked.</p></div><button class="btn btn-ghost btn-small" data-action="close-modal">Close</button></div>
    <div class="ai-comparison-grid"><section class="ai-comparison-panel"><div class="ai-panel-title"><h3>Operational and solution context</h3><span class="badge">Source controlled</span></div><textarea class="ai-comparison-text" readonly>${esc(sectionOriginalInputSummary(section))}</textarea>${section.cloud_inventory_approach?.text?`<div class="ai-trace"><strong>Accepted Cloud Inventory approach</strong><p>${esc(section.cloud_inventory_approach.text)}</p></div>`:''}${existing.length?`<div class="ai-trace"><strong>Existing benefit statements</strong><ul>${existing.map(item=>`<li>${esc(item.statement)}</li>`).join('')}</ul></div>`:''}</section><section class="ai-comparison-panel"><div class="ai-panel-title"><h3>AI-proposed targeted benefits</h3><span class="help">Human selection and review required</span></div><div id="ai-benefits-output"><div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Preparing benefit assessment…</p></div></div></section></div>
  </section>`;
  document.body.appendChild(wrap);
  await requestTargetedBenefits(section);
}

function renderDemoPlanResult(job) {
  const result=job?.suggestion?.content||{}; const plan=result.demo_plan||{}; const output=document.getElementById('ai-demo-plan-output'); if(!output)return;
  const passed=result.verification_status==='PASSED'&&result.accept_allowed!==false; const unsupported=result.unsupported_claims||[];
  const flow=plan.flow||[]; const readText=[...(plan.objectives||[]),...flow.map(item=>`${item.operational_area}. ${item.functionality}. ${item.value_statement}`)].join('. ');
  output.innerHTML=`<div class="ai-result-head"><span class="badge ${passed?'badge-success':'badge-danger'}">${esc(result.verification_status||'REVIEW REQUIRED')}</span><button class="btn btn-ghost btn-small" type="button" data-action="speak-ai-text" ${readText?'':'disabled'}>🔊 Read aloud</button></div>
    <h3>${esc(plan.title||'Cloud Inventory Solution Demonstration Plan')}</h3><div class="card-meta"><span>${esc(plan.duration_minutes||'')} minutes</span><span>${esc(plan.audience||'Audience not specified')}</span></div>
    ${(plan.objectives||[]).length?`<div class="ai-trace"><strong>Objectives</strong><ul>${plan.objectives.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}
    ${flow.length?`<div class="demo-flow-preview">${flow.map(item=>`<article class="finding"><div class="section-head"><div><strong>${esc(item.sequence)}. ${esc(item.operational_area)}</strong><div class="card-meta"><span>${esc(String(item.priority||'').replaceAll('_',' '))}</span>${item.estimated_minutes?`<span>${esc(item.estimated_minutes)} min</span>`:''}</div></div></div><p><strong>Show:</strong> ${esc(item.functionality||'')}</p><p><strong>Value:</strong> ${esc(item.value_statement||'')}</p><p class="help">${esc(item.scenario||'')}</p></article>`).join('')}</div>`:'<p class="help">No valid demo flow was returned.</p>'}
    ${(plan.risks_to_avoid||[]).length?`<div class="validation-item WARNING"><strong>Claims and risks to avoid</strong><ul>${plan.risks_to_avoid.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}
    ${(plan.open_questions||[]).length?`<div class="ai-trace"><strong>Open questions and gaps</strong><ul>${plan.open_questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}
    ${unsupported.length?`<div class="validation-item ERROR"><strong>Unsupported demo claims or priority conflicts detected.</strong><ul>${unsupported.map(item=>`<li>${esc(item.text||JSON.stringify(item))}${item.reason?` — ${esc(item.reason)}`:''}</li>`).join('')}</ul></div>`:''}
    <div class="field ai-refinement-field"><label for="ai-demo-refinement">Refine the demo plan</label><textarea id="ai-demo-refinement" placeholder="For example: Put receiving first, reduce the plan to 45 minutes, or make cycle counting a must-show scenario."></textarea></div>
    <div class="card-actions"><button class="btn btn-secondary" type="button" data-action="refine-demo-plan" data-suggestion-id="${esc(job.suggestion.id)}">Refine</button><button class="btn btn-primary" type="button" data-action="accept-demo-plan" data-suggestion-id="${esc(job.suggestion.id)}" ${passed?'':'disabled'}>Accept demo plan</button></div>`;
  output.dataset.enhancedText=readText;
}

async function pollDemoPlan(jobId,token){const output=document.getElementById('ai-demo-plan-output');for(let attempt=0;attempt<90;attempt+=1){if(token!==state.aiEnhancementPollToken||!document.getElementById('ai-demo-plan-modal'))return;const job=await api(`/api/ai-jobs/${jobId}`,{},false);if(job.status==='COMPLETED'&&job.suggestion){renderDemoPlanResult(job);return;}if(['FAILED','BLOCKED'].includes(job.status)){if(output)output.innerHTML=`<div class="validation-item ERROR"><strong>Demo plan generation failed.</strong><p>${esc(job.error||job.policy_decision?.reason||'The AI job could not be completed.')}</p></div>`;return;}if(output)output.innerHTML='<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Prioritizing operational areas and building a customer-specific demo flow…</p></div>';await new Promise(resolve=>setTimeout(resolve,1500));}if(output)output.innerHTML='<div class="validation-item ERROR">Demo plan generation timed out. You can close this window and try again.</div>';}

async function requestDemoPlan(parentSuggestionId=null){const instruction=document.getElementById('ai-demo-refinement')?.value?.trim()||null;const output=document.getElementById('ai-demo-plan-output');if(output)output.innerHTML='<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Prioritizing operational areas and building a customer-specific demo flow…</p></div>';const result=await api(`/api/reports/${state.report.report.id}/ai`,{method:'POST',body:{section_id:null,purpose:'DEMO_PLAN',instructions:instruction,parent_suggestion_id:parentSuggestionId}},false);const token=++state.aiEnhancementPollToken;await pollDemoPlan(result.ai_job_id,token);}

async function showDemoPlan(){if(!navigator.onLine)throw new Error('Demo plan generation requires an online connection.');if(!state.aiStatus?.policy?.allowed)throw new Error(state.aiStatus?.policy?.reason||'AI enhancement is not configured for this environment.');if(!state.report.capability_mappings.some(item=>item.approval_state==='APPROVED'))throw new Error('Approve at least one capability mapping before generating a demo plan.');closeModal();const wrap=document.createElement('div');wrap.id='modal-root';wrap.className='modal-backdrop';const priorities=state.report.sections.filter(item=>item.state!=='REMOVED').map(section=>{const priority=demoPriorityForSection(section.id);return `<li><strong>${esc(section.title)}</strong> — ${esc(String(priority?.priority||'OPTIONAL').replaceAll('_',' '))}${priority?.user_notes?`<br><span class="help">${esc(priority.user_notes)}</span>`:''}</li>`;}).join('');wrap.innerHTML=`<section id="ai-demo-plan-modal" class="modal ai-enhancement-modal" role="dialog" aria-modal="true" aria-label="Generate demo preparation plan"><div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">DEMO ORCHESTRATION</span><span>${esc(state.report.report.title)}</span></div><h2>Create the customer-specific demo flow</h2><p class="help">The plan uses accepted operational content, approved capability mappings, approved benefits, and the priorities entered by the presales team.</p></div><button class="btn btn-ghost btn-small" data-action="close-modal">Close</button></div><div class="ai-comparison-grid"><section class="ai-comparison-panel"><div class="ai-panel-title"><h3>Demo inputs and priorities</h3><span class="badge">Internal only</span></div><p><strong>Audience:</strong> ${esc(state.report.demo_settings?.audience||'Not specified')}</p><p><strong>Duration:</strong> ${esc(state.report.demo_settings?.duration_minutes||45)} minutes</p><p><strong>Additional priorities:</strong> ${esc(state.report.demo_settings?.additional_priorities||'None entered')}</p><ul>${priorities}</ul></section><section class="ai-comparison-panel"><div class="ai-panel-title"><h3>AI-proposed demo plan</h3><span class="help">Human approval required</span></div><div id="ai-demo-plan-output"><div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Preparing demo plan…</p></div></div></section></div></section>`;document.body.appendChild(wrap);await requestDemoPlan();}

async function showDemoPlanHistory(){const versions=await api(`/api/reports/${state.report.report.id}/demo-plan-versions`);showModal('Demo Plan Version History',versions.length?`<div class="version-history">${versions.map(item=>`<article class="finding"><div class="section-head"><div><strong>Version ${item.version}</strong><div class="card-meta"><span>${esc(item.source_type.replaceAll('_',' '))}</span><span>${esc(fmtDateTime(item.created_at))}</span></div></div>${item.is_current?'<span class="badge badge-success">CURRENT</span>':''}</div><p>${esc(item.content?.title||'Demo plan')}</p><p class="help">${esc((item.content?.flow||[]).length)} flow items</p></article>`).join('')}</div>`:'<p>No accepted demo plan history exists yet.</p>','');}


function readinessBadge(status) {
  const cls = status === 'READY' ? 'badge-success' : status === 'REVIEW_REQUIRED' ? 'badge-warning' : status === 'MISSING' ? 'badge-danger' : status === 'NOT_APPLICABLE' ? '' : 'badge-cyan';
  return `<span class="badge ${cls}">${esc(String(status || 'PARTIAL').replaceAll('_',' '))}</span>`;
}

async function saveExecutiveSummary(value, statusElement) {
  const expectedVersion = state.report.executive_summary?.version ?? null;
  try {
    if (statusElement) statusElement.textContent = 'Saving...';
    const result = await api(`/api/reports/${state.report.report.id}/content`, {
      method:'PUT',
      body:{content_type:'EXECUTIVE_SUMMARY',text:value,expected_version:expectedVersion},
    });
    if (statusElement) statusElement.textContent = result.offlineQueued ? 'Queued offline' : 'Saved';
    if (!result.offlineQueued) {
      state.report.executive_summary = {id:result.id,version:result.version,text:value,source_type:'USER',source_refs:[],created_at:new Date().toISOString()};
      state.report.report.revision = result.report_revision;
    }
    return result;
  } catch (error) {
    if (statusElement) statusElement.textContent = error.status === 409 ? 'Conflict - reloading' : 'Save failed';
    toast(error.status === 409 ? 'The executive summary changed in another session. The latest version is being loaded.' : error.message, 'error');
    if (error.status === 409) setTimeout(() => renderReport(state.report.report.id, 'report-preview'), 350);
    throw error;
  }
}

function scheduleExecutiveSummarySave(value, statusElement) {
  const key = 'report:executive-summary';
  clearTimeout(state.saveTimers.get(key));
  if (statusElement) statusElement.textContent = 'Unsaved changes...';
  const timer = setTimeout(() => saveExecutiveSummary(value, statusElement).catch(() => {}), 900);
  state.saveTimers.set(key, timer);
}

async function flushExecutiveSummarySave() {
  const editor = document.getElementById('executive-summary-editor');
  if (!editor) return;
  const key = 'report:executive-summary';
  clearTimeout(state.saveTimers.get(key));
  state.saveTimers.delete(key);
  if (editor.value.trim() === (state.report.executive_summary?.text || '').trim()) return;
  await saveExecutiveSummary(editor.value, document.getElementById('executive-summary-save'));
}

function renderExecutiveSummaryResult(job) {
  const result = job?.suggestion?.content || {};
  const output = document.getElementById('ai-executive-summary-output');
  if (!output) return;
  const text = result.summary_text || result.suggested_text || '';
  const passed = result.verification_status === 'PASSED' && result.accept_allowed !== false;
  const refs = result.source_refs || [];
  const gaps = result.gaps || [];
  const unsupported = result.unsupported_claims || [];
  output.innerHTML = `<div class="ai-result-head"><span class="badge ${passed?'badge-success':'badge-danger'}">${esc(result.verification_status||'REVIEW REQUIRED')}</span><button class="btn btn-ghost btn-small" type="button" data-action="speak-ai-text" ${text?'':'disabled'}>🔊 Read aloud</button></div>
    <textarea id="ai-executive-summary-text" class="ai-comparison-text" readonly>${esc(text)}</textarea>
    ${refs.length?`<div class="ai-trace"><strong>Sources used</strong><ul>${refs.map(item=>`<li>${esc(item.label||item.ref||item)}</li>`).join('')}</ul></div>`:''}
    ${gaps.length?`<div class="validation-item WARNING"><strong>Open dependencies and gaps</strong><ul>${gaps.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}
    ${unsupported.length?`<div class="validation-item ERROR"><strong>Unsupported claims detected</strong><ul>${unsupported.map(item=>`<li>${esc(item.text||JSON.stringify(item))}${item.reason?` — ${esc(item.reason)}`:''}</li>`).join('')}</ul></div>`:''}
    <div class="field ai-refinement-field"><label for="ai-executive-summary-refinement">Refine the summary</label><textarea id="ai-executive-summary-refinement" placeholder="For example: make this more concise, emphasize the operational themes, or make the next steps clearer."></textarea></div>
    <div class="card-actions"><button class="btn btn-secondary" type="button" data-action="refine-executive-summary" data-suggestion-id="${esc(job.suggestion.id)}">Refine</button><button class="btn btn-primary" type="button" data-action="accept-executive-summary" data-suggestion-id="${esc(job.suggestion.id)}" ${passed?'':'disabled'}>Accept executive summary</button></div>`;
  output.dataset.enhancedText = text;
}

async function pollExecutiveSummary(jobId, token) {
  const output = document.getElementById('ai-executive-summary-output');
  for (let attempt=0; attempt<90; attempt+=1) {
    if (token !== state.aiEnhancementPollToken || !document.getElementById('ai-executive-summary-modal')) return;
    const job = await api(`/api/ai-jobs/${jobId}`, {}, false);
    if (job.status === 'COMPLETED' && job.suggestion) { renderExecutiveSummaryResult(job); return; }
    if (['FAILED','BLOCKED'].includes(job.status)) {
      if (output) output.innerHTML = `<div class="validation-item ERROR"><strong>Executive summary generation failed.</strong><p>${esc(job.error||job.policy_decision?.reason||'The AI job could not be completed.')}</p></div>`;
      return;
    }
    if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Synthesizing accepted operational evidence, solution themes, benefits, and open dependencies…</p></div>';
    await new Promise(resolve=>setTimeout(resolve,1500));
  }
  if (output) output.innerHTML = '<div class="validation-item ERROR">Executive summary generation timed out. You can close this window and try again.</div>';
}

async function requestExecutiveSummary(parentSuggestionId=null) {
  const instruction = document.getElementById('ai-executive-summary-refinement')?.value?.trim() || null;
  const output = document.getElementById('ai-executive-summary-output');
  if (output) output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Synthesizing accepted report content…</p></div>';
  const result = await api(`/api/reports/${state.report.report.id}/ai`, {method:'POST',body:{section_id:null,purpose:'EXECUTIVE_SUMMARY',instructions:instruction,parent_suggestion_id:parentSuggestionId}}, false);
  const token = ++state.aiEnhancementPollToken;
  await pollExecutiveSummary(result.ai_job_id, token);
}

async function showExecutiveSummary() {
  if (!navigator.onLine) throw new Error('Executive summary generation requires an online connection.');
  if (!state.aiStatus?.policy?.allowed) throw new Error(state.aiStatus?.policy?.reason || 'AI enhancement is not configured for this environment.');
  await flushExecutiveSummarySave();
  closeModal();
  const wrap=document.createElement('div'); wrap.id='modal-root'; wrap.className='modal-backdrop';
  wrap.innerHTML=`<section id="ai-executive-summary-modal" class="modal ai-enhancement-modal" role="dialog" aria-modal="true" aria-label="Generate executive summary"><div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">EXECUTIVE SUMMARY</span><span>${esc(state.report.report.title)}</span></div><h2>Create the customer-facing executive overview</h2><p class="help">AI uses accepted report content only. Unsupported capabilities, numerical claims, guarantees, and customer facts are blocked.</p></div><button class="btn btn-ghost btn-small" data-action="close-modal">Close</button></div><div class="ai-comparison-grid"><section class="ai-comparison-panel"><div class="ai-panel-title"><h3>Current accepted summary</h3><span class="badge">Version controlled</span></div><textarea class="ai-comparison-text" readonly>${esc(state.report.executive_summary?.text||'No executive summary has been accepted or entered.')}</textarea></section><section class="ai-comparison-panel"><div class="ai-panel-title"><h3>AI-proposed summary</h3><span class="help">Human approval required</span></div><div id="ai-executive-summary-output"><div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Preparing executive summary…</p></div></div></section></div></section>`;
  document.body.appendChild(wrap);
  await requestExecutiveSummary();
}

async function showExecutiveSummaryHistory() {
  const versions=await api(`/api/reports/${state.report.report.id}/content-versions?content_type=EXECUTIVE_SUMMARY`);
  showModal('Executive Summary Version History', versions.length?`<div class="version-history">${versions.map(item=>`<article class="finding"><div class="section-head"><div><strong>Version ${item.version}</strong><div class="card-meta"><span>${esc(item.source_type.replaceAll('_',' '))}</span><span>${esc(fmtDateTime(item.created_at))}</span></div></div>${item.is_current?'<span class="badge badge-success">CURRENT</span>':''}</div><p class="version-text">${esc(item.text||'(blank)').replaceAll('\n','<br>')}</p></article>`).join('')}</div>`:'<p>No executive summary history exists yet.</p>','');
}

function renderReportQualityResult(job) {
  const result=job?.suggestion?.content||{};
  const output=document.getElementById('ai-report-quality-output');
  if(!output)return;
  const issues=result.issues||[];
  const strengths=result.strengths||[];
  const questions=result.follow_up_questions||[];
  const verification=result.verification_status||'REVIEW REQUIRED';
  output.innerHTML=`<div class="ai-result-head"><span class="badge ${verification==='PASSED'?'badge-success':'badge-danger'}">${esc(verification)}</span><span class="help">Recommendations only — no report content is changed.</span></div>
    ${result.overall_assessment?`<div class="ai-trace"><strong>Overall assessment</strong><p>${esc(result.overall_assessment)}</p></div>`:''}
    ${strengths.length?`<div class="ai-trace"><strong>Strengths</strong><ul>${strengths.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}
    <div class="quality-issue-list">${issues.map(item=>`<article class="quality-issue"><div class="section-head"><strong>${esc(String(item.category||'QUALITY').replaceAll('_',' '))}</strong><span class="badge ${item.severity==='HIGH'||item.severity==='ERROR'?'badge-danger':item.severity==='MEDIUM'||item.severity==='WARNING'?'badge-warning':'badge-cyan'}">${esc(item.severity||'REVIEW')}</span></div><p>${esc(item.message||'')}</p>${item.recommendation?`<p class="help"><strong>Recommendation:</strong> ${esc(item.recommendation)}</p>`:''}${item.section_id?`<button class="btn btn-ghost btn-small" data-action="navigate-quality-section" data-section-id="${esc(item.section_id)}">Open section</button>`:''}</article>`).join('')||'<p class="help">No quality issues were returned.</p>'}</div>
    ${questions.length?`<div class="validation-item WARNING"><strong>Suggested follow-up questions</strong><ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}
    <div class="card-actions"><button class="btn btn-primary" type="button" data-action="mark-quality-reviewed" data-suggestion-id="${esc(job.suggestion.id)}">Mark review addressed</button><button class="btn btn-ghost" type="button" data-action="dismiss-quality-review" data-suggestion-id="${esc(job.suggestion.id)}">Dismiss review</button></div>`;
}

async function pollReportQuality(jobId, token) {
  const output=document.getElementById('ai-report-quality-output');
  for(let attempt=0;attempt<90;attempt+=1){
    if(token!==state.aiEnhancementPollToken||!document.getElementById('ai-report-quality-modal'))return;
    const job=await api(`/api/ai-jobs/${jobId}`,{},false);
    if(job.status==='COMPLETED'&&job.suggestion){renderReportQualityResult(job);return;}
    if(['FAILED','BLOCKED'].includes(job.status)){if(output)output.innerHTML=`<div class="validation-item ERROR"><strong>Whole-report review failed.</strong><p>${esc(job.error||job.policy_decision?.reason||'The AI job could not be completed.')}</p></div>`;return;}
    if(output)output.innerHTML='<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Reviewing completeness, consistency, traceability, benefits, and demo alignment…</p></div>';
    await new Promise(resolve=>setTimeout(resolve,1500));
  }
  if(output)output.innerHTML='<div class="validation-item ERROR">Whole-report review timed out. You can close this window and try again.</div>';
}

async function requestReportQualityReview(){const result=await api(`/api/reports/${state.report.report.id}/ai`,{method:'POST',body:{section_id:null,purpose:'REPORT_QUALITY_REVIEW'}},false);const token=++state.aiEnhancementPollToken;await pollReportQuality(result.ai_job_id,token);}

async function showReportQualityReview(existing=false){
  if(!existing){if(!navigator.onLine)throw new Error('Whole-report AI review requires an online connection.');if(!state.aiStatus?.policy?.allowed)throw new Error(state.aiStatus?.policy?.reason||'AI enhancement is not configured for this environment.');}
  closeModal();const wrap=document.createElement('div');wrap.id='modal-root';wrap.className='modal-backdrop';
  wrap.innerHTML=`<section id="ai-report-quality-modal" class="modal ai-enhancement-modal" role="dialog" aria-modal="true" aria-label="Whole-report quality review"><div class="section-head"><div><div class="card-meta"><span class="badge badge-cyan">REPORT QUALITY REVIEW</span><span>Revision ${esc(state.report.report.revision)}</span></div><h2>Completeness, consistency, and evidence review</h2><p class="help">The review identifies issues and follow-up questions but does not rewrite or approve report content.</p></div><button class="btn btn-ghost btn-small" data-action="close-modal">Close</button></div><div id="ai-report-quality-output"><div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>${existing?'Loading the latest review…':'Preparing whole-report review…'}</p></div></div></section>`;
  document.body.appendChild(wrap);
  if(existing&&state.report.quality_review){renderReportQualityResult({suggestion:{id:state.report.quality_review.id,content:state.report.quality_review.content}});}else await requestReportQualityReview();
}

async function showTraceability(){
  const data=await api(`/api/reports/${state.report.report.id}/traceability`);
  const cards=data.sections.map(section=>`<article class="finding"><h3>${esc(section.section_title)}</h3>${section.claims.length?section.claims.map(claim=>`<div class="traceability-claim"><span class="badge">${esc(claim.classification.replaceAll('_',' '))}</span><p>${esc(claim.text)}</p>${(claim.source_refs||[]).length?`<div class="help">Sources: ${claim.source_refs.map(item=>esc(item?.label||item?.ref||item)).join(', ')}</div>`:''}</div>`).join(''):'<p class="help">No accepted claims are recorded.</p>'}</article>`).join('');
  showModal('Report Source and Claim Traceability',`${data.executive_summary?`<article class="finding"><h3>Executive Summary</h3><span class="badge">${esc(data.executive_summary.classification.replaceAll('_',' '))}</span><p>${esc(data.executive_summary.text)}</p></article>`:''}<div class="traceability-list">${cards}</div>`,'');
}

function speakAiText() {
  const text = document.getElementById('ai-enhanced-output')?.dataset.enhancedText || document.getElementById('ai-solution-output')?.dataset.enhancedText || document.getElementById('ai-benefits-output')?.dataset.enhancedText || document.getElementById('ai-demo-plan-output')?.dataset.enhancedText || document.getElementById('ai-executive-summary-output')?.dataset.enhancedText || document.getElementById('ai-enhanced-text')?.value || document.getElementById('ai-solution-text')?.value || '';
  if (!text) return;
  if (!('speechSynthesis' in window)) { toast('Text-to-speech is not supported by this browser.','error'); return; }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}

function reportSectionContent(section) {
  const report = state.report;
  const module = section.process_module || 'GENERAL';
  const prompts = report.prompts_by_module[module] || report.prompts_by_module.GENERAL || [];
  const answered = new Map(section.responses.map(r => [r.prompt_id, r]));
  const findings = report.findings.filter(f => f.section_id === section.id);
  const evidence = report.evidence.filter(e => e.section_id === section.id);
  const generalObservations = sectionObservationSources(section).filter(item => item.general);
  const approach = section.cloud_inventory_approach;
  const approvedMappings = report.capability_mappings.filter(item => item.section_id === section.id && item.approval_state === 'APPROVED');
  const approvedCapabilityCount = state.capabilities.filter(item => item.status === 'APPROVED').length;
  const solutionEnabled = Boolean(section.process_module && state.aiStatus?.policy?.allowed && approvedCapabilityCount && sectionObservationSources(section).length);
  const sectionBenefits = report.benefits.filter(item => item.section_id === section.id && item.approval_state !== 'REJECTED');
  const benefitsEnabled = Boolean(state.aiStatus?.policy?.allowed && sectionObservationSources(section).length && (approach?.text || approvedMappings.length));
  const demoPriority = demoPriorityForSection(section.id);
  return `
    <div class="mobile-section-select"><label class="sr-only" for="mobile-section">Screen or section</label><select id="mobile-section" data-action="mobile-section">${reportSectionOptions(section.id)}</select></div>
    <section class="card">
      <div class="section-head"><div><div class="card-meta">${section.process_module?`<span>${esc(section.process_module.replaceAll('_',' '))}</span>`:''}</div><h2>${esc(section.title)}</h2></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="ai-enhance-observations" ${state.aiStatus?.policy?.allowed?'':'disabled'} title="${esc(state.aiStatus?.policy?.reason || 'AI status unavailable')}">AI Enhance</button><button class="btn btn-ghost btn-small" data-action="section-version-history">Version history</button>${canOwn(report.access_scope)?'<button class="btn btn-danger btn-small" data-action="remove-section">Remove</button>':''}</div></div>
      <p class="help">This section is open for collaborative entry by anyone associated with the report. No assignment or section status is required.</p>
      <div class="field"><label for="section-narrative">Current operations narrative</label><textarea id="section-narrative" class="editor" data-section-id="${section.id}" placeholder="Write or refine the customer-facing narrative. Autosaves after you stop typing.">${esc(section.narrative)}</textarea><div id="narrative-save" class="save-state"></div></div>
    </section>
    <section class="card">
      <div class="section-head"><div><h2>Guided discovery questions</h2><p class="help">Structured answers preserve evidence and can later be converted into approved narrative.</p></div></div>
      <div class="prompt-list">${prompts.map(p => { const r=answered.get(p.id); return `<article class="prompt-card"><div class="prompt-question"><span>${esc(p.question)}</span></div>${p.answer_type==='PHOTO'?`<button class="btn btn-ghost btn-small" data-action="section-upload-photo">Add photo to this section</button>`:`<textarea class="prompt-answer" data-prompt-id="${p.id}" data-response-version="${r?.version || ''}" placeholder="Capture the answer, facts, assumptions, and examples.">${esc(r?.narrative || '')}</textarea><div class="save-state" data-save-for="${p.id}"></div>`}</article>`; }).join('')}</div>
    </section>
    <section class="card" id="findings"><div class="section-head"><div><h2>Findings</h2><p class="help">Use a formal finding when you want to classify an Observation, Pain Point, Risk, Gap, Strength, or Opportunity. General current-operations notes and guided responses are automatically treated as <strong>Observations</strong> when assessing Cloud Inventory functionality; they do not need to be duplicated here.</p></div><button class="btn btn-ghost btn-small" data-action="new-finding">Add detailed finding</button></div>${findings.map(f => `<article class="finding"><div class="card-meta"><span class="badge">${esc(f.finding_type.replaceAll('_',' '))}</span><span>Confidence: ${esc(f.confidence)}</span></div><p>${esc(f.statement)}</p>${f.impact?`<p class="impact"><strong>Impact:</strong> ${esc(f.impact)}</p>`:''}</article>`).join('') || '<p class="help">No specifically classified findings have been captured for this section.</p>'}${generalObservations.length?`<div class="general-observation-summary"><strong>${generalObservations.length} general note${generalObservations.length===1?'':'s'} available as Observations for functionality mapping</strong><ul>${generalObservations.slice(0,6).map(item=>`<li>${esc(item.label.replace('Observation — ',''))}: ${esc(item.statement.slice(0,180))}${item.statement.length>180?'…':''}</li>`).join('')}</ul></div>`:''}</section>
    ${section.process_module ? `<section class="card" id="cloud-inventory-approach"><div class="section-head"><div><h2>Cloud Inventory Approach</h2><p class="help">Type the Cloud Inventory approach directly, map approved capabilities to operational observations, generate a source-grounded response with AI, or use any combination of these methods. AI generation uses approved product references and approved historical knowledge only.</p></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="generate-solution-approach" ${solutionEnabled?'':'disabled'} title="${esc(solutionEnabled ? 'Generate or improve a source-grounded Cloud Inventory approach' : (state.aiStatus?.policy?.reason || (!approvedCapabilityCount ? 'No approved Cloud Inventory capabilities are available.' : 'Enter operational observations before generating an approach.')))}">${approach?.text ? 'Enhance with AI' : 'Generate with AI'}</button><button class="btn btn-ghost btn-small" data-action="solution-version-history">Version history</button><button class="btn btn-ghost btn-small" data-action="map-capability" ${sectionObservationSources(section).length?'':'disabled'}>Map approved capability</button></div></div><div class="field"><label for="cloud-inventory-approach-editor">Cloud Inventory approach narrative</label><textarea id="cloud-inventory-approach-editor" class="editor solution-approach-editor" data-section-id="${section.id}" data-content-version="${approach?.version || ''}" placeholder="Describe how Cloud Inventory will support this operational area. You can type directly, map approved capabilities, or use Generate with AI. Autosaves after you stop typing.">${esc(approach?.text || '')}</textarea><div id="solution-approach-save" class="save-state">${approach ? `${esc(approach.source_type.replaceAll('_',' '))} · Version ${esc(approach.version)} · ${esc(fmtDateTime(approach.created_at))}` : ''}</div></div>${approvedMappings.length?`<div class="solution-mapping-summary"><strong>Approved functionality mappings</strong>${approvedMappings.map(item=>`<div class="finding"><div class="card-meta"><span class="badge badge-success">${esc(item.capability_code)}</span><span>${esc(item.source_label || 'Operational observation')}</span></div><strong>${esc(item.capability_name)}</strong><p>${esc(item.rationale)}</p></div>`).join('')}</div>`:''}</section>` : ''}
    ${section.process_module ? `<section class="card" id="targeted-benefits"><div class="section-head"><div><h2>Targeted Benefits</h2><p class="help">Capture or generate concise benefits that connect the observed operation to the accepted Cloud Inventory approach. Numeric claims require a recorded metric, formula, and explicit assumptions.</p></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="generate-targeted-benefits" ${benefitsEnabled?'':'disabled'}>${sectionBenefits.length?'Enhance with AI':'Generate with AI'}</button><button class="btn btn-ghost btn-small" data-action="new-benefit">Add benefit</button></div></div>${sectionBenefits.length?`<div class="benefit-list">${sectionBenefits.map(item=>`<article class="finding"><div class="section-head"><div><strong>${esc(benefitCategoryLabel(item.category))}</strong><div class="card-meta"><span>${esc(item.measure_type)}</span><span>Confidence: ${esc(item.confidence)}</span></div></div><span class="badge ${item.approval_state==='APPROVED'?'badge-success':'badge-warning'}">${esc(item.approval_state)}</span></div><p>${esc(item.statement)}</p>${item.source_label?`<p class="help"><strong>Based on:</strong> ${esc(item.source_label)}</p>`:''}${canReview(report.access_scope)&&item.approval_state==='PENDING'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-benefit" data-id="${item.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-benefit" data-id="${item.id}" data-decision="REJECTED">Reject</button></div>`:''}</article>`).join('')}</div>`:'<p class="help">No targeted benefits have been captured for this operational area.</p>'}</section>
    <section class="card" id="demo-priority"><div class="section-head"><div><h2>Demo Priority</h2><p class="help">These inputs are internal to the presales team and are used to build the customer-specific demo flow.</p></div></div><form id="section-demo-priority-form"><input type="hidden" name="section_id" value="${section.id}"><input type="hidden" name="expected_version" value="${demoPriority?.version||''}"><div class="field-row"><div class="field"><label>Importance</label><select name="priority"><option value="MUST_SHOW" ${demoPriority?.priority==='MUST_SHOW'?'selected':''}>Must show</option><option value="SHOULD_SHOW" ${demoPriority?.priority==='SHOULD_SHOW'?'selected':''}>Should show</option><option value="OPTIONAL" ${!demoPriority||demoPriority.priority==='OPTIONAL'?'selected':''}>Optional</option><option value="DO_NOT_SHOW" ${demoPriority?.priority==='DO_NOT_SHOW'?'selected':''}>Do not show</option></select></div><div class="field"><label>Estimated minutes</label><input name="estimated_minutes" type="number" min="1" max="240" value="${esc(demoPriority?.estimated_minutes||'')}"></div></div><div class="field"><label>What the presales consultant should show</label><textarea name="user_notes" placeholder="For example: Demonstrate how urgent picking work can be prioritized without relying on verbal instructions.">${esc(demoPriority?.user_notes||'')}</textarea></div><div class="field"><label>Constraints or claims to avoid</label><textarea name="constraints" placeholder="For example: Do not demonstrate ERP order creation; the ERP remains the system of record.">${esc(demoPriority?.constraints||'')}</textarea></div><button class="btn btn-ghost btn-small" type="submit">Save demo priority</button></form></section>` : ''}
    <section class="card" id="photos"><div class="section-head"><div><h2>Site photographs and attachments</h2><p class="help">Upload photographs directly to this operational section. Evidence routed from Quick Entry also appears here for review, AI enhancement, and publication.</p></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="section-upload-photo">Add photographs</button><button class="btn btn-ghost btn-small" data-action="go-quick-entry">Open Quick Entry</button></div></div><div class="evidence-grid">${evidence.map(e => `<article class="evidence-card"><div class="evidence-thumb">${e.file?.mime_type?.startsWith('image/')?`<img src="/api/files/${e.file.id}?inline=true" alt="${esc(e.caption || e.file.file_name)}" loading="lazy">`:'Attachment'}</div><div class="evidence-body"><strong>${esc(e.caption || e.file?.file_name || 'Evidence')}</strong><div class="card-meta"><span>${esc(e.placement)}</span><span>${e.file?bytes(e.file.size_bytes):''}</span><span class="badge">${esc(e.extraction_state || 'NOT APPLICABLE')}</span></div>${e.file?`<a href="/api/files/${e.file.id}" target="_blank">Open file</a>`:''}${canReview(report.access_scope)?`<div class="card-actions"><button class="btn btn-ghost btn-small" data-action="review-evidence" data-id="${e.id}" data-include="true">Include</button><button class="btn btn-ghost btn-small" data-action="review-evidence" data-id="${e.id}" data-include="false">Supporting only</button></div>`:''}</div></article>`).join('') || '<p class="help">No site photographs have been added to this section yet.</p>'}</div></section>`;
}

function reportInspector(section) {
  const report = state.report;
  const findings = report.findings.filter(f => f.section_id === section.id);
  const observationSources = sectionObservationSources(section);
  const mappings = report.capability_mappings.filter(m => m.section_id === section.id || findings.some(f => f.id === m.finding_id));
  const benefits = report.benefits.filter(b => b.section_id === section.id && b.approval_state !== 'REJECTED');
  const suggestions = report.ai_suggestions.filter(s => !s.section_id || s.section_id === section.id);
  const comments = (report.comments || []).filter(c => !c.section_id || c.section_id === section.id);
  const canR = canReview(report.access_scope);
  return `
    <aside class="report-inspector">
      <section class="inspector-card"><h3>Cloud Inventory functionality</h3>${observationSources.length?`<button class="btn btn-ghost btn-small btn-wide" data-action="map-capability">Map approved capability</button><p class="help">Formal findings and general notes are both available as mapping sources. Unclassified general notes are treated as Observations.</p>`:'<p class="help">Capture a current-operations note, guided response, or finding before mapping functionality.</p>'}${mappings.map(m=>`<div class="finding"><div class="card-meta"><span>${esc(m.source_label || 'Operational source')}</span><span class="badge ${m.approval_state==='APPROVED'?'badge-success':'badge-warning'}">${esc(m.approval_state)}</span></div><strong>${esc(m.capability_name)}</strong><p>${esc(m.rationale)}</p>${m.source_statement?`<p class="help"><strong>Mapped from:</strong> ${esc(m.source_statement)}</p>`:''}${canR&&m.approval_state==='PENDING'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-mapping" data-id="${m.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-mapping" data-id="${m.id}" data-decision="REJECTED">Reject</button></div>`:''}</div>`).join('')}</section>
      <section class="inspector-card"><h3>Benefits and baselines</h3><button class="btn btn-ghost btn-small btn-wide" data-action="new-benefit">Add benefit statement</button>${benefits.map(b=>`<div class="finding"><p>${esc(b.statement)}</p><div class="card-meta"><span>${esc(b.measure_type)}</span><span class="badge ${b.approval_state==='APPROVED'?'badge-success':'badge-warning'}">${esc(b.approval_state)}</span></div>${canR&&b.approval_state==='PENDING'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-benefit" data-id="${b.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-benefit" data-id="${b.id}" data-decision="REJECTED">Reject</button></div>`:''}</div>`).join('')}</section>
      <section class="inspector-card"><h3>AI assistance</h3><p class="help">${esc(state.aiStatus?.policy?.reason || 'AI status unavailable.')}</p>${suggestions.filter(s=>['OBSERVATION_ENHANCEMENT','SOLUTION_APPROACH','TARGETED_BENEFITS'].includes(s.purpose)).slice(0,5).map(s=>`<div class="finding"><div class="card-meta"><span>${s.purpose==='SOLUTION_APPROACH'?'Cloud Inventory approach':s.purpose==='TARGETED_BENEFITS'?'Targeted benefits':'Observation enhancement'}</span><span>${esc(fmtDateTime(s.created_at))}</span><span class="badge ${s.review_state==='APPROVED'?'badge-success':'badge-warning'}">${esc(s.review_state)}</span></div><p>${esc(((s.content.solution_text || s.content.enhanced_text || (s.content.benefits||[]).map(item=>item.statement).join('; ') || '')).slice(0,220))}${(s.content.solution_text || s.content.enhanced_text || (s.content.benefits||[]).map(item=>item.statement).join('; ') || '').length>220?'…':''}</p></div>`).join('')}</section>
      <section class="inspector-card"><h3>Collaboration comments</h3><form id="comment-form"><input type="hidden" name="section_id" value="${section.id}"><div class="field"><label class="sr-only">Comment</label><textarea name="body" required placeholder="Add a review note, question, or follow-up request."></textarea></div><button class="btn btn-ghost btn-small btn-wide" type="submit">Add comment</button></form>${comments.map(c=>`<div class="finding"><div class="card-meta"><strong>${esc(c.author_name)}</strong><span>${fmtDate(c.created_at)}</span></div><p>${esc(c.body)}</p><span class="badge ${c.status==='RESOLVED'?'badge-success':'badge-warning'}">${esc(c.status)}</span>${canR&&c.status==='OPEN'?`<button class="btn btn-ghost btn-small" data-action="resolve-comment" data-id="${c.id}">Resolve</button>`:''}</div>`).join('') || '<p class="help">No comments for this section.</p>'}</section>
    </aside>`;
}

function reportSectionHasContent(section) {
  const report = state.report;
  return Boolean(
    section.narrative?.trim() ||
    section.responses?.some(response => (response.narrative || '').trim() || response.payload) ||
    report.findings.some(item => item.section_id === section.id && item.status !== 'REJECTED') ||
    report.evidence.some(item => item.section_id === section.id && ['READY','AVAILABLE'].includes(item.status)) ||
    report.benefits.some(item => item.section_id === section.id && item.approval_state === 'APPROVED') ||
    Boolean(section.cloud_inventory_approach?.text?.trim())
  );
}

function reportPreviewSection(section) {
  const report = state.report;
  const responses = (section.responses || []).filter(response => (response.narrative || '').trim() || response.payload);
  const findings = report.findings.filter(item => item.section_id === section.id && item.status !== 'REJECTED');
  const findingIds = new Set(findings.map(item => item.id));
  const mappings = report.capability_mappings.filter(item => (item.section_id === section.id || findingIds.has(item.finding_id)) && item.approval_state === 'APPROVED');
  const approach = section.cloud_inventory_approach?.text || '';
  const benefits = report.benefits.filter(item => item.section_id === section.id && item.approval_state === 'APPROVED');
  const evidence = report.evidence.filter(item => item.section_id === section.id && ['READY','AVAILABLE'].includes(item.status) && item.placement === 'INLINE');
  const noContent = !reportSectionHasContent(section);
  return `<article class="compiled-section">
    <h2>${esc(section.title)}</h2>
    ${section.narrative?.trim()?`<div class="compiled-narrative">${esc(section.narrative).replaceAll('\n','<br>')}</div>`:''}
    ${responses.length?`<h3>Discovery Responses</h3>${responses.map(response=>`<div class="compiled-response"><strong>${esc(response.question)}</strong><p>${esc(response.narrative || JSON.stringify(response.payload || {}))}</p></div>`).join('')}`:''}
    ${findings.length?`<h3>Current-State Findings</h3><ul>${findings.map(item=>`<li><strong>${esc(item.finding_type.replaceAll('_',' '))}:</strong> ${esc(item.statement)}${item.impact?`<div class="help"><strong>Impact:</strong> ${esc(item.impact)}</div>`:''}</li>`).join('')}</ul>`:''}
    ${approach?`<h3>Cloud Inventory Approach</h3><div class="compiled-narrative">${esc(approach).replaceAll('\n','<br>')}</div>`:''}
    ${mappings.length?`<h3>Mapped Cloud Inventory Functionality</h3><ul>${mappings.map(item=>`<li><strong>${esc(item.capability_name)}:</strong> ${esc(item.rationale)}${item.source_label?`<div class="help"><strong>Mapped from:</strong> ${esc(item.source_label)}</div>`:''}</li>`).join('')}</ul>`:''}
    ${benefits.length?`<h3>Benefits</h3><ul>${benefits.map(item=>`<li>${esc(item.statement)}</li>`).join('')}</ul>`:''}
    ${evidence.length?`<h3>Site Photographs and Evidence</h3><div class="compiled-evidence">${evidence.map(item=>`<div>${item.file?.mime_type?.startsWith('image/')?`<img src="/api/files/${item.file.id}?inline=true" alt="${esc(item.caption || item.file.file_name)}" loading="lazy">`:''}<p>${esc(item.caption || item.file?.file_name || 'Evidence')}</p></div>`).join('')}</div>`:''}
    ${noContent?'<p class="help">This section is marked complete but contains no reportable content.</p>':''}
  </article>`;
}

function reportPreviewContent() {
  const report = state.report;
  const activeSections = report.sections.filter(section => section.state !== 'REMOVED');
  const contentSections = activeSections.filter(reportSectionHasContent);
  const emptySections = activeSections.length - contentSections.length;
  const storageConfigured = state.storageStatus?.configured === true;
  const readiness = report.readiness || {overall_status:'PARTIAL',sections:[],counts:{}};
  const reviewQueue = report.review_queue || {count:0,items:[]};
  const quality = report.quality_review?.content || null;
  const storageMessage = storageConfigured
    ? `<div class="validation-item">Persistent document storage is configured.</div>`
    : `<div class="validation-item WARNING">Persistent Cloudflare R2 storage is not configured. Draft Word/PDF downloads remain available; final publication, evidence, logos, and stored documents require R2.</div>`;
  return `
    <div class="mobile-section-select"><label class="sr-only" for="mobile-section">Screen or section</label><select id="mobile-section" data-action="mobile-section">${reportSectionOptions('report-preview')}</select></div>
    <section class="card" id="executive-summary">
      <div class="section-head"><div><h2>Executive Summary</h2><p class="help">Enter the summary directly or generate a source-grounded draft from accepted report content. Manual and AI versions remain available in version history.</p></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="generate-executive-summary" ${state.aiStatus?.policy?.allowed?'':'disabled'}>${report.executive_summary?.text?'Enhance with AI':'Generate with AI'}</button><button class="btn btn-ghost btn-small" data-action="executive-summary-history">Version history</button></div></div>
      <div class="field"><label for="executive-summary-editor">Customer-facing executive overview</label><textarea id="executive-summary-editor" class="editor" placeholder="Summarize operational context, principal observations, Cloud Inventory solution themes, expected benefits, open dependencies, and recommended next steps.">${esc(report.executive_summary?.text||'')}</textarea><div id="executive-summary-save" class="save-state"></div></div>
      ${report.executive_summary?`<div class="card-meta"><span class="badge badge-success">CURRENT</span><span>Version ${esc(report.executive_summary.version)}</span><span>${esc(report.executive_summary.source_type.replaceAll('_',' '))}</span></div>`:'<p class="help">No executive summary has been entered.</p>'}
    </section>
    <section class="card report-governance-card" id="report-readiness">
      <div class="section-head"><div><h2>Report Quality and Readiness</h2><p class="help">Readiness is calculated from actual accepted content; it does not reintroduce section assignment or manual status workflows.</p></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="review-entire-report" ${state.aiStatus?.policy?.allowed?'':'disabled'}>Review Entire Report</button>${quality?'<button class="btn btn-ghost btn-small" data-action="view-quality-review">View latest AI review</button>':''}<button class="btn btn-ghost btn-small" data-action="view-traceability">View traceability</button></div></div>
      <div class="report-progress governance-summary"><span>${readinessBadge(readiness.overall_status)}</span><span><strong>${esc(readiness.counts?.READY||0)}</strong> ready</span><span><strong>${esc(readiness.counts?.REVIEW_REQUIRED||0)}</strong> review required</span><span><strong>${esc(readiness.counts?.MISSING||0)}</strong> missing</span><span><strong>${esc(reviewQueue.count||0)}</strong> queue items</span></div>
      <div class="table-wrap readiness-table"><table><thead><tr><th>Operational section</th><th>Status</th><th>Current operation</th><th>CI approach</th><th>Mappings</th><th>Benefits</th><th>Demo</th><th>Action</th></tr></thead><tbody>${readiness.sections.map(item=>`<tr><td><strong>${esc(item.title)}</strong>${item.missing?.length?`<br><span class="help">Missing: ${esc(item.missing.join(', '))}</span>`:''}</td><td>${readinessBadge(item.status)}</td><td>${item.current_operations?'✓':'—'}</td><td>${item.approach_present?'✓':'—'}</td><td>${esc(item.approved_mapping_count)}${item.pending_mapping_count?` <span class="badge badge-warning">${item.pending_mapping_count} pending</span>`:''}</td><td>${esc(item.approved_benefit_count)}${item.pending_benefit_count?` <span class="badge badge-warning">${item.pending_benefit_count} pending</span>`:''}</td><td>${esc(String(item.demo_priority||'OPTIONAL').replaceAll('_',' '))}${item.demo_covered?' ✓':''}</td><td><button class="btn btn-ghost btn-small" data-action="navigate-quality-section" data-section-id="${item.section_id}">Open</button></td></tr>`).join('')}</tbody></table></div>
      <div class="review-queue-panel"><h3>Reviewer work queue</h3>${reviewQueue.items?.length?reviewQueue.items.slice(0,12).map(item=>`<article class="review-queue-item"><div><span class="badge ${item.status==='STALE'?'badge-danger':'badge-warning'}">${esc(item.status)}</span> <strong>${esc(item.type.replaceAll('_',' '))}</strong>${item.section_title?` — ${esc(item.section_title)}`:''}<p>${esc(item.label||'')}</p></div>${item.section_id?`<button class="btn btn-ghost btn-small" data-action="navigate-quality-section" data-section-id="${item.section_id}">Open</button>`:''}</article>`).join(''):'<p class="help">No pending mappings, benefits, AI suggestions, comments, quality issues, or failed publications.</p>'}</div>
    </section>
    <section class="card" id="demo-preparation">
      <div class="section-head"><div><h2>Demo Preparation</h2><p class="help">Define the audience, timebox, operational priorities, and internal guidance used to create the presales demonstration flow.</p></div><div class="toolbar"><button class="btn btn-primary btn-small" data-action="generate-demo-plan" ${state.aiStatus?.policy?.allowed&&report.capability_mappings.some(item=>item.approval_state==='APPROVED')?'':'disabled'}>${report.demo_plan?'Regenerate with AI':'Generate with AI'}</button><button class="btn btn-ghost btn-small" data-action="demo-plan-history">Version history</button></div></div>
      <form id="demo-settings-form"><input type="hidden" name="expected_version" value="${report.demo_settings?.version||''}"><div class="field-row"><div class="field"><label>Demo audience</label><input name="audience" value="${esc(report.demo_settings?.audience||'')}" placeholder="For example: Operations leadership, warehouse supervisors, and IT"></div><div class="field"><label>Available minutes</label><input name="duration_minutes" type="number" min="10" max="480" value="${esc(report.demo_settings?.duration_minutes||45)}"></div></div><div class="field"><label>Additional must-show points and flow guidance</label><textarea name="additional_priorities" placeholder="Enter cross-process priorities, sequence preferences, required scenarios, or known demo constraints.">${esc(report.demo_settings?.additional_priorities||'')}</textarea></div><button class="btn btn-ghost btn-small" type="submit">Save demo settings</button></form>
      <div class="demo-priority-summary"><h3>Operational priorities</h3>${report.sections.filter(item=>item.state!=='REMOVED'&&item.process_module).map(section=>{const item=demoPriorityForSection(section.id);return `<div class="finding"><div class="section-head"><strong>${esc(section.title)}</strong><span class="badge ${item?.priority==='MUST_SHOW'?'badge-success':item?.priority==='DO_NOT_SHOW'?'badge-danger':'badge-warning'}">${esc(String(item?.priority||'OPTIONAL').replaceAll('_',' '))}</span></div>${item?.user_notes?`<p>${esc(item.user_notes)}</p>`:'<p class="help">No section-specific demo note entered.</p>'}</div>`;}).join('')}</div>
      ${report.demo_plan?`<div class="accepted-demo-plan"><div class="section-head"><div><h3>${esc(report.demo_plan.content?.title||'Accepted Demo Plan')}</h3><div class="card-meta"><span>Version ${esc(report.demo_plan.version)}</span><span>${esc(fmtDateTime(report.demo_plan.created_at))}</span></div></div><span class="badge badge-success">ACCEPTED</span></div>${(report.demo_plan.content?.objectives||[]).length?`<ul>${report.demo_plan.content.objectives.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}<div class="demo-flow-preview">${(report.demo_plan.content?.flow||[]).map(item=>`<article class="finding"><strong>${esc(item.sequence)}. ${esc(item.operational_area)}</strong><p>${esc(item.functionality||'')}</p><p class="help">${esc(item.value_statement||'')}</p></article>`).join('')}</div></div>`:'<p class="help">No demo plan has been accepted. Save section priorities and generate a plan when the approved functionality mappings are ready.</p>'}
    </section>
    <section class="card report-tools-card">
      <div class="section-head"><div><h2>Report Review</h2><p class="help">The draft compiles automatically from every section containing reportable content. Section assignment and section status are not required.</p></div>${reportStatusControl(report)}</div>
      <div class="report-progress"><span><strong>${contentSections.length}</strong> sections with content</span><span><strong>${emptySections}</strong> empty sections</span><span><strong>${report.report.revision}</strong> revision</span></div>
      <div class="toolbar"><button class="btn btn-ghost" data-action="validate-draft">Check Report</button>${canOwn(report.access_scope)?'<button class="btn btn-secondary" data-action="validate-final">Check Final</button>':''}</div>
      ${state.validation?`<div class="validation-list">${state.validation.issues.map(item=>`<div class="validation-item ${item.severity}">${esc(item.message)}</div>`).join('') || '<div class="validation-item">No issues found.</div>'}</div>`:''}
      <div class="section-head report-download-head"><div><h3>Draft Downloads</h3><p class="help">Draft documents are generated directly and do not require persistent R2 storage.</p></div></div>
      <div class="card-actions report-publication-actions"><a class="btn btn-primary" href="/api/reports/${report.report.id}/draft.docx">Download Draft Word</a><a class="btn btn-primary" href="/api/reports/${report.report.id}/draft.pdf">Download Draft PDF</a></div>
      <div class="section-head report-download-head"><div><h3>Controlled Publication</h3><p class="help">Final and stored publications use persistent Cloudflare R2 object storage.</p></div></div>
      ${storageMessage}
      <div class="card-actions report-publication-actions"><button class="btn btn-ghost" data-action="publish" data-type="DEMO_BRIEF" data-final="false" ${storageConfigured?'':'disabled'}>Generate Demo Brief</button><button class="btn btn-ghost" data-action="publish" data-type="FOLLOW_UP_QUESTIONNAIRE" data-final="false" ${storageConfigured?'':'disabled'}>Generate Follow-up Questionnaire</button>${canOwn(report.access_scope)?`<button class="btn btn-secondary" data-action="publish" data-type="FULL_DISCOVERY" data-final="true" ${storageConfigured?'':'disabled'}>Generate Final Report</button>`:''}</div>
    </section>
    <section class="card">
      <div class="section-head"><div><h2>Generated Documents</h2><p class="help">Persisted Word and PDF files appear here after controlled publication.</p></div><button class="btn btn-ghost btn-small" data-action="refresh-report">Refresh status</button></div>
      <div class="generated-documents">${report.publications.map(item=>{
        const createdAt = item.created_at ? new Date(item.created_at).getTime() : 0;
        const laterSuccess = item.status === 'FAILED' && report.publications.some(other => other.status === 'COMPLETED' && other.created_at && new Date(other.created_at).getTime() > createdAt);
        const statusLabel = laterSuccess ? 'PREVIOUS FAILED ATTEMPT' : item.status;
        const statusClass = item.status === 'COMPLETED' ? 'badge-success' : laterSuccess ? 'badge-warning' : item.status === 'FAILED' ? 'badge-danger' : 'badge-warning';
        return `<div class="finding"><div class="section-head"><div><strong>${esc(item.publication_type.replaceAll('_',' '))}</strong><div class="card-meta"><span>Revision ${esc(item.report_revision ?? '')}</span><span>${esc(fmtDateTime(item.completed_at || item.created_at))}</span></div></div><span class="badge ${statusClass}">${esc(statusLabel)}</span></div>${item.error?`<p class="impact">${esc(item.error)}</p>`:''}<div class="card-actions">${item.docx_file_id?`<a class="btn btn-ghost btn-small" href="/api/files/${item.docx_file_id}">Word</a>`:''}${item.pdf_file_id?`<a class="btn btn-ghost btn-small" href="/api/files/${item.pdf_file_id}">PDF</a>`:''}${item.status==='FAILED'&&canReview(report.access_scope)?`<button class="btn btn-ghost btn-small" data-action="dismiss-publication" data-id="${item.id}">Dismiss failed attempt</button>`:''}</div></div>`;
      }).join('') || '<p class="help">No persisted documents have been requested.</p>'}</div>
    </section>
    <section class="compiled-report card">
      <div class="compiled-report-cover"><div class="card-meta"><span class="badge badge-cyan">REPORT REVIEW</span>${reportStatusBadge(report.report.state)}</div><h1>${esc(report.report.title)}</h1><p>Revision ${report.report.revision} · ${esc(report.report.report_kind)}</p></div>
      ${report.executive_summary?.text?`<section class="compiled-report-section"><h2>Executive Summary</h2><div class="compiled-narrative">${esc(report.executive_summary.text).replaceAll('\n','<br>')}</div></section>`:''}
      ${contentSections.length?contentSections.map(reportPreviewSection).join(''):'<div class="empty"><h2>No reportable content yet</h2><p>As information is entered in any section it will appear here automatically.</p></div>'}
    </section>`;
}

async function renderReport(id, sectionId = null) {
  setLoading();
  await loadReport(id);
  const report = state.report;
  const screenId = sectionId || 'quick-entry';
  const quickEntry = screenId === 'quick-entry';
  const reportPreview = screenId === 'report-preview';
  const section = (!quickEntry && !reportPreview) ? getActiveSection(screenId) : null;
  if (!quickEntry && !reportPreview && !section) { toast('Report contains no sections.', 'error'); return; }
  const sections = report.sections;
  const sidebar = `<aside class="report-sidebar"><div class="section-nav"><button class="${quickEntry?'active':''}" data-action="open-quick-entry"><span>Quick Entry</span></button>${sections.map(item=>`<button class="${section&&item.id===section.id?'active':''} ${item.state==='REMOVED'?'removed':''}" data-action="open-section" data-id="${item.id}"><span>${esc(item.title)}</span></button>`).join('')}<button class="report-nav-final ${reportPreview?'active':''}" data-action="open-report-preview"><span>Report</span></button></div></aside>`;
  app.innerHTML = shell(`
    <div class="page">
      <div class="breadcrumbs"><button data-action="go" data-route="#/prospects">Prospects</button><span>/</span><button data-action="go" data-route="#/prospect/${report.report.prospect_id}">Workspace</button><span>/</span><span>${esc(report.report.title)}</span></div>
      <header class="page-header"><div><h1>${esc(report.report.title)}</h1><p>Revision ${report.report.revision} - ${esc(report.report.report_kind)}</p></div><div class="toolbar"><span class="badge badge-cyan">${esc(report.access_scope)}</span>${reportStatusControl(report)}<button class="btn btn-ghost" data-action="add-section">Add section</button>${canOwn(report.access_scope)?'<button class="btn btn-secondary" data-action="merge-reports">Merge reports</button><button class="btn btn-danger" data-action="delete-report">Delete draft</button>':''}</div></header>
      <div class="report-layout ${quickEntry || reportPreview ? 'quick-entry-layout' : ''}">
        ${sidebar}
        <main class="report-main">${quickEntry ? quickEntryContent() : reportPreview ? reportPreviewContent() : reportSectionContent(section)}</main>
        ${quickEntry || reportPreview ? '' : reportInspector(section)}
      </div>
    </div>`, 'prospects');
  updateConnection();
  requestAnimationFrame(() => restoreReportNavPosition(screenId));
}

function selectedSection() {
  const parts = location.hash.split('/');
  const screenId = parts[3];
  if (!screenId || screenId === 'quick-entry' || screenId === 'report-preview') return null;
  return state.report.sections.find(section => section.id === screenId) || null;
}
function currentReportScreen() {
  const parts = location.hash.split('/');
  return parts[3] || 'quick-entry';
}

function scheduleNarrativeSave(sectionId, value, statusElement) {
  clearTimeout(state.saveTimers.get(`section:${sectionId}`));
  statusElement.textContent = 'Unsaved changes...';
  const timer = setTimeout(async () => {
    const section = state.report.sections.find(s=>s.id===sectionId);
    try {
      statusElement.textContent = 'Saving...';
      const result = await api(`/api/reports/${state.report.report.id}/sections/${sectionId}`, {method:'PATCH', body:{narrative:value,expected_version:section?.version}});
      statusElement.textContent = result.offlineQueued ? 'Queued offline' : 'Saved';
      if (section && !result.offlineQueued) { section.narrative=value; section.version=result.version; }
    } catch (e) {
      statusElement.textContent=e.status===409?'Conflict - reloading':'Save failed';
      toast(e.status===409?'This section changed in another session. The latest version is being loaded.':e.message,'error');
      if(e.status===409) setTimeout(()=>renderReport(state.report.report.id,sectionId),350);
    }
  }, 900);
  state.saveTimers.set(`section:${sectionId}`, timer);
}

async function saveSolutionApproach(sectionId, value, statusElement) {
  const section = state.report.sections.find(item => item.id === sectionId);
  const expectedVersion = section?.cloud_inventory_approach?.version ?? null;
  try {
    if (statusElement) statusElement.textContent = 'Saving...';
    const result = await api(`/api/reports/${state.report.report.id}/sections/${sectionId}/content`, {
      method:'PUT',
      body:{
        content_type:'CLOUD_INVENTORY_APPROACH',
        text:value,
        expected_version:expectedVersion,
      },
    });
    if (statusElement) statusElement.textContent = result.offlineQueued ? 'Queued offline' : 'Saved';
    if (section && !result.offlineQueued) {
      section.cloud_inventory_approach = {
        id:result.id,
        version:result.version,
        text:result.text,
        source_type:result.source_type,
        source_refs:[],
        created_at:result.created_at,
      };
      section.version = result.section_version;
      state.report.report.revision = result.report_revision;
    }
    return result;
  } catch (error) {
    if (statusElement) statusElement.textContent = error.status === 409 ? 'Conflict - reloading' : 'Save failed';
    toast(error.status === 409 ? 'The Cloud Inventory approach changed in another session. The latest version is being loaded.' : error.message, 'error');
    if (error.status === 409) setTimeout(() => renderReport(state.report.report.id, sectionId), 350);
    throw error;
  }
}

function scheduleSolutionApproachSave(sectionId, value, statusElement) {
  const key = `solution:${sectionId}`;
  clearTimeout(state.saveTimers.get(key));
  if (statusElement) statusElement.textContent = 'Unsaved changes...';
  const timer = setTimeout(() => {
    saveSolutionApproach(sectionId, value, statusElement).catch(() => {});
  }, 900);
  state.saveTimers.set(key, timer);
}

async function flushSolutionApproachSave(section) {
  const editor = document.getElementById('cloud-inventory-approach-editor');
  if (!editor || !section) return;
  const key = `solution:${section.id}`;
  clearTimeout(state.saveTimers.get(key));
  state.saveTimers.delete(key);
  const currentText = section.cloud_inventory_approach?.text || '';
  if (editor.value.trim() === currentText.trim()) return;
  await saveSolutionApproach(section.id, editor.value, document.getElementById('solution-approach-save'));
}

function schedulePromptSave(sectionId, promptId, value, statusElement) {
  clearTimeout(state.saveTimers.get(`prompt:${promptId}`));
  statusElement.textContent = 'Unsaved changes...';
  const timer = setTimeout(async () => {
    const section=state.report.sections.find(s=>s.id===sectionId);
    const existing=section?.responses?.find(r=>r.prompt_id===promptId);
    try {
      statusElement.textContent = 'Saving...';
      const body={prompt_id:promptId,narrative:value,client_mutation_id:uid()};
      if(existing) body.expected_version=existing.version;
      const result = await api(`/api/reports/${state.report.report.id}/sections/${sectionId}/responses`, {method:'PUT', body});
      statusElement.textContent = result.offlineQueued ? 'Queued offline' : 'Saved';
      if(!result.offlineQueued && section){
        if(existing){existing.narrative=value;existing.version=result.version;}
        else section.responses.push({id:result.id,prompt_id:promptId,narrative:value,payload:null,version:result.version});
      }
    } catch(e) {
      statusElement.textContent=e.status===409?'Conflict - reloading':'Save failed';
      toast(e.status===409?'This answer changed in another session. The latest version is being loaded.':e.message,'error');
      if(e.status===409) setTimeout(()=>renderReport(state.report.report.id,sectionId),350);
    }
  }, 900);
  state.saveTimers.set(`prompt:${promptId}`, timer);
}

function showDetailedFinding() {
  showModal('Add finding', `<form id="finding-form"><div class="field"><label>Finding type</label><select name="finding_type"><option>OBSERVATION</option><option>PAIN_POINT</option><option>RISK</option><option>GAP</option><option>STRENGTH</option><option>OPPORTUNITY</option></select></div><div class="field"><label>Finding</label><textarea name="statement" required></textarea></div><div class="field"><label>Impact</label><textarea name="impact"></textarea></div><div class="field"><label>Confidence</label><select name="confidence"><option>HIGH</option><option selected>MEDIUM</option><option>LOW</option></select></div><button class="btn btn-primary btn-wide" type="submit">Add finding</button></form>`, '');
}
function showAddSection() {
  showModal('Add report section', `<form id="section-form"><div class="field"><label>Section title</label><input name="title" required></div><div class="field"><label>Process module</label><select name="process_module"><option value="">General</option>${['RECEIVING','PUTAWAY','TRANSFER','ORDER_MANAGEMENT','PICKING','PACKING','SHIPPING','CYCLE_COUNT','WORK_ORDERS','PRINTING','FIELD_INVENTORY','MANUFACTURING'].map(x=>`<option>${x}</option>`).join('')}</select></div><p class="help">All report sections and discovery questions are optional.</p><button class="btn btn-primary btn-wide" type="submit">Add section</button></form>`, '');
}
function showRemoveSection() {
  const section = selectedSection();
  showModal('Remove report section', `<p>Removed sections are excluded from validation and publication but remain in the audit history.</p><form id="remove-section-form"><div class="field"><label>Reason</label><textarea name="removed_reason" required></textarea></div><button class="btn btn-danger btn-wide" type="submit">Remove ${esc(section.title)}</button></form>`, '');
}
function showMapCapability() {
  const section = selectedSection();
  const sources = sectionObservationSources(section);
  if (!sources.length) { toast('Capture a current-operations note, guided response, or finding before mapping functionality.', 'error'); return; }
  const options = state.capabilities.filter(c=>c.status==='APPROVED').map(c=>`<option value="${c.id}">${esc(c.domain)} - ${esc(c.name)}</option>`).join('');
  if (!options) { toast('No approved Cloud Inventory capabilities are available.', 'error'); return; }
  showModal('Map Cloud Inventory functionality', `<form id="mapping-form"><input type="hidden" name="section_id" value="${section.id}"><div class="field"><label>Operational observation or finding</label><select name="source_ref">${sources.map(item=>`<option value="${esc(item.ref)}">${esc(item.type.replaceAll('_',' '))} - ${esc(item.statement.slice(0,110))}</option>`).join('')}</select><small>General notes and guided responses are treated as Observations for mapping; their original wording and classification are not changed.</small></div><div class="field"><label>Approved capability</label><select name="capability_id">${options}</select></div><div class="field"><label>Rationale</label><textarea name="rationale" required placeholder="Explain how this approved capability supports the selected observation, finding, or operational need."></textarea></div><div class="field"><label>Prerequisites</label><textarea name="prerequisites"></textarea></div><button class="btn btn-primary btn-wide" type="submit">Create mapping for review</button></form>`, '');
}

function showBenefit() {
  const section = selectedSection();
  const sources = sectionBenefitSources(section);
  if (!sources.length) { toast('Capture an observation, mapping, accepted approach, or metric before adding a benefit.','error'); return; }
  showModal('Add targeted benefit', `<form id="benefit-form"><input type="hidden" name="section_id" value="${section.id}"><div class="field"><label>Benefit basis</label><select name="source_ref">${sources.map(item=>`<option value="${esc(item.ref)}">${esc(item.type.replaceAll('_',' '))} — ${esc(item.label)}</option>`).join('')}</select><small>The selected source is retained for traceability.</small></div><div class="field"><label>Benefit category</label><select name="category"><option value="OPERATIONAL_EFFICIENCY">Operational Efficiency</option><option value="INVENTORY_VISIBILITY">Inventory Visibility</option><option value="ACCURACY_CONTROL">Accuracy and Control</option><option value="CUSTOMER_SERVICE">Customer Service</option><option value="WORKFORCE_PRODUCTIVITY">Workforce Productivity</option><option value="COMPLIANCE_TRACEABILITY">Compliance and Traceability</option><option value="MANAGEMENT_VISIBILITY">Management Visibility</option><option value="SCALABILITY">Scalability</option></select></div><div class="field"><label>Benefit statement</label><textarea name="statement" required placeholder="State the expected operational benefit without presenting an unvalidated result as guaranteed."></textarea></div><div class="field-row"><div class="field"><label>Measurement type</label><select name="measure_type"><option>QUALITATIVE</option><option>QUANTITATIVE</option></select></div><div class="field"><label>Confidence</label><select name="confidence"><option>LOW</option><option selected>MEDIUM</option><option>HIGH</option></select></div></div><div class="field"><label>Formula or measurement method</label><textarea name="formula" placeholder="Required for a quantitative benefit."></textarea></div><div class="field"><label>Assumptions</label><textarea name="assumptions" placeholder="Required for a quantitative benefit."></textarea></div><button class="btn btn-primary btn-wide" type="submit">Create benefit for review</button></form>`, '');
}

async function showMergeReports() {
  const prospect = await api(`/api/prospects/${state.report.report.prospect_id}`);
  const candidates = prospect.reports.filter(r => r.id !== state.report.report.id && r.state !== 'MERGED' && r.state !== 'DELETED');
  if (!candidates.length) { toast('No other active reports are available to merge.', 'error'); return; }
  showModal('Merge contributor reports', `<p>Content and evidence will be copied into the target report. Source reports will enter a recoverable merged state for 30 days.</p><form id="merge-form"><div class="field"><label>Target report</label><select name="target_report_id">${prospect.reports.filter(r=>r.state!=='MERGED'&&r.state!=='DELETED').map(r=>`<option value="${r.id}" ${r.id===state.report.report.id?'selected':''}>${esc(r.title)}</option>`).join('')}</select></div><div class="field"><label>Source reports</label>${candidates.map(r=>`<label><input type="checkbox" name="source_report_ids" value="${r.id}"> ${esc(r.title)}</label>`).join('')}</div><label><input type="checkbox" name="delete_sources_after_merge" checked> Place source reports in recoverable merged state</label><button class="btn btn-primary btn-wide" type="submit">Merge reports</button></form>`, '');
}

async function renderAdmin() {
  setLoading();
  if (!hasRole('ADMIN')) { location.hash='#/prospects'; return; }
  const [users, branding, capabilities, knowledge, prospects, retention, audit, reviewQueue, operations] = await Promise.all([api('/api/users'), api('/api/admin/branding'), api('/api/capabilities'), api('/api/admin/knowledge'), api('/api/prospects'), api('/api/admin/retention-due?days=90'), api('/api/admin/audit?limit=100'), api('/api/admin/review-queue'), api('/api/admin/operations')]);
  state.users=users; state.capabilities=capabilities;
  app.innerHTML = shell(`<div class="page"><header class="page-header"><div><h1>Administration</h1><p>Users, review work, operational health, capability governance, knowledge, branding, retention, and audit.</p></div></header><nav class="tabs"><button class="tab active" data-action="admin-tab" data-tab="users">Users</button><button class="tab" data-action="admin-tab" data-tab="review-queue">Review Queue</button><button class="tab" data-action="admin-tab" data-tab="operations">Operations</button><button class="tab" data-action="admin-tab" data-tab="capabilities">Capabilities</button><button class="tab" data-action="admin-tab" data-tab="knowledge">Knowledge</button><button class="tab" data-action="admin-tab" data-tab="retention">Retention</button><button class="tab" data-action="admin-tab" data-tab="branding">Branding</button><button class="tab" data-action="admin-tab" data-tab="audit">Audit</button></nav><div id="admin-panel"></div></div>`, 'admin');
  window.__adminData={users,branding,capabilities,knowledge,prospects,retention,audit,reviewQueue,operations};
  renderAdminTab('users'); updateConnection();
}
function renderAdminTab(tab) {
  const data=window.__adminData; const panel=document.getElementById('admin-panel');
  document.querySelectorAll('[data-action="admin-tab"]').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));
  if(tab==='users') panel.innerHTML=`<div class="page-header"><div><h2>Users</h2><p>Application-managed identities and global roles.</p></div><button class="btn btn-primary" data-action="new-user">Create user</button></div><div class="table-wrap"><table><thead><tr><th>User</th><th>Email</th><th>Roles</th><th>Status</th></tr></thead><tbody>${data.users.map(u=>`<tr><td>${esc(u.display_name||u.username)}<br><span class="help">${esc(u.username)}</span></td><td>${esc(u.email)}</td><td>${u.roles.map(r=>`<span class="badge">${esc(r)}</span>`).join(' ')}</td><td>${esc(u.status)}</td></tr>`).join('')}</tbody></table></div>`;
  if(tab==='review-queue') panel.innerHTML=`<div class="page-header"><div><h2>Central Reviewer Work Queue</h2><p>Pending capability mappings, benefits, AI suggestions, comments, failed publications, report-quality recommendations, and knowledge approvals.</p></div><span class="badge badge-warning">${esc(data.reviewQueue.count)} items</span></div><div class="review-queue-panel">${data.reviewQueue.items.length?data.reviewQueue.items.map(item=>`<article class="review-queue-item"><div><div class="card-meta"><span class="badge ${item.status==='STALE'?'badge-danger':'badge-warning'}">${esc(item.status)}</span><span>${esc(item.type.replaceAll('_',' '))}</span>${item.report_title?`<span>${esc(item.report_title)}</span>`:''}</div><strong>${esc(item.label||'Review item')}</strong></div>${item.report_id?`<button class="btn btn-ghost btn-small" data-action="open-queue-report" data-report-id="${item.report_id}" data-section-id="${item.section_id||'report-preview'}">Open</button>`:item.type==='KNOWLEDGE'?`<button class="btn btn-ghost btn-small" data-action="review-knowledge-detail" data-id="${item.id}">Review</button>`:''}</article>`).join(''):'<p class="help">No reviewer work is currently queued.</p>'}</div>`;
  if(tab==='operations') {const o=data.operations;const w=o.worker;panel.innerHTML=`<div class="page-header"><div><h2>AI, Worker, Storage, and Publication Health</h2><p>Operational signals exclude credentials and other secret values.</p></div><span class="badge badge-cyan">v${esc(o.app_version)}</span></div><section class="stats"><div class="stat"><strong>${o.ai.enabled?'ON':'OFF'}</strong><span>Web AI ${esc(o.ai.model||'')}</span></div><div class="stat"><strong>${esc(o.ai.job_counts?.QUEUED||0)}</strong><span>AI queued</span></div><div class="stat"><strong>${esc(o.ai.job_counts?.FAILED||0)}</strong><span>AI failed</span></div><div class="stat"><strong>${o.ai.average_processing_seconds==null?'—':esc(o.ai.average_processing_seconds)}</strong><span>Avg AI seconds</span></div><div class="stat"><strong>${esc(o.lifecycle.capabilities_due)}</strong><span>Capabilities due</span></div><div class="stat"><strong>${esc(o.lifecycle.knowledge_due)}</strong><span>Knowledge due</span></div><div class="stat"><strong>${esc(o.lifecycle.knowledge_expired)}</strong><span>Knowledge expired</span></div></section><div class="grid grid-2"><section class="card"><h3>Worker heartbeat</h3>${w?`<p>${readinessBadge(['HEALTHY','RUNNING'].includes(w.status)?'READY':'REVIEW_REQUIRED')}</p><p><strong>Version:</strong> ${esc(w.app_version||'Unknown')}</p><p><strong>Last seen:</strong> ${esc(fmtDateTime(w.last_seen_at))}</p><p><strong>Age:</strong> ${w.age_seconds==null?'Unknown':esc(Math.round(w.age_seconds))+' seconds'}</p><p><strong>Storage configured:</strong> ${w.storage_configured?'Yes':'No'}</p><p><strong>Worker AI:</strong> ${w.details?.ai_enabled?'Enabled':'Disabled'}${w.details?.ai_model?` — ${esc(w.details.ai_model)}`:''}</p>`:'<div class="validation-item ERROR">No worker heartbeat has been recorded.</div>'}</section><section class="card"><h3>Storage and publication</h3><p>${o.storage.configured?'<span class="badge badge-success">STORAGE CONFIGURED</span>':'<span class="badge badge-danger">STORAGE NOT CONFIGURED</span>'}</p><p><strong>Mode:</strong> ${esc(o.storage.mode||'')}</p><p><strong>Last successful publication:</strong> ${o.last_successful_publication?esc(fmtDateTime(o.last_successful_publication.completed_at)):'None recorded'}</p></section></div>${o.ai.recent_failures?.length?`<section class="card"><h3>Recent AI failures</h3>${o.ai.recent_failures.map(item=>`<div class="validation-item ERROR"><strong>${esc(item.purpose.replaceAll('_',' '))}</strong><p>${esc(item.error||'No error detail')}</p><span class="help">${esc(fmtDateTime(item.created_at))}</span></div>`).join('')}</section>`:''}`;}
  if(tab==='capabilities') panel.innerHTML=`<div class="page-header"><div><h2>Controlled capability catalog</h2><p>Only approved, current capabilities are available for prospect recommendations and AI grounding.</p></div><button class="btn btn-primary" data-action="new-capability">Add capability</button></div><div class="table-wrap"><table><thead><tr><th>Code</th><th>Domain / version</th><th>Capability</th><th>Status</th><th>Lifecycle</th><th>Source / action</th></tr></thead><tbody>${data.capabilities.map(c=>`<tr><td>${esc(c.capability_code)}</td><td>${esc(c.domain)}${c.product_version?`<br><span class="badge badge-cyan">${esc(c.product_version)}</span>`:''}</td><td><strong>${esc(c.name)}</strong><br><span class="help">${esc(c.controlled_description)}</span></td><td><span class="badge ${c.status==='APPROVED'?'badge-success':c.status==='RETIRED'?'badge-danger':'badge-warning'}">${esc(c.status)}</span></td><td>Review due: ${fmtDate(c.review_due_at)}<br><span class="help">Last reviewed: ${fmtDate(c.last_reviewed_at)}</span></td><td>${esc(c.source||'')}<div class="card-actions"><button class="btn btn-ghost btn-small" data-action="edit-capability" data-id="${c.id}">Review / edit</button>${c.status==='PROPOSED'?`<button class="btn btn-primary btn-small" data-action="review-capability" data-id="${c.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-capability" data-id="${c.id}" data-decision="REJECTED">Retire</button>`:''}</div></td></tr>`).join('')}</tbody></table></div>`;
  if(tab==='knowledge') panel.innerHTML=`<div class="page-header"><div><h2>Discovery knowledge repository</h2><p>Only approved, non-expired knowledge can ground Cloud Inventory solution wording. Prospect-specific content remains isolated until explicitly de-identified and approved.</p></div><div class="toolbar"><button class="btn btn-primary" data-action="new-knowledge">Add knowledge</button><button class="btn btn-secondary" data-action="import-knowledge">Import historical document</button></div></div><div class="table-wrap"><table><thead><tr><th>Source</th><th>Title / content</th><th>Area / capability</th><th>Scope</th><th>Status</th><th>Lifecycle</th><th>Review</th></tr></thead><tbody>${data.knowledge.map(k=>{const cap=data.capabilities.find(c=>c.id===k.capability_id);return `<tr><td>${esc(k.source_type)}<br><span class="help">${esc(k.source_ref||'')}</span></td><td><strong>${esc(k.title)}</strong><br><span class="help">${esc(k.content.slice(0,320))}${k.content.length>320?'…':''}</span></td><td>${esc(k.process_module||'General')}${cap?`<br><span class="badge badge-cyan">${esc(cap.capability_code)}</span>`:''}</td><td>${k.prospect_id?'<span class="badge badge-warning">Prospect specific</span>':'<span class="badge badge-cyan">Shared internal</span>'}${k.reusable_across_prospects?'<span class="badge badge-success">Reusable</span>':''}</td><td><span class="badge ${k.approval_state==='APPROVED'?'badge-success':k.approval_state==='REJECTED'?'badge-danger':'badge-warning'}">${esc(k.approval_state)}</span></td><td>Review: ${fmtDate(k.review_due_at)}<br>Expires: ${fmtDate(k.expires_at)}</td><td><button class="btn btn-ghost btn-small" data-action="review-knowledge-detail" data-id="${k.id}">Review / edit</button>${k.approval_state==='PENDING'?`<button class="btn btn-primary btn-small" data-action="review-knowledge" data-id="${k.id}" data-decision="APPROVED">Approve isolated</button><button class="btn btn-danger btn-small" data-action="review-knowledge" data-id="${k.id}" data-decision="REJECTED">Reject</button>`:''}</td></tr>`;}).join('')}</tbody></table></div>`;
  if(tab==='retention') panel.innerHTML=`<div class="page-header"><div><h2>Retention review</h2><p>Export is mandatory before permanent prospect deletion. Legal holds block archival and deletion.</p></div></div><div class="table-wrap"><table><thead><tr><th>Prospect</th><th>Status</th><th>Due</th><th>Last export</th><th>Actions</th></tr></thead><tbody>${data.retention.map(p=>`<tr><td><strong>${esc(p.name)}</strong>${p.legal_hold?'<br><span class="badge badge-danger">Legal hold</span>':''}</td><td>${esc(p.status)}</td><td>${fmtDate(p.retention_due_at)}</td><td>${fmtDate(p.last_exported_at)}</td><td><a class="btn btn-ghost btn-small" href="/api/prospects/${p.id}/export">Export</a>${p.last_exported_at&&!p.legal_hold?`<button class="btn btn-danger btn-small" data-action="delete-prospect" data-id="${p.id}" data-name="${esc(p.name)}">Delete</button>`:''}</td></tr>`).join('')||'<tr><td colspan="5">No prospects are due within the selected window.</td></tr>'}</tbody></table></div>`;
  if(tab==='branding') { const b=data.branding; panel.innerHTML=`<div class="card"><h2>Default Denver-derived branding</h2><form id="branding-form"><div class="grid grid-3"><div class="field"><label>Primary color</label><input name="primary_color" type="color" value="${esc(b.primary_color)}"></div><div class="field"><label>Secondary color</label><input name="secondary_color" type="color" value="${esc(b.secondary_color)}"></div><div class="field"><label>Accent color</label><input name="accent_color" type="color" value="${esc(b.accent_color)}"></div></div><div class="grid grid-2"><div class="field"><label>Heading font</label><input name="heading_font" value="${esc(b.heading_font)}"></div><div class="field"><label>Body font</label><input name="body_font" value="${esc(b.body_font)}"></div></div><div class="field"><label>Confidentiality statement</label><textarea name="confidentiality_text">${esc(b.confidentiality_text)}</textarea></div><div class="grid grid-2"><div class="field"><label>Draft watermark</label><input name="draft_watermark" value="${esc(b.draft_watermark)}"></div><div class="field"><label>Footer</label><input name="footer_text" value="${esc(b.footer_text)}"></div></div><input type="hidden" name="brand_id" value="${b.id}"><button class="btn btn-primary" type="submit">Save branding</button></form></div><div class="card"><h2>Report logo</h2><p class="help">${b.has_custom_logo?'A custom logo is active. Uploading a new image replaces it.':'The standard Cloud Inventory logo is active.'}</p><form id="branding-logo-form"><input type="hidden" name="brand_id" value="${b.id}"><div class="field"><label>Logo image</label><input name="file" type="file" accept="image/png,image/jpeg,image/webp" required></div><button class="btn btn-primary" type="submit">Upload report logo</button></form></div>`; }
  if(tab==='audit') panel.innerHTML=`<div class="table-wrap"><table><thead><tr><th>When</th><th>Action</th><th>Target</th><th>Actor</th><th>Metadata</th></tr></thead><tbody>${data.audit.map(a=>`<tr><td>${fmtDate(a.created_at)}</td><td>${esc(a.action)}</td><td>${esc(a.target_type)}<br><span class="help">${esc(a.target_id||'')}</span></td><td>${esc(a.actor_user_id||'System')}</td><td><code>${esc(JSON.stringify(a.metadata))}</code></td></tr>`).join('')}</tbody></table></div>`;
}

function showSectionPhotoUpload(section) {
  if (!section) { toast('Select a report section before adding photographs.', 'error'); return; }
  showModal('Add site photographs', `
    <p>Upload one or more photographs directly to <strong>${esc(section.title)}</strong>. On a phone or tablet, the file picker can use the camera or photo library.</p>
    <form id="section-photo-form">
      <input type="hidden" name="section_id" value="${esc(section.id)}">
      <div class="field"><label>Photographs</label><input name="file" type="file" accept="image/*" multiple required></div>
      <div class="field"><label>Caption / observation (optional)</label><textarea name="caption" placeholder="Describe what the photograph shows or why it is relevant to this operational area."></textarea></div>
      <p class="help">New photographs are included inline by default. A reviewer can later mark individual photographs as supporting only.</p>
      <button class="btn btn-primary btn-wide" type="submit">Upload photographs</button>
    </form>`, '');
}

function showDeleteProspect(id,name){showModal('Permanently delete prospect',`<p>This action permanently deletes the prospect workspace, reports, evidence, publications, and audit-linked customer data. A completed export is required.</p><form id="delete-prospect-form"><input type="hidden" name="prospect_id" value="${esc(id)}"><div class="field"><label>Type the prospect name to confirm</label><input name="confirm_name" required></div><label><input type="checkbox" name="confirm_exported" required> I confirm that the workspace export has been downloaded and retained.</label><button class="btn btn-danger btn-wide" type="submit">Permanently delete ${esc(name)}</button></form>`,'');}
function showNewUser(){showModal('Create user',`<form id="user-form"><div class="field"><label>Username</label><input name="username" required></div><div class="field"><label>Display name</label><input name="display_name"></div><div class="field"><label>Email</label><input name="email" type="email" required></div><div class="field"><label>Temporary password</label><input name="password" type="password" minlength="14" required></div><div class="field"><label>Roles</label><label><input type="checkbox" name="roles" value="CONTRIBUTOR" checked> Contributor</label><label><input type="checkbox" name="roles" value="REVIEWER"> Reviewer</label><label><input type="checkbox" name="roles" value="OWNER"> Owner</label><label><input type="checkbox" name="roles" value="ADMIN"> Administrator</label></div><button class="btn btn-primary btn-wide" type="submit">Create user</button></form>`,'');}
function showNewCapability(){showModal('Add controlled capability',`<form id="capability-form"><div class="grid grid-2"><div class="field"><label>Code</label><input name="capability_code" required></div><div class="field"><label>Domain</label><input name="domain" required></div></div><div class="grid grid-2"><div class="field"><label>Name</label><input name="name" required></div><div class="field"><label>Applicable product version</label><input name="product_version" placeholder="For example: Current SaaS release"></div></div><div class="field"><label>Controlled description</label><textarea name="controlled_description" required></textarea></div><div class="field"><label>Typical prerequisites</label><textarea name="typical_prerequisites"></textarea></div><div class="field"><label>Limitations</label><textarea name="limitations"></textarea></div><div class="grid grid-2"><div class="field"><label>Status</label><select name="status"><option>PROPOSED</option><option>APPROVED</option></select></div><div class="field"><label>Next review date</label><input name="review_due_at" type="datetime-local"></div></div><div class="field"><label>Source</label><input name="source"></div><button class="btn btn-primary btn-wide" type="submit">Add capability</button></form>`,'');}

function showEditCapability(capabilityId) {
  const item=window.__adminData?.capabilities?.find(capability=>capability.id===capabilityId);
  if(!item){toast('Capability not found.','error');return;}
  showModal('Review and edit capability',`<form id="capability-edit-form"><input type="hidden" name="capability_id" value="${item.id}"><input type="hidden" name="expected_version" value="${item.version}"><div class="grid grid-2"><div class="field"><label>Code</label><input name="capability_code" value="${esc(item.capability_code)}" required></div><div class="field"><label>Domain</label><input name="domain" value="${esc(item.domain)}" required></div></div><div class="grid grid-2"><div class="field"><label>Name</label><input name="name" value="${esc(item.name)}" required></div><div class="field"><label>Applicable product version</label><input name="product_version" value="${esc(item.product_version||'')}"></div></div><div class="field"><label>Controlled description</label><textarea name="controlled_description" required>${esc(item.controlled_description)}</textarea></div><div class="field"><label>Typical prerequisites</label><textarea name="typical_prerequisites">${esc(item.typical_prerequisites||'')}</textarea></div><div class="field"><label>Limitations</label><textarea name="limitations">${esc(item.limitations||'')}</textarea></div><div class="grid grid-2"><div class="field"><label>Status</label><select name="status"><option ${item.status==='PROPOSED'?'selected':''}>PROPOSED</option><option ${item.status==='APPROVED'?'selected':''}>APPROVED</option><option ${item.status==='RETIRED'?'selected':''}>RETIRED</option></select></div><div class="field"><label>Next review date</label><input name="review_due_at" type="datetime-local" value="${item.review_due_at?esc(item.review_due_at.slice(0,16)):''}"></div></div><div class="field"><label>Source</label><input name="source" value="${esc(item.source||'')}"></div><button class="btn btn-primary btn-wide" type="submit">Save capability</button></form>`,'');
}



function knowledgeModuleOptions(selected='') {
  const values = [...QUICK_ENTRY_AREAS.filter(item=>item.value!=='OTHER'), {value:'MANUFACTURING',label:'Manufacturing'}, {value:'FIELD_INVENTORY',label:'Field Inventory'}];
  const unique = [...new Map(values.map(item=>[item.value,item])).values()];
  return `<option value="" ${!selected?'selected':''}>General / cross-process</option>${unique.map(item=>`<option value="${item.value}" ${item.value===selected?'selected':''}>${esc(item.label)}</option>`).join('')}`;
}

function showNewKnowledge() {
  const data=window.__adminData;
  const capabilities=data.capabilities.filter(item=>item.status==='APPROVED');
  showModal('Add controlled knowledge', `<form id="knowledge-form">
    <div class="grid grid-2"><div class="field"><label>Source type</label><input name="source_type" value="INTERNAL_REFERENCE" required></div><div class="field"><label>Source reference</label><input name="source_ref" placeholder="Document, template, or source identifier"></div></div>
    <div class="field"><label>Title</label><input name="title" required></div>
    <div class="grid grid-2"><div class="field"><label>Operational area</label><select name="process_module">${knowledgeModuleOptions()}</select></div><div class="field"><label>Linked approved capability</label><select name="capability_id"><option value="">None</option>${capabilities.map(c=>`<option value="${c.id}">${esc(c.capability_code)} — ${esc(c.name)}</option>`).join('')}</select></div></div>
    <div class="field"><label>Knowledge content</label><textarea name="content" required placeholder="Approved wording, operational explanation, prerequisites, limitations, or reusable implementation guidance."></textarea></div>
    <div class="grid grid-2"><div class="field"><label>Prospect scope</label><select name="prospect_id"><option value="">Shared internal candidate</option>${data.prospects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></div><div class="field"><label>Classification</label><select name="classification"><option>INTERNAL</option><option>CONFIDENTIAL</option><option>PUBLIC</option></select></div></div>
    <div class="grid grid-2"><div class="field"><label>Next review date</label><input name="review_due_at" type="datetime-local"></div><div class="field"><label>Expiration date</label><input name="expires_at" type="datetime-local"></div></div><label><input type="checkbox" name="reusable_across_prospects"> Mark as reusable across prospects</label><p class="help">Prospect-specific content cannot become reusable until it is reviewed and explicitly de-identified.</p>
    <button class="btn btn-primary btn-wide" type="submit">Create pending knowledge entry</button>
  </form>`, '');
}

function showImportKnowledge() {
  const data=window.__adminData;
  const capabilities=data.capabilities.filter(item=>item.status==='APPROVED');
  showModal('Import historical knowledge document', `<p>Supported documents are converted to controlled text chunks and placed in <strong>Pending</strong> status. Imported content cannot ground AI output until it is reviewed and approved.</p><form id="knowledge-import-form">
    <div class="field"><label>Knowledge source title</label><input name="title" required placeholder="For example: Approved Warehouse Discovery Report Template"></div>
    <div class="grid grid-2"><div class="field"><label>Operational area</label><select name="process_module">${knowledgeModuleOptions()}</select></div><div class="field"><label>Linked approved capability</label><select name="capability_id"><option value="">None / multiple capabilities</option>${capabilities.map(c=>`<option value="${c.id}">${esc(c.capability_code)} — ${esc(c.name)}</option>`).join('')}</select></div></div>
    <div class="field"><label>Source scope</label><select name="prospect_id"><option value="">Shared internal reference candidate</option>${data.prospects.map(p=>`<option value="${p.id}">Prospect-specific — ${esc(p.name)}</option>`).join('')}</select><small>Select the original prospect when importing a customer-specific historical report. It will remain isolated until de-identified.</small></div>
    <div class="field"><label>Historical document</label><input name="file" type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xlsm,.json,.xml" required></div>
    <button class="btn btn-primary btn-wide" type="submit">Import for review</button>
  </form>`, '');
}

function showReviewKnowledge(entryId) {
  const data=window.__adminData;
  const item=data.knowledge.find(k=>k.id===entryId);
  if(!item){toast('Knowledge entry not found.','error');return;}
  const prospect=data.prospects.find(p=>p.id===item.prospect_id);
  showModal('Review controlled knowledge', `<form id="knowledge-review-form"><input type="hidden" name="entry_id" value="${item.id}">
    <div class="field"><label>Title</label><input name="title" value="${esc(item.title)}" required></div>
    <div class="field"><label>Controlled content</label><textarea name="content" required>${esc(item.content)}</textarea></div>
    ${prospect?`<div class="validation-item WARNING">This entry originated from <strong>${esc(prospect.name)}</strong>. To reuse it across prospects, remove customer-identifying and customer-specific information before selecting reusable.</div>`:''}
    <label><input type="checkbox" name="reusable_across_prospects" ${item.reusable_across_prospects?'checked':''}> Approved for reuse across prospects</label>
    <div class="grid grid-2"><div class="field"><label>Next review date</label><input name="review_due_at" type="datetime-local" value="${item.review_due_at?esc(item.review_due_at.slice(0,16)):''}"></div><div class="field"><label>Expiration date</label><input name="expires_at" type="datetime-local" value="${item.expires_at?esc(item.expires_at.slice(0,16)):''}"></div></div><div class="field"><label>Decision</label><select name="decision"><option value="APPROVED" ${item.approval_state==='APPROVED'?'selected':''}>APPROVED</option><option value="REJECTED" ${item.approval_state==='REJECTED'?'selected':''}>REJECTED</option></select></div>
    <div class="field"><label>Review note</label><textarea name="note" placeholder="Record de-identification or approval rationale."></textarea></div>
    <button class="btn btn-primary btn-wide" type="submit">Save knowledge review</button>
  </form>`, '');
}

function formObject(form, checkboxes = []) {
  const fd = new FormData(form); const obj={};
  for(const [k,v] of fd.entries()) { if(checkboxes.includes(k)){(obj[k]??=[]).push(v);} else obj[k]=v; }
  for(const cb of form.querySelectorAll('input[type="checkbox"]')) if(!checkboxes.includes(cb.name)) obj[cb.name]=cb.checked;
  return obj;
}

async function uploadQuickEntryFiles(input) {
  const reportId = state.report?.report?.id;
  const area = document.getElementById('quick-entry-area')?.value || '';
  const section = quickEntrySection(area);
  if (!area) throw new Error('Select an Area of operation before adding evidence.');
  if (!section) throw new Error(`The ${quickEntryAreaLabel(area)} report section is not available.`);
  const files = Array.from(input.files || []);
  if (!files.length) return;
  const captionInput = document.getElementById('quick-entry-caption');
  const caption = captionInput?.value?.trim() || '';
  for (const file of files) {
    if (!navigator.onLine) {
      await queueEvidence({reportId, sectionId:section.id, caption, placement:'INLINE', file});
    } else {
      const fd = new FormData();
      fd.append('section_id', section.id);
      if (caption) fd.append('caption', caption);
      fd.append('classification', 'CONFIDENTIAL');
      fd.append('file', file);
      await api(`/api/reports/${reportId}/evidence`, {method:'POST', body:fd}, false);
    }
  }
  input.value = '';
  if (captionInput) captionInput.value = '';
  toast(navigator.onLine ? `Evidence added to ${section.title}.` : `Evidence queued for ${section.title}.`, 'success');
  updateQueueCount();
}

async function handleSubmit(event) {
  const form=event.target; if(!(form instanceof HTMLFormElement)) return;
  event.preventDefault();
  try {
    if(form.id==='login-form'){const o=formObject(form);const me=await api('/api/auth/login',{method:'POST',body:o},false);state.me=me;state.csrf=me.csrf_token;location.hash='#/prospects';if(me.force_password_change)showPasswordModal();return;}
    if(form.id==='password-form'){
      const o=formObject(form);

      if(o.new_password!==o.confirm_password){
        throw new Error('New passwords do not match.');
      }

      await api(
        '/api/auth/change-password',
        {
          method:'POST',
          body:{
            current_password:o.current_password,
            new_password:o.new_password
          }
        },
        false
      );

      const me=await api('/api/auth/me',{},false);
      state.me=me;
      state.csrf=me.csrf_token;

      closeModal();
      toast('Password updated.','success');
      await route();
      return;
    }
    if(form.id==='prospect-onboarding-form'){
      const o=formObject(form);
      const createSite=o.create_site===true;
      const createEngagement=o.create_engagement===true;
      const payload={
        prospect:{
          name:o.prospect_name,
          industry:o.prospect_industry||null,
          opportunity:o.prospect_opportunity||null,
        },
        site:createSite?{
          name:o.site_name,
          address:o.site_address||null,
          timezone:o.site_timezone||null,
        }:null,
        engagement:createEngagement?{
          name:o.engagement_name,
          survey_date:o.engagement_survey_date||null,
          objectives:o.engagement_objectives||null,
        }:null,
      };
      const result=await api('/api/prospects/onboard',{method:'POST',body:payload},false);
      closeModal();
      state.activeProspectTab=result.next_tab||'reports';
      const created=[result.site_id?'site':null,result.engagement_id?'engagement':null].filter(Boolean);
      toast(created.length?`Prospect, ${created.join(' and ')} created.`:'Prospect created.','success');
      location.hash=`#/prospect/${result.id}`;
      return;
    }
    const prospectId=state.prospect?.prospect?.id;
    if(form.id==='site-form'){await api(`/api/prospects/${prospectId}/sites`,{method:'POST',body:formObject(form)});closeModal();toast('Site added.','success');renderProspect(prospectId,'sites');return;}
    if(form.id==='engagement-form'){const o=formObject(form);if(!o.site_id)o.site_id=null;if(!o.survey_date)o.survey_date=null;await api(`/api/prospects/${prospectId}/engagements`,{method:'POST',body:o});closeModal();toast('Engagement added.','success');renderProspect(prospectId,'engagements');return;}
    if(form.id==='report-form'){const o=formObject(form);const result=await api(`/api/prospects/${prospectId}/reports`,{method:'POST',body:o});closeModal();if(result.id)location.hash=`#/report/${result.id}`;return;}
    if(form.id==='prospect-member-form'){const fd=new FormData(form);await api(`/api/prospects/${prospectId}/members`,{method:'POST',body:fd});closeModal();renderProspect(prospectId,'team');return;}
    if(form.id==='prospect-logo-form'){const fd=new FormData(form);const id=fd.get('prospect_id');fd.delete('prospect_id');await api(`/api/prospects/${id}/logo`,{method:'POST',body:fd},false);closeModal();toast('Prospect logo updated.','success');renderProspect(id,state.activeProspectTab);return;}
    if(form.id==='archive-prospect-form'){await api(`/api/prospects/${prospectId}/archive`,{method:'POST',body:formObject(form)});closeModal();toast('Prospect archived.','success');renderProspect(prospectId);return;}
    const reportId=state.report?.report?.id; const section=selectedSection();
    if(form.id==='section-photo-form'){
      const fd=new FormData(form);
      const targetSectionId=String(fd.get('section_id')||'');
      const targetSection=state.report?.sections?.find(item=>item.id===targetSectionId && item.state!=='REMOVED');
      if(!targetSection)throw new Error('The selected report section is no longer available.');
      const files=Array.from(form.elements.file?.files||[]);
      if(!files.length)throw new Error('Select at least one photograph to upload.');
      const caption=String(fd.get('caption')||'').trim();
      for(const file of files){
        if(!file.type?.startsWith('image/'))throw new Error(`${file.name} is not an image file.`);
        if(!navigator.onLine){
          await queueEvidence({reportId,sectionId:targetSection.id,caption,placement:'INLINE',file});
        }else{
          const upload=new FormData();
          upload.append('section_id',targetSection.id);
          if(caption)upload.append('caption',caption);
          upload.append('placement','INLINE');
          upload.append('classification','CONFIDENTIAL');
          upload.append('file',file,file.name);
          await api(`/api/reports/${reportId}/evidence`,{method:'POST',body:upload},false);
        }
      }
      closeModal();
      updateQueueCount();
      toast(navigator.onLine?`Photograph${files.length===1?'':'s'} added to ${targetSection.title}.`:`Photograph${files.length===1?'':'s'} queued for ${targetSection.title}.`,'success');
      await renderReport(reportId,targetSection.id);
      return;
    }
    if(form.id==='quick-entry-note-form'){
      const area=document.getElementById('quick-entry-area')?.value||'';
      const destination=quickEntrySection(area);
      if(!area)throw new Error('Select an Area of operation before capturing a note.');
      if(!destination)throw new Error(`The ${quickEntryAreaLabel(area)} report section is not available.`);
      const o=formObject(form);
      await api(`/api/reports/${reportId}/quick-capture`,{method:'POST',body:{section_id:destination.id,note:o.note,finding_type:o.finding_type,client_mutation_id:uid()}});
      form.elements.note.value='';
      form.elements.note.focus();
      toast(`${quickEntryAreaLabel(area)} ${o.finding_type.replaceAll('_',' ').toLowerCase()} captured.`, 'success');
      return;
    }
    if(form.id==='finding-form'){const o=formObject(form);await api(`/api/reports/${reportId}/findings`,{method:'POST',body:{...o,section_id:section.id,client_mutation_id:uid()}});closeModal();renderReport(reportId,section.id);return;}
    if(form.id==='section-form'){const o=formObject(form);o.process_module=o.process_module||null;const result=await api(`/api/reports/${reportId}/sections`,{method:'POST',body:o});closeModal();renderReport(reportId,result.id||section.id);return;}
    if(form.id==='remove-section-form'){const o=formObject(form);await api(`/api/reports/${reportId}/sections/${section.id}`,{method:'PATCH',body:{state:'REMOVED',removed_reason:o.removed_reason}});closeModal();renderReport(reportId);return;}
    if(form.id==='mapping-form'){await api(`/api/reports/${reportId}/capability-mappings`,{method:'POST',body:formObject(form)});closeModal();renderReport(reportId,section.id);return;}
    if(form.id==='benefit-form'){const o=formObject(form);o.finding_id=null;o.capability_mapping_id=o.source_ref?.startsWith('mapping:')?o.source_ref.split(':')[1]:null;if(o.capability_mapping_id)o.source_ref=null;await api(`/api/reports/${reportId}/benefits`,{method:'POST',body:o});closeModal();toast('Benefit created for reviewer approval.','success');renderReport(reportId,section.id);return;}
    if(form.id==='section-demo-priority-form'){const o=formObject(form);o.estimated_minutes=o.estimated_minutes?Number(o.estimated_minutes):null;o.expected_version=o.expected_version?Number(o.expected_version):null;await api(`/api/reports/${reportId}/sections/${o.section_id}/demo-priority`,{method:'PUT',body:o});toast('Demo priority saved.','success');renderReport(reportId,section.id);return;}
    if(form.id==='demo-settings-form'){const o=formObject(form);o.duration_minutes=Number(o.duration_minutes||45);o.expected_version=o.expected_version?Number(o.expected_version):null;await api(`/api/reports/${reportId}/demo-settings`,{method:'PUT',body:o});toast('Demo settings saved.','success');renderReport(reportId,'report-preview');return;}
    if(form.id==='comment-form'){await api(`/api/reports/${reportId}/comments`,{method:'POST',body:formObject(form)});form.reset();toast('Comment added.','success');renderReport(reportId,section.id);return;}
    if(form.id==='delete-report-form'){const o=formObject(form);const prospect=state.report.report.prospect_id;await api(`/api/reports/${reportId}`,{method:'DELETE',body:o},false);closeModal();toast('Report permanently deleted.','success');location.hash=`#/prospect/${prospect}`;return;}
    if(form.id==='merge-form'){const o=formObject(form,['source_report_ids']);if(!o.source_report_ids?.length)throw new Error('Select at least one source report.');await api('/api/reports/merge',{method:'POST',body:o},false);closeModal();toast('Reports merged.','success');location.hash=`#/report/${o.target_report_id}`;route();return;}
    if(form.id==='delete-prospect-form'){const o=formObject(form);const id=o.prospect_id;delete o.prospect_id;await api(`/api/admin/prospects/${id}`,{method:'DELETE',body:o},false);closeModal();toast('Prospect permanently deleted.','success');renderAdmin();return;}
    if(form.id==='user-form'){const o=formObject(form,['roles']);await api('/api/admin/users',{method:'POST',body:o});closeModal();toast('User created.','success');renderAdmin();return;}
    if(form.id==='capability-form'){const o=formObject(form);o.product_version=o.product_version||null;o.review_due_at=o.review_due_at||null;await api('/api/admin/capabilities',{method:'POST',body:o});closeModal();toast('Capability added.','success');renderAdmin();return;}
    if(form.id==='capability-edit-form'){const o=formObject(form);const id=o.capability_id;delete o.capability_id;o.expected_version=Number(o.expected_version);o.product_version=o.product_version||null;o.review_due_at=o.review_due_at||null;await api(`/api/admin/capabilities/${id}`,{method:'PATCH',body:o});closeModal();toast('Capability updated.','success');renderAdmin();return;}
    if(form.id==='knowledge-form'){const o=formObject(form);o.process_module=o.process_module||null;o.capability_id=o.capability_id||null;o.prospect_id=o.prospect_id||null;o.review_due_at=o.review_due_at||null;o.expires_at=o.expires_at||null;if(o.prospect_id&&o.reusable_across_prospects)throw new Error('Prospect-specific knowledge must be de-identified during review before it can be reusable.');await api('/api/admin/knowledge',{method:'POST',body:o});closeModal();toast('Knowledge entry created for review.','success');renderAdmin();return;}
    if(form.id==='knowledge-import-form'){const fd=new FormData(form);const result=await api('/api/admin/knowledge/import',{method:'POST',body:fd},false);closeModal();toast(result.message||`${result.created} knowledge entries imported for review.`,'success');renderAdmin();return;}
    if(form.id==='knowledge-review-form'){const o=formObject(form);const id=o.entry_id;delete o.entry_id;o.review_due_at=o.review_due_at||null;o.expires_at=o.expires_at||null;await api(`/api/admin/knowledge/${id}/review`,{method:'POST',body:o});closeModal();toast('Knowledge review saved.','success');renderAdmin();return;}
    if(form.id==='branding-form'){const o=formObject(form);const id=o.brand_id;delete o.brand_id;await api(`/api/admin/branding/${id}`,{method:'PATCH',body:o});toast('Branding updated.','success');renderAdmin();return;}
    if(form.id==='branding-logo-form'){const fd=new FormData(form);const id=fd.get('brand_id');fd.delete('brand_id');await api(`/api/admin/branding/${id}/logo`,{method:'POST',body:fd},false);toast('Report logo updated.','success');renderAdmin();return;}
  } catch(error){toast(error.message,'error');}
}

async function handleClick(event) {
  const target=event.target.closest('[data-action]'); if(!target)return;
  const action=target.dataset.action;
  try {
    if(action==='go'){location.hash=target.dataset.route;return;}
    if(action==='close-modal'){closeModal();return;}
    if(action==='user-menu'){showUserMenu();return;}
    if(action==='change-password'){closeModal();showPasswordModal();return;}
    if(action==='logout'){await api('/api/auth/logout',{method:'POST'},false);state.me=null;state.csrf=null;closeModal();renderLogin();return;}
    if(action==='new-prospect'){showNewProspect();return;}
    if(action==='prospect-tab'){renderProspect(state.prospect.prospect.id,target.dataset.tab);return;}
    if(action==='new-site'){showNewSite();return;}
    if(action==='new-engagement'){showNewEngagement();return;}
    if(action==='new-report'){showNewReport();return;}
    if(action==='add-prospect-member'){showAddProspectMember();return;}
    if(action==='upload-prospect-logo'){showProspectLogoUpload();return;}
    if(action==='archive-prospect'){showArchiveProspect();return;}
    if(action==='open-quick-entry'){navigateReportScreen('quick-entry');return;}
    if(action==='open-section'){navigateReportScreen(target.dataset.id);return;}
    if(action==='open-report-preview'){navigateReportScreen('report-preview');return;}
    if(action==='add-section'){showAddSection();return;}
    if(action==='remove-section'){showRemoveSection();return;}
    if(action==='new-finding'){showDetailedFinding();return;}
    if(action==='section-upload-photo'){showSectionPhotoUpload(selectedSection());return;}
    if(action==='focus-photo'||action==='go-quick-entry'){navigateReportScreen('quick-entry');return;}
    if(action==='quick-take-photo'){const area=document.getElementById('quick-entry-area')?.value||'';if(!area)throw new Error('Select an Area of operation before taking a photo.');document.getElementById('quick-entry-camera')?.click();return;}
    if(action==='quick-choose-file'){const area=document.getElementById('quick-entry-area')?.value||'';if(!area)throw new Error('Select an Area of operation before choosing a file.');document.getElementById('quick-entry-file')?.click();return;}
    if(action==='map-capability'){showMapCapability();return;}
    if(action==='new-benefit'){showBenefit();return;}
    if(action==='merge-reports'){showMergeReports();return;}
    if(action==='delete-report'){showDeleteReport();return;}
    const reportId=state.report?.report?.id;const section=selectedSection();const screenId=currentReportScreen();
    if(action==='review-mapping'){await api(`/api/reports/${reportId}/capability-mappings/${target.dataset.id}/review`,{method:'POST',body:{decision:target.dataset.decision}});renderReport(reportId,section.id);return;}
    if(action==='review-benefit'){await api(`/api/reports/${reportId}/benefits/${target.dataset.id}/review`,{method:'POST',body:{decision:target.dataset.decision}});renderReport(reportId,section.id);return;}
    if(action==='review-evidence'){await api(`/api/reports/${reportId}/evidence/${target.dataset.id}/review`,{method:'POST',body:{include_in_report:target.dataset.include==='true'}});toast('Evidence disposition updated.','success');renderReport(reportId,section.id);return;}
    if(action==='resolve-comment'){await api(`/api/reports/${reportId}/comments/${target.dataset.id}/resolve`,{method:'POST'});renderReport(reportId,section.id);return;}
    if(action==='ai-enhance-observations'){await showAiEnhancement(section);return;}
    if(action==='section-version-history'){await showSectionContentHistory(section);return;}
    if(action==='generate-solution-approach'){await flushSolutionApproachSave(section);await showSolutionApproach(section);return;}
    if(action==='generate-targeted-benefits'){await flushSolutionApproachSave(section);await showTargetedBenefits(section);return;}
    if(action==='generate-demo-plan'){await showDemoPlan();return;}
    if(action==='demo-plan-history'){await showDemoPlanHistory();return;}
    if(action==='solution-version-history'){await showSolutionContentHistory(section);return;}
    if(action==='speak-ai-text'){speakAiText();return;}
    if(action==='refine-ai-enhancement'){await requestAiEnhancement(section,target.dataset.suggestionId);return;}
    if(action==='accept-ai-enhancement'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'APPROVED',note:'Accepted from AI observation enhancement comparison.'}},false);toast('AI-enhanced current-operations wording accepted. Original input has been retained in version history.','success');closeModal();await renderReport(reportId,section.id);return;}
    if(action==='refine-solution-approach'){await requestSolutionApproach(section,target.dataset.suggestionId);return;}
    if(action==='accept-solution-approach'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'APPROVED',note:'Accepted from Cloud Inventory solution intelligence comparison.'}},false);toast('Cloud Inventory approach accepted and approved functionality mappings applied.','success');closeModal();await renderReport(reportId,section.id);return;}
    if(action==='refine-targeted-benefits'){await requestTargetedBenefits(section,target.dataset.suggestionId);return;}
    if(action==='accept-targeted-benefits'){const selected=Array.from(document.querySelectorAll('[data-benefit-index]:checked')).map(item=>Number(item.dataset.benefitIndex));await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'APPROVED',note:'Selected from targeted benefit comparison.',selected_item_indexes:selected}},false);toast('Selected benefits added for reviewer approval.','success');closeModal();await renderReport(reportId,section.id);return;}
    if(action==='refine-demo-plan'){await requestDemoPlan(target.dataset.suggestionId);return;}
    if(action==='accept-demo-plan'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'APPROVED',note:'Accepted from demo orchestration comparison.'}},false);toast('Demo plan accepted.','success');closeModal();await renderReport(reportId,'report-preview');return;}
    if(action==='generate-executive-summary'){await showExecutiveSummary();return;}
    if(action==='executive-summary-history'){await showExecutiveSummaryHistory();return;}
    if(action==='refine-executive-summary'){await requestExecutiveSummary(target.dataset.suggestionId);return;}
    if(action==='accept-executive-summary'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'APPROVED',note:'Accepted from executive summary comparison.'}},false);toast('Executive summary accepted.','success');closeModal();await renderReport(reportId,'report-preview');return;}
    if(action==='review-entire-report'){await showReportQualityReview(false);return;}
    if(action==='view-quality-review'){await showReportQualityReview(true);return;}
    if(action==='mark-quality-reviewed'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'APPROVED',note:'Whole-report quality recommendations reviewed.'}},false);toast('Quality review marked as addressed.','success');closeModal();await renderReport(reportId,'report-preview');return;}
    if(action==='dismiss-quality-review'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.suggestionId}/review`,{method:'POST',body:{decision:'REJECTED',note:'Whole-report quality review dismissed.'}},false);toast('Quality review dismissed.','success');closeModal();await renderReport(reportId,'report-preview');return;}
    if(action==='view-traceability'){await showTraceability();return;}
    if(action==='navigate-quality-section'){closeModal();navigateReportScreen(target.dataset.sectionId||'report-preview');return;}
    if(action==='open-queue-report'){location.hash=`#/report/${target.dataset.reportId}/${target.dataset.sectionId||'report-preview'}`;return;}
    if(action==='request-ai'){const result=await api(`/api/reports/${reportId}/ai`,{method:'POST',body:{section_id:section.id,purpose:'NARRATIVE'}});toast(result.message||'AI draft queued for generation and human review.','success');renderReport(reportId,section.id);return;}
    if(action==='review-ai'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.id}/review`,{method:'POST',body:{decision:target.dataset.decision}});renderReport(reportId,section.id);return;}
    if(action==='validate-draft'||action==='validate-final'){const final=action==='validate-final';state.validation=await api(`/api/reports/${reportId}/validate`,{method:'POST',body:{final_requested:final}});renderReport(reportId,screenId);return;}
    if(action==='publish'){await api(`/api/reports/${reportId}/publications`,{method:'POST',body:{publication_type:target.dataset.type,is_final:target.dataset.final==='true'}},false);toast('Document generation queued. Refresh status in a few moments.','success');renderReport(reportId,screenId);return;}
    if(action==='dismiss-publication'){await api(`/api/reports/${reportId}/publications/${target.dataset.id}/dismiss`,{method:'POST'});toast('Failed publication attempt dismissed.','success');renderReport(reportId,screenId);return;}
    if(action==='refresh-report'){renderReport(reportId,screenId);return;}
    if(action==='admin-tab'){renderAdminTab(target.dataset.tab);return;}
    if(action==='new-user'){showNewUser();return;}
    if(action==='new-capability'){showNewCapability();return;}
    if(action==='edit-capability'){showEditCapability(target.dataset.id);return;}
    if(action==='new-knowledge'){showNewKnowledge();return;}
    if(action==='import-knowledge'){showImportKnowledge();return;}
    if(action==='review-knowledge-detail'){showReviewKnowledge(target.dataset.id);return;}
    if(action==='review-capability'){await api(`/api/admin/capabilities/${target.dataset.id}/review`,{method:'POST',body:{decision:target.dataset.decision}});toast('Capability review recorded.','success');renderAdmin();return;}
    if(action==='review-knowledge'){await api(`/api/admin/knowledge/${target.dataset.id}/review`,{method:'POST',body:{decision:target.dataset.decision,reusable_across_prospects:false}});toast('Knowledge review recorded.','success');renderAdmin();return;}
    if(action==='delete-prospect'){showDeleteProspect(target.dataset.id,target.dataset.name);return;}
    if(action==='sync-now'){await flushQueue();return;}
  }catch(error){toast(error.message,'error');}
}

async function handleChange(event) {
  const target=event.target;
  try {
    if(target.matches('[data-action="onboarding-toggle"]')){setOnboardingSectionEnabled(target);return;}
    if(target.matches('[data-action="mobile-section"]')){navigateReportScreen(target.value);return;}
    if(target.matches('[data-action="quick-entry-area"]')){setQuickEntryArea(state.report.report.id,target.value);return;}
    if(target.id==='quick-entry-camera'||target.id==='quick-entry-file'){await uploadQuickEntryFiles(target);return;}
    if(target.matches('[data-action="report-status"]')){const reportId=state.report.report.id;const result=await api(`/api/reports/${reportId}`,{method:'PATCH',body:{state:target.value}});state.report.report.state=result.state;toast('Report status updated.','success');renderReport(reportId,currentReportScreen());return;}
  }catch(error){toast(error.message,'error');}
}

function handleInput(event) {
  const target=event.target;
  if(target.id==='section-narrative'){scheduleNarrativeSave(target.dataset.sectionId,target.value,document.getElementById('narrative-save'));}
  if(target.id==='executive-summary-editor'){scheduleExecutiveSummarySave(target.value,document.getElementById('executive-summary-save'));}
  if(target.id==='cloud-inventory-approach-editor'){scheduleSolutionApproachSave(target.dataset.sectionId,target.value,document.getElementById('solution-approach-save'));}
  if(target.classList.contains('prompt-answer')){const section=selectedSection();const status=document.querySelector(`[data-save-for="${target.dataset.promptId}"]`);schedulePromptSave(section.id,target.dataset.promptId,target.value,status);}
}

async function route() {
  if(!state.me){const ok=await loadMe();if(!ok){renderLogin();return;}}
  const hash=location.hash || '#/prospects'; const parts=hash.slice(2).split('/');
  try {
    if(parts[0]==='prospects'||!parts[0]) await renderProspects();
    else if(parts[0]==='prospect') await renderProspect(parts[1]);
    else if(parts[0]==='report') await renderReport(parts[1],parts[2]||null);
    else if(parts[0]==='admin') await renderAdmin();
    else location.hash='#/prospects';
  }catch(error){console.error(error);if(error.status!==401)app.innerHTML=shell(`<div class="page"><div class="card empty"><h2>Unable to load workspace</h2><p>${esc(error.message)}</p><button class="btn btn-primary" data-action="go" data-route="#/prospects">Return to prospects</button></div></div>`);}
}

// Offline mutation queue
const DB_NAME='ci-discovery-offline'; const DB_VERSION=1;
function openOfflineDb(){return new Promise((resolve,reject)=>{const req=indexedDB.open(DB_NAME,DB_VERSION);req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains('mutations'))db.createObjectStore('mutations',{keyPath:'id'});if(!db.objectStoreNames.contains('evidence'))db.createObjectStore('evidence',{keyPath:'id'});};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
async function idbPut(store,value){const db=await openOfflineDb();return new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');tx.objectStore(store).put(value);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
async function idbAll(store){const db=await openOfflineDb();return new Promise((resolve,reject)=>{const req=db.transaction(store,'readonly').objectStore(store).getAll();req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
async function idbDelete(store,id){const db=await openOfflineDb();return new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');tx.objectStore(store).delete(id);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
async function queueMutation(item){await idbPut('mutations',{id:uid(),createdAt:new Date().toISOString(),...item});}
async function queueEvidence(item){await idbPut('evidence',{id:uid(),createdAt:new Date().toISOString(),...item});updateQueueCount();}
async function updateQueueCount(){try{const n=(await idbAll('mutations')).length+(await idbAll('evidence')).length;const el=document.getElementById('queued-stat');if(el)el.textContent=String(n);}catch{} }
async function flushQueue(){if(!navigator.onLine){toast('Still offline.','error');return;}try{const me=await api('/api/auth/me',{},false);state.csrf=me.csrf_token;for(const item of await idbAll('mutations')){try{const headers={...(item.headers||{}),'X-CSRF-Token':state.csrf};await api(item.url,{method:item.method,body:item.body,headers},false);await idbDelete('mutations',item.id);}catch(e){if(e.status>=400&&e.status<500){toast(`Queued change requires attention: ${e.message}`,'error');}break;}}for(const item of await idbAll('evidence')){try{const fd=new FormData();fd.append('section_id',item.sectionId);fd.append('caption',item.caption||item.file.name);fd.append('placement',item.placement||'INLINE');fd.append('classification','CONFIDENTIAL');fd.append('file',item.file,item.file.name);await api(`/api/reports/${item.reportId}/evidence`,{method:'POST',body:fd},false);await idbDelete('evidence',item.id);}catch{break;}}updateConnection();updateQueueCount();toast('Offline queue synchronized.','success');}catch(error){toast(error.message,'error');}}
function updateConnection(){const pill=document.getElementById('connection-pill');if(pill){pill.textContent=navigator.onLine?'Online':'Offline - capture continues';pill.classList.toggle('offline',!navigator.onLine);}updateQueueCount();}

document.addEventListener('submit',handleSubmit);
document.addEventListener('click',handleClick);
document.addEventListener('change',handleChange);
document.addEventListener('input',handleInput);
window.addEventListener('hashchange',route);
window.addEventListener('online',()=>{updateConnection();flushQueue();});
window.addEventListener('offline',updateConnection);
window.addEventListener('keydown',event=>{if(event.key==='Escape')closeModal();});
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(console.warn);
route();
