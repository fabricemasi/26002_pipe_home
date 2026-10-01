#!/usr/bin/env python3
"""
Pipeline Browser - navigateur en colonnes (Miller columns) pour F:\\PIPELINE.

Habillage base sur la maquette Claude Design :
  IBM Plex Sans / IBM Plex Mono, fond #1a1c1e, accent #3f6f9f,
  colonnes de 220px, lignes de 24px, barre de statut monospace.

Lecture seule pour l'instant.

    pip install PySide6
    pythonw pipeline_browser.py   (pythonw = sans fenetre console ; python = avec)
"""

import hashlib
import io
import json
import math
import mmap
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

if sys.platform == "win32":
    # Sans cette declaration, Windows ne sait pas que l'appli gere elle-meme
    # le DPI par moniteur : des qu'une fenetre s'etend sur plusieurs ecrans
    # d'echelle differente (125% + 100% par ex.), il applique lui-meme un
    # zoom bitmap sur la portion affichee sur l'ecran le moins dense, d'ou
    # l'effet de flou/pixelisation - independant de tout ce que l'appli
    # dessine. Doit etre appele avant la creation de la QApplication.
    import ctypes
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+) :
        # rendu natif par moniteur, aucun etirement par l'OS.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QByteArray, QEasingCurve, QEvent, QEventLoop, QMimeData, QObject, QParallelAnimationGroup, QPoint, QPointF,
    QPropertyAnimation, QRunnable, QRect, QRectF, QSize, Qt, QThreadPool, QTimer, QUrl, Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QDrag,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygon,
    QPolygonF,
    QRegion,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
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
    C,
    COLUMN_FRAME_KEYS,
    COLUMN_TYPE_OVERRIDE_KEYS,
    INSPECTOR_TITLE,
    PREVIEW_STACK_TITLE,
    STYLESHEET_COLOR_KEYS,
    _hex_to_rgb,
    apply_dwm_frame,
    apply_style,
    auto_collapse_set_columns,
    column_gap,
    columns_resizable,
    custom_softwares,
    removed_softwares,
    set_custom_softwares,
    set_removed_softwares,
    font,
    header_qss,
    refresh_style,
    resize_hit_test,
    role_color,
    role_font,
    scaled,
    set_auto_collapse_set_columns,
    set_button_frame,
    set_button_radius,
    set_color,
    set_column_gap,
    set_columns_resizable,
    set_header_style,
    set_input_frame,
    set_input_radius,
    set_role_font,
    set_table_radius,
    set_ui_scale,
    ui_scale,
    start_native_move,
    resolve_color_ref,
    set_general_column_style,
    set_column_style,
    column_frame_style,
    column_header_qss,
    column_padding_for,
    column_style_for,
    ITEM_FONT_ROLE_LABELS,
)
from settings_window import (
    M,
    SettingsWindow,
    load_settings,
    save_settings,
    _coerce_side_enabled,
    _load_presets,
    _paint_bordered_rect,
    _radius_dict,
    _radius_any,
    _radius_shrink,
    _rounded_rect_path,
    _save_presets,
    _sync_slider_style,
    _sync_dynamic_M,
    _TableFrame,
)

# ==========================================================================
# Configuration
# ==========================================================================

ROOT = Path(r"F:\PIPELINE")

COLUMN_LABELS = ["Type", "Projets", "Sous-projet", "Logiciels", "Contenu"]

# Repli des colonnes "de set" (voir Column.set_collapsed/PipelineBrowser.
# _apply_project_columns_collapsed) : une fois la chaine de navigation
# COMPLETEMENT settee jusqu'au repertoire de travail (voir
# _chain_expected_total, N colonnes reelles quelconques — Type/Projets/
# Sous-projet en legacy, ou N niveaux configures, voir load_project_
# columns), ces colonnes perdent leur utilite immediate (le contexte est
# fixe) et peuvent se replier en bandeau etroit, avec une icone pour les
# redeplier a la demande (voir PipelineBrowser._sync_collapse_state) — pas
# de liste de TITRES fixe (voir Column.collapsible, base sur group_kind) :
# generalise a N'IMPORTE QUEL nombre d'etapes, voir la remarque de
# l'utilisateur, "si un projet est sur une base 3 etapes, 3 colonnes
# devront se rabattre, si c'est une base 4, 4 colonnes ... en fait c'est
# toutes les colonnes avant les colonnes de focus". Reglable (voir
# app_style.auto_collapse_set_columns/General > Application, "un toggle
# qui permet ou pas de rabattre les colonnes de set").

# Dossiers dont le contenu est remonte dans la colonne du parent.
FLATTEN_FOLDERS = {"WORK"}

HIDDEN_PREFIXES = (".", "$", "~")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico",
}

# Fichiers 3D dont on peut generer un apercu (voir _decode_obj_image) : pas
# une vraie image, mais traites comme tel partout ailleurs (meme ligne-carte,
# meme cache disque) via PREVIEWABLE_EXTENSIONS.
OBJ_EXTENSIONS = {".obj"}
ABC_EXTENSIONS = {".abc"}
BLEND_EXTENSIONS = {".blend"}
MAYA_SCENE_EXTENSIONS = {".ma", ".mb"}
FBX_EXTENSIONS = {".fbx"}
DWG_EXTENSIONS = {".dwg"}
RENDERABLE_3D_EXTENSIONS = (
    OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS
)
_DWG_RENDER_LOCK = threading.Lock()

# Fichiers Photoshop : Qt ne sait pas les decoder (absent de
# QImageReader.supportedImageFormats), mais Photoshop y embarque presque
# toujours une vignette JPEG prete a l'emploi (voir _decode_psd_thumbnail) —
# bien plus simple/rapide qu'une vraie composition des calques, qui serait
# hors de portee ici.
PSD_EXTENSIONS = {".psd", ".psb"}

# Rendus HDR .exr (voir _decode_exr_image) : necessite le paquet OpenEXR
# (voir _OPENEXR_AVAILABLE) ; sans lui, ces fichiers restent sans apercu,
# comme avant.
EXR_EXTENSIONS = {".exr"}

# Textures Arnold/OpenImageIO : conversion vers une vignette PNG via oiiotool.
TX_EXTENSIONS = {".tx"}

# HDRI Radiance (voir _decode_hdr_image) : format RGBE documente/stable,
# parseur maison (juste numpy, AUCUNE dependance externe contrairement a
# .exr/OpenEXR) — voir la remarque de l'utilisateur, "possible de faire
# les apercus des hdri ?".
HDR_EXTENSIONS = {".hdr"}

# Videos : une frame extraite via QtMultimedia (voir _decode_video_frame),
# module fourni avec PySide6 (ffmpeg embarque, aucune dependance externe).
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}

PREVIEWABLE_EXTENSIONS = (
    IMAGE_EXTENSIONS | OBJ_EXTENSIONS | ABC_EXTENSIONS | BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS | DWG_EXTENSIONS | PSD_EXTENSIONS | EXR_EXTENSIONS | HDR_EXTENSIONS | TX_EXTENSIONS | VIDEO_EXTENSIONS
)
TWO_D_IMAGE_EXTENSIONS = (
    IMAGE_EXTENSIONS | PSD_EXTENSIONS | EXR_EXTENSIONS | HDR_EXTENSIONS | TX_EXTENSIONS | DWG_EXTENSIONS
)

_MANUAL_3D_PREVIEW_REQUESTS: set[str] = set()
_STALE_PREVIEW_PATHS: set[str] = set()

# Fichiers texte/code dont le contenu (debut) s'affiche dans l'inspecteur
# (voir DetailPanel.show_path) : contrairement a IMAGE_EXTENSIONS/
# OBJ_EXTENSIONS/ABC_EXTENSIONS, jamais utilise pour les cartes-vignette des colonnes (un
# extrait de texte reduit a la taille d'une icone serait illisible) — texte
# brut affiche en clair uniquement dans le panneau de droite.
TEXT_PREVIEW_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".xml", ".yaml", ".yml", ".ini",
    ".cfg", ".conf", ".log", ".csv", ".tsv", ".py", ".js", ".ts", ".html",
    ".css", ".sh", ".bat", ".ps1", ".nk", ".mel",
}
TEXT_PREVIEW_MAX_BYTES = 4000    # lu depuis le disque, avant decodage/troncature
TEXT_PREVIEW_MAX_LINES = 40
TEXT_PREVIEW_PANEL_HEIGHT = 220   # hauteur fixe du panneau de texte dans l'inspecteur (voir DetailPanel)
PUR_PREVIEW_EXTENSIONS = {".pur"}
PUR_MAX_EMBEDDED_IMAGES = 3000
_PUR_IMAGE_INDEX_CACHE: dict[str, tuple[float, list[tuple[int, int, str]]]] = {}

# Reglable depuis la fenetre de parametres : affiche les fichiers image, dans
# n'importe quelle colonne classique, avec exactement le meme style de ligne
# que les vignettes de projet (vignette carree a gauche + nom/metadonnee a
# droite), plutot que le marqueur habituel. Pas de menu "changer l'image"
# pour ces lignes : l'image EST le fichier.
SHOW_FILE_IMAGE_PREVIEWS = True

PREVIEW_MIN_HEIGHT = 104   # hauteur de la vignette sans image (ou image tres petite)
PREVIEW_MAX_HEIGHT = 1200  # affichage natif des apercus OBJ/ABC en 1200 x 1200 px

# Vignettes de dossier (colonnes "Projets" et "Sous-projet") : image
# personnalisee stockee a la racine du dossier, sinon image par defaut
# generique.
THUMBNAIL_COLUMN_LABELS = {"Projets", "Sous-projet"}
THUMBNAIL_FILENAME = ".thumbnail.png"
THUMBNAIL_MAX_DIM = 1024   # taille max (px) a laquelle une vignette perso est enregistree
PROJECT_ROW_HEIGHT = 64    # hauteur de ligne (vignette carree + texte a droite)

# Logos de logiciel (colonne "Logiciels") : badge colore genere a la volee
# (pas de fichier image) par defaut, identifie par le nom du dossier (HOUDINI,
# MAYA...). Peut etre remplace par une image perso via le clic droit ; cette
# icone perso est alors globale au logiciel (pas au projet), stockee a cote
# du script puisqu'elle ne depend pas de la racine du pipeline consultee.
SOFTWARE_COLUMN_LABEL = "Logiciels"
# 16 (valeur d'origine) etait bien EN DESSOUS de la hauteur de ligne
# reelle (24-40px selon les reglages) : software_icon_pixmap mettait donc
# en cache un bitmap de 16x16, ensuite AGRANDI par _paint_row_image pour
# remplir la ligne — un agrandissement, jamais net (voir la remarque de
# l'utilisateur, "je veux que toutes les icones soient parfaitement
# redimensionnables sans pixelisation"). 128 : large marge au-dessus de
# toute hauteur de ligne realiste, pour que la mise a l'echelle EFFECTIVE
# (dans _paint_row_image) soit TOUJOURS un RETRECISSEMENT — voir
# _smooth_scale_down, jamais floue/pixelisee dans ce sens.
SOFTWARE_ICON_SIZE = 128
CUSTOM_SOFTWARE_ICON_DIR = Path(__file__).resolve().parent / ".pipeline_software_icons"
ICONS_DIR = Path(__file__).resolve().parent / "icons"
CUSTOM_SOFTWARE_ICON_MAX_DIM = 128

_FILE_ATTRIBUTE_HIDDEN = 0x2


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
FILE_IMAGE_DISK_CACHE_DIR = Path(__file__).resolve().parent / ".pipeline_preview_cache"

# La cle de cache disque ne depend que du chemin source et de son mtime :
# un changement du CODE de rendu (ex. _decode_obj_image) ne les fait pas
# bouger, donc un vieux rendu perime resterait sinon servi indefiniment tant
# que le fichier source lui-meme n'est pas retouche. A incrementer chaque
# fois que la logique de decodage/rendu change reellement (ex. le passage a
# un flat shading sans contour) pour forcer une regeneration.
_PREVIEW_CACHE_VERSION = 44

# Evite de rescanner le cache disque a chaque repaint d'une ligne sans apercu.
# La cle inclut le mtime : une modification du fichier force une nouvelle recherche.
_PREVIEW_STALE_LOOKUP_MISSES: set[tuple[str, int]] = set()
_PREVIEW_CACHE_HAS_PNG: bool | None = None


def _file_image_cache_signature(path: Path) -> str:
    template_signature = ""
    if path.suffix.lower() in {".obj", ".abc", ".blend"} | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS | DWG_EXTENSIONS:
        template_path = Path(__file__).resolve().parent / "files" / "scene pour appercu.blend"
        try:
            template_stat = template_path.stat()
            template_signature = f":{template_stat.st_mtime_ns}:{template_stat.st_size}"
        except OSError:
            pass
        if path.suffix.lower() == ".blend":
            template_signature += ":blend_all_modifiers_subd_smooth_gloss_shadow_v4"
        elif path.suffix.lower() in MAYA_SCENE_EXTENSIONS:
            template_signature += ":maya_ascii_join_apply_all_transforms_before_bbox_scale_v8"
        elif path.suffix.lower() in FBX_EXTENSIONS:
            template_signature += ":fbx_blender_template_import_v1"
        elif path.suffix.lower() in DWG_EXTENSIONS:
            template_signature += ":dwg_oda_dxf_ezdxf_2d_v1"
    return template_signature


def _file_image_cache_path(path: Path, mtime: float, version: int | None = None, signature: str | None = None) -> Path:
    if version is None:
        version = _PREVIEW_CACHE_VERSION
    if signature is None:
        signature = _file_image_cache_signature(path)
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
# Camera fixe en haut a droite, axes Z-up : yaw autour de Z, puis pitch
# autour de X. L'ecran projette X horizontal et Z vertical.
_OBJ_YAW = math.radians(-20)
_OBJ_PITCH = math.radians(20)


def _decode_obj_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Produit une image opaque en wireframe depuis un OBJ Wavefront."""
    eevee_image = _render_wireframe_eevee(path, max_dim, progress_callback, cancel_event)
    if eevee_image is not None:
        return eevee_image
    if cancel_event is not None and cancel_event.is_set():
        return None
    template_path = Path(__file__).resolve().parent / "files" / "scene pour appercu.blend"
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


def _render_wireframe_eevee(path: Path, max_dim: int, progress_callback=None, cancel_event=None, kind_override=None) -> QImage | None:
    """Rend l'objet dans la scene Eevee du template, avec son eclairage."""
    blender = _blender_executable()
    if not blender:
        return None
    suffix = path.suffix.lower()
    script = r'''import bpy, sys
from mathutils import Matrix, Vector
src, dst, status_path, kind, output_dim = sys.argv[sys.argv.index("--") + 1:sys.argv.index("--") + 6]
output_dim = int(output_dim)
def report(percent, text):
    try:
        with open(status_path, "w", encoding="utf-8") as f: f.write("%d|%s" % (percent, text))
    except OSError: pass
def fail(message):
    report(99, message)
    raise RuntimeError(message)
report(3, "Ouverture de la scene de rendu")
scene = bpy.context.scene
if scene.camera is None: fail("La scene de preview ne contient pas de camera")
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
        scene.collection.children.link(source_scene.collection)
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
if kind in {"ma", "mb", "maya"}:
    report(16, "Selection de tous les objets Maya et fusion avec Ctrl+J")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
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
subdivision_objects = set()
if kind == "blend":
    report(14, "Application de tous les modifiers avant le cadrage")
    for obj in objects:
        if any(mod.type == "SUBSURF" for mod in obj.modifiers):
            subdivision_objects.add(obj.as_pointer())
        modifier_names = [mod.name for mod in obj.modifiers]
        if modifier_names:
            obj.data = obj.data.copy()
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            for modifier_name in modifier_names:
                if obj.modifiers.get(modifier_name) is None:
                    continue
                try:
                    bpy.ops.object.modifier_apply(modifier=modifier_name)
                except Exception as exc:
                    fail("Impossible d'appliquer le modifier %s sur %s : %s" % (modifier_name, obj.name, exc))
    if subdivision_objects:
        for light in scene.objects:
            if light.type == "LIGHT" and hasattr(light.data, "use_shadow"):
                light.data.use_shadow = True
    bpy.context.view_layer.update()
report(20, "Calcul de la bounding box de l'objet")
world_matrices = {obj: obj.matrix_world.copy() for obj in objects}
world_points = [world_matrices[obj] @ vertex.co for obj in objects for vertex in obj.data.vertices]
if not world_points: fail("Aucune geometrie exploitable")
source_min = Vector(tuple(min(p[i] for p in world_points) for i in range(3)))
source_max = Vector(tuple(max(p[i] for p in world_points) for i in range(3)))
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
    use_subdivision_shading = obj.as_pointer() in subdivision_objects
    for polygon in obj.data.polygons: polygon.use_smooth = use_subdivision_shading
    obj.data.materials.clear()
surface = bpy.data.materials.new("Preview - surface opaque")
surface.diffuse_color = (0.48, 0.50, 0.53, 1.0)
surface.use_nodes = True
principled = surface.node_tree.nodes.get("Principled BSDF")
if principled:
    principled.inputs["Base Color"].default_value = surface.diffuse_color
    principled.inputs["Roughness"].default_value = 0.78
    principled.inputs["Alpha"].default_value = 1.0
surface_subdivision = bpy.data.materials.new("Preview - surface lisse brillante")
surface_subdivision.diffuse_color = (0.48, 0.50, 0.53, 1.0)
surface_subdivision.use_nodes = True
principled_subdivision = surface_subdivision.node_tree.nodes.get("Principled BSDF")
if principled_subdivision:
    principled_subdivision.inputs["Base Color"].default_value = surface_subdivision.diffuse_color
    principled_subdivision.inputs["Roughness"].default_value = 0.22
    principled_subdivision.inputs["Metallic"].default_value = 0.08
    principled_subdivision.inputs["Alpha"].default_value = 1.0
    coat_weight = principled_subdivision.inputs.get("Coat Weight")
    if coat_weight is not None:
        coat_weight.default_value = 0.12
    coat_roughness = principled_subdivision.inputs.get("Coat Roughness")
    if coat_roughness is not None:
        coat_roughness.default_value = 0.2
wire_material = bpy.data.materials.new("Preview - wireframe noir")
wire_material.diffuse_color = (0.002, 0.002, 0.002, 1.0)
wire_material.use_nodes = True
nodes = wire_material.node_tree.nodes
nodes.clear()
output = nodes.new("ShaderNodeOutputMaterial")
emission = nodes.new("ShaderNodeEmission")
emission.inputs["Color"].default_value = (0.002, 0.002, 0.002, 1.0)
emission.inputs["Strength"].default_value = 1.0
wire_material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
for index, obj in enumerate(objects):
    obj.data.materials.append(
        surface_subdivision if obj.as_pointer() in subdivision_objects else surface
    )
    obj.data.materials.append(wire_material)
    if obj.as_pointer() not in subdivision_objects:
        wire = obj.modifiers.new("Wireframe fin", "WIREFRAME")
        wire.thickness = target_size * 1.8 / max(output_dim, 1)
        wire.offset = 0.0
        wire.use_replace = False
        wire.use_even_offset = False
        wire.use_boundary = True
        wire.use_crease = False
        wire.use_relative_offset = False
        wire.material_offset = 1
    if index % max(1, len(objects) // 5) == 0:
        report(42 + int(20 * index / max(1, len(objects))), "Preparation du wireframe : objet %d/%d" % (index + 1, len(objects)))
# Grille, axes, curseur et gizmos sont des overlays du viewport, jamais rendus.
for obj in scene.objects:
    if obj.type in {'EMPTY', 'CAMERA'}: obj.hide_render = True
bbox_obj.hide_render = True
scene.camera.hide_render = False
scene.camera.data.clip_start = 0.1
scene.camera.data.clip_end = 10000.0
scene.render.resolution_x = output_dim
scene.render.resolution_y = output_dim
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.film_transparent = False
scene.render.filepath = dst
report(70, "Rendu Eevee dans le template avec ses lumieres et sa camera")
bpy.ops.render.render(write_still=True)
report(98, "Apercu Eevee pret")
'''
    try:
        with tempfile.TemporaryDirectory(prefix="pipe_eevee_wire_") as temp_dir:
            temp = Path(temp_dir)
            script_path, image_path, status_path = temp / "render.py", temp / "preview.png", temp / "status.txt"
            error_path = temp / "blender_error.log"
            script_path.write_text(script, encoding="utf-8")
            error_stream = error_path.open("w", encoding="utf-8", errors="replace")
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": error_stream}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            template_path = Path(__file__).resolve().parent / "files" / "scene pour appercu.blend"
            if not template_path.is_file():
                if progress_callback:
                    progress_callback(99, f"Scene de rendu introuvable : {template_path}")
                error_stream.close()
                return None
            proc = subprocess.Popen(
                [blender, "--background", str(template_path), "--python", str(script_path), "--",
                 str(path.resolve()), str(image_path), str(status_path),
                 kind_override or ("abc" if suffix == ".abc" else "blend" if suffix == ".blend" else "fbx" if suffix == ".fbx" else "obj"), str(max_dim)],
                **kwargs,
            )
            last_status = ""
            deadline = time.monotonic() + 90
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
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    proc.terminate()
                    proc.wait(timeout=3)
                    error_stream.close()
                    return None
                time.sleep(0.1)
            error_stream.close()
            if proc.returncode != 0 or not image_path.is_file():
                if progress_callback:
                    try:
                        percent, message = last_status.split("|", 1)
                        details = error_path.read_text(encoding="utf-8", errors="replace").splitlines()
                        detail = next((line.strip() for line in reversed(details) if line.strip()), "")
                        progress_callback(99, f"Echec Eevee : {detail or message}")
                    except ValueError:
                        pass
                return None
            image = QImage(str(image_path))
            return image.copy() if not image.isNull() else None
    except (OSError, subprocess.SubprocessError):
        return None
def _decode_abc_image(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
    """Extrait le maillage Alembic via Blender, puis reutilise le rendu OBJ."""
    try:
        with open(path, "rb") as source_file:
            legacy_hdf5 = source_file.read(8) == b"\x89HDF\r\n\x1a\n"
    except OSError:
        return None
    if legacy_hdf5:
        if progress_callback:
            progress_callback(100, "Alembic HDF5 obsolète : réexport Blender en Ogawa requis")
        return None
    eevee_image = _render_wireframe_eevee(path, max_dim, progress_callback, cancel_event)
    if eevee_image is not None:
        return eevee_image
    if cancel_event is not None and cancel_event.is_set():
        return None
    template_path = Path(__file__).resolve().parent / "files" / "scene pour appercu.blend"
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
                if progress_callback else None, cancel_event=cancel_event,
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


def _render_ma_wireframe(path: Path, max_dim: int, progress_callback=None, cancel_event=None) -> QImage | None:
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
            return _render_wireframe_eevee(abc_path, max_dim, progress_callback, cancel_event, kind_override="maya")
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
        return cached[1], key in _STALE_PREVIEW_PATHS
    current_path = _file_image_cache_path(path, mtime)
    if current_path.is_file():
        pix = QPixmap(str(current_path))
        if not pix.isNull():
            is_stale = key in _STALE_PREVIEW_PATHS
            if not is_stale:
                _STALE_PREVIEW_PATHS.discard(key)
            _bounded_cache_set(_file_image_cache, key, (mtime, pix))
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
            _bounded_cache_set(_file_image_cache, key, (mtime, pix))
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
        cached = _file_image_cache.get(key)
        if cached and (cached[0] == mtime or key in _STALE_PREVIEW_PATHS):
            return cached[1]
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
    _bounded_cache_set(_file_image_cache, key, (mtime, pix))
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


def _cached_file_image_pixmap(path: Path) -> QPixmap | None:
    """Lit seulement le cache d'un apercu, sans lancer sa generation."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    pix, _is_stale = _read_preview_pixmap(path, mtime)
    return pix


class _PreviewDecodeSignals(QObject):
    finished = Signal(object, str, float, object)
    progress = Signal(str, int, str)


class _PreviewDecodeTask(QRunnable):
    """Genere un apercu 3D sans bloquer l'interface; ne manipule que QImage."""
    def __init__(self, path: Path, mtime: float, quiet: bool = False, cancel_event=None, cache_only: bool = False, force_render: bool = False):
        super().__init__()
        self.path = path
        self.mtime = mtime
        self.quiet = quiet
        self.cancel_event = cancel_event
        self.cache_only = cache_only
        self.force_render = force_render
        self.signals = _PreviewDecodeSignals()

    def run(self):
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), str(message))
        try:
            cache_path = _file_image_cache_path(self.path, self.mtime)
            if cache_path.is_file() and not self.force_render:
                image = QImage(str(cache_path))
                if image.isNull():
                    image = None
            elif self.cache_only:
                image = None
            else:
                image = self._decode()
            if image is not None and not image.isNull() and (self.force_render or not cache_path.is_file()):
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
                except OSError:
                    pass
        except Exception:
            image = None
        if image is not None and not image.isNull():
            report(100, "Image prête")
        else:
            report(100, "Aucun rendu exploitable")
        self.signals.finished.emit(self, str(self.path), self.mtime, image)

    def _decode(self):
        def report(percent, message):
            if not self.quiet:
                self.signals.progress.emit(str(self.path), int(percent), str(message))
        suffix = self.path.suffix.lower()
        if suffix in OBJ_EXTENSIONS: return _decode_obj_image(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event)
        if suffix in ABC_EXTENSIONS: return _decode_abc_image(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event)
        if suffix in BLEND_EXTENSIONS: return _render_wireframe_eevee(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event)
        if suffix in MAYA_SCENE_EXTENSIONS: return _render_ma_wireframe(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event)
        if suffix in FBX_EXTENSIONS: return _render_wireframe_eevee(self.path, OBJ_PREVIEW_DIM, report, self.cancel_event)
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

    def __init__(self):
        super().__init__()
        self.active: dict[str, _PreviewDecodeTask] = {}

    def request(self, path: Path, mtime: float, quiet: bool = False, cancel_event=None, cache_only: bool = False, force_render: bool = False):
        key = str(path)
        if key in self.active:
            return
        task = _PreviewDecodeTask(path, mtime, quiet=quiet, cancel_event=cancel_event,
                                  cache_only=cache_only, force_render=force_render)
        task.signals.finished.connect(self._on_finished)
        task.signals.progress.connect(self._on_task_progress)
        self.active[key] = task
        if not quiet:
            self.started.emit(key)
        _PREVIEW_DECODE_POOL.start(task)

    def _on_finished(self, task, path_str: str, mtime: float, image):
        self.active.pop(path_str, None)
        self.ready.emit(path_str, mtime, image)

    def _on_task_progress(self, path_str: str, percent: int, message: str):
        task = self.active.get(path_str)
        if task is None or not task.quiet:
            self.progress.emit(path_str, percent, message)


_PREVIEW_DECODE_MANAGER = _PreviewDecodeManager()


class _IdleFileScanSignals(QObject):
    finished = Signal(str, object, object)


class _IdleFileScanTask(QRunnable):
    """Parcourt recursivement la racine sans bloquer la fenetre."""
    def __init__(self, root: Path, supported: set[str], cancel_event,
                 omit_file_names: set[str] | None = None, omit_extensions: set[str] | None = None):
        super().__init__()
        self.root = root
        self.supported = supported
        self.cancel_event = cancel_event
        self.omit_file_names = omit_file_names or set()
        self.omit_extensions = omit_extensions or set()
        self.signals = _IdleFileScanSignals()

    def run(self):
        found = []
        root_text = str(self.root)
        try:
            for current, dirs, files in os.walk(root_text, topdown=True, followlinks=False):
                if self.cancel_event.is_set():
                    break
                dirs.sort(key=str.casefold)
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
        self.active_key: str | None = None
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
        self.scan_in_progress = True
        self.scan_root = str(root)
        self.scan_cancel_event = threading.Event()
        task = _IdleFileScanTask(
            root, self.SUPPORTED_SUFFIXES, self.scan_cancel_event,
            GLOBAL_OMIT_FILE_NAMES.copy(), GLOBAL_OMIT_FILE_EXTENSIONS.copy(),
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
            if identity in seen or identity in self.done or key in _PREVIEW_DECODE_MANAGER.active:
                continue
            seen.add(identity)
            if _file_image_cache_path(path, mtime).is_file():
                self.done.add(identity)
                continue
            found.append((path, mtime))
        self.queue.extend(found)
        self._start_next()

    def _append_log(self, line: str):
        path = self.active_log_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line.rstrip("\r\n") + "\n")
        except OSError:
            pass

    def _on_preview_started(self, path_str: str):
        if path_str != self.active_key:
            return
        self.active_log_path = Path(self.browser.root_field.text().strip()) / "pipeline_preview_render.log"
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
            self._append_log(f"[{percent:3d}%] {Path(path_str).name} — {message}")

    def _start_next(self):
        while self.queue:
            path, previous_mtime = self.queue.pop(0)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            identity = (key, mtime)
            if identity in self.done or key in _PREVIEW_DECODE_MANAGER.active:
                continue
            if _file_image_cache_path(path, mtime).is_file():
                self.done.add(identity)
                continue
            self.active_key = key
            self.active_identity = identity
            self.cancel_event = threading.Event()
            self.browser.detail.prepare_auto_preview_log(path)
            _PREVIEW_DECODE_MANAGER.request(path, mtime, cancel_event=self.cancel_event, force_render=True)
            if key not in _PREVIEW_DECODE_MANAGER.active:
                self.active_key = None
                self.active_identity = None
                self.cancel_event = None
            return

    def _on_preview_ready(self, path_str: str, mtime: float, image):
        if path_str != self.active_key:
            return
        canceled = self.cancel_event is not None and self.cancel_event.is_set()
        if canceled:
            self._append_log(f"[---] {Path(path_str).name} — interrompu par une activité utilisateur")
        else:
            message = "Aperçu terminé" if image is not None and not image.isNull() else "Aperçu indisponible"
            self._append_log(f"[100%] {Path(path_str).name} — {message}")
        identity = self.active_identity
        self.active_key = None
        self.active_identity = None
        self.cancel_event = None
        self.active_log_path = None
        if canceled:
            if identity is not None:
                self.queue.insert(0, (Path(path_str), mtime))
            return
        if identity is not None:
            self.done.add((path_str, mtime))
        if self.is_idle and self._user_is_idle():
            self._start_next()


_FALLBACK_SOFTWARE_BADGE_PALETTE = [
    ("#5c6bc0", "#eef0ff"), ("#26a69a", "#e8fff9"), ("#8d6e63", "#fff3e6"),
    ("#7e57c2", "#f2ecff"), ("#42a5f5", "#e8f4ff"), ("#66bb6a", "#eafff0"),
    ("#ec407a", "#ffe9f1"), ("#ffa726", "#3a2200"),
]


def _fallback_software_badge_style(key: str) -> tuple[str, str, str]:
    """Couleur/lettres d'un logiciel AJOUTE par l'utilisateur (voir
    software_icon_key/app_style.custom_softwares) : pas de charte connue
    comme SOFTWARE_ICONS, mais un badge STABLE (meme cle -> toujours la
    meme couleur/les memes lettres) plutot qu'un rendu incoherent."""
    label_source = next((e["label"] for e in custom_softwares() if e["key"] == key), key)
    bg, fg = _FALLBACK_SOFTWARE_BADGE_PALETTE[sum(ord(c) for c in key) % len(_FALLBACK_SOFTWARE_BADGE_PALETTE)]
    letters = "".join(ch for ch in label_source if ch.isalnum())[:2].upper() or "?"
    return bg, fg, letters


def _generate_software_badge(key: str, size: int) -> QPixmap:
    entry = SOFTWARE_ICONS.get(key)
    bg, fg, label = entry if entry is not None else _fallback_software_badge_style(key)
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(bg))
    radius = max(2, round(size * 0.22))
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    painter.setFont(font(max(8, round(size * 0.44)), 700))
    painter.setPen(QColor(fg))
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, label)
    painter.end()
    return pix


def software_icon_pixmap(key: str, size: int) -> QPixmap:
    """Icone perso (voir custom_software_icon_path) si elle existe, sinon
    badge genere pour le logiciel `key` (voir SOFTWARE_ICONS)."""
    custom = custom_software_icon_path(key)
    try:
        mtime = custom.stat().st_mtime if custom.is_file() else None
    except OSError:
        mtime = None

    cache_key = (key, size)
    cached = _software_icon_cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]

    pix = None
    if mtime is not None:
        loaded = QPixmap(str(custom))
        if not loaded.isNull():
            pix = _contain_square(loaded, size)
    if pix is None:
        pix = _generate_software_badge(key, size)

    _software_icon_cache[cache_key] = (mtime, pix)
    return pix


def _row_icon_pixmap(is_dir: bool, icon_key: str | None, size: int) -> QPixmap | None:
    """Icone de gauche pour UNE ligne (voir _paint_unified_row) : celle du
    logiciel reconnu si `icon_key` en a un ; sinon, le REPLI par defaut
    dossier/fichier choisi dans Settings > ICONES > General (voir
    UI_ICON_FOLDER_DEFAULT/UI_ICON_FILE_DEFAULT) si l'utilisateur en a
    choisi un ; sinon None (comportement inchange : aucune icone)."""
    if icon_key is not None:
        return software_icon_pixmap(icon_key, size)
    return custom_ui_icon_pixmap(UI_ICON_FOLDER_DEFAULT if is_dir else UI_ICON_FILE_DEFAULT, size)


_PIN_ICON_CACHE: dict[tuple[bool, int], QPixmap] = {}


def _pin_icon_pixmap(active: bool, size: int) -> QPixmap:
    """Icone punaise d'en-tete de colonne (voir Column._toggle_pin, la
    remarque de l'utilisateur, "je viens de te coller deux icones ...
    punaise_01.png [par defaut] / punaise_02.png [actif]") — chargee une
    fois depuis icons/, puis mise a l'echelle en carre CONTENU (voir
    _contain_square/_smooth_scale_down, memes raisons que software_icon_
    pixmap : source haute resolution, jamais pixelisee en la retrecissant
    vers la petite taille d'en-tete)."""
    custom = custom_ui_icon_pixmap(UI_ICON_PIN_ACTIVE if active else UI_ICON_PIN_INACTIVE, size)
    if custom is not None:
        return custom
    key = (active, size)
    cached = _PIN_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    src = QPixmap(str(ICONS_DIR / ("punaise_02.png" if active else "punaise_01.png")))
    pix = _contain_square(src, size) if not src.isNull() else QPixmap()
    _PIN_ICON_CACHE[key] = pix
    return pix

# ==========================================================================
# Design tokens : voir app_style.py (C, STYLESHEET, font()) partage entre
# toutes les applications du pipeline.
# ==========================================================================

COLUMN_WIDTH = 220
COLUMN_MIN_WIDTH = 120
COLUMN_MAX_WIDTH = 640
COLUMN_RESIZE_MARGIN = 5   # zone (px) autour de la bordure ou le curseur change
# Hauteur des colonnes du groupe IN/OVER/OUT/LOGICIELS (voir Column.
# __init__ group_kind/fill_height, height_resize_begin/update/end) :
# CHACUNE a sa PROPRE hauteur, independante des 3 autres, redimensionnable a
# la main comme n'importe quel bord — SAUF la DERNIERE colonne de l'ordre
# courant (voir PipelineBrowser._group_column_order), qui reste TOUJOURS
# etiree jusqu'en bas de la page (comme une colonne normale, pas de poignee
# de redimensionnement) — voir la remarque de l'utilisateur, "je ne veux
# pas qu'elles aient toute la meme hauteur, mais chacune leur hauteur ...
# il est important que la derniere colonne aille bien jusqu'en bas de la
# page".
GROUP_COLUMN_DEFAULT_HEIGHT = 220
GROUP_COLUMN_MIN_HEIGHT = 80
GROUP_COLUMN_MAX_HEIGHT = 900
# Repli local (voir _WIDGET_SIZE_MAX) : valeur historique de
# QWIDGETSIZE_MAX (2**24-1, absente de certains bindings PySide6) utilisee
# pour LIBERER la hauteur maximale d'une colonne du groupe qui redevient la
# DERNIERE (voir Column.set_group_fill_height) — memes raison/valeur que
# l'ancienne constante module-level du meme nom, retiree avec la refonte du
# detail "Fichiers pour X".
_WIDGET_SIZE_MAX = 16777215
# Redimensionnement des lignes a la souris (Ctrl + clic entre 2 lignes +
# glisser, voir Column.row_resize_begin/_in_row_resize_zone, disponible sur
# TOUTE colonne) — memes bornes que le slider "Hauteur de la ligne" de la
# fenetre de parametres (voir settings_window._ITEM_TEXT_FIELD_SPECS) pour
# qu'une valeur posee ici ne soit jamais silencieusement recadree en
# rouvrant les parametres.
ROW_RESIZE_MIN_HEIGHT = 14
ROW_RESIZE_MAX_HEIGHT = 80
ROW_HEIGHT = 24
ROW_SPACING = 1            # espace (px) entre les lignes, dans toutes les colonnes
HEADER_HEIGHT = 26
HEADER_PADDING = 0    # inset (4 cotes) entre le fond colore de l'entete et les bords de la colonne/inspecteur (voir Column/DetailPanel)
TOPBAR_HEIGHT = 40
STATUS_HEIGHT = 24
TITLEBAR_HEIGHT = 28
# Largeur de depart de l'Inspecteur (voir DetailPanel.__init__) — mutable
# par apply_all_settings (cle "detail_panel_width") : auto-enregistree sans
# punaise, comme Type/Focus, voir DetailPanel.mouseReleaseEvent — la
# colonne Inspecteur n'a pas de bouton punaise ni d'onglet de surcharge
# PAR TITRE dedie, une simple cle GENERALE suffit (une seule instance dans
# toute l'appli, contrairement a Type/Focus qui partagent un bucket de
# style avec d'autres colonnes du meme genre).
DETAIL_PANEL_WIDTH = 300
DETAIL_PANEL_MIN_WIDTH = 220
DETAIL_PANEL_MAX_WIDTH = 520
GLOBAL_OMIT_FILE_NAMES: set[str] = set()
GLOBAL_OMIT_FILE_EXTENSIONS: set[str] = set()
# INSPECTOR_TITLE (titre "virtuel" pour resoudre le style EFFECTIF de
# l'inspecteur, voir app_style.column_style_for/DetailPanel.refresh_header/
# refresh_colors) est desormais importe depuis app_style.py, MEME raison
# que PREVIEW_STACK_TITLE ci-dessous : possede maintenant son propre onglet
# de surcharge (voir SettingsWindow._build_columns_page) — voir la remarque
# de l'utilisateur, "ajoute ... la colonne inspecteur" (dans les settings).
# PREVIEW_STACK_TITLE (la colonne fantome de l'apercu image empile, une
# fois une selection faite dans Projets/Sous-projet) est desormais
# importee depuis app_style.py — settings_window.py en a aussi besoin
# depuis qu'elle a son propre onglet de surcharge (voir
# SettingsWindow._build_columns_page), d'ou son deplacement la-bas (MEME
# raison que COLUMN_TYPE_OVERRIDE_KEYS : source UNIQUE partagee entre les
# 2 fichiers plutot que dupliquee).

# Rayon de bordure de la fenetre principale (Parametres > General). Voir
# PipelineBrowser.__init__ (WA_TranslucentBackground) pour le mecanisme.
WINDOW_RADIUS = 0
# Rayon de bordure applique a TOUS les boutons (Parametres > Boutons) : voir
# app_style.set_button_radius / build_stylesheet.
BUTTON_RADIUS = 0

# ==========================================================================
# Reglages par colonne (fenetre de parametres > pages "Colonne ...") :
# largeur / hauteur de ligne / espacement, et pour les colonnes a vignettes,
# padding/rayon des images qu'elles affichent (vignettes de projet pour
# Projets/Sous-projet, apercus fichier-image pour Logiciels/Contenu). Cle =
# COLUMN_LABELS (ou "Contenu" pour toute colonne au-dela de Logiciels).
# COLUMN_LABELS n'est definie que plus bas dans le fichier ; les reglages par
# defaut ci-dessous sont donc indexes a la main sur les memes intitules.
# ==========================================================================

COLUMN_SETTINGS: dict[str, dict[str, int]] = {
    "Type":        {"width": 140, "height": 25, "spacing": 0, "img_pad": 0, "img_radius": 0},
    "Projets":     {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0},
    "Sous-projet": {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0},
    "Logiciels":   {"width": 186, "height": 30, "plain_height": 22, "spacing": 0, "img_pad": 3, "img_radius": 2},
    "Contenu":     {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
    # IN/OVER/OUT (colonnes du groupe fantome, voir update_preview_stack) :
    # memes valeurs de depart que "Contenu" — c'est le bucket qu'elles
    # partageaient AVANT d'obtenir leur propre onglet de surcharge dedie
    # (voir SettingsWindow._build_columns_page, la remarque de
    # l'utilisateur, "ajoute la colonne logiciels dans les settings, ainsi
    # que in over et out") : aucun changement visuel tant qu'aucune
    # surcharge n'est activee pour l'une d'elles.
    "IN":          {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
    "OVER":        {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
    "OUT":         {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
}

# Style de Colonnes/Entetes/Items par titre reel (voir settings_window.
# _section_headers, "Colonnes" dans l'onglet General, et
# _build_column_override_page pour les surcharges par titre) — cles
# EFFECTIVEMENT resolues (general OU surcharge, voir apply_all_settings
# ci-dessous) dans app_style.set_column_style/column_style_for, lues par
# Column/RowDelegate (voir Column.refresh_colors/refresh_header,
# _paint_unified_row). "column_gap" est volontairement absent : un
# espacement ENTRE colonnes n'a pas de sens pour une seule colonne.
# Colonne/entete (fond/bordure/rayon/padding — voir app_style.column_frame_
# qss/column_header_qss/column_padding_for) et cles "item_*" (texte/
# selection des LIGNES, voir _paint_unified_row) sont TOUTES deux
# APPLIQUEES a TOUTE colonne depuis l'unification du rendu — voir la
# remarque de l'utilisateur, "je veux que tu reformate toutes les autres
# colonnes exactement de la meme maniere que la colonne type". Listes
# elles-memes definies dans app_style.py (COLUMN_FRAME_KEYS/
# COLUMN_TYPE_OVERRIDE_KEYS, importees ci-dessus) — SOURCE UNIQUE partagee
# avec settings_window.py, qui ne peut pas importer CE fichier (sens
# d'import inverse) mais peut importer app_style.py comme ici.


# Colonnes > Texte > Police : libelle "police du soft" (voir
# app_style.ITEM_FONT_ROLE_LABELS) -> role (voir role_font) — sens
# INVERSE de la table de settings_window (qui, elle, va du role vers le
# libelle affiche dans le selecteur) — utilise par Column.refresh_fonts
# pour resoudre la famille REELLEMENT choisie pour ce role.
_ITEM_FONT_LABEL_TO_ROLE = {label: role for role, label in ITEM_FONT_ROLE_LABELS.items()}

# Padding (dict, 4 cotes INDEPENDANTS) et rayon (dict, 4 coins
# INDEPENDANTS) appliques a la grande vignette carree de l'apercu empile
# (voir _SquarePreviewImage) — distinct du padding par colonne ci-dessus,
# qui lui ne concerne que les vignettes DANS les lignes des colonnes
# Projets/Sous-projet/Logiciels/Contenu.
PREVIEW_IMAGE_PAD: dict = {}
PREVIEW_IMAGE_RADIUS: dict = {}

# Style EFFECTIF du cadre de redimensionnement (voir _show_resize_width/
# _resize_width_indicator, General > Colonnes > "Cadre de redimensionnement"
# des reglages) — repeuple entierement par apply_all_settings, jamais lu
# ailleurs qu'a l'affichage du badge (pas un chemin chaud) — voir la
# remarque de l'utilisateur, "je veux que dans general/colonnes/ tu crees
# une sous section cadre de redimensionnement". Valeurs par defaut ICI =
# comportement D'AVANT ce reglage (coin bas-droit, police mono de l'appli,
# fond/bordure C['chrome']/C['border'] fige, 1px, 4px de rayon) — utilisees
# tant qu'apply_all_settings n'a pas encore tourne (tout debut du
# demarrage).
RESIZE_BADGE_STYLE: dict = {
    "position": "bottom_right",
    "offset_x": 8,
    "offset_y": 8,
    "font_family": "",
    "text_color": "#d6d9dc",
    "bg_color": "#202326",
    "border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "border": {"top": "@border2", "right": "@border2", "bottom": "@border2", "left": "@border2"},
    "border_thickness": 1,
    "border_radius": {"top_left": 4, "top_right": 4, "bottom_right": 4, "bottom_left": 4},
}


def _col_key(title: str) -> str:
    return title if title in COLUMN_SETTINGS else "Contenu"


# Chaque accesseur passe par scaled() (voir app_style.py) : les valeurs
# stockees dans COLUMN_SETTINGS restent les grandeurs "logiques" (100%,
# telles que reglees dans la fenetre de parametres), la mise a l'echelle ne
# s'applique qu'ici, a l'usage — meme principe que role_font() pour le
# texte. Ainsi le slider "Scale general de l'interface" affecte aussi les
# colonnes/lignes/vignettes, pas seulement les polices.

def col_width(title: str) -> int:
    return scaled(COLUMN_SETTINGS[_col_key(title)]["width"])


def col_row_height(title: str) -> int:
    return scaled(COLUMN_SETTINGS[_col_key(title)]["height"])


def col_plain_height(title: str) -> int:
    """Hauteur des lignes SANS apercu (fichier ordinaire, pas une image/
    .obj/.psd/.exr/video) dans une colonne qui melange les deux (voir
    RowDelegate.sizeHint) — plus basse que col_row_height, inutile de
    reserver la place d'une vignette carree la ou aucune n'est dessinee.
    Repli sur "height" si la colonne n'a pas de reglage distinct (colonnes
    a vignettes systematiques comme Projets/Sous-projet, ou Type qui n'a
    jamais d'image du tout : une seule hauteur y suffit)."""
    settings = COLUMN_SETTINGS[_col_key(title)]
    return scaled(settings.get("plain_height", settings["height"]))


def col_spacing(title: str) -> int:
    # minimum=0 : un espacement regle a 0 doit rester 0 apres mise a
    # l'echelle (voir scaled()), sinon deux lignes contigues se
    # retrouveraient quand meme separees par 1px.
    return scaled(COLUMN_SETTINGS[_col_key(title)]["spacing"], minimum=0)


def col_img_pad(title: str) -> int:
    # minimum=0, meme raison que col_spacing : un padding regle a 0 ne doit
    # jamais remonter a 1px (voir scaled()), sans quoi l'image d'une
    # vignette parait rognee/decalee d'un cote alors que le reglage
    # affiche bien 0.
    return scaled(COLUMN_SETTINGS[_col_key(title)]["img_pad"], minimum=0)


def col_img_radius(title: str) -> int:
    return scaled(COLUMN_SETTINGS[_col_key(title)]["img_radius"], minimum=0)


# ==========================================================================
# Scan disque
# ==========================================================================

def _is_globally_omitted_file(name: str) -> bool:
    lowered = name.casefold()
    return lowered in GLOBAL_OMIT_FILE_NAMES or any(
        lowered.endswith("." + extension) for extension in GLOBAL_OMIT_FILE_EXTENSIONS
    )


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return ""


def list_entries(directory: Path, exclude: frozenset[str] | None = None) -> list[Path]:
    """Dossiers puis fichiers, tries. Les FLATTEN_FOLDERS sont traverses.
    `exclude` (noms en minuscules) : entrees jamais listees, quel que soit
    leur contenu — voir STATUS_FOLDERS, exclus des colonnes Projets/
    Sous-projet (voir Column.refresh)."""
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
                    continue
                if exclude and entry.name.lower() in exclude:
                    continue
                path = Path(entry.path)
                if entry.is_dir():
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        dirs.extend(p for p in list_entries(path) if p.is_dir())
                    else:
                        dirs.append(path)
                else:
                    if _is_globally_omitted_file(entry.name):
                        continue
                    files.append(path)
    except OSError:
        return []
    key = lambda p: p.name.lower()
    return sorted(dirs, key=key) + sorted(files, key=key)


# Dossiers de statut d'un projet/sous-projet (in/over/out), affiches comme
# des indicateurs dedies au-dessus de sa vignette dans l'apercu empile (voir
# _PreviewBlock) plutot que comme des lignes normales : jamais listes tels
# quels dans les colonnes Projets/Sous-projet (voir Column.refresh).
STATUS_FOLDERS = ("in", "over", "out")
_STATUS_FOLDER_SET = frozenset(STATUS_FOLDERS)


def _translucent_grab(widget: QWidget, opacity: float = 0.55) -> QPixmap:
    """Capture de `widget` (voir Column.eventFilter, group_kind) rendue
    semi-transparente, utilisee comme image suivant le curseur pendant le
    glisser-deposer d'une colonne du groupe IN/OVER/OUT/LOGICIELS — voir la
    remarque de l'utilisateur, "possible lors du glisser d'avoir la colonne
    en curseur avec de la transparence ?". Repeint dans un PIXMAP A PART
    (fond transparent + opacite du QPainter) plutot qu'un simple
    setWindowOpacity sur le widget source : celui-ci reste affiche a l'ecran
    pendant le glisser, une capture directe serait donc a pleine opacite
    quoi que ce reglage change."""
    source = widget.grab()
    result = QPixmap(source.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return result


def _make_group_drag_ghost(column: QWidget) -> QWidget:
    """Petite fenetre top-level SANS decoration, qui affiche la capture
    semi-transparente de `column` (voir _translucent_grab) et suit le
    curseur pendant le glisser d'un en-tete du groupe IN/OVER/OUT/LOGICIELS
    — voir Column.eventFilter (group_kind), qui la deplace a chaque
    MouseMove et la ferme au relachement. Qt.ToolTip (pas de barre de
    titre/entree dans la barre des taches, ne prend jamais le focus) +
    WA_TransparentForMouseEvents (ne doit jamais intercepter le clic —
    la cible du depot est determinee a la main par _find_group_drop_target,
    pas par ce que Qt voit sous le curseur)."""
    ghost = QLabel(None)
    ghost.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    ghost.setAttribute(Qt.WA_TranslucentBackground, True)
    ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    ghost.setAttribute(Qt.WA_ShowWithoutActivating, True)
    pixmap = _translucent_grab(column)
    ghost.setPixmap(pixmap)
    ghost.resize(pixmap.size())
    ghost.show()
    return ghost


def _dir_has_content(directory: Path) -> bool:
    """True des que `directory` contient au moins une entree visible
    (fichier ou dossier, hors HIDDEN_PREFIXES)."""
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if not entry.name.startswith(HIDDEN_PREFIXES):
                    if not entry.is_dir() and _is_globally_omitted_file(entry.name):
                        continue
                    return True
    except OSError:
        pass
    return False


def status_folder_state(directory: Path, name: str) -> tuple[bool, Path]:
    """Etat d'un dossier de statut (in/over/out) sous `directory` : (actif,
    chemin). Actif = le dossier existe (insensible a la casse) et n'est pas
    vide. Le chemin retourne est celui trouve sur le disque si actif, sinon
    `directory / name` (repli pour l'ouverture eventuelle malgre tout)."""
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_dir() and entry.name.lower() == name:
                    path = Path(entry.path)
                    return _dir_has_content(path), path
    except OSError:
        pass
    return False, directory / name


# Convention du pipeline : les logiciels d'un sous-projet vivent dans un
# sous-dossier "softs" (F:\PIPELINE\...\<sous-projet>\softs\<logiciel>), pas
# directement sous le sous-projet (qui a aussi "in"/"out"...). Voir
# _named_subdir, utilise par PipelineBrowser.on_selected en ouvrant la
# colonne "Logiciels", ET par la chaine de navigation CONFIGUREE (voir
# load_project_columns/ColumnConfigDialog) pour CHAQUE niveau configure —
# meme convention generalisee (nom de sous-dossier FIXE, pas un choix libre)
# — voir la remarque de l'utilisateur, "chaque colonne configuree pointe
# vers un nom de dossier fixe".
SOFTS_FOLDER_NAME = "softs"


def _named_subdir(directory: Path, name: str) -> Path:
    """Repertoire reellement liste pour un niveau de navigation dont le nom
    de dossier est FIXE (voir SOFTS_FOLDER_NAME/_softs_subdir, l'ancien nom
    de cette fonction avant sa generalisation a la chaine configurable) : le
    sous-dossier `name` de `directory` (insensible a la casse) s'il existe,
    sinon `directory` lui-meme (repli si la convention n'est pas suivie)."""
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_dir() and entry.name.lower() == name.lower():
                    return Path(entry.path)
    except OSError:
        pass
    return directory


def _softs_subdir(directory: Path) -> Path:
    return _named_subdir(directory, SOFTS_FOLDER_NAME)


def _count_dirs_recursive(directory: Path) -> int:
    """Nombre de dossiers obtenus en listant `directory` avec repli des
    FLATTEN_FOLDERS (memes regles que list_entries, mais ne garde que les
    dossiers) : utilise par count_entries pour les FLATTEN_FOLDERS imbriques."""
    count = 0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
                    continue
                if entry.is_dir():
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        count += _count_dirs_recursive(Path(entry.path))
                    else:
                        count += 1
    except OSError:
        return 0
    return count


def count_entries(directory: Path, exclude: frozenset[str] | None = None) -> int:
    """Equivalent de len(list_entries(directory, exclude)), sans construire
    ni trier de liste : utilise pour la seule metadonnee « N elements » des
    colonnes a vignettes (Projets, Sous-projet), recalculee pour chaque
    ligne a chaque refresh() — le tri et l'allocation de list_entries y sont
    un travail pur perte, le compte etant la seule chose utilisee."""
    count = 0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
                    continue
                if exclude and entry.name.lower() in exclude:
                    continue
                if entry.is_dir():
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        count += _count_dirs_recursive(Path(entry.path))
                    else:
                        count += 1
                else:
                    if _is_globally_omitted_file(entry.name):
                        continue
                    count += 1
    except OSError:
        return 0
    return count


def project_thumbnail_path(directory: Path) -> Path:
    """Emplacement de la vignette perso d'un dossier de projet (fichier
    cache, jamais liste par list_entries puisqu'il commence par un point)."""
    return directory / THUMBNAIL_FILENAME


_project_thumbnail_cache: dict[str, tuple[float | None, QPixmap]] = {}


def project_thumbnail_pixmap(path: Path) -> QPixmap:
    """Vignette perso de `path` (voir project_thumbnail_path), ou image par
    defaut generique si aucune n'a ete choisie. Mise en cache par date de
    modification (cache borne, voir _bounded_cache_set) — seule source pour
    ces vignettes : ProjectTileDelegate (colonnes) et l'apercu empile de la
    premiere colonne s'y refere tous deux, plutot que de garder chacun leur
    propre copie en memoire du meme fichier."""
    thumb = project_thumbnail_path(path)
    try:
        mtime = thumb.stat().st_mtime if thumb.is_file() else None
    except OSError:
        mtime = None
    key = str(path)
    cached = _project_thumbnail_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    pix = QPixmap(str(thumb)) if mtime is not None else QPixmap()
    if pix.isNull():
        pix = default_thumbnail()
    _bounded_cache_set(_project_thumbnail_cache, key, (mtime, pix))
    return pix


_default_thumbnail: QPixmap | None = None


def default_thumbnail() -> QPixmap:
    """Image generique (montagne + soleil) utilisee tant qu'aucune vignette
    perso n'a ete choisie pour un projet. Generee une seule fois."""
    global _default_thumbnail
    if _default_thumbnail is not None:
        return _default_thumbnail

    size = 480
    pix = QPixmap(size, size)
    pix.fill(QColor(C["well"]))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)

    margin = round(size * 0.26)
    frame = pix.rect().adjusted(margin, margin, -margin, -margin)

    pen = QPen(QColor(C["mark_dir_bd"]))
    pen.setWidth(round(size * 0.014))
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(frame, 8, 8)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(C["mark_dir_bd"]))

    sun_r = round(frame.width() * 0.11)
    sun_c = QPoint(frame.left() + round(frame.width() * 0.27), frame.top() + round(frame.height() * 0.3))
    painter.drawEllipse(sun_c, sun_r, sun_r)

    poly = QPolygon([
        QPoint(frame.left() + round(frame.width() * 0.04), frame.bottom() - round(frame.height() * 0.1)),
        QPoint(frame.left() + round(frame.width() * 0.38), frame.top() + round(frame.height() * 0.38)),
        QPoint(frame.left() + round(frame.width() * 0.58), frame.bottom() - round(frame.height() * 0.28)),
        QPoint(frame.left() + round(frame.width() * 0.74), frame.top() + round(frame.height() * 0.56)),
        QPoint(frame.right() - round(frame.width() * 0.04), frame.bottom() - round(frame.height() * 0.1)),
    ])
    painter.drawPolygon(poly)
    painter.end()

    _default_thumbnail = pix
    return pix


# ==========================================================================
# Chaine de navigation configurable PAR PROJET (voir ColumnConfigDialog) —
# voir la remarque de l'utilisateur, "j'aimerai que cette configuration
# change, mais suivant les besoins de l'utilisateur ... cette icone doit
# etre cliquable et faire apparaitre une fenetre qui permettra de determiner
# le nombres de colonnes a deployer". Stockee DANS le dossier du projet
# (voyage avec lui, meme esprit que THUMBNAIL_FILENAME/project_thumbnail_
# path juste au-dessus) — un projet SANS ce fichier (cas le plus courant,
# tant que l'utilisateur n'a jamais ouvert cette fenetre) garde EXACTEMENT
# la chaine fixe Type/Projets/Sous-projet/Logiciels d'aujourd'hui (voir
# PipelineBrowser.on_selected, branche `if config is None`).
# ==========================================================================

PROJECT_COLUMNS_FILENAME = ".pipeline_columns.json"

# "Type" du repertoire de travail final (voir ColumnConfigDialog, menu
# deroulant "Repertoire de travail > Type") : cle -> nom de DOSSIER fixe
# recherche (voir _named_subdir), libelle du menu deroulant ("label"),
# intitule affiche en entete de la colonne du groupe ("display", INCHANGE
# entre les 2 types — c'est la meme colonne conceptuelle, seule son
# APPARENCE change), et cle de STYLE ("style_title", voir column_style_for)
# qui pilote reellement hauteur de ligne/police/couleurs/bordures/padding —
# voir la remarque de l'utilisateur, "je veux avoir le choix entre deux
# types : logiciels ... et standard ... elle doit avoir le meme
# comportement que les colonnes standards que l'on trouve apres" :
# "standard" reutilise donc la cle "Contenu", DEJA partagee par IN/OVER/OUT
# (voir add_group_column plus bas) et desactive only_recognized_software
# (icones/filtre "logiciel reconnu", propre au type "logiciel").
WORK_DIR_TYPES: dict[str, dict] = {
    "logiciel": {
        "folder_name": SOFTS_FOLDER_NAME, "label": "Logiciels",
        "display": SOFTWARE_COLUMN_LABEL, "style_title": SOFTWARE_COLUMN_LABEL,
        "only_recognized_software": True,
    },
    "standard": {
        "folder_name": SOFTS_FOLDER_NAME, "label": "Standard",
        "display": SOFTWARE_COLUMN_LABEL, "style_title": "Contenu",
        "only_recognized_software": False,
        # En-tete DYNAMIQUE (voir update_preview_stack, "display" ci-dessus
        # ignore alors) : reprend le nom de la selection de la colonne
        # PRECEDENTE (terminal_path), exactement comme une colonne "de set"
        # normale (voir add_column/display_title) — voir la remarque de
        # l'utilisateur, "quand la colonne logiciels n'est pas formatee
        # comme logiciel, je veux qu'elle ait le nom de la selection de la
        # colonne precedente".
        "display_from_selection": True,
    },
}
DEFAULT_WORK_DIR_TYPE = "logiciel"


def _project_columns_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_COLUMNS_FILENAME


def _coerce_project_column(raw: dict) -> dict:
    """Normalise UN niveau de la chaine configuree (voir load_project_
    columns) — repli sur des valeurs sures pour toute cle manquante/mal
    typee dans un JSON ecrit a la main ou corrompu, plutot que de faire
    planter toute la navigation pour un seul projet mal configure."""
    name = str(raw.get("name") or "").strip()
    return {
        "name": name,
        "show_dirs": bool(raw.get("show_dirs", True)),
        "show_files": bool(raw.get("show_files", False)),
        "omit_dirs": [str(v) for v in (raw.get("omit_dirs") or []) if str(v).strip()],
        "omit_files": [str(v) for v in (raw.get("omit_files") or []) if str(v).strip()],
        "focus": bool(raw.get("focus", False)),
    }


def _coerce_work_dir(raw: dict) -> dict:
    work_type = raw.get("type")
    if work_type not in WORK_DIR_TYPES:
        work_type = DEFAULT_WORK_DIR_TYPE
    return {
        "type": work_type,
        "show_dirs": bool(raw.get("show_dirs", True)),
        "show_files": bool(raw.get("show_files", False)),
        "omit_dirs": [str(v) for v in (raw.get("omit_dirs") or []) if str(v).strip()],
        "omit_files": [str(v) for v in (raw.get("omit_files") or []) if str(v).strip()],
    }


_PROJECT_COLUMNS_CACHE: dict[Path, tuple[float | None, dict | None]] = {}


def load_project_columns(project_dir: Path) -> dict | None:
    """Configuration de chaine de navigation propre a `project_dir` (voir
    PROJECT_COLUMNS_FILENAME) — None si le fichier est absent/illisible/
    invalide (repli SILENCIEUX sur la chaine legacy fixe, voir on_selected :
    un JSON corrompu ne doit jamais empecher de naviguer, juste ignorer la
    personnalisation) : `{"columns": [{"name","show_dirs","show_files",
    "omit_dirs","omit_files","focus"}, ...], "work_dir": {"type",
    "show_dirs","show_files","omit_dirs","omit_files"}}`. Chaque niveau de
    "columns" ne garde jamais un `name` vide (voir _coerce_project_column) —
    un niveau sans nom n'aurait aucun dossier fixe a chercher. "columns"
    VIDE est desormais une configuration VALIDE (voir ColumnConfigDialog.
    MIN_STEPS, "base 2" : Type+Projets, directement suivis du repertoire de
    travail, aucun niveau intermediaire) — voir la remarque de
    l'utilisateur, "peux-tu faire en sorte de pouvoir setter en base 2" :
    distinct d'un fichier ABSENT/invalide (repli sur la chaine legacy a 3
    etapes), un fichier valide avec "columns": [] doit rester tel quel,
    PAS retomber sur le repli legacy.

    Cache par mtime (voir _PROJECT_COLUMNS_CACHE, meme principe que
    software_icon_pixmap) : appelee a CHAQUE peinture d'une ligne "Projets"
    (voir ProjectTileDelegate.paint, step_badge) — sans cache, un
    Ctrl+glisser de redimensionnement de ligne (jusqu'a ~60 relayouts/s,
    voir _throttled_layout) relisait ce fichier ET reparsait son JSON a
    CHAQUE ligne visible ET a CHAQUE frame, d'ou la lenteur constatee par
    l'utilisateur specifiquement sur cette colonne, "quand je veux
    redimensionner les lignes ... il y a de grosses lenteurs"."""
    path = _project_columns_path(project_dir)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    cached = _PROJECT_COLUMNS_CACHE.get(project_dir)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    result: dict | None = None
    if mtime is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            columns = [_coerce_project_column(c) for c in (raw.get("columns") or []) if isinstance(c, dict)]
            columns = [c for c in columns if c["name"]]
            result = {
                "columns": columns, "work_dir": _coerce_work_dir(raw.get("work_dir") or {}),
                # Toggles maitres (voir ColumnConfigDialog, la remarque de
                # l'utilisateur, "j'aimerai ajouter trois toggles ... set /
                # focus / logiciels" puis "in over et out") — defaut True
                # partout : comportement INCHANGE pour un fichier ecrit
                # AVANT ce reglage. Toggle "logiciels" SUPPRIME depuis (voir
                # la remarque de l'utilisateur, "supprime le toggle
                # logiciels") — la cle "logiciels_enabled" d'un fichier plus
                # ancien est desormais simplement IGNOREE, jamais relue.
                "set_enabled": bool(raw.get("set_enabled", True)),
                "focus_enabled": bool(raw.get("focus_enabled", True)),
                "in_over_out_enabled": bool(raw.get("in_over_out_enabled", True)),
            }
    _PROJECT_COLUMNS_CACHE[project_dir] = (mtime, result)
    return result


def save_project_columns(project_dir: Path, config: dict) -> None:
    """Ecrit `config` (MEME forme que load_project_columns) dans le dossier
    du projet — voir ColumnConfigDialog._on_save. `_set_hidden` (deja
    utilise pour .thumbnail.png/.pipeline_preview_cache) : cache le fichier
    a l'explorateur Windows, meme convention que le reste des fichiers
    internes de l'appli poses directement dans un dossier de projet.
    `_clear_hidden` AVANT d'ecrire (voir sa remarque de tete) : ce fichier a
    deja pu etre cache par un PRECEDENT appel — sans ca, toute MODIFICATION
    d'une configuration existante echouait silencieusement (PermissionError
    non rattrapee)."""
    path = _project_columns_path(project_dir)
    payload = {
        "columns": [_coerce_project_column(c) for c in config.get("columns", [])],
        "work_dir": _coerce_work_dir(config.get("work_dir") or {}),
        "set_enabled": bool(config.get("set_enabled", True)),
        "focus_enabled": bool(config.get("focus_enabled", True)),
        "in_over_out_enabled": bool(config.get("in_over_out_enabled", True)),
    }
    _clear_hidden(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _set_hidden(path)
    # Purge le cache (voir load_project_columns) : une resolution de mtime
    # au-dela de la seconde (courante sur certains systemes de fichiers)
    # pourrait sinon renvoyer encore l'ANCIENNE config juste apres cet
    # enregistrement.
    _PROJECT_COLUMNS_CACHE.pop(project_dir, None)


def project_step_count(config: dict | None) -> int | str:
    """Nombre d'etapes necessaires pour etre "bien sette" dans l'espace de
    travail d'un projet (voir le badge numerote, ProjectTileDelegate.paint)
    — Type + Projets (2, TOUJOURS presents) + le nombre de niveaux
    configures avant le repertoire de travail ; 3 (comportement D'AVANT ce
    reglage — Type/Projets/Sous-projet) si aucune configuration — voir la
    remarque de l'utilisateur, "actuellement l'icone devrait comporter le
    chiffre 3"."""
    if config is None:
        return 3
    if not config.get("set_enabled", True):
        # "N" (PAS 2, voir _step_badge_color/_step_badge_text_color) : sans
        # "set", ce projet n'a plus de nombre d'etapes a proprement parler
        # (aucune limite de profondeur, voir _chain_expected_total/
        # on_selected) — voir la remarque de l'utilisateur, "quand set est
        # desactive je veux que l'indicateur de base affiche N".
        return "N"
    return 2 + len(config["columns"])


# ==========================================================================
# Reglages de MISE EN PAGE propres a UN dossier (hauteur de ligne d'une
# colonne, hauteur des colonnes du groupe IN/OVER/OUT/LOGICIELS) — meme
# convention que .pipeline_columns.json/.thumbnail.png (fichier CACHE pose
# DANS le dossier concerne, voir _set_hidden) : voir la remarque de
# l'utilisateur, "le dimensionnement en hauteur des colonnes de focus doit
# etre enregistre en temps reel et ce dependant du [sous-]dossier ... d'un
# sous dossier a l'autre, les dimensionnements seront differents ...
# exactement pareil pour la hauteur des lignes de dossier et de fichier de
# l'ensemble de l'appli ... des fichiers de settings qui enregistrent ces
# modifs directement sur les emplacements des dossiers". Remplace, pour la
# hauteur de ligne, l'ancien reglage UNIQUEMENT GLOBAL (COLUMN_SETTINGS/
# _col_key, par bucket de style partage entre TOUTES les colonnes de ce
# style) par un reglage PAR DOSSIER REELLEMENT AFFICHE (voir Column.
# directory) — le bucket de style reste le repli par defaut tant qu'aucun
# dossier n'a encore ete ajuste a la main.
# ==========================================================================

LAYOUT_SETTINGS_FILENAME = ".pipeline_layout.json"


def _layout_settings_path(directory: Path) -> Path:
    return directory / LAYOUT_SETTINGS_FILENAME


def load_layout_settings(directory: Path) -> dict:
    """Reglages de mise en page de `directory` — {} si le fichier est
    absent/illisible/invalide (repli SILENCIEUX sur les valeurs par
    defaut, meme esprit que load_project_columns : jamais bloquant)."""
    path = _layout_settings_path(directory)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_layout_settings(directory: Path, data: dict) -> None:
    """Ecrit `data` (dict complet) dans le dossier — voir _update_layout_
    setting pour ne modifier qu'UNE cle. `_clear_hidden` AVANT d'ecrire
    (voir sa remarque de tete, meme piege Windows deja rencontre avec
    save_project_columns) : ce fichier a deja pu etre cache par un
    PRECEDENT appel."""
    path = _layout_settings_path(directory)
    _clear_hidden(path)
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return
    _set_hidden(path)


def _update_layout_setting(directory: Path, key: str, value) -> None:
    """Modifie UNE seule cle des reglages de mise en page de `directory`,
    en conservant les autres (voir save_layout_settings) — appelee a
    CHAQUE relachement de glisser (voir Column.row_resize_end/
    PipelineBrowser._on_group_height_resize_end), jamais pendant le
    glisser lui-meme (memes bornes que _persist_row_height, deja
    limitees au relachement pour ne pas ecrire sur le disque a CHAQUE
    mouvement de souris)."""
    data = load_layout_settings(directory)
    data[key] = value
    save_layout_settings(directory, data)


# Raccourcis (voir Column._on_context_menu "Ajouter un raccourci", refresh()) :
# un dossier situe AILLEURS sur le disque, affiche comme s'il etait
# physiquement dans CE dossier — enregistres dans un fichier cache PROPRE A
# CE DOSSIER (meme convention que .pipeline_layout.json/la punaise), pas dans
# un reglage GENERAL : si le dossier racine change, un raccourci pose ICI ne
# doit jamais se retrouver, par erreur, dans une colonne d'un tout AUTRE
# projet — voir la remarque de l'utilisateur, "de maniere a ce que si on
# change le root, le raccourci ne se retrouve pas dans une colonne malgre
# lui".
SHORTCUTS_FILENAME = ".pipeline_shortcuts.json"


def _shortcuts_path(directory: Path) -> Path:
    return directory / SHORTCUTS_FILENAME


def load_shortcuts(directory: Path) -> list[dict]:
    """Raccourcis de `directory` — [] si le fichier est absent/illisible/
    invalide (repli SILENCIEUX, meme convention que load_layout_settings)."""
    try:
        raw = json.loads(_shortcuts_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and e.get("target")]


def save_shortcuts(directory: Path, shortcuts: list[dict]) -> None:
    path = _shortcuts_path(directory)
    _clear_hidden(path)
    try:
        path.write_text(json.dumps(shortcuts, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return
    _set_hidden(path)


def add_shortcut(directory: Path, target: Path) -> None:
    shortcuts = load_shortcuts(directory)
    target_str = str(target)
    if any(s.get("target") == target_str for s in shortcuts):
        return
    shortcuts.append({"target": target_str})
    save_shortcuts(directory, shortcuts)


def remove_shortcut(directory: Path, target: Path) -> None:
    shortcuts = load_shortcuts(directory)
    target_str = str(target)
    filtered = [s for s in shortcuts if s.get("target") != target_str]
    if len(filtered) != len(shortcuts):
        save_shortcuts(directory, filtered)


# Reglable en direct (voir apply_all_settings/STEP_BADGE_STYLE, Settings >
# Colonnes > Projets > Colonnes > "Icone de niveaux") — ces 2 constantes ne
# restent que comme les toutes PREMIERES valeurs par defaut (avant le tout
# premier apply_all_settings au demarrage, voir main()).
STEP_BADGE_SIZE = 18
STEP_BADGE_MARGIN = 4
STEP_BADGE_STYLE: dict = {
    "width": STEP_BADGE_SIZE, "height": STEP_BADGE_SIZE,
    "border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "border": {}, "border_thickness": 1,
    "radius": {"top_left": 9, "top_right": 9, "bottom_right": 9, "bottom_left": 9},
    "colors": {2: "#5c6368", 3: "#5c6368", 4: "#3f6f9f", 5: "#3f6f9f", 6: "#d9822b", "N": "#5c6368"},
    "text_colors": {2: "#eef2f5", 3: "#eef2f5", 4: "#eef2f5", 5: "#eef2f5", 6: "#eef2f5", "N": "#eef2f5"},
    "offset_x": STEP_BADGE_MARGIN, "offset_y": 0,
    "font_family": "", "font_bold": True, "border_smoothing": True,
    "font_smoothing_enabled": False, "font_smoothing": "current",
}

# Police/couleur des lignes "raccourci" (voir ROLE_IS_SHORTCUT, Settings >
# RACCOURCI) — DISTINCTES du reste du texte de la ligne, pour reperer un
# raccourci au premier coup d'oeil, meme rendu partage (_paint_unified_row)
# que le reste : voir la remarque de l'utilisateur, "police : choix de la
# police avec toggle : app ou systeme, toggle gras ou regulier, couleur,
# taille".
SHORTCUT_TEXT_STYLE: dict = {
    "font_family": "", "font_bold": False, "color": "#8fb4d5", "font_size": 11,
}

# Bouton de repliement de colonne (voir Column.set_collapsed/toggle_btn) :
# "chevrons" (defaut, comportement inchange, voir IconButton kind
# dchevron_left/right) ou "icone" (voir UI_ICON_COLLAPSE_TOGGLE, Settings >
# ICONES > General) — reglage Settings > Colonnes > Focus > Bouton
# repliement > "Icone".
COLLAPSE_TOGGLE_MODE = "chevrons"

def _step_badge_color(n: int | str) -> str:
    """Couleur du badge numerote (voir ProjectTileDelegate.paint) selon le
    nombre d'etapes `n` (project_step_count) — une des 5 couleurs reglables
    (STEP_BADGE_STYLE["colors"], Settings > Colonnes > Projets > Colonnes >
    "Icone de niveaux", "couleur fond base 2 a 6") : n est BORNE a [2, 6],
    2 pour tout n <= 2, 6 pour tout n >= 6 (chaine plus longue que prevu
    par les 5 couleurs — reutilise la derniere plutot que planter).
    `n == "N"` (voir project_step_count, toggle "set" desactive dans
    ColumnConfigDialog) : 6e couleur DEDIEE (STEP_BADGE_STYLE["colors"]
    ["N"]), jamais confondue avec la base 2 — voir la remarque de
    l'utilisateur, "quand set est desactive je veux que l'indicateur de
    base affiche N ... rajoute cette option pour le choix de la couleur
    dans les settings".
    resolve_color_ref (PAS la valeur brute) : ce champ (_AppOrCustomColorField,
    voir sa docstring) peut valoir soit un hex direct, soit une reference
    "@<slot>" a une pastille semantique de l'appli — SANS cette resolution,
    une couleur "app" choisie ici produisait un QColor invalide (chaine
    "@accent" telle quelle, jamais un hex) — voir la remarque de
    l'utilisateur, "il y a des bugs avec les couleurs appli, ca ne
    fonctionne pas"."""
    key = "N" if n == "N" else max(2, min(6, n))
    return resolve_color_ref(STEP_BADGE_STYLE["colors"][key])


def _step_badge_text_color(n: int | str) -> str:
    """Couleur du TEXTE du badge — une PAR base (2 a 6, PAS une seule
    globale) — voir STEP_BADGE_STYLE["text_colors"], Settings > Colonnes >
    Projets > Colonnes > "Icone de niveaux", carre du HAUT de chaque paire
    — voir la remarque de l'utilisateur, "la couleur du haut est pour le
    texte (pour chacune des bases) et la couleur du bas est pour le
    fond". MEME bornage/MEME resolution/MEME cas "N" que _step_badge_color."""
    key = "N" if n == "N" else max(2, min(6, n))
    return resolve_color_ref(STEP_BADGE_STYLE["text_colors"][key])


def _row_preview_left_x(row_rect: QRect, style: dict) -> int:
    """Bord GAUCHE du slot ou l'apercu se dessine sur cette ligne (voir
    _paint_unified_row, "apercu ... ANCRE sur le bord DROIT de la zone de
    selection") — calcul PARTAGE avec le hit-test du badge numerote (voir
    _step_badge_rect/Column.eventFilter), pour rester synchronises SANS
    dupliquer la formule."""
    pad = style.get("item_selection_padding") or {}
    sel_left = row_rect.left() + max(0, int(pad.get("left", 0)))
    sel_width = row_rect.width() - max(0, int(pad.get("left", 0))) - max(0, int(pad.get("right", 0)))
    img_size = row_rect.height() - max(0, int(pad.get("top", 0))) - max(0, int(pad.get("bottom", 0)))
    if img_size <= 0:
        img_size = 14
    img_ratio = float(style.get("item_image_ratio", 1.0) or 1.0)
    img_width = max(1, round(img_size * img_ratio))
    if sel_width > 0:
        return sel_left + sel_width - img_width
    return row_rect.right() - img_width


def _step_badge_rect(row_rect: QRect, preview_left: int | None = None) -> QRect:
    """Rect du badge numerote — voir ProjectTileDelegate.paint/Column.
    eventFilter, fonction PARTAGEE entre le dessin et le hit-test du clic,
    pour rester synchronisees. `preview_left` (voir _row_preview_left_x) :
    juste AVANT (a gauche de) l'apercu de la ligne, PAS par-dessus (voir la
    remarque de l'utilisateur, "j'aimerai que la petite icone de levels
    soit avant l'apercu et pas a l'interieur") — repli sur l'ancien
    comportement (haut-droite de row_rect) si aucun apercu n'est fourni
    (ne devrait plus arriver en pratique, "Projets" en a toujours un, voir
    project_thumbnail_pixmap)."""
    width = STEP_BADGE_STYLE["width"]
    height = STEP_BADGE_STYLE["height"]
    offset_x = STEP_BADGE_STYLE["offset_x"]
    offset_y = STEP_BADGE_STYLE["offset_y"]
    if preview_left is not None:
        x = preview_left - offset_x - width
        y = row_rect.top() + (row_rect.height() - height) // 2 + offset_y
    else:
        x = row_rect.right() - width - offset_x
        y = row_rect.top() + offset_x + offset_y
    return QRect(x, y, width, height)


def _resize_width_indicator(win: QWidget, key: str = "default") -> QLabel:
    """Badge flottant affichant la largeur/hauteur (px) pendant le
    redimensionnement d'une colonne ou du panneau de details (voir
    Column.resize_*/height_resize_*/DetailPanel mousePressEvent/
    mouseMoveEvent/mouseReleaseEvent). UN badge PAR `key`, stocke sur `win`
    (dict `_resize_width_labels`) — la plupart des redimensionnements
    n'utilisent QUE la cle par defaut (un seul actif a la fois, jamais
    besoin de plus d'un badge) ; la SEULE exception est le glisser d'un
    bord de colonne du groupe IN/OVER/OUT/LOGICIELS, qui bouge 2 colonnes a
    la fois (voir PipelineBrowser._on_group_height_resize_begin/
    _on_group_height_resized, cle "group_below" EN PLUS de la cle par
    defaut pour la colonne du dessus) — voir la remarque de l'utilisateur,
    "je veux le cadre de mesure de la hauteur pour les deux colonnes
    concernees par le redimensionnement"."""
    labels = getattr(win, "_resize_width_labels", None)
    if labels is None:
        labels = {}
        win._resize_width_labels = labels
    label = labels.get(key)
    if label is None:
        label = QLabel(win)
        label.setObjectName("ResizeWidthIndicator")
        # Sinon ce badge, place tout pres du bord glisse, peut lui-meme
        # recevoir les evenements souris et bloquer le redimensionnement en
        # cours.
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        labels[key] = label
    return label



def _refresh_resize_width_style(label: QLabel) -> None:
    """Reapplique police/couleur de fond/bordure/rayon du cadre de
    redimensionnement DEPUIS RESIZE_BADGE_STYLE (voir apply_all_settings,
    General > Colonnes > "Cadre de redimensionnement") — rejoue a CHAQUE
    affichage (pas seulement a la creation du badge, voir
    _resize_width_indicator) : ce badge est cree UNE FOIS puis reutilise
    pour toute la duree de vie de la fenetre, sans ca un reglage change en
    cours de session (previsualisation en direct) resterait fige sur le
    style d'a la creation."""
    s = RESIZE_BADGE_STYLE
    # Police (voir _resolve_font_family, MEME resolution "police du soft"
    # (role)/"police systeme" que les autres sections — voir la remarque de
    # l'utilisateur, "pour la police, je veux comme les autres section le
    # choix entre les police appli et systeme") : "" (auto, jamais touche)
    # garde le comportement D'AVANT ce reglage — la police MONO de l'appli
    # (mono_family()), PAS une resolution par role (_resolve_font_family
    # n'a aucun repli "mono", seulement des roles a chasse variable).
    family_label = s.get("font_family") or ""
    size = int(s.get("font_size", 11))
    weight = 600 if s.get("font_bold", True) else 400
    italic = bool(s.get("font_italic", False))
    smoothing = s.get("font_smoothing", "current") if s.get("font_smoothing_enabled") else "current"
    if family_label:
        resolved_family = _resolve_font_family(family_label, size, weight)
        label.setFont(font(size, weight, family=resolved_family, smoothing=smoothing, italic=italic))
    else:
        label.setFont(font(size, weight, mono=True, smoothing=smoothing, italic=italic))
    text_color = resolve_color_ref(s.get("text_color", "#d6d9dc"))
    bg = resolve_color_ref(s.get("bg_color", "#202326"))
    thickness = max(0, int(s.get("border_thickness", 1)))
    enabled = s.get("border_enabled") or {}
    colors = s.get("border") or {}
    radius = s.get("border_radius") or {}
    sides = []
    for side in ("top", "right", "bottom", "left"):
        side_thickness = thickness if enabled.get(side, True) else 0
        side_color = resolve_color_ref(colors.get(side, "@border2"))
        sides.append(f"border-{side}: {side_thickness}px solid {side_color};")
    corners = []
    for css_corner, key_corner in (
        ("top-left", "top_left"), ("top-right", "top_right"),
        ("bottom-right", "bottom_right"), ("bottom-left", "bottom_left"),
    ):
        corners.append(f"border-{css_corner}-radius: {max(0, int(radius.get(key_corner, 4)))}px;")
    label.setStyleSheet(
        f"#ResizeWidthIndicator {{ background: {bg}; color: {text_color}; padding: 6px;"
        f" {' '.join(sides)} {' '.join(corners)} }}"
    )


def _show_resize_width(widget: QWidget, width: int, key: str = "default") -> None:
    """Affiche/deplace le badge de largeur pres du coin ANCRE (voir
    RESIZE_BADGE_STYLE["position"], General > Colonnes > "Cadre de
    redimensionnement" des reglages — bas-droit par defaut, comportement
    INCHANGE) de `widget` (le bord qu'on est en train de glisser, ou sa
    voisine — voir `key`) — voir _resize_width_indicator. Ancre au coin
    choisi du fond de `widget`, cadre INSERE de offset_x/offset_y px (voir
    RESIZE_BADGE_STYLE, sliders "H"/"V" sur la ligne "Position" des
    reglages — 8/8 par defaut, comportement INCHANGE) — voir la remarque de
    l'utilisateur, "distance entre le bas du fond de la colonne et le bas
    du cadre de dimension [ET] le cote droit du fond de la colonne et le
    cote droit du cadre de dimension doivent etre de 8px" puis "sous
    position je veux egalement deux sliders (sur la mm ligne) pour la
    position H et la position V"."""
    win = widget.window()
    label = _resize_width_indicator(win, key)
    label.setText(str(width))
    _refresh_resize_width_style(label)
    label.adjustSize()
    position = RESIZE_BADGE_STYLE.get("position", "bottom_right")
    offset_x = int(RESIZE_BADGE_STYLE.get("offset_x", 8))
    offset_y = int(RESIZE_BADGE_STYLE.get("offset_y", 8))
    anchor_x = 0 if position.endswith("left") else widget.width()
    anchor_y = 0 if position.startswith("top") else widget.height()
    anchor = widget.mapToGlobal(QPoint(anchor_x, anchor_y))
    local = win.mapFromGlobal(anchor)
    label_x = local.x() + offset_x if position.endswith("left") \
        else local.x() - label.width() - offset_x
    label_y = local.y() + offset_y if position.startswith("top") \
        else local.y() - label.height() - offset_y
    label.move(label_x, label_y)
    label.show()
    label.raise_()


def _hide_resize_width(widget: QWidget, key: str = "default") -> None:
    labels = getattr(widget.window(), "_resize_width_labels", None)
    if labels is not None and key in labels:
        labels[key].hide()


def _show_row_resize_indicator(column: "Column", row_index: int, height: int) -> None:
    """MEME badge que _show_resize_width (voir _resize_width_indicator/
    RESIZE_BADGE_STYLE pour l'habillage : police/couleur/fond/bordure
    restent les memes reglages), mais ancre juste SOUS `row_index` (voir
    Column.row_resize_begin) plutot que sous le coin de la colonne entiere
    — voir la remarque de l'utilisateur, "je veux que la position de
    l'indicateur de hauteur soit juste au dessous de la ligne que l'on
    redimensionne". `key="row_height"` DEDIE (jamais "default", partage
    par le redimensionnement de LARGEUR/hauteur de groupe) : ce glisser
    peut survenir alors qu'un AUTRE indicateur est deja affiche ailleurs
    sur la meme fenetre (peu probable mais gratuit a eviter)."""
    win = column.window()
    label = _resize_width_indicator(win, "row_height")
    label.setText(str(height))
    _refresh_resize_width_style(label)
    label.adjustSize()
    row_rect = None
    if row_index >= 0:
        index = column.list.model().index(row_index, 0)
        if index.isValid():
            row_rect = column.list.visualRect(index)
    viewport = column.list.viewport()
    if row_rect is not None:
        anchor_local = QPoint(row_rect.center().x(), row_rect.bottom())
    else:
        anchor_local = QPoint(viewport.width() // 2, 0)
    anchor_global = viewport.mapToGlobal(anchor_local)
    local = win.mapFromGlobal(anchor_global)
    label.move(local.x() - label.width() // 2, local.y() + 4)
    label.show()
    label.raise_()


def _persist_row_height(win, title: str, new_height: int) -> None:
    """Enregistre `new_height` comme hauteur de ligne EFFECTIVE de `title`
    sur le disque (voir Column.row_resize_end) — memes cles que la fenetre
    de parametres (settings_window._build_column_override_page) : "Type"
    garde ses cles historiques, "Projets"/"Sous-projet" les nouvelles cles
    imbriquees par titre (voir _override_store cote settings_window) — pour
    qu'un redimensionnement a la souris se retrouve, actif, la prochaine
    fois que Colonnes > (Type/Projets/Sous-projets) est ouvert. Ctrl+glisser
    est desormais possible sur TOUTE colonne (voir _in_row_resize_zone, la
    remarque de l'utilisateur, "doit etre sur toutes les colonnes") — mais
    "Logiciels"/"Contenu" (et toute colonne de chaine CONFIGUREE qui retombe
    dans ce meme bucket, voir _col_key, ex. "test1") n'ont PAS d'onglet de
    surcharge PAR TITRE dedie (voir apply_all_settings, "suivent directement
    la valeur GENERALE") : le SEUL reglage qui pilote reellement leur
    hauteur est le defaut GENERAL "item_row_height", c'est donc lui qu'il
    faut ecrire pour que ce glisser survive a un redemarrage — memes effet
    que le slider General > Colonnes > "Hauteur de la ligne"""
    def _apply_height_override(target: dict) -> None:
        if title == "Type":
            target.setdefault("column_type_overrides", {})["item_row_height"] = new_height
            target.setdefault("column_type_override_enabled", {})["item_row_height"] = True
        elif title in ("Projets", "Sous-projet", PREVIEW_STACK_TITLE):
            target.setdefault("column_overrides_by_title", {}).setdefault(title, {})["item_row_height"] = new_height
            target.setdefault("column_override_enabled_by_title", {}).setdefault(title, {})["item_row_height"] = True
        else:
            target["item_row_height"] = new_height

    settings = load_settings()
    _apply_height_override(settings)
    save_settings(settings)

    # Applique en LIVE depuis la vue COURANTE de la fenetre de parametres
    # si elle est ouverte (dialog._current_values()) plutot que `settings`
    # ci-dessus, qui vient d'etre RELU du disque et ne contient PAS
    # d'eventuels reglages en cours de previsualisation mais pas encore
    # enregistres (ex. "Espacement entre les lignes" juste ajuste au
    # slider, general) — les reappliquer ici aurait silencieusement ecrase
    # cette previsualisation, et ce pour LES 5 COLONNES A LA FOIS puisque
    # apply_all_settings en recalcule le spacing a partir du MEME dict —
    # voir la remarque de l'utilisateur, "apres un redimensionnement les
    # espacements entre les lignes ne sont plus respecte, et ca concerne
    # toutes les colonnes". La hauteur est re-appliquee explicitement sur
    # CETTE vue aussi (_apply_height_override).
    dialog = getattr(win, "_settings_dialog", None)
    live_settings = None
    if dialog is not None:
        try:
            if dialog.isVisible():
                live_settings = dialog._current_values()
        except RuntimeError:
            live_settings = None
    if live_settings is not None:
        _apply_height_override(live_settings)
    apply_all_settings(live_settings if live_settings is not None else settings)


def _sync_default_preset_override(settings: dict, apply_override) -> None:
    """Reapplique `apply_override` (MEME callable que celui deja utilise sur
    `settings`) au preset "par defaut" ACTIF (settings["default_preset"],
    voir General > Application) — sans ca, une largeur "auto-enregistree"
    (voir _persist_column_width/_persist_detail_panel_width) etait
    silencieusement ECRASEE par la valeur PERIMEE de ce preset des le
    PROCHAIN chargement (voir settings_window.load_settings, qui fusionne
    TOUJOURS le preset par defaut PAR-DESSUS pipeline_settings.json), tant
    qu'un preset par defaut restait configure — voir la remarque de
    l'utilisateur, "la largeur de la colonne inspecteur ne s'enregistre
    toujours pas automatiquement". No-op si aucun preset par defaut n'est
    configure, ou s'il a depuis ete supprime/renomme (repli SILENCIEUX,
    meme convention que load_settings)."""
    default_preset = settings.get("default_preset")
    if not default_preset:
        return
    presets = _load_presets()
    preset = presets.get(default_preset)
    if preset is None:
        return
    apply_override(preset)
    _save_presets(presets)


def _persist_column_width(win, title: str, new_width: int) -> None:
    """Analogue de _persist_row_height, mais pour la LARGEUR — reservee aux
    colonnes qui n'ont pas (ou plus) besoin de punaise pour s'enregistrer :
    Type (jamais de bouton punaise, voir Column.__init__) et Focus/
    PREVIEW_STACK_TITLE (colonnes empilees Projets/Sous-projet de
    l'apercu, voir PreviewColumn — aucune notion de dossier UNIQUE a
    associer, donc pas de mecanisme .pipeline_layout.json possible pour
    elles) — voir la remarque de l'utilisateur, "les seules colonnes dont
    les parametres sont enregistrees automatiquement sont : colonne type,
    colonnes focus, colonne inspecteur"."""
    def _apply_width_override(target: dict) -> None:
        if title == "Type":
            target.setdefault("column_type_overrides", {})["item_column_width"] = new_width
            target.setdefault("column_type_override_enabled", {})["item_column_width"] = True
        elif title in ("Projets", "Sous-projet", PREVIEW_STACK_TITLE):
            target.setdefault("column_overrides_by_title", {}).setdefault(title, {})["item_column_width"] = new_width
            target.setdefault("column_override_enabled_by_title", {}).setdefault(title, {})["item_column_width"] = True
        else:
            target["item_column_width"] = new_width

    settings = load_settings()
    _apply_width_override(settings)
    save_settings(settings)
    _sync_default_preset_override(settings, _apply_width_override)

    dialog = getattr(win, "_settings_dialog", None)
    live_settings = None
    if dialog is not None:
        try:
            if dialog.isVisible():
                live_settings = dialog._current_values()
        except RuntimeError:
            live_settings = None
    if live_settings is not None:
        _apply_width_override(live_settings)
    apply_all_settings(live_settings if live_settings is not None else settings)


def _persist_detail_panel_width(win, new_width: int) -> None:
    """Analogue de _persist_column_width, mais pour l'Inspecteur (voir
    DetailPanel.mouseReleaseEvent) — une seule cle GENERALE PLATE
    ("detail_panel_width", pas de branchement par titre : cette colonne
    n'a ni punaise ni onglet de surcharge dedie, une seule instance existe
    dans toute l'appli) — voir la remarque de l'utilisateur, "la largeur
    de la colonne inspecteur ... doivent etre enregistrees
    automatiquement"."""
    settings = load_settings()
    settings["detail_panel_width"] = new_width
    save_settings(settings)
    _sync_default_preset_override(settings, lambda target: target.__setitem__("detail_panel_width", new_width))

    dialog = getattr(win, "_settings_dialog", None)
    live_settings = None
    if dialog is not None:
        try:
            if dialog.isVisible():
                live_settings = dialog._current_values()
        except RuntimeError:
            live_settings = None
    if live_settings is not None:
        live_settings["detail_panel_width"] = new_width
    apply_all_settings(live_settings if live_settings is not None else settings)


def open_path(path: Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_file_manager(path: Path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


# Gestion de la vignette perso d'un dossier (voir project_thumbnail_path) —
# fonctions LIBRES (pas des methodes Column), pour etre partagees par
# Column._change_thumbnail/_capture_thumbnail/_save_thumbnail_pixmap/
# _reset_thumbnail (menu clic droit d'une ligne normale) ET
# _PreviewBlock._on_context_menu (menu clic droit d'un bloc Focus, voir sa
# remarque de tete) — voir la remarque de l'utilisateur, "les fichiers et
# dossiers de focus ne fonctionnent pas comme les autres colonnes,
# notamment pour le clic droit". `anchor` : SEULEMENT utilise comme parent
# de dialogue (QFileDialog/QMessageBox, n'importe quel QWidget convient)
# et pour garder une reference Python vivante sur la capture d'ecran en
# cours (voir _prompt_capture_thumbnail, `anchor._capture_overlay`) tant
# que la fenetre de selection est ouverte — jamais suppose etre un Column.
# `on_done` : callback SANS argument, appele apres une ecriture/suppression
# reussie (le SEUL bout specifique a l'appelant — un repaint de liste pour
# Column, un rechargement de pixmap pour _PreviewBlock).


def _prompt_change_thumbnail(anchor: QWidget, path: Path, on_done) -> None:
    # QTimer.singleShot(0, ...) : NE JAMAIS ouvrir ce QFileDialog
    # DIRECTEMENT depuis ce slot — appele depuis un menu CONTEXTUEL tout
    # juste ferme (voir Column._on_context_menu/_PreviewBlock.
    # _show_context_menu, menu.exec(...) qui vient de retourner) : ouvrir
    # un 2e dialogue modal DANS LE MEME CYCLE D'EVENEMENTS que la
    # fermeture du 1er est un piege Qt classique — le clic de
    # relachement qui a ferme le menu se fait parfois REINTERPRETER par
    # le NOUVEAU dialogue comme un clic EN DEHORS de lui, le refermant
    # INSTANTANEMENT — voir la remarque de l'utilisateur, "quand je
    # clique sur changer l'icone du logiciel, la fenetre pour choisir
    # une nouvelle image se referme tout de suite" (meme mecanisme,
    # voir _change_software_icon). QTimer.singleShot(150, ...) — PAS 0
    # (essaye puis insuffisant sur _change_software_icon, voir la
    # remarque de l'utilisateur "cette fois-ci aucune fenetre ne
    # s'ouvre" : un simple tour de boucle Qt ne suffit pas a laisser
    # Windows relacher completement le grab souris/clavier NATIF du
    # menu contextuel tout juste ferme). Meme delai deja utilise
    # ailleurs dans ce fichier pour un probleme de meme nature
    # (_capture_thumbnail/_capture_software_icon).
    def open_dialog():
        chosen, _ = QFileDialog.getOpenFileName(
            anchor, "Choisir une image", str(path),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)",
        )
        if not chosen:
            return
        pix = QPixmap(chosen)
        if pix.isNull():
            QMessageBox.warning(anchor, "Image", "Impossible de charger cette image.")
            return
        _save_thumbnail_pixmap_for(path, pix, anchor, on_done)

    QTimer.singleShot(150, open_dialog)


def _prompt_capture_thumbnail(anchor: QWidget, path: Path, on_done) -> None:
    """Ouvre un selecteur de zone carree (un par ecran connecte) pour
    capturer une vignette de projet directement depuis l'affichage."""
    win = anchor.window()
    was_visible = win.isVisible()
    if was_visible:
        win.hide()
    QApplication.processEvents()

    def start_overlay():
        capture = MultiScreenCapture()
        anchor._capture_overlay = capture  # garde une reference tant que les fenetres sont ouvertes

        def finish():
            if was_visible:
                win.show()
            anchor._capture_overlay = None

        def on_captured(pix: QPixmap):
            finish()
            _save_thumbnail_pixmap_for(path, pix, anchor, on_done)

        capture.captured.connect(on_captured)
        capture.cancelled.connect(finish)

    # Laisse le temps a la fenetre principale de disparaitre avant la
    # capture, sinon elle apparait encore dans la vignette.
    QTimer.singleShot(150, start_overlay)


def _save_thumbnail_pixmap_for(path: Path, pix: QPixmap, anchor: QWidget, on_done) -> None:
    if pix.isNull():
        return
    if max(pix.width(), pix.height()) > THUMBNAIL_MAX_DIM:
        pix = _smooth_scale_down(pix, QSize(THUMBNAIL_MAX_DIM, THUMBNAIL_MAX_DIM), Qt.KeepAspectRatio)
    dest = project_thumbnail_path(path)
    if not pix.save(str(dest), "PNG"):
        QMessageBox.warning(anchor, "Image", "Impossible d'enregistrer la vignette.")
        return
    _set_hidden(dest)
    on_done()


def _prompt_reset_thumbnail(anchor: QWidget, path: Path, on_done) -> None:
    thumb = project_thumbnail_path(path)
    if thumb.exists():
        try:
            thumb.unlink()
        except OSError as exc:
            QMessageBox.warning(anchor, "Image", f"Impossible de supprimer la vignette :\n{exc}")
            return
    on_done()


# ==========================================================================
# Rendu des lignes
# ==========================================================================

ROLE_PATH = Qt.UserRole
ROLE_ISDIR = Qt.UserRole + 1
ROLE_META = Qt.UserRole + 2
# Annotation "(projet)"/"(<nom du sous-projet>)" a cote du nom, dans les
# colonnes IN/OVER/OUT du groupe (voir Column.__init__ source_labels,
# PipelineBrowser.update_preview_stack, _paint_unified_row) — None (partout
# ailleurs) = pas d'annotation, comportement INCHANGE — voir la remarque de
# l'utilisateur, "je veux une anotation a cote du nom du repertoire ...
# s'il vient de projet ou de sous projet".
ROLE_SOURCE_LABEL = Qt.UserRole + 3
# Position (2 = Type, 3 = Projets, 4 = Sous-projet, 5+ = niveaux configures
# suivants) de la colonne "de set" SOURCE d'une ligne fusionnee IN/OVER/OUT
# (voir Column.refresh, PipelineBrowser.update_preview_stack) — reutilise
# TEL QUEL le meme palier de couleur que le badge numerote (voir
# _step_badge_color/STEP_BADGE_STYLE, Settings > Colonnes > Projets >
# Colonnes > "Icone de niveaux") pour colorer l'etiquette d'origine
# differemment selon l'etape source — voir la remarque de l'utilisateur,
# "les couleurs des indications doivent changer selon les etapes". None
# (partout ailleurs) = couleur fixe inchangee.
ROLE_SOURCE_STEP = Qt.UserRole + 4
# Vrai pour une ligne "raccourci" (voir load_shortcuts/Column.refresh,
# Column._on_context_menu "Ajouter un raccourci") : un dossier situe
# AILLEURS sur le disque, affiche comme s'il etait physiquement dans CE
# dossier — voir _resolve_shortcut_font_color/SHORTCUT_TEXT_STYLE (police/
# couleur dediees, Settings > RACCOURCI) pour le distinguer visuellement,
# et le menu contextuel reduit ("Retirer le raccourci" au lieu de
# Renommer/Supprimer, qui agirait par erreur sur la VRAIE cible).
ROLE_IS_SHORTCUT = Qt.UserRole + 5


def _paint_row_border(painter: QPainter, rect, option, style: dict):
    """Filet horizontal ENTRE les lignes (voir DEFAULT_SETTINGS.
    item_row_border_*/settings_window._ITEM_TEXT_FIELD_SPECS/_RowBorderField)
    — partage par toutes les colonnes (voir _paint_unified_row) pour eviter
    de dupliquer ce calcul —
    voir la remarque de l'utilisateur, "place ensuite cette meme section
    dans les onglets projets et sous projets pour y controler les colonnes
    respectives".

    A APPELER AVANT la selection (pas apres) : celle-ci, peinte par
    l'appelant juste apres, doit pouvoir RECOUVRIR le filet la ou elle
    deborde dessus — sinon le filet tranchait visiblement le bas du
    rectangle de selection des que le padding de selection ou l'espacement
    entre lignes etait faible (voir la remarque de l'utilisateur, capture a
    l'appui, "c'est comme si la bordure etait posee sur la derniere ligne
    de la selection")."""
    if not style.get("item_row_border_enabled"):
        return
    thickness = max(1, int(style.get("item_row_border_thickness", 1)))
    border_color = resolve_color_ref(style.get("item_row_border_color", "@ligne"))
    # Centre dans l'ESPACEMENT entre 2 lignes (voir ROW_SPACING), pas colle
    # au bas de CETTE ligne : `rect` exclut deja cet espacement (voir
    # l'appel du delegate, option.rect.adjusted(0, 0, 0, -spacing)) —
    # `option.rect`, lui, le comprend encore, d'ou le milieu entre les 2
    # pour rester centre meme si l'espacement change (voir la remarque de
    # l'utilisateur, "je veux que cette bordure soit exactement au milieu
    # de deux lignes, meme quand on augmente l'espacement"). fillRect (PAS
    # drawLine+QPen) avec l'antialiasing coupe : un filet de 1px trace au
    # pinceau sur une coordonnee entiere se retrouve sinon reparti sur 2
    # lignes de pixels a 50% de couverture chacune (lissage) —
    # visuellement 2px flous au lieu d'1px net (voir la remarque de
    # l'utilisateur, "en realite elle en fait deux"). Entiers UNIQUEMENT
    # (PAS de round() sur un flottant) : un arrondi pouvait retomber pile
    # sur rect.bottom() (dernier pixel du CONTENU de la ligne, PAS
    # l'espacement) des que gap+epaisseur donnait une somme impaire (ex.
    # espacement=1/epaisseur=1). Reste sous rect.bottom() (borne bas
    # comprise) tant que l'espacement est suffisant ; ne deborde vers LE
    # HAUT de CETTE ligne que si l'epaisseur choisie depasse l'espacement
    # disponible — jamais vers le bas dans la ligne SUIVANTE (qui se
    # repeindrait par-dessus, rendant le filet invisible a chaque frame).
    gap_top = rect.bottom() + 1
    gap_h = max(0, option.rect.bottom() - rect.bottom())
    if thickness <= gap_h:
        top = gap_top + (gap_h - thickness) // 2
    else:
        top = gap_top + gap_h - thickness
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.fillRect(QRect(rect.left(), top, rect.width(), thickness), QColor(border_color))
    painter.restore()


_IMAGE_MASK_CACHE: dict[tuple, QPixmap] = {}
_IMAGE_MASK_CACHE_MAX = 128


def _rounded_mask_pixmap(width: int, height: int, radius: dict) -> QPixmap:
    """Masque (blanc opaque a l'interieur, transparent au coin arrondi)
    sur-echantillonne 8x pour _paint_row_image, mis en CACHE par (taille,
    rayon) — CONTENU-INDEPENDANT (contrairement au composite final, qui
    depend de l'image affichee et reste recalcule a chaque ligne) : evite
    de re-rasteriser le meme contour antialiase a CHAQUE ligne et a CHAQUE
    frame de scroll — voir la remarque de l'utilisateur, "il y a des
    ralentissements dans les animations, optimise un maximum"."""
    radius_key = tuple(sorted(radius.items()))
    key = (width, height, radius_key)
    cached = _IMAGE_MASK_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_IMAGE_MASK_CACHE) >= _IMAGE_MASK_CACHE_MAX:
        _IMAGE_MASK_CACHE.clear()
    SS = 8
    big = QSize(width * SS, height * SS)
    big_rect = QRect(0, 0, big.width(), big.height())
    big_radius = {k: v * SS for k, v in radius.items()}
    mask = QPixmap(big)
    mask.fill(Qt.transparent)
    mkp = QPainter(mask)
    mkp.setRenderHint(QPainter.Antialiasing, True)
    mkp.setPen(Qt.NoPen)
    mkp.setBrush(Qt.white)
    mkp.drawPath(_rounded_rect_path(big_rect, big_radius))
    mkp.end()
    _IMAGE_MASK_CACHE[key] = mask
    return mask


def _paint_row_image(
    painter: QPainter, slot_rect: QRect, pixmap: QPixmap, style: dict,
    base_pad: int = 0,
):
    """Recadre/peint `pixmap` en "cover" dans `slot_rect`, avec le padding/
    bordure/rayon regles dans Colonnes > ... > Image (voir DEFAULT_SETTINGS.
    item_image_*/settings_window._section_headers) — partage par toutes les
    colonnes (apercu personnalise sur "Type", vignette Projets/Sous-projet/
    Logiciels/Contenu, voir _paint_unified_row) —
    voir la remarque de l'utilisateur, "les parametres images ... sont pour
    controler les apercus que l'on trouve sur les differentes lignes".

    `item_image_radius` est un reglage INDEPENDANT (defaut 0 = carre),
    JAMAIS remplace par un rayon "herite" d'ailleurs (colonne/selection) —
    un essai precedent faisait heriter le rayon de la boite de selection
    tant qu'item_image_radius valait 0, mais rendait alors un 0 EXPLICITE
    indiscernable d'un rayon "pas encore regle" : le coin restait
    visiblement arrondi meme regle a 0 — voir la remarque de l'utilisateur,
    capture a l'appui, "si je met une valeur de 0 a l'arrondi, les coins
    ne sont pas vraiment carre". `base_pad` (additif, jamais ambigu) reste
    le seul reglage "herite" — l'ancien padding fixe par colonne
    (col_img_pad, Projets/Sous-projet/Logiciels/Contenu)."""
    pad = style.get("item_image_padding") or {}
    left = base_pad + max(0, int(pad.get("left", 0)))
    top_p = base_pad + max(0, int(pad.get("top", 0)))
    right = base_pad + max(0, int(pad.get("right", 0)))
    bottom = base_pad + max(0, int(pad.get("bottom", 0)))
    img_rect = QRect(
        slot_rect.left() + left, slot_rect.top() + top_p,
        slot_rect.width() - left - right, slot_rect.height() - top_p - bottom,
    )
    if img_rect.width() <= 0 or img_rect.height() <= 0:
        return

    radius = _radius_dict(style.get("item_image_radius") or 0)

    # Taille PHYSIQUE reelle (devicePixelRatio), pas seulement LOGIQUE —
    # voir la remarque de l'utilisateur, "je trouve les icones encore tres
    # floues" : sur un ecran mis a l'echelle (>100%, tres courant), un
    # pixmap cree a EXACTEMENT la taille logique du slot (devicePixelRatio
    # implicite 1.0) est ensuite lui-meme RE-agrandi par Qt au moment de
    # le peindre dans ce MEME rect logique sur un peripherique physique
    # plus dense — un flou invisible cote algorithme de mise a l'echelle
    # (deja bon, voir _smooth_scale_down), uniquement du a ce DERNIER saut
    # (le pixmap final n'annonce jamais sa vraie densite a Qt)."""
    device = painter.device()
    dpr = (device.devicePixelRatioF() if device is not None else 1.0) or 1.0
    phys_w = max(1, round(img_rect.width() * dpr))
    phys_h = max(1, round(img_rect.height() * dpr))

    if _radius_any(radius):
        # Masque construit a la main (REMPLISSAGE antialiase + composition
        # DestinationIn), PAS un setClipPath direct : le moteur RASTER de
        # Qt ne produit pas un clip vraiment antialiase. Sur-echantillonne
        # 8x (PAS 1 seule passe) : a un PETIT rayon, un chemin rasterise
        # directement a la resolution finale laissait un arrondi en
        # escalier (chaque pixel de coin couvert a 0% ou 100%, jamais entre
        # les deux) — voir la remarque de l'utilisateur, "l'antialiasing
        # est affreux" puis "peux tu ameliorer encore plus l'antialiasing"
        # (4x -> 8x). MEME facteur que le trait de bordure dans
        # _paint_bordered_rect. `radius` mis a l'echelle par dpr AVANT
        # de rejoindre le masque (PAS le rayon "logique" brut) : sinon les
        # coins paraitraient proportionnellement plus petits que prevu des
        # que dpr > 1 (le masque, lui, grandit avec phys_w/phys_h, le
        # rayon doit suivre pour rester visuellement identique).
        #
        # Le masque passe par un PIXMAP intermediaire (dessine ENTIEREMENT
        # par-dessus l'image avec drawPixmap), PAS par un fillPath direct
        # en DestinationIn : cette composition ne s'applique qu'aux pixels
        # que la primitive source TOUCHE reellement — un fillPath ne touche
        # que l'INTERIEUR du chemin, les coins (hors chemin) n'etaient donc
        # jamais composes et gardaient l'image intacte, laissant un carre
        # parfait malgre le rayon demande — voir la remarque de
        # l'utilisateur, capture a l'appui, "l'image doit avoir un coin
        # arrondi, le meme que la bordure". Un drawPixmap, lui, couvre TOUT
        # le rectangle : les coins du masque (transparents) y remettent
        # bien l'alpha a 0.
        #
        # `hires_cropped` recadre/reduit DIRECTEMENT `pixmap` (la source
        # ORIGINALE, haute resolution) a la taille SUR-ECHANTILLONNEE du
        # masque — PAS un recadrage prealable a la taille FINALE (phys_w/
        # phys_h) suivi d'un agrandissement 8x pour rejoindre le masque :
        # cet aller-retour (retrecir PUIS agrandir PUIS retrecir a nouveau)
        # perdait du detail a chaque etape — voir la remarque de
        # l'utilisateur, "je trouve les icones encore tres floues".
        radius_dpr = {k: v * dpr for k, v in radius.items()}
        mask = _rounded_mask_pixmap(phys_w, phys_h, radius_dpr)
        big = mask.size()
        hires = _smooth_scale_down(pixmap, big, Qt.KeepAspectRatioByExpanding)
        hsx = max(0, (hires.width() - big.width()) // 2)
        hsy = max(0, (hires.height() - big.height()) // 2)
        hires_cropped = hires.copy(hsx, hsy, min(big.width(), hires.width()), min(big.height(), hires.height()))

        masked = QPixmap(big)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.setRenderHint(QPainter.SmoothPixmapTransform, True)
        mp.drawPixmap(QRect(0, 0, big.width(), big.height()), hires_cropped)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()

        masked = _smooth_scale_down(masked, QSize(phys_w, phys_h), Qt.IgnoreAspectRatio)
        masked.setDevicePixelRatio(dpr)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(img_rect, masked)
    else:
        cropped = _smooth_scale_down(pixmap, QSize(phys_w, phys_h), Qt.KeepAspectRatioByExpanding)
        sx = max(0, (cropped.width() - phys_w) // 2)
        sy = max(0, (cropped.height() - phys_h) // 2)
        cropped = cropped.copy(sx, sy, min(phys_w, cropped.width()), min(phys_h, cropped.height()))
        cropped.setDevicePixelRatio(dpr)
        painter.drawPixmap(img_rect, cropped)

    border_enabled = dict(style.get("item_image_border_enabled") or {})
    if any(border_enabled.values()):
        thickness = max(1, int(style.get("item_image_border_thickness", 1)))
        border_colors = {k: resolve_color_ref(v) for k, v in (style.get("item_image_border") or {}).items()}
        painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        _paint_bordered_rect(painter, img_rect, radius, border_enabled, thickness, border_colors, None)
        painter.setRenderHint(QPainter.Antialiasing, False)


def _resolve_font_family(label: str, size: int, weight: int = 400, fallback_role: str = "folders") -> str:
    """Resout un libelle de police stocke (voir item_font_family/
    _ITEM_FONT_LABEL_TO_ROLE) vers un nom de police REEL : "police du
    soft" (role, voir Polices principales) ou nom de police systeme
    litteral — meme logique que _resolve_row_font_color ci-dessous,
    partagee ici pour Colonnes > Apercu > Zone titre (Titre/Apercu des
    dossiers) — voir la remarque de l'utilisateur, "je veux le choix de
    la police (titre + apercu des dossiers) (choix entre polices appli ou
    polices systeme)"."""
    role = _ITEM_FONT_LABEL_TO_ROLE.get(label)
    if role is not None:
        return role_font(role, size, weight).family()
    return label or role_font(fallback_role, size, weight).family()


def _resolve_row_font_color(title: str):
    """Police/couleur EFFECTIVES du texte d'une ligne, pour LE style de
    `title` (general ou surcharge, voir app_style.column_style_for) —
    UNIQUE source pour toutes les colonnes (Type/Projets/Sous-projet/
    Logiciels/Contenu, voir RowDelegate/ProjectTileDelegate.refresh_fonts)
    depuis que leur rendu est partage (voir _paint_unified_row) — voir la
    remarque de l'utilisateur, "je veux que tu reformate toutes les autres
    colonnes exactement de la meme maniere que la colonne type"."""
    s = column_style_for(title)
    family = (s.get("item_font_family") or "").strip()
    size = max(1, int(s.get("item_font_size") or 10))
    resolved_family = _resolve_font_family(family, size, 400)
    smoothing = s.get("item_antialias_override") if s.get("item_antialias_override_enabled") else "current"
    # Gras (voir Colonnes > Texte > Police, toggle "Gras" — DEFAULT_
    # SETTINGS.item_font_bold) : voir la remarque de l'utilisateur, "pour
    # les polices ... j'aimerais rajouter une option pour mettre le texte
    # en gras (toggle)".
    weight = 600 if s.get("item_font_bold") else 400
    italic = bool(s.get("item_font_italic", False))
    row_font = font(size, weight=weight, family=resolved_family, smoothing=smoothing, italic=italic)
    row_color = resolve_color_ref(s.get("item_color") or C["text"])
    return row_font, row_color


def _resolve_shortcut_font_color():
    """Police/couleur EFFECTIVES d'une ligne "raccourci" (voir
    ROLE_IS_SHORTCUT/SHORTCUT_TEXT_STYLE, Settings > RACCOURCI) — GENERALE
    (pas par colonne, contrairement a _resolve_row_font_color : un
    raccourci doit se reperer de la MEME facon partout)."""
    family = (SHORTCUT_TEXT_STYLE.get("font_family") or "").strip()
    size = max(1, int(SHORTCUT_TEXT_STYLE.get("font_size") or 11))
    resolved_family = _resolve_font_family(family, size, 400)
    weight = 600 if SHORTCUT_TEXT_STYLE.get("font_bold") else 400
    italic = bool(SHORTCUT_TEXT_STYLE.get("font_italic", False))
    smoothing = (
        SHORTCUT_TEXT_STYLE.get("font_smoothing", "current")
        if SHORTCUT_TEXT_STYLE.get("font_smoothing_enabled") else "current")
    row_font = font(size, weight=weight, family=resolved_family, smoothing=smoothing, italic=italic)
    row_color = resolve_color_ref(SHORTCUT_TEXT_STYLE.get("color") or C["text"])
    return row_font, row_color


class RowDelegate(QStyledItemDelegate):
    """Icone/image + nom, rendu UNIQUE partage par toutes les colonnes SAUF
    Projets/Sous-projet (voir ProjectTileDelegate) — voir _paint_unified_row.
    L'image affichee (voir paint) est resolue par colonne : apercu
    personnalise (colonne "Type"), icone logiciel reconnu (colonne
    "Logiciels"), ou apercu du fichier lui-meme si previsualisable (voir
    SHOW_FILE_IMAGE_PREVIEWS) — sinon l'icone toggle (voir item_icon_enabled)."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.refresh_fonts()

    def refresh_fonts(self):
        """Relit la police/couleur EFFECTIVES du texte (voir
        _resolve_row_font_color, General ou surcharge par colonne) : appele
        a la creation, et de nouveau si l'utilisateur change les parametres
        de typographie sans reconstruire la colonne (previsualisation en
        direct)."""
        self.type_font, self.type_color = _resolve_row_font_color(self.column.style_title)

    def _has_preview(self, index) -> bool:
        """Version bon marche de _image_pixmap : dit si CETTE ligne
        affichera un apercu, sans decoder/charger l'image elle-meme (juste
        le type ISDIR et l'extension, deja en memoire dans le modele).
        Utilisee par sizeHint (voir plus bas) — y appeler _image_pixmap
        directement forcerait Qt (listes a tailles non uniformes, voir
        Column.__init__) a decoder TOUTES les images d'un dossier des son
        ouverture pour calculer la mise en page, plutot que paresseusement
        au dessin des seules lignes visibles (voir paint) : exactement le
        ralentissement observe a l'ouverture d'un gros dossier de
        references."""
        if not SHOW_FILE_IMAGE_PREVIEWS or bool(index.data(ROLE_ISDIR)):
            return False
        path_str = index.data(ROLE_PATH)
        return bool(path_str) and Path(path_str).suffix.lower() in PREVIEWABLE_EXTENSIONS

    def _image_pixmap(self, index) -> QPixmap | None:
        if not self._has_preview(index):
            return None
        return file_image_pixmap(Path(index.data(ROLE_PATH)), asynchronous=True)

    def sizeHint(self, option, index) -> QSize:
        # L'espacement est ajoute a la hauteur ici, puis retranche au dessin
        # (voir paint) : c'est ce reste, non peint, qui forme l'espace exact
        # entre deux lignes (voir la remarque sur QListView.setSpacing plus
        # haut dans Column.__init__). Hauteur UNIFORME (col_row_height,
        # PAS col_plain_height selon presence d'apercu) : comme la colonne
        # "Type", toutes les lignes d'une meme colonne partagent desormais
        # la MEME hauteur, avec ou sans image — voir la remarque de
        # l'utilisateur, "reformate toutes les autres colonnes exactement
        # de la meme maniere que la colonne type".
        title = self.column.style_title
        return QSize(self.column.width(), self.column.effective_row_height() + col_spacing(title))

    def paint(self, painter: QPainter, option, index):
        # Rendu UNIQUE, PARTAGE par toutes les colonnes (voir
        # _paint_unified_row) — seule la RESOLUTION de l'image affichee
        # differe encore par colonne : apercu personnalise (voir Column.
        # _on_context_menu) sur "Type", icone logiciel reconnu ou apercu de
        # fichier (deja existants, REUTILISES tels quels) sur les autres —
        # voir la remarque de l'utilisateur, "je veux que tu reformate
        # toutes les autres colonnes exactement de la meme maniere que la
        # colonne type ... si une colonne a deja des images, reutilises
        # les".
        title = self.column.style_title
        spacing = col_spacing(title)
        rect = option.rect.adjusted(0, 0, 0, -spacing)
        is_dir = bool(index.data(ROLE_ISDIR))
        path_str = index.data(ROLE_PATH)

        # Icone de logiciel (voir software_icon_key/SOFTWARE_ICONS/
        # settings_window._section_logiciels) : DISTINCTE d'un apercu (voir
        # ci-dessous) — voir la remarque de l'utilisateur, "tous les
        # dossiers qui ont le nom d'un logiciel doivent avoir son icone, je
        # veux que tu fasses la distinction entre une icone et un apercu".
        # Reconnue pour TOUT dossier dont le NOM correspond a un logiciel
        # (connu ou ajoute), dans N'IMPORTE QUELLE colonne — plus seulement
        # "Logiciels" comme avant. DISTINCTE d'un apercu (voir plus bas) —
        # les DEUX peuvent coexister sur la meme ligne (voir la remarque de
        # l'utilisateur, "les apercus a droite et les icones a gauche,
        # comme ca il n'y aura plus d'ambiguite" — voir _paint_unified_row).
        is_shortcut = bool(index.data(ROLE_IS_SHORTCUT))
        icon_key = software_icon_key(index.data(Qt.DisplayRole) or "") if is_dir else None
        icon_pixmap = _row_icon_pixmap(is_dir, icon_key, SOFTWARE_ICON_SIZE)
        if is_shortcut:
            # Icone DEDIEE (Settings > ICONES > General > "Raccourcis") si
            # l'utilisateur en a choisi une, prioritaire sur l'icone
            # logiciel/le repli dossier — voir la remarque de l'utilisateur,
            # "dans les icones merci de rajouter une ligne raccourcis".
            shortcut_icon = custom_ui_icon_pixmap(UI_ICON_SHORTCUT, SOFTWARE_ICON_SIZE)
            if shortcut_icon is not None:
                icon_pixmap = shortcut_icon

        # Apercu personnalise (voir Column._on_context_menu, "Ajouter un
        # apercu.../Capturer une zone d'ecran...") : deja generalise a
        # N'IMPORTE QUELLE colonne/ligne dossier cote menu (voir sa
        # remarque, "n'importe quelle ligne de n'importe quelle colonne"),
        # y compris une colonne de chaine CONFIGUREE (voir load_project_
        # columns/on_selected, ex. "test1"/"test2") — teste ici pour TOUT
        # titre, pas seulement "Type" comme avant, sinon une capture prise
        # sur une de ces colonnes ne s'affichait jamais (project_thumbnail_
        # path existait bien sur le disque, mais RowDelegate.paint ne le
        # consultait que sur "Type").
        preview_pixmap = None
        if path_str and is_dir and project_thumbnail_path(Path(path_str)).is_file():
            preview_pixmap = project_thumbnail_pixmap(Path(path_str))
        elif title != "Type":
            preview_pixmap = self._image_pixmap(index)

        # Police/couleur DEDIEES pour un raccourci (voir SHORTCUT_TEXT_
        # STYLE, Settings > RACCOURCI) — GENERALE, pas par colonne : un
        # raccourci doit se reperer de la MEME facon partout.
        row_font, row_color = _resolve_shortcut_font_color() if is_shortcut else (self.type_font, self.type_color)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        _paint_unified_row(
            painter, rect, option, column_style_for(title),
            index.data(Qt.DisplayRole), icon_pixmap, preview_pixmap, row_font, row_color,
            self.column.is_active, annotation=index.data(ROLE_SOURCE_LABEL),
            annotation_step=index.data(ROLE_SOURCE_STEP),
            icon_visible_override=self.column._show_icon_override,
            preview_visible_override=self.column._show_preview_override,
            icon_size_override=self.column._icon_size_override,
            icon_padding_left_override=self.column._icon_padding_left_override,
            text_padding_left_override=self.column._text_padding_left_override,
        )
        painter.restore()


def _paint_unified_row(
    painter: QPainter, rect, option, style: dict, name: str,
    icon_pixmap: QPixmap | None, preview_pixmap: QPixmap | None,
    text_font, text_color: str, active: bool, annotation: str | None = None,
    step_badge: int | str | None = None, annotation_step: int | None = None,
    icon_visible_override: bool | None = None, preview_visible_override: bool | None = None,
    icon_size_override: int | None = None, icon_padding_left_override: int | None = None,
    text_padding_left_override: int | None = None,
):
    """Ligne UNIQUE, PARTAGEE par toutes les colonnes (Type/Projets/Sous-
    projet/Logiciels/Contenu) : icone toggle optionnelle, icone de
    logiciel/apercu personnalise (ou les DEUX a la fois) + nom + pastille
    de selection — voir la remarque de l'utilisateur, "je veux que tu
    reformate toutes les autres colonnes exactement de la meme maniere que
    la colonne type ... si une colonne a deja des images, reutilises les".
    `icon_pixmap`/`preview_pixmap` : DISTINCTS (voir la remarque de
    l'utilisateur, "je veux que desormais nous distinguions icone et
    apercu ... les apercus a droite et les icones a gauche, comme ca il
    n'y aura plus d'ambiguite") — une icone IDENTIFIE ce qu'est le dossier
    (logiciel reconnu, voir software_icon_key), toujours ANCREE a GAUCHE,
    comme avant ; un apercu est une simple DECORATION facultative (vignette
    de projet, capture d'ecran...), desormais ANCRE a DROITE — les DEUX
    peuvent coexister sur la MEME ligne (voir RowDelegate.paint/
    ProjectTileDelegate.paint, qui les resolvent independamment). Chacun
    est deja RESOLU par l'appelant (chaque colonne garde sa propre
    logique de choix d'image, voir RowDelegate.paint/ProjectTileDelegate.
    `annotation` (voir ROLE_SOURCE_LABEL, RowDelegate.paint) : texte
    "(projet)"/"(<nom du sous-projet>)" affiche APRES le nom, police/
    couleur DIFFERENTES (role "info", comme le compteur d'en-tete) — voir
    la remarque de l'utilisateur, "je veux une anotation a cote du nom du
    repertoire ... entre parentheses (d'une police et couleur
    differente)".
    paint) ; None affiche l'icone toggle (si activee) ou rien.
    `step_badge` (voir project_step_count/_step_badge_color/_step_badge_rect,
    ProjectTileDelegate.paint) : nombre affiche dans un badge rond en haut a
    droite de `rect` (colonne "Projets" uniquement) ; None = pas de badge."""
    s = style
    selected = bool(option.state & QStyle.State_Selected)
    hovered = bool(option.state & QStyle.State_MouseOver)

    # C["void"] (Skin - niveau 2), PAS C["row_idle"] : meme couleur que
    # le fond de la colonne SOUS l'entete (voir column_frame_qss, bg_hex
    # passe C["void"] aussi) — une ligne NON selectionnee doit se fondre
    # avec l'espace vide de la colonne, pas trancher avec sa propre
    # teinte — voir la remarque de l'utilisateur, "je veux que la
    # couleur sous l'entete/sous les textes non selectionnes soient
    # Skin - niveau 2".
    painter.fillRect(rect, QColor(C["void"]))

    # Filet horizontal ENTRE les lignes — AVANT la selection (pas apres) :
    # voir sa docstring.
    _paint_row_border(painter, rect, option, s)

    icon_enabled = bool(s.get("item_icon_enabled", True))
    # "Padding gauche du texte" (menu contextuel, voir Column._on_context_
    # menu/_text_padding_left_override) : surcharge PAR COLONNE de item_
    # text_padding — voir la remarque de l'utilisateur, "je veux que le
    # padding left ... du texte de chaque ligne soit modifiable dans le
    # menu contextuel".
    text_padding = max(0, text_padding_left_override if text_padding_left_override is not None
                       else int(s.get("item_text_padding", 8)))
    # Menu contextuel "Afficher l'icone"/"Afficher l'apercu" (voir Column.
    # _on_context_menu/_show_icon_override/_show_preview_override) : None
    # (repli) = comportement INCHANGE, sinon force explicitement visible/
    # masque pour CETTE colonne — voir la remarque de l'utilisateur,
    # "ajoute une option 'afficher l'apercu' avec un toggle, une autre
    # 'afficher l'icone' avec un toggle".
    icon_visible = True if icon_visible_override is None else icon_visible_override
    preview_visible = True if preview_visible_override is None else preview_visible_override
    has_icon = icon_pixmap is not None and icon_visible
    has_preview = preview_pixmap is not None and preview_visible

    if selected:
        state = "focus" if active else "unfocus"
        sel_color = s.get("item_selection_focus_color", C["accent"]) if active \
            else s.get("item_selection_unfocus_color", C["sel_idle"])
    elif hovered:
        state = "hover"
        sel_color = s.get("item_hover_color", C["hover"])
    else:
        # Boite "non selectionnee" (voir DEFAULT_SETTINGS.
        # item_idle_color) : MEME forme (padding/bordure/rayon) que les
        # autres etats — voir la remarque de l'utilisateur, "ajoute une
        # couleur (sous couleur de survol) qui represente la couleur
        # non selectionnee ... un fond sur les items non selectionnes,
        # de la meme forme que les divers selections". resolve_color_ref
        # (PAS s.get(...) direct) : _AppOrCustomColorField (contrairement
        # a Focus/Hors focus/Survol, restes en _ColorField) peut stocker
        # une reference "@slot", pas seulement un hex direct.
        state = "idle"
        sel_color = resolve_color_ref(s.get("item_idle_color"), C["row_idle"])

    if sel_color:
        # Forme (padding/bordure/rayon/bord de colonne) : "focus" reste la
        # BASE (cles item_selection_* historiques, inchangees) — les 3
        # autres etats (unfocus/hover/idle) EN HERITENT SAUF override
        # explicite (un toggle par parametre, voir Settings > General >
        # Colonnes > Selection > Non focus/Survol/Non selectionne) — voir
        # la remarque de l'utilisateur, "non focus survol et non
        # selectionne sont des clones des focus (sauf la couleur) donc
        # mets leur des toggles d'override".
        def _shape(value_key: str, base_key: str, default, toggle_suffix: str | None = None):
            if state == "focus":
                return s.get(base_key, default)
            toggle_suffix = toggle_suffix or value_key
            if s.get(f"item_selection_{state}_{toggle_suffix}_override"):
                return s.get(f"item_selection_{state}_{value_key}", default)
            return s.get(base_key, default)

        pad = _shape("padding", "item_selection_padding", {}) or {}
        pad_left = max(0, int(pad.get("left", 0)))
        pad_right = max(0, int(pad.get("right", 0)))
        pad_top = max(0, int(pad.get("top", 0)))
        pad_bottom = max(0, int(pad.get("bottom", 0)))
        # Reduit PROPORTIONNELLEMENT (jamais coupe a 0 net) si la somme
        # depasse la dimension disponible : un padding General reglé pour
        # des lignes HAUTES (Projets/Sous-projet, ~58px) pouvait a lui
        # seul depasser la hauteur des lignes bien plus COURTES (Logiciels/
        # Contenu/IN/OVER/OUT, ~25-30px), rendant sel_rect degenere
        # (largeur/hauteur <= 0) — la boite de selection (et donc sa
        # couleur) disparaissait alors SILENCIEUSEMENT (voir le test
        # `sel_rect.width() > 0 and sel_rect.height() > 0` plus bas), MEME
        # avec une couleur parfaitement valide — voir la remarque de
        # l'utilisateur, "pour les colonnes logiciels in over et out, la
        # couleur des selections ne se fait pas ... sa couleur ne devient
        # pas celle definie dans les settings".
        if pad_top + pad_bottom >= rect.height():
            total = pad_top + pad_bottom
            budget = max(0, rect.height() - 1)
            scale = budget / total if total > 0 else 0
            pad_top = int(pad_top * scale)
            pad_bottom = int(pad_bottom * scale)
        if pad_left + pad_right >= rect.width():
            total = pad_left + pad_right
            budget = max(0, rect.width() - 1)
            scale = budget / total if total > 0 else 0
            pad_left = int(pad_left * scale)
            pad_right = int(pad_right * scale)
        sel_rect = QRect(
            rect.left() + pad_left, rect.top() + pad_top,
            rect.width() - pad_left - pad_right, rect.height() - pad_top - pad_bottom,
        )
        border_enabled = dict(_shape(
            "border_enabled", "item_selection_border_enabled", {}, toggle_suffix="border") or {})
        border_colors = {
            k: resolve_color_ref(v) for k, v in (
                _shape("border", "item_selection_border", {}, toggle_suffix="border") or {}
            ).items()
        }
        edge_border = bool(_shape("edge_border", "item_selection_edge_border", True))
        for side, side_pad in (("left", pad_left), ("right", pad_right)):
            flush = side_pad <= 0
            if flush and not edge_border:
                border_enabled[side] = False
        radius = _radius_dict(_shape("radius", "item_selection_radius", 0))
        if sel_rect.width() > 0 and sel_rect.height() > 0:
            painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
            _paint_bordered_rect(painter, sel_rect, radius, border_enabled, 1, border_colors, sel_color)
            painter.setRenderHint(QPainter.Antialiasing, False)

    # Ancre du contenu (icone/image/texte) : le bord GAUCHE du cadre de
    # selection (sel_rect, TOUJOURS defini ici puisque sel_color l'est
    # desormais dans les 3 etats, voir plus haut), PAS le bord de la
    # colonne — voir la remarque de l'utilisateur, "quand on a une ligne
    # sans apercu, le padding du texte ne doit pas etre entre le texte et
    # le bord de la colonne, mais entre le texte et le bord du cadre de
    # selection, donc si le padding change, ca doit etre pris en compte
    # dans le calcul". Repli sur le bord de la colonne UNIQUEMENT si le
    # cadre de selection est degenere (padding superieur a la largeur/
    # hauteur de la ligne).
    icon_x = sel_rect.left() + text_padding if sel_rect.width() > 0 else rect.left() + text_padding
    text_x = icon_x

    # Icone (gauche) / apercu (droite) EN PREMIER PLAN (voir la remarque de
    # l'utilisateur, "l'image d'apercu est dessous les zones de selection
    # ... mets les en premier plan") : dessines APRES la boite de
    # selection/idle ci-dessus, jamais recouverts par son remplissage
    # opaque. Les DEUX peuvent coexister sur la meme ligne (voir la
    # docstring de cette fonction, "je veux que desormais nous
    # distinguions icone et apercu ... les apercus a droite et les icones
    # a gauche") — chacun garde la MEME hauteur que la zone de selection,
    # MEME ratio (item_image_ratio) — seule leur ANCRE horizontale differe.
    img_size = sel_rect.height() if sel_rect.height() > 0 else 14
    # item_image_ratio (largeur/hauteur, voir Colonnes > ... > Image) :
    # 1.0 = carre (comportement INCHANGE par defaut) — plus grand, plus
    # l'image est allongee HORIZONTALEMENT (largeur > hauteur) — voir la
    # remarque de l'utilisateur, "je veux une section ratio, qui
    # correspond au ratio entre la hauteur et la largeur. Plus le chiffre
    # est grand et plus l'image est allongee horizontalement". La HAUTEUR
    # reste toujours celle de la zone de selection (voir plus haut) ;
    # seule la LARGEUR en depend.
    img_ratio = float(s.get("item_image_ratio", 1.0) or 1.0)
    img_width = max(1, round(img_size * img_ratio))
    img_y = sel_rect.top() if sel_rect.height() > 0 else rect.center().y() - 7
    img_pad = s.get("item_image_padding") or {}
    text_right_limit = rect.right() - text_padding

    if has_icon:
        # Hauteur = celle de la zone de selection, collee sur son bord
        # GAUCHE — voir la remarque de l'utilisateur, "la hauteur de
        # l'image soit de la meme hauteur que les zones de selection ...
        # collee sur le bord gauche des zones de selection" — PAS le
        # carre 14x14 fixe de l'icone toggle (elle, inchangee, voir le
        # "elif" plus bas).
        # Padding gauche DEDIE a l'icone (item_icon_padding_left, General >
        # Colonnes > Texte, MEME esprit que le padding du texte) : decale
        # l'icone SEULE, sans toucher au texte ni a l'apercu — voir la
        # remarque de l'utilisateur, "comme les textes j'aimerais que tu
        # ajoutes un padding left sur les icones pour chaque lignes".
        icon_left_pad = max(0, icon_padding_left_override if icon_padding_left_override is not None
                            else int(s.get("item_icon_padding_left", 0) or 0))
        icon_img_x = (sel_rect.left() if sel_rect.width() > 0 else icon_x) + icon_left_pad
        # Taille de l'icone INDEPENDANTE de l'apercu (item_icon_size,
        # General > Colonnes > Texte > "Taille de l'icone par defaut") : 0
        # (repli) = comportement INCHANGE, la meme hauteur que la zone de
        # selection (img_size, comme l'apercu) — une valeur positive fixe
        # la taille de l'icone independamment de la hauteur de ligne,
        # centree verticalement dans l'espace qu'elle occuperait sinon —
        # voir la remarque de l'utilisateur, "ajoute une ligne dans les
        # settings ... taille de l'icone par defaut".
        icon_box_size = max(1, icon_size_override or int(s.get("item_icon_size") or 0) or img_size)
        icon_box_width = max(1, round(icon_box_size * img_ratio))
        icon_img_y = img_y + (img_size - icon_box_size) // 2
        # Padding/bordure/rayon (voir Colonnes > ... > Image, DEFAULT_
        # SETTINGS.item_image_*) — voir la remarque de l'utilisateur,
        # "les parametres images ... sont pour controler les apercus
        # que l'on trouve sur les differentes lignes". item_image_radius
        # est un reglage INDEPENDANT du rayon de selection (0 = carre).
        _paint_row_image(painter, QRect(icon_img_x, icon_img_y, icon_box_width, icon_box_size), icon_pixmap, s)
        # Distance texte<->icone PILOTEE par "Padding du texte" (item_
        # text_padding), PAS un ecart fixe — voir la remarque de
        # l'utilisateur, "je veux que le padding du texte ... controle
        # ... la distance entre le texte et l'image quand il y a un
        # apercu". Mesuree depuis le bord REEL de l'image (le carre
        # visible, retreci par son propre padding, voir _paint_row_image/
        # item_image_padding), PAS depuis le bord du slot qui la
        # contient : sinon le padding de l'image s'ajouterait EN PLUS
        # du padding du texte au lieu d'etre pris en compte dedans —
        # voir la remarque de l'utilisateur, "attention a bien prendre
        # en compte le bord de l'image, c'est a dire que si l'image a
        # elle-meme un padding, ca doit etre pris en compte dans la
        # distance totale".
        img_right_pad = max(0, int(img_pad.get("right", 0)))
        text_x = icon_img_x + icon_box_width - img_right_pad + text_padding
    elif icon_enabled and icon_visible:
        box_y = rect.center().y() - 14 // 2
        painter.setPen(QPen(QColor(role_color("dim", C["label"])), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(icon_x, box_y, 14 - 1, 14 - 1)
        text_x = icon_x + 14 + 8

    preview_img_x = None
    if has_preview:
        # MEME principe que l'icone, mais ANCRE sur le bord DROIT de la
        # zone de selection (QRect.right() = left+width-1, voir Qt) —
        # jamais lie a la presence/absence d'une icone a gauche.
        preview_img_x = (sel_rect.right() - img_width + 1) if sel_rect.width() > 0 else (rect.right() - img_width)
        _paint_row_image(painter, QRect(preview_img_x, img_y, img_width, img_size), preview_pixmap, s)
        img_left_pad = max(0, int(img_pad.get("left", 0)))
        text_right_limit = preview_img_x + img_left_pad - text_padding

    # Badge numerote (voir plus bas) : calcule ICI (avant text_rect) des
    # que l'apercu est connu — voir la remarque de l'utilisateur, "je
    # veux que la petite icone de levels soit AVANT l'apercu et pas a
    # l'interieur" : desormais sa propre plage, entre le texte et
    # l'apercu, retranchee de text_right_limit comme l'apercu lui-meme
    # (sinon un nom long pourrait passer PAR-DESSOUS le badge).
    badge_rect = None
    if step_badge is not None:
        badge_rect = _step_badge_rect(rect, preview_img_x)
        text_right_limit = min(text_right_limit, badge_rect.left() - text_padding)

    final_text_color = C["accent_text"] if (selected and active) else text_color
    text_rect = QRect(text_x, rect.top(), max(0, text_right_limit - text_x), rect.height())
    if annotation:
        # Largeur de l'annotation d'ABORD (police "info", voir sa remarque
        # de tete) : le nom n'a droit qu'au RESTE de text_rect, elide en
        # consequence — sinon un nom long masquerait completement une
        # annotation qui tiendrait pourtant a cote.
        ann_text = f" ({annotation})"
        ann_font = role_font("info", 10, 400)
        painter.setFont(ann_font)
        ann_width = painter.fontMetrics().horizontalAdvance(ann_text)

        painter.setFont(text_font)
        painter.setPen(QColor(final_text_color))
        name_width = max(0, text_rect.width() - ann_width)
        elided_name = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, name_width)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)

        name_actual_width = painter.fontMetrics().horizontalAdvance(elided_name)
        ann_rect = QRect(
            text_rect.left() + name_actual_width, text_rect.top(),
            max(0, text_rect.width() - name_actual_width), text_rect.height())
        if ann_rect.width() > 0:
            painter.setFont(ann_font)
            # Couleur par etape (voir ROLE_SOURCE_STEP/_step_badge_color,
            # Settings > Colonnes > Projets > Colonnes > "Icone de
            # niveaux") si connue, sinon la couleur fixe d'origine (voir la
            # remarque de l'utilisateur, "les couleurs des indications
            # doivent changer selon les etapes").
            ann_color = _step_badge_color(annotation_step) if annotation_step is not None else role_color("info", C["dim"])
            painter.setPen(QColor(ann_color))
            elided_ann = painter.fontMetrics().elidedText(ann_text, Qt.ElideRight, ann_rect.width())
            painter.drawText(ann_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_ann)
    else:
        painter.setFont(text_font)
        painter.setPen(QColor(final_text_color))
        elided = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, max(0, text_rect.width()))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

    if badge_rect is not None:
        # Style REGLABLE (voir apply_all_settings/STEP_BADGE_STYLE, Settings
        # > Colonnes > Projets > Colonnes > "Icone de niveaux") — largeur/
        # hauteur/bordure/rayon/couleur, MEME technique que n'importe quel
        # autre rectangle borde-arrondi de l'appli (_paint_bordered_rect),
        # plutot qu'un simple cercle fixe comme avant.
        badge_style = STEP_BADGE_STYLE
        badge_border_colors = {
            k: resolve_color_ref(v) for k, v in (badge_style.get("border") or {}).items()
        }
        # Lissage (antialiasing) du TRAIT de bordure — DESACTIVABLE (voir
        # Settings > Colonnes > Projets > Colonnes > "Icone de niveaux" >
        # "Lissage de la bordure"), contrairement au reste — voir la
        # remarque de l'utilisateur, "lissage des bordures" -> "antialiasing
        # du contour de la bordure".
        painter.setRenderHint(QPainter.Antialiasing, bool(badge_style.get("border_smoothing", True)))
        _paint_bordered_rect(
            painter, badge_rect, badge_style["radius"], badge_style.get("border_enabled") or {},
            max(1, int(badge_style.get("border_thickness", 1))), badge_border_colors,
            _step_badge_color(step_badge),
        )
        painter.setRenderHint(QPainter.Antialiasing, False)
        # Police/gras/lissage du numero (voir Settings > ... > "Icone de
        # niveaux" > "Police / gras / lissage du numero") — couleur PAR
        # BASE (_step_badge_text_color), PAS un champ separe (voir la
        # remarque de l'utilisateur, "enleve la couleur dans la ligne
        # texte ... la couleur du haut est pour le texte").
        badge_font_weight = 700 if badge_style.get("font_bold", True) else 400
        badge_font_family = _resolve_font_family(
            (badge_style.get("font_family") or "").strip(), 10, badge_font_weight, fallback_role="info")
        badge_smoothing = (
            badge_style.get("font_smoothing", "current")
            if badge_style.get("font_smoothing_enabled") else "current")
        painter.setPen(QColor(_step_badge_text_color(step_badge)))
        painter.setFont(font(10, badge_font_weight, family=badge_font_family, smoothing=badge_smoothing))
        painter.drawText(badge_rect, Qt.AlignCenter, str(step_badge))


class ProjectTileDelegate(QStyledItemDelegate):
    """Colonnes "Projets"/"Sous-projet" : meme rendu PARTAGE que RowDelegate
    (voir _paint_unified_row), avec la vignette de projet (perso si
    presente, voir project_thumbnail_path, sinon image par defaut
    generique) comme image."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.refresh_fonts()

    def refresh_fonts(self):
        self.font_name, self.color_name = _resolve_row_font_color(self.column.style_title)

    def sizeHint(self, option, index) -> QSize:
        # L'espacement est ajoute ici, retranche au dessin (voir paint) :
        # voir la remarque sur QListView.setSpacing dans Column.__init__.
        title = self.column.style_title
        return QSize(self.column.width(), self.column.effective_row_height() + col_spacing(title))

    def paint(self, painter: QPainter, option, index):
        # Rendu UNIQUE, PARTAGE avec RowDelegate (voir _paint_unified_row) —
        # voir la remarque de l'utilisateur, "je veux que tu reformate
        # toutes les autres colonnes exactement de la meme maniere que la
        # colonne type ... si une colonne a deja des images, reutilises
        # les" : la vignette de projet (project_thumbnail_pixmap, perso ou
        # generique par defaut, cache module-level partage — voir plus
        # haut) est REUTILISEE telle quelle, seule la mise en page/le style
        # autour changent.
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        path = Path(index.data(ROLE_PATH))
        title = self.column.style_title
        rect = option.rect.adjusted(0, 0, 0, -col_spacing(title))
        step_badge = None
        if title == "Projets" and bool(index.data(ROLE_ISDIR)):
            step_badge = project_step_count(load_project_columns(path))
        # Icone de logiciel (voir RowDelegate.paint, MEME regle "tous les
        # dossiers qui ont le nom d'un logiciel", meme si un Projet/Sous-
        # projet nomme comme un logiciel reste rare en pratique) — la
        # vignette de projet (project_thumbnail_pixmap, perso ou generique
        # par defaut) est elle un APERCU (voir _paint_unified_row) :
        # DISTINCTS, la premiere a gauche, le second desormais a droite.
        is_dir_entry = bool(index.data(ROLE_ISDIR))
        icon_key = software_icon_key(path.name) if is_dir_entry else None
        icon_pixmap = _row_icon_pixmap(is_dir_entry, icon_key, SOFTWARE_ICON_SIZE)
        is_shortcut = bool(index.data(ROLE_IS_SHORTCUT))
        if is_shortcut:
            shortcut_icon = custom_ui_icon_pixmap(UI_ICON_SHORTCUT, SOFTWARE_ICON_SIZE)
            if shortcut_icon is not None:
                icon_pixmap = shortcut_icon
        row_font, row_color = _resolve_shortcut_font_color() if is_shortcut else (self.font_name, self.color_name)
        _paint_unified_row(
            painter, rect, option, column_style_for(title),
            path.name, icon_pixmap, project_thumbnail_pixmap(path), row_font, row_color,
            self.column.is_active, step_badge=step_badge,
            icon_visible_override=self.column._show_icon_override,
            preview_visible_override=self.column._show_preview_override,
            icon_size_override=self.column._icon_size_override,
            icon_padding_left_override=self.column._icon_padding_left_override,
            text_padding_left_override=self.column._text_padding_left_override,
        )
        painter.restore()


def _square_checkbox_qss(muted: bool = False) -> str:
    """Habillage QSS partage par toutes les cases a cocher de
    ColumnConfigDialog (case CARREE petite + coche, pas le rendu natif de
    l'OS) — reproduit la maquette fournie par l'utilisateur, "change
    l'interface de la fenetre scrupuleusement comme celle en piece
    jointe" : le fonctionnement (isChecked/setChecked/toggled, deja
    utilise partout ci-dessous) reste EXACTEMENT celui d'un QCheckBox
    normal, seul l'indicateur est restyle via QSS (::indicator).

    `muted=True` (voir "Focus"/"In / Over / Out", toggles secondaires a
    cote de "Set") : texte NORMAL (pas seulement `:disabled`) attenue —
    voir la remarque de l'utilisateur, "le texte de focus et in over out
    doit etre vraiment moins perceptible"."""
    # 0.30 (pas 0.55) : voir la remarque de l'utilisateur, "le texte de
    # focus et in over out doit etre vraiment moins perceptible (plus de
    # transparence, laisse 30%)".
    text_color = f"rgba({', '.join(str(c) for c in _hex_to_rgb(C['text']))}, 0.30)" if muted else C['text']
    return (
        f"QCheckBox {{ color: {text_color}; spacing: 8px; background: transparent; }}"
        f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 2px; "
        f"border: 1px solid {C['border']}; background: {C['well']}; }}"
        f"QCheckBox::indicator:hover {{ border: 1px solid {C['accent']}; }}"
        f"QCheckBox::indicator:checked {{ background: {C['accent']}; border: 1px solid {C['accent']}; }}"
        # Grise (voir setEnabled(False), la remarque de l'utilisateur,
        # "quand set est desactive, desactive automatiquement focus, in
        # over et out, et grise les") : les couleurs ci-dessus etant fixes
        # (QSS EXPLICITE, pas le rendu natif de l'OS), Qt ne les assombrit
        # PAS automatiquement a l'etat desactive sans ces regles ":disabled"
        # dediees. rgba (alpha ~0.5 sur la couleur NORMALE, pas C['dim']
        # directement) : un simple saut vers C['dim'] (bien plus sombre que
        # le texte normal) rendait le grisage trop marque — voir la remarque
        # de l'utilisateur, "le grise de desactivation doit etre moins
        # perceptible".
        f"QCheckBox:disabled {{ color: rgba({', '.join(str(c) for c in _hex_to_rgb(C['text']))}, 0.45); }}"
        f"QCheckBox::indicator:disabled {{ "
        f"border: 1px solid rgba({', '.join(str(c) for c in _hex_to_rgb(C['border']))}, 0.6); "
        f"background: {C['well']}; }}"
    )


class _StepperField(QWidget):
    """Compteur "Nombre de colonnes" (ColumnConfigDialog) : boite en
    lecture + 2 petits boutons empiles ▲/▼, EXACTEMENT la maquette fournie
    par l'utilisateur (remplace le QSpinBox natif, dont le style de l'OS
    ne pouvait pas rendre cette disposition) — expose la MEME API minimale
    (value/setValue/valueChanged) qu'un QSpinBox, seuls les appelants
    utilises ci-dessous (voir _rebuild_blocks, ColumnConfigDialog.__init__)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self.setFixedSize(70, 26)
        self.setStyleSheet(
            f"background: {C['well']}; border: 1px solid {C['border']}; border-radius: 4px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.value_label = QLabel(str(self._value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(font(12, 400, mono=True))
        self.value_label.setStyleSheet(f"color: {C['text']}; background: transparent; border: none;")
        layout.addWidget(self.value_label, 1)

        btns = QWidget(self)
        btns.setFixedWidth(18)
        btns.setStyleSheet(f"background: transparent; border-left: 1px solid {C['border']};")
        btns_l = QVBoxLayout(btns)
        btns_l.setContentsMargins(0, 0, 0, 0)
        btns_l.setSpacing(0)
        up_btn = QPushButton("▲")
        down_btn = QPushButton("▼")
        for b, cb in ((up_btn, self._increment), (down_btn, self._decrement)):
            b.setFixedHeight(12)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {C['label']}; "
                f"border: none; font-size: 7px; padding: 0; }}"
                f"QPushButton:hover {{ color: {C['text']}; background: {C['hover']}; }}"
            )
            b.clicked.connect(cb)
            btns_l.addWidget(b)
        layout.addWidget(btns)

    def _increment(self):
        self.setValue(self._value + 1)

    def _decrement(self):
        self.setValue(self._value - 1)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.value_label.setText(str(value))
            self.valueChanged.emit(value)


class _OmitListField(QWidget):
    """Petite liste "a omettre" (repertoires/fichiers) reutilisable dans
    ColumnConfigDialog : QListWidget + boutons +/- (ajout via
    QInputDialog.getText, meme pattern que Column._create_folder)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.list = QListWidget(self)
        self.list.setFixedHeight(96)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; }}"
            f"QListWidget::item {{ padding: 2px 4px; }}"
            f"QListWidget::item:selected {{ background: {C['sel_idle']}; }}"
        )
        layout.addWidget(self.list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        add_btn = QPushButton("+")
        remove_btn = QPushButton("-")
        for b in (add_btn, remove_btn):
            b.setFixedSize(24, 20)
            # Police EXPLICITE (voir la remarque de l'utilisateur,
            # "ajoute + et - sur les boutons" — les glyphes restaient
            # quasi invisibles, herites d'une police par defaut trop
            # discrete pour une si petite case) : grasse, bien plus
            # grande que le texte courant, pour que +/- restent lisibles
            # a cette taille de bouton.
            b.setFont(font(13, 700))
            b.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; padding: 0px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
            )
        add_btn.clicked.connect(self._add)
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _add(self):
        name, ok = QInputDialog.getText(self, "Ajouter", "Nom a omettre :")
        name = name.strip()
        if ok and name:
            self.list.addItem(name)

    def _remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def values(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def set_values(self, values) -> None:
        self.list.clear()
        self.list.addItems([str(v) for v in (values or [])])


class _ColumnConfigBlock(QWidget):
    """Une CARTE "Colonne N" dans ColumnConfigDialog (largeur fixe, alignee
    a cote des autres dans une rangee defilante horizontalement) : nom +
    afficher repertoires/fichiers + listes a omettre + toggle Focus
    (independant par colonne, voir la remarque de l'utilisateur, "un
    toggle Focus independant par colonne") — reproduit la maquette fournie
    par l'utilisateur, "change l'interface de la fenetre scrupuleusement
    comme celle en piece jointe"."""

    CARD_WIDTH = 308

    def __init__(self, index: int, data: dict, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.CARD_WIDTH)
        self.setObjectName("ColCard")
        self.setStyleSheet(
            f"#ColCard {{ background: {C['chrome']}; border: 1px solid {C['border_soft']}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.setSpacing(9)
        label = QLabel(f"Nom colonne {index + 3}")
        label.setFont(font(11, 400))
        label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        name_row.addWidget(label)
        self.name_edit = QLineEdit(data.get("name", ""))
        self.name_edit.setStyleSheet(
            f"QLineEdit {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; padding: 3px 8px; }}"
        )
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.show_dirs_check = QCheckBox("Afficher les repertoires")
        self.show_files_check = QCheckBox("Afficher les fichiers")
        self.show_dirs_check.setChecked(bool(data.get("show_dirs", True)))
        self.show_files_check.setChecked(bool(data.get("show_files", False)))
        for cb in (self.show_dirs_check, self.show_files_check):
            cb.setStyleSheet(_square_checkbox_qss())
            layout.addWidget(cb)

        omit_row = QHBoxLayout()
        omit_row.setSpacing(10)
        dirs_col = QVBoxLayout()
        dirs_col.setSpacing(5)
        dirs_label = QLabel("Repertoires a omettre")
        dirs_label.setFont(font(9, 600, tracking=0.07))
        dirs_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        dirs_col.addWidget(dirs_label)
        self.omit_dirs = _OmitListField(self)
        self.omit_dirs.set_values(data.get("omit_dirs"))
        dirs_col.addWidget(self.omit_dirs)
        files_col = QVBoxLayout()
        files_col.setSpacing(5)
        files_label = QLabel("Fichiers a omettre")
        files_label.setFont(font(9, 600, tracking=0.07))
        files_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        files_col.addWidget(files_label)
        self.omit_files = _OmitListField(self)
        self.omit_files.set_values(data.get("omit_files"))
        files_col.addWidget(self.omit_files)
        omit_row.addLayout(dirs_col)
        omit_row.addLayout(files_col)
        layout.addLayout(omit_row)

        # Toggle "Focus" PAR COLONNE SUPPRIME (voir la remarque de
        # l'utilisateur, "supprime le toggle focus ... celui qui indique
        # coche focus le contenu du repertoire" — redondant/confus a cote
        # du toggle MAITRE "Focus" de ColumnConfigDialog, qui masque ou
        # affiche TOUTE la colonne fantome des vignettes). La valeur
        # persistee garde simplement celle DEJA enregistree pour ce niveau
        # (`_coerce_project_column`, repli `True` pour un bloc SANS config
        # anterieure — voir _rebuild_blocks) — plus aucun moyen de la
        # changer depuis cette fenetre, mais un fichier existant qui avait
        # deliberement "focus": False pour un niveau garde ce choix.
        self._focus_value = bool(data.get("focus", True))

    def data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "show_dirs": self.show_dirs_check.isChecked(),
            "show_files": self.show_files_check.isChecked(),
            "omit_dirs": self.omit_dirs.values(),
            "omit_files": self.omit_files.values(),
            "focus": self._focus_value,
        }


class ColumnConfigDialog(QDialog):
    """Fenetre de configuration de la chaine de navigation d'UN projet (voir
    le badge numerote cliquable, Column._open_column_config) — reproduit la
    maquette fournie par l'utilisateur : nombre de colonnes, blocs "Colonne
    N" dynamiques (nom, afficher repertoires/fichiers, a omettre, Focus
    independant), puis un bloc "Repertoire de travail" (type/afficher/
    omettre, sans Focus — voir WORK_DIR_TYPES). Enregistrer ecrit le fichier
    de config DANS LE DOSSIER DU PROJET (voir save_project_columns, choix de
    l'utilisateur "dans le dossier du projet ... voyage avec le projet")."""

    # MIN_STEPS = 2 (Type+Projets seuls, AUCUN niveau intermediaire — voir
    # load_project_columns, "columns": [] est desormais une config VALIDE)
    # — voir la remarque de l'utilisateur, "peux-tu faire en sorte de
    # pouvoir setter en base 2 ?".
    MIN_STEPS = 2
    MAX_STEPS = 12

    def __init__(self, project_path: Path, config: dict | None, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        # Plus large qu'avant (etait 460x560) : les colonnes configurees se
        # rangent desormais cote a cote (voir _blocks_container, cartes de
        # largeur fixe) au lieu d'etre empilees verticalement — reproduit
        # la maquette fournie par l'utilisateur, "change l'interface de la
        # fenetre scrupuleusement comme celle en piece jointe".
        self.resize(980, 850)
        # Redimensionnable par les bords (voir nativeEvent/showEvent
        # ci-dessous, meme mecanisme que PipelineBrowser/SettingsWindow) —
        # voir la remarque de l'utilisateur, "fait la fenetre configuration
        # redimensionnable".
        self.setMinimumSize(760, 480)

        self._blocks: list[dict] = []
        if config is not None:
            for col in config["columns"]:
                self._blocks.append(dict(col))
            self._work_dir = dict(config["work_dir"])
            self._set_enabled = bool(config.get("set_enabled", True))
            self._focus_enabled = bool(config.get("focus_enabled", True))
            self._in_over_out_enabled = bool(config.get("in_over_out_enabled", True))
        else:
            self._blocks = [{
                "name": "Sous-projet", "show_dirs": True, "show_files": False,
                "omit_dirs": [], "omit_files": [], "focus": True,
            }]
            self._work_dir = {
                # "show_files": True (PAS False) : voir la remarque de
                # l'utilisateur, "active par defaut les fichiers dans
                # repertoire de travail" — repli SEULEMENT pour un NOUVEAU
                # projet (config is None) ; un projet DEJA configure garde
                # sa propre valeur enregistree, jamais reecrasee ici.
                "type": DEFAULT_WORK_DIR_TYPE, "show_dirs": True, "show_files": True,
                "omit_dirs": [], "omit_files": [],
            }
            self._set_enabled = True
            self._focus_enabled = True
            self._in_over_out_enabled = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("ConfigPanel")
        panel.setStyleSheet(
            f"#ConfigPanel {{ background: {C['window']}; "
            f"border: 1px solid {C['border']}; border-radius: {WINDOW_RADIUS}px; }}"
        )
        outer.addWidget(panel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        head = QWidget(panel)
        head.setFixedHeight(34)
        head.setStyleSheet(f"background: {C['chrome']}; border-top-left-radius: {WINDOW_RADIUS}px; "
                            f"border-top-right-radius: {WINDOW_RADIUS}px;")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(12, 0, 8, 0)
        title_label = QLabel(f"Configuration - {project_path.name}")
        title_label.setFont(font(11, 600))
        title_label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        head_l.addWidget(title_label, 1)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        # Police EXPLICITE (voir _OmitListField, MEME correctif/MEME
        # raison — le glyphe restait quasi invisible sans elle, voir la
        # remarque de l'utilisateur, "je ne vois pas le x").
        close_btn.setFont(font(12, 700))
        close_btn.setStyleSheet(
            f"QPushButton {{ color: {C['label']}; background: transparent; border: none; padding: 0px; }}"
            f"QPushButton:hover {{ background: {C['hover']}; color: {C['text']}; }}"
        )
        close_btn.clicked.connect(self.reject)
        head_l.addWidget(close_btn)
        head.mousePressEvent = self._head_mouse_press
        panel_layout.addWidget(head)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(8)
        scroll.setWidget(body)
        panel_layout.addWidget(scroll, 1)

        spin_row = QHBoxLayout()
        spin_row.setSpacing(14)
        spin_label = QLabel("Nombre de colonnes")
        spin_label.setFont(font(12, 400))
        spin_label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        spin_row.addWidget(spin_label)
        self.spin = _StepperField(self.MIN_STEPS, self.MAX_STEPS, 2 + len(self._blocks), self)
        self.spin.valueChanged.connect(self._on_spin_changed)
        spin_row.addWidget(self.spin)
        spin_hint = QLabel("2 premieres colonnes figees — Type puis Projet")
        spin_hint.setFont(font(9, 400))
        spin_hint.setStyleSheet(f"color: {C['dim']}; background: transparent;")
        spin_row.addWidget(spin_hint)
        spin_row.addStretch(1)
        self._body_layout.addLayout(spin_row)

        # Toggles maitres (voir la remarque de l'utilisateur, "j'aimerai
        # ajouter trois toggles ... set / focus / logiciels" puis "in over
        # et out") — a 0 : "set" saute directement de Projets a la colonne
        # apres le groupe IN/OVER/OUT/LOGICIELS (aucun niveau intermediaire
        # configure ci-dessous n'est alors utilise, quel que soit leur
        # nombre) ; "focus" masque la colonne Focus (vignettes) ; "in/over/
        # out" masque ces 3 colonnes du groupe (LOGICIELS reste). Toggle
        # "logiciels" SUPPRIME (voir la remarque de l'utilisateur, "supprime
        # le toggle logiciels") — desormais toujours affichee.
        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(18)
        self.set_check = QCheckBox("Set")
        self.set_check.setChecked(self._set_enabled)
        self.set_check.setStyleSheet(_square_checkbox_qss())
        toggles_row.addWidget(self.set_check)
        self.focus_check_master = QCheckBox("Focus")
        self.focus_check_master.setChecked(self._focus_enabled)
        self.focus_check_master.setStyleSheet(_square_checkbox_qss(muted=True))
        toggles_row.addWidget(self.focus_check_master)
        self.in_over_out_check = QCheckBox("In / Over / Out")
        self.in_over_out_check.setChecked(self._in_over_out_enabled)
        self.in_over_out_check.setStyleSheet(_square_checkbox_qss(muted=True))
        toggles_row.addWidget(self.in_over_out_check)
        toggles_row.addStretch(1)
        self._body_layout.addLayout(toggles_row)

        # "Set" a 0 : "Focus"/"In / Over / Out" perdent tout sens (rien
        # avant lequel se distinguer, voir _chain_expected_total) —
        # decoches et desactives AUTOMATIQUEMENT, grises tant que "Set"
        # reste desactive — voir la remarque de l'utilisateur, "quand set
        # est desactive, desactive automatiquement focus, in over et out,
        # et grise les".
        def _on_set_toggled(checked: bool):
            if not checked:
                self.focus_check_master.setChecked(False)
                self.in_over_out_check.setChecked(False)
            self.focus_check_master.setEnabled(checked)
            self.in_over_out_check.setEnabled(checked)

        self.set_check.toggled.connect(_on_set_toggled)
        _on_set_toggled(self.set_check.isChecked())

        # "Colonne 1 - Type"/"Colonne 2 - Projet" : rangee label + boite
        # valeur (figee, italique) + note, comme les 2 premieres colonnes
        # FIXES de la maquette fournie par l'utilisateur.
        for fixed_index, fixed_label, fixed_value, fixed_note in (
            (1, "Type", project_path.parent.name, "Fixe — determine par le dossier racine"),
            (2, "Projet", project_path.name, "Fixe — determine par la selection en cours"),
        ):
            fixed_row = QHBoxLayout()
            fixed_row.setSpacing(14)
            name_lbl = QLabel(f"Colonne {fixed_index} — {fixed_label}")
            name_lbl.setFont(font(12, 400))
            name_lbl.setFixedWidth(150)
            name_lbl.setStyleSheet(f"color: {C['text']}; background: transparent;")
            fixed_row.addWidget(name_lbl)
            value_box = QLabel(fixed_value)
            value_box.setFont(font(11, 400, mono=True))
            value_box.setStyleSheet(
                f"background: {C['chrome']}; color: {C['label']}; font-style: italic; "
                f"border: 1px solid {C['border_soft']}; padding: 0 9px;"
            )
            value_box.setFixedHeight(25)
            fixed_row.addWidget(value_box)
            note_lbl = QLabel(fixed_note)
            note_lbl.setFont(font(9, 400))
            note_lbl.setStyleSheet(f"color: {C['dim']}; background: transparent;")
            fixed_row.addWidget(note_lbl)
            fixed_row.addStretch(1)
            self._body_layout.addLayout(fixed_row)

        # Cartes "Colonne N" cote a cote (voir _ColumnConfigBlock, largeur
        # fixe) dans leur PROPRE zone de defilement HORIZONTALE, imbriquee
        # dans la zone de defilement verticale du dialogue — reproduit la
        # rangee de cartes de la maquette fournie par l'utilisateur.
        blocks_scroll = QScrollArea(body)
        blocks_scroll.setWidgetResizable(True)
        blocks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        blocks_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        blocks_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        blocks_host = QWidget()
        blocks_host.setStyleSheet("background: transparent;")
        self._blocks_container = QHBoxLayout(blocks_host)
        self._blocks_container.setContentsMargins(0, 0, 0, 0)
        self._blocks_container.setSpacing(16)
        blocks_scroll.setWidget(blocks_host)
        self._body_layout.addWidget(blocks_scroll)
        self._block_widgets: list[_ColumnConfigBlock] = []
        self._rebuild_blocks()

        self._body_layout.addStretch(1)

        # "Repertoire de travail" BLOQUEE en bas, HORS de la zone
        # deroulante (voir `scroll`/`self._body_layout` ci-dessus) — ajoutee
        # a `panel_layout` directement, entre `scroll` et `btn_row` (voir
        # plus bas) : reste TOUJOURS visible, quelle que soit la position
        # de defilement du reste du contenu — voir la remarque de
        # l'utilisateur, "je veux que la partie repertoire de travail soit
        # bloquee en bas vers les boutons".
        work_section = QWidget(panel)
        work_section.setStyleSheet("background: transparent;")
        work_layout = QVBoxLayout(work_section)
        work_layout.setContentsMargins(14, 10, 14, 0)
        work_layout.setSpacing(8)

        line = QFrame(work_section)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background: {C['border_soft']}; border: none;")
        line.setFixedHeight(1)
        work_layout.addWidget(line)

        work_label = QLabel("REPERTOIRE DE TRAVAIL")
        work_label.setFont(font(10, 600, tracking=0.16))
        work_label.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        work_layout.addWidget(work_label)

        type_row = QHBoxLayout()
        type_row.setSpacing(14)
        type_lbl = QLabel("Type")
        type_lbl.setFont(font(12, 400))
        type_lbl.setFixedWidth(60)
        type_lbl.setStyleSheet(f"color: {C['text']}; background: transparent;")
        type_row.addWidget(type_lbl)
        self.work_type_combo = QComboBox()
        self.work_type_combo.setFixedHeight(26)
        self.work_type_combo.setStyleSheet(
            f"QComboBox {{ background: {C['well']}; color: {C['text']}; font-style: italic; "
            f"border: 1px solid {C['border']}; border-radius: 0px; padding: 3px 8px; }}"
            f"QComboBox:hover {{ border: 1px solid {C['accent']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        )
        for key, info in WORK_DIR_TYPES.items():
            self.work_type_combo.addItem(info["label"], key)
        idx = self.work_type_combo.findData(self._work_dir.get("type", DEFAULT_WORK_DIR_TYPE))
        self.work_type_combo.setCurrentIndex(max(0, idx))
        type_row.addWidget(self.work_type_combo)
        type_row.addStretch(1)
        work_layout.addLayout(type_row)

        self.work_show_dirs_check = QCheckBox("Afficher les repertoires")
        self.work_show_files_check = QCheckBox("Afficher les fichiers")
        self.work_show_dirs_check.setChecked(bool(self._work_dir.get("show_dirs", True)))
        # "Afficher les fichiers" active par defaut ICI aussi (repli True,
        # PAS False) — voir la remarque de l'utilisateur, "afficher les
        # fichiers doit etre active par defaut dans cette section" : filet
        # de securite en plus du defaut deja pose sur `self._work_dir`
        # (config is None, voir plus haut) — reste vrai meme si `self.
        # _work_dir` provenait d'un fichier plus ancien sans cette cle.
        self.work_show_files_check.setChecked(bool(self._work_dir.get("show_files", True)))
        for cb in (self.work_show_dirs_check, self.work_show_files_check):
            cb.setStyleSheet(_square_checkbox_qss())
            work_layout.addWidget(cb)

        work_omit_row = QHBoxLayout()
        work_omit_row.setSpacing(10)
        work_dirs_col = QVBoxLayout()
        work_dirs_col.setSpacing(5)
        work_dirs_label = QLabel("Repertoires a omettre")
        work_dirs_label.setFont(font(9, 600, tracking=0.07))
        work_dirs_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        work_dirs_col.addWidget(work_dirs_label)
        self.work_omit_dirs = _OmitListField(self)
        self.work_omit_dirs.set_values(self._work_dir.get("omit_dirs"))
        work_dirs_col.addWidget(self.work_omit_dirs)
        work_files_col = QVBoxLayout()
        work_files_col.setSpacing(5)
        work_files_label = QLabel("Fichiers a omettre")
        work_files_label.setFont(font(9, 600, tracking=0.07))
        work_files_label.setStyleSheet(f"color: {C['label']}; background: transparent;")
        work_files_col.addWidget(work_files_label)
        self.work_omit_files = _OmitListField(self)
        self.work_omit_files.set_values(self._work_dir.get("omit_files"))
        work_files_col.addWidget(self.work_omit_files)
        work_omit_row.addLayout(work_dirs_col)
        work_omit_row.addLayout(work_files_col)
        work_layout.addLayout(work_omit_row)

        work_note = QLabel("Le repertoire de travail peut aussi omettre certains repertoires ou fichiers.")
        work_note.setFont(font(9, 400))
        work_note.setStyleSheet(f"color: {C['dim']}; background: transparent;")
        work_layout.addWidget(work_note)

        panel_layout.addWidget(work_section)

        # Petit espace ENTRE les 2 boutons (pas colles l'un a l'autre),
        # tous 2 groupes a droite — voir la remarque de l'utilisateur,
        # "quand je disait separes, je voulais dire un petit espace"
        # (corrige un 1er essai qui les avait envoyes aux 2 extremites).
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(14, 10, 14, 10)
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Annuler")
        save_btn = QPushButton("Enregistrer")
        for b in (cancel_btn, save_btn):
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
            f"border: 1px solid {C['btn_border']}; border-radius: 4px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
        )
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {C['accent']}; color: {C['accent_text']}; "
            f"border: none; border-radius: 4px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ background: {C['accent']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        panel_layout.addLayout(btn_row)

    def _head_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            start_native_move(self)
            event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        apply_dwm_frame(self, WINDOW_RADIUS, C["border"], resizable=True)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redimensionnement par les bords (voir PipelineBrowser.nativeEvent/
        app_style.resize_hit_test, meme mecanisme) — necessite resizable=True
        dans showEvent ci-dessus (pose WS_THICKFRAME cote Windows)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _current_block_values(self) -> list[dict]:
        return [b.data() for b in self._block_widgets]

    def _rebuild_blocks(self):
        # Conserve les valeurs deja saisies, MEME celles temporairement
        # masquees par un aller-retour du spinner (ex. 5 -> 4 -> 5) : ne met
        # a jour QUE le prefixe actuellement visible de self._blocks (voir
        # la remarque de tete, "conserver les valeurs deja saisies") — les
        # entrees au-dela restent intactes tant qu'on ne les tronque pas
        # explicitement (jamais ici : seule la SAUVEGARDE ne retient que le
        # prefixe VISIBLE, voir _on_save/_current_block_values).
        if self._block_widgets:
            current = self._current_block_values()
            self._blocks[:len(current)] = current
        while self._blocks_container.count():
            item = self._blocks_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._block_widgets = []
        wanted = self.spin.value() - 2
        while len(self._blocks) < wanted:
            # Nom par defaut NON VIDE (voir la remarque de l'utilisateur,
            # "quand je passe d'une base 3 a 4, ca ne fonctionne pas, il
            # refuse d'augmenter la base") : un bloc cree avec un nom VIDE
            # se faisait discretement ELIMINER a l'enregistrement (voir
            # _on_save, `if c["name"]`) des que l'utilisateur oubliait de
            # le renommer avant de cliquer Enregistrer — le "nombre de
            # colonnes" retombait alors silencieusement a sa valeur
            # d'avant, donnant l'impression que le spinner "refusait"
            # d'augmenter la base alors qu'il l'augmentait bien, seule la
            # SAUVEGARDE perdait le nouveau niveau sans nom.
            # focus=True (pas False) : voir la remarque de l'utilisateur,
            # "pour les colonnes focus, je veux qu'il y ait toutes les
            # etapes du set entier ... si le projet est un projet base 4,
            # il doit y avoir 3 colonnes empilees, pour un projet base 5,
            # 4 colonnes empilees" — un niveau nouvellement ajoute (en
            # augmentant le spinner) participe donc desormais a la pile
            # Focus PAR DEFAUT, comme le tout premier niveau ("Sous-
            # projet") l'a toujours fait ; l'utilisateur reste libre de
            # decocher "Focus" ligne par ligne s'il veut en exclure un.
            self._blocks.append({
                "name": f"Colonne {len(self._blocks) + 3}", "show_dirs": True, "show_files": False,
                "omit_dirs": [], "omit_files": [], "focus": True,
            })
        for i, data in enumerate(self._blocks[:wanted]):
            block = _ColumnConfigBlock(i, data, self)
            self._blocks_container.addWidget(block)
            self._block_widgets.append(block)
        # Etirement final (voir la rangee HORIZONTALE de cartes ci-dessus,
        # __init__) : sans lui, peu de cartes s'etalaient toutes seules
        # sur toute la largeur au lieu de rester tassees a gauche comme
        # dans la maquette fournie par l'utilisateur.
        self._blocks_container.addStretch(1)

    def _on_spin_changed(self, _value):
        self._rebuild_blocks()

    def _on_save(self):
        columns = self._current_block_values()
        # Refuse (au lieu d'eliminer silencieusement, voir _rebuild_blocks
        # pour le detail du bug que ca causait) des qu'UN SEUL bloc visible
        # n'a pas de nom — jamais un filtre `if c["name"]` muet : perdre un
        # niveau sans que l'utilisateur le sache est exactement ce qui
        # donnait l'impression que "ca refuse d'augmenter la base". PAS de
        # `not columns` ici (contrairement a avant) : une liste VIDE est
        # desormais une configuration VALIDE ("base 2" — MIN_STEPS=2, voir
        # sa remarque, Type+Projets seuls) — voir la remarque de
        # l'utilisateur, "peux-tu faire en sorte de pouvoir setter en base
        # 2".
        if any(not c["name"] for c in columns):
            QMessageBox.warning(self, "Configuration", "Chaque colonne doit avoir un nom.")
            return
        work_dir = {
            "type": self.work_type_combo.currentData() or DEFAULT_WORK_DIR_TYPE,
            "show_dirs": self.work_show_dirs_check.isChecked(),
            "show_files": self.work_show_files_check.isChecked(),
            "omit_dirs": self.work_omit_dirs.values(),
            "omit_files": self.work_omit_files.values(),
        }
        # try/except (voir la remarque de l'utilisateur, "quand j'essaie
        # d'enregistrer une modification ... il ne se passe rien") : une
        # ecriture qui echoue (fichier verrouille par un autre programme,
        # droits insuffisants...) ne doit plus jamais se solder par une
        # exception NON rattrapee dans ce slot Qt — le dialogue restait
        # ouvert SANS aucun message, cause exacte de "ca ne prend pas en
        # compte les modifs" deja rencontree une fois (voir save_project_
        # columns/_clear_hidden, corrige separement pour le cas HIDDEN sur
        # Windows) : desormais un message explicite plutot qu'un silence.
        try:
            save_project_columns(self.project_path, {
                "columns": columns, "work_dir": work_dir,
                "set_enabled": self.set_check.isChecked(),
                "focus_enabled": self.focus_check_master.isChecked(),
                "in_over_out_enabled": self.in_over_out_check.isChecked(),
            })
        except OSError as exc:
            QMessageBox.warning(
                self, "Configuration", f"Impossible d'enregistrer la configuration :\n{exc}")
            return
        self.accept()


class SquareCaptureOverlay(QWidget):
    """Fenetre plein ecran translucide sur UN SEUL moniteur, permettant de
    choisir une zone carree a capturer (deplacable et redimensionnable a la
    souris). Reste volontairement limitee a un seul ecran : une fenetre qui
    chevauche deux moniteurs d'echelles differentes se fait etirer (bitmap
    stretch) par Windows lui-meme des que le process n'est pas reconnu
    "Per-Monitor DPI Aware" par le systeme (ce qui echappe totalement au
    controle de l'appli) — d'ou le flou/pixelisation observe en tentant de
    couvrir plusieurs ecrans dans une seule fenetre. Pour capturer sur
    plusieurs moniteurs, voir MultiScreenCapture qui ouvre une instance de
    cette classe par ecran. Emet `captured` (QPixmap deja carree) a la
    validation, ou `cancelled` si l'utilisateur abandonne (Echap / fermeture)."""

    captured = Signal(QPixmap)
    cancelled = Signal()

    HANDLE_SIZE = 16
    MIN_SIZE = 24

    def __init__(self, screen):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self.background = screen.grabWindow(0)
        self.setGeometry(screen.geometry())

        w, h = self.width(), self.height()
        size = max(self.MIN_SIZE, min(320, w, h))
        self.sel = QRect((w - size) // 2, (h - size) // 2, size, size)

        self._mode = None       # None | "move" | "resize" | "new"
        self._anchor = QPoint()
        self._drag_offset = QPoint()
        self._done = False

        self.font_hint = font(12, 500)

    def _handle_rect(self) -> QRect:
        s = self.HANDLE_SIZE
        return QRect(self.sel.right() - s + 1, self.sel.bottom() - s + 1, s, s)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.background)

        painter.setClipRegion(self._dim_region())
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setClipping(False)

        painter.setPen(QPen(QColor(C["accent"]), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.sel)

        handle = self._handle_rect()
        painter.fillRect(handle, QColor(C["accent"]))

        painter.setFont(self.font_sub_size())
        painter.setPen(QColor("#ffffff"))
        label = f"{self.sel.width()} x {self.sel.height()}"
        painter.drawText(self.sel.x(), max(16, self.sel.y() - 8), label)

        painter.setFont(self.font_hint)
        painter.setPen(QColor("#ffffff"))
        hint = (
            "Glisser l'interieur pour deplacer  •  coin bas-droit pour redimensionner  •  "
            "Entree pour valider  •  Echap pour annuler"
        )
        painter.drawText(20, self.height() - 24, hint)

    def font_sub_size(self):
        return font(11, 400, mono=True)

    def _dim_region(self):
        return QRegion(self.rect()).subtracted(QRegion(self.sel))

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if self._handle_rect().contains(pos):
            self._mode = "resize"
            self._anchor = self.sel.topLeft()
        elif self.sel.contains(pos):
            self._mode = "move"
            self._drag_offset = pos - self.sel.topLeft()
        else:
            self._mode = "new"
            self._anchor = pos
            self.sel = QRect(pos, QSize(1, 1))
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._mode == "move":
            top_left = pos - self._drag_offset
            top_left.setX(max(0, min(top_left.x(), self.width() - self.sel.width())))
            top_left.setY(max(0, min(top_left.y(), self.height() - self.sel.height())))
            self.sel.moveTopLeft(top_left)
            self.update()
        elif self._mode == "resize":
            size = max(self.MIN_SIZE, min(pos.x() - self._anchor.x(), pos.y() - self._anchor.y()))
            size = min(size, self.width() - self._anchor.x(), self.height() - self._anchor.y())
            self.sel = QRect(self._anchor, QSize(size, size))
            self.update()
        elif self._mode == "new":
            dx, dy = pos.x() - self._anchor.x(), pos.y() - self._anchor.y()
            size = max(abs(dx), abs(dy), 1)
            x = self._anchor.x() if dx >= 0 else self._anchor.x() - size
            y = self._anchor.y() if dy >= 0 else self._anchor.y() - size
            x = max(0, min(x, self.width() - size))
            y = max(0, min(y, self.height() - size))
            size = min(size, self.width() - x, self.height() - y)
            self.sel = QRect(x, y, size, size)
            self.update()
        else:
            if self._handle_rect().contains(pos):
                self.setCursor(Qt.SizeFDiagCursor)
            elif self.sel.contains(pos):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        self._mode = None

    def mouseDoubleClickEvent(self, event):
        self._finish()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish()
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _finish(self):
        if self.sel.width() < self.MIN_SIZE or self.sel.height() < self.MIN_SIZE:
            return
        dpr = self.background.devicePixelRatio()
        crop = QRect(
            round(self.sel.x() * dpr), round(self.sel.y() * dpr),
            round(self.sel.width() * dpr), round(self.sel.height() * dpr),
        )
        cropped = self.background.copy(crop)
        cropped.setDevicePixelRatio(1.0)
        self._done = True
        self.captured.emit(cropped)
        self.close()

    def closeEvent(self, event):
        if not self._done:
            self.cancelled.emit()
        super().closeEvent(event)


class MultiScreenCapture(QObject):
    """Ouvre un SquareCaptureOverlay par ecran physique connecte, pour
    permettre de capturer sur n'importe lequel sans jamais faire chevaucher
    une seule fenetre sur deux ecrans d'echelles differentes (voir
    SquareCaptureOverlay). Valider la selection dans l'un d'eux ferme
    automatiquement tous les autres ; Echap dans n'importe lequel annule
    l'ensemble. `captured`/`cancelled` ne sont emis qu'une seule fois."""

    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, initial_screen=None, parent=None):
        super().__init__(parent)
        self._done = False
        screens = QApplication.screens()
        focus_screen = initial_screen or QApplication.screenAt(QCursor.pos()) or screens[0]

        self._overlays = [SquareCaptureOverlay(screen) for screen in screens]
        for overlay in self._overlays:
            overlay.captured.connect(self._on_captured)
            overlay.cancelled.connect(self._on_cancelled)
            overlay.show()
        for overlay, screen in zip(self._overlays, screens):
            if screen is focus_screen:
                overlay.activateWindow()
                overlay.setFocus()

    def _on_captured(self, pix: QPixmap):
        if self._done:
            return
        self._done = True
        self._close_all()
        self.captured.emit(pix)

    def _on_cancelled(self):
        if self._done:
            return
        self._done = True
        self._close_all()
        self.cancelled.emit()

    def _close_all(self):
        for overlay in self._overlays:
            if overlay.isVisible():
                overlay._done = True  # evite un cancelled/capture en double
                overlay.close()


# ==========================================================================
# Liste avec glisser-deposer de vrais fichiers
# ==========================================================================

class FileListWidget(QListWidget):
    """QListWidget dont le glisser-deposer manipule des fichiers reels sur
    le disque : entre colonnes de l'app, mais aussi avec l'explorateur
    Windows (et inversement)."""

    def __init__(self, column: "Column", parent=None):
        super().__init__(parent)
        self.column = column
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def mimeData(self, items):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(it.data(ROLE_PATH)) for it in items])
        return mime

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def startDrag(self, supportedActions):
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction)
        self.column.refresh_all()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return

        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            action = Qt.CopyAction
        elif mods & Qt.ShiftModifier:
            action = Qt.MoveAction
        elif event.proposedAction() in (Qt.CopyAction, Qt.MoveAction):
            action = event.proposedAction()
        else:
            action = Qt.CopyAction

        target_item = self.itemAt(event.position().toPoint())
        dest_dir = self.column.directory
        if target_item and target_item.data(ROLE_ISDIR):
            dest_dir = Path(target_item.data(ROLE_PATH))

        last_dest = self.apply_drop(mime.urls(), action, dest_dir)

        event.setDropAction(action)
        event.accept()
        if last_dest:
            for i in range(self.count()):
                it = self.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.setCurrentItem(it)
                    break

    def apply_drop(self, urls, action, dest_dir: Path | None = None) -> Path | None:
        """Copie ou deplace les fichiers/dossiers de `urls` dans `dest_dir`
        (par defaut le dossier de cette colonne ; peut aussi etre un
        sous-dossier vise directement, cf. dropEvent). Retourne le dernier
        chemin depose (ou None). Separe de dropEvent() pour rester testable
        sans QDropEvent reel."""
        dest_dir = dest_dir if dest_dir is not None else self.column.directory
        errors = []
        last_dest = None
        for url in urls:
            if not url.isLocalFile():
                continue
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            try:
                if src.resolve() == dest_dir.resolve():
                    continue
                if src.parent.resolve() == dest_dir.resolve():
                    continue  # deja dans ce dossier
                if src.is_dir() and dest_dir.resolve() != src.resolve():
                    try:
                        dest_dir.resolve().relative_to(src.resolve())
                        continue  # depose dans lui-meme ou un sous-dossier
                    except ValueError:
                        pass
            except OSError:
                continue
            dest = self.column._unique_dest_path(src, dest_dir)
            try:
                if action == Qt.MoveAction:
                    shutil.move(str(src), str(dest))
                else:
                    if src.is_dir():
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")

        if errors:
            QMessageBox.warning(
                self, "Glisser-deposer",
                "Impossible de deplacer/copier :\n" + "\n".join(errors),
            )

        self.column.refresh_all()
        return last_dest


# ==========================================================================
# Apercu empile (premiere colonne) : quand un projet, puis un sous-projet,
# est selectionne plus loin dans l'arborescence, la toute premiere colonne
# affiche sous sa propre liste un aperçu (image carree + titre) par niveau
# selectionne ayant une vignette, empiles les uns sous les autres.
# ==========================================================================

PREVIEW_TITLE_HEIGHT = 52   # hauteur fixe de la barre de titre (grand intitule "affiche"), au-dessus de chaque image empilee
PREVIEW_STATUS_HEIGHT = 26  # hauteur de la rangee d'indicateurs in/over/out, au-dessus du titre
PREVIEW_HEADER_HEIGHT = PREVIEW_STATUS_HEIGHT + PREVIEW_TITLE_HEIGHT


class _SquarePreviewImage(QLabel):
    """Image bord a bord (aucune marge) avec les bords de la colonne, de
    taille EXPLICITEMENT fixee (voir set_rect) plutot que recalculee en
    reaction a un resizeEvent : un widget dont la taille reagit a son propre
    resizeEvent peut se faire redimensionner une seconde fois par son parent
    avant que ce premier changement soit repercute, le rendant tantot trop
    petit, tantot etire par un layout qui redistribue l'espace en trop —
    exactement le symptome observe (espaces morts, doublons visuels lors
    d'une navigation rapide). Taille fixe des le depart = aucune ambiguite.
    Le fichier d'origine sur le disque n'est jamais modifie/degrade : on ne
    fait que le redimensionner en memoire pour l'affichage.

    "Square" dans le nom pour raisons historiques (garde tel quel, deja
    reference ailleurs) : le rectangle n'est plus force carre depuis
    Colonnes > Apercu > Image > Ratio (voir set_rect/la remarque de
    l'utilisateur, "je veux une section ratio")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw = QPixmap()
        # Pas de "border-bottom" ici (essaye puis abandonne) : sur un QLabel
        # de taille fixe rempli d'un pixmap plein cadre, ce filet ne se
        # rendait pas de facon fiable. Le separateur entre blocs est
        # desormais un widget dedie, voir _PreviewBlock. Fond C["chrome"]
        # (pas C["well"]) : c'est la couleur des en-tetes de colonne, celle
        # de tout le bloc (voir _PreviewBlock) — doit rester coherente
        # derriere l'image elle-meme, la ou le padding/le lettrboxing la
        # laisse apparaitre.
        self.setStyleSheet(f"background: {C['chrome']};")

    def set_source_pixmap(self, pixmap: QPixmap):
        self._raw = pixmap
        self._refresh()

    def set_side(self, side: int):
        """Alias retro-compatible de set_rect(side, side) — carre."""
        self.set_rect(side, side)

    def set_rect(self, width: int, height: int):
        if width > 0 and height > 0:
            self.setFixedSize(width, height)
        self._refresh()

    def _refresh(self):
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0 or self._raw.isNull():
            self.clear()
            return
        # Padding (voir Colonnes > Apercu > Image) N'EST PLUS gere ici : le
        # widget recoit desormais directement sa taille FINALE, deja
        # reduite du padding par _PreviewBlock (voir sa remarque, "la
        # largeur de l'image correspond a la largeur de la colonne moins
        # les differents padding") — ce widget ne fait plus que recadrer
        # "cover"/arrondir sur SA PROPRE taille, sans plus rien composer
        # dedans. Rayon (dict 4 coins INDEPENDANTS, voir apply_all_
        # settings) : minimum=0 — une valeur reglee a 0 doit le rester
        # (voir scaled).
        radius = {k: scaled(v, 0) for k, v in _radius_dict(PREVIEW_IMAGE_RADIUS).items()}
        # _cover_crop_rect (PAS un simple scaled()) : "remplir" (recadre en
        # conservant le ratio, comme le fond d'ecran Windows), voir la
        # remarque de l'utilisateur, "l'image d'origine doit s'adapter aux
        # dimensions choisies ... comme 'remplir' dans Windows".
        cropped = _cover_crop_rect(self._raw, width, height)
        if not _radius_any(radius):
            self.setPixmap(cropped)
            return
        # Coins arrondis (voir Colonnes > Apercu > Image) : masque construit
        # a la main (REMPLISSAGE antialiase + CONTOUR de composition
        # DestinationIn via drawPixmap), PAS un fillPath direct sur
        # `masked` — MEME correctif/MEME raison que _paint_row_image (voir
        # sa docstring) : fillPath ne compose que les pixels que le CHEMIN
        # touche reellement, laissant les coins (hors chemin) intacts/
        # opaques — un fillPath direct ici est EXACTEMENT le bug signale
        # par l'utilisateur, "les coins arrondis ... ça ne fonctionne
        # pas". Un mask PIXMAP intermediaire, lui, couvre le rectangle
        # ENTIER (drawPixmap touche tous les pixels), donc les coins y
        # redeviennent bien transparents.
        mask = QPixmap(width, height)
        mask.fill(Qt.transparent)
        mkp = QPainter(mask)
        mkp.setRenderHint(QPainter.Antialiasing, True)
        mkp.setPen(Qt.NoPen)
        mkp.setBrush(Qt.white)
        mkp.drawPath(_rounded_rect_path(QRect(0, 0, width, height), radius))
        mkp.end()

        masked = QPixmap(width, height)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.drawPixmap(0, 0, cropped)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()
        self.setPixmap(masked)


class _StatusLabel(QLabel):
    """Un des trois indicateurs in/over/out en tete d'un _PreviewBlock : voir
    STATUS_FOLDERS/status_folder_state. Sombre et inerte si le dossier
    correspondant est vide/absent, clair et cliquable (ouvre le dossier) des
    qu'il contient quelque chose."""

    clicked = Signal()

    def __init__(self, name: str, active: bool, parent=None, font_size: int = 10,
                 active_color: str | None = None, idle_color: str | None = None,
                 font_family: str | None = None, smoothing: str = "current",
                 weight: int = 700, italic: bool = False):
        super().__init__(name.upper(), parent)
        self._active = active
        # `font_family` (voir Colonnes > Apercu > Zone titre > Polices >
        # "Apercu des dossiers") : famille REELLEMENT resolue (voir
        # _resolve_font_family), pas le libelle stocke — None = role
        # "info" par defaut (comportement INCHANGE). `smoothing` (voir
        # _OverrideSmoothingField) : role_font n'accepte pas de surcharge
        # explicite (suit toujours le lissage DU ROLE) — on en extrait
        # seulement la famille ici, `font()` applique ensuite le lissage
        # demande par-dessus.
        resolved_family = font_family or role_font("info", font_size, 700, tracking=0.08).family()
        self.setFont(font(font_size, weight, family=resolved_family, tracking=0.08, smoothing=smoothing, italic=italic))
        # C["text"]/C["dim"] directement, PAS role_color("info", ...) : ce
        # role peut etre personnalise par l'utilisateur (fenetre de
        # parametres) avec une couleur fixe, qui ecraserait alors les DEUX
        # branches actif/inactif avec la meme teinte (role_color ignore le
        # `default_hex` passe des qu'une surcharge existe) — l'etat vide/
        # rempli du dossier ne doit jamais dependre de ce reglage.
        # `active_color`/`idle_color` (voir Colonnes > Apercu > Zone titre >
        # Polices > "Apercu des dossiers"/"Non selectionne", MEME ligne —
        # voir la remarque de l'utilisateur, "ajoute une couleur : non
        # selectionne, sur la meme ligne que apercu des dossiers -
        # couleur").
        color = (active_color or C["text"]) if active else (idle_color or C["dim"])
        self.setStyleSheet(f"color: {color}; background: transparent;")
        if active:
            self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if self._active and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _ColumnStyleBorderOverlay(QWidget):
    """Fine couche transparente, toujours AU-DESSUS des autres enfants (voir
    _PreviewBlock, raise_ee a chaque redimensionnement) :
    peint SEULEMENT la bordure/le rayon "style colonne" (voir
    _paint_column_style_border) PAR-DESSUS le contenu deja peint (l'image
    bord a bord y compris) — un paintEvent directement sur le widget parent
    serait, lui, peint AVANT ses enfants (l'ordre normal de composition
    Qt : parent, puis enfants par-dessus), donc recouvert par l'image
    plutot que visible par-dessus elle."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, event):
        _paint_column_style_border(self)


def _paint_column_style_border(widget: QWidget):
    """Peint, PAR-DESSUS le contenu deja affiche de `widget`, le MEME cadre
    (bordure/rayon, PAS le fond — deja peint par le style-sheet du widget)
    que celui des vraies colonnes (voir app_style.column_frame_style,
    style GENERAL) — voir la remarque de l'utilisateur, "je veux les trois
    colonnes (avec style predefini dans les settings) les unes sur les
    autres" : _PreviewBlock doit avoir l'air d'une colonne a lui seul.
    PREVIEW_STACK_TITLE (PAS "Sous-projet", contrairement a une version
    precedente) : "Sous-projet" est desormais un titre SURCHARGEABLE (voir
    settings_window._build_column_override_page), une surcharge active la
    aurait alors fuite ICI (sur le bloc "Projets" aussi, montre avec le
    MEME style que celui de "Sous-projet") au lieu du style GENERAL voulu
    pour ce cadre "decoratif" — PREVIEW_STACK_TITLE n'est jamais surcharge,
    garantit donc TOUJOURS le style general, quoi que l'utilisateur regle
    par ailleurs. scaled() sur rayon/epaisseur : meme raison que Column.
    refresh_colors (coherence a l'echelle d'interface)."""
    frame = column_frame_style(PREVIEW_STACK_TITLE)
    radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
    thickness = scaled(frame["thickness"], 0)
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
    _paint_bordered_rect(painter, widget.rect(), radius, frame["enabled"], thickness, frame["colors"], None)
    painter.end()


class _PreviewBlock(QWidget):
    """Contenu d'UNE colonne fantome de l'apercu (voir PreviewColumn.
    set_preview_block) : une rangee d'indicateurs in/over/out, une grande
    barre de titre « affiche » (nom du projet/sous-projet), suivies
    directement (sans espace) de son image carree bord a bord avec la
    colonne. `width` (la largeur de contenu de la colonne au moment de la
    construction) fixe la taille de l'image des le depart — voir
    _SquarePreviewImage.set_side. `path` sert a determiner l'etat des trois
    indicateurs (voir status_folder_state) ; `open_status(folder_path)` est
    appele au clic sur un indicateur actif (voir
    PipelineBrowser._open_group_folder : ouvre son contenu dans la colonne
    suivante, pas dans l'explorateur Windows). PAS d'entete ICI : chaque
    niveau (Projets/Sous-projet) est une VRAIE colonne fantome a part
    entiere (voir PreviewColumn, construite avec son PROPRE titre reel),
    empilees VERTICALEMENT (une colonne sous l'autre, PAS cote a cote —
    voir PipelineBrowser.update_preview_stack), ce bloc n'est que le
    CONTENU de l'une d'elles — voir la remarque de l'utilisateur, "non,
    tu as merger les deux colonnes en une seule, ce que je veux c'est deux
    colonnes separees, une en dessous de l'autre !"."""

    def __init__(self, title: str, pixmap: QPixmap, width: int, path: Path, open_status,
                 source_column: "Column" = None, parent=None):
        super().__init__(parent)
        # Chemin REPRESENTE par ce bloc (le dossier Projet/Sous-projet/
        # niveau configure actuellement selectionne) — garde ici (self.
        # _path) pour le menu clic droit (voir _on_context_menu, la
        # remarque de l'utilisateur, "les fichiers et dossiers de focus ne
        # fonctionnent pas comme les autres colonnes, notamment pour le
        # clic droit") : jusqu'ici ce widget n'avait AUCUNE interaction
        # clic droit du tout, contrairement a une ligne normale (voir
        # Column._on_context_menu). `source_column` (voir _rename) : la
        # VRAIE colonne de navigation dont ce bloc reprend la selection
        # courante — permet de renommer avec la MEME resynchronisation de
        # la navigation qu'une ligne normale (voir Column._rename_item) —
        # voir la remarque de l'utilisateur, "je veux que le comportement
        # des colonnes fonctionne de la meme maniere sur tous les points".
        self._path = path
        self._source_column = source_column
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        # Style EFFECTIF de Colonnes > Apercu (voir app_style.column_style_
        # for/PREVIEW_STACK_TITLE) — "Zone titre" (hauteur/police du titre/
        # police de l'apercu des dossiers) — voir la remarque de
        # l'utilisateur, "toujours dans la section colonnes/apercu, je veux
        # une section 'zone titre' avec les parametres suivants : hauteur
        # ... polices : titre (taille, couleur, padding) ... apercu des
        # dossiers (taille, couleur, padding)".
        s = column_style_for(PREVIEW_STACK_TITLE)
        title_height = int(s.get("preview_title_zone_height", PREVIEW_TITLE_HEIGHT))
        title_font_size = int(s.get("preview_title_font_size", 26))
        title_font_color = resolve_color_ref(s.get("preview_title_font_color", "#d6d9dc"))
        # Choix de police (police du soft ou police systeme, voir
        # _resolve_font_family/_DualFontSelectField) — voir la remarque de
        # l'utilisateur, "je veux le choix de la police (titre + apercu
        # des dossiers) (choix entre polices appli ou polices systeme)".
        title_font_weight = 700 if s.get("preview_title_font_bold", True) else 400
        title_font_italic = bool(s.get("preview_title_font_italic", False))
        title_font_family = _resolve_font_family(
            (s.get("preview_title_font_family") or "").strip(), title_font_size, title_font_weight)
        # Lissage (voir Colonnes > Texte > Lissage, MEME mecanique
        # toggle+niveau) — voir la remarque de l'utilisateur, "ajoute les
        # niveaux de lissage sur les lignes des polices".
        title_font_smoothing = (
            s.get("preview_title_font_smoothing", "current")
            if s.get("preview_title_font_smoothing_enabled") else "current")
        title_pad = s.get("preview_title_padding") or {"left": 14, "top": 0, "right": 14, "bottom": 8}
        status_font_size = int(s.get("preview_status_font_size", 10))
        status_font_color = resolve_color_ref(s.get("preview_status_font_color", "#d6d9dc"))
        status_font_color_idle = resolve_color_ref(s.get("preview_status_font_color_idle", "#5f666b"))
        status_font_weight = 700 if s.get("preview_status_font_bold", True) else 400
        status_font_italic = bool(s.get("preview_status_font_italic", False))
        status_font_family = _resolve_font_family(
            (s.get("preview_status_font_family") or "").strip(), status_font_size, status_font_weight,
            fallback_role="info")
        status_font_smoothing = (
            s.get("preview_status_font_smoothing", "current")
            if s.get("preview_status_font_smoothing_enabled") else "current")
        status_pad = s.get("preview_status_padding") or {"left": 14, "top": 0, "right": 14, "bottom": 0}

        # Fond unique du bloc entier (indicateurs + titre + image), pas
        # seulement derriere l'image : la "grande affiche" doit se lire
        # comme un seul panneau, sans bande de couleur differente au-dessus.
        # MEME couleur que le cadre de la colonne (Colonnes > Focus >
        # Colonnes > Couleur de fond, voir app_style.column_frame_style,
        # PAS C["chrome"] fige comme avant) : sinon, la ou l'entete est
        # masquee (header_visible=False) ou la zone titre reste
        # transparente, ce bloc laissait voir C["chrome"] au lieu de cette
        # couleur — voir la remarque de l'utilisateur, "la couleur de fond
        # doit aussi controler les zones avec la croix rouge sur le
        # screenshot et la zone sous l'entete".
        # WA_StyledBackground indispensable ici : ce widget est un ENFANT
        # (dans preview_layout/PreviewColumn, eux-memes dans la fenetre),
        # pas une fenetre top-level — sans cet attribut, Qt
        # n'applique jamais le fond du style-sheet sur un simple QWidget
        # enfant (il retombe sur le fond herite de ses parents, ici
        # C["window"] via la regle globale QWidget), meme si le style-sheet
        # semble correct. Piege deja documente ailleurs dans ce fichier
        # (TitleBar, DetailPanel, PreviewColumn) — oublie ici la premiere
        # fois, d'ou le fond incoherent malgre un style-sheet "correct".
        block_bg = resolve_color_ref(s.get("column_bg_color", "@skinN2"))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {block_bg};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        status_bar = QWidget()
        status_bar.setFixedHeight(PREVIEW_STATUS_HEIGHT)
        # MEME couleur que le reste du bloc (block_bg, Colonnes > Focus >
        # Colonnes > Couleur de fond) — PAS de fond de selection sous les
        # items des colonnes Focus (essaye puis retire, voir la remarque
        # de l'utilisateur, "je ne veux pas de fond de selection sous les
        # items des colonnes focus"). Aucun filet entre les indicateurs et
        # le titre (border: none, EXPLICITE) — juste explicite ici pour ne PAS
        # heriter d'un style par defaut.
        status_bar.setAttribute(Qt.WA_StyledBackground, True)
        status_bar.setStyleSheet(f"background: {block_bg}; border: none;")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(
            int(status_pad.get("left", 14)), int(status_pad.get("top", 0)),
            int(status_pad.get("right", 14)), int(status_pad.get("bottom", 0)))
        status_layout.setSpacing(14)
        status_layout.addStretch(1)
        for name in STATUS_FOLDERS:
            active, folder_path = status_folder_state(path, name)
            label = _StatusLabel(
                name, active, font_size=status_font_size,
                active_color=status_font_color, idle_color=status_font_color_idle,
                font_family=status_font_family, smoothing=status_font_smoothing,
                weight=status_font_weight, italic=status_font_italic)
            if active:
                label.clicked.connect(lambda p=folder_path: open_status(p))
            status_layout.addWidget(label)
        layout.addWidget(status_bar)
        self._status_bar = status_bar

        title_bar = QWidget()
        title_bar.setFixedHeight(title_height)
        # MEME couleur que status_bar/le reste du bloc (block_bg) — voir sa
        # remarque juste au-dessus.
        title_bar.setAttribute(Qt.WA_StyledBackground, True)
        title_bar.setStyleSheet(f"background: {block_bg}; border: none;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(
            int(title_pad.get("left", 14)), int(title_pad.get("top", 0)),
            int(title_pad.get("right", 14)), int(title_pad.get("bottom", 8)))
        name = QLabel(title)
        name.setFont(font(
            title_font_size, title_font_weight, family=title_font_family, tracking=0.0,
            smoothing=title_font_smoothing, italic=title_font_italic))
        name.setStyleSheet(f"color: {title_font_color}; background: transparent;")
        # Colle au bas de la barre de titre (juste au-dessus de l'image),
        # pas centre sur toute sa hauteur : plus proche de l'image, plus
        # affiche.
        title_layout.addWidget(name, 0, Qt.AlignBottom | Qt.AlignLeft)
        layout.addWidget(title_bar)
        self._title_bar = title_bar

        # Toujours enveloppee dans image_wrap (meme si le padding est nul) :
        # une structure STABLE, jamais reconstruite, est necessaire pour
        # pouvoir juste re-appeler apply_width() plus tard (voir
        # PreviewColumn.resize_update) sans reconstruire tout le bloc a
        # chaque glisser de bordure — voir la remarque de l'utilisateur,
        # "je veux pouvoir controler la largeur des colonnes focus projet
        # et sous projet en slidant les bords de celles-ci ... la largeur
        # des images ... doit etre egale a cette largeur de colonne".
        self.image = _SquarePreviewImage()
        self.image.set_source_pixmap(pixmap)
        self._image_wrap = QWidget()
        # MEME couleur que status_bar/title_bar/le reste du bloc (block_bg)
        # — visible dans la marge du Padding de l'image (voir
        # _image_wrap_layout.setContentsMargins plus bas).
        self._image_wrap.setAttribute(Qt.WA_StyledBackground, True)
        self._image_wrap.setStyleSheet(f"background: {block_bg}; border: none;")
        self._image_wrap_layout = QVBoxLayout(self._image_wrap)
        self._image_wrap_layout.setContentsMargins(0, 0, 0, 0)
        self._image_wrap_layout.setSpacing(0)
        self._image_wrap_layout.addWidget(self.image)
        layout.addWidget(self._image_wrap)

        # PAS de filet sous l'image (essaye un temps, widget dedie sous
        # l'image) : redondant avec _ColumnStyleBorderOverlay (voir plus
        # bas), qui peint deja la bordure "colonne" complete (y compris son
        # cote haut, juste sous le bloc precedent) — deux traits l'un sous
        # l'autre a la jonction — voir la remarque de l'utilisateur,
        # "supprime la bordure qu'il y a sous la colonne (juste sous
        # l'image)".
        self.apply_width(width)

        # Style "colonne" (bordure/rayon des settings, voir
        # _paint_column_style_border) par-dessus tout le bloc — voir
        # _ColumnStyleBorderOverlay, la remarque de l'utilisateur.
        self._border_overlay = _ColumnStyleBorderOverlay(self)
        self._border_overlay.setGeometry(self.rect())
        self._border_overlay.raise_()
        # APRES la construction de _status_bar/_title_bar/_image_wrap/
        # self.image (voir _connect_context_menu, sa remarque) : cable le
        # clic droit EN PLUS sur chacun d'eux.
        self._connect_context_menu()

    def apply_width(self, width: int):
        """Recalcule la largeur/hauteur de l'image (et la hauteur totale du
        bloc) pour une largeur de colonne donnee — appelee une fois a la
        construction, puis a nouveau a CHAQUE glisser de bordure (voir
        PreviewColumn.resize_update), sans reconstruire le reste du bloc
        (entete/statut/zone titre INCHANGES) — voir la remarque de
        l'utilisateur, "je veux pouvoir controler la largeur des colonnes
        focus projet et sous projet en slidant les bords de celles-ci ...
        la largeur des images de ces colonnes doit etre egale a cette
        largeur de colonne". Re-resout le style a CHAQUE appel (pas de
        valeurs mises en cache a la construction) : reste coherent meme si
        Colonnes > Focus change entre-temps (previsualisation en direct)."""
        s = column_style_for(PREVIEW_STACK_TITLE)
        title_height = int(s.get("preview_title_zone_height", PREVIEW_TITLE_HEIGHT))
        img_ratio = float(s.get("item_image_ratio", 1.0) or 1.0)
        # Padding de l'image (voir Colonnes > Apercu > Image) : une marge de
        # layout REELLE autour de _SquarePreviewImage (voir _image_wrap
        # ci-dessus) plutot qu'un inset compose a l'interieur d'un widget de
        # taille pleine colonne — voir la remarque de l'utilisateur, "de
        # base, la largeur de l'image correspond a la largeur de la colonne
        # moins les differents padding (a calculer)".
        pad = s.get("preview_padding") or {}
        pad_left = max(0, scaled(int(pad.get("left", 0)), 0))
        pad_top = max(0, scaled(int(pad.get("top", 0)), 0))
        pad_right = max(0, scaled(int(pad.get("right", 0)), 0))
        pad_bottom = max(0, scaled(int(pad.get("bottom", 0)), 0))
        available_width = max(1, width - pad_left - pad_right)
        # Largeur TOUJOURS calee sur la largeur de colonne (moins le
        # padding), hauteur deduite du Ratio — plus de reglage "Hauteur de
        # l'image" (voir Colonnes > Focus > Colonnes > Image, ancienne cle
        # preview_image_height, retiree) — voir la remarque de
        # l'utilisateur, "supprime la ligne hauteur de l'image et calle la
        # largeur de l'image a la largeur de la colonne".
        img_width = available_width
        img_height = max(1, round(available_width / img_ratio))
        self.image.set_rect(img_width, img_height)
        self._image_wrap_layout.setContentsMargins(pad_left, pad_top, pad_right, pad_bottom)
        image_area_height = pad_top + img_height + pad_bottom

        # Sans une hauteur EXPLICITE, ce widget garde une politique de
        # taille verticale "Preferred" par defaut : des qu'un parent (voir
        # Column) lui offre plus de hauteur que son contenu n'en a besoin
        # (ex. la liste TYPE capee plus haut libere de la place), Qt etire
        # le bloc au-dela de sa hauteur reelle et repartit l'exces en
        # espaces morts AVANT, ENTRE et APRES ses sous-elements —
        # exactement le defaut visible (grand vide au-dessus du titre,
        # avant l'image). PAS d'entete ICI (elle vit sur la PreviewColumn
        # qui heberge ce bloc, voir set_preview_block) : PREVIEW_STATUS_
        # HEIGHT + title_height + img_height (PAS PREVIEW_BLOCK_EXTRA_
        # HEIGHT + width, fige sur les anciennes constantes/le carre) :
        # hauteur EFFECTIVE, ratio/hauteur de zone titre compris.
        self.setFixedHeight(PREVIEW_STATUS_HEIGHT + title_height + image_area_height)

    def install_resize_filter(self, owner: QWidget):
        """Installe `owner` (PreviewColumn, voir resize_begin/resize_update/
        _in_resize_zone) comme filtre d'evenements sur chacune des barres
        pleine-largeur de ce bloc (statut/zone titre/image) : sans
        ceci, un widget ENFANT sous le curseur intercepte l'evenement souris
        AVANT que PreviewColumn ne le voie, rendant la bordure de
        redimensionnement inaccessible des que le curseur survole un bloc
        empile — MEME piege/MEME correctif que Column (voir son
        eventFilter/installEventFilter dans __init__) — voir la remarque de
        l'utilisateur, "je veux pouvoir controler la largeur des colonnes
        focus projet et sous projet en slidant les bords de celles-ci".
        setMouseTracking(True) sur chacun : Column.header s'en charge deja
        explicitement (voir Column.__init__), mais un QWidget/QLabel simple
        ne le fait PAS par defaut (contrairement au viewport d'un
        QListWidget, qui l'active tout seul) — sans lui, Qt ne livre les
        MouseMove de survol (sans bouton enfonce) a AUCUN de ces widgets,
        donc jamais a l'eventFilter installe dessus : le curseur ne se
        changeait jamais en fleche de redimensionnement en survolant un
        bloc, rendant la bordure impossible a reperer avant de cliquer a
        l'aveugle — voir la remarque de l'utilisateur, "je n'arrive pas
        bien a selectionner le bord des colonnes de focus pour le
        redimensionnement"."""
        for w in (self._status_bar, self._title_bar, self._image_wrap, self.image):
            w.setMouseTracking(True)
            w.installEventFilter(owner)

    def _on_context_menu(self, pos):
        """Relais pour self.customContextMenuRequested (voir __init__) —
        `pos` LOCALE a `self` : voir _show_context_menu pour le VRAI menu,
        partage avec _connect_context_menu (cable EN PLUS sur chaque
        widget ENFANT pleine-largeur, voir sa remarque)."""
        self._show_context_menu(self.mapToGlobal(pos))

    def _connect_context_menu(self):
        """Cable le menu clic droit EN PLUS sur chaque widget ENFANT
        pleine-largeur du bloc (statut/zone titre/image — MEME liste que
        install_resize_filter, MEME raison), pas SEULEMENT sur `self` —
        voir la remarque de l'utilisateur, "le menu clic droit n'apparait
        pas dans les colonnes focus" : compter sur la seule PROPAGATION
        Qt d'un QContextMenuEvent ignore vers le widget PARENT (ce que
        `self.setContextMenuPolicy` seul suppose) s'est avere peu fiable
        ici — voir install_resize_filter, qui documente DEJA exactement
        le meme piege ("un widget ENFANT sous le curseur intercepte
        l'evenement AVANT que le parent ne le voie") pour le
        redimensionnement, corrige alors de la MEME facon (installation
        EXPLICITE sur chaque enfant plutot que de compter sur la
        remontee). Appelee en FIN de __init__, une fois ces widgets
        construits (contrairement a self.setContextMenuPolicy, deja pose
        plus haut des la construction)."""
        for child in (self._status_bar, self._title_bar, self._image_wrap, self.image):
            child.setContextMenuPolicy(Qt.CustomContextMenu)
            child.customContextMenuRequested.connect(
                lambda pos, w=child: self._show_context_menu(w.mapToGlobal(pos)))

    def _show_context_menu(self, global_pos):
        """Menu clic droit du bloc Focus (voir _on_context_menu/
        _connect_context_menu, `global_pos` deja en coordonnees GLOBALES,
        source unique partagee par tous les points d'entree) — voir la
        remarque de tete de classe, "les fichiers et dossiers de focus ne
        fonctionnent pas comme les autres colonnes, notamment pour le
        clic droit" : ce bloc n'avait jusqu'ici AUCUNE interaction clic
        droit, contrairement a une ligne normale (voir Column.
        _on_context_menu). MEME ensemble complet d'actions qu'une ligne
        DOSSIER normale desormais (voir _rename, la remarque de
        l'utilisateur, "je veux que le comportement des colonnes
        fonctionne de la meme maniere sur tous les points") — Renommer +
        Afficher dans l'explorateur + image personnalisee (vignette de
        PROJET, exactement celle affichee ici, voir
        project_thumbnail_pixmap) + Copier/Copier le chemin."""
        path = self._path
        menu = QMenu(self)
        menu.setFont(font(11, 400))
        act_rename = menu.addAction("Renommer") if self._source_column is not None else None
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        menu.addSeparator()
        has_custom = project_thumbnail_path(path).is_file()
        act_change_thumb = menu.addAction("Changer l'image..." if has_custom else "Ajouter un apercu...")
        act_capture_thumb = menu.addAction("Capturer une zone d'ecran...")
        act_reset_thumb = menu.addAction("Reinitialiser l'image") if has_custom else None
        menu.addSeparator()
        act_copy_file = menu.addAction("Copier")
        act_copy_path = menu.addAction("Copier le chemin")
        chosen = menu.exec(global_pos)
        if act_rename is not None and chosen is act_rename:
            self._rename()
        elif chosen is act_reveal:
            reveal_in_file_manager(path)
        elif chosen is act_change_thumb:
            _prompt_change_thumbnail(self, path, self._refresh_thumbnail)
        elif chosen is act_capture_thumb:
            _prompt_capture_thumbnail(self, path, self._refresh_thumbnail)
        elif act_reset_thumb is not None and chosen is act_reset_thumb:
            _prompt_reset_thumbnail(self, path, self._refresh_thumbnail)
        elif chosen is act_copy_file:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(path))

    def _rename(self):
        """Renomme le dossier REPRESENTE PAR LA SELECTION COURANTE de la
        VRAIE colonne source (voir __init__/_source_column) — MEME
        validations que Column._rename_item (caracteres interdits,
        collision de nom, erreur disque), pour un comportement identique
        a une ligne normale. La resynchronisation de la navigation
        (colonnes filles construites depuis l'ANCIEN chemin, redessin du
        bloc Focus lui-meme...) n'est PAS geree ICI a la main : comme pour
        Column._rename_item, on se contente de RAFRAICHIR la vraie
        colonne source puis d'y RESELECTIONNER l'item renomme —
        currentItemChanged declenche alors normalement Column.
        _on_current_changed -> PipelineBrowser.on_selected, qui fait deja
        tout le reste (prune_after + reconstruction, y compris ce bloc
        Focus lui-meme via update_preview_stack) — exactement le meme
        chemin qu'un Renommer sur une ligne normale, aucune duplication de
        logique."""
        column = self._source_column
        if column is None:
            return
        path = self._path
        new_name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", QLineEdit.Normal, path.name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == path.name:
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Renommer", "Le nom contient des caracteres interdits.")
            return
        new_path = path.with_name(new_name)
        if new_path.exists():
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe deja.")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Renommer", f"Impossible de renommer :\n{exc}")
            return
        column.refresh()
        for i in range(column.list.count()):
            it = column.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                column.list.setCurrentItem(it)
                break

    def _refresh_thumbnail(self):
        """Recharge la vignette (voir project_thumbnail_pixmap, cache par
        date de modification — deja invalide des l'ecriture/suppression du
        fichier, voir _prompt_change_thumbnail/_prompt_capture_thumbnail/
        _prompt_reset_thumbnail) apres une modification depuis CE bloc —
        contrairement a une ligne normale (self.list.viewport().update(),
        qui redessine une DELEGATE a partir du modele), ce bloc affiche
        l'image directement dans un widget deja construit, il faut donc
        explicitement lui repasser le nouveau pixmap."""
        self.image.set_source_pixmap(project_thumbnail_pixmap(self._path))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._border_overlay.setGeometry(self.rect())
        self._border_overlay.raise_()


class _RoundedCornersEffect(QGraphicsEffect):
    """Decoupe self.card (fond + TOUS ses enfants, entete/liste compris) a
    la silhouette de son rayon d'angle, AVEC anti-aliasing — remplace
    Column._update_card_mask/QWidget.setMask() : un QRegion est un
    decoupage BINAIRE (pixel dedans/dehors, jamais de demi-teinte), ce qui
    rendait les coins arrondis visiblement crenelés/en escalier — voir la
    remarque de l'utilisateur, capture a l'appui, "les arrondis sont
    degueulasse, ils ne sont pas lisses". Technique standard Qt pour un
    coin arrondi lisse sur un widget composite : peindre le widget (et ses
    enfants) dans un pixmap hors-ecran (sourcePixmap), puis le recomposer
    ICI a travers un QPainterPath arrondi avec Antialiasing actif — la
    MEME geometrie que celle reellement peinte par _ColumnCard.paintEvent
    (_rounded_rect_path), pour rester coherent avec le fond/la bordure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius: dict = {}

    def setRadius(self, radius: dict):
        self._radius = radius
        self.update()

    def draw(self, painter: QPainter):
        """QPainter.setClipPath (1er essai, voir git blame) NE PRODUIT PAS
        d'arrondi vraiment antialiase sur le moteur de rendu RASTER de Qt
        (celui utilise ici, PAS OpenGL) : un clip y retombe sur un masque
        BINAIRE en interne, meme render hint Antialiasing actif — voir la
        remarque de l'utilisateur, comparaison a l'appui (VSCode/Electron,
        qui compose ses coins arrondis via le GPU, PAS ce chemin), "j'ai du
        mal a croire qu'il n'existe pas un autre algorithme... regarde le
        screen, il s'agit de vscode... admet qu'il y a un probleme". Fix :
        construire le masque a la main via un REMPLISSAGE (fillPath, PAS un
        clip — le remplissage, lui, est correctement antialiase par le
        moteur raster) d'un pixmap ARGB transparent, puis composer ce
        pixmap source AU TRAVERS de ce masque via CompositionMode_
        DestinationIn (l'alpha du masque, deja lisse, multiplie celui de
        l'image source) — technique Qt standard pour un decoupage
        VRAIMENT antialiase, contrairement a un simple clip path."""
        offset = QPoint()
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates, offset)
        if pixmap.isNull():
            return
        dpr = pixmap.devicePixelRatio() or 1.0
        w = int(round(pixmap.width() / dpr))
        h = int(round(pixmap.height() / dpr))
        # PAS de marge elargie ici (essaye puis abandonne — voir git blame,
        # "la bordure disparait completement dans l'arrondi") : cette
        # meme classe sert AUSSI a self._content_effect (voir Column.
        # _update_card_mask), dont le rayon (RETRECI, inner_radius) doit
        # rester EXACT — l'elargir laissait l'entete/la liste (coins
        # carres) deborder PAR-DESSUS l'anneau de la bordure exactement
        # dans la courbe, la ou l'entete est peinte SANS son propre rayon
        # (voir column_header_qss, "plus de nibbling... le rognage visuel
        # est deja garanti par ce decoupage") — recouvrant entierement la
        # bordure a cet endroit precis. self._card_effect, lui, n'a de
        # toute facon plus besoin d'etre actif des qu'une bordure existe
        # (voir _update_card_mask, setEnabled) : plus rien ici a compenser
        # par une marge.
        path = _rounded_rect_path(QRect(0, 0, w, h), self._radius)
        # Masque construit a la main dans un pixmap SEPARE (REMPLISSAGE
        # antialiase dans un pixmap transparent DEDIE), PAS un fillPath
        # DIRECT sur `masked` en mode DestinationIn — MEME correctif/MEME
        # raison que _paint_row_image/_SquarePreviewImage._refresh (voir
        # leurs docstrings) : un fillPath direct dans ce mode ne compose
        # que les pixels que le CHEMIN touche reellement, laissant les
        # coins (hors chemin) intacts/opaques des que RIEN d'autre ne les
        # recouvre par-dessus (typiquement une bordure, qui masquait ce
        # defaut jusqu'ici) — exactement le bug signale par l'utilisateur,
        # "quand on n'a pas d'entete ... les coins arrondis doivent etre
        # present" (sans bordure ni entete pour le camoufler). Un mask
        # PIXMAP intermediaire, lui, couvre le rectangle ENTIER (drawPixmap
        # touche tous les pixels), donc les coins y redeviennent bien
        # transparents.
        mask = QPixmap(pixmap.size())
        mask.setDevicePixelRatio(dpr)
        mask.fill(Qt.transparent)
        mkp = QPainter(mask)
        mkp.setRenderHint(QPainter.Antialiasing, True)
        mkp.setPen(Qt.NoPen)
        mkp.setBrush(Qt.white)
        mkp.drawPath(path)
        mkp.end()

        masked = QPixmap(pixmap.size())
        masked.setDevicePixelRatio(dpr)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.drawPixmap(0, 0, pixmap)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()
        painter.drawPixmap(offset, masked)


class _ColumnCard(QWidget):
    """Porte le fond/la bordure REELS d'une colonne (voir Column.card) —
    peinte a la main (QPainter, _paint_bordered_rect, MEME technique que
    settings_window._ColumnPreview) plutot que via border-radius QSS : la
    QSS et le masque de decoupe des enfants (voir Column._update_card_mask)
    utilisaient chacun leur PROPRE geometrie de coin arrondi (le moteur de
    style de Qt d'un cote, un chemin arrondi maison de l'autre), jamais
    parfaitement identiques — la bordure ne "enveloppait" alors pas
    exactement le masque — voir la remarque de l'utilisateur, capture a
    l'appui, "le cadre n'enveloppe pas les bordures radius". Peindre ICI
    avec la MEME fonction (_rounded_rect_path, via _paint_bordered_rect)
    que celle qui calcule le masque garantit desormais une geometrie
    identique au pixel pres."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = "#000000"
        self._radius: dict = {}
        self._enabled: dict = {}
        self._colors: dict = {}
        self._thickness = 1

    def setFrameStyle(self, bg: str, radius: dict, enabled: dict, colors: dict, thickness: int):
        self._bg, self._radius, self._enabled, self._colors, self._thickness = bg, radius, enabled, colors, thickness
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, _radius_any(self._radius))
        _paint_bordered_rect(p, self.rect(), self._radius, self._enabled, self._thickness, self._colors, self._bg)
        p.end()


def _widget_containing_layout(widget: QWidget):
    """Layout REEL contenant directement `widget` (voir Column.
    _suppress_left, docstring d'origine pour le detail du piege) —
    factorisee ici pour etre PARTAGEE avec PreviewColumn, qui a exactement
    le meme besoin de detection de voisin de gauche dans columns_layout."""
    parent = widget.parentWidget()
    if parent is None or parent.layout() is None:
        return None

    def search(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is widget:
                return layout
            sub_layout = item.layout()
            if sub_layout is not None:
                found = search(sub_layout)
                if found is not None:
                    return found
        return None

    return search(parent.layout())


def _column_suppress_left(widget: QWidget, title: str) -> bool:
    """`widget` (une colonne "reelle" OU fantome — Column/PreviewColumn,
    toutes deux membres de columns_layout) a-t-elle une AUTRE colonne
    immediatement a sa gauche ET les 2 cartes se touchent VRAIMENT (aucun
    espace de layout — voir column_gap — ET aucun padding sur le cote qui
    les separe, voir column_padding_for) ? MEME regle que settings_window.
    _ColumnPreview (has_left_neighbor) — un SEUL filet reste visible a la
    frontiere entre 2 colonnes collees (celui de DROITE de celle de
    gauche) plutot que 2 cumules — voir la remarque de l'utilisateur, "je
    veux que les deux bordures qui se chevauchent n'en forment qu'une
    seule". Factorisee ici (auparavant seulement Column._suppress_left) :
    PreviewColumn en a desormais besoin aussi (voir la remarque de
    l'utilisateur, "formate les comme toutes les autres colonnes")."""
    parent_layout = _widget_containing_layout(widget)
    if parent_layout is None:
        return False
    idx = parent_layout.indexOf(widget)
    if idx <= 0 or column_gap() > 0:
        return False
    if column_padding_for(title)["left"] > 0:
        return False
    prev_item = parent_layout.itemAt(idx - 1)
    prev_widget = prev_item.widget() if prev_item is not None else None
    prev_title = getattr(prev_widget, "column_title", None)
    if prev_title is not None and column_padding_for(prev_title)["right"] > 0:
        return False
    return True


# ==========================================================================
# Colonne
# ==========================================================================

class Column(QWidget):

    selected = Signal(object, object)   # (Column, Path | None)
    activated = Signal(object)          # Path

    def __init__(self, directory: Path, title: str, parent=None,
                 source_dirs: list[Path] | None = None, display_title: str | None = None,
                 style_title: str | None = None,
                 user_width: int | None = None, on_resize=None,
                 group_kind: str | None = None, on_reorder=None,
                 user_height: int | None = None, on_height_resize=None, fill_height: bool = False,
                 on_height_resize_begin=None, on_height_resize_end=None,
                 source_labels: list[str] | None = None,
                 is_focus_level: bool | None = None,
                 show_dirs: bool = True, show_files: bool = True,
                 omit_dirs: frozenset = frozenset(), omit_files: frozenset = frozenset(),
                 only_recognized_software: bool = False,
                 on_group_maximize=None, on_group_equalize=None):
        super().__init__(parent)
        self.directory = directory
        # Filtre "que des repertoires logiciel reconnus" (voir refresh()) —
        # remplace un test litteral `group_kind == "logiciels"` : un simple
        # booleen explicite, sans rapport avec l'identite group_kind (voir
        # la remarque de l'utilisateur, "base toi sur les colonnes creees
        # avant les focus" — group_kind ne pilote plus que le
        # reordonnancement/redimensionnement partage entre colonnes voisines,
        # jamais le contenu affiche).
        self._only_recognized_software = only_recognized_software
        # Hauteur de ligne PROPRE a ce dossier (voir load_layout_settings/
        # row_resize_begin/update/end, Colonnes.effective_row_height) —
        # SEULEMENT pour une colonne de navigation REELLE (group_kind=None,
        # PAS une colonne fantome du groupe IN/OVER/OUT/LOGICIELS, dont
        # `directory` n'est qu'un repli parmi plusieurs sources fusionnees,
        # voir source_dirs) : Ctrl+glisser sur une TELLE colonne enregistre
        # desormais la hauteur choisie DANS ce dossier (fichier cache
        # .pipeline_layout.json), pas dans un reglage GLOBAL partage entre
        # TOUTES les colonnes du meme style — voir la remarque de
        # l'utilisateur, "le dimensionnement en hauteur ... doit etre
        # enregistre en temps reel et ce dependant du [sous-]dossier ...
        # jamais les mm suivant le sous dossier precedent". None (repli) :
        # aucun reglage propre a ce dossier, suit la valeur GENERALE (voir
        # effective_row_height) — comportement INCHANGE tant qu'aucun
        # dossier n'a encore ete ajuste a la main.
        # Punaise d'en-tete (voir _toggle_pin/refresh_header, la remarque de
        # l'utilisateur, "punaise_02.png lorsque l'on clique dessus, les
        # valeurs de dimensions de colonnes et de lignes sont alors
        # overridees par les valeurs du json ... lorsque l'on rappuie ...
        # prend en compte les valeurs par defaut des settings") : couche
        # ADDITIVE et PRIORITAIRE sur tout le reste (largeur/hauteur
        # "normales" ci-dessus/generales) — cles DEDIEES (pinned*, jamais
        # les memes que row_height/_user_width) pour ne RIEN changer au
        # comportement existant tant que la punaise n'a jamais ete
        # activee sur ce dossier precis. CALCULEE AVANT _folder_row_height
        # ci-dessous (voir sa remarque) : la lecture de "row_height" en
        # depend desormais.
        layout_data = load_layout_settings(directory)
        self._pin_active = bool(layout_data.get("pinned", False))
        self._pin_column_width = layout_data.get("pinned_column_width") if self._pin_active else None
        self._pin_row_height = layout_data.get("pinned_row_height") if self._pin_active else None

        self._folder_row_height: int | None = None
        # Ne charge "row_height" QUE si la punaise est active — voir
        # row_resize_end, qui n'ecrit desormais PLUS cette cle du tout hors
        # punaise (seules Type/Focus s'auto-enregistrent, ailleurs). Sans ce
        # garde-fou, une valeur ECRITE AVANT ce changement (ancien
        # comportement : toute colonne auto-enregistrait sans punaise)
        # restait lue indefiniment ici, ce qui affichait une hauteur figee
        # (ex. 80px, le plafond ROW_RESIZE_MAX_HEIGHT) sans rapport avec le
        # reglage general — voir la remarque de l'utilisateur, "certaines
        # de mes colonnes affichent des hauteurs de ligne a 80px et je ne
        # comprends pas d'ou vient cette valeur".
        if self._pin_active:
            raw_height = layout_data.get("row_height")
            if isinstance(raw_height, (int, float)):
                self._folder_row_height = int(raw_height)

        # Menu contextuel "Afficher l'apercu"/"Afficher l'icone"/"Taille de
        # l'icone" (voir _on_context_menu) : None (repli) = valeur GENERALE
        # des reglages (comportement INCHANGE) ; MEME regle de persistance
        # que la hauteur/largeur de ligne ci-dessus — n'est charge que si
        # la punaise est active, SAUF "Type" (jamais de punaise, mais
        # auto-enregistre quand meme, voir _should_autosave_context_
        # override) — voir la remarque de l'utilisateur, "tous les
        # parametres du menu contextuel ne s'enregistrent pas
        # automatiquement dans la colonne de type".
        self._show_icon_override: bool | None = None
        self._show_preview_override: bool | None = None
        self._icon_size_override: int | None = None
        self._icon_padding_left_override: int | None = None
        self._text_padding_left_override: int | None = None
        _style_title_for_gate = style_title if style_title is not None else title
        if self._pin_active or _style_title_for_gate == "Type":
            if isinstance(layout_data.get("show_icon"), bool):
                self._show_icon_override = layout_data["show_icon"]
            if isinstance(layout_data.get("show_preview"), bool):
                self._show_preview_override = layout_data["show_preview"]
            raw_icon_size = layout_data.get("icon_size")
            if isinstance(raw_icon_size, (int, float)):
                self._icon_size_override = int(raw_icon_size)
            raw_icon_pad = layout_data.get("icon_padding_left")
            if isinstance(raw_icon_pad, (int, float)):
                self._icon_padding_left_override = int(raw_icon_pad)
            raw_text_pad = layout_data.get("text_padding_left")
            if isinstance(raw_text_pad, (int, float)):
                self._text_padding_left_override = int(raw_text_pad)
        # `source_dirs` (voir IN/OVER/OUT, PipelineBrowser.update_preview_
        # stack) : colonne dont le contenu est le MERGE de plusieurs
        # dossiers sources (ex. le "in" du Projet ET celui du Sous-projet
        # selectionnes) au lieu d'un dossier unique — voir refresh(), qui
        # bascule sur ce chemin quand source_dirs n'est pas None. `directory`
        # reste le repli utilise pour les operations a CIBLE unique (nouveau
        # dossier, deplacement par glisser-deposer) — voir leurs remarques
        # respectives. `source_labels` (meme longueur/ordre que source_dirs,
        # optionnel) : annotation "(projet)"/"(<nom du sous-projet>)" a
        # afficher a cote du nom de chaque entree venant de CETTE source
        # (voir ROLE_SOURCE_LABEL/refresh/_paint_unified_row) — voir la
        # remarque de l'utilisateur, "je veux une anotation a cote du nom du
        # repertoire ... s'il vient de projet ou de sous projet".
        self._source_dirs = source_dirs
        self._source_labels = source_labels
        # `user_width`/`on_resize` (voir PreviewColumn, MEME convention) :
        # pour une colonne RECONSTRUITE entierement a chaque navigation (le
        # groupe IN/OVER/OUT/LOGICIELS, voir PipelineBrowser.
        # update_preview_stack/_on_group_column_resized) — sans ce relais,
        # tout glisser de bordure serait perdu des le clic suivant, et les 4
        # colonnes du groupe ne resteraient pas alignees a la meme largeur
        # entre elles (voir la remarque de l'utilisateur, "les 4 colonnes
        # doivent avoir la meme largeur constamment"). None/None pour une
        # colonne NORMALE (comportement INCHANGE : `self._user_width` geree
        # localement par resize_update, voir sa remarque).
        self._user_width = user_width
        self._on_resize = on_resize
        # `group_kind`/`on_reorder` : active le glisser-deposer de l'ENTETE
        # (pas le contenu de la liste, deja pris par FileListWidget) pour
        # interchanger la place de cette colonne avec une AUTRE colonne du
        # MEME groupe (voir PipelineBrowser.update_preview_stack/
        # _on_group_reorder, eventFilter plus bas) — voir la remarque de
        # l'utilisateur, "possible de pouvoir glisser deposer ces colonnes
        # afin de pouvoir interchanger leur place ?". None pour une colonne
        # NORMALE (pas de glisser d'en-tete du tout).
        self._group_kind = group_kind
        self._on_reorder = on_reorder
        # Boutons d'entete "Agrandir"/"Egaliser" (voir __init__ plus bas,
        # dans header_layout) — SEULEMENT pour une colonne du groupe
        # IN/OVER/OUT/LOGICIELS (group_kind is not None) : voir la remarque
        # de l'utilisateur, "dans les 4 colonnes ... je veux dans l'entete
        # un bouton qui me permette d'agrandir au maximum la fenetre en
        # cours et de minimiser les autres ... je veux un autre bouton pour
        # mettre les 4 colonnes a exactement la meme hauteur". Column ne
        # connait que SES PROPRES voisines via ces callbacks (MEME
        # principe que on_reorder/on_height_resize) — PipelineBrowser seule
        # a acces aux 4 colonnes du groupe a la fois.
        self._on_group_maximize = on_group_maximize
        self._on_group_equalize = on_group_equalize
        # `user_height`/`on_height_resize(_begin/_end)` : glisser le bord
        # BAS de CETTE colonne ne fait bouger qu'ELLE ET sa voisine
        # IMMEDIATEMENT SUIVANTE (voir PipelineBrowser.
        # _on_group_height_resize_begin/_on_group_height_resized, "vraie"
        # poignee de scission entre les 2 colonnes de part et d'autre) —
        # JAMAIS les autres, qui ne bougent ni de taille ni de position —
        # voir la remarque de l'utilisateur, "seulement deux colonnes
        # peuvent etre dimensionnees en hauteur ... les deux colonnes
        # concernees doivent etre seulement les deux colonnes de part et
        # d'autre de la zone de selection pour le slide". Column ne calcule
        # PAS la nouvelle hauteur elle-meme : elle transmet le DELTA brut
        # (voir height_resize_update), PipelineBrowser connait seule les 2
        # voisines et leurs hauteurs de depart pour repartir l'espace entre
        # elles sans toucher au reste. `fill_height` (voir
        # set_group_fill_height) : SEULE la DERNIERE colonne de l'ordre
        # courant (voir PipelineBrowser._group_column_order) l'a a True —
        # pas de hauteur fixe pour elle, reste etiree jusqu'en bas comme une
        # colonne normale, ni poignee de redimensionnement — voir la
        # remarque de l'utilisateur, "il est important que la derniere
        # colonne aille bien jusqu'en bas de la page".
        self._group_user_height = user_height
        self._on_height_resize = on_height_resize
        self._on_height_resize_begin = on_height_resize_begin
        self._on_height_resize_end = on_height_resize_end
        self._group_fill_height = fill_height
        self._group_height_resizing = False
        self._group_height_resize_start_y = 0
        self._group_height_resize_start_height = 0
        self._group_drag_start: QPoint | None = None
        # Fenetre "fantome" (voir _make_group_drag_ghost) affichee pendant
        # le glisser d'un en-tete du groupe, et decalage curseur/coin
        # superieur gauche fixe une fois pour toutes au demarrage du glisser
        # (voir eventFilter) : la ghost doit suivre le curseur au MEME point
        # relatif ou l'utilisateur a saisi la colonne, pas se recaler au
        # coin a chaque mouvement.
        self._group_ghost: QWidget | None = None
        self._group_ghost_offset = QPoint()
        self.is_active = False
        self.column_title = title
        # `display_title` (voir PreviewColumn, meme convention) : texte
        # d'entete affiche, SEPARE de `title`/self.column_title (la cle de
        # STYLE/COLUMN_SETTINGS par defaut) — permet a IN/OVER/OUT de
        # partager le style "Type" (liste plate, sans vignette ni icone
        # logiciel) tout en affichant leur propre libelle.
        # `style_title` (nouveau, voir PipelineBrowser.on_selected chaine
        # CONFIGUREE/settings_window "INTERMEDIAIRE") : repli symetrique a
        # `display_title`, mais pour la cle de STYLE cette fois — un niveau
        # de chaine CONFIGUREE (nom quelconque choisi par l'utilisateur, ex.
        # "test1") garde `column_title`/`display_title` = son propre nom
        # (identite/annotations "(test1)", voir update_preview_stack), MAIS
        # `style_title` = "Sous-projet" pour suivre le MEME reglage que
        # l'onglet General > Colonnes > INTERMEDIAIRE (voir la remarque de
        # l'utilisateur, "le tab sous projets doit maintenant se nommer
        # 'INTERMEDIAIRE', et doit controler toutes les colonnes entre celle
        # de projet et focus") plutot que de retomber sur le bucket
        # generique "Contenu" (voir _col_key) comme n'importe quel titre
        # inconnu. None (repli, TOUTE colonne EXISTANTE avant ce reglage —
        # Type/Projets/Sous-projet legacy/Logiciels/Contenu/groupe) : MEME
        # valeur que `title`, comportement rigoureusement INCHANGE.
        self.style_title = style_title if style_title is not None else title
        self.has_thumbnails = title in THUMBNAIL_COLUMN_LABELS
        # `is_focus_level` (voir update_preview_stack, group_columns du
        # groupe IN/OVER/OUT/LOGICIELS) : participation a la pile Focus,
        # DECOUPLEE de `has_thumbnails` (qui pilote le RENDU — tuile a
        # vignette vs liste plate) — un niveau de la chaine CONFIGUREE (voir
        # PipelineBrowser.on_selected/load_project_columns) peut etre en
        # liste plate ET quand meme contribuer a la pile Focus (son propre
        # toggle "Focus", voir ColumnConfigDialog). None (repli, colonnes
        # "normales" Type/Projets/Sous-projet/Logiciels/Contenu) : MEME
        # valeur que has_thumbnails — comportement D'AVANT ce reglage
        # INCHANGE (seules Projets/Sous-projet participaient a la pile) —
        # voir la remarque de l'utilisateur, "le toggle focus [est]
        # independant par colonne".
        self.is_focus_level = self.has_thumbnails if is_focus_level is None else is_focus_level
        # `show_dirs`/`show_files`/`omit_dirs`/`omit_files` (voir refresh(),
        # ColumnConfigDialog) : filtres de CONTENU d'un niveau de la chaine
        # CONFIGUREE — True/True/vide (comportement INCHANGE, tout est
        # affiche) pour toute colonne NORMALE.
        self._show_dirs = show_dirs
        self._show_files = show_files
        self._omit_dirs = {n.lower() for n in omit_dirs}
        self._omit_files = {n.lower() for n in omit_files}
        # Repli/depli (voir set_collapsed) : toute colonne de navigation
        # NORMALE (group_kind=None — Type/Projets/tout niveau configure,
        # PAS une colonne fantome du groupe IN/OVER/OUT/LOGICIELS) est
        # structurellement repliable — c'est PipelineBrowser.
        # _apply_project_columns_collapsed qui decide LESQUELLES replier
        # (les N premieres de self.columns, voir _chain_expected_total),
        # pas un titre fixe (voir la remarque de l'utilisateur, "toutes les
        # colonnes avant les colonnes de focus", N quelconque).
        self.collapsible = group_kind is None
        self.collapsed = False
        self._expanded_width = None
        self._width_anim = None

        self.title_label = QLabel(display_title or title)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")

        # objectName + selecteur ID : voir la remarque sur #TitleBar dans
        # PipelineBrowser — sans lui, title_label heriterait du border-
        # bottom nu et se retrouverait souligne sur sa largeur de texte au
        # lieu du filet courant sur toute la colonne.
        #
        # header (exterieur, hauteur fixe, JAMAIS stylise) enveloppe
        # header_fill (interieur, c'est LUI qui porte le fond/rayon/cadre de
        # header_qss) avec une marge = HEADER_PADDING sur les 4 cotes : le
        # padding regle "l'espace entre le fond colore et les bords de la
        # colonne" (voir Parametres > Entetes), PAS la marge du texte a
        # l'interieur du fond (qui reste fixe, voir header_fill_layout
        # ci-dessous) — a ne pas confondre, voir la remarque de
        # l'utilisateur qui a precise ce point.
        header = QWidget()
        header.setObjectName("ColumnHeaderOuter")
        header.setFixedHeight(scaled(HEADER_HEIGHT))
        self.header = header
        header_outer_layout = QVBoxLayout(header)
        # minimum=0 (voir la docstring de scaled) : un padding regle a 0 doit
        # rester 0, pas remonter a 1px apres arrondi.
        header_outer_layout.setContentsMargins(scaled(HEADER_PADDING, 0), scaled(HEADER_PADDING, 0),
                                                scaled(HEADER_PADDING, 0), scaled(HEADER_PADDING, 0))
        header_outer_layout.setSpacing(0)

        header_fill = QWidget()
        header_fill.setObjectName("ColumnHeader")
        header_fill.setStyleSheet(header_qss("ColumnHeader"))
        self.header_fill = header_fill
        header_layout = QHBoxLayout(header_fill)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        # "Agrandir"/"Egaliser" (voir __init__, on_group_maximize/
        # on_group_equalize) : SEULEMENT sur une colonne du groupe
        # IN/OVER/OUT/LOGICIELS — voir la remarque de l'utilisateur, "dans
        # les 4 colonnes ... un bouton qui me permette d'agrandir au
        # maximum ... et un autre bouton pour mettre les 4 colonnes a
        # exactement la meme hauteur". Boutons TEXTE (pas d'icone dediee
        # existante) — meme taille/meme style transparent que la punaise.
        if self._group_kind is not None:
            def _group_header_btn(text: str, tooltip: str, handler) -> QPushButton:
                btn = QPushButton(text)
                btn.setFlat(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFocusPolicy(Qt.NoFocus)
                btn.setFixedSize(18, 18)
                btn.setFont(font(11, 700))
                btn.setToolTip(tooltip)
                btn.setStyleSheet(
                    "QPushButton { background: transparent; border: none; padding: 0; "
                    f"color: {C['label']}; }}"
                    "QPushButton:hover { background: rgba(255,255,255,0.12); border-radius: 3px; "
                    f"color: {C['text']}; }}"
                )
                btn.clicked.connect(handler)
                header_layout.addWidget(btn)
                return btn

            if on_group_maximize is not None:
                _group_header_btn(
                    "⤢", "Agrandir cette colonne au maximum, reduire les autres a leur contenu",
                    lambda: on_group_maximize(self._group_kind))
            if on_group_equalize is not None:
                _group_header_btn(
                    "≡", "Repartir les 4 colonnes du groupe a hauteur egale",
                    lambda: on_group_equalize())
        # Punaise (voir _toggle_pin/_pin_icon_pixmap) : sur TOUTE colonne
        # SAUF "Type" et les colonnes Focus (celles-ci ne passent jamais
        # par Column, voir PreviewColumn/_PreviewBlock — exclusion donc
        # automatique, aucune condition a poser ici pour elles) — voir la
        # remarque de l'utilisateur, "je viens de te coller deux icones
        # que j'aimerai que tu places en haut a droite de chaque colonne
        # sauf : colonne type, colonnes focus".
        self._pin_btn = None
        if title != "Type":
            pin_btn = QPushButton()
            pin_btn.setFlat(True)
            pin_btn.setCursor(Qt.PointingHandCursor)
            pin_btn.setFocusPolicy(Qt.NoFocus)
            pin_btn.setFixedSize(18, 18)
            pin_btn.setIconSize(QSize(14, 14))
            pin_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 0; }"
                "QPushButton:hover { background: rgba(255,255,255,0.12); border-radius: 3px; }"
            )
            pin_btn.setToolTip("Fige la largeur/hauteur de ligne de ce dossier (voir Parametres)")
            pin_btn.clicked.connect(self._toggle_pin)
            self._pin_btn = pin_btn
            header_layout.addWidget(pin_btn)
        self._refresh_pin_icon()
        header_outer_layout.addWidget(header_fill)

        self.list = FileListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        # Uniforme seulement pour les colonnes a vignettes (toutes les lignes
        # font PROJECT_ROW_HEIGHT) : dans les colonnes classiques, un fichier
        # image peut desormais prendre une hauteur differente des autres
        # lignes (voir RowDelegate), donc les hauteurs n'y sont plus uniformes.
        self.list.setUniformItemSizes(self.has_thumbnails)
        # L'espacement entre lignes est gere a la main dans les delegates
        # (voir ROW_SPACING) plutot que via QListView.setSpacing(), qui
        # ajoute la valeur des DEUX cotes de chaque ligne (donc un ecart reel
        # de 2x la valeur demandee, et jamais de valeur impaire exacte).
        self.list.setSpacing(0)
        self.list.setItemDelegate(ProjectTileDelegate(self) if self.has_thumbnails else RowDelegate(self))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setViewportMargins(0, 0, 0, 0)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.customContextMenuRequested.connect(self._on_context_menu)

        # self.card : porte le fond/la bordure/le rayon REELS de la colonne
        # (voir refresh_colors/app_style.column_frame_qss) — self, lui, ne
        # sert plus qu'a reserver l'EMPLACEMENT plein (largeur allouee,
        # cible du redimensionnement a la souris) et a inserer ce card en
        # retrait de Padding px sur chaque cote (voir refresh_header/
        # app_style.column_padding_for) : une "carte flottante" qui peut
        # RETRECIR sans deplacer la frontiere de redimensionnement ni les
        # colonnes voisines — voir la remarque de l'utilisateur, "je veux
        # que le fond de la colonne se replie ... pour toutes les colonnes
        # de l'appli".
        self.card = _ColumnCard()
        self.card.setObjectName("ColumnCard")
        # Voir _RoundedCornersEffect : remplace setMask() (crenele, voir la
        # remarque de l'utilisateur "les arrondis sont degueulasse, ils ne
        # sont pas lisses") par un decoupage anti-aliase.
        self._card_effect = _RoundedCornersEffect(self.card)
        self.card.setGraphicsEffect(self._card_effect)

        # self._content : porte l'entete/la liste, en retrait de la bordure
        # (voir refresh_header, reserve()) DANS self.card — separe de
        # self.card pour lui appliquer son PROPRE decoupage arrondi (voir
        # self._content_effect ci-dessous, rayon RETRECI de l'epaisseur de
        # bordure, _radius_shrink, meme calcul que le clip du FOND dans
        # _paint_bordered_rect) : une simple marge DROITE/UNIFORME (voir
        # reserve()) ne degage assez de place que le long des segments
        # DROITS du cadre — a un COIN arrondi, l'anneau de la bordure
        # plonge plus profondement vers le centre (jusqu'a `radius` px en
        # diagonale) que cette marge (juste `thickness` px) ne le prevoit,
        # laissant l'entete/la liste recouvrir le trace courbe de la
        # bordure a chaque coin — voir la remarque de l'utilisateur,
        # capture a l'appui, "il n'y a toujours pas de bordure dans les
        # angles".
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_effect = _RoundedCornersEffect(self._content)
        self._content.setGraphicsEffect(self._content_effect)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(header)
        # Espace REGLABLE entre l'entete et le 1er item de la liste (voir
        # Colonnes > Texte > "Espace avant le premier item"/refresh_header,
        # qui pilote sa hauteur) — voir la remarque de l'utilisateur,
        # "ajoute un slider qui cree un espace entre l'entete et le
        # premier item de la liste". Widget dedie (PAS un simple padding
        # sur le TOP de la liste elle-meme) : un padding QListWidget
        # colorerait cet espace comme le fond de la liste (C['void']),
        # pas comme celui, distinct, de la colonne SOUS l'entete — voir la
        # meme remarque que column_frame_qss pour ce fond.
        self.header_gap_spacer = QWidget()
        self.header_gap_spacer.setStyleSheet("background: transparent;")
        self.header_gap_spacer.setFixedHeight(0)
        content_layout.addWidget(self.header_gap_spacer)
        content_layout.addWidget(self.list, 1)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(0, 0, 1, 0)   # voir refresh_header, qui l'ajuste a l'epaisseur de bordure
        layout.setSpacing(0)
        layout.addWidget(self._content)
        self._column_layout = layout

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, qui l'ajuste a Padding
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.card)
        self._outer_layout = outer_layout

        self.setFixedWidth(self._pin_column_width or self._user_width or col_width(title))
        # Hauteur FIXE (voir GROUP_COLUMN_DEFAULT_HEIGHT) SEULEMENT pour une
        # colonne du groupe IN/OVER/OUT/LOGICIELS QUI N'EST PAS la derniere
        # de l'ordre courant (voir fill_height/set_group_fill_height) : une
        # colonne NORMALE (fill_height=False ET group_kind=None) n'appelle
        # jamais setFixedHeight, elle reste etiree sur toute la hauteur
        # disponible par columns_layout (comportement INCHANGE).
        if self._group_kind is not None and not fill_height:
            self.setFixedHeight(self._group_user_height or GROUP_COLUMN_DEFAULT_HEIGHT)
        self.setObjectName("Column")
        # Transparent EXPLICITE (self ne peint plus rien lui-meme desormais,
        # voir self.card ci-dessus) : sans lui, ce QWidget nu heriterait du
        # fond OPAQUE par defaut de la feuille de style globale, masquant le
        # fond de #ColumnsHost (voir PipelineBrowser.refresh_colors) la ou
        # Padding fait justement RETRECIR self.card en dessous de la pleine
        # largeur/hauteur de self.
        self.setStyleSheet("#Column { background: transparent; }")

        # Redimensionnement par glisser-deposer sur la bordure droite.
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        # Redimensionnement de la HAUTEUR des lignes : Ctrl + clic entre 2
        # lignes + glisser (voir row_resize_begin/_in_row_resize_zone) —
        # voir la remarque de l'utilisateur, "je veux pouvoir redimensionner
        # la hauteur des lignes directement dans l'interface ... appuyer sur
        # la touche controle du clavier et cliquer entre deux lignes et
        # glisser".
        self._row_resizing = False
        self._row_resize_start_y = 0
        self._row_resize_start_height = 0
        self._row_resize_row_index = -1
        # Limite doItemsLayout() (recalcule le sizeHint() de CHAQUE ligne,
        # pas un simple repaint) a ~60/s pendant un glisser (largeur OU
        # hauteur de ligne) : sans ca, il se rejoue a CHAQUE evenement
        # MouseMove brut, potentiellement bien plus de 60/s sur une souris a
        # haut taux de rafraichissement — voir la remarque de l'utilisateur,
        # "il y a des ralentissements dans les animations, optimise un
        # maximum". Front montant (1er mouvement applique tout de suite) +
        # purge finale (_flush_layout_throttle, pour ne jamais rater le tout
        # dernier mouvement avant le prochain palier).
        self._layout_throttle_timer = QTimer(self)
        self._layout_throttle_timer.setSingleShot(True)
        self._layout_throttle_timer.setInterval(16)
        self._layout_throttle_timer.timeout.connect(self._flush_layout_throttle)
        self._layout_pending = False
        self.setMouseTracking(True)
        header.setMouseTracking(True)
        header.installEventFilter(self)
        # `_group_header_widgets` : header_fill (fond/rayon, voir plus haut)
        # ET les 2 labels COUVRENT ENTIEREMENT header (header_fill occupe
        # tout header, moins juste le Padding d'entete, souvent 0) — sans
        # installer AUSSI le filtre sur eux, la souris ne touche quasiment
        # JAMAIS `header` lui-meme (seulement l'etroite marge de Padding, si
        # non nulle) : le glisser d'un en-tete du groupe IN/OVER/OUT/
        # LOGICIELS ne demarrait alors QUE par hasard, selon le pixel exact
        # survole — voir la remarque de l'utilisateur, "le changement ne
        # fonctionne pas tout le temps, il est des fois impossible de faire
        # le changement" — MEME piege/MEME correctif que PreviewColumn.
        # install_resize_filter pour la bordure de redimensionnement.
        # Assigne AVANT installEventFilter() : celui-ci peut redeclencher
        # eventFilter() de maniere SYNCHRONE (evenements internes Qt) avant
        # meme la fin de cette boucle — sans l'attribut deja pose, ce 1er
        # appel plantait avec AttributeError (_group_header_widgets
        # manquant).
        if self._group_kind is not None:
            self._group_header_widgets = (header, header_fill, self.title_label)
            for w in self._group_header_widgets:
                w.setMouseTracking(True)
                w.installEventFilter(self)
        else:
            self._group_header_widgets = ()
        self.list.viewport().installEventFilter(self)
        # La scrollbar verticale est un widget a part, positionne PAR-DESSUS
        # le bord droit du viewport des que la liste deborde : sans son
        # propre eventFilter, ses clics/mouvements ne passaient jamais par
        # _in_resize_zone, rendant la bordure de redimensionnement
        # inaccessible chaque fois qu'une scrollbar est visible.
        self.list.verticalScrollBar().installEventFilter(self)

        # Rejoue immediatement le style au-dessus (header_fill/le cadre de
        # cette colonne, tous 2 fixes en dur juste plus haut) : necessaire
        # pour cette colonne, dont le style EFFECTIF (general ou surcharge,
        # voir app_style.column_style_for) peut deja differer du style
        # partage par les autres colonnes des la construction.
        self.refresh_header()
        self.refresh_colors()

        self.refresh()

    def set_active(self, active: bool):
        if self.is_active != active:
            self.is_active = active
            self.list.viewport().update()

    def set_collapsed(self, collapsed: bool, animate: bool = True):
        """Replie entierement la colonne (largeur animee jusqu'a 0, voir
        _animate_width) ou la redeploie a sa largeur precedente. Ignore
        silencieusement les colonnes non repliables (voir `collapsible`,
        pose a la construction) : PipelineBrowser peut appeler ceci sur
        toutes ses colonnes sans avoir a filtrer lui-meme — pilote par
        l'icone unique de la colonne des vignettes (voir
        PipelineBrowser._toggle_project_columns), pas par une icone propre
        a chaque colonne."""
        if not self.collapsible or self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        if collapsed:
            self._expanded_width = self.width()
            target = 0
        else:
            target = self._expanded_width or self._pin_column_width or self._user_width or col_width(self.style_title)
        if animate:
            self._animate_width(target)
        else:
            self.setFixedWidth(target)

    def _animate_width(self, target_width: int, duration: int = 220):
        """Anime la largeur (minimumWidth/maximumWidth, les deux proprietes
        que setFixedWidth pose habituellement d'un coup) de la largeur
        actuelle vers `target_width`. Les deux animations tournent en
        parallele pour ne jamais laisser min > max (ou inversement) pendant
        la transition, ce qui ferait clignoter/planter la mise en page."""
        if getattr(self, "_width_anim", None) is not None:
            self._width_anim.stop()
        start_width = self.width()
        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self, prop)
            anim.setDuration(duration)
            anim.setStartValue(start_width)
            anim.setEndValue(target_width)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)
        # Garder la reference : sans elle, le GC Python peut detruire le
        # groupe avant la fin de l'animation (Qt ne la garde pas vivante a
        # notre place ici, contrairement a un parent QObject classique).
        self._width_anim = group
        group.start()

    def refresh_all(self):
        """Rafraichit toutes les colonnes de la fenetre (utilise apres un
        glisser-deposer, qui peut affecter la colonne source ET la cible)."""
        win = self.window()
        if hasattr(win, "refresh_all_columns"):
            win.refresh_all_columns()
        else:
            self.refresh()

    def _in_resize_zone(self, x: int) -> bool:
        # Une colonne repliee (largeur nulle, voir set_collapsed) ne se
        # redimensionne pas a la main. columns_resizable() : Fenetre de
        # parametres > Tableaux > Colonnes dimensionnables (voir
        # app_style.set_columns_resizable) — desactive, ni le curseur ni le
        # glisser ne s'activent plus sur cette bordure.
        if self.collapsed or not columns_resizable():
            return False
        return self.width() - COLUMN_RESIZE_MARGIN <= x <= self.width()

    @property
    def is_resizing(self) -> bool:
        return self._resizing

    def resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        _show_resize_width(self, self.width())

    def _throttled_layout(self):
        """Voir le commentaire pres de _layout_throttle_timer (__init__) —
        appelle doItemsLayout() tout de suite si aucun appel n'est deja "en
        vol" dans les 16ms courantes, sinon note juste qu'un rattrapage
        sera necessaire (_flush_layout_throttle, au timeout)."""
        if self._layout_throttle_timer.isActive():
            self._layout_pending = True
            return
        self.list.doItemsLayout()
        self._layout_throttle_timer.start()

    def _flush_layout_throttle(self):
        if self._layout_pending:
            self._layout_pending = False
            self.list.doItemsLayout()

    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self._user_width = new_width
        self.setFixedWidth(new_width)
        self._throttled_layout()
        self._update_card_mask()   # voir sa docstring — self.card change de largeur ici aussi
        if self._on_resize is not None:
            self._on_resize(new_width)
        _show_resize_width(self, new_width)

    def resize_end(self):
        self._resizing = False
        _hide_resize_width(self)
        # Purge immediate (pas d'attente du prochain timeout a 16ms, voir
        # _throttled_layout) : le tout DERNIER mouvement avant le relachement
        # doit se voir sans le moindre delai perceptible.
        self._layout_throttle_timer.stop()
        self._layout_pending = False
        self.list.doItemsLayout()
        if self.style_title == "Type":
            # "Type" n'a jamais de bouton punaise (voir __init__) mais doit
            # neanmoins s'enregistrer automatiquement — voir la remarque de
            # l'utilisateur, "les seules colonnes dont les parametres sont
            # enregistrees automatiquement sont : colonne type, colonnes
            # focus, colonne inspecteur".
            _persist_column_width(self.window(), "Type", self.width())
        elif self._pin_active:
            # Punaise ACTIVE (voir _toggle_pin) : la largeur qu'on vient de
            # glisser a la main REMPLACE automatiquement celle figee — voir la
            # remarque de l'utilisateur, "quand on modifie une valeur quand une
            # punaise est pinnee, cette valeur doit etre enregistree
            # automatiquement" (sans repincer/depincer a la main).
            self._pin_column_width = self.width()
            _update_layout_setting(self.directory, "pinned_column_width", self._pin_column_width)
        # Sans punaise et hors "Type" : la largeur n'est PLUS persistee du
        # tout (voir la remarque de l'utilisateur, "les hauteurs ne peuvent
        # pas etre enregistrees sauf si on met la punaise" — meme principe
        # etendu a la largeur) ; elle reste ajustable pour la session
        # courante via self._user_width (voir refresh_all_columns).

    def _in_height_resize_zone(self, y: int) -> bool:
        """Bord BAS d'une colonne du groupe IN/OVER/OUT/LOGICIELS (voir
        group_kind) — EXACTEMENT le meme principe que _in_resize_zone (bord
        DROIT), mais applique a la hauteur : ces 4 colonnes empilees ont une
        hauteur FIXE (voir __init__), contrairement a une colonne NORMALE
        toujours etiree sur toute la hauteur disponible — glisser ce bord
        n'a donc de sens QUE pour elles, et PAS pour la DERNIERE colonne de
        l'ordre courant (voir fill_height, TOUJOURS etiree jusqu'en bas —
        rien a redimensionner puisqu'elle n'a justement PAS de hauteur
        fixe). Priorite sur _in_row_resize_zone (Ctrl+glisser entre 2
        lignes) : gate sur `group_kind`, jamais actif en meme temps que
        celle-ci (styles "Contenu"/"Logiciels", hors
        _ROW_HEIGHT_RESIZABLE_TITLES)."""
        if self._group_kind is None or self._group_fill_height or self.collapsed or not columns_resizable():
            return False
        return self.height() - COLUMN_RESIZE_MARGIN <= y <= self.height()

    def height_resize_begin(self, global_y: int):
        self._group_height_resizing = True
        self._group_height_resize_start_y = global_y
        self._group_height_resize_start_height = self.height()
        if self._on_height_resize_begin is not None:
            self._on_height_resize_begin(self._group_kind)
        _show_resize_width(self, self.height())

    def height_resize_update(self, global_y: int):
        # PAS de calcul de hauteur ICI (voir la remarque de tete sur
        # `on_height_resize`) : seul PipelineBrowser._on_group_height_resized
        # connait les 2 colonnes concernees (celle-ci ET sa voisine
        # suivante) et leurs hauteurs de depart — il applique lui-meme
        # setFixedHeight() sur les DEUX, jamais Column elle-meme.
        delta = global_y - self._group_height_resize_start_y
        if self._on_height_resize is not None:
            self._on_height_resize(self._group_kind, delta)
        _show_resize_width(self, self.height())

    def set_group_fill_height(self, fill: bool):
        """Bascule cette colonne du groupe entre hauteur FIXE (voir
        _group_user_height/GROUP_COLUMN_DEFAULT_HEIGHT) et hauteur ETIREE
        jusqu'en bas (voir fill_height, __init__) — appele quand l'ordre
        change (voir PipelineBrowser._reorder_group_columns_animated) et
        qu'une AUTRE colonne devient la derniere : celle qui redevient
        derniere doit se liberer de sa hauteur fixe (setMaximumHeight a
        _WIDGET_SIZE_MAX, valeur par defaut de Qt), celle qui ne l'est plus
        doit en reprendre une."""
        if fill == self._group_fill_height:
            return
        self._group_fill_height = fill
        if fill:
            # 0 (PAS GROUP_COLUMN_MIN_HEIGHT) : voir la remarque de
            # l'utilisateur, "la colonne du bas (out) a une hauteur
            # minimum. supprime cette limite" — SEULE la colonne fill
            # (toujours la DERNIERE de l'ordre courant) perd cette borne ;
            # les AUTRES colonnes du groupe gardent la leur (voir
            # _on_group_height_resized, `max(GROUP_COLUMN_MIN_HEIGHT, ...)`
            # sur `new_above`, INCHANGE).
            self.setMinimumHeight(0)
            self.setMaximumHeight(_WIDGET_SIZE_MAX)
        else:
            self.setMinimumHeight(0)
            self.setFixedHeight(self._group_user_height or GROUP_COLUMN_DEFAULT_HEIGHT)

    def height_resize_end(self):
        self._group_height_resizing = False
        if self._on_height_resize_end is not None:
            self._on_height_resize_end()
        _hide_resize_width(self)

    def _in_row_resize_zone(self, y: int) -> bool:
        """Vrai si `y` (coordonnee LOCALE au viewport de self.list) tombe
        dans la marge de redimensionnement entre 2 lignes, Ctrl enfonce —
        voir la remarque de l'utilisateur, "appuyer sur la touche controle
        du clavier et cliquer entre deux lignes et glisser ... doit etre
        sur toutes les colonnes". Disponible sur TOUTE colonne (plus de
        liste de titres fixe — anciennement limite a Type/Projets/Sous-
        projet, ce qui excluait aussi bien Logiciels/Contenu que toute
        colonne d'une chaine CONFIGUREE comme "test1"/"test2") : ajuste
        TOUJOURS `COLUMN_SETTINGS[_col_key(title)]["height"]` (voir
        row_resize_begin/update, deja generique), c'est-a-dire la hauteur
        des lignes AVEC vignette/dossier — Logiciels/Contenu melangent 2
        hauteurs (voir col_plain_height pour les lignes fichier SANS
        apercu), mais cette 2e hauteur n'est simplement jamais celle que ce
        geste modifie, aucune ambiguite reelle (voir _persist_row_height
        pour la persistance, qui ecrit dans le defaut GENERAL pour ces
        titres-la, faute d'onglet de surcharge dedie)."""
        if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
            return False
        above = self.list.indexAt(QPoint(1, y - COLUMN_RESIZE_MARGIN))
        if not above.isValid():
            return False
        below = self.list.indexAt(QPoint(1, y + COLUMN_RESIZE_MARGIN))
        return not below.isValid() or below.row() != above.row()

    def effective_row_height(self) -> int:
        """Hauteur de ligne EFFECTIVE de cette colonne (voir sizeHint des
        delegates) : la punaise (voir __init__/_pin_row_height/_toggle_pin)
        d'ABORD si active (prioritaire sur tout le reste), sinon celle
        propre a `self.directory` si elle a deja ete ajustee a la main
        (voir __init__/_folder_row_height) — MEME mecanisme pour une
        colonne du groupe IN/OVER/OUT/LOGICIELS que pour une colonne
        normale depuis que ces 4 colonnes recoivent une identite de
        dossier STABLE (voir PipelineBrowser.update_preview_stack,
        add_group_column) et ne sont plus reconstruites a chaque
        navigation — plus besoin d'un bucket separe (GROUP_ROW_HEIGHT,
        supprime) qui les faisait toutes partager la MEME hauteur via le
        style "Contenu" — voir la remarque de l'utilisateur, "elle
        intervient sur plusieurs colonnes en meme temps" ; sinon la valeur
        GENERALE du bucket de style (voir col_row_height/_col_key)."""
        if self._pin_row_height is not None:
            return scaled(self._pin_row_height)
        if self._folder_row_height is not None:
            return scaled(self._folder_row_height)
        return col_row_height(self.style_title)

    def group_content_height_hint(self) -> int:
        """Hauteur NECESSAIRE pour afficher tout le contenu de cette
        colonne SANS scroll (entete + toutes les lignes + espacement) —
        voir PipelineBrowser._on_group_maximize, la remarque de
        l'utilisateur, "agrandir au maximum ... et de minimiser les
        autres au maximum en fonction de leur contenu". Bornee a
        GROUP_COLUMN_MIN_HEIGHT/GROUP_COLUMN_MAX_HEIGHT (memes bornes que
        le redimensionnement manuel, voir _on_group_height_resized) —
        jamais 0 (colonne vide) ni demesuree (des centaines de lignes)."""
        header_h = self.header.height()
        if header_h <= 0:
            header_h = scaled(int(column_style_for(self.style_title).get("header_height", HEADER_HEIGHT)))
        count = self.list.count()
        row_h = self.effective_row_height()
        spacing = col_spacing(self.style_title)
        content_h = count * row_h + max(0, count - 1) * spacing
        return max(GROUP_COLUMN_MIN_HEIGHT, min(GROUP_COLUMN_MAX_HEIGHT, header_h + content_h + 8))

    def row_resize_begin(self, global_y: int, local_y: int | None = None):
        self._row_resizing = True
        self._row_resize_start_y = global_y
        # Ligne au-dessus du bord glisse (voir _in_row_resize_zone, MEME
        # calcul) : memorisee ICI pour ancrer l'indicateur de hauteur juste
        # SOUS elle pendant tout le glisser (voir _show_row_resize_
        # indicator) — voir la remarque de l'utilisateur, "je veux que la
        # position de l'indicateur de hauteur soit juste au dessous de la
        # ligne que l'on redimensionne".
        self._row_resize_row_index = -1
        if local_y is not None:
            above = self.list.indexAt(QPoint(1, local_y - COLUMN_RESIZE_MARGIN))
            if above.isValid():
                self._row_resize_row_index = above.row()
        # MEME PRIORITE que effective_row_height() (punaise D'ABORD) : sans
        # ca, demarrer un glisser sur une colonne PINNEE repartait d'une
        # hauteur DIFFERENTE de celle reellement affichee (_folder_row_
        # height/generale, jamais _pin_row_height), faisant "sauter" la
        # ligne des le tout premier mouvement — voir la remarque de
        # l'utilisateur, "le redimensionnement des lignes dans les
        # colonnes se fait mal".
        # MEME calcul pour une colonne du groupe IN/OVER/OUT/LOGICIELS que
        # pour une colonne normale (voir effective_row_height, sa remarque) :
        # ces 4 colonnes ont desormais une identite de dossier STABLE, plus
        # besoin d'un chemin separe.
        self._row_resize_start_height = (
            self._pin_row_height if self._pin_row_height is not None
            else self._folder_row_height if self._folder_row_height is not None
            else COLUMN_SETTINGS[_col_key(self.style_title)]["height"])
        _show_row_resize_indicator(self, self._row_resize_row_index, self.effective_row_height())

    def row_resize_update(self, global_y: int):
        delta_screen = global_y - self._row_resize_start_y
        delta_logical = round(delta_screen * 100 / max(1, ui_scale()))
        new_height = max(
            ROW_RESIZE_MIN_HEIGHT, min(ROW_RESIZE_MAX_HEIGHT, self._row_resize_start_height + delta_logical))
        # Colonne de navigation REELLE OU colonne du groupe IN/OVER/OUT/
        # LOGICIELS (voir effective_row_height, sa remarque) : la valeur
        # choisie ici reste PROPRE a ce dossier (identite STABLE meme pour
        # les 4 colonnes de groupe, voir update_preview_stack/
        # add_group_column), JAMAIS ecrite dans le bucket de style GLOBAL
        # (COLUMN_SETTINGS) partage par toutes les colonnes du meme style —
        # voir la remarque de l'utilisateur, "jamais les mm suivant le sous
        # dossier precedent"/"elle intervient sur plusieurs colonnes en
        # meme temps" : une AUTRE colonne du meme style (naviguee vers un
        # AUTRE dossier, ou un AUTRE kind du groupe) ne doit PAS bouger.
        self._folder_row_height = new_height
        # Punaise ACTIVE : _pin_row_height doit AUSSI suivre EN DIRECT (pas
        # seulement au relachement, voir row_resize_end) — effective_row_
        # height() le priorise sur _folder_row_height, le laisser fige
        # pendant tout le glisser figeait l'AFFICHAGE (rien ne bougeait a
        # l'ecran) meme si la valeur interne changeait bien — voir la
        # remarque de l'utilisateur, "quand on modifie la hauteur de la
        # ligne, elle ne se modifie pas en temps reelle tant que la
        # punaise est activee".
        if self._pin_active:
            self._pin_row_height = new_height
        # doItemsLayout() (pas juste un repaint) : sizeHint() de CHAQUE ligne
        # depend de col_row_height(), qu'on vient de changer — un simple
        # viewport().update() garderait les anciennes tailles/positions.
        # _throttled_layout() (pas un appel direct) : voir son commentaire,
        # limite ce recalcul a ~60/s pendant le glisser.
        self._throttled_layout()
        _show_row_resize_indicator(self, self._row_resize_row_index, new_height)

    def row_resize_end(self):
        self._row_resizing = False
        _hide_resize_width(self, "row_height")
        # Purge immediate (voir resize_end, meme raison) : la hauteur du
        # tout dernier mouvement doit s'appliquer sans attendre le prochain
        # timeout de _layout_throttle_timer.
        self._layout_throttle_timer.stop()
        self._layout_pending = False
        self.list.doItemsLayout()
        if self.style_title == "Type":
            # "Type" n'a jamais de bouton punaise mais doit neanmoins
            # s'enregistrer automatiquement — voir la remarque de
            # l'utilisateur, "les seules colonnes dont les parametres
            # sont enregistrees automatiquement sont : colonne type,
            # colonnes focus, colonne inspecteur". Pas de notion de
            # dossier ici (voir _persist_row_height) : la valeur GLOBALE
            # de style est mise a jour directement.
            _persist_row_height(self.window(), "Type", self._folder_row_height)
        elif self._pin_active:
            # Punaise ACTIVE (voir _toggle_pin/resize_end, MEME raison) :
            # persiste DANS CE DOSSIER (voir __init__/_folder_row_height,
            # la remarque de l'utilisateur, "jamais les mm suivant le
            # sous dossier precedent") et remplace automatiquement la
            # valeur figee — voir la remarque de l'utilisateur, "quand
            # on modifie une valeur quand une punaise est pinnee, cette
            # valeur doit etre enregistree automatiquement". MEME chemin
            # pour une colonne du groupe IN/OVER/OUT/LOGICIELS (identite
            # de dossier STABLE, voir update_preview_stack).
            _update_layout_setting(self.directory, "row_height", self._folder_row_height)
            self._pin_row_height = self._folder_row_height
            _update_layout_setting(self.directory, "pinned_row_height", self._pin_row_height)
        # Sans punaise et hors "Type" : la hauteur n'est PLUS persistee
        # (voir la remarque de l'utilisateur, "les hauteurs ne peuvent
        # pas etre enregistrees sauf si on met la punaise") ; elle reste
        # ajustable pour la session courante via self._folder_row_height,
        # qui persiste desormais avec l'INSTANCE (les 4 colonnes de groupe
        # ne sont plus reconstruites a chaque navigation, voir
        # update_preview_stack).

    def eventFilter(self, obj, event):
        etype = event.type()
        # Glisser-deposer de l'ENTETE (voir group_kind/on_reorder, __init__)
        # : SEULEMENT pour une colonne du groupe IN/OVER/OUT/LOGICIELS, sur
        # header/header_fill/les 2 labels (voir _group_header_widgets — ils
        # COUVRENT header, sans eux la souris le touche presque jamais) —
        # jamais sur self.list.viewport()/sa scrollbar (deja pris par
        # FileListWidget pour glisser des FICHIERS). SUIVI A LA MAIN (pas de
        # QDrag/OLE natif) : sur une fenetre SANS decoration systeme et
        # translucide (voir PipelineBrowser.__init__, WA_TranslucentBackground/
        # FramelessWindowHint), le glisser-deposer natif Windows s'est avere
        # peu fiable — voir la remarque de l'utilisateur, "il y a encore des
        # cas ou ca ne fonctionne pas" (deja apres le correctif de couverture
        # de l'entete). Repose ICI sur le SEUL mecanisme deja fiable dans ce
        # fichier pour ce genre de geste (voir resize_begin/_row_resizing) :
        # la capture implicite Qt du bouton par le widget qui a recu le
        # QMouseEvent.Press, qui continue a recevoir MouseMove/Release tant
        # que le bouton reste enfonce, MEME hors de ce widget — aucun DnD
        # necessaire. Traite EN PREMIER, avant le reste (resize de bordure/
        # de ligne) : le seuil de demarrage du drag (MouseMove) doit passer
        # AVANT le test de zone de redimensionnement pour ne pas lui faire
        # concurrence au centre de l'entete (hors de cette zone).
        if self._group_kind is not None and obj in self._group_header_widgets:
            if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                local_x = obj.mapTo(self, event.position().toPoint()).x()
                if not self._in_resize_zone(local_x):
                    self._group_drag_start = event.globalPosition().toPoint()
            elif etype == QEvent.MouseMove and self._group_drag_start is not None:
                global_pos = event.globalPosition().toPoint()
                if self._group_ghost is not None:
                    self._group_ghost.move(global_pos - self._group_ghost_offset)
                    return True
                moved = global_pos - self._group_drag_start
                if moved.manhattanLength() >= QApplication.startDragDistance():
                    self._group_ghost_offset = global_pos - self.mapToGlobal(QPoint(0, 0))
                    self._group_ghost = _make_group_drag_ghost(self)
                    self._group_ghost.move(global_pos - self._group_ghost_offset)
                    return True
            elif etype == QEvent.MouseButtonRelease:
                self._group_drag_start = None
                if self._group_ghost is not None:
                    self._group_ghost.close()
                    self._group_ghost = None
                    target = self._find_group_drop_target(event.globalPosition().toPoint())
                    if target is not None and target is not self and self._on_reorder is not None:
                        self._on_reorder(self._group_kind, target._group_kind)
                    return True
        if etype == QEvent.MouseMove:
            if self._row_resizing:
                self.row_resize_update(event.globalPosition().toPoint().y())
                return True
            if self._group_height_resizing:
                self.height_resize_update(event.globalPosition().toPoint().y())
                return True
            if obj is self.list.viewport() and self._in_row_resize_zone(int(event.position().y())):
                obj.setCursor(Qt.SizeVerCursor)
                return False
            local_point = obj.mapTo(self, event.position().toPoint())
            if self._in_height_resize_zone(local_point.y()):
                obj.setCursor(Qt.SizeVerCursor)
                return False
            if self._resizing:
                self.resize_update(event.globalPosition().toPoint().x())
                return True
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_point.x()) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # Badge numerote (voir _step_badge_rect/_row_preview_left_x/
            # ProjectTileDelegate.paint, project_step_count) : SEULEMENT sur
            # "Projets", avant tout autre test de cette branche (desormais
            # juste AVANT l'apercu, voir _paint_unified_row, PLUS au bord
            # haut-droit de la ligne — meme calcul de position ici, pour
            # que le hit-test reste synchronise avec le dessin) — consomme
            # le clic (return True), aucune selection/navigation ne doit se
            # declencher.
            if obj is self.list.viewport() and self.column_title == "Projets":
                pos = event.position().toPoint()
                idx = self.list.indexAt(pos)
                if idx.isValid() and bool(idx.data(ROLE_ISDIR)):
                    row_rect = self.list.visualRect(idx)
                    preview_left = _row_preview_left_x(row_rect, column_style_for(self.style_title))
                    if _step_badge_rect(row_rect, preview_left).contains(pos):
                        self._open_column_config(Path(idx.data(ROLE_PATH)))
                        return True
            if obj is self.list.viewport() and self._in_row_resize_zone(int(event.position().y())):
                self.row_resize_begin(event.globalPosition().toPoint().y(), int(event.position().y()))
                return True
            local_point = obj.mapTo(self, event.position().toPoint())
            if self._in_height_resize_zone(local_point.y()):
                self.height_resize_begin(event.globalPosition().toPoint().y())
                return True
            if self._in_resize_zone(local_point.x()):
                self.resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.RightButton and obj is self.list.viewport():
            # Consomme le clic DROIT AVANT qu'il n'atteigne
            # QAbstractItemView.mousePressEvent (comportement Qt PAR
            # DEFAUT sinon : TOUT clic, gauche OU droit, change la
            # selection COURANTE de l'item sous le curseur) — voir la
            # remarque de l'utilisateur, "absolument rien ne se passe,
            # aucun menu n'apparait du tout" (clic droit sur un fichier/
            # dossier des colonnes IN/OVER/OUT/LOGICIELS) : CONFIRME —
            # pour une colonne du groupe (group_kind is not None), un
            # simple clic droit sur un DOSSIER changeait la selection,
            # declenchant Column._on_current_changed -> self.selected ->
            # PipelineBrowser._on_group_item_selected -> _open_group_
            # folder -> update_preview_stack(), qui DETRUIT ET RECONSTRUIT
            # tout le groupe — Y COMPRIS CETTE COLONNE ELLE-MEME — AVANT
            # meme que le QContextMenuEvent (qui suit normalement le
            # MouseButtonPress droit, PAS lie a lui) n'ait la moindre
            # chance d'etre livre au widget entre-temps deja detruit : le
            # clic droit "ne faisait absolument rien" de visible. Retourner
            # True ICI empeche desormais tout changement de selection au
            # clic droit (comportement standard des explorateurs de
            # fichiers, de toute facon plus coherent que le declenchement
            # de navigation involontaire que ca provoquait deja, sans
            # degat visible, sur les colonnes NORMALES) — le menu
            # contextuel (voir customContextMenuRequested/_on_context_menu,
            # policy Qt.CustomContextMenu deja posee sur self.list) suit
            # ensuite normalement, sans aucun rapport avec ce MousePress.
            return True
        elif etype == QEvent.MouseButtonRelease and (self._resizing or self._row_resizing or self._group_height_resizing):
            if self._row_resizing:
                self.row_resize_end()
            elif self._group_height_resizing:
                self.height_resize_end()
            else:
                self.resize_end()
            return True
        elif etype == QEvent.Leave and not (self._resizing or self._row_resizing or self._group_height_resizing):
            obj.unsetCursor()
        return False

    def _open_column_config(self, project_path: Path):
        """Ouvre ColumnConfigDialog pour `project_path` (clic sur le badge
        numerote, voir eventFilter) — a la fermeture par Enregistrer :
        `refresh()` (le badge affiche le nouveau project_step_count) et, si
        `project_path` est ACTUELLEMENT selectionne dans cette colonne,
        re-emet `selected` pour forcer PipelineBrowser.on_selected a
        recharger la config et reconstruire la chaine avec les nouveaux
        niveaux — sans ca, un projet deja ouvert garderait son ancienne
        chaine jusqu'a un clic explicite ailleurs puis retour."""
        config = load_project_columns(project_path)
        dlg = ColumnConfigDialog(project_path, config, self.window())
        if dlg.exec() == QDialog.Accepted:
            self.refresh()
            current = self.list.currentItem()
            if current is not None and Path(current.data(ROLE_PATH)) == project_path:
                self.selected.emit(self, project_path)

    def _find_group_drop_target(self, global_pos: QPoint) -> "Column | None":
        """Colonne du groupe IN/OVER/OUT/LOGICIELS (voir group_kind) dont le
        rectangle ECRAN contient `global_pos` (voir eventFilter, appele au
        relachement du glisser d'en-tete) — hit-test A LA MAIN plutot que
        `QApplication.widgetAt()` : celui-ci renverrait la ghost window
        elle-meme (voir _make_group_drag_ghost) si elle n'etait pas
        WA_TransparentForMouseEvents, ou tout widget ENFANT de la colonne
        (liste, labels...) sinon — on veut la COLONNE entiere, quel que soit
        l'enfant precis survole. `self.window()` : PipelineBrowser, seul
        detenteur de la liste a jour des colonnes du groupe (voir
        update_preview_stack)."""
        win = self.window()
        for column in getattr(win, "group_columns", []):
            top_left = column.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, column.size())
            if rect.contains(global_pos):
                return column
        return None

    # Gestionnaires DIRECTS sur self, EN PLUS de l'eventFilter ci-dessus
    # (installe sur header/self.list.viewport()/sa scrollbar — voir
    # __init__) : Padding (voir refresh_header/self._outer_layout) peut
    # desormais retrecir self.card (et tout son contenu, header/liste
    # compris) EN DECA du bord droit REEL de self — la zone de
    # redimensionnement, elle, reste TOUJOURS a ce bord reel (largeur
    # ALLOUEE, jamais retrecie par Padding, voir _in_resize_zone/self.
    # width()). Sans ces 2 gestionnaires, cette bande (le "vide" du
    # padding, visible entre le bord de la carte et le bord reel de la
    # colonne) n'etait couverte par AUCUN widget enfant — donc par aucun
    # eventFilter — rendant le redimensionnement tout simplement
    # INACCESSIBLE a la souris des que Padding > 0 — voir la remarque de
    # l'utilisateur, "il est impossible de redimensionner la colonne quand
    # on commence a toucher aux settings".
    def mouseMoveEvent(self, event):
        if self._resizing:
            self.resize_update(event.globalPosition().toPoint().x())
            return
        if self._group_height_resizing:
            self.height_resize_update(event.globalPosition().toPoint().y())
            return
        pos = event.position().toPoint()
        if self._in_height_resize_zone(pos.y()):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(pos.x()) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if self._in_height_resize_zone(pos.y()):
                self.height_resize_begin(event.globalPosition().toPoint().y())
                return
            if self._in_resize_zone(pos.x()):
                self.resize_begin(event.globalPosition().toPoint().x())
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self.resize_end()
            return
        if self._group_height_resizing:
            self.height_resize_end()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not (self._resizing or self._group_height_resizing):
            self.unsetCursor()
        super().leaveEvent(event)

    def refresh(self):
        current = self.current_path()
        self.list.blockSignals(True)
        self.list.clear()
        if self._source_dirs is not None:
            # IN/OVER/OUT (voir __init__/PipelineBrowser.update_preview_
            # stack) : simple concatenation, dans l'ordre des sources
            # fournies (Projet puis Sous-projet) — pas de deduplication,
            # chaque source garde ses propres entrees meme en cas
            # d'homonymie. `label` (voir source_labels) : annotation
            # associee a CETTE source, reportee sur chacune de ses entrees.
            entries = []
            for i, source in enumerate(self._source_dirs):
                label = self._source_labels[i] if self._source_labels else None
                # Position de CETTE source dans la chaine (2 = Type, voir
                # ROLE_SOURCE_STEP) : PAS d'etiquette -> pas de palier non
                # plus (LOGICIELS, source_labels=None).
                step = (i + 2) if self._source_labels else None
                entries.extend((path, label, step, False) for path in list_entries(source))
            if self._only_recognized_software:
                # Uniquement des REPERTOIRES DE LOGICIEL reconnus (voir
                # software_icon_key/app_style.custom_softwares) — pas de
                # fichier isole ni de dossier non reconnu qui trainerait
                # dans le dossier de travail — voir la remarque de
                # l'utilisateur, "dans la colonne logiciel, il ne doit y
                # avoir que des repertoires logiciel".
                entries = [
                    (path, label, step, is_shortcut) for path, label, step, is_shortcut in entries
                    if path.is_dir() and software_icon_key(path.name) is not None
                ]
        else:
            # Colonnes REELLES (Type/Projets/Sous-projet/toute colonne "de
            # set" configuree, focus ou non) : in/over/out ne sont jamais
            # des lignes normales, ils deviennent des colonnes dediees (voir
            # IN/OVER/OUT ci-dessus, STATUS_FOLDERS) — INCONDITIONNEL (plus
            # seulement self.has_thumbnails) : voir la remarque de
            # l'utilisateur, "si a l'interieur des colonnes de set il y a
            # un repertoire in out ou over, il n'apparaisse pas dans la
            # colonne concernee".
            entries = [(path, None, None, False) for path in list_entries(self.directory, _STATUS_FOLDER_SET)]
            # Raccourcis (voir load_shortcuts/ROLE_IS_SHORTCUT, Column._on_
            # context_menu "Ajouter un raccourci") : dossiers d'AILLEURS sur
            # le disque, affiches comme s'ils etaient physiquement ICI —
            # propres a CE dossier (jamais pour une colonne du groupe IN/
            # OVER/OUT/LOGICIELS, source_dirs deja exclu par ce `else`) —
            # voir la remarque de l'utilisateur, "faire comme si il etait
            # au meme endroit que les autres repertoires de l'emplacement
            # actuel". Cible manquante (dossier deplace/supprime depuis) :
            # ignoree silencieusement, pas d'entree fantome.
            for shortcut in load_shortcuts(self.directory):
                target = Path(shortcut.get("target", ""))
                if target.is_dir():
                    entries.append((target, None, None, True))
        # Filtres de contenu (voir __init__ show_dirs/show_files/omit_dirs/
        # omit_files, ColumnConfigDialog) : SEULEMENT pour un niveau de la
        # chaine CONFIGUREE — toute colonne NORMALE garde ses valeurs par
        # defaut (True/True/vide), donc ce bloc ne change RIEN pour elle
        # (le `if` court-circuite direct au cas commun, entries INCHANGE).
        if (not self._show_dirs or not self._show_files or self._omit_dirs or self._omit_files
                or GLOBAL_OMIT_FILE_NAMES or GLOBAL_OMIT_FILE_EXTENSIONS):
            filtered = []
            for path, label, step, is_shortcut in entries:
                is_dir = path.is_dir()
                if is_dir and not self._show_dirs:
                    continue
                if not is_dir and not self._show_files:
                    continue
                name_lower = path.name.lower()
                if is_dir and name_lower in self._omit_dirs:
                    continue
                if not is_dir and name_lower in self._omit_files:
                    continue
                if not is_dir and (
                    name_lower in GLOBAL_OMIT_FILE_NAMES
                    or any(name_lower.endswith("." + extension)
                           for extension in GLOBAL_OMIT_FILE_EXTENSIONS)
                ):
                    continue
                filtered.append((path, label, step, is_shortcut))
            entries = filtered
        for path, label, step, is_shortcut in entries:
            item = QListWidgetItem(path.name)
            item.setData(ROLE_PATH, str(path))
            is_dir = path.is_dir()
            item.setData(ROLE_ISDIR, is_dir)
            item.setData(ROLE_SOURCE_LABEL, label)
            item.setData(ROLE_SOURCE_STEP, step)
            item.setData(ROLE_IS_SHORTCUT, is_shortcut)
            meta = ""
            if not is_dir:
                try:
                    meta = human_size(path.stat().st_size)
                except OSError:
                    pass
            elif self.has_thumbnails:
                count = count_entries(path, _STATUS_FOLDER_SET)
                meta = f"{count} element{'s' if count != 1 else ''}"
            item.setData(ROLE_META, meta)
            self.list.addItem(item)
            if current and path == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def relayout(self, do_layout: bool = True):
        """Reapplique la mise en page (tailles de ligne) apres un changement
        de reglage purement cosmetique (police, hauteur de ligne...), SANS
        retourner sur le disque : le contenu deja charge (noms, tailles,
        vignettes) reste valable, seul son rendu change. Utilise par
        PipelineBrowser.refresh_all_columns(rescan=False), notamment pendant
        la previsualisation en direct de la fenetre de parametres, ou un
        column.refresh() complet (rescan du dossier, y compris le comptage
        recursif des colonnes a vignettes) serait rejoue a chaque cran de
        slider pour rien.

        `do_layout=False` (voir PipelineBrowser._apply_settings, qui compare
        col_row_height()/col_spacing() avant/apres apply_all_settings) saute
        le doItemsLayout() — le SEUL poste vraiment couteux ici (recalcule le
        sizeHint() de CHAQUE ligne visible) — quand ce cran de slider n'a
        PAS touche a la hauteur/l'espacement des lignes de CETTE colonne
        (couleur, bordure, rayon, padding de selection...)."""
        if do_layout:
            self.list.doItemsLayout()

    def refresh_colors(self):
        """Reapplique les couleurs (voir C, mutable via app_style.set_color)
        aux qss fixes une fois pour toutes a la construction — necessaire
        car un changement de couleur depuis la fenetre de parametres ne
        retouche pas les widgets deja construits (voir la remarque sur
        set_color dans app_style.py)."""
        # Style APPLIQUE POUR DE VRAI a TOUTE colonne desormais (voir
        # app_style.column_header_qss/column_frame_qss — le style general
        # Colonnes/Entetes, "Type" seule pouvant le SURCHARGER depuis
        # Colonnes > Type, voir SettingsWindow._build_column_type_page),
        # pas seulement l'apercu de la fenetre de parametres comme avant —
        # voir la remarque de l'utilisateur, "je veux que tu en fasse de
        # meme pour toute les colonnes de l'appli. les settings doivent
        # refletter a 100% ce qui se passe dans l'appli".
        self.header_fill.setStyleSheet(column_header_qss("ColumnHeader", self.style_title))
        frame = column_frame_style(self.style_title, self._suppress_left())
        # scaled() ICI, sur le MEME dict que celui repasse tel quel au
        # masque (voir _update_card_mask, qui relit self.card._radius
        # plutot que de recalculer independamment) : sans ca, peinture et
        # masque pouvaient utiliser 2 rayons LEGEREMENT differents des que
        # l'echelle d'interface (Application > Scale) n'est pas 100%.
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        # scaled() sur l'epaisseur AUSSI (pas seulement le rayon ci-dessus) :
        # refresh_header reserve deja scaled(border_thickness) comme marge
        # pour cette bordure — la peindre ICI avec l'epaisseur BRUTE (non
        # scaled) desaccordait les deux des que l'echelle d'interface
        # (Application > Scale) n'est pas 100%, laissant un filet trop fin/
        # epais par rapport a la marge qui lui est reservee.
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        self._update_card_mask()
        # PAS de reapplication de self.title_label ici (BUG corrige, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette ligne existait AVANT le systeme de
        # surcharge par titre (header_font_color/family/bold/italic/taille,
        # voir refresh_header ci-dessous) et l'ecrasait INCONDITIONNELLEMENT
        # avec la couleur GENERIQUE role_color('colhead', ...) — refresh_
        # colors() est TOUJOURS appelee APRES refresh_header() (voir
        # PipelineBrowser._apply_settings/add_column/Column.__init__), donc
        # toute surcharge de "Couleur du titre" pour CETTE colonne (Colonnes
        # > Type/Projets/.../Logiciels/IN/OVER/OUT/Inspecteur) etait
        # silencieusement annulee des le refresh SUIVANT. refresh_header()
        # gere deja CE style correctement (voir sa remarque de tete, `s =
        # column_style_for(self.style_title)`), y compris le cas SANS
        # surcharge (repli sur la valeur GENERALE de "header_font_color",
        # deja identique par defaut a l'ancienne couleur fixe ici) : rien
        # d'autre a faire.

    def _suppress_left(self) -> bool:
        """Voir _column_suppress_left (module-level, factorisee pour etre
        partagee avec PreviewColumn)."""
        return _column_suppress_left(self, self.style_title)

    def refresh_header(self):
        """Reapplique hauteur/padding/police de l'entete (voir HEADER_HEIGHT/
        HEADER_PADDING, role 'colhead') — reglable en direct depuis
        Parametres > Entetes. HEADER_PADDING est la marge de header (voir
        __init__) : l'espace entre le fond colore (header_fill) et les
        bords de la colonne, pas la marge du texte a l'interieur du fond.

        Style EFFECTIF de CETTE colonne (voir app_style.column_style_for —
        general, ou surcharge Colonnes > Type pour "Type") plutot que les
        globals HEADER_HEIGHT/HEADER_PADDING partages a l'ancienne."""
        s = column_style_for(self.style_title)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", HEADER_HEIGHT))
        padding = int(s.get("header_padding", HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)   # 0 = valeur reglee valide (voir scaled)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/hauteur du titre (voir COLUMN_FRAME_KEYS/
        # app_style.column_style_for, Settings > General > Colonnes >
        # Entetes — OU sa surcharge Colonnes > Type/Projets/Sous-projets,
        # voir la remarque de l'utilisateur, "mets a jour egalement les
        # colonnes overidees ... avec tous les nouveaux parametres de
        # general") — "" (Systeme, aucune surcharge choisie) retombe
        # EXACTEMENT sur le role "colhead" d'origine (_resolve_font_family,
        # fallback_role) : comportement INCHANGE tant que l'utilisateur ne
        # personnalise pas.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.title_label.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.title_label.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")
        # Padding droit des icones (voir __init__, bouton punaise) :
        # marge droite DIRECTEMENT pilotee par ce reglage (PAS 10 + la
        # valeur — voir la remarque de l'utilisateur, "je veux que la
        # valeur 0 soit tres collee contre le bord de la colonne") —
        # seulement si une icone existe reellement sur cette colonne
        # (jamais "Type"/les colonnes Focus, voir __init__).
        if self._pin_btn is not None:
            self.header_fill.layout().setContentsMargins(
                10, 0, int(s.get("header_icon_right_padding", 0)), 0)
        # Espace avant le 1er item (voir __init__/self.header_gap_spacer,
        # Colonnes > Texte) : cle "item_*", donc seulement definie pour
        # "Type" (voir app_style.column_style_for) — 0 pour toute autre
        # colonne, comme avant ce reglage.
        self.header_gap_spacer.setFixedHeight(scaled(int(s.get("item_header_gap", 0) or 0), 0))
        # Bordure du CADRE : reserve, sur CHAQUE cote EFFECTIVEMENT peint
        # (voir column_frame_qss/_suppress_left — meme regle ICI pour le
        # cote gauche), la meme epaisseur que celle reellement dessinee la
        # — sinon le contenu (liste/entete, colle a self.card sans marge)
        # recouvrirait le filet, cote par cote — voir _TableFrame dans
        # settings_window.py, meme necessite/meme raison, deja documentee
        # la-bas. 1er essai : UNE seule marge, a droite (l'ancien filet
        # unique code en dur) — insuffisant des que les 4 cotes peuvent
        # etre actives independamment, voir la remarque de l'utilisateur,
        # "quand je met une valeur de padding, il n'y a pas de bordure sur
        # tous les cotes de la colonne" (le filet HAUT/GAUCHE/BAS restait
        # bien peint par la QSS, mais aussitot recouvert par l'entete/la
        # liste, qui n'en reservaient pas la place).
        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._column_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        # Padding de la colonne, PAR COTE (voir settings_window.
        # _ColumnPreview.setPadding/Colonnes > Colonnes > Padding) : fait
        # RETRECIR self.card (fond + bordure) de ce nombre de px sur chaque
        # cote choisi, PAS un simple retrait de son contenu — voir la
        # remarque de l'utilisateur, "je veux que le fond de la colonne se
        # replie". Cote GAUCHE mis a 0 si cette colonne est COLLEE a une
        # voisine (meme regle que _suppress_left pour la bordure) : sinon
        # l'ecart VISIBLE entre 2 colonnes collees cumulait le padding
        # DROIT de celle de gauche ET le padding GAUCHE de celle de
        # droite — le double de la valeur reglee — voir la remarque de
        # l'utilisateur, "la distance entre 2 colonnes doit etre la valeur
        # du padding et non celle du padding*2".
        col_pad = dict(column_padding_for(self.style_title))
        if self._suppress_left():
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()

    def _refresh_pin_icon(self):
        """Applique l'icone punaise (01 par defaut, 02 si active, voir
        _toggle_pin/_pin_icon_pixmap) — no-op sur "Type" (pas de bouton,
        voir __init__)."""
        if self._pin_btn is not None:
            self._pin_btn.setIcon(QIcon(_pin_icon_pixmap(self._pin_active, 14)))

    def _toggle_pin(self):
        """Punaise d'en-tete — voir __init__/effective_row_height, la
        remarque de l'utilisateur, "punaise_02.png lorsque l'on clique
        dessus, les valeurs de dimensions de colonnes et de lignes sont
        alors overridees par les valeurs du json se trouvant a la base du
        repertoire en cours ... lorsque l'on rappuie sur cette icone,
        l'icone redevient punaise_01.png et prend en compte les valeurs
        par defaut des settings". Desactiver NE SUPPRIME PAS les valeurs
        enregistrees (juste `pinned: False`) : rappuyer plus tard restaure
        exactement la largeur/hauteur figees precedemment, sans avoir a
        redimensionner de nouveau a la main."""
        if self._pin_active:
            self._pin_active = False
            self._pin_column_width = None
            self._pin_row_height = None
            _update_layout_setting(self.directory, "pinned", False)
        else:
            self._pin_active = True
            self._pin_column_width = self.width()
            self._pin_row_height = self.effective_row_height()
            data = load_layout_settings(self.directory)
            data["pinned"] = True
            data["pinned_column_width"] = self._pin_column_width
            data["pinned_row_height"] = self._pin_row_height
            save_layout_settings(self.directory, data)
        self._refresh_pin_icon()
        self.setFixedWidth(self._pin_column_width or self._user_width or col_width(self.style_title))
        self.list.doItemsLayout()

    def _update_card_mask(self):
        """Decoupe VRAIMENT self.card (fond + TOUS ses enfants — entete ET
        liste) a la silhouette EXACTE de son rayon d'angle — voir la
        remarque de l'utilisateur, capture a l'appui, "le fond et l'entete
        passent toujours devant la bordure de la colonne" : reserver une
        marge DROITE (voir refresh_header) ne protege que les segments
        DROITS des bords, jamais la zone COURBE d'un coin — l'entete
        (coins hauts) ET la liste (coins bas, ses propres lignes restant
        toujours des rectangles PLEINS, sans rayon) y debordaient donc
        encore des que column_border_radius > 0. Qt ne clippe jamais
        automatiquement des enfants au rayon QSS de leur parent — voir
        _TableFrame dans settings_window.py, qui avait DEJA essaye puis
        ABANDONNE un masque pour cette meme raison : un decoupage BINAIRE,
        non anti-aliase, degrade le rendu du coin arrondi lui-meme. Ce
        compromis reste neanmoins prefere ICI (une seule silhouette
        exterieure, generalement grande, contre de nombreux petits coins de
        ligne pour _TableFrame) plutot que de laisser la bordure invisible
        — voir la meme remarque de l'utilisateur, qui persiste malgre 2
        correctifs precedents (reserve de marge, "0px solid transparent")
        insuffisants a eux seuls."""
        # self.card._radius (deja SCALE, voir refresh_colors) — PAS
        # recalcule independamment ici : garantit le MEME rayon que celui
        # reellement peint (voir _ColumnCard.paintEvent/la docstring de
        # cette classe), plutot que 2 sources qui pourraient diverger.
        # activate() FORCE la resolution immediate du layout (largeur/
        # hauteur de self.card) : setContentsMargins()/setFixedWidth()
        # n'appliquent la nouvelle geometrie qu'au PROCHAIN cycle de
        # peinture (activation PARESSEUSE de Qt) — sans ce forçage,
        # self.card.rect() ci-dessous pouvait encore renvoyer l'ANCIENNE
        # taille au moment ou le masque est calcule, produisant un masque
        # decale/trop grand par rapport a ce qui est reellement peint —
        # voir la remarque de l'utilisateur, capture a l'appui, "les
        # arrondis ne sont pas du tout recouvert par la bordure".
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        # Desactive CE decoupage-ci des qu'une bordure existe (thickness>0) :
        # dans ce cas, _ColumnCard.paintEvent peint DEJA fond+bordure
        # exactement dans le silhouette voulu (voir _paint_bordered_rect,
        # qui a son PROPRE antialiasing sur le trait), et self._content est
        # DEJA reduit plus etroit par _content_effect ci-dessous (donc
        # jamais debordant) — ce masque-ci n'a plus RIEN a proteger, il ne
        # fait plus que reappliquer une 2e passe d'antialiasing PAR-DESSUS
        # celle, deja correcte, du trait — exactement au MEME rayon, donc
        # sur les MEMES pixels de transition : les 2 alphas partiels se
        # MULTIPLIENT plutot que de s'additionner, ce qui faisait carrement
        # disparaitre la bordure dans la courbe — voir la remarque de
        # l'utilisateur, capture a l'appui, "la bordure disparait
        # completement dans l'arrondi de l'angle". Reste ACTIF quand il n'y
        # a PAS de bordure (thickness<=0) : LA, _content_effect est lui-meme
        # desactive (voir plus bas) et ce masque-ci redevient le SEUL a
        # empecher l'entete/la liste (coins carres) de deborder du fond
        # arrondi.
        self._card_effect.setEnabled(self.card._thickness <= 0)
        # self._content (entete+liste) : decoupe a un rayon RETRECI de
        # l'epaisseur de bordure REELLEMENT peinte (self.card._thickness,
        # deja scaled — voir refresh_colors) — MEME formule que le clip du
        # FOND dans _paint_bordered_rect (_radius_shrink(radius, thickness))
        # — pour rester en retrait de l'anneau de la bordure jusque dans
        # les coins, pas seulement le long des segments droits (voir
        # reserve()/la docstring de self._content ci-dessus)."""
        # +1px de MARGE SUPPLEMENTAIRE (au-dela du strict inner_radius
        # geometrique) : self._content (coins CARRES, jamais son propre
        # rayon — voir column_header_qss, "le rognage visuel est deja
        # garanti par ce decoupage") est un ENFANT peint PAR-DESSUS
        # self.card (Z-order Qt normal) — a epaisseur de bordure FAIBLE
        # (1px), le bord antialiase de CE decoupage (inner_radius) et celui,
        # deja antialiase, du trait de bordure (juste 1px plus loin, a
        # `radius`) tombent quasiment sur LES MEMES pixels : le contenu,
        # AU-DESSUS, y "mangeait" alors la bordure au lieu de s'arreter
        # juste avant elle — voir la remarque de l'utilisateur, capture a
        # l'appui, "la bordure disparait completement dans l'arrondi de
        # l'angle". Cette marge laisse un peu d'air entre les 2 contours
        # pour que la bordure garde une zone a elle, sans concurrence.
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._content_effect.setRadius(_radius_dict(inner_radius))
        # Desactive ce 2e decoupage des qu'il n'a plus rien a proteger
        # (aucune bordure reellement peinte, thickness<=0) : inner_radius
        # egale alors radius au chiffre pres, donc self._content (deja a
        # l'interieur du silhouette de self.card, qui l'enveloppe ET tous
        # ses enfants dans SA PROPRE passe d'antialiasing via _card_effect)
        # n'a plus besoin d'etre roule une 2e fois — un 2e QGraphicsEffect,
        # rasterise dans SA PROPRE pixmap hors-ecran independante, ne
        # retombe JAMAIS EXACTEMENT sur les memes pixels que le 1er (chaque
        # passe d'antialiasing calcule sa propre couverture sous-pixel) :
        # 2 arrondis quasi identiques mais jamais superposables au pixel
        # pres laissaient un lisere visible a chaque coin — voir la
        # remarque de l'utilisateur, "je veux que le lissage de l'arrondi
        # soit parfait ce qui est loin d'etre le cas". Toujours REACTIVE
        # des qu'une bordure existe a nouveau (thickness>0) : LA, le rayon
        # interieur retrecit vraiment et reste indispensable (voir la
        # docstring de self._content plus haut, "l'entete/la liste
        # recouvrait le trace courbe de la bordure a chaque coin").
        self._content_effect.setEnabled(self.card._thickness > 0)

    def current_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(ROLE_PATH)) if item else None

    def _on_current_changed(self, item, _previous):
        self.selected.emit(self, Path(item.data(ROLE_PATH)) if item else None)

    def _on_double_clicked(self, item):
        self.activated.emit(Path(item.data(ROLE_PATH)))

    def _on_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            menu = QMenu(self)
            menu.setFont(font(11, 400))
            act_new_folder = menu.addAction("Nouveau dossier")
            act_new_text_file = menu.addAction("Nouveau document texte") if self._show_files else None
            act_add_shortcut = menu.addAction("Ajouter un raccourci...")
            act_paste = None
            if QApplication.clipboard().mimeData().hasUrls():
                menu.addSeparator()
                act_paste = menu.addAction("Coller")
            chosen = menu.exec(self.list.mapToGlobal(pos))
            if chosen is act_new_folder:
                # QTimer.singleShot(0, ...) (PAS un appel direct) : ouvrir
                # une QInputDialog SYNCHRONE juste apres la fermeture du
                # QMenu (meme pile d'appel, meme evenement souris) lui
                # laissait parfois recevoir le RELACHEMENT de CE MEME clic
                # (celui qui vient de fermer le menu), la refermant aussitot
                # — voir la remarque de l'utilisateur, "des fois (notamment
                # quand on vient juste de creer un repertoire) la petite
                # fenetre qui demande le nom du repertoire apparait et
                # disparait aussitot". Reporter d'un tour de boucle
                # d'evenements laisse ce relachement etre traite normalement
                # AVANT que la boite de dialogue n'existe.
                QTimer.singleShot(0, self._create_folder)
            elif chosen is act_new_text_file:
                QTimer.singleShot(0, self._create_text_file)
            elif chosen is act_add_shortcut:
                # 150ms (PAS 0) : ce menu ouvre un QFileDialog (via
                # _add_shortcut), pas seulement une QInputDialog — voir
                # _prompt_change_thumbnail, la MEME remarque ("un simple
                # tour de boucle Qt ne suffit pas a laisser Windows
                # relacher completement le grab souris/clavier NATIF du
                # menu contextuel tout juste ferme").
                QTimer.singleShot(150, self._add_shortcut)
            elif act_paste is not None and chosen is act_paste:
                self._paste_items()
            return
        path = Path(item.data(ROLE_PATH))
        if item.data(ROLE_IS_SHORTCUT):
            # Menu REDUIT (voir ROLE_IS_SHORTCUT) : "Renommer"/vignette
            # agiraient par erreur sur la VRAIE cible, situee ailleurs sur
            # le disque — seul "Retirer le raccourci" retire l'ENTREE,
            # jamais le dossier cible lui-meme.
            menu = QMenu(self)
            menu.setFont(font(11, 400))
            act_open = menu.addAction("Ouvrir")
            act_reveal = menu.addAction("Afficher dans l'explorateur")
            menu.addSeparator()
            act_copy_path = menu.addAction("Copier le chemin")
            menu.addSeparator()
            act_remove_shortcut = menu.addAction("Retirer le raccourci")
            chosen = menu.exec(self.list.mapToGlobal(pos))
            if chosen is act_open:
                self.activated.emit(path)
            elif chosen is act_reveal:
                reveal_in_file_manager(path)
            elif chosen is act_copy_path:
                QApplication.clipboard().setText(str(path))
            elif chosen is act_remove_shortcut:
                remove_shortcut(self.directory, path)
                self.refresh()
            return
        menu = QMenu(self)
        menu.setFont(font(11, 400))
        act_open = menu.addAction("Ouvrir")
        act_rename = menu.addAction("Renommer")
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        act_render_preview = None
        if path.is_file() and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
            menu.addSeparator()
            act_render_preview = menu.addAction("Générer le rendu de l'aperçu")
        act_change_thumb = None
        act_capture_thumb = None
        act_reset_thumb = None
        # `item.data(ROLE_ISDIR)` seul (PAS `self.has_thumbnails and ...`) :
        # cette fonctionnalite (deja generique, voir project_thumbnail_path/
        # _save_thumbnail_pixmap, aucune modification necessaire) etait
        # jusqu'ici reservee aux colonnes Projets/Sous-projet — voir la
        # remarque de l'utilisateur, "pouvoir integrer des images sur
        # n'importe quelle ligne de n'importe quelle colonne, comme par
        # exemple type ... en cliquant droit sur une ligne, ajouter un
        # apercu". Libelle "Ajouter" tant qu'aucun apercu personnalise
        # n'existe encore, "Changer" une fois qu'il y en a un (voir
        # _paint_unified_row, qui l'affiche a la place de l'icone toggle sur
        # la colonne "Type").
        has_custom = project_thumbnail_path(path).is_file()
        if item.data(ROLE_ISDIR):
            menu.addSeparator()
            act_change_thumb = menu.addAction("Changer l'image..." if has_custom else "Ajouter un apercu...")
            act_capture_thumb = menu.addAction("Capturer une zone d'ecran...")
            if has_custom:
                act_reset_thumb = menu.addAction("Reinitialiser l'image")

        menu.addSeparator()
        # "Afficher l'apercu"/"Afficher l'icone"/"Taille de l'icone" (voir
        # __init__ _show_icon_override/_show_preview_override/
        # _icon_size_override, _paint_unified_row) — valeur de depart =
        # celle EFFECTIVEMENT affichee (override deja actif, sinon le
        # reglage GENERAL) ; toute modification s'applique tout de suite
        # (session courante), et n'est ENREGISTREE (.pipeline_layout.json)
        # que si la punaise est active — voir la remarque de l'utilisateur,
        # "la valeur doit etre celle par defaut, et s'il y a changement
        # elle doit etre enregistree quand la colonne est pinnee
        # seulement".
        current_icon_visible = (
            self._show_icon_override if self._show_icon_override is not None
            else bool(column_style_for(self.style_title).get("item_icon_enabled", True)))
        current_preview_visible = (
            self._show_preview_override if self._show_preview_override is not None else True)
        act_show_icon = menu.addAction("Afficher l'icone")
        act_show_icon.setCheckable(True)
        act_show_icon.setChecked(current_icon_visible)
        act_show_icon.toggled.connect(self._set_show_icon_override)
        act_show_preview = menu.addAction("Afficher l'apercu")
        act_show_preview.setCheckable(True)
        act_show_preview.setChecked(current_preview_visible)
        act_show_preview.toggled.connect(self._set_show_preview_override)

        default_icon_size = int(column_style_for(self.style_title).get("item_icon_size") or 0) or 32
        self._add_context_slider(
            menu, "Taille de l'icone", self._icon_size_override or default_icon_size,
            8, 128, self._set_icon_size_override)

        default_icon_pad = int(column_style_for(self.style_title).get("item_icon_padding_left") or 0)
        self._add_context_slider(
            menu, "Padding gauche de l'icone", self._icon_padding_left_override or default_icon_pad,
            0, 64, self._set_icon_padding_left_override)

        default_text_pad = int(column_style_for(self.style_title).get("item_text_padding") or 8)
        self._add_context_slider(
            menu, "Padding gauche du texte", self._text_padding_left_override or default_text_pad,
            0, 64, self._set_text_padding_left_override)

        menu.addSeparator()
        act_copy_file = menu.addAction("Copier")
        act_copy_path = menu.addAction("Copier le chemin")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is act_open:
            self.activated.emit(path)
        elif chosen is act_rename:
            self._rename_item(path)
        elif chosen is act_reveal:
            reveal_in_file_manager(path)
        elif act_render_preview is not None and chosen is act_render_preview:
            try:
                mtime = path.stat().st_mtime
                path_key = str(path)
                _MANUAL_3D_PREVIEW_REQUESTS.add(path_key)
                _STALE_PREVIEW_PATHS.add(path_key)
                self.selected.emit(self, path)
            except OSError:
                pass
        elif act_change_thumb is not None and chosen is act_change_thumb:
            self._change_thumbnail(path)
        elif act_capture_thumb is not None and chosen is act_capture_thumb:
            self._capture_thumbnail(path)
        elif act_reset_thumb is not None and chosen is act_reset_thumb:
            self._reset_thumbnail(path)
        elif chosen is act_copy_file:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(path))

    def _add_context_slider(self, menu: QMenu, label_text: str, value: int, vmin: int, vmax: int, on_change):
        """Ligne "slider + valeur px en temps reel" du menu contextuel
        (voir _on_context_menu, "Taille de l'icone"/"Padding gauche de
        l'icone"/"Padding gauche du texte") — reutilise TEL QUEL le
        _SliderField de la fenetre de parametres (slider + boite de
        saisie px, deja avec sa valeur en temps reel) — voir la remarque
        de l'utilisateur, "je veux que le style [du slider] soit celui des
        settings" (remplace l'ancien QSlider habille a la main). Import
        DIFFERE (jamais au niveau module, meme raison que settings_window
        important pipeline_browser) : sans danger ici, appele bien apres
        que les deux modules soient charges."""
        import settings_window as sw

        action = QWidgetAction(menu)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)
        label = QLabel(label_text)
        label.setFont(font(11, 400))
        field = sw._SliderField(vmin, vmax, value, slider_width=120, box_width=60)
        field.valueChanged.connect(on_change)
        layout.addWidget(label)
        layout.addWidget(field, 1)
        action.setDefaultWidget(widget)
        menu.addAction(action)

    def _should_autosave_context_override(self) -> bool:
        """Vrai si CE reglage du menu contextuel doit s'enregistrer SANS
        punaise — "Type" n'a jamais de bouton punaise (voir __init__) mais
        doit neanmoins s'enregistrer automatiquement, comme sa largeur/sa
        hauteur de ligne (voir _persist_column_width/row_resize_end) — voir
        la remarque de l'utilisateur, "tous les parametres du menu
        contextuel ne s'enregistrent pas automatiquement dans la colonne
        de type"."""
        return self._pin_active or self.style_title == "Type"

    def _set_show_icon_override(self, value: bool):
        self._show_icon_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "show_icon", value)

    def _set_show_preview_override(self, value: bool):
        self._show_preview_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "show_preview", value)

    def _set_icon_size_override(self, value: int):
        self._icon_size_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "icon_size", value)

    def _set_icon_padding_left_override(self, value: int):
        self._icon_padding_left_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "icon_padding_left", value)

    def _set_text_padding_left_override(self, value: int):
        self._text_padding_left_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "text_padding_left", value)

    def _create_folder(self):
        name, ok = QInputDialog.getText(
            self, "Nouveau dossier", "Nom du dossier :", QLineEdit.Normal, "Nouveau dossier"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau dossier", "Le nom contient des caracteres interdits.")
            return
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            # Colonne IN/OVER/OUT (contenu FUSIONNE de plusieurs colonnes de
            # set, voir __init__/PipelineBrowser.update_preview_stack) :
            # `self.directory` n'est qu'un repli parmi plusieurs sources
            # possibles — demande a QUEL NIVEAU (quelle colonne de set
            # actuellement affichee) ce nouveau dossier doit reellement
            # etre cree sur le disque, plutot que de choisir silencieusement
            # le premier — voir la remarque de l'utilisateur, "je veux
            # pouvoir creer des repertoires dans les colonnes in over et
            # out. quand c'est le cas, je veux que le soft me demande a
            # quel niveau (quelle colonne) il doit les enregistrer".
            choice, ok_level = QInputDialog.getItem(
                self, "Nouveau dossier", "A quel niveau enregistrer ce dossier ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau dossier", f"« {name} » existe deja.")
            return
        try:
            # parents=True : `target_dir` (repli sur un NIVEAU DE SET
            # choisi, voir ci-dessus) peut lui-meme ne pas encore exister
            # (in/over/out jamais cree pour ce niveau precis) — voir la
            # remarque de l'utilisateur, capture a l'appui, "il y a un
            # probleme quand on cree un repertoire alors que la hierarchie
            # n'est pas encore creee ... que toute la hierarchie soit
            # creee en meme temps que le repertoire" (WinError 3, "chemin
            # d'acces introuvable").
            new_path.mkdir(parents=True)
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau dossier", f"Impossible de creer le dossier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

    def _create_text_file(self):
        """"Nouveau document texte" (voir _on_context_menu) : cree un fichier
        .txt vierge, MEME mecanique que _create_folder (nom/caracteres
        interdits/choix du niveau pour une colonne IN/OVER/OUT fusionnee/
        creation des dossiers parents manquants) — voir la remarque de
        l'utilisateur, "dans les colonnes ou le texte est permis, merci
        d'ajouter une option 'nouveau document texte' qui permet de creer
        un fichier txt vierge"."""
        name, ok = QInputDialog.getText(
            self, "Nouveau document texte", "Nom du fichier :", QLineEdit.Normal, "Nouveau document texte"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau document texte", "Le nom contient des caracteres interdits.")
            return
        if not name.lower().endswith(".txt"):
            name += ".txt"
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            choice, ok_level = QInputDialog.getItem(
                self, "Nouveau document texte", "A quel niveau enregistrer ce fichier ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau document texte", f"« {name} » existe deja.")
            return
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text("", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau document texte", f"Impossible de creer le fichier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

    def _add_shortcut(self):
        """"Ajouter un raccourci" (voir _on_context_menu, ROLE_IS_SHORTCUT/
        load_shortcuts/add_shortcut) : va chercher un repertoire A
        N'IMPORTE QUEL autre emplacement du disque et l'affiche comme s'il
        etait physiquement dans CE dossier — voir la remarque de
        l'utilisateur, "aller chercher un repertoire dans un emplacement
        autre ... et de faire comme si il etait au meme endroit que les
        autres repertoires de l'emplacement actuel"."""
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            # MEME choix de niveau que _create_folder, MEME raison (colonne
            # IN/OVER/OUT, contenu fusionne de plusieurs colonnes de set).
            choice, ok_level = QInputDialog.getItem(
                self, "Ajouter un raccourci", "A quel niveau enregistrer ce raccourci ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        chosen = QFileDialog.getExistingDirectory(self, "Choisir un repertoire", str(target_dir))
        if not chosen:
            return
        chosen_path = Path(chosen)
        if chosen_path == target_dir or chosen_path.parent == target_dir:
            QMessageBox.warning(self, "Ajouter un raccourci", "Ce repertoire est deja ici.")
            return
        add_shortcut(target_dir, chosen_path)
        self.refresh()

    def _change_thumbnail(self, path: Path):
        _prompt_change_thumbnail(self, path, lambda: self.list.viewport().update())

    def _capture_thumbnail(self, path: Path):
        _prompt_capture_thumbnail(self, path, lambda: self.list.viewport().update())

    def _save_thumbnail_pixmap(self, path: Path, pix: QPixmap):
        _save_thumbnail_pixmap_for(path, pix, self, lambda: self.list.viewport().update())

    def _reset_thumbnail(self, path: Path):
        _prompt_reset_thumbnail(self, path, lambda: self.list.viewport().update())

    def _unique_dest_path(self, src: Path, dest_dir: Path | None = None) -> Path:
        """Chemin de destination dans `dest_dir` (par defaut ce dossier), en
        evitant les collisions (« nom - copie », « nom - copie (2) », ...)."""
        dest_dir = dest_dir if dest_dir is not None else self.directory
        dest = dest_dir / src.name
        if not dest.exists():
            return dest
        stem, suffix = (src.stem, src.suffix) if src.is_file() else (src.name, "")
        candidate = dest_dir / f"{stem} - copie{suffix}"
        i = 2
        while candidate.exists():
            candidate = dest_dir / f"{stem} - copie ({i}){suffix}"
            i += 1
        return candidate

    def _paste_items(self):
        mime = QApplication.clipboard().mimeData()
        if not mime.hasUrls():
            return
        last_dest = None
        errors = []
        for url in mime.urls():
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            dest = self._unique_dest_path(src)
            try:
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")
        if errors:
            QMessageBox.warning(self, "Coller", "Impossible de coller :\n" + "\n".join(errors))
        self.refresh()
        if last_dest:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.list.setCurrentItem(it)
                    break

    def _rename_item(self, path: Path):
        new_name, ok = QInputDialog.getText(
            self, "Renommer", "Nouveau nom :", QLineEdit.Normal, path.name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == path.name:
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Renommer", "Le nom contient des caracteres interdits.")
            return
        new_path = path.with_name(new_name)
        if new_path.exists():
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe deja.")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Renommer", f"Impossible de renommer :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break


# Texte d'entete des 2 colonnes fantomes Focus (voir PreviewColumn.
# display_title/PipelineBrowser.update_preview_stack) — cle = titre REEL de
# la colonne source (Projets/Sous-projet, voir column.column_title) — voir
# la remarque de l'utilisateur, "il doit y avoir deux colonnes, une focus
# projet et l'autre focus sous projet, je veux aucune autre entete".
_FOCUS_LEVEL_LABEL = {"Projets": "Focus Projet", "Sous-projet": "Focus Sous-projet"}


class PreviewColumn(QWidget):
    """Colonne sans contenu de dossier propre, juste un apercu (voir
    PipelineBrowser.update_preview_stack) — utilisee pour
    PipelineBrowser.image_preview_columns : DEUX colonnes fantomes SEPAREES,
    une par niveau selectionne (Projets, Sous-projet — voir _PreviewBlock/
    set_preview_block), empilees VERTICALEMENT dans un conteneur commun
    (voir PipelineBrowser._preview_stack_wrapper), PERMANENTES — jamais
    remplacees par une vraie colonne (il n'y a pas de "dossier des images").
    `title` (le titre REEL, cle de style) est TOUJOURS PREVIEW_STACK_TITLE
    pour les 2 : SEUL l'onglet "Focus" des reglages les controle, jamais
    "Projets"/"Sous-projets" (voir `display_title`, le texte d'entete
    AFFICHE — "Focus Projet"/"Focus Sous-projet" — SEPARE de `title`) — voir
    la remarque de l'utilisateur, "il doit y avoir deux colonnes, une focus
    projet et l'autre focus sous projet, je veux aucune autre entete. a
    savoir que les settings 'focus' doivent controler les deux colonnes".

    En-tete + cadre (fond/bordure/rayon/padding) IDENTIQUES a une vraie
    colonne (voir Column.header/card/_content/column_header_qss/
    column_frame_style) — cette colonne fantome n'avait ni l'un ni l'autre
    jusqu'ici (contrairement a toutes les autres) — voir la remarque de
    l'utilisateur, "formate les comme toutes les autres colonnes ... il
    n'y a pas d'espace avec les autres colonnes, la couleur de fond
    derriere la colonne n'est pas bonne" (a propos du gros apercu image
    empile de Projets/Sous-projet une fois une selection faite) : sans un
    VRAI self.card retreci par le Padding (voir refresh_header), self
    peignait deja C['void'] sur la totalite de son rect, y compris la
    marge de padding — rendant ce retrait invisible (aucun contraste de
    couleur) et laissant voir C['void'] au lieu de C['window'] la ou une
    vraie colonne revele le fond de la fenetre."""

    def __init__(self, title: str, parent=None, on_toggle=None,
                 user_width: int | None = None, on_resize=None, fit_height: bool = False,
                 display_title: str | None = None):
        super().__init__(parent)
        self.column_title = title
        # `display_title` (texte de l'entete, ex. "Focus Projet"/"Focus
        # Sous-projet") : SEPARE de `title`/self.column_title (la cle de
        # STYLE — voir column_style_for/column_header_qss/column_frame_
        # style, toujours PREVIEW_STACK_TITLE pour les 2 colonnes Focus) —
        # voir la remarque de l'utilisateur, "je veux aucune autre entete
        # ... les settings 'focus' doivent controler les deux colonnes" :
        # un SEUL style ("Focus") pour les 2, mais un texte d'entete
        # DIFFERENT par colonne pour les distinguer visuellement.
        self.has_thumbnails = False
        # Hauteur reduite au CONTENU (voir _fit_height_to_content), au lieu
        # de s'etirer jusqu'en bas de la fenetre — SEULEMENT pour le role 1
        # (vignettes Focus, voir PipelineBrowser.update_preview_stack) : le
        # role 2 ("Fichiers pour X", fantome de "Logiciels") doit continuer
        # a remplir toute la hauteur disponible, comme la vraie colonne
        # qu'il remplace — voir la remarque de l'utilisateur, "Reduire les
        # colonnes en hauteur".
        self._fit_height = fit_height
        # Largeur choisie a la main (glisser le bord droit, voir resize_
        # begin/update/end plus bas) — SESSION SEULEMENT, jamais ecrite sur
        # le disque (meme convention que Column._user_width) : `user_width`
        # est fourni par l'appelant (PipelineBrowser, qui le conserve d'un
        # appel a l'autre puisque cette colonne est RECONSTRUITE a chaque
        # update_preview_stack — voir sa remarque), `on_resize(new_width)`
        # le lui renvoie a chaque glisser pour qu'il survive a la
        # prochaine reconstruction — voir la remarque de l'utilisateur,
        # "je veux pouvoir controler la largeur des colonnes focus projet
        # et sous projet en slidant les bords de celles-ci".
        self._user_width = user_width
        self._on_resize = on_resize
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)

        # header (exterieur, hauteur/padding EFFECTIFS, voir refresh_header)
        # ET header_fill (interieur, voir plus bas) recoivent aussi
        # setMouseTracking(True) explicitement (MEME correctif/MEME raison
        # que _PreviewBlock.install_resize_filter ci-dessous) : sans lui, le
        # survol pur (sans bouton enfonce) de l'entete ne generait jamais de
        # MouseMove, donc jamais d'appel a l'eventFilter installe dessus —
        # le curseur ne changeait jamais en fleche de redimensionnement.
        # enveloppe header_fill (interieur, fond/rayon/cadre CONFIGURABLE de
        # column_header_qss) — EXACTEMENT la meme construction que Column.
        header = QWidget()
        header.setObjectName("PreviewColumnHeaderOuter")
        header.setFixedHeight(scaled(HEADER_HEIGHT))
        self.header = header
        header_outer_layout = QVBoxLayout(header)
        pad = scaled(HEADER_PADDING, 0)
        header_outer_layout.setContentsMargins(pad, pad, pad, pad)
        header_outer_layout.setSpacing(0)

        header_fill = QWidget()
        header_fill.setObjectName("PreviewColumnHeader")
        header_fill.setStyleSheet(column_header_qss("PreviewColumnHeader", title))
        self.header_fill = header_fill
        self.title_label = QLabel(display_title or title)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        header_layout = QHBoxLayout(header_fill)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_outer_layout.addWidget(header_fill)

        self.preview_layout = QVBoxLayout()
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(0)

        # self.card/self._inner : MEME structure a 2 niveaux que Column.card/
        # Column._content (voir leurs remarques respectives, et DetailPanel.
        # card/_inner, MEME principe applique la en premier) — self.card
        # porte le fond/la bordure/le rayon REELS, self._inner (en-tete +
        # apercu empile) est decoupe a sa silhouette arrondie EXACTE.
        inner_layout = QVBoxLayout()
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addWidget(header)
        inner_layout.addLayout(self.preview_layout)
        inner_layout.addStretch(1)
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._inner_effect = _RoundedCornersEffect(self._inner)
        self._inner.setGraphicsEffect(self._inner_effect)
        self._inner.setLayout(inner_layout)

        self.card = _ColumnCard()
        self.card.setObjectName("PreviewColumnCard")
        self._card_effect = _RoundedCornersEffect(self.card)
        self.card.setGraphicsEffect(self._card_effect)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste a l'epaisseur de bordure
        card_layout.setSpacing(0)
        card_layout.addWidget(self._inner)
        self._card_layout = card_layout

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste au Padding
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.card)
        self._outer_layout = outer_layout

        # Icone de repli/depli de Type/Projets/Sous-projet (voir
        # PipelineBrowser._toggle_project_columns) : seulement sur la
        # colonne PERMANENTE des vignettes (image_preview_column), pas sur
        # le fantome "Logiciels". Flottante (enfant direct de `self`, HORS
        # de `self.card`) plutot que dans l'en-tete : elle se superpose au
        # coin superieur gauche du 1er bloc empile, SOUS l'en-tete (voir
        # refresh_header, qui repositionne son ancrage a chaque changement
        # de hauteur/padding d'en-tete OU de Padding de colonne).
        self.toggle_btn = None
        if on_toggle is not None:
            self.toggle_btn = IconButton(
                "dchevron_right", role_color("buttons", "#c4cacf"), C["text"], parent=self
            )
            self.toggle_btn.setCursor(Qt.ArrowCursor)
            self.toggle_btn.setFlat(True)
            self.toggle_btn.setToolTip("Replier les colonnes de set")
            # Taille/fond/bordure/police-ou-icone : voir refresh_toggle_
            # style (Colonnes > Apercu > Bouton repliement) — voir la
            # remarque de l'utilisateur, "ajouter les settings de style du
            # bouton repliement".
            self.toggle_btn.clicked.connect(on_toggle)
            self.toggle_btn.raise_()

        # Largeur PAR DEFAUT (tant que l'utilisateur n'a pas encore glisse
        # son bord, voir _user_width ci-dessus) : pour le fantome "Fichiers
        # pour X" (role 2, title="Logiciels"), elle occupe la place REELLE
        # de "Logiciels" avant que cette colonne existe pour de vrai, donc
        # suit son reglage — INCHANGE. Pour la colonne des vignettes Focus
        # (role 1, title=PREVIEW_STACK_TITLE), elle n'a RIEN a voir avec
        # "Logiciels" (une colonne potentiellement large, pensee pour des
        # noms de fichiers) : caler sa largeur dessus la rendait bien trop
        # large "de base" (largeur de l'image comprise, puisqu'elle suit
        # desormais la largeur de colonne, voir _PreviewBlock.apply_width)
        # — voir la remarque de l'utilisateur, "pourquoi de base tu fait
        # une image aussi grande!!!!!!! ... je veux ... la largeur de
        # l'image egale a la largeur de la colonne [Projets/Sous-projet]".
        # col_width("Logiciels") : largeur DEJA reglee par l'utilisateur pour
        # la colonne dont ce bloc reprend le contenu, un repere bien plus
        # sense qu'une colonne sans rapport. Pour PREVIEW_STACK_TITLE, sa
        # PROPRE largeur par defaut (voir settings_window.DEFAULT_SETTINGS.
        # item_column_width, surchargeable dans Colonnes > Focus, MEME
        # mecanisme general/surcharge que Colonnes > Type/Projets/Sous-
        # projets, resolu par apply_all_settings dans column_style_for
        # (PREVIEW_STACK_TITLE)) — plus calee sur col_width("Projets"), qui
        # n'a plus aucun rapport depuis que cette colonne a son propre
        # reglage — voir la remarque de l'utilisateur, "tu as oublie
        # l'overide des colonnes focus".
        if title == "Logiciels":
            default_width = col_width("Logiciels")
        else:
            default_width = scaled(int(column_style_for(PREVIEW_STACK_TITLE).get("item_column_width") or 180))
        self.setFixedWidth(self._user_width or default_width)
        # self ne peint plus rien lui-meme desormais (voir self.card
        # ci-dessus, EXACTEMENT le meme principe que Column/DetailPanel).
        self.setObjectName("PreviewColumn")
        self.setStyleSheet("#PreviewColumn { background: transparent; }")
        self.header.setMouseTracking(True)
        self.header.installEventFilter(self)
        # self.card couvre TOUTE la surface de self (outer_layout, marges a
        # 0) : les zones NON couvertes par un bloc empile (espacement entre
        # blocs, marge sous le dernier bloc) sont donc en realite survolees
        # via self.card, pas via self directement — sans son propre
        # setMouseTracking(True), le survol de ces zones ne generait aucun
        # MouseMove, ni sur self.card (jamais filtre de toute facon) ni sur
        # self (masque dessous) : la bordure semblait "trouee" par endroits.
        self.card.setMouseTracking(True)
        self.card.installEventFilter(self)
        self.refresh_header()
        self.refresh_colors()

    def _in_resize_zone(self, x: int) -> bool:
        """MEME convention que Column._in_resize_zone (bord DROIT) — voir
        sa docstring."""
        return self.width() - COLUMN_RESIZE_MARGIN <= x <= self.width()

    def resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        _show_resize_width(self, self.width())

    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self._user_width = new_width
        self.setFixedWidth(new_width)
        self._relayout_blocks()
        if self._on_resize is not None:
            self._on_resize(new_width)
        _show_resize_width(self, new_width)

    def resize_end(self):
        self._resizing = False
        _hide_resize_width(self)
        # Les colonnes Focus (empilees Projets/Sous-projet) n'ont pas de
        # bouton punaise (pas de Column/dossier unique auquel s'accrocher)
        # mais doivent neanmoins s'enregistrer automatiquement — voir la
        # remarque de l'utilisateur, "les seules colonnes dont les
        # parametres sont enregistrees automatiquement sont : colonne type,
        # colonnes focus, colonne inspecteur".
        _persist_column_width(self.window(), PREVIEW_STACK_TITLE, self.width())

    def set_width_external(self, new_width: int):
        """Applique une largeur decidee AILLEURS (voir PipelineBrowser.
        _on_preview_column_resized) : les colonnes Projets/Sous-projet de
        l'apercu Focus sont des colonnes SEPAREES (voir set_preview_block)
        mais doivent rester alignees a la MEME largeur, empilees dans un
        seul conteneur vertical — glisser le bord de L'UNE d'elles doit
        donc repercuter la meme largeur sur les AUTRES, MEME MECANISME que
        resize_update mais sans geste souris propre a CETTE instance — voir
        la remarque de l'utilisateur, "deux colonnes separees, une en
        dessous de l'autre"."""
        self._user_width = new_width
        self.setFixedWidth(new_width)
        self._relayout_blocks()

    def _relayout_blocks(self):
        """Recalcule la largeur/hauteur de l'image de chaque _PreviewBlock
        empile pour la largeur COURANTE de cette colonne (voir _PreviewBlock.
        apply_width) — appele a CHAQUE glisser de bordure, pas seulement au
        relachement, pour un retour visuel immediat (meme principe que
        Column.resize_update/_throttled_layout) — voir la remarque de
        l'utilisateur, "la largeur des images de ces colonnes doit etre
        egale a cette largeur de colonne"."""
        self._outer_layout.activate()
        # outer_layout.activate() seul ne resout QUE la geometrie de
        # self.card (son enfant DIRECT) — self._inner, imbrique un niveau
        # plus loin (DANS self.card, voir card_layout), garde sinon la
        # taille par defaut de Qt pour un widget jamais encore affiche
        # (640x480 — voir la remarque de l'utilisateur, capture a l'appui,
        # "pourquoi de base tu fait une image aussi grande!!!!!", ce widget
        # geant 640px de large etait la cause reelle) tant qu'aucun
        # evenement resize n'a encore ete traite pour de vrai — activer
        # EXPLICITEMENT card_layout en plus le force a se mettre a jour
        # tout de suite, sans attendre un passage par la boucle d'evenements.
        self._card_layout.activate()
        content_width = self._inner.width() - 1
        for i in range(self.preview_layout.count()):
            block = self.preview_layout.itemAt(i).widget()
            if isinstance(block, _PreviewBlock):
                block.apply_width(content_width)
        # La hauteur de chaque bloc peut changer avec sa largeur (le Ratio
        # deduit la hauteur de l'image de la largeur, voir _PreviewBlock.
        # apply_width) : la hauteur totale de la colonne doit suivre en
        # direct pendant le glisser, pas seulement au relachement — voir
        # _fit_height_to_content.
        self._fit_height_to_content()

    def eventFilter(self, obj, event):
        """MEME mecanique que Column.eventFilter (voir sa docstring/
        remarque de tete) : installe sur self.header ET sur les barres
        pleine-largeur du _PreviewBlock de cette colonne (voir
        set_preview_block) — sans cela, ces widgets ENFANTS
        interceptent l'evenement souris AVANT que self ne le voie, rendant
        la bordure de redimensionnement inaccessible des que le curseur
        survole un bloc."""
        etype = event.type()
        if etype == QEvent.MouseMove:
            if self._resizing:
                self.resize_update(event.globalPosition().toPoint().x())
                return True
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_x) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._in_resize_zone(local_x):
                self.resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonRelease and self._resizing:
            self.resize_end()
            return True
        elif etype == QEvent.Leave and not self._resizing:
            obj.unsetCursor()
        return False

    def mouseMoveEvent(self, event):
        if self._resizing:
            self.resize_update(event.globalPosition().toPoint().x())
            return
        x = int(event.position().x())
        self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(x) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._in_resize_zone(int(event.position().x())):
            self.resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self.resize_end()
            return
        super().mouseReleaseEvent(event)

    def _suppress_left(self) -> bool:
        """Voir _column_suppress_left (module-level, partagee avec Column)."""
        return _column_suppress_left(self, self.column_title)

    def refresh_header(self):
        """Reapplique hauteur/padding de l'en-tete + bordure/padding du
        cadre — MEME logique que Column.refresh_header (voir sa docstring).
        Repositionne aussi l'icone de repli/depli, dont l'ancrage depend de
        la hauteur d'en-tete ET du Padding (voir _card_layout/outer_layout
        ci-dessous, INCLUS dans son decalage)."""
        s = column_style_for(self.column_title)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", HEADER_HEIGHT))
        padding = int(s.get("header_padding", HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/taille du titre (voir Column.refresh_header,
        # MEME logique/MEMES cles — bug corrige au passage, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette colonne fantome N'APPLIQUAIT
        # JAMAIS ces surcharges (header_font_color/family/bold/italic/
        # taille), malgre son propre onglet de surcharge Colonnes > Focus.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.title_label.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.title_label.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")
        # PAS de stylesheet explicite sur self.header : transparent par
        # defaut, la marge du Padding d'entete revele donc deja le fond de
        # self.card (column_bg_color, voir refresh_colors/_paint_bordered_
        # rect) — UNE SEULE couleur de fond pour toute la colonne (voir
        # PLUS de reglage "Zone titre > Fond" separe, source de confusion —
        # _PreviewBlock utilise desormais cette MEME couleur) — voir la
        # remarque de l'utilisateur, "voici la couleur a appliquer sur les
        # zones avec des croix".

        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._card_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        col_pad = dict(column_padding_for(self.column_title))
        if suppress_left:
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()
        if self.toggle_btn is not None:
            # Position EXPLICITE (X/Y depuis le coin superieur GAUCHE de la
            # colonne, voir Colonnes > Apercu > Bouton repliement) — voir
            # la remarque de l'utilisateur, "supprime le padding mais
            # ajoute un parametre de position par rapport au coin
            # superieur gauche de la colonne en x et en y" (remplace
            # l'ancien ancrage automatique sous l'en-tete, fige a 8px).
            pos_x = scaled(int(s.get("preview_toggle_x", 8)), 0)
            pos_y = scaled(int(s.get("preview_toggle_y", 34)), 0)
            self.toggle_btn.move(self.card.x() + pos_x, self.card.y() + pos_y)
            self.toggle_btn.raise_()
        if self._fit_height:
            # Reste coherent si l'entete/le cadre changent (ex. echelle
            # d'interface) SANS reconstruction complete de la colonne — voir
            # _fit_height_to_content, meme raison.
            self._fit_height_to_content()

    def _update_card_mask(self):
        """MEME mecanisme que Column._update_card_mask (voir sa docstring)."""
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        self._card_effect.setEnabled(self.card._thickness <= 0)
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._inner_effect.setRadius(_radius_dict(inner_radius))
        self._inner_effect.setEnabled(self.card._thickness > 0)

    def refresh_colors(self):
        self.header_fill.setStyleSheet(column_header_qss("PreviewColumnHeader", self.column_title))
        # PAS de reapplication de self.title_label ici — voir Column.
        # refresh_colors, MEME correctif/MEME raison (refresh_header,
        # toujours appele AVANT, gere deja ce style correctement).
        frame = column_frame_style(self.column_title, self._suppress_left())
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        # Meme couleur que le CADRE (frame["bg"], "Couleur de fond" de
        # Colonnes > Focus > Colonnes) sur self LUI-MEME (pas seulement
        # self.card) : sans ca, la marge de Padding autour de la carte
        # (voir refresh_header/_outer_layout) revelait le fond de la
        # FENETRE au lieu de cette couleur — voir la remarque de
        # l'utilisateur, "la couleur de fond doit aussi controler les
        # zones avec la croix rouge sur le screenshot et la zone sous
        # l'entete".
        self.setStyleSheet(f"#PreviewColumn {{ background: {frame['bg']}; }}")
        self._update_card_mask()
        if self.toggle_btn is not None:
            self.toggle_btn.set_colors(role_color("buttons", "#c4cacf"), C["text"])
            self.refresh_toggle_style()

    def refresh_toggle_style(self):
        """Colonnes > Apercu > Bouton repliement (taille/fond/bordure/
        rayon) — voir la remarque de l'utilisateur, "ajouter les settings
        de style du bouton repliement : taille bouton, hauteur, largeur
        ... border ... couleur fond". Remplace l'ancien QSS fixe
        (rgba(15,17,20,150), rayon 4px en dur, 22x22 fige). Toujours
        l'icone dessinee a la main (voir la remarque de l'utilisateur,
        "supprime police ou icone ... supprime image personnalisee") — la
        position (voir refresh_header) est, elle, EXPLICITE (X/Y depuis le
        coin superieur gauche de la colonne), plus un padding implicite."""
        if self.toggle_btn is None:
            return
        s = column_style_for(self.column_title)
        w = scaled(int(s.get("preview_toggle_width", 22)))
        h = scaled(int(s.get("preview_toggle_height", 22)))
        self.toggle_btn.setFixedSize(max(1, w), max(1, h))
        radius = _radius_dict(scaled(int(s.get("preview_toggle_radius", 4)), 0))
        enabled = _coerce_side_enabled(s.get("preview_toggle_border_enabled", False))
        colors = {k: resolve_color_ref(v) for k, v in (s.get("preview_toggle_border") or {}).items()}
        thickness = scaled(int(s.get("preview_toggle_border_thickness", 1)), 0)
        bg = resolve_color_ref(s.get("preview_toggle_bg_color", "#960f1114"))
        self.toggle_btn.set_frame_style(bg, enabled, colors, thickness, radius)

    def set_toggle_state(self, collapsed: bool):
        """Met a jour l'icone (voir __init__, `on_toggle`) apres un repli/
        depli des colonnes de set declenche depuis ailleurs (par exemple
        automatiquement, voir PipelineBrowser._sync_collapse_state) — sans
        effet si cette instance n'a pas d'icone (fantome "Logiciels")."""
        if self.toggle_btn is None:
            return
        self.toggle_btn.set_kind("dchevron_left" if collapsed else "dchevron_right")
        self.toggle_btn.setToolTip(
            "Deplier les colonnes de set" if collapsed else "Replier les colonnes de set"
        )

    def _clear_preview_layout(self):
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _content_width(self) -> int:
        # self._inner.width() (PAS self.width()) : le Padding/la bordure de
        # self.card (voir refresh_header) retrecissent desormais le
        # contenu reel sous self — utiliser self.width() ici carrerait le
        # contenu sur la largeur TOTALE de la colonne fantome, deborderait
        # du cadre des que Padding/Bordure sont actifs.
        self._outer_layout.activate()
        # outer_layout.activate() seul ne resout QUE la geometrie de
        # self.card — self._inner (imbrique un niveau plus loin, dans
        # card_layout) garde sinon la taille par defaut de Qt pour un
        # widget jamais encore affiche (640x480, voir _relayout_blocks,
        # MEME correctif/MEME raison) tant qu'aucun resizeEvent reel n'a
        # encore ete traite — d'ou des images DEMESUREES a la toute
        # premiere construction (avant le moindre glisser de bordure) —
        # voir la remarque de l'utilisateur, capture a l'appui, "pourquoi
        # de base tu fait une image aussi grande!!!!!".
        self._card_layout.activate()
        return self._inner.width() - 1

    def set_preview_block(self, title: str, pixmap: QPixmap, path: Path, open_status, source_column: "Column"):
        """Peuple cette colonne fantome avec UN SEUL niveau d'apercu (voir
        _PreviewBlock) — cette colonne EST "Projets" ou "Sous-projet" a
        elle seule (self.column_title, passe a la construction, voir
        PipelineBrowser.update_preview_stack), avec sa PROPRE entete
        REELLE (self.header, deja construite dans __init__ a partir de ce
        meme titre) — DEUX colonnes fantomes SEPAREES (chacune son propre
        cadre/bordure/entete), empilees VERTICALEMENT dans un conteneur
        commun (voir PipelineBrowser._preview_stack_wrapper), PAS cote a
        cote et PAS fusionnees en une seule — voir la remarque de
        l'utilisateur, "non, tu as merger les deux colonnes en une seule,
        ce que je veux c'est deux colonnes separees, une en dessous de
        l'autre !". `source_column` (voir _PreviewBlock._rename/
        update_preview_stack) : la VRAIE colonne de navigation dont ce
        bloc reprend la selection courante."""
        self._clear_preview_layout()
        block = _PreviewBlock(title, pixmap, self._content_width(), path, open_status, source_column)
        # Sans ceci, la bordure de redimensionnement (voir resize_begin/
        # _in_resize_zone) est inaccessible a la souris des qu'elle
        # survole ce bloc (voir install_resize_filter).
        block.install_resize_filter(self)
        self.preview_layout.addWidget(block)
        # Ce bloc est, par defaut, empile PAR-DESSUS l'icone flottante
        # (creee avant lui, voir __init__) : la remonter au premier plan a
        # chaque reconstruction, sinon elle disparait derriere le bloc des
        # que set_preview_block est rappelee.
        if self.toggle_btn is not None:
            self.toggle_btn.raise_()
        self._fit_height_to_content()

    def _fit_height_to_content(self):
        """Hauteur reduite au CONTENU reel (entete + blocs empiles), au
        lieu de s'etirer jusqu'en bas de la fenetre comme les vraies
        colonnes (qui, elles, ont une liste a faire defiler jusqu'au bout
        de l'espace disponible) — voir la remarque de l'utilisateur,
        "Reduire les colonnes en hauteur". self.header/chaque bloc empile
        ont deja leur PROPRE hauteur FIXEE explicitement (setFixedHeight) :
        pas besoin d'activer quoi que ce soit pour les lire, contrairement
        a une largeur (voir _content_width, MEME distinction que le
        correctif du bug 640x480)."""
        content_height = self.header.height() + sum(
            self.preview_layout.itemAt(i).widget().height()
            for i in range(self.preview_layout.count())
        )
        card_margins = self._card_layout.contentsMargins()
        outer_margins = self._outer_layout.contentsMargins()
        self.setFixedHeight(
            content_height + card_margins.top() + card_margins.bottom()
            + outer_margins.top() + outer_margins.bottom()
        )

def read_text_preview(path: Path) -> str | None:
    """Debut du contenu de `path` (voir TEXT_PREVIEW_EXTENSIONS), pour
    affichage brut dans l'inspecteur (voir DetailPanel.show_path). Lit au
    plus TEXT_PREVIEW_MAX_BYTES sur le disque (fichier potentiellement
    enorme, pas besoin de plus pour un apercu), puis tronque a
    TEXT_PREVIEW_MAX_LINES. None si illisible ou visiblement binaire (octet
    nul dans les premiers kilo-octets)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(TEXT_PREVIEW_MAX_BYTES)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    truncated_bytes = len(raw) >= TEXT_PREVIEW_MAX_BYTES
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = truncated_bytes or len(lines) > TEXT_PREVIEW_MAX_LINES
    lines = lines[:TEXT_PREVIEW_MAX_LINES]
    if truncated:
        lines.append("…")
    return "\n".join(lines)


def pur_embedded_image_ranges(path: Path, mtime: float | None = None) -> list[tuple[int, int, str]]:
    """Indexe les JPEG/PNG embarques d'un .pur sans les decoder ni les copier."""
    key = str(path)
    if mtime is None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []
    cached = _PUR_IMAGE_INDEX_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    ranges: list[tuple[int, int, str]] = []
    jpeg_signature = b"\xff\xd8\xff"
    png_signature = b"\x89PNG\r\n\x1a\n"
    try:
        with path.open("rb") as stream:
            if path.stat().st_size == 0:
                return []
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                # PureRef 2.x a change de conteneur : les marqueurs JPEG
                # apparaissent aussi dans des donnees internes et ne
                # delimitent pas des images autonomes. Le premier JPEG de
                # l'en-tete est la vignette valide de la planche.
                header = data[4:96].decode("utf-16-be", errors="ignore")
                if re.search(r"\b2\.\d+", header):
                    start = data.find(jpeg_signature)
                    if start >= 0:
                        eoi = data.find(b"\xff\xd9", start + 3)
                        if eoi >= 0:
                            image = QImage.fromData(data[start:eoi + 2])
                            if not image.isNull():
                                ranges.append((start, eoi + 2, "JPEG"))
                    _bounded_cache_set(_PUR_IMAGE_INDEX_CACHE, key, (mtime, ranges), max_entries=24)
                    return ranges
                position = 0
                size = len(data)
                while position < size and len(ranges) < PUR_MAX_EMBEDDED_IMAGES:
                    jpeg_at = data.find(jpeg_signature, position)
                    png_at = data.find(png_signature, position)
                    candidates = [(offset, fmt) for offset, fmt in ((jpeg_at, "JPEG"), (png_at, "PNG"))
                                  if offset >= 0]
                    if not candidates:
                        break
                    start, fmt = min(candidates)
                    if fmt == "JPEG":
                        eoi = data.find(b"\xff\xd9", start + 3)
                        if eoi < 0:
                            position = start + len(jpeg_signature)
                            continue
                        end = eoi + 2
                    else:
                        # Parcourt la structure PNG jusqu'au chunk IEND pour
                        # ne pas confondre son contenu avec d'autres images.
                        cursor = start + len(png_signature)
                        end = -1
                        while cursor + 12 <= size:
                            chunk_size = int.from_bytes(data[cursor:cursor + 4], "big")
                            chunk_type = data[cursor + 4:cursor + 8]
                            next_chunk = cursor + 12 + chunk_size
                            if next_chunk > size:
                                break
                            if chunk_type == b"IEND":
                                end = next_chunk
                                break
                            cursor = next_chunk
                        if end < 0:
                            position = start + len(png_signature)
                            continue
                    ranges.append((start, end, fmt))
                    position = end
    except (OSError, ValueError):
        return []
    _bounded_cache_set(_PUR_IMAGE_INDEX_CACHE, key, (mtime, ranges), max_entries=24)
    return ranges


def pur_file_major_version(path: Path) -> int | None:
    """Retourne la version du conteneur PureRef depuis son en-tete."""
    try:
        with path.open("rb") as stream:
            header = stream.read(96)
        text = header[4:].decode("utf-16-be", errors="ignore")
        match = re.search(r"^\s*(\d+)\.\d+", text)
        return int(match.group(1)) if match else None
    except OSError:
        return None


class _PureRefExportSignals(QObject):
    progress = Signal(str, float, object)
    finished = Signal(str, float, object, str)


class _PureRefExportTask(QRunnable):
    """Exporte les images d'une planche PureRef 2.x via son CLI officiel."""
    def __init__(self, path: Path, mtime: float):
        super().__init__()
        self.path = path
        self.mtime = mtime
        self.signals = _PureRefExportSignals()

    @staticmethod
    def _running_pids() -> set[int]:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PureRef.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return {int(value) for value in re.findall(r'"PureRef.exe","(\d+)"', result.stdout)}
        except (OSError, subprocess.SubprocessError):
            return set()

    @staticmethod
    def _executable() -> str | None:
        candidates = [
            shutil.which("PureRef.exe"),
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PureRef" / "PureRef.exe"),
            str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "PureRef" / "PureRef.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "PureRef" / "PureRef.exe"),
        ]
        return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)

    def run(self):
        exported: list[str] = []
        error = ""
        launched_pid: int | None = None
        try:
            digest = hashlib.sha256(f"{self.path}|{self.mtime}".encode("utf-8", errors="replace")).hexdigest()
            output_dir = FILE_IMAGE_DISK_CACHE_DIR / "pureref_images" / digest
            cached_files = sorted(output_dir.glob("*.png"), key=lambda item: item.name.casefold()) if output_dir.is_dir() else []
            exported = [str(item) for item in cached_files if item.is_file() and item.stat().st_size > 0]
            complete_marker = output_dir / ".export_complete"
            if exported and complete_marker.is_file():
                self.signals.finished.emit(str(self.path), self.mtime, exported, "")
                return
            executable = self._executable()
            if executable is None:
                raise RuntimeError("PureRef n'est pas installé à un emplacement détectable.")
            before = self._running_pids()
            if before:
                raise RuntimeError("Ferme PureRef pour permettre l'export sans modifier sa scène ouverte.")

            output_dir.mkdir(parents=True, exist_ok=True)
            for old_file in output_dir.iterdir():
                if old_file.is_file():
                    old_file.unlink(missing_ok=True)
            normalized_path = self.path.resolve().as_posix()
            normalized_output = output_dir.resolve().as_posix()
            command = [
                executable,
                "-c", f"load;{normalized_path}",
                "-c", f"exportImages;{normalized_output};false;%2",
            ]
            startup_info = None
            if os.name == "nt":
                startup_info = subprocess.STARTUPINFO()
                startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup_info.wShowWindow = 0
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True, startupinfo=startup_info)
            launched_pid = process.pid
            deadline = time.monotonic() + 600
            last_signature = None
            stable_since = None
            last_progress_count = 0
            while time.monotonic() < deadline:
                files = sorted(output_dir.glob("*.png"), key=lambda item: item.name.casefold())
                file_stats = [(item, item.stat()) for item in files if item.is_file()]
                signature = tuple((item.name, stat.st_size) for item, stat in file_stats)
                stable_files = [str(item) for item, stat in file_stats
                                if stat.st_size > 0 and time.time() - stat.st_mtime >= 0.75]
                if len(stable_files) > last_progress_count:
                    last_progress_count = len(stable_files)
                    self.signals.progress.emit(str(self.path), self.mtime, stable_files)
                if signature and signature == last_signature:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 3.0:
                        exported = [str(item) for item in files if item.is_file() and item.stat().st_size > 0]
                        complete_marker.touch()
                        break
                else:
                    last_signature = signature
                    stable_since = None
                time.sleep(0.25)
            if not exported:
                raise RuntimeError("PureRef n'a retourné aucune image (délai dépassé ou scène illisible).")
        except Exception as exc:
            error = str(exc)
        finally:
            # Le CLI PureRef reste parfois ouvert après avoir terminé ses
            # commandes. Ne fermer que le PID retourné par notre Popen.
            if launched_pid is not None and launched_pid in self._running_pids():
                try:
                    subprocess.run(["taskkill", "/PID", str(launched_pid), "/T", "/F"],
                                   capture_output=True, timeout=5, check=False)
                except (OSError, subprocess.SubprocessError):
                    pass
        self.signals.finished.emit(str(self.path), self.mtime, exported, error)


_PUR_EXPORT_POOL = QThreadPool()
_PUR_EXPORT_POOL.setMaxThreadCount(1)


def read_pur_embedded_image(path: Path, image_range: tuple[int, int, str]) -> QImage | None:
    """Decode uniquement l'image PureRef selectionnee, pas les autres."""
    start, end, fmt = image_range
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            raw = stream.read(end - start)
    except OSError:
        return None
    image = QImage.fromData(raw)
    if image.isNull():
        return None
    if max(image.width(), image.height()) > 1600:
        image = image.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def read_pur_exported_image(path: Path) -> QImage | None:
    """Charge une image exportee sans decoder sa pleine resolution en memoire."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > 1600:
        scale = 1600 / max(size.width(), size.height())
        reader.setScaledSize(QSize(max(1, round(size.width() * scale)),
                                   max(1, round(size.height() * scale))))
    image = reader.read()
    return None if image.isNull() else image


# ==========================================================================
# Panneau de details
# ==========================================================================

class DetailPanel(QWidget):

    FIELDS = ["kind", "size", "modified", "path"]

    def __init__(self, parent=None):
        super().__init__(parent)
        # objectName + selecteur ID (voir la meme remarque pour #CentralFrame
        # dans PipelineBrowser).
        self.setObjectName("DetailPanel")
        # self ne peint plus rien lui-meme desormais (voir self.card
        # ci-dessous, EXACTEMENT le meme principe que Column.card) — voir la
        # remarque de l'utilisateur, "la colonne inspecteur est differente
        # des autres, je veux exactement le meme style, parametres par
        # parametres" : l'inspecteur suit maintenant Colonnes > Colonnes/
        # Entetes (padding/bordure/rayon par cote, fond, rayon d'entete...)
        # au lieu d'un simple filet de gauche fixe et d'un fond fige sur
        # C['void'] — voir INSPECTOR_TITLE (colonne "virtuelle", toujours
        # generale : aucun onglet de surcharge dedie, comme Logiciels/
        # Contenu).
        self.setStyleSheet("#DetailPanel { background: transparent; }")
        # Largeur fixe par defaut (et non un stretch qui la ferait grandir
        # avec la fenetre) : un inspecteur qui s'etire jusqu'a occuper tout
        # l'espace restant laisse un vide enorme autour de son contenu des
        # que la fenetre est large. Restee ajustable a la souris (voir
        # mousePressEvent) comme n'importe quelle colonne, via ce meme filet
        # de gauche.
        self.setFixedWidth(DETAIL_PANEL_WIDTH)
        self.setMouseTracking(True)
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0

        # En-tete identique dans l'esprit a celui des colonnes (voir Column) :
        # meme hauteur/fond/police, pour que l'inspecteur se lise comme une
        # colonne de plus plutot que comme un panneau a part. Le badge a
        # droite reprend le type de l'element selectionne (voir show_path).
        # header (exterieur, hauteur/padding EFFECTIFS, voir refresh_header)
        # enveloppe header_fill (interieur, fond/rayon/cadre CONFIGURABLE de
        # column_header_qss) — meme separation exterieur/interieur que
        # Column.header, voir sa remarque.
        header = QWidget()
        header.setObjectName("DetailHeaderOuter")
        header.setFixedHeight(scaled(HEADER_HEIGHT))
        self.header = header
        header_outer_layout = QVBoxLayout(header)
        pad = scaled(HEADER_PADDING, 0)   # 0 = valeur reglee valide (voir scaled)
        header_outer_layout.setContentsMargins(pad, pad, pad, pad)
        header_outer_layout.setSpacing(0)

        header_fill = QWidget()
        header_fill.setObjectName("DetailHeader")
        header_fill.setStyleSheet(column_header_qss("DetailHeader", INSPECTOR_TITLE))
        self.header_fill = header_fill
        self.header_title = QLabel("Inspecteur")
        self.header_title.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.header_title.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        self.badge = QLabel("")
        self.badge.setFont(role_font("info", 9, 600, tracking=0.6, caps=True))
        self.badge.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        header_layout = QHBoxLayout(header_fill)
        self._header_layout = header_layout
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.header_title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.badge)
        header_outer_layout.addWidget(header_fill)

        self.name = QLabel("")
        self.name.setFont(role_font("folders", 12, 600, tracking=0.12))
        self.name.setStyleSheet(f"color: {role_color('folders', C['text'])}; background: transparent;")
        self.name_row = QWidget()
        name_row_layout = QHBoxLayout(self.name_row)
        name_row_layout.setContentsMargins(0, 0, 0, 0)
        name_row_layout.setSpacing(6)
        name_row_layout.addWidget(self.name, 1)
        self.open_render_log_button = QPushButton("Ouvrir le journal")
        self.open_render_log_button.setToolTip("Ouvrir le journal des rendus automatiques")
        self.open_render_log_button.setCursor(Qt.PointingHandCursor)
        self.open_render_log_button.setFixedHeight(scaled(24))
        self.open_render_log_button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            f"border-radius: 3px; padding: 0 7px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
        )
        self.open_render_log_button.clicked.connect(self.open_preview_render_log)
        name_row_layout.addWidget(self.open_render_log_button)

        self.pur_navigation = QWidget()
        pur_nav_layout = QHBoxLayout(self.pur_navigation)
        pur_nav_layout.setContentsMargins(0, 0, 0, 0)
        pur_nav_layout.setSpacing(6)
        self.pur_previous_button = QPushButton("‹")
        self.pur_next_button = QPushButton("›")
        for button in (self.pur_previous_button, self.pur_next_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(scaled(28), scaled(24))
            button.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; font-size: 16px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
                f"QPushButton:disabled {{ color: {C['dim']}; }}"
            )
        self.pur_image_counter = QLabel("")
        self.pur_image_counter.setAlignment(Qt.AlignCenter)
        self.pur_image_counter.setStyleSheet(
            f"color: {role_color('info', '#aab1b6')}; background: transparent;"
        )
        pur_nav_layout.addStretch(1)
        pur_nav_layout.addWidget(self.pur_previous_button)
        pur_nav_layout.addWidget(self.pur_image_counter)
        pur_nav_layout.addWidget(self.pur_next_button)
        pur_nav_layout.addStretch(1)
        self.pur_navigation.hide()
        self.pur_previous_button.clicked.connect(lambda: self._navigate_pur_image(-1))
        self.pur_next_button.clicked.connect(lambda: self._navigate_pur_image(1))

        self.well = QFrame()
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.well.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.well.setStyleSheet(
            f"background: {C['well']}; border: 1px solid #282c30;"
        )
        self._preview_pixmap: QPixmap | None = None
        self._preview_request_path: str | None = None
        self._current_path: str | None = None
        self._pur_image_path: str | None = None
        self._pur_image_ranges: list[tuple[int, int, str]] = []
        self._pur_exported_images: list[str] = []
        self._pur_export_task: _PureRefExportTask | None = None
        self._pur_image_index = 0
        self._preview_generation_paths: set[str] = set()
        self._auto_preview_paths: set[str] = set()
        self._auto_preview_log_count = 0
        self.well_label = QLabel(self.well)
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        self.preview_info_table = _TableFrame()
        self.preview_info_table.setFixedHeight(96)
        self._preview_info_cell_layouts = []
        info_layout = QGridLayout(self.preview_info_table)
        info_layout.setContentsMargins(1, 1, 1, 1)
        info_layout.setSpacing(0)
        info_layout.setHorizontalSpacing(1)
        info_layout.setVerticalSpacing(1)
        for column in range(3):
            info_layout.setColumnStretch(column, 1)
        self.preview_dimensions_value = QLabel("—")
        self.preview_dimensions_value.setObjectName("PreviewInfoValue")
        self.preview_dimensions_value.setWordWrap(True)
        self.preview_log = QPlainTextEdit(self.well)
        self.preview_log.setReadOnly(True)
        self.preview_log.setFrameShape(QFrame.NoFrame)
        self.preview_log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview_log.setMaximumBlockCount(1200)
        self.preview_log.setFont(font(9, 400, mono=True, smoothing="none"))
        self.preview_log.setStyleSheet(
            "QPlainTextEdit { background: transparent; color: #00ff00; border: none; padding: 5px; }"
        )
        well_layout = QVBoxLayout(self.well)
        well_layout.setContentsMargins(0, 0, 0, 0)
        well_layout.setSpacing(0)
        well_layout.addWidget(self.well_label)
        well_layout.addWidget(self.preview_log)
        self.preview_log.hide()
        self.preview_progress = QWidget(self.well)
        progress_layout = QVBoxLayout(self.preview_progress)
        progress_layout.setContentsMargins(18, 14, 18, 14)
        progress_layout.setSpacing(8)
        self.preview_progress_label = QLabel("Génération de l’aperçu…")
        self.preview_progress_label.setAlignment(Qt.AlignCenter)
        self.preview_progress_label.setStyleSheet(
            f"color: {role_color('info', '#aab1b6')}; background: transparent; border: none;"
        )
        self.preview_progress_bar = QProgressBar()
        self.preview_progress_bar.setRange(0, 0)
        self.preview_progress_bar.setTextVisible(False)
        self.preview_progress_bar.setFixedHeight(5)
        self.preview_progress_bar.setStyleSheet(
            "QProgressBar { background: #282c30; border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background: #7fa8cf; border-radius: 2px; }"
        )
        progress_layout.addWidget(self.preview_progress_label)
        progress_layout.addWidget(self.preview_progress_bar)
        self.preview_progress.hide()
        well_layout.addWidget(self.preview_progress)
        _PREVIEW_DECODE_MANAGER.started.connect(self._on_preview_generation_started)
        _PREVIEW_DECODE_MANAGER.progress.connect(self._on_preview_generation_progress)
        _PREVIEW_DECODE_MANAGER.ready.connect(self._on_3d_preview_ready)

        # Extrait de contenu pour les fichiers texte/code (voir
        # TEXT_PREVIEW_EXTENSIONS/read_text_preview) : remplace le "well"
        # image le temps de l'affichage, jamais les deux a la fois (voir
        # show_path). Widget distinct plutot qu'un simple QLabel dans
        # `well` : un QPlainTextEdit sait faire defiler un texte plus long
        # que la hauteur disponible, ce qu'un QLabel ne fait pas.
        self.text_preview = QPlainTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setFrameShape(QFrame.NoFrame)
        self.text_preview.setFixedHeight(TEXT_PREVIEW_PANEL_HEIGHT)
        self.text_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_preview.setFont(font(10, 400, mono=True))
        self.text_preview.setStyleSheet(
            f"QPlainTextEdit {{ background: {C['well']}; color: {role_color('info', '#aab1b6')};"
            f" border: 1px solid #282c30; padding: 6px; }}"
        )
        self.text_preview.hide()

        # Lecture (silencieuse, en boucle) des videos selectionnees : plutot
        # que la frame figee de file_image_pixmap (toujours utilisee comme
        # vignette dans les colonnes, ou tant que la lecture n'a pas
        # demarre). Widget distinct du "well" : QVideoWidget a besoin de sa
        # propre surface de rendu, jamais affiche en meme temps que well/
        # text_preview (voir show_path/_stop_video).
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: black; border: 1px solid #282c30;")
        self.video_widget.hide()
        self._video_player = QMediaPlayer(self)
        self._video_audio = QAudioOutput(self)
        self._video_audio.setMuted(True)
        self._video_player.setAudioOutput(self._video_audio)
        self._video_player.setVideoOutput(self.video_widget)
        self._video_player.setLoops(QMediaPlayer.Loops.Infinite)

        self.values: dict[str, QLabel] = {}
        self.key_labels: dict[str, QLabel] = {}
        for key in self.FIELDS:
            key_label = QLabel(key.upper())
            key_label.setObjectName("PreviewInfoHeading")
            key_label.setFont(role_font("info", 9, 600))
            self.key_labels[key] = key_label
            value = QLabel("")
            value.setObjectName("PreviewInfoValue")
            value.setFont(role_font("info", 11, 400))
            value.setWordWrap(True)
            self.values[key] = value

        def add_info_cell(key: str, row: int, column: int, column_span: int = 1):
            cell = QWidget(self.preview_info_table)
            cell.setStyleSheet(f"background: {M['table_row_a']};")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(6, 3, 6, 3)
            cell_layout.setSpacing(1)
            self._preview_info_cell_layouts.append(cell_layout)
            cell_layout.addWidget(self.key_labels[key])
            cell_layout.addWidget(self.values[key])
            info_layout.addWidget(cell, row, column, 1, column_span)

        add_info_cell("kind", 0, 0)
        add_info_cell("size", 0, 1)
        add_info_cell("modified", 0, 2)
        add_info_cell("path", 1, 0, 2)
        dimensions_cell = QWidget(self.preview_info_table)
        dimensions_cell.setStyleSheet(f"background: {M['table_row_a']};")
        dimensions_layout = QVBoxLayout(dimensions_cell)
        dimensions_layout.setContentsMargins(6, 3, 6, 3)
        dimensions_layout.setSpacing(1)
        self._preview_info_cell_layouts.append(dimensions_layout)
        self.preview_dimensions_heading = QLabel("DIMENSIONS · RATIO · TAILLE")
        self.preview_dimensions_heading.setObjectName("PreviewInfoHeading")
        self.preview_dimensions_heading.setFont(role_font("info", 9, 600))
        dimensions_heading_row = QHBoxLayout()
        dimensions_heading_row.setContentsMargins(0, 0, 0, 0)
        dimensions_heading_row.setSpacing(5)
        dimensions_heading_row.addWidget(self.preview_dimensions_heading)
        dimensions_heading_row.addStretch(1)
        self.preview_stale_badge = QLabel("PÉRIMÉ")
        self.preview_stale_badge.setFont(role_font("info2", 8, 700))
        self.preview_stale_badge.setToolTip("Aperçu conservé en attendant sa régénération")
        self.preview_stale_badge.setStyleSheet(
            "color: #1d1608; background: #e5b85c; border-radius: 2px; padding: 1px 5px;"
        )
        self.preview_stale_badge.hide()
        dimensions_heading_row.addWidget(self.preview_stale_badge)
        dimensions_layout.addLayout(dimensions_heading_row)
        dimensions_layout.addWidget(self.preview_dimensions_value)
        info_layout.addWidget(dimensions_cell, 1, 2)
        info_layout.setRowStretch(0, 1)
        info_layout.setRowStretch(1, 1)
        self._apply_preview_table_style()

        content = QVBoxLayout()
        self._content_layout = content
        content.setContentsMargins(16, 14, 16, 14)
        content.setSpacing(8)
        content.addWidget(self.name_row)
        content.addWidget(self.preview_info_table)
        content.addWidget(self.pur_navigation)
        content.addWidget(self.well, 1)
        content.addWidget(self.text_preview)
        content.addWidget(self.video_widget)

        # self.card/self._inner : MEME structure a 2 niveaux que Column.card/
        # Column._content (voir leurs remarques respectives) — self.card
        # porte le fond/la bordure/le rayon REELS (_ColumnCard, peints a la
        # main via _paint_bordered_rect, voir refresh_colors), self._inner
        # (entete + contenu) est decoupe a sa silhouette arrondie EXACTE
        # (double QGraphicsEffect, voir _update_card_mask) — necessaire pour
        # les MEMES raisons que Column (Qt ne clippe jamais automatiquement
        # des enfants au rayon QSS de leur parent).
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._inner_effect = _RoundedCornersEffect(self._inner)
        self._inner.setGraphicsEffect(self._inner_effect)
        inner_layout = QVBoxLayout(self._inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addWidget(header)
        inner_layout.addLayout(content, 1)

        self.card = _ColumnCard()
        self.card.setObjectName("DetailPanelCard")
        self._card_effect = _RoundedCornersEffect(self.card)
        self.card.setGraphicsEffect(self._card_effect)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste a l'epaisseur de bordure
        card_layout.setSpacing(0)
        card_layout.addWidget(self._inner)
        self._card_layout = card_layout

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste au Padding
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.card)
        self._outer_layout = outer_layout

        # self.card couvre TOUTE la surface de self (outer_layout, marges a
        # 0, voir plus haut) : sans ceci, la bordure GAUCHE de redimensionnement
        # (voir mousePressEvent/mouseMoveEvent ci-dessous) n'etait JAMAIS
        # accessible a la souris — self.card (et self._inner/header par-
        # dessus) interceptait tout mouvement/clic AVANT qu'ils n'atteignent
        # self — voir la remarque de l'utilisateur, "la selection du bord de
        # la colonne inspecteur est toujours aussi peinible a selectionner
        # pour la redimension". MEME mecanique que PreviewColumn.eventFilter
        # (voir sa docstring de tete, MEME correctif deja applique la-bas).
        self.card.setMouseTracking(True)
        self.card.installEventFilter(self)
        self.header.setMouseTracking(True)
        self.header.installEventFilter(self)

        self.clear()
        self.refresh_header()
        self.refresh_colors()

    def refresh_header(self):
        """Reapplique hauteur/padding de l'entete + bordure/padding du cadre
        — MEME logique que Column.refresh_header (voir sa docstring),
        applique ici a l'inspecteur pour la premiere fois — voir la
        remarque de l'utilisateur, "la colonne inspecteur est differente
        des autres, je veux exactement le meme style, parametres par
        parametres". Style EFFECTIF via INSPECTOR_TITLE, TOUJOURS general
        (aucun onglet de surcharge dedie, comme Logiciels/Contenu — voir
        app_style.column_style_for)."""
        s = column_style_for(INSPECTOR_TITLE)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", HEADER_HEIGHT))
        padding = int(s.get("header_padding", HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)   # 0 = valeur reglee valide (voir scaled)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/taille du titre (voir Column.refresh_header,
        # MEME logique/MEMES cles — bug corrige au passage, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette methode n'appliquait jusqu'ici QUE
        # hauteur/padding/bordure, jamais la police/couleur du titre (voir
        # refresh_fonts, qui la fixait a la couleur GENERIQUE role_color
        # sans jamais lire de surcharge) — desormais l'onglet Colonnes >
        # Inspecteur > Entetes > "Couleur du titre" fonctionne enfin ici.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.header_title.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.header_title.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")

        # Bordure du CADRE : reserve, sur CHAQUE cote EFFECTIVEMENT peint, la
        # meme epaisseur que celle reellement dessinee la (voir Column.
        # refresh_header, MEME raison — sinon l'entete/le contenu, colles a
        # self.card sans marge, recouvriraient le filet).
        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._card_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        # Padding, PAR COTE (voir Column.refresh_header, MEME logique "carte
        # flottante") — cote gauche a 0 si collee a la derniere colonne
        # (meme regle que la bordure ci-dessus).
        col_pad = dict(column_padding_for(INSPECTOR_TITLE))
        if suppress_left:
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()

    def _suppress_left(self) -> bool:
        """L'inspecteur est TOUJOURS la derniere "colonne" de la rangee
        (voir PipelineBrowser.__init__) : contrairement a Column.
        _suppress_left, inutile d'y chercher un voisin de gauche par
        indexOf — il en existe TOUJOURS un (au moins "Type"). Meme
        condition que l'ancienne app_style.column_seam_border() qu'elle
        remplace ici : Distance entre colonnes <= 0 ET aucun padding actif
        de ce cote — sinon 2 filets se cumuleraient a cette frontiere."""
        if column_gap() > 0:
            return False
        return column_padding_for(INSPECTOR_TITLE)["left"] <= 0

    def _update_card_mask(self):
        """MEME mecanisme que Column._update_card_mask (voir sa docstring
        pour le detail du double decoupage anti-aliase)."""
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        self._card_effect.setEnabled(self.card._thickness <= 0)
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._inner_effect.setRadius(_radius_dict(inner_radius))
        self._inner_effect.setEnabled(self.card._thickness > 0)

    # -- redimensionnement par glisser-deposer sur la bordure gauche,
    # comme n'importe quelle colonne (voir Column.resize_begin/update/end) --

    def _max_width(self) -> int:
        """Largeur maximale ATTEIGNABLE au glisser : toute la place
        disponible jusqu'a la colonne d'en face (la rangee Type/Projets/...
        a gauche), PAS une constante fixe — voir la remarque de
        l'utilisateur, "augmente cette limite a la place disponible jusqu'a
        la colonne en face". `win.scroll`/`win.columns_layout` (voir
        PipelineBrowser.__init__) : largeur du viewport visible moins la
        largeur REELLE actuelle de la rangee de colonnes (sizeHint() d'un
        QHBoxLayout aux enfants a largeur fixe = leur somme + espacements) —
        DETAIL_PANEL_MIN_WIDTH en repli si l'un des deux manque (fenetre pas
        encore construite) ou si le resultat tombe en-dessous."""
        win = self.window()
        scroll = getattr(win, "scroll", None)
        columns_layout = getattr(win, "columns_layout", None)
        if scroll is None or columns_layout is None:
            return DETAIL_PANEL_MAX_WIDTH
        available = scroll.viewport().width() - columns_layout.sizeHint().width()
        return max(DETAIL_PANEL_MIN_WIDTH, available)

    def _in_resize_zone(self, x: int) -> bool:
        """Bord GAUCHE (contrairement a Column/PreviewColumn, bord DROIT —
        l'inspecteur est TOUJOURS la DERNIERE colonne de la rangee, voir
        _suppress_left)."""
        return 0 <= x <= COLUMN_RESIZE_MARGIN

    def _resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        _show_resize_width(self, self.width())

    def _resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(
            DETAIL_PANEL_MIN_WIDTH,
            min(self._max_width(), self._resize_start_width - delta),
        )
        self.setFixedWidth(new_width)
        _show_resize_width(self, new_width)

    def _resize_end(self):
        self._resizing = False
        _hide_resize_width(self)
        _persist_detail_panel_width(self.window(), self.width())

    def eventFilter(self, obj, event):
        """MEME mecanique que PreviewColumn.eventFilter/Column.eventFilter
        (voir leur docstring de tete) : installe sur self.card/self.header
        (voir __init__) — sans cela, ces widgets ENFANTS, qui couvrent TOUTE
        la surface de self, interceptent l'evenement souris AVANT que self
        ne le voie, rendant la bordure de redimensionnement inaccessible —
        voir la remarque de l'utilisateur, "la selection du bord de la
        colonne inspecteur est toujours aussi peinible a selectionner pour
        la redimension"."""
        etype = event.type()
        if etype == QEvent.MouseMove:
            if self._resizing:
                self._resize_update(event.globalPosition().toPoint().x())
                return True
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_x) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._in_resize_zone(local_x):
                self._resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonRelease and self._resizing:
            self._resize_end()
            return True
        elif etype == QEvent.Leave and not self._resizing:
            obj.unsetCursor()
        return False

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._resizing:
            self._resize_update(event.globalPosition().toPoint().x())
            return
        self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(x) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        x = event.position().toPoint().x()
        if event.button() == Qt.LeftButton and self._in_resize_zone(x):
            self._resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resize_end()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._resizing:
            self.unsetCursor()
        super().leaveEvent(event)

    def _stop_video(self):
        """Coupe la lecture en cours et cache le lecteur : appele avant
        toute selection (voir show_path/clear), pas seulement pour un
        fichier non-video — quitter la selection d'une video ne doit
        jamais la laisser jouer en arriere-plan, invisible."""
        if self._video_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._video_player.stop()
        self._video_player.setSource(QUrl())
        self.video_widget.hide()

    def clear(self):
        self._preview_request_path = None
        self._current_path = None
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
        self.pur_navigation.hide()
        self.name.setText("")
        self.badge.setText("")
        self.preview_dimensions_value.setText("—")
        self.preview_stale_badge.hide()
        self.well.hide()
        self._preview_pixmap = None
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.well_label.clear()
        self.well_label.show()
        self.preview_log.hide()
        self.preview_progress.hide()
        self.text_preview.hide()
        self.text_preview.clear()
        self._stop_video()
        for value in self.values.values():
            value.setText("")

    def refresh_fonts(self, is_dir: bool = True):
        """Reapplique les polices de role (voir role_font) : necessaire car
        ce panneau, contrairement aux colonnes, n'est pas reconstruit par
        PipelineBrowser.reload() apres un changement de reglages. Geometrie
        de l'entete (hauteur/padding) desormais dans refresh_header, PAS
        ici (voir sa docstring). Police/couleur du TITRE d'entete
        (self.header_title) AUSSI desormais dans refresh_header (bug
        corrige, voir sa remarque) — cette methode-ci ne touche plus qu'au
        NOM du fichier/dossier selectionne et aux champs de detail."""
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self.open_render_log_button.setFont(role_font("buttons", 10, 500))
        for key_label in self.key_labels.values():
            key_label.setFont(role_font("info", 9, 600))
            key_label.setStyleSheet(
                f"color: {M['table_head_fg']}; background: transparent; border: none;"
            )
        for value in self.values.values():
            value.setFont(role_font("info2", 11, 400))
            value.setStyleSheet(
                f"color: {M['value_fg']}; background: transparent; border: none;"
            )
        self.preview_dimensions_heading.setFont(role_font("info", 9, 600))
        self.preview_dimensions_heading.setStyleSheet(
            f"color: {M['table_head_fg']}; background: transparent; border: none;"
        )
        self.preview_dimensions_value.setFont(role_font("info2", 11, 400))
        self.preview_dimensions_value.setStyleSheet(
            f"color: {M['value_fg']}; background: transparent; border: none;"
        )
        self.preview_stale_badge.setFont(role_font("info2", 8, 700))

    def refresh_colors(self):
        """Reapplique les couleurs — MEME logique que Column.refresh_colors
        (voir sa docstring), applique ici a l'inspecteur pour la premiere
        fois (voir la remarque de l'utilisateur, "je veux exactement le
        meme style, parametres par parametres") : fond/bordure/rayon du
        cadre suivent desormais Colonnes > Colonnes, comme toute colonne."""
        self.header_fill.setStyleSheet(column_header_qss("DetailHeader", INSPECTOR_TITLE))
        frame = column_frame_style(INSPECTOR_TITLE, self._suppress_left())
        # scaled() ICI, sur le MEME dict que celui repasse tel quel au
        # masque (voir _update_card_mask/Column.refresh_colors, MEME raison).
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        self._update_card_mask()
        self.well.setStyleSheet(f"background: {C['well']}; border: 1px solid #282c30;")
        self._apply_preview_table_style()
        self.open_render_log_button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            f"border-radius: 3px; padding: 0 7px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
        )
        self.refresh_fonts(True if not self.values["kind"].text() else self.values["kind"].text() == "Dossier")

    def _apply_preview_table_style(self):
        """Applique au tableau de l'inspecteur les reglages des tableaux Parametres."""
        settings = load_settings()
        colors = settings.get("colors") or {}
        _sync_dynamic_M(colors)
        self.preview_info_table.setRadius(int(settings.get("table_radius", 0)))
        border_enabled = _coerce_side_enabled(settings.get("table_border_enabled", True))
        border_colors = {
            side: resolve_color_ref(value, M["panel_border"])
            for side, value in (settings.get("table_border") or {}).items()
        }
        self.preview_info_table.setBorder(
            border_enabled, border_colors, int(settings.get("table_border_thickness", 1))
        )
        padding = settings.get("table_cell_padding") or {}
        margins = (
            max(0, int(padding.get("left", 14))),
            max(0, int(padding.get("top", 8))),
            max(0, int(padding.get("right", 14))),
            max(0, int(padding.get("bottom", 8))),
        )
        for layout in self._preview_info_cell_layouts:
            layout.setContentsMargins(*margins)
        for cell in self.preview_info_table.findChildren(QWidget):
            if isinstance(cell, QLabel):
                continue
            cell.setStyleSheet(f"background: {M['table_row_a']};")
        heading_style = (
            f"color: {M['table_head_fg']}; background: transparent; border: none; "
            "padding: 0; font-size: 9px;"
        )
        value_style = (
            f"color: {M['value_fg']}; background: transparent; border: none; "
            "padding: 0; font-size: 11px;"
        )
        for label in self.preview_info_table.findChildren(QLabel):
            if label.objectName() == "PreviewInfoHeading":
                label.setStyleSheet(heading_style)
            elif label.objectName() == "PreviewInfoValue":
                label.setStyleSheet(value_style)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def _update_preview(self):
        if self._preview_pixmap is None:
            self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
            self.preview_dimensions_value.setText("—")
            if self.preview_log.isVisible():
                return
            if self.preview_progress.isVisible():
                return
            self.well_label.clear()
            return
        pw, ph = self._preview_pixmap.width(), self._preview_pixmap.height()
        if pw <= 0 or ph <= 0:
            self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
            self.preview_dimensions_value.setText("—")
            self.well_label.clear()
            return
        # Largeur disponible = largeur du panneau moins ses marges (16 de
        # chaque cote). Jamais d'agrandissement au-dela de la taille reelle
        # de l'image, et jamais plus haut que PREVIEW_MAX_HEIGHT.
        avail_w = max(self.width() - 32, 50)
        scale = min(1.0, avail_w / pw, PREVIEW_MAX_HEIGHT / ph)
        final_w = max(1, round(pw * scale))
        final_h = max(1, round(ph * scale))
        ratio_gcd = math.gcd(final_w, final_h)
        self.preview_dimensions_value.setText(
            f"{final_w} × {final_h} px · {final_w // ratio_gcd}:{final_h // ratio_gcd} · {scale * 100:.0f}%"
        )
        self.well.setMinimumHeight(max(final_h, PREVIEW_MIN_HEIGHT))
        scaled = self._preview_pixmap.scaled(
            final_w, final_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.well_label.setPixmap(scaled)

    def _refresh_preview_stale_badge(self, path: Path | None = None):
        key = str(path) if path is not None else self._current_path
        self.preview_stale_badge.setVisible(bool(key and self._preview_pixmap is not None and key in _STALE_PREVIEW_PATHS))

    def _navigate_pur_image(self, step: int):
        if self._pur_image_path != self._current_path:
            return
        direction = -1 if step < 0 else 1
        index = self._pur_image_index + step if step else self._pur_image_index
        total = len(self._pur_exported_images) or len(self._pur_image_ranges)
        while 0 <= index < total:
            if self._pur_exported_images:
                image = read_pur_exported_image(Path(self._pur_exported_images[index]))
            else:
                image = read_pur_embedded_image(Path(self._pur_image_path), self._pur_image_ranges[index])
            if image is not None and not image.isNull():
                self._pur_image_index = index
                self._preview_pixmap = QPixmap.fromImage(image)
                suffix = " (extraction en cours)" if self._pur_export_task is not None else ""
                self.pur_image_counter.setText(f"Image {index + 1} / {total}{suffix}")
                self.pur_previous_button.setEnabled(index > 0)
                self.pur_next_button.setEnabled(index + 1 < total)
                self.well.show()
                self.well_label.show()
                self._update_preview()
                return
            index += direction
        self.pur_previous_button.setEnabled(index > 0)
        self.pur_next_button.setEnabled(False if direction > 0 else index + 1 < total)

    def _start_pur_export(self, path: Path, mtime: float):
        current = self._pur_export_task
        if current is not None and str(current.path) == str(path) and current.mtime == mtime:
            return
        task = _PureRefExportTask(path, mtime)
        task.signals.progress.connect(self._on_pur_export_progress)
        task.signals.finished.connect(self._on_pur_export_finished)
        self._pur_export_task = task
        _PUR_EXPORT_POOL.start(task)

    def _on_pur_export_progress(self, path_str: str, mtime: float, files):
        if path_str != self._current_path or path_str != self._pur_image_path:
            return
        try:
            if Path(path_str).stat().st_mtime != mtime:
                return
        except OSError:
            return
        self._pur_exported_images = list(files)
        self.pur_next_button.setEnabled(self._pur_image_index + 1 < len(files))
        self._navigate_pur_image(0)

    def _on_pur_export_finished(self, path_str: str, mtime: float, files, error: str):
        if self._pur_export_task is not None and str(self._pur_export_task.path) == path_str:
            self._pur_export_task = None
        if path_str != self._current_path or path_str != self._pur_image_path:
            return
        try:
            current_mtime = Path(path_str).stat().st_mtime
        except OSError:
            return
        if current_mtime != mtime:
            return
        if files:
            self._pur_exported_images = list(files)
            self._pur_image_index = min(self._pur_image_index, len(files) - 1)
            self.pur_next_button.setEnabled(self._pur_image_index + 1 < len(files))
            self._navigate_pur_image(0)
        elif error:
            self.pur_image_counter.setText(error)
            self.pur_previous_button.setEnabled(False)
            self.pur_next_button.setEnabled(False)

    def _start_3d_preview(self, path: Path):
        """Affiche la barre d'activite et lance le rendu OBJ/ABC en arriere-plan."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        self._preview_request_path = str(path)
        self._preview_pixmap = None
        self.well_label.clear()
        _PREVIEW_DECODE_MANAGER.request(path, mtime, force_render=True)
        if str(path) in _PREVIEW_DECODE_MANAGER.active and str(path) not in self._preview_generation_paths:
            self._on_preview_generation_started(str(path))

    def prepare_auto_preview_log(self, path: Path):
        """Marque le prochain rendu automatique avant le signal started."""
        self._auto_preview_paths.add(str(path))

    def open_preview_render_log(self):
        """Ouvre le journal automatique situe a la racine du navigateur."""
        window = self.window()
        root_field = getattr(window, "root_field", None)
        if root_field is None:
            return
        path = Path(root_field.text().strip()) / "pipeline_preview_render.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except OSError:
            return
        open_path(path)

    def _on_preview_generation_started(self, path_str: str):
        was_idle = not self._preview_generation_paths
        self._preview_generation_paths.add(path_str)
        automatic = path_str in self._auto_preview_paths
        if self.text_preview.isVisible() or self.video_widget.isVisible():
            if not automatic:
                return
            self.text_preview.hide()
            self._stop_video()
            self.well.show()
        if was_idle:
            if automatic:
                if self._auto_preview_log_count == 0:
                    self.preview_log.clear()
                else:
                    self.preview_log.appendPlainText(_IdlePreviewScheduler.LOG_SEPARATOR)
            else:
                self.preview_log.clear()
                self._auto_preview_log_count = 0
        if automatic:
            self._auto_preview_log_count += 1
        self.well.show()
        self.preview_log.show()
        self.preview_progress.hide()
        self.well_label.hide()
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.preview_log.appendPlainText(f"> Aperçu en cours : {path_str}")
        self.preview_log.ensureCursorVisible()

    def _on_preview_generation_progress(self, path_str: str, percent: int, message: str):
        if path_str not in self._preview_generation_paths:
            return
        if self.text_preview.isVisible() or self.video_widget.isVisible():
            if path_str not in self._auto_preview_paths:
                return
            self.text_preview.hide()
            self._stop_video()
            self.well.show()
        if not self.preview_log.isVisible():
            self.well.show()
            self.preview_log.show()
            self.well_label.hide()
            self.preview_progress.hide()
        self.preview_log.appendPlainText(f"[{percent:3d}%] {Path(path_str).name} — {message}")
        self.preview_log.ensureCursorVisible()

    def _on_3d_preview_ready(self, path_str: str, mtime: float, image):
        """Met en cache le resultat du worker, puis l'affiche s'il est toujours selectionne."""
        was_requested = path_str == self._preview_request_path or path_str in self._preview_generation_paths
        self._preview_generation_paths.discard(path_str)
        self._auto_preview_paths.discard(path_str)
        path = Path(path_str)
        try:
            still_current_file = path.stat().st_mtime == mtime
        except OSError:
            still_current_file = False
        pix = None
        if still_current_file and image is not None and not image.isNull():
            pix = QPixmap.fromImage(image)
            _bounded_cache_set(_file_image_cache, path_str, (mtime, pix))
            _STALE_PREVIEW_PATHS.discard(path_str)
            # Les delegates des colonnes consultent le meme cache; les
            # repeindre leur fait afficher le rendu qui vient d'etre produit.
            for widget in QApplication.allWidgets():
                if isinstance(widget, QAbstractItemView):
                    widget.viewport().update()
        if self._preview_request_path == path_str or self._current_path == path_str:
            if pix is None and path_str in _STALE_PREVIEW_PATHS and still_current_file:
                pix, _is_stale = _read_preview_pixmap(path, mtime)
            self._preview_request_path = None
            if pix is not None and path.suffix.lower() in IMAGE_EXTENSIONS:
                source_pix = QPixmap(path_str)
                self._preview_pixmap = source_pix if not source_pix.isNull() else pix
            else:
                self._preview_pixmap = pix
            self._update_preview()
            self._refresh_preview_stale_badge(path)
        if not was_requested:
            return
        if self._preview_generation_paths:
            if not self.text_preview.isVisible() and not self.video_widget.isVisible():
                completion_percent = 100 if pix is not None else 0
                completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
                self.preview_log.appendPlainText(
                    f"[{completion_percent:3d}%] {path.name} — {completion_message}"
                )
                self.preview_log.ensureCursorVisible()
            return
        if not self.text_preview.isVisible() and not self.video_widget.isVisible():
            completion_percent = 100 if pix is not None else 0
            completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
            self.preview_log.appendPlainText(
                f"[{completion_percent:3d}%] {path.name} — {completion_message}"
            )
            self.preview_log.ensureCursorVisible()
            self.preview_log.hide()
        self.preview_progress.hide()
        self.well_label.show()
        self._update_preview()

    def show_loading_step(self, label: str, depth: int = 0):
        """Reutilise le "puits" de l'Inspecteur (self.well/well_label, le
        "carre noir" a cote des metadonnees) comme indicateur de
        chargement PENDANT la construction de la fenetre de parametres
        (voir SettingsWindow._report_loading_step, appele entre chaque
        section) — voir la remarque de l'utilisateur, "la fenetre de
        settings est toujours tres longue a charger ... peux tu faire une
        sorte d'animation dans le champ apercu de l'inspecteur et afficher
        tous les elements que tu charges en temps reel". Chaque etape
        s'AJOUTE a la suite des precedentes (jamais remplacee), comme un
        fichier LOG qui se construit ligne par ligne dans un terminal —
        voir la remarque de l'utilisateur, "fait ca comme si c'etait un
        vieil ordinateur qui balancait des lignes de code dans un
        terminal, ne supprime pas les etapes d'avant mais met les
        suivantes a la ligne"."""
        if not getattr(self, "_loading_log_lines", None):
            self._loading_log_lines = []
            # self.well est CACHE par defaut (voir clear()/show_path()) tant
            # qu'aucun fichier/dossier n'est selectionne dans l'appli — sans
            # ce show() explicite, l'animation restait invisible des que la
            # fenetre de parametres s'ouvrait sans rien de selectionne au
            # prealable.
            self.well.show()
            self.well_label.setPixmap(QPixmap())
            self.well_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.well_label.setWordWrap(False)
            # Police CODE de l'appli (mono_family, voir font()), vert pur
            # (0,255,0) et SANS lissage (smoothing="none", voir font()) —
            # voir la remarque de l'utilisateur, "je veux que la police
            # soit code de l'appli, qu'elle soit verte 0,255,0 et qu'elle
            # ne soit pas lissee".
            self.well_label.setFont(font(9, 400, mono=True, smoothing="none"))
            self.well_label.setStyleSheet(
                "background: transparent; border: none; color: rgb(0, 255, 0); padding: 6px;")
        # Indentation par niveau (tab = 2 caracteres, voir _report_
        # construction_step cote settings_window) — voir la remarque de
        # l'utilisateur, "quand tu load les settings, incrémente les
        # differents niveaux de settings (tab = 2 carac)".
        self._loading_log_lines.append(f"{'  ' * max(0, depth)}> {label}")
        self.well_label.setText("\n".join(self._loading_log_lines))
        self.well_label.adjustSize()
        # Se redimensionne selon le contenu, jusqu'a 1000px maxi (PAS une
        # hauteur fixe) — voir la remarque de l'utilisateur, "je veux que
        # le carre d'apercu soit plus haut que ca, qu'il se redimensionne
        # si besoin jusqu'a une hauteur de 1000px maxi".
        needed = self.well_label.sizeHint().height() + 12
        self.well.setMinimumHeight(max(PREVIEW_MIN_HEIGHT, min(1000, needed)))

    def clear_loading_step(self):
        """Restaure l'apparence normale du puits (voir show_loading_step) —
        _update_preview() y remet la vignette REELLEMENT selectionnee
        (ou rien), pas besoin de la memoriser a part."""
        self._loading_log_lines = []
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setWordWrap(False)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        self._update_preview()

    def _show_video(self, path: Path):
        """Dimensionne le lecteur video sur la frame deja mise en cache
        (voir file_image_pixmap/_decode_video_frame) — meme calcul que
        _update_preview pour une image fixe — puis lance la lecture,
        silencieuse et en boucle (voir __init__)."""
        static = file_image_pixmap(path)
        avail_w = max(self.width() - 32, 50)
        if static is not None and not static.isNull() and static.width() > 0 and static.height() > 0:
            scale = min(1.0, avail_w / static.width(), PREVIEW_MAX_HEIGHT / static.height())
            self.video_widget.setFixedSize(
                max(1, round(static.width() * scale)), max(1, round(static.height() * scale))
            )
        else:
            self.video_widget.setFixedSize(avail_w, PREVIEW_MIN_HEIGHT)
        self.video_widget.show()
        self._video_player.setSource(QUrl.fromLocalFile(str(path)))
        self._video_player.play()

    def show_path(self, path: Path):
        self._current_path = str(path)
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
        self.pur_navigation.hide()
        self.name.setText(path.name)
        is_dir = path.is_dir()
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self._preview_pixmap = None
        self._preview_request_path = None
        self.preview_stale_badge.hide()
        self.preview_progress.hide()
        if self._preview_generation_paths:
            self.preview_log.show()
            self.well_label.hide()
        else:
            self.preview_log.hide()
            self.well_label.show()
        self._stop_video()
        is_text_preview = not is_dir and path.suffix.lower() in TEXT_PREVIEW_EXTENSIONS
        is_video = not is_dir and path.suffix.lower() in VIDEO_EXTENSIONS
        if is_video:
            # Lecture reelle (voir _stop_video/video_widget), pas la frame
            # figee de file_image_pixmap : celle-ci ne sert plus ici qu'a
            # dimensionner le lecteur avant que la premiere image ne soit
            # decodee (voir _show_video). well/text_preview jamais affiches
            # en meme temps.
            self.well.hide()
            self.text_preview.hide()
            self._show_video(path)
        elif is_text_preview:
            # Extrait de contenu (voir read_text_preview) plutot que le
            # "well" image : les deux ne s'affichent jamais ensemble.
            self.well.hide()
            content_text = read_text_preview(path)
            self.text_preview.setPlainText(content_text if content_text is not None else "(apercu indisponible)")
            self.text_preview.show()
        else:
            self.text_preview.hide()
            self.well.show()
            if not is_dir:
                suffix = path.suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        mtime = None
                    stale_pix = None
                    is_stale = False
                    if mtime is not None:
                        stale_pix, is_stale = _read_preview_pixmap(path, mtime)
                    if is_stale and stale_pix is not None:
                        self._preview_pixmap = stale_pix
                        file_image_pixmap(path)  # auto-régénère les caches 2D périmés
                    else:
                        pix = QPixmap(str(path))
                        if not pix.isNull():
                            self._preview_pixmap = pix
                        file_image_pixmap(path)  # crée le cache 2D manquant
                elif suffix in OBJ_EXTENSIONS | ABC_EXTENSIONS:
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        _cached_file_image_pixmap(path)  # charge l'ancien rendu si disponible
                        self._start_3d_preview(path)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(path)
                elif suffix in (BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS):
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        _cached_file_image_pixmap(path)
                        self._start_3d_preview(path)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(path)
                elif suffix in DWG_EXTENSIONS:
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
                elif suffix in PUR_PREVIEW_EXTENSIONS:
                    # Indexe les images embarquees sans les decoder, puis
                    # l'inspecteur ne charge que celle actuellement choisie.
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        mtime = None
                    self._pur_image_ranges = pur_embedded_image_ranges(path, mtime)
                    pur_version = pur_file_major_version(path)
                    is_pur_v2 = pur_version is not None and pur_version >= 2
                    if self._pur_image_ranges or is_pur_v2:
                        self._pur_image_path = str(path)
                        self.pur_navigation.show()
                        self.pur_previous_button.setEnabled(False)
                        self.pur_next_button.setEnabled(len(self._pur_image_ranges) > 1)
                        if is_pur_v2:
                            self.pur_image_counter.setText("Extraction des images PureRef…")
                            self.pur_next_button.setEnabled(False)
                            if mtime is not None:
                                self._start_pur_export(path, mtime)
                        if self._pur_image_ranges:
                            self._navigate_pur_image(0)
                        else:
                            self.well_label.setText("Extraction des images PureRef en cours…")
                    else:
                        self.well_label.setText("Aucune image intégrée lisible dans ce fichier PureRef.")
                elif (suffix in PSD_EXTENSIONS
                      or suffix in EXR_EXTENSIONS or suffix in HDR_EXTENSIONS
                      or suffix in TX_EXTENSIONS):
                    # Rendu genere (.obj, voir _decode_obj_image), vignette
                    # embarquee extraite (.psd/.psb, voir
                    # _decode_psd_thumbnail) ou tone-mapping HDR (.exr/.hdr,
                    # voir _decode_exr_image/_decode_hdr_image) : pas un
                    # fichier que QPixmap sait charger directement, passe
                    # par le meme cache que les cartes-fichier
                    # (file_image_pixmap).
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
            self._update_preview()
            self._refresh_preview_stale_badge(path)
        try:
            info = path.stat()
            modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            info, modified = None, "-"
        if path.is_dir():
            kind = "Dossier"
            size = f"{count_entries(path)} elements"
        else:
            kind = (path.suffix[1:].upper() + " file") if path.suffix else "Fichier"
            size = human_size(info.st_size) if info else "-"
        self.values["kind"].setText(kind)
        self.values["size"].setText(size)
        self.values["modified"].setText(modified)
        self.values["path"].setText(str(path))

        if is_dir:
            self.badge.setText("DOSSIER")
            self.badge.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        else:
            self.badge.setText(path.suffix[1:].upper() if path.suffix else "FICHIER")
            self.badge.setStyleSheet("color: #7fa8cf; background: transparent;")


# ==========================================================================
# Etat de session (position/taille de la fenetre, dernier dossier parcouru) :
# separe des parametres utilisateur (pipeline_settings.json, gere par
# settings_window.py) puisque ce n'est pas un reglage mais un etat automatique
# de l'appli, sauvegarde a la fermeture et restaure au demarrage suivant.
# ==========================================================================

WINDOW_STATE_PATH = Path(__file__).resolve().parent / "pipeline_window_state.json"


def load_window_state() -> dict:
    try:
        if WINDOW_STATE_PATH.is_file():
            data = json.loads(WINDOW_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_window_state(state: dict) -> None:
    try:
        WINDOW_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


class IconButton(QPushButton):
    """Bouton dessine au QPainter (─ □ × pour TitleBar, engrenage pour les
    Parametres) plutot qu'avec un glyphe de police : quel que soit le
    symbole choisi (─, □, ×, ⚙...), toute police testee (mono_family(),
    sans_family(), Segoe UI Symbol) le rendait soit absent soit minuscule/
    flou a ces tailles de 11-14px (verifie pixel par pixel a chaque
    tentative) — un souci de metriques internes a la police, pas de
    contenu. Dessiner l'icone soi-meme evite ce souci une fois pour
    toutes, quelle que soit la machine/les polices installees."""

    def __init__(self, kind: str, color: str, hover_color: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._color = color
        self._hover_color = hover_color
        # Cadre CUSTOM (voir set_frame_style) — None par defaut :
        # comportement INCHANGE (fond QSS herite) pour TOUS les usages
        # existants (TitleBar min/max/close, engrenage Parametres). Utilise
        # UNIQUEMENT par PreviewColumn.toggle_btn (voir Colonnes > Apercu >
        # Bouton repliement) — voir la remarque de l'utilisateur, "ajouter
        # les settings de style du bouton repliement : taille bouton ...
        # border ... couleur fond".
        self._frame = None   # (bg, enabled, colors, thickness, radius) | None

    def set_colors(self, color: str, hover_color: str):
        self._color = color
        self._hover_color = hover_color
        self.update()

    def set_kind(self, kind: str):
        self._kind = kind
        self.update()

    def set_frame_style(self, bg: str | None, enabled: dict, colors: dict, thickness: int, radius: dict):
        """Cadre peint a la main (_paint_bordered_rect), REMPLACE le fond
        QSS herite (voir paintEvent, super().paintEvent() saute des qu'un
        cadre custom est actif) — voir Colonnes > Apercu > Bouton
        repliement > Couleur fond/Bordure."""
        self._frame = (bg, enabled, colors, thickness, radius)
        self.update()

    def paintEvent(self, event):
        if self._frame is not None:
            painter = QPainter(self)
            bg, enabled, colors, thickness, radius = self._frame
            painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
            _paint_bordered_rect(painter, self.rect(), radius, enabled, thickness, colors, bg)
        else:
            super().paintEvent(event)
            painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        custom_pix = self._custom_icon_pixmap(rect)
        if custom_pix is not None:
            target = QRect(0, 0, custom_pix.width(), custom_pix.height())
            target.moveCenter(rect.center())
            painter.drawPixmap(target, custom_pix)
            painter.end()
            return
        color = self._hover_color if self.underMouse() else self._color
        pen = QPen(QColor(color))
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        cx, cy = rect.center().x(), rect.center().y()
        s = min(rect.width(), rect.height()) * 0.16
        if self._kind == "min":
            painter.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        elif self._kind == "max":
            painter.drawRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))
        elif self._kind == "close":
            painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
            painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
        elif self._kind == "gear":
            r = s * 1.7
            painter.drawEllipse(QPointF(cx, cy), r * 0.5, r * 0.5)
            for i in range(8):
                ang = math.radians(i * (360 / 8))
                x1 = cx + math.cos(ang) * r * 0.7
                y1 = cy + math.sin(ang) * r * 0.7
                x2 = cx + math.cos(ang) * r
                y2 = cy + math.sin(ang) * r
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        elif self._kind in ("dchevron_left", "dchevron_right"):
            # Repli/depli de Type/Projets/Sous-projet (voir
            # Column.set_collapsed) : double chevron ("«"/"»") pointant vers
            # la gauche ("replier") ou la droite ("deplier") — deux chevrons
            # simples, decales horizontalement.
            sign = -1 if self._kind == "dchevron_left" else 1
            ss = s * 0.95
            for offset in (-ss * 0.85, ss * 0.85):
                ox = cx + offset
                painter.drawLine(QPointF(ox + sign * ss * 0.5, cy - ss), QPointF(ox - sign * ss * 0.5, cy))
                painter.drawLine(QPointF(ox - sign * ss * 0.5, cy), QPointF(ox + sign * ss * 0.5, cy + ss))
        painter.end()

    def _custom_icon_pixmap(self, rect: QRect) -> QPixmap | None:
        """Icone perso (voir Settings > ICONES > General) pour ce bouton,
        si l'utilisateur en a choisi une — sinon None (le glyphe peint ci-
        dessus reste le rendu par defaut). "gear" (bouton Parametres) suit
        TOUJOURS sa propre icone si elle existe ; les chevrons de repli
        (dchevron_left/right) ne la remplacent que si COLLAPSE_TOGGLE_MODE
        vaut "icone" (voir Settings > Colonnes > Focus > Bouton repliement >
        "Icone")."""
        size = int(min(rect.width(), rect.height()) * 0.9)
        if size <= 0:
            return None
        if self._kind == "gear":
            return custom_ui_icon_pixmap(UI_ICON_SETTINGS_GEAR, size)
        if self._kind in ("dchevron_left", "dchevron_right") and COLLAPSE_TOGGLE_MODE == "icone":
            return custom_ui_icon_pixmap(UI_ICON_COLLAPSE_TOGGLE, size)
        return None


# ==========================================================================
# Barre de titre intrinseque : la fenetre principale est sans decoration
# systeme (voir PipelineBrowser.__init__), donc cette barre en tient lieu —
# deplacement, reduction/agrandissement/fermeture — avec le meme habillage
# sombre que le reste de l'appli plutot que le chrome blanc/bleu de Windows.
# ==========================================================================

class TitleBar(QWidget):

    def __init__(self, window: "PipelineBrowser", parent=None):
        super().__init__(parent)
        self._window = window
        self.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        # objectName + selecteur ID (voir la meme remarque pour #CentralFrame
        # et #DetailPanel) : sans ce ciblage strict, le "border-bottom" nu se
        # propageait au title_label (le seul enfant sans bordure propre),
        # qui se retrouvait souligne sur sa seule largeur de texte au lieu du
        # filet visant a courir sur toute la largeur de la barre.
        self.setObjectName("TitleBar")
        # Indispensable pour qu'une sous-classe de QWidget (comme celle-ci)
        # peigne effectivement son propre style — sans lui, le fond et la
        # bordure ci-dessus sont ignores au rendu (seul un QWidget "nu",
        # sans sous-classe, les applique automatiquement) : voir Column, qui
        # pose deja cet attribut pour la meme raison.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        self.setMouseTracking(True)

        icon = QLabel()
        self._icon = icon
        icon_size = scaled(9)
        icon.setFixedSize(icon_size, icon_size)
        # Icone perso (voir Settings > ICONES > General, UI_ICON_APP_LOGO)
        # si l'utilisateur en a choisi une, sinon le carre neutre d'origine.
        custom_logo = custom_ui_icon_pixmap(UI_ICON_APP_LOGO, icon_size)
        if custom_logo is not None:
            icon.setPixmap(custom_logo)
            icon.setStyleSheet("background: transparent;")
        else:
            icon.setStyleSheet(f"border: 1px solid {C['mark_dir_bd']}; background: transparent;")
        # Transparent aux clics : sans ca, cliquer PILE sur l'icone ou le
        # texte du titre (plutot qu'a cote, sur le fond nu de la barre) ne
        # declenche jamais TitleBar.mousePressEvent ci-dessous — un widget
        # enfant sous le curseur capte l'evenement souris meme s'il n'en
        # fait rien, Qt ne le remonte pas tout seul au parent. C'etait la
        # cause du "des fois le clic ne deplace pas la fenetre".
        icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.title_label = QLabel(window.windowTitle())
        self.title_label.setFont(role_font("app", 11, 400, tracking=0.01))
        self.title_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(icon)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.btn_min = self._make_button("min", window.showMinimized)
        self.btn_max = self._make_button("max", self._toggle_max)
        self.btn_close = self._make_button("close", window.close)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def refresh_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) a la
        hauteur de la barre et a ses boutons — construits une seule fois
        (contrairement aux colonnes, jamais reconstruits), donc sans cela le
        slider d'echelle ne les affecterait qu'au prochain lancement."""
        self.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        self._icon.setFixedSize(scaled(9), scaled(9))
        for btn in (self.btn_min, self.btn_max, self.btn_close):
            btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))

    def _make_button(self, kind: str, slot) -> IconButton:
        btn = IconButton(kind, C["label"], C["text"])
        btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))
        btn.setCursor(Qt.ArrowCursor)
        btn.setFlat(True)
        btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; border: none;"
            "}"
            "QPushButton:hover {"
            f"  background: {C['hover']};"
            "}"
        )
        btn.clicked.connect(slot)
        return btn

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_max()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Voir app_style.start_native_move : SendMessage synchrone
            # plutot que QWindow.startSystemMove() (qui POSTE son SC_MOVE,
            # asynchrone) — evite que la fenetre "rate" le debut du glisser
            # si d'autres evenements souris arrivent avant que Windows ne
            # traite ce message en file.
            start_native_move(self._window)
            event.accept()
        else:
            super().mousePressEvent(event)


# ==========================================================================
# Fenetre principale
# ==========================================================================

class PipelineBrowser(QMainWindow):

    def __init__(self, root: Path):
        super().__init__()
        self.setWindowTitle("Pipeline Browser")
        # Sans decoration systeme : le chrome blanc/bleu de Windows (barre de
        # titre, boutons min/max/fermer natifs) est remplace par la barre
        # intrinseque de l'appli (voir TitleBar), habillee comme le reste de
        # l'interface. Le redimensionnement par les bords, perdu avec le
        # cadre systeme, est retrouve via nativeEvent (voir plus bas).
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # Fond translucide (voir Parametres > General > "Border radius de la
        # fenetre principale") : indispensable pour qu'un rayon de bordure
        # non nul, applique plus bas en QSS sur `central`, laisse voir au
        # travers des coins au lieu de les peindre carres derriere le
        # widget arrondi. Actif en permanence (rayon 0 = coins carres, rendu
        # identique a avant) pour que le reglage marche en direct sans
        # devoir re-afficher la fenetre.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1280, 620)
        self.columns: list[Column] = []
        # Etat courant (unique source de verite, voir _sync_collapse_state/
        # _toggle_project_columns) de repli de Type/Projets/Sous-projet, et
        # icone associee sur la colonne des vignettes (voir
        # PreviewColumn.set_toggle_state).
        self._project_columns_collapsed = False
        # Tant que ce drapeau est vrai, la prochaine fois que Sous-projet
        # obtient une selection declenche le repli automatique une fois
        # (voir _sync_collapse_state) — desarme par un repli/depli manuel
        # (icone) pour ne pas annuler le choix de l'utilisateur tant que la
        # selection reste la meme, puis rearme des que Sous-projet perd sa
        # selection (retour en arriere).
        self._auto_collapse_armed = True
        # Signature du dernier RENDU de update_preview_stack (voir
        # _preview_style_snapshot/refresh_all_columns) — permet a
        # refresh_all_columns(rescan=False) de sauter une reconstruction
        # complete (detruit/recree jusqu'a 6 widgets, RE-SCANNE LE DISQUE :
        # vignettes/in/over/out/logiciels) quand rien de ce dont depend le
        # RENDU n'a change depuis le dernier appel — voir la remarque de
        # l'utilisateur, "gros ralentissements ... les manips sont donc
        # tres lourdes". None : jamais encore rendu, le premier appel via
        # cette voie reconstruit TOUJOURS (repli surs).
        self._last_preview_style_snapshot: str | None = None
        # Groupe IN/OVER/OUT/LOGICIELS (voir update_preview_stack) : 4
        # colonnes fantomes EMPILEES VERTICALEMENT (meme principe que
        # _preview_stack_wrapper ci-dessous) — reconstruites SEULEMENT
        # quand le contexte de navigation change reellement (voir
        # _group_context_key ci-dessous), jamais a chaque appel : ces
        # instances restent stables d'une navigation a l'autre, EXACTEMENT
        # comme Type/Projets/Sous-projet — voir la remarque de
        # l'utilisateur, "leur comportement ne fonctionne pas du tout ...
        # base toi sur les colonnes creees avant les focus".
        self._group_stack_wrapper: QWidget | None = None
        self.group_columns: list[Column] = []
        # (terminal_path, tuple(levels), work_dir_style) de la DERNIERE
        # construction reussie du groupe (voir update_preview_stack) — None
        # tant qu'aucune construction n'a encore eu lieu (repli sur : le
        # premier appel reconstruit toujours).
        self._group_context_key: object | None = None
        # Colonne du groupe IN/OVER/OUT/LOGICIELS la plus RECEMMENT
        # selectionnee (voir update_active_column/_on_group_item_selected) —
        # une SEULE des 4 doit apparaitre "focus" (fond bleu) a la fois,
        # pas les 4 independamment des qu'elles ont chacune une selection —
        # voir la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir".
        self._last_active_group_column: Column | None = None
        # Largeur commune aux 4 colonnes du groupe (voir Column.__init__
        # user_width/on_resize, _on_group_column_resized) — MEME principe/
        # MEME raison que _preview_column_user_width plus bas (colonnes
        # RECONSTRUITES a chaque navigation) — voir la remarque de
        # l'utilisateur, "les 4 colonnes doivent avoir la meme largeur
        # constamment".
        self._group_column_user_width: int | None = None
        # Hauteur INDEPENDANTE de chacune des colonnes du groupe (voir
        # Column.__init__ user_height/on_height_resize/fill_height,
        # _on_group_height_resized), par kind ("in"/"over"/"out"/
        # "logiciels") — PAS une largeur commune : contrairement a la
        # largeur (memes proportions pour les 4), chaque colonne garde SA
        # PROPRE hauteur — voir la remarque de l'utilisateur, "je ne veux
        # pas qu'elles aient toute la meme hauteur, mais chacune leur
        # hauteur". La DERNIERE colonne de _group_column_order n'y figure
        # jamais activement (voir fill_height) : elle reste etiree jusqu'en
        # bas de la page, jamais une hauteur fixe.
        self._group_column_user_heights: dict[str, int] = {}
        # Etat du glisser de hauteur EN COURS (voir _on_group_height_resize_
        # begin/_on_group_height_resized) : (colonne du dessus, colonne du
        # dessous, sa hauteur de depart, la hauteur de depart de sa voisine)
        # — None hors glisser. Scission a 2 (voir leurs remarques) : SEULES
        # ces 2 colonnes-la sont jamais touchees, jamais tout le groupe.
        self._group_height_drag: tuple[Column, Column, int, int] | None = None
        # Configuration de chaine de navigation DU PROJET COURANT (voir
        # load_project_columns/on_selected/ColumnConfigDialog) — None tant
        # qu'aucun projet n'est selectionne OU que le projet selectionne n'a
        # pas de fichier de configuration (repli sur la chaine legacy fixe,
        # voir COLUMN_LABELS) — voir la remarque de l'utilisateur, "cette
        # configuration [doit changer] suivant les besoins de l'utilisateur".
        self._active_project_config: dict | None = None
        # Ordre d'affichage des 4 colonnes du groupe (voir update_preview_
        # stack/_on_group_reorder) — LOGICIELS en premier par defaut, voir
        # la remarque de l'utilisateur, "la colonne logiciel doit etre en
        # premiere position en haut". Reordonnable par glisser-deposer de
        # l'entete (voir Column.__init__ group_kind/on_reorder).
        self._group_column_order: list[str] = ["logiciels", "in", "over", "out"]
        # Groupe des animations de position en cours (voir
        # _reorder_group_columns_animated) — reference gardee pour ne pas
        # etre ramassee par le GC avant la fin, meme raison que Column.
        # _width_anim.
        self._group_reorder_anim: QParallelAnimationGroup | None = None
        # Colonnes fantomes PERMANENTES des vignettes (voir _PreviewBlock) :
        # jamais remplacees par une vraie colonne, contrairement au groupe
        # IN/OVER/OUT/LOGICIELS ci-dessus (dont le clic sur une ligne ouvre,
        # lui, une vraie colonne). UNE VRAIE colonne fantome SEPAREE par niveau
        # selectionne (Projets, Sous-projet), PLUS une derniere colonne
        # fantome vide (voir PreviewColumn.set_preview_block/set_empty) —
        # chacune avec son PROPRE cadre/bordure/entete (voir app_style.
        # column_style_for), empilees VERTICALEMENT dans UN SEUL conteneur
        # (voir _preview_stack_wrapper ci-dessous), lui-meme insere comme
        # UNE SEULE colonne dans columns_layout — voir la remarque de
        # l'utilisateur, "je veux les trois colonnes ... les unes sur les
        # autres" puis "chaque colonne doit avoir sa propre entete" puis,
        # apres un essai fusionnant tout dans une seule carte, "non, tu as
        # merger les deux colonnes en une seule, ce que je veux c'est deux
        # colonnes separees, une en dessous de l'autre !".
        self.image_preview_columns: list[PreviewColumn] = []
        # Conteneur vertical (QWidget+QVBoxLayout) qui heberge les colonnes
        # ci-dessus, INSERE comme un SEUL element de columns_layout — voir
        # update_preview_stack.
        self._preview_stack_wrapper: QWidget | None = None
        # Largeur choisie a la main sur la colonne Focus (voir PreviewColumn.
        # resize_begin/resize_update, _on_preview_column_resized) — vit ICI
        # (pas sur les instances PreviewColumn elles-memes) car update_
        # preview_stack() les RECONSTRUIT entierement a chaque navigation :
        # sans ce relais, tout glisser de bordure serait perdu des le clic
        # suivant. PARTAGEE par toutes (pas par niveau) : ce sont des
        # colonnes SEPAREES mais elles doivent rester alignees a la meme
        # largeur (voir PreviewColumn.set_width_external) — None = pas
        # encore ajustee a la main, retombe sur col_width("Projets") — voir
        # la remarque de l'utilisateur, "je veux pouvoir controler la
        # largeur des colonnes focus projet et sous projet en slidant les
        # bords de celles-ci".
        self._preview_column_user_width: int | None = None
        # Cle (couleurs + rayon des boutons) du dernier _apply_settings :
        # sert a ne reconstruire la feuille de style globale (voir
        # refresh_colors) que lorsque l'un des deux a vraiment change,
        # plutot qu'a chaque cran de n'importe quel slider.
        self._last_style_key = None
        # app.setStyleSheet (voir refresh_colors/refresh_style) est de
        # LOIN le poste le plus cher de tout ce rafraichissement — mesure
        # a plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte (des milliers de widgets, chacun avec son propre QSS
        # local a re-cascader) — voir la remarque de l'utilisateur, "il y
        # a toujours un tres gros problemes de performance dans les
        # settings". Le gate ci-dessus (style_key) evite de le rejouer
        # quand RIEN n'a change, mais durant un glisser de COULEUR, la
        # valeur change reellement a CHAQUE tick (~30ms) : ce gate seul ne
        # peut donc rien y faire. Regroupe ici les reconstructions
        # rapprochees (voir _flush_stylesheet_rebuild) : le reste de
        # refresh_colors (couleurs des colonnes/boutons individuels, DEJA
        # rapide et DEJA la source principale du retour visuel en direct)
        # continue de tourner a CHAQUE tick, seul cet appel natif couteux
        # est repousse a un rythme beaucoup plus lache — invisible a
        # l'oeil (le style GENERIQUE — boutons/scrollbars/menus — n'est de
        # toute facon pas ce qu'on regarde en glissant une pastille de
        # couleur), mais qui evite l'accumulation de secondes de latence.
        self._pending_stylesheet_rebuild = False
        self._stylesheet_rebuild_timer = QTimer(self)
        self._stylesheet_rebuild_timer.setSingleShot(True)
        self._stylesheet_rebuild_timer.setInterval(250)
        self._stylesheet_rebuild_timer.timeout.connect(self._flush_stylesheet_rebuild)

        # --- barre du haut ---
        self.root_label = QLabel("Root")
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")

        self.root_field = QLineEdit(str(root))
        self.root_field.setFont(role_font("info", 12, 400))
        self.root_field.setFixedHeight(scaled(24))
        self.root_field.returnPressed.connect(self.reload)

        self.btn_browse = QPushButton("Parcourir")
        self.btn_reload = QPushButton("Refresh")
        self.btn_last_place = QPushButton("↩ Dernier endroit")
        # IconButton (voir la classe, juste avant TitleBar), PAS un glyphe
        # de police "⚙" : aucune police testee (sans_family(), Segoe UI
        # Symbol...) ne le rendait de facon fiable a cette taille — meme
        # correctif que pour les boutons min/max/close de TitleBar.
        self.btn_settings = IconButton("gear", role_color("buttons", "#c4cacf"), C["text"])
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
            btn.setFixedHeight(scaled(24))
            btn.setCursor(Qt.ArrowCursor)
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place):
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.setFixedWidth(scaled(28))
        self.btn_settings.setToolTip("Parametres")
        self.btn_last_place.setToolTip("Revenir a l'endroit ouvert a la derniere fermeture")
        self.btn_browse.clicked.connect(self.browse_root)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_last_place.clicked.connect(self.go_to_last_place)
        self.btn_settings.clicked.connect(self.open_settings)
        # Chemin ouvert a la derniere fermeture (voir closeEvent) : l'appli
        # s'ouvre toujours a la racine, ce bouton permet d'y revenir a la
        # demande plutot que d'y naviguer automatiquement (voir
        # _restore_window_state).
        self._last_place: Path | None = None
        self.btn_last_place.setEnabled(False)

        self.synced_label = QLabel("")
        self.synced_label.setFont(role_font("info2", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")

        topbar = QWidget()
        self.topbar = topbar
        topbar.setFixedHeight(TOPBAR_HEIGHT)
        # objectName + selecteur ID : voir la remarque sur #TitleBar plus
        # haut (meme piege, meme correctif) — root_label et synced_label,
        # simples QLabel sans bordure propre, heriteraient sinon du
        # border-bottom nu et se retrouveraient chacun souligne.
        topbar.setObjectName("TopBar")
        topbar.setStyleSheet(
            f"#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['border']}; }}"
        )
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(10, 0, 10, 0)
        top_layout.setSpacing(10)
        top_layout.addWidget(self.root_label)
        top_layout.addWidget(self.root_field, 1)
        top_layout.addWidget(self.btn_browse)
        top_layout.addWidget(self.btn_reload)
        top_layout.addWidget(self.btn_last_place)
        top_layout.addWidget(self.synced_label)
        top_layout.addWidget(self.btn_settings)

        # --- zone des colonnes ---
        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        # column_gap() (pas 0 en dur) : lit deja la valeur persistee (voir
        # apply_all_settings, appele par main() AVANT la construction de
        # cette fenetre) — Fenetre de parametres > Colonnes > Distance
        # entre colonnes, voir la remarque de l'utilisateur. max(0, ...) :
        # column_gap() peut valoir -1 (voir set_column_gap/la remarque de
        # l'utilisateur, "que les bordures ne se cumulent pas"), mais
        # QBoxLayout.setSpacing() n'accepte PAS un espacement reellement
        # negatif — verifie directement, TOUTE valeur negative y retombe
        # silencieusement sur l'espacement du STYLE (6px ici, pire qu'un
        # simple 0) plutot que -1px reel. L'effet "-1" (filet non cumule)
        # passe donc par Column._suppress_left()/DetailPanel._suppress_left()
        # (chacune masque son propre bord gauche quand collee a sa voisine),
        # pas par un espacement negatif ici.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))

        self.detail = DetailPanel()

        # objectName + selecteur ID : le fond au-dela de la derniere colonne
        # (l'espace que la colonne Inspecteur, desormais a largeur fixe, ne
        # comble plus) est C["window"] ("Fond") — DISTINCT du fond de chaque
        # colonne/panneau (C["void"], peint par chacun sur lui-meme, voir
        # Column/PreviewColumn/DetailPanel), qui ne depend plus de ce widget
        # pour son propre "vide" — voir la remarque de l'utilisateur,
        # nouvelle capture annotee a l'appui (auparavant les deux etaient
        # confondus dans le meme C["void"]).
        columns_host = QWidget()
        self.columns_host = columns_host
        columns_host.setObjectName("ColumnsHost")
        columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['window']}; }}")
        host_layout = QHBoxLayout(columns_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addLayout(self.columns_layout)
        host_layout.addStretch(1)
        host_layout.addWidget(self.detail, 0)

        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(columns_host)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- barre de statut ---
        self.path_label = QLabel("")
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right = QLabel("read-only")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")

        statusbar = QWidget()
        self.statusbar = statusbar
        statusbar.setFixedHeight(STATUS_HEIGHT)
        # objectName + selecteur ID : meme piege/correctif que #TitleBar.
        statusbar.setObjectName("StatusBar")
        statusbar.setStyleSheet(
            f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}"
        )
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(12)
        status_layout.addWidget(self.path_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.status_right)

        self.titlebar = TitleBar(self)

        # objectName + selecteur ID : une regle "nue" (sans selecteur) posee
        # via setStyleSheet sur un widget conteneur se propage a TOUS ses
        # descendants sans style propre (fond ET bordure y compris) — un
        # "border" ici sans ce ciblage strict entourait chaque QLabel de
        # l'inspecteur d'un cadre. Le contour est peint ici meme (pas
        # seulement laisse a Windows/_apply_native_frame) : DWM ne le
        # rendait pas de facon fiable dans tous les cas (coins carres
        # compris), ce filet QSS garantit un contour visible tout autour de
        # la fenetre quel que soit le reglage de coins.
        central = QWidget()
        self.central = central
        central.setObjectName("CentralFrame")
        # Indispensable pour que le "border"/"border-radius" ci-dessous soit
        # reellement peint : sur un QWidget nu, Qt applique le fond du QSS
        # via un chemin rapide qui ignore ce flag, mais PAS la bordure — sans
        # lui, la bordure etait silencieusement ignorée (verifie pixel par
        # pixel : le bord de la fenetre restait exactement la couleur de
        # fond, jamais {C['border']}). Meme remarque que pour TitleBar/
        # Column plus bas, mais leur cas ne concernait jusque-la que le fond.
        central.setAttribute(Qt.WA_StyledBackground, True)
        central.setStyleSheet(
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {WINDOW_RADIUS}px; }}"
        )
        layout = QVBoxLayout(central)
        # Marge de 1px (= l'epaisseur du filet ci-dessus), PAS 0 : a marge
        # nulle, les enfants (titlebar, colonnes...) sont peints PAR-DESSUS
        # la bordure de central sur ses 4 cotes (verifie pixel par pixel),
        # la rendant invisible malgre WA_StyledBackground — l'ordre de
        # peinture Qt fait passer les enfants apres le fond/bordure du
        # parent, donc un enfant a bord franc la recouvre entierement.
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.titlebar)
        layout.addWidget(topbar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(statusbar)
        self.setCentralWidget(central)

        self.addAction(QAction(self, shortcut="F5", triggered=self.reload))
        self.reload()
        self._apply_native_frame()

        self._restore_window_state()
        self._idle_preview_scheduler = _IdlePreviewScheduler(self)

    def _restore_window_state(self):
        """Reapplique la position/taille de fenetre au moment de la derniere
        fermeture (voir closeEvent). L'appli s'ouvre toujours a la racine :
        le dossier parcouru a la derniere fermeture n'est pas retrouve
        automatiquement, mais retenu pour le bouton "Dernier endroit" (voir
        go_to_last_place)."""
        state = load_window_state()
        geometry_b64 = state.get("geometry")
        if geometry_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode("ascii")))
            except (ValueError, TypeError):
                pass
        last_path = state.get("last_path")
        self._last_place = Path(last_path) if last_path else None
        self.btn_last_place.setEnabled(self._last_place is not None)

    def go_to_last_place(self):
        if self._last_place is not None:
            self._navigate_to(self._last_place)

    def _navigate_to(self, target: Path):
        """Deplie les colonnes jusqu'a `target` en simulant les selections
        successives, sans effet si `target` n'existe plus ou n'est pas sous
        la racine actuellement affichee."""
        root = Path(self.root_field.text())
        try:
            parts = target.relative_to(root).parts
        except ValueError:
            return
        current = root
        for part in parts:
            current = current / part
            if not self.columns:
                return
            column = self.columns[-1]
            match = None
            for i in range(column.list.count()):
                item = column.list.item(i)
                if Path(item.data(ROLE_PATH)).name == part:
                    match = item
                    break
            if match is None:
                return
            column.list.setCurrentItem(match)
            if not current.is_dir():
                return

    def closeEvent(self, event):
        state = load_window_state()
        state["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        state["last_path"] = str(self.columns[-1].directory) if self.columns else ""
        save_window_state(state)
        super().closeEvent(event)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redonne le redimensionnement par les bords a cette fenetre sans
        decoration systeme (voir __init__) — voir app_style.resize_hit_test
        pour le detail (partage avec SettingsWindow.nativeEvent)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _apply_native_frame(self):
        """Coins/bordure DWM (voir app_style.apply_dwm_frame) + accrochage
        aux bords (resizable=True, seule cette fenetre est vraiment
        redimensionnable par l'utilisateur — voir nativeEvent/WM_NCHITTEST
        pour le redimensionnement par les bords, gere a la main)."""
        apply_dwm_frame(self, WINDOW_RADIUS, C["border"], resizable=True)

    # -- gestion des colonnes ------------------------------------------

    def reload(self):
        root = Path(self.root_field.text())
        self.prune_after(-1)
        self.detail.clear()
        if not root.is_dir():
            self.path_label.setText(f"Introuvable : {root}")
            self.synced_label.setText("")
            return
        self._project_columns_collapsed = False
        self._auto_collapse_armed = True
        self.add_column(root, 0)
        self.path_label.setText(str(root))
        self.synced_label.setText(datetime.now().strftime("scan %H:%M:%S"))
        self.update_preview_stack()
        self._sync_collapse_state()

    def _detach_group_stack(self):
        """Retire le groupe fantome de columns_layout SANS le detruire
        (voir add_column) — contrairement a _clear_group_stack, garde
        `self.group_columns`/`self._group_context_key` intacts : le
        prochain update_preview_stack (toujours appele juste apres, voir
        add_column) le REINSERE tel quel si le contexte de navigation n'a
        pas change, ou le detruira lui-meme via _clear_group_stack si
        besoin d'une reconstruction complete."""
        if self._group_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._group_stack_wrapper)

    def _clear_group_stack(self):
        if self._group_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._group_stack_wrapper)
            self._group_stack_wrapper.setParent(None)
            self._group_stack_wrapper.deleteLater()
            self._group_stack_wrapper = None
        self.group_columns = []
        self._group_context_key = None
        self._last_active_group_column = None

    def _clear_image_preview_columns(self):
        if self._preview_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._preview_stack_wrapper)
            self._preview_stack_wrapper.setParent(None)
            self._preview_stack_wrapper.deleteLater()
            self._preview_stack_wrapper = None
        self.image_preview_columns = []

    def add_column(self, directory: Path, depth: int, title: str | None = None,
                   is_focus_level: bool | None = None,
                   show_dirs: bool = True, show_files: bool = True,
                   omit_dirs: frozenset = frozenset(), omit_files: frozenset = frozenset(),
                   style_title: str | None = None, display_title: str | None = None):
        # `title` : impose un intitule (voir _open_group_folder, qui ouvre
        # un dossier in/over/out/logiciel sans rapport avec ce que la profondeur
        # suggererait normalement — pas question d'afficher "SOUS-PROJET" au
        # dessus du contenu de "in"). None (cas normal) : intitule deduit de
        # la profondeur, comme avant. `is_focus_level`/`show_dirs`/`show_files`/
        # `omit_dirs`/`omit_files` (voir Column.__init__, on_selected) :
        # SEULEMENT fournis pour un niveau de la chaine CONFIGUREE (voir
        # load_project_columns) — valeurs par defaut = comportement INCHANGE
        # pour tout le reste (Type/Sous-projet legacy/Logiciels/Contenu).
        # `style_title` (voir Column.style_title/on_selected) : cle de STYLE
        # SEPAREE du nom affiche — utilisee pour qu'un niveau de chaine
        # CONFIGUREE (nom quelconque, ex. "test1") suive quand meme le
        # reglage General > Colonnes > INTERMEDIAIRE (voir la remarque de
        # l'utilisateur, "doit controler toutes les colonnes entre celle de
        # projet et focus"). None (repli, comportement INCHANGE) : style_title
        # = title, comme avant ce reglage.
        normal_navigation = title is None
        if title is None:
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        if display_title is None and normal_navigation and depth > 1:
            # En-tete DYNAMIQUE pour toute colonne "de set" APRES Type ET
            # Projets (Type garde son titre fixe, aucune colonne
            # PRECEDENTE dont reprendre le nom ; "Projets" doit lui
            # TOUJOURS s'appeler ainsi — voir la remarque de l'utilisateur,
            # "la deuxieme colonne doit toujours s'appeler PROJETS", une
            # correction de la demande initiale "dans les colonnes de set
            # le nom des colonnes correspond au nom du repertoire
            # selectionne") : `directory` EST precisement le dossier
            # SELECTIONNE dans la colonne precedente (celui dont cette
            # nouvelle colonne liste le contenu). Seulement en navigation
            # NORMALE (`title` deja None avant l'affectation ci-dessus) :
            # PAS pour _open_group_folder, qui fixe deja lui-meme son
            # propre display_title (voir sa remarque).
            display_title = directory.name
        column = Column(
            directory, title, is_focus_level=is_focus_level, style_title=style_title,
            display_title=display_title,
            show_dirs=show_dirs, show_files=show_files, omit_dirs=omit_dirs, omit_files=omit_files)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
        self.columns.append(column)
        # Le groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
        # stack) peut occuper cet emplacement depuis la selection
        # precedente : le RETIRER (pas le DETRUIRE, voir _detach_group_
        # stack) avant d'ajouter la vraie colonne, sinon celle-ci se
        # retrouverait ajoutee APRES lui dans columns_layout (ordre visuel
        # casse). image_preview_column, elle, n'est PAS retiree ici : c'est
        # une colonne permanente qui doit rester juste avant celle qu'on
        # ajoute (voir update_preview_stack, qui la reconstruit a la bonne
        # position a chaque appel). update_preview_stack (appele juste
        # apres, a la fin de on_selected/_open_group_folder) le REINSERE
        # a la bonne position SANS le reconstruire si le contexte de
        # navigation n'a pas change (voir sa remarque, la remarque de
        # l'utilisateur "base toi sur les colonnes creees avant les
        # focus") — un _clear_group_stack() (destructeur) ici aurait
        # recree les 4 colonnes a CHAQUE _open_group_folder, y compris pour
        # une simple creation de dossier qui re-selectionne l'element cree.
        self._detach_group_stack()
        self.columns_layout.addWidget(column)
        # _suppress_left() (voir Column._containing_layout) a besoin que la
        # colonne soit DEJA dans columns_layout pour detecter correctement
        # sa voisine de gauche — au moment de Column.__init__ (donc de son
        # 1er refresh_header()/refresh_colors(), voir plus haut), elle n'a
        # encore AUCUN parent, _suppress_left() y renvoie donc TOUJOURS
        # False, figeant a tort un padding/bordure gauche PLEIN (jamais
        # supprime) pour toute colonne qui n'est pourtant PAS la premiere
        # de la rangee — voir la remarque de l'utilisateur, "la distance
        # entre deux colonnes est toujours deux fois plus grande que la
        # valeur du padding" : rejouer les 2 ICI, une fois REELLEMENT
        # inseree, recalcule enfin la bonne valeur.
        column.refresh_header()
        column.refresh_colors()
        self.update_active_column()
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()

    def refresh_all_columns(self, rescan: bool = True, relayout_titles: set | None = None):
        """Reapplique aux colonnes existantes (largeur, delegate, polices)
        les reglages globaux courants, SANS reconstruire l'arborescence : la
        navigation en cours (profondeur, selection) reste intacte. Utilise
        par le glisser-deposer (rescan=True : le contenu du dossier a change
        sur le disque), et par la previsualisation en direct des parametres
        (voir _apply_settings, rescan=False : aucun reglage cosmetique
        (police, largeur, hauteur de ligne...) ne change le contenu d'un
        dossier — retourner sur le disque, y compris le comptage recursif
        des colonnes a vignettes, a chaque cran de slider n'apporterait
        rien et coute cher sur un partage reseau).

        `relayout_titles` (uniquement pertinent avec rescan=False, voir
        _apply_settings) : titres de colonne dont col_row_height()/
        col_spacing() ont REELLEMENT change depuis le dernier appel — les
        AUTRES colonnes sautent le doItemsLayout() de Column.relayout()
        (voir sa docstring), puisqu'un cran de slider qui ne touche qu'a une
        couleur/bordure/rayon n'a aucune raison de recalculer le sizeHint()
        de CHAQUE ligne — None (comportement par defaut, tous les autres
        appelants) relayoute TOUJOURS tout, sans cette optimisation — voir
        la remarque de l'utilisateur, "il y a des ralentissements dans les
        animations, optimise un maximum"."""
        for column in self.columns:
            # Une colonne repliee (voir Column.set_collapsed) garde une
            # largeur nulle : col_width(...) est la largeur DEPLOYEE, la
            # reappliquer ici la ferait rebondir a pleine largeur a chaque
            # glisser-deposer/reglage sans que column.collapsed n'ait change.
            # Largeur choisie a la main (voir Column._user_width) prioritaire
            # sur col_width(...) : sinon repasser sur N'IMPORTE quel reglage
            # (y compris Colonnes > Padding/Bordure, rejoue a chaque cran de
            # slider pour la previsualisation en direct) ecrasait aussitot
            # tout redimensionnement manuel par la largeur par defaut.
            if not column.collapsed:
                # _pin_column_width (voir Column._toggle_pin) EN PREMIER :
                # sans lui, tout changement de reglage (n'importe quel
                # champ de la fenetre de parametres, voir _apply_settings)
                # ecrasait aussitot la largeur FIGEE d'une colonne pinnee —
                # voir la remarque de l'utilisateur, "quand on fait une
                # modif dans les settings, ca annule toutes les valeurs
                # des colonnes qui sont pinnees".
                column.setFixedWidth(
                    column._pin_column_width or column._user_width or col_width(column.style_title))
            else:
                column.setFixedWidth(0)
            column.refresh_header()
            column.list.setUniformItemSizes(column.has_thumbnails)
            delegate = column.list.itemDelegate()
            if hasattr(delegate, "refresh_fonts"):
                delegate.refresh_fonts()
            if rescan:
                column.refresh()
                # doItemsLayout() supplementaire : refresh() ci-dessus vide
                # puis repeuple la liste (clear()+addItem() par entree), sans
                # jamais rejouer explicitement la mise en page finale — voir
                # relayout() juste en dessous, qui elle le fait DEJA (pas de
                # doItemsLayout() double dans ce cas, voir la remarque de
                # l'utilisateur, "il y a des ralentissements dans les
                # animations, optimise un maximum" : ce 2e appel tournait
                # inutilement a CHAQUE cran de slider pendant la
                # previsualisation en direct, voir rescan=False plus bas).
                column.list.doItemsLayout()
            else:
                do_layout = relayout_titles is None or column.style_title in relayout_titles
                column.relayout(do_layout=do_layout)
        if rescan:
            self.update_preview_stack()
        else:
            # Gate (voir _preview_style_snapshot/la remarque de tete de
            # cette methode) : SEULEMENT pour la previsualisation en direct
            # des parametres (rescan=False, seul appelant de cette
            # branche) — sauter la reconstruction complete du groupe IN/
            # OVER/OUT/LOGICIELS/des vignettes Focus (destruction/recreation
            # de jusqu'a 6 widgets + RE-SCAN DU DISQUE) quand rien de ce
            # qu'elle utilise n'a change depuis le dernier rendu, au lieu de
            # la rejouer a CHAQUE cran de glisser de N'IMPORTE quel slider
            # de la fenetre de parametres — voir la remarque de
            # l'utilisateur, "gros ralentissements ... les manips sont donc
            # tres lourdes".
            snapshot = self._preview_style_snapshot()
            if snapshot != self._last_preview_style_snapshot:
                self.update_preview_stack()

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        for i, column in enumerate(self.columns):
            column.set_active(i == last_selected)
        # Colonnes du groupe IN/OVER/OUT/LOGICIELS : UNE SEULE a la fois
        # doit apparaitre "focus" (voir _last_active_group_column, mis a
        # jour par _on_group_item_selected a CHAQUE clic sur l'une d'elles)
        # — pas les 4 independamment des qu'elles ont chacune une
        # selection (1ere version de ce correctif, revenue sur elle : voir
        # la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir").
        for column in self.group_columns:
            column.set_active(
                column is self._last_active_group_column and column.current_path() is not None)

    def _chain_expected_total(self) -> int:
        """Nombre de colonnes REELLES requises pour que la chaine de
        navigation soit complete (Type + Projets + niveaux configures, voir
        load_project_columns/self._active_project_config) — 3 (Type,
        Projets, Sous-projet) si aucune config (chaine legacy). Utilise a
        la fois par update_preview_stack (position des vignettes/du groupe)
        et _open_group_folder (position ou du contenu ouvert depuis ce
        groupe doit s'inserer) — voir leurs remarques, "ancrer sur la FIN
        DE LA CHAINE REQUISE, pas sur le dernier niveau focus"."""
        active_config = self._active_project_config
        if active_config is None:
            return 3
        # Toggle "set" DESACTIVE (voir ColumnConfigDialog, la remarque de
        # l'utilisateur, "si il est a 0, le set ne se fait pas, et on passe
        # directement de la colonne projets a la colonne apres les
        # logiciels/in/out/over") : ignore les niveaux configures, comme
        # une chaine "base 2" (Type+Projets seuls).
        if not active_config.get("set_enabled", True):
            return 2
        return 2 + len(active_config["columns"])

    def _chain_terminal_path(self) -> Path | None:
        """Chemin actuellement selectionne dans la DERNIERE colonne requise
        de la chaine (voir _chain_expected_total) — None tant que la chaine
        n'est pas COMPLETEMENT settee jusqu'au repertoire de travail (soit
        pas assez de colonnes reelles encore ouvertes, soit rien de
        selectionne dans la derniere). self.columns[expected_total - 1]
        (position FIXE), PAS self.columns[-1] : une fois du contenu ouvert
        depuis le groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder),
        self.columns contient des colonnes SUPPLEMENTAIRES apres la chaine
        — voir update_preview_stack, meme remarque. Partagee par
        update_preview_stack (afficher ou non les vignettes/le groupe) ET
        _sync_collapse_state (repli automatique des colonnes de set, voir
        la remarque de l'utilisateur, "une fois que l'on est sur l'espace
        de travail")."""
        expected_total = self._chain_expected_total()
        if len(self.columns) < expected_total:
            return None
        path = self.columns[expected_total - 1].current_path()
        # Un FICHIER selectionne dans cette colonne ne "sette" PAS le
        # projet — seul un REPERTOIRE marque l'espace de travail atteint
        # (voir update_preview_stack/_sync_collapse_state/_on_group_
        # height_resize_end, tous les 3 appelants) — voir la remarque de
        # l'utilisateur, "les fichiers ne sont pas des elements de set".
        if path is not None and not path.is_dir():
            return None
        return path

    def _preview_style_snapshot(self) -> str:
        """Signature LEGERE de tout ce dont depend le RENDU (pas le
        contenu/la selection, jamais impactes par un simple reglage
        cosmetique) de update_preview_stack — les 3 styles resolus qu'elle
        utilise pour construire ses widgets (vignettes Focus, groupe IN/
        OVER/OUT au style "Contenu", groupe LOGICIELS) plus l'espacement
        entre colonnes. Comparee par refresh_all_columns(rescan=False,
        voir sa remarque) pour sauter une reconstruction complete —
        detruire/recreer jusqu'a 6 widgets et RE-SCANNER LE DISQUE
        (vignettes/in/over/out/logiciels) — quand AUCUNE de ces 4 valeurs
        n'a reellement change depuis le dernier rendu, plutot qu'a CHAQUE
        cran de glisser d'un slider quelconque de la fenetre de parametres,
        meme sans aucun rapport avec ces colonnes — voir la remarque de
        l'utilisateur, "gros ralentissements ... les manips sont donc tres
        lourdes". json.dumps (pas un simple tuple) : ces styles sont des
        dict (parfois imbriques, bordures/rayons par cote/coin), non
        hashables tels quels — sort_keys=True pour une representation
        STABLE (ordre d'iteration du dict sans importance)."""
        return json.dumps(
            [
                column_style_for(PREVIEW_STACK_TITLE),
                column_style_for("Contenu"),
                column_style_for("Logiciels"),
                column_gap(),
            ],
            sort_keys=True, default=str,
        )

    def update_preview_stack(self):
        """Recalcule l'apercu empile : un bloc par colonne a vignettes
        (Projets, Sous-projet) actuellement selectionnee, dans l'ordre de
        navigation, reparti sur DEUX emplacements juste apres la derniere
        colonne A VIGNETTES :

        1. Les vignettes (voir _PreviewBlock) : DEUX colonnes fantomes
           PERMANENTES SEPAREES (image_preview_columns), une par niveau
           selectionne (Projets, Sous-projet), empilees VERTICALEMENT dans
           un conteneur commun (voir _preview_stack_wrapper), reconstruites
           ici a chaque fois a la bonne position — il n'y a pas de
           "dossier" pour des images, donc jamais de vraie colonne a cet
           endroit. Les 2 partagent le MEME style (fond/bordure/rayon/
           entete), TOUJOURS celui de l'onglet "Focus" des reglages (voir
           PreviewColumn.display_title) — voir la remarque de
           l'utilisateur, "il doit y avoir deux colonnes, une focus projet
           et l'autre focus sous projet, je veux aucune autre entete ...
           les settings 'focus' doivent controler les deux colonnes".
        2. Le groupe IN/OVER/OUT/LOGICIELS (voir group_columns) : 4 VRAIES
           colonnes fantomes (liste cliquable/navigable comme n'importe
           quelle Column, pas un simple detail statique), empilees
           VERTICALEMENT juste apres les vignettes, RECONSTRUITES ici a
           chaque fois — remplace l'ancien detail "Fichiers pour X" +
           l'ancienne colonne reelle "Logiciels" (melangeant blocs de
           statut et liste de logiciels) — voir la remarque de
           l'utilisateur, "je veux creer 4 colonnes empilees les unes sur
           les autres : colonne IN, OVER, OUT et LOGICIEL". IN/OVER/OUT :
           contenu FUSIONNE du dossier correspondant du Projet ET du
           Sous-projet selectionnes (voir status_folder_state) — voir la
           remarque de l'utilisateur, "contenu de tous les dossiers des
           repertoires IN des sections projet et sous projets". LOGICIELS :
           SEUL le niveau le plus profond (Sous-projet si selectionne,
           sinon Projet), meme source que l'ancienne colonne reelle "Logi-
           ciels" (voir _softs_subdir) — voir la remarque de l'utilisateur,
           "identique au contenu actuel". Cliquer une ligne ouvre son
           contenu dans une VRAIE colonne juste apres le groupe (voir
           _open_group_folder), navigation normale comme partout ailleurs
           dans l'appli."""
        # Signature du RENDU en cours (voir _preview_style_snapshot/
        # refresh_all_columns) : mise a jour ICI, EN PREMIER, quel que soit
        # le chemin de sortie ci-dessous (chaine incomplete -> vide, ou
        # reconstruction complete) — reste ainsi TOUJOURS en phase avec ce
        # qui est REELLEMENT affiche, peu importe quel appelant a declenche
        # ce rendu (navigation normale, glisser-deposer, ou previsualisation
        # de reglages).
        self._last_preview_style_snapshot = self._preview_style_snapshot()
        self._clear_image_preview_columns()
        if not self.columns:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # Rien n'apparait (ni vignettes, ni groupe IN/OVER/OUT/LOGICIELS)
        # tant que la chaine n'est pas COMPLETEMENT settee jusqu'au
        # repertoire de travail (voir load_project_columns/on_selected,
        # expected_total = Type+Projets+niveaux configures) — voir la
        # remarque de l'utilisateur, "ne pas faire apparaitre les colonnes
        # focus tant que le set n'est pas fini jusqu'a l'espace de
        # travail". AVANT (pas seulement pour softs_dirs comme avant) :
        # deplace ici, calcule EN PREMIER, pour pouvoir couper court avant
        # meme de construire les vignettes — un focus PARTIEL (ex.
        # seulement "Projets" selectionne, avant tout choix dans "Sous-
        # projet") ne doit plus rien afficher du tout.
        active_config = self._active_project_config
        expected_total = self._chain_expected_total()
        # Toggles "focus"/"in_over_out" (voir ColumnConfigDialog, la
        # remarque de l'utilisateur, "si il est a 0, on n'affiche pas la
        # colonne focus"/"in over et out") — True par defaut (chaine legacy
        # OU champ absent d'une config plus ancienne). Toggle "logiciels"
        # SUPPRIME (voir la remarque de l'utilisateur, "supprime le toggle
        # logiciels") — la colonne LOGICIELS du groupe est desormais
        # TOUJOURS affichee, sans condition.
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        in_over_out_enabled = True if active_config is None else active_config.get("in_over_out_enabled", True)
        if active_config is None:
            work_dir_info = WORK_DIR_TYPES[DEFAULT_WORK_DIR_TYPE]
        else:
            work_dir_info = WORK_DIR_TYPES.get(
                active_config["work_dir"]["type"], WORK_DIR_TYPES[DEFAULT_WORK_DIR_TYPE])
        # _chain_terminal_path (voir sa remarque de tete) : PAS
        # self.columns[-1] — une fois du contenu ouvert depuis le groupe
        # IN/OVER/OUT/LOGICIELS (voir _open_group_folder), self.columns
        # contient des colonnes SUPPLEMENTAIRES apres la chaine, dont le
        # dernier ne represente plus le niveau REEL terminal.
        terminal_path = self._chain_terminal_path()
        if terminal_path is None:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # Hauteurs des colonnes du groupe IN/OVER/OUT/LOGICIELS PROPRES a
        # CE dossier terminal (voir load_layout_settings/
        # _on_group_height_resize_end) — remplace INTEGRALEMENT le dict en
        # memoire (jamais fusionne avec l'ancien contenu) : ce dict est
        # TOUJOURS synchronise avec le disque a la fin de chaque glisser
        # (_on_group_height_resize_end persiste immediatement, "temps
        # reel"), donc jamais de valeur "en attente" a preserver ici — voir
        # la remarque de l'utilisateur, "le dimensionnement en hauteur des
        # colonnes de focus doit etre enregistre en temps reel et ce
        # dependant du [sous-]dossier ... d'un sous dossier a l'autre, les
        # dimensionnements seront differents".
        raw_group_heights = load_layout_settings(terminal_path).get("group_heights")
        self._group_column_user_heights = {}
        if isinstance(raw_group_heights, dict):
            for kind, height in raw_group_heights.items():
                if isinstance(height, (int, float)):
                    self._group_column_user_heights[kind] = int(height)

        entries: list[tuple[str, QPixmap, Path, object, str, Column]] = []
        for column in self.columns if focus_enabled else ():
            if not column.is_focus_level:
                continue
            path = column.current_path()
            if path is None:
                continue
            open_status = lambda p: self._open_group_folder(p)
            # `column.column_title` (5e element, "Projets"/"Sous-projet") :
            # niveau REEL de ce bloc empile — voir _PreviewBlock/la remarque
            # de l'utilisateur, "ce n'est pas deux blocs empiles, mais deux
            # colonnes empilees" (chaque bloc doit reprendre l'entete REEL
            # de SA colonne, pas un entete generique commun aux deux).
            # `column` (6e element, la VRAIE Column source) : voir
            # _PreviewBlock._rename/set_preview_block, la remarque de
            # l'utilisateur, "je veux que le comportement des colonnes
            # fonctionne de la meme maniere sur tous les points" — permet
            # au bloc Focus de retrouver la VRAIE colonne dont il reprend
            # la selection, pour y appliquer un Renommer avec la MEME
            # resynchronisation de la navigation qu'une ligne normale
            # (voir Column._rename_item : renommer puis re-selectionner
            # l'item renomme retriggue on_selected/prune_after tout seul).
            entries.append((path.name, project_thumbnail_pixmap(path), path, open_status, column.column_title, column))

        if focus_enabled and not entries:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # 1. Vignettes : juste APRES LA FIN DE LA CHAINE REQUISE (Type +
        # Projets + niveaux configures, voir expected_total plus haut) —
        # PAS le dernier niveau FOCUS (un niveau configure peut avoir
        # focus=False, y compris le DERNIER juste avant le repertoire de
        # travail : dans ce cas le dernier focus-level est plus TOT dans la
        # chaine, et ancrer dessus inserait les vignettes/le groupe AU
        # MILIEU des colonnes reelles au lieu d'apres toutes — voir la
        # remarque de l'utilisateur, "si nous sommes en presence d'un
        # projet a 4 etapes avant set, les colonnes de focus devront etre a
        # la 5eme place"). PAS len(self.columns) non plus : cet indice peut
        # DEPASSER expected_total une fois du contenu ouvert depuis le
        # groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) — les
        # vignettes/le groupe doivent rester COLLES juste apres la chaine
        # requise, pas glisser plus loin derriere ce contenu deja ouvert.
        # A cet instant columns_layout contient exactement self.columns,
        # dans l'ordre : l'indice de colonne vaut l'indice de layout.
        anchor = expected_total - 1
        # Toggle "focus" DESACTIVE (voir ColumnConfigDialog, la remarque de
        # l'utilisateur, "si il est a 0, on n'affiche pas la colonne
        # focus") : aucune vignette construite, le groupe IN/OVER/OUT/
        # LOGICIELS vient alors s'inserer JUSTE apres la chaine (anchor+1)
        # au lieu de anchor+2 (pas de gap laisse par des vignettes
        # absentes).
        group_anchor_offset = 2
        if focus_enabled:
            # Conteneur vertical UNIQUE (voir _preview_stack_wrapper) : occupe
            # UNE SEULE place dans columns_layout (horizontal), mais empile ses
            # colonnes fantomes VERTICALEMENT en son sein — voir la remarque de
            # l'utilisateur, "deux colonnes separees, une en dessous de
            # l'autre". Espacement VERTICAL entre elles : meme reglage GENERAL
            # que "Distance entre colonnes" (column_gap), transpose a la
            # verticale — coherent avec l'espacement HORIZONTAL habituel entre
            # colonnes.
            wrapper = QWidget()
            wrapper.setStyleSheet("background: transparent;")
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(scaled(max(0, column_gap()), 0))
            wrapper_layout.setAlignment(Qt.AlignTop)
            # EXACTEMENT une colonne par entree (Projets, Sous-projet), AUCUNE
            # autre entete (ni entete generique "Focus" a part, ni 3e colonne
            # vide) — texte d'entete "Focus <niveau>" (voir _FOCUS_LEVEL_LABEL),
            # mais STYLE (fond/bordure/rayon/police/padding/image/zone titre/
            # bouton repliement) TOUJOURS celui de PREVIEW_STACK_TITLE (l'onglet
            # "Focus" des reglages, PAS "Projets"/"Sous-projets") pour LES DEUX
            # — voir la remarque de l'utilisateur, "il doit y avoir deux
            # colonnes, une focus projet et l'autre focus sous projet, je veux
            # aucune autre entete. a savoir que les settings 'focus' doivent
            # controler les deux colonnes".
            for offset, (title, pixmap, path, open_status, level_title, source_column) in enumerate(entries):
                column = PreviewColumn(
                    PREVIEW_STACK_TITLE, on_toggle=self._toggle_project_columns if offset == 0 else None,
                    user_width=self._preview_column_user_width,
                    on_resize=self._on_preview_column_resized, fit_height=True,
                    display_title=_FOCUS_LEVEL_LABEL.get(level_title, PREVIEW_STACK_TITLE))
                if offset == 0:
                    column.set_toggle_state(self._project_columns_collapsed)
                wrapper_layout.addWidget(column)
                column.set_preview_block(title, pixmap, path, open_status, source_column)
                self.image_preview_columns.append(column)
            self._preview_stack_wrapper = wrapper
            self.columns_layout.insertWidget(anchor + 1, wrapper)
        else:
            group_anchor_offset = 1

        # 2. Groupe IN/OVER/OUT/LOGICIELS : insere JUSTE APRES LES VIGNETTES
        # (anchor + group_anchor_offset), PAS ajoute en fin (`addWidget`) — meme raison que
        # pour les vignettes ci-dessus : une colonne ouverte depuis une
        # PRECEDENTE navigation dans le groupe peut deja trainer en fin de
        # columns_layout (voir _open_group_folder) au moment ou ce groupe
        # est reconstruit, il doit malgre tout rester colle juste apres les
        # vignettes, pas relegue derriere.
        # IN/OVER/OUT : fusionne le contenu de CHAQUE colonne "de set"
        # actuellement selectionnee (Type + Projets + tout niveau
        # intermediaire configure, FOCUS ou non), pas seulement les niveaux
        # FOCUS (voir `entries` ci-dessus, qui reste lui limite aux
        # vignettes) — voir la remarque de l'utilisateur, "que si a
        # l'interieur des colonnes de set il y a un repertoire in out ou
        # over, son contenu doit se retrouver dans les colonnes
        # correspondantes". Borne a expected_total (pas self.columns en
        # entier) : au-dela, self.columns contient du contenu deja OUVERT
        # depuis le groupe IN/OVER/OUT/LOGICIELS lui-meme (voir
        # _open_group_folder) — jamais une source a refusionner ici.
        status_levels: list[Path] = []
        level_labels: list[str] = []
        for column in self.columns[:expected_total]:
            level_path = column.current_path()
            if level_path is None:
                continue
            status_levels.append(level_path)
            if column.column_title == "Projets":
                level_labels.append("projet")
            elif column.column_title == "Type":
                level_labels.append("Type")
            else:
                level_labels.append(level_path.name)
        levels = status_levels or [path for (_name, _pix, path, _open, _level, _col) in entries]
        # LOGICIELS/"Repertoire de travail" (voir add_group_column plus bas) :
        # `terminal_path`/`expected_total`/`work_dir_info` deja calcules et
        # verifies EN HAUT de la methode (voir la remarque de tete) — le
        # groupe n'est construit que lorsque la chaine est deja complete,
        # `terminal_path` est donc garanti non-None ici.
        softs_dirs = [_named_subdir(terminal_path, work_dir_info["folder_name"])]
        work_dir_display = (
            terminal_path.name if work_dir_info.get("display_from_selection")
            else work_dir_info["display"]
        )
        work_dir_style = work_dir_info["style_title"]
        work_dir_only_recognized_software = work_dir_info["only_recognized_software"]

        # Reconstruction EVITEE si le contexte de navigation n'a pas change
        # (meme dossier terminal, memes niveaux fusionnes, meme type de
        # repertoire de travail) — voir la remarque de tete de cette
        # methode et celle de l'utilisateur, "leur comportement ne
        # fonctionne pas du tout ... base toi sur les colonnes creees
        # avant les focus". AVANT ce correctif, les 4 colonnes etaient
        # DETRUITES ET RECONSTRUITES a CHAQUE appel de update_preview_stack
        # (a chaque selection, a chaque previsualisation de reglages en
        # direct) — exactement comme si Type/Projets/Sous-projet etaient
        # recrees a chaque clic — leur faisant perdre punaise/overrides de
        # menu contextuel/etat "actif" en permanence, et forçant un dict
        # separe (GROUP_ROW_HEIGHT, desormais supprime) pour simuler une
        # persistance qu'une VRAIE colonne stable obtient gratuitement.
        # `column.refresh()` (pas un no-op) : capte quand meme un
        # changement de CONTENU sur le disque (ex. refresh_all_columns
        # (rescan=True)) sans reconstruire les objets.
        # Toggle "in_over_out" DESACTIVE (voir ColumnConfigDialog, la
        # remarque de l'utilisateur, "si il est a 0, on n'affiche pas les
        # colonnes in over et out") : filtre localement,
        # self._group_column_order (ordre PERSISTE, voir _on_group_reorder)
        # reste INCHANGE pour retrouver la meme disposition une fois le
        # toggle reactive.
        active_group_order = list(self._group_column_order)
        if not in_over_out_enabled:
            active_group_order = [k for k in active_group_order if k not in ("in", "over", "out")]
        # `in_over_out_enabled` DANS la cle (pas seulement la longueur
        # comparee juste apres) : sans lui, basculer ce toggle SANS changer
        # de dossier terminal semblait "contexte inchange" et ne rejouait
        # que column.refresh() sur les colonnes DEJA existantes, sans
        # jamais ajouter/retirer les colonnes concernees.
        context_key = (terminal_path, tuple(levels), work_dir_style, in_over_out_enabled)
        if context_key == self._group_context_key and len(self.group_columns) == len(active_group_order):
            for column in self.group_columns:
                column.refresh()
            if self._group_stack_wrapper is not None:
                self.columns_layout.removeWidget(self._group_stack_wrapper)
                self.columns_layout.insertWidget(anchor + group_anchor_offset, self._group_stack_wrapper)
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.maximum())
            return

        self._clear_group_stack()
        self._group_context_key = context_key
        group_wrapper = QWidget()
        group_wrapper.setStyleSheet("background: transparent;")
        group_layout = QVBoxLayout(group_wrapper)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(scaled(max(0, column_gap()), 0))
        # PAS de setAlignment(Qt.AlignTop) ici (contrairement a wrapper_
        # layout ci-dessus) : la DERNIERE colonne de l'ordre (voir
        # fill_height plus bas) porte un facteur d'etirement (stretch=1)
        # pour absorber tout l'espace restant jusqu'en bas de group_wrapper
        # — AlignTop l'en empecherait, en tassant les 4 colonnes en haut et
        # laissant un vide sous la derniere — voir la remarque de
        # l'utilisateur, "il est important que la derniere colonne aille
        # bien jusqu'en bas de la page".
        last_kind = active_group_order[-1] if active_group_order else None

        # Annotation "(projet)"/"(<nom de la colonne>)" (voir Column.
        # __init__ source_labels/ROLE_SOURCE_LABEL) : UNE par colonne "de
        # set" fusionnee, PARALLELE a `levels`/`level_labels` deja calcules
        # plus haut (voir leur remarque) — SEULEMENT pour IN/OVER/OUT (voir
        # add_group_column) : LOGICIELS n'a qu'UNE SEULE source (le niveau
        # le plus profond, voir softs_dirs), une annotation n'y aurait aucun
        # sens.

        def add_group_column(kind: str, display: str, source_dirs: list[Path], style_title: str,
                              source_labels: list[str] | None = None):
            fill = kind == last_kind
            # Identite de dossier STABLE (pas "source_dirs[0]", qui varie
            # selon la selection courante ET l'ordre des sources fusionnees)
            # : "in"/"over"/"out" pointent vers le dossier statut du niveau
            # le plus profond (deja l'une des sources fusionnees, jamais
            # synthetique), "logiciels" vers son unique source (softs_dirs,
            # deja stable) — voir la remarque de l'utilisateur, "base toi
            # sur les colonnes creees avant les focus" : necessaire pour que
            # la punaise/la hauteur de ligne/les overrides de menu
            # contextuel persistent correctement sur le MEME dossier d'une
            # navigation a l'autre, exactement comme une colonne normale.
            stable_directory = softs_dirs[0] if kind == "logiciels" else terminal_path / kind
            column = Column(
                stable_directory, style_title,
                source_dirs=source_dirs, source_labels=source_labels, display_title=display,
                user_width=self._group_column_user_width, on_resize=self._on_group_column_resized,
                group_kind=kind, on_reorder=self._on_group_reorder,
                user_height=self._group_column_user_heights.get(kind), on_height_resize=self._on_group_height_resized,
                on_height_resize_begin=self._on_group_height_resize_begin,
                on_height_resize_end=self._on_group_height_resize_end,
                fill_height=fill,
                only_recognized_software=(kind == "logiciels" and work_dir_only_recognized_software),
                on_group_maximize=self._on_group_maximize, on_group_equalize=self._on_group_equalize)
            column.selected.connect(lambda col, p, k=kind: self._on_group_item_selected(col, p, k))
            column.activated.connect(self.on_activated)
            group_layout.addWidget(column, 1 if fill else 0)
            self.group_columns.append(column)

        # Chaque groupe (kind -> libelle/sources/style/annotations) construit
        # une fois, puis ajoute dans l'ORDRE COURANT (voir
        # _group_column_order, LOGICIELS premiere par defaut, reordonnable
        # par glisser-deposer de l'entete — voir la remarque de
        # l'utilisateur, "la colonne logiciel doit etre en premiere position
        # en haut ... possible de pouvoir glisser deposer ces colonnes afin
        # de pouvoir interchanger leur place ?").
        groups = {
            "logiciels": (work_dir_display, softs_dirs, work_dir_style, None),
        }
        for status_name in STATUS_FOLDERS:
            source_dirs = [status_folder_state(level, status_name)[1] for level in levels]
            # style_title = "IN"/"OVER"/"OUT" (PLUS "Contenu" partage) :
            # onglet de surcharge DEDIE desormais disponible pour chacune
            # (voir SettingsWindow._build_columns_page, la remarque de
            # l'utilisateur, "ajoute ... in over et out"). Le contenu
            # ouvert AU-DELA (voir _open_group_folder/on_selected, clic
            # sur une ligne DE ce groupe) reste lui sur le bucket generique
            # "Contenu", INCHANGE — seule la ligne DU groupe elle-meme
            # devient independamment stylable.
            groups[status_name] = (status_name.upper(), source_dirs, status_name.upper(), level_labels)
        for kind in active_group_order:
            display, source_dirs, style_title, source_labels = groups[kind]
            add_group_column(kind, display, source_dirs, style_title, source_labels)

        self._group_stack_wrapper = group_wrapper
        self.columns_layout.insertWidget(anchor + group_anchor_offset, group_wrapper)

        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _on_group_item_selected(self, column: Column, path: Path | None, kind: str) -> None:
        """Reagit a un clic sur une ligne du groupe IN/OVER/OUT/LOGICIELS
        (voir update_preview_stack) : un dossier ouvre son contenu dans une
        VRAIE colonne suivante (voir _open_group_folder) — navigation
        normale, pas l'explorateur Windows. Un fichier ne fait rien de plus
        ici (deja previsualise dans l'inspecteur par la selection normale
        de Column/on_selected — non branche pour ce groupe, voir sa
        remarque) ; double-clic l'ouvre malgre tout via l'application par
        defaut (voir Column.activated/on_activated, cable separement).
        `column` (colonne SOURCE, IN/OVER/OUT/LOGICIELS) : recupere
        l'etiquette d'origine (ROLE_SOURCE_LABEL) de la ligne cliquee sur
        SON item courant, pour l'ajouter entre parentheses a l'en-tete de
        la colonne ouverte — voir _open_group_folder/la remarque de
        l'utilisateur, "pour les titres dans les entetes de colonnes apres
        in over et out, j'aimerais ajouter aussi la mention entre
        parenthese"."""
        # Une SEULE selection de groupe a la fois : les 3 AUTRES groupes
        # n'ont plus rien a voir avec le point courant des qu'on clique
        # dans CELUI-CI — deselectionnes ENTIEREMENT (pas seulement rendus
        # "non focus"), sinon une vieille selection sans rapport (ex.
        # OVER > textures cliquee il y a longtemps) restait affichee
        # coloree indefiniment — voir la remarque de l'utilisateur, capture
        # a l'appui, "le repertoire textures est encore en selection alors
        # qu'il ne devrait pas du tout".
        if path is not None:
            for other in self.group_columns:
                if other is not column:
                    other.list.clearSelection()
                    other.list.setCurrentItem(None)
        # "focus" BRILLANT reserve au point VRAIMENT courant : un FICHIER
        # (rien ne s'ouvre plus loin) reste actif ; un DOSSIER ouvre une
        # VRAIE colonne plus loin qui devient alors le point courant reel —
        # cette ligne redevient "chemin" (non focus, bleu FONCE) comme une
        # colonne ancestrale de la chaine normale — voir la remarque de
        # l'utilisateur, "in/references qui est actuellement en focus
        # alors qu'il ne devrait pas non plus, il devrait par contre lui
        # etre en bleu fonce puisqu'il fait partie du cheminement".
        if path is not None:
            is_folder = path.is_dir()
            self._last_active_group_column = None if is_folder else column
        self.update_active_column()
        if path is None or not path.is_dir():
            return
        current_item = column.list.currentItem()
        source_label = current_item.data(ROLE_SOURCE_LABEL) if current_item is not None else None
        self._open_group_folder(path, source_label=source_label)

    def _open_group_folder(self, path: Path, title: str | None = None, source_label: str | None = None) -> None:
        """Ouvre `path` (indicateur in/over/out d'un _PreviewBlock, ou une
        ligne de dossier du groupe IN/OVER/OUT/LOGICIELS, voir
        update_preview_stack/_on_group_item_selected) dans une VRAIE
        colonne juste apres la FIN DE LA CHAINE REQUISE (voir
        _chain_expected_total, PAS le dernier niveau focus — meme raison
        que dans update_preview_stack, un niveau configure peut ne pas etre
        focus meme en derniere position) — jamais `Column_index`, une
        colonne arbitraire plus loin : ce groupe est TOUJOURS positionne
        juste apres la chaine, quoi que la navigation ait deja ouvert plus
        loin. STYLE toujours le bucket generique "Contenu" (comme toute
        colonne "au-dela de la chaine", voir on_selected/COLUMN_LABELS) —
        avant ce correctif, le nom du dossier lui-meme (en capitales)
        servait AUSSI de cle de style, creant une entree COLUMN_SETTINGS
        orpheline par nom de dossier different. En-tete AFFICHE, lui,
        dynamique (voir add_column/display_title) — le nom du dossier
        SELECTIONNE dans la colonne precedente (ici, la ligne cliquee dans
        IN/OVER/OUT/LOGICIELS) — voir la remarque de l'utilisateur, "le
        titre dans les colonnes apres focus doit aussi etre le nom du
        repertoire de la colonne precedente sauf les colonnes LOGICIELS IN
        OVER OUT" (ces 4-la restent des colonnes FANTOMES distinctes,
        jamais construites ici)."""
        insert_index = self._chain_expected_total() - 1
        self.prune_after(insert_index)
        # "(<etiquette d'origine>)" (voir source_label/ROLE_SOURCE_LABEL) —
        # MEME texte que l'annotation de la ligne cliquee dans IN/OVER/OUT,
        # mais rendu ici dans la couleur STANDARD de l'en-tete (un seul
        # QLabel, une seule couleur) — voir la remarque de l'utilisateur,
        # "avec la couleur standard de texte pour l'entete" (PAS la couleur
        # dediee aux annotations de ligne).
        display_title = f"{path.name} ({source_label})" if source_label else path.name
        self.add_column(path, insert_index + 1, title=title or "Contenu", display_title=display_title)
        self.update_active_column()
        self.update_preview_stack()
        self._sync_collapse_state()

    def _on_group_column_resized(self, new_width: int) -> None:
        """Relais de Column.resize_update pour une colonne du groupe
        IN/OVER/OUT/LOGICIELS (voir Column.__init__ user_width/on_resize,
        MEME principe que PipelineBrowser._on_preview_column_resized) :
        conserve la largeur choisie a la main pour qu'elle survive a la
        PROCHAINE reconstruction du groupe (update_preview_stack, appelee a
        chaque navigation), ET la repercute TOUT DE SUITE sur les 3 AUTRES
        colonnes du groupe — voir la remarque de l'utilisateur, "les 4
        colonnes doivent avoir la meme largeur constamment"."""
        self._group_column_user_width = new_width
        for column in self.group_columns:
            if column.width() != new_width:
                column._user_width = new_width
                column.setFixedWidth(new_width)

    def _on_group_height_resize_begin(self, kind: str) -> None:
        """Debut d'un glisser du bord bas d'une colonne du groupe (voir
        Column.height_resize_begin) : identifie les 2 SEULES colonnes
        concernees — `kind` ET sa voisine IMMEDIATEMENT SUIVANTE dans
        l'ordre COURANT (voir group_columns, deja dans cet ordre) — et fige
        leurs 2 hauteurs de depart. Aucune 3e colonne n'est jamais
        impliquee — voir la remarque de l'utilisateur, "les deux colonnes
        concernees doivent etre seulement les deux colonnes de part et
        d'autre de la zone de selection pour le slide" (redemande apres
        une tentative de simplification "hauteur independante par colonne"
        qui avait par erreur remplace cette regle — voir _on_group_height_
        resize_end pour la persistance par dossier, elle INCHANGEE, seule
        la MECANIQUE du glisser lui-meme revient ici a la regle d'origine)."""
        columns = self.group_columns
        idx = next((i for i, c in enumerate(columns) if c._group_kind == kind), None)
        if idx is None or idx + 1 >= len(columns):
            self._group_height_drag = None
            return
        above, below = columns[idx], columns[idx + 1]
        self._group_height_drag = (above, below, above.height(), below.height())
        # Badge de mesure (voir _show_resize_width) SUR LES 2 colonnes
        # concernees, pas seulement celle dont le bord est glisse (voir
        # Column.height_resize_begin, qui affiche deja le sien avec la cle
        # par defaut) — voir la remarque de l'utilisateur, "je veux le
        # cadre de mesure de la hauteur pour les deux colonnes concernees
        # par le redimensionnement".
        _show_resize_width(below, below.height(), key="group_below")

    def _on_group_height_resized(self, kind: str, delta: int) -> None:
        """Relais de Column.height_resize_update (voir sa remarque de tete —
        transmet un DELTA brut, ne se redimensionne pas elle-meme) : reporte
        `delta` sur la colonne du dessus (grandit/retrecit) et applique
        l'INVERSE exact a sa voisine du dessous (retrecit/grandit d'autant)
        — la somme des 2 hauteurs reste CONSTANTE, donc AUCUNE autre colonne
        ne bouge, ni en taille ni en position (contrairement a une seule
        colonne redimensionnee dans son coin, qui aurait pousse tout ce qui
        suit vers le bas) — voir la remarque de l'utilisateur, "ne pas
        descendre l'ensemble des colonnes vers le bas". Voisine du dessous
        = colonne fill_height (la derniere, voir set_group_fill_height) :
        elle n'a pas de hauteur PROPRE a faire varier en retour, son
        minimumHeight (deja pose par set_group_fill_height) suffit a lui
        seul a borner `delta` via le layout — rien a lui appliquer ici."""
        drag = self._group_height_drag
        if drag is None:
            return
        above, below, start_above, start_below = drag
        if above._group_kind != kind:
            return
        new_above = max(GROUP_COLUMN_MIN_HEIGHT, min(GROUP_COLUMN_MAX_HEIGHT, start_above + delta))
        if not below._group_fill_height:
            # Le delta REELLEMENT applicable est borne par la place que
            # peut ceder la voisine (jusqu'a SON minimum) — au-dela, la
            # colonne du dessus s'arrete de grandir plutot que de pousser
            # la voisine sous son minimum.
            max_above = start_above + (start_below - GROUP_COLUMN_MIN_HEIGHT)
            new_above = min(new_above, max_above)
            new_below = start_above + start_below - new_above
            below._group_user_height = new_below
            below.setFixedHeight(new_below)
            self._group_column_user_heights[below._group_kind] = new_below
        above._group_user_height = new_above
        above.setFixedHeight(new_above)
        # Force la mise a jour REELLE des positions/tailles AVANT de lire
        # below.mapToGlobal(...) dans _show_resize_width juste apres (voir
        # sa remarque, ancre sur le coin de `below`) — voir la remarque de
        # l'utilisateur, "pourquoi lorsque l'on change la hauteur
        # l'indication de hauteur de la colonne du bas change de position
        # si on monte ou si on descend" : SANS ce activate() ICI (deja fait
        # pour la branche fill_height, mais PAS pour celle-ci), la position
        # de `below` lue par mapToGlobal restait celle d'AVANT que `above`
        # n'ait sa NOUVELLE hauteur (setFixedHeight, juste au-dessus, ne
        # reflue le layout QUE de facon DIFFEREE) — d'ou un badge qui
        # "sautait" d'une quantite differente selon le sens du glisser (le
        # decalage accumule dependait de l'historique des positions
        # PRECEDEMMENT lues, pas de la position REELLE courante).
        wrapper = self._group_stack_wrapper
        if wrapper is not None:
            wrapper.layout().activate()
        _show_resize_width(below, below.height(), key="group_below")
        self._group_column_user_heights[kind] = new_above

    def _on_group_height_resize_end(self) -> None:
        self._group_height_drag = None
        _hide_resize_width(self, key="group_below")
        # Persiste EN TEMPS REEL (voir load_layout_settings/
        # update_preview_stack, la remarque de l'utilisateur "doit etre
        # enregistre en temps reel") dans le dossier TERMINAL courant (voir
        # _chain_terminal_path) — chaque relachement de glisser ecrit
        # immediatement le dict COMPLET (les 2 colonnes concernees, voir
        # _on_group_height_resized) : la PROCHAINE fois que ce MEME dossier
        # sera navigue, ces hauteurs seront retrouvees telles quelles.
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_maximize(self, kind: str) -> None:
        """Bouton d'entete "⤢" (voir Column.__init__ on_group_maximize) :
        agrandit `kind` au maximum, reduit les 3 AUTRES colonnes du groupe
        a la hauteur necessaire pour montrer TOUT leur contenu sans scroll
        (voir Column.group_content_height_hint) — voir la remarque de
        l'utilisateur, "un bouton qui me permette d'agrandir au maximum la
        fenetre en cours et de minimiser les autres au maximum en fonction
        de leur contenu". `layout.setStretchFactor` (PAS de reconstruction,
        voir _reorder_group_columns_animated pour le meme principe) :
        seule `kind` recoit desormais le facteur d'etirement, quelle que
        soit sa position dans l'ordre COURANT (independant de `fill_
        height`/set_group_fill_height, normalement lie a la DERNIERE
        position — ce bouton doit fonctionner sur N'IMPORTE LAQUELLE)."""
        columns = self.group_columns
        target = next((c for c in columns if c._group_kind == kind), None)
        wrapper = self._group_stack_wrapper
        if target is None or wrapper is None:
            return
        layout = wrapper.layout()
        for c in columns:
            if c is target:
                continue
            content_h = c.group_content_height_hint()
            c._group_fill_height = False
            c.setMinimumHeight(0)
            c.setMaximumHeight(_WIDGET_SIZE_MAX)
            c.setFixedHeight(content_h)
            c._group_user_height = content_h
            self._group_column_user_heights[c._group_kind] = content_h
            layout.setStretchFactor(c, 0)
        target._group_fill_height = True
        target.setMinimumHeight(0)
        target.setMaximumHeight(_WIDGET_SIZE_MAX)
        layout.setStretchFactor(target, 1)
        self._group_column_user_heights.pop(kind, None)
        layout.activate()
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_equalize(self) -> None:
        """Bouton d'entete "≡" (voir Column.__init__ on_group_equalize) :
        repartit la hauteur TOTALE actuelle du groupe (deja exactement
        celle du conteneur, une colonne l'occupant TOUJOURS en entier —
        voir fill_height) a PARTS EGALES entre les 4 — voir la remarque de
        l'utilisateur, "je veux un autre bouton pour mettre les 4 colonnes
        a exactement la meme hauteur". Aucune des 4 ne garde le facteur
        d'etirement ensuite (`setStretchFactor(c, 0)` partout) : un
        redimensionnement MANUEL derriere resterait sans effet sur le
        conteneur sinon (les 4 sont desormais TOUTES a hauteur FIXE)."""
        columns = self.group_columns
        wrapper = self._group_stack_wrapper
        if not columns or wrapper is None:
            return
        layout = wrapper.layout()
        total = sum(c.height() for c in columns) or GROUP_COLUMN_DEFAULT_HEIGHT * len(columns)
        equal = max(GROUP_COLUMN_MIN_HEIGHT, total // len(columns))
        for c in columns:
            c._group_fill_height = False
            c.setMinimumHeight(0)
            c.setMaximumHeight(_WIDGET_SIZE_MAX)
            c.setFixedHeight(equal)
            c._group_user_height = equal
            self._group_column_user_heights[c._group_kind] = equal
            layout.setStretchFactor(c, 0)
        layout.activate()
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_reorder(self, source_kind: str, target_kind: str) -> None:
        """Reagit au depot de l'entete `source_kind` sur l'entete
        `target_kind` (voir Column.__init__ group_kind/on_reorder,
        eventFilter) : deplace `source_kind` juste devant `target_kind` dans
        _group_column_order, puis reordonne les colonnes EXISTANTES en
        animant leur glissement (voir _reorder_group_columns_animated) —
        voir la remarque de l'utilisateur, "possible de pouvoir glisser
        deposer ces colonnes afin de pouvoir interchanger leur place ?"."""
        if source_kind == target_kind or source_kind not in self._group_column_order:
            return
        order = self._group_column_order
        order.remove(source_kind)
        order.insert(order.index(target_kind), source_kind)
        self._reorder_group_columns_animated()

    def _reorder_group_columns_animated(self, duration: int = 220) -> None:
        """Reordonne les widgets DEJA CONSTRUITS du groupe IN/OVER/OUT/
        LOGICIELS (voir group_columns) selon le nouvel ordre de
        _group_column_order, SANS reconstruction (leur contenu ne change
        pas, seule leur place change) : chacune glisse de son ancienne
        position vers la nouvelle plutot que de sauter instantanement — voir
        la remarque de l'utilisateur, "j'aimerai egalement une animation des
        colonnes qui s'interchange lorsque l'on depose la colonne".

        removeWidget()+addWidget() (pas insertWidget a un index precis) :
        reordonne le layout ENTIER, dans l'ordre d'iteration de
        _group_column_order, en une passe — plus simple qu'un deplacement
        relatif d'UN SEUL item. Le role fill_height (voir Column.
        set_group_fill_height) suit aussi l'ordre : si la colonne qui
        devient DERNIERE change, celle qui l'etait perd sa place etiree
        (reprend une hauteur fixe) et la nouvelle derniere l'acquiert —
        voir la remarque de l'utilisateur, "il est important que la
        derniere colonne aille bien jusqu'en bas de la page". Anime la
        geometrie ENTIERE (pas seulement la position) : la colonne qui
        change de role fill_height change aussi de TAILLE, pas seulement de
        place. layout.activate() force le recalcul SYNCHRONE des geometries
        (sinon les nouvelles valeurs ne seraient connues qu'au prochain
        passage par la boucle d'evenements, une fois l'animation deja
        demarree sur les anciennes)."""
        wrapper = self._group_stack_wrapper
        if wrapper is None or not self.group_columns:
            self.update_preview_stack()
            return
        by_kind = {c._group_kind: c for c in self.group_columns}
        old_geometries = {c: c.geometry() for c in self.group_columns}
        layout = wrapper.layout()
        new_last_kind = self._group_column_order[-1] if self._group_column_order else None
        for kind in self._group_column_order:
            column = by_kind.get(kind)
            if column is None:
                continue
            layout.removeWidget(column)
            layout.addWidget(column, 1 if kind == new_last_kind else 0)
            column.set_group_fill_height(kind == new_last_kind)
        layout.activate()
        self.group_columns = [by_kind[k] for k in self._group_column_order if k in by_kind]

        if getattr(self, "_group_reorder_anim", None) is not None:
            self._group_reorder_anim.stop()
        group = QParallelAnimationGroup(self)
        for column, old_geom in old_geometries.items():
            new_geom = column.geometry()
            if new_geom == old_geom:
                continue
            column.setGeometry(old_geom)
            anim = QPropertyAnimation(column, b"geometry")
            anim.setDuration(duration)
            anim.setStartValue(old_geom)
            anim.setEndValue(new_geom)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)
        # Garder la reference : sans elle, le GC Python peut detruire le
        # groupe avant la fin de l'animation (meme piege que Column.
        # _animate_width).
        self._group_reorder_anim = group
        group.start()

    def on_selected(self, column: Column, path: Path | None):
        index = self.columns.index(column)
        self.prune_after(index)
        # Configuration de chaine (voir load_project_columns) : (re)lue
        # UNIQUEMENT quand c'est la colonne Projets elle-meme qui vient
        # d'etre cliquee — None si aucune selection (repli legacy) ou si ce
        # projet n'a pas de fichier de configuration — voir la remarque de
        # tete de _active_project_config. REMISE A None des que "Type"
        # change de selection : sans ca, une configuration "base 2" (voir
        # ColumnConfigDialog.MIN_STEPS) restait ACCROCHEE au projet
        # PRECEDENT tant que "Projets" n'avait pas encore ete recliquee —
        # voir la remarque de l'utilisateur, "quand je suis sette par
        # exemple dans bib/houdini en base 2 et que je reviens en 3d des
        # colonnes disparaissent" : reselectionner "Type" (depth=1,
        # ajoute TOUJOURS "Projets" via la logique GENERIQUE, jamais
        # pilotee par une config de projet) tombait alors, a tort, dans la
        # branche "chaine configuree" du bloc plus bas (index=0 < expected_
        # total-1, calcule depuis ce config PERIME) avec level_index=-1 —
        # `config["columns"][-1]` levait IndexError sur une liste VIDE
        # (base 2), interrompant on_selected APRES le prune_after mais
        # AVANT de rajouter la nouvelle colonne "Projets" : elle
        # disparaissait alors purement et simplement, sans jamais
        # revenir.
        if column.column_title == "Type":
            self._active_project_config = None
        elif column.column_title == "Projets":
            self._active_project_config = load_project_columns(path) if path is not None else None
        if path is None:
            self.detail.clear()
            self.update_active_column()
            self.update_preview_stack()
            self._sync_collapse_state()
            return
        self.path_label.setText(str(path))
        self.detail.show_path(path)
        if path.is_dir():
            depth = index + 1
            config = self._active_project_config
            # `index < expected_total - 1` (PAS juste `config is not None`) :
            # la chaine CONFIGUREE ne pilote QUE les colonnes ENCORE DANS
            # la chaine elle-meme (avant le repertoire de travail) — au-
            # dela (contenu ouvert depuis le groupe fantome IN/OVER/OUT/
            # LOGICIELS, voir _open_group_folder, ou tout niveau descendu
            # ENSUITE), la navigation doit rester GENERIQUE et illimitee,
            # exactement comme en legacy — voir la remarque de
            # l'utilisateur, "quand on navigue de dossier en dossier, au
            # bout d'un moment tu ne crees plus de colonnes, comme si tu
            # avais mis une limite, je veux supprimer cette limite" :
            # AVANT ce correctif, `level_index < len(columns_cfg)` restait
            # FAUX pour TOUJOURS des qu'on descendait plus loin que la
            # chaine configuree elle-meme (son index ne fait QUE croitre),
            # bloquant silencieusement toute colonne suivante dans une
            # BRANCHE de contenu ouverte apres le groupe.
            expected_total = self._chain_expected_total()
            # `index >= 1` (garde-fou EN PLUS de la remise a None ci-dessus,
            # voir sa remarque) : depth=1 (index=0, "Type") ajoute TOUJOURS
            # "Projets" par la logique GENERIQUE plus bas, jamais par la
            # chaine configuree d'un projet — quel que soit `config`,
            # level_index (= depth - 2) y serait negatif.
            if config is not None and index >= 1 and index < expected_total - 1:
                # Chaine CONFIGUREE (voir ColumnConfigDialog) : depth 2 =
                # 1er niveau configure (config["columns"][0]), etc. Chaque
                # niveau pointe vers un sous-dossier au nom FIXE (voir
                # _named_subdir) — la colonne liste ensuite son CONTENU
                # (filtre par show_dirs/show_files/omit_dirs/omit_files),
                # l'utilisateur clique une entree pour descendre — voir la
                # remarque de l'utilisateur, "chaque colonne configuree
                # pointe vers un nom de dossier fixe ... la colonne liste
                # le contenu ... filtre par les options Afficher/Omettre".
                level_index = depth - 2
                col_cfg = config["columns"][level_index]
                child_dir = _named_subdir(path, col_cfg["name"])
                # style_title="Sous-projet" (voir Column.style_title,
                # settings_window "INTERMEDIAIRE") : le NOM affiche
                # reste celui choisi par l'utilisateur (title=col_cfg
                # ["name"], ex. "test1" — identite/annotations
                # inchangees), mais l'APPARENCE (hauteur de ligne,
                # police, couleurs, bordures, padding...) suit TOUJOURS
                # le MEME reglage General > Colonnes > INTERMEDIAIRE,
                # quel que soit le nombre de niveaux configures — voir
                # la remarque de l'utilisateur, "doit controler toutes
                # les colonnes entre celle de projet et focus" : sans
                # ca, un titre inconnu retombait sur le bucket
                # generique "Contenu" (voir _col_key), partage a tort
                # avec les colonnes fantomes IN/OVER/OUT.
                self.add_column(
                    child_dir, depth, title=col_cfg["name"],
                    is_focus_level=col_cfg["focus"], style_title="Sous-projet",
                    show_dirs=col_cfg["show_dirs"], show_files=col_cfg["show_files"],
                    omit_dirs=frozenset(n.lower() for n in col_cfg["omit_dirs"]),
                    omit_files=frozenset(n.lower() for n in col_cfg["omit_files"]),
                    # En-tete DYNAMIQUE (voir add_column/la remarque de
                    # l'utilisateur, "le nom des colonnes correspond au nom
                    # du repertoire selectionne dans la colonne
                    # precedente") : `path` est le dossier SELECTIONNE dans
                    # la colonne precedente — `child_dir` (son contenu
                    # FIXE, ex. "test1") n'aurait ici aucun rapport.
                    display_title=path.name)
            elif config is not None and index == expected_total - 1:
                # Dernier niveau configure ATTEINT (`column` EST le niveau
                # terminal, pas encore de contenu ouvert au-dela) — comme
                # "Logiciels" en legacy, pas de vraie colonne ici, le
                # groupe fantome (update_preview_stack) gere le
                # "Repertoire de travail" (config["work_dir"]).
                pass
            else:
                # Legacy (config is None) : `depth` reste ALIGNE sur
                # COLUMN_LABELS par construction (Type/Projets/Sous-projet/
                # Logiciels/Contenu, expected_total TOUJOURS 3) — depth 3
                # ("Logiciels") reste donc le seul et unique endroit ou
                # sauter l'ajout d'une VRAIE colonne : elle fait partie du
                # groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
                # stack), reconstruit a partir de la selection courante.
                #
                # Chaine CONFIGUREE (config is not None) : tout ce qui
                # atteint CETTE branche est du contenu ouvert AU-DELA du
                # terminal (voir _open_group_folder, puis toute descente
                # ulterieure) — le terminal lui-meme est deja gere par le
                # "elif index == expected_total - 1" ci-dessus. `depth` n'y
                # est PLUS forcement aligne avec COLUMN_LABELS des que "set"
                # est desactive ou que le nombre de niveaux configures
                # differe de 1 (voir _chain_expected_total) : y reappliquer
                # le lookup COLUMN_LABELS/le test SOFTWARE_COLUMN_LABEL
                # pouvait a tort retomber sur "Logiciels" et sauter
                # l'ajout — voir la remarque de l'utilisateur, "on ne doit
                # pas avoir de limite de repertoire quand le set est
                # desactive, actuellement je ne peux pas aller dans plus de
                # deux repertoire". Toujours le bucket generique "Contenu"
                # ici (comme _open_group_folder), jamais de lookup par depth.
                if config is None:
                    title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
                    if title != SOFTWARE_COLUMN_LABEL:
                        self.add_column(path, depth)
                else:
                    self.add_column(path, depth, title="Contenu")
        self.update_active_column()
        self.update_preview_stack()
        self._sync_collapse_state()

    def _sync_collapse_state(self):
        """Replie automatiquement TOUTES les colonnes de la chaine requise
        (voir _chain_expected_total/Column.collapsible, PAS une liste de
        titres fixe — N quelconque : 3 en legacy, ou le nombre de niveaux
        configures, voir la remarque de l'utilisateur, "si un projet est
        sur une base 3 etapes, 3 colonnes devront se rabattre, si c'est une
        base 4, 4 colonnes ... en fait c'est toutes les colonnes avant les
        colonnes de focus") des que la chaine est COMPLETEMENT settee
        jusqu'au repertoire de travail (voir _chain_terminal_path) : ce
        contexte devient fixe, ces colonnes de navigation n'ont plus besoin
        de rester deployees. Desactivable entierement (voir General >
        Application, "un toggle qui permet ou pas de rabattre les colonnes
        de set" — auto_collapse_set_columns()) : dans ce cas, jamais replie
        automatiquement, mais l'icone de repli MANUEL sur la colonne des
        vignettes reste disponible (voir _toggle_project_columns). Ne force
        ce repli qu'UNE fois par selection (voir _auto_collapse_armed) : un
        depli manuel ensuite (icone sur la colonne des vignettes) n'est pas
        systematiquement annule tant que la selection reste la meme.
        Redeploie tout automatiquement des que la chaine n'est plus
        complete (retour en arriere dans la navigation), pour laisser le
        choix a nouveau visible, et rearme alors le repli automatique pour
        la prochaine selection."""
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        has_selection = self._chain_terminal_path() is not None
        if not has_selection or not focus_enabled:
            # Sans colonne Focus (voir ColumnConfigDialog, toggle "Focus" a
            # 0), replier les colonnes d'avant n'a plus aucun but (voir sa
            # remarque de tete : ce repli sert a REVELER la colonne Focus,
            # qui n'existe pas ici) — les colonnes de la chaine restent donc
            # TOUJOURS deployees dans ce cas.
            self._auto_collapse_armed = True
            if self._project_columns_collapsed:
                self._apply_project_columns_collapsed(False)
        elif auto_collapse_set_columns() and self._auto_collapse_armed and not self._project_columns_collapsed:
            self._apply_project_columns_collapsed(True)
            self._auto_collapse_armed = False

    def _toggle_project_columns(self):
        """Reagit a l'icone unique portee par la colonne des vignettes
        (voir PreviewColumn/update_preview_stack) : bascule les colonnes de
        la chaine (voir _apply_project_columns_collapsed), et desarme le
        repli automatique pour que ce choix manuel ne soit pas aussitot
        ecrase par _sync_collapse_state tant que la chaine reste la meme.
        Toujours disponible, MEME si le repli automatique est desactive
        (voir auto_collapse_set_columns/_sync_collapse_state) : c'est un
        geste manuel independant."""
        self._apply_project_columns_collapsed(not self._project_columns_collapsed)

    def _on_preview_column_resized(self, new_width: int):
        """Relais de PreviewColumn.resize_update (voir _preview_column_
        user_width, sa remarque de tete) : conserve la largeur choisie a la
        main pour qu'elle survive a la PROCHAINE reconstruction des
        colonnes Focus (update_preview_stack, appelee a chaque navigation),
        ET la repercute TOUT DE SUITE sur les AUTRES colonnes Focus (voir
        PreviewColumn.set_width_external) : ce sont des colonnes SEPAREES
        (voir la remarque de l'utilisateur, "deux colonnes separees, une
        en dessous de l'autre") mais elles doivent rester alignees a la
        meme largeur, glisser le bord de L'UNE suffit a redimensionner
        les autres."""
        self._preview_column_user_width = new_width
        for column in self.image_preview_columns:
            if column.width() != new_width:
                column.set_width_external(new_width)
        self._auto_collapse_armed = False

    def _apply_project_columns_collapsed(self, collapsed: bool):
        """Replie/deplie EXACTEMENT les N premieres colonnes de self.columns
        (voir _chain_expected_total), N = le nombre d'etapes du projet
        courant — jamais au-dela : une colonne de contenu ouverte depuis le
        groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) reste
        TOUJOURS deployee, quoi qu'il arrive aux colonnes de set — voir la
        remarque de l'utilisateur, "attention a bien rabattre toutes
        colonnes ... c'est toutes les colonnes avant les colonnes de
        focus"."""
        self._project_columns_collapsed = collapsed
        expected_total = self._chain_expected_total()
        for c in self.columns[:expected_total]:
            c.set_collapsed(collapsed)
        if self.image_preview_columns:
            self.image_preview_columns[0].set_toggle_state(collapsed)

    def on_activated(self, path: Path):
        open_path(path)

    def browse_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Racine du pipeline", self.root_field.text()
        )
        if chosen:
            self.root_field.setText(chosen)
            self.reload()

    def open_settings(self):
        # Deja ouverte : la ramener au premier plan plutot que d'en ouvrir
        # une seconde (qui ecraserait sa propre previsualisation). La
        # fenetre precedente est detruite cote C++ des sa fermeture (voir
        # WA_DeleteOnClose ci-dessous) : la reference Python devient alors
        # invalide et tout appel dessus (meme isVisible()) leve un
        # RuntimeError qu'il faut absorber pour pouvoir en rouvrir une neuve.
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None:
            try:
                still_visible = existing.isVisible()
            except RuntimeError:
                still_visible = False
            if still_visible:
                existing.raise_()
                existing.activateWindow()
                return
        dialog = SettingsWindow(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        # Non modale : la fenetre principale reste interactive et se
        # met a jour en direct pendant qu'on ajuste les parametres.
        dialog.settingsChanged.connect(self._apply_settings)
        dialog.settingsSaved.connect(self._apply_settings)
        self._settings_dialog = dialog
        dialog.show()

    def _apply_settings(self, settings: dict):
        """Applique des reglages (live, pendant qu'on les ajuste dans la
        fenetre de parametres, ou definitifs a l'enregistrement — les deux
        cas appellent cette meme methode). N'ecrit jamais sur le disque
        (voir SettingsWindow._on_save pour la persistance).

        Si la racine n'a pas change, les colonnes existantes sont juste
        rafraichies sur place (refresh_all_columns) : la navigation en cours
        (profondeur, selection) n'est PAS perdue. Un reload() complet n'a
        lieu que si la racine elle-meme a change, ce qui invalide de toute
        facon le chemin courant."""
        # Cliche AVANT/APRES (voir refresh_all_columns(relayout_titles=...))
        # de la hauteur/l'espacement de ligne EFFECTIFS (COLUMN_SETTINGS,
        # deja resolus general/surcharge par apply_all_settings) de CHAQUE
        # colonne : seules celles ou cette paire a reellement change auront
        # besoin d'un doItemsLayout() plus bas — un cran de slider qui ne
        # touche qu'une couleur/bordure/rayon/padding n'affecte le sizeHint()
        # d'AUCUNE ligne, quelle que soit la colonne — voir la remarque de
        # l'utilisateur, "il y a des ralentissements dans les animations,
        # optimise un maximum".
        prev_geometry = {title: (conf["height"], conf["spacing"]) for title, conf in COLUMN_SETTINGS.items()}
        prev_omissions = (GLOBAL_OMIT_FILE_NAMES.copy(), GLOBAL_OMIT_FILE_EXTENSIONS.copy())
        apply_all_settings(settings)
        omissions_changed = prev_omissions != (GLOBAL_OMIT_FILE_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS)
        changed_titles = {
            title for title, conf in COLUMN_SETTINGS.items()
            if (conf["height"], conf["spacing"]) != prev_geometry.get(title)
        }
        # column_gap() : apply_all_settings vient de le mettre a jour (voir
        # set_column_gap ci-dessus), mais c'est un global — encore besoin
        # de le repercuter ICI sur l'instance reelle de columns_layout,
        # comme refresh_all_columns le fait deja pour la largeur/hauteur
        # des colonnes.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))
        if settings["root_path"] != self.root_field.text():
            self.root_field.setText(settings["root_path"])
            self.reload()
        else:
            self.refresh_all_columns(
                rescan=omissions_changed,
                relayout_titles=None if omissions_changed else changed_titles,
            )
        if omissions_changed:
            hidden_path = self.detail._current_path
            if hidden_path:
                name = Path(hidden_path).name.casefold()
                if (name in GLOBAL_OMIT_FILE_NAMES
                        or any(name.endswith("." + extension) for extension in GLOBAL_OMIT_FILE_EXTENSIONS)):
                    self.detail.clear()
            idle_scheduler = getattr(self, "_idle_preview_scheduler", None)
            if idle_scheduler is not None:
                if idle_scheduler.scan_cancel_event is not None:
                    idle_scheduler.scan_cancel_event.set()
                idle_scheduler.queue.clear()
                idle_scheduler.done.clear()
                if (idle_scheduler.active_key is not None and idle_scheduler.cancel_event is not None):
                    active_name = Path(idle_scheduler.active_key).name.casefold()
                    if (active_name in GLOBAL_OMIT_FILE_NAMES
                            or any(active_name.endswith("." + ext) for ext in GLOBAL_OMIT_FILE_EXTENSIONS)):
                        idle_scheduler.cancel_event.set()
                idle_scheduler.last_scan = 0.0
        # app.setStyleSheet (dans refresh_colors -> refresh_style) repolit
        # TOUS les widgets de TOUTES les fenetres de l'appli — le poste le
        # plus cher, et de loin, de tout ce rafraichissement (mesure a
        # plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte, voir _flush_stylesheet_rebuild). Un slider qui ne
        # touche ni aux couleurs, ni au cadre/rayon des boutons, ni au
        # cadre/rayon des zones de saisie, ni au rayon des tableaux (largeur
        # de colonne, echelle, hauteur d'entete...) n'a aucune raison de le
        # declencher a chaque cran : seule une vraie difference sur ces
        # points (les seuls que build_stylesheet lit reellement) force la
        # reconstruction complete de la feuille de style — MAIS durant un
        # glisser de COULEUR, cette difference est reelle a CHAQUE tick, ce
        # gate seul ne suffit donc plus (voir la remarque de l'utilisateur,
        # "il y a toujours un tres gros problemes de performance") : la
        # reconstruction elle-meme est donc REGROUPEE (voir
        # _flush_stylesheet_rebuild), jamais appelee directement ici.
        colors = settings.get("colors") or {}
        style_key = (
            tuple(colors.get(k, C[k]) for k in STYLESHEET_COLOR_KEYS),
            settings.get("button_radius"),
            settings.get("button_frame"),
            settings.get("input_radius"),
            settings.get("input_frame"),
            settings.get("table_radius"),
        )
        if style_key != self._last_style_key:
            self._last_style_key = style_key
            self._pending_stylesheet_rebuild = True
            if not self._stylesheet_rebuild_timer.isActive():
                self._stylesheet_rebuild_timer.start()
        self.refresh_colors(rebuild_stylesheet=False)
        self.refresh_chrome_sizes()
        self._apply_native_frame()

    def _flush_stylesheet_rebuild(self):
        """Reconstruction DIFFEREE et REGROUPEE de la feuille de style
        globale (voir _apply_settings/app_style.refresh_style) — le SEUL
        appel a ce chemin couteux (mesure a plus de 3 SECONDES une fois la
        fenetre de parametres ouverte, des milliers de widgets ayant
        chacun leur propre QSS local a re-cascader contre le nouveau QSS
        d'appli). `_stylesheet_rebuild_timer` (250ms, singleShot, voir
        __init__) le declenche au plus tot 250ms apres le DERNIER
        changement de style_key — pendant un glisser continu de couleur,
        cela ramene un cout de plusieurs secondes PAR TICK (~30ms) a un
        seul appel toutes les ~250ms, invisible a l'oeil (le style
        GENERIQUE — boutons/scrollbars/menus — n'est de toute facon pas ce
        qu'on regarde en glissant une pastille de couleur ; tout le reste
        du retour visuel en direct passe par refresh_colors(rebuild_
        stylesheet=False), deja rejoue a chaque tick, DEJA rapide)."""
        if not self._pending_stylesheet_rebuild:
            return
        self._pending_stylesheet_rebuild = False
        app = QApplication.instance()
        if app is not None:
            refresh_style(app)

    def refresh_chrome_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) aux
        widgets permanents de la fenetre (barre de titre, barre du haut),
        qui comme leurs polices (voir refresh_chrome_fonts) ne sont
        construits qu'une fois et ne suivraient donc pas le slider d'echelle
        sans ce rafraichissement explicite."""
        self.titlebar.refresh_sizes()
        self.root_field.setFixedHeight(scaled(24))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFixedHeight(scaled(24))
        self.btn_settings.setFixedWidth(scaled(28))

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.titlebar.title_label.setFont(role_font("titles", 11, 400, tracking=0.01))
        self.titlebar.title_label.setStyleSheet(f"color: {role_color('titles', C['label'])}; background: transparent;")
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.root_field.setFont(role_font("info", 12, 400))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place):
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.set_colors(role_color("buttons", "#c4cacf"), C["text"])
        self.synced_label.setFont(role_font("info2", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        for column in self.columns:
            column.refresh_header()
        self.detail.refresh_header()
        for column in self.image_preview_columns:
            column.refresh_header()
        for column in self.group_columns:
            column.refresh_header()
        is_dir = True
        if self.columns:
            selected = self.columns[-1].current_path()
            if selected is not None:
                is_dir = selected.is_dir()
        self.detail.refresh_fonts(is_dir)

    def refresh_colors(self, rebuild_stylesheet: bool = True):
        """Reapplique toutes les couleurs (voir app_style.C, mutable via
        set_color) aux widgets dont le style QSS a ete fixe une fois pour
        toutes a la construction — indispensable pour que la page Couleurs
        de la fenetre de parametres s'applique en temps reel (voir la
        remarque sur set_color dans app_style.py).

        rebuild_stylesheet=False saute uniquement le app.setStyleSheet
        global (repolissage de TOUS les widgets de l'appli, tres couteux) :
        a utiliser quand on sait qu'aucune des valeurs lues par
        build_stylesheet (couleurs, cadre/rayon des boutons, cadre/rayon des
        zones de saisie, rayon des tableaux) n'a bouge (voir _apply_settings),
        le reste de cette methode restant assez leger pour tourner a chaque
        rafraichissement."""
        if rebuild_stylesheet:
            app = QApplication.instance()
            if app is not None:
                refresh_style(app)
        self.central.setStyleSheet(
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {WINDOW_RADIUS}px; }}"
        )
        self.columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['window']}; }}")
        self.titlebar.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        for btn in (self.titlebar.btn_min, self.titlebar.btn_max, self.titlebar.btn_close):
            btn.set_colors(C["label"], C["text"])
        self.topbar.setStyleSheet(f"#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['border']}; }}")
        self.statusbar.setStyleSheet(f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}")
        for column in self.columns:
            column.refresh_colors()
        for column in self.group_columns:
            column.refresh_colors()
        for column in self.image_preview_columns:
            column.refresh_colors()
        self.detail.refresh_colors()
        self.refresh_chrome_fonts()
        # PAS de update_preview_stack() ici : le seul appelant
        # (_apply_settings) vient deja d'en faire un via refresh_all_columns
        # / reload juste avant — le rejouer ici doublerait pour rien le
        # travail (stat + chargement des vignettes) a chaque rafraichissement.


def apply_all_settings(settings: dict) -> None:
    """Point d'entree unique qui recopie un dict de reglages (voir
    settings_window.DEFAULT_SETTINGS) dans les globals/tokens qu'ils
    pilotent : geometrie par colonne, apercu empile, fenetre, boutons,
    entete de colonne, echelle generale, couleurs et roles typographiques.
    N'a aucun effet visible tant qu'aucun refresh (refresh_all_columns,
    refresh_colors, refresh_chrome_fonts...) n'est rejoue par-dessus —
    voir PipelineBrowser._apply_settings et main() pour ces deux appelants."""
    global WINDOW_RADIUS, BUTTON_RADIUS, HEADER_HEIGHT, HEADER_PADDING
    global PREVIEW_IMAGE_PAD, PREVIEW_IMAGE_RADIUS
    global RESIZE_BADGE_STYLE
    global STEP_BADGE_STYLE
    global COLLAPSE_TOGGLE_MODE
    global SHORTCUT_TEXT_STYLE
    global DETAIL_PANEL_WIDTH
    global GLOBAL_OMIT_FILE_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS

    omit_names = settings.get("application_omit_file_names") or []
    omit_extensions = settings.get("application_omit_extensions") or []
    if isinstance(omit_names, str):
        omit_names = omit_names.replace(";", ",").split(",")
    if isinstance(omit_extensions, str):
        omit_extensions = omit_extensions.replace(";", ",").split(",")
    GLOBAL_OMIT_FILE_NAMES = {
        str(value).strip().casefold()
        for value in omit_names
        if str(value).strip()
    }
    GLOBAL_OMIT_FILE_EXTENSIONS = {
        str(value).strip().casefold().removeprefix("*.").lstrip(".")
        for value in omit_extensions
        if str(value).strip().lstrip("*.")
    }

    # Entete de colonne : padding droit des icones + police/gras/couleur/
    # hauteur du titre (voir Column.refresh_header, app_style.COLUMN_FRAME_
    # KEYS/column_style_for — desormais des cles GENERALES comme le reste
    # de cette liste, overridables PAR TITRE, PAS un dict a part) — voir la
    # remarque de l'utilisateur, "ajoute un slider pour le padding droit
    # des icones ... choix de la police + gras/regular + couleur" puis
    # "mets a jour egalement les colonnes overidees ... avec tous les
    # nouveaux parametres de general".

    # Icone de niveaux (badge numerote, colonne "Projets" — voir
    # _step_badge_rect/_paint_unified_row, Settings > Colonnes > Projets >
    # Colonnes > "Icone de niveaux") — voir la remarque de l'utilisateur,
    # "j'aimerais pouvoir controler l'aspect de cette petite icone".
    STEP_BADGE_STYLE = {
        "width": int(settings.get("step_badge_width", 18)),
        "height": int(settings.get("step_badge_height", 18)),
        "border_enabled": _coerce_side_enabled(settings.get("step_badge_border_enabled", False)),
        "border": settings.get("step_badge_border") or {},
        "border_thickness": int(settings.get("step_badge_border_thickness", 1)),
        "radius": _radius_dict(settings.get("step_badge_radius", 9)),
        "colors": {
            2: settings.get("step_badge_color_base2", "#5c6368"),
            3: settings.get("step_badge_color_base3", "#5c6368"),
            4: settings.get("step_badge_color_base4", "#3f6f9f"),
            5: settings.get("step_badge_color_base5", "#3f6f9f"),
            6: settings.get("step_badge_color_base6", "#d9822b"),
            "N": settings.get("step_badge_color_basen", "#5c6368"),
        },
        "text_colors": {
            2: settings.get("step_badge_text_color_base2", "#eef2f5"),
            3: settings.get("step_badge_text_color_base3", "#eef2f5"),
            4: settings.get("step_badge_text_color_base4", "#eef2f5"),
            5: settings.get("step_badge_text_color_base5", "#eef2f5"),
            6: settings.get("step_badge_text_color_base6", "#eef2f5"),
            "N": settings.get("step_badge_text_color_basen", "#eef2f5"),
        },
        "offset_x": int(settings.get("step_badge_offset_x", 4)),
        "offset_y": int(settings.get("step_badge_offset_y", 0)),
        "font_family": settings.get("step_badge_font_family", ""),
        "font_bold": bool(settings.get("step_badge_font_bold", True)),
        "font_smoothing_enabled": bool(settings.get("step_badge_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("step_badge_font_smoothing", "current"),
        "border_smoothing": bool(settings.get("step_badge_border_smoothing", True)),
    }

    COLLAPSE_TOGGLE_MODE = settings.get("collapse_toggle_mode", "chevrons")

    # Raccourcis (voir ROLE_IS_SHORTCUT, Settings > RACCOURCI) — General >
    # RACCOURCI > "Police".
    SHORTCUT_TEXT_STYLE = {
        "font_family": settings.get("shortcut_font_family", ""),
        "font_bold": bool(settings.get("shortcut_font_bold", False)),
        "font_italic": bool(settings.get("shortcut_font_italic", False)),
        "color": settings.get("shortcut_color", "#8fb4d5"),
        "font_size": int(settings.get("shortcut_font_size", 11)),
        "font_smoothing_enabled": bool(settings.get("shortcut_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("shortcut_font_smoothing", "current"),
    }
    DETAIL_PANEL_WIDTH = int(settings.get("detail_panel_width", 300))

    # Habillage des sliders peints a la main (voir settings_window.
    # _MiniSlider/_SLIDER_STYLE/_sync_slider_style, General > Geometrie >
    # Slider "Rail"/"Selecteur") : auparavant synchronise UNIQUEMENT depuis
    # SettingsWindow.__init__/_apply_slider_style, jamais depuis ce point
    # d'entree central — un _MiniSlider construit AILLEURS (voir Column.
    # _add_context_slider, menu contextuel) AVANT la toute premiere
    # ouverture de la fenetre de parametres dans la session gardait donc
    # les couleurs par defaut codees en dur, jamais celles enregistrees —
    # voir la remarque de l'utilisateur, "les sliders des menus contextuels
    # n'ont pas le style defini dans les settings".
    _sync_slider_style(settings)

    RESIZE_BADGE_STYLE = {
        "position": settings.get("resize_badge_position", "bottom_right"),
        "offset_x": int(settings.get("resize_badge_offset_x", 8)),
        "offset_y": int(settings.get("resize_badge_offset_y", 8)),
        "font_family": settings.get("resize_badge_font_family", ""),
        "font_bold": bool(settings.get("resize_badge_font_bold", True)),
        "font_italic": bool(settings.get("resize_badge_font_italic", False)),
        "font_size": int(settings.get("resize_badge_font_size", 11)),
        "font_smoothing_enabled": bool(settings.get("resize_badge_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("resize_badge_font_smoothing", "current"),
        "text_color": settings.get("resize_badge_text_color", "#d6d9dc"),
        "bg_color": settings.get("resize_badge_bg_color", "#202326"),
        "border_enabled": _coerce_side_enabled(settings.get("resize_badge_border_enabled", True)),
        "border": settings.get("resize_badge_border") or {},
        "border_thickness": int(settings.get("resize_badge_border_thickness", 1)),
        "border_radius": _radius_dict(settings.get("resize_badge_border_radius", 4)),
    }

    for title, conf in settings.get("columns", {}).items():
        if title not in COLUMN_SETTINGS:
            continue
        COLUMN_SETTINGS[title].update({
            "width": conf.get("width", COLUMN_SETTINGS[title]["width"]),
            "height": conf.get("height", COLUMN_SETTINGS[title]["height"]),
            "spacing": conf.get("spacing", COLUMN_SETTINGS[title]["spacing"]),
        })
        if "img_pad" in conf:
            COLUMN_SETTINGS[title]["img_pad"] = conf["img_pad"]
        if "img_radius" in conf:
            COLUMN_SETTINGS[title]["img_radius"] = conf["img_radius"]
        if "plain_height" in conf:
            COLUMN_SETTINGS[title]["plain_height"] = conf["plain_height"]
    # "Sous-projet" peut suivre les valeurs de "Projets" (voir les toggles
    # de liaison dans la fenetre de parametres) : resolu ici, une fois pour
    # toutes, plutot qu'a chaque ligne dessinee.
    sous = settings.get("columns", {}).get("Sous-projet", {})
    if sous.get("img_pad_link", True):
        COLUMN_SETTINGS["Sous-projet"]["img_pad"] = COLUMN_SETTINGS["Projets"]["img_pad"]
    if sous.get("img_radius_link", True):
        COLUMN_SETTINGS["Sous-projet"]["img_radius"] = COLUMN_SETTINGS["Projets"]["img_radius"]

    # dicts (4 cotes / 4 coins INDEPENDANTS, voir _SquarePreviewImage._
    # refresh) — voir la remarque de l'utilisateur, "controle des paddings
    # sur les 4 cotes comme partout ailleurs ... pareil pour les coins
    # arrondis".
    PREVIEW_IMAGE_PAD = settings.get("preview_padding") or {}
    PREVIEW_IMAGE_RADIUS = settings.get("preview_radius") or {}

    HEADER_HEIGHT = settings.get("header_height", HEADER_HEIGHT)
    HEADER_PADDING = settings.get("header_padding", HEADER_PADDING)
    WINDOW_RADIUS = settings.get("window_radius", WINDOW_RADIUS)
    BUTTON_RADIUS = settings.get("button_radius", BUTTON_RADIUS)
    set_button_radius(BUTTON_RADIUS)
    set_button_frame(settings.get("button_frame", True))
    set_input_frame(settings.get("input_frame", True))
    set_input_radius(settings.get("input_radius", 0))
    set_table_radius(settings.get("table_radius", 0))
    set_columns_resizable(settings.get("columns_resizable", True))
    set_auto_collapse_set_columns(settings.get("auto_collapse_set_columns", True))
    set_custom_softwares(settings.get("custom_softwares", []))
    set_removed_softwares(settings.get("removed_softwares", []))
    set_column_gap(settings.get("column_gap", 0))
    set_header_style(
        settings.get("header_color", "skinN1"),
        settings.get("header_radius", 0),
        # header_border_enabled (nouveau nom) ; header_edges (ancien nom,
        # meme format dict {cote: bool}) en repli pour les presets deja
        # sauvegardes avant ce renommage — voir la remarque de
        # l'utilisateur, "renomme le parametre 'cadre des entetes' ->
        # 'Bordure'".
        settings.get("header_border_enabled") or settings.get("header_edges")
        or {"top": False, "right": False, "bottom": True, "left": False},
        settings.get("header_border") or {},
        settings.get("header_border_thickness", 1),
    )
    set_ui_scale(settings.get("ui_scale", 100))

    for key, hexval in (settings.get("colors") or {}).items():
        set_color(key, hexval)

    # Style de colonne GENERAL (voir app_style.set_general_column_style) :
    # applique tel quel a TOUTE colonne sans surcharge active (Logiciels/
    # Contenu, ou Type/Projets/Sous-projet tant qu'aucune ligne de leur
    # onglet dedie n'est activee, voir plus bas) — TOUTES les cles de
    # COLUMN_TYPE_OVERRIDE_KEYS (cadre + texte/selection/image), pas
    # seulement le cadre : depuis que le rendu des lignes est PARTAGE par
    # toutes les colonnes (voir _paint_unified_row), Logiciels/Contenu ont
    # eux aussi besoin de item_selection_*/item_image_* pour suivre les
    # reglages generaux — voir la remarque de l'utilisateur, "le padding et
    # les coins arrondis des autres colonnes que type ne fonctionnent
    # pas". APRES la boucle set_color() ci-dessus, dont depend
    # resolve_color_ref (les couleurs "@<slot>" se resolvent contre la
    # palette live, pas l'ancienne).
    set_general_column_style({key: settings.get(key) for key in COLUMN_TYPE_OVERRIDE_KEYS})

    # Colonne "Type"/"Projets"/"Sous-projet" > style EFFECTIF (voir
    # COLUMN_TYPE_OVERRIDE_KEYS/app_style.set_column_style) : la valeur
    # GENERALE de chaque cle, sauf si Colonnes > (Type/Projets/Sous-
    # projets) l'a explicitement surchargee pour CETTE colonne (voir
    # SettingsWindow._build_column_override_page, un toggle par ligne) —
    # "Type" garde ses cles de stockage historiques (column_type_overrides/
    # column_type_override_enabled), Projets/Sous-projet utilisent les
    # nouvelles cles imbriquees par titre (voir la remarque de
    # l'utilisateur, "place ensuite cette meme section dans les onglets
    # projets et sous projets pour y controler les colonnes respectives").
    overrides_by_title = settings.get("column_overrides_by_title") or {}
    enabled_by_title = settings.get("column_override_enabled_by_title") or {}
    # "Logiciels"/"IN"/"OVER"/"OUT"/INSPECTOR_TITLE (ajoutes ici, voir la
    # remarque de l'utilisateur, "ajoute la colonne logiciels dans les
    # settings, ainsi que in over et out, puis la colonne inspecteur") :
    # MEME mecanisme "column_overrides_by_title" que Projets/Sous-projet,
    # chacune avec son propre onglet de surcharge dedie (voir
    # SettingsWindow._build_columns_page) — plus de repli general-only
    # special pour elles (voir l'ancienne remarque plus bas, desormais
    # limitee a "Contenu" seul, le SEUL bucket restant sans onglet dedie).
    for real_title in ("Type", "Projets", "Sous-projet", "Logiciels", "IN", "OVER", "OUT", INSPECTOR_TITLE):
        if real_title == "Type":
            overrides = settings.get("column_type_overrides") or {}
            override_enabled = settings.get("column_type_override_enabled") or {}
        else:
            overrides = overrides_by_title.get(real_title) or {}
            override_enabled = enabled_by_title.get(real_title) or {}
        col_style = {}
        for key in COLUMN_TYPE_OVERRIDE_KEYS:
            if override_enabled.get(key) and key in overrides:
                col_style[key] = overrides[key]
            else:
                # "Projets"/"Sous-projet" suivent desormais la valeur
                # GENERALE par defaut, exactement comme "Type" (voir
                # _paint_unified_row, rendu PARTAGE par toutes les
                # colonnes) — plus de repli neutre special pour ces 2
                # colonnes (essaye puis abandonne : il empechait
                # padding/rayon/bordure de selection de s'appliquer du
                # tout tant qu'aucune surcharge PAR TITRE n'etait activee,
                # voir la remarque de l'utilisateur, "le padding et les
                # coins arrondis des autres colonnes que type ne
                # fonctionnent pas").
                col_style[key] = settings.get(key)
        set_column_style(real_title, col_style)
        # sizeHint (voir RowDelegate.sizeHint/ProjectTileDelegate.sizeHint)
        # lit deja COLUMN_SETTINGS[titre] — y ecrire la hauteur/l'espacement
        # de ligne EFFECTIFS (col_style : surcharge PAR TITRE si active,
        # sinon la valeur GENERALE) evite un 2e chemin de lecture rien que
        # pour ca. TOUJOURS col_style, pour les 3 titres — PAS seulement
        # "Type" (essaye puis abandonne : "Projets"/"Sous-projet" gardaient
        # alors LEUR propre defaut fige, 58/1, tant qu'aucune surcharge PAR
        # TITRE n'etait activee, ignorant purement et simplement le reglage
        # GENERAL "Hauteur de la ligne"/"Espacement entre les lignes") —
        # voir la remarque de l'utilisateur, "le parametre de hauteur de
        # ligne ne prend que la colonne type en compte ... pareil pour
        # espacement entre les lignes".
        # INSPECTOR_TITLE n'est PAS dans COLUMN_SETTINGS (voir sa remarque
        # de tete — pas une colonne a LIGNES, DetailPanel n'a pas de
        # sizeHint/item_row_* a y ecrire, MEME raison que PREVIEW_STACK_
        # TITLE ci-dessous) : rien de plus a faire pour elle une fois
        # set_column_style() appele ci-dessus.
        if real_title in COLUMN_SETTINGS:
            if col_style.get("item_row_height") is not None:
                COLUMN_SETTINGS[real_title]["height"] = int(col_style["item_row_height"])
            COLUMN_SETTINGS[real_title]["spacing"] = max(0, int(col_style.get("item_row_spacing") or 0))
            # Largeur par defaut (voir settings_window.DEFAULT_SETTINGS.
            # item_column_width, 1er parametre de General > Colonnes > Colonnes,
            # et son override dans Colonnes > Type/Projets/Sous-projets) : MEME
            # resolution generale/surcharge PAR TITRE que hauteur/espacement juste au-
            # dessus — remplace les largeurs fixes codees en dur ci-dessus
            # (COLUMN_SETTINGS, "width": 140/208/...) des qu'un reglage existe
            # — voir la remarque de l'utilisateur, "ajoute un parametre de
            # largeur de colonne par defaut ... et un overide pour chacune des
            # autres colonnes".
            if col_style.get("item_column_width") is not None:
                COLUMN_SETTINGS[real_title]["width"] = int(col_style["item_column_width"])

    # PREVIEW_STACK_TITLE (voir sa remarque de tete/PreviewColumn) : MEME
    # resolution generale/surcharge que ci-dessus (son propre onglet, voir
    # SettingsWindow._build_columns_page), mais a PART — pas dans
    # COLUMN_SETTINGS (pas une colonne a LIGNES, aucun sizeHint/item_row_*
    # a y ecrire, voir PreviewColumn.set_preview_block) — voir la remarque
    # de l'utilisateur, "je veux les overrides dans les settings aussi".
    preview_overrides = overrides_by_title.get(PREVIEW_STACK_TITLE) or {}
    preview_enabled = enabled_by_title.get(PREVIEW_STACK_TITLE) or {}
    preview_style = {}
    for key in COLUMN_TYPE_OVERRIDE_KEYS:
        if preview_enabled.get(key) and key in preview_overrides:
            preview_style[key] = preview_overrides[key]
        else:
            preview_style[key] = settings.get(key)
    set_column_style(PREVIEW_STACK_TITLE, preview_style)

    # "Contenu" n'a pas d'onglet de surcharge dedie (voir settings_window.
    # _build_columns_page) : suit directement la valeur GENERALE, jamais
    # une surcharge PAR TITRE — c'est le SEUL bucket restant dans ce cas
    # ("Logiciels"/"IN"/"OVER"/"OUT" ont desormais leur propre onglet, voir
    # la boucle ci-dessus) : c'est le bucket GENERIQUE partage par tout
    # contenu ouvert au-dela d'une chaine (configuree ou legacy), un nom de
    # dossier quelconque, jamais un concept fixe a surcharger individuellement.
    if "Contenu" in COLUMN_SETTINGS:
        if settings.get("item_row_height") is not None:
            COLUMN_SETTINGS["Contenu"]["height"] = int(settings.get("item_row_height"))
        COLUMN_SETTINGS["Contenu"]["spacing"] = max(0, int(settings.get("item_row_spacing") or 0))
        if settings.get("item_column_width") is not None:
            COLUMN_SETTINGS["Contenu"]["width"] = int(settings.get("item_column_width"))

    header_family = (settings.get("header_font_family") or "").strip()
    if header_family:
        conf = dict(settings.get("font_colhead") or {})
        conf["family"] = header_family
        settings = dict(settings)
        settings["font_colhead"] = conf

    for role, key in (
        ("app", "font_main"),
        ("titles", "font_titles"),
        ("folders", "font_folders"),
        ("files", "font_files"),
        ("buttons", "font_buttons"),
        ("colhead", "font_colhead"),
        ("info", "font_info"),
        ("info2", "font_info2"),
        ("code", "font_code"),
    ):
        conf = settings.get(key) or {}
        set_role_font(
            role, conf.get("family", ""), conf.get("size", 12), conf.get("bold", False),
            conf.get("smoothing", "current"), conf.get("color", ""), conf.get("custom", False),
        )


def main():
    settings = load_settings()
    apply_all_settings(settings)
    root = Path(settings["root_path"])

    app = QApplication(sys.argv)
    apply_style(app)
    window = PipelineBrowser(root)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
