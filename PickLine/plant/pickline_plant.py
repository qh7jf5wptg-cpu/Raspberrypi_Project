#!/usr/bin/env python3
"""PickLine plant model: a pick-and-place gantry that feeds a conveyor belt.

One plant owns both machines so they stay in lock-step:
  * a 3-axis gantry with a two-finger gripper picks a part from a bin and
    drops it at the belt infeed,
  * the belt carries the part along X until it exits at the far end.

The soft PLC in ../plc/pickline_plc.py drives it through MQTT target topics.

Run:
    python3 pickline_plant.py
    MQTT_BROKER=192.168.50.1 python3 pickline_plant.py   # broker on the Mac
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
BELT_SPEED = 90.0       # belt speed, mm/s
BELT_TIME = 0.30        # seconds for the belt to start/stop
LOOP_HZ = 20.0

X_MAX, Y_MAX, Z_MAX = 300.0, 220.0, 100.0
PICK = (260.0, 20.0, 0.0)       # part bin
DROP = (0.0, 100.0, 0.0)        # belt infeed (belt runs along y = 100)
PICK_TOL = 8.0                  # mm, xy tolerance to grab or drop a part

BELT_LEN = 400.0                # belt runs x = 0 .. 400 at y = 100
SENSOR_IN_X = 30.0              # infeed sensor
SENSOR_OUT_X = 370.0            # outfeed sensor (just before the exit)
SENSOR_TOL = 6.0

lock = threading.Lock()

pos = [0.0, 0.0, 60.0]          # actual tool position (mm)
target = [0.0, 0.0, 60.0]       # commanded position
grip = 1.0                      # 1.0 open, 0.0 closed (animated)
grip_target = 1.0
part_held = False
placed = 0

belt = 0.0
belt_target = 0.0
part_on_belt = False
belt_pos = -1.0                 # -1 means no part on the belt
exited = 0
sensor_in = 0
sensor_out = 0

last_published = {}


def clamp(value, low, high):
    return max(low, min(high, value))


def near(xy, ref, tol):
    return math.hypot(xy[0] - ref[0], xy[1] - ref[1]) <= tol


def reset_plant():
    global part_held, placed, part_on_belt, belt_pos, exited
    part_held = False
    placed = 0
    part_on_belt = False
    belt_pos = -1.0
    exited = 0


def on_connect(client, *_args):
    client.subscribe("pickline/target/#")
    client.subscribe("pickline/plant/reset")


def on_message(_client, _userdata, msg):
    global grip_target, belt_target
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
            elif msg.topic == "pickline/plant/reset":
                reset_plant()
        except ValueError:
            pass


def step(dt):
    """Advance the plant by dt seconds."""
    global grip, part_held, placed, belt, part_on_belt, belt_pos, exited
    global sensor_in, sensor_out

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

        # Jaws closed at the bin -> grab the part.
        if grip <= 0.05 and not part_held and near(pos, PICK, PICK_TOL) and pos[2] <= 5.0:
            part_held = True

        # Jaws opened while holding -> release the part.
        if grip >= 0.95 and part_held:
            part_held = False
            if near(pos, DROP, PICK_TOL) and pos[2] <= 5.0:
                placed += 1
                part_on_belt = True
                belt_pos = 0.0

        if belt < belt_target:
            belt = min(belt_target, belt + dt / BELT_TIME)
        elif belt > belt_target:
            belt = max(belt_target, belt - dt / BELT_TIME)

        if part_on_belt:
            belt_pos += BELT_SPEED * belt * dt
            if belt_pos >= BELT_LEN:
                exited += 1
                part_on_belt = False
                belt_pos = -1.0

        sensor_in = 1 if (part_on_belt and abs(belt_pos - SENSOR_IN_X) < SENSOR_TOL) else 0
        sensor_out = 1 if (part_on_belt and abs(belt_pos - SENSOR_OUT_X) < SENSOR_TOL) else 0


def snapshot():
    with lock:
        busy = any(abs(target[i] - pos[i]) > 0.2 for i in range(3))

        # Part location: follows the tool while held, rides the belt otherwise.
        if part_held:
            part_x, part_y, part_z = pos
        elif part_on_belt:
            part_x, part_y, part_z = belt_pos, DROP[1], 0.0
        else:
            part_x, part_y, part_z = -1.0, -1.0, -1.0

        return {
            "pickline/x": "%.2f" % pos[0],
            "pickline/y": "%.2f" % pos[1],
            "pickline/z": "%.2f" % pos[2],
            "pickline/grip": "%.2f" % grip,
            "pickline/holding": "1" if part_held else "0",
            "pickline/part_x": "%.2f" % part_x,
            "pickline/part_y": "%.2f" % part_y,
            "pickline/part_z": "%.2f" % part_z,
            "pickline/belt": "%.2f" % belt,
            "pickline/belt_pos": "%.1f" % belt_pos,
            "pickline/sensor_in": "1" if sensor_in else "0",
            "pickline/sensor_out": "1" if sensor_out else "0",
            "pickline/placed": str(placed),
            "pickline/exited": str(exited),
            "pickline/busy": "1" if busy else "0",
        }


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
    print("Try:  mosquitto_pub -t pickline/target/x -m 120")

    period = 1.0 / LOOP_HZ
    last = time.monotonic()
    last_alive = 0.0
    while True:
        now = time.monotonic()
        step(min(now - last, 0.2))
        last = now
        publish(client, snapshot())
        if now - last_alive >= 1.0:
            client.publish("pickline/plant/alive", "%.0f" % time.time(), retain=True)
            last_alive = now
        time.sleep(max(0.0, period - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
