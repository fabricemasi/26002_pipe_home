"""Détection de mayapy et rendu des scènes Maya.

Carte et pièges : docs/agents/apercus.md.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PySide6.QtGui import QImage
from . import blender as _blender

def _mayapy_executable() -> str | None:
    """Trouve l'interpreteur Maya necessaire pour lire les fichiers .ma."""
    configured = os.environ.get("MAYA_PYTHON_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    maya_location = os.environ.get("MAYA_LOCATION")
    candidates = [Path(maya_location) / "bin" / "mayapy.exe"] if maya_location else []
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Autodesk"
    try:
        candidates.extend(root.glob("Maya*/bin/mayapy.exe"))
    except OSError:
        pass
    existing = sorted((p for p in candidates if p.is_file()), reverse=True)
    return str(existing[0]) if existing else None

def _render_ma_wireframe(path: Path, max_dim: int, progress_callback=None, cancel_event=None, render_mode: str = "low", profile_override=None) -> QImage | None:
    """Ouvre un fichier Maya ASCII/binaire, l'exporte en Alembic temporaire et le rend."""
    mayapy = _mayapy_executable()
    if not mayapy:
        if progress_callback:
            progress_callback(99, f"Maya/mayapy introuvable pour lire le fichier {path.suffix.lower()}")
        return None
    script = r'''import sys
import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds
src, dst = sys.argv[sys.argv.index("--") + 1:sys.argv.index("--") + 3]
cmds.loadPlugin("AbcExport", quiet=True)
cmds.file(src, open=True, force=True, prompt=False, ignoreVersion=True)
frame = cmds.currentTime(query=True)
roots = cmds.ls(assemblies=True, long=True) or []
if not roots: raise RuntimeError("Aucune racine de scene a exporter")
parts = ["-frameRange", str(frame), str(frame), "-step", "1", "-dataFormat", "ogawa", "-worldSpace"]
for root in roots:
    parts.extend(("-root", '"%s"' % root.replace('"', '\\"')))
abc_output_path = dst.replace("\\", "/").replace('"', '\\"')
parts.extend(("-file", '"%s"' % abc_output_path))
cmds.AbcExport(j=" ".join(parts))
'''
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_ma_preview_") as temp_dir:
            temp = Path(temp_dir)
            script_path, abc_path = temp / "convert.py", temp / "scene.abc"
            log_path = temp / "maya_error.log"
            script_path.write_text(script, encoding="utf-8")
            env = os.environ.copy()
            tool_dir = str(Path(mayapy).resolve().parent)
            env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
            env.setdefault("MAYA_DISABLE_CIP", "1")
            log_stream = log_path.open("w", encoding="utf-8", errors="replace")
            kwargs = {"stdout": log_stream, "stderr": log_stream, "env": env}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if progress_callback:
                progress_callback(5, "Ouverture du fichier Maya dans mayapy")
            proc = subprocess.Popen([mayapy, str(script_path), "--", str(path.resolve()), str(abc_path)], **kwargs)
            deadline = time.monotonic() + 120
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    log_stream.close()
                    return None
                if time.monotonic() >= deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    log_stream.close()
                    if progress_callback:
                        progress_callback(99, "Delai depasse pendant l'ouverture Maya")
                    return None
                time.sleep(0.1)
            log_stream.close()
            if proc.returncode != 0 or not abc_path.is_file() or abc_path.stat().st_size == 0:
                if progress_callback:
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    detail = next((line.strip() for line in reversed(lines) if line.strip()), "")
                    progress_callback(99, f"Echec import Maya : {detail or 'export Alembic impossible'}")
                return None
            if progress_callback:
                progress_callback(32, "Scene convertie; rendu Eevee dans le template")
            return _blender._render_wireframe_eevee(abc_path, max_dim, progress_callback, cancel_event, kind_override="maya", render_mode=render_mode, profile_override=profile_override)
    except (OSError, subprocess.SubprocessError):
        return None
