"""Create the Blender scene for the PickLine (gripper + conveyor)."""
import bpy
from mathutils import Vector

OUT = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/PickLine/twin/PickLine_Twin.blend"

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


def add_cylinder(name, loc, scale, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.rotation_euler = rot
    obj.data.materials.append(mat)
    return obj


def box(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


belt_mat = material("Belt", (0.35, 0.38, 0.42), roughness=0.7)
roller_mat = material("Roller", (0.55, 0.58, 0.62), metallic=0.6, roughness=0.3)
frame_mat = material("Frame", (0.25, 0.30, 0.38), metallic=0.5, roughness=0.4)
bin_mat = material("Bin", (0.80, 0.62, 0.10), roughness=0.5)
tool_mat = material("Tool", (0.90, 0.45, 0.12), roughness=0.4)
part_mat = material("Part", (0.95, 0.78, 0.10), roughness=0.35)
sensor_mat = material("Sensor", (0.18, 0.22, 0.26), roughness=0.5)
text_mat = material("StatusTextMat", (0.1, 0.9, 0.4), emission=2.0)

# Conveyor belt: 4 m long along X, at Y = 1 m, thin on the ground.
box("Belt", (2.0, 1.0, 0.04), (2.0, 0.09, 0.02), belt_mat)
add_cylinder("RollerL", (0.0, 1.0, 0.05), (0.08, 0.12, 0.08), roller_mat, (1.5708, 0, 0))
add_cylinder("RollerR", (4.0, 1.0, 0.05), (0.08, 0.12, 0.08), roller_mat, (1.5708, 0, 0))

# Gantry frame: a beam spanning over the belt and the bin.
box("FrameBeam", (1.5, 0.9, 1.0), (1.5, 0.05, 0.05), frame_mat)
box("FramePostA", (0.0, 0.9, 0.5), (0.05, 0.05, 0.5), frame_mat)
box("FramePostB", (3.0, 0.9, 0.5), (0.05, 0.05, 0.5), frame_mat)

# Bin at the far end of the gantry area.
box("Bin", (2.6, 0.2, 0.10), (0.16, 0.16, 0.10), bin_mat)

# Gantry tool head and jaws.
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0.0, 0.0, 0.6))
tool = bpy.context.object
tool.name = "ToolHead"
tool.data.materials.append(tool_mat)
box("JawA", (0.0, 0.06, 0.42), (0.03, 0.03, 0.08), frame_mat)
box("JawB", (0.0, -0.06, 0.42), (0.03, 0.03, 0.08), frame_mat)

# The part (hidden off-screen until picked).
box("Part", (100.0, 100.0, 100.0), (0.04, 0.04, 0.04), part_mat)

# Sensors on the belt.
box("SensorIn", (0.3, 1.0, 0.08), (0.025, 0.025, 0.025), sensor_mat)
box("SensorOut", (3.7, 1.0, 0.08), (0.025, 0.025, 0.025), sensor_mat)

# Status text.
text = bpy.data.curves.new("StatusText", type="FONT")
text.body = "IDLE   placed 0   exited 0"
text.align_x = "CENTER"
text_obj = bpy.data.objects.new("StatusText", text)
text_obj.location = (2.0, 2.4, 1.8)
text_obj.scale = (0.14, 0.14, 0.14)
text_obj.data.materials.append(text_mat)
bpy.context.collection.objects.link(text_obj)

# Camera and light.
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (2.0, -3.8, 2.6)
bpy.context.collection.objects.link(cam)
look = Vector((2.0, 1.0, 0.5)) - cam.location
cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
sun.data.energy = 4.0
sun.location = (2, -6, 8)
bpy.context.collection.objects.link(sun)

world = bpy.context.scene.world
if world and world.use_nodes:
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1.0)

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("Saved:", OUT)
