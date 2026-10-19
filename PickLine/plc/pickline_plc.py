#!/usr/bin/env python3
"""Soft PLC for the PickLine: gripper feeds a conveyor, one part at a time.

Auto sequence:
    pick a part from the bin -> carry it to the belt infeed -> release ->
    wait until that part exits the belt -> wait the gap -> pick the next one.

The gap (seconds between a part leaving the belt and the next pick) is
adjustable at runtime.

Commands:
    mosquitto_pub -t pickline/command/mode  -m auto|manual
    mosquitto_pub -t pickline/command/gap   -m 2.5
    mosquitto_pub -t pickline/command/start -m 1
    mosquitto_pub -t pickline/command/stop  -m 1
    mosquitto_pub -t pickline/command/reset -m 1
"""
import math
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
LOOP_HZ = 10.0

PICK = (260.0, 20.0, 0.0)
DROP = (0.0, 100.0, 0.0)
HOME = (0.0, 0.0, 60.0)
TRAVEL_Z = 60.0
TOL = 2.0               # mm
STEP_TIMEOUT = 15.0     # seconds per motion step
WAIT_TIMEOUT = 30.0     # seconds to wait for a part to exit the belt
DEFAULT_GAP = 1.5       # seconds between exit and the next pick

# (state name, kind, argument)
SEQUENCE = [
    ("TO_PICK",    "move", (PICK[0], PICK[1], TRAVEL_Z)),
    ("LOWER_PICK", "move", PICK),
    ("GRIP",       "grip", 0),
    ("LIFT_PICK",  "move", (PICK[0], PICK[1], TRAVEL_Z)),
    ("TO_DROP",    "move", (DROP[0], DROP[1], TRAVEL_Z)),
    ("LOWER_DROP", "move", DROP),
    ("RELEASE",    "grip", 1),
    ("LIFT_DROP",  "move", (DROP[0], DROP[1], TRAVEL_Z)),
    ("WAIT_EXIT",  "wait_exit", None),
]

lock = threading.Lock()
client = None

tags = {"x": 0.0, "y": 0.0, "z": 60.0, "busy": 0, "holding": 0, "exited": 0}
state = "IDLE"
mode = "auto"
started = False
gap = DEFAULT_GAP
alarm = ""
step_idx = 0
step_started = 0.0

# WAIT_EXIT bookkeeping.
exit_base = 0
part_exited = False
part_exited_at = 0.0

last = {}


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
    global exit_base, part_exited, part_exited_at
    step_idx = index
    step_started = now
    name, kind, arg = SEQUENCE[index]
    state = name
    if kind == "move":
        client.publish("pickline/target/x", "%.1f" % arg[0], retain=True)
        client.publish("pickline/target/y", "%.1f" % arg[1], retain=True)
        client.publish("pickline/target/z", "%.1f" % arg[2], retain=True)
    elif kind == "grip":
        client.publish("pickline/target/grip", str(arg), retain=True)
    elif kind == "wait_exit":
        exit_base = tags["exited"]
        part_exited = False
        part_exited_at = 0.0


def hold_position():
    client.publish("pickline/target/x", "%.1f" % tags["x"], retain=True)
    client.publish("pickline/target/y", "%.1f" % tags["y"], retain=True)
    client.publish("pickline/target/z", "%.1f" % tags["z"], retain=True)


def start_auto():
    global started, alarm, exit_base, part_exited, part_exited_at
    started = True
    alarm = ""
    # Clear the line so exactly one part is in flight per cycle.
    client.publish("pickline/plant/reset", "1", retain=False)
    client.publish("pickline/target/belt", "1", retain=True)
    exit_base = 0
    part_exited = False
    part_exited_at = 0.0
    enter_step(0, time.monotonic())


def on_connect(cli, *_args):
    cli.subscribe("pickline/x")
    cli.subscribe("pickline/y")
    cli.subscribe("pickline/z")
    cli.subscribe("pickline/busy")
    cli.subscribe("pickline/holding")
    cli.subscribe("pickline/exited")
    cli.subscribe("pickline/command/#")


def on_message(_cli, _userdata, msg):
    global mode, started, state, gap, alarm, step_idx
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "pickline/x":
                tags["x"] = float(payload)
            elif msg.topic == "pickline/y":
                tags["y"] = float(payload)
            elif msg.topic == "pickline/z":
                tags["z"] = float(payload)
            elif msg.topic == "pickline/busy":
                tags["busy"] = int(float(payload or 0))
            elif msg.topic == "pickline/holding":
                tags["holding"] = int(float(payload or 0))
            elif msg.topic == "pickline/exited":
                tags["exited"] = int(float(payload or 0))
        except ValueError:
            pass

        if msg.topic == "pickline/command/start":
            if mode == "auto":
                start_auto()
        elif msg.topic == "pickline/command/stop":
            started = False
            state = "IDLE"
            hold_position()
            client.publish("pickline/target/belt", "0", retain=True)
        elif msg.topic == "pickline/command/reset":
            started = False
            alarm = ""
            step_idx = 0
            state = "IDLE"
            client.publish("pickline/target/belt", "0", retain=True)
            client.publish("pickline/plant/reset", "1", retain=False)
        elif msg.topic == "pickline/command/mode":
            mode = "manual" if payload.lower().startswith("m") else "auto"
            if mode == "manual":
                started = False
                state = "MANUAL"
                hold_position()
            else:
                state = "IDLE"
        elif msg.topic == "pickline/command/gap":
            try:
                gap = max(0.0, min(30.0, float(payload)))
            except ValueError:
                pass


def step_done(now):
    """True when the current sequence step is complete."""
    global part_exited, part_exited_at
    name, kind, arg = SEQUENCE[step_idx]
    if kind == "grip":
        return (tags["holding"] == 1) if arg == 0 else (tags["holding"] == 0)
    if kind == "wait_exit":
        if not part_exited and tags["exited"] > exit_base:
            part_exited = True
            part_exited_at = now
        return part_exited and (now - part_exited_at >= gap)
    return at_target()


def tick(now):
    global step_idx, started, alarm, state
    with lock:
        if mode != "auto" or not started:
            return

        name, kind, _arg = SEQUENCE[step_idx]

        if step_done(now):
            step_idx += 1
            if step_idx >= len(SEQUENCE):
                step_idx = 0
            enter_step(step_idx, now)
            return

        timeout = WAIT_TIMEOUT if kind == "wait_exit" else STEP_TIMEOUT
        if now - step_started > timeout:
            started = False
            state = "FAULT"
            alarm = "Timeout in " + name
            client.publish("pickline/target/belt", "0", retain=True)


def publish_status():
    values = {
        "pickline/state": state,
        "pickline/mode": mode,
        "pickline/gap": "%.2f" % gap,
        "pickline/alarm": alarm,
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
    print("PickLine PLC running (broker %s:%d)" % (BROKER, PORT))
    publish_status()

    period = 1.0 / LOOP_HZ
    last_alive = 0.0
    while True:
        now = time.monotonic()
        tick(now)
        publish_status()
        if now - last_alive >= 1.0:
            client.publish("pickline/plc/alive", "%.0f" % time.time(), retain=True)
            last_alive = now
        time.sleep(period)


if __name__ == "__main__":
    main()
