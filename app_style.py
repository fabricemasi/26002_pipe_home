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


def font(size: int, weight: int = 400, mono: bool = False,
         tracking: float = 0.0, caps: bool = False) -> QFont:
    f = QFont(mono_family() if mono else sans_family())
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    if caps:
        f.setCapitalization(QFont.AllUppercase)
    return f


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
