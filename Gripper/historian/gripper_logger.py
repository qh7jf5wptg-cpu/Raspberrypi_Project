#!/usr/bin/env python3
"""Log the Gripper twin's tags to SQLite.

    python3 gripper_logger.py            # start logging (one row every 0.5 s)
    python3 gripper_logger.py --stats    # summarise the existing log
"""
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
DB = os.environ.get(
    "GRIPPER_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "gripper.db"),
)
SAMPLE_S = 0.5

tags = {"x": 0.0, "y": 0.0, "z": 0.0, "grip": 1.0, "part": 0,
        "placed": 0, "state": "IDLE", "mode": "auto"}
con = None


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("gripper/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    try:
        if key in ("x", "y", "z", "grip"):
            tags[key] = float(payload)
        elif key in ("part", "placed"):
            tags[key] = int(float(payload))
        elif key in ("state", "mode"):
            tags[key] = payload
    except ValueError:
        pass


def store():
    con.execute(
        "INSERT INTO log (ts, x, y, z, grip, part, placed, state, mode)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (time.time(), tags["x"], tags["y"], tags["z"], tags["grip"],
         tags["part"], tags["placed"], tags["state"], tags["mode"]),
    )
    con.commit()


def print_stats(db_path):
    if not os.path.isfile(db_path):
        print("No log yet at", db_path)
        return
    c = sqlite3.connect(db_path)
    try:
        row = c.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts), MAX(placed) FROM log"
        ).fetchone()
    except sqlite3.OperationalError:
        print("No log table in", db_path)
        return
    finally:
        c.close()
    count, first, last, placed = row
    if not count:
        print("The log is empty.")
        return
    print("Log file   :", db_path)
    print("Samples    :", count)
    print("From       :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first)))
    print("To         :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)))
    print("Parts placed:", placed)


def main():
    global con
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS log (ts REAL, x REAL, y REAL, z REAL,"
        " grip REAL, part INTEGER, placed INTEGER, state TEXT, mode TEXT)"
    )
    con.commit()
    print("Logging to", DB)

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe("gripper/#")
    client.loop_start()

    try:
        while True:
            time.sleep(SAMPLE_S)
            store()
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        con.close()
        print()
        print_stats(DB)


if __name__ == "__main__":
    if "--stats" in sys.argv[1:]:
        print_stats(DB)
    else:
        main()
