#!/usr/bin/env python3
"""Log the conveyor tags to SQLite (one row every 0.5 s)."""
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
DB = os.environ.get(
    "CONVEYOR_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "conveyor.db"),
)
SAMPLE_S = 0.5

tags = {"sensor1": 0, "sensor2": 0, "part_x": 0.0, "part_y": 0.0,
        "diverter": 0.0, "belt": 1.0, "passed": 0, "diverted": 0,
        "state": "IDLE", "decision": "STRAIGHT"}
con = None


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("conveyor/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    try:
        if key in ("part_x", "part_y", "diverter", "belt"):
            tags[key] = float(payload)
        elif key in ("sensor1", "sensor2", "passed", "diverted"):
            tags[key] = int(float(payload))
        elif key in ("state", "decision"):
            tags[key] = payload
    except ValueError:
        pass


def store():
    con.execute(
        "INSERT INTO log (ts, sensor1, sensor2, part_x, part_y, diverter, belt,"
        " passed, diverted, state, decision)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), tags["sensor1"], tags["sensor2"], tags["part_x"],
         tags["part_y"], tags["diverter"], tags["belt"], tags["passed"],
         tags["diverted"], tags["state"], tags["decision"]),
    )
    con.commit()


def print_stats(db_path):
    if not os.path.isfile(db_path):
        print("No log yet at", db_path)
        return
    c = sqlite3.connect(db_path)
    try:
        row = c.execute("SELECT COUNT(*), MIN(ts), MAX(ts), MAX(passed), MAX(diverted) FROM log").fetchone()
    except sqlite3.OperationalError:
        print("No log table in", db_path)
        return
    finally:
        c.close()
    count, first, last, passed, diverted = row
    if not count:
        print("The log is empty.")
        return
    print("Log file    :", db_path)
    print("Samples     :", count)
    print("From        :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first)))
    print("To          :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)))
    print("Passed      :", passed)
    print("Diverted    :", diverted)


def main():
    global con
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS log (ts REAL, sensor1 INTEGER, sensor2 INTEGER,"
        " part_x REAL, part_y REAL, diverter REAL, belt REAL, passed INTEGER,"
        " diverted INTEGER, state TEXT, decision TEXT)"
    )
    con.commit()
    print("Logging to", DB)

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe("conveyor/#")
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
