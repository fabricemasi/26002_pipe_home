"""Type « audio_doc » du `.brd` (SANS Qt) : un son, une prise, un sample, un effet, une ambiance, un
mixage, un export, un projet FM Audio ou une composition FM Music posé sur le Board.

Le Board ORGANISE et RÉFÉRENCE : le fichier est lié (chemin absolu + relatif au board), jamais
copié ni modifié. Valeurs : `title`, `path`, `rel`, `role` (rôle affiché, deviné du nom, modifiable),
`module` (« audio » | « music » : bonne cible d'ouverture), `resource` / `revision` (identité de la
bibliothèque commune et révision épinglée), `duration`, `sample_rate`, `channels`, `codec`,
`tags`, `note`. Une version de l'appli qui ne connaît pas ce type le garde dans `foreign`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

AUDIO_DOC = "audio_doc"
AUDIO_TYPES = (AUDIO_DOC,)
ROLES = ("son", "prise", "sample", "effet", "ambiance", "mixage", "export", "projet", "composition", "stem")
DEFAULTS = {AUDIO_DOC: {"w": 280.0, "h": 104.0, "title": "", "path": "", "rel": "", "role": "son", "module": "audio",
                        "resource": "", "revision": 0, "duration": 0.0, "sample_rate": 0, "channels": 0, "codec": "",
                        "tags": "", "note": ""}}
MIN_W, MIN_H = 140.0, 56.0
SOUND_EXT = (".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a", ".bwf", ".rf64")
PROJECT_EXT = {".fmaudio": ("projet", "audio"), ".fmmusic": ("composition", "music"), ".mid": ("composition", "music"),
               ".midi": ("composition", "music")}


def accepts(path) -> bool:
    s = Path(path).suffix.lower()
    return s in SOUND_EXT or s in PROJECT_EXT


def guess_role(path) -> tuple[str, str]:
    """(rôle, module) d'après l'extension puis le nom (prise, sample, sfx, ambiance, mix, export, stem)."""
    p = Path(path)
    s = p.suffix.lower()
    if s in PROJECT_EXT:
        return PROJECT_EXT[s]
    name = p.stem.lower()
    for pattern, role in ((r"(prise|take|_p\d\d)", "prise"), (r"(sample|one.?shot|kick|snare|hat)", "sample"),
                          (r"(sfx|fx|effet|foley)", "effet"), (r"(ambi|room|atmos)", "ambiance"), (r"stem", "stem"),
                          (r"(mix|master)", "mixage"), (r"(export|bounce|render)", "export")):
        if re.search(pattern, name):
            return role, "audio"
    return "son", "audio"


def normalize_entity(item: dict) -> None:
    base = DEFAULTS[AUDIO_DOC]
    item["w"] = max(MIN_W, float(item.get("w") or base["w"]))
    item["h"] = max(MIN_H, float(item.get("h") or base["h"]))
    for key in ("title", "path", "rel", "resource", "codec", "tags", "note"):
        if not isinstance(item.get(key), str):
            item[key] = ""
    if item.get("role") not in ROLES:
        item["role"] = "son"
    if item.get("module") not in ("audio", "music"):
        item["module"] = "audio"
    for key, cast, low in (("revision", int, 0), ("sample_rate", int, 0), ("channels", int, 0), ("duration", float, 0.0)):
        try:
            item[key] = max(low, cast(item.get(key) or 0))
        except (TypeError, ValueError):
            item[key] = low


def link_values(path, board_path=None) -> dict:
    """{path, rel, title, role, module} ; `rel` seulement si le board est enregistré sur le même volume."""
    path = Path(path).resolve()
    rel = ""
    if board_path:
        try:
            rel = os.path.relpath(path, Path(board_path).resolve().parent)
        except ValueError:                                   # autre lecteur
            rel = ""
    role, module = guess_role(path)
    return {"path": str(path), "rel": rel, "title": path.stem, "role": role, "module": module}


def resolve(item: dict, board_path=None) -> Path | None:
    """Fichier lié : relatif au board d'abord (dossier déplacé), puis absolu ; None s'il est introuvable."""
    if item.get("rel") and board_path:
        candidate = (Path(board_path).resolve().parent / item["rel"]).resolve()
        if candidate.is_file():
            return candidate
    if item.get("path") and Path(item["path"]).is_file():
        return Path(item["path"])
    return None


def relink(item: dict, new_path, board_path=None) -> dict:
    """Réparation contrôlée d'une référence : nouvelles valeurs de lien (titre, rôle, révision conservés)."""
    v = link_values(new_path, board_path)
    return {"path": v["path"], "rel": v["rel"]}


def candidates(item: dict, search_dirs) -> list[Path]:
    """Fichiers du même nom dans des dossiers indiqués par l'utilisateur (aucun balayage global)."""
    name = Path(item.get("path") or item.get("rel") or "").name
    if not name:
        return []
    out = []
    for d in search_dirs:
        p = Path(d) / name
        if p.is_file():
            out.append(p)
    return out


def describe(item: dict) -> str:
    """Ligne d'information : rôle, durée, fréquence, canaux, révision."""
    parts = [item.get("role") or "son"]
    d = float(item.get("duration") or 0)
    if d > 0:
        parts.append(f"{int(d // 60)}:{d % 60:04.1f}")
    if item.get("sample_rate"):
        parts.append(f"{item['sample_rate'] / 1000:g} kHz")
    if item.get("channels"):
        parts.append("mono" if item["channels"] == 1 else f"{item['channels']} can.")
    if item.get("revision"):
        parts.append(f"r{item['revision']}")
    return " · ".join(parts)
