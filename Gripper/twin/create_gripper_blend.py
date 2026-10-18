"""Create the Blender scene for the Gripper digital twin.

Builds a Cartesian pick-and-place gantry (X/Y/Z + two-finger gripper), two
work stations and three part objects, then saves Gripper_Twin.blend.

Run:
    blender --background --python create_gripper_blend.py
"""
import bpy
from mathutils import Vector

OUT = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/Gripper/twin/Gripper_Twin.blend"

# Scene units: 1 Blender unit = 100 mm.
PICK = (0.2, 0.2)      # 20 mm, 20 mm
PLACE = (2.8, 1.8)     # 280 mm, 180 mm

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def material(name, color, metallic=0.0, roughness=0.5, emission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission
    return m


def box(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


def label(name, text, loc, scale, mat):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = text
    curve.align_x = "CENTER"
    obj = bpy.data.objects.new(name, curve)
    obj.location = loc
    obj.scale = scale
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj


frame_mat = material("Frame", (0.20, 0.22, 0.25), metallic=0.6, roughness=0.35)
rail_mat = material("Rail", (0.55, 0.58, 0.62), metallic=0.9, roughness=0.2)
tool_mat = material("Tool", (0.85, 0.55, 0.10), metallic=0.3, roughness=0.4)
part_mat = material("Part", (0.95, 0.75, 0.15), metallic=0.0, roughness=0.5)
pad_mat = material("Pad", (0.15, 0.35, 0.55), roughness=0.7)
text_mat = material("StatusTextMat", (0.1, 0.9, 0.4), emission=2.0)

# Base and frame.
box("Base", (1.5, 1.0, -0.06), (3.7, 2.5, 0.12), frame_mat)
box("RailY1", (-0.15, 1.0, 2.25), (0.10, 2.5, 0.10), rail_mat)
box("RailY2", (3.15, 1.0, 2.25), (0.10, 2.5, 0.10), rail_mat)
box("ColumnL", (-0.15, -0.1, 1.1), (0.10, 0.10, 2.3), frame_mat)
box("ColumnR", (-0.15, 2.1, 1.1), (0.10, 0.10, 2.3), frame_mat)

# Moving parts (positions are driven by the twin script).
box("Beam", (1.5, 1.0, 2.25), (3.4, 0.12, 0.12), rail_mat)
box("Carriage", (0.0, 0.0, 2.25), (0.22, 0.22, 0.20), frame_mat)
box("ZRod", (0.0, 0.0, 1.6), (0.06, 0.06, 1.2), rail_mat)
box("Tool", (0.0, 0.0, 0.10), (0.18, 0.14, 0.10), tool_mat)
box("JawL", (-0.09, 0.0, 0.06), (0.035, 0.10, 0.14), tool_mat)
box("JawR", (0.09, 0.0, 0.06), (0.035, 0.10, 0.14), tool_mat)

# Work stations.
box("PickPad", (PICK[0], PICK[1], 0.01), (0.20, 0.20, 0.02), pad_mat)
box("PlacePad", (PLACE[0], PLACE[1], 0.01), (0.20, 0.20, 0.02), pad_mat)

# Parts: one waiting at the pick station, one held, one delivered.
box("PartPick", (PICK[0], PICK[1], 0.08), (0.09, 0.09, 0.09), part_mat)
held = box("PartHeld", (0.0, 0.0, 0.10), (0.09, 0.09, 0.09), part_mat)
held.hide_viewport = True
held.hide_render = True
delivered = box("PartPlaced", (PLACE[0], PLACE[1], 0.08), (0.09, 0.09, 0.09), part_mat)
delivered.hide_viewport = True
delivered.hide_render = True

# Status text above the machine.
label("StatusText", "IDLE   placed 0", (1.5, 2.3, 3.1), (0.22, 0.22, 0.22), text_mat)

# Camera and light.
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (4.6, -4.4, 4.2)
bpy.context.collection.objects.link(cam)
look = Vector((1.5, 1.0, 1.3)) - cam.location
cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
sun.data.energy = 4.0
sun.location = (4, -6, 8)
bpy.context.collection.objects.link(sun)

world = bpy.context.scene.world
if world and world.use_nodes:
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1.0)

for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        bpy.context.scene.render.engine = engine
        break
    except TypeError:
        continue
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("Saved:", OUT)
