#!/usr/bin/env python3
"""Blender digital-twin driver (bidirectional).

Shows the Pi's live state (temperature text, heat bar, spinning rotor, LED
color) and lets you control the Pi from a Blender sidebar panel (LED toggle +
threshold slider).

Run from Blender's Scripting workspace (Run Script).
"""

import bpy
import math
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883

state = {"temperature": 0.0, "led": False, "threshold": 60.0}

_client = None
_pub = {"led": None, "threshold": None}
_switch = {"last_up": None, "last_state": None}


def on_message(_client, _userdata, msg):
    try:
        payload = msg.payload.decode("utf-8").strip()
        if msg.topic == "machine/temperature":
            state["temperature"] = float(payload)
        elif msg.topic == "machine/led":
            state["led"] = payload in ("1", "true", "True", "on")
        elif msg.topic == "machine/threshold":
            state["threshold"] = float(payload)
    except (ValueError, UnicodeDecodeError):
        pass


def _set_material_color(name, color):
    mat = bpy.data.materials.get(name)
    if not mat or not mat.use_nodes:
        return
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            node.inputs["Base Color"].default_value = color
            break


def _set_led_material(on):
    # Material (shown in Material Preview / Rendered views)
    mat = bpy.data.materials.get("LED")
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                if on:
                    node.inputs["Base Color"].default_value = (1.0, 0.05, 0.05, 1.0)
                    node.inputs["Emission Color"].default_value = (1.0, 0.0, 0.0, 1.0)
                    node.inputs["Emission Strength"].default_value = 5.0
                else:
                    node.inputs["Base Color"].default_value = (0.04, 0.04, 0.04, 1.0)
                    node.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)
                    node.inputs["Emission Strength"].default_value = 0.0
                break

    # Viewport display color (also shown in Solid view)
    obj = bpy.data.objects.get("LED")
    if obj:
        obj.color = (1.0, 0.1, 0.1, 1.0) if on else (0.12, 0.12, 0.12, 1.0)


def _heat_color(t):
    # Map 30..80 C to blue -> red.
    x = max(0.0, min(1.0, (t - 30.0) / 50.0))
    return (x, 0.25 * (1.0 - x) + 0.05, 1.0 - x, 1.0)


def ensure_objects():
    """Create the temperature text and heat bar if the .blend lacks them."""
    # Temperature text: create if missing, then make it big and bright.
    obj = bpy.data.objects.get("TempText")
    if obj is None:
        curve = bpy.data.curves.new("TempText", type="FONT")
        curve.body = "45.0 C"
        curve.align_x = "CENTER"
        obj = bpy.data.objects.new("TempText", curve)
        bpy.context.collection.objects.link(obj)

    obj.location = (0.0, 0.0, 1.05)
    obj.scale = (0.65, 0.65, 0.65)

    mat = bpy.data.materials.get("TempTextMat")
    if mat is None:
        mat = bpy.data.materials.new("TempTextMat")
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (1.0, 0.9, 0.2, 1.0)
        bsdf.inputs["Emission Color"].default_value = (1.0, 0.9, 0.2, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 3.0
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    if "Heatbar" not in bpy.data.objects:
        mat = bpy.data.materials.new("Heatbar")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.10, 0.35, 0.90, 1.0)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(1.55, 0.0, 0.22))
        heat = bpy.context.object
        heat.name = "Heatbar"
        heat.scale = (0.07, 0.07, 0.34)
        heat.data.materials.append(mat)

    # Toggle switch (3D representation of the LED state).
    if "SwitchBase" not in bpy.data.objects:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(-1.25, 0.0, 0.16))
        base = bpy.context.object
        base.name = "SwitchBase"
        base.scale = (0.34, 0.16, 0.07)

    if "SwitchLever" not in bpy.data.objects:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(-1.25, 0.0, 0.28))
        lever = bpy.context.object
        lever.name = "SwitchLever"
        lever.scale = (0.26, 0.025, 0.025)
        mat = bpy.data.materials.new("SwitchLeverMat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.15, 0.15, 0.2, 1.0)
        lever.data.materials.append(mat)


def apply_twin():
    scene = bpy.context.scene

    # Rotor: speed proportional to temperature.
    rotor = bpy.data.objects.get("Rotor")
    if rotor:
        rotor.rotation_euler.z += state["temperature"] * 0.002

    # LED material: red when on, dark when off.
    _set_led_material(state["led"])

    # Toggle switch lever: rotate it in the viewport to control the LED,
    # and it snaps to reflect the Pi's actual state.
    lever = bpy.data.objects.get("SwitchLever")
    if lever:
        lever_up = lever.rotation_euler.x > 0

        # If the user flipped the lever, update the panel value so the
        # publish logic below sends the command.
        if _switch["last_up"] is not None and lever_up != _switch["last_up"]:
            scene.twin_led_on = lever_up
        _switch["last_up"] = lever_up

        # Snap the lever to the actual Pi state when it changes.
        if state["led"] != _switch["last_state"]:
            lever.rotation_euler.x = math.radians(30) if state["led"] else math.radians(-30)
            scene.twin_led_on = state["led"]
            _switch["last_up"] = state["led"]
            _switch["last_state"] = state["led"]

    # Temperature text readout.
    txt = bpy.data.objects.get("TempText")
    if txt:
        txt.data.body = f"{state['temperature']:.1f} C"

    # Heat bar color (blue -> red).
    _set_material_color("Heatbar", _heat_color(state["temperature"]))

    # Publish control commands only when the panel values change.
    if _client:
        led = bool(scene.twin_led_on)
        thr = float(scene.twin_threshold)
        if led != _pub["led"]:
            _client.publish("machine/command/mode", "manual")
            _client.publish("machine/command/led", "1" if led else "0")
            _pub["led"] = led
        if _pub["threshold"] is None or abs(thr - _pub["threshold"]) > 0.05:
            _client.publish("machine/command/threshold", f"{thr:.1f}")
            _pub["threshold"] = thr

    return 0.5


class TWIN_OT_toggle_led(bpy.types.Operator):
    bl_idname = "twin.toggle_led"
    bl_label = "Toggle LED"
    bl_description = "Toggle the Raspberry Pi LED"

    def execute(self, context):
        context.scene.twin_led_on = not context.scene.twin_led_on
        return {'FINISHED'}


class TWIN_PT_control(bpy.types.Panel):
    bl_label = "Pi Twin"
    bl_idname = "VIEW3D_PT_twin_control"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Twin"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Status", icon="INFO")
        row = box.row()
        row.label(text="Temperature")
        row.label(text=f"{state['temperature']:.1f} °C")
        row = box.row()
        row.label(text="LED")
        row.label(text="ON" if state["led"] else "OFF")
        row = box.row()
        row.label(text="Threshold")
        row.label(text=f"{state['threshold']:.1f} °C")

        box = layout.box()
        box.label(text="Control", icon="TOOL_SETTINGS")
        row = box.row()
        row.operator("twin.toggle_led", text="Force LED ON" if not scene.twin_led_on else "Turn LED OFF", icon="LIGHT")
        box.prop(scene, "twin_threshold", text="Threshold (°C)")

        layout.separator()
        layout.label(text="Changes are sent to the Pi", icon="INFO")


def register():
    if not hasattr(bpy.types.Scene, "twin_led_on"):
        bpy.types.Scene.twin_led_on = bpy.props.BoolProperty(
            name="LED on", description="Turn the Pi LED on/off", default=False
        )
    if not hasattr(bpy.types.Scene, "twin_threshold"):
        bpy.types.Scene.twin_threshold = bpy.props.FloatProperty(
            name="Threshold (C)", default=60.0, min=20.0, max=100.0
        )
    try:
        bpy.utils.register_class(TWIN_OT_toggle_led)
        bpy.utils.register_class(TWIN_PT_control)
    except ValueError:
        pass  # already registered from a previous run


def main():
    global _client
    try:
        _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        _client = mqtt.Client()

    _client.on_message = on_message
    _client.connect(BROKER, PORT, 60)
    _client.subscribe("machine/#")
    _client.loop_start()

    register()
    ensure_objects()
    bpy.app.timers.register(apply_twin, first_interval=0.5)
    print("Blender twin running (bidirectional). Open the 'Twin' sidebar panel.")


main()
