# Always runs the newest blender_gripper.py sitting next to this .blend file.
# Just click Run Script (or press Alt+P) - there is nothing to reload.
import bpy

path = bpy.path.abspath("//blender_gripper.py")
with open(path, encoding="utf-8") as handle:
    code = handle.read()
exec(compile(code, path, "exec"), {"__name__": "__main__"})
