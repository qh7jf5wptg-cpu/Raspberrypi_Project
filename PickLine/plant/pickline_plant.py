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
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

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

X_MAX, Y_MAX, Z_MAX = 300.0, 220.0, 100.0
PICK_DOWN = (260.0, 20.0, 0.0)
PICK_UP = (260.0, 190.0, 0.0)
DROP = (0.0, 100.0, 0.0)        # belt infeed (belt runs along y = 100)
PICK_TOL = 8.0

BELT_LEN = 400.0                # belt runs x = 0 .. 400 at y = 100
STRAIGHT_END = 460.0            # station A sits beyond the straight belt end
LEFT_END_Y = 240.0              # station B sits beyond the left lane end
SENSOR_IN_X = 30.0
SENSOR_OUT_X = 370.0
SENSOR_DIVERT_Y = 230.0
SENSOR_TOL = 6.0

lock = threading.Lock()

pos = [0.0, 0.0, 60.0]
target = [0.0, 0.0, 60.0]
grip = 1.0
grip_target = 1.0
part_held = False
placed = 0

belt = 0.0
belt_target = 0.0
belt_speed = BELT_SPEED
diverter = 0.0
diverter_target = 0.0

part_lane = "none"              # none | belt | straight | left | wait_a | wait_b
part_x = -1.0
part_y = -1.0
exited = 0

volume = VOLUME
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


def clamp(value, low, high):
    return max(low, min(high, value))


def near(xy, ref, tol):
    return math.hypot(xy[0] - ref[0], xy[1] - ref[1]) <= tol


def reset_plant():
    global part_held, placed, part_lane, part_x, part_y, exited, total, jam
    part_held = False
    placed = 0
    part_lane = "none"
    part_x = -1.0
    part_y = -1.0
    exited = 0
    total = 0.0
    jam = False
    for key in ("a", "b"):
        fill[key]["state"] = "EMPTY"
        fill[key]["level"] = 0.0
        fill[key]["filled"] = 0
        fill[key]["count"] = 0
        fill[key]["alarm"] = ""
        fill[key]["pouring"] = 0
        fill[key]["pour_timer"] = 0.0


def clear_belt():
    global part_lane, part_x, part_y, placed
    if part_lane in ("belt", "straight", "left", "wait_a", "wait_b"):
        part_lane = "none"
        part_x = -1.0
        part_y = -1.0
        placed = max(0, placed - 1)


def on_connect(client, *_args):
    client.subscribe("pickline/target/#")
    client.subscribe("pickline/plant/reset")
    client.subscribe("pickline/fill/a/take")
    client.subscribe("pickline/fill/b/take")
    client.subscribe("pickline/fault/#")
    client.subscribe("pickline/clear_belt")


def on_message(_client, _userdata, msg):
    global grip_target, belt_target, diverter_target, belt_speed, volume, jam
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "pickline/target/x":
                target[0] = clamp(float(payload), 0.0, X_MAX)
            elif msg.topic == "pickline/target/y":
                target[1] = clamp(float(payload), 0.0, Y_MAX)
            elif msg.topic == "pickline/target/z":
                target[2] = clamp(float(payload), 0.0, Z_MAX)
            elif msg.topic == "pickline/target/grip":
                grip_target = 1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
            elif msg.topic == "pickline/target/belt":
                belt_target = 1.0 if payload.lower() in ("1", "true", "on", "run") else 0.0
            elif msg.topic == "pickline/target/diverter":
                diverter_target = 1.0 if payload.lower() in ("1", "true", "on", "divert") else 0.0
            elif msg.topic == "pickline/target/speed":
                belt_speed = clamp(float(payload), BELT_SPEED_MIN, BELT_SPEED_MAX)
            elif msg.topic == "pickline/target/volume":
                volume = clamp(float(payload), VOLUME_MIN, VOLUME_MAX)
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
            elif msg.topic == "pickline/fault/jam":
                jam = payload.lower() in ("1", "true", "on", "jam")
            elif msg.topic == "pickline/fault/clear":
                jam = False
        except ValueError:
            pass


def enter_station(key):
    global part_lane, part_x, part_y, exited, total
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
    part_lane = "none"
    part_x = -1.0
    part_y = -1.0
    exited += 1


def step(dt):
    global grip, part_held, placed, belt, diverter, part_lane, part_x, part_y
    global total, sensor_in, sensor_out, sensor_divert

    with lock:
        for i in range(3):
            error = target[i] - pos[i]
            max_step = SPEED_MM_S * dt
            if abs(error) <= max_step:
                pos[i] = target[i]
            else:
                pos[i] += math.copysign(max_step, error)

        if grip < grip_target:
            grip = min(grip_target, grip + dt / GRIP_TIME)
        elif grip > grip_target:
            grip = max(grip_target, grip - dt / GRIP_TIME)

        if grip <= 0.05 and not part_held and pos[2] <= 5.0:
            if near(pos, PICK_DOWN, PICK_TOL) or near(pos, PICK_UP, PICK_TOL):
                part_held = True

        if grip >= 0.95 and part_held:
            part_held = False
            if near(pos, DROP, PICK_TOL) and pos[2] <= 5.0:
                placed += 1
                part_lane = "belt"
                part_x = 0.0
                part_y = DROP[1]

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

        # Container: belt -> approach lane -> fill station.
        if part_lane == "belt":
            part_x += part_speed * dt
            if part_x >= BELT_LEN:
                if diverter > 0.5:
                    part_lane = "left"
                    part_x = BELT_LEN
                    part_y = DROP[1]
                else:
                    part_lane = "straight"
                    part_y = DROP[1]
        elif part_lane == "straight":
            part_x += part_speed * dt
            if part_x >= STRAIGHT_END:
                if fill["a"]["state"] not in ("FULL", "FAULT"):
                    enter_station("a")
                else:
                    part_lane = "wait_a"
                    part_x = STRAIGHT_END
        elif part_lane == "left":
            part_y += part_speed * dt
            if part_y >= LEFT_END_Y:
                if fill["b"]["state"] not in ("FULL", "FAULT"):
                    enter_station("b")
                else:
                    part_lane = "wait_b"
                    part_y = LEFT_END_Y
        elif part_lane == "wait_a":
            if fill["a"]["state"] not in ("FULL", "FAULT"):
                enter_station("a")
        elif part_lane == "wait_b":
            if fill["b"]["state"] not in ("FULL", "FAULT"):
                enter_station("b")

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

        sensor_in = 1 if (part_lane == "belt" and abs(part_x - SENSOR_IN_X) < SENSOR_TOL) else 0
        sensor_out = 1 if (part_lane == "belt" and abs(part_x - SENSOR_OUT_X) < SENSOR_TOL) else 0
        sensor_divert = 1 if (part_lane == "left" and abs(part_y - SENSOR_DIVERT_Y) < SENSOR_TOL) else 0


def snapshot():
    with lock:
        busy = any(abs(target[i] - pos[i]) > 0.2 for i in range(3))

        if part_held:
            px, py, pz = pos
        elif part_lane in ("belt", "straight", "left", "wait_a", "wait_b"):
            px, py, pz = part_x, part_y, 0.0
        else:
            px, py, pz = -1.0, -1.0, -1.0

        belt_pos = part_x if part_lane == "belt" else -1.0

        values = {
            "pickline/x": "%.2f" % pos[0],
            "pickline/y": "%.2f" % pos[1],
            "pickline/z": "%.2f" % pos[2],
            "pickline/grip": "%.2f" % grip,
            "pickline/holding": "1" if part_held else "0",
            "pickline/part_x": "%.2f" % px,
            "pickline/part_y": "%.2f" % py,
            "pickline/part_z": "%.2f" % pz,
            "pickline/part_on_line": "1" if part_lane != "none" else "0",
            "pickline/belt": "%.2f" % belt,
            "pickline/belt_pos": "%.1f" % belt_pos,
            "pickline/speed": "%.0f" % belt_speed,
            "pickline/diverter": "%.2f" % diverter,
            "pickline/sensor_in": "1" if sensor_in else "0",
            "pickline/sensor_out": "1" if sensor_out else "0",
            "pickline/sensor_divert": "1" if sensor_divert else "0",
            "pickline/placed": str(placed),
            "pickline/exited": str(exited),
            "pickline/busy": "1" if busy else "0",
            "pickline/volume": "%.0f" % volume,
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
        return values


def publish(client, values):
    for topic, payload in values.items():
        if last_published.get(topic) != payload:
            client.publish(topic, payload, retain=True)
            last_published[topic] = payload


def main():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.loop_start()
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
