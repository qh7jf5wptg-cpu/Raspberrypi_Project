#!/usr/bin/env python3
"""Soft PLC for the conveyor digital twin.

Reads the upstream sensor and decides, part by part, whether to divert. Three
modes:
    alternate   - divert every other part
    divert_all  - divert every part
    pass_all    - never divert

Commands:
    mosquitto_pub -t conveyor/command/mode  -m alternate
    mosquitto_pub -t conveyor/command/start -m 1
    mosquitto_pub -t conveyor/command/stop  -m 1
    mosquitto_pub -t conveyor/command/reset -m 1
"""
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
LOOP_HZ = 10.0

lock = threading.Lock()
client = None

sensor1 = 0
sensor1_prev = 0
state = "IDLE"
mode = "alternate"
started = False
decision = "STRAIGHT"
alternate_flag = False
alarm = ""
last = {}


def on_connect(cli, *_args):
    cli.subscribe("conveyor/sensor1")
    cli.subscribe("conveyor/sensor2")
    cli.subscribe("conveyor/command/#")


def publish_status():
    values = {
        "conveyor/state": state,
        "conveyor/mode": mode,
        "conveyor/decision": decision,
        "conveyor/alarm": alarm,
    }
    for topic, payload in values.items():
        if last.get(topic) != payload:
            client.publish(topic, payload, retain=True)
            last[topic] = payload


def apply_decision(value):
    global decision
    decision = "DIVERT" if value else "STRAIGHT"
    client.publish("conveyor/target/diverter", "1" if value else "0", retain=True)


def decide_next():
    global alternate_flag
    if mode == "divert_all":
        apply_decision(True)
    elif mode == "pass_all":
        apply_decision(False)
    else:  # alternate
        alternate_flag = not alternate_flag
        apply_decision(alternate_flag)


def on_message(_cli, _userdata, msg):
    global sensor1, state, mode, started, decision, alternate_flag, alarm
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        if msg.topic == "conveyor/sensor1":
            try:
                sensor1 = int(float(payload or 0))
            except ValueError:
                pass
        elif msg.topic == "conveyor/command/start":
            started = True
            state = "RUNNING"
            alarm = ""
            alternate_flag = False
            apply_decision(False)
            client.publish("conveyor/target/belt", "1", retain=True)
        elif msg.topic == "conveyor/command/stop":
            started = False
            state = "IDLE"
            client.publish("conveyor/target/belt", "0", retain=True)
        elif msg.topic == "conveyor/command/reset":
            started = False
            state = "IDLE"
            alarm = ""
            decision = "STRAIGHT"
            alternate_flag = False
            client.publish("conveyor/target/belt", "0", retain=True)
            client.publish("conveyor/command/reset", "1", retain=False)
        elif msg.topic == "conveyor/command/mode":
            mode = payload.lower() if payload.lower() in ("alternate", "divert_all", "pass_all") else "alternate"
            if mode != "alternate":
                alternate_flag = False


def tick():
    global sensor1_prev
    with lock:
        if not started:
            return
        if sensor1 == 1 and sensor1_prev == 0:
            decide_next()
        sensor1_prev = sensor1


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
    print("Conveyor PLC running (broker %s:%d)" % (BROKER, PORT))
    publish_status()

    period = 1.0 / LOOP_HZ
    last_alive = 0.0
    while True:
        tick()
        publish_status()
        if time.monotonic() - last_alive >= 1.0:
            client.publish("conveyor/plc/alive", "%.0f" % time.time(), retain=True)
            last_alive = time.monotonic()
        time.sleep(period)


if __name__ == "__main__":
    main()
