"""Create the Blender scene for the filling station."""
import bpy
from mathutils import Vector

OUT = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/Filling/twin/Filling_Twin.blend"

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


def add_cylinder(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


def box(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


tank_mat = material("Tank", (0.75, 0.80, 0.88), roughness=0.3)
liquid_mat = material("Liquid", (0.10, 0.55, 0.90), roughness=0.2)
pump_mat = material("Pump", (0.55, 0.58, 0.62), metallic=0.6, roughness=0.3)
valve_mat = material("Valve", (0.85, 0.30, 0.20), roughness=0.4)
pipe_mat = material("Pipe", (0.45, 0.48, 0.52), metallic=0.7, roughness=0.25)
sensor_mat = material("Sensor", (0.20, 0.25, 0.30), roughness=0.5)
text_mat = material("StatusTextMat", (0.1, 0.9, 0.4), emission=2.0)

add_cylinder("Tank", (0.0, 0.0, 1.0), (1.0, 1.0, 2.0), tank_mat)
add_cylinder("Liquid", (0.0, 0.0, 0.05), (0.82, 0.82, 0.1), liquid_mat)
box("Pump", (-1.5, 0.0, 0.35), (0.5, 0.4, 0.3), pump_mat)
box("Pipe", (-0.7, 0.0, 1.5), (0.1, 0.1, 1.0), pipe_mat)
box("Valve", (0.0, 0.0, 2.3), (0.28, 0.05, 0.12), valve_mat)
box("Sensor", (0.62, 0.0, 1.8), (0.05, 0.08, 0.08), sensor_mat)

text = bpy.data.curves.new("StatusText", type="FONT")
text.body = "IDLE   level 0 %   batches 0"
text.align_x = "CENTER"
text_obj = bpy.data.objects.new("StatusText", text)
text_obj.location = (0.0, 1.4, 2.6)
text_obj.scale = (0.14, 0.14, 0.14)
text_obj.data.materials.append(text_mat)
bpy.context.collection.objects.link(text_obj)

cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (4.2, -3.6, 3.2)
bpy.context.collection.objects.link(cam)
look = Vector((0.0, 0.0, 1.1)) - cam.location
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
