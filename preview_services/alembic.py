"""Aperçus Alembic et script Blender embarqué.

Carte et pièges : docs/agents/apercus.md.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtGui import QImage
from . import blender as _blender
from . import executables as _executables
from . import obj as _obj
from . import profiles as _profiles

def _is_legacy_alembic(path: Path) -> bool:
    with path.open("rb") as source_file:
        return source_file.read(8) == b"\x89HDF\r\n\x1a\n"

def _decode_abc_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None, render_mode: str = "low", profile_override=None) -> QImage | None:
    """Extrait le maillage Alembic via Blender, puis reutilise le rendu OBJ."""
    try:
        legacy_hdf5 = _is_legacy_alembic(path)
    except OSError:
        return None
    if legacy_hdf5:
        if progress_callback:
            progress_callback(100, "Alembic HDF5 obsolète : réexport Blender en Ogawa requis")
        return None
    eevee_image = _blender._render_wireframe_eevee(path, max_dim, progress_callback, cancel_event, render_mode=render_mode, profile_override=profile_override)
    if eevee_image is not None:
        return eevee_image
    if cancel_event is not None and cancel_event.is_set():
        return None
    template_path = Path(__file__).resolve().parent.parent / "files" / str(_profiles._render_profile(render_mode, profile_override)["template"])
    if _executables._blender_executable() and template_path.is_file():
        return None
    blender = _executables._blender_executable()
    if not blender:
        if progress_callback:
            progress_callback(1, "Blender introuvable")
        return None
    # Blender evalue l'Alembic a sa frame de depart et exporte les meshes
    # evalues en OBJ temporaire. Le rendu et le cadrage restent identiques
    # aux apercus OBJ, et le cache existant evite de relancer Blender.
    script = r'''import bpy, sys
from mathutils import Vector
src, dst, status_path = sys.argv[sys.argv.index("--") + 1:sys.argv.index("--") + 4]
def report(pct, message):
    with open(status_path, "w", encoding="utf-8") as status:
        status.write("%d|%s" % (pct, message))
report(5, "Import Alembic dans Blender")
# Blender demarre avec une scene contenant un cube par defaut : vider la
# scene avant l'import pour ne pas l'inclure dans le maillage d'aperçu.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.wm.alembic_import(filepath=src)
source_y_up = open(src, "rb").read(8) == b"\x89HDF\r\n\x1a\n"
report(18, "Alembic importé; conversion Y-up" if source_y_up else "Alembic importé; axe Z-up")
deps = bpy.context.evaluated_depsgraph_get()
vertices, polygons = [], []
triangle_count = 0
limit = 150000
mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
for object_index, obj in enumerate(mesh_objects):
    report(18 + int(12 * object_index / max(1, len(mesh_objects))),
           "Extraction du maillage : objet %d/%d" % (object_index + 1, len(mesh_objects)))
    if obj.type != "MESH": continue
    evaluated = obj.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    if not mesh: continue
    offset = len(vertices)
    matrix = evaluated.matrix_world
    for vertex in mesh.vertices:
        world = matrix @ vertex.co
        vertices.append(Vector((world.x, -world.z, world.y)) if source_y_up else world)
    poly_step = max(1, len(mesh.polygons) // 8)
    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index % poly_step == 0:
            report(20 + int(10 * (object_index + poly_index / max(1, len(mesh.polygons)))
                             / max(1, len(mesh_objects))),
                   "Extraction des faces : %d/%d" % (poly_index + 1, len(mesh.polygons)))
        ids = list(poly.vertices)
        if len(ids) >= 3:
            polygons.append([offset + i + 1 for i in ids])
            triangle_count += len(ids) - 2
        if triangle_count >= limit: break
    evaluated.to_mesh_clear()
    if triangle_count >= limit: break
report(32, "Écriture du maillage temporaire")
with open(dst, "w", encoding="utf-8") as f:
    for v in vertices: f.write("v %.9g %.9g %.9g\n" % (v.x, v.y, v.z))
    for polygon in polygons: f.write("f " + " ".join(map(str, polygon)) + "\n")
report(35, "Maillage prêt; préparation du rendu")
'''
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_abc_preview_") as temp_dir:
            temp = Path(temp_dir)
            pyfile, meshfile, statusfile = temp / "extract.py", temp / "mesh.obj", temp / "status.txt"
            pyfile.write_text(script, encoding="utf-8")
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen([blender, "--background", "--python", str(pyfile), "--",
                                     str(path.resolve()), str(meshfile), str(statusfile)], **kwargs)
            if progress_callback:
                progress_callback(3, "Démarrage de Blender")
            deadline = time.monotonic() + 45
            last_status = ""
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    return None
                try:
                    current_status = statusfile.read_text(encoding="utf-8")
                    if current_status and current_status != last_status:
                        last_status = current_status
                        percent_text, message = current_status.split("|", 1)
                        if progress_callback:
                            progress_callback(int(percent_text), message)
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    proc.terminate()
                    proc.wait(timeout=3)
                    return None
                time.sleep(0.1)
            if proc.returncode != 0:
                return None
            if not meshfile.is_file() or meshfile.stat().st_size == 0:
                return None
            return _obj._decode_obj_image(
                meshfile, max_dim,
                progress_callback=(lambda pct, msg: progress_callback(35 + int(pct * 0.64), msg))
                if progress_callback else None, cancel_event=cancel_event, render_mode=render_mode,
                profile_override=profile_override,
            )
    except (OSError, subprocess.SubprocessError):
        return None
