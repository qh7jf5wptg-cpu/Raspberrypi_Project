#!/usr/bin/env python3
"""Blender digital-twin driver (bidirectional).

Shows the Pi's live state (temperature text, heat bar, spinning rotor, LED
color) and lets you control the Pi from a Blender sidebar panel (LED toggle +
threshold slider).

Run from Blender's Scripting workspace (Run Script).
"""

import bpy
import math
import time
import json
import datetime
import ssl
import urllib.request
import paho.mqtt.client as mqtt
from mathutils import Vector

BROKER = "localhost"
PORT = 1883

state = {"temperature": 0.0, "led": False, "threshold": 60.0}

_client = None
_pub = {"led": None, "threshold": None}
_switch = {"last_up": None, "last_state": None}
forecast = []


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
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                node.inputs["Base Color"].default_value = color
                break
        mat.diffuse_color = color
    obj = bpy.data.objects.get(name)
    if obj:
        obj.color = color


def _set_led_material(on):
    # LED: green when on, original dark gray when off.
    mat = bpy.data.materials.get("LED")
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                if on:
                    node.inputs["Base Color"].default_value = (0.2, 0.9, 0.3, 1.0)
                    node.inputs["Emission Color"].default_value = (0.1, 0.8, 0.2, 1.0)
                    node.inputs["Emission Strength"].default_value = 4.0
                else:
                    node.inputs["Base Color"].default_value = (0.05, 0.05, 0.05, 1.0)
                    node.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)
                    node.inputs["Emission Strength"].default_value = 0.0
                break
        mat.diffuse_color = (0.2, 0.9, 0.3, 1.0) if on else (0.05, 0.05, 0.05, 1.0)

    # Viewport display color (also shown in Solid view)
    obj = bpy.data.objects.get("LED")
    if obj:
        obj.color = (0.2, 0.9, 0.3, 1.0) if on else (0.12, 0.12, 0.12, 1.0)


def _heat_color(t):
    # Map 30..80 C to blue -> red.
    x = max(0.0, min(1.0, (t - 30.0) / 50.0))
    return (x, 0.25 * (1.0 - x) + 0.05, 1.0 - x, 1.0)


def _weather_kind(code):
    if code == 0:
        return "sun"
    if code <= 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67:
        return "rain"
    if 71 <= code <= 77:
        return "snow"
    if 80 <= code <= 82:
        return "rain"
    if code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunder"
    return "cloud"


def _weather_color(kind):
    return {
        "sun": (0.95, 0.61, 0.07, 1.0),
        "cloud": (0.50, 0.55, 0.58, 1.0),
        "fog": (0.62, 0.66, 0.69, 1.0),
        "rain": (0.20, 0.60, 0.85, 1.0),
        "snow": (0.00, 0.74, 0.83, 1.0),
        "thunder": (0.95, 0.77, 0.06, 1.0),
    }.get(kind, (1.0, 1.0, 1.0, 1.0))


def fetch_forecast():
    url = ("https://api.open-meteo.com/v1/forecast?latitude=60.1699&longitude=24.9384"
           "&daily=temperature_2m_max,temperature_2m_min,weather_code"
           "&timezone=Europe/Helsinki&forecast_days=7")
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, timeout=10, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8"))
        daily = data.get("daily", {})
        times = daily.get("time", [])
        codes = daily.get("weather_code", [])
        his = daily.get("temperature_2m_max", [])
        los = daily.get("temperature_2m_min", [])
        out = []
        for i in range(min(len(times), 7)):
            try:
                dow = datetime.date.fromisoformat(times[i]).strftime("%a")
            except Exception:
                dow = times[i][5:]
            out.append({
                "day": times[i][5:],
                "dow": dow,
                "code": codes[i] if i < len(codes) else 0,
                "hi": round(his[i]) if i < len(his) else 0,
                "lo": round(los[i]) if i < len(los) else 0,
            })
        return out
    except Exception as e:
        print("forecast fetch failed:", repr(e))
        return []


def _forecast_items(self, context):
    if not forecast:
        return [("0", "Loading forecast...", "", 0)]
    return [(str(i), f"{f['dow']} {f['day']}", f"{f['hi']} / {f['lo']} C", i) for i, f in enumerate(forecast)]


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
        heat.scale = (0.13, 0.13, 0.4)
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

    # --- Weather preview objects ---
    if "WeatherSun" not in bpy.data.objects:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.22, location=(0.0, 0.0, 1.7))
        sun = bpy.context.object
        sun.name = "WeatherSun"
        mat = bpy.data.materials.new("WeatherSunMat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (1.0, 0.8, 0.1, 1.0)
            bsdf.inputs["Emission Color"].default_value = (1.0, 0.7, 0.0, 1.0)
            bsdf.inputs["Emission Strength"].default_value = 4.0
        sun.data.materials.append(mat)

    if "WeatherCloud" not in bpy.data.objects:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(0.0, 0.0, 1.7))
        cloud = bpy.context.object
        cloud.name = "WeatherCloud"
        cloud.scale = (1.0, 0.55, 0.42)
        mat = bpy.data.materials.new("WeatherCloudMat")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.82, 0.84, 0.87, 1.0)
        cloud.data.materials.append(mat)

    if not any(o.name.startswith("WeatherDrop") for o in bpy.data.objects):
        mat = bpy.data.materials.new("WeatherDropMat")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.4, 0.6, 1.0, 1.0)
        for i in range(6):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, location=(0.0, 0.0, 1.5))
            d = bpy.context.object
            d.name = f"WeatherDrop{i}"
            d.data.materials.append(mat)

    if "WeatherBolt" not in bpy.data.objects:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0.0, 0.0, 1.25))
        bolt = bpy.context.object
        bolt.name = "WeatherBolt"
        bolt.scale = (0.04, 0.04, 0.45)
        mat = bpy.data.materials.new("WeatherBoltMat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (1.0, 0.9, 0.2, 1.0)
            bsdf.inputs["Emission Color"].default_value = (1.0, 0.9, 0.2, 1.0)
            bsdf.inputs["Emission Strength"].default_value = 0.0
        bolt.data.materials.append(mat)

    if "WeatherTemp" not in bpy.data.objects:
        curve = bpy.data.curves.new("WeatherTemp", type="FONT")
        curve.body = "--"
        curve.align_x = "CENTER"
        obj = bpy.data.objects.new("WeatherTemp", curve)
        obj.location = (0.0, -1.1, 1.6)
        obj.scale = (0.32, 0.32, 0.32)
        mat = bpy.data.materials.new("WeatherTempMat")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        obj.data.materials.append(mat)
        bpy.context.collection.objects.link(obj)


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
        txt.data.body = f"{state['temperature']:.1f} °C"

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

    # Weather preview animation for the selected forecast day.
    idx = int(scene.twin_day)
    sel = forecast[idx] if 0 <= idx < len(forecast) else None
    kind = _weather_kind(sel["code"]) if sel else "sun"
    anim = time.time()

    sun = bpy.data.objects.get("WeatherSun")
    cloud = bpy.data.objects.get("WeatherCloud")
    bolt = bpy.data.objects.get("WeatherBolt")
    drops = [o for o in bpy.data.objects if o.name.startswith("WeatherDrop")]
    ttxt = bpy.data.objects.get("WeatherTemp")

    for o in (sun, cloud, bolt):
        if o:
            o.hide_viewport = True
            o.hide_render = True
    for d in drops:
        d.hide_viewport = True
        d.hide_render = True

    if kind == "sun" and sun:
        sun.hide_viewport = False
        sun.hide_render = False
        sun.rotation_euler.z += 0.03
        sc = 1.0 + 0.08 * math.sin(anim * 3)
        sun.scale = (sc, sc, sc)
    elif kind in ("cloud", "fog") and cloud:
        cloud.hide_viewport = False
        cloud.hide_render = False
        cloud.location.z = 1.7 + 0.05 * math.sin(anim * 2)
    elif kind in ("rain", "snow"):
        if cloud:
            cloud.hide_viewport = False
            cloud.hide_render = False
            cloud.location.z = 1.7 + 0.05 * math.sin(anim * 2)
        speed = 0.9 if kind == "rain" else 0.45
        for i, d in enumerate(drops):
            d.hide_viewport = False
            d.hide_render = False
            d.location.x = -0.22 + i * 0.09
            d.location.z = 1.5 - ((anim * speed + i * 0.22) % 0.9)
    elif kind == "thunder":
        if cloud:
            cloud.hide_viewport = False
            cloud.hide_render = False
            cloud.location.z = 1.7 + 0.05 * math.sin(anim * 2)
        if bolt:
            bolt.hide_viewport = False
            bolt.hide_render = False
            if bolt.data.materials and bolt.data.materials[0].use_nodes:
                for node in bolt.data.materials[0].node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        node.inputs["Emission Strength"].default_value = 5.0 if (int(anim * 3) % 2 == 0) else 0.0
                        break

    if ttxt:
        if sel:
            ttxt.data.body = f"{sel['dow']} {sel['day']}  {sel['hi']}°C / {sel['lo']}°C"
            color = _weather_color(kind)
        else:
            ttxt.data.body = "--"
            color = (1.0, 1.0, 1.0, 1.0)
        ttxt.color = color
        if ttxt.data and ttxt.data.materials:
            mat = ttxt.data.materials[0]
            mat.diffuse_color = color
            if mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        node.inputs["Base Color"].default_value = color
                        node.inputs["Emission Color"].default_value = color
                        node.inputs["Emission Strength"].default_value = 1.0
                        break

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

        box = layout.box()
        box.label(text="Weather preview", icon="OUTLINER_OB_LIGHT")
        box.prop(scene, "twin_day", text="Day")
        _i = int(scene.twin_day)
        if 0 <= _i < len(forecast):
            _wf = forecast[_i]
            box.label(text=f"{_wf['dow']} {_wf['day']}: {_wf['hi']}/{_wf['lo']} C  (code {_wf['code']})")

        layout.separator()
        layout.label(text="Changes are sent to the Pi", icon="INFO")


def register():
    if not hasattr(bpy.types.Scene, "twin_led_on"):
        bpy.types.Scene.twin_led_on = bpy.props.BoolProperty(
            name="LED on", description="Turn the Pi LED on/off", default=False
        )
    if not hasattr(bpy.types.Scene, "twin_day"):
        bpy.types.Scene.twin_day = bpy.props.EnumProperty(
            name="Weather day",
            description="Select a day to preview its weather",
            items=_forecast_items,
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
    global _client, forecast
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
    forecast = fetch_forecast()
    print("forecast days:", len(forecast))

    # Frame the whole scene (machine + weather + side objects).
    cam = bpy.context.scene.camera
    if cam:
        cam.location = (7.5, -6.5, 4.5)
        look = Vector((0.0, 0.0, 0.8)) - cam.location
        cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    bpy.app.timers.register(apply_twin, first_interval=0.5)
    print("Blender twin running (bidirectional). Open the 'Twin' sidebar panel.")


main()
