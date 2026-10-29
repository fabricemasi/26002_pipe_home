"""Icônes des logiciels et de l’interface.

Carte et pièges : docs/agents/apercus.md.
"""

from pathlib import Path
from PySide6.QtGui import QPixmap
from app_style import custom_softwares, removed_softwares
from config import CUSTOM_SOFTWARE_ICON_DIR
from . import mtime as _mtime
from . import pixmaps as _pixmaps

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

UI_ICON_SETTINGS_STYLE = "ui_settings_style"

UI_ICON_APP_LOGO = "ui_app_logo"

UI_ICON_NAVBAR_MIN = "ui_navbar_min"

UI_ICON_NAVBAR_MAX = "ui_navbar_max"

UI_ICON_NAVBAR_CLOSE = "ui_navbar_close"

UI_ICON_NAVBAR_BROWSE = "ui_navbar_browse"       # parcourir (choix de la racine)

UI_ICON_NAVBAR_PRESETS = "ui_navbar_presets"     # gerer les presets

UI_ICON_NAVBAR_CRUMB_SEPARATOR = "ui_navbar_crumb_separator"   # separateur du cheminement (mode « icone »)

UI_ICON_NAVBAR_VIEWER = "ui_navbar_viewer"             # entrer dans la visionneuse

UI_ICON_NAVBAR_TEXT_EDITOR = "ui_navbar_text_editor"   # ouvrir l'editeur Markdown / code (paquet mdeditor/)

UI_ICON_NAVBAR_BOARD = "ui_navbar_board"   # ouvrir le board (.mro) selectionne

UI_ICON_COLLAPSE_TOGGLE = "ui_collapse_toggle"

UI_ICON_SHORTCUT = "ui_shortcut"

# Icones de la VISIONNEUSE (Reglages > Visionneuse > Icones) : boutons de la rangee du haut et attributs des
# diapositives. Absente = le glyphe peint par defaut.
UI_ICON_VIEWER_HIDE = "ui_viewer_hide"            # masquer les colonnes

UI_ICON_VIEWER_SHOW = "ui_viewer_show"            # reafficher les colonnes

UI_ICON_VIEWER_GALLERY = "ui_viewer_gallery"      # ouvrir la planche

UI_ICON_VIEWER_SINGLE = "ui_viewer_single"        # revenir a l'image en cours

UI_ICON_VIEWER_FILTER = "ui_viewer_filter"        # filtres de la planche

UI_ICON_VIEWER_STAR_ON = "ui_viewer_star_on"      # etoile de la note allumee

UI_ICON_VIEWER_STAR_OFF = "ui_viewer_star_off"    # etoile vide

UI_ICON_VIEWER_FLAG_KEEP = "ui_viewer_flag_keep"  # drapeau « marquee »

UI_ICON_VIEWER_FLAG_DELETE = "ui_viewer_flag_delete"  # drapeau « rejetee »

UI_ICON_VIEWER_PLUS = "ui_viewer_plus"            # « + » des mots cles

UI_ICON_VIEWER_RECURSIVE = "ui_viewer_recursive"  # « Recursif » : photos des sous-dossiers

VIEWER_BUTTON_ICONS = {"fade_columns": UI_ICON_VIEWER_HIDE, "show_columns": UI_ICON_VIEWER_SHOW,
                       "gallery": UI_ICON_VIEWER_GALLERY, "single_image": UI_ICON_VIEWER_SINGLE,
                       "filter": UI_ICON_VIEWER_FILTER, "recursive": UI_ICON_VIEWER_RECURSIVE}

VIEWER_ICON_KEYS = (UI_ICON_VIEWER_HIDE, UI_ICON_VIEWER_SHOW, UI_ICON_VIEWER_GALLERY, UI_ICON_VIEWER_SINGLE,
                    UI_ICON_VIEWER_FILTER, UI_ICON_VIEWER_STAR_ON, UI_ICON_VIEWER_STAR_OFF,
                    UI_ICON_VIEWER_FLAG_KEEP, UI_ICON_VIEWER_FLAG_DELETE, UI_ICON_VIEWER_PLUS,
                    UI_ICON_VIEWER_RECURSIVE)

_UI_ICON_CACHE: dict[tuple[str, int], tuple[float, QPixmap]] = {}

def custom_ui_icon_pixmap(key: str, size: int) -> QPixmap | None:
    """Pixmap perso pour une icone d'INTERFACE (voir les UI_ICON_* ci-
    dessus) si l'utilisateur en a choisi une (Settings > ICONES >
    General), sinon None — l'appelant garde alors son rendu par defaut
    actuel (glyphe peint/chevrons/fichier fourni). MEME invalidation par
    mtime que software_icon_pixmap : pas de purge explicite necessaire au
    moment de l'enregistrement depuis la fenetre de parametres."""
    path = custom_software_icon_path(key)
    mtime = _mtime.cached_mtime(path)
    if mtime is None:
        return None
    cache_key = (key, size)
    cached = _UI_ICON_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    loaded = QPixmap(str(path))
    if loaded.isNull():
        return None
    pix = _pixmaps._contain_square(loaded, size)
    _UI_ICON_CACHE[cache_key] = (mtime, pix)
    return pix

_FALLBACK_SOFTWARE_BADGE_PALETTE = [
    ("#5c6bc0", "#eef0ff"), ("#26a69a", "#e8fff9"), ("#8d6e63", "#fff3e6"),
    ("#7e57c2", "#f2ecff"), ("#42a5f5", "#e8f4ff"), ("#66bb6a", "#eafff0"),
    ("#ec407a", "#ffe9f1"), ("#ffa726", "#3a2200"),
]
