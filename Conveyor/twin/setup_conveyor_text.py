"""Put the self-updating RUN_CONVEYOR.py loader into Conveyor_Twin.blend."""
import bpy

BLEND = "/Users/kjde/Documents/ChatGPT/Raspberrypi_Project/Conveyor/twin/Conveyor_Twin.blend"
NAME = "RUN_CONVEYOR.py"

LOADER = '''# Always runs the newest blender_conveyor.py sitting next to this .blend file.
import bpy

path = bpy.path.abspath("//blender_conveyor.py")
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
