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

## 4. Run the Blender subscriber (Mac)

In Blender, open the **Scripting** workspace, open `blender_twin.py`, and press
**Run Script**. First create:

- an object named **Rotor** (a part that should spin), and
- a material named **LED** (assigned to a part that should change color).

The rotor spins faster as temperature rises; the LED material turns red when
the LED is on.

## Next steps

- Publish from a real GPIO/LED and a DS18B20 sensor instead of the CPU temp.
- Drive a part that maps to a real machine axis (e.g. a cutting blade).
- Add OPC UA so the same data can feed a TwinCAT/industrial twin.
