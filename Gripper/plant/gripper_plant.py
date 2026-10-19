#!/usr/bin/env python3
"""Gantry plant model for the Gripper digital twin.

Simulates the machine itself - a 3-axis pick-and-place gantry with a gripper -
and publishes its sensors over MQTT.  The soft PLC in ../plc/gripper_plc.py
drives it by publishing target positions on gripper/target/*.

Run:
    python3 gripper_plant.py
    MQTT_BROKER=192.168.50.1 python3 gripper_plant.py   # broker on the Mac
"""
import math
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

SPEED_MM_S = 140.0      # axis travel speed
GRIP_TIME = 0.35        # seconds for the jaws to open or close
LOOP_HZ = 20.0

X_MAX, Y_MAX, Z_MAX = 300.0, 200.0, 100.0
PICK = (20.0, 20.0, 0.0)
PLACE = (280.0, 180.0, 0.0)
PICK_TOL = 8.0          # mm, xy tolerance to grab or drop a part

lock = threading.Lock()

pos = [0.0, 0.0, 60.0]          # actual tool position (mm)
target = [0.0, 0.0, 60.0]       # commanded position
grip = 1.0                      # 1.0 open, 0.0 closed (animated)
grip_target = 1.0
part_held = False
placed = 0
part_pos = [PICK[0], PICK[1], PICK[2]]

last_published = {}


def clamp(value, low, high):
    return max(low, min(high, value))


def near(xy, ref, tol):
    return math.hypot(xy[0] - ref[0], xy[1] - ref[1]) <= tol


def reset_plant():
    global part_held, placed
    part_held = False
    placed = 0
    part_pos[:] = PICK


def on_connect(client, *_args):
    client.subscribe("gripper/target/#")
    client.subscribe("gripper/command/reset")


def on_message(_client, _userdata, msg):
    global grip_target
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "gripper/target/x":
                target[0] = clamp(float(payload), 0.0, X_MAX)
            elif msg.topic == "gripper/target/y":
                target[1] = clamp(float(payload), 0.0, Y_MAX)
            elif msg.topic == "gripper/target/z":
                target[2] = clamp(float(payload), 0.0, Z_MAX)
            elif msg.topic == "gripper/target/grip":
                grip_target = 1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
            elif msg.topic == "gripper/command/reset":
                reset_plant()
        except ValueError:
            pass


def step(dt):
    """Advance the plant by dt seconds."""
    global grip, part_held, placed
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

        # Jaws closed at the pick station -> grab the part.
        if grip <= 0.05 and not part_held and near(pos, PICK, PICK_TOL) and pos[2] <= 5.0:
            part_held = True

        # Jaws opened while holding -> release the part.
        if grip >= 0.95 and part_held:
            part_held = False
            if near(pos, PLACE, PICK_TOL) and pos[2] <= 5.0:
                placed += 1
                part_pos[:] = PLACE
            else:
                part_pos[:] = list(pos)

        if part_held:
            part_pos[:] = list(pos)


def snapshot():
    with lock:
        busy = any(abs(target[i] - pos[i]) > 0.2 for i in range(3))
        return {
            "gripper/x": "%.2f" % pos[0],
            "gripper/y": "%.2f" % pos[1],
            "gripper/z": "%.2f" % pos[2],
            "gripper/grip": "%.2f" % grip,
            "gripper/part": "1" if part_held else "0",
            "gripper/placed": str(placed),
            "gripper/part_x": "%.2f" % part_pos[0],
            "gripper/part_y": "%.2f" % part_pos[1],
            "gripper/part_z": "%.2f" % part_pos[2],
            "gripper/busy": "1" if busy else "0",
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

    print("Gripper plant running (broker %s:%d)" % (BROKER, PORT))
    print("Try:  mosquitto_pub -t gripper/target/x -m 120")

    period = 1.0 / LOOP_HZ
    last = time.monotonic()
    last_alive = 0.0
    while True:
        now = time.monotonic()
        dt = min(now - last, 0.2)
        last = now
        step(dt)
        publish(client, snapshot())
        if now - last_alive >= 1.0:
            client.publish("gripper/plant/alive", "%.0f" % time.time(), retain=True)
            last_alive = now
        time.sleep(max(0.0, period - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
