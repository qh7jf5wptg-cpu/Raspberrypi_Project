"""Live Blender twin for the PickLine (gantry + conveyor, two exits).

Maps the plant's top-view world (mm) onto the Blender ground plane (m):
    world (x, y, z)  ->  Blender (x/100, y/100, z/100)
"""
import math
import os

import bpy
import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883

state = {"x": 0.0, "y": 0.0, "z": 60.0, "grip": 1.0, "holding": 0,
         "part_x": -1.0, "part_y": -1.0, "belt": 0.0, "speed": 90.0,
         "diverter": 0.0, "sensor_in": 0, "sensor_out": 0, "sensor_divert": 0,
         "placed": 0, "passed": 0, "diverted": 0, "state": "IDLE",
         "side": "down", "decision": "STRAIGHT", "gap": 1.5}


def _num(payload, default=0.0):
    try:
        return float(payload)
    except ValueError:
        return default


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("pickline/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    if key in ("x", "y", "z", "grip", "belt", "speed", "diverter", "part_x", "part_y", "gap"):
        state[key] = _num(payload, state[key])
    elif key in ("holding", "sensor_in", "sensor_out", "sensor_divert",
                 "placed", "passed", "diverted"):
        state[key] = int(_num(payload))
    elif key in ("state", "side", "decision"):
        state[key] = payload


def _obj(name):
    return bpy.data.objects.get(name)


def _set_color(obj, color):
    if obj is None:
        return
    obj.color = color
    if obj.data.materials:
        mat = obj.data.materials[0]
        mat.diffuse_color = color
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    node.inputs["Base Color"].default_value = color
                    break


def apply_twin():
    tool = _obj("ToolHead")
    jaw_a = _obj("JawA")
    jaw_b = _obj("JawB")

    if tool:
        tool.location = (state["x"] * 0.01, state["y"] * 0.01, state["z"] * 0.01)

    # Jaws open/close around the tool head.
    gap = 0.05 + 0.05 * state["grip"]
    if jaw_a:
        jaw_a.location = (tool.location[0], tool.location[1] + gap, tool.location[2] - 0.16)
    if jaw_b:
        jaw_b.location = (tool.location[0], tool.location[1] - gap, tool.location[2] - 0.16)

    # Part: follows the tool while held, rides the belt / side lane otherwise.
    part = _obj("Part")
    if part:
        if state["holding"]:
            part.location = (tool.location[0], tool.location[1], tool.location[2] - 0.10)
        elif state["part_x"] >= 0:
            part.location = (state["part_x"] * 0.01, state["part_y"] * 0.01, 0.06)
        else:
            part.location = (100.0, 100.0, 100.0)

    # End gate swings onto the side lane while diverting.
    gate = _obj("Gate")
    if gate:
        gate.rotation_euler = (0.0, 0.0, -1.1 * state["diverter"])
        _set_color(gate, (0.20, 0.85, 0.35, 1.0) if state["diverter"] > 0.5 else (0.85, 0.30, 0.22, 1.0))

    # Rollers spin while the belt runs.
    for name in ("RollerL", "RollerR"):
        roller = _obj(name)
        if roller and state["belt"] > 0.5:
            roller.rotation_euler[0] += 0.02 * state["speed"] / 90.0

    # Sensors light green when they see the part.
    _set_color(_obj("SensorIn"), (0.2, 0.9, 0.35, 1.0) if state["sensor_in"] else (0.18, 0.22, 0.26, 1.0))
    _set_color(_obj("SensorOut"), (0.2, 0.9, 0.35, 1.0) if state["sensor_out"] else (0.18, 0.22, 0.26, 1.0))
    _set_color(_obj("SensorDivert"), (0.2, 0.9, 0.35, 1.0) if state["sensor_divert"] else (0.18, 0.22, 0.26, 1.0))

    text = _obj("StatusText")
    if text:
        text.data.body = "%s   side %s   %s   out %d (%d/%d)" % (
            state["state"], state["side"], state["decision"],
            state["passed"] + state["diverted"], state["passed"], state["diverted"])
        color = (0.95, 0.20, 0.15, 1.0) if state["state"] == "FAULT" else (0.10, 0.90, 0.40, 1.0)
        text.color = color
        if text.data.materials:
            mat = text.data.materials[0]
            mat.diffuse_color = color
            if mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        node.inputs["Base Color"].default_value = color
                        node.inputs["Emission Color"].default_value = color
                        break

    return 0.05


def main():
    old_timer = bpy.app.driver_namespace.get("pickline_timer")
    if old_timer and bpy.app.timers.is_registered(old_timer):
        bpy.app.timers.unregister(old_timer)
    old_client = bpy.app.driver_namespace.get("pickline_client")
    if old_client:
        try:
            old_client.loop_stop()
            old_client.disconnect()
        except Exception:
            pass

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.subscribe("pickline/#")
    client.loop_start()

    bpy.app.driver_namespace["pickline_client"] = client
    bpy.app.driver_namespace["pickline_timer"] = apply_twin
    bpy.app.timers.register(apply_twin, first_interval=0.1)
    print("PickLine twin running (broker %s:%d)" % (BROKER, PORT))


main()
