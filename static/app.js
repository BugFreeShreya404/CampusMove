/* CampusMove front-end (vanilla JS, no build step). Talks to the Flask REST API. */
(() => {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hm = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const dt = ts => new Date(ts * 1000).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
const inr = n => '₹' + Number(n).toFixed(2);
const NS = 'http://www.w3.org/2000/svg';

const COLORS = { free: '#2a9d5c', reserved: '#e0a021', occupied: '#d64545', payment_due: '#7b4fc4', mismatch: 'url(#hatch)', maintenance: '#8794a1' };
const LABELS = { free: 'Free', reserved: 'Reserved', occupied: 'In use', payment_due: 'Pay due', mismatch: 'Sensor alert', maintenance: 'Closed' };
const FRESH = { live: 'Live', stale: 'Stale', unavailable: 'No location', out_of_service: 'Out of service' };

const S = {
  token: sessionStorage.getItem('tok'), user: JSON.parse(sessionStorage.getItem('usr') || 'null'),
  view: 'map', parking: null, overview: null, buses: [], notifs: null, reservations: [],
  sel: null, whenMode: 'now', whenDay: '0', whenTime: '', hours: 1, vehicle: localStorage.getItem('veh') || '',
  toastedId: null, activeSig: '', adminRoute: null, editStops: [], busy: false,
};

/* ------------------------------------------------------------- api / ui helpers */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(S.token ? { Authorization: 'Bearer ' + S.token } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    if (res.status === 401 && S.token) logout(true);
    const e = new Error(data.error?.message || 'Request failed (' + res.status + ')');
    e.status = res.status; e.code = data.error?.code; e.fields = data.error?.fields || {};
    throw e;
  }
  return data;
}
function toast(msg, kind = 'info') {
  const t = document.createElement('div');
  t.className = 'toast ' + kind; t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), kind === 'error' ? 7000 : 4500);
}
const isAdmin = () => S.user?.role === 'admin';
function setConn(ok) {
  $('#conn').className = 'dot ' + (ok ? 'ok' : 'bad');
  $('#connText').textContent = ok ? 'Connected' : 'Server not reachable – retrying…';
}
const chip = (cls, text) => `<span class="chip ${esc(cls)}">${esc(text)}</span>`;

/* ------------------------------------------------------------- auth screens */
function showLogin(mode = 'login') {
  $('#top').hidden = $('#simBanner').hidden = $('#foot').hidden = true;
  $('#view').style.cssText = 'max-width:none;padding:0';
  const reg = mode === 'register';
  $('#view').innerHTML = `
  <div class="login-wrap"><form class="login" id="loginForm" novalidate>
    <div class="logo"><svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5z" fill="currentColor"/></svg></div>
    <h1>CampusMove</h1><p class="muted" style="margin:0 0 16px">IoT-based campus parking &amp; smart transport locator</p>
    ${reg ? `<div class="field"><label for="lName">Full name</label><input id="lName" autocomplete="name"></div>` : ''}
    <div class="field"><label for="lUser">Username</label><input id="lUser" autocomplete="username" autofocus></div>
    <div class="field"><label for="lPass">Password</label><input id="lPass" type="password" autocomplete="${reg ? 'new-password' : 'current-password'}"></div>
    <div class="err" id="lErr" role="alert"></div>
    <button class="btn block" style="margin-top:10px">${reg ? 'Create student account' : 'Log in'}</button>
    <p style="text-align:center;margin:12px 0 0" class="muted">${reg ? 'Have an account?' : 'New student?'}
      <button type="button" class="link" data-act="${reg ? 'showLogin' : 'showRegister'}">${reg ? 'Log in' : 'Register'}</button></p>
    ${reg ? '' : `<div class="demo-creds"><button type="button" class="btn ghost sm" data-demo="shreya">Shreya Kanade</button>
      <button type="button" class="btn ghost sm" data-demo="abhijit">Abhijit More</button>
      <button type="button" class="btn ghost sm" data-demo="admin">Admin</button></div>`}
    <div class="sim"><b>Simulation notice:</b> sensors, GPS, payments and notifications are simulated. All accounts and data are fictitious.</div>
  </form></div>`;
  $('#loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    $('#lErr').textContent = '';
    const username = $('#lUser').value.trim(), password = $('#lPass').value;
    try {
      if (reg) {
        await api('/api/register', { method: 'POST', body: { name: $('#lName').value, username, password } });
        toast('Account created – logging you in.', 'success');
      }
      const r = await api('/api/login', { method: 'POST', body: { username, password } });
      S.token = r.token; S.user = r.user;
      sessionStorage.setItem('tok', r.token); sessionStorage.setItem('usr', JSON.stringify(r.user));
      start();
    } catch (err) { $('#lErr').textContent = err.message; }
  });
  const DEMO = { shreya: ['Shreya Kanade', 'shreya123'], abhijit: ['Abhijit More', 'abhijit123'], admin: ['admin', 'admin123'] };
  $$('[data-demo]').forEach(b => b.addEventListener('click', () => {
    const [u, p] = DEMO[b.dataset.demo];
    $('#lUser').value = u; $('#lPass').value = p;
    $('#loginForm').requestSubmit();
  }));

}
function logout(expired) {
  if (S.token && !expired) api('/api/logout', { method: 'POST' }).catch(() => {});
  S.token = null; S.user = null; S.notifs = null; S.toastedId = null;
  sessionStorage.clear();
  showLogin();
  if (expired) toast('Session ended – please log in again.', 'warning');
}

/* ------------------------------------------------------------- shell / routing */
const VIEWS = {
  map: { title: 'Live Map', mount: mountMap, load: loadMap },
  parking: { title: 'Parking', mount: mountParking, load: loadParking },
  buses: { title: 'Buses', mount: mountBuses, load: loadBuses },
  bookings: { title: 'My Bookings', mount: mountBookings, load: loadBookings, student: true },
  alerts: { title: 'Alerts', mount: mountAlerts, load: async () => { renderAlerts(); } },
  admin: { title: 'Admin Console', mount: mountAdmin, load: loadAdmin, admin: true },
  tests: { title: 'Test Cases', mount: mountTests, load: async () => {}, admin: true },
};
function renderNav() {
  $('#nav').innerHTML = Object.entries(VIEWS)
    .filter(([, v]) => (!v.admin || isAdmin()) && (!v.student || !isAdmin()))
    .map(([k, v]) => `<a href="#/${k}" class="${k === S.view ? 'on' : ''}">${v.title}</a>`).join('');
}
function route() {
  if (!S.token) return;
  let name = location.hash.replace('#/', '') || 'map';
  const v = VIEWS[name];
  if (!v || (v.admin && !isAdmin()) || (v.student && isAdmin())) name = 'map';
  S.view = name; S.activeSig = ''; S.adminRoute = null;
  renderNav();
  $('#view').innerHTML = '';
  VIEWS[name].mount();
  poll();
}
function start() {
  $('#top').hidden = $('#simBanner').hidden = $('#foot').hidden = false;
  $('#view').style.cssText = '';
  $('#userName').textContent = S.user.name; $('#userRole').textContent = S.user.role;
  if (!location.hash) location.hash = '#/map';
  S.toastedId = null;
  route();
}
async function poll() {
  if (!S.token) return;
  try {
    await Promise.all([loadNotifs(), VIEWS[S.view].load()]);
    setConn(true);
  } catch (e) { if (e.status === undefined) setConn(false); }
}

/* ------------------------------------------------------------- notifications */
async function loadNotifs(silent = false) {
  const d = await api('/api/notifications');
  S.notifs = d;
  const b = $('#bellBadge');
  b.hidden = !d.unread; b.textContent = d.unread > 99 ? '99+' : d.unread;
  const maxId = d.items.length ? d.items[0].id : 0;
  if (S.toastedId === null || silent) { S.toastedId = maxId; }
  else {
    d.items.filter(n => n.id > S.toastedId).reverse().slice(-3).forEach(n =>
      toast('🔔 ' + n.message, n.kind === 'critical' ? 'error' : n.kind));
    S.toastedId = Math.max(S.toastedId, maxId);
  }
  if (S.view === 'alerts') renderAlerts();
  if (S.view === 'map' && S.parking && S.overview) drawMapSide();
}

const FULL = ['occupied', 'payment_due', 'mismatch'];   // slots that hold a vehicle -> show a car icon
const carSvg = () => '<svg class="car" viewBox="0 0 64 32" aria-hidden="true"><use href="#car"/></svg>';

/* ------------------------------------------------------------- MAP */
function mountMap() {
  $('#view').innerHTML = `
  <div class="page-h"><div><h1>Live campus map</h1><p>Parking availability and bus positions at a glance.</p></div>
    <span class="chip sim">SIMULATED sensors &amp; GPS</span></div>
  <div class="grid g-map3">
    <aside class="side-list area-left" id="mapLeft"></aside>
    <section class="card map-card area-map">
      <svg id="map" viewBox="0 0 1000 700" role="img" aria-label="Campus map with parking lots and buses">
        <defs><pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="7" height="7" fill="#e05555"/><rect width="3" height="7" fill="#fff"/></pattern></defs>
        <rect width="1000" height="700" fill="#0d0a1e"/>
        <g id="gRoutes"></g><g id="gBldg"></g><g id="gLots"></g><g id="gBuses"></g>
      </svg>
      <div class="legend">
        <span><i class="st-free"></i>Free</span><span><i class="st-reserved"></i>Reserved</span>
        <span><i class="st-occupied"></i>Car parked</span><span><i class="st-payment_due"></i>Payment due</span>
        <span><i class="st-mismatch"></i>Sensor mismatch</span><span><i class="st-maintenance"></i>Maintenance</span>
        <span>▼ Dashed = basement</span><span>● Bus (simulated GPS)</span></div>
    </section>
    <aside class="side-list area-right" id="mapRight"></aside>
  </div>`;
  S.mapRoutesSig = '';
}
async function loadMap() {
  const [p, o] = await Promise.all([api('/api/parking'), api('/api/transport/overview')]);
  S.parking = p; S.overview = o; S.buses = o.buses;
  if (S.view !== 'map') return;
  drawMap(); drawMapSide();
}
function el(name, attrs = {}, parent) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
// shift overlapping routes slightly so every route colour stays visible
const routeOff = id => (id - 2.5) * 4;
function drawMap() {
  const o = S.overview, p = S.parking;
  const sig = JSON.stringify(o.routes.map(r => [r.id, r.status, r.stops.map(s => s.id)]));
  if (sig !== S.mapRoutesSig) {
    S.mapRoutesSig = sig;
    const gr = $('#gRoutes'), gb = $('#gBldg');
    gr.innerHTML = ''; gb.innerHTML = '';
    o.routes.forEach(r => {
      const pts = r.stops.map(s => `${s.x},${s.y}`);
      pts.push(pts[0]);
      el('polyline', { points: pts.join(' '), class: 'road', stroke: r.color, 'stroke-width': 6, opacity: r.status === 'active' ? .9 : .35,
        'stroke-dasharray': r.status === 'active' ? '' : '3 10', transform: `translate(0,${routeOff(r.id)})` }, gr);
    });
    o.stops.forEach(s => {
      const w = Math.max(84, s.name.length * 7 + 18);
      el('rect', { class: 'bldg', x: s.x - w / 2, y: s.y - 16, width: w, height: 32, rx: 8 }, gb);
      const t = el('text', { x: s.x, y: s.y + 4.5, class: 'stop-label', 'text-anchor': 'middle', style: 'stroke:none' }, gb);
      t.textContent = s.name;
    });
  }
  const gl = $('#gLots'); gl.innerHTML = '';
  p.lots.forEach(l => {
    const base = l.kind === 'basement';
    el('rect', { x: l.x, y: l.y, width: l.w, height: l.h, rx: 8, fill: base ? '#0a0716' : '#1c1540', stroke: base ? '#a78bfa' : '#5b44b8',
      'stroke-width': 1.5, 'stroke-dasharray': base ? '5 3' : '' }, gl);
    const t = el('text', { x: l.x, y: l.y - 7, class: 'lot-label' }, gl);
    t.textContent = `${base ? '▼ ' : ''}${l.name.split(' – ')[0]} · ${l.counts.free}/${l.total - l.counts.maintenance} free`;
    const rows = Math.ceil(l.slots.length / l.cols), pad = 6, cw = (l.w - pad * 2) / l.cols, ch = (l.h - pad * 2) / rows;
    l.slots.forEach((s, i) => {
      const cx = l.x + pad + (i % l.cols) * cw, cy = l.y + pad + Math.floor(i / l.cols) * ch;
      const r = el('rect', { x: cx + 1.5, y: cy + 1.5, width: cw - 3, height: ch - 3, rx: 4, fill: COLORS[s.state] }, gl);
      el('title', {}, r).textContent = `${s.label}: ${LABELS[s.state]}`;
      if (FULL.includes(s.state)) {
        el('use', { href: '#car', x: cx + (cw - 30) / 2, y: cy + (ch - 15) / 2, width: 30, height: 15, style: 'pointer-events:none' }, gl);
      } else {
        const lt = el('text', { x: cx + cw / 2, y: cy + ch / 2 + 3.5, 'text-anchor': 'middle', 'font-size': 9.5, 'font-weight': 800, fill: '#fff',
          style: 'pointer-events:none;paint-order:stroke;stroke:rgba(0,0,0,.45);stroke-width:2px' }, gl);
        lt.textContent = s.label;
      }
    });
  });
  updateBuses($('#gBuses'));
}
function updateBuses(g) {
  const seen = new Set();
  S.buses.filter(b => b.x != null).forEach(b => {
    seen.add('bus-' + b.id);
    let n = $('#bus-' + b.id, g);
    if (!n) {
      n = el('g', { id: 'bus-' + b.id }, g);
      n.style.transform = `translate(${b.x}px,${b.y + routeOff(b.route_id)}px)`;
      el('circle', { class: 'ring', r: 14, stroke: b.color }, n);
      el('circle', { r: 13, fill: b.color, stroke: '#fff', 'stroke-width': 2.5 }, n);
      el('text', { y: 4 }, n).textContent = b.route_code;
      el('title', {}, n);
    }
    n.setAttribute('class', 'bus ' + b.freshness);
    n.style.transform = `translate(${b.x}px,${b.y + routeOff(b.route_id)}px)`;
    $('title', n).textContent = `${b.plate} · ${b.route_code} · ${FRESH[b.freshness]}${b.next_stop ? ' · next: ' + b.next_stop : ''}`;
  });
  $$('.bus', g).forEach(n => { if (!seen.has(n.id)) n.remove(); });
}
function busRow(b) {
  const eta = b.next_stop ? `Next: <b>${esc(b.next_stop)}</b> in ~${mmss(b.eta_s)}` : esc(b.message);
  return `<div class="bus-row"><div class="bus-ico" style="background:${esc(b.color)}">${esc(b.route_code)}</div>
    <div style="flex:1;min-width:0"><b>${esc(b.plate)}</b> ${chip(b.freshness, FRESH[b.freshness])}
    <div class="muted" style="font-size:13px">${b.freshness === 'live' || b.freshness === 'stale' ? eta : esc(b.message)}</div>
    ${b.freshness === 'stale' ? `<div class="muted" style="font-size:12px">⚠ ${esc(b.message)}</div>` : ''}</div></div>`;
}
function drawMapSide() {
  const t = S.parking.totals, usable = S.parking.lots.reduce((a, l) => a + l.total - l.counts.maintenance, 0);
  const live = S.buses.filter(b => b.freshness === 'live').length;
  const bar = l => ['free', 'reserved', 'occupied', 'payment_due', 'mismatch', 'maintenance'].map(k =>
    `<span class="st-${k}" style="width:${100 * l.counts[k] / l.total}%"></span>`).join('');
  $('#mapLeft').innerHTML = `
  <div class="kpis" style="grid-template-columns:1fr 1fr;margin:0">
    <div class="kpi"><b style="color:var(--free)">${t.free}<small style="font-size:14px"> / ${usable}</small></b><span>parking slots free now</span></div>
    <div class="kpi"><b>${live}<small style="font-size:14px"> / ${S.buses.length}</small></b><span>buses with live location</span></div></div>
  <div class="card"><div class="card-h"><h3>Parking lots</h3><a href="#/parking" class="link">Reserve →</a></div>
    ${S.parking.lots.map(l => `<div style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;gap:8px"><b>${l.kind === 'basement' ? '▼ ' : ''}${esc(l.name)}</b>
      <span class="muted" style="white-space:nowrap">${l.counts.free} free · ₹${l.rate_per_hour}/h</span></div>
      <div class="lot-bar">${bar(l)}</div></div>`).join('')}</div>`;
  const alerts = (S.notifs?.items || []).slice(0, 4);
  $('#mapRight').innerHTML = `
  <div class="card"><div class="card-h"><h3>Buses</h3><a href="#/buses" class="link">Routes &amp; timings →</a></div>${S.buses.map(busRow).join('')}</div>
  <div class="card"><div class="card-h"><h3>Latest alerts</h3><a href="#/alerts" class="link">All →</a></div>
    ${alerts.length ? alerts.map(n => `<div class="notif ${esc(n.kind)}"><div class="bar"></div><div style="flex:1;font-size:13px">${esc(n.message)}<br><small>${dt(n.ts)}</small></div></div>`).join('') : '<div class="empty">No alerts yet.</div>'}</div>`;
}

/* ------------------------------------------------------------- PARKING */
function mountParking() {
  $('#view').innerHTML = `
  <div class="page-h"><div><h1>Smart parking</h1><p>Check availability, reserve a slot, then simulate entry, exit and payment.</p></div>
    <span class="chip sim">SIMULATED IoT sensors · payment</span></div>
  <div class="grid g-park">
    <section>
      <div class="card" style="margin-bottom:16px"><div class="row">
        <div><label for="when">Arrival</label><select id="when"><option value="now">Now</option><option value="30">In 30 minutes</option>
          <option value="60">In 1 hour</option><option value="120">In 2 hours</option><option value="later">Pick a day &amp; time…</option></select></div>
        <div class="whenBox" hidden><label for="whenDay">Day</label><select id="whenDay"><option value="0">Today</option><option value="1">Tomorrow</option></select></div>
        <div class="whenBox" hidden><label for="whenTime">Start time</label><input type="time" id="whenTime"></div>
        <div><label for="hours">Duration</label><select id="hours">${[1, 2, 3, 4, 5, 6, 7, 8].map(h => `<option value="${h}">${h} hour${h > 1 ? 's' : ''}</option>`).join('')}</select></div></div>
        <div class="hint">You can book up to 24 hours ahead (today or tomorrow). Slots that cannot be booked for the chosen window are dimmed.</div></div>
      <div id="lots" class="lots-grid"></div>
      <div class="card"><div class="legend" style="margin:0"><span><i class="st-free"></i>Free</span><span><i class="st-reserved"></i>Reserved</span>
        <span><i class="st-occupied"></i>Car parked</span><span><i class="st-payment_due"></i>Payment due</span><span><i class="st-mismatch"></i>Sensor mismatch</span>
        <span><i class="st-maintenance"></i>Maintenance</span></div></div>
    </section>
    <aside class="side-list"><div id="activeBox"></div><div class="card" id="reserveBox"></div></aside>
  </div>`;
  $('#when').value = S.whenMode; $('#hours').value = S.hours; $('#whenDay').value = S.whenDay; $('#whenTime').value = S.whenTime;
  $$('.whenBox').forEach(b => { b.hidden = S.whenMode !== 'later'; });
  renderReserveBox();
}
// chosen arrival time as epoch seconds (null = now)
function whenTs() {
  if (S.whenMode === 'now') return null;
  if (S.whenMode !== 'later') return Date.now() / 1000 + Number(S.whenMode) * 60;
  if (!S.whenTime) return null;
  const [h, m] = S.whenTime.split(':').map(Number), d = new Date();
  d.setDate(d.getDate() + Number(S.whenDay)); d.setHours(h, m, 0, 0);
  return d.getTime() / 1000;
}
function windowQuery() {
  let q = `duration_hours=${S.hours}`;
  const ts = whenTs();
  if (ts) q += `&start_ts=${ts}`;
  return q;
}
async function loadParking() {
  const [p, r] = await Promise.all([api('/api/parking?' + windowQuery()), isAdmin() ? Promise.resolve({ reservations: [] }) : api('/api/reservations')]);
  S.parking = p; S.reservations = r.reservations;
  if (S.view !== 'parking') return;
  drawLots(); renderActive();
}
function drawLots() {
  $('#lots').innerHTML = S.parking.lots.map(l => `
    <div class="card lot ${esc(l.kind)}"><div class="lot-h"><h2>${l.kind === 'basement' ? '<span class="tag-base">BASEMENT</span> ' : ''}${esc(l.name)}</h2>
      <span class="muted">₹${l.rate_per_hour}/hour · <b>${l.counts.free}</b> free of ${l.total}</span></div>
    <div class="slots" style="grid-template-columns:repeat(${Math.min(l.cols, 6)},minmax(0,1fr))">
    ${l.slots.map(s => {
      const canPick = s.bookable && !isAdmin();
      const cls = ['slot', s.state, s.state === 'free' && !s.bookable ? 'unavail' : '', S.sel === s.id ? 'sel' : '', s.mine ? 'mine' : ''].join(' ');
      const sub = s.state === 'free' && !s.bookable ? 'Booked' : LABELS[s.state];
      const body = FULL.includes(s.state) ? carSvg() + (s.state === 'payment_due' && s.mine ? '<small>Pay due</small>' : '') : `<small>${esc(sub)}</small>`;
      return `<button class="${cls}" data-act="pick" data-id="${s.id}" ${canPick || isAdmin() ? '' : 'aria-disabled="true"'} title="${esc(s.label)}: ${esc(sub)}"
        aria-label="Slot ${esc(s.label)}: ${esc(sub)}${s.mine ? ' (yours)' : ''}">${s.reserved_later ? '<span class="later" title="Has a later booking">⏱</span>' : ''}<span class="sl">${esc(s.label)}</span>${body}
        ${s.vehicle_no ? `<small>${esc(s.vehicle_no)}</small>` : ''}</button>`;
    }).join('')}</div></div>`).join('');
}
function findSlot(id) { return S.parking?.lots.flatMap(l => l.slots.map(s => ({ ...s, lot: l }))).find(s => s.id === id); }
function renderReserveBox() {
  const box = $('#reserveBox'); if (!box) return;
  if (isAdmin()) { box.innerHTML = `<h3>Admin view</h3><p class="muted">Vehicle numbers are visible on occupied slots. Use the <a href="#/admin" class="link">Admin console</a> to inject sensor events.</p>`; return; }
  const s = S.sel ? findSlot(S.sel) : null;
  if (!s) { box.innerHTML = `<h3>Reserve a slot</h3><p class="muted">Pick a free (green) slot from the lots to start a reservation.</p>`; return; }
  const start = whenTs() ? new Date(whenTs() * 1000) : new Date();
  const end = new Date(start.getTime() + S.hours * 3600e3);
  const t = d => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  box.innerHTML = `<h3>Reserve slot ${esc(s.label)}</h3>
    <dl class="kv"><dt>Lot</dt><dd>${esc(s.lot.name)}</dd><dt>Time</dt><dd>${!whenTs() ? 'Now' : (S.whenMode === 'later' && S.whenDay === '1' ? 'Tomorrow ' : '') + t(start)} – ${t(end)} (${S.hours} h)</dd>
    <dt>Rate</dt><dd>₹${s.lot.rate_per_hour}/h (simulated)</dd></dl>
    <div class="field"><label for="veh">Vehicle number</label><input id="veh" placeholder="MH12AB1234" maxlength="14" value="${esc(S.vehicle)}" autocomplete="off">
      <div class="hint">Format: 2 letters, 2 digits, 1–3 letters, 4 digits.</div></div>
    <div class="err" id="resErr" role="alert"></div>
    <button class="btn block" data-act="reserve" ${s.bookable ? '' : 'disabled'}>${s.bookable ? 'Confirm reservation' : 'Not available for this window'}</button>`;
}
function renderActive() {
  const box = $('#activeBox'); if (!box || isAdmin()) return;
  const r = S.reservations.find(x => ['reserved', 'parked', 'awaiting_payment'].includes(x.status));
  if (!r) { box.innerHTML = ''; S.activeSig = ''; return; }
  const sig = r.id + r.status;
  if (sig === S.activeSig) { const f = $('#feeNow'); if (f && r.fee_so_far != null) f.textContent = inr(r.fee_so_far); return; }
  S.activeSig = sig;
  let body = '';
  if (r.status === 'reserved') body = `
    <p class="muted" style="margin:0">Drive to your slot. When the sensor detects your car, parking starts.</p>
    <div class="actions"><button class="btn" data-act="enter" data-id="${r.id}">Simulate: arrive at slot</button>
      <button class="btn danger" data-act="cancel" data-id="${r.id}">Cancel</button></div>`;
  if (r.status === 'parked') body = `
    <div class="muted">Fee so far (min. 1 hour)</div><div class="bigfee" id="feeNow">${inr(r.fee_so_far ?? 0)}</div>
    <div class="field" style="margin-top:12px"><label for="simMin">Demo: fast-forward minutes before leaving</label>
      <input id="simMin" type="number" min="0" max="720" value="0"><div class="hint">Demo-only shortcut so fees are visible without waiting. Try 61, or 200 to see an overstay penalty.</div></div>
    <button class="btn block" data-act="leave" data-id="${r.id}">Simulate: leave slot (sensor reports free)</button>`;
  if (r.status === 'awaiting_payment') { const f = r.fee_breakdown; body = `
    <div class="muted">Amount due</div><div class="bigfee">${inr(r.fee)}</div>
    <div class="hint">${f.billed_hours} h × ₹${f.rate} = ₹${f.base}${f.overstay_hours ? ` + overstay penalty ₹${f.overstay_penalty} (${f.overstay_hours} h late)` : ''} · parked ${f.parked_minutes} min</div>
    <div class="field" style="margin-top:12px"><label for="payM">Payment method (simulated gateway)</label>
      <select id="payM"><option>UPI</option><option>CARD</option><option>WALLET</option></select></div>
    <div class="field" id="fUpi"><label for="upi">UPI ID</label><input id="upi" placeholder="name@bank" value="shreya@okbank"></div>
    <div class="field" id="fCard" hidden><label for="card">Test card number</label><input id="card" inputmode="numeric" placeholder="4242 4242 4242 4242" maxlength="19">
      <div class="hint">4242 4242 4242 4242 approves · 4000 0000 0000 0002 declines</div></div>
    <label class="check"><input type="checkbox" id="forceFail"> Force payment failure (demo switch)</label>
    <div class="err" id="payErr" role="alert"></div>
    <button class="btn block" data-act="pay" data-id="${r.id}">Pay ${inr(r.fee)}</button>
    <p class="hint">The slot is released only after a successful payment.</p>`; }
  box.innerHTML = `<div class="card active-card"><div class="card-h"><h3>Your reservation #${r.id}</h3>${chip(r.status, r.status.replace('_', ' '))}</div>
    <dl class="kv"><dt>Slot</dt><dd>${esc(r.slot)} · ${esc(r.lot)}</dd><dt>Vehicle</dt><dd>${esc(r.vehicle_no)}</dd>
    <dt>Window</dt><dd>${dt(r.start_ts)} – ${hm(r.end_ts)}</dd></dl>${body}</div>`;
}

/* ------------------------------------------------------------- BUSES */
function mountBuses() {
  $('#view').innerHTML = `
  <div class="page-h"><div><h1>Campus buses</h1><p>Routes, stops, schedules and live (simulated) locations.</p></div>
    <span class="chip sim">SIMULATED GPS</span></div>
  <div class="grid g2"><section id="routeList"></section>
  <section class="card"><div class="card-h"><h2>Live bus status</h2><a class="link" href="#/map">View on map →</a></div><div id="busList"></div>
    <p class="hint">A bus is marked <b>Stale</b> if no GPS ping arrives for 20 s, and <b>No location</b> if it has never reported.</p></section></div>`;
  S.routesSig = '';
}
async function loadBuses() {
  const o = await api('/api/transport/overview');
  S.overview = o; S.buses = o.buses;
  if (S.view !== 'buses') return;
  const sig = JSON.stringify(o.routes);
  if (sig !== S.routesSig) {
    S.routesSig = sig;
    $('#routeList').innerHTML = o.routes.map(r => `
      <div class="card route-card" style="--c:${esc(r.color)}"><div class="card-h" style="margin-bottom:6px"><h2>${esc(r.code)} · ${esc(r.name)}</h2>
        ${chip(r.status === 'active' ? 'live' : 'out_of_service', r.status === 'active' ? 'Running' : 'Suspended')}</div>
      <div class="muted">First ${esc(r.first_departure)} · last ${esc(r.last_departure)} · every <b>${r.frequency_min} min</b> · ${r.trips_per_day} trips/day</div>
      ${r.note ? `<div class="note">📢 ${esc(r.note)}</div>` : ''}
      <div class="stops">${r.stops.map((s, i) => `${i ? '<i>→</i>' : ''}<span>${esc(s.name)}</span>`).join('')}<i>↺</i></div>
      <div style="margin-top:10px" class="muted">Next departures from ${esc(r.stops[0]?.name || 'first stop')}:</div>
      <div class="times">${r.status !== 'active' ? '<span class="muted">Service suspended</span>' : r.next_departures.length ? r.next_departures.map(t => `<b>${t}</b>`).join('') : '<span class="muted">No more trips today</span>'}</div></div>`).join('');
  }
  $('#busList').innerHTML = S.buses.map(b => {
    const pos = b.lat != null ? `<div class="muted" style="font-size:12px">${b.lat}, ${b.lon} <i>(simulated coordinates)</i> · ${b.speed_kmh} km/h</div>` : '';
    return busRow(b) .replace('</div></div>', pos + '</div></div>');
  }).join('');
}

/* ------------------------------------------------------------- BOOKINGS / ALERTS */
function mountBookings() {
  $('#view').innerHTML = `<div class="page-h"><div><h1>My bookings</h1><p>History of your parking reservations and payments.</p></div></div>
  <div class="card scroll" id="bookList"></div>`;
}
async function loadBookings() {
  S.reservations = (await api('/api/reservations')).reservations;
  if (S.view !== 'bookings') return;
  $('#bookList').innerHTML = S.reservations.length ? `<table><thead><tr><th>#</th><th>Slot</th><th>Vehicle</th><th>Window</th><th>Status</th><th>Fee (simulated)</th><th></th></tr></thead><tbody>
    ${S.reservations.map(r => `<tr><td>${r.id}</td><td>${esc(r.slot)}<br><small>${esc(r.lot)}</small></td><td>${esc(r.vehicle_no)}</td>
    <td>${dt(r.start_ts)} – ${hm(r.end_ts)}</td><td>${chip(r.status, r.status.replace('_', ' '))}</td>
    <td>${r.fee != null ? inr(r.fee) : '–'}</td><td>${['reserved', 'parked', 'awaiting_payment'].includes(r.status) ? '<a class="link" href="#/parking">Manage →</a>' : ''}</td></tr>`).join('')}</tbody></table>`
    : `<div class="empty">No bookings yet. <a class="link" href="#/parking">Reserve a slot →</a></div>`;
}
function mountAlerts() {
  $('#view').innerHTML = `<div class="page-h"><div><h1>Alerts &amp; notifications</h1><p>Route changes, reservation updates and payment messages.</p></div>
    <div><span class="chip sim">In-app notifications (simulated push)</span> <button class="btn ghost sm" data-act="readAll">Mark all read</button></div></div>
  <div class="card" id="notifList"></div>`;
  renderAlerts();
}
function renderAlerts() {
  const box = $('#notifList'); if (!box || !S.notifs) return;
  box.innerHTML = S.notifs.items.length ? S.notifs.items.map(n => `<div class="notif ${n.unread ? 'unread' : ''} ${esc(n.kind)}"><div class="bar"></div>
    <div style="flex:1"><div>${esc(n.message)}</div><small>${dt(n.ts)}${n.unread ? ' · <b>new</b>' : ''}</small></div></div>`).join('') : '<div class="empty">No notifications.</div>';
}

/* ------------------------------------------------------------- ADMIN */
function mountAdmin() {
  $('#view').innerHTML = `
  <div class="page-h"><div><h1>Admin console</h1><p>Operate parking sensors, bus GPS, routes and alerts.</p></div>
    <button class="btn danger sm" data-act="reset">Reset demo data</button></div>
  <div class="kpis" id="kpis"></div>
  <div class="grid g-admin">
    <section class="card"><div class="card-h"><h2>Sensor simulator</h2><span class="chip sim">SIMULATED</span></div>
      <div class="field"><label for="sSlot">Parking slot</label><select id="sSlot"></select></div>
      <div class="actions" style="margin:0 0 8px"><button class="btn" data-act="sensor" data-state="occupied">Report OCCUPIED</button>
        <button class="btn ghost" data-act="sensor" data-state="free">Report FREE</button>
        <button class="btn ghost" data-act="maint" data-on="1">Set maintenance</button><button class="btn ghost" data-act="maint" data-on="0">Clear maintenance</button></div>
      <div class="hint">“Occupied” on a slot with no reservation raises a mismatch alert. “Free” on a parked slot triggers exit &amp; fee calculation.</div>
      <div id="sRes" class="hint" style="font-weight:700"></div>
      <h3 style="margin-top:16px">Sensor mismatch alerts</h3><div id="alertList"></div></section>
    <section class="card"><div class="card-h"><h2>Route &amp; timing editor</h2></div>
      <div class="field"><label for="rtSel">Route</label><select id="rtSel"></select></div>
      <div class="row"><div class="field"><label for="rtFirst">First departure</label><input id="rtFirst" type="time"></div>
        <div class="field"><label for="rtLast">Last departure</label><input id="rtLast" type="time"></div>
        <div class="field"><label for="rtFreq">Every (min)</label><input id="rtFreq" type="number" min="5" max="60"></div></div>
      <div class="row"><div class="field"><label for="rtStatus">Status</label><select id="rtStatus"><option value="active">Active</option><option value="suspended">Suspended</option></select></div>
        <div class="field" style="flex:2"><label for="rtNote">Note shown to students</label><input id="rtNote" maxlength="160" placeholder="e.g. Diversion due to construction"></div></div>
      <label>Stops (in order)</label><ul class="stops-edit" id="rtStops"></ul>
      <div class="row"><select id="rtAdd"></select><button class="btn ghost" data-act="addStop" style="flex:none">+ Add stop</button></div>
      <div class="err" id="rtErr" role="alert"></div><div class="okmsg" id="rtOk"></div>
      <button class="btn block" style="margin-top:10px" data-act="saveRoute">Save &amp; notify students</button></section>
    <section class="card"><div class="card-h"><h2>Bus GPS (simulated)</h2></div><div id="gpsList" class="scroll"></div></section>
    <section class="card"><div class="card-h"><h2>Broadcast alert</h2></div>
      <div class="row"><div class="field"><label for="alRoute">Route</label><select id="alRoute"></select></div>
        <div class="field"><label for="alSev">Severity</label><select id="alSev"><option>info</option><option selected>warning</option><option>critical</option></select></div></div>
      <div class="field"><label for="alMsg">Message</label><input id="alMsg" maxlength="200" placeholder="e.g. R1 running 10 minutes late"></div>
      <div class="err" id="alErr" role="alert"></div><button class="btn block" data-act="sendAlert">Send alert</button></section>
  </div>
  <section class="card scroll" style="margin-top:16px"><div class="card-h"><h2>All reservations</h2></div><div id="allRes"></div></section>`;
  S.adminInit = false;
}
async function loadAdmin() {
  const [sum, al, rs, p, o] = await Promise.all([api('/api/admin/summary'), api('/api/admin/sensor-alerts'), api('/api/reservations'),
    api('/api/parking'), api('/api/transport/overview')]);
  if (S.view !== 'admin') return;
  S.parking = p; S.overview = o; S.buses = o.buses;
  $('#kpis').innerHTML = [
    [sum.occupancy_pct + '%', 'parking occupancy'], [S.parking.totals.free, 'slots free'], [sum.active_reservations, 'active reservations'],
    [sum.open_alerts, 'open sensor alerts'], ['₹' + sum.revenue_simulated.toFixed(2), 'revenue (simulated)'],
    [`${sum.buses.live || 0}/${S.buses.length}`, 'buses live']].map(([b, s]) => `<div class="kpi"><b>${b}</b><span>${s}</span></div>`).join('');
  $('#alertList').innerHTML = al.alerts.length ? al.alerts.map(a => `<div class="notif ${a.resolved ? '' : 'critical'}"><div class="bar"></div><div style="flex:1">
    <b>Slot ${esc(a.slot)}</b> · ${esc(a.kind.replace('_', ' '))} ${a.resolved ? chip('completed', 'resolved') : chip('critical', 'open')}<br><small>${esc(a.detail)} · ${dt(a.ts)}</small></div>
    ${a.resolved ? '' : `<button class="btn ghost sm" data-act="resolve" data-id="${a.id}">Resolve</button>`}</div>`).join('') : '<div class="empty">No alerts.</div>';
  $('#gpsList').innerHTML = `<table><thead><tr><th>Bus</th><th>Route</th><th>Status</th><th>Last ping</th><th></th></tr></thead><tbody>${S.buses.map(b => `<tr>
    <td>${esc(b.plate)}</td><td>${esc(b.route_code)}</td><td>${chip(b.freshness, FRESH[b.freshness])}</td><td>${b.age_s != null ? b.age_s + ' s ago' : 'never'}</td>
    <td><button class="btn ghost sm" data-act="gps" data-id="${b.id}" data-on="${b.gps_enabled ? 0 : 1}">${b.gps_enabled ? 'Cut GPS' : 'Enable GPS'}</button></td></tr>`).join('')}</tbody></table>`;
  $('#allRes').innerHTML = rs.reservations.length ? `<table><thead><tr><th>#</th><th>User</th><th>Slot</th><th>Vehicle</th><th>Window</th><th>Status</th><th>Fee</th></tr></thead><tbody>
    ${rs.reservations.map(r => `<tr><td>${r.id}</td><td>${esc(r.user)}</td><td>${esc(r.slot)}</td><td>${esc(r.vehicle_no)}</td><td>${dt(r.start_ts)} – ${hm(r.end_ts)}</td>
    <td>${chip(r.status, r.status.replace('_', ' '))}</td><td>${r.fee != null ? inr(r.fee) : '–'}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No reservations.</div>';
  if (!S.adminInit) initAdminForms();
}
function initAdminForms() {
  S.adminInit = true;
  $('#sSlot').innerHTML = S.parking.lots.map(l => `<optgroup label="${esc(l.name)}">${l.slots.map(s => `<option value="${s.id}">${esc(s.label)} – ${LABELS[s.state]}</option>`).join('')}</optgroup>`).join('');
  const routes = S.overview.routes;
  $('#rtSel').innerHTML = routes.map(r => `<option value="${r.id}">${esc(r.code)} · ${esc(r.name)}</option>`).join('');
  $('#alRoute').innerHTML = '<option value="">All routes</option>' + routes.map(r => `<option value="${r.id}">${esc(r.code)} · ${esc(r.name)}</option>`).join('');
  $('#rtAdd').innerHTML = S.overview.stops.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  fillRoute();
}
function fillRoute() {
  const r = S.overview.routes.find(x => x.id === +$('#rtSel').value); if (!r) return;
  $('#rtFirst').value = r.first_departure; $('#rtLast').value = r.last_departure; $('#rtFreq').value = r.frequency_min;
  $('#rtStatus').value = r.status; $('#rtNote').value = r.note || '';
  S.editStops = r.stops.map(s => ({ id: s.id, name: s.name })); drawEditStops();
  $('#rtErr').textContent = ''; $('#rtOk').textContent = '';
}
function drawEditStops() {
  $('#rtStops').innerHTML = S.editStops.map((s, i) => `<li><span>${i + 1}. ${esc(s.name)}</span>
    <button data-act="stopUp" data-i="${i}" aria-label="Move up">↑</button><button data-act="stopDown" data-i="${i}" aria-label="Move down">↓</button>
    <button data-act="stopDel" data-i="${i}" aria-label="Remove">✕</button></li>`).join('');
}

/* ------------------------------------------------------------- TESTS */
function mountTests() {
  $('#view').innerHTML = `<div class="page-h"><div><h1>Test cases</h1><p>Executes the automated suite (positive, negative, boundary) against a throw-away database and shows expected vs actual results.</p></div>
    <button class="btn" data-act="runTests">Run all tests</button></div><div class="card scroll" id="testOut"><div class="empty">Press “Run all tests”.</div></div>`;
}

/* ------------------------------------------------------------- actions */
const slotSelectedMsg = 'Please pick a slot first.';
const A = {
  showLogin: () => showLogin('login'), showRegister: () => showLogin('register'), logout: () => logout(),
  goAlerts: () => { location.hash = '#/alerts'; },
  readAll: async () => { await api('/api/notifications/read', { method: 'POST' }); await loadNotifs(true); },
  pick(b) {
    const s = findSlot(+b.dataset.id);
    if (isAdmin()) return;
    if (!s.bookable) { toast(`Slot ${s.label} is not available for the selected time (${LABELS[s.state]}).`, 'warning'); return; }
    S.sel = s.id; drawLots(); renderReserveBox();
  },
  async reserve() {
    const err = $('#resErr'); err.textContent = ''; $('#veh').classList.remove('bad');
    S.vehicle = $('#veh').value.trim().toUpperCase(); localStorage.setItem('veh', S.vehicle);
    if (!S.sel) { err.textContent = slotSelectedMsg; return; }
    const body = { slot_id: S.sel, duration_hours: S.hours, vehicle_no: S.vehicle };
    if (S.whenMode === 'later' && !S.whenTime) { err.textContent = 'Choose a start time, or switch Arrival to “Now”.'; return; }
    const ts = whenTs();
    if (ts) {
      if (ts < Date.now() / 1000 - 60) { err.textContent = 'That time has already passed. Pick a later time or switch Day to Tomorrow.'; return; }
      if (ts > Date.now() / 1000 + 24 * 3600) { err.textContent = 'You can only book up to 24 hours ahead.'; return; }
      body.start_ts = ts;
    }
    try {
      const r = await api('/api/reservations', { method: 'POST', body });
      toast(`Reservation #${r.reservation.id} confirmed for slot ${r.reservation.slot}.`, 'success');
      S.sel = null; await loadNotifs(true); await loadParking(); renderReserveBox();
    } catch (e) {
      err.textContent = e.message;
      if (e.fields.vehicle_no) $('#veh').classList.add('bad');
      if (e.code === 'slot_conflict') { await loadParking(); renderReserveBox(); }
    }
  },
  async enter(b) { await act(`/api/reservations/${b.dataset.id}/entry`, {}, 'Entry detected by the (simulated) sensor – parking started.', 'success'); },
  async leave(b) {
    const m = parseInt($('#simMin').value || '0', 10);
    await act(`/api/reservations/${b.dataset.id}/exit`, { simulate_minutes: isNaN(m) ? 0 : m }, 'Exit detected – fee calculated. Please pay to release the slot.', 'info');
  },
  async cancel(b) { if (confirm('Cancel this reservation?')) await act(`/api/reservations/${b.dataset.id}/cancel`, {}, 'Reservation cancelled – slot released.', 'info'); },
  async pay(b) {
    const method = $('#payM').value, body = { method, simulate_failure: $('#forceFail').checked, upi_id: $('#upi').value, card_number: $('#card').value };
    $('#payErr').textContent = '';
    try {
      await api(`/api/reservations/${b.dataset.id}/pay`, { method: 'POST', body });
      toast('Payment approved (simulated). Slot released – thank you!', 'success');
      await loadNotifs(true); await loadParking();
    } catch (e) { $('#payErr').textContent = e.message; await loadNotifs(true); }
  },
  async sensor(b) {
    try {
      const r = await api('/api/admin/sensors', { method: 'POST', body: { slot_id: +$('#sSlot').value, state: b.dataset.state } });
      $('#sRes').textContent = '→ ' + r.result.message; await loadNotifs(true); await loadAdmin(); refreshSlotOptions();
    } catch (e) { $('#sRes').textContent = '✖ ' + e.message; }
  },
  async maint(b) {
    try { await api(`/api/admin/slots/${$('#sSlot').value}/maintenance`, { method: 'POST', body: { maintenance: b.dataset.on === '1' } });
      $('#sRes').textContent = '→ Maintenance flag updated.'; await loadAdmin(); refreshSlotOptions(); } catch (e) { $('#sRes').textContent = '✖ ' + e.message; }
  },
  async resolve(b) { await api(`/api/admin/sensor-alerts/${b.dataset.id}/resolve`, { method: 'POST' }); await loadAdmin(); refreshSlotOptions(); },
  async gps(b) { await api(`/api/admin/buses/${b.dataset.id}/gps`, { method: 'POST', body: { enabled: b.dataset.on === '1' } }); await loadAdmin(); },
  addStop() {
    const id = +$('#rtAdd').value; if (S.editStops.some(s => s.id === id)) { $('#rtErr').textContent = 'That stop is already on the route.'; return; }
    S.editStops.push({ id, name: $('#rtAdd').selectedOptions[0].textContent }); $('#rtErr').textContent = ''; drawEditStops();
  },
  stopUp(b) { const i = +b.dataset.i; if (i > 0) { [S.editStops[i - 1], S.editStops[i]] = [S.editStops[i], S.editStops[i - 1]]; drawEditStops(); } },
  stopDown(b) { const i = +b.dataset.i; if (i < S.editStops.length - 1) { [S.editStops[i + 1], S.editStops[i]] = [S.editStops[i], S.editStops[i + 1]]; drawEditStops(); } },
  stopDel(b) { S.editStops.splice(+b.dataset.i, 1); drawEditStops(); },
  async saveRoute() {
    $('#rtErr').textContent = ''; $('#rtOk').textContent = '';
    const body = { first_departure: $('#rtFirst').value, last_departure: $('#rtLast').value, frequency_min: $('#rtFreq').value,
      status: $('#rtStatus').value, note: $('#rtNote').value, stops: S.editStops.map(s => s.id) };
    try {
      const r = await api('/api/admin/routes/' + $('#rtSel').value, { method: 'PUT', body });
      $('#rtOk').textContent = r.changed ? 'Saved. Students were notified: ' + r.changes.join('; ') : 'No changes to save.';
      const o = await api('/api/transport/overview'); S.overview = o; await loadNotifs(true);
      const keep = $('#rtSel').value; $('#rtSel').value = keep;
      S.editStops = r.route.stops.map(s => ({ id: s.id, name: s.name })); drawEditStops();
    } catch (e) { $('#rtErr').textContent = e.message; }
  },
  async sendAlert() {
    $('#alErr').textContent = '';
    try {
      await api('/api/admin/alerts', { method: 'POST', body: { route_id: $('#alRoute').value || null, severity: $('#alSev').value, message: $('#alMsg').value } });
      $('#alMsg').value = ''; toast('Alert sent to all students (simulated push).', 'success'); await loadNotifs(true);
    } catch (e) { $('#alErr').textContent = e.message; }
  },
  async reset() {
    if (!confirm('Reset ALL demo data (reservations, payments, routes, alerts, accounts)?')) return;
    await api('/api/admin/reset-demo', { method: 'POST' }); logout(true); toast('Demo data reset. Log in again.', 'success');
  },
  async runTests(b) {
    b.disabled = true; b.textContent = 'Running…';
    try {
      const r = await api('/api/admin/run-tests', { method: 'POST' });
      $('#testOut').innerHTML = `<div style="margin-bottom:10px;font-size:16px"><b class="${r.failed ? 'fail' : 'pass'}">${r.passed}/${r.total} passed</b>
        ${r.failed ? ` · ${r.failed} failed` : ' · all green'}</div><table><thead><tr><th>ID</th><th>Test case</th><th>Type</th><th>Expected</th><th>Actual</th><th>Result</th></tr></thead><tbody>
        ${r.results.map(t => `<tr><td>${esc(t.id)}</td><td>${esc(t.name)}</td><td>${chip(t.type === 'Positive' ? 'live' : t.type === 'Negative' ? 'critical' : 'warning', t.type)}</td>
        <td>${esc(t.expected)}</td><td>${esc(t.actual)}</td><td class="${t.passed ? 'pass' : 'fail'}">${t.passed ? 'PASS' : 'FAIL'}</td></tr>`).join('')}</tbody></table>`;
    } catch (e) { toast(e.message, 'error'); }
    b.disabled = false; b.textContent = 'Run all tests';
  },
};
async function act(path, body, okMsg, kind) {
  try { await api(path, { method: 'POST', body }); toast(okMsg, kind); await loadNotifs(true); S.activeSig = ''; await loadParking(); }
  catch (e) { toast(e.message, 'error'); await loadNotifs(true); await loadParking(); }
}
function refreshSlotOptions() {
  const v = $('#sSlot').value;
  $('#sSlot').innerHTML = S.parking.lots.map(l => `<optgroup label="${esc(l.name)}">${l.slots.map(s => `<option value="${s.id}">${esc(s.label)} – ${LABELS[s.state]}</option>`).join('')}</optgroup>`).join('');
  $('#sSlot').value = v;
}

/* ------------------------------------------------------------- global events */
document.addEventListener('click', e => {
  const b = e.target.closest('[data-act]');
  if (b && A[b.dataset.act]) { e.preventDefault(); A[b.dataset.act](b); }
});
document.addEventListener('change', e => {
  const id = e.target.id;
  if (id === 'when') { S.whenMode = e.target.value; $$('.whenBox').forEach(b => { b.hidden = S.whenMode !== 'later'; }); S.sel = null; loadParking().then(renderReserveBox); }
  else if (id === 'whenDay') { S.whenDay = e.target.value; S.sel = null; loadParking().then(renderReserveBox); }
  else if (id === 'whenTime') { S.whenTime = e.target.value; S.sel = null; loadParking().then(renderReserveBox); }
  else if (id === 'hours') { S.hours = +e.target.value; S.sel = null; loadParking().then(renderReserveBox); }
  else if (id === 'payM') { $('#fUpi').hidden = e.target.value !== 'UPI'; $('#fCard').hidden = e.target.value !== 'CARD'; }
  else if (id === 'rtSel') fillRoute();
});
window.addEventListener('hashchange', route);
setInterval(poll, 3000);

if (S.token && S.user) start(); else showLogin();
})();
