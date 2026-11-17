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
  const unavailable = ['STALE', 'INVALID', 'DISCONNECTED', 'ERROR', 'STOPPED', 'CONNECTING', 'VIEW OFFLINE', 'STORAGE_LIMIT', 'FORCED_TERMINATION'].includes(source.status) || flags.some(f => ['CROSSED', 'MISSING_BID', 'MISSING_ASK', 'INVALID_BID', 'INVALID_ASK', 'MISSING_SOURCE_TIME', 'FUTURE_SOURCE_TIME', 'UNSUPPORTED_SYMBOL', 'SOURCE_OUT_OF_ORDER', 'RECEIVE_TIME_REVERSED'].includes(f));
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
    if (source.last_valid && ['STALE', 'INVALID', 'DISCONNECTED', 'ERROR', 'STOPPED', 'VIEW OFFLINE', 'STORAGE_LIMIT', 'FORCED_TERMINATION'].includes(source.status)) {
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
  sourceIds.forEach((id, index) => { c.strokeStyle = colors[index % colors.length]; c.fillStyle = colors[index % colors.length]; c.lineWidth = 2; c.beginPath(); let open = false, count = 0, lastX = 0, lastY = 0;
    for (const p of series.get(id) || []) { if (p.t < minT || !Number.isFinite(p.t)) continue; if (p.v === null || !Number.isFinite(p.v)) {open=false; continue;} const x=pad.l+(p.t-minT)/(maxT-minT)*(w-pad.l-pad.r), y=pad.t+(ymax-p.v)/(ymax-ymin)*(h-pad.t-pad.b); count++;lastX=x;lastY=y;if(!open){c.moveTo(x,y);open=true;}else c.lineTo(x,y); } c.stroke();if(count===1){c.beginPath();c.arc(lastX,lastY,3,0,2*Math.PI);c.fill();} });
  $('chart-range').textContent = maxT ? utc(minT).slice(11,19) + ' — ' + utc(maxT).slice(11,19) : '—';
}
$('window').addEventListener('change', () => { loadHistory().catch(() => {}); });
window.addEventListener('resize', draw);
window.addEventListener('beforeunload', () => { generation++; clearTimeout(retry); if (socket) socket.close(); });
connect();

// Research controls only read sealed local data. They never send ingestion requests.
const researchSessions = new Map();
let selectedSeries = new Set(), knownSeries = new Set(), pickerKey = '', historyCursor = null;
const originalRender = render;
render = function(snapshot) {
  originalRender(snapshot);
  const key = snapshot.sources.map(s => s.source_id).join('|');
  if (key !== pickerKey) {
    pickerKey = key; $('source-picker').replaceChildren();
    snapshot.sources.forEach(s => {
      if (!knownSeries.has(s.source_id)) { knownSeries.add(s.source_id); selectedSeries.add(s.source_id); }
      const wrap = make('label'), checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.checked = selectedSeries.has(s.source_id);
      checkbox.addEventListener('change', () => { if (checkbox.checked) selectedSeries.add(s.source_id); else selectedSeries.delete(s.source_id); draw(); });
      wrap.append(checkbox, document.createTextNode(s.broker_id + ' · ' + s.expected_account_environment));
      $('source-picker').append(wrap);
    });
  }
  $('system-detail').textContent = snapshot.sources.map(s => s.source_id + ' · ' + s.status + ' · display queue drops ' + s.queue_dropped + ' · run ' + s.output_run).join('\n');
};
const originalDraw = draw;
draw = function() {
  if (!latest || selectedSeries.size === latest.sources.length) return originalDraw();
  const full = latest;
  latest = {...full, sources:full.sources.filter(s => selectedSeries.has(s.source_id))};
  try { originalDraw(); } finally { latest = full; }
};
function fail(id, error) { $(id).textContent = 'Unable to read sealed local data: ' + error.message; }
async function getJson(url) { const response=await fetch(url,{cache:'no-store'}); if(!response.ok) { const body=await response.json().catch(()=>({})); throw Error(body.detail || ('HTTP ' + response.status)); } return response.json(); }
function sessionText(s) { const x=s.source || {}; return (x.broker_id || 'unknown') + ' · ' + (x.environment || 'UNKNOWN') + ' · ' + s.session_id + ' · ' + s.state; }
async function refreshSessions() {
  const sessions = await getJson('/live/sessions?limit=100'); researchSessions.clear();
  sessions.forEach(s => researchSessions.set(s.session_id,s));
  for (const name of ['history-session','analytics-session','compare-left','compare-right']) {
    const field=$(name), previous=field.value; field.replaceChildren();
    for (const s of sessions) { const option=make('option','',sessionText(s)); option.value=s.session_id; field.append(option); }
    if (researchSessions.has(previous)) field.value=previous;
  }
  if (sessions.length>1 && $('compare-left').value === $('compare-right').value) $('compare-right').selectedIndex=1;
  $('system-storage').textContent = 'Local sessions visible: ' + sessions.length + ' · Only sealed segments are readable.';
  await refreshSegments();
}
async function refreshSegments() {
  const id=$('history-session').value, field=$('history-segment'); field.replaceChildren(); historyCursor=null;
  $('history-next').disabled=true; if(!id){$('history-info').textContent='No sealed session manifests found.';return;}
  const session=await getJson('/live/sessions/'+encodeURIComponent(id));
  for(const segment of session.segments){const option=make('option','', 'Segment '+segment.index+' · '+segment.rows+' observations');option.value=segment.index;field.append(option);}
  const state=session.state === 'COMPLETE' ? 'COMPLETE' : session.state + ' · partial or active; only sealed segments available';
  $('history-info').textContent=state+' · '+(session.source?.source_id || 'source not yet observed')+' · '+session.segments.length+' sealed segments. '+(session.segments.length ? 'Available receive ns: '+session.segments[0].min_receive_ns+' — '+session.segments[session.segments.length-1].max_receive_ns : 'No sealed data yet.');
}
function historyParams(after=0){
  const params=new URLSearchParams({segment:$('history-segment').value,after:String(after),limit:'200'});
  for(const name of ['start','end']){const v=$('history-'+name).value.trim();if(v){if(!/^\d{1,19}$/.test(v))throw Error('receive window must be integer UTC nanoseconds');params.set(name+'_ns',v);}}
  return params;
}
function tableRow(body, values){ const tr=make('tr');values.forEach(v=>tr.append(make('td','',label(v))));body.append(tr); }
function drawHistorical(rows){
  const canvas=$('history-chart'), box=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
  canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);const c=canvas.getContext('2d');c.scale(dpr,dpr);
  const points=rows.map(x=>{const o=x.observation,r=o.quote.raw,f=o.spread.data_quality_flags;return {t:nsToMs(r.received_time_ns),v:f.some(v=>['STALE','CROSSED','MISSING_BID','MISSING_ASK','INVALID_BID','INVALID_ASK','MISSING_SOURCE_TIME','FUTURE_SOURCE_TIME','UNSUPPORTED_SYMBOL','SOURCE_OUT_OF_ORDER','RECEIVE_TIME_REVERSED'].includes(v)) || o.spread.spread_usd_per_oz===null ? null : Number(o.spread.spread_usd_per_oz)};});
  const good=points.filter(p=>Number.isFinite(p.t)&&p.v!==null&&Number.isFinite(p.v)); c.strokeStyle='#263b47';c.beginPath();c.moveTo(45,box.height/2);c.lineTo(box.width-10,box.height/2);c.stroke();if(!good.length)return;
  const lo=Math.min(...good.map(p=>p.v)),hi=Math.max(...good.map(p=>p.v)),loT=Math.min(...good.map(p=>p.t)),hiT=Math.max(...good.map(p=>p.t));
  const min=lo-Math.max((hi-lo)*.2,.005), max=hi+Math.max((hi-lo)*.2,.005);c.strokeStyle='#79d8bb';c.fillStyle='#79d8bb';c.lineWidth=2;c.beginPath();let open=false;
  for(const p of points){if(p.v===null||!Number.isFinite(p.t)||!Number.isFinite(p.v)){open=false;continue;}const x=45+(hiT===loT?.5:(p.t-loT)/(hiT-loT))*(box.width-55),y=10+(max-p.v)/(max-min)*(box.height-20);if(!open){c.moveTo(x,y);open=true;}else c.lineTo(x,y);c.moveTo(x+2,y);c.arc(x,y,2,0,2*Math.PI);c.moveTo(x,y);}c.stroke();
}
async function loadHistorical(after=0){
  const id=$('history-session').value;if(!id||!$('history-segment').value)throw Error('choose a session with a sealed segment');
  const data=await getJson('/live/sessions/'+encodeURIComponent(id)+'/observations?'+historyParams(after));
  const body=$('history-rows');body.replaceChildren();
  data.rows.forEach(row=>{const o=row.observation,r=o.quote.raw;tableRow(body,[utc(nsToMs(r.received_time_ns)),r.source_time_ms,r.bid,r.ask,o.spread.spread_usd_per_oz,o.spread.data_quality_flags.join(', ')||'none']);});
  historyCursor=data.next_after;$('history-next').disabled=historyCursor===null;drawHistorical(data.rows);
  $('history-info').textContent='Session '+id+' · sealed segment '+data.segment+' · '+data.rows.length+' rows on this page; no forward fill.';
}
function metric(container,title,value){const cell=make('div','metric');cell.append(make('span','label',title),make('strong','',label(value)));container.append(cell);}
async function analytics(){
  const id=$('analytics-session').value,t=$('analytics-threshold').value.trim(),fresh=$('analytics-freshness').value;
  if(!id||!t)throw Error('select a session and enter a widening threshold');
  const query=new URLSearchParams({threshold:t,freshness_seconds:fresh});const data=await getJson('/live/sessions/'+encodeURIComponent(id)+'/statistics?'+query), m=data.metrics;
  $('analytics-info').textContent=data.session_state+' · '+(data.source?.broker_id||'unknown')+' · '+(data.source?.environment||'UNKNOWN')+' · '+m.valid_snapshots+'/'+m.snapshots+' valid snapshots · receive-time units USD/oz';
  const box=$('analytics-metrics');box.replaceChildren();[['MEAN',m.mean],['MEDIAN',m.median],['P95',m.p95],['P99',m.p99],['MIN / MAX',label(m.minimum)+' / '+label(m.maximum)],['TIME-WEIGHTED MEAN',m.time_weighted_mean],['VALID COVERAGE',m.valid_coverage],['STALE RATE',m.quality_rates.stale],['DUPLICATE RATE',m.quality_rates.duplicate],['INVALID RATE',m.quality_rates.invalid],['CHANGES / VALID SECOND',m.changes_per_valid_second],['WIDENING EVENTS',m.widening_count]].forEach(x=>metric(box,...x));
  const rows=$('analytics-events');rows.replaceChildren();m.widening_events.forEach(e=>tableRow(rows,[utc(nsToMs(e.start_ns)),utc(nsToMs(e.end_ns)),Number(BigInt(e.widening_duration_ns))/1e9,e.recovery_duration_ns===null?'—':Number(BigInt(e.recovery_duration_ns))/1e9,e.recovered?'recovered':'censored']));
  $('analytics-metadata').textContent=JSON.stringify(m.instrument_metadata,null,2);
  const download=$('report-download');download.href='/live/sessions/'+encodeURIComponent(id)+'/report?'+new URLSearchParams({threshold:t,freshness_seconds:fresh,download:'true'});download.hidden=false;
}
async function compareSessions(){
  const left=$('compare-left').value,right=$('compare-right').value,age=$('compare-age').value,t=$('compare-threshold').value.trim();
  if(!left||!right||left===right||!t)throw Error('select distinct sessions and enter a widening threshold');
  const [data,a,b]=await Promise.all([getJson('/live/compare?'+new URLSearchParams({left,right,tolerance_ms:age})),getJson('/live/sessions/'+encodeURIComponent(left)+'/statistics?'+new URLSearchParams({threshold:t})),getJson('/live/sessions/'+encodeURIComponent(right)+'/statistics?'+new URLSearchParams({threshold:t}))]);
  const r=data.result;$('compare-info').textContent=data.left_source.broker_id+' · '+data.left_source.environment+' versus '+data.right_source.broker_id+' · '+data.right_source.environment+' · '+r.warning+' · Showing up to 100 of '+r.matched+' matches.';
  const box=$('compare-metrics');box.replaceChildren();[['MATCHED / EVALUATIONS',r.matched+' / '+r.evaluations],['UNMATCHED',r.unmatched],['COVERAGE',r.coverage],['MEAN DIFFERENCE',r.mean_spread_difference],['MEAN ABS DIFFERENCE',r.mean_absolute_spread_difference],['LEFT / RIGHT WIDENINGS',a.metrics.widening_count+' / '+b.metrics.widening_count],['LEFT / RIGHT INVALID RATE',label(a.metrics.quality_rates.invalid)+' / '+label(b.metrics.quality_rates.invalid)],['LEFT / RIGHT STALE RATE',label(a.metrics.quality_rates.stale)+' / '+label(b.metrics.quality_rates.stale)],['LEFT / RIGHT DUPLICATE RATE',label(a.metrics.quality_rates.duplicate)+' / '+label(b.metrics.quality_rates.duplicate)]].forEach(x=>metric(box,...x));
  $('compare-metadata').textContent=JSON.stringify({left:data.left_instrument,right:data.right_instrument},null,2);
  const rows=$('compare-rows');rows.replaceChildren();r.rows.slice(0,100).forEach(x=>tableRow(rows,[utc(nsToMs(x.evaluation_ns)),Number(BigInt(x.age_ns))/1e6,label(x.left_bid)+' / '+label(x.left_ask),label(x.right_bid)+' / '+label(x.right_ask),x.left_spread+' / '+x.right_spread,label(x.left_points)+' / '+label(x.right_points),x.spread_difference]));
}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));document.querySelectorAll('[data-panel]').forEach(panel=>{panel.hidden=panel.dataset.panel!==button.dataset.tab;});if(button.dataset.tab==='realtime')draw();if(['history','analytics','compare','system'].includes(button.dataset.tab)){const target={history:'history-info',analytics:'analytics-info',compare:'compare-info',system:'system-storage'}[button.dataset.tab];refreshSessions().catch(e=>fail(target,e));}}));
$('refresh-sessions').addEventListener('click',()=>refreshSessions().catch(e=>fail('history-info',e)));
$('history-session').addEventListener('change',()=>refreshSegments().catch(e=>fail('history-info',e)));
$('history-load').addEventListener('click',()=>loadHistorical().catch(e=>fail('history-info',e)));
$('history-next').addEventListener('click',()=>loadHistorical(historyCursor).catch(e=>fail('history-info',e)));
$('analytics-run').addEventListener('click',()=>analytics().catch(e=>fail('analytics-info',e)));
$('compare-run').addEventListener('click',()=>compareSessions().catch(e=>fail('compare-info',e)));

['analytics-session','analytics-threshold','analytics-freshness'].forEach(id=>$(id).addEventListener('input',()=>{$('report-download').hidden=true;}));
