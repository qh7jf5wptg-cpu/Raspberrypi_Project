"""Put the self-updating RUN_GRIPPER.py loader into Gripper_Twin.blend.

Run:
    blender --background --python setup_gripper_text.py
"""
import bpy

BLEND = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/Gripper/twin/Gripper_Twin.blend"
NAME = "RUN_GRIPPER.py"

LOADER = '''# Always runs the newest blender_gripper.py sitting next to this .blend file.
# Just click Run Script (or press Alt+P) - there is nothing to reload.
import bpy

path = bpy.path.abspath("//blender_gripper.py")
with open(path, encoding="utf-8") as handle:
    code = handle.read()
exec(compile(code, path, "exec"), {"__name__": "__main__"})
'''

bpy.ops.wm.open_mainfile(filepath=BLEND)

text = bpy.data.texts.get(NAME) or bpy.data.texts.new(NAME)
text.clear()
text.write(LOADER)
text.filepath = ""
text.use_fake_user = True

bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
print("Installed", NAME, "->", [t.name for t in bpy.data.texts])
