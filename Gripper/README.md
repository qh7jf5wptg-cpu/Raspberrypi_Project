# Gripper — Pick & Place Digital Twin

A virtual-commissioning style digital twin of a 3-axis pick-and-place gantry
(X / Y / Z + two-finger gripper) built with free tools on macOS + Raspberry Pi.

```
   plant model            soft PLC              clients
  ┌────────────┐        ┌────────────┐       ┌──────────────────┐
  │ gripper_   │◀target▶│ gripper_   │       │ Qt HMI (QML/C++) │
  │ plant.py   │   MQTT │ plc.py     │◀─────▶│ Blender 3D twin  │
  └────────────┘        └────────────┘       │ SQLite historian │
        └────────── gripper/# ───────────────┴──────────────────┘
```

The **plant** simulates the machine (axis motion, gripper, part handling) and
publishes its sensors. The **PLC** runs the pick-and-place sequence as a state
machine and drives the plant through target topics. Everything else is just a
client of the same tag set.

## Layout

| Folder | What it is |
| --- | --- |
| `plant/` | `gripper_plant.py` — machine simulation, publishes sensors |
| `plc/` | `gripper_plc.py` — soft PLC / sequence controller |
| `twin/` | Blender scene + live twin script |
| `hmi/` | Qt 6 Quick HMI (CMake, C++ MQTT bridge, QML) |
| `historian/` | `gripper_logger.py` — SQLite recorder |

## Topic contract

Sensors (plant → everyone):

| Topic | Meaning |
| --- | --- |
| `gripper/x`, `y`, `z` | actual tool position, mm |
| `gripper/grip` | 1 = open, 0 = closed |
| `gripper/part` | 1 = part held |
| `gripper/placed` | parts delivered |
| `gripper/part_x/y/z` | position of the part |
| `gripper/busy` | 1 while any axis is moving |

Actuators (PLC or HMI → plant):

| Topic | Meaning |
| --- | --- |
| `gripper/target/x`, `y`, `z` | commanded position, mm |
| `gripper/target/grip` | 1 open / 0 close |
| `gripper/command/reset` | reset the plant |

PLC status and commands:

| Topic | Meaning |
| --- | --- |
| `gripper/state` | IDLE, TO_PICK, GRIP, HOME, FAULT, ... |
| `gripper/count` | completed cycles |
| `gripper/mode` | auto / manual |
| `gripper/alarm` | last fault message |
| `gripper/command/start`, `stop`, `reset` | cycle control |

Positions are millimetres: X 0–300, Y 0–200, Z 0–100.

## Run it

Start the broker once (on the Mac):

```sh
brew install mosquitto
brew services start mosquitto
```

Then open three terminals (all defaults to `localhost`; set
`MQTT_BROKER=192.168.50.1` to point at the Mac from the Pi):

```sh
cd Gripper

# 1. machine simulation
python3 plant/gripper_plant.py

# 2. soft PLC
python3 plc/gripper_plc.py

# 3. historian (optional)
python3 historian/gripper_logger.py
```

Start a cycle:

```sh
mosquitto_pub -t gripper/command/mode  -m auto
mosquitto_pub -t gripper/command/start -m 1
```

Watch the tags:

```sh
mosquitto_sub -h localhost -t 'gripper/#' -v
```

## Qt HMI

```sh
cd Gripper/hmi
cmake -S . -B build -DCMAKE_PREFIX_PATH=~/Qt/6.11.2/macos
cmake --build build
./build/appGripperHMI.app/Contents/MacOS/appGripperHMI
```

Shows a top view of the work envelope with pick/place stations, the tool and
the part, axis readouts, the PLC state, and Start / Stop / Reset. In **manual
mode** the X/Y/Z sliders and the Open/Close buttons drive the plant directly.

## Blender twin

```sh
cd Gripper/twin
blender --background --python create_gripper_blend.py   # build the scene once
blender --background --python setup_gripper_text.py     # install RUN_GRIPPER.py
```

Open `Gripper_Twin.blend`, switch to the Scripting workspace and run
**RUN_GRIPPER.py**. The beam follows Y, the carriage follows X, the tool
follows Z, the jaws open and close, and the part moves between stations. The
tool turns green while holding a part and red on a fault.

## Notes

- The plant and PLC are deliberately separate processes: the PLC never sees
  the simulation's internals, only the tag values — the same boundary a real
  PLC has against a digital plant model.
- The PLC has a 15 s timeout per step, so a missing plant or a jammed axis
  produces a `FAULT` state with an alarm instead of hanging forever.
- `gripper.db` is a local recording; it is git-ignored. Use
  `python3 historian/gripper_logger.py --stats` for a quick summary.
- To move the "PLC" onto real hardware later, replace `plc/gripper_plc.py`
  with CODESYS on the Pi and keep the same tag names — the HMI, twin and
  historian keep working unchanged.
