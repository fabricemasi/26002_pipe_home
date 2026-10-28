"""Filtres de la planche (demande de l'utilisateur) : critères sur les attributs des fichiers
(file_attributes : note, couleur, j'aime, mots clés, statut), le type de fichier (extension), la taille,
la date de modification, et la PORTÉE du filtre :
- « local » : les fichiers de la colonne en cours ;
- « level:<n> » : tout ce qui est sous le dossier choisi au niveau n de la chaîne du set
  (Type / Projet / Sous-projet…), sous-dossiers compris ;
- « root » : tous les fichiers à aperçu de la racine.
Les images des planches PureRef déjà extraites (cache de l'appli) font partie des fichiers parcourus, rangées
à la place de leur planche (leurs attributs sont ceux de la planche, file_attributes.set_alias).

PROVENANCE (`provenance`) : d'après les dossiers au-dessus du fichier — « archives » (sous un dossier
archives), « bib » (sous un dossier bib), le NOM du sous-dossier d'un in / over / out (screenshots, rendu,
ref… ; fichier posé directement dans in / over / out : ce nom-là), « travail » (sous un dossier de logiciel
reconnu, ou softs), « autres » sinon.

Le filtre est un dict (`DEFAULT_FILTER`) ; `matches` le teste sur un fichier, `scan` parcourt un dossier
récursivement (portées larges : `scan_files` une fois par portée, sur un fil de fond, FilterScanTask ;
les critères filtrent ensuite en mémoire, `filter_entries`), `describe` donne les éléments
écrits à côté du bouton (« style code »)."""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from fm_visionneuse import file_attributes
from config import DATA_DIR, HIDDEN_PREFIXES, PREVIEWABLE_EXTENSIONS, PUR_PREVIEW_EXTENSIONS

SCOPE_LOCAL, SCOPE_ROOT = "local", "root"
STATUS_NONE = "none"                                     # « sans statut »
DATE_PERIODS = (("", "Toutes"), ("today", "Aujourd'hui"), ("7d", "7 derniers jours"),
                ("30d", "30 derniers jours"), ("year", "Cette année"))
_PERIOD_DAYS = {"7d": 7, "30d": 30}
MB = 1024 * 1024

RATING_MIN, RATING_EQ = "min", "eq"
RATING_MODES = ((RATING_MIN, "au moins"), (RATING_EQ, "égal à"))
# Precisions d'un critere, qui ne filtrent rien seules (mode de la note sans note).
MODIFIERS = ("rating_mode",)

DEFAULT_FILTER = {
    "scope": SCOPE_LOCAL, "rating": 0, "rating_mode": RATING_MIN, "color": [], "keywords": [], "status": "",
    "extensions": [], "size_min": 0, "size_max": 0, "period": "", "date_from": "", "date_to": "",
    "provenance": "",
}

PROV_WORK, PROV_BIB, PROV_ARCHIVES, PROV_OTHER = "work", "bib", "archives", "other"
PROV_IO = "io:"                                          # + nom du sous-dossier de in / over / out
PROVENANCE_FIXED = ((PROV_WORK, "Travail"), (PROV_BIB, "Bib"), (PROV_ARCHIVES, "Archives"), (PROV_OTHER, "Autres"))
_IO_FOLDERS = ("in", "over", "out")
_BIB_FOLDERS = ("bib",)
_ARCHIVE_FOLDERS = ("archives", "archive")
_WORK_FOLDERS = ("softs", "logiciels")


def _is_software_folder(name: str) -> bool:
    if name.casefold() in _WORK_FOLDERS:
        return True
    from previews import software_icon_key
    return software_icon_key(name) is not None


def provenance_of_folder(folder, root=None) -> tuple[str, str]:
    """(cle, libelle) de provenance d'un fichier pose dans `folder` (voir l'entete du module). Chaines
    seulement (appele pour chaque dossier d'une portee : des dizaines de milliers de fichiers)."""
    text = os.path.normpath(str(folder))
    if root is not None:
        base = os.path.normpath(str(root))
        if os.path.normcase(text).startswith(os.path.normcase(base) + os.sep):
            text = text[len(base) + 1:]
    parts = [p for p in text.split(os.sep) if p]
    names = [p.casefold() for p in parts]
    if any(n in _ARCHIVE_FOLDERS for n in names):
        return PROV_ARCHIVES, "archives"
    if any(n in _BIB_FOLDERS for n in names):
        return PROV_BIB, "bib"
    for i in range(len(names) - 1, -1, -1):
        if names[i] in _IO_FOLDERS:
            label = parts[i + 1] if i + 1 < len(parts) else parts[i]
            return PROV_IO + label.casefold(), label
    if any(_is_software_folder(p) for p in parts):
        return PROV_WORK, "travail"
    return PROV_OTHER, "autres"


def provenance(path: Path, root: Path | None = None) -> tuple[str, str]:
    """(cle, libelle) de provenance de `path` ; image d'une planche PureRef : celle de la planche."""
    folder, _key = file_attributes.location(Path(path))
    return provenance_of_folder(Path(folder), root)


def provenance_choices(entries, root: Path | None = None) -> list[tuple[str, str]]:
    """Provenances proposees : les fixes, puis les sous-dossiers de in / over / out rencontres dans
    `entries` (chemins ou (chemin, ...)), par nom."""
    seen: dict = {}
    folders: dict = {}
    for entry in entries:
        path = Path(entry if isinstance(entry, (str, Path)) else entry[0])
        folder = file_attributes.location(path)[0]
        if str(folder) in folders:
            continue
        folders[str(folder)] = True
        key, label = provenance_of_folder(Path(folder), root)
        if key.startswith(PROV_IO):
            seen.setdefault(key, label)
    return list(PROVENANCE_FIXED) + sorted(seen.items(), key=lambda kv: kv[1].casefold())


def normalized(spec: dict | None) -> dict:
    out = dict(DEFAULT_FILTER)
    out.update({k: v for k, v in (spec or {}).items() if k in DEFAULT_FILTER})
    out["extensions"] = [e.strip().lstrip(".").lower() for e in out["extensions"] or [] if e.strip().lstrip(".")]
    out["keywords"] = [k.strip() for k in out["keywords"] or [] if k.strip()]
    for key in ("rating", "size_min", "size_max"):
        out[key] = max(0, int(out[key] or 0))
    if out["rating_mode"] not in dict(RATING_MODES):
        out["rating_mode"] = RATING_MIN
    # Couleurs : plusieurs possibles (une seule = ancien format, un entier).
    colors = out["color"]
    colors = [colors] if isinstance(colors, int) else list(colors or [])
    out["color"] = sorted({int(c) for c in colors if int(c or 0) > 0})
    out["provenance"] = str(out["provenance"] or "")
    return out


def criteria_active(spec: dict | None) -> bool:
    """Au moins un critère qui écarte des fichiers (la portée seule n'en est pas un)."""
    s = normalized(spec)
    return any(s[k] != DEFAULT_FILTER[k] for k in DEFAULT_FILTER if k != "scope" and k not in MODIFIERS)


def is_active(spec: dict | None) -> bool:
    """Le filtre change la planche : un critère, ou une portée plus large que la colonne."""
    s = normalized(spec)
    return criteria_active(s) or s["scope"] != SCOPE_LOCAL


def parse_extensions(text: str) -> list[str]:
    return [e.strip().lstrip(".").lower() for e in text.replace(";", ",").replace(" ", ",").split(",")
            if e.strip().lstrip(".")]


def parse_date(text: str) -> float | None:
    """« 31/12/2026 », « 31-12-2026 », « 2026-12-31 » -> horodatage du début du jour ; sinon None."""
    text = (text or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


def _date_bounds(spec: dict, now: float | None = None) -> tuple:
    """(début, fin) en horodatages (None = pas de borne)."""
    now = time.time() if now is None else now
    low = high = None
    period = spec["period"]
    if period == "today":
        low = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    elif period == "year":
        low = datetime.fromtimestamp(now).replace(month=1, day=1, hour=0, minute=0, second=0,
                                                  microsecond=0).timestamp()
    elif period in _PERIOD_DAYS:
        low = now - _PERIOD_DAYS[period] * 86400
    start = parse_date(spec["date_from"])
    if start is not None:
        low = start if low is None else max(low, start)
    end = parse_date(spec["date_to"])
    if end is not None:
        end += 86400                                    # jour compris
        high = end
    return low, high


def needs_stat(spec: dict) -> bool:
    s = normalized(spec)
    return bool(s["size_min"] or s["size_max"] or s["period"] or s["date_from"] or s["date_to"])


def needs_attributes(spec: dict) -> bool:
    s = normalized(spec)
    return bool(s["rating"] or s["color"] or s["keywords"] or s["status"])


def matches(path: Path, spec: dict, size: int | None = None, mtime: float | None = None,
            _bounds: tuple | None = None, _attrs: dict | None = None) -> bool:
    """`path` passe-t-il le filtre ? `size` / `mtime` : deja connus (parcours), sinon lus au besoin."""
    s = spec if _bounds is not None else normalized(spec)
    if s["extensions"] and path.suffix.lower().lstrip(".") not in s["extensions"]:
        return False
    if _bounds is None and s["provenance"] and provenance(path)[0] != s["provenance"]:
        return False
    if needs_attributes(s):
        values = _attrs if _attrs is not None else file_attributes.get(path)
        if not _attrs_pass(s, values):
            return False
    if needs_stat(s):
        if size is None or mtime is None:
            try:
                st = path.stat()
            except OSError:
                return False
            size, mtime = st.st_size, st.st_mtime
        if s["size_min"] and size < s["size_min"] * MB:
            return False
        if s["size_max"] and size > s["size_max"] * MB:
            return False
        low, high = _bounds if _bounds is not None else _date_bounds(s)
        if low is not None and mtime < low:
            return False
        if high is not None and mtime >= high:
            return False
    return True


def filter_entries(entries, spec: dict, root: Path | None = None) -> list[Path]:
    """`entries` : chemins, ou (chemin, taille, date[, planche]) d'un parcours (scan_files). Une portee large
    compte des dizaines de milliers de fichiers et chaque changement de critere refiltre tout : chaines
    seulement, attributs et provenance lus une fois par dossier (attributs : controle disque de moins de 2 s
    suffisant). `root` : racine, borne de la provenance."""
    s = normalized(spec)
    bounds = _date_bounds(s)
    low, high = bounds
    with_attrs = needs_attributes(s)
    with_stat = needs_stat(s)
    wanted = s["provenance"]
    extensions = {"." + e for e in s["extensions"]}
    size_min, size_max = s["size_min"] * MB, s["size_max"] * MB
    bare_pass = _attrs_pass(s, file_attributes.DEFAULTS)     # fichier sans attribut (« sans statut »)
    per_dir: dict = {}
    origins: dict = {}
    aliases = file_attributes._ALIASES
    normcase, sep = os.path.normcase, os.sep
    # Seules les images des planches PureRef (cache de l'appli, dans data/) ont un alias.
    data_prefix = os.path.normcase(str(DATA_DIR))
    prefix_len = len(data_prefix)
    out = []
    for entry in entries:
        path, size, mtime = (entry, None, None) if isinstance(entry, (str, Path)) else entry[:3]
        text = str(path)
        if extensions and os.path.splitext(text)[1].lower() not in extensions:
            continue
        if wanted or with_attrs:
            alias = (aliases.get(normcase(text))
                     if aliases and text[:prefix_len].lower() == data_prefix else None)
            if alias is not None:
                folder, name = str(alias[0]), alias[1]
            else:
                folder, _sep, name = text.rpartition(sep)
                if not _sep:
                    folder, name = os.path.split(text)
            if wanted:
                origin = origins.get(folder)
                if origin is None:
                    origin = origins[folder] = provenance_of_folder(folder, root)[0]
                if origin != wanted:
                    continue
            if with_attrs:
                try:
                    import lightroom_bridge
                    managed = lightroom_bridge.is_managed(Path(path))
                except (ImportError, OSError, ValueError):
                    managed = False
                if managed:
                    values = file_attributes.get(Path(path))
                    passes = _attrs_pass(s, values)
                else:
                    stored = per_dir.get(folder)
                    if stored is None:
                        stored = per_dir[folder] = file_attributes._load_dir(folder, max_age=2.0)
                    own = stored.get(name)
                    passes = bare_pass if own is None else _attrs_pass(s, file_attributes.values_of(own))
                if not passes:
                    continue
        if with_stat:
            if size is None or mtime is None:
                try:
                    st = os.stat(text)
                except OSError:
                    continue
                size, mtime = st.st_size, st.st_mtime
            if (size_min and size < size_min) or (size_max and size > size_max):
                continue
            if (low is not None and mtime < low) or (high is not None and mtime >= high):
                continue
        out.append(path if isinstance(path, Path) else Path(path))
    return out


def _attrs_pass(s: dict, values: dict) -> bool:
    if s["rating"] and (values["rating"] != s["rating"] if s["rating_mode"] == RATING_EQ
                        else values["rating"] < s["rating"]):
        return False
    if s["color"] and values["color"] not in s["color"]:          # une des couleurs choisies
        return False
    if s["status"]:
        if values["status"] != ("" if s["status"] == STATUS_NONE else s["status"]):
            return False
    if s["keywords"]:
        own = [k.casefold() for k in values["keywords"]]
        if not all(any(word.casefold() in k for k in own) for word in s["keywords"]):
            return False
    return True


def filter_paths(paths: list, spec: dict) -> list:
    return filter_entries(paths, spec)


def _omitted_dir(name: str) -> bool:
    from browser_core import _is_globally_omitted_dir
    return _is_globally_omitted_dir(name)


def _pur_entries(pur: Path, size: int, mtime: float) -> list[tuple]:
    """Images d'une planche PureRef deja extraites (cache) : (image, taille, date de la planche, (planche,
    date)) ; leurs attributs sont ceux de la planche. Pas encore extraites : rien (aucune extraction ici)."""
    from preview_column import pur_image_files
    try:
        files = pur_image_files(pur, mtime)
    except OSError:
        files = None
    out = []
    for image in files or []:
        image = Path(image)
        file_attributes.set_alias(image, pur.parent, f"{pur.name}/{image.name}")
        try:
            image_size = image.stat().st_size
        except OSError:
            image_size = 0
        out.append((image, image_size, mtime, (pur, mtime)))
    return out


def scan_files(folder: Path, cancelled=lambda: False) -> list[tuple]:
    """(chemin, taille, date) de tous les fichiers a apercu sous `folder` (sous-dossiers compris, ni caches
    ni omis ni internes a l'appli), dossier par dossier, par nom ; une planche PureRef deja extraite est
    remplacee par ses images (4e element : (planche, date)). `cancelled()` vrai : arret (None)."""
    data_dir = os.path.normcase(str(DATA_DIR.resolve()))
    out: list[tuple] = []
    stack = [str(folder)]
    while stack:
        if cancelled():
            return None
        current = stack.pop()
        if os.path.normcase(current) == data_dir:
            continue
        files, dirs = [], []
        try:
            with os.scandir(current) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith(HIDDEN_PREFIXES):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not _omitted_dir(name):
                                dirs.append(entry.path)
                        elif os.path.splitext(name)[1].lower() in PREVIEWABLE_EXTENSIONS:
                            st = entry.stat()
                            files.append((entry.name.casefold(), Path(entry.path), st.st_size, st.st_mtime))
                        elif os.path.splitext(name)[1].lower() in PUR_PREVIEW_EXTENSIONS:
                            st = entry.stat()
                            files.append((entry.name.casefold(), Path(entry.path), st.st_size, st.st_mtime, "pur"))
                    except OSError:
                        continue
        except OSError:
            continue
        files.sort(key=lambda f: f[0])
        for f in files:
            if len(f) == 5:
                out.extend(_pur_entries(f[1], f[2], f[3]))
            else:
                out.append(f[1:])
        stack.extend(sorted(dirs, key=lambda d: os.path.basename(d).casefold(), reverse=True))
    return out


def scan(folder: Path, spec: dict) -> list[Path]:
    """Fichiers sous `folder` qui passent le filtre (parcours + filtrage, en une fois)."""
    return filter_entries(scan_files(folder) or [], spec)


_POOL = None


def pool() -> QThreadPool:
    """File des parcours de portees larges : un seul a la fois (le dernier demande)."""
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(1)
    return _POOL


class _ScanSignals(QObject):
    finished = Signal(str, object)                     # (dossier, [(chemin, taille, date)])


class FilterScanTask(QRunnable):
    """Parcours d'une portee large sur un fil de fond (la racine entiere peut etre longue)."""

    def __init__(self, folder: Path):
        super().__init__()
        self.setAutoDelete(True)
        self.folder = folder
        self.cancel = False
        self.signals = _ScanSignals()

    def run(self):
        result = scan_files(self.folder, lambda: self.cancel)
        if result is not None and not self.cancel:
            self.signals.finished.emit(str(self.folder), result)


def _size_text(mb: int) -> str:
    return f"{mb / 1024:g} Go" if mb >= 1024 and mb % 1024 == 0 else f"{mb} Mo"


def describe(spec: dict, color_names: list[str] | None = None, scope_label: str = "") -> list[str]:
    """Éléments du filtre, écrits à côté du bouton (dans l'ordre de la fenêtre)."""
    s = normalized(spec)
    out = []
    if s["scope"] != SCOPE_LOCAL and scope_label:
        out.append(scope_label)
    if s["rating"]:
        exact = s["rating_mode"] == RATING_EQ
        out.append(("= " if exact else "") + "★" * s["rating"] + ("+" if not exact and s["rating"] < 5 else ""))
    if s["color"]:
        names = color_names or []
        out.append(" / ".join(names[c - 1] if c - 1 < len(names) and names[c - 1] else f"couleur {c}"
                              for c in s["color"]))
    out.extend(f"#{k}" for k in s["keywords"])
    if s["status"]:
        out.append({"keep": "marquée", "delete": "rejetée", STATUS_NONE: "neutre"}[s["status"]])
    if s["extensions"]:
        out.append(" ".join(f".{e}" for e in s["extensions"]))
    if s["size_min"] and s["size_max"]:
        out.append(f"{_size_text(s['size_min'])}–{_size_text(s['size_max'])}")
    elif s["size_min"]:
        out.append(f"≥ {_size_text(s['size_min'])}")
    elif s["size_max"]:
        out.append(f"≤ {_size_text(s['size_max'])}")
    if s["provenance"]:
        prov = s["provenance"]
        out.append(prov[len(PROV_IO):] if prov.startswith(PROV_IO)
                   else dict(PROVENANCE_FIXED).get(prov, prov).lower())
    if s["period"]:
        out.append(dict(DATE_PERIODS)[s["period"]].lower())
    if s["date_from"] and s["date_to"]:
        out.append(f"{s['date_from']} → {s['date_to']}")
    elif s["date_from"]:
        out.append(f"depuis {s['date_from']}")
    elif s["date_to"]:
        out.append(f"jusqu'au {s['date_to']}")
    return out

