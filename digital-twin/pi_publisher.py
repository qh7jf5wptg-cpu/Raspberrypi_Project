#!/usr/bin/env python3
"""Publish machine temperature, threshold, and LED state over MQTT.

Run this on the Raspberry Pi (real /sys values) or on macOS (fake drifting
values) so you can develop before wiring real hardware.

Install:
    python3 -m pip install paho-mqtt

Run (broker on this machine):
    python3 pi_publisher.py

Run from the Pi when the broker is on your Mac:
    MQTT_BROKER=<mac-ip> python3 pi_publisher.py
"""

import math
import os
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883

TOPIC_TEMP = "machine/temperature"
TOPIC_LED = "machine/led"
TOPIC_THRESHOLD = "machine/threshold"

THRESHOLD = 60.0       # degrees C
INTERVAL = 1.0         # seconds

_tick = 0


def read_temperature_c() -> float:
    """Read the CPU temperature on the Pi, or fake a drifting value elsewhere."""
    global _tick
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as fh:
            return int(fh.read().strip()) / 1000.0
    except (OSError, ValueError):
        # macOS / no sensor: fake a slowly moving value (35..55 C).
        _tick += 1
        return 45.0 + 10.0 * math.sin(_tick * 0.05)


def main() -> None:
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()  # paho-mqtt 1.x

    client.connect(BROKER, PORT, 60)
    client.loop_start()
    print(f"Publishing to {BROKER}:{PORT} on machine/#")

    try:
        while True:
            temp = read_temperature_c()
            led = 1 if temp > THRESHOLD else 0
            client.publish(TOPIC_TEMP, f"{temp:.1f}")
            client.publish(TOPIC_LED, led)
            client.publish(TOPIC_THRESHOLD, f"{THRESHOLD:.1f}")
            print(f"temp={temp:.1f} C  led={'ON' if led else 'OFF'}")
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
