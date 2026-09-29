"""Create the starter Blender scene for the Raspberry Pi digital twin.

Produces a small machine with:
  - a "Rotor" object (a propeller bar the twin script spins)
  - a "LED" material (assigned to an indicator sphere, toggled red/dark)
  - a camera and a sun light

Run:
  blender --background --python create_twin_blend.py
"""

import bpy
from mathutils import Vector

OUT = "/Users/kjde/Documents/ChatGPT/Testing/digital-twin/RaspberryPi_Twin.blend"

# Start from a clean scene.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def make_material(name, color, metallic=0.0, roughness=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return m


led_mat = make_material("LED", (0.05, 0.05, 0.05), roughness=0.3)
body_mat = make_material("MachineBody", (0.22, 0.26, 0.30), metallic=0.4, roughness=0.45)
rotor_mat = make_material("RotorMetal", (0.85, 0.20, 0.20), metallic=0.7, roughness=0.3)
heat_mat = make_material("Heatbar", (0.10, 0.35, 0.90), roughness=0.4)

# Machine body.
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
body = bpy.context.object
body.name = "MachineBody"
body.scale = (2.4, 1.3, 0.35)
body.data.materials.append(body_mat)

# Rotor: a propeller bar; blender_twin.py spins it around Z.
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.22))
rotor = bpy.context.object
rotor.name = "Rotor"
rotor.scale = (1.15, 0.14, 0.06)
rotor.data.materials.append(rotor_mat)

# LED indicator sphere.
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.08, location=(0.95, 0, 0.24))
led = bpy.context.object
led.name = "LED"
led.data.materials.append(led_mat)

# Temperature readout (3D text, updated live by blender_twin.py).
temp_text = bpy.data.curves.new("TempText", type="FONT")
temp_text.body = "45.0 C"
temp_text.align_x = "CENTER"
temp_obj = bpy.data.objects.new("TempText", temp_text)
temp_obj.location = (0.0, 0.0, 0.85)
temp_obj.scale = (0.35, 0.35, 0.35)
bpy.context.collection.objects.link(temp_obj)

# Heat bar: a thin vertical strip whose color maps to temperature.
bpy.ops.mesh.primitive_cube_add(size=1, location=(1.55, 0.0, 0.22))
heat = bpy.context.object
heat.name = "Heatbar"
heat.scale = (0.07, 0.07, 0.34)
heat.data.materials.append(heat_mat)

# Camera.
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
cam.location = (4.5, -4.0, 3.0)
bpy.context.collection.objects.link(cam)
look = Vector((0, 0, 0.25)) - cam.location
cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

# Sun light.
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
sun.data.energy = 4.0
sun.location = (4, -6, 8)
bpy.context.collection.objects.link(sun)

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("Saved:", OUT)
