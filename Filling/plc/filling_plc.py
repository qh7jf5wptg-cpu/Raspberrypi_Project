#!/usr/bin/env python3
"""Soft PLC for the filling station.

Auto: open the valve, run the pump, fill to the setpoint, stop. Wait a short
change-over, then start the next batch.

Commands:
    mosquitto_pub -t fill/command/mode     -m auto|manual
    mosquitto_pub -t fill/command/setpoint -m 85
    mosquitto_pub -t fill/command/start    -m 1
    mosquitto_pub -t fill/command/stop     -m 1
    mosquitto_pub -t fill/command/reset    -m 1
"""
import os
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
LOOP_HZ = 10.0

HIGH_SETPOINT = 90.0
CHANGE_OVER = 2.0     # seconds between batches

lock = threading.Lock()
client = None

level = 0.0
state = "IDLE"
mode = "auto"
setpoint = HIGH_SETPOINT
started = False
batches = 0
batch_done_time = 0.0
alarm = ""
last = {}


def on_connect(cli, *_args):
    cli.subscribe("fill/level")
    cli.subscribe("fill/command/#")


def set_actuators(pump_on, valve_on):
    client.publish("fill/target/pump", "1" if pump_on else "0", retain=True)
    client.publish("fill/target/valve", "1" if valve_on else "0", retain=True)


def publish_status():
    values = {
        "fill/state": state,
        "fill/mode": mode,
        "fill/setpoint": "%.1f" % setpoint,
        "fill/batches": str(batches),
        "fill/alarm": alarm,
    }
    for topic, payload in values.items():
        if last.get(topic) != payload:
            client.publish(topic, payload, retain=True)
            last[topic] = payload


def on_message(_cli, _userdata, msg):
    global level, state, mode, setpoint, started, batches, alarm
    payload = msg.payload.decode("utf-8", "replace").strip()
    with lock:
        if msg.topic == "fill/level":
            try:
                level = float(payload)
            except ValueError:
                pass
        elif msg.topic == "fill/command/start":
            if mode == "auto":
                started = True
                state = "FILLING"
                alarm = ""
                set_actuators(True, True)
        elif msg.topic == "fill/command/stop":
            started = False
            state = "IDLE"
            set_actuators(False, False)
        elif msg.topic == "fill/command/reset":
            started = False
            state = "IDLE"
            batches = 0
            alarm = ""
            set_actuators(False, False)
            client.publish("fill/plant/reset", "1", retain=False)
        elif msg.topic == "fill/command/mode":
            mode = "manual" if payload.lower() == "manual" else "auto"
            if mode == "manual":
                started = False
                state = "MANUAL"
            else:
                state = "IDLE"
        elif msg.topic == "fill/command/setpoint":
            try:
                setpoint = max(5.0, min(100.0, float(payload)))
            except ValueError:
                pass


def tick(now):
    global state, batches, batch_done_time
    with lock:
        if mode == "manual" or not started:
            return
        if state == "FILLING":
            if level >= setpoint:
                set_actuators(False, False)
                state = "FULL"
                batch_done_time = now
        elif state == "FULL":
            if now - batch_done_time >= CHANGE_OVER:
                batches += 1
                client.publish("fill/plant/reset", "1", retain=False)
                set_actuators(True, True)
                state = "FILLING"


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
    print("Filling PLC running (broker %s:%d)" % (BROKER, PORT))
    publish_status()

    period = 1.0 / LOOP_HZ
    last_alive = 0.0
    while True:
        tick(time.monotonic())
        publish_status()
        if time.monotonic() - last_alive >= 1.0:
            client.publish("fill/plc/alive", "%.0f" % time.time(), retain=True)
            last_alive = time.monotonic()
        time.sleep(period)


if __name__ == "__main__":
    main()
