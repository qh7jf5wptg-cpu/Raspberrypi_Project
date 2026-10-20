# PickLine — Pick, Convey, and Fill Cell

A combined digital twin of a pick-and-place gantry, a conveyor belt, and two
filling stations. The gantry picks an empty container from one of two bins and
drops it on the belt; the belt carries it to the end and routes it to fill
station A (straight) or station B (left). Each station fills the container and
then blocks until the full container is taken out manually.

```
   plant model            soft PLC            clients
  ┌────────────┐        ┌────────────┐       ┌──────────────────┐
  │ pickline_  │◀target▶│ pickline_  │       │ Qt HMI (QML/C++) │
  │ plant.py   │   MQTT │ plc.py     │◀─────▶│ Blender 3D twin  │
  └────────────┘        └────────────┘       │ SQLite historian │
        └──────── pickline/# ────────────────┴──────────────────┘
```

## The machine

- **Gantry** — 3-axis (X 0–300, Y 0–220, Z 0–100 mm) with a two-finger
  gripper. Picks from two bins: DOWN `(260, 20)` or UP `(260, 190)`, chosen
  per cycle (down / up / alternate). Drops at the belt infeed `(0, 100)`.
- **Conveyor** — belt along X, 0–400 mm at Y = 100, speed adjustable 20–250
  mm/s. Past the belt end there is a short straight approach to station A
  `(460, 100)` and a left approach to station B `(400, 240)`.
- **Two fill stations** — every container has the same adjustable volume
  (default 100 units). Station A fills faster than station B (both rates
  adjustable), so the stations are deliberately different.
- **Routing** — containers alternate straight / left one by one. When a
  station holds a full container it blocks, and new containers route only to
  the other station. If neither station is free the cell waits.
- **Take-out is manual** — a "Take out" button (or MQTT message) removes a
  full container and frees that station.

## Topic contract

Sensors (plant → everyone):

| Topic | Meaning |
| --- | --- |
| `pickline/x`, `y`, `z` | tool position, mm |
| `pickline/grip`, `holding` | jaws and held-part state |
| `pickline/part_x`, `part_y` | container location, mm |
| `pickline/belt`, `speed`, `diverter` | conveyor state |
| `pickline/placed`, `exited` | fed onto belt / entered a station |
| `pickline/volume` | container capacity, units |
| `pickline/fill/a/level`, `state`, `count`, `rate`, `valve` | station A |
| `pickline/fill/b/level`, `state`, `count`, `rate`, `valve` | station B |
| `pickline/fill/total` | total liquid dispensed, units |

Actuators (PLC or HMI → plant):

| Topic | Meaning |
| --- | --- |
| `pickline/target/x`, `y`, `z`, `grip`, `belt`, `diverter`, `speed` | gantry/conveyor |
| `pickline/target/volume` | container capacity (10–500) |
| `pickline/target/fill/a/rate`, `fill/b/rate` | fill speed (1–200 u/s) |
| `pickline/fill/a/take`, `fill/b/take` | take out a full container |
| `pickline/plant/reset` | clear belt, stations and counters |

PLC status and commands:

| Topic | Meaning |
| --- | --- |
| `pickline/state` | IDLE, TO_PICK, WAIT_EXIT, WAIT_STATION, FAULT, ... |
| `pickline/mode` | auto / manual |
| `pickline/side` | current pick side (down / up) |
| `pickline/decision` | STRAIGHT / LEFT (current route) |
| `pickline/gap` | seconds between a container entering and the next pick |
| `pickline/command/start`, `stop`, `reset`, `mode`, `side`, `gap` | control |

Heartbeats: `pickline/plant/alive` and `pickline/plc/alive` (1/s, retained).

## Run it

```sh
brew services start mosquitto          # once

cd PickLine
python3 plant/pickline_plant.py        # machine simulation
python3 plc/pickline_plc.py            # soft PLC
python3 historian/pickline_logger.py   # optional
```

Start the cell:

```sh
mosquitto_pub -t pickline/command/mode  -m auto
mosquitto_pub -t pickline/command/side  -m alternate
mosquitto_pub -t pickline/command/gap   -m 0.5
mosquitto_pub -t pickline/command/start -m 1
```

Take out a full container when a station blocks:

```sh
mosquitto_pub -t pickline/fill/a/take -m 1
mosquitto_pub -t pickline/fill/b/take -m 1
```

Adjust the container volume and fill speeds:

```sh
mosquitto_pub -t pickline/target/volume       -m 120
mosquitto_pub -t pickline/target/fill/a/rate  -m 45
mosquitto_pub -t pickline/target/fill/b/rate  -m 30
```

Watch everything:

```sh
mosquitto_sub -h localhost -t 'pickline/#' -v
```

## Qt HMI

```sh
cd PickLine/hmi
cmake -S . -B build -DCMAKE_PREFIX_PATH=~/Qt/6.11.2/macos
cmake --build build
open build/appPickLineHMI.app
```

The canvas shows the belt, the two fill tanks with live liquid levels, the
bins, and the moving container and gantry. The side panel has the state,
volume and fill-speed sliders, a "Take out" button per station, Start / Stop /
Reset, and manual jog.

## Blender twin

```sh
cd PickLine/twin
blender --background --python create_pickline_blend.py   # build the scene once
blender --background --python setup_pickline_text.py     # install RUN_PICKLINE.py
```

Open `PickLine_Twin.blend` and run **RUN_PICKLINE.py**. The gantry and jaws
move, the container rides the belt, and the two liquid columns rise as the
stations fill, turning green when full.

## Live dashboard

```sh
python3 dashboard/pickline_dashboard.py
```

Open <http://localhost:8080>. The page shows the machine state, both stations
with live fill bars, total dispensed, throughput (fills/minute) and a live
history chart. It subscribes straight to MQTT, so it works without the
historian.

## Faults

| Fault | How it happens | Result |
| --- | --- | --- |
| Belt jam | `pickline/fault/jam -m 1` (or a stuck container) | PLC goes `FAULT`, alarm `BELT JAM` |
| Overfill | lower `volume` below a station's current level | station goes `FAULT`, alarm `OVERFILL` |

Clear a jam with `pickline/fault/clear -m 1` or a Reset. Clear an overfilled
station with its Take out button. The HMI has "Jam belt" / "Clear jam" buttons,
and shows each station's alarm.

## Notes

- The plant and PLC are separate processes: the PLC only sees tag values,
  never the simulation's internals — the same boundary a real PLC has against
  a physical cell.
- Stations are "free" only when EMPTY; FILLING and FULL both block them. The
  cell therefore waits in `WAIT_STATION` until you take a full container out.
- `pickline.db` is a local recording and is git-ignored. Use
  `python3 historian/pickline_logger.py --stats` for a quick summary.
- To run the control on real hardware later, replace `plc/pickline_plc.py`
  with CODESYS on the Pi and keep the same tag names — the HMI, twin and
  historian keep working unchanged.
