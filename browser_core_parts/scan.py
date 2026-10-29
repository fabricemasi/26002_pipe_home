"""Lecture des dossiers, caches de métadonnées et de configuration. Carte : docs/agents/colonnes.md."""

import os
import time
import threading
from pathlib import Path
from config import FLATTEN_FOLDERS, HIDDEN_PREFIXES
from config import GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS, GLOBAL_OMIT_FILE_NAMES

# ==========================================================================
# Scan disque
# ==========================================================================

def _is_globally_omitted_file(name: str) -> bool:
    lowered = name.casefold()
    return lowered in GLOBAL_OMIT_FILE_NAMES or any(
        lowered.endswith("." + extension) for extension in GLOBAL_OMIT_FILE_EXTENSIONS
    )

def _is_globally_omitted_dir(name: str) -> bool:
    return name.casefold() in GLOBAL_OMIT_DIR_NAMES

def _is_globally_omitted_path(path: Path) -> bool:
    if path.is_dir() and _is_globally_omitted_dir(path.name):
        return True
    if path.is_file() and _is_globally_omitted_file(path.name):
        return True
    return any(_is_globally_omitted_dir(parent.name) for parent in path.parents)

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return ""

# Type et taille de chaque element lu par list_entries : `os.scandir` les donne avec le nom (sous Windows, sans
# aucun acces de plus). Column.refresh les reprend au lieu de refaire `is_dir()` / `stat()` par ligne — sur un
# partage reseau, chacun etait un aller-retour (dossier de 200 elements : plusieurs secondes figees).
_ENTRY_INFO: dict[str, tuple[bool, int | None, float | None]] = {}

_LISTED_COUNT: dict[str, tuple[float, int]] = {}      # dossier -> (instant, nombre d'elements de sa lecture)

_DIR_CHILDREN: dict[str, dict[str, Path]] = {}       # sous-dossiers, statuts compris

def _remote_gui(path) -> bool:
    from previews import is_remote_path
    return threading.current_thread() is threading.main_thread() and is_remote_path(path)

def _request_directory(directory):
    """Revalidation partagée, sans stat réseau préalable sur le fil Qt."""
    from column_loading import loader
    service = loader()
    directories = [Path(directory)]
    key = service.key(directories, None)
    data = service.cached(key)
    if data is None or time.monotonic() - data.stamp >= service.FRESH_S:
        service.request(key, directories, None, service)

def remember_entry(path, is_dir: bool, size: int | None = None, mtime: float | None = None) -> None:
    if len(_ENTRY_INFO) > 200_000:
        _ENTRY_INFO.clear()
    _ENTRY_INFO[str(path)] = (bool(is_dir), size, mtime)

def entry_mtime(path) -> float | None:
    """Date de modification, reprise de la lecture de son dossier quand elle est connue (sinon `stat`)."""
    info = _ENTRY_INFO.get(str(path))
    if info is not None and info[2] is not None:
        return info[2]
    if _remote_gui(path):
        _request_directory(Path(path).parent)
        return None
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None

def listed_count(directory, max_age: float = 5.0) -> int | None:
    """Nombre d'elements de la derniere lecture de `directory` par list_entries (si recente), sinon None."""
    hit = _LISTED_COUNT.get(os.path.normcase(str(directory)))
    if hit is not None and time.monotonic() - hit[0] < max_age:
        return hit[1]
    return None

def entry_is_dir(path) -> bool:
    """`path.is_dir()`, repris de la derniere lecture de son dossier quand elle est connue."""
    info = _ENTRY_INFO.get(str(path))
    if info is not None:
        return info[0]
    if _remote_gui(path):
        _request_directory(Path(path).parent)
        return False
    return Path(path).is_dir()

def entry_size(path) -> int | None:
    """Taille d'un fichier, reprise de la lecture de son dossier quand elle est connue (sinon `stat`)."""
    info = _ENTRY_INFO.get(str(path))
    if info is not None and info[1] is not None:
        return info[1]
    if _remote_gui(path):
        _request_directory(Path(path).parent)
        return None
    try:
        return Path(path).stat().st_size
    except OSError:
        return None

# Fichiers de configuration caches d'un dossier (.pipeline_layout.json, .pipeline_shortcuts.json,
# .pipeline_columns.json, .pipeline_lightroom.json…) : relus a CHAQUE clic et a chaque peinture d'une ligne
# (pastille d'etapes), chaque lecture ou `stat` etant un aller-retour sur un partage reseau (~70 par clic,
# mesure). La lecture du dossier (`list_entries`) les voit passer avec leur date et leur taille (donnees de
# `os.scandir`, gratuites sous Windows) : tant que cette lecture est recente, un fichier absent n'est pas
# cherche et un contenu deja lu est repris s'il a la meme date et la meme taille. Nos propres ecritures
# oublient l'etat du dossier (`forget_config`). Hors d'une lecture recente : `stat` garde CONFIG_FRESH_S.
CONFIG_FRESH_S = 4.0

_CONFIG_REVISION = 0

_CONFIG_PREFIX = ".pipeline"

_DIR_CONFIG: dict[str, tuple[float, dict]] = {}          # dossier -> (instant, {nom: (mtime_ns, taille)})

_CONFIG_STAT: dict[str, tuple[float, tuple | None]] = {}  # fichier -> (instant, (mtime_ns, taille) | None)

_CONFIG_TEXT: dict[str, tuple[tuple, str]] = {}           # fichier -> (etat, contenu)

def _note_dir_config(directory, found: dict) -> None:
    if len(_DIR_CONFIG) > 20_000:
        _DIR_CONFIG.clear()
    _DIR_CONFIG[os.path.normcase(str(directory))] = (time.monotonic(), found)

def config_state(path) -> tuple | None:
    """(mtime_ns, taille) du fichier de configuration `path`, None s'il n'existe pas."""
    path = Path(path)
    now = time.monotonic()
    record = _DIR_CONFIG.get(os.path.normcase(str(path.parent)))
    if _remote_gui(path):
        if record is None or now - record[0] >= CONFIG_FRESH_S:
            _request_directory(path.parent)
        return record[1].get(path.name.lower()) if record else None
    if record is not None and now - record[0] < CONFIG_FRESH_S:
        return record[1].get(path.name.lower())
    key = os.path.normcase(str(path))
    hit = _CONFIG_STAT.get(key)
    if hit is not None and now - hit[0] < CONFIG_FRESH_S:
        return hit[1]
    try:
        st = os.stat(path)
        state = (st.st_mtime_ns, st.st_size)
    except OSError:
        state = None
    if len(_CONFIG_STAT) > 20_000:
        _CONFIG_STAT.clear()
    _CONFIG_STAT[key] = (now, state)
    return state

def read_config_text(path) -> str | None:
    """Contenu du fichier de configuration `path` (None s'il est absent ou illisible), relu seulement s'il a
    change (voir config_state)."""
    path = Path(path)
    state = config_state(path)
    if state is None:
        return None
    key = os.path.normcase(str(path))
    hit = _CONFIG_TEXT.get(key)
    if hit is not None and hit[0] == state:
        return hit[1]
    if _remote_gui(path):
        _request_directory(path.parent)
        return hit[1] if hit else None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(_CONFIG_TEXT) > 5_000:
        _CONFIG_TEXT.clear()
    _CONFIG_TEXT[key] = (state, text)
    return text

def forget_config(path) -> None:
    """A appeler apres avoir ecrit / supprime un fichier de configuration : etats et contenu oublies."""
    global _CONFIG_REVISION
    _CONFIG_REVISION += 1
    path = Path(path)
    key = os.path.normcase(str(path))
    _CONFIG_TEXT.pop(key, None)
    _CONFIG_STAT.pop(key, None)
    _DIR_CONFIG.pop(os.path.normcase(str(path.parent)), None)

def forget_all_config() -> None:
    global _CONFIG_REVISION
    _CONFIG_REVISION += 1
    _CONFIG_TEXT.clear()
    _CONFIG_STAT.clear()
    _DIR_CONFIG.clear()

def list_entries(directory: Path, exclude: frozenset[str] | None = None, *, strict: bool = False) -> list[Path]:
    """Dossiers puis fichiers, tries. Les FLATTEN_FOLDERS sont traverses.
    `exclude` (noms en minuscules) : entrees jamais listees, quel que soit
    leur contenu — voir STATUS_FOLDERS, exclus des colonnes Projets/
    Sous-projet (voir Column.refresh). Type et taille retenus (`entry_is_dir`, `entry_size`) ; fichiers de
    configuration du dossier retenus (voir config_state)."""
    dirs: list[Path] = []
    files: list[Path] = []
    config: dict = {}
    children = {}
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_dir() and not entry.name.startswith(HIDDEN_PREFIXES):
                    children[entry.name.lower()] = Path(entry.path)
                if entry.name.startswith(HIDDEN_PREFIXES):
                    if entry.name.startswith(_CONFIG_PREFIX):
                        try:
                            st = entry.stat()
                            config[entry.name.lower()] = (st.st_mtime_ns, st.st_size)
                        except OSError:
                            pass
                    continue
                if exclude and entry.name.lower() in exclude:
                    continue
                is_dir = entry.is_dir()
                if is_dir and _is_globally_omitted_dir(entry.name):
                    continue
                path = Path(entry.path)
                try:
                    st = entry.stat()
                    size = None if is_dir else st.st_size
                    mtime = st.st_mtime
                except OSError:
                    size = mtime = None
                remember_entry(path, is_dir, size, mtime)
                if is_dir:
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        dirs.extend(p for p in list_entries(path, strict=strict) if entry_is_dir(p))
                    else:
                        dirs.append(path)
                else:
                    if _is_globally_omitted_file(entry.name):
                        continue
                    files.append(path)
    except OSError:
        if strict:
            raise
        return []
    _note_dir_config(directory, config)
    if len(_DIR_CHILDREN) > 20_000:
        _DIR_CHILDREN.clear()
    _DIR_CHILDREN[os.path.normcase(str(directory))] = children
    if len(_LISTED_COUNT) > 20_000:
        _LISTED_COUNT.clear()
    _LISTED_COUNT[os.path.normcase(str(directory))] = (time.monotonic(), len(dirs) + len(files))
    key = lambda p: p.name.lower()
    return sorted(dirs, key=key) + sorted(files, key=key)
