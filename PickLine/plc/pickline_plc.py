#!/usr/bin/env python3
"""Soft PLC for the PickLine: gantry feeds a conveyor with two filling stations.

Auto sequence:
    pick an empty container from a bin -> carry it to the belt infeed ->
    release -> choose a route (straight station A / left station B) ->
    wait for the container to enter a station -> wait the gap ->
    only start the next pick when a station is free.

Routing is station-aware:
    both stations free   -> alternate straight / left, one by one
    one station full     -> route only to the other (free) station
    no station free      -> wait until a full container is taken out manually

Take-out is manual: publish to pickline/fill/a/take or pickline/fill/b/take.

Commands:
    mosquitto_pub -t pickline/command/mode  -m auto|manual
    mosquitto_pub -t pickline/command/side  -m down|up|alternate
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

PICK_DOWN = (260.0, 20.0, 0.0)
PICK_UP = (260.0, 190.0, 0.0)
DROP = (0.0, 100.0, 0.0)
TRAVEL_Z = 60.0
TOL = 2.0
STEP_TIMEOUT = 15.0
WAIT_TIMEOUT = 15.0
DEFAULT_GAP = 0.5

SEQUENCE = [
    ("TO_PICK",       "move", "pick_z"),
    ("LOWER_PICK",    "move", "pick"),
    ("GRIP",          "grip", 0),
    ("LIFT_PICK",     "move", "pick_z"),
    ("TO_DROP",       "move", "drop_z"),
    ("LOWER_DROP",    "move", "drop"),
    ("RELEASE",       "grip", 1),
    ("LIFT_DROP",     "move", "drop_z"),
    ("WAIT_EXIT",     "wait_exit", None),
    ("WAIT_STATION",  "wait_station", None),
]

lock = threading.Lock()
client = None

tags = {"x": 0.0, "y": 0.0, "z": 60.0, "busy": 0, "holding": 0, "exited": 0}
station = {"a": "EMPTY", "b": "EMPTY"}
passes = {"a": 2, "b": 5}
jam_flag = 0
state = "IDLE"
mode = "auto"
started = False
gap = DEFAULT_GAP
side = "down"
side_mode = "alternate"
side_alt = False
alternate_flag = False
decision = "STRAIGHT"
alarm = ""
step_idx = 0
step_started = 0.0

exit_base = 0
part_exited = False
part_exited_at = 0.0

last = {}


def current_pick():
    return PICK_UP if side == "up" else PICK_DOWN


def choose_side():
    global side, side_alt
    if side_mode == "down":
        side = "down"
    elif side_mode == "up":
        side = "up"
    else:
        side_alt = not side_alt
        side = "up" if side_alt else "down"


def move_target(kind):
    if kind == "pick":
        x, y, _z = current_pick()
        return (x, y, 0.0)
    if kind == "pick_z":
        x, y, _z = current_pick()
        return (x, y, TRAVEL_Z)
    if kind == "drop":
        return DROP
    if kind == "drop_z":
        return (DROP[0], DROP[1], TRAVEL_Z)
    return (0.0, 0.0, TRAVEL_Z)


def at_target():
    name, kind, arg = SEQUENCE[step_idx]
    if tags["busy"] != 0:
        return False
    if kind != "move":
        return True
    tx, ty, tz = move_target(arg)
    return (abs(tags["x"] - tx) <= TOL
            and abs(tags["y"] - ty) <= TOL
            and abs(tags["z"] - tz) <= TOL)


def apply_diverter(value):
    global decision
    decision = "LEFT" if value else "STRAIGHT"
    client.publish("pickline/target/diverter", "1" if value else "0", retain=False)


def decide_route():
    global alternate_flag
    a_free = station["a"] == "EMPTY"
    b_free = station["b"] == "EMPTY"
    if a_free and b_free:
        # Prefer the faster station (fewer passes); alternate on a tie.
        if passes["a"] < passes["b"]:
            apply_diverter(False)
        elif passes["b"] < passes["a"]:
            apply_diverter(True)
        else:
            alternate_flag = not alternate_flag
            apply_diverter(alternate_flag)
    elif a_free:
        apply_diverter(False)
    elif b_free:
        apply_diverter(True)
    # else: neither free — handled by WAIT_STATION before the next pick.


def enter_step(index, now):
    global step_idx, step_started, state
    global exit_base, part_exited, part_exited_at
    step_idx = index
    step_started = now
    name, kind, arg = SEQUENCE[index]
    state = name
    if kind == "move":
        tx, ty, tz = move_target(arg)
        client.publish("pickline/target/x", "%.1f" % tx, retain=False)
        client.publish("pickline/target/y", "%.1f" % ty, retain=False)
        client.publish("pickline/target/z", "%.1f" % tz, retain=False)
    elif kind == "grip":
        client.publish("pickline/target/grip", str(arg), retain=False)
    elif kind == "wait_exit":
        decide_route()
        exit_base = tags["exited"]
        part_exited = False
        part_exited_at = 0.0


def hold_position():
    client.publish("pickline/target/x", "%.1f" % tags["x"], retain=False)
    client.publish("pickline/target/y", "%.1f" % tags["y"], retain=False)
    client.publish("pickline/target/z", "%.1f" % tags["z"], retain=False)


def start_auto():
    global started, alarm, exit_base, part_exited, part_exited_at, alternate_flag, jam_flag
    started = True
    alarm = ""
    alternate_flag = False
    jam_flag = 0
    client.publish("pickline/plant/reset", "1", retain=False)
    client.publish("pickline/target/belt", "1", retain=False)
    exit_base = 0
    part_exited = False
    part_exited_at = 0.0
    choose_side()
    enter_step(0, time.monotonic())


def on_connect(cli, *_args):
    cli.subscribe("pickline/x")
    cli.subscribe("pickline/y")
    cli.subscribe("pickline/z")
    cli.subscribe("pickline/busy")
    cli.subscribe("pickline/holding")
    cli.subscribe("pickline/exited")
    cli.subscribe("pickline/fill/a/state")
    cli.subscribe("pickline/fill/b/state")
    cli.subscribe("pickline/fill/a/passes")
    cli.subscribe("pickline/fill/b/passes")
    cli.subscribe("pickline/jam")
    cli.subscribe("pickline/command/#")


def on_message(_cli, _userdata, msg):
    global mode, started, state, gap, side_mode, alarm, step_idx, jam_flag
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
            elif msg.topic == "pickline/fill/a/state":
                station["a"] = payload
            elif msg.topic == "pickline/fill/b/state":
                station["b"] = payload
            elif msg.topic == "pickline/fill/a/passes":
                passes["a"] = int(float(payload or 0))
            elif msg.topic == "pickline/fill/b/passes":
                passes["b"] = int(float(payload or 0))
            elif msg.topic == "pickline/jam":
                jam_flag = int(float(payload or 0))
        except ValueError:
            pass

        if msg.topic == "pickline/command/start":
            if mode == "auto":
                start_auto()
        elif msg.topic == "pickline/command/stop":
            started = False
            state = "IDLE"
            hold_position()
            client.publish("pickline/target/belt", "0", retain=False)
        elif msg.topic == "pickline/command/reset":
            started = False
            alarm = ""
            step_idx = 0
            state = "IDLE"
            client.publish("pickline/target/belt", "0", retain=False)
            client.publish("pickline/target/diverter", "0", retain=False)
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
        elif msg.topic == "pickline/command/side":
            side_mode = payload.lower() if payload.lower() in ("down", "up", "alternate") else "alternate"


def step_done(now):
    global part_exited, part_exited_at
    name, kind, arg = SEQUENCE[step_idx]
    if kind == "grip":
        return (tags["holding"] == 1) if arg == 0 else (tags["holding"] == 0)
    if kind == "wait_exit":
        if not part_exited and tags["exited"] > exit_base:
            part_exited = True
            part_exited_at = now
        return part_exited and (now - part_exited_at >= gap)
    if kind == "wait_station":
        return station["a"] == "EMPTY" or station["b"] == "EMPTY"
    return at_target()


def tick(now):
    global step_idx, started, alarm, state
    with lock:
        if mode != "auto" or not started:
            return

        if jam_flag:
            started = False
            state = "FAULT"
            alarm = "BELT JAM"
            client.publish("pickline/target/belt", "0", retain=False)
            return

        name, kind, _arg = SEQUENCE[step_idx]

        if step_done(now):
            step_idx += 1
            if step_idx >= len(SEQUENCE):
                step_idx = 0
                choose_side()
            enter_step(step_idx, now)
            return

        timeout = WAIT_TIMEOUT if kind == "wait_exit" else STEP_TIMEOUT
        if kind != "wait_station" and now - step_started > timeout:
            started = False
            state = "FAULT"
            alarm = "BELT JAM" if kind == "wait_exit" else "Timeout in " + name
            client.publish("pickline/target/belt", "0", retain=False)


def publish_status():
    values = {
        "pickline/state": state,
        "pickline/mode": mode,
        "pickline/side": side,
        "pickline/side_mode": side_mode,
        "pickline/decision": decision,
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
