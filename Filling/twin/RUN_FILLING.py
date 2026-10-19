# Always runs the newest blender_filling.py sitting next to this .blend file.
import bpy

path = bpy.path.abspath("//blender_filling.py")
with open(path, encoding="utf-8") as handle:
    code = handle.read()
exec(compile(code, path, "exec"), {"__name__": "__main__"})
