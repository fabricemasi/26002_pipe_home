"""Détection de hython, export Houdini et rendu Blender.

Carte et pièges : docs/agents/apercus.md.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtGui import QImage
from . import blender as _blender

def _hython_executable() -> str | None:
    """Trouve hython (Python de Houdini), necessaire pour lire les .hip : HOUDINI_HYTHON, puis
    $HFS/bin, puis la version la plus recente sous Side Effects Software."""
    configured = os.environ.get("HOUDINI_HYTHON")
    if configured and Path(configured).is_file():
        return configured
    candidates = []
    if os.environ.get("HFS"):
        candidates.append(Path(os.environ["HFS"]) / "bin" / "hython.exe")
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Side Effects Software"
    try:
        candidates.extend(root.glob("Houdini*/bin/hython.exe"))
    except OSError:
        pass

    def version_key(path: Path):
        return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.parent.parent.name)]
    existing = sorted((p for p in candidates if p.is_file()), key=version_key, reverse=True)
    return str(existing[0]) if existing else None

# Execute DANS hython (pas dans l'appli) : ouvre la scene SANS jamais l'enregistrer, reunit la
# geometrie AFFICHEE de /obj a l'image courante (jamais les objets masques : les cuire peut prendre
# des minutes ; une scene rendue via Solaris sans objet affiche echoue donc tout de suite), en
# espace monde, depaquetee et convertie en polygones,
# puis l'exporte en Alembic. Les scenes non commerciales (.hipnc) n'ont pas le droit d'exporter
# en Alembic : OBJ ecrit en Python pur a la place (sens des faces inverse : Houdini tourne dans
# le sens horaire). Imprime « PIPE_FORMAT abc|obj » pour l'appli.
_HIP_EXPORT_SCRIPT = r'''import sys
import hou
src, dst_abc, dst_obj = sys.argv[sys.argv.index("--") + 1:sys.argv.index("--") + 4]
hou.hipFile.load(src, suppress_save_prompt=True, ignore_load_warnings=True)

def geometry_objects(displayed_only=True):
    found = []
    for node in hou.node("/obj").allSubChildren():
        if not isinstance(node, hou.ObjNode) or node.name() == "__pipe_preview":
            continue
        kind = node.type().name().split("::")[0].lower()
        if "cam" in kind or "light" in kind:
            continue
        try:
            sop = node.displayNode()
        except Exception:
            sop = None
        if sop is None:
            continue
        if displayed_only and not node.isObjectDisplayed():
            continue
        found.append(node)
    return found

objects = geometry_objects(True)
if not objects:
    raise RuntimeError("Error: aucun objet affiche dans /obj (scene rendue via Solaris ?)")
preview = hou.node("/obj").createNode("geo", "__pipe_preview")
for child in preview.children():
    child.destroy()
merge = preview.createNode("object_merge")
merge.parm("numobj").set(len(objects))
for index, node in enumerate(objects, 1):
    merge.parm("objpath%d" % index).set(node.path())
merge.parm("xformtype").set(1)
last = merge
for _ in range(3):
    last = last.createOutputNode("unpack")
last = last.createOutputNode("convert")
geometry = last.geometry()
polygons = [prim for prim in geometry.prims() if prim.type() == hou.primType.Polygon] if geometry else []
if not polygons:
    raise RuntimeError("Error: aucun polygone dans la geometrie affichee a l'image %s" % hou.frame())
try:
    rop = last.createOutputNode("rop_alembic")
    rop.parm("filename").set(dst_abc.replace("\\", "/"))
    rop.parm("trange").set(0)
    rop.render()
    print("PIPE_FORMAT abc")
except hou.OperationFailed:
    positions = geometry.pointFloatAttribValues("P")
    with open(dst_obj, "w") as stream:
        for i in range(0, len(positions), 3):
            stream.write("v %.6g %.6g %.6g\n" % (positions[i], positions[i + 1], positions[i + 2]))
        for prim in polygons:
            numbers = [point.number() + 1 for point in prim.points()]
            if len(numbers) >= 3:
                stream.write("f %s\n" % " ".join(str(n) for n in reversed(numbers)))
    print("PIPE_FORMAT obj")
'''

def _render_hip_wireframe(path: Path, max_dim: int, progress_callback=None, cancel_event=None,
                          render_mode: str = "low", profile_override=None) -> QImage | None:
    """Scene Houdini : hython en exporte la geometrie affichee (_HIP_EXPORT_SCRIPT), puis meme rendu
    Blender que les autres fichiers 3D (profils low/high, turntable). None sans Houdini, scene
    illisible ou sans polygone."""
    hython = _hython_executable()
    if not hython:
        if progress_callback:
            progress_callback(99, f"Houdini/hython introuvable pour lire le fichier {path.suffix.lower()}")
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_hip_preview_") as temp_dir:
            temp = Path(temp_dir)
            script_path, abc_path, obj_path = temp / "export.py", temp / "scene.abc", temp / "scene.obj"
            log_path = temp / "houdini.log"
            script_path.write_text(_HIP_EXPORT_SCRIPT, encoding="utf-8")
            log_stream = log_path.open("w", encoding="utf-8", errors="replace")
            kwargs = {"stdout": log_stream, "stderr": log_stream}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if progress_callback:
                progress_callback(5, "Ouverture de la scene dans hython")
            proc = subprocess.Popen([hython, str(script_path), "--", str(path.resolve()), str(abc_path),
                                     str(obj_path)], **kwargs)
            # Demarrage de Houdini (10-20 s) + cuisson de la scene a l'image courante.
            deadline = time.monotonic() + 300
            while proc.poll() is None:
                if (cancel_event is not None and cancel_event.is_set()) or time.monotonic() >= deadline:
                    timed_out = time.monotonic() >= deadline
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    log_stream.close()
                    if timed_out and progress_callback:
                        progress_callback(99, "Delai depasse pendant l'ouverture Houdini")
                    return None
                time.sleep(0.1)
            log_stream.close()
            source = next((p for p in (abc_path, obj_path) if p.is_file() and p.stat().st_size > 0), None)
            if proc.returncode != 0 or source is None:
                if progress_callback:
                    lines = [line.strip() for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                             if line.strip() and "dehancer" not in line]
                    detail = next((line for line in reversed(lines) if "Error" in line or "rror:" in line),
                                  lines[-1] if lines else "")
                    progress_callback(99, f"Echec Houdini : {detail or 'export impossible'}")
                return None
            if progress_callback:
                progress_callback(32, "Scene Houdini exportee; rendu Eevee dans le template")
            return _blender._render_wireframe_eevee(source, max_dim, progress_callback, cancel_event,
                                           kind_override="houdini" if source == abc_path else "obj",
                                           render_mode=render_mode, profile_override=profile_override)
    except (OSError, subprocess.SubprocessError):
        return None
