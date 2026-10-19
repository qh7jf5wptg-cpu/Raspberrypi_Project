#!/usr/bin/env python3
"""Log the filling station tags to SQLite (one row every 0.5 s)."""
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
DB = os.environ.get("FILLING_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "filling.db"))
SAMPLE_S = 0.5

tags = {"level": 0.0, "pump": 0.0, "valve": 0.0, "filling": 0,
        "state": "IDLE", "setpoint": 90.0, "batches": 0}
con = None


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("fill/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    try:
        if key in ("level", "pump", "valve", "setpoint"):
            tags[key] = float(payload)
        elif key in ("filling", "batches"):
            tags[key] = int(float(payload))
        elif key == "state":
            tags[key] = payload
    except ValueError:
        pass


def store():
    con.execute(
        "INSERT INTO log (ts, level, pump, valve, filling, state, setpoint, batches)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (time.time(), tags["level"], tags["pump"], tags["valve"], tags["filling"],
         tags["state"], tags["setpoint"], tags["batches"]),
    )
    con.commit()


def print_stats(db_path):
    if not os.path.isfile(db_path):
        print("No log yet at", db_path)
        return
    c = sqlite3.connect(db_path)
    try:
        row = c.execute("SELECT COUNT(*), MIN(ts), MAX(ts), MAX(batches) FROM log").fetchone()
    except sqlite3.OperationalError:
        print("No log table in", db_path)
        return
    finally:
        c.close()
    count, first, last, batches = row
    if not count:
        print("The log is empty.")
        return
    print("Log file :", db_path)
    print("Samples  :", count)
    print("From     :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first)))
    print("To       :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)))
    print("Batches  :", batches)


def main():
    global con
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS log (ts REAL, level REAL, pump REAL, valve REAL,"
        " filling INTEGER, state TEXT, setpoint REAL, batches INTEGER)"
    )
    con.commit()
    print("Logging to", DB)

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe("fill/#")
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
