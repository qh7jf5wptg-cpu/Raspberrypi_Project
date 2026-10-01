#!/usr/bin/env python3
"""Put a self-updating loader into RaspberryPi_Twin.blend.

Blender copies a script *into* the .blend file when you open it in the Text
Editor. That copy never follows the file on disk, so after a `git pull` you
are still running yesterday's code until you click Text > Reload from Disk.

This script replaces that stale copy with a six-line loader that reads the
real `blender_twin.py` from disk every time you run it. So "Run Script" is
never out of date again, and there is nothing to reload.

Run it once with Blender in background mode:

    /Applications/Blender.app/Contents/MacOS/Blender --background \\
        --factory-startup --python digital-twin/setup_twin_text.py

Set TWIN_BLEND if the .blend lives somewhere else.
"""
import os
import sys

import bpy

LOADER_NAME = "RUN_TWIN.py"
TARGET = "blender_twin.py"

LOADER = '''# Always runs the newest blender_twin.py sitting next to this .blend file.
# Just click Run Script (or press Alt+P) - there is nothing to reload.
import bpy

path = bpy.path.abspath("//{target}")
with open(path, encoding="utf-8") as handle:
    code = handle.read()
exec(compile(code, path, "exec"), {{"__name__": "__main__"}})
'''.format(target=TARGET)


def find_blend():
    override = os.environ.get("TWIN_BLEND")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "RaspberryPi_Twin.blend")


def main():
    blend = find_blend()
    if not os.path.isfile(blend):
        print("Blend file not found:", blend)
        sys.exit(1)

    bpy.ops.wm.open_mainfile(filepath=blend)
    print("opened", blend)
    print("texts before:", [t.name for t in bpy.data.texts])

    stale = bpy.data.texts.get(TARGET)
    if stale is not None:
        bpy.data.texts.remove(stale)
        print("removed the embedded copy of", TARGET)

    text = bpy.data.texts.get(LOADER_NAME)
    if text is None:
        text = bpy.data.texts.new(LOADER_NAME)
    text.clear()
    text.write(LOADER)
    text.filepath = ""          # not linked to a file, so it cannot go stale
    text.use_fake_user = True   # keep it even if no editor is showing it
    print("installed", LOADER_NAME)

    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    print("saved", blend)
    print("texts after:", [t.name for t in bpy.data.texts])
    print("objects after:", sorted(o.name for o in bpy.data.objects))


main()
