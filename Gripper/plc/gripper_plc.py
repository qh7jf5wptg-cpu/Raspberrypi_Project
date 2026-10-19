#!/usr/bin/env python3
"""Soft PLC for the Gripper digital twin.

Runs the pick-and-place sequence as a small state machine and drives the plant
model in ../plant/gripper_plant.py through MQTT target topics.

Commands:
    mosquitto_pub -t gripper/command/mode  -m auto
    mosquitto_pub -t gripper/command/start -m 1
    mosquitto_pub -t gripper/command/stop  -m 1
    mosquitto_pub -t gripper/command/reset -m 1
"""
import math
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
LOOP_HZ = 10.0

PICK = (20.0, 20.0, 0.0)
PLACE = (280.0, 180.0, 0.0)
HOME = (0.0, 0.0, 60.0)
TRAVEL_Z = 60.0
TOL = 2.0               # mm
STEP_TIMEOUT = 15.0     # seconds

# (state name, kind, argument)
SEQUENCE = [
    ("TO_PICK", "move", (PICK[0], PICK[1], TRAVEL_Z)),
    ("LOWER_PICK", "move", PICK),
    ("GRIP", "grip", 0),
    ("LIFT_PICK", "move", (PICK[0], PICK[1], TRAVEL_Z)),
    ("TO_PLACE", "move", (PLACE[0], PLACE[1], TRAVEL_Z)),
    ("LOWER_PLACE", "move", PLACE),
    ("RELEASE", "grip", 1),
    ("LIFT_PLACE", "move", (PLACE[0], PLACE[1], TRAVEL_Z)),
    ("HOME", "move", HOME),
]

lock = threading.Lock()
client = None

tags = {"x": 0.0, "y": 0.0, "z": 60.0, "busy": 0, "part": 0, "placed": 0}
state = "IDLE"
mode = "auto"
started = False
count = 0
alarm = ""
step_idx = 0
step_started = 0.0
last = {}


def distance_to_xy(pos, ref):
    return math.hypot(pos[0] - ref[0], pos[1] - ref[1])


def at_target():
    """True when the plant is idle and sitting on the commanded point."""
    name, kind, arg = SEQUENCE[step_idx]
    if tags["busy"] != 0:
        return False
    if kind != "move":
        return True
    return (abs(tags["x"] - arg[0]) <= TOL
            and abs(tags["y"] - arg[1]) <= TOL
            and abs(tags["z"] - arg[2]) <= TOL)


def enter_step(index, now):
    global step_idx, step_started, state
    step_idx = index
    step_started = now
    name, kind, arg = SEQUENCE[index]
    state = name
    if kind == "move":
        client.publish("gripper/target/x", "%.1f" % arg[0], retain=True)
        client.publish("gripper/target/y", "%.1f" % arg[1], retain=True)
        client.publish("gripper/target/z", "%.1f" % arg[2], retain=True)
    else:
        client.publish("gripper/target/grip", str(arg), retain=True)


def hold_position():
    client.publish("gripper/target/x", "%.1f" % tags["x"], retain=True)
    client.publish("gripper/target/y", "%.1f" % tags["y"], retain=True)
    client.publish("gripper/target/z", "%.1f" % tags["z"], retain=True)


def on_connect(cli, *_args):
    cli.subscribe("gripper/x")
    cli.subscribe("gripper/y")
    cli.subscribe("gripper/z")
    cli.subscribe("gripper/busy")
    cli.subscribe("gripper/part")
    cli.subscribe("gripper/placed")
    cli.subscribe("gripper/command/#")


def on_message(_cli, _userdata, msg):
    global mode, started, count, alarm, step_idx, state
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "gripper/x":
                tags["x"] = float(payload)
            elif msg.topic == "gripper/y":
                tags["y"] = float(payload)
            elif msg.topic == "gripper/z":
                tags["z"] = float(payload)
            elif msg.topic == "gripper/busy":
                tags["busy"] = int(float(payload or 0))
            elif msg.topic == "gripper/part":
                tags["part"] = int(float(payload or 0))
            elif msg.topic == "gripper/placed":
                tags["placed"] = int(float(payload or 0))
        except ValueError:
            return

        if msg.topic == "gripper/command/start":
            if mode == "auto":
                started = True
                alarm = ""
                enter_step(0, time.monotonic())
        elif msg.topic == "gripper/command/stop":
            started = False
            state = "IDLE"
            hold_position()
        elif msg.topic == "gripper/command/reset":
            started = False
            count = 0
            alarm = ""
            step_idx = 0
            state = "IDLE"
        elif msg.topic == "gripper/command/mode":
            mode = "manual" if payload.lower().startswith("m") else "auto"
            if mode == "manual":
                started = False
                state = "IDLE"


def tick(now):
    global step_idx, count, started, alarm, state
    with lock:
        if mode != "auto" or not started:
            return

        name, kind, arg = SEQUENCE[step_idx]

        if kind == "grip":
            done = (tags["part"] == 1) if arg == 0 else (tags["part"] == 0)
        else:
            done = at_target()

        if done:
            step_idx += 1
            if step_idx >= len(SEQUENCE):
                count += 1
                step_idx = 0
            enter_step(step_idx, now)
        elif now - step_started > STEP_TIMEOUT:
            started = False
            state = "FAULT"
            alarm = "Timeout in " + name


def publish_status():
    values = {
        "gripper/state": state,
        "gripper/count": str(count),
        "gripper/alarm": alarm,
        "gripper/mode": mode,
    }
    for topic, payload in values.items():
        if last.get(topic) != payload:
            client.publish(topic, payload, retain=True)
            last[topic] = payload


def main():
    global client
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.loop_start()

    print("Gripper PLC running (broker %s:%d)" % (BROKER, PORT))
    publish_status()

    period = 1.0 / LOOP_HZ
    last_alive = 0.0
    while True:
        tick(time.monotonic())
        publish_status()
        if time.monotonic() - last_alive >= 1.0:
            client.publish("gripper/plc/alive", "%.0f" % time.time(), retain=True)
            last_alive = time.monotonic()
        time.sleep(period)


if __name__ == "__main__":
    main()
