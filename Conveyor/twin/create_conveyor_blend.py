"""Create the Blender scene for the conveyor digital twin."""
import bpy
from mathutils import Vector

OUT = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/Conveyor/twin/Conveyor_Twin.blend"

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def material(name, color, metallic=0.0, roughness=0.6, emission=0.0):
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


belt_mat = material("Belt", (0.35, 0.42, 0.50), roughness=0.7)
lane_mat = material("Lane", (0.25, 0.32, 0.40), roughness=0.7)
gate_mat = material("Gate", (0.90, 0.30, 0.20), roughness=0.4)
sensor_mat = material("Sensor", (0.20, 0.25, 0.30), roughness=0.5)
part_mat = material("Part", (0.95, 0.75, 0.15), roughness=0.5)
frame_mat = material("Frame", (0.16, 0.18, 0.20), metallic=0.5, roughness=0.4)
text_mat = material("StatusTextMat", (0.1, 0.9, 0.4), emission=2.0)

box("Frame", (2.0, 0.35, -0.04), (2.2, 1.2, 0.08), frame_mat)
box("Belt", (2.0, 0.0, 0.03), (2.1, 0.30, 0.03), belt_mat)
box("DivertLane", (2.5, 0.75, 0.03), (0.30, 1.5, 0.03), lane_mat)
box("Gate", (2.5, 0.03, 0.10), (0.05, 0.08, 0.12), gate_mat)
box("Sensor1", (1.2, 0.22, 0.10), (0.04, 0.04, 0.10), sensor_mat)
box("Sensor2", (3.4, 0.22, 0.10), (0.04, 0.04, 0.10), sensor_mat)
part = box("Part", (0.0, 0.0, 0.12), (0.08, 0.08, 0.08), part_mat)
part.hide_viewport = True
part.hide_render = True

text = bpy.data.curves.new("StatusText", type="FONT")
text.body = "IDLE   STRAIGHT   passed 0   diverted 0"
text.align_x = "CENTER"
text_obj = bpy.data.objects.new("StatusText", text)
text_obj.location = (2.0, 0.7, 0.6)
text_obj.scale = (0.12, 0.12, 0.12)
text_obj.data.materials.append(text_mat)
bpy.context.collection.objects.link(text_obj)

cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (4.4, -3.6, 3.4)
bpy.context.collection.objects.link(cam)
look = Vector((2.0, 0.2, 0.3)) - cam.location
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

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("Saved:", OUT)
