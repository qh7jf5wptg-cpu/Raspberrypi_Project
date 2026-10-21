# OPC UA bridge

Exposes the PickLine MQTT tag space as a standard **OPC UA** address space, so
industrial clients (TwinCAT, CODESYS, UaExpert, SCADA) can monitor and control
the cell.

```
plant ──MQTT── PLC ──MQTT── HMI / Blender / historian / dashboard
                │
                └── opcua_server.py ──OPC UA── TwinCAT / UaExpert / SCADA
```

## Run

On the Pi (or Mac), next to the plant and PLC:

```sh
pip install asyncua
python3 opcua/opcua_server.py
```

Environment variables:

| Variable | Default |
| --- | --- |
| `MQTT_BROKER` | `localhost` |
| `MQTT_PORT` | `1883` |
| `OPCUA_ENDPOINT` | `opc.tcp://0.0.0.0:4840` |

## Address space

Under `Objects > PickLine`:

| Folder | Nodes |
| --- | --- |
| `Status` | state, mode, side, route_mode, decision, alarm, paused, estop |
| `Gantry` | x, y, z, grip, holding |
| `Conveyor` | belt, speed, diverter, part_x, part_y, part_on_line |
| `Production` | placed, exited, volume, fill_total |
| `FillA` | level, state, count, filled, pickups |
| `FillB` | level, state, count, filled, pickups |
| `Settings` (writable) | speed, volume, gap, fill_a_pickups, fill_b_pickups, mode, route, side |
| `Commands` (writable booleans) | start, stop, reset, pause, resume, estop, clear_belt, take_a, take_b |

Settings publish to MQTT when written. Command nodes are edge-triggered: write
`True` and the bridge publishes the command then resets the node to `False`.

## Check with UaExpert

1. Install and open [UaExpert](https://www.unified-automation.com/products/development-tools/uaexpert.html).
2. Add server: URL `opc.tcp://192.168.50.2:4840` (Pi) or `opc.tcp://localhost:4840` (Mac).
3. Security policy: **None** / anonymous (the bridge has no certificate).
4. Browse to `Objects > PickLine` and read the tags; write to `Settings.*` or
   `Commands.*` to control the cell.

## Quick smoke test (no UaExpert)

```sh
python3 opcua/opcua_client_test.py
```

For a fuller browse/read/write without a GUI client (works on macOS and
Raspberry Pi, which have no UaExpert build):

```sh
python3 opcua/opcua_browse.py                    # dump the whole tree + values
python3 opcua/opcua_browse.py --read Status/state
python3 opcua/opcua_browse.py --write Settings/gap 2.5
python3 opcua/opcua_browse.py --write-bool Commands/take_a true
```
