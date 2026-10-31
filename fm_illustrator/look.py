"""Réglages APPLIQUÉS du module Illustrator (SANS Qt) : `LOOK` (clés `board_ill_*` sans préfixe), posé par
`apply_settings` (appelé par `BoardPane.apply_settings` à chaque réglage `board_` ; vrai si quelque chose a changé),
puis recopié dans les modules déjà chargés (`push`) : ils lisent leurs constantes à chaque usage (couleur de
sélection, tailles des poignées et des points, distance d'aimantation, flèches, fidélité du crayon, DPI du PDF).
Aucun travail si rien n'a changé (chemin rapide des réglages)."""
from __future__ import annotations

import sys

from .settings_defaults import ILL_DEFAULTS

PREFIX = "board_ill_"
LOOK: dict = {}


def apply_settings(settings: dict | None) -> bool:
    get = (settings or {}).get
    look = {}
    for key, default in ILL_DEFAULTS.items():
        value = get(key, default)
        if type(value) is not type(default) and not (isinstance(default, int) and isinstance(value, float)
                                                     and not isinstance(default, bool)):
            value = default
        if isinstance(value, str) and value.startswith("@"):         # couleur de l'appli (« @skinN2 ») : résolue
            try:
                from app_style import resolve_color_ref
                value = resolve_color_ref(value)
            except Exception:                                       # noqa: BLE001 - référence inconnue : défaut
                value = default
        look[key[len(PREFIX):]] = value
    if look["units"] not in ("pt", "mm", "px"):
        look["units"] = "pt"
    if look == LOOK:
        return False
    LOOK.clear()
    LOOK.update(look)
    push()
    return True


def value(name: str):
    if not LOOK:
        apply_settings(None)
    return LOOK[name]


def push():
    """Recopie dans les modules CHARGÉS (les autres liront `LOOK` à leur import, via `push` du contrôleur)."""
    if not LOOK:
        apply_settings(None)
        return
    mods = sys.modules
    model = mods.get("fm_illustrator.model")
    if model is not None:
        model.ACCENT = LOOK["accent"] or model.ACCENT
    tools = mods.get("fm_illustrator.tools")
    if tools is not None:
        tools.HANDLE_PX = LOOK["handle_size"] / 2.0
        tools.ANCHOR_PX = float(LOOK["anchor_size"])
    overlay = mods.get("fm_illustrator.overlay")
    if overlay is not None:
        overlay.ANCHOR_SIDE = float(LOOK["anchor_size"])
        overlay.GUIDE_COLOR = LOOK["guide_color"]
    xform = mods.get("fm_illustrator.tools_xform")
    if xform is not None:
        xform.SNAP_PX = float(LOOK["snap_px"])
    controller = mods.get("fm_illustrator.controller")
    if controller is not None:
        controller.NUDGE = float(LOOK["nudge"])
        controller.NUDGE_BIG = float(LOOK["nudge_big"])
    draw = mods.get("fm_illustrator.tools_draw")
    if draw is not None:
        draw.PencilTool.FIDELITY_PX = LOOK["pencil_fidelity"] / 10.0
    pdf = mods.get("fm_illustrator.pdf")
    if pdf is not None:
        pdf.DPI = int(LOOK["pdf_dpi"])


UNIT_FACTORS = {"pt": 96.0 / 72.0, "mm": 96.0 / 25.4, "px": 1.0}      # unités du board par unité affichée


def to_display(units_value: float) -> str:
    """Longueur du board -> texte dans l'unité affichée (« 1,5 pt », « 0,53 mm »…)."""
    unit = value("units")
    v = units_value / UNIT_FACTORS[unit]
    return f"{round(v, 2 if unit == 'mm' else 1):g} {unit}"


def artboard_size() -> tuple[float, float]:
    from .model import ARTBOARD_FORMATS
    name = value("artboard_format")
    for fmt, w, h in ARTBOARD_FORMATS:
        if fmt == name:
            return w, h
    return ARTBOARD_FORMATS[0][1], ARTBOARD_FORMATS[0][2]
