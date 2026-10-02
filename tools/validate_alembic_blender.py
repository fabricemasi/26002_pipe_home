"""Read-only import validation, run with Blender --background --python."""
import json
import sys
from pathlib import Path

import bpy

source, report = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
result = bpy.ops.wm.alembic_import(filepath=source, as_background_job=False)
if "FINISHED" not in result:
    raise RuntimeError("Alembic import did not finish")
meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
data = {
    "objects": len(bpy.data.objects),
    "meshes": len(meshes),
    "vertices": sum(len(obj.data.vertices) for obj in meshes),
    "polygons": sum(len(obj.data.polygons) for obj in meshes),
    "cameras": sum(obj.type == "CAMERA" for obj in bpy.data.objects),
}
if not data["objects"]:
    raise RuntimeError("Empty Alembic import")
Path(report).write_text(json.dumps(data, indent=2), encoding="utf-8")
print("ALEMBIC_VALIDATED", json.dumps(data), flush=True)
