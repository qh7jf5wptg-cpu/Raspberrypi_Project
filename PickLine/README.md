# PickLine — Gripper Feeds a Conveyor

A combined digital twin of a pick-and-place gantry and a conveyor belt. The
gripper picks a part from a bin and drops it at the belt infeed; the belt
carries it to the far end; once it exits, the gripper waits an adjustable gap
and feeds the next part. One part is in flight at a time.

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
from the gripper's drop instead of spawning them on a timer.

## The machine

- **Gantry** — 3-axis (X 0–300, Y 0–220, Z 0–100 mm) with a two-finger
  gripper. Picks at the bin `(260, 20)` and drops at the belt infeed
  `(0, 100)`.
- **Conveyor** — belt along X, 0–400 mm at Y = 100, running at 90 mm/s.
- **Infeed sensor** — sees the part just after it lands on the belt (x = 30).
- **Outfeed sensor** — sees the part just before it exits (x = 370).
- **Gap** — adjustable seconds between a part leaving the belt and the next
  pick (default 1.5 s, range 0–30 s).

## Topic contract

Sensors (plant → everyone):

| Topic | Meaning |
| --- | --- |
| `pickline/x`, `y`, `z` | tool position, mm |
| `pickline/grip` | 1 open / 0 closed |
| `pickline/holding` | 1 while a part is held |
| `pickline/part_x`, `part_y`, `part_z` | part location, mm |
| `pickline/belt` | 0 stopped / 1 running |
| `pickline/belt_pos` | part position on the belt, mm (−1 = none) |
| `pickline/sensor_in`, `sensor_out` | 1 while a part is in front of the sensor |
| `pickline/placed` | parts fed onto the belt |
| `pickline/exited` | parts that left the belt |

Actuators (PLC or HMI → plant):

| Topic | Meaning |
| --- | --- |
| `pickline/target/x`, `y`, `z` | commanded tool position, mm |
| `pickline/target/grip` | 1 open / 0 close |
| `pickline/target/belt` | 0 / 1 |
| `pickline/plant/reset` | clear belt and counters |

PLC status and commands:

| Topic | Meaning |
| --- | --- |
| `pickline/state` | IDLE, TO_PICK, GRIP, TO_DROP, WAIT_EXIT, FAULT, ... |
| `pickline/mode` | auto / manual |
| `pickline/gap` | seconds between exit and next pick |
| `pickline/alarm` | last fault message |
| `pickline/command/start`, `stop`, `reset`, `mode`, `gap` | control |

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
mosquitto_pub -t pickline/command/mode -m auto
mosquitto_pub -t pickline/command/gap  -m 2.0
mosquitto_pub -t pickline/command/start -m 1
```

Change the gap on the fly:

```sh
mosquitto_pub -t pickline/command/gap -m 4.5
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

One canvas shows both machines: the belt with its two sensors, the drop zone,
the bin, the moving part and the gantry tool. The side panel has the state,
placed/exited counters, a gap slider, Start / Stop / Reset, and manual jog of
the axes, gripper and belt.

## Blender twin

```sh
cd PickLine/twin
blender --background --python create_pickline_blend.py   # build the scene once
blender --background --python setup_pickline_text.py     # install RUN_PICKLINE.py
```

Open `PickLine_Twin.blend`, switch to the Scripting workspace and run
**RUN_PICKLINE.py**. The gantry head and jaws move over the belt, the part
travels along it, the two sensor cubes light green as it passes, the rollers
spin while the belt runs, and the status line shows the state, counts and gap.

## Notes

- The plant and PLC are separate processes: the PLC only sees tag values,
  never the simulation's internals — the same boundary a real PLC has against
  a physical cell.
- The gap is applied after the part exits, so there is never more than one
  part on the belt. A 30 s timeout turns a lost part into a `FAULT` instead of
  hanging.
- `pickline.db` is a local recording and is git-ignored. Use
  `python3 historian/pickline_logger.py --stats` for a quick summary.
- To run the control on real hardware later, replace `plc/pickline_plc.py`
  with CODESYS on the Pi and keep the same tag names — the HMI, twin and
  historian keep working unchanged.
