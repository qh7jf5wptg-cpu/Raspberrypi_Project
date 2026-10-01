#!/usr/bin/env python3
"""Live web dashboard for the Raspberry Pi digital twin.

Serves a small web page on http://localhost:8000 showing the live CPU
temperature, LED state, mode and alarm threshold -- with a rolling chart, a
control panel, and the current time and 7-day weather forecast for Helsinki.
It talks to the same MQTT broker as the Qt app and the Blender twin, so all
three stay in sync.

Run on the Mac (where the broker runs):
    python3 dashboard.py
Then open http://localhost:8000

Options (environment variables):
    MQTT_BROKER     broker host       (default: localhost)
    MQTT_PORT       broker port       (default: 1883)
    DASHBOARD_PORT  web server port   (default: 8000)
"""
import datetime
import json
import os
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
HTTP_PORT = int(os.environ.get("DASHBOARD_PORT", "8000"))

HISTORY_LEN = 600          # keep ~10 minutes of samples (one per second)
FORECAST_REFRESH = 1800    # re-download the weather every 30 minutes

HELSINKI_LAT = 60.1699
HELSINKI_LON = 24.9384
MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "Jun.",
          "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec."]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_lock = threading.Lock()
_state = {"temperature": None, "led": None, "threshold": None, "mode": None}
_history = []      # list of [unix_seconds, temperature]
_forecast = None
_connected = False
_client = None

# what the browser is allowed to publish
_COMMANDS = {
    "led": "machine/command/led",
    "mode": "machine/command/mode",
    "threshold": "machine/command/threshold",
}


# ---------------------------------------------------------------- MQTT ----

def _on_connect(client, _userdata, _flags, _reason_code, _props=None):
    global _connected
    _connected = True
    client.subscribe("machine/#")


def _on_disconnect(*_args):
    global _connected
    _connected = False


def _on_message(_client, _userdata, msg):
    # Exactly these topics carry state. machine/command/... is what we send.
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
            elif msg.topic == "machine/mode":
                _state["mode"] = payload.lower()
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
    elif target == "mode":
        text = "auto" if str(value).lower().startswith("a") else "manual"
    else:
        text = str(value)
    _client.publish(topic, text)
    return True, text


def _snapshot():
    with _lock:
        history = list(_history)
        state = dict(_state)
        connected = _connected
        forecast = _forecast
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
        "forecast": forecast,
    }


# ------------------------------------------------------------ forecast ----

def _fetch_json(url):
    """Fetch JSON, falling back to an unverified context if the first try fails."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, timeout=10, context=context) as response:
            return json.loads(response.read().decode("utf-8"))


def fetch_forecast():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=%s&longitude=%s"
        "&current=temperature_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code,"
        "precipitation_probability_max"
        "&timezone=Europe%%2FHelsinki&forecast_days=7"
        % (HELSINKI_LAT, HELSINKI_LON)
    )
    try:
        data = _fetch_json(url)
    except Exception as exc:
        print("forecast fetch failed:", repr(exc))
        return None

    daily = data.get("daily", {})
    times = daily.get("time", [])
    codes = daily.get("weather_code", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    rain = daily.get("precipitation_probability_max", [])

    def pick(seq, index):
        return seq[index] if index < len(seq) and seq[index] is not None else None

    days = []
    for index, iso in enumerate(times[:7]):
        try:
            when = datetime.date.fromisoformat(iso)
            weekday = WEEKDAYS[when.weekday()]
            label = "%s %d" % (MONTHS[when.month - 1], when.day)
        except ValueError:
            weekday, label = iso[5:], iso
        high, low = pick(highs, index), pick(lows, index)
        days.append({
            "date": iso,
            "dow": weekday,
            "label": label,
            "code": pick(codes, index) or 0,
            "hi": round(high) if high is not None else None,
            "lo": round(low) if low is not None else None,
            "rain": pick(rain, index),
        })

    current = data.get("current", {})
    now_temp = current.get("temperature_2m")
    return {
        "days": days,
        "now": {
            "temp": round(now_temp) if now_temp is not None else None,
            "code": current.get("weather_code") or 0,
        },
        "fetched": time.time(),
    }


def forecast_loop():
    global _forecast
    while True:
        result = fetch_forecast()
        if result:
            with _lock:
                _forecast = result
            time.sleep(FORECAST_REFRESH)
        else:
            # Keep whatever we already have, and try again soon.
            time.sleep(60)


# ---------------------------------------------------------------- page ----

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
  .wrap { max-width: 1040px; margin: 0 auto; padding: 24px; }
  header { display: flex; align-items: center; justify-content: space-between;
           gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }
  h1 { font-size: 17px; font-weight: 600; color: #9fb0c0; margin: 0; }
  h2 { font-size: 14px; font-weight: 600; color: #9fb0c0; margin: 0; }
  .head-right { display: flex; align-items: center; gap: 18px; }
  .clock { font-size: 14px; color: #cdd6e0; font-variant-numeric: tabular-nums; }
  .tag { font-size: 11px; color: #7f8c9b; background: #1c2229;
         border: 1px solid #262e37; border-radius: 5px; padding: 2px 5px;
         margin-right: 6px; }
  .status { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #7f8c9b; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #7f3540; }
  .dot.on { background: #3ba55d; box-shadow: 0 0 8px #3ba55d; }
  .cards { display: flex; gap: 16px; margin-bottom: 14px; flex-wrap: wrap; }
  .card { flex: 1 1 210px; background: #171c22; border: 1px solid #232a33;
          border-radius: 12px; padding: 16px; }
  .label { font-size: 12px; color: #7f8c9b; text-transform: uppercase;
           letter-spacing: .05em; }
  .value { font-size: 32px; font-weight: 700; margin: 6px 0 10px; color: #55606c; }
  #temp.value { color: #e6e9ee; }
  #led.on { color: #3ba55d; }
  #mode.value.on { color: #cdd6e0; }
  .row { display: flex; gap: 8px; align-items: center; }
  .btn { flex: 1; background: #222a33; color: #cdd6e0; border: 1px solid #2e3843;
         border-radius: 8px; padding: 8px 10px; font-size: 13px; cursor: pointer; }
  .btn:hover { background: #2b3540; }
  .btn.active { background: #1f6f3d; border-color: #3ba55d; color: #fff; }
  .btn.attention { background: #7a5a12; border-color: #d7a925; color: #fff; }
  input[type=range] { width: 100%; margin: 4px 0 10px; accent-color: #3ba55d; }
  .muted { font-size: 12px; color: #7f8c9b; }
  .note { min-height: 18px; font-size: 13px; margin: 0 2px 12px; }
  .note.ok { color: #3ba55d; }
  .note.bad { color: #e0685f; }
  canvas { background: #171c22; border: 1px solid #232a33;
           border-radius: 12px; padding: 8px; }
  .stats { display: flex; gap: 18px; margin: 14px 2px 8px; font-size: 13px; color: #7f8c9b; }
  .stats b { color: #cdd6e0; }
  .weather { margin-top: 24px; }
  .weather-head { display: flex; align-items: baseline; gap: 14px;
                  justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; }
  .days { display: flex; gap: 10px; flex-wrap: wrap; }
  .day { flex: 1 1 118px; background: #171c22; border: 1px solid #232a33;
         border-radius: 12px; padding: 12px 10px; text-align: center; }
  .day .dow { font-size: 12px; color: #9fb0c0; text-transform: uppercase;
              letter-spacing: .04em; }
  .day .date { font-size: 12px; color: #7f8c9b; margin-bottom: 8px; }
  .day .icon { font-size: 30px; line-height: 1.1; }
  .day .temps { font-size: 14px; margin-top: 8px; color: #cdd6e0; }
  .day .temps .lo { color: #7f8c9b; }
  .day .rain { font-size: 12px; color: #4f9fd4; margin-top: 4px; min-height: 15px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Raspberry Pi Twin &mdash; live dashboard</h1>
    <div class="head-right">
      <div class="clock"><span class="tag">Fin</span><b id="clock">--:--:--</b></div>
      <div class="status"><span class="dot" id="dot"></span><span id="conn">connecting...</span></div>
    </div>
  </header>

  <div class="cards">
    <div class="card">
      <div class="label">Temperature</div>
      <div class="value" id="temp">--</div>
      <div class="muted">CPU core, one sample per second</div>
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
      <input id="range" type="range" min="30" max="90" step="1" value="60"
             oninput="onSlider(this.value)">
      <div class="row">
        <span class="muted" id="rval">60 \u00b0C</span>
        <button class="btn" id="btnSet" onclick="setThreshold()">Set</button>
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

  <div id="note" class="note"></div>

  <div class="stats">
    <span>last 60 s &mdash; min <b id="smin">--</b></span>
    <span>max <b id="smax">--</b></span>
    <span>avg <b id="savg">--</b></span>
    <span>samples <b id="scount">0</b></span>
  </div>
  <canvas id="chart" height="120"></canvas>

  <section class="weather">
    <div class="weather-head">
      <h2>Helsinki &mdash; 7 day forecast</h2>
      <div class="muted" id="nowline">loading...</div>
    </div>
    <div class="days" id="days"></div>
  </section>
</div>

<script>
// ---------------------------------------------------------------- chart --
let chart = null;
try {
  if (typeof Chart !== 'undefined') {
    chart = new Chart(document.getElementById('chart'), {
      type: 'line',
      data: { labels: [], datasets: [{
        label: 'CPU temperature (\u00b0C)',
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
          y: { ticks: { color: '#7f8c9b', callback: v => v + '\u00b0' },
               grid: { color: 'rgba(35,42,51,.6)' } }
        },
        plugins: { legend: { labels: { color: '#9fb0c0' } } }
      }
    });
  } else {
    document.getElementById('chart').replaceWith('chart needs internet (cdn.jsdelivr.net)');
  }
} catch (e) {}

// ------------------------------------------------------------ helpers ---
const DEG = '\u00b0C';
let lastState = null;
let sliderTouched = false;

function fmt(value, unit) {
  return value == null ? '--' : value.toFixed(1) + unit;
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

function setConn(ok) {
  document.getElementById('dot').className = ok ? 'dot on' : 'dot';
  document.getElementById('conn').textContent = ok ? 'broker connected' : 'no broker';
}

let noteTimer = null;
function note(text, bad) {
  const box = document.getElementById('note');
  box.textContent = text;
  box.className = 'note ' + (bad ? 'bad' : 'ok');
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => { box.textContent = ''; box.className = 'note'; }, 5000);
}

// The slider is the value you *want*; the big number is what the Pi reports.
// They only sync while you are not holding a change in your hand.
function onSlider(value) {
  sliderTouched = true;
  document.getElementById('rval').textContent = value + ' ' + DEG;
  const button = document.getElementById('btnSet');
  button.textContent = 'Set ' + value + ' ' + DEG;
  button.className = 'btn attention';
}

async function send(target, value) {
  try {
    const response = await fetch('/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target, value: value })
    });
    const result = await response.json();
    if (!result.ok) note('Could not send ' + target + ': ' + result.detail, true);
    setTimeout(tick, 250);
    return result;
  } catch (e) {
    note('Could not reach the dashboard server.', true);
    return { ok: false };
  }
}

async function setThreshold() {
  const value = document.getElementById('range').value;
  const result = await send('threshold', value);
  if (result.ok) {
    note('Threshold set to ' + value + ' ' + DEG + ' - the Pi confirmed: waiting for it to report back.');
    sliderTouched = false;
    const button = document.getElementById('btnSet');
    button.textContent = 'Set';
    button.className = 'btn';
  }
}

// --------------------------------------------------------------- clock --
function tickClock() {
  const now = new Date();
  const text = now.toLocaleString('en-GB', {
    timeZone: 'Europe/Helsinki', day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  });
  document.getElementById('clock').textContent = text;
}

// ------------------------------------------------------------- weather --
function weatherIcon(code) {
  if (code === 0) return "\u2600\ufe0f";
  if (code <= 3) return "\U0001f324\ufe0f";
  if (code === 45 || code === 48) return "\U0001f32b\ufe0f";
  if (code >= 51 && code <= 67) return "\U0001f327\ufe0f";
  if (code >= 71 && code <= 77) return "\u2744\ufe0f";
  if (code >= 80 && code <= 82) return "\U0001f326\ufe0f";
  if (code === 85 || code === 86) return "\U0001f328\ufe0f";
  if (code >= 95) return "\u26c8\ufe0f";
  return "\U0001f321\ufe0f";
}

function weatherName(code) {
  if (code === 0) return 'clear';
  if (code <= 3) return 'cloudy';
  if (code === 45 || code === 48) return 'fog';
  if (code >= 51 && code <= 57) return 'drizzle';
  if (code >= 61 && code <= 67) return 'rain';
  if (code >= 71 && code <= 77) return 'snow';
  if (code >= 80 && code <= 82) return 'showers';
  if (code === 85 || code === 86) return 'snow showers';
  if (code >= 95) return 'thunderstorm';
  return 'unknown';
}

function renderForecast(data) {
  const days = document.getElementById('days');
  const nowline = document.getElementById('nowline');
  if (!data || !data.days || !data.days.length) {
    nowline.textContent = 'loading Helsinki forecast...';
    days.innerHTML = '';
    return;
  }

  const now = data.now || {};
  const stamp = new Date(data.fetched * 1000).toLocaleTimeString([], { hour12: false });
  nowline.textContent = 'right now ' + (now.temp == null ? '--' : now.temp + DEG)
    + ' ' + weatherIcon(now.code) + ' ' + weatherName(now.code)
    + '  \u00b7  updated ' + stamp;

  days.innerHTML = data.days.map(day => {
    const hi = day.hi == null ? '--' : day.hi;
    const lo = day.lo == null ? '--' : day.lo;
    const rain = day.rain == null ? '' : '\U0001f4a7 ' + day.rain + '%';
    return '<div class="day">'
      + '<div class="dow">' + day.dow + '</div>'
      + '<div class="date">' + day.label + '</div>'
      + '<div class="icon" title="' + weatherName(day.code) + '">' + weatherIcon(day.code) + '</div>'
      + '<div class="temps">' + hi + '\u00b0 <span class="lo">' + lo + '\u00b0</span></div>'
      + '<div class="rain">' + rain + '</div>'
      + '</div>';
  }).join('');
}

// ---------------------------------------------------------------- poll --
async function tick() {
  try {
    const response = await fetch('/data');
    const data = await response.json();
    const state = data.state;
    lastState = state;
    setConn(data.connected);

    document.getElementById('temp').textContent = fmt(state.temperature, ' ' + DEG);
    document.getElementById('thr').textContent = fmt(state.threshold, ' ' + DEG);

    const led = document.getElementById('led');
    if (state.led === 1) { led.textContent = 'ON'; led.className = 'value on'; }
    else if (state.led === 0) { led.textContent = 'OFF'; led.className = 'value'; }
    else { led.textContent = '--'; led.className = 'value'; }
    document.getElementById('btnOn').className = 'btn' + (state.led === 1 ? ' active' : '');
    document.getElementById('btnOff').className = 'btn' + (state.led === 0 ? ' active' : '');

    const mode = document.getElementById('mode');
    if (state.mode === 'auto') { mode.textContent = 'Auto'; mode.className = 'value on'; }
    else if (state.mode === 'manual') { mode.textContent = 'Manual'; mode.className = 'value on'; }
    else { mode.textContent = '--'; mode.className = 'value'; }
    document.getElementById('btnAuto').className = 'btn' + (state.mode === 'auto' ? ' active' : '');
    document.getElementById('btnManual').className = 'btn' + (state.mode === 'manual' ? ' active' : '');

    if (!sliderTouched && state.threshold != null) {
      const range = document.getElementById('range');
      range.value = Math.round(state.threshold);
      document.getElementById('rval').textContent = range.value + ' ' + DEG;
    }

    document.getElementById('smin').textContent = fmt(data.stats.min, ' ' + DEG);
    document.getElementById('smax').textContent = fmt(data.stats.max, ' ' + DEG);
    document.getElementById('savg').textContent = fmt(data.stats.avg, ' ' + DEG);
    document.getElementById('scount').textContent = data.stats.count;

    if (chart) {
      chart.data.labels = data.history.map(point => fmtTime(point.t));
      chart.data.datasets[0].data = data.history.map(point => point.v);
      chart.update();
    }

    renderForecast(data.forecast);
  } catch (e) {
    setConn(false);
  }
}

tickClock();
setInterval(tickClock, 1000);
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

    threading.Thread(target=forecast_loop, daemon=True).start()

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
