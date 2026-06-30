#!/usr/bin/env python3
"""
gen_flows.py  — generate valid Node-RED flows.json
Uses only stdlib, no external deps.
"""
import json, os

TOKEN = "apiv3_ds_pESsacfI0_vXWdSHp49SZaXPbODKnd8gaSQopgUOV-ijAiLEeqLy3IiyXhp0bQtGmN1pHOHS83CJfKWqP7w"
HOST  = "http://influxdb:8181"

MACHINES_JSON = json.dumps([
    {"id": "machine_01", "location": "produksi_a", "basePower": 12, "baseVoltage": 220, "baseCurrent": 55},
    {"id": "machine_02", "location": "produksi_a", "basePower": 10, "baseVoltage": 218, "baseCurrent": 46},
    {"id": "machine_03", "location": "produksi_b", "basePower": 22, "baseVoltage": 221, "baseCurrent": 100},
    {"id": "machine_04", "location": "gudang",     "basePower":  4, "baseVoltage": 219, "baseCurrent": 18},
    {"id": "machine_05", "location": "office",     "basePower":  3, "baseVoltage": 220, "baseCurrent": 14},
])

def fn(code): return code.strip()

# ── Function node code strings ───────────────────────────────────────────────

MIG_FN_INIT = fn(f"""
// [1] Init: define databases and tables, use InfluxDB v3 native API
const HOST  = '{HOST}';
const TOKEN = '{TOKEN}';
const databases = [
  {{ db: 'energy_monitoring', retention_period: null,  label: 'RAW (permanent)' }},
  {{ db: 'energy_minutes',    retention_period: '14d', label: 'MINUTES (14d)' }},
  {{ db: 'energy_hour',       retention_period: null,  label: 'HOURLY (permanent)' }}
];
const tables = [
  {{ db: 'energy_monitoring', table: 'energy_raw',    tags: ['machine_id','location'] }},
  {{ db: 'energy_minutes',    table: 'energy_minute', tags: ['machine_id','location'] }},
  {{ db: 'energy_hour',       table: 'energy_hour',   tags: ['machine_id','location'] }}
];
flow.set('mig_host', HOST);
flow.set('mig_token', TOKEN);
flow.set('mig_databases', databases);
flow.set('mig_tables', tables);
flow.set('mig_db_idx', 0);
flow.set('mig_tbl_idx', 0);
node.status({{ fill: 'blue', shape: 'dot', text: 'Starting...' }});
msg.payload = 'start';
return msg;
""")

MIG_FN_NEXT_DB = fn("""
// [1] Loop: POST /api/v3/configure/database
const databases = flow.get('mig_databases') || [];
const idx = flow.get('mig_db_idx') || 0;
if (idx >= databases.length) {
  node.status({ fill: 'green', shape: 'dot', text: idx + ' DBs created' });
  return [null, msg];
}
const db = databases[idx];
const body = { db: db.db };
if (db.retention_period) body.retention_period = db.retention_period;
msg.url     = flow.get('mig_host') + '/api/v3/configure/database';
msg.method  = 'POST';
msg.headers = { 'Authorization': 'Bearer ' + flow.get('mig_token'), 'Content-Type': 'application/json' };
msg.payload = JSON.stringify(body);
msg._label  = db.label;
msg._idx    = idx;
node.status({ fill: 'blue', shape: 'ring', text: 'DB: ' + db.db });
return [msg, null];
""")

MIG_FN_DB_RESULT = fn("""
const code = msg.statusCode;
if (code === 200 || code === 201) {
  node.log('[mig] DB created: ' + msg._label);
} else if (code === 409 || code === 422) {
  node.log('[mig] DB exists: ' + msg._label + ' (OK)');
} else {
  node.warn('[mig] DB status ' + code + ': ' + msg.payload);
}
flow.set('mig_db_idx', (msg._idx || 0) + 1);
return msg;
""")

MIG_FN_NEXT_TBL = fn("""
// [2] Loop: POST /api/v3/configure/table
const tables = flow.get('mig_tables') || [];
const idx = flow.get('mig_tbl_idx') || 0;
if (idx >= tables.length) {
  node.status({ fill: 'green', shape: 'dot', text: idx + ' tables created' });
  return [null, msg];
}
const t = tables[idx];
msg.url     = flow.get('mig_host') + '/api/v3/configure/table';
msg.method  = 'POST';
msg.headers = { 'Authorization': 'Bearer ' + flow.get('mig_token'), 'Content-Type': 'application/json' };
msg.payload = JSON.stringify({ db: t.db, table: t.table, tags: t.tags });
msg._tbl    = t.db + '.' + t.table;
msg._tidx   = idx;
node.status({ fill: 'blue', shape: 'ring', text: 'Table: ' + t.table });
return [msg, null];
""")

MIG_FN_TBL_RESULT = fn("""
const code = msg.statusCode;
if (code === 200 || code === 201) {
  node.log('[mig] Table created: ' + msg._tbl);
} else if (code === 409 || code === 422) {
  node.log('[mig] Table exists: ' + msg._tbl + ' (OK)');
} else {
  node.warn('[mig] Table status ' + code + ' for ' + msg._tbl + ': ' + msg.payload);
}
flow.set('mig_tbl_idx', (msg._tidx || 0) + 1);
return msg;
""")

MIG_FN_SEED_RAW = fn(f"""
// [3] Seed RAW: POST /api/v3/write_lp?db=energy_monitoring
const HOST  = flow.get('mig_host');
const TOKEN = flow.get('mig_token');
const machines = {MACHINES_JSON};
const INTERVAL_SEC = 10, LOOKBACK_HOURS = 24, BATCH_SIZE = 500;
const now = Date.now(), startMs = now - (LOOKBACK_HOURS * 3600 * 1000);
const vary  = (base, pct) => base * (1 + (Math.random() - 0.5) * 2 * pct);
const round = (v, d)      => Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
let lines = [], batches = [];
const flush = () => {{
  if (!lines.length) return;
  batches.push({{ url: HOST + '/api/v3/write_lp?db=energy_monitoring', body: lines.join('\\n') }});
  lines = [];
}};
for (let ts = startMs; ts < now; ts += INTERVAL_SEC * 1000) {{
  const tsNs = (ts * 1000000).toString();
  for (const m of machines) {{
    const power   = round(vary(m.basePower,   0.20), 3);
    const voltage = round(vary(m.baseVoltage, 0.02), 1);
    const current = round(vary(m.baseCurrent, 0.15), 2);
    const pf      = round(0.85 + Math.random() * 0.12, 3);
    const energy  = round(power * INTERVAL_SEC / 3600, 6);
    lines.push('energy_raw,machine_id=' + m.id + ',location=' + m.location +
      ' power_kw=' + power + ',voltage_v=' + voltage + ',current_a=' + current +
      ',energy_kwh=' + energy + ',power_factor=' + pf + ' ' + tsNs);
    if (lines.length >= BATCH_SIZE) flush();
  }}
}}
flush();
flow.set('seed_raw_batches', batches);
flow.set('seed_raw_idx', 0);
node.status({{ fill: 'blue', shape: 'dot', text: 'RAW: ' + batches.length + ' batches' }});
msg.payload = {{ totalBatches: batches.length }};
return msg;
""")

MIG_FN_NEXT_RAW = fn("""
const batches = flow.get('seed_raw_batches') || [];
const idx = flow.get('seed_raw_idx') || 0;
if (idx >= batches.length) {
  node.status({ fill: 'green', shape: 'dot', text: 'RAW done: ' + batches.length });
  return [null, msg];
}
const b = batches[idx];
flow.set('seed_raw_idx', idx + 1);
msg.url     = b.url;
msg.method  = 'POST';
msg.headers = { 'Authorization': 'Bearer ' + flow.get('mig_token'), 'Content-Type': 'text/plain' };
msg.payload = b.body;
node.status({ fill: 'blue', shape: 'ring', text: 'RAW batch ' + (idx+1) + '/' + batches.length });
return [msg, null];
""")

MIG_FN_SEED_MIN = fn(f"""
// [4] Seed MINUTES: POST /api/v3/write_lp?db=energy_minutes
const HOST  = flow.get('mig_host');
const TOKEN = flow.get('mig_token');
const machines = {MACHINES_JSON};
const LOOKBACK_HOURS = 24, BATCH_SIZE = 500;
const now = Date.now(), startMs = now - (LOOKBACK_HOURS * 3600 * 1000);
const vary  = (base, pct) => base * (1 + (Math.random() - 0.5) * 2 * pct);
const round = (v, d)      => Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
let lines = [], batches = [];
const flush = () => {{
  if (!lines.length) return;
  batches.push({{ url: HOST + '/api/v3/write_lp?db=energy_minutes', body: lines.join('\\n') }});
  lines = [];
}};
for (let ts = startMs; ts < now; ts += 60 * 1000) {{
  const tsNs = (Math.floor(ts / 60000) * 60000 * 1000000).toString();
  for (const m of machines) {{
    const avgPow = round(vary(m.basePower,   0.15), 3);
    const sumE   = round(avgPow * 60 / 3600, 6);
    const avgV   = round(vary(m.baseVoltage, 0.02), 1);
    const avgA   = round(avgPow * 1000 / avgV, 2);
    const avgPF  = round(0.87 + Math.random() * 0.10, 3);
    const minPow = round(avgPow * 0.85, 3);
    const maxPow = round(avgPow * 1.18, 3);
    lines.push('energy_minute,machine_id=' + m.id + ',location=' + m.location +
      ' avg_power_kw=' + avgPow + ',sum_energy_kwh=' + sumE +
      ',avg_voltage_v=' + avgV + ',avg_current_a=' + avgA +
      ',avg_power_factor=' + avgPF + ',min_power_kw=' + minPow +
      ',max_power_kw=' + maxPow + ',sample_count=6i' + ' ' + tsNs);
    if (lines.length >= BATCH_SIZE) flush();
  }}
}}
flush();
flow.set('seed_min_batches', batches);
flow.set('seed_min_idx', 0);
node.status({{ fill: 'blue', shape: 'dot', text: 'MINUTES: ' + batches.length + ' batches' }});
msg.payload = {{ totalBatches: batches.length }};
return msg;
""")

MIG_FN_NEXT_MIN = fn("""
const batches = flow.get('seed_min_batches') || [];
const idx = flow.get('seed_min_idx') || 0;
if (idx >= batches.length) {
  node.status({ fill: 'green', shape: 'dot', text: 'MINUTES done: ' + batches.length });
  return [null, msg];
}
const b = batches[idx];
flow.set('seed_min_idx', idx + 1);
msg.url     = b.url;
msg.method  = 'POST';
msg.headers = { 'Authorization': 'Bearer ' + flow.get('mig_token'), 'Content-Type': 'text/plain' };
msg.payload = b.body;
node.status({ fill: 'blue', shape: 'ring', text: 'MIN batch ' + (idx+1) + '/' + batches.length });
return [msg, null];
""")

MIG_FN_SEED_HOURLY = fn(f"""
// [5] Seed HOURLY: POST /api/v3/write_lp?db=energy_hour
const HOST  = flow.get('mig_host');
const TOKEN = flow.get('mig_token');
const machines = {MACHINES_JSON};
const LOOKBACK_HOURS = 24;
const now = Date.now(), startMs = now - (LOOKBACK_HOURS * 3600 * 1000);
const vary  = (base, pct) => base * (1 + (Math.random() - 0.5) * 2 * pct);
const round = (v, d)      => Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
let lines = [];
for (let ts = startMs; ts < now; ts += 3600 * 1000) {{
  const tsNs = (Math.floor(ts / 3600000) * 3600000 * 1000000).toString();
  for (const m of machines) {{
    const avgPow = round(vary(m.basePower,   0.12), 3);
    const sumE   = round(avgPow * 1, 4);
    const avgV   = round(vary(m.baseVoltage, 0.02), 1);
    const avgA   = round(avgPow * 1000 / avgV, 2);
    const avgPF  = round(0.88 + Math.random() * 0.09, 3);
    const minPow = round(avgPow * 0.80, 3);
    const maxPow = round(avgPow * 1.20, 3);
    lines.push('energy_hour,machine_id=' + m.id + ',location=' + m.location +
      ' avg_power_kw=' + avgPow + ',sum_energy_kwh=' + sumE +
      ',avg_voltage_v=' + avgV + ',avg_current_a=' + avgA +
      ',avg_power_factor=' + avgPF + ',min_power_kw=' + minPow +
      ',max_power_kw=' + maxPow + ',sample_count=360i' + ' ' + tsNs);
  }}
}}
msg.url     = HOST + '/api/v3/write_lp?db=energy_hour';
msg.method  = 'POST';
msg.headers = {{ 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'text/plain' }};
msg.payload = lines.join('\\n');
node.status({{ fill: 'blue', shape: 'dot', text: 'Writing ' + lines.length + ' HOURLY...' }});
return msg;
""")

MIG_FN_DONE = fn("""
const ok = msg.statusCode === 200 || msg.statusCode === 204;
node.status({ fill: 'green', shape: 'dot', text: ok ? 'All seeding done!' : 'Done (status ' + msg.statusCode + ')' });
msg.payload = { status: 'done', influx_code: msg.statusCode };
return msg;
""")

SIM_FN_GEN = fn(f"""
// [2] Generate realistic 5-machine telemetry
const machines = {MACHINES_JSON};
const vary  = (base, pct) => base * (1 + (Math.random() - 0.5) * 2 * pct);
const round = (v, d)      => Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
const INTERVAL_SEC = 10;
const now = new Date().toISOString();
msg.payload = machines.map(m => {{
  const power   = round(vary(m.basePower,   0.2),  3);
  const voltage = round(vary(m.baseVoltage, 0.02), 1);
  const current = round(vary(m.baseCurrent, 0.15), 2);
  const pf      = round(0.85 + Math.random() * 0.12, 3);
  const energy  = round(power * INTERVAL_SEC / 3600, 6);
  return {{ machine_id: m.id, location: m.location, timestamp: now,
    power_kw: power, voltage_v: voltage, current_a: current,
    energy_kwh: energy, power_factor: pf }};
}});
node.status({{ fill: 'green', shape: 'dot', text: 'x5 @ ' + now.substring(11,19) }});
return msg;
""")

SIM_FN_TOPIC = fn("""
msg.topic   = 'energy/' + msg.payload.machine_id + '/data';
msg.payload = JSON.stringify(msg.payload);
return msg;
""")

ING_FN_VALIDATE = fn("""
// [3] Validate: drop if missing/NaN field
const d = msg.payload;
const required = ['machine_id','location','power_kw','voltage_v','current_a','energy_kwh','power_factor'];
for (const f of required) {
  if (d[f] === undefined || d[f] === null) {
    node.warn('[ing] Dropped: missing ' + f);
    node.status({ fill: 'red', shape: 'ring', text: 'Missing: ' + f });
    return null;
  }
}
for (const f of ['power_kw','voltage_v','current_a','energy_kwh','power_factor']) {
  const v = parseFloat(d[f]);
  if (isNaN(v)) {
    node.warn('[ing] Dropped: NaN in ' + f);
    node.status({ fill: 'red', shape: 'ring', text: 'NaN: ' + f });
    return null;
  }
  d[f] = v;
}
msg.payload = d;
return msg;
""")

ING_FN_LP = fn(f"""
// [4] Build InfluxDB Line Protocol -> write to energy_monitoring
const d = msg.payload;
const esc = v => String(v).replace(/ /g,'\\\\ ').replace(/,/g,'\\\\,').replace(/=/g,'\\\\=');
let tsMs;
try {{ tsMs = d.timestamp ? new Date(d.timestamp).getTime() : Date.now(); if (isNaN(tsMs)) tsMs = Date.now(); }}
catch(e) {{ tsMs = Date.now(); }}
const tsNs = (tsMs * 1000000).toString();
const line = 'energy_raw,machine_id=' + esc(d.machine_id) + ',location=' + esc(d.location) +
  ' power_kw=' + d.power_kw + ',voltage_v=' + d.voltage_v + ',current_a=' + d.current_a +
  ',energy_kwh=' + d.energy_kwh + ',power_factor=' + d.power_factor + ' ' + tsNs;
msg.url     = '{HOST}/api/v3/write_lp?db=energy_monitoring';
msg.method  = 'POST';
msg.headers = {{ 'Authorization': 'Bearer {TOKEN}', 'Content-Type': 'text/plain' }};
msg.payload = line;
return msg;
""")

ING_FN_CHECK = fn("""
if (msg.statusCode === 200 || msg.statusCode === 204) {
  node.status({ fill: 'green', shape: 'dot', text: 'OK @ ' + new Date().toISOString().substring(11,19) });
} else {
  node.status({ fill: 'red', shape: 'ring', text: 'Error ' + msg.statusCode });
  node.warn('[ing] Write failed (' + msg.statusCode + '): ' + msg.payload);
}
return msg;
""")

DASH_FN_RT = fn(f"""
// [2] Query realtime: last 60s, all machines
const TOKEN = '{TOKEN}', HOST = '{HOST}';
flow.set('dash_req', msg.req);
flow.set('dash_res', msg.res);
flow.set('dash_results', {{}});
const sql = `SELECT machine_id, location,
  LAST(power_kw) AS power_kw, LAST(voltage_v) AS voltage_v,
  LAST(current_a) AS current_a, LAST(power_factor) AS power_factor, MAX(time) AS last_seen
FROM energy_raw
WHERE time >= NOW() - INTERVAL '60 seconds'
GROUP BY machine_id, location ORDER BY machine_id ASC`;
msg.url     = HOST + '/api/v3/query';
msg.method  = 'POST';
msg.headers = {{ 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' }};
msg.payload = JSON.stringify({{ query: sql, database: 'energy_monitoring', format: 'json' }});
return msg;
""")

DASH_FN_PARSE_RT = fn("""
try {
  const rows = Array.isArray(msg.payload) ? msg.payload : [];
  const machines = rows.map(r => ({
    machine_id: r.machine_id, location: r.location,
    power_kw: parseFloat(r.power_kw)||0, voltage_v: parseFloat(r.voltage_v)||0,
    current_a: parseFloat(r.current_a)||0, power_factor: parseFloat(r.power_factor)||0,
    last_seen: r.last_seen
  }));
  const results = flow.get('dash_results') || {};
  results.realtime = {
    total_power_kw: Math.round(machines.reduce((s,m)=>s+m.power_kw,0)*100)/100,
    machines
  };
  flow.set('dash_results', results);
} catch(e) { node.warn('[dash] realtime: ' + e.message); }
return msg;
""")

DASH_FN_HOURLY = fn(f"""
// [3] Query hourly trend from energy_hour
const TOKEN = '{TOKEN}', HOST = '{HOST}';
const sql = `SELECT DATE_BIN(INTERVAL '1 hour', time, TIMESTAMP '1970-01-01') AS hour_bucket,
  machine_id, SUM(sum_energy_kwh) AS energy_kwh
FROM energy_hour
WHERE time >= DATE_TRUNC('day', NOW()) AND time < DATE_TRUNC('day', NOW()) + INTERVAL '1 day'
GROUP BY hour_bucket, machine_id ORDER BY hour_bucket ASC, machine_id ASC`;
msg.url     = HOST + '/api/v3/query';
msg.method  = 'POST';
msg.headers = {{ 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' }};
msg.payload = JSON.stringify({{ query: sql, database: 'energy_hour', format: 'json' }});
return msg;
""")

DASH_FN_PARSE_HOURLY = fn("""
try {
  const rows = Array.isArray(msg.payload) ? msg.payload : [];
  const machineMap = {}, hourSet = new Set();
  rows.forEach(r => {
    const h = new Date(r.hour_bucket).getUTCHours();
    const label = String(h).padStart(2,'0') + ':00';
    hourSet.add(label);
    if (!machineMap[r.machine_id]) machineMap[r.machine_id] = {};
    machineMap[r.machine_id][label] = Math.round(parseFloat(r.energy_kwh)*1000)/1000;
  });
  const labels = Array.from(hourSet).sort();
  const datasets = Object.entries(machineMap).map(([m,d]) => ({ label:m, data:labels.map(h=>d[h]||0) }));
  const results = flow.get('dash_results') || {};
  results.line_chart = { title: 'Konsumsi Energi Per Jam', labels, datasets };
  flow.set('dash_results', results);
} catch(e) { node.warn('[dash] hourly: ' + e.message); }
return msg;
""")

DASH_FN_PIE = fn(f"""
// [4] Query pie chart: total kWh per machine from energy_minutes
const TOKEN = '{TOKEN}', HOST = '{HOST}';
const sql = `SELECT machine_id, SUM(sum_energy_kwh) AS total_kwh
FROM energy_minute
WHERE time >= DATE_TRUNC('day', NOW()) AND time < NOW()
GROUP BY machine_id ORDER BY total_kwh DESC`;
msg.url     = HOST + '/api/v3/query';
msg.method  = 'POST';
msg.headers = {{ 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' }};
msg.payload = JSON.stringify({{ query: sql, database: 'energy_minutes', format: 'json' }});
return msg;
""")

DASH_FN_PARSE_PIE = fn("""
try {
  const rows = Array.isArray(msg.payload) ? msg.payload : [];
  const results = flow.get('dash_results') || {};
  results.pie_chart = {
    title: 'Distribusi Konsumsi Per Mesin — Hari Ini',
    labels: rows.map(r=>r.machine_id),
    values: rows.map(r=>Math.round(parseFloat(r.total_kwh)*1000)/1000),
    unit: 'kWh'
  };
  flow.set('dash_results', results);
} catch(e) { node.warn('[dash] pie: ' + e.message); }
return msg;
""")

DASH_FN_MERGE = fn("""
// [5] Merge results and return JSON API response
const results = flow.get('dash_results') || {};
msg.payload = {
  generated_at: new Date().toISOString(),
  realtime:   results.realtime   || { total_power_kw: 0, machines: [] },
  line_chart: results.line_chart || { title: '', labels: [], datasets: [] },
  pie_chart:  results.pie_chart  || { title: '', labels: [], values: [], unit: 'kWh' }
};
msg.req = flow.get('dash_req');
msg.res = flow.get('dash_res');
msg.statusCode = 200;
msg.headers = { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' };
node.status({ fill: 'green', shape: 'dot', text: 'Served @ ' + new Date().toISOString().substring(11,19) });
return msg;
""")

DASH_FN_ERR = fn("""
node.warn('[dash] Error: ' + msg.error.message);
msg.statusCode = 500;
msg.payload = JSON.stringify({ error: msg.error.message });
msg.headers = { 'Content-Type': 'application/json' };
return msg;
""")

# ── Build flow array ─────────────────────────────────────────────────────────

flows = [
    # Tabs
    {"id":"tab-migration","type":"tab","label":"Migration / Seeders","disabled":False,
     "info":"Tab 1: Create DBs + Tables + Seed historical data. Runs once on startup."},
    {"id":"tab-simulator","type":"tab","label":"Simulator","disabled":False,
     "info":"Tab 2: Generate 5-machine telemetry every 10s, publish to EMQX MQTT."},
    {"id":"tab-ingestion","type":"tab","label":"Ingestion","disabled":False,
     "info":"Tab 3: Subscribe MQTT energy/+/data -> validate -> write RAW to InfluxDB."},
    {"id":"tab-dashboard","type":"tab","label":"Dashboard Output","disabled":False,
     "info":"Tab 4: Query 3 DBs -> JSON API at GET /api/dashboard/energy"},

    # MQTT Broker config node
    {"id":"cfg-emqx","type":"mqtt-broker","name":"EMQX Broker","broker":"emqx","port":"1883",
     "clientid":"nodered-energy","autoConnect":True,"usetls":False,"protocolVersion":"5",
     "keepalive":"60","cleansession":True,"autoUnsubscribe":True,
     "birthTopic":"","birthQos":"0","birthPayload":"",
     "closeTopic":"","closeQos":"0","closePayload":"",
     "willTopic":"","willQos":"0","willPayload":""},

    # ── TAB 1: MIGRATION / SEEDERS ────────────────────────────────────────

    {"id":"mig-trigger","type":"inject","z":"tab-migration",
     "name":"Startup / Manual Trigger",
     "props":[{"p":"payload"}],"repeat":"","crontab":"","once":True,"onceDelay":1.5,
     "topic":"","payload":"start","payloadType":"str","x":160,"y":80,
     "wires":[["mig-fn-init"]]},

    {"id":"mig-cmt-1","type":"comment","z":"tab-migration",
     "name":"[1] POST /api/v3/configure/database — Create 3 databases","info":"","x":500,"y":80,"wires":[]},
    {"id":"mig-fn-init","type":"function","z":"tab-migration",
     "name":"[1] Init Migration","func":MIG_FN_INIT,"outputs":1,"x":500,"y":120,
     "wires":[["mig-fn-next-db"]]},
    {"id":"mig-fn-next-db","type":"function","z":"tab-migration",
     "name":"[1] Next DB","func":MIG_FN_NEXT_DB,"outputs":2,"x":740,"y":120,
     "wires":[["mig-http-db"],["mig-fn-next-tbl"]]},
    {"id":"mig-http-db","type":"http request","z":"tab-migration",
     "name":"[1] POST /api/v3/configure/database","method":"use","ret":"txt","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":1000,"y":120,"wires":[["mig-fn-db-result"]]},
    {"id":"mig-fn-db-result","type":"function","z":"tab-migration",
     "name":"[1] Advance DB Index","func":MIG_FN_DB_RESULT,"outputs":1,"x":1000,"y":180,
     "wires":[["mig-fn-next-db"]]},

    {"id":"mig-cmt-2","type":"comment","z":"tab-migration",
     "name":"[2] POST /api/v3/configure/table — Create 3 tables with tags","info":"","x":740,"y":240,"wires":[]},
    {"id":"mig-fn-next-tbl","type":"function","z":"tab-migration",
     "name":"[2] Next Table","func":MIG_FN_NEXT_TBL,"outputs":2,"x":740,"y":280,
     "wires":[["mig-http-tbl"],["mig-fn-seed-raw"]]},
    {"id":"mig-http-tbl","type":"http request","z":"tab-migration",
     "name":"[2] POST /api/v3/configure/table","method":"use","ret":"txt","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":1000,"y":280,"wires":[["mig-fn-tbl-result"]]},
    {"id":"mig-fn-tbl-result","type":"function","z":"tab-migration",
     "name":"[2] Advance Table Index","func":MIG_FN_TBL_RESULT,"outputs":1,"x":1000,"y":340,
     "wires":[["mig-fn-next-tbl"]]},

    {"id":"mig-cmt-3","type":"comment","z":"tab-migration",
     "name":"[3] POST /api/v3/write_lp?db=energy_monitoring — Seed RAW 24h","info":"","x":500,"y":420,"wires":[]},
    {"id":"mig-fn-seed-raw","type":"function","z":"tab-migration",
     "name":"[3] Generate RAW Seed (24h × 5 mesin × 10s)","func":MIG_FN_SEED_RAW,"outputs":1,"x":500,"y":460,
     "wires":[["mig-fn-next-raw"]]},
    {"id":"mig-fn-next-raw","type":"function","z":"tab-migration",
     "name":"[3] Next RAW Batch","func":MIG_FN_NEXT_RAW,"outputs":2,"x":740,"y":460,
     "wires":[["mig-http-raw"],["mig-fn-seed-min"]]},
    {"id":"mig-http-raw","type":"http request","z":"tab-migration",
     "name":"[3] POST /api/v3/write_lp RAW","method":"use","ret":"txt","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":1000,"y":460,"wires":[["mig-fn-after-raw"]]},
    {"id":"mig-fn-after-raw","type":"function","z":"tab-migration",
     "name":"[3] Advance RAW Index",
     "func":"if(msg.statusCode!==200&&msg.statusCode!==204){node.warn('[seed-raw] '+msg.statusCode+': '+msg.payload);} return msg;",
     "outputs":1,"x":1000,"y":520,"wires":[["mig-fn-next-raw"]]},

    {"id":"mig-cmt-4","type":"comment","z":"tab-migration",
     "name":"[4] POST /api/v3/write_lp?db=energy_minutes — Seed MINUTES 24h","info":"","x":500,"y":600,"wires":[]},
    {"id":"mig-fn-seed-min","type":"function","z":"tab-migration",
     "name":"[4] Generate MINUTES Seed (24h × 5 mesin × 1m)","func":MIG_FN_SEED_MIN,"outputs":1,"x":500,"y":640,
     "wires":[["mig-fn-next-min"]]},
    {"id":"mig-fn-next-min","type":"function","z":"tab-migration",
     "name":"[4] Next MINUTES Batch","func":MIG_FN_NEXT_MIN,"outputs":2,"x":740,"y":640,
     "wires":[["mig-http-min"],["mig-fn-seed-hourly"]]},
    {"id":"mig-http-min","type":"http request","z":"tab-migration",
     "name":"[4] POST /api/v3/write_lp MINUTES","method":"use","ret":"txt","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":1000,"y":640,"wires":[["mig-fn-after-min"]]},
    {"id":"mig-fn-after-min","type":"function","z":"tab-migration",
     "name":"[4] Advance MINUTES Index",
     "func":"if(msg.statusCode!==200&&msg.statusCode!==204){node.warn('[seed-min] '+msg.statusCode+': '+msg.payload);} return msg;",
     "outputs":1,"x":1000,"y":700,"wires":[["mig-fn-next-min"]]},

    {"id":"mig-cmt-5","type":"comment","z":"tab-migration",
     "name":"[5] POST /api/v3/write_lp?db=energy_hour — Seed HOURLY 24h","info":"","x":500,"y":780,"wires":[]},
    {"id":"mig-fn-seed-hourly","type":"function","z":"tab-migration",
     "name":"[5] Generate HOURLY Seed (24h × 5 mesin)","func":MIG_FN_SEED_HOURLY,"outputs":1,"x":500,"y":820,
     "wires":[["mig-http-hourly"]]},
    {"id":"mig-http-hourly","type":"http request","z":"tab-migration",
     "name":"[5] POST /api/v3/write_lp HOURLY","method":"use","ret":"txt","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":760,"y":820,"wires":[["mig-fn-done"]]},
    {"id":"mig-fn-done","type":"function","z":"tab-migration",
     "name":"[5] Migration Complete","func":MIG_FN_DONE,"outputs":1,"x":1000,"y":820,
     "wires":[["mig-debug"]]},
    {"id":"mig-debug","type":"debug","z":"tab-migration",
     "name":"Seeder Status","active":True,"tosidebar":True,"console":False,
     "tostatus":True,"complete":"payload","targetType":"msg","x":1220,"y":820},
    {"id":"mig-catch","type":"catch","z":"tab-migration",
     "name":"Error Handler","scope":None,"uncaught":False,"x":160,"y":940,"wires":[["mig-debug-err"]]},
    {"id":"mig-debug-err","type":"debug","z":"tab-migration",
     "name":"Error Log","active":True,"tosidebar":True,"tostatus":False,
     "complete":"true","targetType":"full","x":400,"y":940},

    # ── TAB 2: SIMULATOR ──────────────────────────────────────────────────

    {"id":"sim-trigger","type":"inject","z":"tab-simulator",
     "name":"[1] Interval 10s — Auto Start",
     "props":[{"p":"payload"}],"repeat":"10","crontab":"","once":True,"onceDelay":2,
     "topic":"","payload":"tick","payloadType":"str","x":180,"y":100,
     "wires":[["sim-fn-gen"]]},
    {"id":"sim-cmt-1","type":"comment","z":"tab-simulator",
     "name":"[1] Trigger setiap 10s — auto start saat deploy","info":"","x":420,"y":60,"wires":[]},
    {"id":"sim-fn-gen","type":"function","z":"tab-simulator",
     "name":"[2] Generate 5 Machine Telemetry","func":SIM_FN_GEN,
     "outputs":1,"x":420,"y":100,"wires":[["sim-split"]]},
    {"id":"sim-cmt-2","type":"comment","z":"tab-simulator",
     "name":"[2] Generate: 5 mesin, variasi acak ±20%","info":"","x":660,"y":60,"wires":[]},
    {"id":"sim-split","type":"split","z":"tab-simulator",
     "name":"Split Array -> 5 Messages","splt":"\n","spltType":"str",
     "arraySplt":1,"arraySpltType":"len","stream":False,"addname":"",
     "x":660,"y":100,"wires":[["sim-fn-topic"]]},
    {"id":"sim-fn-topic","type":"function","z":"tab-simulator",
     "name":"[3] Set MQTT Topic per Machine","func":SIM_FN_TOPIC,
     "outputs":1,"x":880,"y":100,"wires":[["sim-mqtt-out"]]},
    {"id":"sim-cmt-3","type":"comment","z":"tab-simulator",
     "name":"[3] Publish: energy/{machine_id}/data ke EMQX","info":"","x":1100,"y":60,"wires":[]},
    {"id":"sim-mqtt-out","type":"mqtt out","z":"tab-simulator",
     "name":"[3] Publish ke EMQX","topic":"","qos":"0","retain":"false",
     "respTopic":"","contentType":"","userProps":"","correl":"","expiry":"",
     "broker":"cfg-emqx","x":1100,"y":100},

    # ── TAB 3: INGESTION ──────────────────────────────────────────────────

    {"id":"ing-mqtt-in","type":"mqtt in","z":"tab-ingestion",
     "name":"[1] Subscribe energy/+/data","topic":"energy/+/data","qos":"0",
     "datatype":"auto","broker":"cfg-emqx","nl":False,"rap":True,"rh":0,
     "inputs":0,"x":180,"y":100,"wires":[["ing-json"]]},
    {"id":"ing-cmt-1","type":"comment","z":"tab-ingestion",
     "name":"[1] Subscribe: energy/+/data — wildcard + = machine_id","info":"","x":440,"y":60,"wires":[]},
    {"id":"ing-json","type":"json","z":"tab-ingestion",
     "name":"[2] Parse JSON","property":"payload","action":"obj","pretty":False,
     "x":440,"y":100,"wires":[["ing-fn-validate"]]},
    {"id":"ing-cmt-2","type":"comment","z":"tab-ingestion",
     "name":"[2] Parse JSON string -> object","info":"","x":660,"y":60,"wires":[]},
    {"id":"ing-fn-validate","type":"function","z":"tab-ingestion",
     "name":"[3] Validate & Sanitize","func":ING_FN_VALIDATE,
     "outputs":1,"x":660,"y":100,"wires":[["ing-fn-lp"]]},
    {"id":"ing-cmt-3","type":"comment","z":"tab-ingestion",
     "name":"[3] Validate: semua field wajib + numerik","info":"","x":880,"y":60,"wires":[]},
    {"id":"ing-fn-lp","type":"function","z":"tab-ingestion",
     "name":"[4] Build Line Protocol","func":ING_FN_LP,
     "outputs":1,"x":880,"y":100,"wires":[["ing-http"]]},
    {"id":"ing-cmt-4","type":"comment","z":"tab-ingestion",
     "name":"[4-5] POST /api/v3/write_lp?db=energy_monitoring","info":"","x":1100,"y":60,"wires":[]},
    {"id":"ing-http","type":"http request","z":"tab-ingestion",
     "name":"[5] POST /api/v3/write_lp","method":"use","ret":"txt","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":1100,"y":100,"wires":[["ing-fn-check"]]},
    {"id":"ing-fn-check","type":"function","z":"tab-ingestion",
     "name":"[5] Check Status","func":ING_FN_CHECK,
     "outputs":1,"x":1100,"y":160,"wires":[]},
    {"id":"ing-catch","type":"catch","z":"tab-ingestion",
     "name":"Error Handler","scope":None,"uncaught":False,"x":180,"y":280,"wires":[["ing-debug-err"]]},
    {"id":"ing-debug-err","type":"debug","z":"tab-ingestion",
     "name":"Error Log","active":True,"tosidebar":True,"tostatus":False,
     "complete":"true","targetType":"full","x":400,"y":280},

    # ── TAB 4: DASHBOARD OUTPUT ───────────────────────────────────────────

    {"id":"dash-http-in","type":"http in","z":"tab-dashboard",
     "name":"[1] GET /api/dashboard/energy","url":"/api/dashboard/energy",
     "method":"get","upload":False,"swaggerDoc":"","x":200,"y":100,"wires":[["dash-fn-rt"]]},
    {"id":"dash-cmt-1","type":"comment","z":"tab-dashboard",
     "name":"[1] GET /api/dashboard/energy | Test: curl http://localhost:1880/api/dashboard/energy","info":"","x":460,"y":60,"wires":[]},
    {"id":"dash-fn-rt","type":"function","z":"tab-dashboard",
     "name":"[2] Query Realtime (RAW DB)","func":DASH_FN_RT,
     "outputs":1,"x":460,"y":100,"wires":[["dash-http-rt"]]},
    {"id":"dash-http-rt","type":"http request","z":"tab-dashboard",
     "name":"[2] POST /api/v3/query RAW","method":"use","ret":"obj","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":720,"y":100,"wires":[["dash-fn-parse-rt"]]},
    {"id":"dash-fn-parse-rt","type":"function","z":"tab-dashboard",
     "name":"[2] Format Realtime","func":DASH_FN_PARSE_RT,
     "outputs":1,"x":960,"y":100,"wires":[["dash-fn-hourly"]]},
    {"id":"dash-fn-hourly","type":"function","z":"tab-dashboard",
     "name":"[3] Query Hourly Trend (HOURLY DB)","func":DASH_FN_HOURLY,
     "outputs":1,"x":460,"y":200,"wires":[["dash-http-hourly"]]},
    {"id":"dash-http-hourly","type":"http request","z":"tab-dashboard",
     "name":"[3] POST /api/v3/query HOURLY","method":"use","ret":"obj","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":720,"y":200,"wires":[["dash-fn-parse-hourly"]]},
    {"id":"dash-fn-parse-hourly","type":"function","z":"tab-dashboard",
     "name":"[3] Format Line Chart","func":DASH_FN_PARSE_HOURLY,
     "outputs":1,"x":960,"y":200,"wires":[["dash-fn-pie"]]},
    {"id":"dash-fn-pie","type":"function","z":"tab-dashboard",
     "name":"[4] Query Pie Chart (MINUTES DB)","func":DASH_FN_PIE,
     "outputs":1,"x":460,"y":300,"wires":[["dash-http-pie"]]},
    {"id":"dash-http-pie","type":"http request","z":"tab-dashboard",
     "name":"[4] POST /api/v3/query MINUTES","method":"use","ret":"obj","paytoqs":"ignore",
     "url":"","tls":"","persist":False,"x":720,"y":300,"wires":[["dash-fn-parse-pie"]]},
    {"id":"dash-fn-parse-pie","type":"function","z":"tab-dashboard",
     "name":"[4] Format Pie Chart","func":DASH_FN_PARSE_PIE,
     "outputs":1,"x":960,"y":300,"wires":[["dash-fn-merge"]]},
    {"id":"dash-fn-merge","type":"function","z":"tab-dashboard",
     "name":"[5] Merge All -> JSON Response","func":DASH_FN_MERGE,
     "outputs":1,"x":460,"y":420,"wires":[["dash-http-response"]]},
    {"id":"dash-http-response","type":"http response","z":"tab-dashboard",
     "name":"[5] JSON API Response","statusCode":"","headers":{},"x":720,"y":420},
    {"id":"dash-catch","type":"catch","z":"tab-dashboard",
     "name":"Error Handler","scope":None,"uncaught":False,"x":200,"y":520,"wires":[["dash-fn-err"]]},
    {"id":"dash-fn-err","type":"function","z":"tab-dashboard",
     "name":"Error -> 500 Response","func":DASH_FN_ERR,
     "outputs":1,"x":460,"y":520,"wires":[["dash-http-response"]]},
]

out_path = os.path.join(os.path.dirname(__file__), "../../nodered/flows.json")
out_path = os.path.normpath(out_path)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(flows, f, indent=2, ensure_ascii=False)

print(f"Generated {len(flows)} nodes -> {out_path}")
