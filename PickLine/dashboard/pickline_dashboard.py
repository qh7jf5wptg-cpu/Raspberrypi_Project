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


def on_message(_client, _userdata, msg):
    key = msg.topic[9:] if msg.topic.startswith("pickline/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        prev = latest.get(key)
        latest[key] = payload
        if key in ("fill/a/count", "fill/b/count") and prev is not None and prev != payload:
            fill_events.append(time.time())


def sampler():
    while True:
        time.sleep(1.0)
        now = time.time()
        with lock:
            a = float(latest.get("fill/a/level", 0) or 0)
            b = float(latest.get("fill/b/level", 0) or 0)
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
  .stations { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
  @media (max-width:640px){ .stations { grid-template-columns:1fr; } }
  .station { background:var(--card); border-radius:12px; padding:14px; }
  .station h2 { margin:0 0 8px; font-size:14px; }
  .bar { height:18px; background:#0b0f18; border-radius:6px; overflow:hidden; }
  .bar > div { height:100%; background:var(--blue); transition:width .3s; }
  .bar.full > div { background:var(--green); }
  .bar.fault > div { background:var(--red); }
  .chart-wrap { background:var(--card); border-radius:12px; padding:14px; }
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
    <div class="card"><div class="label">Total dispensed</div><div class="value" id="total">0 u</div></div>
    <div class="card"><div class="label">Throughput</div><div class="value" id="tput">0 /min</div></div>
    <div class="card"><div class="label">Placed</div><div class="value" id="placed">0</div></div>
    <div class="card"><div class="label">Entered stations</div><div class="value" id="exited">0</div></div>
  </div>
  <div class="stations">
    <div class="station">
      <h2>Station A <span id="a-state" style="color:var(--muted)"></span></h2>
      <div class="bar" id="a-bar"><div style="width:0%"></div></div>
      <p id="a-info" style="color:var(--muted);font-size:12px"></p>
    </div>
    <div class="station">
      <h2>Station B <span id="b-state" style="color:var(--muted)"></span></h2>
      <div class="bar" id="b-bar"><div style="width:0%"></div></div>
      <p id="b-info" style="color:var(--muted);font-size:12px"></p>
    </div>
  </div>
  <div class="chart-wrap"><canvas id="chart"></canvas></div>
</main>
<script>
const A = [], B = [], L = [];
const chart = new Chart(document.getElementById('chart'), {
  type:'line',
  data:{ labels:L, datasets:[
    { label:'Station A', data:A, borderColor:'#4aa3df', backgroundColor:'#4aa3df22', tension:.3, pointRadius:0, fill:true },
    { label:'Station B', data:B, borderColor:'#f1c40f', backgroundColor:'#f1c40f22', tension:.3, pointRadius:0, fill:true }
  ]},
  options:{ responsive:true, animation:false, scales:{
    x:{ ticks:{ color:'#8fa0b8', maxTicksLimit:8 } },
    y:{ min:0, ticks:{ color:'#8fa0b8' } }
  }, plugins:{ legend:{ labels:{ color:'#e8edf5' } } } }
});

function el(id){ return document.getElementById(id); }
function barState(st){
  el('state').textContent = st || '—';
  el('state').className = 'state ' + (st || 'IDLE');
}

async function poll(){
  try {
    const r = await fetch('/api');
    const d = await r.json();
    const t = d.latest || {};
    barState(t.state);
    el('mode').textContent = 'mode ' + (t.mode || '—') + ' · ' + (t.decision || '—');
    el('alarm').textContent = t.alarm || (t.jam === '1' ? 'BELT JAM' : '');
    el('total').textContent = (parseFloat(t['fill/total']||0)||0).toFixed(0) + ' u';
    el('tput').textContent = (d.fills_per_min||0) + ' /min';
    el('placed').textContent = t.placed || 0;
    el('exited').textContent = t.exited || 0;

    [['a','a'],['b','b']].forEach(([k,p]) => {
      const vol = parseFloat(t.volume||100)||100;
      const lvl = parseFloat(t['fill/'+k+'/level']||0)||0;
      const st = t['fill/'+k+'/state']||'EMPTY';
      const pct = Math.min(100, lvl/vol*100);
      el(p+'-bar').style.width = pct + '%';
      el(p+'-bar').className = 'bar ' + (st==='FULL'?'full':st==='FAULT'?'fault':'');
      el(p+'-state').textContent = st;
      el(p+'-info').textContent = lvl.toFixed(1)+' / '+vol.toFixed(0)+' u · '+(t['fill/'+k+'/count']||0)+' fills · pass '+(t['fill/'+k+'/pass']||0)+'/'+(t['fill/'+k+'/passes']||0)+(t['fill/'+k+'/alarm']?' · '+t['fill/'+k+'/alarm']:'');
    });

    A.length = B.length = L.length = 0;
    (d.history||[]).forEach(([ts,a,b]) => {
      L.push(new Date(ts*1000).toLocaleTimeString());
      A.push(a); B.push(b);
    });
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

    def log_message(self, *_args):
        pass


def main():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, MQTT_PORT, 60)
    client.subscribe("pickline/#")
    client.loop_start()
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
