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
import sys
import threading
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot import geometry as G

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
LOOP_HZ = 10.0

PICK_DOWN = (260.0, 20.0, 0.0)
PICK_UP = (260.0, 190.0, 0.0)
DROP = (0.0, 100.0, 0.0)
DROP_B = (0.0, -70.0, 0.0)
TRAVEL_Z = 30.0
TOL = 2.0
STEP_TIMEOUT = 15.0
DEFAULT_GAP = 0.0
DROP_SPACING = 40.0       # minimum belt advance before the second gripper drops

SEQUENCE = [
    ("TO_PICK",       "move", "pick_z"),
    ("LOWER_PICK",    "move", "pick"),
    ("GRIP",          "grip", None),
    ("LIFT_PICK",     "move", "pick_z"),
    ("TO_DROP_A",     "move", "drop_a_z"),
    ("WAIT_INFEED",   "wait_infeed", None),
    ("LOWER_A",       "move", "drop_a"),
    ("RELEASE_A",     "grip_a", None),
    ("LIFT_A",        "move", "drop_a_z"),
    ("TO_DROP_B",     "move", "drop_b_z"),
    ("WAIT_GAP",      "wait_gap", None),
    ("LOWER_B",       "move", "drop_b"),
    ("RELEASE_B",     "grip_b", None),
    ("LIFT_B",        "move", "drop_b_z"),
]

lock = threading.Lock()
client = None

tags = {"x": 0.0, "y": 0.0, "z": 60.0, "busy": 0,
        "holding_a": 0, "holding_b": 0, "exited": 0}
station = {"a": "EMPTY", "b": "EMPTY"}
pickups = {"a": 2, "b": 5}
jam_flag = 0
paused = False
estop = False
part_on_line = 0
state = "IDLE"
mode = "auto"
started = False
gap = DEFAULT_GAP
side = "both"
side_mode = "both"
route_mode = "auto"
decision = "A+B"
alarm = ""
step_idx = 0
step_started = 0.0
scanned = ""
belt_pos = -1.0
belt_infeed_clear = 1
gap_start = 0.0

last = {}
last_resend = 0.0

robot = {
    "a": {"state": "IDLE", "tcp": (0.0, 0.0, 0.0), "holding": 0},
    "b": {"state": "IDLE", "tcp": (0.0, 0.0, 0.0), "holding": 0},
}
place_owner = None       # 'a' or 'b' currently placing on the outfeed, else None
infeed_clear = 1


def move_target(kind):
    if kind == "pick":
        return (PICK_DOWN[0], PICK_DOWN[1], 0.0)
    if kind == "pick_z":
        return (PICK_DOWN[0], PICK_DOWN[1], TRAVEL_Z)
    if kind == "drop_a":
        return DROP
    if kind == "drop_a_z":
        return (DROP[0], DROP[1], TRAVEL_Z)
    if kind == "drop_b":
        return DROP_B
    if kind == "drop_b_z":
        return (DROP_B[0], DROP_B[1], TRAVEL_Z)
    return (0.0, 0.0, TRAVEL_Z)


def at_target():
    name, kind, arg = SEQUENCE[step_idx]
    if kind != "move":
        return True
    if tags["busy"] != 0:
        return False
    tx, ty, tz = move_target(arg)
    return (abs(tags["x"] - tx) <= TOL
            and abs(tags["y"] - ty) <= TOL
            and abs(tags["z"] - tz) <= TOL)


def send_move_target():
    _name, kind, arg = SEQUENCE[step_idx]
    if kind != "move":
        return
    tx, ty, tz = move_target(arg)
    client.publish("pickline/target/x", "%.1f" % tx, retain=False)
    client.publish("pickline/target/y", "%.1f" % ty, retain=False)
    client.publish("pickline/target/z", "%.1f" % tz, retain=False)


def enter_step(index, now):
    global step_idx, step_started, state
    global gap_start, last_resend
    step_idx = index
    step_started = now
    last_resend = now
    name, kind, arg = SEQUENCE[index]
    state = name
    if kind == "move":
        send_move_target()
    elif kind == "grip":
        client.publish("pickline/target/grip_a", "0", retain=False)
        client.publish("pickline/target/grip_b", "0", retain=False)
    elif kind == "grip_a":
        client.publish("pickline/target/grip_a", "1", retain=False)
        gap_start = now
    elif kind == "grip_b":
        client.publish("pickline/target/grip_b", "1", retain=False)


def hold_position():
    client.publish("pickline/target/x", "%.1f" % tags["x"], retain=False)
    client.publish("pickline/target/y", "%.1f" % tags["y"], retain=False)
    client.publish("pickline/target/z", "%.1f" % tags["z"], retain=False)


def robot_poses(key):
    pick = G.PICK_A if key == "a" else G.PICK_B
    lift = (pick[0], pick[1], pick[2] + 80.0)
    pre = (G.OUTFEED_DROP[0], G.OUTFEED_DROP[1], G.OUTFEED_DROP[2] + 80.0)
    return {
        "pick": pick,
        "lift": lift,
        "pre_place": pre,
        "place": G.OUTFEED_DROP,
        "clear": pre,
        "park": lift,
    }


def send_robot_target(key, pos):
    client.publish("pickline/robot/%s/target/x" % key, "%.1f" % pos[0], retain=False)
    client.publish("pickline/robot/%s/target/y" % key, "%.1f" % pos[1], retain=False)
    client.publish("pickline/robot/%s/target/z" % key, "%.1f" % pos[2], retain=False)


def send_robot_grip(key, value):
    client.publish("pickline/robot/%s/target/grip" % key, str(value), retain=False)


def robot_at(key, pos):
    tx, ty, tz = robot[key]["tcp"]
    return (math.hypot(tx - pos[0], ty - pos[1]) <= G.GRIP_TOL
            and abs(tz - pos[2]) <= G.GRIP_TOL)


def tick_robots(_now):
    global place_owner
    with lock:
        for key in ("a", "b"):
            rb = robot[key]
            poses = robot_poses(key)
            state = rb["state"]

            if state == "IDLE":
                if station[key] in ("FULL", "FAULT"):
                    rb["state"] = "GO_PICK"
                    send_robot_grip(key, 1)
                    send_robot_target(key, poses["pick"])

            elif state == "GO_PICK":
                if robot_at(key, poses["pick"]):
                    rb["state"] = "GRASP"
                    send_robot_grip(key, 0)

            elif state == "GRASP":
                if rb["holding"]:
                    rb["state"] = "GO_LIFT"
                    send_robot_target(key, poses["lift"])
                elif station[key] not in ("FULL", "FAULT"):
                    # Station was cleared another way; abort safely.
                    rb["state"] = "IDLE"
                    send_robot_grip(key, 1)
                    send_robot_target(key, poses["park"])

            elif state == "GO_LIFT":
                if robot_at(key, poses["lift"]):
                    rb["state"] = "GO_PRE_PLACE"
                    send_robot_target(key, poses["pre_place"])

            elif state == "GO_PRE_PLACE":
                if robot_at(key, poses["pre_place"]):
                    rb["state"] = "WAIT_SLOT"

            elif state == "WAIT_SLOT":
                if place_owner is None and infeed_clear:
                    place_owner = key
                    rb["state"] = "GO_PLACE"
                    send_robot_target(key, poses["place"])

            elif state == "GO_PLACE":
                if robot_at(key, poses["place"]):
                    rb["state"] = "RELEASE"
                    send_robot_grip(key, 1)

            elif state == "RELEASE":
                if not rb["holding"]:
                    rb["state"] = "GO_CLEAR"
                    send_robot_target(key, poses["clear"])

            elif state == "GO_CLEAR":
                if robot_at(key, poses["clear"]):
                    place_owner = None
                    rb["state"] = "IDLE"
                    send_robot_target(key, poses["park"])


def start_auto():
    global started, alarm, jam_flag, decision
    started = True
    alarm = ""
    jam_flag = 0
    decision = "STRAIGHT"
    # Clear any part on the belt but keep fill stations and production counts.
    client.publish("pickline/clear_belt", "1", retain=False)
    client.publish("pickline/target/belt", "1", retain=False)
    client.publish("pickline/target/diverter", "0", retain=False)
    enter_step(0, time.monotonic())


def on_connect(cli, *_args):
    cli.subscribe("pickline/x")
    cli.subscribe("pickline/y")
    cli.subscribe("pickline/z")
    cli.subscribe("pickline/busy")
    cli.subscribe("pickline/holding_a")
    cli.subscribe("pickline/holding_b")
    cli.subscribe("pickline/exited")
    cli.subscribe("pickline/fill/a/state")
    cli.subscribe("pickline/fill/b/state")
    cli.subscribe("pickline/fill/a/pickups")
    cli.subscribe("pickline/fill/b/pickups")
    cli.subscribe("pickline/jam")
    cli.subscribe("pickline/part_on_line")
    cli.subscribe("pickline/scanned")
    cli.subscribe("pickline/belt_pos")
    cli.subscribe("pickline/belt_infeed_clear")
    cli.subscribe("pickline/robot/+/tcp/+")
    cli.subscribe("pickline/robot/+/holding")
    cli.subscribe("pickline/outfeed/infeed_clear")
    cli.subscribe("pickline/command/#")


def on_message(_cli, _userdata, msg):
    global mode, started, state, gap, side_mode, route_mode, alarm, step_idx, jam_flag
    global paused, estop, part_on_line, infeed_clear, decision, scanned, belt_pos
    global belt_infeed_clear
    try:
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
                elif msg.topic == "pickline/holding_a":
                    tags["holding_a"] = int(float(payload or 0))
                elif msg.topic == "pickline/holding_b":
                    tags["holding_b"] = int(float(payload or 0))
                elif msg.topic == "pickline/exited":
                    tags["exited"] = int(float(payload or 0))
                elif msg.topic == "pickline/fill/a/state":
                    station["a"] = payload
                elif msg.topic == "pickline/fill/b/state":
                    station["b"] = payload
                elif msg.topic == "pickline/fill/a/pickups":
                    pickups["a"] = int(float(payload or 0))
                elif msg.topic == "pickline/fill/b/pickups":
                    pickups["b"] = int(float(payload or 0))
                elif msg.topic == "pickline/jam":
                    jam_flag = int(float(payload or 0))
                elif msg.topic == "pickline/part_on_line":
                    part_on_line = int(float(payload or 0))
                elif msg.topic == "pickline/scanned":
                    scanned = payload
                    # The scanner reads each container at the belt infeed. The
                    # route is decided per container in the plant; here we only
                    # mirror it for the HMI/dashboard display.
                    if payload.upper() == "B":
                        decision = "LEFT"
                    else:
                        decision = "STRAIGHT"
                elif msg.topic == "pickline/belt_pos":
                    belt_pos = float(payload)
                elif msg.topic == "pickline/belt_infeed_clear":
                    belt_infeed_clear = int(float(payload or 0))
                elif msg.topic.startswith("pickline/robot/") and "/tcp/" in msg.topic:
                    key = msg.topic.split("/")[2]
                    axis = msg.topic.split("/")[4]
                    if key in robot and axis in ("x", "y", "z"):
                        idx = {"x": 0, "y": 1, "z": 2}[axis]
                        tcp = list(robot[key]["tcp"])
                        tcp[idx] = float(payload)
                        robot[key]["tcp"] = tuple(tcp)
                elif msg.topic.startswith("pickline/robot/") and msg.topic.endswith("/holding"):
                    key = msg.topic.split("/")[2]
                    if key in robot:
                        robot[key]["holding"] = int(float(payload or 0))
                elif msg.topic == "pickline/outfeed/infeed_clear":
                    infeed_clear = int(float(payload or 0))
            except ValueError:
                pass

            if msg.topic == "pickline/command/start":
                if mode == "auto":
                    if estop and part_on_line:
                        state = "ESTOP"
                        alarm = "CLEAR BELT TO START"
                    else:
                        estop = False
                        paused = False
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
                estop = False
                paused = False
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
                side_mode = payload.lower() if payload.lower() in ("down", "up", "alternate", "auto") else "auto"
            elif msg.topic == "pickline/command/route":
                route_mode = payload.lower() if payload.lower() in ("auto", "straight", "left", "alternate") else "auto"
            elif msg.topic == "pickline/command/pause":
                if mode == "auto" and started and not paused and step_idx <= 6:
                    paused = True
                    hold_position()
            elif msg.topic == "pickline/command/resume":
                paused = False
            elif msg.topic == "pickline/command/estop":
                estop = True
                started = False
                paused = False
                state = "ESTOP"
                client.publish("pickline/target/belt", "0", retain=False)
                hold_position()
            elif msg.topic == "pickline/command/clear_belt":
                client.publish("pickline/clear_belt", "1", retain=False)
    except BaseException as exc:
        print("PLC on_message error:", repr(exc), flush=True)


def step_done(now):
    name, kind, _arg = SEQUENCE[step_idx]
    if kind == "grip":
        return tags["holding_a"] == 1 and tags["holding_b"] == 1
    if kind == "grip_a":
        return tags["holding_a"] == 0
    if kind == "grip_b":
        return tags["holding_b"] == 0
    if kind == "wait_infeed":
        # Do not lower the first gripper until the belt infeed is clear.
        return belt_infeed_clear == 1
    if kind == "wait_gap":
        # Pitch the two drops apart: the first container must advance past the
        # safety distance and the configured gap time must have elapsed.
        return (belt_pos < 0 or belt_pos >= DROP_SPACING) and (now - gap_start >= gap)
    return at_target()


def tick(now):
    global step_idx, started, alarm, state, last_resend
    with lock:
        if mode != "auto" or not started:
            return

        if jam_flag:
            started = False
            state = "FAULT"
            alarm = "BELT JAM"
            client.publish("pickline/target/belt", "0", retain=False)
            return

        if estop or paused:
            return

        name, kind, arg = SEQUENCE[step_idx]

        if step_done(now):
            step_idx += 1
            if step_idx >= len(SEQUENCE):
                step_idx = 0
            enter_step(step_idx, now)
            return

        # Re-send the current step command periodically in case the plant missed it.
        if kind in ("move", "grip", "grip_a", "grip_b") and now - last_resend >= 1.0:
            if kind == "move":
                send_move_target()
            elif kind == "grip":
                client.publish("pickline/target/grip_a", "0", retain=False)
                client.publish("pickline/target/grip_b", "0", retain=False)
            elif kind == "grip_a":
                client.publish("pickline/target/grip_a", "1", retain=False)
            elif kind == "grip_b":
                client.publish("pickline/target/grip_b", "1", retain=False)
            last_resend = now

        # Move/grip steps have a hard timeout. WAIT_INFEED and WAIT_GAP wait
        # legitimately for the belt to make room, so they are not timed out.
        if kind in ("move", "grip") and now - step_started > STEP_TIMEOUT:
            started = False
            state = "FAULT"
            alarm = "Timeout in " + name
            client.publish("pickline/target/belt", "0", retain=False)


def publish_status():
    values = {
        "pickline/state": state,
        "pickline/mode": mode,
        "pickline/side": side,
        "pickline/side_mode": side_mode,
        "pickline/route_mode": route_mode,
        "pickline/decision": decision,
        "pickline/gap": "%.2f" % gap,
        "pickline/paused": "1" if paused else "0",
        "pickline/estop": "1" if estop else "0",
        "pickline/alarm": alarm,
        "pickline/robot/a/task": robot["a"]["state"],
        "pickline/robot/b/task": robot["b"]["state"],
        "pickline/outfeed/owner": place_owner or "",
    }
    for topic, payload in values.items():
        if last.get(topic) != payload:
            client.publish(topic, payload, retain=True)
            last[topic] = payload


def on_disconnect(_cli, _userdata, rc, *_args):
    print("PLC MQTT disconnected (rc=%s); reconnecting automatically" % rc,
          flush=True)


def main():
    global client
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.max_queued_messages_set(20)

    # Keep retrying the initial connect so a broker that is briefly down does
    # not kill the PLC process.
    while True:
        try:
            client.connect(BROKER, PORT, 60)
            break
        except Exception as exc:
            print("PLC connect failed (%s); retrying in 2s" % exc, flush=True)
            time.sleep(2)

    client.loop_start()
    print("PickLine PLC running (broker %s:%d)" % (BROKER, PORT))
    publish_status()

    period = 1.0 / LOOP_HZ
    last_alive = 0.0
    disconnected_since = None
    while True:
        try:
            now = time.monotonic()
            if not client.is_connected():
                if disconnected_since is None:
                    disconnected_since = now
                elif now - disconnected_since > 10.0:
                    print("PLC: broker unreachable >10s; forcing reconnect",
                          flush=True)
                    try:
                        client.reconnect()
                    except Exception:
                        pass
                    disconnected_since = now
            else:
                disconnected_since = None

            tick(now)
            tick_robots(now)
            publish_status()
            if now - last_alive >= 1.0:
                client.publish("pickline/plc/alive", "%.0f" % time.time(), retain=True)
                last_alive = now
        except Exception as exc:
            print("PLC loop error:", repr(exc), flush=True)
        time.sleep(period)


if __name__ == "__main__":
    main()
