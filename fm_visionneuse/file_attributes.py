"""Attributs des fichiers (demande de l'utilisateur, base du systeme de filtres des images / videos) : pour tout
fichier qui a un apercu (jamais un dossier) — note de 0 a 5, une des 5 couleurs de Reglages > Visionneuse >
Filtres, mots cles et drapeau « neutre / marquée / rejetée ».

Rangement : un fichier cache par dossier, `.pipeline_attributes.json` (comme `.pipeline_layout.json`),
`{nom du fichier: {attribut: valeur}}` — seules les valeurs non vides sont ecrites. Cache memoire par dossier
(relu si le fichier a change sur le disque : synchro, autre poste)."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from config import DATA_DIR, PREVIEWABLE_EXTENSIONS
from previews import _clear_hidden, _set_hidden

FILENAME = ".pipeline_attributes.json"
COLOR_COUNT = 5
STATUS_KEEP, STATUS_DELETE = "keep", "delete"
DEFAULTS = {"rating": 0, "color": 0, "keywords": [], "status": ""}

_CACHE: dict[str, tuple[float, dict]] = {}       # dossier -> (date du fichier, contenu)
# Mots cles deja employes (propose a la saisie, avec autocompletion) : {mot: nombre d'emplois}. Fichier de
# l'appli (ignore par git) ; les tests le redirigent (tests/_isolate.py, variable d'environnement).
KEYWORDS_PATH = Path(os.environ.get("PIPELINE_KEYWORDS_FILE") or (DATA_DIR / "file_keywords.json"))
# Images d'une planche PureRef (fichiers du cache de l'appli, voir pipeline_browser._remember_pur) : leurs
# attributs sont ceux de la PLANCHE, ranges dans le dossier du .pur sous « planche.pur/<image> ».
_ALIASES: dict[str, tuple[Path, str]] = {}


def set_alias(path: Path, folder: Path, key: str):
    """`path` (fichier interne de l'appli) range ses attributs dans `folder`, sous le nom `key`."""
    _ALIASES[os.path.normcase(str(path))] = (Path(folder), key)


def location(path: Path) -> tuple[Path, str]:
    """(dossier, nom) sous lesquels les attributs de `path` sont ranges."""
    return _ALIASES.get(os.path.normcase(str(path))) or (path.parent, path.name)


def eligible(path: Path | None) -> bool:
    """Un fichier A APERCU (images, videos, scenes 3D...), jamais un dossier ni un fichier interne de l'appli
    (images extraites des planches PureRef, caches)."""
    if path is None or path.suffix.lower() not in PREVIEWABLE_EXTENSIONS:
        return False
    if os.path.normcase(str(path)) in _ALIASES:
        return True                               # image d'une planche PureRef
    try:
        path.resolve().relative_to(DATA_DIR.resolve())
        return False
    except (ValueError, OSError):
        pass
    return not path.is_dir()


def _store(directory: Path) -> Path:
    return directory / FILENAME


_CHECKED: dict[str, float] = {}                  # dossier -> instant du dernier controle sur le disque


def _load_dir(directory, max_age: float = 0.0) -> dict:
    """Attributs ranges dans `directory`. `max_age` : un controle sur le disque datant de moins de
    `max_age` s suffit (filtres : des milliers de dossiers a chaque changement de critere)."""
    key = str(directory)
    if max_age:
        checked = _CHECKED.get(key)
        if checked is not None and time.monotonic() - checked < max_age:
            hit = _CACHE.get(key)
            return hit[1] if hit is not None else {}
    _CHECKED[key] = time.monotonic()
    path = os.path.join(key, FILENAME)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        _CACHE.pop(key, None)
        return {}
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    _CACHE[key] = (mtime, data)
    return data


def _clean(values: dict) -> dict:
    """Valeurs normalisees ; seules les non vides sont gardees."""
    out = {}
    rating = int(values.get("rating") or 0)
    if 1 <= rating <= 5:
        out["rating"] = rating
    color = int(values.get("color") or 0)
    if 1 <= color <= COLOR_COUNT:
        out["color"] = color
    keywords = [k.strip() for k in values.get("keywords") or [] if isinstance(k, str) and k.strip()]
    if keywords:
        out["keywords"] = list(dict.fromkeys(keywords))
    if values.get("status") in (STATUS_KEEP, STATUS_DELETE):
        out["status"] = values["status"]
    return out


def values_of(own: dict | None) -> dict:
    """Attributs complets (valeurs par defaut comprises) a partir de ce qui est range pour un fichier."""
    clean = _clean(own if isinstance(own, dict) else {})
    return {**DEFAULTS, **clean, "keywords": list(clean.get("keywords", []))}


def get(path: Path) -> dict:
    """Attributs de `path` (toutes les cles, valeurs par defaut comprises)."""
    try:
        import lightroom_bridge
        if lightroom_bridge.is_managed(Path(path)):
            return values_of(lightroom_bridge.attributes(Path(path)) or {})
    except (ImportError, OSError, ValueError, sqlite3.Error):
        return values_of({})
    folder, key = location(path)
    return values_of(_load_dir(folder).get(key))


def update(path: Path, **changes) -> dict:
    """Change des attributs de `path` et les enregistre aussitot ; retourne ses attributs."""
    try:
        import lightroom_bridge
        if lightroom_bridge.is_managed(Path(path)):
            lightroom_bridge.write_attributes(Path(path), changes)
            return get(path)                 # Lightroom reste la source de vérité.
    except (ImportError, OSError, ValueError):
        return get(path)
    directory, key = location(path)
    data = dict(_load_dir(directory))
    before = {k.casefold() for k in get(path)["keywords"]}
    values = _clean({**get(path), **changes})
    _remember_keywords([k for k in values.get("keywords", []) if k.casefold() not in before])
    if values:
        data[key] = values
    else:
        data.pop(key, None)
    store = _store(directory)
    try:
        if data:
            _clear_hidden(store)
            temp = store.with_name(store.name + ".tmp")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, store)
            _set_hidden(store)
        elif store.exists():
            _clear_hidden(store)
            store.unlink()
    except OSError:
        return get(path)
    _CACHE.pop(str(directory), None)
    _CHECKED.pop(str(directory), None)
    return get(path)


def known_keywords() -> list[str]:
    """Mots cles deja employes, les plus frequents d'abord (puis par nom), plus ceux des dossiers deja lus
    dans la session."""
    counts = dict(_read_known())
    for _mtime, data in list(_CACHE.values()):
        for values in data.values():
            for word in (values or {}).get("keywords") or [] if isinstance(values, dict) else []:
                if isinstance(word, str) and word.strip():
                    counts.setdefault(word.strip(), 0)
    merged: dict = {}
    for word, count in counts.items():
        key = word.casefold()
        if key not in merged or count > merged[key][1]:
            merged[key] = (word, max(count, merged.get(key, ("", 0))[1]))
    return [w for w, _c in sorted(merged.values(), key=lambda wc: (-wc[1], wc[0].casefold()))]


def _read_known() -> dict:
    try:
        data = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _remember_keywords(words: list[str]):
    """Mots cles NOUVEAUX sur un fichier : comptes dans le registre (ecriture par fichier temporaire)."""
    if not words:
        return
    counts = _read_known()
    lowered = {k.casefold(): k for k in counts}
    for word in words:
        key = lowered.get(word.casefold(), word)
        counts[key] = counts.get(key, 0) + 1
    try:
        KEYWORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = KEYWORDS_PATH.with_name(KEYWORDS_PATH.name + ".tmp")
        temp.write_text(json.dumps(counts, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, KEYWORDS_PATH)
    except OSError:
        pass


def parse_keywords(text: str) -> list[str]:
    """« ciel nuit, ville ; mer » -> ["ciel", "nuit", "ville", "mer"] (espaces, virgules, points-virgules)."""
    return text.replace(";", " ").replace(",", " ").split()
