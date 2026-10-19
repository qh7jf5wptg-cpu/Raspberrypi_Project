#!/usr/bin/env python3
"""Conveyor plant model with a diverter and two sensors.

A belt carries parts along X. Sensor 1 sits upstream and sees each part
arrive; the soft PLC then decides whether to divert it. A diverter gate at the
midpoint pushes selected parts onto a side lane; sensor 2 sits downstream on
the main line and only sees the parts that went straight.

Run:
    python3 conveyor_plant.py
    MQTT_BROKER=192.168.50.1 python3 conveyor_plant.py
"""
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

SPEED_MM_S = 90.0       # belt speed
DIVERT_TIME = 0.25      # seconds for the gate to actuate
BELT_TIME = 0.30        # seconds for the belt to start/stop
LOOP_HZ = 20.0

BELT_LEN = 400.0
SENSOR1_X = 120.0       # upstream: sees the part arrive
SENSOR2_X = 340.0       # downstream: sees only straight-through parts
DIVERT_X = 250.0        # where the gate sits
DIVERT_Y = 120.0        # length of the side lane
SENSOR_TOL = 6.0
SPAWN_DELAY = 1.5       # gap between parts

lock = threading.Lock()

belt = 1.0
belt_target = 1.0
diverter = 0.0
diverter_target = 0.0

part_x = -100.0         # -100 means no part on the belt
part_y = 0.0
part_lane = "none"      # "none" | "belt" | "divert"
spawn_timer = 0.0

sensor1 = 0
sensor2 = 0
passed = 0
diverted = 0

last_published = {}


def reset_plant():
    global part_lane, spawn_timer, passed, diverted
    part_lane = "none"
    part_x = -100.0
    part_y = 0.0
    spawn_timer = 0.2
    passed = 0
    diverted = 0


def on_connect(client, *_args):
    client.subscribe("conveyor/target/#")
    client.subscribe("conveyor/command/reset")


def on_message(_client, _userdata, msg):
    global diverter_target, belt_target
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "conveyor/target/diverter":
                diverter_target = 1.0 if payload.lower() in ("1", "true", "on", "divert") else 0.0
            elif msg.topic == "conveyor/target/belt":
                belt_target = 1.0 if payload.lower() in ("1", "true", "on", "run") else 0.0
            elif msg.topic == "conveyor/command/reset":
                reset_plant()
        except ValueError:
            pass


def step(dt):
    global belt, diverter, part_x, part_y, part_lane, spawn_timer
    global sensor1, sensor2, passed, diverted

    with lock:
        if belt < belt_target:
            belt = min(belt_target, belt + dt / BELT_TIME)
        elif belt > belt_target:
            belt = max(belt_target, belt - dt / BELT_TIME)

        if diverter < diverter_target:
            diverter = min(diverter_target, diverter + dt / DIVERT_TIME)
        elif diverter > diverter_target:
            diverter = max(diverter_target, diverter - dt / DIVERT_TIME)

        speed = SPEED_MM_S * belt

        if part_lane == "none":
            spawn_timer -= dt
            if spawn_timer <= 0 and belt > 0.5:
                part_x = 0.0
                part_y = 0.0
                part_lane = "belt"

        elif part_lane == "belt":
            part_x += speed * dt
            if part_x >= DIVERT_X and diverter > 0.5:
                part_lane = "divert"
            elif part_x >= BELT_LEN:
                passed += 1
                part_lane = "none"
                spawn_timer = SPAWN_DELAY

        elif part_lane == "divert":
            part_y += speed * dt
            if part_y >= DIVERT_Y:
                diverted += 1
                part_lane = "none"
                spawn_timer = SPAWN_DELAY

        sensor1 = 1 if (part_lane == "belt" and abs(part_x - SENSOR1_X) < SENSOR_TOL) else 0
        sensor2 = 1 if (part_lane == "belt" and abs(part_x - SENSOR2_X) < SENSOR_TOL) else 0


def snapshot():
    with lock:
        return {
            "conveyor/sensor1": "1" if sensor1 else "0",
            "conveyor/sensor2": "1" if sensor2 else "0",
            "conveyor/part_x": "%.1f" % part_x,
            "conveyor/part_y": "%.1f" % part_y,
            "conveyor/diverter": "%.2f" % diverter,
            "conveyor/belt": "%.2f" % belt,
            "conveyor/passed": str(passed),
            "conveyor/diverted": str(diverted),
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
    print("Conveyor plant running (broker %s:%d)" % (BROKER, PORT))

    period = 1.0 / LOOP_HZ
    last = time.monotonic()
    last_alive = 0.0
    while True:
        now = time.monotonic()
        step(min(now - last, 0.2))
        last = now
        publish(client, snapshot())
        if now - last_alive >= 1.0:
            client.publish("conveyor/plant/alive", "%.0f" % time.time(), retain=True)
            last_alive = now
        time.sleep(max(0.0, period - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
