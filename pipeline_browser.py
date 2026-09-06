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

import json
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

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QDrag,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
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

from app_style import C, apply_style, font, role_color, role_font, set_role_font
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

# Libelle (singulier, minuscule) affiche au-dessus de chaque aperçu empile
# dans la premiere colonne (voir Column.set_preview_stack) pour un titre de
# colonne a vignettes donne.
PREVIEW_KIND_LABELS = {"Projets": "projet", "Sous-projet": "sous-projet"}

# Logos de logiciel (colonne "Logiciels") : badge colore genere a la volee
# (pas de fichier image) par defaut, identifie par le nom du dossier (HOUDINI,
# MAYA...). Peut etre remplace par une image perso via le clic droit ; cette
# icone perso est alors globale au logiciel (pas au projet), stockee a cote
# du script puisqu'elle ne depend pas de la racine du pipeline consultee.
SOFTWARE_COLUMN_LABEL = "Logiciels"
SOFTWARE_ICON_SIZE = 16
CUSTOM_SOFTWARE_ICON_DIR = Path(__file__).resolve().parent / ".pipeline_software_icons"
CUSTOM_SOFTWARE_ICON_MAX_DIM = 128

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


def file_image_pixmap(path: Path) -> QPixmap | None:
    """Image brute du fichier `path` lui-meme (pas une vignette perso a
    choisir : c'est le fichier), mise en cache par date de modification. Le
    recadrage carre se fait au dessin (voir paint_thumbnail_row), a la
    taille reelle de la ligne — pas ici, pour rester correct si la hauteur de
    ligne change (reglage utilisateur). None si le fichier n'est plus
    lisible ou n'est pas une image valide."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    cached = _file_image_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    _file_image_cache[key] = (mtime, pix)
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


# ==========================================================================
# Scan disque
# ==========================================================================

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return ""


def list_entries(directory: Path) -> list[Path]:
    """Dossiers puis fichiers, tries. Les FLATTEN_FOLDERS sont traverses."""
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
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


def project_thumbnail_path(directory: Path) -> Path:
    """Emplacement de la vignette perso d'un dossier de projet (fichier
    cache, jamais liste par list_entries puisqu'il commence par un point)."""
    return directory / THUMBNAIL_FILENAME


_project_thumbnail_cache: dict[str, tuple[float | None, QPixmap]] = {}


def project_thumbnail_pixmap(path: Path) -> QPixmap:
    """Vignette perso de `path` (voir project_thumbnail_path), ou image par
    defaut generique si aucune n'a ete choisie. Mise en cache par date de
    modification (meme logique que ProjectTileDelegate._pixmap_for, mais
    partagee ici pour l'aperçu empile de la premiere colonne)."""
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
    _project_thumbnail_cache[key] = (mtime, pix)
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

    def _image_pixmap(self, index) -> QPixmap | None:
        if not SHOW_FILE_IMAGE_PREVIEWS or bool(index.data(ROLE_ISDIR)):
            return None
        path_str = index.data(ROLE_PATH)
        if not path_str or Path(path_str).suffix.lower() not in IMAGE_EXTENSIONS:
            return None
        return file_image_pixmap(Path(path_str))

    def sizeHint(self, option, index) -> QSize:
        # ROW_SPACING est ajoute a la hauteur ici, puis retranche au dessin
        # (voir paint) : c'est ce reste, non peint, qui forme l'espace exact
        # entre deux lignes (voir la remarque sur QListView.setSpacing plus
        # haut dans Column.__init__).
        if self._image_pixmap(index) is not None:
            return QSize(self.column.width(), FILE_PREVIEW_ROW_HEIGHT + ROW_SPACING)
        return QSize(COLUMN_WIDTH, ROW_HEIGHT + ROW_SPACING)

    def paint(self, painter: QPainter, option, index):
        image_pixmap = self._image_pixmap(index)
        if image_pixmap is not None:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            paint_thumbnail_row(
                painter, option.rect.adjusted(0, 0, 0, -ROW_SPACING), image_pixmap,
                index.data(Qt.DisplayRole), index.data(ROLE_META) or "",
                bool(option.state & QStyle.State_Selected),
                bool(option.state & QStyle.State_MouseOver),
                self.column.is_active,
                self.font_image_name, self.font_image_sub,
                self.color_file, self.color_meta,
            )
            painter.restore()
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = option.rect.adjusted(0, 0, 0, -ROW_SPACING)
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
                border, fill = C["mark_dir_bd"], C["mark_dir_fill"]
            else:
                border, fill = C["mark_file_bd"], "transparent"
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
):
    """Dessine une ligne « vignette carree a gauche + nom/metadonnee a
    droite » : le style de reference des cartes de projet, partage avec les
    lignes de fichier-image (voir RowDelegate) pour un rendu identique."""
    if selected:
        bg = C["accent"] if active else C["sel_idle"]
    elif hovered:
        bg = C["hover"]
    else:
        bg = None
    if bg:
        painter.fillRect(rect, QColor(bg))

    # Vignette carree a gauche, recadree en "cover".
    thumb_rect = rect.adjusted(0, 0, 0, 0)
    thumb_rect.setWidth(rect.height())
    scaled = pixmap.scaled(thumb_rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    sx = max(0, (scaled.width() - thumb_rect.width()) // 2)
    sy = max(0, (scaled.height() - thumb_rect.height()) // 2)
    cropped = scaled.copy(sx, sy, min(thumb_rect.width(), scaled.width()), min(thumb_rect.height(), scaled.height()))
    painter.fillRect(thumb_rect, QColor(C["well"]))
    painter.drawPixmap(thumb_rect.topLeft(), cropped)
    painter.setPen(QColor(C["border"]))
    painter.drawLine(thumb_rect.topRight(), thumb_rect.bottomRight())

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
        self._cache: dict[str, tuple[float | None, QPixmap]] = {}

    def refresh_fonts(self):
        self.font_name = role_font("folders", 12, 600, tracking=0.01)
        self.font_sub = role_font("info", 10, 400)
        self.color_name = role_color("folders", C["text"])
        self.color_sub = role_color("info", C["dim"])

    def sizeHint(self, option, index) -> QSize:
        # ROW_SPACING ajoute ici, retranche au dessin (voir paint) : voir la
        # remarque sur QListView.setSpacing dans Column.__init__.
        return QSize(self.column.width(), PROJECT_ROW_HEIGHT + ROW_SPACING)

    def _pixmap_for(self, path: Path) -> QPixmap:
        thumb = project_thumbnail_path(path)
        try:
            mtime = thumb.stat().st_mtime if thumb.is_file() else None
        except OSError:
            mtime = None
        key = str(path)
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        pix = QPixmap(str(thumb)) if mtime is not None else QPixmap()
        if pix.isNull():
            pix = default_thumbnail()
        self._cache[key] = (mtime, pix)
        return pix

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        path = Path(index.data(ROLE_PATH))
        paint_thumbnail_row(
            painter, option.rect.adjusted(0, 0, 0, -ROW_SPACING), self._pixmap_for(path), path.name,
            index.data(ROLE_META) or "",
            bool(option.state & QStyle.State_Selected),
            bool(option.state & QStyle.State_MouseOver),
            self.column.is_active,
            self.font_name, self.font_sub,
            self.color_name, self.color_sub,
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

class _SquarePreviewImage(QLabel):
    """Image carree qui suit la largeur disponible (colonne redimensionnable),
    recadree en « cover » depuis l'image source. Le fichier d'origine sur le
    disque n'est jamais modifie/degrade : on ne fait que le redimensionner en
    memoire pour l'affichage, a chaque changement de largeur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw = QPixmap()
        self.setStyleSheet(f"background: {C['well']}; border: 1px solid {C['border']};")

    def set_source_pixmap(self, pixmap: QPixmap):
        self._raw = pixmap
        self._refresh()

    def resizeEvent(self, event):
        width = self.width()
        if width > 0 and self.height() != width:
            self.setFixedHeight(width)
        self._refresh()
        super().resizeEvent(event)

    def _refresh(self):
        side = self.width()
        if side <= 0 or self._raw.isNull():
            self.clear()
            return
        self.setPixmap(_cover_crop_square(self._raw, side))


class _PreviewBlock(QWidget):
    """Un niveau d'aperçu empile : libelle ("projet" / "sous-projet"), nom,
    puis image carree."""

    def __init__(self, kind_label: str, title: str, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        kind = QLabel(kind_label)
        kind.setFont(role_font("info", 10, 400))
        kind.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")

        name = QLabel(title)
        name.setFont(role_font("folders", 13, 700))
        name.setStyleSheet(f"color: {role_color('folders', C['text'])}; background: transparent;")
        name.setWordWrap(True)

        self.image = _SquarePreviewImage()
        self.image.set_source_pixmap(pixmap)

        layout.addWidget(kind)
        layout.addWidget(name)
        layout.addSpacing(6)
        layout.addWidget(self.image)


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
        self.title_label.setFont(role_font("app", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('app', C['header'])}; background: transparent;")

        self.count_label = QLabel("")
        self.count_label.setFont(role_font("info", 10, 400))
        self.count_label.setStyleSheet(f"color: {role_color('info', C['count'])}; background: transparent;")

        header = QWidget()
        header.setFixedHeight(HEADER_HEIGHT)
        header.setStyleSheet(
            f"background: {C['chrome']}; border-bottom: 1px solid {C['border']};"
        )
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
        # pour la toute premiere colonne, par PipelineBrowser. Vide/masque,
        # il ne prend aucune place et la liste garde son comportement normal
        # (etiree sur toute la hauteur de la colonne).
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(14, 16, 14, 16)
        self.preview_layout.setSpacing(18)
        self.preview_container.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 1, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.preview_container, 0)

        self.setFixedWidth(COLUMN_WIDTH)
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

        self.refresh()

    def set_active(self, active: bool):
        if self.is_active != active:
            self.is_active = active
            self.list.viewport().update()

    def _list_content_height(self) -> int:
        total = sum(self.list.sizeHintForRow(i) for i in range(self.list.count()))
        return total + 2

    def set_preview_stack(self, entries: list[tuple[str, str, QPixmap]]):
        """Peuple (ou vide) l'aperçu empile sous la liste : `entries` est une
        liste de (libelle, titre, pixmap), un par niveau selectionne plus
        loin dans l'arborescence qui possede une vignette (voir
        PipelineBrowser.update_preview_stack). Quand elle est vide, la liste
        retrouve son comportement normal (etiree sur toute la colonne)."""
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not entries:
            self.preview_container.hide()
            self.list.setMaximumHeight(QWIDGETSIZE_MAX)
            return

        for kind_label, title, pixmap in entries:
            self.preview_layout.addWidget(_PreviewBlock(kind_label, title, pixmap))
        self.preview_container.show()
        self.list.setMaximumHeight(self._list_content_height())

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

    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self.setFixedWidth(new_width)
        self.list.doItemsLayout()

    def resize_end(self):
        self._resizing = False

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
        entries = list_entries(self.directory)
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
                count = len(list_entries(path))
                meta = f"{count} element{'s' if count != 1 else ''}"
            item.setData(ROLE_META, meta)
            self.list.addItem(item)
            if current and path == current:
                self.list.setCurrentItem(item)
        self.count_label.setText(str(len(entries)))
        self.list.blockSignals(False)
        self._fit_width_to_content()

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
            return PROJECT_ROW_HEIGHT + 21 + max_w

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
                and Path(name).suffix.lower() in IMAGE_EXTENSIONS
            )
            if is_image_row:
                # Meme formule que les cartes de projet (vignette carree a
                # gauche, calee sur la hauteur de ligne, + nom/meta a droite).
                row_w = FILE_PREVIEW_ROW_HEIGHT + 21 + max(
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
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Icone", f"Impossible de creer le dossier de configuration :\n{exc}")
            return
        if not pix.save(str(dest), "PNG"):
            QMessageBox.warning(self, "Icone", "Impossible d'enregistrer l'icone.")
            return
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


# ==========================================================================
# Panneau de details
# ==========================================================================

class DetailPanel(QWidget):

    FIELDS = ["kind", "size", "modified", "path"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {C['detail_bg']};")
        self.setMinimumWidth(260)

        # Colonne juste a gauche (la derniere) : permet de la redimensionner
        # en attrapant la bordure depuis ce cote-ci aussi, puisqu'elle n'a
        # pas d'autre colonne voisine pour agrandir la zone de prise.
        self.left_column = None
        self.setMouseTracking(True)

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(self.name)
        layout.addWidget(self.well)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.clear()

    # -- prolonge la poignee de redimensionnement de la derniere colonne --

    def mouseMoveEvent(self, event):
        col = self.left_column
        if col is None:
            return super().mouseMoveEvent(event)
        x = event.position().toPoint().x()
        if col.is_resizing:
            col.resize_update(event.globalPosition().toPoint().x())
            return
        if x <= COLUMN_RESIZE_MARGIN:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        col = self.left_column
        x = event.position().toPoint().x()
        if col is not None and event.button() == Qt.LeftButton and x <= COLUMN_RESIZE_MARGIN:
            col.resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        col = self.left_column
        if col is not None and col.is_resizing:
            col.resize_end()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        col = self.left_column
        if col is None or not col.is_resizing:
            self.unsetCursor()
        super().leaveEvent(event)

    def clear(self):
        self.name.setText("")
        self.well.hide()
        self._preview_pixmap = None
        self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
        self.well_label.clear()
        for value in self.values.values():
            value.setText("")

    def refresh_fonts(self, is_dir: bool = True):
        """Reapplique les polices de role (voir role_font) : necessaire car
        ce panneau, contrairement aux colonnes, n'est pas reconstruit par
        PipelineBrowser.reload() apres un changement de reglages."""
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        for key_label in self.key_labels.values():
            key_label.setFont(role_font("info", 11, 400))
            key_label.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        for value in self.values.values():
            value.setFont(role_font("info", 11, 400))
            value.setStyleSheet(f"color: {role_color('info', '#aab1b6')}; background: transparent;")

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

    def show_path(self, path: Path):
        self.name.setText(path.name)
        is_dir = path.is_dir()
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self.well.show()
        self._preview_pixmap = None
        if not path.is_dir() and path.suffix.lower() in IMAGE_EXTENSIONS:
            pix = QPixmap(str(path))
            if not pix.isNull():
                self._preview_pixmap = pix
        self._update_preview()
        try:
            info = path.stat()
            modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            info, modified = None, "-"
        if path.is_dir():
            kind = "Dossier"
            size = f"{len(list_entries(path))} elements"
        else:
            kind = (path.suffix[1:].upper() + " file") if path.suffix else "Fichier"
            size = human_size(info.st_size) if info else "-"
        self.values["kind"].setText(kind)
        self.values["size"].setText(size)
        self.values["modified"].setText(modified)
        self.values["path"].setText(str(path))


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
# Fenetre principale
# ==========================================================================

class PipelineBrowser(QMainWindow):

    def __init__(self, root: Path):
        super().__init__()
        self.setWindowTitle("Pipeline Browser")
        self.resize(1280, 620)
        self.columns: list[Column] = []

        # --- barre du haut ---
        self.root_label = QLabel("Root")
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")

        self.root_field = QLineEdit(str(root))
        self.root_field.setFont(role_font("info", 12, 400))
        self.root_field.setFixedHeight(24)
        self.root_field.returnPressed.connect(self.reload)

        self.btn_browse = QPushButton("Parcourir")
        self.btn_reload = QPushButton("Refresh")
        self.btn_settings = QPushButton("⚙")
        for btn in (self.btn_browse, self.btn_reload, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
            btn.setFixedHeight(24)
            btn.setCursor(Qt.ArrowCursor)
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.setFixedWidth(28)
        self.btn_settings.setToolTip("Parametres")
        self.btn_browse.clicked.connect(self.browse_root)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_settings.clicked.connect(self.open_settings)

        self.synced_label = QLabel("")
        self.synced_label.setFont(role_font("info", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")

        topbar = QWidget()
        topbar.setFixedHeight(TOPBAR_HEIGHT)
        topbar.setStyleSheet(
            f"background: {C['topbar']}; border-bottom: 1px solid {C['border']};"
        )
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(10, 0, 10, 0)
        top_layout.setSpacing(10)
        top_layout.addWidget(self.root_label)
        top_layout.addWidget(self.root_field, 1)
        top_layout.addWidget(self.btn_browse)
        top_layout.addWidget(self.btn_reload)
        top_layout.addWidget(self.synced_label)
        top_layout.addWidget(self.btn_settings)

        # --- zone des colonnes ---
        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(0)

        self.detail = DetailPanel()

        columns_host = QWidget()
        host_layout = QHBoxLayout(columns_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addLayout(self.columns_layout)
        host_layout.addWidget(self.detail, 1)

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
        self.status_right.setFont(role_font("info", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")

        statusbar = QWidget()
        statusbar.setFixedHeight(STATUS_HEIGHT)
        statusbar.setStyleSheet(
            f"background: {C['chrome']}; border-top: 1px solid {C['border']};"
        )
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(12)
        status_layout.addWidget(self.path_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.status_right)

        central = QWidget()
        central.setStyleSheet(f"background: {C['window']};")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(topbar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(statusbar)
        self.setCentralWidget(central)

        self.addAction(QAction(self, shortcut="F5", triggered=self.reload))
        self.reload()

        self._restore_window_state()

    def _restore_window_state(self):
        """Reapplique la position/taille de fenetre et le dossier parcouru
        au moment de la derniere fermeture (voir closeEvent)."""
        state = load_window_state()
        geometry_b64 = state.get("geometry")
        if geometry_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode("ascii")))
            except (ValueError, TypeError):
                pass
        last_path = state.get("last_path")
        if last_path:
            self._navigate_to(Path(last_path))

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

    def add_column(self, directory: Path, depth: int):
        title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        column = Column(directory, title)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
        self.columns.append(column)
        self.columns_layout.addWidget(column)
        self.detail.left_column = column
        self.update_active_column()
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()
        self.detail.left_column = self.columns[-1] if self.columns else None

    def refresh_all_columns(self):
        """Reapplique aux colonnes existantes (largeur, delegate, polices)
        les reglages globaux courants, SANS reconstruire l'arborescence : la
        navigation en cours (profondeur, selection) reste intacte. Utilise
        par le glisser-deposer, et par la previsualisation en direct des
        parametres (voir _apply_settings)."""
        for column in self.columns:
            column.setFixedWidth(COLUMN_WIDTH)
            column.list.setUniformItemSizes(column.has_thumbnails)
            delegate = column.list.itemDelegate()
            if hasattr(delegate, "refresh_fonts"):
                delegate.refresh_fonts()
            column.refresh()
            column.list.doItemsLayout()
        self.update_preview_stack()

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        for i, column in enumerate(self.columns):
            column.set_active(i == last_selected)

    def update_preview_stack(self):
        """Recalcule l'aperçu empile de la premiere colonne (voir
        Column.set_preview_stack) : un bloc (libelle + titre + image) par
        colonne a vignettes (Projets, Sous-projet) actuellement selectionnee,
        dans l'ordre de navigation."""
        if not self.columns:
            return
        entries: list[tuple[str, str, QPixmap]] = []
        for column in self.columns:
            if not column.has_thumbnails:
                continue
            path = column.current_path()
            if path is None:
                continue
            kind_label = PREVIEW_KIND_LABELS.get(column.column_title, column.column_title.lower())
            entries.append((kind_label, path.name, project_thumbnail_pixmap(path)))
        self.columns[0].set_preview_stack(entries)

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
            self.add_column(path, index + 1)
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
        global COLUMN_WIDTH, PROJECT_ROW_HEIGHT, ROW_SPACING, THUMBNAIL_MAX_DIM
        global CUSTOM_SOFTWARE_ICON_MAX_DIM, SHOW_FILE_IMAGE_PREVIEWS, FILE_PREVIEW_ROW_HEIGHT
        COLUMN_WIDTH = settings["column_width"]
        PROJECT_ROW_HEIGHT = settings["project_row_height"]
        ROW_SPACING = settings["row_spacing"]
        THUMBNAIL_MAX_DIM = settings["thumbnail_max_dim"]
        CUSTOM_SOFTWARE_ICON_MAX_DIM = settings["software_icon_max_dim"]
        SHOW_FILE_IMAGE_PREVIEWS = settings["show_file_image_previews"]
        FILE_PREVIEW_ROW_HEIGHT = settings["file_preview_size"]
        _apply_font_settings(settings)
        if settings["root_path"] != self.root_field.text():
            self.root_field.setText(settings["root_path"])
            self.reload()
        else:
            self.refresh_all_columns()
        self.refresh_chrome_fonts()

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.root_field.setFont(role_font("info", 12, 400))
        for btn in (self.btn_browse, self.btn_reload, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.synced_label.setFont(role_font("info", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right.setFont(role_font("info", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        is_dir = True
        if self.columns:
            selected = self.columns[-1].current_path()
            if selected is not None:
                is_dir = selected.is_dir()
        self.detail.refresh_fonts(is_dir)


def _apply_font_settings(settings: dict):
    """Enregistre (voir app_style.set_role_font) les surcharges de police
    pour chacun des 5 roles reglables depuis la fenetre de parametres."""
    for role, key in (
        ("files", "font_files"),
        ("folders", "font_folders"),
        ("info", "font_info"),
        ("buttons", "font_buttons"),
        ("app", "font_app"),
    ):
        conf = settings.get(key) or {}
        set_role_font(
            role, conf.get("family", ""), conf.get("size", 12), conf.get("bold", False),
            conf.get("smoothing", "current"), conf.get("color", ""),
        )


def main():
    global COLUMN_WIDTH, PROJECT_ROW_HEIGHT, ROW_SPACING, THUMBNAIL_MAX_DIM
    global CUSTOM_SOFTWARE_ICON_MAX_DIM, SHOW_FILE_IMAGE_PREVIEWS, FILE_PREVIEW_ROW_HEIGHT

    settings = load_settings()
    COLUMN_WIDTH = settings["column_width"]
    PROJECT_ROW_HEIGHT = settings["project_row_height"]
    ROW_SPACING = settings["row_spacing"]
    THUMBNAIL_MAX_DIM = settings["thumbnail_max_dim"]
    CUSTOM_SOFTWARE_ICON_MAX_DIM = settings["software_icon_max_dim"]
    SHOW_FILE_IMAGE_PREVIEWS = settings["show_file_image_previews"]
    FILE_PREVIEW_ROW_HEIGHT = settings["file_preview_size"]
    _apply_font_settings(settings)
    root = Path(settings["root_path"]) if settings["remember_last_root"] else ROOT

    app = QApplication(sys.argv)
    apply_style(app)
    window = PipelineBrowser(root)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
