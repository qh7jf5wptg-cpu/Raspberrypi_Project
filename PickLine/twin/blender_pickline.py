"""Live Blender twin for the PickLine (gantry + conveyor + two fill stations).

Maps the plant's top-view world (mm) onto the Blender ground plane (m):
    world (x, y, z)  ->  Blender (x/100, y/100, z/100)
"""
import os
import sys
import math
import time
import json

import bpy
from mathutils import Vector
import paho.mqtt.client as mqtt

_project_root = os.path.dirname(bpy.path.abspath("//").rstrip("/"))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from robot.kinematics import SixAxisRobot

BROKER = os.environ.get("MQTT_BROKER", "localhost")
PORT = 1883

ROBOT_MODEL = SixAxisRobot()
ROBOT_BASES = {"a": (4.6, 1.35, 0.0), "b": (4.3, 2.05, 0.0)}

state = {"x": 0.0, "y": 0.0, "z": 60.0,
         "grip_a": 1.0, "grip_b": 1.0,
         "holding_a": 0, "holding_b": 0,
         "part_a/x": -1.0, "part_a/y": -1.0, "part_b/x": -1.0, "part_b/y": -1.0,
         "belt": 0.0, "speed": 90.0,
         "diverter": 0.0, "sensor_in": 0, "sensor_out": 0, "sensor_divert": 0,
         "placed": 0, "exited": 0, "state": "IDLE", "side": "down",
         "decision": "STRAIGHT", "gap": 0.5, "volume": 100.0,
         "paused": 0, "estop": 0,
         "fill/a/level": 0.0, "fill/a/state": "EMPTY", "fill/a/count": 0,
         "fill/a/filled": 0, "fill/a/pickups": 2, "fill/a/pouring": 0,
         "fill/b/level": 0.0, "fill/b/state": "EMPTY", "fill/b/count": 0,
         "fill/b/filled": 0, "fill/b/pickups": 5, "fill/b/pouring": 0,
         "fill/total": 0.0,
         "outfeed/a/positions": "", "outfeed/b/positions": "",
         "outfeed/a/queued": 0, "outfeed/b/queued": 0,
         "lift/a/state": "IDLE", "lift/b/state": "IDLE",
         "lift/a/z": 0.0, "lift/b/z": 0.0,
         "lift/a/stack": 0, "lift/b/stack": 0,
         "lift/a/pallets": 0, "lift/b/pallets": 0,
         "reject/items": "[]", "reject/total": 0,
         "reject_rate": 0.12,
         "pallet/last": "",
         "robot/a/holding": 0, "robot/b/holding": 0,
         "robot/a/gripper": 1.0, "robot/b/gripper": 1.0,
         "scanned": ""}


def _num(payload, default=0.0):
    try:
        return float(payload)
    except ValueError:
        return default


def on_message(_client, _userdata, msg):
    key = msg.topic.split("/", 1)[-1] if msg.topic.startswith("pickline/") else msg.topic
    payload = msg.payload.decode("utf-8", "replace").strip()
    if key in ("x", "y", "z", "grip_a", "grip_b", "belt", "speed", "diverter",
               "part_a/x", "part_a/y", "part_b/x", "part_b/y",
               "gap", "volume", "reject_rate", "fill/a/level", "fill/b/level",
               "fill/total"):
        state[key] = _num(payload, state[key])
    elif key in ("holding_a", "holding_b", "sensor_in", "sensor_out", "sensor_divert",
                 "placed", "exited", "fill/a/count", "fill/b/count",
                 "fill/a/filled", "fill/a/pickups", "fill/a/pouring",
                 "fill/b/filled", "fill/b/pickups", "fill/b/pouring",
                 "paused", "estop"):
        state[key] = int(_num(payload))
    elif key in ("state", "side", "decision", "fill/a/state", "fill/b/state",
                 "scanned"):
        state[key] = payload

    if key.startswith("robot/"):
        if "/joint/" in key or "/tcp/" in key:
            state[key] = _num(payload)
        elif key.endswith("/holding") or key.endswith("/gripper"):
            state[key] = _num(payload)
    elif key.startswith("outfeed/"):
        if key.endswith("/positions"):
            state[key] = payload
        else:
            state[key] = int(_num(payload))
    elif key.startswith("lift/"):
        if key.endswith("/state"):
            state[key] = payload
        else:
            state[key] = _num(payload)
    elif key.startswith("reject/"):
        if key == "reject/items":
            state[key] = payload
        else:
            state[key] = int(_num(payload))
    elif key == "pallet/last":
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


def _set_light(name, on, color, strength=10.0):
    obj = _obj(name)
    if obj is None:
        return
    grey = (0.40, 0.43, 0.47, 1.0)
    obj.color = (*color, 1.0) if on else grey
    if not obj.data.materials:
        return
    mat = obj.data.materials[0]
    mat.diffuse_color = (*color, 1.0) if on else grey
    if not mat.use_nodes:
        return
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            if on:
                node.inputs["Base Color"].default_value = (
                    color[0] * 0.12, color[1] * 0.12, color[2] * 0.12, 1.0)
                node.inputs["Emission Color"].default_value = (*color, 1.0)
                node.inputs["Emission Strength"].default_value = strength
            else:
                node.inputs["Base Color"].default_value = grey
                node.inputs["Emission Strength"].default_value = 0.0
            break


_CUBE_VERTS = [
    (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
    (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
]
_CUBE_FACES = [
    (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]


def _make_material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def _make_box(name, loc, dims, color):
    ob = _obj(name)
    if ob is not None:
        return ob
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(_CUBE_VERTS, [], _CUBE_FACES)
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    ob.scale = dims
    ob.data.materials.append(_make_material(name + "_mat", color))
    return ob


_line_objects_ready = False
_part_objects_ready = False


def _ensure_part_objects():
    global _part_objects_ready
    if _part_objects_ready:
        return
    _part_objects_ready = True
    try:
        _make_box("Part", (100.0, 100.0, 100.0), (0.04, 0.04, 0.04),
                  (0.98, 0.76, 0.10))
        _make_box("PartB", (100.0, 100.0, 100.0), (0.04, 0.04, 0.04),
                  (0.10, 0.75, 0.35))
    except Exception:
        pass


def _ensure_line_objects():
    global _line_objects_ready
    if _line_objects_ready:
        return
    _line_objects_ready = True
    try:
        _make_box("OutfeedBeltB", (5.2, 2.45, 0.04), (2.0, 0.10, 0.02),
                  (0.60, 0.65, 0.70))
        _make_box("LiftA", (6.2, 1.7, 0.08), (0.18, 0.18, 0.06),
                  (0.90, 0.50, 0.20))
        _make_box("LiftB", (6.2, 2.45, 0.08), (0.18, 0.18, 0.06),
                  (0.90, 0.50, 0.20))
        for i in range(4):
            _make_box("LiftStackA%d" % i, (100.0, 100.0, 100.0),
                      (0.12, 0.12, 0.05), (0.98, 0.76, 0.10))
        for i in range(2):
            _make_box("LiftStackB%d" % i, (100.0, 100.0, 100.0),
                      (0.12, 0.12, 0.05), (0.10, 0.75, 0.35))
        _make_box("RejectBin", (5.5, 2.075, 0.02), (0.32, 0.32, 0.04),
                  (0.78, 0.22, 0.18))
        for i in range(6):
            _make_box("RejectBox%d" % i, (100.0, 100.0, 100.0),
                      (0.08, 0.08, 0.08), (0.90, 0.25, 0.20))
        for i in range(10):
            _make_box("RejectPile%d" % i, (100.0, 100.0, 100.0),
                      (0.07, 0.07, 0.05), (0.90, 0.25, 0.20))
    except Exception:
        pass


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
    reject_rate: bpy.props.IntProperty(
        name="Reject rate (%)", default=12, min=0, max=100,
        update=lambda self, ctx: None if _syncing else _publish(
            "pickline/target/reject_rate", "%.2f" % (self.reject_rate / 100.0)))


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
        box.label(text="Quality")
        box.label(text="Rejects: %s%s" % (
            state.get("reject/total", 0),
            " (FULL)" if int(state.get("reject/full", 0)) else ""))
        op = box.operator("pickline.publish", text="Clear rejects")
        op.topic = "pickline/reject/clear"
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
        box.prop(settings, "reject_rate")


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
        reject = int(round(float(state.get("reject_rate", 0.12)) * 100))
        if abs(settings.gap - gap) > 0.05:
            settings.gap = gap
        if settings.speed != speed:
            settings.speed = speed
        if settings.reject_rate != reject:
            settings.reject_rate = reject
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
    else:
        color = (0.10, 0.75, 0.35, 1.0) if key == "b" else (0.98, 0.76, 0.10, 1.0)
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


def _set_link(name, p1, p2, radius):
    obj = _obj(name)
    if obj is None:
        return
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0, (p1[2] + p2[2]) / 2.0)
    direction = Vector((p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]))
    length = max(direction.length, 0.001)
    obj.location = mid
    obj.scale = (radius, radius, length)
    obj.rotation_euler = Vector((0.0, 0.0, 1.0)).rotation_difference(
        direction.normalized()
    ).to_euler()


def _set_box_link(name, p1, p2, width, depth):
    obj = _obj(name)
    if obj is None:
        return
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0, (p1[2] + p2[2]) / 2.0)
    direction = Vector((p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]))
    length = max(direction.length, 0.001)
    obj.location = mid
    obj.scale = (width, depth, length)
    obj.rotation_euler = Vector((0.0, 0.0, 1.0)).rotation_difference(
        direction.normalized()
    ).to_euler()


def _set_oriented_box(name, loc, size, direction):
    obj = _obj(name)
    if obj is None:
        return
    obj.location = loc
    obj.scale = size
    direction = Vector(direction)
    obj.rotation_euler = Vector((0.0, 0.0, 1.0)).rotation_difference(
        direction.normalized()
    ).to_euler()


def _place(name, pos):
    obj = _obj(name)
    if obj is not None:
        obj.location = pos


def _robot_joints(key):
    return [math.radians(state.get("robot/%s/joint/%d" % (key, i), 0.0))
            for i in range(1, 7)]


def _update_robots():
    for key, base in ROBOT_BASES.items():
        points = ROBOT_MODEL.joint_positions(_robot_joints(key))
        p = [(base[0] + x / 100.0, base[1] + y / 100.0, base[2] + z / 100.0)
             for x, y, z in points]
        p0, p1, p2, p3, p4 = p
        prefix = "Robot" + key.upper()
        _set_link(prefix + "_Column", p0, p1, 0.05)
        arm_dir = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
        _set_oriented_box(prefix + "_Shoulder", p1, (0.13, 0.13, 0.13), arm_dir)
        _set_box_link(prefix + "_UpperArm", p1, p2, 0.09, 0.07)
        _set_box_link(prefix + "_Forearm", p2, p3, 0.07, 0.06)
        _place(prefix + "_Elbow", p2)
        _place(prefix + "_Wrist", p3)
        _place(prefix + "_Flange", p4)
        # Gripper fingers open/close with the robot gripper state.
        grip = state.get("robot/%s/gripper" % key, 1.0)
        gap = 0.012 + 0.025 * grip
        _place(prefix + "_GripperA", (p4[0], p4[1] + gap, p4[2] - 0.045))
        _place(prefix + "_GripperB", (p4[0], p4[1] - gap, p4[2] - 0.045))


def _update_outfeed():
    _ensure_line_objects()

    # Line A uses OutfeedBox0..2 at y = 1.7 (yellow), line B uses OutfeedBox3..5
    # at y = 2.45 (green).
    lines = {
        "a": {"y": 1.7, "color": (0.98, 0.76, 0.10, 1.0), "first": 0},
        "b": {"y": 2.45, "color": (0.10, 0.75, 0.35, 1.0), "first": 3},
    }
    for key, cfg in lines.items():
        positions = state.get("outfeed/%s/positions" % key, "")
        xs = [float(v) for v in positions.split(",") if v.strip()] if positions else []
        for i in range(3):
            box = _obj("OutfeedBox%d" % (cfg["first"] + i))
            if box is None:
                continue
            if i < len(xs):
                box.location = (xs[i] / 100.0, cfg["y"], 0.06)
                _set_color(box, cfg["color"])
            else:
                box.location = (100.0, 100.0, 100.0)

    # Lift platforms collect stacked containers at the bottom and rise with the
    # plant lift z once the pallet is full.
    for key, y, max_stack in (("a", 1.7, 4), ("b", 2.45, 2)):
        lift_z = state.get("lift/%s/z" % key, 0.0) / 100.0
        stack = max(0, int(state.get("lift/%s/stack" % key, 0)))
        lift = _obj("Lift%s" % key.upper())
        if lift:
            lift.location = (6.2, y, 0.06 + lift_z)
        for i in range(max_stack):
            box = _obj("LiftStack%s%d" % (key.upper(), i))
            if box is None:
                continue
            if i < stack:
                box.location = (6.2, y, 0.13 + lift_z + i * 0.05)
            else:
                box.location = (100.0, 100.0, 100.0)


def _update_rejects():
    _ensure_line_objects()
    raw = state.get("reject/items", "[]")
    try:
        items = json.loads(raw) if raw else []
    except Exception:
        items = []
    for i in range(6):
        box = _obj("RejectBox%d" % i)
        if box is None:
            continue
        if i < len(items):
            it = items[i]
            box.location = (
                float(it["x"]) / 100.0, float(it["y"]) / 100.0, 0.06,
            )
        else:
            box.location = (100.0, 100.0, 100.0)

    # Pile the rejected containers inside the bin.
    total = min(10, max(0, int(state.get("reject/total", 0))))
    for i in range(10):
        pile = _obj("RejectPile%d" % i)
        if pile is None:
            continue
        if i < total:
            row = i // 5
            col = i % 5
            pile.location = (
                5.5 + (col - 2) * 0.055,
                2.075,
                0.06 + row * 0.05,
            )
        else:
            pile.location = (100.0, 100.0, 100.0)


def apply_twin():
    _ensure_part_objects()
    tool = _obj("ToolHead")
    tool_b = _obj("ToolHeadB")
    jaw_a = _obj("JawA")
    jaw_b = _obj("JawB")
    jaw_c = _obj("JawC")
    jaw_d = _obj("JawD")

    x, y, z = state["x"] * 0.01, state["y"] * 0.01, state["z"] * 0.01

    if tool:
        tool.location = (x, y, z)
    if tool_b:
        tool_b.location = (x, y + 1.7, z)

    carriage = _obj("Carriage")
    if carriage:
        carriage.location = (x, y, 1.08)

    gap_a = 0.05 + 0.05 * state["grip_a"]
    gap_b = 0.05 + 0.05 * state["grip_b"]
    if jaw_a:
        jaw_a.location = (x, y + gap_a, z - 0.16)
    if jaw_b:
        jaw_b.location = (x, y - gap_a, z - 0.16)
    if jaw_c:
        jaw_c.location = (x, y + 1.7 + gap_b, z - 0.16)
    if jaw_d:
        jaw_d.location = (x, y + 1.7 - gap_b, z - 0.16)

    part = _obj("Part")
    part_b = _obj("PartB")
    if part:
        _set_color(part, (0.98, 0.76, 0.10, 1.0))
        if state["holding_a"]:
            part.location = (x, y, z - 0.10)
        elif state["part_a/x"] >= 0:
            part.location = (state["part_a/x"] * 0.01, state["part_a/y"] * 0.01, 0.06)
        else:
            part.location = (100.0, 100.0, 100.0)
    if part_b:
        _set_color(part_b, (0.10, 0.75, 0.35, 1.0))
        if state["holding_b"]:
            part_b.location = (x, y + 1.7, z - 0.10)
        elif state["part_b/x"] >= 0:
            part_b.location = (state["part_b/x"] * 0.01, state["part_b/y"] * 0.01, 0.06)
        else:
            part_b.location = (100.0, 100.0, 100.0)

    gate = _obj("Gate")
    if gate:
        gate.rotation_euler = (0.0, 0.0, -1.1 * state["diverter"])
        _set_color(gate, (0.20, 0.85, 0.35, 1.0) if state["diverter"] > 0.5 else (0.85, 0.30, 0.22, 1.0))

    for name in ("RollerL", "RollerR"):
        roller = _obj(name)
        if roller and state["belt"] > 0.5:
            roller.rotation_euler[0] += 0.02 * state["speed"] / 90.0

    for name in ("OutfeedRollerL", "OutfeedRollerR"):
        roller = _obj(name)
        if roller:
            roller.rotation_euler[0] += 0.02  # outfeed runs continuously

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
    active_states = {"TO_PICK", "LOWER_PICK", "GRIP", "LIFT_PICK",
                     "TO_DROP_A", "WAIT_INFEED", "LOWER_A", "RELEASE_A", "LIFT_A",
                     "TO_DROP_B", "WAIT_GAP", "LOWER_B", "RELEASE_B", "LIFT_B",
                     "WAIT_ROUND"}
    running = (state.get("mode", "auto") == "auto"
               and state.get("state", "IDLE") in active_states
               and not state.get("paused", 0) and not state.get("estop", 0))
    blink = int(time.time() * 2) % 2 == 0
    red_on = (state.get("estop", 0) or state.get("state", "") == "FAULT") and blink
    yellow_on = state.get("paused", 0) and blink
    green_on = running and blink
    any_full = (state.get("fill/a/state", "") == "FULL"
                or state.get("fill/b/state", "") == "FULL")
    reject_full = int(state.get("reject/full", 0)) > 0
    blue_on = (any_full or reject_full) and blink
    _set_light("TowerRed", red_on, (1.0, 0.02, 0.02))
    _set_light("TowerYellow", yellow_on, (1.0, 0.85, 0.05))
    _set_light("TowerGreen", green_on, (0.05, 1.0, 0.1))
    _set_light("TowerBlue", blue_on, (0.05, 0.25, 1.0))
    _update_robots()
    _update_outfeed()
    _update_rejects()
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
