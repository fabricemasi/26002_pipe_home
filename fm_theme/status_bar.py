"""Barre d'état (fm_theme, section « Barre d'état », 2026-11-05) : hauteur, fond, bordure haute, marges, espacement
et deux textes (chemin à gauche, infos à droite), clés `statusbar_*`. Tout hôte qui a une barre d'état l'habille avec
`apply_status_bar` ; rien n'est refait quand rien n'a changé (`set_qss`, comparaison des valeurs posées).
Aucun import de l'appli.
"""
from __future__ import annotations

from PySide6.QtGui import QFont

from .style import C, _resolve_font_family, font, resolve_color_ref, role_font, scaled, set_qss

ROLES = {"path": "info", "info": "info2"}         # texte -> role de police de repli (police vide)


def text_font(settings: dict, prefix: str, role: str, size_default: int = 11) -> QFont:
    """Police d'un gabarit `<prefix>_font_*` : famille choisie, sinon celle du role (comme le titre de la barre de
    navigation)."""
    size = max(6, int(settings.get(f"{prefix}_font_size", size_default) or size_default))
    weight = 700 if settings.get(f"{prefix}_font_bold") else 400
    italic = bool(settings.get(f"{prefix}_font_italic", False))
    family = settings.get(f"{prefix}_font_family") or ""
    if family:
        return font(size, weight, family=_resolve_font_family(family, size, weight), italic=italic)
    # Famille vide : celle du role, mais la taille et le gras de la ligne (un role personnalise imposerait les siens).
    return font(size, weight, family=role_font(role, size, weight).family(), italic=italic)


def apply_status_bar(bar, texts: dict, settings: dict) -> None:
    """Habille `bar` (objectName posé par l'hôte) et ses textes {"path": QLabel, "info": QLabel}."""
    height = scaled(max(12, int(settings.get("statusbar_height", 24) or 24)))
    if bar.height() != height or bar.minimumHeight() != height:
        bar.setFixedHeight(height)
    bg = resolve_color_ref(settings.get("statusbar_bg_color"), C["chrome"])
    top = 0
    if settings.get("statusbar_top_enabled", True):
        top = max(0, int(settings.get("statusbar_top_thickness", 1) or 0))
    line = resolve_color_ref(settings.get("statusbar_top_color"), C["border"])
    name = bar.objectName() or "StatusBar"
    set_qss(bar, f"#{name} {{ background: {bg}; border-top: {top}px solid {line}; }}")
    layout = bar.layout()
    if layout is not None:
        pad = scaled(max(0, int(settings.get("statusbar_padding_x", 10) or 0)), 0)
        if layout.contentsMargins().left() != pad or layout.contentsMargins().right() != pad:
            layout.setContentsMargins(pad, 0, pad, 0)
        spacing = scaled(max(0, int(settings.get("statusbar_spacing", 12) or 0)), 0)
        if layout.spacing() != spacing:
            layout.setSpacing(spacing)
    for key, label in texts.items():
        if label is None:
            continue
        prefix = f"statusbar_{key}"
        new_font = text_font(settings, prefix, ROLES.get(key, "info"))
        if label.font() != new_font:
            label.setFont(new_font)
        color = resolve_color_ref(settings.get(f"{prefix}_font_color"), C["text_mono"] if key == "path" else C["dim"])
        set_qss(label, f"color: {color}; background: transparent;")
