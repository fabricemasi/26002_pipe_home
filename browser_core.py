import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from PySide6.QtCore import (
    QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)
from app_style import (
    C,
    COLUMN_TYPE_OVERRIDE_KEYS,
    INSPECTOR_TITLE,
    PREVIEW_STACK_TITLE,
    custom_softwares,
    set_custom_softwares,
    set_removed_softwares,
    font,
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
    resolve_color_ref,
    set_general_column_style,
    set_column_style,
    column_style_for,
    ITEM_FONT_ROLE_LABELS,
)
import ui_state
from config import (
    FLATTEN_FOLDERS,
    HIDDEN_PREFIXES,
    ICONS_DIR,
    SOFTWARE_COLUMN_LABEL,
    THUMBNAIL_FILENAME,
    THUMBNAIL_MAX_DIM,
)
from previews import (
    SOFTWARE_ICONS,
    UI_ICON_FILE_DEFAULT,
    UI_ICON_FOLDER_DEFAULT,
    UI_ICON_PIN_ACTIVE,
    UI_ICON_PIN_INACTIVE,
    _FALLBACK_SOFTWARE_BADGE_PALETTE,
    _bounded_cache_set,
    _clear_hidden,
    _contain_square,
    _set_hidden,
    _smooth_scale_down,
    _software_icon_cache,
    custom_software_icon_path,
    custom_ui_icon_pixmap,
)
from config import (
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
)
from settings_store import (
    _coerce_side_enabled,
    _load_presets,
    _save_presets,
    _sync_slider_style,
    load_settings,
    save_settings,
)
from settings_widgets import (
    _paint_bordered_rect,
    _radius_any,
    _radius_dict,
    _rounded_rect_path,
)

if TYPE_CHECKING:
    from column import Column


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

# Dependances optionnelles (voir requirements.txt) : import protege pour
# qu'une install sans ces paquets perde juste les apercus concernes, sans
# empecher l'appli de demarrer. numpy sert au rasteriseur des .obj
# (voir _rasterize_obj_numpy) ET, avec OpenEXR, au decodage des .exr (voir
# _decode_exr_image) — verifie separement, un .obj lisse ne doit pas
# dependre de la presence d'OpenEXR.
try:
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

try:
    _OPENEXR_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _OPENEXR_AVAILABLE = False

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

TOPBAR_HEIGHT = 40

STATUS_HEIGHT = 24

TITLEBAR_HEIGHT = 28

DETAIL_PANEL_MIN_WIDTH = 220

DETAIL_PANEL_MAX_WIDTH = 520

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
                if entry.is_dir() and _is_globally_omitted_dir(entry.name):
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
                    if entry.is_dir() and _is_globally_omitted_dir(entry.name):
                        continue
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
                    if _is_globally_omitted_dir(entry.name):
                        continue
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
                    if _is_globally_omitted_dir(entry.name):
                        continue
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
    return resolve_color_ref(ui_state.STEP_BADGE_STYLE["colors"][key])

def _step_badge_text_color(n: int | str) -> str:
    """Couleur du TEXTE du badge — une PAR base (2 a 6, PAS une seule
    globale) — voir STEP_BADGE_STYLE["text_colors"], Settings > Colonnes >
    Projets > Colonnes > "Icone de niveaux", carre du HAUT de chaque paire
    — voir la remarque de l'utilisateur, "la couleur du haut est pour le
    texte (pour chacune des bases) et la couleur du bas est pour le
    fond". MEME bornage/MEME resolution/MEME cas "N" que _step_badge_color."""
    key = "N" if n == "N" else max(2, min(6, n))
    return resolve_color_ref(ui_state.STEP_BADGE_STYLE["text_colors"][key])

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
    width = ui_state.STEP_BADGE_STYLE["width"]
    height = ui_state.STEP_BADGE_STYLE["height"]
    offset_x = ui_state.STEP_BADGE_STYLE["offset_x"]
    offset_y = ui_state.STEP_BADGE_STYLE["offset_y"]
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
    s = ui_state.RESIZE_BADGE_STYLE
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
    position = ui_state.RESIZE_BADGE_STYLE.get("position", "bottom_right")
    offset_x = int(ui_state.RESIZE_BADGE_STYLE.get("offset_x", 8))
    offset_y = int(ui_state.RESIZE_BADGE_STYLE.get("offset_y", 8))
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
    family = (ui_state.SHORTCUT_TEXT_STYLE.get("font_family") or "").strip()
    size = max(1, int(ui_state.SHORTCUT_TEXT_STYLE.get("font_size") or 11))
    resolved_family = _resolve_font_family(family, size, 400)
    weight = 600 if ui_state.SHORTCUT_TEXT_STYLE.get("font_bold") else 400
    italic = bool(ui_state.SHORTCUT_TEXT_STYLE.get("font_italic", False))
    smoothing = (
        ui_state.SHORTCUT_TEXT_STYLE.get("font_smoothing", "current")
        if ui_state.SHORTCUT_TEXT_STYLE.get("font_smoothing_enabled") else "current")
    row_font = font(size, weight=weight, family=resolved_family, smoothing=smoothing, italic=italic)
    row_color = resolve_color_ref(ui_state.SHORTCUT_TEXT_STYLE.get("color") or C["text"])
    return row_font, row_color

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

    omit_names = settings.get("application_omit_file_names") or []
    omit_dirs = settings.get("application_omit_dir_names") or []
    omit_extensions = settings.get("application_omit_extensions") or []
    if isinstance(omit_names, str):
        omit_names = omit_names.replace(";", ",").split(",")
    if isinstance(omit_dirs, str):
        omit_dirs = omit_dirs.replace(";", ",").split(",")
    if isinstance(omit_extensions, str):
        omit_extensions = omit_extensions.replace(";", ",").split(",")
    legacy_extensions = [part for value in omit_extensions
                         for part in str(value).replace(",", " ").replace(";", " ").split()]
    GLOBAL_OMIT_DIR_NAMES.clear()
    GLOBAL_OMIT_DIR_NAMES.update({
        str(value).strip().casefold() for value in omit_dirs if str(value).strip()
    })
    GLOBAL_OMIT_FILE_NAMES.clear()
    GLOBAL_OMIT_FILE_NAMES.update({
        str(value).strip().casefold()
        for value in omit_names
        if str(value).strip() and not str(value).strip().startswith("*.")
    })
    GLOBAL_OMIT_FILE_EXTENSIONS.clear()
    GLOBAL_OMIT_FILE_EXTENSIONS.update({
        str(value).strip().casefold().removeprefix("*.").lstrip(".")
        for value in [*legacy_extensions, *(name for name in omit_names if str(name).strip().startswith("*."))]
        if str(value).strip().lstrip("*.")
    })

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
    ui_state.STEP_BADGE_STYLE = {
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

    ui_state.COLLAPSE_TOGGLE_MODE = settings.get("collapse_toggle_mode", "chevrons")

    # Raccourcis (voir ROLE_IS_SHORTCUT, Settings > RACCOURCI) — General >
    # RACCOURCI > "Police".
    ui_state.SHORTCUT_TEXT_STYLE = {
        "font_family": settings.get("shortcut_font_family", ""),
        "font_bold": bool(settings.get("shortcut_font_bold", False)),
        "font_italic": bool(settings.get("shortcut_font_italic", False)),
        "color": settings.get("shortcut_color", "#8fb4d5"),
        "font_size": int(settings.get("shortcut_font_size", 11)),
        "font_smoothing_enabled": bool(settings.get("shortcut_font_smoothing_enabled", False)),
        "font_smoothing": settings.get("shortcut_font_smoothing", "current"),
    }
    ui_state.DETAIL_PANEL_WIDTH = int(settings.get("detail_panel_width", 300))

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

    ui_state.RESIZE_BADGE_STYLE = {
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
    ui_state.PREVIEW_IMAGE_PAD = settings.get("preview_padding") or {}
    ui_state.PREVIEW_IMAGE_RADIUS = settings.get("preview_radius") or {}

    ui_state.HEADER_HEIGHT = settings.get("header_height", ui_state.HEADER_HEIGHT)
    ui_state.HEADER_PADDING = settings.get("header_padding", ui_state.HEADER_PADDING)
    ui_state.WINDOW_RADIUS = settings.get("window_radius", ui_state.WINDOW_RADIUS)
    ui_state.BUTTON_RADIUS = settings.get("button_radius", ui_state.BUTTON_RADIUS)
    set_button_radius(ui_state.BUTTON_RADIUS)
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
