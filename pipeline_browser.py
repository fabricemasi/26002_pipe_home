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
    QByteArray, QEvent, QEventLoop, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl,
    Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QDrag,
    QFontMetrics,
    QImage,
    QImageReader,
    QLinearGradient,
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
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

# Qt expose QWIDGETSIZE_MAX en C++ mais pas toujours dans les bindings Python
# (absent de cette version de PySide6) : c'est la valeur historique (2**24-1)
# utilisee par setMaximumHeight/Width pour signifier "pas de limite".
QWIDGETSIZE_MAX = 16777215

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
    apply_dwm_frame,
    apply_style,
    font,
    refresh_style,
    role_color,
    role_font,
    scaled,
    set_button_radius,
    set_color,
    set_role_font,
    set_ui_scale,
    start_native_move,
)
from settings_window import SettingsWindow, load_settings

# ==========================================================================
# Configuration
# ==========================================================================

ROOT = Path(r"F:\PIPELINE")

COLUMN_LABELS = ["Type", "Projets", "Sous-projet", "Logiciels", "Contenu"]

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
FILE_PREVIEW_ROW_HEIGHT = 64   # hauteur de ces lignes-carte (reglable independamment de PROJECT_ROW_HEIGHT)

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


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


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
    Le recadrage carre final se fait au dessin (voir paint_thumbnail_row), a
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
ROW_HEIGHT = 24
ROW_SPACING = 1            # espace (px) entre les lignes, dans toutes les colonnes
HEADER_HEIGHT = 26
TOPBAR_HEIGHT = 40
STATUS_HEIGHT = 24
TITLEBAR_HEIGHT = 28
DETAIL_PANEL_WIDTH = 300
DETAIL_PANEL_MIN_WIDTH = 220
DETAIL_PANEL_MAX_WIDTH = 520

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
    "Type":        {"width": 140, "height": 25, "spacing": 0, "img_pad": 0, "img_radius": 0, "sep_h": True, "sep_v": True},
    "Projets":     {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0, "sep_h": True, "sep_v": True},
    "Sous-projet": {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0, "sep_h": True, "sep_v": True},
    "Logiciels":   {"width": 186, "height": 30, "plain_height": 22, "spacing": 0, "img_pad": 3, "img_radius": 2, "sep_h": True, "sep_v": True},
    "Contenu":     {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0, "sep_h": True, "sep_v": True},
}

# Padding (sur les 4 cotes) et rayon appliques a la grande vignette carree de
# l'apercu empile (voir _SquarePreviewImage) — distinct du padding par
# colonne ci-dessus, qui lui ne concerne que les vignettes DANS les lignes
# des colonnes Projets/Sous-projet/Logiciels/Contenu.
PREVIEW_IMAGE_PAD = 0
PREVIEW_IMAGE_RADIUS = 0


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


def col_sep_h(title: str) -> bool:
    """Ligne horizontale entre deux lignes de vignettes (voir
    paint_thumbnail_row)."""
    return COLUMN_SETTINGS[_col_key(title)].get("sep_h", True)


def col_sep_v(title: str) -> bool:
    """Ligne verticale separant la vignette du texte (nom/metadonnee),
    voir paint_thumbnail_row."""
    return COLUMN_SETTINGS[_col_key(title)].get("sep_v", True)


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


def _resize_width_indicator(win: QWidget) -> QLabel:
    """Badge flottant affichant la largeur (px) pendant le redimensionnement
    d'une colonne ou du panneau de details (voir Column.resize_*/
    DetailPanel mousePressEvent/mouseMoveEvent/mouseReleaseEvent). Un seul
    par fenetre, cree a la demande et stocke sur `win` : jamais plus d'un
    redimensionnement actif en meme temps de toute facon, pas besoin d'une
    instance par widget redimensionnable."""
    label = getattr(win, "_resize_width_label", None)
    if label is None:
        label = QLabel(win)
        label.setObjectName("ResizeWidthIndicator")
        label.setFont(font(11, 600, mono=True))
        label.setStyleSheet(
            f"#ResizeWidthIndicator {{ background: {C['chrome']}; color: {C['text']};"
            f" border: 1px solid {C['border']}; border-radius: 4px; padding: 3px 8px; }}"
        )
        # Sinon ce badge, place tout pres du bord glisse, peut lui-meme
        # recevoir les evenements souris et bloquer le redimensionnement en
        # cours.
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        win._resize_width_label = label
    return label


def _show_resize_width(widget: QWidget, width: int) -> None:
    """Affiche/deplace le badge de largeur pres du coin bas-droit de
    `widget` (le bord qu'on est en train de glisser) — voir
    _resize_width_indicator."""
    win = widget.window()
    label = _resize_width_indicator(win)
    label.setText(str(width))
    label.adjustSize()
    bottom_right = widget.mapToGlobal(QPoint(widget.width(), widget.height() - 8))
    local = win.mapFromGlobal(bottom_right)
    label.move(local.x() - label.width() - 8, local.y() - label.height())
    label.show()
    label.raise_()


def _hide_resize_width(widget: QWidget) -> None:
    label = getattr(widget.window(), "_resize_width_label", None)
    if label is not None:
        label.hide()


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


class RowDelegate(QStyledItemDelegate):
    """Marqueur carre + nom + metadonnee alignee a droite. Un fichier image
    (si SHOW_FILE_IMAGE_PREVIEWS) prend a la place exactement le style des
    cartes de projet : vignette carree du fichier lui-meme + nom/taille."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.refresh_fonts()

    def refresh_fonts(self):
        """Relit les polices de role courantes (voir role_font) : appele a
        la creation, et de nouveau si l'utilisateur change les parametres de
        typographie sans reconstruire la colonne (previsualisation en direct)."""
        self.font_dir = role_font("folders", 12, 600, tracking=0.12)
        self.font_file = role_font("files", 12, 400, tracking=0.12)
        self.font_meta = role_font("info", 11, 400)
        self.font_image_name = role_font("files", 12, 600, tracking=0.01)
        self.font_image_sub = role_font("info", 10, 400)
        self.color_dir = role_color("folders", C["text"])
        self.color_file = role_color("files", C["text_file"])
        self.color_meta = role_color("info", C["dim"])

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
        # haut dans Column.__init__). Hauteur pilotee par colonne (voir
        # COLUMN_SETTINGS), mais differente selon que CETTE ligne a un
        # apercu ou non (col_row_height vs col_plain_height) : une ligne de
        # fichier ordinaire n'a pas besoin de la place reservee a une
        # vignette carree qu'elle n'affiche pas. _has_preview (pas
        # _image_pixmap) : voir sa docstring, critique pour la paresse du
        # decodage.
        title = self.column.column_title
        row_height = col_row_height(title) if self._has_preview(index) else col_plain_height(title)
        return QSize(self.column.width(), row_height + col_spacing(title))

    def paint(self, painter: QPainter, option, index):
        title = self.column.column_title
        spacing = col_spacing(title)
        image_pixmap = self._image_pixmap(index)
        if image_pixmap is not None:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            paint_thumbnail_row(
                painter, option.rect.adjusted(0, 0, 0, -spacing), image_pixmap,
                index.data(Qt.DisplayRole), index.data(ROLE_META) or "",
                bool(option.state & QStyle.State_Selected),
                bool(option.state & QStyle.State_MouseOver),
                self.column.is_active,
                self.font_image_name, self.font_image_sub,
                self.color_file, self.color_meta,
                col_img_pad(title), col_img_radius(title),
                col_sep_h(title), col_sep_v(title),
            )
            painter.restore()
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = option.rect.adjusted(0, 0, 0, -spacing)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        is_dir = bool(index.data(ROLE_ISDIR))
        active = self.column.is_active

        if selected:
            bg = C["accent"] if active else C["sel_idle"]
        elif hovered:
            bg = C["hover"]
        else:
            bg = None
        if bg:
            painter.fillRect(rect, QColor(bg))

        # Marqueur : logo logiciel (colonne "Logiciels") si reconnu, sinon
        # carre 9x9 habituel.
        mark_x = rect.left() + 10
        icon_key = None
        if is_dir and self.column.column_title == SOFTWARE_COLUMN_LABEL:
            icon_key = software_icon_key(index.data(Qt.DisplayRole) or "")

        if icon_key is not None:
            icon_size = SOFTWARE_ICON_SIZE
            icon_y = rect.center().y() - icon_size // 2
            painter.drawPixmap(mark_x, icon_y, software_icon_pixmap(icon_key, icon_size))
            mark_width = icon_size
        else:
            mark_y = rect.center().y() - 4
            if selected and active:
                border, fill = C["accent_text"], "transparent"
            elif is_dir:
                # Fond du marqueur aligne sur la couleur du texte de la
                # ligne (color_dir), pas une couleur fixe independante.
                border, fill = C["mark_dir_bd"], self.color_dir
            else:
                border, fill = C["mark_file_bd"], self.color_file
            if fill != "transparent":
                painter.fillRect(mark_x, mark_y, 9, 9, QColor(fill))
            painter.setPen(QColor(border))
            painter.drawRect(mark_x, mark_y, 8, 8)
            mark_width = 9

        # Metadonnee (taille fichier)
        meta = index.data(ROLE_META) or ""
        meta_w = 0
        if meta:
            painter.setFont(self.font_meta)
            meta_w = painter.fontMetrics().horizontalAdvance(meta) + 10
            painter.setPen(QColor(C["accent_text"] if (selected and active) else self.color_meta))
            painter.drawText(
                rect.adjusted(0, 0, -10, 0),
                Qt.AlignRight | Qt.AlignVCenter,
                meta,
            )

        # Nom
        text_x = mark_x + mark_width + 7
        text_rect = rect.adjusted(text_x - rect.left(), 0, -(10 + meta_w), 0)
        painter.setFont(self.font_dir if is_dir else self.font_file)
        if selected and active:
            painter.setPen(QColor(C["accent_text"]))
        else:
            painter.setPen(QColor(self.color_dir if is_dir else self.color_file))
        name = painter.fontMetrics().elidedText(
            index.data(Qt.DisplayRole), Qt.ElideMiddle, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, name)

        painter.restore()


def paint_thumbnail_row(
    painter: QPainter, rect, pixmap: QPixmap, name: str, meta: str,
    selected: bool, hovered: bool, active: bool, font_name, font_sub,
    name_color: str = None, sub_color: str = None,
    pad: int = 0, radius: int = 0, sep_h: bool = True, sep_v: bool = True,
):
    """Dessine une ligne « vignette carree a gauche + nom/metadonnee a
    droite » : le style de reference des cartes de projet, partage avec les
    lignes de fichier-image (voir RowDelegate) pour un rendu identique.
    `pad` (les 4 cotes) et `radius` sont regles par colonne (voir
    COLUMN_SETTINGS). `sep_h`/`sep_v` : filets separateurs entre lignes
    (horizontal) et entre vignette/texte (vertical), aussi regles par
    colonne — voir col_sep_h/col_sep_v."""
    if selected:
        bg = C["accent"] if active else C["sel_idle"]
    elif hovered:
        bg = C["hover"]
    else:
        bg = None
    if bg:
        painter.fillRect(rect, QColor(bg))

    # Vignette carree a gauche, recadree en "cover". La zone reservee reste
    # carree (largeur = hauteur de ligne) ; le padding reduit l'image
    # elle-meme, a l'identique sur les 4 cotes.
    slot_rect = rect.adjusted(0, 0, 0, 0)
    slot_rect.setWidth(rect.height())
    thumb_rect = slot_rect.adjusted(pad, pad, -pad, -pad)
    if thumb_rect.width() > 0 and thumb_rect.height() > 0:
        scaled = pixmap.scaled(thumb_rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        sx = max(0, (scaled.width() - thumb_rect.width()) // 2)
        sy = max(0, (scaled.height() - thumb_rect.height()) // 2)
        cropped = scaled.copy(sx, sy, min(thumb_rect.width(), scaled.width()), min(thumb_rect.height(), scaled.height()))
        # Fond du slot (visible sous l'image des que le padding > 0, ou que
        # l'image ne remplit pas un carre parfait) : couleur de la ligne en
        # survol/selection, sinon celle du fond DERRIERE le texte — c'est a
        # dire le fond normal de la liste (C["window"], voir QListWidget
        # dans app_style.build_stylesheet), pas la couleur du texte lui-meme
        # (confusion du premier essai) ni un C["well"] fixe deconnecte du
        # reste de la ligne.
        painter.fillRect(slot_rect, QColor(bg or C["window"]))
        # drawPixmap(rect, pixmap) plutot que drawPixmap(point, pixmap) : le
        # scaled()/copy() ci-dessus peut, par arrondi, rendre `cropped` 1px
        # plus petit que thumb_rect dans un sens — dessine au point, ce
        # manque laissait un liseret de C["well"] visible (l'image parait
        # decalee de 1px). Dessiner dans le rectangle force l'image a le
        # remplir exactement, arrondi inclus.
        if radius > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(thumb_rect), radius, radius)
            painter.save()
            # Antialiasing force ici (independamment du reglage du
            # painter appelant, souvent coupe pour un rendu pixel-perfect
            # ailleurs) : sans lui, les coins arrondis ressortaient
            # crenelés/pas lisses.
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setClipPath(path)
            painter.drawPixmap(thumb_rect, cropped)
            painter.restore()
        else:
            painter.drawPixmap(thumb_rect, cropped)
    if sep_v:
        painter.setPen(QColor(C["border"]))
        painter.drawLine(slot_rect.topRight(), slot_rect.bottomRight())
    if sep_h:
        painter.setPen(QColor(C["border"]))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
    thumb_rect = slot_rect

    # Nom + sous-titre a droite de la vignette.
    text_x = thumb_rect.right() + 11
    text_rect = rect.adjusted(text_x - rect.left(), 0, -10, 0)
    name_rect = text_rect.adjusted(0, 0, 0, -text_rect.height() // 2)
    sub_rect = text_rect.adjusted(0, text_rect.height() // 2, 0, 0)

    painter.setFont(font_name)
    painter.setPen(QColor(C["accent_text"] if (selected and active) else (name_color or C["text"])))
    elided_name = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, name_rect.width())
    painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)

    if meta:
        painter.setFont(font_sub)
        painter.setPen(QColor(C["accent_text"] if (selected and active) else (sub_color or C["dim"])))
        sub = painter.fontMetrics().elidedText(meta, Qt.ElideRight, sub_rect.width())
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter, sub)


class ProjectTileDelegate(QStyledItemDelegate):
    """Ligne avec vignette carree a gauche (comme les autres colonnes, mais
    illustree), pour la colonne « Projets ». Vignette perso si presente (voir
    project_thumbnail_path), sinon image par defaut generique."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.refresh_fonts()

    def refresh_fonts(self):
        self.font_name = role_font("folders", 12, 600, tracking=0.01)
        self.font_sub = role_font("info", 10, 400)
        self.color_name = role_color("folders", C["text"])
        self.color_sub = role_color("info", C["dim"])

    def sizeHint(self, option, index) -> QSize:
        # L'espacement est ajoute ici, retranche au dessin (voir paint) :
        # voir la remarque sur QListView.setSpacing dans Column.__init__.
        title = self.column.column_title
        return QSize(self.column.width(), col_row_height(title) + col_spacing(title))

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        path = Path(index.data(ROLE_PATH))
        title = self.column.column_title
        # project_thumbnail_pixmap (cache module-level partage, voir plus
        # haut) plutot qu'un cache prive a ce delegate : sans ca, la meme
        # vignette etait chargee et gardee en memoire deux fois (ici et pour
        # l'apercu empile de la premiere colonne), et une fois par colonne
        # "Projets"/"Sous-projet" ouverte en plus.
        paint_thumbnail_row(
            painter, option.rect.adjusted(0, 0, 0, -col_spacing(title)), project_thumbnail_pixmap(path), path.name,
            index.data(ROLE_META) or "",
            bool(option.state & QStyle.State_Selected),
            bool(option.state & QStyle.State_MouseOver),
            self.column.is_active,
            self.font_name, self.font_sub,
            self.color_name, self.color_sub,
            col_img_pad(title), col_img_radius(title),
            col_sep_h(title), col_sep_v(title),
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
PREVIEW_SEPARATOR_HEIGHT = 1   # filet sous l'image, entre deux blocs empiles (ou avant la liste "Logiciels")
PREVIEW_BLOCK_EXTRA_HEIGHT = PREVIEW_HEADER_HEIGHT + PREVIEW_SEPARATOR_HEIGHT   # tout, hors le cote carre de l'image


class _SquarePreviewImage(QLabel):
    """Image carree bord a bord (aucune marge) avec les bords de la colonne,
    de taille EXPLICITEMENT fixee (voir set_side) plutot que recalculee en
    reaction a un resizeEvent : un widget dont la taille reagit a son propre
    resizeEvent peut se faire redimensionner une seconde fois par son parent
    avant que ce premier changement soit repercute, le rendant tantot trop
    petit, tantot etire par un layout qui redistribue l'espace en trop —
    exactement le symptome observe (espaces morts, doublons visuels lors
    d'une navigation rapide). Taille fixe des le depart = aucune ambiguite.
    Le fichier d'origine sur le disque n'est jamais modifie/degrade : on ne
    fait que le redimensionner en memoire pour l'affichage."""

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
        if side > 0:
            self.setFixedSize(side, side)
        self._refresh()

    def _refresh(self):
        side = self.width()
        if side <= 0 or self._raw.isNull():
            self.clear()
            return
        # minimum=0 : voir la remarque sur col_img_pad/col_img_radius —
        # PREVIEW_IMAGE_PAD/RADIUS regles a 0 doivent le rester.
        pad = scaled(PREVIEW_IMAGE_PAD, minimum=0)
        radius = scaled(PREVIEW_IMAGE_RADIUS, minimum=0)
        inner = max(1, side - 2 * pad)
        cropped = _cover_crop_square(self._raw, inner)
        if pad <= 0 and radius <= 0:
            self.setPixmap(cropped)
            return
        # Padding (4 cotes) et/ou coins arrondis (voir "Images projets et
        # sous-projets" dans les parametres) : composee sur un canevas
        # side x side dans la couleur de fond du bloc (C["chrome"], voir
        # __init__), l'image reduite/recadree etant ensuite dessinee au
        # centre, avec un clip arrondi si besoin.
        canvas = QPixmap(side, side)
        canvas.fill(QColor(C["chrome"]))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing, True)
        if radius > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(pad, pad, inner, inner), radius, radius)
            p.setClipPath(path)
        p.drawPixmap(pad, pad, cropped)
        p.end()
        self.setPixmap(canvas)


class _StatusLabel(QLabel):
    """Un des trois indicateurs in/over/out en tete d'un _PreviewBlock : voir
    STATUS_FOLDERS/status_folder_state. Sombre et inerte si le dossier
    correspondant est vide/absent, clair et cliquable (ouvre le dossier) des
    qu'il contient quelque chose."""

    clicked = Signal()

    def __init__(self, name: str, active: bool, parent=None):
        super().__init__(name.upper(), parent)
        self._active = active
        self.setFont(role_font("info", 10, 700, tracking=0.08))
        # C["text"]/C["dim"] directement, PAS role_color("info", ...) : ce
        # role peut etre personnalise par l'utilisateur (fenetre de
        # parametres) avec une couleur fixe, qui ecraserait alors les DEUX
        # branches actif/inactif avec la meme teinte (role_color ignore le
        # `default_hex` passe des qu'une surcharge existe) — l'etat vide/
        # rempli du dossier ne doit jamais dependre de ce reglage.
        color = C["text"] if active else C["dim"]
        self.setStyleSheet(f"color: {color}; background: transparent;")
        if active:
            self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if self._active and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _PreviewBlock(QWidget):
    """Un niveau d'aperçu empile : une rangee d'indicateurs in/over/out, une
    grande barre de titre « affiche » (nom du projet/sous-projet), suivies
    directement (sans espace) de son image carree bord a bord avec la
    colonne. `width` (la largeur de contenu de la colonne au moment de la
    construction) fixe la taille de l'image des le depart — voir
    _SquarePreviewImage.set_side. `path` sert a determiner l'etat des trois
    indicateurs (voir status_folder_state) ; `open_status(folder_path)` est
    appele au clic sur un indicateur actif (voir
    PipelineBrowser._open_status_folder : ouvre son contenu dans la colonne
    suivante, pas dans l'explorateur Windows)."""

    def __init__(self, title: str, pixmap: QPixmap, width: int, path: Path, open_status, parent=None):
        super().__init__(parent)
        # Fond unique du bloc entier (indicateurs + titre + image), pas
        # seulement derriere l'image : la "grande affiche" doit se lire
        # comme un seul panneau, sans bande de couleur differente au-dessus.
        # C["chrome"] (couleur des en-tetes de colonne), pas C["well"] :
        # coherent avec les en-tetes de colonne — c'est ce fond, deja
        # present des le premier bloc, qui tient lieu de bandeau d'en-tete
        # pour la colonne (voir Column.__init__).
        # WA_StyledBackground indispensable ici : ce widget est un ENFANT
        # (dans preview_layout/preview_container/Column, eux-memes dans la
        # fenetre), pas une fenetre top-level — sans cet attribut, Qt
        # n'applique jamais le fond du style-sheet sur un simple QWidget
        # enfant (il retombe sur le fond herite de ses parents, ici
        # C["window"] via la regle globale QWidget), meme si le style-sheet
        # semble correct. Piege deja documente ailleurs dans ce fichier
        # (TitleBar, DetailPanel, PreviewColumn) — oublie ici la premiere
        # fois, d'ou le fond incoherent malgre un style-sheet "correct".
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {C['chrome']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        status_bar = QWidget()
        status_bar.setFixedHeight(PREVIEW_STATUS_HEIGHT)
        # Explicite (pas seulement l'absence de regle) : bord transparent,
        # aucun filet ne doit apparaitre entre les indicateurs et le titre.
        status_bar.setStyleSheet("background: transparent; border: none;")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(14, 0, 14, 0)
        status_layout.setSpacing(14)
        status_layout.addStretch(1)
        for name in STATUS_FOLDERS:
            active, folder_path = status_folder_state(path, name)
            label = _StatusLabel(name, active)
            if active:
                label.clicked.connect(lambda p=folder_path: open_status(p))
            status_layout.addWidget(label)
        layout.addWidget(status_bar)

        title_bar = QWidget()
        title_bar.setFixedHeight(PREVIEW_TITLE_HEIGHT)
        # Idem : aucun filet entre le titre et l'image, meme remarque que
        # status_bar ci-dessus.
        title_bar.setStyleSheet("background: transparent; border: none;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 0, 14, 8)
        name = QLabel(title)
        name.setFont(role_font("folders", 26, 700, tracking=0.0))
        name.setStyleSheet(f"color: {role_color('folders', C['text'])}; background: transparent;")
        # Colle au bas de la barre de titre (juste au-dessus de l'image),
        # pas centre sur toute sa hauteur : plus proche de l'image, plus
        # affiche.
        title_layout.addWidget(name, 0, Qt.AlignBottom | Qt.AlignLeft)
        layout.addWidget(title_bar)

        self.image = _SquarePreviewImage()
        self.image.set_source_pixmap(pixmap)
        self.image.set_side(width)
        layout.addWidget(self.image)

        # Filet de separation, sous l'image : entre deux blocs empiles (ce
        # projet puis son sous-projet), ou entre le dernier bloc et la liste
        # "Logiciels" en dessous. Widget dedie plutot qu'un "border-bottom"
        # sur l'image elle-meme (essaye, ne se rendait pas de facon fiable
        # sur ce QLabel a taille fixe — voir _SquarePreviewImage).
        separator = QWidget()
        separator.setFixedHeight(PREVIEW_SEPARATOR_HEIGHT)
        separator.setStyleSheet(f"background: {C['border']};")
        layout.addWidget(separator)

        # Sans ceci, ce widget garde une politique de taille verticale
        # "Preferred" par defaut : des qu'un parent (voir Column) lui offre
        # plus de hauteur que son contenu n'en a besoin (ex. la liste TYPE
        # capee plus haut libere de la place), Qt etire le bloc au-dela de
        # sa hauteur reelle et repartit l'exces en espaces morts AVANT,
        # ENTRE et APRES ses sous-elements — exactement le defaut visible
        # (grand vide au-dessus du titre, avant l'image).
        self.setFixedHeight(PREVIEW_BLOCK_EXTRA_HEIGHT + width)


# ==========================================================================
# Colonne
# ==========================================================================

class Column(QWidget):

    selected = Signal(object, object)   # (Column, Path | None)
    activated = Signal(object)          # Path

    def __init__(self, directory: Path, title: str, parent=None):
        super().__init__(parent)
        self.directory = directory
        self.is_active = False
        self.column_title = title
        self.has_thumbnails = title in THUMBNAIL_COLUMN_LABELS

        self.title_label = QLabel(title)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")

        self.count_label = QLabel("")
        self.count_label.setFont(role_font("info", 10, 400))
        self.count_label.setStyleSheet(f"color: {role_color('info', C['count'])}; background: transparent;")

        # objectName + selecteur ID : voir la remarque sur #TitleBar dans
        # PipelineBrowser — sans lui, title_label/count_label heriteraient du
        # border-bottom nu et se retrouveraient chacun souligne sur sa
        # largeur de texte au lieu du filet courant sur toute la colonne.
        header = QWidget()
        header.setObjectName("ColumnHeader")
        header.setFixedHeight(scaled(HEADER_HEIGHT))
        header.setStyleSheet(
            f"#ColumnHeader {{ background: {C['chrome']}; border-bottom: 1px solid {C['border']}; }}"
        )
        self.header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.count_label)

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

        # Aperçu empile (voir set_preview_stack) : uniquement peuple/visible
        # pour la colonne "Logiciels", par PipelineBrowser. Vide/masque,
        # il ne prend aucune place et la liste garde son comportement normal
        # (etiree sur toute la hauteur de la colonne).
        self.preview_container = QWidget()
        self.preview_container.setStyleSheet(f"border-bottom: 1px solid {C['border']};")
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(0)
        self.preview_container.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 1, 0)
        layout.setSpacing(0)
        # L'en-tete (titre + compteur) est place APRES l'apercu empile : tant
        # que celui-ci est vide/masque (colonnes sans apercu, ou Logiciels
        # avant selection), il ne prend aucune place et l'en-tete reste
        # visuellement tout en haut, aligne avec les autres colonnes. Des que
        # l'apercu est peuple (colonne Logiciels), l'en-tete se retrouve
        # colle juste au-dessus de la liste, sous les images, comme demande.
        # Pas de bandeau chrome separe au-dessus de l'apercu : le premier
        # bloc (voir _PreviewBlock) est deja entierement colore en chrome
        # (indicateurs + titre), en ajouter un ici ne ferait que dupliquer
        # cette hauteur et decaler tout l'apercu vers le bas des qu'une
        # vraie colonne (avec liste) remplace la colonne fantome.
        layout.addWidget(self.preview_container, 0)
        layout.addWidget(header)
        layout.addWidget(self.list, 1)
        # Espaceur de fin, initialement sans etirement (voir
        # set_preview_stack) : tant que la liste garde son facteur
        # d'etirement (pas d'apercu), il n'absorbe rien. Des que la liste est
        # plafonnee en hauteur (apercu visible), c'est LUI qui recupere tout
        # l'espace en trop en fin de colonne — sinon Qt le rend quand meme a
        # la liste malgre son plafond, en la centrant dans l'espace qui lui
        # avait ete alloue au lieu de la laisser collee en haut, sous l'en-tete.
        layout.addStretch(0)
        self._column_layout = layout

        self.setFixedWidth(col_width(title))
        self.setObjectName("Column")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#Column {{ border-right: 1px solid {C['border']}; }}")

        # Redimensionnement par glisser-deposer sur la bordure droite.
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)
        header.setMouseTracking(True)
        header.installEventFilter(self)
        self.list.viewport().installEventFilter(self)
        # La scrollbar verticale est un widget a part, positionne PAR-DESSUS
        # le bord droit du viewport des que la liste deborde : sans son
        # propre eventFilter, ses clics/mouvements ne passaient jamais par
        # _in_resize_zone, rendant la bordure de redimensionnement
        # inaccessible chaque fois qu'une scrollbar est visible.
        self.list.verticalScrollBar().installEventFilter(self)

        self.refresh()

    def set_active(self, active: bool):
        if self.is_active != active:
            self.is_active = active
            self.list.viewport().update()

    def _list_content_height(self) -> int:
        total = sum(self.list.sizeHintForRow(i) for i in range(self.list.count()))
        return total + 2

    def set_preview_stack(self, entries: list[tuple[str, QPixmap, Path, object]]):
        """Peuple (ou vide) l'aperçu empile au-dessus de la liste : `entries`
        est une liste de (titre, pixmap, chemin, open_status), un par niveau
        selectionne plus loin dans l'arborescence qui possede une vignette
        (voir PipelineBrowser.update_preview_stack ; `open_status` ouvre un
        indicateur in/over/out dans la colonne suivante, voir _PreviewBlock).
        Quand elle est vide, la liste retrouve son comportement normal
        (etiree sur toute la colonne)."""
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # takeAt() le retire du layout mais pas de l'arbre des widgets
                # enfants : sans hide()/setParent(None) immediats, il reste
                # affiche a sa derniere position (plus geree par le layout)
                # jusqu'a ce que deleteLater() s'execute, faisant apparaitre
                # un « fantome » en surimpression du bloc precedent des que
                # la selection change deux fois de suite rapidement.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        if not entries:
            self.preview_container.hide()
            self.list.setMaximumHeight(QWIDGETSIZE_MAX)
            self._column_layout.setStretch(2, 1)   # la liste (index 2) reprend tout
            self._column_layout.setStretch(3, 0)   # l'espaceur de fin (index 3) n'absorbe rien
            return

        # self.width() (fixee explicitement via setFixedWidth) plutot que
        # self.list.width() : interroge en plein milieu de la chaine de
        # signaux de selection, ce dernier peut encore renvoyer une largeur
        # perimee (le layout n'a pas fini de se reappliquer), ce qui a deja
        # produit des images bien trop grandes juste apres une selection.
        width = self.width() - 1
        for title, pixmap, path, open_status in entries:
            self.preview_layout.addWidget(_PreviewBlock(title, pixmap, width, path, open_status))
        self.preview_container.show()
        # Meme raisonnement que pour chaque bloc (voir _PreviewBlock) : sans
        # cette limite explicite, le conteneur lui-meme peut etre etire par
        # la colonne au-dela de la hauteur reelle de ses blocs.
        self.preview_container.setFixedHeight(len(entries) * (PREVIEW_BLOCK_EXTRA_HEIGHT + width))
        self.list.setMaximumHeight(self._list_content_height())
        # La liste ne doit plus reclamer sa part d'etirement (elle est
        # plafonnee) : sans ca, Qt lui laisse quand meme une grande partie de
        # la hauteur disponible (a cause du stretch=1 pose a la construction)
        # puis, ne pouvant pas depasser son maximum, la CENTRE dans cet espace
        # au lieu de la coller sous l'en-tete — l'espaceur de fin (index 3)
        # recupere desormais tout l'exces, qui reste alors sous l'apercu.
        self._column_layout.setStretch(2, 0)
        self._column_layout.setStretch(3, 1)

    def _resize_preview_images(self):
        """Redimensionne les images de l'aperçu empile (voir set_preview_stack)
        a la volee pendant un glisser de la bordure de colonne, sans
        reconstruire les blocs."""
        if not self.preview_container.isVisible():
            return
        # self.width() (fixee explicitement via setFixedWidth) plutot que
        # self.list.width() : interroge en plein milieu de la chaine de
        # signaux de selection, ce dernier peut encore renvoyer une largeur
        # perimee (le layout n'a pas fini de se reappliquer), ce qui a deja
        # produit des images bien trop grandes juste apres une selection.
        width = self.width() - 1
        count = self.preview_layout.count()
        for i in range(count):
            block = self.preview_layout.itemAt(i).widget()
            if block is not None:
                block.image.set_side(width)
                block.setFixedHeight(PREVIEW_BLOCK_EXTRA_HEIGHT + width)
        self.preview_container.setFixedHeight(count * (PREVIEW_BLOCK_EXTRA_HEIGHT + width))

    def refresh_all(self):
        """Rafraichit toutes les colonnes de la fenetre (utilise apres un
        glisser-deposer, qui peut affecter la colonne source ET la cible)."""
        win = self.window()
        if hasattr(win, "refresh_all_columns"):
            win.refresh_all_columns()
        else:
            self.refresh()

    def _in_resize_zone(self, x: int) -> bool:
        return self.width() - COLUMN_RESIZE_MARGIN <= x <= self.width()

    @property
    def is_resizing(self) -> bool:
        return self._resizing

    def resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        _show_resize_width(self, self.width())

    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self.setFixedWidth(new_width)
        self.list.doItemsLayout()
        self._resize_preview_images()
        _show_resize_width(self, new_width)

    def resize_end(self):
        self._resizing = False
        _hide_resize_width(self)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.MouseMove:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._resizing:
                self.resize_update(event.globalPosition().toPoint().x())
                return True
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

    def refresh(self):
        current = self.current_path()
        self.list.blockSignals(True)
        self.list.clear()
        # Colonnes a vignettes (Projets/Sous-projet) : in/over/out ne sont
        # jamais des lignes normales, ils deviennent des indicateurs dedies
        # dans l'apercu empile (voir _PreviewBlock/STATUS_FOLDERS).
        exclude = _STATUS_FOLDER_SET if self.has_thumbnails else None
        entries = list_entries(self.directory, exclude)
        for path in entries:
            item = QListWidgetItem(path.name)
            item.setData(ROLE_PATH, str(path))
            is_dir = path.is_dir()
            item.setData(ROLE_ISDIR, is_dir)
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
        self._fit_width_to_content()

    def relayout(self):
        """Reapplique la mise en page (tailles de ligne, ajustement de
        largeur) apres un changement de reglage purement cosmetique (police,
        hauteur de ligne, largeur de colonne...), SANS retourner sur le
        disque : le contenu deja charge (noms, tailles, vignettes) reste
        valable, seul son rendu change. Utilise par
        PipelineBrowser.refresh_all_columns(rescan=False), notamment pendant
        la previsualisation en direct de la fenetre de parametres, ou un
        column.refresh() complet (rescan du dossier, y compris le comptage
        recursif des colonnes a vignettes) serait rejoue a chaque cran de
        slider pour rien."""
        self.list.doItemsLayout()
        self._fit_width_to_content()

    def refresh_colors(self):
        """Reapplique les couleurs (voir C, mutable via app_style.set_color)
        aux qss fixes une fois pour toutes a la construction — necessaire
        car un changement de couleur depuis la fenetre de parametres ne
        retouche pas les widgets deja construits (voir la remarque sur
        set_color dans app_style.py)."""
        self.header.setStyleSheet(
            f"#ColumnHeader {{ background: {C['chrome']}; border-bottom: 1px solid {C['border']}; }}"
        )
        self.preview_container.setStyleSheet(f"border-bottom: 1px solid {C['border']};")
        self.setStyleSheet(f"#Column {{ border-right: 1px solid {C['border']}; }}")
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        self.count_label.setStyleSheet(f"color: {role_color('info', C['count'])}; background: transparent;")

    def refresh_header(self):
        """Reapplique la hauteur/police de l'entete (voir HEADER_HEIGHT, role
        'colhead') — reglable en direct depuis Parametres > General."""
        self.header.setFixedHeight(scaled(HEADER_HEIGHT))
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.count_label.setFont(role_font("info", 10, 400))

    def _fit_width_to_content(self):
        """Elargit automatiquement la colonne si son contenu (nom le plus
        long, metadonnee) ne rentre pas dans la largeur actuelle. Ne retrecit
        jamais une colonne deja assez large (y compris redimensionnee a la
        main par l'utilisateur)."""
        needed = self._content_min_width()
        if needed > self.width():
            self.setFixedWidth(min(COLUMN_MAX_WIDTH, needed))
            self.list.doItemsLayout()

    def _content_min_width(self) -> int:
        if self.list.count() == 0:
            return 0
        if self.has_thumbnails:
            fm_name = QFontMetrics(role_font("folders", 12, 600, tracking=0.01))
            fm_sub = QFontMetrics(role_font("info", 10, 400))
            max_w = 0
            for i in range(self.list.count()):
                item = self.list.item(i)
                name_w = fm_name.horizontalAdvance(item.data(Qt.DisplayRole))
                sub_w = fm_sub.horizontalAdvance(item.data(ROLE_META) or "")
                max_w = max(max_w, name_w, sub_w)
            return scaled(PROJECT_ROW_HEIGHT) + scaled(21) + max_w

        fm_name_dir = QFontMetrics(role_font("folders", 12, 600, tracking=0.12))
        fm_name_file = QFontMetrics(role_font("files", 12, 400, tracking=0.12))
        fm_meta = QFontMetrics(role_font("info", 11, 400))
        fm_image_name = QFontMetrics(role_font("files", 12, 600, tracking=0.01))
        fm_image_sub = QFontMetrics(role_font("info", 10, 400))
        max_w = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            is_dir = bool(item.data(ROLE_ISDIR))
            name = item.data(Qt.DisplayRole)
            meta = item.data(ROLE_META) or ""
            is_image_row = (
                not is_dir
                and SHOW_FILE_IMAGE_PREVIEWS
                and Path(name).suffix.lower() in PREVIEWABLE_EXTENSIONS
            )
            if is_image_row:
                # Meme formule que les cartes de projet (vignette carree a
                # gauche, calee sur la hauteur de ligne, + nom/meta a droite).
                row_w = scaled(FILE_PREVIEW_ROW_HEIGHT) + scaled(21) + max(
                    fm_image_name.horizontalAdvance(name),
                    fm_image_sub.horizontalAdvance(meta),
                )
            else:
                name_w = (fm_name_dir if is_dir else fm_name_file).horizontalAdvance(name)
                meta_w = (fm_meta.horizontalAdvance(meta) + 10) if meta else 0
                has_icon = (
                    is_dir
                    and self.column_title == SOFTWARE_COLUMN_LABEL
                    and software_icon_key(name) is not None
                )
                mark_w = SOFTWARE_ICON_SIZE if has_icon else 9
                row_w = 27 + mark_w + name_w + meta_w
            max_w = max(max_w, row_w)
        return max_w

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
        if self.has_thumbnails and item.data(ROLE_ISDIR):
            menu.addSeparator()
            act_change_thumb = menu.addAction("Changer l'image...")
            act_capture_thumb = menu.addAction("Capturer une zone d'ecran...")
            if project_thumbnail_path(path).is_file():
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


class PreviewColumn(QWidget):
    """Colonne "fantome" affichee a la position de la colonne suivante,
    juste apres une colonne a vignettes (Projets/Sous-projet) qui n'a pas
    encore de selection : elle n'a pas de contenu de dossier propre, juste
    l'apercu empile courant (voir PipelineBrowser.update_preview_stack),
    pour que l'image du projet/sous-projet choisi soit visible des sa
    selection, sans attendre le niveau suivant. Remplacee par la vraie
    colonne (Column) des qu'une selection plus loin l'ouvre pour de bon.

    Pas d'en-tete "Logiciels" ici : ce titre n'a de sens qu'une fois la
    colonne Logiciels reellement ouverte (avec sa liste) — tant que seul le
    projet (ou le sous-projet) est selectionne, seule l'image doit
    apparaitre."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.column_title = title
        self.has_thumbnails = False

        self.preview_layout = QVBoxLayout()
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 1, 0)
        layout.setSpacing(0)
        layout.addLayout(self.preview_layout)
        layout.addStretch(1)

        # Cette colonne fantome occupe la place de "Logiciels" : sa largeur
        # suit donc le meme reglage.
        self.setFixedWidth(col_width("Logiciels"))
        # objectName distinct de celui des vraies colonnes (voir Column) :
        # le fond, propre a ce fantome (le vide sous les images empilees, non
        # couvert par une liste), doit rester specifique a lui — le partager
        # avec "#Column" l'aurait aussi impose aux vraies colonnes.
        self.setObjectName("PreviewColumn")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#PreviewColumn {{ background: {C['void']}; border-right: 1px solid {C['border']}; }}"
        )

    def refresh_colors(self):
        self.setStyleSheet(
            f"#PreviewColumn {{ background: {C['void']}; border-right: 1px solid {C['border']}; }}"
        )

    def set_preview_stack(self, entries: list[tuple[str, QPixmap, Path, object]]):
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        width = self.width() - 1
        for title, pixmap, path, open_status in entries:
            self.preview_layout.addWidget(_PreviewBlock(title, pixmap, width, path, open_status))


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
        # dans PipelineBrowser) : un "border-left" nu se propagerait a tous
        # les QLabel enfants (kind/size/modified/path), qui se retrouveraient
        # chacun entoure d'un cadre au lieu du simple filet separant le
        # panneau du reste de la fenetre.
        self.setObjectName("DetailPanel")
        # Voir la meme remarque dans TitleBar : sans cet attribut, une
        # sous-classe de QWidget comme celle-ci ne peint pas son propre
        # style — le fond et la bordure ci-dessous restaient ignores,
        # laissant voir la couleur du widget en dessous (d'ou le "mauvais"
        # fond signale ici).
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#DetailPanel {{ background: {C['detail_bg']}; border-left: 1px solid {C['border']}; }}")
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
        # border-left ici aussi : cet en-tete est un enfant qui couvre toute
        # la largeur du panneau, donc SON fond recouvre le filet de gauche
        # peint par #DetailPanel sur ce segment — sans ce rappel, la ligne de
        # separation avec le reste de la fenetre serait coupee sur la
        # hauteur de l'en-tete.
        header = QWidget()
        header.setObjectName("DetailHeader")
        header.setFixedHeight(scaled(HEADER_HEIGHT))
        header.setStyleSheet(
            f"#DetailHeader {{ background: {C['chrome']}; border-bottom: 1px solid {C['border']};"
            f" border-left: 1px solid {C['border']}; }}"
        )
        self.header = header
        self.header_title = QLabel("Inspecteur")
        self.header_title.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.header_title.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        self.badge = QLabel("")
        self.badge.setFont(role_font("info", 9, 600, tracking=0.6, caps=True))
        self.badge.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.header_title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.badge)

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
        content.setContentsMargins(16, 14, 16, 14)
        content.setSpacing(8)
        content.addWidget(self.name)
        content.addWidget(self.well)
        content.addWidget(self.text_preview)
        content.addWidget(self.video_widget)
        content.addLayout(grid)
        content.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addLayout(content, 1)
        self.clear()

    # -- redimensionnement par glisser-deposer sur la bordure gauche,
    # comme n'importe quelle colonne (voir Column.resize_begin/update/end) --

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(
                DETAIL_PANEL_MIN_WIDTH,
                min(DETAIL_PANEL_MAX_WIDTH, self._resize_start_width - delta),
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
        PipelineBrowser.reload() apres un changement de reglages."""
        self.header.setFixedHeight(scaled(HEADER_HEIGHT))
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
        """Reapplique les couleurs fixees a la construction (voir la remarque
        sur refresh_colors dans Column) apres un changement de couleur."""
        self.setStyleSheet(f"#DetailPanel {{ background: {C['detail_bg']}; border-left: 1px solid {C['border']}; }}")
        self.header.setStyleSheet(
            f"#DetailHeader {{ background: {C['chrome']}; border-bottom: 1px solid {C['border']};"
            f" border-left: 1px solid {C['border']}; }}"
        )
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

        self.btn_min = self._make_button("─", window.showMinimized)
        self.btn_max = self._make_button("□", self._toggle_max)
        self.btn_close = self._make_button("×", window.close)
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

    def _make_button(self, glyph: str, slot) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))
        btn.setCursor(Qt.ArrowCursor)
        btn.setFlat(True)
        btn.setFont(font(11, 400, mono=True))
        btn.setStyleSheet(
            "QPushButton {"
            f"  background: transparent; border: none; color: {C['label']};"
            "}"
            "QPushButton:hover {"
            f"  background: {C['hover']}; color: {C['text']};"
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
        self.preview_placeholder: PreviewColumn | None = None
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
        self.btn_settings = QPushButton("⚙")
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
            btn.setFixedHeight(scaled(24))
            btn.setCursor(Qt.ArrowCursor)
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
        self.columns_layout.setSpacing(0)

        self.detail = DetailPanel()

        # objectName + selecteur ID : le fond au-dela de la derniere colonne
        # (l'espace que la colonne Inspecteur, desormais a largeur fixe, ne
        # comble plus) doit avoir le meme ton sombre "de vide" que dans la
        # maquette html plutot que la couleur generale des colonnes.
        columns_host = QWidget()
        self.columns_host = columns_host
        columns_host.setObjectName("ColumnsHost")
        columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['void']}; }}")
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
        decoration systeme (voir __init__) : sans cadre natif, Windows ne
        sait plus quel bord/coin est survole pour proposer les curseurs et
        le glisser de redimensionnement habituels. On repond nous-memes au
        message WM_NCHITTEST plutot que de reimplementer ce glisser a la
        main — Windows/Qt gerent ensuite le reste (curseur, aimantation,
        contraintes de taille) normalement, comme pour une fenetre a cadre
        classique."""
        if sys.platform == "win32" and eventType == b"windows_generic_MSG" and not self.isMaximized():
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    import ctypes
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value - self.frameGeometry().x()
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value - self.frameGeometry().y()
                    w, h, b = self.width(), self.height(), self._RESIZE_BORDER
                    left, right = x < b, x > w - b
                    top, bottom = y < b, y > h - b
                    hit = None
                    if top and left: hit = 13       # HTTOPLEFT
                    elif top and right: hit = 14    # HTTOPRIGHT
                    elif bottom and left: hit = 16  # HTBOTTOMLEFT
                    elif bottom and right: hit = 17 # HTBOTTOMRIGHT
                    elif left: hit = 10             # HTLEFT
                    elif right: hit = 11            # HTRIGHT
                    elif top: hit = 12              # HTTOP
                    elif bottom: hit = 15           # HTBOTTOM
                    if hit is not None:
                        return True, hit
            except Exception:
                pass
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
        self.add_column(root, 0)
        self.path_label.setText(str(root))
        self.synced_label.setText(datetime.now().strftime("scan %H:%M:%S"))
        self.update_preview_stack()

    def _clear_preview_placeholder(self):
        if self.preview_placeholder is not None:
            self.columns_layout.removeWidget(self.preview_placeholder)
            self.preview_placeholder.setParent(None)
            self.preview_placeholder.deleteLater()
            self.preview_placeholder = None

    def add_column(self, directory: Path, depth: int, title: str | None = None):
        # `title` : impose un intitule (voir _open_status_folder, qui ouvre
        # un dossier in/over/out sans rapport avec ce que la profondeur
        # suggererait normalement — pas question d'afficher "SOUS-PROJET" au
        # dessus du contenu de "in"). None (cas normal) : intitule deduit de
        # la profondeur, comme avant.
        if title is None:
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        column = Column(directory, title)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
        self.columns.append(column)
        # Une colonne fantome (voir PreviewColumn) peut occuper cet
        # emplacement depuis la selection precedente : la retirer avant
        # d'ajouter la vraie colonne, sinon celle-ci se retrouverait ajoutee
        # APRES elle dans columns_layout (ordre visuel casse).
        self._clear_preview_placeholder()
        self.columns_layout.addWidget(column)
        self.update_active_column()
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()

    def refresh_all_columns(self, rescan: bool = True):
        """Reapplique aux colonnes existantes (largeur, delegate, polices)
        les reglages globaux courants, SANS reconstruire l'arborescence : la
        navigation en cours (profondeur, selection) reste intacte. Utilise
        par le glisser-deposer (rescan=True : le contenu du dossier a change
        sur le disque), et par la previsualisation en direct des parametres
        (voir _apply_settings, rescan=False : aucun reglage cosmetique
        (police, largeur, hauteur de ligne...) ne change le contenu d'un
        dossier — retourner sur le disque, y compris le comptage recursif
        des colonnes a vignettes, a chaque cran de slider n'apporterait
        rien et coute cher sur un partage reseau)."""
        for column in self.columns:
            column.setFixedWidth(col_width(column.column_title))
            column.refresh_header()
            column.list.setUniformItemSizes(column.has_thumbnails)
            delegate = column.list.itemDelegate()
            if hasattr(delegate, "refresh_fonts"):
                delegate.refresh_fonts()
            if rescan:
                column.refresh()
            else:
                column.relayout()
            column.list.doItemsLayout()
        if self.preview_placeholder is not None:
            self.preview_placeholder.setFixedWidth(col_width("Logiciels"))
        self.update_preview_stack()

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        for i, column in enumerate(self.columns):
            column.set_active(i == last_selected)

    def update_preview_stack(self):
        """Recalcule l'aperçu empile : un bloc (titre + image) par colonne a
        vignettes (Projets, Sous-projet) actuellement selectionnee, dans
        l'ordre de navigation.

        L'apercu n'apparait JAMAIS ailleurs que dans la colonne "Logiciels" :
        si elle existe deja (vraie colonne), l'apercu s'y pose directement,
        au-dessus de sa liste ; sinon (Sous-projet vient d'etre ouverte mais
        pas encore selectionnee, donc "Logiciels" n'existe pas pour de bon)
        une colonne fantome a sa place (voir PreviewColumn) le porte a la
        place, pour que l'image apparaisse des la selection du projet/
        sous-projet sans attendre. Toute autre colonne (Contenu compris) est
        systematiquement videe de son apercu."""
        self._clear_preview_placeholder()
        if not self.columns:
            return
        entries: list[tuple[str, QPixmap, Path, object]] = []
        for index, column in enumerate(self.columns):
            if not column.has_thumbnails:
                continue
            path = column.current_path()
            if path is None:
                continue
            open_status = lambda p, idx=index: self._open_status_folder(idx, p)
            entries.append((path.name, project_thumbnail_pixmap(path), path, open_status))

        target = next((c for c in self.columns if c.column_title == "Logiciels"), None)
        for column in self.columns:
            if column is not target:
                column.set_preview_stack([])

        if target is not None:
            target.set_preview_stack(entries)
            return

        if not entries or not self.columns[-1].has_thumbnails:
            return
        depth = len(self.columns)
        title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        if title != "Logiciels":
            return
        self.preview_placeholder = PreviewColumn(title)
        self.columns_layout.addWidget(self.preview_placeholder)
        self.preview_placeholder.set_preview_stack(entries)
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _open_status_folder(self, column_index: int, path: Path) -> None:
        """Ouvre le contenu d'un indicateur in/over/out (voir
        STATUS_FOLDERS/_PreviewBlock) dans une colonne suivante — navigation
        normale dans l'appli, pas l'explorateur Windows. `column_index` :
        position, dans self.columns, de la colonne Projets/Sous-projet dont
        ce bloc represente la selection (fixee au moment de la construction
        de l'apercu, voir update_preview_stack).

        Ne coupe JAMAIS la colonne "Logiciels" quand elle existe deja
        (l'apercu empile — images de Projets/Sous-projet — et la liste des
        softs y sont montes) : seul ce qui vient APRES elle (une precedente
        navigation dans un dossier de statut, par exemple) est remplace. Si
        "Logiciels" n'existe pas encore (colonne fantome seulement, voir
        PreviewColumn), rien a preserver : on coupe alors juste apres la
        colonne Projets/Sous-projet elle-meme, comme avant."""
        target = next((c for c in self.columns if c.column_title == "Logiciels"), None)
        insert_index = self.columns.index(target) if target is not None else column_index
        self.prune_after(insert_index)
        self.add_column(path, insert_index + 1, title=path.name.upper())
        self.update_active_column()
        self.update_preview_stack()

    def on_selected(self, column: Column, path: Path | None):
        index = self.columns.index(column)
        self.prune_after(index)
        if path is None:
            self.detail.clear()
            self.update_active_column()
            self.update_preview_stack()
            return
        self.path_label.setText(str(path))
        self.detail.show_path(path)
        if path.is_dir():
            depth = index + 1
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
            # Colonne "Logiciels" : liste le sous-dossier "softs" du
            # sous-projet, pas le sous-projet lui-meme (voir _softs_subdir).
            child_dir = _softs_subdir(path) if title == SOFTWARE_COLUMN_LABEL else path
            self.add_column(child_dir, depth)
        self.update_active_column()
        self.update_preview_stack()

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
        apply_all_settings(settings)
        if settings["root_path"] != self.root_field.text():
            self.root_field.setText(settings["root_path"])
            self.reload()
        else:
            self.refresh_all_columns(rescan=False)
        # app.setStyleSheet (dans refresh_colors -> refresh_style) repolit
        # TOUS les widgets de TOUTES les fenetres de l'appli — le poste le
        # plus cher, et de loin, de tout ce rafraichissement. Un slider qui
        # ne touche ni aux couleurs ni au rayon des boutons (largeur de
        # colonne, echelle, hauteur d'entete...) n'a aucune raison de le
        # declencher a chaque cran : seule une vraie difference sur ces deux
        # points force la reconstruction complete de la feuille de style.
        style_key = (json.dumps(settings.get("colors", {}), sort_keys=True), settings.get("button_radius"))
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
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.synced_label.setFont(role_font("info2", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        for column in self.columns:
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
        a utiliser quand on sait que ni les couleurs ni le rayon des
        boutons n'ont bouge (voir _apply_settings), le reste de cette
        methode restant assez leger pour tourner a chaque rafraichissement."""
        if rebuild_stylesheet:
            app = QApplication.instance()
            if app is not None:
                refresh_style(app)
        self.central.setStyleSheet(
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {WINDOW_RADIUS}px; }}"
        )
        self.columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['void']}; }}")
        self.titlebar.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        self.topbar.setStyleSheet(f"#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['border']}; }}")
        self.statusbar.setStyleSheet(f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}")
        for column in self.columns:
            column.refresh_colors()
        if self.preview_placeholder is not None:
            self.preview_placeholder.refresh_colors()
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
    global WINDOW_RADIUS, BUTTON_RADIUS, HEADER_HEIGHT
    global PREVIEW_IMAGE_PAD, PREVIEW_IMAGE_RADIUS

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
        if "sep_h" in conf:
            COLUMN_SETTINGS[title]["sep_h"] = conf["sep_h"]
        if "sep_v" in conf:
            COLUMN_SETTINGS[title]["sep_v"] = conf["sep_v"]
    # "Sous-projet" peut suivre les valeurs de "Projets" (voir les toggles
    # de liaison dans la fenetre de parametres) : resolu ici, une fois pour
    # toutes, plutot qu'a chaque ligne dessinee.
    sous = settings.get("columns", {}).get("Sous-projet", {})
    if sous.get("img_pad_link", True):
        COLUMN_SETTINGS["Sous-projet"]["img_pad"] = COLUMN_SETTINGS["Projets"]["img_pad"]
    if sous.get("img_radius_link", True):
        COLUMN_SETTINGS["Sous-projet"]["img_radius"] = COLUMN_SETTINGS["Projets"]["img_radius"]

    PREVIEW_IMAGE_PAD = settings.get("preview_pad", 0)
    PREVIEW_IMAGE_RADIUS = settings.get("preview_radius", 0)

    HEADER_HEIGHT = settings.get("header_height", HEADER_HEIGHT)
    WINDOW_RADIUS = settings.get("window_radius", WINDOW_RADIUS)
    BUTTON_RADIUS = settings.get("button_radius", BUTTON_RADIUS)
    set_button_radius(BUTTON_RADIUS)
    set_ui_scale(settings.get("ui_scale", 100))

    for key, hexval in (settings.get("colors") or {}).items():
        set_color(key, hexval)

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
