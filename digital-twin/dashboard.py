#!/usr/bin/env python3
"""Live web dashboard for the Raspberry Pi digital twin.

Serves a small web page on http://localhost:8000 that shows the live CPU
temperature, LED state and alarm threshold -- and lets you control the LED,
the mode and the threshold from the browser. It talks to the same MQTT broker
as the Qt app and the Blender twin, so all three stay in sync.

Run on the Mac (where the broker runs):
    python3 dashboard.py
Then open http://localhost:8000

Options (environment variables):
    MQTT_BROKER     broker host       (default: localhost)
    MQTT_PORT       broker port       (default: 1883)
    DASHBOARD_PORT  web server port   (default: 8000)
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
HTTP_PORT = int(os.environ.get("DASHBOARD_PORT", "8000"))

HISTORY_LEN = 600  # keep ~10 minutes of samples (one per second)

_lock = threading.Lock()
_state = {"temperature": None, "led": None, "threshold": None}
_history = []  # list of [unix_seconds, temperature]
_connected = False
_client = None

# what the browser is allowed to publish
_COMMANDS = {
    "led": "machine/command/led",
    "mode": "machine/command/mode",
    "threshold": "machine/command/threshold",
}


def _on_connect(client, _userdata, _flags, _reason_code, _props=None):
    global _connected
    _connected = True
    client.subscribe("machine/#")


def _on_disconnect(*_args):
    global _connected
    _connected = False


def _on_message(_client, _userdata, msg):
    payload = msg.payload.decode("utf-8", "replace").strip()
    with _lock:
        try:
            if msg.topic == "machine/temperature":
                value = float(payload)
                _state["temperature"] = value
                _history.append([time.time(), value])
                del _history[:-HISTORY_LEN]
            elif msg.topic == "machine/led":
                _state["led"] = 1 if payload.lower() in ("1", "true", "on") else 0
            elif msg.topic == "machine/threshold":
                _state["threshold"] = float(payload)
        except ValueError:
            pass


def _publish(target, value):
    topic = _COMMANDS.get(target)
    if topic is None:
        return False, "unknown target %r" % (target,)
    if _client is None:
        return False, "not connected to the broker"
    if target == "led":
        text = "1" if str(value).lower() in ("1", "true", "on") else "0"
    else:
        text = str(value)
    _client.publish(topic, text)
    return True, text


def _snapshot():
    with _lock:
        history = list(_history)
        state = dict(_state)
        connected = _connected
    recent = [v for _, v in history][-60:]
    stats = {
        "count": len(recent),
        "min": min(recent) if recent else None,
        "max": max(recent) if recent else None,
        "avg": (sum(recent) / len(recent)) if recent else None,
    }
    return {
        "connected": connected,
        "state": state,
        "stats": stats,
        "history": [{"t": t, "v": v} for t, v in history[-180:]],
    }


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raspberry Pi Twin - Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, system-ui, sans-serif;
         background: #0f1216; color: #e6e9ee; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 24px; }
  header { display: flex; align-items: center; justify-content: space-between;
           margin-bottom: 18px; }
  h1 { font-size: 17px; font-weight: 600; color: #9fb0c0; margin: 0; }
  .status { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #7f8c9b; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #7f3540; }
  .dot.on { background: #3ba55d; box-shadow: 0 0 8px #3ba55d; }
  .cards { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .card { flex: 1 1 220px; background: #171c22; border: 1px solid #232a33;
          border-radius: 12px; padding: 16px; }
  .label { font-size: 12px; color: #7f8c9b; text-transform: uppercase;
           letter-spacing: .05em; }
  .value { font-size: 32px; font-weight: 700; margin: 6px 0 10px; color: #55606c; }
  #temp.value { color: #e6e9ee; }
  #led.on { color: #3ba55d; }
  .row { display: flex; gap: 8px; align-items: center; }
  .btn { flex: 1; background: #222a33; color: #cdd6e0; border: 1px solid #2e3843;
         border-radius: 8px; padding: 8px 10px; font-size: 13px; cursor: pointer; }
  .btn:hover { background: #2b3540; }
  .btn.active { background: #1f6f3d; border-color: #3ba55d; color: #fff; }
  input[type=range] { width: 100%; margin: 4px 0 10px; accent-color: #3ba55d; }
  .muted { font-size: 12px; color: #7f8c9b; }
  canvas { background: #171c22; border: 1px solid #232a33;
           border-radius: 12px; padding: 8px; }
  .stats { display: flex; gap: 18px; margin: 14px 2px 8px; font-size: 13px; color: #7f8c9b; }
  .stats b { color: #cdd6e0; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Raspberry Pi Twin &mdash; live dashboard</h1>
    <div class="status"><span class="dot" id="dot"></span><span id="conn">connecting...</span></div>
  </header>

  <div class="cards">
    <div class="card">
      <div class="label">Temperature</div>
      <div class="value" id="temp">--</div>
      <div class="muted">CPU core temperature, one sample per second</div>
    </div>

    <div class="card">
      <div class="label">LED</div>
      <div class="value" id="led">--</div>
      <div class="row">
        <button class="btn" id="btnOn"  onclick="send('led','1')">On</button>
        <button class="btn" id="btnOff" onclick="send('led','0')">Off</button>
      </div>
    </div>

    <div class="card">
      <div class="label">Alarm threshold</div>
      <div class="value" id="thr">--</div>
      <input id="range" type="range" min="30" max="90" step="1" value="70"
             oninput="document.getElementById('rval').textContent = this.value + ' \\u00b0C';">
      <div class="row">
        <span class="muted" id="rval">70 \\u00b0C</span>
        <button class="btn" onclick="send('threshold', document.getElementById('range').value)">Set</button>
      </div>
    </div>

    <div class="card">
      <div class="label">Mode</div>
      <div class="value" id="mode">--</div>
      <div class="row">
        <button class="btn" id="btnManual" onclick="send('mode','manual')">Manual</button>
        <button class="btn" id="btnAuto"   onclick="send('mode','auto')">Auto</button>
      </div>
    </div>
  </div>

  <div class="stats">
    <span>last 60 s &mdash; min <b id="smin">--</b></span>
    <span>max <b id="smax">--</b></span>
    <span>avg <b id="savg">--</b></span>
    <span>samples <b id="scount">0</b></span>
  </div>
  <canvas id="chart" height="120"></canvas>
</div>

<script>
// The chart library comes from a CDN. If there is no internet the cards still
// work -- we just skip the graph.
let chart = null;
try {
  if (typeof Chart !== 'undefined') {
    chart = new Chart(document.getElementById('chart'), {
      type: 'line',
      data: { labels: [], datasets: [{
        label: 'CPU temperature (\\u00b0C)',
        data: [],
        borderColor: '#3ba55d',
        backgroundColor: 'rgba(59,165,93,.15)',
        fill: true, tension: .35, pointRadius: 0, borderWidth: 2
      }] },
      options: {
        animation: false,
        responsive: true,
        interaction: { intersect: false, mode: 'index' },
        scales: {
          x: { ticks: { color: '#7f8c9b', maxTicksLimit: 6, maxRotation: 0 },
               grid: { color: 'rgba(35,42,51,.6)' } },
          y: { ticks: { color: '#7f8c9b', callback: v => v + '\\u00b0' },
               grid: { color: 'rgba(35,42,51,.6)' } }
        },
        plugins: { legend: { labels: { color: '#9fb0c0' } } }
      }
    });
  } else {
    document.getElementById('chart').replaceWith('chart needs internet (cdn.jsdelivr.net)');
  }
} catch (e) {}

let lastState = null;

async function send(target, value) {
  try {
    await fetch('/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target, value: value })
    });
    setTimeout(tick, 250);
  } catch (e) {}
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

function fmt(v, unit) {
  return v == null ? '--' : v.toFixed(1) + unit;
}

function setConn(ok) {
  document.getElementById('dot').className = ok ? 'dot on' : 'dot';
  document.getElementById('conn').textContent = ok ? 'broker connected' : 'no broker';
}

function highlight() {
  const s = lastState || {};
  document.getElementById('btnOn').className = 'btn' + (s.led === 1 ? ' active' : '');
  document.getElementById('btnOff').className = 'btn' + (s.led === 0 ? ' active' : '');
}

async function tick() {
  try {
    const res = await fetch('/data');
    const d = await res.json();
    const s = d.state;
    lastState = s;
    setConn(d.connected);
    highlight();

    document.getElementById('temp').textContent = fmt(s.temperature, ' \\u00b0C');
    document.getElementById('thr').textContent = fmt(s.threshold, ' \\u00b0C');

    const led = document.getElementById('led');
    if (s.led === 1) { led.textContent = 'ON'; led.className = 'value on'; }
    else if (s.led === 0) { led.textContent = 'OFF'; led.className = 'value'; }
    else { led.textContent = '--'; led.className = 'value'; }

    if (s.threshold != null) {
      const r = document.getElementById('range');
      if (document.activeElement !== r) r.value = Math.round(s.threshold);
    }

    document.getElementById('smin').textContent = fmt(d.stats.min, ' \\u00b0C');
    document.getElementById('smax').textContent = fmt(d.stats.max, ' \\u00b0C');
    document.getElementById('savg').textContent = fmt(d.stats.avg, ' \\u00b0C');
    document.getElementById('scount').textContent = d.stats.count;

    if (chart) {
      chart.data.labels = d.history.map(h => fmtTime(h.t));
      chart.data.datasets[0].data = d.history.map(h => h.v);
      chart.update();
    }
  } catch (e) {
    setConn(false);
  }
}

setInterval(tick, 1000);
tick();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "PiTwinDashboard/1.0"

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/data":
            self._send(200, json.dumps(_snapshot()).encode(), "application/json")
        else:
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        if urlparse(self.path).path != "/command":
            self._send(404, b'{"ok": false, "detail": "not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        ok, detail = _publish(str(data.get("target", "")), data.get("value"))
        body = json.dumps({"ok": ok, "detail": detail}).encode()
        self._send(200 if ok else 400, body, "application/json")

    def log_message(self, *args):
        pass


def main():
    global _client
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    _client = client

    try:
        client.connect(BROKER, MQTT_PORT, 60)
        client.loop_start()
    except OSError as exc:
        print("Could not reach the MQTT broker at %s:%d (%s)." % (BROKER, MQTT_PORT, exc))
        print("Start it on the Mac with:  brew services start mosquitto")
        return

    httpd = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    print("Dashboard running:  http://localhost:%d" % HTTP_PORT)
    print("Broker: %s:%d   (Ctrl+C to stop)" % (BROKER, MQTT_PORT))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.loop_stop()


if __name__ == "__main__":
    main()
