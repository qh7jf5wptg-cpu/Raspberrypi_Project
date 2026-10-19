#!/usr/bin/env python3
"""Filling station plant model: a tank, an inlet valve and a pump.

The tank fills only when the pump is running AND the valve is open. The level
sensor is the fill level itself (0-100 %).

Run:
    python3 filling_plant.py
    MQTT_BROKER=192.168.50.1 python3 filling_plant.py
"""
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))

FILL_RATE = 8.0       # percent per second
ACTUATE_TIME = 0.3    # seconds for pump/valve to change
LOOP_HZ = 20.0

lock = threading.Lock()

level = 0.0
pump = 0.0
pump_target = 0.0
valve = 0.0
valve_target = 0.0

last_published = {}


def on_connect(client, *_args):
    client.subscribe("fill/target/#")
    client.subscribe("fill/plant/reset")


def on_message(_client, _userdata, msg):
    global pump_target, valve_target, level
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        try:
            if msg.topic == "fill/target/pump":
                pump_target = 1.0 if payload.lower() in ("1", "true", "on", "run") else 0.0
            elif msg.topic == "fill/target/valve":
                valve_target = 1.0 if payload.lower() in ("1", "true", "on", "open") else 0.0
            elif msg.topic == "fill/plant/reset":
                level = 0.0
        except ValueError:
            pass


def step(dt):
    global pump, valve, level
    with lock:
        if pump < pump_target:
            pump = min(pump_target, pump + dt / ACTUATE_TIME)
        elif pump > pump_target:
            pump = max(pump_target, pump - dt / ACTUATE_TIME)

        if valve < valve_target:
            valve = min(valve_target, valve + dt / ACTUATE_TIME)
        elif valve > valve_target:
            valve = max(valve_target, valve - dt / ACTUATE_TIME)

        if pump > 0.5 and valve > 0.5:
            level = min(100.0, level + FILL_RATE * dt)


def snapshot():
    with lock:
        filling = 1 if (pump > 0.5 and valve > 0.5 and level < 100.0) else 0
        return {
            "fill/level": "%.1f" % level,
            "fill/pump": "%.2f" % pump,
            "fill/valve": "%.2f" % valve,
            "fill/filling": "1" if filling else "0",
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
    print("Filling plant running (broker %s:%d)" % (BROKER, PORT))

    period = 1.0 / LOOP_HZ
    last = time.monotonic()
    last_alive = 0.0
    while True:
        now = time.monotonic()
        step(min(now - last, 0.2))
        last = now
        publish(client, snapshot())
        if now - last_alive >= 1.0:
            client.publish("fill/plant/alive", "%.0f" % time.time(), retain=True)
            last_alive = now
        time.sleep(max(0.0, period - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
