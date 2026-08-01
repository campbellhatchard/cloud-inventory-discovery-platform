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
};

const esc = value => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
const fmtDate = value => value ? new Intl.DateTimeFormat(undefined, {year:'numeric', month:'short', day:'numeric'}).format(new Date(value)) : 'Not set';
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
function closeModal() { document.getElementById('modal-root')?.remove(); }

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

function reportSectionContent(section) {
  const report = state.report;
  const module = section.process_module || 'GENERAL';
  const prompts = report.prompts_by_module[module] || report.prompts_by_module.GENERAL || [];
  const answered = new Map(section.responses.map(r => [r.prompt_id, r]));
  const findings = report.findings.filter(f => f.section_id === section.id);
  const evidence = report.evidence.filter(e => e.section_id === section.id);
  return `
    <div class="mobile-section-select"><label class="sr-only" for="mobile-section">Screen or section</label><select id="mobile-section" data-action="mobile-section">${reportSectionOptions(section.id)}</select></div>
    <section class="card">
      <div class="section-head"><div><div class="card-meta">${section.process_module?`<span>${esc(section.process_module.replaceAll('_',' '))}</span>`:''}</div><h2>${esc(section.title)}</h2></div><div class="toolbar">${canOwn(report.access_scope)?'<button class="btn btn-danger btn-small" data-action="remove-section">Remove</button>':''}</div></div>
      <p class="help">This section is open for collaborative entry by anyone associated with the report. No assignment or section status is required.</p>
      <div class="field"><label for="section-narrative">Section narrative</label><textarea id="section-narrative" class="editor" data-section-id="${section.id}" placeholder="Write or refine the customer-facing narrative. Autosaves after you stop typing.">${esc(section.narrative)}</textarea><div id="narrative-save" class="save-state"></div></div>
    </section>
    <section class="card">
      <div class="section-head"><div><h2>Guided discovery questions</h2><p class="help">Structured answers preserve evidence and can later be converted into approved narrative.</p></div></div>
      <div class="prompt-list">${prompts.map(p => { const r=answered.get(p.id); return `<article class="prompt-card"><div class="prompt-question"><span>${esc(p.question)}</span></div>${p.answer_type==='PHOTO'?`<button class="btn btn-ghost btn-small" data-action="go-quick-entry">Open Quick Entry</button>`:`<textarea class="prompt-answer" data-prompt-id="${p.id}" data-response-version="${r?.version || ''}" placeholder="Capture the answer, facts, assumptions, and examples.">${esc(r?.narrative || '')}</textarea><div class="save-state" data-save-for="${p.id}"></div>`}</article>`; }).join('')}</div>
    </section>
    <section class="card" id="findings"><div class="section-head"><div><h2>Findings</h2><p class="help">Facts and interpretations should remain traceable to the section evidence.</p></div><button class="btn btn-ghost btn-small" data-action="new-finding">Add detailed finding</button></div>${findings.map(f => `<article class="finding"><div class="card-meta"><span class="badge">${esc(f.finding_type.replaceAll('_',' '))}</span><span>Confidence: ${esc(f.confidence)}</span></div><p>${esc(f.statement)}</p>${f.impact?`<p class="impact"><strong>Impact:</strong> ${esc(f.impact)}</p>`:''}</article>`).join('') || '<p class="help">No findings have been captured for this section.</p>'}</section>
    <section class="card" id="photos"><div class="section-head"><div><h2>Site photographs and attachments</h2><p class="help">Photographs and attachments routed from Quick Entry appear here for review and publication.</p></div><button class="btn btn-ghost btn-small" data-action="go-quick-entry">Open Quick Entry</button></div><div class="evidence-grid">${evidence.map(e => `<article class="evidence-card"><div class="evidence-thumb">${e.file?.mime_type?.startsWith('image/')?`<img src="/api/files/${e.file.id}?inline=true" alt="${esc(e.caption || e.file.file_name)}" loading="lazy">`:'Attachment'}</div><div class="evidence-body"><strong>${esc(e.caption || e.file?.file_name || 'Evidence')}</strong><div class="card-meta"><span>${esc(e.placement)}</span><span>${e.file?bytes(e.file.size_bytes):''}</span><span class="badge">${esc(e.extraction_state || 'NOT APPLICABLE')}</span></div>${e.file?`<a href="/api/files/${e.file.id}" target="_blank">Open file</a>`:''}${canReview(report.access_scope)?`<div class="card-actions"><button class="btn btn-ghost btn-small" data-action="review-evidence" data-id="${e.id}" data-include="true">Include</button><button class="btn btn-ghost btn-small" data-action="review-evidence" data-id="${e.id}" data-include="false">Supporting only</button></div>`:''}</div></article>`).join('')}</div></section>`;
}

function reportInspector(section) {
  const report = state.report;
  const findings = report.findings.filter(f => f.section_id === section.id);
  const mappings = report.capability_mappings.filter(m => findings.some(f => f.id === m.finding_id));
  const benefits = report.benefits.filter(b => !b.finding_id || findings.some(f=>f.id===b.finding_id));
  const suggestions = report.ai_suggestions.filter(s => !s.section_id || s.section_id === section.id);
  const comments = (report.comments || []).filter(c => !c.section_id || c.section_id === section.id);
  const canR = canReview(report.access_scope);
  return `
    <aside class="report-inspector">
      <section class="inspector-card"><h3>Cloud Inventory functionality</h3>${findings.length?`<button class="btn btn-ghost btn-small btn-wide" data-action="map-capability">Map approved capability</button>`:'<p class="help">Capture a finding before mapping functionality.</p>'}${mappings.map(m=>`<div class="finding"><strong>${esc(m.capability_name)}</strong><p>${esc(m.rationale)}</p><span class="badge ${m.approval_state==='APPROVED'?'badge-success':'badge-warning'}">${esc(m.approval_state)}</span>${canR&&m.approval_state==='PENDING'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-mapping" data-id="${m.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-mapping" data-id="${m.id}" data-decision="REJECTED">Reject</button></div>`:''}</div>`).join('')}</section>
      <section class="inspector-card"><h3>Benefits and baselines</h3><button class="btn btn-ghost btn-small btn-wide" data-action="new-benefit">Add benefit statement</button>${benefits.map(b=>`<div class="finding"><p>${esc(b.statement)}</p><div class="card-meta"><span>${esc(b.measure_type)}</span><span class="badge ${b.approval_state==='APPROVED'?'badge-success':'badge-warning'}">${esc(b.approval_state)}</span></div>${canR&&b.approval_state==='PENDING'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-benefit" data-id="${b.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-benefit" data-id="${b.id}" data-decision="REJECTED">Reject</button></div>`:''}</div>`).join('')}</section>
      <section class="inspector-card"><h3>AI assistance</h3><p class="help">${esc(state.aiStatus?.policy?.reason || 'AI status unavailable.')}</p><button class="btn btn-ghost btn-small btn-wide" data-action="request-ai" ${state.aiStatus?.policy?.allowed?'':'disabled'}>Draft from evidence</button>${suggestions.map(s=>`<details class="accordion"><summary>${esc(s.purpose)} - ${esc(s.review_state)}</summary><div class="accordion-body"><p>${esc(s.content.suggested_text || s.content.summary || JSON.stringify(s.content))}</p>${canR&&s.review_state==='PENDING'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-ai" data-id="${s.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-ai" data-id="${s.id}" data-decision="REJECTED">Reject</button></div>`:''}</div></details>`).join('')}</section>
      <section class="inspector-card"><h3>Collaboration comments</h3><form id="comment-form"><input type="hidden" name="section_id" value="${section.id}"><div class="field"><label class="sr-only">Comment</label><textarea name="body" required placeholder="Add a review note, question, or follow-up request."></textarea></div><button class="btn btn-ghost btn-small btn-wide" type="submit">Add comment</button></form>${comments.map(c=>`<div class="finding"><div class="card-meta"><strong>${esc(c.author_name)}</strong><span>${fmtDate(c.created_at)}</span></div><p>${esc(c.body)}</p><span class="badge ${c.status==='RESOLVED'?'badge-success':'badge-warning'}">${esc(c.status)}</span>${canR&&c.status==='OPEN'?`<button class="btn btn-ghost btn-small" data-action="resolve-comment" data-id="${c.id}">Resolve</button>`:''}</div>`).join('') || '<p class="help">No comments for this section.</p>'}</section>
    </aside>`;
}

function reportSectionHasContent(section) {
  const report = state.report;
  return Boolean(
    section.narrative?.trim() ||
    section.responses?.some(response => (response.narrative || '').trim() || response.payload) ||
    report.findings.some(item => item.section_id === section.id && item.status !== 'REJECTED') ||
    report.evidence.some(item => item.section_id === section.id && ['READY','AVAILABLE'].includes(item.status))
  );
}

function reportPreviewSection(section) {
  const report = state.report;
  const responses = (section.responses || []).filter(response => (response.narrative || '').trim() || response.payload);
  const findings = report.findings.filter(item => item.section_id === section.id && item.status !== 'REJECTED');
  const findingIds = new Set(findings.map(item => item.id));
  const mappings = report.capability_mappings.filter(item => findingIds.has(item.finding_id) && item.approval_state === 'APPROVED');
  const benefits = report.benefits.filter(item => item.approval_state === 'APPROVED' && (!item.finding_id || findingIds.has(item.finding_id)));
  const evidence = report.evidence.filter(item => item.section_id === section.id && ['READY','AVAILABLE'].includes(item.status) && item.placement === 'INLINE');
  const noContent = !reportSectionHasContent(section);
  return `<article class="compiled-section">
    <h2>${esc(section.title)}</h2>
    ${section.narrative?.trim()?`<div class="compiled-narrative">${esc(section.narrative).replaceAll('\n','<br>')}</div>`:''}
    ${responses.length?`<h3>Discovery Responses</h3>${responses.map(response=>`<div class="compiled-response"><strong>${esc(response.question)}</strong><p>${esc(response.narrative || JSON.stringify(response.payload || {}))}</p></div>`).join('')}`:''}
    ${findings.length?`<h3>Current-State Findings</h3><ul>${findings.map(item=>`<li><strong>${esc(item.finding_type.replaceAll('_',' '))}:</strong> ${esc(item.statement)}${item.impact?`<div class="help"><strong>Impact:</strong> ${esc(item.impact)}</div>`:''}</li>`).join('')}</ul>`:''}
    ${mappings.length?`<h3>Cloud Inventory Functionality</h3><ul>${mappings.map(item=>`<li><strong>${esc(item.capability_name)}:</strong> ${esc(item.rationale)}</li>`).join('')}</ul>`:''}
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
  const storageMessage = storageConfigured
    ? `<div class="validation-item">Persistent document storage is configured.</div>`
    : `<div class="validation-item WARNING">Persistent Cloudflare R2 storage is not configured. Draft Word/PDF downloads remain available; final publication, evidence, logos, and stored documents require R2.</div>`;
  return `
    <div class="mobile-section-select"><label class="sr-only" for="mobile-section">Screen or section</label><select id="mobile-section" data-action="mobile-section">${reportSectionOptions('report-preview')}</select></div>
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
      <div class="generated-documents">${report.publications.map(item=>`<div class="finding"><strong>${esc(item.publication_type.replaceAll('_',' '))}</strong><span class="badge ${item.status==='COMPLETED'?'badge-success':item.status==='FAILED'?'badge-danger':'badge-warning'}">${esc(item.status)}</span>${item.error?`<p class="impact">${esc(item.error)}</p>`:''}<div class="card-actions">${item.docx_file_id?`<a class="btn btn-ghost btn-small" href="/api/files/${item.docx_file_id}">Word</a>`:''}${item.pdf_file_id?`<a class="btn btn-ghost btn-small" href="/api/files/${item.pdf_file_id}">PDF</a>`:''}</div></div>`).join('') || '<p class="help">No persisted documents have been requested.</p>'}</div>
    </section>
    <section class="compiled-report card">
      <div class="compiled-report-cover"><div class="card-meta"><span class="badge badge-cyan">REPORT REVIEW</span>${reportStatusBadge(report.report.state)}</div><h1>${esc(report.report.title)}</h1><p>Revision ${report.report.revision} · ${esc(report.report.report_kind)}</p></div>
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
  const findings = state.report.findings.filter(f=>f.section_id===section.id);
  const options = state.capabilities.filter(c=>c.status==='APPROVED').map(c=>`<option value="${c.id}">${esc(c.domain)} - ${esc(c.name)}</option>`).join('');
  showModal('Map Cloud Inventory functionality', `<form id="mapping-form"><div class="field"><label>Finding</label><select name="finding_id">${findings.map(f=>`<option value="${f.id}">${esc(f.finding_type)} - ${esc(f.statement.slice(0,90))}</option>`).join('')}</select></div><div class="field"><label>Approved capability</label><select name="capability_id">${options}</select></div><div class="field"><label>Rationale</label><textarea name="rationale" required placeholder="Explain how this capability addresses the specific evidence and pain point."></textarea></div><div class="field"><label>Prerequisites</label><textarea name="prerequisites"></textarea></div><button class="btn btn-primary btn-wide" type="submit">Create mapping for review</button></form>`, '');
}
function showBenefit() {
  const section = selectedSection();
  const findings = state.report.findings.filter(f=>f.section_id===section.id);
  showModal('Add benefit statement', `<form id="benefit-form"><div class="field"><label>Related finding</label><select name="finding_id"><option value="">Cross-process benefit</option>${findings.map(f=>`<option value="${f.id}">${esc(f.statement.slice(0,100))}</option>`).join('')}</select></div><div class="field"><label>Benefit statement</label><textarea name="statement" required placeholder="State the expected benefit without presenting an unvalidated result as a guarantee."></textarea></div><div class="field"><label>Measurement type</label><select name="measure_type"><option>QUALITATIVE</option><option>QUANTITATIVE</option></select></div><div class="field"><label>Formula or measurement method</label><textarea name="formula"></textarea></div><div class="field"><label>Assumptions</label><textarea name="assumptions"></textarea></div><button class="btn btn-primary btn-wide" type="submit">Create benefit for review</button></form>`, '');
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
  const [users, branding, capabilities, knowledge, retention, audit] = await Promise.all([api('/api/users'), api('/api/admin/branding'), api('/api/capabilities'), api('/api/admin/knowledge'), api('/api/admin/retention-due?days=90'), api('/api/admin/audit?limit=100')]);
  state.users=users; state.capabilities=capabilities;
  app.innerHTML = shell(`<div class="page"><header class="page-header"><div><h1>Administration</h1><p>Users, capability governance, knowledge review, branding, retention, and audit.</p></div></header><nav class="tabs"><button class="tab active" data-action="admin-tab" data-tab="users">Users</button><button class="tab" data-action="admin-tab" data-tab="capabilities">Capabilities</button><button class="tab" data-action="admin-tab" data-tab="knowledge">Knowledge</button><button class="tab" data-action="admin-tab" data-tab="retention">Retention</button><button class="tab" data-action="admin-tab" data-tab="branding">Branding</button><button class="tab" data-action="admin-tab" data-tab="audit">Audit</button></nav><div id="admin-panel"></div></div>`, 'admin');
  window.__adminData={users,branding,capabilities,knowledge,retention,audit};
  renderAdminTab('users'); updateConnection();
}
function renderAdminTab(tab) {
  const data=window.__adminData; const panel=document.getElementById('admin-panel');
  document.querySelectorAll('[data-action="admin-tab"]').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));
  if(tab==='users') panel.innerHTML=`<div class="page-header"><div><h2>Users</h2><p>Application-managed identities and global roles.</p></div><button class="btn btn-primary" data-action="new-user">Create user</button></div><div class="table-wrap"><table><thead><tr><th>User</th><th>Email</th><th>Roles</th><th>Status</th></tr></thead><tbody>${data.users.map(u=>`<tr><td>${esc(u.display_name||u.username)}<br><span class="help">${esc(u.username)}</span></td><td>${esc(u.email)}</td><td>${u.roles.map(r=>`<span class="badge">${esc(r)}</span>`).join(' ')}</td><td>${esc(u.status)}</td></tr>`).join('')}</tbody></table></div>`;
  if(tab==='capabilities') panel.innerHTML=`<div class="page-header"><div><h2>Controlled capability catalog</h2><p>Only approved capabilities are available for prospect recommendations and AI grounding.</p></div><button class="btn btn-primary" data-action="new-capability">Add capability</button></div><div class="table-wrap"><table><thead><tr><th>Code</th><th>Domain</th><th>Capability</th><th>Status</th><th>Source / action</th></tr></thead><tbody>${data.capabilities.map(c=>`<tr><td>${esc(c.capability_code)}</td><td>${esc(c.domain)}</td><td><strong>${esc(c.name)}</strong><br><span class="help">${esc(c.controlled_description)}</span></td><td><span class="badge ${c.status==='APPROVED'?'badge-success':c.status==='RETIRED'?'badge-danger':'badge-warning'}">${esc(c.status)}</span></td><td>${esc(c.source||'')}${c.status==='PROPOSED'?`<div class="card-actions"><button class="btn btn-primary btn-small" data-action="review-capability" data-id="${c.id}" data-decision="APPROVED">Approve</button><button class="btn btn-danger btn-small" data-action="review-capability" data-id="${c.id}" data-decision="REJECTED">Retire</button></div>`:''}</td></tr>`).join('')}</tbody></table></div>`;
  if(tab==='knowledge') panel.innerHTML=`<div class="page-header"><div><h2>Discovery knowledge repository</h2><p>Approved reusable knowledge can ground future AI drafts. Prospect-specific entries remain isolated until explicitly de-identified.</p></div></div><div class="table-wrap"><table><thead><tr><th>Source</th><th>Title / content</th><th>Scope</th><th>Status</th><th>Review</th></tr></thead><tbody>${data.knowledge.map(k=>`<tr><td>${esc(k.source_type)}<br><span class="help">${esc(k.source_ref||'')}</span></td><td><strong>${esc(k.title)}</strong><br><span class="help">${esc(k.content.slice(0,320))}${k.content.length>320?'…':''}</span></td><td>${k.prospect_id?'<span class="badge badge-warning">Prospect specific</span>':'<span class="badge badge-cyan">Shared internal</span>'}${k.reusable_across_prospects?'<span class="badge badge-success">Reusable</span>':''}</td><td><span class="badge ${k.approval_state==='APPROVED'?'badge-success':k.approval_state==='REJECTED'?'badge-danger':'badge-warning'}">${esc(k.approval_state)}</span></td><td>${k.approval_state==='PENDING'?`<button class="btn btn-primary btn-small" data-action="review-knowledge" data-id="${k.id}" data-decision="APPROVED">Approve isolated</button><button class="btn btn-danger btn-small" data-action="review-knowledge" data-id="${k.id}" data-decision="REJECTED">Reject</button>`:''}</td></tr>`).join('')}</tbody></table></div>`;
  if(tab==='retention') panel.innerHTML=`<div class="page-header"><div><h2>Retention review</h2><p>Export is mandatory before permanent prospect deletion. Legal holds block archival and deletion.</p></div></div><div class="table-wrap"><table><thead><tr><th>Prospect</th><th>Status</th><th>Due</th><th>Last export</th><th>Actions</th></tr></thead><tbody>${data.retention.map(p=>`<tr><td><strong>${esc(p.name)}</strong>${p.legal_hold?'<br><span class="badge badge-danger">Legal hold</span>':''}</td><td>${esc(p.status)}</td><td>${fmtDate(p.retention_due_at)}</td><td>${fmtDate(p.last_exported_at)}</td><td><a class="btn btn-ghost btn-small" href="/api/prospects/${p.id}/export">Export</a>${p.last_exported_at&&!p.legal_hold?`<button class="btn btn-danger btn-small" data-action="delete-prospect" data-id="${p.id}" data-name="${esc(p.name)}">Delete</button>`:''}</td></tr>`).join('')||'<tr><td colspan="5">No prospects are due within the selected window.</td></tr>'}</tbody></table></div>`;
  if(tab==='branding') { const b=data.branding; panel.innerHTML=`<div class="card"><h2>Default Denver-derived branding</h2><form id="branding-form"><div class="grid grid-3"><div class="field"><label>Primary color</label><input name="primary_color" type="color" value="${esc(b.primary_color)}"></div><div class="field"><label>Secondary color</label><input name="secondary_color" type="color" value="${esc(b.secondary_color)}"></div><div class="field"><label>Accent color</label><input name="accent_color" type="color" value="${esc(b.accent_color)}"></div></div><div class="grid grid-2"><div class="field"><label>Heading font</label><input name="heading_font" value="${esc(b.heading_font)}"></div><div class="field"><label>Body font</label><input name="body_font" value="${esc(b.body_font)}"></div></div><div class="field"><label>Confidentiality statement</label><textarea name="confidentiality_text">${esc(b.confidentiality_text)}</textarea></div><div class="grid grid-2"><div class="field"><label>Draft watermark</label><input name="draft_watermark" value="${esc(b.draft_watermark)}"></div><div class="field"><label>Footer</label><input name="footer_text" value="${esc(b.footer_text)}"></div></div><input type="hidden" name="brand_id" value="${b.id}"><button class="btn btn-primary" type="submit">Save branding</button></form></div><div class="card"><h2>Report logo</h2><p class="help">${b.has_custom_logo?'A custom logo is active. Uploading a new image replaces it.':'The standard Cloud Inventory logo is active.'}</p><form id="branding-logo-form"><input type="hidden" name="brand_id" value="${b.id}"><div class="field"><label>Logo image</label><input name="file" type="file" accept="image/png,image/jpeg,image/webp" required></div><button class="btn btn-primary" type="submit">Upload report logo</button></form></div>`; }
  if(tab==='audit') panel.innerHTML=`<div class="table-wrap"><table><thead><tr><th>When</th><th>Action</th><th>Target</th><th>Actor</th><th>Metadata</th></tr></thead><tbody>${data.audit.map(a=>`<tr><td>${fmtDate(a.created_at)}</td><td>${esc(a.action)}</td><td>${esc(a.target_type)}<br><span class="help">${esc(a.target_id||'')}</span></td><td>${esc(a.actor_user_id||'System')}</td><td><code>${esc(JSON.stringify(a.metadata))}</code></td></tr>`).join('')}</tbody></table></div>`;
}
function showDeleteProspect(id,name){showModal('Permanently delete prospect',`<p>This action permanently deletes the prospect workspace, reports, evidence, publications, and audit-linked customer data. A completed export is required.</p><form id="delete-prospect-form"><input type="hidden" name="prospect_id" value="${esc(id)}"><div class="field"><label>Type the prospect name to confirm</label><input name="confirm_name" required></div><label><input type="checkbox" name="confirm_exported" required> I confirm that the workspace export has been downloaded and retained.</label><button class="btn btn-danger btn-wide" type="submit">Permanently delete ${esc(name)}</button></form>`,'');}
function showNewUser(){showModal('Create user',`<form id="user-form"><div class="field"><label>Username</label><input name="username" required></div><div class="field"><label>Display name</label><input name="display_name"></div><div class="field"><label>Email</label><input name="email" type="email" required></div><div class="field"><label>Temporary password</label><input name="password" type="password" minlength="14" required></div><div class="field"><label>Roles</label><label><input type="checkbox" name="roles" value="CONTRIBUTOR" checked> Contributor</label><label><input type="checkbox" name="roles" value="REVIEWER"> Reviewer</label><label><input type="checkbox" name="roles" value="OWNER"> Owner</label><label><input type="checkbox" name="roles" value="ADMIN"> Administrator</label></div><button class="btn btn-primary btn-wide" type="submit">Create user</button></form>`,'');}
function showNewCapability(){showModal('Add controlled capability',`<form id="capability-form"><div class="grid grid-2"><div class="field"><label>Code</label><input name="capability_code" required></div><div class="field"><label>Domain</label><input name="domain" required></div></div><div class="field"><label>Name</label><input name="name" required></div><div class="field"><label>Controlled description</label><textarea name="controlled_description" required></textarea></div><div class="field"><label>Typical prerequisites</label><textarea name="typical_prerequisites"></textarea></div><div class="field"><label>Limitations</label><textarea name="limitations"></textarea></div><div class="field"><label>Status</label><select name="status"><option>PROPOSED</option><option>APPROVED</option></select></div><div class="field"><label>Source</label><input name="source"></div><button class="btn btn-primary btn-wide" type="submit">Add capability</button></form>`,'');}

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
    if(form.id==='benefit-form'){const o=formObject(form);o.finding_id=o.finding_id||null;o.capability_mapping_id=null;await api(`/api/reports/${reportId}/benefits`,{method:'POST',body:o});closeModal();renderReport(reportId,section.id);return;}
    if(form.id==='comment-form'){await api(`/api/reports/${reportId}/comments`,{method:'POST',body:formObject(form)});form.reset();toast('Comment added.','success');renderReport(reportId,section.id);return;}
    if(form.id==='delete-report-form'){const o=formObject(form);const prospect=state.report.report.prospect_id;await api(`/api/reports/${reportId}`,{method:'DELETE',body:o},false);closeModal();toast('Report permanently deleted.','success');location.hash=`#/prospect/${prospect}`;return;}
    if(form.id==='merge-form'){const o=formObject(form,['source_report_ids']);if(!o.source_report_ids?.length)throw new Error('Select at least one source report.');await api('/api/reports/merge',{method:'POST',body:o},false);closeModal();toast('Reports merged.','success');location.hash=`#/report/${o.target_report_id}`;route();return;}
    if(form.id==='delete-prospect-form'){const o=formObject(form);const id=o.prospect_id;delete o.prospect_id;await api(`/api/admin/prospects/${id}`,{method:'DELETE',body:o},false);closeModal();toast('Prospect permanently deleted.','success');renderAdmin();return;}
    if(form.id==='user-form'){const o=formObject(form,['roles']);await api('/api/admin/users',{method:'POST',body:o});closeModal();toast('User created.','success');renderAdmin();return;}
    if(form.id==='capability-form'){await api('/api/admin/capabilities',{method:'POST',body:formObject(form)});closeModal();toast('Capability added.','success');renderAdmin();return;}
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
    if(action==='request-ai'){const result=await api(`/api/reports/${reportId}/ai`,{method:'POST',body:{section_id:section.id,purpose:'NARRATIVE'}});toast(result.message||'AI draft queued for generation and human review.','success');renderReport(reportId,section.id);return;}
    if(action==='review-ai'){await api(`/api/reports/${reportId}/ai-suggestions/${target.dataset.id}/review`,{method:'POST',body:{decision:target.dataset.decision}});renderReport(reportId,section.id);return;}
    if(action==='validate-draft'||action==='validate-final'){const final=action==='validate-final';state.validation=await api(`/api/reports/${reportId}/validate`,{method:'POST',body:{final_requested:final}});renderReport(reportId,screenId);return;}
    if(action==='publish'){await api(`/api/reports/${reportId}/publications`,{method:'POST',body:{publication_type:target.dataset.type,is_final:target.dataset.final==='true'}},false);toast('Document generation queued. Refresh status in a few moments.','success');renderReport(reportId,screenId);return;}
    if(action==='refresh-report'){renderReport(reportId,screenId);return;}
    if(action==='admin-tab'){renderAdminTab(target.dataset.tab);return;}
    if(action==='new-user'){showNewUser();return;}
    if(action==='new-capability'){showNewCapability();return;}
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
