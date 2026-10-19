"""Live Blender twin for the filling station."""
import math
import os

import bpy
import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883

state = {"level": 0.0, "pump": 0.0, "valve": 0.0, "filling": 0,
         "state": "IDLE", "mode": "auto", "setpoint": 90.0, "batches": 0}


def _num(payload, default=0.0):
    try:
        return float(payload)
    except ValueError:
        return default


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("fill/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    if key in ("level", "pump", "valve", "setpoint"):
        state[key] = _num(payload, state[key])
    elif key in ("filling", "batches"):
        state[key] = int(_num(payload))
    elif key in ("state", "mode"):
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
    liquid = _obj("Liquid")
    if liquid:
        height = max(0.02, state["level"] / 100.0 * 1.85)
        liquid.scale.z = height
        liquid.location.z = height / 2.0

    pump = _obj("Pump")
    if pump:
        _set_color(pump, (0.20, 0.85, 0.35, 1.0) if state["pump"] > 0.5 else (0.55, 0.58, 0.62, 1.0))
        if state["pump"] > 0.5:
            pump.rotation_euler.z += 0.3

    valve = _obj("Valve")
    if valve:
        valve.rotation_euler.z = (math.pi / 2.0) * state["valve"]
        _set_color(valve, (0.20, 0.85, 0.35, 1.0) if state["valve"] > 0.5 else (0.85, 0.30, 0.20, 1.0))

    sensor = _obj("Sensor")
    if sensor:
        _set_color(sensor, (0.20, 0.90, 0.35, 1.0) if state["filling"] else (0.20, 0.25, 0.30, 1.0))

    text = _obj("StatusText")
    if text:
        text.data.body = "%s   level %d %%   batches %d" % (
            state["state"], state["level"], state["batches"])
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
    old_timer = bpy.app.driver_namespace.get("filling_timer")
    if old_timer and bpy.app.timers.is_registered(old_timer):
        bpy.app.timers.unregister(old_timer)
    old_client = bpy.app.driver_namespace.get("filling_client")
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
    client.subscribe("fill/#")
    client.loop_start()

    bpy.app.driver_namespace["filling_client"] = client
    bpy.app.driver_namespace["filling_timer"] = apply_twin
    bpy.app.timers.register(apply_twin, first_interval=0.1)
    print("Filling twin running (broker %s:%d)" % (BROKER, PORT))


main()
