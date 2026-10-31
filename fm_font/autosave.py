"""Sauvegarde de SECOURS (sans Qt) : le travail non enregistré est copié régulièrement hors du projet, pour être
proposé à la réouverture après un plantage. Le projet de l'utilisateur n'est jamais touché par ce mécanisme.

FLUIDITÉ : sur le fil de l'interface, seulement un INSTANTANÉ en tuples (6,5 ms pour 1000 glyphes) ; la
reconstruction des UFO et l'écriture se font dans un fil à part. Dossier : `FM_FONT_AUTOSAVE_DIR` (tests), sinon
`%LOCALAPPDATA%/fm_font/secours/<clé du projet>/` (Designspace + masters + `secours.json`, écrit en dernier)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import ufoLib2

from .document import FontProject, save_ufo_atomic
from .undo import _plain, glyph_restore, glyph_snapshot

META = "secours.json"


def default_dir() -> Path:
    env = os.environ.get("FM_FONT_AUTOSAVE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "fm_font" / "secours"


def key_for(path=None, source=None, project=None) -> str:
    target = path or source
    if target is None and project is not None:
        return f"nouveau-{id(project):x}"
    return hashlib.sha1(str(Path(target).resolve()).lower().encode("utf-8")).hexdigest()[:16]


def project_key(project) -> str:
    return key_for(project.path, project.source, project)


def snapshot(project) -> dict:
    """Copie en données simples de tout le projet (fil de l'interface : quelques ms)."""
    masters = []
    for m in project.masters:
        f = m.font
        masters.append({
            "name": m.name, "location": dict(m.location), "path": str(m.path) if m.path else None,
            "info": copy.deepcopy(f.info), "order": list(f.glyphOrder),
            "glyphs": {g.name: glyph_snapshot(g) for g in f},
            "kerning": dict(f.kerning), "groups": {k: list(v) for k, v in f.groups.items()},
            "features": f.features.text, "lib": _plain(dict(f.lib)),
        })
    return {"masters": masters, "axes": copy.deepcopy(project.axes), "instances": copy.deepcopy(project.instances),
            "path": str(project.path) if project.path else None,
            "source": str(project.source) if project.source else None,
            "family": project.family_name, "time": time.time()}


def _build(master: dict) -> ufoLib2.Font:
    font = ufoLib2.Font()
    font.info = master["info"]
    for name, snap in master["glyphs"].items():
        glyph_restore(font.newGlyph(name), snap)
    font.glyphOrder = master["order"]
    font.kerning.update(master["kerning"])
    font.groups.update(master["groups"])
    font.features.text = master["features"] or ""
    font.lib.update(master["lib"])
    return font


def project_from_snapshot(snap: dict) -> FontProject:
    """Projet INDÉPENDANT reconstruit d'un instantané (fil de fond : export, secours) : modifier le projet affiché
    pendant ce temps ne change rien à ce qui est compilé ou écrit."""
    from .document import Master
    project = FontProject()
    project.axes = snap["axes"]
    project.instances = snap["instances"]
    project.path = Path(snap["path"]) if snap.get("path") else None
    project.source = Path(snap["source"]) if snap.get("source") else None
    for m in snap["masters"]:
        project.masters.append(Master(_build(m), m["name"], m["location"], Path(m["path"]) if m["path"] else None))
    return project


def write_snapshot(snap: dict, folder: Path) -> Path:
    """Écrit le secours (fil de fond possible) : masters, Designspace, puis `secours.json` (ce qui le rend
    valable)."""
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / META
    if meta_path.exists():
        meta_path.unlink()                                  # plus valable pendant l'écriture
    project = FontProject()
    project.axes = snap["axes"]
    project.instances = snap["instances"]
    from .document import Master
    for index, m in enumerate(snap["masters"]):
        font = _build(m)
        ufo = folder / f"master{index}.ufo"
        save_ufo_atomic(font, ufo)
        project.masters.append(Master(font, m["name"], m["location"], ufo))
    ds = folder / "secours.designspace"
    project.designspace(ds).write(ds)
    meta = {"path": snap["path"], "source": snap["source"], "family": snap["family"], "time": snap["time"],
            "masters": [m["path"] for m in snap["masters"]]}
    tmp = folder / (META + ".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, meta_path)
    return folder


class Autosaver:
    """Une écriture à la fois ; une demande pendant une écriture est gardée pour la suivante."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else default_dir()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def folder(self, project) -> Path:
        return self.directory / project_key(project)

    def write(self, project, background: bool = True) -> threading.Thread | None:
        snap = snapshot(project)
        folder = self.folder(project)

        def work():
            with self._lock:
                try:
                    write_snapshot(snap, folder)
                    self.last_error = None
                except Exception as exc:                    # noqa: BLE001 - secours : jamais bloquant
                    self.last_error = f"{type(exc).__name__} : {exc}"
        if not background:
            work()
            return None
        self._thread = threading.Thread(target=work, name="fm_font secours", daemon=True)
        self._thread.start()
        return self._thread

    def wait(self, timeout: float = 30) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def find(self, path=None, source=None) -> Path | None:
        """Secours PLUS RÉCENT que le fichier, pour cette source (ou police importée), sinon None."""
        folder = self.directory / key_for(path, source)
        meta_path = folder / META
        if not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        target = Path(path or source)
        newest = 0.0
        if target.exists():
            newest = target.stat().st_mtime
            for child in ("metainfo.plist", "fontinfo.plist"):
                if (target / child).is_file():
                    newest = max(newest, (target / child).stat().st_mtime)
        return folder if meta.get("time", 0) > newest else None

    def restore(self, folder: Path) -> FontProject:
        """Projet repris du secours : mêmes chemins d'enregistrement que l'original, marqué « modifié »."""
        meta = json.loads((folder / META).read_text(encoding="utf-8"))
        project = FontProject.open(folder / "secours.designspace")
        project.path = Path(meta["path"]) if meta.get("path") else None
        project.source = Path(meta["source"]) if meta.get("source") else None
        for master, original in zip(project.masters, meta.get("masters", [])):
            master.path = Path(original) if original else None
        if project.path is not None and project.path.suffix.lower() == ".ufo" and len(project.masters) == 1:
            project.masters[0].path = project.path
        project.dirty_extra = True
        project.messages.append("Version de secours récupérée : enregistrez pour la garder.")
        return project

    def discard(self, project=None, folder: Path | None = None) -> None:
        folder = folder or (self.folder(project) if project is not None else None)
        if folder is not None and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
