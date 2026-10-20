"""Live Blender twin for the PickLine (gantry + conveyor + two fill stations).

Maps the plant's top-view world (mm) onto the Blender ground plane (m):
    world (x, y, z)  ->  Blender (x/100, y/100, z/100)
"""
import os
import time

import bpy
import paho.mqtt.client as mqtt

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883

state = {"x": 0.0, "y": 0.0, "z": 60.0, "grip": 1.0, "holding": 0,
         "part_x": -1.0, "part_y": -1.0, "belt": 0.0, "speed": 90.0,
         "diverter": 0.0, "sensor_in": 0, "sensor_out": 0, "sensor_divert": 0,
         "placed": 0, "exited": 0, "state": "IDLE", "side": "down",
         "decision": "STRAIGHT", "gap": 0.5, "volume": 100.0,
         "paused": 0, "estop": 0,
         "fill/a/level": 0.0, "fill/a/state": "EMPTY", "fill/a/count": 0,
         "fill/a/filled": 0, "fill/a/pickups": 2, "fill/a/pouring": 0,
         "fill/b/level": 0.0, "fill/b/state": "EMPTY", "fill/b/count": 0,
         "fill/b/filled": 0, "fill/b/pickups": 5, "fill/b/pouring": 0,
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
                 "placed", "exited", "fill/a/count", "fill/b/count",
                 "fill/a/filled", "fill/a/pickups", "fill/a/pouring",
                 "fill/b/filled", "fill/b/pickups", "fill/b/pouring",
                 "paused", "estop"):
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


def _set_light(name, on, color, strength=6.0):
    obj = _obj(name)
    if obj is None:
        return
    # Viewport display color (visible in Solid view) so the blink shows everywhere.
    if on:
        obj.color = (color[0], color[1], color[2], 1.0)
    else:
        obj.color = (0.07, 0.08, 0.10, 1.0)
    if not obj.data.materials:
        return
    mat = obj.data.materials[0]
    if on:
        mat.diffuse_color = (*color, 1.0)
    else:
        mat.diffuse_color = (0.07, 0.08, 0.10, 1.0)
    if not mat.use_nodes:
        return
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            if on:
                node.inputs["Base Color"].default_value = (*color, 1.0)
                node.inputs["Emission Color"].default_value = (*color, 1.0)
                node.inputs["Emission Strength"].default_value = strength
            else:
                node.inputs["Base Color"].default_value = (0.07, 0.08, 0.10, 1.0)
                node.inputs["Emission Strength"].default_value = 0.0
            break


def _redraw():
    try:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    except Exception:
        pass


_syncing = False


def _mqtt_client():
    return bpy.app.driver_namespace.get("pickline_client")


def _publish(topic, payload):
    client = _mqtt_client()
    if client:
        client.publish(topic, payload)


class PicklineSettings(bpy.types.PropertyGroup):
    gap: bpy.props.FloatProperty(
        name="Gap (s)", default=0.5, min=0.0, max=10.0,
        update=lambda self, ctx: None if _syncing else _publish(
            "pickline/command/gap", "%.1f" % self.gap))
    speed: bpy.props.IntProperty(
        name="Belt speed (mm/s)", default=90, min=20, max=250,
        update=lambda self, ctx: None if _syncing else _publish(
            "pickline/target/speed", str(self.speed)))


class PICKLINE_OT_publish(bpy.types.Operator):
    bl_idname = "pickline.publish"
    bl_label = "Publish MQTT"
    bl_options = {'REGISTER', 'UNDO'}
    topic: bpy.props.StringProperty()
    payload: bpy.props.StringProperty()

    def execute(self, context):
        _publish(self.topic, self.payload)
        return {'FINISHED'}


class PICKLINE_OT_start(bpy.types.Operator):
    bl_idname = "pickline.start"
    bl_label = "Start auto cycle"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _publish("pickline/command/mode", "auto")
        _publish("pickline/command/start", "1")
        return {'FINISHED'}


class PICKLINE_PT_control(bpy.types.Panel):
    bl_label = "PickLine Control"
    bl_idname = "PICKLINE_PT_control"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PickLine"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.pickline_settings

        box = layout.box()
        box.label(text="Status", icon="INFO")
        box.label(text="Machine: %s" % state.get("state", "IDLE"))
        box.label(text="A: %s %d/%d · done %d" % (
            state.get("fill/a/state", "EMPTY"), state.get("fill/a/filled", 0),
            state.get("fill/a/pickups", 2), state.get("fill/a/count", 0)))
        box.label(text="B: %s %d/%d · done %d" % (
            state.get("fill/b/state", "EMPTY"), state.get("fill/b/filled", 0),
            state.get("fill/b/pickups", 5), state.get("fill/b/count", 0)))

        box = layout.box()
        box.label(text="Filling")
        row = box.row(align=True)
        op = row.operator("pickline.publish", text="Take out A")
        op.topic = "pickline/fill/a/take"
        op.payload = "1"
        op = row.operator("pickline.publish", text="Take out B")
        op.topic = "pickline/fill/b/take"
        op.payload = "1"

        box = layout.box()
        box.label(text="Routing")
        row = box.row(align=True)
        op = row.operator("pickline.publish", text="Go straight")
        op.topic = "pickline/target/diverter"
        op.payload = "0"
        op = row.operator("pickline.publish", text="Go left")
        op.topic = "pickline/target/diverter"
        op.payload = "1"

        box = layout.box()
        box.label(text="Cycle")
        row = box.row(align=True)
        row.operator("pickline.start", text="Start")
        op = row.operator("pickline.publish", text="Stop")
        op.topic = "pickline/command/stop"
        op.payload = "1"
        op = row.operator("pickline.publish", text="Reset")
        op.topic = "pickline/command/reset"
        op.payload = "1"

        box = layout.box()
        box.label(text="Faults")
        row = box.row(align=True)
        op = row.operator("pickline.publish", text="Jam belt")
        op.topic = "pickline/fault/jam"
        op.payload = "1"
        op = row.operator("pickline.publish", text="Clear jam")
        op.topic = "pickline/fault/clear"
        op.payload = "1"

        box = layout.box()
        box.label(text="Safety")
        row = box.row(align=True)
        op = row.operator("pickline.publish", text="Pause")
        op.topic = "pickline/command/pause"
        op.payload = "1"
        op = row.operator("pickline.publish", text="Resume")
        op.topic = "pickline/command/resume"
        op.payload = "1"
        row = box.row(align=True)
        op = row.operator("pickline.publish", text="Emergency")
        op.topic = "pickline/command/estop"
        op.payload = "1"
        op = row.operator("pickline.publish", text="Clear belt")
        op.topic = "pickline/command/clear_belt"
        op.payload = "1"

        box = layout.box()
        box.label(text="Settings")
        box.prop(settings, "gap")
        box.prop(settings, "speed")


def register_panel():
    for cls in (PicklineSettings, PICKLINE_OT_publish, PICKLINE_OT_start, PICKLINE_PT_control):
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    if not hasattr(bpy.types.Scene, "pickline_settings"):
        bpy.types.Scene.pickline_settings = bpy.props.PointerProperty(type=PicklineSettings)


def sync_settings():
    global _syncing
    try:
        settings = bpy.context.scene.pickline_settings
    except Exception:
        return
    _syncing = True
    try:
        gap = float(state.get("gap", 0.5))
        speed = int(state.get("speed", 90))
        if abs(settings.gap - gap) > 0.05:
            settings.gap = gap
        if settings.speed != speed:
            settings.speed = speed
    finally:
        _syncing = False


def set_liquid(key, liquid_name, sx, sy):
    liquid = _obj(liquid_name)
    if liquid is None:
        return
    filled = max(0, state.get("fill/" + key + "/filled", 0))
    pickups = max(1, state.get("fill/" + key + "/pickups", 1))
    frac = min(1.0, filled / pickups)
    h = max(0.02, frac * 0.54)
    liquid.scale = (0.13, 0.13, h)
    liquid.location = (sx, sy, 0.02 + h / 2.0)
    st = state.get("fill/" + key + "/state", "")
    if st == "FAULT":
        color = (0.90, 0.20, 0.15, 1.0)
    elif st == "FULL":
        color = (0.90, 0.20, 0.15, 1.0)
    else:
        color = (0.10, 0.55, 0.90, 1.0)
    _set_color(liquid, color)


def set_stream(key, stream_name, nozzle_name, sx, sy):
    pouring = state.get("fill/" + key + "/pouring", 0)
    stream = _obj(stream_name)
    nozzle = _obj(nozzle_name)
    if stream:
        if pouring:
            stream.scale = (0.015, 0.015, 0.14)
            stream.location = (sx, sy, 0.67)
        else:
            stream.scale = (0.015, 0.015, 0.005)
    if nozzle:
        nozzle.location = (sx, sy, 0.79 if pouring else 0.84)


def apply_twin():
    tool = _obj("ToolHead")
    jaw_a = _obj("JawA")
    jaw_b = _obj("JawB")

    if tool:
        tool.location = (state["x"] * 0.01, state["y"] * 0.01, state["z"] * 0.01)

    carriage = _obj("Carriage")
    if carriage:
        carriage.location = (tool.location[0], tool.location[1], 1.08)

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

    set_liquid("a", "LiquidA", 4.6, 1.0)
    set_liquid("b", "LiquidB", 4.0, 2.4)
    set_stream("a", "StreamA", "NozzleA", 4.6, 1.0)
    set_stream("b", "StreamB", "NozzleB", 4.0, 2.4)

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

    # Industrial stack light: green blinks while running, yellow on pause, red on estop/fault.
    active_states = {"TO_PICK", "LOWER_PICK", "GRIP", "LIFT_PICK", "TO_DROP",
                     "LOWER_DROP", "RELEASE", "LIFT_DROP", "WAIT_EXIT", "WAIT_STATION"}
    running = (state.get("mode", "auto") == "auto"
               and state.get("state", "IDLE") in active_states
               and not state.get("paused", 0) and not state.get("estop", 0))
    blink = int(time.time() * 2) % 2 == 0
    red_on = state.get("estop", 0) or state.get("state", "") == "FAULT"
    yellow_on = state.get("paused", 0)
    green_on = running and blink
    both_full = (state.get("fill/a/state", "") == "FULL"
                 and state.get("fill/b/state", "") == "FULL")
    blue_on = both_full and blink
    _set_light("TowerRed", red_on, (1.0, 0.05, 0.05))
    _set_light("TowerYellow", yellow_on, (1.0, 0.9, 0.1))
    _set_light("TowerGreen", green_on, (0.05, 1.0, 0.1))
    _set_light("TowerBlue", blue_on, (0.1, 0.35, 1.0))
    _redraw()

    sync_settings()
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
    register_panel()
    bpy.app.driver_namespace["pickline_timer"] = apply_twin
    bpy.app.timers.register(apply_twin, first_interval=0.1)
    print("PickLine twin running (broker %s:%d)" % (BROKER, PORT))


main()
