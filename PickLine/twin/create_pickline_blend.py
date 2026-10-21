"""Create the Blender scene for the PickLine (gantry + conveyor, two fill stations)."""
import bpy
from mathutils import Vector

OUT = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/PickLine/twin/PickLine_Twin.blend"

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def material(name, color, metallic=0.0, roughness=0.5, emission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = (*color, 1.0)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    bsdf.inputs["Emission Strength"].default_value = emission
    return m


def tank_material(name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Alpha"].default_value = 0.18
    bsdf.inputs["Roughness"].default_value = 0.08
    m.blend_method = "BLEND"
    return m


def grid_material(name, dark, light):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    checker = m.node_tree.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Color1"].default_value = (*dark, 1.0)
    checker.inputs["Color2"].default_value = (*light, 1.0)
    checker.inputs["Scale"].default_value = 10.0
    m.node_tree.links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
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


def add_sphere(name, loc, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


floor_mat = grid_material("Floor", (0.08, 0.09, 0.11), (0.12, 0.14, 0.17))
belt_mat = material("Belt", (0.16, 0.18, 0.21), roughness=0.55)
lane_mat = material("Lane", (0.42, 0.32, 0.18), roughness=0.6)
roller_mat = material("Roller", (0.62, 0.66, 0.72), metallic=0.9, roughness=0.25)
frame_mat = material("Frame", (0.20, 0.24, 0.30), metallic=0.8, roughness=0.35)
rail_mat = material("Rail", (0.28, 0.33, 0.40), metallic=0.85, roughness=0.3)
bin_mat = material("Bin", (0.82, 0.58, 0.08), metallic=0.2, roughness=0.45)
gate_mat = material("Gate", (0.88, 0.26, 0.18), roughness=0.4)
tool_mat = material("Tool", (0.95, 0.45, 0.10), metallic=0.4, roughness=0.3)
carriage_mat = material("Carriage", (0.90, 0.35, 0.10), metallic=0.6, roughness=0.3)
part_mat = material("Part", (0.95, 0.72, 0.10), metallic=0.2, roughness=0.35)
sensor_mat = material("Sensor", (0.16, 0.20, 0.25), roughness=0.5)
tank_mat = tank_material("Tank", (0.78, 0.84, 0.90))
rim_mat = material("Rim", (0.55, 0.60, 0.66), metallic=0.9, roughness=0.25)
liquid_mat = material("Liquid", (0.10, 0.55, 0.90), roughness=0.15, emission=0.5)
nozzle_mat = material("Nozzle", (0.35, 0.40, 0.46), metallic=0.9, roughness=0.25)
stream_mat = material("Stream", (0.35, 0.78, 0.98), emission=2.5)
text_mat = material("StatusTextMat", (0.1, 0.9, 0.4), emission=2.0)
lens_grey = (0.40, 0.43, 0.47)
light_red = material("LightRed", lens_grey, roughness=0.3, emission=0.0)
light_yellow = material("LightYellow", lens_grey, roughness=0.3, emission=0.0)
light_green = material("LightGreen", lens_grey, roughness=0.3, emission=0.0)
light_blue = material("LightBlue", lens_grey, roughness=0.3, emission=0.0)
tower_pole_mat = material("TowerPole", (0.10, 0.11, 0.13), metallic=0.7, roughness=0.35)

# Grid floor.
bpy.ops.mesh.primitive_plane_add(size=14, location=(2.0, 1.1, 0.0))
floor = bpy.context.object
floor.name = "Floor"
floor.data.materials.append(floor_mat)

# Straight belt: 4 m along X at Y = 1 m.
box("Belt", (2.0, 1.0, 0.04), (2.0, 0.09, 0.02), belt_mat)
add_cylinder("RollerL", (0.0, 1.0, 0.05), (0.08, 0.12, 0.08), roller_mat, (1.5708, 0, 0))
add_cylinder("RollerR", (4.0, 1.0, 0.05), (0.08, 0.12, 0.08), roller_mat, (1.5708, 0, 0))
for i, x in enumerate((1.0, 2.0, 3.0)):
    add_cylinder("RollerM%d" % i, (x, 1.0, 0.05), (0.055, 0.10, 0.055), roller_mat, (1.5708, 0, 0))

# Conveyor side rails.
box("RailFront", (2.0, 1.13, 0.10), (2.0, 0.02, 0.02), rail_mat)
box("RailBack", (2.0, 0.87, 0.10), (2.0, 0.02, 0.02), rail_mat)

# Left lane and straight approach lane.
box("Lane", (4.0, 1.7, 0.04), (0.09, 0.7, 0.02), lane_mat)
box("LaneStraight", (4.3, 1.0, 0.04), (0.3, 0.09, 0.02), lane_mat)

# End gate.
box("Gate", (4.0, 1.12, 0.08), (0.035, 0.16, 0.03), gate_mat)

# Gantry: four posts, two X-rails and a moving carriage.
for px, py in ((0.0, 0.15), (3.0, 0.15), (0.0, 1.85), (3.0, 1.85)):
    box("Post_%.1f_%.1f" % (px, py), (px, py, 0.58), (0.06, 0.06, 0.58), frame_mat)
box("RailY0", (1.5, 0.15, 1.15), (1.5, 0.04, 0.04), rail_mat)
box("RailY2", (1.5, 1.85, 1.15), (1.5, 0.04, 0.04), rail_mat)
box("Carriage", (0.0, 0.0, 1.08), (0.22, 0.14, 0.07), carriage_mat)

# Two bins: DOWN at y = 0.2, UP at y = 1.9.
box("BinDown", (2.6, 0.2, 0.10), (0.16, 0.16, 0.10), bin_mat)
box("BinUp", (2.6, 1.9, 0.10), (0.16, 0.16, 0.10), bin_mat)

# Parts waiting in the bins.
box("PartDown", (2.6, 0.2, 0.18), (0.05, 0.05, 0.05), part_mat)
box("PartUp", (2.6, 1.9, 0.18), (0.05, 0.05, 0.05), part_mat)

# Gantry tool head and jaws.
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0.0, 0.0, 0.6))
tool = bpy.context.object
tool.name = "ToolHead"
tool.data.materials.append(tool_mat)
box("JawA", (0.0, 0.06, 0.42), (0.03, 0.03, 0.08), frame_mat)
box("JawB", (0.0, -0.06, 0.42), (0.03, 0.03, 0.08), frame_mat)

# The part in flight (hidden until picked).
box("Part", (100.0, 100.0, 100.0), (0.04, 0.04, 0.04), part_mat)

# Sensors.
box("SensorIn", (0.3, 1.0, 0.08), (0.025, 0.025, 0.025), sensor_mat)
box("SensorOut", (3.7, 1.0, 0.08), (0.025, 0.025, 0.025), sensor_mat)
box("SensorDivert", (4.0, 2.3, 0.08), (0.025, 0.025, 0.025), sensor_mat)

# Two fill stations.
box("TankA", (4.6, 1.0, 0.30), (0.17, 0.17, 0.30), tank_mat)
box("LiquidA", (4.6, 1.0, 0.03), (0.13, 0.13, 0.03), liquid_mat)
add_cylinder("RimA", (4.6, 1.0, 0.61), (0.17, 0.17, 0.012), rim_mat)
box("TankB", (4.0, 2.4, 0.30), (0.17, 0.17, 0.30), tank_mat)
box("LiquidB", (4.0, 2.4, 0.03), (0.13, 0.13, 0.03), liquid_mat)
add_cylinder("RimB", (4.0, 2.4, 0.61), (0.17, 0.17, 0.012), rim_mat)

# Nozzles and fill streams above each tank.
add_cylinder("NozzleA", (4.6, 1.0, 0.82), (0.03, 0.03, 0.06), nozzle_mat)
add_cylinder("StreamA", (4.6, 1.0, 0.67), (0.015, 0.015, 0.005), stream_mat)
add_cylinder("NozzleB", (4.0, 2.4, 0.82), (0.03, 0.03, 0.06), nozzle_mat)
add_cylinder("StreamB", (4.0, 2.4, 0.67), (0.015, 0.015, 0.005), stream_mat)

# Industrial signal tower: pole + red, yellow, green, blue (top to bottom).
add_cylinder("TowerPole", (0.4, -0.4, 0.56), (0.018, 0.018, 0.56), tower_pole_mat)
add_cylinder("TowerBlue", (0.4, -0.4, 0.24), (0.14, 0.14, 0.11), light_blue)
add_cylinder("TowerGreen", (0.4, -0.4, 0.48), (0.14, 0.14, 0.11), light_green)
add_cylinder("TowerYellow", (0.4, -0.4, 0.72), (0.14, 0.14, 0.11), light_yellow)
add_cylinder("TowerRed", (0.4, -0.4, 0.96), (0.14, 0.14, 0.11), light_red)

# Status text.
text = bpy.data.curves.new("StatusText", type="FONT")
text.body = "IDLE   done A0 B0"
text.align_x = "CENTER"
text_obj = bpy.data.objects.new("StatusText", text)
text_obj.location = (2.0, 3.0, 2.0)
text_obj.scale = (0.14, 0.14, 0.14)
text_obj.data.materials.append(text_mat)
bpy.context.collection.objects.link(text_obj)

# Camera.
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (2.6, -8.5, 4.5)
cam.data.lens = 28.0
bpy.context.collection.objects.link(cam)
look = Vector((2.5, 0.8, 0.5)) - cam.location
cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

# Lighting: key sun, soft area fill, and a cool rim light.
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
sun.data.energy = 3.5
sun.location = (2, -7, 10)
bpy.context.collection.objects.link(sun)

bpy.ops.object.light_add(type="AREA", location=(2.0, 1.1, 6.0))
area = bpy.context.object
area.name = "FillArea"
area.data.energy = 220.0
area.data.size = 8.0

bpy.ops.object.light_add(type="POINT", location=(7.0, -3.0, 2.0))
rim = bpy.context.object
rim.name = "RimPoint"
rim.data.energy = 400.0
rim.data.color = (0.55, 0.70, 1.0)

# World: dark blue-grey backdrop.
world = bpy.context.scene.world
if world and world.use_nodes:
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.045, 0.055, 0.075, 1.0)

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("Saved:", OUT)
