"""Live Blender twin for the PickLine (gantry + conveyor + two fill stations).

Maps the plant's top-view world (mm) onto the Blender ground plane (m):
    world (x, y, z)  ->  Blender (x/100, y/100, z/100)
"""
import os

import bpy
import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883

state = {"x": 0.0, "y": 0.0, "z": 60.0, "grip": 1.0, "holding": 0,
         "part_x": -1.0, "part_y": -1.0, "belt": 0.0, "speed": 90.0,
         "diverter": 0.0, "sensor_in": 0, "sensor_out": 0, "sensor_divert": 0,
         "placed": 0, "exited": 0, "state": "IDLE", "side": "down",
         "decision": "STRAIGHT", "gap": 0.5, "volume": 100.0,
         "fill/a/level": 0.0, "fill/a/state": "EMPTY", "fill/a/count": 0,
         "fill/b/level": 0.0, "fill/b/state": "EMPTY", "fill/b/count": 0,
         "fill/total": 0.0}


def _num(payload, default=0.0):
    try:
        return float(payload)
    except ValueError:
        return default


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("pickline/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    if key in ("x", "y", "z", "grip", "belt", "speed", "diverter", "part_x",
               "part_y", "gap", "volume", "fill/a/level", "fill/b/level", "fill/total"):
        state[key] = _num(payload, state[key])
    elif key in ("holding", "sensor_in", "sensor_out", "sensor_divert",
                 "placed", "exited", "fill/a/count", "fill/b/count"):
        state[key] = int(_num(payload))
    elif key in ("state", "side", "decision", "fill/a/state", "fill/b/state"):
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


def set_liquid(key, liquid_name, sx, sy):
    liquid = _obj(liquid_name)
    if liquid is None:
        return
    vol = max(state.get("volume", 100.0), 1e-6)
    lvl = max(0.0, state.get("fill/" + key + "/level", 0.0))
    h = max(0.02, (lvl / vol) * 0.54)
    liquid.scale = (0.13, 0.13, h)
    liquid.location = (sx, sy, 0.02 + h / 2.0)
    full = state.get("fill/" + key + "/state", "") == "FULL"
    _set_color(liquid, (0.15, 0.80, 0.35, 1.0) if full else (0.10, 0.55, 0.90, 1.0))


def apply_twin():
    tool = _obj("ToolHead")
    jaw_a = _obj("JawA")
    jaw_b = _obj("JawB")

    if tool:
        tool.location = (state["x"] * 0.01, state["y"] * 0.01, state["z"] * 0.01)

    gap = 0.05 + 0.05 * state["grip"]
    if jaw_a:
        jaw_a.location = (tool.location[0], tool.location[1] + gap, tool.location[2] - 0.16)
    if jaw_b:
        jaw_b.location = (tool.location[0], tool.location[1] - gap, tool.location[2] - 0.16)

    part = _obj("Part")
    if part:
        if state["holding"]:
            part.location = (tool.location[0], tool.location[1], tool.location[2] - 0.10)
        elif state["part_x"] >= 0:
            part.location = (state["part_x"] * 0.01, state["part_y"] * 0.01, 0.06)
        else:
            part.location = (100.0, 100.0, 100.0)

    gate = _obj("Gate")
    if gate:
        gate.rotation_euler = (0.0, 0.0, -1.1 * state["diverter"])
        _set_color(gate, (0.20, 0.85, 0.35, 1.0) if state["diverter"] > 0.5 else (0.85, 0.30, 0.22, 1.0))

    for name in ("RollerL", "RollerR"):
        roller = _obj(name)
        if roller and state["belt"] > 0.5:
            roller.rotation_euler[0] += 0.02 * state["speed"] / 90.0

    _set_color(_obj("SensorIn"), (0.2, 0.9, 0.35, 1.0) if state["sensor_in"] else (0.18, 0.22, 0.26, 1.0))
    _set_color(_obj("SensorOut"), (0.2, 0.9, 0.35, 1.0) if state["sensor_out"] else (0.18, 0.22, 0.26, 1.0))
    _set_color(_obj("SensorDivert"), (0.2, 0.9, 0.35, 1.0) if state["sensor_divert"] else (0.18, 0.22, 0.26, 1.0))

    set_liquid("a", "LiquidA", 4.0, 1.0)
    set_liquid("b", "LiquidB", 4.0, 2.2)

    text = _obj("StatusText")
    if text:
        text.data.body = "%s   %s   fills A%d B%d   total %.0f u" % (
            state["state"], state["decision"],
            state["fill/a/count"], state["fill/b/count"], state["fill/total"])
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
