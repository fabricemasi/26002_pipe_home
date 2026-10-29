"""Détection de Blender.

Carte et pièges : docs/agents/apercus.md.
"""

import os
import shutil
import sys
from pathlib import Path

def _blender_executable() -> str | None:
    """Trouve Blender, requis pour lire les caches Alembic binaires."""
    configured = os.environ.get("BLENDER_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("blender")
    if found:
        return found
    if sys.platform == "win32":
        for root in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation",
                     Path(r"C:\Program Files\Blender Foundation")):
            try:
                candidates = sorted(root.glob("Blender */blender.exe"), reverse=True)
                if candidates:
                    return str(candidates[0])
            except OSError:
                pass
    return None
