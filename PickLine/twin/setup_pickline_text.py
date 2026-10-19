"""Put the self-updating RUN_PICKLINE.py loader into PickLine_Twin.blend."""
import bpy

BLEND = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/PickLine/twin/PickLine_Twin.blend"
NAME = "RUN_PICKLINE.py"

LOADER = '''# Always runs the newest blender_pickline.py sitting next to this .blend file.
import bpy

path = bpy.path.abspath("//blender_pickline.py")
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
print("Installed", NAME)
