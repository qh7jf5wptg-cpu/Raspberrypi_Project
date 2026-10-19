# Conveyor — Digital Twin with a Diverter

A small sorting-line digital twin: a conveyor belt carries parts past two
sensors, and a diverter gate pushes selected parts onto a side lane.

```
   plant model            soft PLC            clients
  ┌────────────┐        ┌────────────┐       ┌──────────────────┐
  │ conveyor_  │◀target▶│ conveyor_  │       │ Qt HMI (QML/C++) │
  │ plant.py   │   MQTT │ plc.py     │◀─────▶│ Blender 3D twin  │
  └────────────┘        └────────────┘       │ SQLite historian │
        └──────────── conveyor/# ────────────┴──────────────────┘
```

## The machine

- **Belt** — moves parts along X at 90 mm/s (0–400 mm).
- **Sensor 1** (upstream, x = 120 mm) — sees each part arrive.
- **Diverter gate** (x = 250 mm) — extends to push a part onto the side lane.
- **Sensor 2** (downstream, x = 340 mm) — sees only the parts that went
  straight through.

The PLC decides, part by part, whether to divert. Modes:

| Mode | Behaviour |
| --- | --- |
| `manual` | PLC stands back; the HMI drives the belt and diverter directly |
| `alternate` | divert every other part |
| `divert_all` | divert every part |
| `pass_all` | never divert |

## Topic contract

Sensors and state (plant → everyone):

| Topic | Meaning |
| --- | --- |
| `conveyor/sensor1`, `sensor2` | 1 while a part is in front of the sensor |
| `conveyor/part_x`, `part_y` | part position, mm |
| `conveyor/diverter` | 0 straight, 1 diverting |
| `conveyor/belt` | 0 stopped, 1 running |
| `conveyor/passed` | parts that went straight (sensor 2) |
| `conveyor/diverted` | parts pushed onto the side lane |

Actuators (PLC or HMI → plant):

| Topic | Meaning |
| --- | --- |
| `conveyor/target/diverter` | 0 / 1 |
| `conveyor/target/belt` | 0 / 1 |
| `conveyor/command/reset` | reset counters |

PLC status and commands:

| Topic | Meaning |
| --- | --- |
| `conveyor/state` | IDLE / RUNNING |
| `conveyor/decision` | STRAIGHT / DIVERT (current part) |
| `conveyor/mode` | alternate / divert_all / pass_all |
| `conveyor/command/start`, `stop`, `reset`, `mode` | control |

## Run it

```sh
brew services start mosquitto          # once

cd Conveyor
python3 plant/conveyor_plant.py        # machine simulation
python3 plc/conveyor_plc.py            # soft PLC
python3 historian/conveyor_logger.py   # optional

mosquitto_pub -t conveyor/command/mode  -m alternate
mosquitto_pub -t conveyor/command/start -m 1
```

Watch: `mosquitto_sub -h localhost -t 'conveyor/#' -v`

## Qt HMI

```sh
cd Conveyor/hmi
cmake -S . -B build -DCMAKE_PREFIX_PATH=~/Qt/6.11.2/macos
cmake --build build
open build/appConveyorHMI.app
```

Top view of the belt with the two sensors, the gate, the part, plus Start /
Stop / Reset, a mode button, and manual belt/diverter controls.

## Blender twin

```sh
cd Conveyor/twin
blender --background --python create_conveyor_blend.py
blender --background --python setup_conveyor_text.py
```

Open `Conveyor_Twin.blend` and run **RUN_CONVEYOR.py**. The part slides along
the belt, the gate extends for divert, the two sensor markers light up green,
and the status line shows the state, decision and counts.
