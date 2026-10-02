"""Aperçus : décodeurs par format, caches mémoire/disque, rendus Blender/Maya et ordonnanceur en tâche de fond."""

import ctypes
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QEventLoop, QObject, QPointF, QRunnable, QSize, Qt, QThreadPool, QTimer,
    QUrl, Signal,
)
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHeaderView,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

# Dependances optionnelles (voir requirements.txt) : import protege pour
# qu'une install sans ces paquets perde juste les apercus concernes, sans
# empecher l'appli de demarrer. numpy sert au rasteriseur des .obj
# (voir _rasterize_obj_numpy) ET, avec OpenEXR, au decodage des .exr (voir
# _decode_exr_image) — verifie separement, un .obj lisse ne doit pas
# dependre de la presence d'OpenEXR.
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
try:
    import OpenEXR
    _OPENEXR_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _OPENEXR_AVAILABLE = False

from app_style import (
    custom_softwares,
    removed_softwares,
)
from config import (
    ABC_EXTENSIONS,
    BLEND_EXTENSIONS,
    CUSTOM_SOFTWARE_ICON_DIR,
    DATA_DIR,
    DWG_EXTENSIONS,
    EXR_EXTENSIONS,
    FBX_EXTENSIONS,
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
    HDR_EXTENSIONS,
    MAYA_SCENE_EXTENSIONS,
    OBJ_EXTENSIONS,
    PSD_EXTENSIONS,
    RENDERABLE_3D_EXTENSIONS,
    TWO_D_IMAGE_EXTENSIONS,
    TX_EXTENSIONS,
    VIDEO_EXTENSIONS,
    _DWG_RENDER_LOCK,
    _FILE_ATTRIBUTE_HIDDEN,
    _STALE_PREVIEW_PATHS,
)



def _set_hidden(path: Path) -> None:
    """Marque `path` (fichier ou dossier) cache pour l'explorateur Windows.
    Le prefixe "." (convention Unix) ne suffit pas sur Windows : sans cet
    attribut, les vignettes/caches generes par l'appli (.thumbnail.png dans
    les dossiers de projet, .pipeline_preview_cache, .pipeline_software_icons)
    restaient visibles au milieu des vrais fichiers. No-op silencieux hors
    Windows ou en cas d'echec (ex: fichier verrouille)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), _FILE_ATTRIBUTE_HIDDEN)
    except (AttributeError, OSError):
        pass


_FILE_ATTRIBUTE_NORMAL = 0x80


def _clear_hidden(path: Path) -> None:
    """Retire l'attribut cache (voir _set_hidden) juste AVANT de RE-ECRIRE
    un fichier deja marque cache lors d'un enregistrement precedent (ex.
    .pipeline_columns.json/.thumbnail.png reecrits a chaque modification) —
    sur Windows, ouvrir en ecriture/troncature (voir Path.write_text, mode
    'w') un fichier EXISTANT ne portant QUE l'attribut HIDDEN echoue avec
    PermissionError (confirme, reproductible a coup sur : SetFileAttributesW
    HIDDEN puis un 2e write_text() du meme fichier echouait TOUJOURS, meme
    en preservant les autres attributs existants) — voir la remarque de
    l'utilisateur, "quand j'essaie d'enregistrer une modification ... il ne
    se passe rien, il ne prend pas en compte les modifs" : c'etait
    exactement cette PermissionError, non rattrapee, qui interrompait
    silencieusement Column._open_column_config/ColumnConfigDialog._on_save
    avant self.accept(). Sans effet si `path` n'existe pas encore (rien a
    reecrire) — l'appelant doit alors re-cacher APRES coup (voir
    _set_hidden), comme avant. No-op silencieux hors Windows."""
    if sys.platform != "win32":
        return
    try:
        if path.is_file():
            ctypes.windll.kernel32.SetFileAttributesW(str(path), _FILE_ATTRIBUTE_NORMAL)
    except (AttributeError, OSError):
        pass


# nom normalise (alphanumerique, majuscules) -> (couleur de fond, couleur du texte, texte du badge)
SOFTWARE_ICONS: dict[str, tuple[str, str, str]] = {
    "HOUDINI": ("#FF4713", "#1a1109", "H"),
    "MAYA": ("#00C8FF", "#0a2733", "M"),
    "NUKE": ("#FFC700", "#1a1a1a", "N"),
    "NUKEX": ("#FFC700", "#1a1a1a", "NX"),
    "PHOTOSHOP": ("#31A8FF", "#001b33", "Ps"),
    "AFTEREFFECTS": ("#9999FF", "#00005b", "Ae"),
    "PREMIERE": ("#9999FF", "#00005b", "Pr"),
    "BLENDER": ("#EA7600", "#265787", "B"),
    "SUBSTANCEPAINTER": ("#CDF546", "#16171a", "SP"),
    "SUBSTANCEDESIGNER": ("#CDF546", "#16171a", "SD"),
    "ZBRUSH": ("#8C8C8C", "#141414", "Z"),
    "KATANA": ("#2e2e2e", "#f7941d", "K"),
    "UNREAL": ("#0e1128", "#ffffff", "UE"),
    "UNITY": ("#161616", "#ffffff", "U"),
    "3DSMAX": ("#37A6DB", "#0a2733", "3D"),
    "MAX": ("#37A6DB", "#0a2733", "3D"),
    "CINEMA4D": ("#011a6a", "#ffffff", "C4"),
    "C4D": ("#011a6a", "#ffffff", "C4"),
    "RESOLVE": ("#1a1a1a", "#ff6600", "DR"),
    "DAVINCIRESOLVE": ("#1a1a1a", "#ff6600", "DR"),
    "MARI": ("#3c3c3c", "#ffffff", "Ma"),
    "CLARISSE": ("#222222", "#ffffff", "Cl"),
    "ILLUSTRATOR": ("#ff9a00", "#1a0f00", "Ai"),
    "INDESIGN": ("#ff3366", "#2b0011", "Id"),
}

_CACHE_MAX_ENTRIES = 300


def _bounded_cache_set(cache: dict, key, value, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
    """Ecrit `value` dans `cache[key]`, puis evince les entrees les plus
    anciennes si la taille depasse `max_entries`. Sans ca, les caches
    d'images ci-dessous (indexes par chemin de fichier, jamais purges
    autrement) grossissent sans jamais redescendre pendant toute la session
    de navigation — jusqu'a plusieurs centaines de Mo sur un pipeline avec
    beaucoup d'images/projets, meme apres qu'on ait quitte ces dossiers."""
    cache.pop(key, None)  # ressort la cle en fin d'ordre d'insertion si deja presente
    cache[key] = value
    while len(cache) > max_entries:
        del cache[next(iter(cache))]


_software_icon_cache: dict[tuple[str, int], tuple[float | None, QPixmap]] = {}


def software_icon_key(name: str) -> str | None:
    """Normalise un nom de dossier (« Nuke X », « nuke_x »...) et le
    rapproche d'un logiciel connu — soit d'origine (SOFTWARE_ICONS), soit
    AJOUTE par l'utilisateur (voir Fenetre de parametres > General >
    Logiciel, "+ Ajouter un logiciel...", app_style.custom_softwares).
    None si non reconnu."""
    norm = "".join(ch for ch in name.upper() if ch.isalnum())
    if norm in removed_softwares():
        return None
    if norm in SOFTWARE_ICONS:
        return norm
    if any(e["key"] == norm for e in custom_softwares()):
        return norm
    return None


def custom_software_icon_path(key: str) -> Path:
    """Emplacement de l'icone perso d'un logiciel (globale, pas liee a un
    projet en particulier)."""
    return CUSTOM_SOFTWARE_ICON_DIR / f"{key}.png"


# Cles d'icones d'INTERFACE personnalisables (voir Settings > ICONES >
# General) — reutilisent TEL QUEL le meme mecanisme de stockage que les
# icones de logiciel (custom_software_icon_path, CUSTOM_SOFTWARE_ICON_DIR/
# {key}.png, deja generique par cle) — prefixees "ui_" pour ne jamais
# entrer en collision avec une cle de logiciel reconnu.
UI_ICON_FOLDER_DEFAULT = "ui_folder_default"
UI_ICON_FILE_DEFAULT = "ui_file_default"
UI_ICON_PIN_INACTIVE = "ui_pin_inactive"
UI_ICON_PIN_ACTIVE = "ui_pin_active"
UI_ICON_SETTINGS_GEAR = "ui_settings_gear"
UI_ICON_APP_LOGO = "ui_app_logo"
UI_ICON_COLLAPSE_TOGGLE = "ui_collapse_toggle"
UI_ICON_SHORTCUT = "ui_shortcut"

_UI_ICON_CACHE: dict[tuple[str, int], tuple[float, QPixmap]] = {}


def custom_ui_icon_pixmap(key: str, size: int) -> QPixmap | None:
    """Pixmap perso pour une icone d'INTERFACE (voir les UI_ICON_* ci-
    dessus) si l'utilisateur en a choisi une (Settings > ICONES >
    General), sinon None — l'appelant garde alors son rendu par defaut
    actuel (glyphe peint/chevrons/fichier fourni). MEME invalidation par
    mtime que software_icon_pixmap : pas de purge explicite necessaire au
    moment de l'enregistrement depuis la fenetre de parametres."""
    path = custom_software_icon_path(key)
    try:
        mtime = path.stat().st_mtime if path.is_file() else None
    except OSError:
        mtime = None
    if mtime is None:
        return None
    cache_key = (key, size)
    cached = _UI_ICON_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    loaded = QPixmap(str(path))
    if loaded.isNull():
        return None
    pix = _contain_square(loaded, size)
    _UI_ICON_CACHE[cache_key] = (mtime, pix)
    return pix


def _smooth_scale_down(pix: QPixmap, target: QSize, mode=Qt.KeepAspectRatioByExpanding) -> QPixmap:
    """Reduit `pix` vers `target` par MOITIES SUCCESSIVES (mipmap), PAS en
    un seul saut quand l'ecart est grand — voir _paint_row_image, la
    remarque de l'utilisateur, "je veux que toutes les icones soient
    parfaitement redimensionnables sans pixelisation mais avec un super
    antialiasing dans le cas ou elle serait plus petite que l'originale".
    Un seul Qt.SmoothTransformation directement d'une haute resolution
    (voir SOFTWARE_ICON_SIZE) vers une PETITE taille de ligne (ratio de
    reduction > 2x) reste un filtre bilineaire simple, qui peut aliaser/
    perdre du detail fin (traits, contours nets) — chaque division par 2
    PRE-MOYENNE reellement 4 pixels source en 1 (une vraie supersample),
    avant qu'une derniere passe (SmoothTransformation, ecart <2x
    restant) ajuste la taille EXACTE demandee sur un pas dorenavant fin."""
    while pix.width() > target.width() * 2 and pix.height() > target.height() * 2:
        pix = pix.scaled(
            max(1, pix.width() // 2), max(1, pix.height() // 2),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
    return pix.scaled(target, mode, Qt.SmoothTransformation)


def _contain_square(pix: QPixmap, size: int) -> QPixmap:
    """Redimensionne `pix` pour tenir ENTIEREMENT dans un carre `size`x`size`
    (contrairement aux apercus/vignettes, qui recadrent en "cover") :
    centree, sans rien couper, le reste transparent — voir
    software_icon_pixmap, la remarque de l'utilisateur, "contrairement aux
    apercus, l'icone, si elle n'est pas totalement carree doit apparaitre
    entiere dans l'espace reserve"."""
    scaled = _smooth_scale_down(pix, QSize(size, size), Qt.KeepAspectRatio)
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return canvas


def _cover_crop_rect(pix: QPixmap, width: int, height: int) -> QPixmap:
    """MEME principe que _cover_crop_square, mais pour un rectangle
    largeur x hauteur QUELCONQUE (pas necessairement carre) — voir
    _SquarePreviewImage.set_rect/Colonnes > Apercu > Image > Ratio, la
    remarque de l'utilisateur, "je veux une section ratio". _smooth_
    scale_down (PAS un .scaled() direct) — voir sa docstring, la remarque
    de l'utilisateur, "les apercus sont tres flous, est-il possible de
    les rendre plus nets ?" : une capture d'ecran/vignette perso est
    souvent BIEN plus haute resolution que le bloc Focus ou elle
    s'affiche, un seul saut de mise a l'echelle y perdait du detail fin."""
    width, height = max(1, width), max(1, height)
    scaled = _smooth_scale_down(pix, QSize(width, height), Qt.KeepAspectRatioByExpanding)
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 2)
    return scaled.copy(x, y, width, height)


_file_image_cache: dict[str, tuple[float, QPixmap]] = {}
_file_image_high_cache: dict[str, tuple[float, QPixmap]] = {}
_file_image_column_cache: dict[str, tuple[float, QPixmap]] = {}
_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM = 80
_FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES = 1200
_FILE_IMAGE_COLUMN_LOOKUP_MISSES: set[tuple[str, int]] = set()


def _cache_file_preview(path_key: str, mtime: float, pix: QPixmap, is_stale: bool = False) -> QPixmap:
    """Garde l'aperçu inspecteur et sa vignette de ligne dans leurs caches dédiés."""
    _bounded_cache_set(_file_image_cache, path_key, (mtime, pix))
    small = pix.scaled(_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM, _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM,
                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _bounded_cache_set(_file_image_column_cache, path_key, (mtime, small),
                       _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES)
    if is_stale:
        _STALE_PREVIEW_PATHS.add(path_key)
    else:
        _STALE_PREVIEW_PATHS.discard(path_key)
    _FILE_IMAGE_COLUMN_LOOKUP_MISSES.discard((path_key, int(mtime)))
    return pix

# Ces lignes n'affichent jamais le fichier plus grand que ~200px (voir
# file_preview_size dans settings_window.py) : decoder et garder en cache
# l'image a sa resolution d'origine (une photo/rendu peut faire plusieurs
# dizaines de Mo une fois decompressee) pour une vignette de quelques
# dizaines de px serait pur gaspillage de memoire. Marge x3 par rapport au
# reglage max pour rester net sur les ecrans HiDPI et les images non carrees.
FILE_IMAGE_CACHE_MAX_DIM = 640

# _file_image_cache ci-dessus ne vit qu'en memoire : tout redemarrage de
# l'appli (ou dossier pas encore visite dans cette session) oblige a
# redecoder et reduire chaque image depuis son fichier d'origine, potentiellement
# lourd sur un partage reseau. On garde donc en plus, sur disque, une copie
# deja reduite (voir FILE_IMAGE_CACHE_MAX_DIM) de chaque image deja vue : les
# ouvertures suivantes du meme dossier n'ont plus qu'a relire ce petit fichier
# local. Nommee par hash du chemin (independant du mtime, pour retrouver et
# purger les anciennes versions perimees d'une meme image, voir
# _prune_stale_disk_cache) suivi du mtime (pour invalider automatiquement des
# qu'un fichier source change).
FILE_IMAGE_DISK_CACHE_DIR = DATA_DIR / ".pipeline_preview_cache"

# La cle de cache disque ne depend que du chemin source et de son mtime :
# un changement du CODE de rendu (ex. _decode_obj_image) ne les fait pas
# bouger, donc un vieux rendu perime resterait sinon servi indefiniment tant
# que le fichier source lui-meme n'est pas retouche. A incrementer chaque
# fois que la logique de decodage/rendu change reellement (ex. le passage a
# un flat shading sans contour) pour forcer une regeneration.
_PREVIEW_CACHE_VERSION = 57
_TURNTABLE_CACHE_VERSION = 1
TURNTABLE_FRAME_COUNT = 72
TURNTABLE_EXTENSIONS = OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS


def _turntable_cache_path(path: Path, mtime: float, profiles_snapshot=None, render_mode: str = "low") -> Path:
    signature = _file_image_cache_signature(path, render_mode=render_mode, profiles_snapshot=profiles_snapshot)
    digest = hashlib.sha1(f"turntable:{_TURNTABLE_CACHE_VERSION}:{_PREVIEW_CACHE_VERSION}:{path.resolve()}:{mtime}:{signature}".encode()).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / ("turntable_" + digest)


def _turntable_metadata_path(path: Path, render_mode: str = "low") -> Path:
    identity = os.path.normcase(str(path.resolve()))
    digest = hashlib.sha1((identity if render_mode == "low" else f"{identity}:high").encode()).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / ("turntable_latest_" + digest + ".json")


def _turntable_work_path(destination: Path, profile: dict, render_mode: str) -> Path:
    references = {}
    for key in ("template", "lighting_hdri", "lighting"):
        if not profile.get(key):
            continue
        path = Path(__file__).resolve().parent / str(profile[key])
        try:
            stat = path.stat()
            references[key] = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
    signature = json.dumps({"version": 2, "profile": profile, "mode": render_mode, "references": references},
                           sort_keys=True, default=str)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return destination.with_name(destination.name + "_partial_" + digest)


def _turntable_frames(path: Path, mtime: float, profiles_snapshot=None, allow_stale=False,
                      render_mode: str = "low") -> list[Path]:
    directory = _turntable_cache_path(path, mtime, profiles_snapshot, render_mode)
    try:
        if not (directory / "complete.json").is_file() and allow_stale:
            directory = Path(json.loads(_turntable_metadata_path(path, render_mode).read_text(encoding="utf-8"))["cache"])
            if directory.parent.resolve() != FILE_IMAGE_DISK_CACHE_DIR.resolve():
                return []
        manifest = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        if manifest.get("frames") != TURNTABLE_FRAME_COUNT:
            return []
        frames = [directory / f"frame_{i:03d}.png" for i in range(TURNTABLE_FRAME_COUNT)]
        return frames if all(frame.is_file() for frame in frames) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []

# Evite de rescanner le cache disque a chaque repaint d'une ligne sans apercu.
# La cle inclut le mtime : une modification du fichier force une nouvelle recherche.
_PREVIEW_STALE_LOOKUP_MISSES: set[tuple[str, int]] = set()
_PREVIEW_CACHE_HAS_PNG: bool | None = None
_PREVIEW_PROTECTION_FILE = DATA_DIR / ".pipeline_protected_previews.json"
_PROTECTED_PREVIEW_PATHS: set[str] | None = None


def _protected_preview_paths() -> set[str]:
    global _PROTECTED_PREVIEW_PATHS
    if _PROTECTED_PREVIEW_PATHS is None:
        try:
            payload = json.loads(_PREVIEW_PROTECTION_FILE.read_text(encoding="utf-8"))
            _PROTECTED_PREVIEW_PATHS = {
                os.path.normcase(str(Path(value).resolve()))
                for value in payload
                if isinstance(value, str)
            }
        except (OSError, ValueError, TypeError):
            _PROTECTED_PREVIEW_PATHS = set()
    return _PROTECTED_PREVIEW_PATHS


def _is_preview_protected(path: Path) -> bool:
    return os.path.normcase(str(path.resolve())) in _protected_preview_paths()


def _set_preview_protected(path: Path, protected: bool) -> None:
    paths = _protected_preview_paths()
    key = os.path.normcase(str(path.resolve()))
    if protected:
        paths.add(key)
    else:
        paths.discard(key)
    try:
        temp_path = _PREVIEW_PROTECTION_FILE.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(sorted(paths), indent=2), encoding="utf-8")
        temp_path.replace(_PREVIEW_PROTECTION_FILE)
    except OSError:
        pass


def _file_image_cache_signature(
    path: Path, render_mode: str = "low", profiles_snapshot: dict | None = None,
) -> str:
    template_signature = ""
    suffix = path.suffix.lower()
    renderable_3d = OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS
    if suffix in renderable_3d:
        profiles = profiles_snapshot if profiles_snapshot is not None else _RENDER_PROFILES
        profile_name = "HIGH POLY" if render_mode == "high" else "LOW POLY"
        profile = profiles.get(profile_name, {})
        template_name = str(profile.get("template", "scene pour appercu.blend"))
        template_path = Path(__file__).resolve().parent / "files" / template_name
        try:
            template_stat = template_path.stat()
            template_signature = f":{template_stat.st_mtime_ns}:{template_stat.st_size}"
        except OSError:
            pass
        profile_digest = hashlib.sha1(
            json.dumps(profile, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
        template_signature += f":profile_render_v2:{render_mode}:{profile_digest}"
    return template_signature


def _file_image_cache_path(
    path: Path, mtime: float, version: int | None = None, signature: str | None = None,
    render_mode: str = "low", profiles_snapshot: dict | None = None,
) -> Path:
    if version is None:
        version = _PREVIEW_CACHE_VERSION
    if signature is None:
        signature = _file_image_cache_signature(path, render_mode, profiles_snapshot)
    digest = hashlib.sha1(f"{version}:{path}{signature}".encode("utf-8")).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"{digest}_{int(mtime)}.png"


def _preview_cache_metadata_path(path: Path) -> Path:
    identity = hashlib.sha1(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"preview_{identity}.json"


def _record_preview_cache(path: Path, source_mtime: float, cache_path: Path) -> None:
    """Remember the last usable image even after its render key goes stale."""
    try:
        _PREVIEW_STALE_LOOKUP_MISSES.discard((str(path), int(source_mtime)))
        FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        metadata_path = _preview_cache_metadata_path(path)
        payload = {
            "source": os.path.normcase(str(path.resolve())),
            "source_mtime": float(source_mtime),
            "cache": str(cache_path.resolve()),
        }
        temp_path = metadata_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(metadata_path)
    except (OSError, ValueError):
        pass


def _preview_cache_metadata_matches(path: Path, cache_path: Path) -> bool:
    try:
        metadata_path = _preview_cache_metadata_path(path)
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return (
            payload.get("source") == os.path.normcase(str(path.resolve()))
            and Path(payload.get("cache", "")).resolve() == cache_path.resolve()
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _find_stale_preview_cache(path: Path, mtime: float, current_path: Path) -> Path | None:
    """Find the last cached image for this source when its render key changed."""
    try:
        metadata_path = _preview_cache_metadata_path(path)
        if metadata_path.is_file():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            stale_path = Path(payload.get("cache", ""))
            same_source = payload.get("source") == os.path.normcase(str(path.resolve()))
            if (same_source and stale_path != current_path and stale_path.parent == FILE_IMAGE_DISK_CACHE_DIR
                    and stale_path.is_file()):
                return stale_path
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    # Le cache peut ne contenir que des sidecars JSON (par exemple si les
    # anciens apercus ont ete purges). Detecter ce cas une seule fois evite
    # alors toute la recherche de migration pour chaque fichier affiche.
    global _PREVIEW_CACHE_HAS_PNG
    if _PREVIEW_CACHE_HAS_PNG is None:
        try:
            _PREVIEW_CACHE_HAS_PNG = next(FILE_IMAGE_DISK_CACHE_DIR.glob("*.png"), None) is not None
        except OSError:
            _PREVIEW_CACHE_HAS_PNG = False
    if not _PREVIEW_CACHE_HAS_PNG:
        return None

    # Migrate legacy cache files created before the metadata sidecar existed.
    # These candidates cover earlier preview revisions without guessing from
    # unrelated PNG files in the shared cache directory.
    suffix = path.suffix.lower()
    signatures = [_file_image_cache_signature(path)]
    if suffix in MAYA_SCENE_EXTENSIONS:
        template_base = signatures[0].split(":maya_", 1)[0]
        signatures.extend(template_base + ":" + value for value in (
            "maya_ascii_join_apply_all_transforms_before_bbox_scale_v8",
            "maya_ascii_join_weld_before_bbox_transform_v7",
            "maya_ascii_join_weld_before_bbox_transform_v6",
            "maya_ascii_join_before_bbox_transform_v5",
            "maya_ascii_binary_join_before_bbox_transform_v4",
            "maya_ascii_binary_collective_bbox_transform_v3",
            "maya_ascii_binary_manual_idle_escaped_paths_v2",
        ))
    digests = set()
    # Les anciennes revisions n'ont pas de sidecar et doivent etre migrees
    # occasionnellement. Ne pas parcourir toute l'histoire du cache a chaque
    # ligne visible : cela faisait des centaines de glob() synchrones, surtout
    # couteux sur les dossiers Maya sans rendu existant. Les revisions recentes
    # couvrent les formats de cache encore susceptibles d'etre presents.
    first_version = max(1, _PREVIEW_CACHE_VERSION - 8)
    for old_version in range(first_version, _PREVIEW_CACHE_VERSION):
        for signature in signatures:
            digests.add(hashlib.sha1(f"{old_version}:{path}{signature}".encode("utf-8")).hexdigest())
    for digest in digests:
        candidates = list(FILE_IMAGE_DISK_CACHE_DIR.glob(f"{digest}_*.png"))
        if candidates:
            candidates.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
            return candidates[0]

    # Source-only changes keep the same render digest; the old source-mtime
    # suffix remains available until a replacement is written.
    digest = current_path.stem.rsplit("_", 1)[0]
    try:
        candidates = [candidate for candidate in FILE_IMAGE_DISK_CACHE_DIR.glob(f"{digest}_*.png")
                      if candidate != current_path]
        if candidates:
            candidates.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
            return candidates[0]
    except OSError:
        pass
    return None


def _prune_stale_disk_cache(cache_path: Path) -> None:
    """Supprime les autres fichiers de cache disque de la meme image (memes
    premiers caracteres de nom, mtime different) que `cache_path`, devenus
    perimes suite a une modification du fichier source."""
    digest = cache_path.stem.split("_", 1)[0]
    try:
        for stale in FILE_IMAGE_DISK_CACHE_DIR.glob(f"{digest}_*.png"):
            if stale != cache_path:
                try:
                    stale.unlink()
                except OSError:
                    pass
    except OSError:
        pass


# Apercu des fichiers .obj : projection orthographique fixe et wireframe
# opaque, sans remplissage, shader ni occlusion ambiante. L'image est mise
# en cache comme les autres apercus apres sa premiere generation.
OBJ_PREVIEW_MAX_TRIANGLES = 150_000   # au-dela, le maillage est tronque (vignette, pas un rendu final)
OBJ_PREVIEW_RENDER_EDGES = 20_000
# Resolution dediee, plus grande que FILE_IMAGE_CACHE_MAX_DIM (640, pense
# pour des photos deja haute def qu'on reduit) : un .obj est genere par
# nos soins a une taille fixe, donc c'est SA resolution native qui
# determine la nettete a l'agrandissement (Inspecteur elargi, HiDPI...),
# pas un simple redimensionnement d'un fichier source. Supersamplee en
# interne (voir _rasterize_obj_numpy) pour lisser aussi le contour. Une
# sortie 1800 px garde les details fins lorsque l'inspecteur est agrandi.
OBJ_PREVIEW_DIM = 1105
# Multiplicateur de l'epaisseur du wireframe. La valeur 1.0 reproduit
# exactement le calcul historique (environ 1.8 px dans l'image finale).
RENDER_PARAMETERS_PATH = Path(__file__).resolve().parent / "files" / "parametres rendus.txt"


def _render_log_line(message: str) -> str:
    """Horodate une entree du journal avec l'heure locale de l'application."""
    return f"[{datetime.now():%H:%M:%S}] {message.rstrip(chr(13) + chr(10))}"


def _render_log_path(directory: Path) -> Path:
    return directory / f"pipeline_preview_render_{datetime.now():%Y-%m-%d}.html"


_RENDER_LOG_LOCK = threading.Lock()


def _update_render_log_rows(rows: list, message: str, source: str = "", media_type: str = "image",
                            render_mode: str = "", output_path: str = "", root: Path | None = None) -> int | None:
    message = message.strip()
    if not message or set(message) == {"-"}:
        return None
    stamp = datetime.now().strftime("%H:%M:%S")
    timestamp = re.match(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$", message, re.S)
    if timestamp:
        stamp, message = timestamp.groups()
    started = message.startswith("> Aperçu en cours : ")
    if started:
        source = message.split(": ", 1)[1]
    progress = re.match(r"^\[\s*(\d+%|---)\]\s*(.*?) — (.*)$", message, re.S)
    filename = Path(source).name if source else (progress.group(2) if progress else "—")
    detail = progress.group(3) if progress else message
    index = next((i for i in range(len(rows) - 1, -1, -1)
                  if (rows[i]["source"] == source if source else rows[i]["file"] == filename)), None)
    if started or index is None:
        rows.append({"start": stamp, "end": "", "source": source, "file": filename,
                     "type": "Turntable" if media_type == "turntable" else "Image",
                     "progress": "—", "state": "En cours", "details": []})
        index = len(rows) - 1
    row = rows[index]
    if source:
        location = Path(source)
        if root is not None:
            try:
                location = location.relative_to(root)
            except ValueError:
                pass
        row["location"] = location.as_posix()
    if render_mode:
        row["poly"] = "High poly" if render_mode == "high" else "Low poly"
    if output_path:
        row["output_directory"] = str(Path(output_path).parent)
        row["output_name"] = Path(output_path).name
    if media_type == "turntable" or "turntable" in detail.casefold():
        row["type"] = "Turntable"
    if progress:
        row["progress"] = progress.group(1)
    lowered = detail.casefold()
    if "interrompu" in lowered or "annul" in lowered:
        row["state"], row["end"] = "Interrompu", stamp
    elif any(word in lowered for word in ("erreur", "échec", "echec", "indisponible", "aucun rendu")):
        row["state"], row["end"] = "Échec", stamp
    elif progress and progress.group(1) == "100%":
        row["state"], row["end"] = "Terminé", stamp
    row["details"].append(f"[{stamp}] {detail}")
    return index


_RENDER_LOG_COLUMNS = ["Emplacement du fichier", "Heure de démarrage", "Heure de fin",
                       "Low / High poly", "Image / Turntable", "Emplacement du fichier généré",
                       "Nom du fichier généré", "Progression", "État"]


def _render_log_values(row: dict) -> list[str]:
    return [row.get("location") or row.get("source") or row.get("file", "—"),
            row["start"], row["end"] or "—", row.get("poly") or "—", row["type"],
            row.get("output_directory") or "—", row.get("output_name") or "—",
            row.get("progress") or "—", row["state"]]


def _render_log_html(rows: list, title: str) -> str:
    body = []
    for row in rows:
        details = "\n".join(row["details"])
        values = _render_log_values(row)
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values[:-1])
        body.append(f'<tr title="{html.escape(row["source"], quote=True)}">{cells}'
                    f'<td><details><summary>{html.escape(values[-1])}</summary><pre>{html.escape(details)}</pre></details></td></tr>')
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return ("<!doctype html><html lang='fr'><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title><style>"
            "body{background:#1a1c1e;color:#ddd;font:14px system-ui;padding:24px}"
            "table{border-collapse:collapse;width:100%}th,td{border:1px solid #45494d;padding:9px;text-align:left;vertical-align:top}"
            "th{background:#303438;position:sticky;top:0}tr:nth-child(even){background:#24272a}"
            "summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}"
            "</style><body>" + f"<h2>{html.escape(title)}</h2><table><thead><tr>"
            + "".join(f"<th>{html.escape(name)}</th>" for name in _RENDER_LOG_COLUMNS) +
            "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
            f'<script id="render-data" type="application/json">{data}</script></body></html>')


def _read_render_log_entries(path: Path) -> list:
    # Certains messages Blender contiennent des octets Windows-1252 au
    # milieu du journal UTF-8 : conserver les accents UTF-8 deja valides.
    content = path.read_bytes().decode("utf-8-sig", errors="surrogateescape")
    content = re.sub(r"[\udc80-\udcff]", lambda match:
                     bytes([ord(match.group()) - 0xdc00]).decode("cp1252", errors="replace"), content)
    match = re.search(r'<script id="render-data" type="application/json">(.*?)</script>', content, re.S)
    return json.loads(match.group(1)) if match else []


def _write_render_log(directory: Path, message: str = "", source: str = "", media_type: str = "image",
                     render_mode: str = "", output_path: str = "") -> Path:
    with _RENDER_LOG_LOCK:
        path = _render_log_path(directory)
        rows = []
        if path.is_file():
            rows = _read_render_log_entries(path)
        if message:
            _update_render_log_rows(rows, message, source, media_type, render_mode, output_path, directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(_render_log_html(rows, f"Rendus du {datetime.now():%Y-%m-%d}"), encoding="utf-8")
        temporary.replace(path)
        return path


class _RenderLogTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(_RENDER_LOG_COLUMNS), parent)
        self._entries = []
        self.setHorizontalHeaderLabels(_RENDER_LOG_COLUMNS)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate([280, 155, 125, 130, 140, 300, 230, 100, 130]):
            self.setColumnWidth(column, width)
        self.setWordWrap(False)
        self.cellDoubleClicked.connect(self._show_details)

    def clear(self):
        self._entries.clear()
        self.setRowCount(0)

    def appendPlainText(self, message, **metadata):
        index = _update_render_log_rows(self._entries, message, **metadata)
        if index is None:
            return
        self.setRowCount(len(self._entries))
        self._display_entry(index)

    def load_entries(self, entries):
        self.clear()
        self._entries = entries
        self.setRowCount(len(entries))
        for index in range(len(entries)):
            self._display_entry(index)

    def _display_entry(self, index):
        row = self._entries[index]
        values = _render_log_values(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(row["source"] + "\n" + "\n".join(row["details"]))
            self.setItem(index, column, item)
        self.setRowHeight(index, max(40, self.fontMetrics().height() * 2 + 8))

    def ensureCursorVisible(self):
        if self.rowCount():
            self.scrollToItem(self.item(self.rowCount() - 1, 0))

    def _show_details(self, row, column):
        dialog = QDialog(self)
        dialog.setWindowTitle("Détails du rendu — " + self._entries[row]["file"])
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(dialog)
        details.setReadOnly(True)
        details.setPlainText(self._entries[row]["source"] + "\n\n" + "\n".join(self._entries[row]["details"]))
        layout.addWidget(details)
        dialog.exec()


def _render_value(text: str):
    text = text.strip()
    lowered = text.casefold()
    if lowered in {"oui", "yes", "true", "on"}:
        return True
    if lowered in {"non", "no", "false", "off"}:
        return False
    # Les chemins et couleurs ne doivent jamais passer par l'extraction
    # numerique ci-dessous : un template comme *_01.blend deviendrait sinon
    # simplement l'entier 1.
    if text.startswith("#") or "\\" in text or "/" in text:
        return text
    if text.startswith("(") and text.endswith(")"):
        parts = [part.strip().replace(",", ".") for part in text[1:-1].split(",")]
        try:
            return tuple(float(part) for part in parts)
        except ValueError:
            pass
    match = re.fullmatch(r"\(?\s*([-+]?\d+(?:[.,]\d+)?)\s*,\s*([-+]?\d+(?:[.,]\d+)?)\s*,\s*([-+]?\d+(?:[.,]\d+)?)(?:\s*,\s*([-+]?\d+(?:[.,]\d+)?))?\s*\)?", text)
    if match:
        values = [float(part.replace(",", ".")) for part in match.groups() if part is not None]
        return tuple(values)
    match = re.search(r"([-+]?\d+(?:[.,]\d+)?)\s*[×x]\s*([-+]?\d+(?:[.,]\d+)?)", text, re.I)
    if match:
        return tuple(int(float(part.replace(",", "."))) for part in match.groups())
    match = re.search(r"([-+]?\d+(?:[.,]\d+)?)", text)
    if match:
        number = float(match.group(1).replace(",", "."))
        return int(number) if number.is_integer() else number
    return text


def _load_render_profiles() -> dict[str, dict[str, object]]:
    """Lit les profils LOW POLY et HIGH POLY depuis le fichier texte."""
    profiles: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    key_map = {
        "fichier blender": "template",
        "vue": "view",
        "eclairage": "lighting",
        "eclairage scene": "lighting_scene",
        "eclairage hdri": "lighting_hdri_enabled",
        "force de l'hdri": "lighting_hdri_strength",
        # Les anciens settings utilisaient "Fond de l'image HDRI" pour le
        # chemin. Les nouveaux distinguent le chemin et l'affichage du fond.
        "path de l'image hdri": "lighting_hdri",
        "fond de l'image hdri": "lighting_hdri_background",
        "shader": "shader_name",
        "afficher l'image hdri dans le fond du rendu": "lighting_hdri_background",
        "facteur d'intensite de l'eclairage hdri": "lighting_hdri_strength",
        "facteur d'intensite des lights presentes dans la scene": "lighting_scene_strength",
        "shadows": "shadows",
        "shadows au sol": "ground_shadows",
        "wireframe": "wireframe",
        "subdivision": "subdivisions",
        "subdivisions": "subdivisions",
        "recalculer les normales": "recalculate_normals",
        "recalcul des normales": "recalculate_normals",
        "recalculer normales": "recalculate_normals",
        "epaisseur du wireframe": "wireframe_thickness",
        "shade": "shade",
        "couleur de base": "base_color",
        "couleur du wireframe": "wire_color",
        "couleur du fond": "background_color",
        "metallic": "metallic",
        "roughness": "roughness",
        "coat weight": "coat_weight",
        "coat roughness": "coat_roughness",
        "alpha": "alpha",
        "ambiant occlusion": "ambient_occlusion",
        "force ambiant occlusion": "ambient_occlusion_strength",
        "rendu": "engine",
        "resolution de sortie": "resolution",
        "format": "format",
        "transparence du fond": "film_transparent",
    }
    try:
        lines = RENDER_PARAMETERS_PATH.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return profiles
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        # Le fichier peut etre ecrit comme une liste Markdown. Retirer les
        # tirets de presentation, mais conserver le contenu de la ligne.
        while line.startswith("-"):
            line = line[1:].strip()
        if not line:
            continue
        if line.endswith(":") and ":" not in line[:-1]:
            name = line[:-1].strip().upper()
            if name in {"LOW POLY", "HIGH POLY"}:
                current = profiles.setdefault(name, {})
            else:
                current = None
            continue
        if current is None or ":" not in line:
            continue
        label, value = line.split(":", 1)
        if label.strip().casefold() == "notes":
            current = None
            continue
        # Nouveau format : "LIGHTING : parametre : valeur". Le premier
        # libelle est une categorie, le second est le vrai parametre.
        category = label.strip().casefold()
        if category == "shader":
            shader_match = re.search(r'["\u201c](.*?)["\u201d]', value)
            current["shader_name"] = (shader_match.group(1) if shader_match else value).strip()
            continue
        if category in {"lighting", "shadows", "wireframe", "ambiant occlusion", "camera"} and ":" in value:
            label, value = value.split(":", 1)
        normalized = label.strip().casefold().replace("é", "e").replace("è", "e").replace("ê", "e")
        normalized = normalized.replace("à", "a").replace("û", "u").replace("’", "'")
        key = key_map.get(normalized)
        if key:
            if key == "background_color" and value.strip().casefold().startswith("a appliquer:"):
                value = value.split(":", 1)[1].strip()
            parsed_value = _render_value(value)
            if key == "lighting_hdri_enabled" and isinstance(parsed_value, str):
                # Compatibilite avec l'ancienne forme ou le chemin etait
                # directement ecrit sur la ligne "Eclairage hdri".
                current["lighting_hdri"] = parsed_value
                current[key] = True
            elif key == "lighting_hdri_background" and isinstance(parsed_value, str):
                # Compatibilite avec l'ancien libelle qui portait directement
                # le chemin HDRI. Avec le nouveau format, cette ligne est un
                # simple oui/non et le chemin vient de "Path de l'image HDRI".
                current["lighting_hdri"] = parsed_value
            else:
                current[key] = parsed_value
            if key == "lighting_hdri" and str(parsed_value).strip():
                # Le format actuel active implicitement l'HDRI dès qu'un
                # chemin est fourni; l'ancien format pouvait encore fournir
                # un champ explicite "Eclairage hdri : non".
                current.setdefault("lighting_hdri_enabled", True)
        elif normalized == "camera":
            clips = re.findall(r"[-+]?\d+(?:[.,]\d+)?", value)
            if len(clips) >= 2:
                current["clip_near"] = float(clips[0].replace(",", "."))
                current["clip_far"] = float(clips[1].replace(",", "."))
        else:
            current.setdefault("unrecognized", []).append(label.strip())
    return profiles


# Instantane initial; les rendus manuels et chaque nouveau scan automatique
# rechargent le fichier avant de determiner si un cache reste valide.
_RENDER_PROFILES = _load_render_profiles()
_AUTOMATIC_RENDER_PROFILE: dict[str, object] | None = None
_AUTOMATIC_RENDER_PROFILES: dict[str, dict[str, object]] | None = None


def _reload_render_profiles() -> None:
    global _RENDER_PROFILES
    _RENDER_PROFILES = _load_render_profiles()


def _begin_automatic_render_batch() -> None:
    global _AUTOMATIC_RENDER_PROFILE, _AUTOMATIC_RENDER_PROFILES
    _reload_render_profiles()
    _AUTOMATIC_RENDER_PROFILES = json.loads(json.dumps(_RENDER_PROFILES))
    _AUTOMATIC_RENDER_PROFILE = _render_profile(
        "low", _AUTOMATIC_RENDER_PROFILES.get("LOW POLY", {})
    )


def _render_profile(render_mode: str, profile_override: dict[str, object] | None = None) -> dict[str, object]:
    profile = dict(profile_override or _RENDER_PROFILES.get("HIGH POLY" if render_mode == "high" else "LOW POLY", {}))
    profile.setdefault("template", "scene pour appercu.blend")
    profile.setdefault("lighting_scene", True)
    profile.setdefault("lighting_scene_strength", 1.0)
    profile.setdefault("lighting_hdri", "")
    profile.setdefault("lighting_hdri_enabled", False)
    profile.setdefault("lighting_hdri_strength", 1.0)
    profile.setdefault("shader_name", "")
    profile.setdefault("wireframe", render_mode != "high")
    profile.setdefault("wireframe_thickness", 1.0)
    profile.setdefault("subdivisions", 0)
    profile.setdefault("recalculate_normals", False)
    profile.setdefault("shadows", render_mode == "high")
    profile.setdefault("ground_shadows", render_mode == "high")
    profile.setdefault("shade", "smooth" if render_mode == "high" else "flat")
    profile.setdefault("base_color", (0.48, 0.50, 0.53))
    profile.setdefault("wire_color", (0.0, 0.0, 0.0, 1.0))
    profile.setdefault("metallic", 0.0)
    profile.setdefault("roughness", 1.0)
    profile.setdefault("coat_weight", 0.0)
    profile.setdefault("coat_roughness", 0.0)
    profile.setdefault("alpha", 1.0)
    profile.setdefault("ambient_occlusion", False)
    profile.setdefault("ambient_occlusion_strength", 1.0)
    profile.setdefault("clip_near", 0.1)
    profile.setdefault("clip_far", 1000.0)
    profile.setdefault("engine", "eevee")
    profile.setdefault("resolution", (1000, 1000))
    profile.setdefault("format", "png")
    profile.setdefault("background_color", "#3a3a3a")
    profile.setdefault("film_transparent", True)
    return profile


def _apply_render_background(image: QImage, profile: dict[str, object]) -> QImage:
    """Compose un rendu detoure sur le fond configure dans le profil.

    Blender rend toujours avec un canal alpha (meme quand le resultat final
    doit etre opaque). Cela evite que le fond du template ou l'HDRI ne soit
    "brule" dans les contours avant la composition finale.
    """
    if bool(profile.get("film_transparent", True)):
        return image
    background = QColor(str(profile.get("background_color", "#3a3a3a")).strip())
    if not background.isValid():
        background = QColor("#3a3a3a")
    background.setAlpha(255)
    composed = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    composed.fill(background)
    painter = QPainter(composed)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.drawImage(0, 0, image)
    painter.end()
    return composed


# Camera fixe en haut a droite, axes Z-up : yaw autour de Z, puis pitch
# autour de X. L'ecran projette X horizontal et Z vertical.
_OBJ_YAW = math.radians(-20)
_OBJ_PITCH = math.radians(20)


def _decode_obj_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None, render_mode: str = "low", profile_override=None) -> QImage | None:
    """Produit une image opaque en wireframe depuis un OBJ Wavefront."""
    eevee_image = _render_wireframe_eevee(path, max_dim, progress_callback, cancel_event, render_mode=render_mode, profile_override=profile_override)
    if eevee_image is not None:
        return eevee_image
    if cancel_event is not None and cancel_event.is_set():
        return None
    template_path = Path(__file__).resolve().parent / "files" / str(_render_profile(render_mode, profile_override)["template"])
    if _blender_executable() and template_path.is_file():
        # Ne pas substituer silencieusement un rendu different du template.
        return None
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []   # triangles (fan) d'indices dans `vertices`
    wire_edges: list[tuple[int, int]] = []   # aretes des polygones sources, sans diagonales de triangulation
    source_y_up = False
    try:
        file_size = path.stat().st_size
    except OSError:
        return None
    last_parse_percent = -1
    if progress_callback:
        progress_callback(1, "Lecture du maillage OBJ")

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            while True:
                line = f.readline()
                if not line:
                    break
                if line.lower().startswith("# file exported by zbrush"):
                    # Dans les OBJ ZBrush de cette collection, l'axe vertical
                    # source est Y; le convertit vers la convention du rendu Z-up.
                    source_y_up = True
                elif line.startswith("v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                        except ValueError:
                            pass
                elif line.startswith("f ") and len(faces) < OBJ_PREVIEW_MAX_TRIANGLES:
                    idx = []
                    for tok in line.split()[1:]:
                        try:
                            n = int(tok.split("/", 1)[0])
                        except ValueError:
                            idx = []
                            break
                        # Index OBJ 1-based, negatif = relatif a la fin de la
                        # liste de sommets deja lus.
                        idx.append(n - 1 if n > 0 else len(vertices) + n)
                    if len(idx) >= 3:
                        if all(0 <= vertex < len(vertices) for vertex in idx):
                            wire_edges.extend((idx[i], idx[(i + 1) % len(idx)]) for i in range(len(idx)))
                        for i in range(1, len(idx) - 1):
                            faces.append((idx[0], idx[i], idx[i + 1]))
                            if len(faces) >= OBJ_PREVIEW_MAX_TRIANGLES:
                                break
                if progress_callback and file_size:
                    percent = min(24, int(f.tell() * 24 / file_size))
                    if percent > last_parse_percent:
                        last_parse_percent = percent
                        progress_callback(percent, f"Lecture OBJ : {percent * 100 // 24}% du fichier")
    except OSError:
        return None

    if source_y_up:
        vertices = [(x, -z, y) for x, y, z in vertices]
        if progress_callback:
            progress_callback(25, "Conversion des coordonnées ZBrush Y-up vers Z-up")
    if not vertices or not faces:
        if progress_callback:
            progress_callback(100, "Aucune géométrie exploitable")
        return None
    # Une arete partagee par deux faces ne doit etre dessinee qu'une fois.
    wire_edges = list(dict.fromkeys((min(a, b), max(a, b)) for a, b in wire_edges if a != b))
    # Ne pas sous-echantillonner les faces : supprimer des triangles de façon
    # uniforme ouvre des trous dans la surface et donne un aspect « éclaté ».
    if len(wire_edges) > OBJ_PREVIEW_RENDER_EDGES:
        stride = math.ceil(len(wire_edges) / OBJ_PREVIEW_RENDER_EDGES)
        wire_edges = wire_edges[::stride]

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0

    cos_y, sin_y = math.cos(_OBJ_YAW), math.sin(_OBJ_YAW)
    cos_p, sin_p = math.cos(_OBJ_PITCH), math.sin(_OBJ_PITCH)
    transformed: list[tuple[float, float, float]] = []
    for x, y, z in vertices:
        x, y, z = (x - cx) / extent, (y - cy) / extent, (z - cz) / extent
        x, y = x * cos_y - y * sin_y, x * sin_y + y * cos_y    # yaw autour de Z
        y, z = y * cos_p - z * sin_p, y * sin_p + z * cos_p    # pitch autour de X
        transformed.append((x, y, z))

    # Etendue projetee (x, z) reelle apres rotation, pour cadrer pile le
    # modele quelle que soit son orientation d'origine.
    proj_xs = [p[0] for p in transformed]
    proj_ys = [p[2] for p in transformed]
    span = max(max(proj_xs) - min(proj_xs), max(proj_ys) - min(proj_ys)) or 1.0
    scale = (max_dim * 0.82) / span
    ox = max_dim / 2 - (min(proj_xs) + max(proj_xs)) / 2 * scale
    oy = max_dim / 2 + (min(proj_ys) + max(proj_ys)) / 2 * scale

    def to_screen(p: tuple[float, float, float]) -> QPointF:
        return QPointF(p[0] * scale + ox, -p[2] * scale + oy)

    # Ajuste les plans selon la profondeur reelle, avec les bornes de
    # reference de l'utilisateur (near >= 0.1, far <= 10000). Les sommets
    # sont normalises avant cette etape : les valeurs restent adaptees au
    # modele plutot que d'utiliser systematiquement toute la plage.
    depth_values = [p[1] for p in transformed]
    depth_span = max(max(depth_values) - min(depth_values), 1e-4)
    near_clip = max(0.1, depth_span * 0.01)
    far_clip = min(10000.0, max(near_clip + 0.1, near_clip + depth_span * 1.05))
    depth_max = max(depth_values)
    camera_depth = [-(depth_max - value + near_clip) for value in depth_values]
    if progress_callback:
        progress_callback(26, f"Caméra Z-up : near={near_clip:.4g}, far={far_clip:.4g}")

    vertex_shade: list[float] = []  # conservé dans la signature du rasteriseur
    base_rgb = (190, 190, 196)

    if _NUMPY_AVAILABLE:
        return _rasterize_obj_numpy(
            transformed, faces, vertex_shade, max_dim, scale, ox, oy, base_rgb, wire_edges,
            progress_callback=progress_callback, camera_depth=camera_depth,
            near_clip=near_clip, far_clip=far_clip,
        )
    return _rasterize_obj_qpainter(
        transformed, faces, vertex_shade, max_dim, to_screen, base_rgb, wire_edges,
        progress_callback=progress_callback,
    )


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


def _render_wireframe_eevee(path: Path, max_dim: int, progress_callback=None, cancel_event=None, kind_override=None, render_mode: str = "low", profile_override=None) -> QImage | None:
    """Rend l'objet dans la scene Eevee du template, avec son eclairage."""
    blender = _blender_executable()
    if not blender:
        return None
    suffix = path.suffix.lower()
    profile = _render_profile(render_mode, profile_override)
    wireframe_thickness = float(profile["wireframe_thickness"])
    output_format = str(profile["format"]).strip().upper()
    turntable_output = str(profile.get("_turntable_output", ""))
    if turntable_output:
        output_format = "PNG"
    output_extensions = {"PNG": ".png", "JPEG": ".jpg", "BMP": ".bmp"}
    if output_format not in output_extensions:
        if progress_callback:
            progress_callback(99, "Format de rendu non pris en charge : " + output_format)
        return None
    script = r'''import bpy, os, sys, math, shutil
from mathutils import Matrix, Vector
bpy.context.preferences.edit.use_global_undo = False
src, dst, status_path, kind, output_dim, output_format = sys.argv[sys.argv.index("--") + 1:sys.argv.index("--") + 7]
output_dim = int(output_dim)
turntable_output = __TURNTABLE_OUTPUT__
def report(percent, text):
    try:
        with open(status_path, "w", encoding="utf-8") as f: f.write("%d|%s" % (percent, text))
    except OSError: pass
def fail(message):
    report(99, message)
    raise RuntimeError(message)
report(3, "Ouverture de la scene de rendu")
if __UNRECOGNIZED_FIELDS__:
    report(4, "Parametres non reconnus : " + ", ".join(__UNRECOGNIZED_FIELDS__))
scene = bpy.context.scene
if scene.camera is None: fail("La scene de preview ne contient pas de camera")
view_name = __VIEW_NAME__
if view_name and view_name.casefold() not in {"camera du fichier blender", "camera du template", "camera", "template"}:
    selected_camera = bpy.data.objects.get(view_name)
    if selected_camera is None or selected_camera.type != "CAMERA":
        fail("Camera demandee introuvable dans le template : " + view_name)
    scene.camera = selected_camera
lighting_path = __LIGHTING_PATH__
if not __LIGHTING_SCENE__:
    for light in scene.objects:
        if light.type == "LIGHT":
            light.hide_render = True
if lighting_path:
    if not os.path.isfile(lighting_path):
        fail("Fichier d'eclairage HDRI introuvable : " + lighting_path)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Pipeline HDRI World")
    scene.world.use_nodes = True
    world_nodes = scene.world.node_tree.nodes
    world_links = scene.world.node_tree.links
    background = next((node for node in world_nodes if node.type == "BACKGROUND"), None)
    if background is None:
        background = world_nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = __HDRI_STRENGTH__
    world_output = next((node for node in world_nodes if node.type == "OUTPUT_WORLD"), None)
    if world_output is None:
        world_output = world_nodes.new("ShaderNodeOutputWorld")
    if not any(link.from_node == background and link.to_node == world_output for link in world_links):
        world_links.new(background.outputs["Background"], world_output.inputs["Surface"])
    environment = world_nodes.new("ShaderNodeTexEnvironment")
    environment.image = bpy.data.images.load(lighting_path, check_existing=True)
    world_links.new(environment.outputs["Color"], background.inputs["Color"])
bbox_obj = bpy.data.objects.get("Cube")
if bbox_obj is None or bbox_obj.type != "MESH": fail("Le cube servant de bounding box est introuvable")
bbox_corners = [bbox_obj.matrix_world @ Vector(corner) for corner in bbox_obj.bound_box]
bbox_min = Vector(tuple(min(p[i] for p in bbox_corners) for i in range(3)))
bbox_max = Vector(tuple(max(p[i] for p in bbox_corners) for i in range(3)))
target_center = (bbox_min + bbox_max) * 0.5
target_size = max(bbox_max - bbox_min)
if target_size <= 1e-12: fail("Le cube de bounding box a une taille nulle")
initial_objects = {obj.as_pointer() for obj in scene.objects}
report(8, "Import du fichier dans le template")
try:
    if kind in {"abc", "maya"}:
        bpy.ops.wm.alembic_import(filepath=src, scale=1.0, validate_meshes=False)
    elif kind == "blend":
        with bpy.data.libraries.load(src, link=False) as (data_from, data_to):
            if not data_from.scenes: raise RuntimeError("Aucune scene dans le fichier .blend")
            data_to.scenes = [data_from.scenes[0]]
        source_scene = data_to.scenes[0]
        if source_scene is None: raise RuntimeError("Scene source introuvable")
        # Une master collection de Scene est un ID embarque : son lien dans
        # une AUTRE scene n'est pas fiable apres sauvegarde/rechargement.
        # Utiliser une vraie collection pour le snapshot de reprise.
        imported_collection = bpy.data.collections.new("Pipeline Imported Geometry")
        scene.collection.children.link(imported_collection)
        for source_obj in source_scene.collection.objects:
            imported_collection.objects.link(source_obj)
        for child in source_scene.collection.children:
            imported_collection.children.link(child)
        def expose_imported_collection(collection):
            collection.hide_viewport = False
            collection.hide_render = False
            for child in collection.children:
                expose_imported_collection(child)
        expose_imported_collection(imported_collection)
        bpy.context.view_layer.update()
        for source_obj in source_scene.objects:
            source_obj.hide_render = source_obj.type != "MESH"
    elif kind == "fbx":
        try:
            bpy.ops.import_scene.fbx(filepath=src)
        except Exception as exc:
            raise RuntimeError("Import FBX impossible : %s" % exc)
    else:
        try:
            bpy.ops.wm.obj_import(filepath=src, global_scale=1.0, clamp_size=0.0,
                forward_axis='NEGATIVE_Z', up_axis='Y', use_split_objects=True,
                use_split_groups=False, import_vertex_groups=False, validate_meshes=True,
                close_spline_loops=True, mtl_name_collision_mode='MAKE_UNIQUE')
        except (AttributeError, TypeError):
            bpy.ops.import_scene.obj(filepath=src, global_clamp_size=0.0,
                axis_forward='-Z', axis_up='Y', use_split_objects=True,
                use_split_groups=False, use_image_search=False)
except Exception as exc:
    fail("Import Blender impossible : %s" % exc)
objects = [o for o in scene.objects if o.as_pointer() not in initial_objects and o.type == "MESH"]
if not objects: fail("Aucun maillage importe par Blender")
for obj in objects:
    obj.hide_viewport = False
    obj.hide_set(False)
bpy.context.view_layer.update()
if kind in {"ma", "mb", "maya"}:
    report(16, "Selection de tous les objets Maya et fusion avec Ctrl+J")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if not turntable_output:
        try:
            bpy.ops.object.join()
        except Exception as exc:
            fail("Impossible de fusionner les objets Maya : %s" % exc)
        objects = [bpy.context.view_layer.objects.active]
    report(18, "Application de Ctrl+A - All Transforms avant le scale")
    try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception as exc:
        fail("Impossible d'appliquer All Transforms au maillage Maya fusionne : %s" % exc)
    bpy.context.view_layer.update()
subdivision_levels = max(0, int(__SUBDIVISIONS__))
if subdivision_levels > 0:
    report(13, "Ajout du modifier Subdivision : niveau %d" % subdivision_levels)
    for obj in objects:
        subdivision = obj.modifiers.new("Subdivision de rendu", "SUBSURF")
        subdivision.subdivision_type = "CATMULL_CLARK"
        subdivision.levels = subdivision_levels
        subdivision.render_levels = subdivision_levels
report(14, "Application de tous les modifiers avant le cadrage")
for obj in objects:
    modifier_names = [mod.name for mod in obj.modifiers]
    if modifier_names:
        obj.data = obj.data.copy()
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for modifier_name in modifier_names:
            modifier = obj.modifiers.get(modifier_name)
            if modifier is None:
                continue
            # Appliquer l'etat de rendu, pas celui du viewport. Un Subsurf
            # de niveau viewport 0 mais rendu 2 ne doit pas rester sur
            # l'objet actif et subdiviser tout le modele apres la fusion.
            if not modifier.show_render:
                obj.modifiers.remove(modifier)
                continue
            modifier.show_viewport = True
            if modifier.type in {'SUBSURF', 'MULTIRES'}:
                modifier.levels = modifier.render_levels
                if modifier.render_levels == 0:
                    obj.modifiers.remove(modifier)
                    continue
            try:
                bpy.ops.object.modifier_apply(modifier=modifier_name)
            except Exception as exc:
                error_text = str(exc)
                if "disabled" in error_text.casefold() or "skipping apply" in error_text.casefold():
                    report(15, "Modifier ignore car desactive : %s sur %s" % (modifier_name, obj.name))
                    remaining_modifier = obj.modifiers.get(modifier_name)
                    if remaining_modifier is not None:
                        obj.modifiers.remove(remaining_modifier)
                    continue
                fail("Impossible d'appliquer le modifier %s sur %s : %s" % (modifier_name, obj.name, exc))
bpy.context.view_layer.update()
for light in scene.objects:
    if light.type == "LIGHT" and hasattr(light.data, "use_shadow"):
        light.data.use_shadow = __SHADOWS__
    if light.type == "LIGHT" and hasattr(light.data, "energy"):
        light.data.energy *= __LIGHTING_SCENE_STRENGTH__
for obj in scene.objects:
    if any(marker in obj.name.casefold() for marker in ("ground", "sol", "floor")):
        obj.hide_render = not __GROUND_SHADOWS__
if len(objects) > 1 and not turntable_output:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    objects = [bpy.context.view_layer.objects.active]
report(20, "Calcul de la bounding box de l'objet")
world_matrices = {obj: obj.matrix_world.copy() for obj in objects}
world_points = [world_matrices[obj] @ vertex.co for obj in objects for vertex in obj.data.vertices]
if not world_points: fail("Aucune geometrie exploitable")
source_min = Vector(tuple(min(p[i] for p in world_points) for i in range(3)))
source_max = Vector(tuple(max(p[i] for p in world_points) for i in range(3)))
del world_points
source_center = (source_min + source_max) * 0.5
source_size = max(source_max - source_min)
if source_size <= 1e-12: fail("La bounding box de l'objet a une taille nulle")
uniform_scale = target_size / source_size
transform = Matrix.Translation(target_center) @ Matrix.Scale(uniform_scale, 4) @ Matrix.Translation(-source_center)
# Une seule transformation est calculee depuis la bounding box globale puis
# cuite dans la geometrie. Les objets Maya ont ete joints et leurs transforms
# appliques avant le calcul de cette bounding box.
report(32, "Scale et centrage du maillage Maya fusionne dans le cube" if kind in {"ma", "mb", "maya"} else "Mise a l'echelle et centrage dans le cube")
for obj in objects:
    original_world = world_matrices[obj]
    obj.data = obj.data.copy()
    obj.data.transform(transform @ original_world)
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)
    if turntable_output:
        obj.animation_data_clear()
        obj.constraints.clear()
        obj.data.animation_data_clear()
        if obj.data.shape_keys is not None:
            obj.data.shape_keys.animation_data_clear()
    for polygon in obj.data.polygons: polygon.use_smooth = __SHADE_SMOOTH__
    obj.data.materials.clear()
if __RECALCULATE_NORMALS__:
    report(35, "Recalcul des normales")
    for obj in objects:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            fail("Impossible de recalculer les normales sur %s : %s" % (obj.name, exc))
shader_source = bpy.data.materials.get(__SHADER_NAME__) if __SHADER_NAME__ else None
if shader_source is None and __SHADER_NAME__:
    # Certains templates historiques nomment le matériau de lookdev
    # "Lookdev" ou "Material0", alors que le profil le désigne comme
    # "rendu_apercu". Résoudre ces alias permet d'appliquer le shader réel
    # présent dans le template au lieu de recréer un Principled par défaut.
    requested_shader = __SHADER_NAME__.casefold()
    aliases = {"rendu_apercu", "rendu apercu", "rendu aperçu"}
    if requested_shader in aliases:
        for candidate_name in ("Lookdev", "Material0", "Material"):
            shader_source = bpy.data.materials.get(candidate_name)
            if shader_source is not None:
                report(45, "Shader de rendu applique : " + shader_source.name)
                break
surface = shader_source.copy() if shader_source is not None else bpy.data.materials.new("Preview - surface opaque")
surface.name = "Preview - " + (__SHADER_NAME__ or "surface opaque")
surface.diffuse_color = __BASE_COLOR_WITH_ALPHA__
surface.use_nodes = True
if __BASE_ALPHA__ < 1.0:
    if hasattr(surface, "surface_render_method"):
        surface.surface_render_method = "DITHERED"
    elif hasattr(surface, "blend_method"):
        surface.blend_method = "BLEND"
principled = surface.node_tree.nodes.get("Principled BSDF")
if principled and shader_source is None:
    principled.inputs["Base Color"].default_value = surface.diffuse_color
    principled.inputs["Roughness"].default_value = __ROUGHNESS__
    principled.inputs["Metallic"].default_value = __METALLIC__
    principled.inputs["Alpha"].default_value = __BASE_ALPHA__
    coat_weight = principled.inputs.get("Coat Weight")
    if coat_weight is not None: coat_weight.default_value = __COAT_WEIGHT__
    coat_roughness = principled.inputs.get("Coat Roughness")
    if coat_roughness is not None: coat_roughness.default_value = __COAT_ROUGHNESS__
    if __AMBIENT_OCCLUSION__:
        # Le noeud AO des materiaux est pris en charge par Cycles, pas par
        # Eevee. On bascule donc le profil AO vers Cycles pour garantir un
        # effet reel dans le rendu final.
        ao_node = surface.node_tree.nodes.new("ShaderNodeAmbientOcclusion")
        ao_node.inputs["Distance"].default_value = __AMBIENT_OCCLUSION_DISTANCE__
        if hasattr(ao_node, "samples"):
            ao_node.samples = 16
        ao_strength = surface.node_tree.nodes.new("ShaderNodeMath")
        ao_strength.operation = "MULTIPLY"
        ao_strength.inputs[1].default_value = __AMBIENT_OCCLUSION_STRENGTH__
        ao_color = surface.node_tree.nodes.new("ShaderNodeMixRGB")
        ao_color.blend_type = "MIX"
        ao_color.inputs[1].default_value = __BASE_COLOR_WITH_ALPHA__
        ao_color.inputs[2].default_value = (0.0, 0.0, 0.0, __BASE_ALPHA__)
        surface.node_tree.links.new(ao_node.outputs["AO"], ao_strength.inputs[0])
        surface.node_tree.links.new(ao_strength.outputs[0], ao_color.inputs[0])
        surface.node_tree.links.new(ao_color.outputs[0], principled.inputs["Base Color"])
wire_material = bpy.data.materials.new("Preview - wireframe noir")
wire_material.diffuse_color = __WIRE_COLOR__
wire_material.use_nodes = True
if __WIRE_ALPHA__ < 1.0:
    if hasattr(wire_material, "surface_render_method"):
        wire_material.surface_render_method = "DITHERED"
    elif hasattr(wire_material, "blend_method"):
        wire_material.blend_method = "BLEND"
nodes = wire_material.node_tree.nodes
nodes.clear()
output = nodes.new("ShaderNodeOutputMaterial")
wire_shader = nodes.new("ShaderNodeBsdfPrincipled")
wire_shader.inputs["Base Color"].default_value = __WIRE_COLOR__
wire_shader.inputs["Roughness"].default_value = 1.0
wire_shader.inputs["Alpha"].default_value = __WIRE_ALPHA__
emission_input = wire_shader.inputs.get("Emission Color")
if emission_input is None:
    emission_input = wire_shader.inputs.get("Emission")
if emission_input is not None:
    emission_input.default_value = __WIRE_COLOR__
emission_strength = wire_shader.inputs.get("Emission Strength")
if emission_strength is not None:
    emission_strength.default_value = 1.0
wire_material.node_tree.links.new(wire_shader.outputs["BSDF"], output.inputs["Surface"])
for index, obj in enumerate(objects):
    obj.data.materials.append(surface)
    if __WIREFRAME_ENABLED__:
        obj.data.materials.append(wire_material)
    if index % max(1, len(objects) // 5) == 0:
        report(42 + int(20 * index / max(1, len(objects))), "Preparation du wireframe : objet %d/%d" % (index + 1, len(objects)))
# Grille, axes, curseur et gizmos sont des overlays du viewport, jamais rendus.
for obj in scene.objects:
    if obj.type in {'EMPTY', 'CAMERA'}: obj.hide_render = True
bbox_obj.hide_render = True
scene.camera.hide_render = False

scene.camera.data.clip_start = __CLIP_NEAR__
scene.camera.data.clip_end = __CLIP_FAR__
if __AMBIENT_OCCLUSION__:
    scene.render.engine = "CYCLES"
elif "eevee" in __ENGINE__.casefold():
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
elif "cycles" in __ENGINE__.casefold():
    scene.render.engine = "CYCLES"
scene.render.resolution_x = output_dim
scene.render.resolution_y = output_dim
scene.render.resolution_percentage = 100
# Respecter le template par defaut ; un profil explicite peut fixer les
# echantillons (notamment pour les tests de memoire a resolution reduite).
if __RENDER_SAMPLES__ > 0:
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = __RENDER_SAMPLES__
    elif hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = __RENDER_SAMPLES__
if turntable_output:
    # Orbite horizontale a la hauteur du centre geometrique final.
    bpy.context.view_layer.update()
    camera = scene.camera
    matrix = camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
    radial = Vector((matrix.translation.x - target_center.x,
                     matrix.translation.y - target_center.y, 0.0))
    if radial.length < 1e-6:
        radial = Vector((0.0, -max(target_size * 4.0, 1.0), 0.0))
    camera.animation_data_clear()
    camera.constraints.clear()
    camera.parent = None
    camera.location = target_center + radial
    camera.rotation_mode = 'QUATERNION'
    camera.rotation_quaternion = (-radial).to_track_quat('-Z', 'Y')
    bpy.context.view_layer.update()
def fit_preview_camera(scene, objects, occupancy=0.70):
    import numpy as np
    # Mesurer la geometrie finale, y compris les modifiers encore actifs.
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        temporary_mesh = bool(obj.modifiers)
        # Les modifiers ont deja ete appliques. Ne pas recopier le maillage
        # entier uniquement pour lire ses coordonnees de cadrage.
        mesh = evaluated.to_mesh() if temporary_mesh else evaluated.data
        try:
            vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", vertices)
            matrix = np.asarray(evaluated.matrix_world, dtype=np.float64)
            chunks.append(vertices.reshape((-1, 3)) @ matrix[:3, :3].T + matrix[:3, 3])
        finally:
            if temporary_mesh:
                evaluated.to_mesh_clear()
    if not chunks or not any(len(chunk) for chunk in chunks):
        fail("Aucune geometrie pour le cadrage camera")
    points = np.concatenate(chunks)
    del chunks
    if turntable_output:
        # Enveloppe cylindrique : une distance fixe contient la geometrie
        # pour les 72 angles, sans zoom ou recadrage entre les images.
        radial = points[:, :2] - np.array(tuple(target_center)[:2])
        radius = float(np.sqrt((radial * radial).sum(axis=1)).max())
        radius /= math.cos(math.pi / 72.0)
        zmin, zmax = float(points[:, 2].min()), float(points[:, 2].max())
        points = np.array([(target_center.x + radius * math.cos(i * math.tau / 72),
                            target_center.y + radius * math.sin(i * math.tau / 72), z)
                           for i in range(72) for z in (zmin, zmax)])
    camera = scene.camera
    if camera.data.type not in {'PERSP', 'ORTHO'}:
        fail("Cadrage automatique incompatible avec cette camera : " + camera.data.type)
    # Copier la camera evaluee evite qu'un parent ou une animation annule
    # le positionnement dans la scene temporaire de rendu.
    matrix = camera.evaluated_get(depsgraph).matrix_world.copy()
    camera.animation_data_clear()
    camera.constraints.clear()
    camera.parent = None
    camera.matrix_world = matrix
    camera.data = camera.data.copy()
    camera.data.animation_data_clear()
    bpy.context.view_layer.update()
    location, ortho_scale = camera.camera_fit_coords(depsgraph, points.reshape(-1))
    camera.location = location
    bpy.context.view_layer.update()
    inverse = camera.matrix_world.normalized().inverted()
    inverse_array = np.asarray(inverse, dtype=np.float64)
    local_points = points @ inverse_array[:3, :3].T + inverse_array[:3, 3]
    del points
    base_depths = -local_points[:, 2]
    minimum_depth = float(base_depths.min())
    base_location = camera.matrix_world.translation.copy()
    back = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
    near = max(camera.data.clip_start, 1e-5)

    def frame_bounds():
        frame = camera.data.view_frame(scene=scene)
        return (min(p.x for p in frame), max(p.x for p in frame),
                min(p.y for p in frame), max(p.y for p in frame), abs(frame[0].z))

    def measure(retreat):
        xmin, xmax, ymin, ymax, frame_depth = frame_bounds()
        if camera.data.type == 'ORTHO':
            projected = local_points[:, :2]
        else:
            if minimum_depth + retreat <= near:
                return float('inf'), None
            projected = local_points[:, :2] * (frame_depth / (base_depths + retreat))[:, None]
        bounds = ((float(projected[:, 0].min()) - xmin) / (xmax - xmin),
                  (float(projected[:, 0].max()) - xmin) / (xmax - xmin),
                  (float(projected[:, 1].min()) - ymin) / (ymax - ymin),
                  (float(projected[:, 1].max()) - ymin) / (ymax - ymin))
        return max(bounds[1] - bounds[0], bounds[3] - bounds[2]), bounds

    if camera.data.type == 'ORTHO':
        camera.data.ortho_scale = max(ortho_scale, 1e-6)
        span, bounds = measure(0.0)
        camera.data.ortho_scale *= span / occupancy
        retreat = max(0.0, near * 1.01 - minimum_depth)
    else:
        # Recherche bornee : toutes les profondeurs restent devant la camera.
        lower = near * 1.01 - minimum_depth
        upper = max(0.0, lower + 1.0)
        for _ in range(60):
            if measure(upper)[0] <= occupancy:
                break
            upper = lower + 2.0 * (upper - lower)
        else:
            fail("Impossible de trouver une distance de cadrage")
        for _ in range(28):
            middle = (lower + upper) * 0.5
            span, bounds = measure(middle)
            if span > occupancy:
                lower = middle
            else:
                upper = middle
            if bounds is not None and abs(span - occupancy) < 0.00001:
                upper = middle
                break
        retreat = upper
    camera.location = base_location + back * retreat
    bpy.context.view_layer.update()
    span, bounds = measure(retreat)
    # Centrer la silhouette projetee avec le decalage optique. Sa taille
    # reste identique ; les marges sur le grand cote deviennent 15%% chacune.
    base_frame = frame_bounds()
    for axis, center, width, index in (
            ('shift_x', (bounds[0] + bounds[1]) * 0.5, base_frame[1] - base_frame[0], 0),
            ('shift_y', (bounds[2] + bounds[3]) * 0.5, base_frame[3] - base_frame[2], 2)):
        value = getattr(camera.data, axis)
        before = frame_bounds()[index]
        setattr(camera.data, axis, value + 1.0)
        derivative = -(frame_bounds()[index] - before) / width
        setattr(camera.data, axis, value + (0.5 - center) / derivative)
    bpy.context.view_layer.update()
    span, bounds = measure(retreat)
    if minimum_depth + retreat <= camera.data.clip_start or float(base_depths.max()) + retreat >= camera.data.clip_end:
        fail("Objet hors des limites near/far de la camera apres cadrage")
    if abs(span - occupancy) > 0.001 or min(bounds) < 0.0 or max(bounds) > 1.0:
        fail("Verification du cadrage camera a %.0f%% echouee" % (occupancy * 100.0))
    report(68, "Cadrage camera : %.2f%% du rendu" % (span * 100.0))

if turntable_output:
    # Import, copies de datablocks, modifiers appliques et fusion laissent
    # des meshes sans utilisateur. Les liberer AVANT l'evaluation wireframe.
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
fit_preview_camera(scene, objects)
if __WIREFRAME_ENABLED__:
    # Ajouter le wireframe apres le cadrage : il ne doit ni influencer
    # la mesure de l'objet, ni garder une epaisseur liee a l'ancienne camera.
    camera = scene.camera
    frame = camera.data.view_frame(scene=scene)
    frame_width = max(p.x for p in frame) - min(p.x for p in frame)
    frame_height = max(p.y for p in frame) - min(p.y for p in frame)
    if camera.data.type == 'PERSP':
        reference_depth = -(camera.matrix_world.normalized().inverted() @ target_center).z
        depth_factor = reference_depth / max(abs(frame[0].z), 1e-8)
        frame_width *= depth_factor
        frame_height *= depth_factor
    world_per_pixel = min(frame_width / max(scene.render.resolution_x, 1),
                          frame_height / max(scene.render.resolution_y, 1))
    thickness_pixels = max(0.0, 1.8 * __WIREFRAME_THICKNESS__)
    for object_index, obj in enumerate(objects):
        wire = obj.modifiers.new("Wireframe fin", "WIREFRAME")
        wire.thickness = world_per_pixel * thickness_pixels
        wire.offset = 0.0
        wire.use_replace = False
        wire.use_even_offset = False
        wire.use_boundary = True
        wire.use_crease = False
        wire.use_relative_offset = False
        wire.material_offset = 1
        if turntable_output:
            # Evaluer chaque composant separement, pas un seul maillage
            # geant issu de la fusion : meme resultat visuel, pic RAM borne.
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=wire.name)
            obj.select_set(False)
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
            if object_index % max(1, len(objects) // 5) == 0:
                report(69, "Wireframe statique : composant %d/%d" % (object_index + 1, len(objects)))
    if not turntable_output:
        bpy.context.view_layer.update()
    report(69, "Epaisseur du wireframe apres cadrage : %.2f px" % thickness_pixels)
scene.render.image_settings.file_format = output_format
hide_hdri_background = bool(lighting_path)
# Le fond final est compose cote application lorsque le profil demande un
# rendu opaque. Garder l'alpha jusqu'a cette etape evite les franges du fond
# Blender/template autour de l'objet detoure.
scene.render.image_settings.color_mode = "RGBA"
scene.render.film_transparent = True
scene.render.filepath = dst
if turntable_output:
    # L'objet est statique : seule la camera et les lights tournent. Cuire
    # le wireframe UNE fois evite de reconstruire des millions de faces
    # et leurs caches de depsgraph pour chacun des 72 angles.
    report(69, "Optimisation memoire : preparation du maillage statique du turntable")
    bpy.context.view_layer.update()
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    scene.render.use_persistent_data = False
report(70, "Rendu " + scene.render.engine + " avec la camera du template")
if turntable_output:
    os.makedirs(turntable_output, exist_ok=True)
    camera_matrix = scene.camera.matrix_world.copy()
    lights = [(light, light.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy())
              for light in scene.objects if light.type == 'LIGHT' and not light.hide_render]
    for light, matrix in lights:
        light.animation_data_clear()
        light.data.animation_data_clear()
        light.constraints.clear()
        light.parent = None
        light.rotation_mode = 'QUATERNION'
        light.matrix_world = matrix
    # Tourner aussi l'environnement lumineux HDRI avec les lights.
    hdri_mapping = None
    if lighting_path:
        hdri_coordinates = world_nodes.new("ShaderNodeTexCoord")
        hdri_mapping = world_nodes.new("ShaderNodeMapping")
        world_links.new(hdri_coordinates.outputs["Generated"], hdri_mapping.inputs["Vector"])
        world_links.new(hdri_mapping.outputs["Vector"], environment.inputs["Vector"])
    for frame in range(72):
        scene.frame_set(frame + 1)
        angle = math.tau * frame / 72.0
        orbit = Matrix.Translation(target_center) @ Matrix.Rotation(angle, 4, 'Z') @ Matrix.Translation(-target_center)
        scene.camera.matrix_world = orbit @ camera_matrix
        for light, matrix in lights:
            light.matrix_world = orbit @ matrix
        for animated in [scene.camera] + [light for light, matrix in lights]:
            animated.keyframe_insert(data_path="location", frame=frame + 1)
            animated.keyframe_insert(data_path="rotation_quaternion", frame=frame + 1)
        if hdri_mapping is not None:
            hdri_mapping.inputs["Rotation"].default_value.z = -angle
            hdri_mapping.inputs["Rotation"].keyframe_insert(data_path="default_value", frame=frame + 1)
    # Un seul rendu d'animation conserve l'engine et ses buffers entre les
    # images, contrairement a 72 appels independants a render(write_still).
    scene.frame_start = 1
    scene.frame_end = 72
    scene.frame_step = 1
    scene.render.filepath = os.path.join(turntable_output, "render_####")
    rendered_paths = [scene.render.frame_path(frame=index + 1) for index in range(72)]
    def turntable_progress(render_scene, *_):
        index = render_scene.frame_current - 1
        report(70 + int(28 * index / 72), "Turntable : image %d / 72" % (index + 1))
    bpy.app.handlers.render_pre.append(turntable_progress)
    scene.frame_set(1)
    if __TURNTABLE_PREPARED_SCENE__:
        # Snapshot autonome de la geometrie preparee et des 72 positions.
        # Chaque image sera rendue dans un NOUVEAU processus Blender.
        prepared = __TURNTABLE_PREPARED_SCENE__
        temporary_scene = prepared + ".tmp.blend"
        # Le .blend importe peut ajouter d'autres scenes. Ne sauvegarder
        # que la scene de rendu pour que -b recharge bien celle-ci.
        if bpy.context.window is not None:
            bpy.context.window.scene = scene
        for other_scene in list(bpy.data.scenes):
            if other_scene != scene:
                bpy.data.scenes.remove(other_scene)
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=temporary_scene, check_existing=False, compress=True)
        os.replace(temporary_scene, prepared)
        report(98, "Scene du turntable preparee pour la reprise image par image")
    else:
        bpy.ops.render.render(animation=True)
        for index, rendered_path in enumerate(rendered_paths):
            os.replace(rendered_path, os.path.join(turntable_output, "frame_%03d.png" % index))
        scene.render.filepath = dst
        shutil.copyfile(os.path.join(turntable_output, "frame_000.png"), dst)
else:
    bpy.ops.render.render(write_still=True)
report(98, "Apercu Eevee pret")
    '''
    replacements = {
        "__TURNTABLE_PREPARED_SCENE__": repr(str(profile.get("_turntable_prepared_scene", ""))),
        "__RENDER_SAMPLES__": repr(max(0, int(profile.get("samples", 0)))),
        "__TURNTABLE_OUTPUT__": repr(turntable_output),
        "__LIGHTING_PATH__": repr(
            str((Path(__file__).resolve().parent / str(profile.get("lighting_hdri") or profile.get("lighting", ""))).resolve())
            if (bool(profile.get("lighting_hdri_enabled", False)) or bool(profile.get("lighting", "")))
            and str(profile.get("lighting_hdri") or profile.get("lighting", "")).strip()
            and str(profile.get("lighting_hdri") or profile.get("lighting", "")).casefold().strip() not in {
                "eclairage du fichier blender", "éclairage du fichier blender",
                "fichier blender", "template", "none", "aucun",
            }
            else ""
        ),
        "__LIGHTING_SCENE__": repr(bool(profile["lighting_scene"])),
        "__LIGHTING_SCENE_STRENGTH__": repr(max(0.0, float(profile["lighting_scene_strength"]))),
        "__HDRI_STRENGTH__": repr(max(0.0, float(profile["lighting_hdri_strength"]))),
        "__SHADER_NAME__": repr(str(profile.get("shader_name", "")).strip()),
        "__VIEW_NAME__": repr(str(profile.get("view", "camera du fichier blender")).strip()),
        "__UNRECOGNIZED_FIELDS__": repr(profile.get("unrecognized", [])),
        "__WIREFRAME_THICKNESS__": repr(wireframe_thickness),
        "__WIREFRAME_ENABLED__": repr(bool(profile["wireframe"])),
        "__SUBDIVISIONS__": repr(max(0, int(profile.get("subdivisions", 0)))),
        "__RECALCULATE_NORMALS__": repr(bool(profile.get("recalculate_normals", False))),
        "__SHADOWS__": repr(bool(profile["shadows"])),
        "__GROUND_SHADOWS__": repr(bool(profile["ground_shadows"])),
        "__ENGINE__": repr(str(profile["engine"])),
        "__AMBIENT_OCCLUSION__": repr(bool(profile["ambient_occlusion"])),
        "__AMBIENT_OCCLUSION_STRENGTH__": repr(max(0.0, float(profile["ambient_occlusion_strength"]))),
        "__AMBIENT_OCCLUSION_DISTANCE__": repr(max(0.001, float(profile.get("ambient_occlusion_distance", 1.0)))),
        "__SHADE_SMOOTH__": repr(str(profile["shade"]).casefold() == "smooth"),
        "__BASE_COLOR_WITH_ALPHA__": repr(tuple(profile["base_color"][:3]) + (float(profile["base_color"][3]) if len(profile["base_color"]) >= 4 else float(profile["alpha"]),)),
        "__BASE_ALPHA__": repr(float(profile["base_color"][3]) if len(profile["base_color"]) >= 4 else float(profile["alpha"])),
        "__WIRE_COLOR__": repr(tuple(profile["wire_color"])),
        "__WIRE_ALPHA__": repr(float(profile["wire_color"][3]) if len(profile["wire_color"]) >= 4 else 1.0),
        "__METALLIC__": repr(float(profile["metallic"])),
        "__ROUGHNESS__": repr(float(profile["roughness"])),
        "__COAT_WEIGHT__": repr(float(profile["coat_weight"])),
        "__COAT_ROUGHNESS__": repr(float(profile["coat_roughness"])),
        "__ALPHA__": repr(float(profile["alpha"])),
        "__CLIP_NEAR__": repr(float(profile["clip_near"])),
        "__CLIP_FAR__": repr(float(profile["clip_far"])),
        "__FILM_TRANSPARENT__": repr(bool(profile["film_transparent"])),
    }
    for token, value in replacements.items():
        script = script.replace(token, value)
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_eevee_wire_") as temp_dir:
            temp = Path(temp_dir)
            script_path, image_path, status_path = temp / "render.py", temp / ("preview" + output_extensions[output_format]), temp / "status.txt"
            error_path = temp / "blender_error.log"
            script_path.write_text(script, encoding="utf-8")
            error_stream = error_path.open("w", encoding="utf-8", errors="replace")
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": error_stream}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            template_path = Path(__file__).resolve().parent / "files" / str(profile["template"])
            if not template_path.is_file():
                if progress_callback:
                    progress_callback(99, f"Scene de rendu introuvable : {template_path}")
                error_stream.close()
                return None
            proc = subprocess.Popen(
                [blender, "--background", str(template_path), "--python", str(script_path), "--",
                 str(path.resolve()), str(image_path), str(status_path),
                 kind_override or ("abc" if suffix == ".abc" else "blend" if suffix == ".blend" else "fbx" if suffix == ".fbx" else "obj"), str(profile["resolution"][0]), output_format],
                **kwargs,
            )
            last_status = ""
            # Les subdivisions des modeles complexes peuvent depasser 90 s
            # avant meme le calcul du cadrage. L'annulation reste disponible.
            deadline = time.monotonic() + (600 if int(profile.get("subdivisions", 0)) > 0 else 300)
            if turntable_output:
                deadline = time.monotonic() + 3600
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    error_stream.close()
                    return None
                try:
                    current = status_path.read_text(encoding="utf-8")
                    if current and current != last_status:
                        last_status = current
                        percent, message = current.split("|", 1)
                        if progress_callback:
                            progress_callback(int(percent), message)
                        if turntable_output:
                            deadline = time.monotonic() + 600
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    proc.terminate()
                    proc.wait(timeout=3)
                    error_stream.close()
                    return None
                time.sleep(0.1)
            error_stream.close()
            prepared = str(profile.get("_turntable_prepared_scene", ""))
            if proc.returncode == 0 and prepared and Path(prepared).is_file():
                image = QImage(1, 1, QImage.Format_ARGB32)
                image.fill(0)
                return image
            if proc.returncode != 0 or not image_path.is_file():
                if progress_callback:
                    try:
                        percent, message = last_status.split("|", 1)
                        details = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
                        detail = next((line.strip() for line in reversed(details) if line.strip()), "")
                        try:
                            _write_render_log(DATA_DIR,
                                              f"[99%] {path.name} — Echec du rendu\n" + "\n".join(details[-200:]),
                                              str(path), "turntable" if turntable_output else "image")
                        except OSError:
                            pass
                        progress_callback(99, f"Echec Eevee : {detail or message}")
                    except ValueError:
                        pass
                return None
            image = QImage(str(image_path))
            if image.isNull():
                return None
            return _apply_render_background(image.copy(), profile)
    except (OSError, subprocess.SubprocessError):
        return None
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
    eevee_image = _render_wireframe_eevee(path, max_dim, progress_callback, cancel_event, render_mode=render_mode, profile_override=profile_override)
    if eevee_image is not None:
        return eevee_image
    if cancel_event is not None and cancel_event.is_set():
        return None
    template_path = Path(__file__).resolve().parent / "files" / str(_render_profile(render_mode, profile_override)["template"])
    if _blender_executable() and template_path.is_file():
        return None
    blender = _blender_executable()
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
                if source_is_hdf5 and progress_callback:
                    progress_callback(99, "Import refusé : archive HDF5 héritée; réexport requis en Ogawa")
                return None
            if not meshfile.is_file() or meshfile.stat().st_size == 0:
                return None
            return _decode_obj_image(
                meshfile, max_dim,
                progress_callback=(lambda pct, msg: progress_callback(35 + int(pct * 0.64), msg))
                if progress_callback else None, cancel_event=cancel_event, render_mode=render_mode,
                profile_override=profile_override,
            )
    except (OSError, subprocess.SubprocessError):
        return None


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
            return _render_wireframe_eevee(abc_path, max_dim, progress_callback, cancel_event, kind_override="maya", render_mode=render_mode, profile_override=profile_override)
    except (OSError, subprocess.SubprocessError):
        return None


def _rasterize_obj_numpy(
    transformed: list[tuple[float, float, float]], faces: list[tuple[int, int, int]],
    vertex_shade: list[float], max_dim: int, scale: float, ox: float, oy: float,
    base_rgb: tuple[int, int, int], wire_edges: list[tuple[int, int]],
    camera_depth: list[float], near_clip: float, far_clip: float, progress_callback=None,
) -> QImage:
    """Construit un z-buffer pour masquer les arêtes cachées et trace un
    wireframe opaque, sans coloration ni occlusion ambiante."""
    supersample = 2.0 / 3.0
    render_dim = int(round(max_dim * supersample))
    r_scale, r_ox, r_oy = scale * supersample, ox * supersample, oy * supersample

    n = len(transformed)
    xs = np.empty(n, dtype=np.float64)
    ys = np.empty(n, dtype=np.float64)
    zs = np.empty(n, dtype=np.float64)
    for i, (x, y, z) in enumerate(transformed):
        xs[i], ys[i], zs[i] = x, y, z
    screen_x = xs * r_scale + r_ox
    screen_y = -zs * r_scale + r_oy
    depth_values = np.asarray(camera_depth, dtype=np.float64)

    color_buf = np.empty((render_dim, render_dim, 3), dtype=np.uint8)
    color_buf[:, :] = (238, 240, 242)
    depth_buf = np.full((render_dim, render_dim), -np.inf, dtype=np.float64)

    face_step = max(1, len(faces) // 20)
    if progress_callback:
        progress_callback(27, "Projection et préparation du z-buffer")
    for face_index, (a, b, c) in enumerate(faces):
        if progress_callback and face_index % face_step == 0:
            progress_callback(28 + int(face_index * 55 / max(1, len(faces))),
                              f"Rendu des faces : {face_index + 1}/{len(faces)}")
        x0, y0, z0 = screen_x[a], screen_y[a], depth_values[a]
        x1, y1, z1 = screen_x[b], screen_y[b], depth_values[b]
        x2, y2, z2 = screen_x[c], screen_y[c], depth_values[c]

        min_x = max(int(math.floor(min(x0, x1, x2))), 0)
        max_x = min(int(math.ceil(max(x0, x1, x2))), render_dim - 1)
        min_y = max(int(math.floor(min(y0, y1, y2))), 0)
        max_y = min(int(math.ceil(max(y0, y1, y2))), render_dim - 1)
        if min_x > max_x or min_y > max_y:
            continue

        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-9:
            continue   # triangle degenere (aire nulle en projection)

        px = np.arange(min_x, max_x + 1, dtype=np.float64) + 0.5
        py = np.arange(min_y, max_y + 1, dtype=np.float64) + 0.5
        gx, gy = np.meshgrid(px, py)

        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denom
        l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denom
        l2 = 1.0 - l0 - l1

        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue

        z_interp = l0 * z0 + l1 * z1 + l2 * z2
        region_depth = depth_buf[min_y:max_y + 1, min_x:max_x + 1]
        in_clip_range = (z_interp <= -near_clip) & (z_interp >= -far_clip)
        closer = inside & in_clip_range & (z_interp > region_depth)
        if not closer.any():
            continue

        region_depth[closer] = z_interp[closer]

    # Conversion de l'image supersamplee : le wireframe est dessine avant
    # cette reduction pour rester net et fin dans l'apercu final.
    rgb8 = np.clip(color_buf, 0, 255).astype(np.uint8)
    rgb8 = np.ascontiguousarray(rgb8)
    # Dessine seulement les aretes des faces source, a la resolution
    # supersamplee, puis reduit proprement : les diagonales creees par la
    # triangulation interne ne deviennent pas visibles.
    image = QImage(rgb8.data, render_dim, render_dim, render_dim * 3, QImage.Format_RGB888).copy()
    if wire_edges:
        if progress_callback:
            progress_callback(93, "Traçage du wireframe des faces")
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(0, 0, 0), 0.75))
        edge_step = max(1, len(wire_edges) // 6)
        for edge_index, (a, b) in enumerate(wire_edges):
            x0, y0, z0 = screen_x[a], screen_y[a], depth_values[a]
            x1, y1, z1 = screen_x[b], screen_y[b], depth_values[b]
            steps = max(1, int(math.ceil(max(abs(x1 - x0), abs(y1 - y0)))))
            run_start = None
            previous = None
            for step in range(steps + 1):
                t = step / steps
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                ix, iy = int(round(x)), int(round(y))
                visible = False
                if 0 <= ix < render_dim and 0 <= iy < render_dim:
                    surface_depth = depth_buf[iy, ix]
                    edge_depth = z0 + (z1 - z0) * t
                    visible = np.isfinite(surface_depth) and edge_depth >= surface_depth - 0.025
                if visible:
                    point = QPointF(x, y)
                    if run_start is None:
                        run_start = point
                    previous = point
                elif run_start is not None:
                    if previous is not None:
                        painter.drawLine(run_start, previous)
                    run_start = previous = None
            if run_start is not None and previous is not None:
                painter.drawLine(run_start, previous)
            if progress_callback and edge_index % edge_step == 0:
                progress_callback(93 + int(edge_index * 6 / max(1, len(wire_edges))),
                                  f"Wireframe : {edge_index + 1}/{len(wire_edges)} arêtes")
        painter.end()
    if progress_callback:
        progress_callback(99, "Mise à l’échelle et finalisation")
    return image.scaled(max_dim, max_dim, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _rasterize_obj_qpainter(
    transformed: list[tuple[float, float, float]], faces: list[tuple[int, int, int]],
    vertex_shade: list[float], max_dim: int, to_screen, base_rgb: tuple[int, int, int],
    wire_edges: list[tuple[int, int]], progress_callback=None,
) -> QImage:
    """Repli opaque sans shader : dessine uniquement les aretes du maillage."""
    image = QImage(max_dim, max_dim, QImage.Format_RGB32)
    image.fill(QColor(238, 240, 242))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(QColor(0, 0, 0), 0.7))
    edge_step = max(1, len(wire_edges) // 8)
    for edge_index, (a, b) in enumerate(wire_edges):
        painter.drawLine(to_screen(transformed[a]), to_screen(transformed[b]))
        if progress_callback and edge_index % edge_step == 0:
            progress_callback(35 + int(edge_index * 63 / max(1, len(wire_edges))),
                              f"Wireframe : {edge_index + 1}/{len(wire_edges)} aretes")
    painter.end()
    if progress_callback:
        progress_callback(99, "Finalisation de l'image opaque")
    return image

def _decode_psd_thumbnail(path: Path) -> QImage | None:
    """Extrait la vignette JPEG que Photoshop embarque dans un .psd/.psb
    (ressource d'image ID 1036, "Thumbnail Resource (Photoshop 5.0)")
    plutot que de composer nous-memes les calques (hors de portee ici) :
    presente dans la quasi-totalite des fichiers Photoshop modernes, sauf
    enregistrement explicitement desactive. None si absente, fichier
    illisible, ou pas un vrai PSD (signature "8BPS" manquante)."""
    try:
        with open(path, "rb") as f:
            header = f.read(26)
            if len(header) < 26 or header[:4] != b"8BPS":
                return None
            length_bytes = f.read(4)
            if len(length_bytes) < 4:
                return None
            # Section "Color Mode Data" (uniquement utile pour le mode
            # Indexe/Duotone, pas pour la vignette) : on la saute.
            f.seek(int.from_bytes(length_bytes, "big"), 1)
            res_len_bytes = f.read(4)
            if len(res_len_bytes) < 4:
                return None
            data = f.read(int.from_bytes(res_len_bytes, "big"))
    except OSError:
        return None

    pos, n = 0, len(data)
    while pos + 12 <= n:
        if data[pos:pos + 4] != b"8BIM":
            break   # bloc de ressource corrompu/inattendu : mieux vaut s'arreter que boucler dans du bruit
        resource_id = int.from_bytes(data[pos + 4:pos + 6], "big")
        name_len = data[pos + 6]
        name_block = 1 + name_len
        if name_block % 2:   # chaine Pascal (longueur + nom) paddee au pair
            name_block += 1
        size_pos = pos + 6 + name_block
        if size_pos + 4 > n:
            break
        data_size = int.from_bytes(data[size_pos:size_pos + 4], "big")
        payload_pos = size_pos + 4
        if payload_pos + data_size > n:
            break
        if resource_id == 1036:
            # Format (4) + largeur/hauteur/widthbytes/taille totale (4x4) +
            # taille compressee (4) + bits/pixel (2) + plans (2) = 28 octets
            # d'entete, suivis directement du flux JPEG lui-meme.
            if data_size > 28 and int.from_bytes(data[payload_pos:payload_pos + 4], "big") == 1:
                jpeg_size = int.from_bytes(data[payload_pos + 20:payload_pos + 24], "big")
                jpeg_data = data[payload_pos + 28:payload_pos + 28 + jpeg_size]
                if jpeg_data:
                    image = QImage.fromData(jpeg_data, "JPEG")
                    if not image.isNull():
                        return image
            return None
        pos = payload_pos + data_size + (data_size % 2)
    return None


def _oiiotool_executable() -> str | None:
    """Trouve l'utilitaire OpenImageIO livre avec Arnold ou Maya."""
    found = shutil.which("oiiotool")
    if found:
        return found
    roots = []
    maya_location = os.environ.get("MAYA_LOCATION")
    if maya_location:
        roots.append(Path(maya_location))
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    roots.extend((program_files / "Autodesk" / "Arnold", program_files / "Autodesk"))
    candidates = []
    for root in roots:
        for pattern in ("Maya*/bin/oiiotool.exe", "*/bin/oiiotool.exe", "bin/oiiotool.exe"):
            try:
                candidates.extend(root.glob(pattern))
            except OSError:
                pass
    candidates = sorted({p for p in candidates if p.is_file()}, reverse=True)
    return str(candidates[0]) if candidates else None


def _decode_tx_image(path: Path, max_dim: int) -> QImage | None:
    """Convertit une texture Arnold .tx en petite image lisible par Qt."""
    oiiotool = _oiiotool_executable()
    if not oiiotool:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_tx_preview_") as temp_dir:
            output_path = Path(temp_dir) / "preview.png"
            tool_dir = str(Path(oiiotool).resolve().parent)
            env = os.environ.copy()
            env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                [oiiotool, str(path.resolve()), "--fit", f"{max_dim}x{max_dim}", "-o", str(output_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=45, check=False, env=env,
            )
            if result.returncode != 0 or not output_path.is_file():
                return None
            image = QImage(str(output_path))
            return image.copy() if not image.isNull() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _decode_exr_image(path: Path, max_dim: int) -> QImage | None:
    """Convertit le rendu HDR d'un .exr en image affichable : tone-mapping
    Reinhard simple (gere sans les cramer les valeurs > 1, frequentes en
    lineaire) puis gamma sRGB approche, sur le premier calque RGB(A) trouve
    (une passe "beaute", pas les innombrables AOV utilitaires que peut
    contenir un .exr multi-couches). None si le fichier n'a pas de calque
    exploitable, est illisible, ou si le paquet OpenEXR n'est pas installe
    (voir _OPENEXR_AVAILABLE)."""
    if not _OPENEXR_AVAILABLE:
        return None
    try:
        channels = OpenEXR.File(str(path)).parts[0].channels
        pixels = None
        for key in ("RGBA", "RGB", "rgba", "rgb"):
            if key in channels:
                pixels = channels[key].pixels
                break
        if pixels is None and "R" in channels and "G" in channels and "B" in channels:
            pixels = np.stack(
                [channels["R"].pixels, channels["G"].pixels, channels["B"].pixels], axis=-1
            )
    except Exception:
        return None
    if pixels is None or pixels.ndim != 3 or pixels.shape[2] < 3:
        return None

    rgb = np.clip(pixels[..., :3].astype(np.float32), 0.0, None)
    rgb = rgb / (1.0 + rgb)             # tone-mapping Reinhard
    rgb = np.power(rgb, 1.0 / 2.2)      # gamma sRGB approche
    rgb8 = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)

    h, w = rgb8.shape[:2]
    longest = max(h, w)
    if longest > max_dim:
        # Sous-echantillonnage simple (pas d'interpolation) avant de laisser
        # Qt remettre a l'echelle exacte au dessin : suffisant pour une
        # vignette, evite de garder une pleine resolution HDR en memoire
        # plus longtemps que necessaire.
        step = max(1, longest // max_dim)
        rgb8 = rgb8[::step, ::step]

    rgb8 = np.ascontiguousarray(rgb8)
    h, w = rgb8.shape[:2]
    # .copy() : QImage(buffer, ...) ne fait que referencer `rgb8.data`, qui
    # serait libere avec le tableau numpy des la sortie de cette fonction.
    return QImage(rgb8.data, w, h, w * 3, QImage.Format_RGB888).copy()


def _decode_hdr_image(path: Path, max_dim: int) -> QImage | None:
    """Convertit un .hdr (Radiance RGBE) en image affichable — MEME tone-
    mapping Reinhard + gamma sRGB que _decode_exr_image (voir sa remarque)
    — voir la remarque de l'utilisateur, "possible de faire les apercus
    des hdri ?". Parseur RGBE MAISON (juste numpy, AUCUNE dependance
    externe contrairement a .exr/OpenEXR — le format Radiance est
    documente/stable et volontairement simple) : supporte le format RLE
    "nouveau style" (l'immense majorite des .hdr generes par les outils
    actuels, HDRI Haven/Poly Haven inclus) ET le format PLAT (non
    compresse) — PAS l'ancien RLE "repeat previous pixel" (marginal,
    fichiers tres anciens des annees 1990) : None dans ce cas, comme pour
    tout fichier illisible/non exploitable ailleurs dans ce module."""
    if not _NUMPY_AVAILABLE:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        pos = data.index(b"\n") + 1
        if not data.startswith(b"#?"):
            return None
        # En-tete texte (FORMAT=.../EXPOSURE=.../commentaires) jusqu'a la
        # PREMIERE ligne vide.
        while True:
            nl = data.index(b"\n", pos)
            if data[pos:nl] == b"":
                pos = nl + 1
                break
            pos = nl + 1
        # Ligne de resolution ("-Y H +X W", quasi-universelle — les
        # variantes retournees/miroir sont ignorees ici, sans consequence
        # pour une simple vignette).
        nl = data.index(b"\n", pos)
        res_parts = data[pos:nl].decode("ascii", errors="ignore").split()
        pos = nl + 1
        if len(res_parts) != 4:
            return None
        h, w = int(res_parts[1]), int(res_parts[3])
        if h <= 0 or w <= 0:
            return None
    except (ValueError, IndexError, UnicodeDecodeError):
        return None

    rgbe = np.zeros((h, w, 4), dtype=np.uint8)
    try:
        for y in range(h):
            if pos + 4 > len(data):
                return None
            b0, b1, b2, b3 = data[pos], data[pos + 1], data[pos + 2], data[pos + 3]
            if b0 == 2 and b1 == 2 and 8 <= w < 0x8000 and (b2 << 8 | b3) == w:
                pos += 4
                row = np.zeros((4, w), dtype=np.uint8)
                for channel in range(4):
                    x = 0
                    while x < w:
                        count = data[pos]
                        pos += 1
                        if count > 128:
                            count -= 128
                            row[channel, x:x + count] = data[pos]
                            pos += 1
                        else:
                            row[channel, x:x + count] = np.frombuffer(
                                data, dtype=np.uint8, count=count, offset=pos)
                            pos += count
                        x += count
                rgbe[y] = row.T
            else:
                # Ancien format PLAT (4 octets/pixel, pas de RLE) — repli
                # simple, pas l'ancien RLE "repeat previous pixel" (voir
                # remarque de tete).
                row = np.frombuffer(data, dtype=np.uint8, count=w * 4, offset=pos).reshape(w, 4)
                pos += w * 4
                rgbe[y] = row
    except (ValueError, IndexError):
        return None

    e = rgbe[..., 3].astype(np.int32)
    # Decodage RGBE standard (voir rgbe2float de Radiance) : mantisse
    # (0-255) * 2^(exposant-128-8), 0 si exposant nul (pixel noir).
    scale = np.where(e > 0, np.exp2((e - 136).astype(np.float32)), 0.0)
    rgb = rgbe[..., :3].astype(np.float32) * scale[..., None]

    rgb = np.clip(rgb, 0.0, None)
    rgb = rgb / (1.0 + rgb)             # tone-mapping Reinhard
    rgb = np.power(rgb, 1.0 / 2.2)      # gamma sRGB approche
    rgb8 = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)

    hh, ww = rgb8.shape[:2]
    longest = max(hh, ww)
    if longest > max_dim:
        step = max(1, longest // max_dim)
        rgb8 = rgb8[::step, ::step]
    rgb8 = np.ascontiguousarray(rgb8)
    hh, ww = rgb8.shape[:2]
    return QImage(rgb8.data, ww, hh, ww * 3, QImage.Format_RGB888).copy()


VIDEO_PREVIEW_SEEK_FRACTION = 0.1   # position dans la video (evite les frames noires/logo d'intro a 0%)
VIDEO_PREVIEW_TIMEOUT_MS = 6000     # securite : fichier corrompu, codec manquant, partage reseau lent...


def _decode_video_frame(path: Path, max_dim: int) -> QImage | None:
    """Extrait une frame a ~10% de la duree d'une video via QtMultimedia
    (QMediaPlayer + QVideoSink, module fourni avec PySide6 — ffmpeg deja
    embarque, aucune dependance externe). L'API est asynchrone (chargement
    et decodage se font en arriere-plan) : cette fonction tourne une
    QEventLoop locale jusqu'a recevoir une frame ou expirer
    (VIDEO_PREVIEW_TIMEOUT_MS), pour rester utilisable comme les autres
    decodeurs synchrones d'appel (cache par file_image_pixmap). None si
    aucune frame n'a pu etre obtenue a temps."""
    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    player.setSource(QUrl.fromLocalFile(str(path)))

    loop = QEventLoop()
    result: dict = {}

    def on_frame(frame):
        if frame.isValid() and "image" not in result:
            result["image"] = frame.toImage()
            loop.quit()

    def on_status(status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            duration = player.duration()
            if duration > 0:
                player.setPosition(int(duration * VIDEO_PREVIEW_SEEK_FRACTION))
            # setPosition() seul, meme a l'arret, ne fait pas toujours
            # decoder/emettre une frame selon le backend — play() force le
            # pipeline a produire au moins la premiere image utile, qu'on
            # recupere puis on coupe aussitot (voir on_frame).
            player.play()
        elif status in (QMediaPlayer.MediaStatus.InvalidMedia, QMediaPlayer.MediaStatus.NoMedia):
            loop.quit()

    def on_error(*_args):
        loop.quit()

    sink.videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(on_error)

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(VIDEO_PREVIEW_TIMEOUT_MS)

    loop.exec()
    player.stop()

    image = result.get("image")
    if image is None or image.isNull():
        return None
    if max(image.width(), image.height()) > max_dim:
        image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def _oda_file_converter() -> str | None:
    """Trouve ODA File Converter, necessaire pour convertir un DWG en DXF."""
    configured = os.environ.get("ODA_FILE_CONVERTER")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
    if found:
        return found
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ODA"]
    roots.append(Path(r"C:\Program Files\ODA"))
    for root in roots:
        try:
            candidates = sorted(root.glob("**/ODAFileConverter.exe"), reverse=True)
            if candidates:
                return str(candidates[0])
        except OSError:
            continue
    return None


def _decode_dwg_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Convertit le DWG en DXF puis rend le model space en image 2D."""
    converter = _oda_file_converter()
    if not converter:
        if progress_callback:
            progress_callback(99, "ODA File Converter requis pour lire les fichiers DWG")
        return None
    try:
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf import recover
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from ezdxf.addons.drawing.properties import LayoutProperties
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:
        if progress_callback:
            progress_callback(99, f"Dependances d'apercu DWG manquantes : {exc}")
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="pipe_dwg_preview_") as temp_dir:
            output_dir = Path(temp_dir)
            log_path = output_dir / "oda_converter.log"
            log_stream = log_path.open("w", encoding="utf-8", errors="replace")
            if progress_callback:
                progress_callback(8, "Conversion DWG vers DXF")
            kwargs = {"stdout": log_stream, "stderr": log_stream}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                [converter, str(path.parent), str(output_dir), "ACAD2018", "DXF", "0", "0", path.name],
                **kwargs,
            )
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
                        progress_callback(99, "Delai depasse pendant la conversion DWG")
                    return None
                time.sleep(0.1)
            log_stream.close()
            dxf_path = next(
                (candidate for candidate in output_dir.glob("*") if candidate.suffix.lower() == ".dxf"),
                None,
            )
            if proc.returncode != 0 or dxf_path is None:
                if progress_callback:
                    progress_callback(99, "Conversion DWG impossible avec ODA File Converter")
                return None
            if progress_callback:
                progress_callback(42, "Lecture du dessin 2D")
            try:
                doc, auditor = recover.readfile(str(dxf_path))
            except Exception:
                doc = ezdxf.readfile(str(dxf_path))
                auditor = None
            if auditor is not None and auditor.errors:
                if progress_callback:
                    progress_callback(99, "Le dessin DXF converti contient des erreurs")
                return None
            layout = doc.modelspace()
            with _DWG_RENDER_LOCK:
                figure = Figure(figsize=(6, 6), dpi=max(96, int(max_dim / 6)))
                canvas = FigureCanvasAgg(figure)
                axes = figure.add_axes((0, 0, 1, 1))
                axes.set_aspect("equal", adjustable="datalim")
                context = RenderContext(doc)
                properties = LayoutProperties.from_layout(layout)
                properties.set_colors("#17191b", "#d6d9dc")
                if progress_callback:
                    progress_callback(68, "Rendu du model space en 2D")
                Frontend(context, MatplotlibBackend(axes)).draw_layout(
                    layout, finalize=True, layout_properties=properties
                )
                canvas.draw()
                buffer = io.BytesIO()
                canvas.print_png(buffer)
            image = QImage.fromData(buffer.getvalue(), "PNG")
            if image.isNull():
                return None
            if max(image.width(), image.height()) > max_dim:
                image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return image
    except (OSError, subprocess.SubprocessError, ezdxf.DXFStructureError) as exc:
        if progress_callback:
            progress_callback(99, f"Erreur de rendu DWG 2D : {exc}")
        return None


def _read_preview_pixmap(path: Path, mtime: float) -> tuple[QPixmap | None, bool]:
    """Load a current cached preview, or keep the last render as stale fallback."""
    key = str(path)
    cached = _file_image_cache.get(key)
    if cached and cached[0] == mtime:
        column_cached = _file_image_column_cache.get(key)
        if column_cached is None or column_cached[0] != mtime:
            _cache_file_preview(key, mtime, cached[1], key in _STALE_PREVIEW_PATHS)
        return cached[1], key in _STALE_PREVIEW_PATHS
    current_path = _file_image_cache_path(path, mtime)
    if current_path.is_file():
        pix = QPixmap(str(current_path))
        if not pix.isNull():
            is_stale = key in _STALE_PREVIEW_PATHS
            if not is_stale:
                _STALE_PREVIEW_PATHS.discard(key)
            _cache_file_preview(key, mtime, pix, is_stale)
            if not _preview_cache_metadata_matches(path, current_path):
                _record_preview_cache(path, mtime, current_path)
            return pix, is_stale
    miss_key = (key, int(mtime))
    if miss_key in _PREVIEW_STALE_LOOKUP_MISSES:
        return None, False
    # Evite meme la lecture des sidecars individuels dans un dossier qui ne
    # contient aucun apercu image. Cas courant pour une serie de scenes Maya
    # en attente du balayage d'inactivite : seul le premier fichier provoque
    # le scan du dossier de cache.
    global _PREVIEW_CACHE_HAS_PNG
    if _PREVIEW_CACHE_HAS_PNG is None:
        try:
            _PREVIEW_CACHE_HAS_PNG = next(FILE_IMAGE_DISK_CACHE_DIR.glob("*.png"), None) is not None
        except OSError:
            _PREVIEW_CACHE_HAS_PNG = False
    if not _PREVIEW_CACHE_HAS_PNG:
        if len(_PREVIEW_STALE_LOOKUP_MISSES) >= 4096:
            _PREVIEW_STALE_LOOKUP_MISSES.clear()
        _PREVIEW_STALE_LOOKUP_MISSES.add(miss_key)
        return None, False
    stale_path = _find_stale_preview_cache(path, mtime, current_path)
    if stale_path is not None:
        pix = QPixmap(str(stale_path))
        if not pix.isNull():
            _STALE_PREVIEW_PATHS.add(key)
            _cache_file_preview(key, mtime, pix, True)
            if not _preview_cache_metadata_matches(path, stale_path):
                try:
                    old_mtime = float(stale_path.stem.rsplit("_", 1)[1])
                except (ValueError, IndexError):
                    old_mtime = 0.0
                _record_preview_cache(path, old_mtime, stale_path)
            return pix, True
    _STALE_PREVIEW_PATHS.discard(key)
    if len(_PREVIEW_STALE_LOOKUP_MISSES) >= 4096:
        _PREVIEW_STALE_LOOKUP_MISSES.clear()
    _PREVIEW_STALE_LOOKUP_MISSES.add(miss_key)
    return None, False


def _decode_2d_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Decode all static 2D preview formats to a bounded QImage."""
    suffix = path.suffix.lower()
    if progress_callback:
        progress_callback(12, f"Lecture de l'image 2D {suffix}")
    if suffix in DWG_EXTENSIONS:
        image = _decode_dwg_image(path, max_dim, progress_callback, cancel_event)
    elif suffix in PSD_EXTENSIONS:
        image = _decode_psd_thumbnail(path)
    elif suffix in EXR_EXTENSIONS:
        image = _decode_exr_image(path, max_dim)
    elif suffix in HDR_EXTENSIONS:
        image = _decode_hdr_image(path, max_dim)
    elif suffix in TX_EXTENSIONS:
        image = _decode_tx_image(path, max_dim)
    else:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > max_dim:
            scale = max_dim / max(size.width(), size.height())
            reader.setScaledSize(QSize(
                max(1, round(size.width() * scale)), max(1, round(size.height() * scale)),
            ))
        image = reader.read()
    if image is None or image.isNull():
        return None
    if max(image.width(), image.height()) > max_dim:
        image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def file_image_pixmap(path: Path, asynchronous: bool = False) -> QPixmap | None:
    """Image du fichier `path` lui-meme (pas une vignette perso a choisir :
    c'est le fichier) — ou, pour un .obj (voir OBJ_EXTENSIONS), un rendu
    genere (voir _decode_obj_image), ou pour un .psd/.psb (voir
    PSD_EXTENSIONS), sa vignette JPEG embarquee (voir
    _decode_psd_thumbnail) — reduite au chargement si besoin (voir
    FILE_IMAGE_CACHE_MAX_DIM) puis mise en cache par date de
    modification, en memoire (cache borne, voir _bounded_cache_set) ET sur
    disque (voir FILE_IMAGE_DISK_CACHE_DIR) : la generation/reduction depuis
    le fichier source, plus couteuse, ne se refait qu'une fois par fichier
    (jusqu'a sa prochaine modification), meme apres redemarrage de l'appli.
    Le recadrage carre final se fait au dessin (voir _paint_row_image), a
    la taille reelle de la ligne. None si le fichier n'est plus lisible ou
    n'a pas de contenu exploitable."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    cache_path = _file_image_cache_path(path, mtime)
    if asynchronous:
        cached = _file_image_column_cache.get(key)
        if cached and (cached[0] == mtime or key in _STALE_PREVIEW_PATHS):
            if key in _STALE_PREVIEW_PATHS and path.suffix.lower() in TWO_D_IMAGE_EXTENSIONS:
                _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True, force_render=True)
            return cached[1]
        cached_full = _file_image_cache.get(key)
        if cached_full and (cached_full[0] == mtime or key in _STALE_PREVIEW_PATHS):
            _cache_file_preview(key, mtime, cached_full[1], key in _STALE_PREVIEW_PATHS)
            return _file_image_column_cache[key][1]
        miss_key = (key, int(mtime))
        if miss_key in _FILE_IMAGE_COLUMN_LOOKUP_MISSES:
            return None
        suffix = path.suffix.lower()
        # Les vignettes sont chargées/décodées en worker pour que l'ouverture
        # d'une colonne ne fasse jamais de lecture image sur le thread UI.
        if suffix in TWO_D_IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(
                path, mtime, quiet=True, cache_only=False, force_render=key in _STALE_PREVIEW_PATHS
            )
        elif suffix in OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True, cache_only=True)
        elif suffix in DWG_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True, cache_only=False)
        return None
    cached_pix, is_stale = _read_preview_pixmap(path, mtime)
    if cached_pix is not None:
        if is_stale and path.suffix.lower() in TWO_D_IMAGE_EXTENSIONS:
            _PREVIEW_DECODE_MANAGER.request(path, mtime, quiet=True)
        return cached_pix

    suffix = path.suffix.lower()
    if suffix in OBJ_EXTENSIONS | ABC_EXTENSIONS:
        # Les rendus OBJ/ABC sont explicites (menu contextuel) ou lances par
        # le balayage d'inactivite ; ne pas les demarrer a la simple selection.
        return None
    elif suffix in DWG_EXTENSIONS:
        # Conversion DWG couteuse : elle est generee en arriere-plan.
        _PREVIEW_DECODE_MANAGER.request(path, mtime)
        return None
    elif suffix in BLEND_EXTENSIONS:
        # Un .blend ne se rend qu'a la demande via son menu contextuel;
        # une fois genere, son cache est affiche comme les autres apercus.
        return None
    elif suffix in MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS:
        # Les scenes Maya se rendent a la demande ou pendant le balayage d'inactivite.
        return None
    elif suffix in TWO_D_IMAGE_EXTENSIONS:
        image = _decode_2d_image(path, FILE_IMAGE_CACHE_MAX_DIM)
        if image is None or image.isNull():
            return None
    elif suffix in VIDEO_EXTENSIONS:
        image = _decode_video_frame(path, FILE_IMAGE_CACHE_MAX_DIM)
        if image is None or image.isNull():
            return None
    else:
        return None
    pix = QPixmap.fromImage(image)
    _STALE_PREVIEW_PATHS.discard(key)
    _cache_file_preview(key, mtime, pix)
    try:
        was_new = not FILE_IMAGE_DISK_CACHE_DIR.is_dir()
        FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if was_new:
            _set_hidden(FILE_IMAGE_DISK_CACHE_DIR)
        if pix.save(str(cache_path), "PNG"):
            global _PREVIEW_CACHE_HAS_PNG
            _PREVIEW_CACHE_HAS_PNG = True
            _set_hidden(cache_path)
            _prune_stale_disk_cache(cache_path)
            _record_preview_cache(path, mtime, cache_path)
    except OSError:
        pass
    return pix


def _cached_file_image_pixmap(path: Path, render_mode: str = "low") -> QPixmap | None:
    """Lit seulement le cache d'un apercu, sans lancer sa generation."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if render_mode == "high":
        cached = _file_image_high_cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        image_path = _file_image_cache_path(path, mtime, render_mode="high")
        pix = QPixmap(str(image_path)) if image_path.is_file() else QPixmap()
        if not pix.isNull():
            _bounded_cache_set(_file_image_high_cache, str(path), (mtime, pix))
        return pix if not pix.isNull() else None
    pix, _is_stale = _read_preview_pixmap(path, mtime)
    return pix


class _PreviewDecodeSignals(QObject):
    finished = Signal(object, str, float, object)
    progress = Signal(str, int, str)


def _set_render_execution_state(flags: int) -> int | None:
    """Requete Windows propre au thread de rendu ; ne modifie pas le plan d'energie."""
    if sys.platform != "win32":
        return None
    try:
        setter = ctypes.windll.kernel32.SetThreadExecutionState
        setter.argtypes = [ctypes.c_uint32]
        setter.restype = ctypes.c_uint32
        previous = setter(flags)
        return int(previous) if previous else None
    except (AttributeError, OSError):
        return None


def _rename_render_directory(source: Path, destination: Path) -> None:
    """Absorbe les verrous Windows brefs sans recalculer les 72 images."""
    for attempt in range(5):
        try:
            source.rename(destination)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1 * (2 ** attempt))


def _render_turntable_frame(prepared: Path, target: Path, index: int, cancel_event=None,
                            progress_callback=None) -> bool:
    """Un processus par image : sa RAM et ses buffers GPU sont liberes a la sortie."""
    blender = _blender_executable()
    if not blender or (cancel_event is not None and cancel_event.is_set()):
        return False
    temporary = target.with_name(target.stem + ".tmp.png")
    expression = (
        "import bpy, os; bpy.context.preferences.edit.use_global_undo=False; "
        f"s=bpy.context.scene; s.frame_set({index + 1}); "
        f"s.render.filepath={str(temporary)!r}; s.render.use_overwrite=True; "
        "s.render.use_placeholder=False; bpy.ops.render.render(write_still=True); "
        f"os.replace({str(temporary)!r}, {str(target)!r})")
    error_path = prepared.parent / "render.log"
    process = None
    try:
        with error_path.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen([blender, "-b", str(prepared), "--python-expr", expression],
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 600
            while process.poll() is None:
                canceled = cancel_event is not None and cancel_event.is_set()
                if canceled or time.monotonic() > deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if not canceled and progress_callback:
                        progress_callback(99, f"Erreur du turntable : delai de 10 minutes depasse a l'image {index + 1}/72")
                    return False
                time.sleep(0.1)
        if process.returncode == 0 and not QImage(str(target)).isNull():
            return True
        if progress_callback:
            details = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
            progress_callback(99, f"Erreur du turntable a l'image {index + 1}/72 :\n" + "\n".join(details[-12:]))
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        if progress_callback:
            progress_callback(99, f"Erreur du turntable a l'image {index + 1}/72 : {exc}")
        return False
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()


class _PreviewDecodeTask(QRunnable):
    """Genere un apercu 3D sans bloquer l'interface; ne manipule que QImage."""
    def __init__(self, path: Path, mtime: float, quiet: bool = False, cancel_event=None, cache_only: bool = False, force_render: bool = False, render_mode: str = "low", profile_override=None, profiles_snapshot=None, automatic: bool = False, media_type: str = "image"):
        super().__init__()
        self.path = path
        self.mtime = mtime
        self.quiet = quiet
        self.cancel_event = cancel_event
        self.cache_only = cache_only
        self.force_render = force_render
        self.render_mode = render_mode
        self.profile_override = profile_override
        self.profiles_snapshot = profiles_snapshot
        self.automatic = automatic
        self.media_type = media_type
        self.output_path = ""
        self.loaded_stale = False
        self.log_directory = None
        self.signals = _PreviewDecodeSignals()

    def run(self):
        # Windows suit ces demandes par thread. Acquisition et liberation
        # restent donc dans ce meme worker, meme en cas d'erreur/annulation.
        rendering = not self.cache_only and self.path.suffix.lower() in RENDERABLE_3D_EXTENSIONS
        previous = _set_render_execution_state(0x80000001) if rendering else None
        if rendering and sys.platform == "win32" and previous is None and not self.quiet:
            self.signals.progress.emit(str(self.path), 0, "Windows n'a pas autorise le blocage de la veille automatique")
        try:
            self._run_preview()
        finally:
            if previous is not None:
                _set_render_execution_state(previous | 0x80000000)

    def _run_preview(self):
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), str(message))
        if self.media_type == "turntable":
            try:
                image = self._decode_turntable()
            except Exception as exc:
                report(99, f"Erreur de turntable : {exc}")
                image = None
            report(100, "Turntable prêt" if image is not None else "Turntable indisponible")
            self.signals.finished.emit(self, str(self.path), self.mtime, image)
            return
        try:
            cache_path = _file_image_cache_path(
                self.path, self.mtime, render_mode=self.render_mode,
                profiles_snapshot=self.profiles_snapshot,
            )
            if cache_path.is_file() and not self.force_render:
                image = QImage(str(cache_path))
                if image.isNull():
                    image = None
                else:
                    self.output_path = str(cache_path.resolve())
            elif self.cache_only:
                stale_path = _find_stale_preview_cache(self.path, self.mtime, cache_path)
                image = QImage(str(stale_path)) if stale_path is not None else None
                if image is not None and not image.isNull():
                    self.loaded_stale = True
                    self.output_path = str(stale_path.resolve())
                else:
                    image = None
            else:
                image = self._decode()
            if (image is not None and not image.isNull() and not self.loaded_stale
                    and (self.force_render or not cache_path.is_file())):
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path = cache_path.with_name(cache_path.stem + ".tmp.png")
                    if image.save(str(temp_path), "PNG"):
                        os.replace(temp_path, cache_path)
                        global _PREVIEW_CACHE_HAS_PNG
                        _PREVIEW_CACHE_HAS_PNG = True
                        _set_hidden(cache_path)
                        _prune_stale_disk_cache(cache_path)
                        _record_preview_cache(self.path, self.mtime, cache_path)
                        self.output_path = str(cache_path.resolve())
                except OSError:
                    pass
        except Exception as exc:
            if not self.quiet:
                self.signals.progress.emit(str(self.path), 99, f"Erreur de rendu : {exc}")
            image = None
        if image is not None and not image.isNull():
            report(100, "Image prête")
        else:
            report(100, "Aucun rendu exploitable")
        self.signals.finished.emit(self, str(self.path), self.mtime, image)

    def _decode_turntable(self):
        if self.path.suffix.lower() not in TURNTABLE_EXTENSIONS:
            return None
        if self.cancel_event is not None and self.cancel_event.is_set():
            return None
        destination = _turntable_cache_path(self.path, self.mtime, self.profiles_snapshot, self.render_mode)
        FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        profile = {key: value for key, value in _render_profile(self.render_mode, self.profile_override).items()
                   if not key.startswith("_turntable_")}
        staging = _turntable_work_path(destination, profile, self.render_mode)
        staging.mkdir(exist_ok=True)
        prepared = staging / "prepared.blend"
        missing = [index for index in range(TURNTABLE_FRAME_COUNT)
                   if QImage(str(staging / f"frame_{index:03d}.png")).isNull()]
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), message)
        report(1, f"Turntable : {TURNTABLE_FRAME_COUNT - len(missing)}/72 images deja sauvegardees")
        if missing:
            if not prepared.is_file():
                self.profile_override = dict(profile, _turntable_output=str(staging.resolve()),
                                             _turntable_prepared_scene=str(prepared.resolve()))
                result = self._decode()
                if result is None or result.isNull() or not prepared.is_file():
                    return None
            for index in missing:
                if self.path.stat().st_mtime != self.mtime:
                    return None
                report(70 + int(28 * index / 72), f"Turntable : image {index + 1}/72 (processus independant)")
                if not _render_turntable_frame(prepared, staging / f"frame_{index:03d}.png", index,
                                               self.cancel_event, report):
                    return None
        # Les fichiers partiels restent en place en cas d'erreur ou de pause.
        # Ce dossier temporaire ne contient que l'ancienne sequence publiee.
        with tempfile.TemporaryDirectory(prefix="turntable_work_", dir=str(FILE_IMAGE_DISK_CACHE_DIR),
                                         ignore_cleanup_errors=True) as work:
            first_image = None
            for index in range(TURNTABLE_FRAME_COUNT):
                if self.cancel_event is not None and self.cancel_event.is_set():
                    return None
                frame = staging / f"frame_{index:03d}.png"
                decoded = QImage(str(frame))
                if decoded.isNull():
                    return None
                composed = _apply_render_background(decoded, profile)
                temporary_frame = frame.with_name(frame.stem + ".compose.tmp.png")
                if not composed.save(str(temporary_frame), "PNG"):
                    return None
                temporary_frame.replace(frame)
                if index == 0:
                    first_image = composed
            if self.path.stat().st_mtime != self.mtime:
                return None
            if self.cancel_event is not None and self.cancel_event.is_set():
                return None
            (staging / "complete.json").write_text(json.dumps({"frames": TURNTABLE_FRAME_COUNT, "source": str(self.path), "mtime": self.mtime}), encoding="utf-8")
            # Ne publier que les 72 images completes ; une interruption
            # conserve le turntable precedent et ses metadonnees.
            previous = Path(work) / "previous"
            if destination.exists():
                _rename_render_directory(destination, previous)
            try:
                _rename_render_directory(staging, destination)
            except OSError:
                if previous.exists():
                    _rename_render_directory(previous, destination)
                raise
            metadata = _turntable_metadata_path(self.path, self.render_mode)
            temporary = metadata.with_suffix(".tmp")
            temporary.write_text(json.dumps({"cache": str(destination.resolve())}), encoding="utf-8")
            temporary.replace(metadata)
            self.output_path = str((destination / "frame_000.png").resolve())
            # Le snapshot lourd n'est utile que tant que la sequence est
            # incomplete. Ne pas le conserver pour chaque turntable publie.
            try:
                (destination / "prepared.blend").unlink(missing_ok=True)
            except OSError:
                pass
            return first_image

    def _decode(self):
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), str(message))
        suffix = self.path.suffix.lower()
        if suffix in OBJ_EXTENSIONS: return _decode_obj_image(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in ABC_EXTENSIONS: return _decode_abc_image(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in BLEND_EXTENSIONS:
            # Le rendu manuel "high resolution" doit rester strictement
            # identique au rendu automatique : la resolution 1105x1105 est
            # conservee et Blender detecte/applique la subdivision comme
            # dans le chemin automatique.
            return _render_wireframe_eevee(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in MAYA_SCENE_EXTENSIONS: return _render_ma_wireframe(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in FBX_EXTENSIONS: return _render_wireframe_eevee(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event, render_mode=self.render_mode, profile_override=self.profile_override)
        if suffix in DWG_EXTENSIONS: return _decode_dwg_image(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event)
        if suffix in TWO_D_IMAGE_EXTENSIONS: return _decode_2d_image(self.path, FILE_IMAGE_CACHE_MAX_DIM, report, self.cancel_event)
        if suffix in VIDEO_EXTENSIONS: return _decode_video_frame(self.path, FILE_IMAGE_CACHE_MAX_DIM)
        return None


_PREVIEW_DECODE_POOL = QThreadPool()
_PREVIEW_DECODE_POOL.setMaxThreadCount(2)
_IDLE_SCAN_POOL = QThreadPool()
_IDLE_SCAN_POOL.setMaxThreadCount(1)


class _PreviewDecodeManager(QObject):
    started = Signal(str)
    progress = Signal(str, int, str)
    ready = Signal(str, float, object)
    turntable_ready = Signal(str, float, object)

    def __init__(self):
        super().__init__()
        self.active: dict[str, _PreviewDecodeTask] = {}
        self.last_completed_mode: dict[str, str] = {}

    def request(self, path: Path, mtime: float, quiet: bool = False, cancel_event=None, cache_only: bool = False, force_render: bool = False, render_mode: str = "low", automatic: bool = False, media_type: str = "image", log_directory: Path | None = None):
        key = str(path)
        if key in self.active:
            return
        global _AUTOMATIC_RENDER_PROFILE
        profile_override = None
        profiles_snapshot = None
        if force_render:
            if automatic:
                if _AUTOMATIC_RENDER_PROFILE is None:
                    _begin_automatic_render_batch()
                profile_override = _AUTOMATIC_RENDER_PROFILE
                profiles_snapshot = _AUTOMATIC_RENDER_PROFILES
            else:
                _reload_render_profiles()
                profile_override = _render_profile(render_mode)
                profiles_snapshot = json.loads(json.dumps(_RENDER_PROFILES))
        elif not automatic:
            # Même les aperçus servis depuis le cache doivent calculer leur
            # clé avec le contenu actuel des paramètres de rendu. Ainsi, une
            # modification de parametres rendus.txt est prise en compte dès
            # le prochain aperçu, sans devoir redémarrer l'application.
            _reload_render_profiles()
        task = _PreviewDecodeTask(path, mtime, quiet=quiet, cancel_event=cancel_event,
                                  cache_only=cache_only, force_render=force_render,
                                  render_mode=render_mode, profile_override=profile_override,
                                  profiles_snapshot=profiles_snapshot,
                                  automatic=automatic, media_type=media_type)
        task.signals.finished.connect(self._on_finished)
        task.signals.progress.connect(self._on_task_progress)
        self.active[key] = task
        task.log_directory = log_directory
        if force_render and not automatic and log_directory is not None:
            self._write_task_log(task, f"> Aperçu en cours : {path}")
        if not quiet:
            self.started.emit(key)
        _PREVIEW_DECODE_POOL.start(task)

    def _on_finished(self, task, path_str: str, mtime: float, image):
        self.active.pop(path_str, None)
        self.last_completed_mode[path_str] = task.render_mode
        if task.media_type == "turntable":
            self.turntable_ready.emit(path_str, mtime, image)
        else:
            miss_key = (path_str, int(mtime))
            if image is not None and not image.isNull():
                _FILE_IMAGE_COLUMN_LOOKUP_MISSES.discard(miss_key)
                if task.loaded_stale:
                    _STALE_PREVIEW_PATHS.add(path_str)
                else:
                    _STALE_PREVIEW_PATHS.discard(path_str)
            elif task.cache_only:
                if len(_FILE_IMAGE_COLUMN_LOOKUP_MISSES) >= 4096:
                    _FILE_IMAGE_COLUMN_LOOKUP_MISSES.clear()
                _FILE_IMAGE_COLUMN_LOOKUP_MISSES.add(miss_key)
            self.ready.emit(path_str, mtime, image)

    def _on_task_progress(self, path_str: str, percent: int, message: str):
        task = self.active.get(path_str)
        if task is not None and task.force_render and not task.automatic and task.log_directory is not None:
            self._write_task_log(task, f"[{percent:3d}%] {Path(path_str).name} — {message}")
        if task is None or not task.quiet:
            self.progress.emit(path_str, percent, message)

    def _write_task_log(self, task, message):
        try:
            _write_render_log(task.log_directory, message, str(task.path), task.media_type,
                              task.render_mode, task.output_path)
        except (OSError, ValueError):
            pass


_PREVIEW_DECODE_MANAGER = _PreviewDecodeManager()


class _IdleFileScanSignals(QObject):
    finished = Signal(str, object, object)


class _IdleFileScanTask(QRunnable):
    """Parcourt recursivement la racine sans bloquer la fenetre."""
    def __init__(self, root: Path, supported: set[str], cancel_event,
                 omit_file_names: set[str] | None = None, omit_extensions: set[str] | None = None,
                 omit_dir_names: set[str] | None = None):
        super().__init__()
        self.root = root
        self.supported = supported
        self.cancel_event = cancel_event
        self.omit_file_names = omit_file_names or set()
        self.omit_extensions = omit_extensions or set()
        self.omit_dir_names = omit_dir_names or set()
        self.signals = _IdleFileScanSignals()

    def run(self):
        found = []
        root_text = str(self.root)
        try:
            for current, dirs, files in os.walk(root_text, topdown=True, followlinks=False):
                if self.cancel_event.is_set():
                    break
                dirs.sort(key=str.casefold)
                dirs[:] = [name for name in dirs if name.casefold() not in self.omit_dir_names]
                files.sort(key=str.casefold)
                for filename in files:
                    if self.cancel_event.is_set():
                        break
                    name_lower = filename.casefold()
                    suffix = Path(filename).suffix.lower()
                    if (suffix not in self.supported
                            or name_lower in self.omit_file_names
                            or any(name_lower.endswith("." + extension) for extension in self.omit_extensions)):
                        continue
                    path = Path(current) / filename
                    try:
                        found.append((str(path), path.stat().st_mtime))
                    except OSError:
                        continue
        except (OSError, PermissionError):
            pass
        self.signals.finished.emit(root_text, found, self.cancel_event.is_set())


class _IdlePreviewScheduler(QObject):
    """Met a jour les apercus 2D/3D perimes apres 2 min d'inactivite."""
    IDLE_DELAY_MS = 120_000
    RESCAN_INTERVAL_SECONDS = 60.0
    LOG_SEPARATOR = "-----------------------------------------"
    SUPPORTED_SUFFIXES = RENDERABLE_3D_EXTENSIONS | TWO_D_IMAGE_EXTENSIONS

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self.last_activity = time.monotonic()
        self.is_idle = False
        self.queue: list[tuple[Path, float]] = []
        self.done: set[tuple[str, float]] = set()
        self.failed: set[tuple[str, float]] = set()
        self.failure_counts: dict[tuple[str, float, str], int] = {}
        self.retry_after: dict[tuple[str, float], float] = {}
        self._batch_profile_signature = None
        self.active_key: str | None = None
        self.active_media_type = "image"
        self.active_permanent_error = ""
        self.active_identity: tuple[str, float] | None = None
        self.cancel_event: threading.Event | None = None
        self.scan_cancel_event: threading.Event | None = None
        self.scan_task: _IdleFileScanTask | None = None
        self.scan_in_progress = False
        self.scan_root = ""
        self.last_scan = 0.0
        self.auto_render_count = 0
        self.active_log_path: Path | None = None
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        _PREVIEW_DECODE_MANAGER.ready.connect(self._on_preview_ready)
        _PREVIEW_DECODE_MANAGER.turntable_ready.connect(self._on_preview_ready)
        _PREVIEW_DECODE_MANAGER.started.connect(self._on_preview_started)
        _PREVIEW_DECODE_MANAGER.progress.connect(self._on_preview_progress)
        self.timer.start()

    def eventFilter(self, watched, event):
        if sys.platform != "win32" and event.type() in {
            QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel, QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease, QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate,
        }:
            self.last_activity = time.monotonic()
        return False

    @staticmethod
    def _system_idle_ms() -> int | None:
        if sys.platform != "win32":
            return None
        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LastInputInfo()
        info.cbSize = ctypes.sizeof(LastInputInfo)
        try:
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        except (AttributeError, OSError):
            return None

    def _user_is_idle(self) -> bool:
        system_idle = self._system_idle_ms()
        if system_idle is not None:
            return system_idle >= self.IDLE_DELAY_MS
        return (time.monotonic() - self.last_activity) * 1000 >= self.IDLE_DELAY_MS

    def _poll(self):
        idle_now = self._user_is_idle()
        if not idle_now:
            self.is_idle = False
            if self.cancel_event is not None:
                self.cancel_event.set()
            if self.scan_cancel_event is not None:
                self.scan_cancel_event.set()
            return
        if not self.is_idle:
            self.is_idle = True
            self.last_scan = 0.0
        if self.active_key is not None:
            return
        if self.scan_in_progress:
            return
        if not self.queue and time.monotonic() - self.last_scan >= self.RESCAN_INTERVAL_SECONDS:
            self._start_file_scan()
        if self.queue:
            self._start_next()

    def _start_file_scan(self):
        self.last_scan = time.monotonic()
        root_text = self.browser.root_field.text().strip()
        root = Path(root_text)
        if not root.is_dir():
            return
        # Le profil automatique est actualise une fois avant le scan qui
        # decide si les caches sont encore valides, puis gele pour toute la file.
        _begin_automatic_render_batch()
        profile_signature = json.dumps(_AUTOMATIC_RENDER_PROFILES, sort_keys=True, default=str)
        for profile in (_AUTOMATIC_RENDER_PROFILES or {}).values():
            template = Path(__file__).resolve().parent / "files" / str(profile.get("template", ""))
            try:
                profile_signature += str(template.stat().st_mtime_ns)
            except OSError:
                pass
        if profile_signature != self._batch_profile_signature:
            self.done.clear()
            self.failed.clear()
            self.failure_counts.clear()
            self.retry_after.clear()
            self._batch_profile_signature = profile_signature
        self.scan_in_progress = True
        self.scan_root = str(root)
        self.scan_cancel_event = threading.Event()
        task = _IdleFileScanTask(
            root, self.SUPPORTED_SUFFIXES, self.scan_cancel_event,
            GLOBAL_OMIT_FILE_NAMES.copy(), GLOBAL_OMIT_FILE_EXTENSIONS.copy(),
            GLOBAL_OMIT_DIR_NAMES.copy(),
        )
        task.signals.finished.connect(self._on_file_scan_finished)
        self.scan_task = task
        _IDLE_SCAN_POOL.start(task)

    def _on_file_scan_finished(self, root_text: str, entries, canceled: bool):
        self.scan_in_progress = False
        self.scan_task = None
        self.scan_cancel_event = None
        self.last_scan = time.monotonic()
        if canceled or not self.is_idle or not self._user_is_idle():
            return
        if str(Path(self.browser.root_field.text().strip())) != root_text:
            return
        found = []
        seen = set()
        for value, mtime in entries:
            path = Path(value)
            key = str(path)
            identity = (key, mtime)
            if identity in seen or identity in self.done or identity in self.failed or key in _PREVIEW_DECODE_MANAGER.active:
                continue
            if _is_preview_protected(path):
                self.done.add(identity)
                continue
            seen.add(identity)
            if _file_image_cache_path(
                path, mtime, profiles_snapshot=_AUTOMATIC_RENDER_PROFILES,
            ).is_file() and (path.suffix.lower() not in TURNTABLE_EXTENSIONS or _turntable_frames(path, mtime, _AUTOMATIC_RENDER_PROFILES)):
                self.done.add(identity)
                continue
            found.append((path, mtime))
        self.queue.extend(found)
        self._start_next()

    def _append_log(self, line: str):
        path = self.active_log_path
        if path is None:
            return
        if line == self.LOG_SEPARATOR:
            return
        try:
            task = _PREVIEW_DECODE_MANAGER.active.get(self.active_key)
            self.active_log_path = _write_render_log(path.parent, line, self.active_key or "", self.active_media_type,
                                                      getattr(task, "render_mode", "low"),
                                                      getattr(task, "output_path", ""))
        except (OSError, ValueError):
            pass

    def _on_preview_started(self, path_str: str):
        if path_str != self.active_key:
            return
        self.active_log_path = _render_log_path(Path(self.browser.root_field.text().strip()))
        try:
            has_previous_render = self.active_log_path.is_file() and self.active_log_path.stat().st_size > 0
        except OSError:
            has_previous_render = False
        if has_previous_render:
            self._append_log(self.LOG_SEPARATOR)
        self.auto_render_count += 1
        # La ligne courante et toutes les progressions sont egalement ecrites
        # dans le journal du root, sans inclure les apercus declenches a la main.
        self._append_log(f"> Aperçu en cours : {path_str}")

    def _on_preview_progress(self, path_str: str, percent: int, message: str):
        if path_str == self.active_key:
            if "HDF5" in message and ("obsol" in message or "réexport" in message):
                self.active_permanent_error = message
            self._append_log(f"[{percent:3d}%] {Path(path_str).name} — {message}")

    def _start_next(self):
        # Un essai par element de la file : les reprises differees ne doivent
        # jamais bloquer le thread GUI dans une boucle de re-enfilement.
        for _ in range(len(self.queue)):
            path, previous_mtime = self.queue.pop(0)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            identity = (key, mtime)
            if time.monotonic() < self.retry_after.get(identity, 0.0):
                self.queue.append((path, mtime))
                continue
            if identity in self.done or identity in self.failed or key in _PREVIEW_DECODE_MANAGER.active:
                continue
            if _is_preview_protected(path):
                self.done.add(identity)
                continue
            if _file_image_cache_path(
                path, mtime, profiles_snapshot=_AUTOMATIC_RENDER_PROFILES,
            ).is_file() and (path.suffix.lower() not in TURNTABLE_EXTENSIONS or _turntable_frames(path, mtime, _AUTOMATIC_RENDER_PROFILES)):
                self.done.add(identity)
                continue
            self.active_key = key
            self.active_permanent_error = ""
            self.active_identity = identity
            self.cancel_event = threading.Event()
            self.active_media_type = "turntable" if _file_image_cache_path(
                path, mtime, profiles_snapshot=_AUTOMATIC_RENDER_PROFILES,
            ).is_file() and path.suffix.lower() in TURNTABLE_EXTENSIONS else "image"
            self.browser.detail.prepare_auto_preview_log(path)
            _PREVIEW_DECODE_MANAGER.request(
                path, mtime, cancel_event=self.cancel_event, force_render=True, automatic=True,
                media_type=self.active_media_type,
            )
            if key not in _PREVIEW_DECODE_MANAGER.active:
                self.active_key = None
                self.active_identity = None
                self.cancel_event = None
            return

    def _on_preview_ready(self, path_str: str, mtime: float, image):
        if path_str != self.active_key:
            return
        canceled = self.cancel_event is not None and self.cancel_event.is_set()
        success = image is not None and not image.isNull()
        if canceled:
            self._append_log(f"[---] {Path(path_str).name} — interrompu par une activité utilisateur")
        else:
            message = "Aperçu terminé" if image is not None and not image.isNull() else "Aperçu indisponible"
            self._append_log(f"[100%] {Path(path_str).name} — {message}")
        identity = self.active_identity
        completed_media = self.active_media_type
        retry = False
        if identity is not None and not canceled and not success:
            failure_key = (*identity, completed_media)
            failures = self.failure_counts.get(failure_key, 0) + 1
            self.failure_counts[failure_key] = failures
            retry = failures < 2 and not self.active_permanent_error
            if retry:
                self._append_log(f"[---] {Path(path_str).name} — Nouvelle tentative differee (au moins 30 secondes), sans bloquer les autres fichiers")
            else:
                reason = self.active_permanent_error or "apres 2 tentatives : suspendu pour cette session"
                self._append_log(f"[---] {Path(path_str).name} — Échec : {reason}")
        self.active_key = None
        self.active_identity = None
        self.cancel_event = None
        self.active_log_path = None
        if canceled:
            if identity is not None:
                self.queue.insert(0, (Path(path_str), mtime))
            return
        if identity is not None:
            if retry:
                self.retry_after[identity] = time.monotonic() + 30.0
                self.queue.append((Path(path_str), mtime))
            elif completed_media == "image" and success and Path(path_str).suffix.lower() in TURNTABLE_EXTENSIONS:
                self.queue.insert(0, (Path(path_str), mtime))
            elif success:
                self.done.add((path_str, mtime))
            else:
                self.failed.add(identity)
            if success:
                self.failure_counts.pop((*identity, completed_media), None)
                self.retry_after.pop(identity, None)
        if self.is_idle and self._user_is_idle():
            self._start_next()


_FALLBACK_SOFTWARE_BADGE_PALETTE = [
    ("#5c6bc0", "#eef0ff"), ("#26a69a", "#e8fff9"), ("#8d6e63", "#fff3e6"),
    ("#7e57c2", "#f2ecff"), ("#42a5f5", "#e8f4ff"), ("#66bb6a", "#eafff0"),
    ("#ec407a", "#ffe9f1"), ("#ffa726", "#3a2200"),
]

