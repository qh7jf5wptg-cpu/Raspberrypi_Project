#!/usr/bin/env python3
"""Live production dashboard for the PickLine cell.

Serves a web page that shows the two fill stations, throughput, total dispensed
and a live history chart. It subscribes to MQTT and keeps its own short history,
so it works even without the historian running.

Run:
    python3 dashboard/pickline_dashboard.py
    MQTT_BROKER=192.168.50.1 python3 dashboard/pickline_dashboard.py

Open http://localhost:8080
"""
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))

latest = {}
history = deque(maxlen=60)          # (epoch, a_level, b_level)
fill_events = deque()               # timestamps of completed fills
lock = threading.Lock()
mqtt_client = None


def on_message(_client, _userdata, msg):
    key = msg.topic[9:] if msg.topic.startswith("pickline/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        prev = latest.get(key)
        latest[key] = payload
        if key in ("fill/a/count", "fill/b/count") and prev is not None and prev != payload:
            fill_events.append(time.time())


def _pct(key):
    filled = int(float(latest.get("fill/%s/filled" % key, 0) or 0))
    pickups = int(float(latest.get("fill/%s/pickups" % key, 1) or 1))
    return min(100.0, filled / max(pickups, 1) * 100.0)


def sampler():
    while True:
        time.sleep(1.0)
        now = time.time()
        with lock:
            a = _pct("a")
            b = _pct("b")
            history.append((now, a, b))
            while fill_events and fill_events[0] < now - 60:
                fill_events.popleft()


def state():
    with lock:
        return {
            "latest": dict(latest),
            "history": [[ts, a, b] for ts, a, b in history],
            "fills_per_min": len(fill_events),
        }


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PickLine Production Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root { --bg:#0f1420; --card:#1a2233; --ink:#e8edf5; --muted:#8fa0b8;
          --green:#2ecc71; --amber:#f1c40f; --red:#e74c3c; --blue:#4aa3df; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,sans-serif; background:var(--bg); color:var(--ink); }
  header { padding:16px 20px; display:flex; align-items:baseline; gap:16px; flex-wrap:wrap; }
  h1 { font-size:18px; margin:0; }
  .state { padding:4px 10px; border-radius:20px; font-weight:700; font-size:13px; }
  .FAULT { background:var(--red); color:#fff; }
  .WAIT_STATION { background:var(--amber); color:#1a1a1a; }
  .RUNNING, .FILLING { background:var(--blue); color:#fff; }
  .IDLE, .EMPTY { background:#2a3448; color:var(--muted); }
  main { padding:0 20px 24px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-bottom:16px; }
  .card { background:var(--card); border-radius:12px; padding:14px; }
  .card .label { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  .card .value { font-size:26px; font-weight:700; margin-top:4px; }
  input[type=range] { width:100%; accent-color:var(--blue); margin-top:8px; }
  .route-btns { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:8px; }
  .route-btns button { padding:7px; border:1px solid #2a3448; background:#1a2233; color:var(--muted);
                        border-radius:6px; cursor:pointer; font-weight:700; }
  .route-btns button.active { background:var(--blue); color:#fff; border-color:var(--blue); }
  .ctrl-btns { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:8px; }
  .ctrl-btns button { padding:7px; border:1px solid #2a3448; background:#1a2233; color:var(--muted);
                       border-radius:6px; cursor:pointer; font-weight:700; }
  .stations { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
  @media (max-width:640px){ .stations { grid-template-columns:1fr; } }
  .station { background:var(--card); border-radius:12px; padding:14px; }
  .station h2 { margin:0 0 8px; font-size:14px; }
  .bar { height:18px; background:#0b0f18; border-radius:6px; overflow:hidden; }
  .bar > div { height:100%; background:var(--blue); transition:width .3s; }
  .bar.full > div { background:var(--red); }
  .bar.fault > div { background:var(--red); }
  .take-btn { margin-top:10px; width:100%; padding:8px; border:none; border-radius:8px;
              background:#2a3448; color:var(--muted); font-weight:700; cursor:pointer; }
  .take-btn:disabled { opacity:0.45; cursor:default; }
  .take-btn.ready { background:var(--red); color:#fff; animation:blink .6s step-start infinite; }
  @keyframes blink { 50% { opacity:.25; } }
  .chart-wrap { background:var(--card); border-radius:12px; padding:14px; }
  .chart-row { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px; }
  @media (max-width:640px){ .chart-row { grid-template-columns:1fr; } }
  canvas { max-height:300px; }
</style>
</head>
<body>
<header>
  <h1>PickLine Production</h1>
  <span id="state" class="state IDLE">—</span>
  <span id="mode" style="color:var(--muted)"></span>
  <span id="alarm" style="color:var(--red);font-weight:700"></span>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="label">Station A done</div><div class="value" id="a-done">0</div></div>
    <div class="card"><div class="label">Station B done</div><div class="value" id="b-done">0</div></div>
    <div class="card"><div class="label">Total done</div><div class="value" id="total-done">0</div></div>
    <div class="card"><div class="label">Total dispensed</div><div class="value" id="total">0 u</div></div>
  </div>
  <div class="cards">
    <div class="card">
      <div class="label">Gap after exit</div>
      <div class="value" id="gap-val">0.5 s</div>
      <input type="range" id="gap-slider" min="0" max="10" step="0.1" value="0.5">
    </div>
    <div class="card">
      <div class="label">Belt speed</div>
      <div class="value" id="speed-val">90 mm/s</div>
      <input type="range" id="speed-slider" min="20" max="250" step="5" value="90">
    </div>
    <div class="card">
      <div class="label">Route direction</div>
      <div class="value" id="route-val">auto</div>
      <div class="route-btns">
        <button data-route="auto">Auto</button>
        <button data-route="straight">Straight</button>
        <button data-route="left">Left</button>
        <button data-route="alternate">Alt</button>
      </div>
    </div>
    <div class="card">
      <div class="label">Control</div>
      <div class="value" id="mode-val">auto</div>
      <div class="ctrl-btns">
        <button id="btn-start">Start</button>
        <button id="btn-stop">Stop</button>
        <button id="btn-reset">Reset</button>
        <button id="btn-mode">Manual</button>
      </div>
    </div>
  </div>
  <div class="stations">
    <div class="station">
      <h2>Station A <span id="a-state" style="color:var(--muted)"></span></h2>
      <div class="bar" id="a-bar"><div id="a-fill" style="width:0%"></div></div>
      <p id="a-info" style="color:var(--muted);font-size:12px"></p>
      <button id="a-take" class="take-btn" disabled>Take out</button>
    </div>
    <div class="station">
      <h2>Station B <span id="b-state" style="color:var(--muted)"></span></h2>
      <div class="bar" id="b-bar"><div id="b-fill" style="width:0%"></div></div>
      <p id="b-info" style="color:var(--muted);font-size:12px"></p>
      <button id="b-take" class="take-btn" disabled>Take out</button>
    </div>
  </div>
  <div class="chart-row">
    <div class="chart-wrap"><canvas id="chart-a"></canvas></div>
    <div class="chart-wrap"><canvas id="chart-b"></canvas></div>
  </div>
  <div class="chart-wrap"><canvas id="chart"></canvas></div>
</main>
<script>
const LA = [], LB = [], LC = [], DA = [], DB = [], DCA = [], DCB = [];
function lineChart(id, labels, datasets){
  return new Chart(document.getElementById(id), {
    type:'line',
    data:{ labels:labels, datasets:datasets },
    options:{ responsive:true, animation:false,
      scales:{ x:{ ticks:{ color:'#8fa0b8', maxTicksLimit:8 } },
               y:{ min:0, max:100, ticks:{ color:'#8fa0b8' } } },
      plugins:{ legend:{ labels:{ color:'#e8edf5' } } } }
  });
}
const chartA = lineChart('chart-a', LA, [
  { label:'Station A', data:DA, borderColor:'#4aa3df', backgroundColor:'#4aa3df22', tension:.3, pointRadius:0, fill:true }
]);
const chartB = lineChart('chart-b', LB, [
  { label:'Station B', data:DB, borderColor:'#f1c40f', backgroundColor:'#f1c40f22', tension:.3, pointRadius:0, fill:true }
]);
const chart = lineChart('chart', LC, [
  { label:'Station A', data:DCA, borderColor:'#4aa3df', backgroundColor:'#4aa3df22', tension:.3, pointRadius:0, fill:true },
  { label:'Station B', data:DCB, borderColor:'#f1c40f', backgroundColor:'#f1c40f22', tension:.3, pointRadius:0, fill:true }
]);

function el(id){ return document.getElementById(id); }
function barState(st){
  el('state').textContent = st || '—';
  el('state').className = 'state ' + (st || 'IDLE');
}

function send(topic, payload){
  fetch('/set', { method:'POST', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({topic:topic, payload:payload}) }).catch(()=>{});
}
const gapSlider = el('gap-slider');
const speedSlider = el('speed-slider');
gapSlider.addEventListener('change', () => send('pickline/command/gap', gapSlider.value));
speedSlider.addEventListener('change', () => send('pickline/target/speed', speedSlider.value));
el('a-take').addEventListener('click', () => send('pickline/fill/a/take', '1'));
el('b-take').addEventListener('click', () => send('pickline/fill/b/take', '1'));
el('btn-start').addEventListener('click', () => {
  send('pickline/command/mode', 'auto');
  send('pickline/command/start', '1');
});
el('btn-stop').addEventListener('click', () => send('pickline/command/stop', '1'));
el('btn-reset').addEventListener('click', () => send('pickline/command/reset', '1'));
el('btn-mode').addEventListener('click', () => {
  send('pickline/command/mode', el('mode-val').textContent === 'auto' ? 'manual' : 'auto');
});
document.querySelectorAll('.route-btns button').forEach((btn) => {
  btn.addEventListener('click', () => send('pickline/command/route', btn.dataset.route));
});

async function poll(){
  try {
    const r = await fetch('/api');
    const d = await r.json();
    const t = d.latest || {};
    barState(t.state);
    el('mode').textContent = 'mode ' + (t.mode || '—') + ' · ' + (t.decision || '—');
    el('alarm').textContent = t.alarm || (t.jam === '1' ? 'BELT JAM' : '');
    const aCount = parseInt(t['fill/a/count']||0)||0;
    const bCount = parseInt(t['fill/b/count']||0)||0;
    el('a-done').textContent = aCount;
    el('b-done').textContent = bCount;
    el('total-done').textContent = aCount + bCount;
    el('total').textContent = (parseFloat(t['fill/total']||0)||0).toFixed(0) + ' u';

    const gap = parseFloat(t.gap||0.5)||0;
    const speed = parseFloat(t.speed||90)||90;
    el('gap-val').textContent = gap.toFixed(1) + ' s';
    el('speed-val').textContent = speed.toFixed(0) + ' mm/s';
    if (document.activeElement !== gapSlider) gapSlider.value = gap;
    if (document.activeElement !== speedSlider) speedSlider.value = speed;

    const route = t.route_mode || 'auto';
    el('route-val').textContent = route;
    document.querySelectorAll('.route-btns button').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.route === route);
    });

    const mode = t.mode || 'auto';
    el('mode-val').textContent = mode;
    el('btn-mode').textContent = mode === 'auto' ? 'Manual' : 'Auto';

    [['a','a'],['b','b']].forEach(([k,p]) => {
      const filled = parseInt(t['fill/'+k+'/filled']||0)||0;
      const pickups = parseInt(t['fill/'+k+'/pickups']||1)||1;
      const st = t['fill/'+k+'/state']||'EMPTY';
      const pct = Math.min(100, filled/pickups*100);
      el(p+'-fill').style.width = pct + '%';
      el(p+'-bar').className = 'bar ' + (st==='FULL'?'full':st==='FAULT'?'fault':'');
      el(p+'-state').textContent = st;
      el(p+'-info').textContent = filled+' / '+pickups+' containers · '+(t['fill/'+k+'/count']||0)+' done'+(t['fill/'+k+'/alarm']?' · '+t['fill/'+k+'/alarm']:'');
      el(p+'-take').disabled = (st !== 'FULL');
      el(p+'-take').classList.toggle('ready', st === 'FULL');
    });

    LA.length = DA.length = LB.length = DB.length = LC.length = DCA.length = DCB.length = 0;
    (d.history||[]).forEach(([ts,a,b]) => {
      const t = new Date(ts*1000).toLocaleTimeString();
      LA.push(t); DA.push(a);
      LB.push(t); DB.push(b);
      LC.push(t); DCA.push(a); DCB.push(b);
    });
    chartA.update('none');
    chartB.update('none');
    chart.update('none');
  } catch(e) { /* retry next tick */ }
}
setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api":
            body = json.dumps(state()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            topic = data.get("topic", "")
            payload = str(data.get("payload", ""))
            if topic.startswith("pickline/") and mqtt_client:
                mqtt_client.publish(topic, payload)
                code = 200
            else:
                code = 400
        except Exception:
            code = 400
        body = b"{}"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    global mqtt_client
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, MQTT_PORT, 60)
    client.subscribe("pickline/#")
    client.loop_start()
    mqtt_client = client
    print("Dashboard MQTT connected to %s:%d" % (BROKER, MQTT_PORT))

    threading.Thread(target=sampler, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print("Dashboard serving on http://localhost:%d" % HTTP_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        client.loop_stop()


if __name__ == "__main__":
    main()
