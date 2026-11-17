'use strict';
const $ = id => document.getElementById(id);
const series = new Map();
const colors = ['#79d8bb', '#9baff4', '#e5b878', '#dc92b6'];
let socket = null, retry = null, generation = 0, latest = null, coalescedOffset = 0;
const maxPoints = 6000;
function label(value) { return value === null || value === undefined || value === '' ? '—' : String(value); }
function utc(ms) { if (!Number.isFinite(ms)) return '—'; const date = new Date(ms); if (!Number.isFinite(date.getTime())) return '—'; return date.toISOString().replace('T', ' ').replace('Z', ' UTC'); }
function nsToMs(ns) { try { return Number(BigInt(ns) / 1000000n); } catch (_) { return NaN; } }
function make(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function row(labelText, text, className = '') { const n = make('div', className); n.append(make('span', 'label', labelText), make('strong', '', label(text))); return n; }
function insertGap(data, t) { if (data.length && data[data.length - 1].v !== null) data.push({t, v: null}); }
function mergePoint(source, previous, coalescedChanged) {
  const id = source.source_id, raw = source.latest?.quote?.raw;
  if (!series.has(id)) series.set(id, []);
  const data = series.get(id);
  if (!raw || !source.latest) return;
  const t = nsToMs(raw.received_time_ns);
  if (!Number.isFinite(t)) return;
  if ((previous && source.sequence > previous + 1) || coalescedChanged) insertGap(data, t);
  const flags = source.latest.spread.data_quality_flags;
  const unavailable = ['STALE', 'INVALID', 'DISCONNECTED', 'ERROR', 'STOPPED', 'CONNECTING', 'VIEW OFFLINE'].includes(source.status) || flags.some(f => ['CROSSED', 'MISSING_BID', 'MISSING_ASK', 'INVALID_BID', 'INVALID_ASK', 'MISSING_SOURCE_TIME', 'FUTURE_SOURCE_TIME', 'UNSUPPORTED_SYMBOL', 'SOURCE_OUT_OF_ORDER', 'RECEIVE_TIME_REVERSED'].includes(f));
  if (unavailable || source.latest.spread.spread_usd_per_oz === null) insertGap(data, t);
  else if (!flags.includes('DUPLICATE') && (!previous || source.sequence !== previous)) {
    const v = Number(source.latest.spread.spread_usd_per_oz);
    if (Number.isFinite(v)) data.push({t, v});
  }
  if (data.length > maxPoints) data.splice(0, data.length - maxPoints);
}
function render(snapshot) {
  latest = snapshot;
  $('mode').textContent = snapshot.mode;
  $('mode-note').textContent = snapshot.mode === 'MOCK' ? 'SYNTHETIC DATA · Two simulated sources. This does not verify MT5 connectivity.' : 'LOCAL READ-ONLY · Broker aliases are user labels. Quotes are snapshots, not executable prices.';
  $('session-clock').textContent = 'Hub session · ' + snapshot.session_seconds + ' s';
  $('source-count').textContent = snapshot.sources.length + (snapshot.sources.length === 1 ? ' SOURCE' : ' SOURCES');
  $('drops').textContent = snapshot.sources.reduce((n, s) => n + s.queue_dropped, 0);
  $('coalesced').textContent = coalescedOffset + (snapshot.display_coalesced || 0);
  $('rejected').textContent = snapshot.rejected_events;
  $('display-time').textContent = new Date().toISOString().slice(11, 19);
  const cards = $('cards'); cards.replaceChildren();
  const legend = $('legend'); legend.replaceChildren();
  snapshot.sources.forEach((source, index) => {
    const obs = source.latest, raw = obs?.quote?.raw, spread = obs?.spread, card = make('article', 'card');
    const head = make('div', 'card-head'), broker = make('div', 'broker'), icon = make('div', 'broker-icon', String(index + 1).padStart(2, '0'));
    const name = make('div'); name.append(make('div', 'broker-title', label(source.broker_id)), make('div', 'source-line', label(source.source_id) + '  ·  ' + label(source.symbol)));
    broker.append(icon, name);
    const badge = make('span', 'badge' + (source.expected_account_environment === 'DEMO' ? ' demo' : ''), source.expected_account_environment + (snapshot.mode === 'MOCK' ? ' · SYNTHETIC' : ''));
    head.append(broker, badge); card.append(head);
    const prices = make('div', 'price-row'); prices.append(row('BID', raw?.bid, 'price'), row('ASK', raw?.ask, 'price ask')); card.append(prices);
    const box = make('div', 'spread-box'), left = make('div'), right = make('div');
    left.append(make('span', 'label', 'SPREAD · USD/OZ'));
    const spreadValue = make('div', 'spread-number', label(spread?.spread_usd_per_oz)); left.append(spreadValue);
    right.append(make('span', 'label', 'POINTS'), make('div', 'points', label(spread?.spread_points))); box.append(left, right); card.append(box);
    const meta = make('div', 'card-meta');
    meta.append(row('CONNECTION', source.status, ['LIVE', 'MOCK'].includes(source.status) ? 'state' : 'state bad'), row('SOURCE QUOTE · UTC', raw?.source_time_ms == null ? '—' : utc(raw.source_time_ms)), row('LOCAL RECEIVE · UTC', raw ? utc(nsToMs(raw.received_time_ns)) : '—'), row('PROCESSING · UTC', obs ? utc(nsToMs(obs.processing_time_ns)) : '—'), row('DUPLICATE / STALE', source.duplicates + ' / ' + source.stale_observations), row('CHANGES / QUEUE DROPS', source.observed_changes + ' / ' + source.queue_dropped), row('ACTIVE CAPTURE · SECONDS', source.active_seconds));
    card.append(meta);
    let note = raw ? 'Flags: ' + ((spread?.data_quality_flags || []).join(', ') || 'none') : 'Waiting for first observation';
    if (source.last_valid && ['STALE', 'INVALID', 'DISCONNECTED', 'ERROR', 'STOPPED', 'VIEW OFFLINE'].includes(source.status)) {
      const retained = source.last_valid.quote.raw;
      note += ' · Last valid (retained, not current): ' + label(retained.bid) + ' / ' + label(retained.ask) + ' · source ' + utc(retained.source_time_ms);
    }
    card.append(make('div', 'card-note', note)); cards.append(card);
    const item = make('div', 'legend-item'), mark = make('span', 'legend-mark series-' + (index % colors.length)); item.append(mark, make('span', '', label(source.broker_id) + ' · ' + source.expected_account_environment)); legend.append(item);
  });
  if (!snapshot.sources.length) cards.append(make('div', 'placeholder', 'No sources configured'));
  draw();
}
let lastSeq = {}, lastDrops = {}, lastCoalesced = 0;
function handle(snapshot) {
  const changed = (snapshot.display_coalesced || 0) > lastCoalesced;
  snapshot.sources.forEach(s => {
    const lost = s.queue_dropped > (lastDrops[s.source_id] || 0);
    mergePoint(s, lastSeq[s.source_id], changed || lost);
    lastSeq[s.source_id] = s.sequence;
    lastDrops[s.source_id] = s.queue_dropped;
  });
  lastCoalesced = snapshot.display_coalesced || 0;
  render(snapshot);
}
async function loadHistory() {
  const response = await fetch('/live/latest', {cache:'no-store'});
  if (!response.ok) throw Error('local hub unavailable');
  const snapshot = await response.json();
  await Promise.all(snapshot.sources.map(async source => {
    const url = '/live/history?source_id=' + encodeURIComponent(source.source_id) + '&seconds=' + encodeURIComponent($('window').value);
    const result = await fetch(url, {cache:'no-store'});
    if (!result.ok) return;
    const body = await result.json();
    series.set(source.source_id, body.points.slice(-maxPoints).map(p => ({t:nsToMs(p.time_ns), v:p.spread === null ? null : Number(p.spread)})));
    lastSeq[source.source_id] = source.sequence;
  }));
  render(snapshot);
}
async function connect() {
  const current = ++generation;
  try { await loadHistory(); } catch (_) { $('socket-status').textContent = 'HUB UNAVAILABLE'; }
  if (current !== generation) return;
  const ws = new WebSocket('ws://' + location.host + '/live/ws'); socket = ws;
  ws.onopen = () => { $('socket-status').textContent = 'CONNECTED'; $('socket-dot').classList.remove('off'); lastCoalesced = 0; };
  ws.onmessage = event => { try { handle(JSON.parse(event.data)); } catch (_) { $('socket-status').textContent = 'DATA ERROR'; } };
  ws.onerror = () => ws.close();
  ws.onclose = () => {
    $('socket-status').textContent = 'DISCONNECTED · RETRYING';
    $('socket-dot').classList.add('off');
    coalescedOffset += lastCoalesced; lastCoalesced = 0;
    if (latest) {
      for (const data of series.values()) if (data.length) insertGap(data, data[data.length - 1].t);
      render({...latest, display_coalesced:0, sources:latest.sources.map(source => ({...source, status:'VIEW OFFLINE'}))});
    }
    if (current === generation) retry = setTimeout(connect, 1500);
  };
}
function draw() {
  const canvas = $('chart'), box = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(box.width * dpr); canvas.height = Math.round(box.height * dpr);
  const c = canvas.getContext('2d'); c.scale(dpr, dpr); const w = box.width, h = box.height, pad = {l:52,r:12,t:17,b:20};
  const sourceIds = (latest?.sources || []).map(s => s.source_id);
  const all = sourceIds.flatMap(id => series.get(id) || []).filter(p => Number.isFinite(p.t));
  const maxT = all.length ? Math.max(...all.map(p => p.t)) : 0;
  const minT = maxT - Number($('window').value) * 1000;
  const values = all.filter(p => p.t >= minT && p.v !== null && Number.isFinite(p.v)).map(p => p.v);
  $('chart-empty').classList.toggle('hidden', values.length > 0);
  c.font = '10px system-ui'; c.textAlign = 'right'; c.fillStyle = '#6f8998'; c.strokeStyle = '#253642'; c.lineWidth = 1;
  const low = values.length ? Math.min(...values) : 0, high = values.length ? Math.max(...values) : 1, margin = Math.max((high - low) * 0.18, 0.005);
  const ymin = low - margin, ymax = high + margin;
  for (let i=0;i<=4;i++) { const y = pad.t + i * (h-pad.t-pad.b)/4; c.beginPath(); c.moveTo(pad.l,y); c.lineTo(w-pad.r,y); c.stroke(); if(values.length) c.fillText((ymax-i*(ymax-ymin)/4).toFixed(3),pad.l-8,y+3); }
  sourceIds.forEach((id, index) => { c.strokeStyle = colors[index % colors.length]; c.lineWidth = 2; c.beginPath(); let open = false;
    for (const p of series.get(id) || []) { if (p.t < minT || !Number.isFinite(p.t)) continue; if (p.v === null || !Number.isFinite(p.v)) {open=false; continue;} const x=pad.l+(p.t-minT)/(maxT-minT)*(w-pad.l-pad.r), y=pad.t+(ymax-p.v)/(ymax-ymin)*(h-pad.t-pad.b); if(!open){c.moveTo(x,y);open=true;}else c.lineTo(x,y); } c.stroke(); });
  $('chart-range').textContent = maxT ? utc(minT).slice(11,19) + ' — ' + utc(maxT).slice(11,19) : '—';
}
$('window').addEventListener('change', () => { loadHistory().catch(() => {}); });
window.addEventListener('resize', draw);
window.addEventListener('beforeunload', () => { generation++; clearTimeout(retry); if (socket) socket.close(); });
connect();
