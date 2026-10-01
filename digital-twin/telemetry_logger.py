#!/usr/bin/env python3
"""Log MQTT telemetry (temperature, LED, threshold) from the Raspberry Pi to a
SQLite database, so you can replay recorded sessions in Blender.

Run on the Mac (where the broker runs) while the Pi app is publishing:

    python3 telemetry_logger.py

Each temperature message stores one row in telemetry.db. Stop with Ctrl+C.

To see what is in the log without knowing any SQL:

    python3 telemetry_logger.py --stats
"""
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883
DB = os.environ.get(
    "TELEMETRY_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetry.db"),
)

latest = {"temperature": None, "led": None, "threshold": None}
con = None


def store():
    if con is None or latest["temperature"] is None:
        return
    con.execute(
        "INSERT INTO telemetry (ts, temperature, led, threshold) VALUES (?, ?, ?, ?)",
        (time.time(), latest["temperature"], latest["led"], latest["threshold"]),
    )
    con.commit()


def on_message(_client, _userdata, msg):
    payload = msg.payload.decode("utf-8").strip()
    try:
        if msg.topic == "machine/temperature":
            latest["temperature"] = float(payload)
            store()
        elif msg.topic == "machine/led":
            latest["led"] = 1 if payload in ("1", "true", "True", "on") else 0
        elif msg.topic == "machine/threshold":
            latest["threshold"] = float(payload)
    except ValueError:
        pass


def main():
    global con
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS telemetry "
        "(ts REAL, temperature REAL, led INTEGER, threshold REAL)"
    )
    con.commit()
    print("Logging to", DB)
    print("(leave this running, then press Ctrl+C to stop)")

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe("machine/#")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if con:
            con.close()
        print()
        print_stats(DB)


def print_stats(db_path):
    """Print a short summary, so the log can be checked without SQL."""
    if not os.path.isfile(db_path):
        print("No log file yet at", db_path)
        return

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT COUNT(*), MIN(temperature), MAX(temperature), MIN(ts), MAX(ts)"
            " FROM telemetry"
        ).fetchone()
    except sqlite3.OperationalError:
        print("The file at", db_path, "has no log table yet.")
        return
    finally:
        con.close()

    count, low, high, first, last = row
    if not count or low is None:
        print("The log at", db_path, "is empty.")
        return

    def stamp(value):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))

    print("Log file   :", db_path)
    print("Samples    :", count)
    print("Temperature: %.1f - %.1f deg C" % (low, high))
    print("From       :", stamp(first))
    print("To         :", stamp(last))
    print()
    print("Same queries by hand (copy and paste from anywhere):")
    print('  sqlite3 "%s" ".tables"' % db_path)
    print('  sqlite3 "%s" "SELECT * FROM telemetry ORDER BY ts DESC LIMIT 5;"' % db_path)


if __name__ == "__main__":
    if "--stats" in sys.argv[1:]:
        print_stats(DB)
    else:
        main()
