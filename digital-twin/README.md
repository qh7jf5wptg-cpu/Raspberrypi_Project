# Raspberry Pi + Blender Digital Twin

A minimal three-layer digital twin for learning embedded Linux and networking:

1. **Raspberry Pi (Linux)** — reads the CPU temperature and computes LED state.
2. **MQTT broker** — carries the live data (`machine/temperature`, `machine/led`, `machine/threshold`).
3. **Blender (Mac)** — a Python script subscribes and moves/colors a 3D model.

## 1. Install the MQTT broker (Mosquitto)

On macOS:

```sh
brew install mosquitto
brew services start mosquitto
```

On the Raspberry Pi:

```sh
sudo apt update && sudo apt install -y mosquitto mosquitto-clients
```

Use one broker. Easiest: run the broker on your Mac, and point the Pi at the
Mac's IP.

## 2. Install paho-mqtt

For the publisher (system Python in VS Code):

```sh
python3 -m pip install paho-mqtt
```

Blender ships its own Python. Install paho-mqtt into it too (path varies by
Blender version):

```sh
/Applications/Blender.app/Contents/Resources/*/python/bin/python3 -m pip install paho-mqtt
```

## 3. Run the publisher (Pi)

```sh
# On the Pi, with the broker on your Mac:
MQTT_BROKER=<mac-ip> python3 pi_publisher.py

# Or locally (fake temperature on macOS):
python3 pi_publisher.py
```

## 4. Run the Blender twin (Mac)

Open `RaspberryPi_Twin.blend`, switch to the **Scripting** workspace, and press
**Run Script** on the text block called **`RUN_TWIN.py`**.

That block is only six lines long: it loads `blender_twin.py` from this folder
every time you run it. So after a `git pull` there is nothing to refresh — just
press Run Script and you are running the newest code.

### Why not open `blender_twin.py` directly?

Blender *copies* a script into the `.blend` file when you open it in the Text
Editor. That copy never follows the file on disk, so it silently goes stale.
The usual fix is to click **Text ▸ Reload from Disk** every time — easy to
forget, and you end up debugging an old version of your own code.

`RUN_TWIN.py` side-steps that: it has no link to a file at all, so it can never
go stale, and it always runs the newest `blender_twin.py`.

### Starting it without the editor

```sh
cd ~/Documents/ChatGPT/Raspberrypi_Project/digital-twin
/Applications/Blender.app/Contents/MacOS/Blender RaspberryPi_Twin.blend --python blender_twin.py
```

### Rebuilding the .blend

If you regenerate the scene with `create_twin_blend.py`, re-install the loader:

```sh
cd ~/Documents/ChatGPT/Raspberrypi_Project/digital-twin
/Applications/Blender.app/Contents/MacOS/Blender --background --python setup_twin_text.py
```

## 5. Log telemetry to SQLite (and replay it)

SQLite is a single-file database built into Python — no server, no install. Use
it to record a session and replay it later in Blender.

Start the Pi app (publishing), then on the Mac run the logger:

```sh
cd ~/Documents/ChatGPT/Raspberrypi_Project/digital-twin
python3 telemetry_logger.py
```

It creates `telemetry.db` and writes one row per second:

| column | meaning |
| --- | --- |
| `ts` | Unix timestamp |
| `temperature` | CPU temperature (deg C) |
| `led` | 1 / 0 |
| `threshold` | threshold (deg C) |

Stop with Ctrl+C. Inspect the log with the `sqlite3` CLI:

```sh
sqlite3 telemetry.db ".tables"
sqlite3 telemetry.db "SELECT COUNT(*), ROUND(MIN(temperature),1), ROUND(MAX(temperature),1) FROM telemetry;"
sqlite3 telemetry.db "SELECT * FROM telemetry ORDER BY ts DESC LIMIT 5;"
```

### Replay it in Blender

In the **Twin** panel, tick **Replay recorded session**. The twin stops using
the live MQTT state and instead loops through the recorded rows, so the rotor,
LED, alarm lamp, and temperature bar graph all follow the recording.

The database path defaults to `digital-twin/telemetry.db`. Override it with the
`TWIN_DB` environment variable before launching Blender if your log is elsewhere.

## 6. Live web dashboard (Mac)

A small web page that shows the live temperature, LED state and alarm threshold
with a rolling chart — and lets you control the LED, the mode and the threshold
from the browser. Everything goes through the same MQTT topics, so the Qt app,
the Blender twin and this page always agree.

```sh
cd ~/Documents/ChatGPT/Raspberrypi_Project/digital-twin
python3 dashboard.py
```

Then open <http://localhost:8000>.

The page is only served on your Mac (`127.0.0.1`), so nothing on the network can
reach it. If `python3` reports `No module named 'paho'`, install the client once:

```sh
python3 -m pip install --user --break-system-packages paho-mqtt
```

Settings come from environment variables: `MQTT_BROKER` (default `localhost`),
`MQTT_PORT` (default `1883`) and `DASHBOARD_PORT` (default `8000`).

## Next steps

- Publish from a real GPIO/LED and a DS18B20 sensor instead of the CPU temp.
- Drive a part that maps to a real machine axis (e.g. a cutting blade).
- Add OPC UA so the same data can feed a TwinCAT/industrial twin.
