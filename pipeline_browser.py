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
import json
import math
import os
import shutil
import subprocess
import sys

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
    QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QDrag,
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

# Dependances optionnelles (voir requirements.txt) : import protege pour
# qu'une install sans ces paquets perde juste les apercus concernes, sans
# empecher l'appli de demarrer. numpy sert au rasteriseur lisse des .obj
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
    PREVIEW_STACK_TITLE,
    STYLESHEET_COLOR_KEYS,
    _hex_to_rgb,
    apply_dwm_frame,
    apply_style,
    column_gap,
    columns_resizable,
    font,
    header_qss,
    refresh_style,
    resize_hit_test,
    role_color,
    role_font,
    scaled,
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
    SettingsWindow,
    load_settings,
    save_settings,
    _coerce_side_enabled,
    _paint_bordered_rect,
    _radius_dict,
    _radius_any,
    _radius_shrink,
    _rounded_rect_path,
)

# ==========================================================================
# Configuration
# ==========================================================================

ROOT = Path(r"F:\PIPELINE")

COLUMN_LABELS = ["Type", "Projets", "Sous-projet", "Logiciels", "Contenu"]

# Colonnes repliables (voir Column.set_collapsed) : une fois Projet ET
# Sous-projet choisis, ces trois colonnes de navigation perdent leur utilite
# immediate (le contexte est fixe) et peuvent se replier en bandeau etroit,
# avec une icone pour les redeplier a la demande (voir
# PipelineBrowser._sync_collapse_state).
COLLAPSIBLE_COLUMN_TITLES = {"Type", "Projets", "Sous-projet"}

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

# Fichiers Photoshop : Qt ne sait pas les decoder (absent de
# QImageReader.supportedImageFormats), mais Photoshop y embarque presque
# toujours une vignette JPEG prete a l'emploi (voir _decode_psd_thumbnail) —
# bien plus simple/rapide qu'une vraie composition des calques, qui serait
# hors de portee ici.
PSD_EXTENSIONS = {".psd", ".psb"}

# Rendus HDR (voir _decode_exr_image) : necessite le paquet OpenEXR (voir
# _OPENEXR_AVAILABLE) ; sans lui, ces fichiers restent sans apercu, comme
# avant.
EXR_EXTENSIONS = {".exr"}

# Videos : une frame extraite via QtMultimedia (voir _decode_video_frame),
# module fourni avec PySide6 (ffmpeg embarque, aucune dependance externe).
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}

PREVIEWABLE_EXTENSIONS = (
    IMAGE_EXTENSIONS | OBJ_EXTENSIONS | PSD_EXTENSIONS | EXR_EXTENSIONS | VIDEO_EXTENSIONS
)

# Fichiers texte/code dont le contenu (debut) s'affiche dans l'inspecteur
# (voir DetailPanel.show_path) : contrairement a IMAGE_EXTENSIONS/
# OBJ_EXTENSIONS, jamais utilise pour les cartes-vignette des colonnes (un
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

# Reglable depuis la fenetre de parametres : affiche les fichiers image, dans
# n'importe quelle colonne classique, avec exactement le meme style de ligne
# que les vignettes de projet (vignette carree a gauche + nom/metadonnee a
# droite), plutot que le marqueur habituel. Pas de menu "changer l'image"
# pour ces lignes : l'image EST le fichier.
SHOW_FILE_IMAGE_PREVIEWS = True

PREVIEW_MIN_HEIGHT = 104   # hauteur de la vignette sans image (ou image tres petite)
PREVIEW_MAX_HEIGHT = 800   # jamais plus grand que ca, meme pour une tres grande image

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
SOFTWARE_ICON_SIZE = 16
CUSTOM_SOFTWARE_ICON_DIR = Path(__file__).resolve().parent / ".pipeline_software_icons"
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
    rapproche d'un logiciel connu. None si non reconnu."""
    norm = "".join(ch for ch in name.upper() if ch.isalnum())
    return norm if norm in SOFTWARE_ICONS else None


def custom_software_icon_path(key: str) -> Path:
    """Emplacement de l'icone perso d'un logiciel (globale, pas liee a un
    projet en particulier)."""
    return CUSTOM_SOFTWARE_ICON_DIR / f"{key}.png"


def _cover_crop_square(pix: QPixmap, size: int) -> QPixmap:
    """Redimensionne `pix` en carre `size`x`size` en recadrant (« cover »)."""
    scaled = pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    return scaled.copy(x, y, size, size)


def _cover_crop_rect(pix: QPixmap, width: int, height: int) -> QPixmap:
    """MEME principe que _cover_crop_square, mais pour un rectangle
    largeur x hauteur QUELCONQUE (pas necessairement carre) — voir
    _SquarePreviewImage.set_rect/Colonnes > Apercu > Image > Ratio, la
    remarque de l'utilisateur, "je veux une section ratio"."""
    width, height = max(1, width), max(1, height)
    scaled = pix.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
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
_PREVIEW_CACHE_VERSION = 5


def _file_image_cache_path(path: Path, mtime: float) -> Path:
    digest = hashlib.sha1(f"{_PREVIEW_CACHE_VERSION}:{path}".encode("utf-8")).hexdigest()
    return FILE_IMAGE_DISK_CACHE_DIR / f"{digest}_{int(mtime)}.png"


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


# Apercu des fichiers .obj : pas de vraie camera/moteur 3D, un shading
# logiciel (projection orthographique fixe + lissage Gouraud vrai — voir
# _rasterize_obj_numpy) suffisant pour reconnaitre la forme d'un modele en
# vignette. Le cout de parsing/rendu n'est pas negligeable sur un gros
# maillage, mais file_image_pixmap le met en cache exactement comme une
# image : recalcule seulement a la premiere ouverture (ou apres
# modification du fichier).
OBJ_PREVIEW_MAX_TRIANGLES = 150_000   # au-dela, le maillage est tronque (vignette, pas un rendu final)
# Resolution dediee, plus grande que FILE_IMAGE_CACHE_MAX_DIM (640, pense
# pour des photos deja haute def qu'on reduit) : un .obj est genere par
# nos soins a une taille fixe, donc c'est SA resolution native qui
# determine la nettete a l'agrandissement (Inspecteur elargi, HiDPI...),
# pas un simple redimensionnement d'un fichier source. Supersamplee en
# interne (voir _rasterize_obj_numpy) pour lisser aussi le contour.
OBJ_PREVIEW_DIM = 1200
# Camera fixe en haut a droite (et de face) : yaw negatif = camera vers +X
# (droite), pitch positif = camera vers +Y (haut) — voir le calcul dans la
# conversation qui a fixe ces signes. 20 deg de chaque cote plutot que le
# coin isometrique classique (45/35) : angle plus doux, l'objet reste vu
# presque de face.
_OBJ_YAW = math.radians(-20)
_OBJ_PITCH = math.radians(20)


def _normalize3(v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / length, y / length, z / length)


_OBJ_LIGHT = _normalize3((0.45, 0.65, 1.0))


def _decode_obj_image(path: Path, max_dim: int) -> QImage | None:
    """Parse `path` (Wavefront .obj) et rend une image flat-shaded de
    max_dim x max_dim px, ou None si le fichier est illisible/vide/sans
    geometrie exploitable. Ne lit que les sommets ("v ") et faces ("f ") :
    materiaux, normales/UV fournis, groupes... ne servent a rien pour une
    simple silhouette ombree."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []   # triangles (fan) d'indices dans `vertices`

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("v "):
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
                        for i in range(1, len(idx) - 1):
                            faces.append((idx[0], idx[i], idx[i + 1]))
                            if len(faces) >= OBJ_PREVIEW_MAX_TRIANGLES:
                                break
    except OSError:
        return None

    if not vertices or not faces:
        return None

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
        x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y   # rotation (yaw)
        y, z = y * cos_p - z * sin_p, y * sin_p + z * cos_p    # rotation (pitch)
        transformed.append((x, y, z))

    # Etendue projetee (x, y) reelle apres rotation, pour cadrer pile le
    # modele quelle que soit son orientation d'origine.
    proj_xs = [p[0] for p in transformed]
    proj_ys = [p[1] for p in transformed]
    span = max(max(proj_xs) - min(proj_xs), max(proj_ys) - min(proj_ys)) or 1.0
    scale = (max_dim * 0.82) / span
    ox = max_dim / 2 - (min(proj_xs) + max(proj_xs)) / 2 * scale
    oy = max_dim / 2 + (min(proj_ys) + max(proj_ys)) / 2 * scale

    def to_screen(p: tuple[float, float, float]) -> QPointF:
        return QPointF(p[0] * scale + ox, -p[1] * scale + oy)

    # Normales par face (non normalisees : leur norme, proportionnelle a
    # l'aire du triangle, sert de poids naturel dans l'accumulation par
    # sommet ci-dessous) puis normales par sommet (moyenne des faces
    # adjacentes), pour un vrai lissage Gouraud (intensite interpolee par
    # pixel entre les 3 sommets d'un triangle, voir _rasterize_obj_numpy) :
    # deux triangles voisins partageant des sommets se retrouvent avec un
    # degrade continu, sans les facettes dures d'un flat shading par face.
    vertex_normals = [[0.0, 0.0, 0.0] for _ in vertices]
    for a, b, c in faces:
        va, vb, vc = transformed[a], transformed[b], transformed[c]
        e1 = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
        e2 = (vc[0] - va[0], vc[1] - va[1], vc[2] - va[2])
        n = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        )
        for i in (a, b, c):
            vertex_normals[i][0] += n[0]
            vertex_normals[i][1] += n[1]
            vertex_normals[i][2] += n[2]

    def vertex_intensity(i: int) -> float:
        nx, ny, nz = vertex_normals[i]
        nlen = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nlen == 0:
            return 0.25
        # abs() plutot qu'un vrai dot signe + culling de face arriere : les
        # normales d'un .obj quelconque ne sont pas garanties bien orientees,
        # et une face vue de "dos" doit quand meme apparaitre (surface
        # ouverte, mesh non manifold...) plutot que rester un trou noir.
        return 0.25 + 0.75 * abs(
            (nx * _OBJ_LIGHT[0] + ny * _OBJ_LIGHT[1] + nz * _OBJ_LIGHT[2]) / nlen
        )

    vertex_shade = [vertex_intensity(i) for i in range(len(vertices))]
    base_rgb = (190, 190, 196)

    if _NUMPY_AVAILABLE:
        return _rasterize_obj_numpy(transformed, faces, vertex_shade, max_dim, scale, ox, oy, base_rgb)
    return _rasterize_obj_qpainter(transformed, faces, vertex_shade, max_dim, to_screen, base_rgb)


def _rasterize_obj_numpy(
    transformed: list[tuple[float, float, float]], faces: list[tuple[int, int, int]],
    vertex_shade: list[float], max_dim: int, scale: float, ox: float, oy: float,
    base_rgb: tuple[int, int, int],
) -> QImage:
    """Rasterise `faces` avec un vrai z-buffer (ordre correct quelle que
    soit la complexite du maillage, contrairement a l'ancien tri peintre)
    et un vrai lissage Gouraud : l'intensite lumineuse est interpolee par
    coordonnees barycentriques a CHAQUE PIXEL entre les 3 sommets d'un
    triangle, pas moyennee une seule fois pour tout le triangle — c'est ce
    qui elimine reellement le facettage visible, la ou le flat shading
    (QPainter, une couleur unie par triangle) ne pouvait que l'attenuer.
    Supersample x2 (rendu a 2*max_dim puis reduit par moyenne de blocs
    2x2) pour lisser aussi le contour exterieur, qu'un rasteriseur naif
    (test au centre du pixel, sans anti-aliasing) laisserait crenele."""
    render_dim = max_dim * 2
    r_scale, r_ox, r_oy = scale * 2, ox * 2, oy * 2

    n = len(transformed)
    xs = np.empty(n, dtype=np.float64)
    ys = np.empty(n, dtype=np.float64)
    zs = np.empty(n, dtype=np.float64)
    for i, (x, y, z) in enumerate(transformed):
        xs[i], ys[i], zs[i] = x, y, z
    screen_x = xs * r_scale + r_ox
    screen_y = -ys * r_scale + r_oy
    shade = np.asarray(vertex_shade, dtype=np.float64)

    color_buf = np.empty((render_dim, render_dim, 3), dtype=np.float64)
    color_buf[:, :] = _hex_to_rgb(C["well"])   # fond, la ou aucun triangle ne couvre le pixel
    depth_buf = np.full((render_dim, render_dim), -np.inf, dtype=np.float64)

    for a, b, c in faces:
        x0, y0, z0 = screen_x[a], screen_y[a], zs[a]
        x1, y1, z1 = screen_x[b], screen_y[b], zs[b]
        x2, y2, z2 = screen_x[c], screen_y[c], zs[c]

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
        closer = inside & (z_interp > region_depth)
        if not closer.any():
            continue

        intensity = l0 * shade[a] + l1 * shade[b] + l2 * shade[c]
        region_depth[closer] = z_interp[closer]
        region_color = color_buf[min_y:max_y + 1, min_x:max_x + 1]
        for k in range(3):
            channel = region_color[..., k]
            channel[closer] = base_rgb[k] * intensity[closer]

    # Reduction 2x2 (moyenne) : supersampling -> anti-aliasing bon marche,
    # sur le contour ET sur les aretes internes que le z-buffer laisserait
    # sinon dentelees (test au centre du pixel, pas de couverture partielle).
    color_buf = color_buf.reshape(max_dim, 2, max_dim, 2, 3).mean(axis=(1, 3))
    rgb8 = np.clip(color_buf, 0, 255).astype(np.uint8)
    rgb8 = np.ascontiguousarray(rgb8)
    # .copy() : QImage(buffer, ...) ne fait que referencer rgb8.data, qui
    # serait libere avec le tableau numpy des la sortie de cette fonction.
    return QImage(rgb8.data, max_dim, max_dim, max_dim * 3, QImage.Format_RGB888).copy()


def _rasterize_obj_qpainter(
    transformed: list[tuple[float, float, float]], faces: list[tuple[int, int, int]],
    vertex_shade: list[float], max_dim: int, to_screen, base_rgb: tuple[int, int, int],
) -> QImage:
    """Repli sans numpy (voir _NUMPY_AVAILABLE) : un triangle = une couleur
    unie (moyenne de l'ombrage a ses 3 sommets, pas un vrai Gouraud par
    pixel) et un tri peintre au lieu d'un z-buffer — degrade mais
    fonctionnel si le paquet numpy manque."""
    faces_sorted = sorted(faces, key=lambda f: (
        transformed[f[0]][2] + transformed[f[1]][2] + transformed[f[2]][2]
    ))
    image = QImage(max_dim, max_dim, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(C["well"]))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    for a, b, c in faces_sorted:
        intensity = (vertex_shade[a] + vertex_shade[b] + vertex_shade[c]) / 3.0
        color = QColor(
            min(255, round(base_rgb[0] * intensity)),
            min(255, round(base_rgb[1] * intensity)),
            min(255, round(base_rgb[2] * intensity)),
        )
        # Contour de la meme couleur que le remplissage (pas de "Qt.NoPen") :
        # au tri peintre, deux triangles adjacents co-plans (la diagonale de
        # triangulation d'une meme face) laissent sinon un filet d'anti-
        # aliasing visible entre eux, qui ressort comme un wireframe residuel
        # malgre un shading identique des deux cotes.
        painter.setPen(color)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([to_screen(transformed[a]), to_screen(transformed[b]), to_screen(transformed[c])]))
    painter.end()
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


def file_image_pixmap(path: Path) -> QPixmap | None:
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
    cached = _file_image_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    cache_path = _file_image_cache_path(path, mtime)
    if cache_path.is_file():
        pix = QPixmap(str(cache_path))
        if not pix.isNull():
            _bounded_cache_set(_file_image_cache, key, (mtime, pix))
            return pix

    suffix = path.suffix.lower()
    if suffix in OBJ_EXTENSIONS:
        image = _decode_obj_image(path, OBJ_PREVIEW_DIM)
        if image is None or image.isNull():
            return None
    elif suffix in PSD_EXTENSIONS:
        image = _decode_psd_thumbnail(path)
        if image is None or image.isNull():
            return None
        if max(image.width(), image.height()) > FILE_IMAGE_CACHE_MAX_DIM:
            image = image.scaled(
                FILE_IMAGE_CACHE_MAX_DIM, FILE_IMAGE_CACHE_MAX_DIM,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
    elif suffix in EXR_EXTENSIONS:
        image = _decode_exr_image(path, FILE_IMAGE_CACHE_MAX_DIM)
        if image is None or image.isNull():
            return None
    elif suffix in VIDEO_EXTENSIONS:
        image = _decode_video_frame(path, FILE_IMAGE_CACHE_MAX_DIM)
        if image is None or image.isNull():
            return None
    else:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            longest = max(size.width(), size.height())
            if longest > FILE_IMAGE_CACHE_MAX_DIM:
                scale = FILE_IMAGE_CACHE_MAX_DIM / longest
                reader.setScaledSize(QSize(
                    max(1, round(size.width() * scale)), max(1, round(size.height() * scale)),
                ))
        image = reader.read()
        if image.isNull():
            return None
    pix = QPixmap.fromImage(image)
    _bounded_cache_set(_file_image_cache, key, (mtime, pix))
    try:
        was_new = not FILE_IMAGE_DISK_CACHE_DIR.is_dir()
        FILE_IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if was_new:
            _set_hidden(FILE_IMAGE_DISK_CACHE_DIR)
        if pix.save(str(cache_path), "PNG"):
            _set_hidden(cache_path)
            _prune_stale_disk_cache(cache_path)
    except OSError:
        pass
    return pix


def _generate_software_badge(key: str, size: int) -> QPixmap:
    bg, fg, label = SOFTWARE_ICONS[key]
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
            pix = _cover_crop_square(loaded, size)
    if pix is None:
        pix = _generate_software_badge(key, size)

    _software_icon_cache[cache_key] = (mtime, pix)
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
# glisser, voir Column.row_resize_begin/_ROW_HEIGHT_RESIZABLE_TITLES) —
# memes bornes que le slider "Hauteur de la ligne" de la fenetre de
# parametres (voir settings_window._ITEM_TEXT_FIELD_SPECS) pour qu'une
# valeur posee ici ne soit jamais silencieusement recadree en rouvrant les
# parametres.
ROW_RESIZE_MIN_HEIGHT = 14
ROW_RESIZE_MAX_HEIGHT = 80
# Colonnes dont "Hauteur de la ligne" est un vrai reglage surchargeable
# (voir settings_window._build_column_override_page) — seules celles-ci
# ont une hauteur de ligne UNIFORME et persistable a la main.
_ROW_HEIGHT_RESIZABLE_TITLES = ("Type", "Projets", "Sous-projet")
ROW_HEIGHT = 24
ROW_SPACING = 1            # espace (px) entre les lignes, dans toutes les colonnes
HEADER_HEIGHT = 26
HEADER_PADDING = 0    # inset (4 cotes) entre le fond colore de l'entete et les bords de la colonne/inspecteur (voir Column/DetailPanel)
TOPBAR_HEIGHT = 40
STATUS_HEIGHT = 24
TITLEBAR_HEIGHT = 28
DETAIL_PANEL_WIDTH = 300
DETAIL_PANEL_MIN_WIDTH = 220
DETAIL_PANEL_MAX_WIDTH = 520
# Titre "virtuel" utilise pour resoudre le style EFFECTIF de l'inspecteur
# (voir app_style.column_style_for/DetailPanel.refresh_header/refresh_
# colors) — jamais dans COLUMN_SETTINGS/COLLAPSIBLE_COLUMN_TITLES/etc (ce
# n'est pas une vraie colonne de la rangee), et jamais surcharge par titre
# (pas d'onglet dedie dans Colonnes > ..., comme Logiciels/Contenu) : suit
# donc TOUJOURS le style GENERAL — voir la remarque de l'utilisateur, "la
# colonne inspecteur est differente des autres, je veux exactement le
# meme style, parametres par parametres".
INSPECTOR_TITLE = "Inspecteur"
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
# _softs_subdir, utilise par PipelineBrowser.on_selected en ouvrant la
# colonne "Logiciels".
SOFTS_FOLDER_NAME = "softs"


def _softs_subdir(directory: Path) -> Path:
    """Repertoire reellement liste pour la colonne "Logiciels" : le
    sous-dossier "softs" de `directory` (insensible a la casse) s'il existe,
    sinon `directory` lui-meme (repli si la convention n'est pas suivie)."""
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_dir() and entry.name.lower() == SOFTS_FOLDER_NAME:
                    return Path(entry.path)
    except OSError:
        pass
    return directory


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
    if family_label:
        resolved_family = _resolve_font_family(family_label, 11, 600)
        label.setFont(font(11, 600, family=resolved_family))
    else:
        label.setFont(font(11, 600, mono=True))
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


def _persist_row_height(win, title: str, new_height: int) -> None:
    """Enregistre `new_height` comme hauteur de ligne EFFECTIVE de `title`
    sur le disque (voir Column.row_resize_end) — memes cles que la fenetre
    de parametres (settings_window._build_column_override_page) : "Type"
    garde ses cles historiques, "Projets"/"Sous-projet" les nouvelles cles
    imbriquees par titre (voir _override_store cote settings_window) — pour
    qu'un redimensionnement a la souris se retrouve, actif, la prochaine
    fois que Colonnes > (Type/Projets/Sous-projets) est ouvert."""
    def _apply_height_override(target: dict) -> None:
        if title == "Type":
            target.setdefault("column_type_overrides", {})["item_row_height"] = new_height
            target.setdefault("column_type_override_enabled", {})["item_row_height"] = True
        else:
            target.setdefault("column_overrides_by_title", {}).setdefault(title, {})["item_row_height"] = new_height
            target.setdefault("column_override_enabled_by_title", {}).setdefault(title, {})["item_row_height"] = True

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
    # CETTE vue aussi (_apply_height_override), sans se reposer sur le fait
    # que _sync_settings_dialog_row_height ait deja synchronise le champ du
    # dialogue pendant le glisser.
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


def _sync_settings_dialog_row_height(win, title: str, new_height: int) -> None:
    """Repercute EN TEMPS REEL, PENDANT le glisser (voir Column.
    row_resize_update, PAS seulement au relachement/_persist_row_height),
    la hauteur choisie sur la fenetre de parametres SI elle est deja
    ouverte — sur son onglet de surcharge PAR TITRE (Colonnes > Type/
    Projets/Sous-projets), jamais General : le glisser cree/met a jour
    TOUJOURS une surcharge (voir _persist_row_height), jamais la valeur
    generale — voir la remarque de l'utilisateur, "quand on change la
    valeur de la hauteur de ligne avec la touche controle, je veux que la
    valeur dans les settings soit mise a jour en temps reel"."""
    dialog = getattr(win, "_settings_dialog", None)
    if dialog is None:
        return
    try:
        if not dialog.isVisible():
            return
    except RuntimeError:
        return
    fields = getattr(dialog, "_type_fields", {}).get(title)
    if not fields or "item_row_height" not in fields:
        return
    # blockSignals ici : ce champ/toggle est cable sur _mark_dirty (voir
    # _connect_column_type_overrides), qui relance via son timer 30ms tout
    # apply_all_settings()/refresh_all_columns() — en le laissant faire a
    # CHAQUE frame de glisser, ce chemin entrait en concurrence avec la
    # mise a jour directe de row_resize_update (COLUMN_SETTINGS +
    # doItemsLayout) et provoquait l'espacement/hauteur qui "buggait"
    # pendant le glisser. setValue/setChecked mettent quand meme l'affichage
    # a jour meme signaux bloques ; seule la notification (donc la cascade
    # settingsChanged) est supprimee pendant le drag.
    field = fields["item_row_height"]
    field.blockSignals(True)
    field.setValue(int(new_height))
    field.blockSignals(False)
    toggles = getattr(dialog, "_type_toggles", {}).get(title) or {}
    toggle = toggles.get("item_row_height")
    if toggle is not None:
        toggle.blockSignals(True)
        toggle.setChecked(True)
        toggle.blockSignals(False)
    if hasattr(dialog, "_apply_column_type_preview"):
        dialog._apply_column_type_preview()


def open_path(path: Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_file_manager(path: Path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


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

    scaled_pix = pixmap.scaled(img_rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    sx = max(0, (scaled_pix.width() - img_rect.width()) // 2)
    sy = max(0, (scaled_pix.height() - img_rect.height()) // 2)
    cropped = scaled_pix.copy(sx, sy, min(img_rect.width(), scaled_pix.width()), min(img_rect.height(), scaled_pix.height()))

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
        # _paint_bordered_rect.
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
        mask = _rounded_mask_pixmap(img_rect.width(), img_rect.height(), radius)
        big = mask.size()
        big_rect = QRect(0, 0, big.width(), big.height())

        masked = QPixmap(big)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.setRenderHint(QPainter.SmoothPixmapTransform, True)
        mp.drawPixmap(big_rect, cropped)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()

        masked = masked.scaled(img_rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(img_rect, masked)
    else:
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
    row_font = font(size, weight=weight, family=resolved_family, smoothing=smoothing)
    row_color = resolve_color_ref(s.get("item_color") or C["text"])
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
        self.type_font, self.type_color = _resolve_row_font_color(self.column.column_title)

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
        return file_image_pixmap(Path(index.data(ROLE_PATH)))

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
        title = self.column.column_title
        return QSize(self.column.width(), col_row_height(title) + col_spacing(title))

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
        title = self.column.column_title
        spacing = col_spacing(title)
        rect = option.rect.adjusted(0, 0, 0, -spacing)
        is_dir = bool(index.data(ROLE_ISDIR))
        path_str = index.data(ROLE_PATH)

        pixmap = None
        if title == "Type":
            if path_str and is_dir and project_thumbnail_path(Path(path_str)).is_file():
                pixmap = project_thumbnail_pixmap(Path(path_str))
        else:
            icon_key = None
            if is_dir and title == SOFTWARE_COLUMN_LABEL:
                icon_key = software_icon_key(index.data(Qt.DisplayRole) or "")
            if icon_key is not None:
                pixmap = software_icon_pixmap(icon_key, SOFTWARE_ICON_SIZE)
            else:
                pixmap = self._image_pixmap(index)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        _paint_unified_row(
            painter, rect, option, column_style_for(title),
            index.data(Qt.DisplayRole), pixmap, self.type_font, self.type_color, self.column.is_active,
            annotation=index.data(ROLE_SOURCE_LABEL),
        )
        painter.restore()


def _paint_unified_row(
    painter: QPainter, rect, option, style: dict, name: str, pixmap: QPixmap | None,
    text_font, text_color: str, active: bool, annotation: str | None = None,
):
    """Ligne UNIQUE, PARTAGEE par toutes les colonnes (Type/Projets/Sous-
    projet/Logiciels/Contenu) : icone toggle optionnelle OU image (apercu
    personnalise sur "Type", vignette de projet/icone logiciel/apercu de
    fichier reutilisee telle quelle sur les autres) + nom + pastille de
    selection — voir la remarque de l'utilisateur, "je veux que tu
    reformate toutes les autres colonnes exactement de la meme maniere que
    la colonne type ... si une colonne a deja des images, reutilises les".
    `pixmap` est deja RESOLU par l'appelant (chaque colonne garde sa propre
    logique de choix d'image, voir RowDelegate.paint/ProjectTileDelegate.
    `annotation` (voir ROLE_SOURCE_LABEL, RowDelegate.paint) : texte
    "(projet)"/"(<nom du sous-projet>)" affiche APRES le nom, police/
    couleur DIFFERENTES (role "info", comme le compteur d'en-tete) — voir
    la remarque de l'utilisateur, "je veux une anotation a cote du nom du
    repertoire ... entre parentheses (d'une police et couleur
    differente)".
    paint) ; None affiche l'icone toggle (si activee) ou rien."""
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
    text_padding = max(0, int(s.get("item_text_padding", 8)))
    has_preview_image = pixmap is not None

    if selected:
        sel_color = s.get("item_selection_focus_color", C["accent"]) if active \
            else s.get("item_selection_unfocus_color", C["sel_idle"])
    elif hovered:
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
        sel_color = resolve_color_ref(s.get("item_idle_color"), C["row_idle"])

    if sel_color:
        pad = s.get("item_selection_padding") or {}
        sel_rect = QRect(
            rect.left() + max(0, int(pad.get("left", 0))),
            rect.top() + max(0, int(pad.get("top", 0))),
            rect.width() - max(0, int(pad.get("left", 0))) - max(0, int(pad.get("right", 0))),
            rect.height() - max(0, int(pad.get("top", 0))) - max(0, int(pad.get("bottom", 0))),
        )
        border_enabled = dict(s.get("item_selection_border_enabled") or {})
        border_colors = {
            k: resolve_color_ref(v) for k, v in (s.get("item_selection_border") or {}).items()
        }
        edge_border = bool(s.get("item_selection_edge_border", True))
        for side in ("left", "right"):
            flush = max(0, int(pad.get(side, 0))) <= 0
            if flush and not edge_border:
                border_enabled[side] = False
        radius = _radius_dict(s.get("item_selection_radius", 0))
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

    # Icone/apercu EN PREMIER PLAN (voir la remarque de l'utilisateur,
    # "l'image d'apercu est dessous les zones de selection ... mets les
    # en premier plan") : dessinee APRES la boite de selection/idle
    # ci-dessus, jamais recouverte par son remplissage opaque.
    if has_preview_image:
        # Hauteur = celle de la zone de selection (sel_rect, TOUJOURS
        # definie ici puisque sel_color l'est desormais dans les 3 etats,
        # voir plus haut), collee sur son bord GAUCHE — voir la remarque
        # de l'utilisateur, "la hauteur de l'image soit de la meme
        # hauteur que les zones de selection ... collee sur le bord
        # gauche des zones de selection" — PAS le carre 14x14 fixe de
        # l'icone toggle (elle, inchangee, voir le "elif" plus bas).
        img_size = sel_rect.height() if sel_rect.height() > 0 else 14
        # item_image_ratio (largeur/hauteur, voir Colonnes > ... > Image) :
        # 1.0 = carre (comportement INCHANGE par defaut) — plus grand,
        # plus l'image est allongee HORIZONTALEMENT (largeur > hauteur) —
        # voir la remarque de l'utilisateur, "je veux une section ratio,
        # qui correspond au ratio entre la hauteur et la largeur. Plus le
        # chiffre est grand et plus l'image est allongee
        # horizontalement". La HAUTEUR reste toujours celle de la zone de
        # selection (voir plus haut) ; seule la LARGEUR en depend.
        img_ratio = float(s.get("item_image_ratio", 1.0) or 1.0)
        img_width = max(1, round(img_size * img_ratio))
        img_x = sel_rect.left() if sel_rect.width() > 0 else icon_x
        img_y = sel_rect.top() if sel_rect.height() > 0 else rect.center().y() - 7
        img_slot = QRect(img_x, img_y, img_width, img_size)
        # Padding/bordure/rayon (voir Colonnes > ... > Image, DEFAULT_
        # SETTINGS.item_image_*) — voir la remarque de l'utilisateur,
        # "les parametres images ... sont pour controler les apercus
        # que l'on trouve sur les differentes lignes". item_image_radius
        # est un reglage INDEPENDANT du rayon de selection (0 = carre).
        _paint_row_image(painter, img_slot, pixmap, s)
        # Distance texte<->image PILOTEE par "Padding du texte" (item_
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
        img_right_pad = max(0, int((s.get("item_image_padding") or {}).get("right", 0)))
        text_x = img_x + img_width - img_right_pad + text_padding
    elif icon_enabled:
        box_y = rect.center().y() - 14 // 2
        painter.setPen(QPen(QColor(role_color("dim", C["label"])), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(icon_x, box_y, 14 - 1, 14 - 1)
        text_x = icon_x + 14 + 8

    final_text_color = C["accent_text"] if (selected and active) else text_color
    text_rect = QRect(text_x, rect.top(), rect.right() - text_x - text_padding, rect.height())
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
            painter.setPen(QColor(role_color("info", C["dim"])))
            elided_ann = painter.fontMetrics().elidedText(ann_text, Qt.ElideRight, ann_rect.width())
            painter.drawText(ann_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_ann)
    else:
        painter.setFont(text_font)
        painter.setPen(QColor(final_text_color))
        elided = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, max(0, text_rect.width()))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)


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
        self.font_name, self.color_name = _resolve_row_font_color(self.column.column_title)

    def sizeHint(self, option, index) -> QSize:
        # L'espacement est ajoute ici, retranche au dessin (voir paint) :
        # voir la remarque sur QListView.setSpacing dans Column.__init__.
        title = self.column.column_title
        return QSize(self.column.width(), col_row_height(title) + col_spacing(title))

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
        title = self.column.column_title
        rect = option.rect.adjusted(0, 0, 0, -col_spacing(title))
        _paint_unified_row(
            painter, rect, option, column_style_for(title),
            path.name, project_thumbnail_pixmap(path), self.font_name, self.color_name, self.column.is_active,
        )
        painter.restore()


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
                 font_family: str | None = None, smoothing: str = "current"):
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
        self.setFont(font(font_size, 700, family=resolved_family, tracking=0.08, smoothing=smoothing))
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

    def __init__(self, title: str, pixmap: QPixmap, width: int, path: Path, open_status, parent=None):
        super().__init__(parent)
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
        title_font_family = _resolve_font_family(
            (s.get("preview_title_font_family") or "").strip(), title_font_size, 700)
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
        status_font_family = _resolve_font_family(
            (s.get("preview_status_font_family") or "").strip(), status_font_size, 700, fallback_role="info")
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
        # Colonnes > Couleur de fond — PLUS de reglage "Zone titre > Fond"
        # separe, source de confusion/desaccord avec cette seule et unique
        # couleur) — voir la remarque de l'utilisateur, "voici la couleur
        # a appliquer sur les zones avec des croix" (pointant precisement
        # sur "Couleur de fond"). Aucun filet entre les indicateurs et le
        # titre (border: none, EXPLICITE) — juste explicite ici pour ne
        # PAS heriter d'un style par defaut.
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
                font_family=status_font_family, smoothing=status_font_smoothing)
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
        name.setFont(font(title_font_size, 700, family=title_font_family, tracking=0.0, smoothing=title_font_smoothing))
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
        # _image_wrap_layout.setContentsMargins plus bas) — voir la
        # remarque de l'utilisateur, "voici la couleur a appliquer sur les
        # zones avec des croix".
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
                 user_width: int | None = None, on_resize=None,
                 group_kind: str | None = None, on_reorder=None,
                 user_height: int | None = None, on_height_resize=None, fill_height: bool = False,
                 on_height_resize_begin=None, on_height_resize_end=None,
                 source_labels: list[str] | None = None):
        super().__init__(parent)
        self.directory = directory
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
        # STYLE/COLUMN_SETTINGS) — permet a IN/OVER/OUT de partager le style
        # "Type" (liste plate, sans vignette ni icone logiciel) tout en
        # affichant leur propre libelle.
        self.has_thumbnails = title in THUMBNAIL_COLUMN_LABELS
        # Repli/depli (voir set_collapsed) : seules Type/Projets/Sous-projet
        # sont concernees (voir COLLAPSIBLE_COLUMN_TITLES et
        # PipelineBrowser._sync_collapse_state) — Logiciels/Contenu n'ont pas
        # d'icone et ignorent silencieusement tout appel a set_collapsed.
        self.collapsible = title in COLLAPSIBLE_COLUMN_TITLES
        self.collapsed = False
        self._expanded_width = None
        self._width_anim = None

        self.title_label = QLabel(display_title or title)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")

        self.count_label = QLabel("")
        self.count_label.setFont(role_font("info", 10, 400))
        self.count_label.setStyleSheet(f"color: {role_color('info', C['count'])}; background: transparent;")

        # objectName + selecteur ID : voir la remarque sur #TitleBar dans
        # PipelineBrowser — sans lui, title_label/count_label heriteraient du
        # border-bottom nu et se retrouveraient chacun souligne sur sa
        # largeur de texte au lieu du filet courant sur toute la colonne.
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
        header_layout.addWidget(self.count_label)
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

        self.setFixedWidth(self._user_width or col_width(title))
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
            self._group_header_widgets = (header, header_fill, self.title_label, self.count_label)
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
            target = self._expanded_width or self._user_width or col_width(self.column_title)
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
            self.setMinimumHeight(GROUP_COLUMN_MIN_HEIGHT)
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
        du clavier et cliquer entre deux lignes et glisser". Seules les
        colonnes a hauteur de ligne UNIFORME/surchargeable (voir
        _ROW_HEIGHT_RESIZABLE_TITLES) sont concernees — Logiciels/Contenu
        melangent 2 hauteurs (voir col_plain_height) sans reglage unique a
        ajuster."""
        if self.column_title not in _ROW_HEIGHT_RESIZABLE_TITLES:
            return False
        if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
            return False
        above = self.list.indexAt(QPoint(1, y - COLUMN_RESIZE_MARGIN))
        if not above.isValid():
            return False
        below = self.list.indexAt(QPoint(1, y + COLUMN_RESIZE_MARGIN))
        return not below.isValid() or below.row() != above.row()

    def row_resize_begin(self, global_y: int):
        self._row_resizing = True
        self._row_resize_start_y = global_y
        self._row_resize_start_height = COLUMN_SETTINGS[_col_key(self.column_title)]["height"]
        _show_resize_width(self, col_row_height(self.column_title))

    def row_resize_update(self, global_y: int):
        delta_screen = global_y - self._row_resize_start_y
        delta_logical = round(delta_screen * 100 / max(1, ui_scale()))
        new_height = max(
            ROW_RESIZE_MIN_HEIGHT, min(ROW_RESIZE_MAX_HEIGHT, self._row_resize_start_height + delta_logical))
        COLUMN_SETTINGS[_col_key(self.column_title)]["height"] = new_height
        # doItemsLayout() (pas juste un repaint) : sizeHint() de CHAQUE ligne
        # depend de col_row_height(), qu'on vient de changer — un simple
        # viewport().update() garderait les anciennes tailles/positions.
        # _throttled_layout() (pas un appel direct) : voir son commentaire,
        # limite ce recalcul a ~60/s pendant le glisser.
        self._throttled_layout()
        _show_resize_width(self, scaled(new_height))
        _sync_settings_dialog_row_height(self.window(), self.column_title, new_height)

    def row_resize_end(self):
        self._row_resizing = False
        _hide_resize_width(self)
        # Purge immediate (voir resize_end, meme raison) : la hauteur du
        # tout dernier mouvement doit s'appliquer sans attendre le prochain
        # timeout de _layout_throttle_timer.
        self._layout_throttle_timer.stop()
        self._layout_pending = False
        self.list.doItemsLayout()
        # Persiste sur le disque (voir _persist_row_height) : sans ca, la
        # hauteur choisie ici ne survivrait pas a un redemarrage/reload, ni
        # a un _apply_settings ulterieur (Colonnes > ... la reecraserait
        # avec la valeur EFFECTIVE actuelle des reglages, voir
        # apply_all_settings).
        _persist_row_height(self.window(), self.column_title, COLUMN_SETTINGS[_col_key(self.column_title)]["height"])

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
            if obj is self.list.viewport() and self._in_row_resize_zone(int(event.position().y())):
                self.row_resize_begin(event.globalPosition().toPoint().y())
                return True
            local_point = obj.mapTo(self, event.position().toPoint())
            if self._in_height_resize_zone(local_point.y()):
                self.height_resize_begin(event.globalPosition().toPoint().y())
                return True
            if self._in_resize_zone(local_point.x()):
                self.resize_begin(event.globalPosition().toPoint().x())
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
                entries.extend((path, label) for path in list_entries(source))
        else:
            # Colonnes a vignettes (Projets/Sous-projet) : in/over/out ne
            # sont jamais des lignes normales, ils deviennent des colonnes
            # dediees (voir IN/OVER/OUT ci-dessus, STATUS_FOLDERS).
            exclude = _STATUS_FOLDER_SET if self.has_thumbnails else None
            entries = [(path, None) for path in list_entries(self.directory, exclude)]
        for path, label in entries:
            item = QListWidgetItem(path.name)
            item.setData(ROLE_PATH, str(path))
            is_dir = path.is_dir()
            item.setData(ROLE_ISDIR, is_dir)
            item.setData(ROLE_SOURCE_LABEL, label)
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
        self.count_label.setText(str(len(entries)))
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
        self.header_fill.setStyleSheet(column_header_qss("ColumnHeader", self.column_title))
        frame = column_frame_style(self.column_title, self._suppress_left())
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
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        self.count_label.setStyleSheet(f"color: {role_color('info', C['count'])}; background: transparent;")

    def _suppress_left(self) -> bool:
        """Voir _column_suppress_left (module-level, factorisee pour etre
        partagee avec PreviewColumn)."""
        return _column_suppress_left(self, self.column_title)

    def refresh_header(self):
        """Reapplique hauteur/padding/police de l'entete (voir HEADER_HEIGHT/
        HEADER_PADDING, role 'colhead') — reglable en direct depuis
        Parametres > Entetes. HEADER_PADDING est la marge de header (voir
        __init__) : l'espace entre le fond colore (header_fill) et les
        bords de la colonne, pas la marge du texte a l'interieur du fond.

        Style EFFECTIF de CETTE colonne (voir app_style.column_style_for —
        general, ou surcharge Colonnes > Type pour "Type") plutot que les
        globals HEADER_HEIGHT/HEADER_PADDING partages a l'ancienne."""
        s = column_style_for(self.column_title)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", HEADER_HEIGHT))
        padding = int(s.get("header_padding", HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)   # 0 = valeur reglee valide (voir scaled)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.count_label.setFont(role_font("info", 10, 400))
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
        col_pad = dict(column_padding_for(self.column_title))
        if self._suppress_left():
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()

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
            act_paste = None
            if QApplication.clipboard().mimeData().hasUrls():
                menu.addSeparator()
                act_paste = menu.addAction("Coller")
            chosen = menu.exec(self.list.mapToGlobal(pos))
            if chosen is act_new_folder:
                self._create_folder()
            elif act_paste is not None and chosen is act_paste:
                self._paste_items()
            return
        path = Path(item.data(ROLE_PATH))
        menu = QMenu(self)
        menu.setFont(font(11, 400))
        act_open = menu.addAction("Ouvrir")
        act_rename = menu.addAction("Renommer")
        act_reveal = menu.addAction("Afficher dans l'explorateur")
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

        act_change_icon = None
        act_capture_icon = None
        act_reset_icon = None
        software_key = None
        if self.column_title == SOFTWARE_COLUMN_LABEL and item.data(ROLE_ISDIR):
            software_key = software_icon_key(path.name)
            if software_key is not None:
                menu.addSeparator()
                act_change_icon = menu.addAction("Changer l'icone du logiciel...")
                act_capture_icon = menu.addAction("Capturer une zone d'ecran (icone)...")
                if custom_software_icon_path(software_key).is_file():
                    act_reset_icon = menu.addAction("Reinitialiser l'icone du logiciel")

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
        elif act_change_thumb is not None and chosen is act_change_thumb:
            self._change_thumbnail(path)
        elif act_capture_thumb is not None and chosen is act_capture_thumb:
            self._capture_thumbnail(path)
        elif act_reset_thumb is not None and chosen is act_reset_thumb:
            self._reset_thumbnail(path)
        elif act_change_icon is not None and chosen is act_change_icon:
            self._change_software_icon(software_key)
        elif act_capture_icon is not None and chosen is act_capture_icon:
            self._capture_software_icon(software_key)
        elif act_reset_icon is not None and chosen is act_reset_icon:
            self._reset_software_icon(software_key)
        elif chosen is act_copy_file:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(path))

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
        new_path = self.directory / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau dossier", f"« {name} » existe deja.")
            return
        try:
            new_path.mkdir()
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau dossier", f"Impossible de creer le dossier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

    def _change_thumbnail(self, path: Path):
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image", str(path),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)",
        )
        if not chosen:
            return
        pix = QPixmap(chosen)
        if pix.isNull():
            QMessageBox.warning(self, "Image", "Impossible de charger cette image.")
            return
        self._save_thumbnail_pixmap(path, pix)

    def _capture_thumbnail(self, path: Path):
        """Ouvre un selecteur de zone carree (un par ecran connecte) pour
        capturer une vignette de projet directement depuis l'affichage."""
        win = self.window()
        was_visible = win.isVisible()
        if was_visible:
            win.hide()
        QApplication.processEvents()

        def start_overlay():
            capture = MultiScreenCapture()
            self._capture_overlay = capture  # garde une reference tant que les fenetres sont ouvertes

            def finish():
                if was_visible:
                    win.show()
                self._capture_overlay = None

            def on_captured(pix: QPixmap):
                finish()
                self._save_thumbnail_pixmap(path, pix)

            capture.captured.connect(on_captured)
            capture.cancelled.connect(finish)

        # Laisse le temps a la fenetre principale de disparaitre avant la
        # capture, sinon elle apparait encore dans la vignette.
        QTimer.singleShot(150, start_overlay)

    def _save_thumbnail_pixmap(self, path: Path, pix: QPixmap):
        if pix.isNull():
            return
        if max(pix.width(), pix.height()) > THUMBNAIL_MAX_DIM:
            pix = pix.scaled(
                THUMBNAIL_MAX_DIM, THUMBNAIL_MAX_DIM,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        dest = project_thumbnail_path(path)
        if not pix.save(str(dest), "PNG"):
            QMessageBox.warning(self, "Image", "Impossible d'enregistrer la vignette.")
            return
        _set_hidden(dest)
        self.list.viewport().update()

    def _reset_thumbnail(self, path: Path):
        thumb = project_thumbnail_path(path)
        if thumb.exists():
            try:
                thumb.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "Image", f"Impossible de supprimer la vignette :\n{exc}")
                return
        self.list.viewport().update()

    def _change_software_icon(self, key: str):
        """Icone perso pour un logiciel : globale (voir custom_software_icon_path),
        s'applique donc partout ou ce logiciel apparait, pas seulement ici."""
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)",
        )
        if not chosen:
            return
        pix = QPixmap(chosen)
        if pix.isNull():
            QMessageBox.warning(self, "Icone", "Impossible de charger cette image.")
            return
        self._save_software_icon_pixmap(key, pix)

    def _capture_software_icon(self, key: str):
        win = self.window()
        was_visible = win.isVisible()
        if was_visible:
            win.hide()
        QApplication.processEvents()

        def start_overlay():
            capture = MultiScreenCapture()
            self._capture_overlay = capture

            def finish():
                if was_visible:
                    win.show()
                self._capture_overlay = None

            def on_captured(pix: QPixmap):
                finish()
                self._save_software_icon_pixmap(key, pix)

            capture.captured.connect(on_captured)
            capture.cancelled.connect(finish)

        QTimer.singleShot(150, start_overlay)

    def _save_software_icon_pixmap(self, key: str, pix: QPixmap):
        if pix.isNull():
            return
        if max(pix.width(), pix.height()) > CUSTOM_SOFTWARE_ICON_MAX_DIM:
            pix = pix.scaled(
                CUSTOM_SOFTWARE_ICON_MAX_DIM, CUSTOM_SOFTWARE_ICON_MAX_DIM,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        dest = custom_software_icon_path(key)
        try:
            was_new = not dest.parent.is_dir()
            dest.parent.mkdir(parents=True, exist_ok=True)
            if was_new:
                _set_hidden(dest.parent)
        except OSError as exc:
            QMessageBox.warning(self, "Icone", f"Impossible de creer le dossier de configuration :\n{exc}")
            return
        if not pix.save(str(dest), "PNG"):
            QMessageBox.warning(self, "Icone", "Impossible d'enregistrer l'icone.")
            return
        _set_hidden(dest)
        self.list.viewport().update()

    def _reset_software_icon(self, key: str):
        dest = custom_software_icon_path(key)
        if dest.exists():
            try:
                dest.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "Icone", f"Impossible de supprimer l'icone :\n{exc}")
                return
        self.list.viewport().update()

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
            self.toggle_btn.setToolTip("Replier Type/Projets/Sous-projet")
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
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
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
        depli de Type/Projets/Sous-projet declenche depuis ailleurs (par
        exemple automatiquement, voir PipelineBrowser._sync_collapse_state)
        — sans effet si cette instance n'a pas d'icone (fantome
        "Logiciels")."""
        if self.toggle_btn is None:
            return
        self.toggle_btn.set_kind("dchevron_left" if collapsed else "dchevron_right")
        self.toggle_btn.setToolTip(
            "Deplier Type/Projets/Sous-projet" if collapsed else "Replier Type/Projets/Sous-projet"
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

    def set_preview_block(self, title: str, pixmap: QPixmap, path: Path, open_status):
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
        l'autre !"."""
        self._clear_preview_layout()
        block = _PreviewBlock(title, pixmap, self._content_width(), path, open_status)
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

        self.well = QFrame()
        self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
        self.well.setStyleSheet(
            f"background: {C['well']}; border: 1px solid #282c30;"
        )
        self._preview_pixmap: QPixmap | None = None
        self.well_label = QLabel(self.well)
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        well_layout = QVBoxLayout(self.well)
        well_layout.setContentsMargins(0, 0, 0, 0)
        well_layout.addWidget(self.well_label)

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

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self.values: dict[str, QLabel] = {}
        self.key_labels: dict[str, QLabel] = {}
        for row, key in enumerate(self.FIELDS):
            key_label = QLabel(key)
            key_label.setFont(role_font("info", 11, 400))
            key_label.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
            self.key_labels[key] = key_label
            value = QLabel("")
            value.setFont(role_font("info", 11, 400))
            value.setStyleSheet(f"color: {role_color('info', '#aab1b6')}; background: transparent;")
            value.setWordWrap(True)
            grid.addWidget(key_label, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)

        content = QVBoxLayout()
        self._content_layout = content
        content.setContentsMargins(16, 14, 16, 14)
        content.setSpacing(8)
        content.addWidget(self.name)
        content.addWidget(self.well)
        content.addWidget(self.text_preview)
        content.addWidget(self.video_widget)
        content.addLayout(grid)
        content.addStretch(1)

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

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(
                DETAIL_PANEL_MIN_WIDTH,
                min(self._max_width(), self._resize_start_width - delta),
            )
            self.setFixedWidth(new_width)
            _show_resize_width(self, new_width)
            return
        if x <= COLUMN_RESIZE_MARGIN:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        x = event.position().toPoint().x()
        if event.button() == Qt.LeftButton and x <= COLUMN_RESIZE_MARGIN:
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_width = self.width()
            _show_resize_width(self, self.width())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            _hide_resize_width(self)
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
        self.name.setText("")
        self.badge.setText("")
        self.well.hide()
        self._preview_pixmap = None
        self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
        self.well_label.clear()
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
        ici (voir sa docstring)."""
        self.header_title.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.header_title.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        for key_label in self.key_labels.values():
            key_label.setFont(role_font("info", 11, 400))
            key_label.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        for value in self.values.values():
            value.setFont(role_font("info2", 11, 400))
            value.setStyleSheet(f"color: {role_color('info2', '#aab1b6')}; background: transparent;")

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
        self.refresh_fonts(True if not self.values["kind"].text() else self.values["kind"].text() == "Dossier")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def _update_preview(self):
        if self._preview_pixmap is None:
            self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
            self.well_label.clear()
            return
        pw, ph = self._preview_pixmap.width(), self._preview_pixmap.height()
        if pw <= 0 or ph <= 0:
            self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
            self.well_label.clear()
            return
        # Largeur disponible = largeur du panneau moins ses marges (16 de
        # chaque cote). Jamais d'agrandissement au-dela de la taille reelle
        # de l'image, et jamais plus haut que PREVIEW_MAX_HEIGHT.
        avail_w = max(self.width() - 32, 50)
        scale = min(1.0, avail_w / pw, PREVIEW_MAX_HEIGHT / ph)
        final_w = max(1, round(pw * scale))
        final_h = max(1, round(ph * scale))
        self.well.setFixedHeight(max(final_h, PREVIEW_MIN_HEIGHT))
        scaled = self._preview_pixmap.scaled(
            final_w, final_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.well_label.setPixmap(scaled)

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
        self.name.setText(path.name)
        is_dir = path.is_dir()
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self._preview_pixmap = None
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
                    pix = QPixmap(str(path))
                    if not pix.isNull():
                        self._preview_pixmap = pix
                elif suffix in OBJ_EXTENSIONS or suffix in PSD_EXTENSIONS or suffix in EXR_EXTENSIONS:
                    # Rendu genere (.obj, voir _decode_obj_image), vignette
                    # embarquee extraite (.psd/.psb, voir
                    # _decode_psd_thumbnail) ou tone-mapping HDR (.exr, voir
                    # _decode_exr_image) : pas un fichier que QPixmap sait
                    # charger directement, passe par le meme cache que les
                    # cartes-fichier (file_image_pixmap).
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
            self._update_preview()
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
        color = self._hover_color if self.underMouse() else self._color
        pen = QPen(QColor(color))
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        rect = self.rect()
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
        icon.setFixedSize(scaled(9), scaled(9))
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
        # Groupe IN/OVER/OUT/LOGICIELS (voir update_preview_stack) : 4
        # colonnes fantomes EMPILEES VERTICALEMENT (meme principe que
        # _preview_stack_wrapper ci-dessous), reconstruites entierement a
        # chaque navigation — voir _clear_group_stack.
        self._group_stack_wrapper: QWidget | None = None
        self.group_columns: list[Column] = []
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

    def _clear_group_stack(self):
        if self._group_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._group_stack_wrapper)
            self._group_stack_wrapper.setParent(None)
            self._group_stack_wrapper.deleteLater()
            self._group_stack_wrapper = None
        self.group_columns = []

    def _clear_image_preview_columns(self):
        if self._preview_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._preview_stack_wrapper)
            self._preview_stack_wrapper.setParent(None)
            self._preview_stack_wrapper.deleteLater()
            self._preview_stack_wrapper = None
        self.image_preview_columns = []

    def add_column(self, directory: Path, depth: int, title: str | None = None):
        # `title` : impose un intitule (voir _open_group_folder, qui ouvre
        # un dossier in/over/out/logiciel sans rapport avec ce que la profondeur
        # suggererait normalement — pas question d'afficher "SOUS-PROJET" au
        # dessus du contenu de "in"). None (cas normal) : intitule deduit de
        # la profondeur, comme avant.
        if title is None:
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        column = Column(directory, title)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
        self.columns.append(column)
        # Le groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
        # stack) peut occuper cet emplacement depuis la selection
        # precedente : le retirer avant d'ajouter la vraie colonne, sinon
        # celle-ci se retrouverait ajoutee APRES lui dans columns_layout
        # (ordre visuel casse). image_preview_column, elle, n'est PAS
        # retiree ici : c'est une colonne permanente qui doit rester juste
        # avant celle qu'on ajoute (voir update_preview_stack, qui la
        # reconstruit a la bonne position a chaque appel).
        self._clear_group_stack()
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
                column.setFixedWidth(column._user_width or col_width(column.column_title))
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
                do_layout = relayout_titles is None or column.column_title in relayout_titles
                column.relayout(do_layout=do_layout)
        self.update_preview_stack()

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        for i, column in enumerate(self.columns):
            column.set_active(i == last_selected)

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
        self._clear_group_stack()
        self._clear_image_preview_columns()
        if not self.columns:
            return
        entries: list[tuple[str, QPixmap, Path, object, str]] = []
        for column in self.columns:
            if not column.has_thumbnails:
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
            entries.append((path.name, project_thumbnail_pixmap(path), path, open_status, column.column_title))

        if not entries:
            return

        # 1. Vignettes : juste APRES LA DERNIERE COLONNE A VIGNETTES
        # (Sous-projet, sinon Projets). Surtout pas len(self.columns) : cet
        # indice pointe apres la derniere colonne REELLE, ce qui rejetait
        # les images derriere toute colonne ouverte ensuite depuis le
        # groupe IN/OVER/OUT/LOGICIELS — les colonnes paraissaient "toutes
        # melangees". Le groupe vient d'etre retire (voir plus haut), donc
        # a cet instant columns_layout contient exactement self.columns,
        # dans l'ordre : l'indice de colonne vaut l'indice de layout.
        anchor = max(i for i, c in enumerate(self.columns) if c.has_thumbnails)
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
        for offset, (title, pixmap, path, open_status, level_title) in enumerate(entries):
            column = PreviewColumn(
                PREVIEW_STACK_TITLE, on_toggle=self._toggle_project_columns if offset == 0 else None,
                user_width=self._preview_column_user_width,
                on_resize=self._on_preview_column_resized, fit_height=True,
                display_title=_FOCUS_LEVEL_LABEL.get(level_title, PREVIEW_STACK_TITLE))
            if offset == 0:
                column.set_toggle_state(self._project_columns_collapsed)
            wrapper_layout.addWidget(column)
            column.set_preview_block(title, pixmap, path, open_status)
            self.image_preview_columns.append(column)
        self._preview_stack_wrapper = wrapper
        self.columns_layout.insertWidget(anchor + 1, wrapper)

        # 2. Groupe IN/OVER/OUT/LOGICIELS : insere JUSTE APRES LES VIGNETTES
        # (anchor + 2), PAS ajoute en fin (`addWidget`) — meme raison que
        # pour les vignettes ci-dessus : une colonne ouverte depuis une
        # PRECEDENTE navigation dans le groupe peut deja trainer en fin de
        # columns_layout (voir _open_group_folder) au moment ou ce groupe
        # est reconstruit, il doit malgre tout rester colle juste apres les
        # vignettes, pas relegue derriere.
        levels = [path for (_name, _pix, path, _open, _level) in entries]
        # LOGICIELS (voir add_group_column plus bas) : seulement une fois
        # "Sous-projet" REELLEMENT selectionne (pas juste "Projets") — meme
        # condition que l'ancienne vraie colonne "Logiciels", qui n'existait
        # jamais avant ce choix (voir COLUMN_LABELS/on_selected) ; sans
        # cette garde, _softs_subdir(levels[-1]) retombait sur le contenu
        # BRUT du Projet (repli documente dans _softs_subdir) des que
        # "Projets" seul etait selectionne, un contenu sans rapport affiche
        # a tort sous l'entete "LOGICIELS".
        softs_dirs = [_softs_subdir(levels[-1])] if entries[-1][4] == "Sous-projet" else []
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
        last_kind = self._group_column_order[-1] if self._group_column_order else None

        # Annotation "(projet)"/"(<nom du sous-projet>)" (voir Column.
        # __init__ source_labels/ROLE_SOURCE_LABEL) : UNE par niveau
        # selectionne, PARALLELE a `levels` — "projet" pour le niveau
        # "Projets", le nom REEL du sous-projet (son propre `title`, deja
        # `path.name`) pour le niveau "Sous-projet" — voir la remarque de
        # l'utilisateur, "si c'est projet, le texte doit etre 'projet' et
        # si c'est sous projet, il doit etre du nom du sous projet".
        # SEULEMENT pour IN/OVER/OUT (voir add_group_column) : LOGICIELS
        # n'a qu'UNE SEULE source (le niveau le plus profond, voir
        # softs_dirs), une annotation n'y aurait aucun sens.
        level_labels = ["projet" if level_title == "Projets" else title
                         for (title, _pix, _path, _open, level_title) in entries]

        def add_group_column(kind: str, display: str, source_dirs: list[Path], style_title: str,
                              source_labels: list[str] | None = None):
            fill = kind == last_kind
            column = Column(
                source_dirs[0] if source_dirs else levels[-1], style_title,
                source_dirs=source_dirs, source_labels=source_labels, display_title=display,
                user_width=self._group_column_user_width, on_resize=self._on_group_column_resized,
                group_kind=kind, on_reorder=self._on_group_reorder,
                user_height=self._group_column_user_heights.get(kind), on_height_resize=self._on_group_height_resized,
                on_height_resize_begin=self._on_group_height_resize_begin,
                on_height_resize_end=self._on_group_height_resize_end,
                fill_height=fill)
            column.selected.connect(lambda _col, p, k=kind: self._on_group_item_selected(p, k))
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
            "logiciels": (SOFTWARE_COLUMN_LABEL, softs_dirs, SOFTWARE_COLUMN_LABEL, None),
        }
        for status_name in STATUS_FOLDERS:
            source_dirs = [status_folder_state(level, status_name)[1] for level in levels]
            groups[status_name] = (status_name.upper(), source_dirs, "Contenu", level_labels)
        for kind in self._group_column_order:
            display, source_dirs, style_title, source_labels = groups[kind]
            add_group_column(kind, display, source_dirs, style_title, source_labels)

        self._group_stack_wrapper = group_wrapper
        self.columns_layout.insertWidget(anchor + 2, group_wrapper)

        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _on_group_item_selected(self, path: Path | None, kind: str) -> None:
        """Reagit a un clic sur une ligne du groupe IN/OVER/OUT/LOGICIELS
        (voir update_preview_stack) : un dossier ouvre son contenu dans une
        VRAIE colonne suivante (voir _open_group_folder) — navigation
        normale, pas l'explorateur Windows. Un fichier ne fait rien de plus
        ici (deja previsualise dans l'inspecteur par la selection normale
        de Column/on_selected — non branche pour ce groupe, voir sa
        remarque) ; double-clic l'ouvre malgre tout via l'application par
        defaut (voir Column.activated/on_activated, cable separement)."""
        if path is None or not path.is_dir():
            return
        title = "Contenu" if kind == "logiciels" else path.name.upper()
        self._open_group_folder(path, title)

    def _open_group_folder(self, path: Path, title: str | None = None) -> None:
        """Ouvre `path` (indicateur in/over/out d'un _PreviewBlock, ou une
        ligne de dossier du groupe IN/OVER/OUT/LOGICIELS, voir
        update_preview_stack/_on_group_item_selected) dans une VRAIE
        colonne juste apres la derniere colonne a vignettes (Sous-projet si
        elle existe, sinon Projets) — jamais `Column_index`, une colonne
        arbitraire plus loin : ce groupe est TOUJOURS positionne juste apres
        les vignettes, quoi que la navigation ait deja ouvert plus loin."""
        insert_index = max((i for i, c in enumerate(self.columns) if c.has_thumbnails), default=-1)
        self.prune_after(insert_index)
        self.add_column(path, insert_index + 1, title=title or path.name.upper())
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
        d'autre de la zone de selection pour le slide"."""
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
            _show_resize_width(below, new_below, key="group_below")
        else:
            # `below` n'a pas de hauteur FIXE a lui appliquer (elle est
            # etiree, voir set_group_fill_height) : sa taille REELLE ne se
            # met a jour qu'au prochain passage du layout — force-le ICI
            # (voir la meme technique dans _reorder_group_columns_animated)
            # pour que le badge affiche sa valeur A JOUR tout de suite,
            # PENDANT le glisser, pas seulement au relachement.
            wrapper = self._group_stack_wrapper
            if wrapper is not None:
                wrapper.layout().activate()
            _show_resize_width(below, below.height(), key="group_below")
        above._group_user_height = new_above
        above.setFixedHeight(new_above)
        self._group_column_user_heights[kind] = new_above

    def _on_group_height_resize_end(self) -> None:
        self._group_height_drag = None
        _hide_resize_width(self, key="group_below")

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
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
            # "Logiciels" n'est plus une VRAIE colonne de cette chaine :
            # elle fait desormais partie du groupe fantome IN/OVER/OUT/
            # LOGICIELS (voir update_preview_stack, appele juste plus bas),
            # reconstruit a partir de la selection courante — rien a
            # ajouter ici pour ce depth precis, contrairement aux autres.
            if title != SOFTWARE_COLUMN_LABEL:
                self.add_column(path, depth)
        self.update_active_column()
        self.update_preview_stack()
        self._sync_collapse_state()

    def _sync_collapse_state(self):
        """Replie automatiquement Type/Projets/Sous-projet (voir
        COLLAPSIBLE_COLUMN_TITLES) des que Projet ET Sous-projet sont
        choisis (la colonne "Sous-projet" a une selection) : ce contexte
        devient fixe, ces colonnes de navigation n'ont plus besoin de rester
        deployees. Ne force ce repli qu'UNE fois par selection (voir
        _auto_collapse_armed) : un depli manuel ensuite (icone sur la
        colonne des vignettes) n'est pas systematiquement annule tant que
        la selection reste la meme. Redeploie tout automatiquement des que
        la selection de Sous-projet est perdue (retour en arriere dans la
        navigation), pour laisser le choix a nouveau visible, et rearme
        alors le repli automatique pour la prochaine selection."""
        sous_projet = next((c for c in self.columns if c.column_title == "Sous-projet"), None)
        has_selection = sous_projet is not None and sous_projet.current_path() is not None
        if not has_selection:
            self._auto_collapse_armed = True
            if self._project_columns_collapsed:
                self._apply_project_columns_collapsed(False)
        elif self._auto_collapse_armed and not self._project_columns_collapsed:
            self._apply_project_columns_collapsed(True)
            self._auto_collapse_armed = False

    def _toggle_project_columns(self):
        """Reagit a l'icone unique portee par la colonne des vignettes
        (voir PreviewColumn/update_preview_stack) : bascule Type/Projets/
        Sous-projet, et desarme le repli automatique pour que ce choix
        manuel ne soit pas aussitot ecrase par _sync_collapse_state tant
        que la selection de Sous-projet ne change pas."""
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
        self._project_columns_collapsed = collapsed
        for c in self.columns:
            if c.column_title in COLLAPSIBLE_COLUMN_TITLES:
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
        apply_all_settings(settings)
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
            self.refresh_all_columns(rescan=False, relayout_titles=changed_titles)
        # app.setStyleSheet (dans refresh_colors -> refresh_style) repolit
        # TOUS les widgets de TOUTES les fenetres de l'appli — le poste le
        # plus cher, et de loin, de tout ce rafraichissement. Un slider qui
        # ne touche ni aux couleurs, ni au cadre/rayon des boutons, ni au
        # cadre/rayon des zones de saisie, ni au rayon des tableaux (largeur
        # de colonne, echelle, hauteur d'entete...) n'a aucune raison de le
        # declencher a chaque cran : seule une vraie difference sur ces
        # points (les seuls que build_stylesheet lit reellement) force la
        # reconstruction complete de la feuille de style.
        colors = settings.get("colors") or {}
        style_key = (
            tuple(colors.get(k, C[k]) for k in STYLESHEET_COLOR_KEYS),
            settings.get("button_radius"),
            settings.get("button_frame"),
            settings.get("input_radius"),
            settings.get("input_frame"),
            settings.get("table_radius"),
        )
        rebuild_stylesheet = style_key != self._last_style_key
        self._last_style_key = style_key
        self.refresh_colors(rebuild_stylesheet=rebuild_stylesheet)
        self.refresh_chrome_sizes()
        self._apply_native_frame()

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

    RESIZE_BADGE_STYLE = {
        "position": settings.get("resize_badge_position", "bottom_right"),
        "offset_x": int(settings.get("resize_badge_offset_x", 8)),
        "offset_y": int(settings.get("resize_badge_offset_y", 8)),
        "font_family": settings.get("resize_badge_font_family", ""),
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
    for real_title in ("Type", "Projets", "Sous-projet"):
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

    # "Logiciels"/"Contenu" n'ont pas d'onglet de surcharge dedie (voir
    # settings_window._build_columns_page) : suivent directement la
    # valeur GENERALE, jamais une surcharge PAR TITRE — memes cles que
    # ci-dessus, meme raison (voir la remarque de l'utilisateur juste au-
    # dessus).
    for real_title in ("Logiciels", "Contenu"):
        if real_title not in COLUMN_SETTINGS:
            continue
        if settings.get("item_row_height") is not None:
            COLUMN_SETTINGS[real_title]["height"] = int(settings.get("item_row_height"))
        COLUMN_SETTINGS[real_title]["spacing"] = max(0, int(settings.get("item_row_spacing") or 0))
        if settings.get("item_column_width") is not None:
            COLUMN_SETTINGS[real_title]["width"] = int(settings.get("item_column_width"))

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
