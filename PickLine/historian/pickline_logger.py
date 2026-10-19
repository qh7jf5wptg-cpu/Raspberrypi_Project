#!/usr/bin/env python3
"""Log the PickLine tags to SQLite (one row every 0.5 s)."""
import os
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
DB = os.environ.get("PICKLINE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pickline.db"))
SAMPLE_S = 0.5

tags = {"x": 0.0, "y": 0.0, "z": 60.0, "holding": 0, "belt": 0.0,
        "belt_pos": -1.0, "speed": 90.0, "diverter": 0.0, "placed": 0,
        "passed": 0, "diverted": 0, "exited": 0, "state": "IDLE",
        "mode": "auto", "side": "down", "decision": "STRAIGHT", "gap": 1.5}
con = None


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("pickline/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    try:
        if key in ("x", "y", "z", "belt", "belt_pos", "speed", "diverter", "gap"):
            tags[key] = float(payload)
        elif key in ("holding", "placed", "passed", "diverted", "exited"):
            tags[key] = int(float(payload))
        elif key in ("state", "mode", "side", "decision"):
            tags[key] = payload
    except ValueError:
        pass


def store():
    con.execute(
        "INSERT INTO log (ts, x, y, z, holding, belt, belt_pos, speed, diverter,"
        " placed, passed, diverted, exited, state, mode, side, decision, gap)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), tags["x"], tags["y"], tags["z"], tags["holding"],
         tags["belt"], tags["belt_pos"], tags["speed"], tags["diverter"],
         tags["placed"], tags["passed"], tags["diverted"], tags["exited"],
         tags["state"], tags["mode"], tags["side"], tags["decision"], tags["gap"]),
    )
    con.commit()


def print_stats(db_path):
    if not os.path.isfile(db_path):
        print("No log yet at", db_path)
        return
    c = sqlite3.connect(db_path)
    try:
        row = c.execute("SELECT COUNT(*), MIN(ts), MAX(ts), MAX(exited) FROM log").fetchone()
    except sqlite3.OperationalError:
        print("No log table in", db_path)
        return
    finally:
        c.close()
    count, first, last, exited = row
    if not count:
        print("The log is empty.")
        return
    print("Log file :", db_path)
    print("Samples  :", count)
    print("From     :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first)))
    print("To       :", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)))
    print("Exited   :", exited)


def main():
    global con
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS log (ts REAL, x REAL, y REAL, z REAL,"
        " holding INTEGER, belt REAL, belt_pos REAL, speed REAL, diverter REAL,"
        " placed INTEGER, passed INTEGER, diverted INTEGER, exited INTEGER,"
        " state TEXT, mode TEXT, side TEXT, decision TEXT, gap REAL)"
    )
    con.commit()
    print("Logging to", DB)

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe("pickline/#")
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
