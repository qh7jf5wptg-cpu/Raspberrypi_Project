# PickLine — Gantry Feeds a Conveyor with Two Exits

A combined digital twin of a pick-and-place gantry and a conveyor belt. The
gripper picks a part from one of two bins (down or up), drops it at the belt
infeed, and the belt carries it the full length. Only at the end does the
direction change: straight off the end, or a 90-degree turn onto a side lane.
One part is in flight at a time, the belt speed is adjustable, and so is the
gap between a part leaving and the next pick.

```
   plant model            soft PLC            clients
  ┌────────────┐        ┌────────────┐       ┌──────────────────┐
  │ pickline_  │◀target▶│ pickline_  │       │ Qt HMI (QML/C++) │
  │ plant.py   │   MQTT │ plc.py     │◀─────▶│ Blender 3D twin  │
  └────────────┘        └────────────┘       │ SQLite historian │
        └──────── pickline/# ────────────────┴──────────────────┘
```

Unlike the separate Gripper and Conveyor projects, the two machines live in
one plant process so they stay in lock-step, and the conveyor takes its parts
from the gripper's drop instead of spawning them on a timer. The direction
change happens at the belt's end, not mid-belt.

## The machine

- **Gantry** — 3-axis (X 0–300, Y 0–220, Z 0–100 mm) with a two-finger
  gripper. Picks from one of two bins: **DOWN** `(260, 20)` or **UP**
  `(260, 190)`, chosen per cycle (down / up / alternate). Drops at the belt
  infeed `(0, 100)`.
- **Conveyor** — belt along X, 0–400 mm at Y = 100, speed adjustable 20–250
  mm/s (default 90 mm/s).
- **End diverter** — at x = 400 the part either exits straight or turns onto
  the side lane (Y 100 → 220).
- **Sensors** — infeed `(30)`, outfeed `(370)`, and a side-lane sensor `(210)`.
- **Gap** — seconds between a part leaving and the next pick (default 1.5 s,
  range 0–30 s).

## Topic contract

Sensors (plant → everyone):

| Topic | Meaning |
| --- | --- |
| `pickline/x`, `y`, `z` | tool position, mm |
| `pickline/grip` | 1 open / 0 closed |
| `pickline/holding` | 1 while a part is held |
| `pickline/part_x`, `part_y`, `part_z` | part location, mm |
| `pickline/belt` | 0 stopped / 1 running |
| `pickline/belt_pos` | part position on the straight belt, mm (−1 = none) |
| `pickline/speed` | belt speed, mm/s |
| `pickline/diverter` | 0 straight / 1 divert |
| `pickline/sensor_in`, `sensor_out`, `sensor_divert` | 1 while a part is in front |
| `pickline/placed` | parts fed onto the belt |
| `pickline/passed` | parts that went straight off the end |
| `pickline/diverted` | parts that turned onto the side lane |

Actuators (PLC or HMI → plant):

| Topic | Meaning |
| --- | --- |
| `pickline/target/x`, `y`, `z` | commanded tool position, mm |
| `pickline/target/grip` | 1 open / 0 close |
| `pickline/target/belt` | 0 / 1 |
| `pickline/target/diverter` | 0 / 1 |
| `pickline/target/speed` | belt speed, mm/s |
| `pickline/plant/reset` | clear belt and counters |

PLC status and commands:

| Topic | Meaning |
| --- | --- |
| `pickline/state` | IDLE, TO_PICK, GRIP, TO_DROP, WAIT_EXIT, FAULT, ... |
| `pickline/mode` | auto / manual |
| `pickline/side` | current pick side (down / up) |
| `pickline/side_mode` | down / up / alternate |
| `pickline/divert_mode` | pass / divert / alternate |
| `pickline/decision` | STRAIGHT / DIVERT (current part) |
| `pickline/gap` | seconds between exit and next pick |
| `pickline/command/start`, `stop`, `reset`, `mode`, `side`, `divert`, `gap` | control |

Heartbeats: `pickline/plant/alive` and `pickline/plc/alive` (1/s, retained).

## Run it

Start the broker once (on the Mac):

```sh
brew install mosquitto
brew services start mosquitto
```

Then open three terminals (all default to `localhost`; set
`MQTT_BROKER=192.168.50.1` to point at the Mac from the Pi):

```sh
cd PickLine

# 1. machine simulation
python3 plant/pickline_plant.py

# 2. soft PLC
python3 plc/pickline_plc.py

# 3. historian (optional)
python3 historian/pickline_logger.py
```

Start the loop:

```sh
mosquitto_pub -t pickline/command/mode   -m auto
mosquitto_pub -t pickline/command/side   -m alternate
mosquitto_pub -t pickline/command/divert -m alternate
mosquitto_pub -t pickline/command/gap    -m 2.0
mosquitto_pub -t pickline/command/start  -m 1
```

Change the belt speed and gap on the fly:

```sh
mosquitto_pub -t pickline/target/speed -m 150
mosquitto_pub -t pickline/command/gap  -m 4.5
```

Watch the tags:

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

One canvas shows both machines: the belt, the end gate and side lane, the two
bins, the drop zone, the sensors, the moving part and the gantry tool. The
side panel has the state, placed/straight/diverted counters, gap and speed
sliders, pick-side and end-routing buttons, Start / Stop / Reset, and manual
jog of the axes, gripper, belt and gate.

## Blender twin

```sh
cd PickLine/twin
blender --background --python create_pickline_blend.py   # build the scene once
blender --background --python setup_pickline_text.py     # install RUN_PICKLINE.py
```

Open `PickLine_Twin.blend`, switch to the Scripting workspace and run
**RUN_PICKLINE.py**. The gantry head and jaws move over the belt, the part
travels along it, the end gate swings onto the side lane when diverting, the
three sensor cubes light green as the part passes, the rollers spin at the
current speed, and the status line shows the state, side, decision and counts.

## Notes

- The plant and PLC are separate processes: the PLC only sees tag values,
  never the simulation's internals — the same boundary a real PLC has against
  a physical cell.
- The gap is applied after the part exits, so there is never more than one
  part on the line. A 30 s timeout turns a lost part into a `FAULT` instead of
  hanging.
- `pickline.db` is a local recording and is git-ignored. Use
  `python3 historian/pickline_logger.py --stats` for a quick summary.
- To run the control on real hardware later, replace `plc/pickline_plc.py`
  with CODESYS on the Pi and keep the same tag names — the HMI, twin and
  historian keep working unchanged.
