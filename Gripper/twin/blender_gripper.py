"""Live Blender twin for the Gripper project.

Subscribes to gripper/# over MQTT and animates the gantry scene: the beam
follows Y, the carriage follows X, the tool follows Z, the jaws open and
close, and the parts appear at the stations.

Run from Blender's Scripting workspace (RUN_GRIPPER.py loads this file), or:
    blender Gripper_Twin.blend --python blender_gripper.py
"""
import os

import bpy
import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883
SCALE = 0.01  # millimetres -> Blender units (1 unit = 100 mm)

state = {
    "x": 0.0, "y": 0.0, "z": 60.0,
    "grip": 1.0, "part": 0, "placed": 0,
    "state": "IDLE", "count": 0, "alarm": "", "mode": "auto",
}


def _num(payload, default=0.0):
    try:
        return float(payload)
    except ValueError:
        return default


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("gripper/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    if key in ("x", "y", "z", "grip"):
        state[key] = _num(payload, state[key])
    elif key in ("part", "placed"):
        state[key] = int(_num(payload))
    elif key in ("state", "alarm", "mode"):
        state[key] = payload
    elif key == "count":
        state["count"] = int(_num(payload))


def _obj(name):
    return bpy.data.objects.get(name)


def _set_color(obj, color):
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
    x = state["x"] * SCALE
    y = state["y"] * SCALE
    z = state["z"] * SCALE
    grip = max(0.0, min(1.0, state["grip"]))

    beam = _obj("Beam")
    if beam:
        beam.location.y = y

    carriage = _obj("Carriage")
    if carriage:
        carriage.location.x = x
        carriage.location.y = y

    top, bottom = 2.25, z + 0.16
    rod = _obj("ZRod")
    if rod:
        rod.location.x = x
        rod.location.y = y
        rod.location.z = (top + bottom) / 2.0
        rod.scale.z = max(0.01, top - bottom)

    tool = _obj("Tool")
    if tool:
        tool.location = (x, y, z + 0.10)

    jaw_off = 0.06 + 0.08 * grip
    jaw_l = _obj("JawL")
    if jaw_l:
        jaw_l.location = (x - jaw_off, y, z + 0.06)
    jaw_r = _obj("JawR")
    if jaw_r:
        jaw_r.location = (x + jaw_off, y, z + 0.06)

    held = _obj("PartHeld")
    if held:
        held.location = (x, y, z + 0.06)
        held.hide_viewport = not bool(state["part"])
        held.hide_render = held.hide_viewport

    pick = _obj("PartPick")
    if pick:
        pick.hide_viewport = bool(state["part"])
        pick.hide_render = pick.hide_viewport

    delivered = _obj("PartPlaced")
    if delivered:
        visible = state["placed"] > 0
        delivered.hide_viewport = not visible
        delivered.hide_render = not visible

    # Tool colour: red on fault, green while holding a part, amber otherwise.
    if state["state"] == "FAULT":
        colour = (0.95, 0.15, 0.12, 1.0)
    elif state["part"]:
        colour = (0.20, 0.85, 0.35, 1.0)
    else:
        colour = (0.85, 0.55, 0.10, 1.0)
    for name in ("Tool", "JawL", "JawR"):
        obj = _obj(name)
        if obj:
            _set_color(obj, colour)

    text = _obj("StatusText")
    if text:
        text.data.body = "%s   placed %d" % (state["state"], state["count"])
        text_colour = (0.95, 0.20, 0.15, 1.0) if state["state"] == "FAULT" else (0.10, 0.90, 0.40, 1.0)
        text.color = text_colour
        if text.data.materials:
            mat = text.data.materials[0]
            mat.diffuse_color = text_colour
            if mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        node.inputs["Base Color"].default_value = text_colour
                        node.inputs["Emission Color"].default_value = text_colour
                        break

    return 0.05


def main():
    # Re-running the script replaces the previous timer and client.
    old_timer = bpy.app.driver_namespace.get("gripper_timer")
    if old_timer and bpy.app.timers.is_registered(old_timer):
        bpy.app.timers.unregister(old_timer)
    old_client = bpy.app.driver_namespace.get("gripper_client")
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
    client.subscribe("gripper/#")
    client.loop_start()

    bpy.app.driver_namespace["gripper_client"] = client
    bpy.app.driver_namespace["gripper_timer"] = apply_twin
    bpy.app.timers.register(apply_twin, first_interval=0.1)
    print("Gripper twin running (broker %s:%d)" % (BROKER, PORT))


main()
