# Filling Station — Digital Twin

A small tank-filling digital twin: a pump pushes liquid through an inlet valve
into a tank, a level sensor reports the fill level, and a soft PLC runs the
fill-to-setpoint sequence batch after batch.

```
   plant model            soft PLC            clients
  ┌────────────┐        ┌────────────┐       ┌──────────────────┐
  │ filling_   │◀target▶│ filling_   │       │ Qt HMI (QML/C++) │
  │ plant.py   │   MQTT │ plc.py     │◀─────▶│ Blender 3D twin  │
  └────────────┘        └────────────┘       │ SQLite historian │
        └────────── fill/# ─────────────────┴──────────────────┘
```

## The machine

- **Pump** — runs only when commanded; fills the tank at 8 %/s.
- **Valve** — the inlet valve; liquid flows only when the pump runs AND the
  valve is open.
- **Level sensor** — the fill level itself, 0–100 %.

In **auto** mode the PLC opens the valve, runs the pump, fills to the setpoint,
stops, waits a short change-over, then starts the next batch and counts it. In
**manual** mode the PLC stands back and the HMI drives the pump and valve
directly.

## Layout

| Folder | What it is |
| --- | --- |
| `plant/` | `filling_plant.py` — tank/pump/valve simulation, publishes sensors |
| `plc/` | `filling_plc.py` — soft PLC / fill sequence controller |
| `twin/` | Blender scene + live twin script |
| `hmi/` | Qt 6 Quick HMI (CMake, C++ MQTT bridge, QML) |
| `historian/` | `filling_logger.py` — SQLite recorder |

## Topic contract

Sensors (plant → everyone):

| Topic | Meaning |
| --- | --- |
| `fill/level` | tank fill level, 0–100 % |
| `fill/pump` | 0–1 (actual pump state) |
| `fill/valve` | 0–1 (actual valve state) |
| `fill/filling` | 1 while liquid is actually flowing |

Actuators (PLC or HMI → plant):

| Topic | Meaning |
| --- | --- |
| `fill/target/pump` | 0 / 1 |
| `fill/target/valve` | 0 / 1 |
| `fill/plant/reset` | empty the tank (plant only) |

PLC status and commands:

| Topic | Meaning |
| --- | --- |
| `fill/state` | IDLE / FILLING / FULL / MANUAL |
| `fill/mode` | auto / manual |
| `fill/setpoint` | fill-to level, % |
| `fill/batches` | completed batches |
| `fill/alarm` | last fault message |
| `fill/command/start`, `stop`, `reset`, `mode`, `setpoint` | control |

Heartbeats: `fill/plant/alive` and `fill/plc/alive` (1/s, retained).

## Run it

Start the broker once (on the Mac):

```sh
brew install mosquitto
brew services start mosquitto
```

Then open three terminals (all default to `localhost`; set
`MQTT_BROKER=192.168.50.1` to point at the Mac from the Pi):

```sh
cd Filling

# 1. machine simulation
python3 plant/filling_plant.py

# 2. soft PLC
python3 plc/filling_plc.py

# 3. historian (optional)
python3 historian/filling_logger.py
```

Start filling:

```sh
mosquitto_pub -t fill/command/mode     -m auto
mosquitto_pub -t fill/command/setpoint -m 85
mosquitto_pub -t fill/command/start    -m 1
```

Watch the tags:

```sh
mosquitto_sub -h localhost -t 'fill/#' -v
```

## Qt HMI

```sh
cd Filling/hmi
cmake -S . -B build -DCMAKE_PREFIX_PATH=~/Qt/6.11.2/macos
cmake --build build
open build/appFillingHMI.app
```

Shows the tank with live liquid level and the setpoint line, pump and valve
indicators, the PLC state, a setpoint slider, and Start / Stop / Reset. In
**manual mode** the pump and valve buttons drive the plant directly.

## Blender twin

```sh
cd Filling/twin
blender --background --python create_filling_blend.py   # build the scene once
blender --background --python setup_filling_text.py     # install RUN_FILLING.py
```

Open `Filling_Twin.blend`, switch to the Scripting workspace and run
**RUN_FILLING.py**. The liquid rises with the level, the pump spins and turns
green while running, the valve rotates and changes colour, the sensor lights up
green while filling, and the status text follows the PLC state and batch count.

## Notes

- The plant and PLC are deliberately separate processes: the PLC only sees tag
  values, never the simulation's internals — the same boundary a real PLC has
  against a physical plant model.
- `fill/command/reset` stops and zeroes the PLC, which then publishes
  `fill/plant/reset` to empty the tank — a separate topic so the PLC's own
  reset command never echoes back into its state machine.
- `filling.db` is a local recording and is git-ignored. Use
  `python3 historian/filling_logger.py --stats` for a quick summary.
- To move the control onto real hardware later, replace `plc/filling_plc.py`
  with a CODESYS program on the Pi and keep the same tag names — the HMI, twin
  and historian keep working unchanged.
