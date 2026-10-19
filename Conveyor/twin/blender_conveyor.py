"""Live Blender twin for the conveyor project."""
import os

import bpy
import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883
SCALE = 0.01

state = {
    "sensor1": 0, "sensor2": 0, "part_x": -100.0, "part_y": 0.0,
    "diverter": 0.0, "belt": 1.0, "passed": 0, "diverted": 0,
    "state": "IDLE", "decision": "STRAIGHT", "mode": "alternate",
}


def _num(payload, default=0.0):
    try:
        return float(payload)
    except ValueError:
        return default


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("conveyor/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    if key in ("part_x", "part_y", "diverter", "belt"):
        state[key] = _num(payload, state[key])
    elif key in ("sensor1", "sensor2", "passed", "diverted"):
        state[key] = int(_num(payload))
    elif key in ("state", "decision", "mode"):
        state[key] = payload


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
    part = _obj("Part")
    if part:
        if state["part_x"] < 0:
            part.hide_viewport = True
            part.hide_render = True
        else:
            part.hide_viewport = False
            part.hide_render = False
            part.location = (state["part_x"] * SCALE, state["part_y"] * SCALE, 0.12)

    gate = _obj("Gate")
    if gate:
        gate.location.y = 0.03 + state["diverter"] * 0.30

    sensor1 = _obj("Sensor1")
    if sensor1:
        _set_color(sensor1, (0.20, 0.90, 0.35, 1.0) if state["sensor1"] else (0.20, 0.25, 0.30, 1.0))
    sensor2 = _obj("Sensor2")
    if sensor2:
        _set_color(sensor2, (0.20, 0.90, 0.35, 1.0) if state["sensor2"] else (0.20, 0.25, 0.30, 1.0))

    belt = _obj("Belt")
    if belt:
        _set_color(belt, (0.35, 0.52, 0.68, 1.0) if state["belt"] > 0.5 else (0.20, 0.22, 0.25, 1.0))

    text = _obj("StatusText")
    if text:
        text.data.body = "%s  %s  passed %d  diverted %d" % (
            state["state"], state["decision"], state["passed"], state["diverted"])
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
    old_timer = bpy.app.driver_namespace.get("conveyor_timer")
    if old_timer and bpy.app.timers.is_registered(old_timer):
        bpy.app.timers.unregister(old_timer)
    old_client = bpy.app.driver_namespace.get("conveyor_client")
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
    client.subscribe("conveyor/#")
    client.loop_start()

    bpy.app.driver_namespace["conveyor_client"] = client
    bpy.app.driver_namespace["conveyor_timer"] = apply_twin
    bpy.app.timers.register(apply_twin, first_interval=0.1)
    print("Conveyor twin running (broker %s:%d)" % (BROKER, PORT))


main()
