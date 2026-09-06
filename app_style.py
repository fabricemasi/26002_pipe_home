#!/usr/bin/env python3
"""
Style partage pour toutes les applications PySide6 du pipeline.

Contient les tokens de design (couleurs, polices) et la feuille de style Qt
(QSS) commune, de maniere a ce que chaque application ait le meme look sans
dupliquer le CSS. Une application l'utilise ainsi :

    from app_style import C, STYLESHEET, font
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    ...
    label.setFont(font(12, 600))

Ou, plus court :

    from app_style import apply_style
    app = QApplication(sys.argv)
    apply_style(app)
"""

from PySide6.QtGui import QFont, QFontDatabase

# ==========================================================================
# Design tokens (maquette Claude Design)
# ==========================================================================

C = {
    "app_bg":        "#101214",
    "window":        "#1a1c1e",
    "chrome":        "#202326",
    "topbar":        "#212427",
    "well":          "#141618",
    "detail_bg":     "#17191b",
    "border":        "#2c3034",
    "border_soft":   "#303539",
    "sel_idle":      "#2e3338",
    "hover":         "#232729",
    "accent":        "#3f6f9f",
    "accent_text":   "#eef2f5",
    "btn":           "#282c30",
    "btn_border":    "#383d42",
    "btn_hover":     "#31363b",
    "btn_hover_bd":  "#454b50",
    "text":          "#d6d9dc",
    "text_file":     "#b3babf",
    "text_mono":     "#b9bfc4",
    "header":        "#9aa1a7",
    "label":         "#7d858b",
    "dim":           "#5f666b",
    "count":         "#5c6368",
    "mark_dir_bd":   "#6c757b",
    "mark_dir_fill": "#3b4045",
    "mark_file_bd":  "#454b50",
    "scroll":        "#35393d",
    "scroll_hover":  "#464b50",
}

# ==========================================================================
# Polices
# ==========================================================================

_SANS = None
_MONO = None
_NAME = None


def sans_family() -> str:
    global _SANS
    if _SANS is None:
        families = set(QFontDatabase.families())
        for candidate in ("Nunito", "IBM Plex Sans", "Inter", "Segoe UI", "Noto Sans"):
            if candidate in families:
                _SANS = candidate
                break
        else:
            _SANS = "Sans Serif"
    return _SANS


def mono_family() -> str:
    global _MONO
    if _MONO is None:
        families = set(QFontDatabase.families())
        for candidate in ("IBM Plex Mono", "Consolas", "DejaVu Sans Mono", "Courier New"):
            if candidate in families:
                _MONO = candidate
                break
        else:
            _MONO = "Monospace"
    return _MONO


def name_family() -> str:
    """Police dediee aux noms de dossiers/fichiers dans les navigateurs du
    pipeline (distincte de la police generale de l'interface : boutons,
    en-tetes, etc. restent sur sans_family())."""
    global _NAME
    if _NAME is None:
        families = set(QFontDatabase.families())
        for candidate in ("Rubik", "Nunito", "IBM Plex Sans", "Inter", "Segoe UI", "Noto Sans"):
            if candidate in families:
                _NAME = candidate
                break
        else:
            _NAME = "Sans Serif"
    return _NAME


SMOOTHING_CHOICES = ("current", "previous", "none")
SMOOTHING_LABELS = {
    "current": "Lissage actuel",
    "previous": "Lissage precedent",
    "none": "Pas de lissage",
}


def font(size: int, weight: int = 400, mono: bool = False,
         tracking: float = 0.0, caps: bool = False, family: str | None = None,
         smoothing: str = "current") -> QFont:
    if family is None:
        family = mono_family() if mono else sans_family()
    f = QFont(family)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    # En dessous d'environ 18-20px, le moteur de rendu de police de Windows
    # bascule sur un anti-aliasing tres grossier (quelques niveaux de gris
    # seulement) des que le hinting est actif, donnant un texte crenele —
    # visible sur toute l'interface puisque la plupart du texte de l'appli
    # est en 10-12px. "current" desactive le hinting pour forcer un lissage
    # complet et coherent quelle que soit la taille (le comportement par
    # defaut de l'appli) ; "previous" restaure le hinting natif de Qt/Windows
    # (comportement d'avant ce correctif, plus crenele en petite taille) ;
    # "none" desactive completement l'anti-aliasing (texte brut, sans lissage).
    if smoothing == "previous":
        f.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    elif smoothing == "none":
        f.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    else:
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    if caps:
        f.setCapitalization(QFont.AllUppercase)
    return f


# ==========================================================================
# Polices par role, personnalisables par l'utilisateur (fenetre Parametres) :
# fichiers, dossiers, informations diverses (compteurs, chemins...), boutons,
# et une police "ensemble de l'appli" qui sert de repli pour les roles non
# surcharges individuellement. Une surcharge vide (family="") revient au
# comportement automatique (name_family/mono_family/sans_family).
# ==========================================================================

ROLE_BASE_KIND = {
    "files": "name",
    "folders": "name",
    "info": "mono",
    "buttons": "sans",
}

_ROLE_DEFAULTS = {"family": "", "size": 12, "bold": False, "smoothing": "current", "color": ""}

_ROLE_OVERRIDES: dict[str, dict] = {
    role: dict(_ROLE_DEFAULTS) for role in ("app", "files", "folders", "info", "buttons")
}


def set_role_font(role: str, family: str, size: int, bold: bool,
                   smoothing: str = "current", color: str = "") -> None:
    """Enregistre la surcharge typographique d'un role : 'app', 'files',
    'folders', 'info' ou 'buttons'. `family` vide revient a l'auto-detection
    pour la police/taille/gras. `smoothing` ('current'/'previous'/'none')
    et `color` (code hex, ou vide pour la couleur par defaut) s'appliquent
    independamment, meme si `family` est vide."""
    _ROLE_OVERRIDES[role] = {
        "family": family, "size": size, "bold": bold,
        "smoothing": smoothing if smoothing in SMOOTHING_CHOICES else "current",
        "color": color,
    }


def _base_family_for(role: str) -> str:
    kind = ROLE_BASE_KIND.get(role, "sans")
    if kind == "mono":
        return mono_family()
    if kind == "name":
        return name_family()
    return sans_family()


def role_font(role: str, default_size: int, default_weight: int = 400,
              tracking: float = 0.0, caps: bool = False) -> QFont:
    """Police pour un `role` donne, en tenant compte d'une eventuelle
    surcharge utilisateur pour ce role, puis de la surcharge globale 'app',
    puis de l'auto-detection habituelle si rien n'est personnalise. Le
    lissage suit la surcharge du role (ou 'current' par defaut)."""
    role_ov = _ROLE_OVERRIDES.get(role) or {}
    app_ov = _ROLE_OVERRIDES.get("app") or {}
    source = role_ov if role_ov.get("family") else (app_ov if app_ov.get("family") else None)
    smoothing = role_ov.get("smoothing") or "current"
    if source:
        return font(
            source["size"], 700 if source["bold"] else 400,
            tracking=tracking, caps=caps, family=source["family"], smoothing=smoothing,
        )
    return font(default_size, default_weight, tracking=tracking, caps=caps,
                family=_base_family_for(role), smoothing=smoothing)


def role_color(role: str, default_hex: str) -> str:
    """Couleur de texte pour un `role` donne : surcharge du role, puis
    surcharge globale 'app', puis `default_hex` si rien n'est personnalise."""
    role_ov = _ROLE_OVERRIDES.get(role) or {}
    app_ov = _ROLE_OVERRIDES.get("app") or {}
    return role_ov.get("color") or app_ov.get("color") or default_hex


# ==========================================================================
# Feuille de style Qt (QSS) commune
# ==========================================================================

STYLESHEET = f"""
QWidget {{ background: {C['window']}; color: {C['text']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {C['window']}; }}
QListWidget {{ background: {C['window']}; border: none; outline: none; }}

QLineEdit {{
    background: {C['well']};
    border: 1px solid {C['border_soft']};
    color: {C['text_mono']};
    padding: 0 8px;
    selection-background-color: {C['accent']};
}}

QPushButton {{
    background: {C['btn']};
    border: 1px solid {C['btn_border']};
    color: #c4cacf;
    padding: 0 12px;
}}
QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}
QPushButton:pressed {{
    background: {C['accent']};
    border-color: {C['accent']};
    color: {C['accent_text']};
}}

QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; width: 9px; height: 9px; margin: 0; }}
QScrollBar::handle {{ background: {C['scroll']}; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {C['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {C['chrome']}; border: 1px solid {C['border']}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 18px; color: {C['text']}; }}
QMenu::item:selected {{ background: {C['accent']}; color: {C['accent_text']}; }}
"""


def apply_style(app) -> None:
    """Applique le style commun (style Fusion + QSS) a une QApplication."""
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
