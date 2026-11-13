#!/usr/bin/env python3
"""PickLine plant: gantry feeds a conveyor that ends in two filling stations.

One plant owns the whole cell so it stays in lock-step:
  * a 3-axis gantry picks an empty container from one of two bins and drops it
    at the belt infeed,
  * the belt carries the container the full length; at the end it goes straight
    to fill station A or turns onto the side lane to fill station B,
  * each station fills the container (same volume, different speed) and then
    blocks until the full container is taken out manually.

The soft PLC in ../plc/pickline_plc.py drives it through MQTT target topics.

Run:
    python3 pickline_plant.py
    MQTT_BROKER=192.168.50.1 python3 pickline_plant.py
"""
import math
import json
import os
import random
import sqlite3
import sys
import threading
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot.kinematics import SixAxisRobot
from robot import geometry as G

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
DB_PATH = os.environ.get(
    "PICKLINE_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pickline.db"),
)

SPEED_MM_S = 140.0      # gantry axis travel speed
GRIP_TIME = 0.35        # seconds for the jaws to open or close
BELT_SPEED = 90.0       # default belt speed, mm/s
BELT_SPEED_MIN = 20.0
BELT_SPEED_MAX = 250.0
BELT_TIME = 0.30
DIVERT_TIME = 0.25
LOOP_HZ = 20.0

VOLUME = 100.0          # container capacity, units (same for every container)
VOLUME_MIN = 10.0
VOLUME_MAX = 500.0
FILL_A_PICKUPS = 2      # station A is full after 2 containers are poured in
FILL_B_PICKUPS = 5      # station B is full after 5 containers are poured in
PICKUPS_MIN = 1
PICKUPS_MAX = 10
POUR_TIME = 0.6         # seconds the pour stream is visible after a container

X_MAX, Y_MIN, Y_MAX, Z_MAX = 300.0, -100.0, 220.0, 100.0
PICK_DOWN = (260.0, 20.0, 0.0)
PICK_UP = (260.0, 190.0, 0.0)
DROP = (0.0, 100.0, 0.0)        # belt infeed (belt runs along y = 100)
PICK_TOL = 8.0
GRIP_OFFSET_Y = 170.0           # gripper B sits +170 mm above gripper A
DROP_B = (0.0, DROP[1] - GRIP_OFFSET_Y, 0.0)  # gantry pose so gripper B is at DROP

BELT_LEN = 400.0                # belt runs x = 0 .. 400 at y = 100
STRAIGHT_END = 460.0            # station A sits beyond the straight belt end
LEFT_END_Y = 240.0              # station B sits beyond the left lane end
SENSOR_IN_X = 30.0
SENSOR_OUT_X = 370.0
SENSOR_DIVERT_Y = 230.0
SENSOR_TOL = 6.0
INFEED_PITCH = 40.0            # belt infeed is considered clear past this x

ROBOT_JOINT_SPEED = 90.0     # deg/s
ROBOT_GRIP_TIME = 0.35       # seconds to open or close the gripper

lock = threading.Lock()

pos = [0.0, 0.0, 60.0]
target = [0.0, 0.0, 60.0]
grip = [1.0, 1.0]               # [A, B], 1 = open
grip_target = [1.0, 1.0]
held = [False, False]           # [A, B]
placed = 0

belt = 0.0
belt_target = 0.0
belt_speed = BELT_SPEED
diverter = 0.0
diverter_target = 0.0

parts = []                      # containers on the line: lane, x, y, type
exited = 0
scanned = ""                    # last type read by the belt scanner

volume = VOLUME
reject_rate = G.REJECT_RATE      # fraction of containers rejected at the gate
fill = {
    "a": {"state": "EMPTY", "level": 0.0, "filled": 0, "pickups": FILL_A_PICKUPS,
          "count": 0, "alarm": "", "pouring": 0, "pour_timer": 0.0},
    "b": {"state": "EMPTY", "level": 0.0, "filled": 0, "pickups": FILL_B_PICKUPS,
          "count": 0, "alarm": "", "pouring": 0, "pour_timer": 0.0},
}
total = 0.0
jam = False

sensor_in = 0
sensor_out = 0
sensor_divert = 0

last_published = {}

robot_model = SixAxisRobot()
robots = {
    "a": {
        "base": G.ROBOT_A_BASE, "pick": G.PICK_A, "place": G.OUTFEED_A_DROP,
        "joints": [0.0] * 6, "joint_targets": [0.0] * 6,
        "tcp": (0.0, 0.0, 0.0), "tcp_target": G.PICK_A,
        "gripper": 1.0, "gripper_target": 1.0,
        "holding": False, "busy": 0, "held_type": "A",
    },
    "b": {
        "base": G.ROBOT_B_BASE, "pick": G.PICK_B, "place": G.OUTFEED_B_DROP,
        "joints": [0.0] * 6, "joint_targets": [0.0] * 6,
        "tcp": (0.0, 0.0, 0.0), "tcp_target": G.PICK_B,
        "gripper": 1.0, "gripper_target": 1.0,
        "holding": False, "busy": 0, "held_type": "B",
    },
}
lines = {
    "a": {
        "outfeed": [],          # {"x": float, "ok": bool} containers on outfeed A
        "entered": 0,           # containers that entered lift A
        "lift_z": 0.0,
        "lift_state": "IDLE",   # IDLE, LOADING, RAISING, UNLOADING, RETURNING
        "stack": 0,             # containers stacked on the current pallet
        "pallets": 0,           # finished pallets that have left
        "timer": 0.0,
    },
    "b": {
        "outfeed": [],
        "entered": 0,
        "lift_z": 0.0,
        "lift_state": "IDLE",
        "stack": 0,
        "pallets": 0,
        "timer": 0.0,
    },
}
reject_bin = {"a": 0, "b": 0}   # rejected containers that reached the bin
rejects = []                    # {"line": "a"/"b", "x": x, "y": y} on the lane
dispatch = []                   # {"id": n, "ts": t, "line": k, "count": c}
pallet_seq = 0


def clamp(value, low, high):
    return max(low, min(high, value))


def near(xy, ref, tol):
    return math.hypot(xy[0] - ref[0], xy[1] - ref[1]) <= tol


def near3(point, ref, tol):
    return (math.hypot(point[0] - ref[0], point[1] - ref[1]) <= tol
            and abs(point[2] - ref[2]) <= tol)


def world_to_local(base, world):
    return (world[0] - base[0], world[1] - base[1], world[2] - base[2])


def local_to_world(base, local):
    return (local[0] + base[0], local[1] + base[1], local[2] + base[2])


def clear_station(key):
    st = fill[key]
    st["state"] = "EMPTY"
    st["level"] = 0.0
    st["filled"] = 0
    st["pouring"] = 0
    st["pour_timer"] = 0.0
    st["alarm"] = ""


def reset_plant():
    global placed, exited, total, jam, scanned, pallet_seq
    global reject_bin, rejects, dispatch
    placed = 0
    exited = 0
    scanned = ""
    total = 0.0
    jam = False
    parts.clear()
    for i in (0, 1):
        held[i] = False
        grip[i] = 1.0
        grip_target[i] = 1.0
    for key in ("a", "b"):
        fill[key]["state"] = "EMPTY"
        fill[key]["level"] = 0.0
        fill[key]["filled"] = 0
        fill[key]["count"] = 0
        fill[key]["alarm"] = ""
        fill[key]["pouring"] = 0
        fill[key]["pour_timer"] = 0.0
        lines[key]["outfeed"].clear()
        lines[key]["entered"] = 0
        lines[key]["lift_z"] = 0.0
        lines[key]["lift_state"] = "IDLE"
        lines[key]["stack"] = 0
        lines[key]["pallets"] = 0
        lines[key]["timer"] = 0.0
    reject_bin = {"a": 0, "b": 0}
    rejects.clear()
    dispatch.clear()
    pallet_seq = 0


def clear_belt():
    global placed
    removed = len(parts)
    parts.clear()
    placed = max(0, placed - removed)


_dispatch_con = None


def init_dispatch_db():
    global _dispatch_con
    try:
        _dispatch_con = sqlite3.connect(DB_PATH)
        _dispatch_con.execute(
            "CREATE TABLE IF NOT EXISTS dispatch ("
            "id INTEGER, ts REAL, line TEXT, count INTEGER)"
        )
        _dispatch_con.commit()
    except Exception as exc:
        print("Dispatch DB init failed:", repr(exc), flush=True)
        _dispatch_con = None


def record_dispatch(event):
    if _dispatch_con is None:
        return
    try:
        _dispatch_con.execute(
            "INSERT INTO dispatch (id, ts, line, count) VALUES (?,?,?,?)",
            (event["id"], event["ts"], event["line"], event["count"]),
        )
        _dispatch_con.commit()
    except Exception as exc:
        print("Dispatch DB write failed:", repr(exc), flush=True)


def on_connect(client, *_args):
    client.subscribe("pickline/target/#")
    client.subscribe("pickline/robot/+/target/#")
    client.subscribe("pickline/plant/reset")
    client.subscribe("pickline/fill/a/take")
    client.subscribe("pickline/fill/b/take")
    client.subscribe("pickline/fault/#")
    client.subscribe("pickline/clear_belt")
    client.subscribe("pickline/reject/clear")


def on_message(_client, _userdata, msg):
    global grip_target, belt_target, diverter_target, belt_speed, volume, jam
    global reject_rate
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "pickline/target/x":
                target[0] = clamp(float(payload), 0.0, X_MAX)
            elif msg.topic == "pickline/target/y":
                target[1] = clamp(float(payload), Y_MIN, Y_MAX)
            elif msg.topic == "pickline/target/z":
                target[2] = clamp(float(payload), 0.0, Z_MAX)
            elif msg.topic == "pickline/target/grip":
                value = 1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
                grip_target[0] = value
                grip_target[1] = value
            elif msg.topic == "pickline/target/grip_a":
                grip_target[0] = 1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
            elif msg.topic == "pickline/target/grip_b":
                grip_target[1] = 1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
            elif msg.topic == "pickline/target/belt":
                belt_target = 1.0 if payload.lower() in ("1", "true", "on", "run") else 0.0
            elif msg.topic == "pickline/target/diverter":
                diverter_target = 1.0 if payload.lower() in ("1", "true", "on", "divert") else 0.0
            elif msg.topic == "pickline/target/speed":
                belt_speed = clamp(float(payload), BELT_SPEED_MIN, BELT_SPEED_MAX)
            elif msg.topic == "pickline/target/volume":
                volume = clamp(float(payload), VOLUME_MIN, VOLUME_MAX)
            elif msg.topic == "pickline/target/reject_rate":
                reject_rate = clamp(float(payload), 0.0, 1.0)
            elif msg.topic == "pickline/target/fill/a/pickups":
                fill["a"]["pickups"] = int(clamp(float(payload), PICKUPS_MIN, PICKUPS_MAX))
            elif msg.topic == "pickline/target/fill/b/pickups":
                fill["b"]["pickups"] = int(clamp(float(payload), PICKUPS_MIN, PICKUPS_MAX))
            elif msg.topic == "pickline/fill/a/take":
                if payload.lower() in ("1", "true", "on", "take"):
                    if fill["a"]["state"] in ("FULL", "FAULT"):
                        fill["a"]["state"] = "EMPTY"
                        fill["a"]["level"] = 0.0
                        fill["a"]["filled"] = 0
                        fill["a"]["pouring"] = 0
                        fill["a"]["pour_timer"] = 0.0
                        fill["a"]["alarm"] = ""
            elif msg.topic == "pickline/fill/b/take":
                if payload.lower() in ("1", "true", "on", "take"):
                    if fill["b"]["state"] in ("FULL", "FAULT"):
                        fill["b"]["state"] = "EMPTY"
                        fill["b"]["level"] = 0.0
                        fill["b"]["filled"] = 0
                        fill["b"]["pouring"] = 0
                        fill["b"]["pour_timer"] = 0.0
                        fill["b"]["alarm"] = ""
            elif msg.topic == "pickline/plant/reset":
                reset_plant()
            elif msg.topic == "pickline/clear_belt":
                clear_belt()
            elif msg.topic == "pickline/reject/clear":
                reject_bin["a"] = 0
                reject_bin["b"] = 0
                rejects.clear()
                # Discard any reject-bound containers still waiting on the
                # outfeeds so nothing re-enters the bin right after clearing.
                for key in ("a", "b"):
                    lines[key]["outfeed"] = [
                        c for c in lines[key]["outfeed"] if c["ok"]
                    ]
            elif msg.topic == "pickline/fault/jam":
                jam = payload.lower() in ("1", "true", "on", "jam")
            elif msg.topic == "pickline/fault/clear":
                jam = False
            elif msg.topic.startswith("pickline/robot/") and "/target/" in msg.topic:
                parts = msg.topic.split("/")
                key = parts[2]
                axis = parts[4]
                rb = robots.get(key)
                if rb is not None:
                    if axis == "grip":
                        rb["gripper_target"] = (
                            1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
                        )
                    elif axis in ("x", "y", "z"):
                        idx = {"x": 0, "y": 1, "z": 2}[axis]
                        tcp = list(rb["tcp_target"])
                        tcp[idx] = float(payload)
                        rb["tcp_target"] = tuple(tcp)
        except ValueError:
            pass
        except BaseException as exc:
            print("Plant on_message error:", repr(exc), flush=True)


def enter_station(part, key):
    global exited, total
    st = fill[key]
    st["filled"] += 1
    st["level"] = st["filled"] * volume
    st["pouring"] = 1
    st["pour_timer"] = POUR_TIME
    if st["filled"] >= st["pickups"]:
        st["state"] = "FULL"
        st["count"] += 1
        total += st["level"]
    else:
        st["state"] = "FILLING"
    part["lane"] = "done"
    exited += 1


def step(dt):
    global placed, belt, diverter, total, sensor_in, sensor_out, sensor_divert
    global scanned, diverter_target, pallet_seq

    with lock:
        for i in range(3):
            error = target[i] - pos[i]
            max_step = SPEED_MM_S * dt
            if abs(error) <= max_step:
                pos[i] = target[i]
            else:
                pos[i] += math.copysign(max_step, error)

        # Two grippers open/close independently (A lower, B upper by +Y).
        for i in (0, 1):
            if grip[i] < grip_target[i]:
                grip[i] = min(grip_target[i], grip[i] + dt / GRIP_TIME)
            elif grip[i] > grip_target[i]:
                grip[i] = max(grip_target[i], grip[i] - dt / GRIP_TIME)

        # Gripper A picks the DOWN bin (type A); gripper B, offset +Y, picks UP.
        if grip[0] <= 0.05 and not held[0] and pos[2] <= 5.0:
            if near(pos, PICK_DOWN, PICK_TOL):
                held[0] = True
        if grip[1] <= 0.05 and not held[1] and pos[2] <= 5.0:
            if near(pos, PICK_DOWN, PICK_TOL):
                held[1] = True

        # Gripper A releases at the belt infeed.
        if grip[0] >= 0.95 and held[0] and near(pos, DROP, PICK_TOL) and pos[2] <= 5.0:
            held[0] = False
            placed += 1
            parts.append({"lane": "belt", "x": 0.0, "y": DROP[1],
                          "type": "A", "route": "straight"})
        # Gripper B releases at the belt infeed (gantry sits at DROP_B).
        if grip[1] >= 0.95 and held[1] and near(pos, DROP_B, PICK_TOL) and pos[2] <= 5.0:
            held[1] = False
            placed += 1
            parts.append({"lane": "belt", "x": 0.0, "y": DROP[1],
                          "type": "B", "route": "left"})

        if belt < belt_target:
            belt = min(belt_target, belt + dt / BELT_TIME)
        elif belt > belt_target:
            belt = max(belt_target, belt - dt / BELT_TIME)

        if diverter < diverter_target:
            diverter = min(diverter_target, diverter + dt / DIVERT_TIME)
        elif diverter > diverter_target:
            diverter = max(diverter_target, diverter - dt / DIVERT_TIME)

        speed = belt_speed * belt
        part_speed = 0.0 if jam else speed

        # Move every container along the line. Each container carries its own
        # route (straight -> station A, left -> station B), so several
        # containers can share the belt at once. The diverter gate still swings
        # to match each container as it reaches the end of the belt.
        for part in parts:
            if part["lane"] == "belt":
                part["x"] += part_speed * dt
                if part["x"] >= BELT_LEN:
                    if part.get("route", "straight") == "left":
                        diverter_target = 1.0
                        part["lane"] = "left"
                        part["x"] = BELT_LEN
                        part["y"] = DROP[1]
                    else:
                        diverter_target = 0.0
                        part["lane"] = "straight"
                        part["y"] = DROP[1]
            elif part["lane"] == "straight":
                part["x"] += part_speed * dt
                if part["x"] >= STRAIGHT_END:
                    if fill["a"]["state"] not in ("FULL", "FAULT"):
                        enter_station(part, "a")
                    else:
                        part["lane"] = "wait_a"
                        part["x"] = STRAIGHT_END
            elif part["lane"] == "left":
                part["y"] += part_speed * dt
                if part["y"] >= LEFT_END_Y:
                    if fill["b"]["state"] not in ("FULL", "FAULT"):
                        enter_station(part, "b")
                    else:
                        part["lane"] = "wait_b"
                        part["y"] = LEFT_END_Y
            elif part["lane"] == "wait_a":
                if fill["a"]["state"] not in ("FULL", "FAULT"):
                    enter_station(part, "a")
            elif part["lane"] == "wait_b":
                if fill["b"]["state"] not in ("FULL", "FAULT"):
                    enter_station(part, "b")

        parts[:] = [p for p in parts if p["lane"] != "done"]

        # Track the pour animation and detect overfill at each station.
        for key in ("a", "b"):
            st = fill[key]
            if st["pour_timer"] > 0:
                st["pour_timer"] -= dt
                if st["pour_timer"] <= 0:
                    st["pour_timer"] = 0.0
                    st["pouring"] = 0

            # Overfill: volume or pickups were lowered below the current level.
            if st["state"] != "FAULT" and st["level"] > st["pickups"] * volume + 0.5:
                st["state"] = "FAULT"
                st["alarm"] = "OVERFILL"
                st["pouring"] = 0

        sensor_in = 1 if any(p["lane"] == "belt" and abs(p["x"] - SENSOR_IN_X) < SENSOR_TOL for p in parts) else 0
        sensor_out = 1 if any(p["lane"] == "belt" and abs(p["x"] - SENSOR_OUT_X) < SENSOR_TOL for p in parts) else 0
        sensor_divert = 1 if any(p["lane"] == "left" and abs(p["y"] - SENSOR_DIVERT_Y) < SENSOR_TOL for p in parts) else 0
        for p in parts:
            if p["lane"] == "belt" and abs(p["x"] - SENSOR_IN_X) < SENSOR_TOL:
                scanned = p["type"]

        # Six-axis tending robots: move joints toward the TCP target, operate
        # the gripper, and unload full containers onto the outfeed conveyor.
        for key, rb in robots.items():
            local_target = world_to_local(rb["base"], rb["tcp_target"])
            rb["joint_targets"] = robot_model.inverse(local_target)

            busy = 0
            max_step = math.radians(ROBOT_JOINT_SPEED) * dt
            for i in range(6):
                error = rb["joint_targets"][i] - rb["joints"][i]
                if abs(error) <= max_step:
                    rb["joints"][i] = rb["joint_targets"][i]
                else:
                    rb["joints"][i] += math.copysign(max_step, error)
                    busy = 1
            rb["busy"] = busy

            local = robot_model.forward(rb["joints"])
            rb["tcp"] = local_to_world(rb["base"], local)

            if rb["gripper"] < rb["gripper_target"]:
                rb["gripper"] = min(rb["gripper_target"], rb["gripper"] + dt / ROBOT_GRIP_TIME)
            elif rb["gripper"] > rb["gripper_target"]:
                rb["gripper"] = max(rb["gripper_target"], rb["gripper"] - dt / ROBOT_GRIP_TIME)

            # Close the gripper over a full station to take the container.
            if rb["gripper"] <= 0.05 and not rb["holding"]:
                if (near3(rb["tcp"], rb["pick"], G.GRIP_TOL)
                        and fill[key]["state"] in ("FULL", "FAULT")):
                    clear_station(key)
                    rb["holding"] = True
                    rb["held_type"] = "A" if key == "a" else "B"

            # Open the gripper over the station's own outfeed drop point.
            if rb["gripper"] >= 0.95 and rb["holding"]:
                if near3(rb["tcp"], rb["place"], G.GRIP_TOL):
                    clear = all(
                        abs(c["x"] - rb["place"][0]) >= G.OUTFEED_PITCH
                        for c in lines[key]["outfeed"]
                    )
                    if clear:
                        rb["holding"] = False
                        lines[key]["outfeed"].append({
                            "x": rb["place"][0],
                            "ok": random.random() >= reject_rate,
                        })

        # Outfeed conveyors, quality gate, and lifts.
        for key, line in lines.items():
            lift_x = G.OUTFEED_A_LIFT_X if key == "a" else G.OUTFEED_B_LIFT_X
            line_y = G.OUTFEED_A_Y if key == "a" else G.OUTFEED_B_Y

            # Advance the outfeed. Rejects divert to the reject lane at the
            # inspection point; good containers continue to the lift.
            advanced = []
            for c in line["outfeed"]:
                nx = c["x"] + G.OUTFEED_SPEED * dt
                if not c["ok"] and nx >= G.INSPECT_X:
                    if reject_bin["a"] + reject_bin["b"] < G.REJECT_FULL:
                        rejects.append({"line": key, "x": G.INSPECT_X, "y": line_y})
                    else:
                        # Bin is full: hold the reject at the inspection gate.
                        advanced.append({"x": G.INSPECT_X, "ok": False})
                elif nx >= lift_x:
                    if line["lift_state"] == "IDLE":
                        line["lift_state"] = "LOADING"
                        line["timer"] = 0.0
                        line["entered"] += 1
                    else:
                        advanced.append({"x": lift_x, "ok": True})
                else:
                    advanced.append({"x": nx, "ok": c["ok"]})
            line["outfeed"] = advanced

            # Lift / palletizer state machine: collect containers onto a pallet
            # at the bottom, then raise the lift only once the pallet is full.
            if line["lift_state"] == "LOADING":
                line["timer"] += dt
                if line["timer"] >= G.LIFT_LOAD_TIME:
                    line["stack"] += 1
                    line["timer"] = 0.0
                    if line["stack"] >= G.PALLET_TARGET[key]:
                        line["lift_state"] = "RAISING"
                    else:
                        line["lift_state"] = "IDLE"
            elif line["lift_state"] == "RAISING":
                line["lift_z"] = min(G.LIFT_TOP_Z, line["lift_z"] + G.LIFT_SPEED * dt)
                if line["lift_z"] >= G.LIFT_TOP_Z:
                    line["timer"] = 0.0
                    line["lift_state"] = "UNLOADING"
            elif line["lift_state"] == "UNLOADING":
                line["timer"] += dt
                if line["timer"] >= G.LIFT_UNLOAD_TIME:
                    line["pallets"] += 1
                    line["stack"] = 0
                    line["timer"] = 0.0
                    line["lift_state"] = "RETURNING"
                    pallet_seq += 1
                    event = {"id": pallet_seq, "ts": time.time(), "line": key,
                             "count": G.PALLET_TARGET[key]}
                    dispatch.append(event)
                    record_dispatch(event)
            elif line["lift_state"] == "RETURNING":
                line["lift_z"] = max(0.0, line["lift_z"] - G.LIFT_SPEED * dt)
                if line["lift_z"] <= 0.0:
                    line["lift_z"] = 0.0
                    line["lift_state"] = "IDLE"

        # Reject lane: carry rejected containers to the shared middle bin.
        for r in rejects:
            target_y = G.REJECT_BIN[1]
            step_y = G.REJECT_SPEED * dt
            if r["line"] == "a":
                r["y"] = min(target_y, r["y"] + step_y)
            else:
                r["y"] = max(target_y, r["y"] - step_y)
            if abs(r["y"] - target_y) < 0.5:
                # The bin has a capacity; once full, keep the reject waiting
                # at the bin instead of counting it in.
                if reject_bin["a"] + reject_bin["b"] < G.REJECT_FULL:
                    reject_bin[r["line"]] += 1
                    r["done"] = True
        rejects[:] = [r for r in rejects if not r.get("done")]


def snapshot():
    with lock:
        busy = any(abs(target[i] - pos[i]) > 0.2 for i in range(3))

        def part_state(idx, type_key):
            if held[idx]:
                gy = pos[1] + (GRIP_OFFSET_Y if idx == 1 else 0.0)
                return pos[0], gy, pos[2]
            for p in parts:
                if p["type"] == type_key:
                    return p["x"], p["y"], 0.0
            return -1.0, -1.0, -1.0

        ax, ay, az = part_state(0, "A")
        bx, by, bz = part_state(1, "B")
        belt_part = next((p for p in parts if p["lane"] == "belt"), None)
        belt_pos = belt_part["x"] if belt_part else -1.0
        belt_infeed_clear = 1
        for p in parts:
            if p["lane"] == "belt" and p["x"] < INFEED_PITCH:
                belt_infeed_clear = 0

        values = {
            "pickline/x": "%.2f" % pos[0],
            "pickline/y": "%.2f" % pos[1],
            "pickline/z": "%.2f" % pos[2],
            "pickline/grip_a": "%.2f" % grip[0],
            "pickline/grip_b": "%.2f" % grip[1],
            "pickline/holding_a": "1" if held[0] else "0",
            "pickline/holding_b": "1" if held[1] else "0",
            "pickline/part_a/x": "%.2f" % ax,
            "pickline/part_a/y": "%.2f" % ay,
            "pickline/part_a/z": "%.2f" % az,
            "pickline/part_a/type": "A",
            "pickline/part_a/on_line": "1" if ax >= 0 else "0",
            "pickline/part_b/x": "%.2f" % bx,
            "pickline/part_b/y": "%.2f" % by,
            "pickline/part_b/z": "%.2f" % bz,
            "pickline/part_b/type": "B",
            "pickline/part_b/on_line": "1" if bx >= 0 else "0",
            "pickline/scanned": scanned,
            "pickline/belt": "%.2f" % belt,
            "pickline/belt_pos": "%.1f" % belt_pos,
            "pickline/belt_infeed_clear": "1" if belt_infeed_clear else "0",
            "pickline/speed": "%.0f" % belt_speed,
            "pickline/diverter": "%.2f" % diverter,
            "pickline/sensor_in": "1" if sensor_in else "0",
            "pickline/sensor_out": "1" if sensor_out else "0",
            "pickline/sensor_divert": "1" if sensor_divert else "0",
            "pickline/placed": str(placed),
            "pickline/exited": str(exited),
            "pickline/busy": "1" if busy else "0",
            "pickline/volume": "%.0f" % volume,
            "pickline/reject_rate": "%.2f" % reject_rate,
            "pickline/fill/total": "%.1f" % total,
            "pickline/jam": "1" if jam else "0",
        }
        for key in ("a", "b"):
            st = fill[key]
            values["pickline/fill/%s/state" % key] = st["state"]
            values["pickline/fill/%s/level" % key] = "%.1f" % st["level"]
            values["pickline/fill/%s/count" % key] = str(st["count"])
            values["pickline/fill/%s/pickups" % key] = str(st["pickups"])
            values["pickline/fill/%s/filled" % key] = str(st["filled"])
            values["pickline/fill/%s/pouring" % key] = "1" if st["pouring"] else "0"
            values["pickline/fill/%s/alarm" % key] = st["alarm"]

        for key, rb in robots.items():
            for i, joint in enumerate(rb["joints"]):
                values["pickline/robot/%s/joint/%d" % (key, i + 1)] = (
                    "%.2f" % math.degrees(joint)
                )
            values["pickline/robot/%s/tcp/x" % key] = "%.2f" % rb["tcp"][0]
            values["pickline/robot/%s/tcp/y" % key] = "%.2f" % rb["tcp"][1]
            values["pickline/robot/%s/tcp/z" % key] = "%.2f" % rb["tcp"][2]
            values["pickline/robot/%s/gripper" % key] = "%.2f" % rb["gripper"]
            values["pickline/robot/%s/holding" % key] = "1" if rb["holding"] else "0"
            values["pickline/robot/%s/busy" % key] = str(rb["busy"])

        for key, line in lines.items():
            drop_x = G.OUTFEED_A_DROP[0] if key == "a" else G.OUTFEED_B_DROP[0]
            infeed_clear = all(
                abs(c["x"] - drop_x) >= G.OUTFEED_PITCH for c in line["outfeed"]
            )
            values["pickline/outfeed/%s/count" % key] = str(line["entered"])
            values["pickline/outfeed/%s/queued" % key] = str(len(line["outfeed"]))
            values["pickline/outfeed/%s/infeed_clear" % key] = (
                "1" if infeed_clear else "0"
            )
            values["pickline/outfeed/%s/positions" % key] = ",".join(
                "%.1f" % c["x"] for c in line["outfeed"]
            )
            values["pickline/lift/%s/z" % key] = "%.1f" % line["lift_z"]
            values["pickline/lift/%s/state" % key] = line["lift_state"]
            values["pickline/lift/%s/stack" % key] = str(line["stack"])
            values["pickline/lift/%s/pallets" % key] = str(line["pallets"])
        values["pickline/reject/a"] = str(reject_bin["a"])
        values["pickline/reject/b"] = str(reject_bin["b"])
        values["pickline/reject/total"] = str(reject_bin["a"] + reject_bin["b"])
        values["pickline/reject/full"] = (
            "1" if reject_bin["a"] + reject_bin["b"] >= G.REJECT_FULL else "0"
        )
        values["pickline/reject/items"] = json.dumps(rejects)
        values["pickline/pallet/dispatched"] = str(len(dispatch))
        values["pickline/pallet/last"] = (
            json.dumps(dispatch[-1]) if dispatch else ""
        )
        values["pickline/pallet/queue"] = (
            json.dumps(dispatch[-8:]) if dispatch else "[]"
        )
        return values


def publish(client, values):
    for topic, payload in values.items():
        if last_published.get(topic) != payload:
            client.publish(topic, payload, retain=True)
            last_published[topic] = payload


def on_disconnect(_cli, _userdata, rc, *_args):
    print("Plant MQTT disconnected (rc=%s); reconnecting automatically" % rc,
          flush=True)


def main():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.max_queued_messages_set(20)

    while True:
        try:
            client.connect(BROKER, PORT, 60)
            break
        except Exception as exc:
            print("Plant connect failed (%s); retrying in 2s" % exc, flush=True)
            time.sleep(2)

    client.loop_start()
    init_dispatch_db()
    print("PickLine plant running (broker %s:%d)" % (BROKER, PORT))

    period = 1.0 / LOOP_HZ
    last = time.monotonic()
    last_alive = 0.0
    last_full = 0.0
    while True:
        now = time.monotonic()
        step(min(now - last, 0.2))
        last = now
        publish(client, snapshot())
        if now - last_alive >= 1.0:
            client.publish("pickline/plant/alive", "%.0f" % time.time(), retain=True)
            last_alive = now
        if now - last_full >= 1.0:
            # Force a full re-publish so clients never miss a state change.
            for topic, payload in snapshot().items():
                client.publish(topic, payload, retain=True)
            last_full = now
        time.sleep(max(0.0, period - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
