"""BARRES D'OUTILS FLOTTANTES (type d'élément « palette » de fm_theme). Spécification : docs/agents/barres_outils_spec.md ;
référence exacte : docs/agents/prototype_barres_outils.html (prototype validé par l'utilisateur, son code JS fait foi).

Une BARRE (`ToolBar`) = un cadre avec un TITRE (poignée « ⋮⋮ » + nom en capitales) et une GRILLE de cases de la taille
d'une icône (capture annotée de l'utilisateur, 2026-11-02, qui remplace les « étages » du prototype) :
- une icône occupe une case, un bouton à texte ou un contrôle n cases de large ; chacun se pose dans N'IMPORTE QUELLE case
  libre ; la barre se redimensionne par ses bords, toujours accrochée à la grille (jamais plus petite que son contenu ni
  que son titre) ; la largeur d'un contrôle s'accroche aussi à la grille ; PAS de poignée d'étages ;
- marges ÉGALES à gauche, à droite et en bas (padding 6) ; titre en haut (horizontale) ou à gauche, écrit de bas en haut
  (verticale : la grille est transposée) ; icône 34 × 34, écart 4.
Un GESTIONNAIRE (`fm_theme/bar_manager.py`) en tient plusieurs sur un espace de travail : aimantation aux bords et aux
autres barres, coins / bordures au contact, éléments déplacés d'une barre à l'autre, nouvelle barre dans le vide.

Gestes (prototype) :
- titre : glisser = déplacer (SANS Ctrl : exception voulue à la règle « Ctrl + glisser » de l'appli, la spec le demande),
  Ctrl + clic = renommer, double-clic = pivoter (barre flottante) ;
- bords : redimensionner la barre, de case en case (barre clipsée : le bord qui ne touche pas la fenêtre) ;
- icône : tirée directement (seuil 4 px ; en dessous c'est un clic) ; contrôle : par sa poignée « ⋮⋮ » de 16 px, le
  contrôle lui-même reste utilisable ; il se pose dans la case libre visée (la barre grandit si elle est pleine) ;
  largeur d'un contrôle : poignée de 9 px à droite, en cases entières (120 à 520 px).

Fluidité : cadre, titre, case de dépôt et éléments dessinés UNE fois en image (clé : taille, habillage, état) ; la mise
en page est un simple calcul de rectangles, refait seulement quand le contenu change. L'habillage est COMMUN (`LOOK`) :
`set_look(réglages)` puis `restyle_palettes_in(racine, réglages)`. Aucun import de l'appli.
"""
from __future__ import annotations

import math
import weakref

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QApplication, QGraphicsOpacityEffect, QWidget
from shiboken6 import isValid

from fm_theme.palette_defaults import (CONTROL_MAX_WIDTH, CONTROL_MIN_WIDTH, PALETTE_DEFAULTS, SIDES, SLIDER_STYLES,
                                       TITLE_ALIGNS, TOGGLE_STYLES, TRANSPARENT)
from fm_theme.placeholder import ink as _placeholder_ink
from fm_theme import icon_frame as _icon_frame, icon_library
from fm_theme.style import font as _font, scaled
from fm_theme.tokens import M, _resolve_color_value
from fm_theme.widgets import (DRAG_GHOST_OPACITY, _MiniSlider, _paint_bordered_vector, _rounded_rect_path, attach_shadow,
                              shadow_look)

CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
DRAG_SLOP = 4                      # pixels : en dessous, un appui suivi d'un relâchement est un clic (spec § 6)
GRIP_W = 16                        # poignée « ⋮⋮ » d'un contrôle
WIDTH_HANDLE = 9                   # poignée de largeur d'un contrôle (à cheval sur son bord droit dans le prototype)
DRAG_OPACITY = 0.94                # barre en cours de déplacement (spec § 4)
KIND_LABELS = {"slider": "Slider", "input": "Saisie", "select": "Menu", "toggle": "Toggle"}
CORNER_FLAGS = ("tl", "tr", "br", "bl")


def _setting(settings: dict, key: str):
    return settings.get(key, PALETTE_DEFAULTS[key])


def _int(settings: dict, key: str, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(_setting(settings, key))))
    except (TypeError, ValueError):
        return max(low, min(high, int(PALETTE_DEFAULTS[key])))


_TRANSPARENT_TOKENS: dict[str, str] = {}      # clé -> jeton M affiché quand la couleur est transparente


def shown_color(key: str) -> str | None:
    """Couleur AFFICHÉE par un réglage `palette_*` laissé transparent (point de départ du sélecteur de couleur,
    2026-11-11) ; None = transparent veut dire « aucun » ou clé pas encore rencontrée."""
    token = _TRANSPARENT_TOKENS.get(key)
    return M.get(token) if token else None


def _color(settings: dict, key: str, token: str | None, colors: dict) -> str:
    """Couleur réglée (hex, « @pastille ») ; transparente = le jeton `token` du thème (M)."""
    if token:
        _TRANSPARENT_TOKENS[key] = token
    value = _setting(settings, key)
    resolved = _resolve_color_value(value, colors) if isinstance(value, str) else ""
    if QColor(resolved).isValid() and (QColor(resolved).alpha() or token is None):
        return resolved
    return M[token] if token else TRANSPARENT


def _sides(value, default: bool = True) -> dict:
    if isinstance(value, dict):
        return {s: bool(value.get(s, default)) for s in SIDES}
    return {s: default if value is None else bool(value) for s in SIDES}


def _side_colors(value, token: str, colors: dict) -> dict:
    out = {}
    for side in SIDES:
        raw = value.get(side) if isinstance(value, dict) else value
        resolved = _resolve_color_value(raw, colors) if isinstance(raw, str) and raw else ""
        out[side] = resolved if QColor(resolved).isValid() and QColor(resolved).alpha() else M[token]
    return out


def _radius(value) -> dict:
    if isinstance(value, dict):
        return {c: max(0, scaled(value.get(c, 0), 0)) for c in CORNERS}
    try:
        return dict.fromkeys(CORNERS, max(0, scaled(int(value), 0)))
    except (TypeError, ValueError):
        return dict.fromkeys(CORNERS, 0)


def _font_spec(settings: dict, prefix: str, caps: bool, tracking: float) -> tuple:
    """Police d'un gabarit (`<prefix>_font_*`) sous forme de valeurs : le QFont se fabrique à la demande (`look_font`)."""
    smoothing = _setting(settings, f"{prefix}_font_smoothing") if _setting(settings, f"{prefix}_font_smoothing_enabled") \
        else "current"
    return (str(_setting(settings, f"{prefix}_font_family") or ""), _int(settings, f"{prefix}_font_size", 6, 40),
            bool(_setting(settings, f"{prefix}_font_bold")), bool(_setting(settings, f"{prefix}_font_italic")),
            str(smoothing), caps, tracking)


SNAP_SIDES = (("none", "1. Rien"), ("no_border", "2. Pas de bordure"), ("color", "3. Couleur de bordure"))


def _snap_side(settings: dict) -> str:
    """« Clipsée : comportement du côté collé » ; l'ancien toggle `palette_snap_border_off` (allumé) vaut « no_border »."""
    value = settings.get("palette_snap_side")
    if value is None and settings.get("palette_snap_border_off"):
        return "no_border"
    value = value or PALETTE_DEFAULTS["palette_snap_side"]
    return value if value in dict(SNAP_SIDES) else "none"


TOOLBAR_BUTTON_VARIANT = "toolbar"


def toolbar_button_fields(settings: dict | None) -> dict:
    """Champs (sans préfixe `button_`) d'une variante du type « bouton » tirée des boutons des barres d'outils
    (`settings` : les clés `palette_*` et `colors`) : fond, bordure, épaisseur et arrondi des cases, couleur des icônes
    pour le texte, police des contrôles des barres, fond au survol, fond / bordure / épaisseur de l'état actif ; une
    couleur transparente « suit le thème » : sa teinte RÉSOLUE. La taille des cases et des icônes n'a pas d'équivalent
    dans le type « bouton » (demande de l'utilisateur, 2026-11-10)."""
    s = settings or {}
    colors = s.get("colors") or {}
    radius = _int(s, "palette_cell_radius", 0, 40)
    border_on = _sides(_setting(s, "palette_cell_border_enabled"), False)
    return {
        "frame": True, "radius": radius, "bg_color": _color(s, "palette_cell_bg_color", None, colors),
        "border_enabled": border_on, "border_enabled_linked": len(set(border_on.values())) == 1,
        "border": _side_colors(_setting(s, "palette_cell_border"), "panel_border", colors),
        "border_thickness": _int(s, "palette_cell_border_thickness", 0, 8),
        "corner_radius": dict.fromkeys(CORNERS, radius), "corner_radius_linked": True,
        "font_family": str(_setting(s, "palette_bar_font_family") or ""),
        "font_size": _int(s, "palette_bar_font_size", 6, 40),
        "font_bold": bool(_setting(s, "palette_bar_font_bold")), "font_italic": bool(_setting(s, "palette_bar_font_italic")),
        "font_smoothing_enabled": bool(_setting(s, "palette_bar_font_smoothing_enabled")),
        "font_smoothing": _setting(s, "palette_bar_font_smoothing"),
        "font_color": _color(s, "palette_icon_color", "value_fg", colors),
        "shadow_enabled": dict.fromkeys(SIDES, False), "shadow_enabled_linked": True,
        "hover_color": _color(s, "palette_cell_hover_color", "btn_hover", colors),
        "active_color": _color(s, "palette_cell_active_color", None, colors),
        "active_border": dict.fromkeys(SIDES, _color(s, "palette_cell_active_border_color", None, colors)),
        "active_border_enabled": dict.fromkeys(SIDES, True), "active_border_enabled_linked": True,
        "active_border_thickness": _int(s, "palette_cell_active_border_thickness", 0, 6),
    }


def palette_look(settings: dict | None) -> dict:
    """Habillage des barres depuis des réglages à plat (`settings` : les clés `palette_*` et `colors`) : tout est
    résolu (couleurs en hex, tailles à l'échelle de l'interface). `key` change avec la moindre valeur."""
    s = settings or {}
    colors = s.get("colors") or {}
    look = {
        "cell": scaled(_int(s, "palette_cell_size", 16, 96)), "gap": scaled(_int(s, "palette_cell_gap", 0, 24), 0),
        "margin": scaled(_int(s, "palette_margin", 0, 32), 0),
        "header": scaled(_int(s, "palette_header_height", 0, 80), 0) if _setting(s, "palette_header_shown") is not False
        else 0,
        "header_shown": _setting(s, "palette_header_shown") is not False,
        "snap": _int(s, "palette_snap_distance", 0, 120),
        "bg": _color(s, "palette_bg_color", "panel_bg", colors),
        "border_on": _sides(_setting(s, "palette_border_enabled")),
        "border": _side_colors(_setting(s, "palette_border"), "panel_border", colors),
        "border_w": scaled(_int(s, "palette_border_thickness", 0, 8), 0),
        "drag_border": _color(s, "palette_drag_border_color", "dash", colors),
        "snap_side": _snap_side(s),
        "snap_border_off": _snap_side(s) in ("no_border", "color"),     # côté collé : sans SA bordure
        "snap_side_color": _color(s, "palette_snap_side_color", "panel_border", colors),
        "snap_separator": bool(_setting(s, "palette_snap_separator")),
        "snap_header_color": bool(_setting(s, "palette_snap_header_color")),
        "snap_bg_color": bool(_setting(s, "palette_snap_bg_color")),
        "snap_border_match": bool(_setting(s, "palette_snap_border_match")),
        "radius": _radius(_setting(s, "palette_corner_radius")),
        "shadow": shadow_look({**{k: _setting(s, k) for k in ("palette_shadow_enabled", "palette_shadow",
                                                              "palette_shadow_size")}}, "palette_shadow",
                              lambda value: _resolve_color_value(value, colors)),
        "title_font": _font_spec(s, "palette_title", bool(_setting(s, "palette_title_caps")),
                                 _int(s, "palette_title_tracking", 0, 60) / 10),
        "title_ink": _color(s, "palette_title_font_color", "title_fg", colors),
        "grip_on": bool(_setting(s, "palette_grip_enabled")), "grip_ink": _color(s, "palette_grip_color", "chevron", colors),
        "title_align": _setting(s, "palette_title_align") if _setting(s, "palette_title_align") in dict(TITLE_ALIGNS)
        else "left",
        "header_bg": _color(s, "palette_header_bg_color", None, colors),
        "cell_bg": _color(s, "palette_cell_bg_color", None, colors),
        "cell_border_on": _sides(_setting(s, "palette_cell_border_enabled"), False),
        "cell_border": _side_colors(_setting(s, "palette_cell_border"), "panel_border", colors),
        "cell_border_w": scaled(_int(s, "palette_cell_border_thickness", 0, 8), 0),
        "cell_radius": scaled(_int(s, "palette_cell_radius", 0, 40), 0), "icon_ratio": _int(s, "palette_icon_ratio", 20, 100),
        "icon_ink": _color(s, "palette_icon_color", "value_fg", colors),
        "hover": _color(s, "palette_cell_hover_color", "btn_hover", colors),
        "active": _color(s, "palette_cell_active_color", None, colors),
        "active_border": _color(s, "palette_cell_active_border_color", None, colors),
        "active_border_w": scaled(_int(s, "palette_cell_active_border_thickness", 0, 6), 0),
        "drop": _color(s, "palette_drop_color", None, colors),
        "separator": _color(s, "palette_separator_color", "panel_border", colors),
        "slide_ms": _int(s, "palette_slide_ms", 0, 400),
        "bar_bg": _color(s, "palette_bar_bg_color", "field_bg", colors),
        "bar_border_on": _sides(_setting(s, "palette_bar_border_enabled")),
        "bar_border": _side_colors(_setting(s, "palette_bar_border"), "field_border", colors),
        "bar_border_w": scaled(_int(s, "palette_bar_border_thickness", 0, 8), 0),
        "bar_radius": scaled(_int(s, "palette_bar_radius", 0, 40), 0),
        "bar_pad": scaled(_int(s, "palette_bar_padding", 0, 32), 0),
        "bar_font": _font_spec(s, "palette_bar", False, 0.0),
        "bar_ink": _color(s, "palette_bar_font_color", "value_muted", colors),
        "bar_value": _color(s, "palette_bar_value_color", "value_text", colors),
        "bar_grip_on": bool(_setting(s, "palette_bar_grip_enabled")),
        "bar_grip_ink": _color(s, "palette_bar_grip_color", "chevron", colors),
        "bar_handle_on": bool(_setting(s, "palette_bar_handle_enabled")),
        "bar_handle_ink": _color(s, "palette_bar_handle_color", "dash", colors),
        "join_gap": scaled(_int(s, "palette_bar_join_gap", 0, 24), 0),
        "slider_mode": _setting(s, "palette_slider_style") if _setting(s, "palette_slider_style") in dict(SLIDER_STYLES)
        else "app",
        "slider": _slider_style(s, colors),
        "slider_value_w": scaled(_int(s, "palette_slider_value_width", 0, 120), 0),
        "select_min": scaled(_int(s, "palette_select_min_width", 20, 300)),
        "select_h": scaled(_int(s, "palette_select_height", 12, 40)),
        "input_min": scaled(_int(s, "palette_input_min_width", 20, 300)),
        "input_h": scaled(_int(s, "palette_input_height", 12, 40)),
        "toggle_style": _setting(s, "palette_toggle_style") if _setting(s, "palette_toggle_style") in dict(TOGGLE_STYLES)
        else "toggle1",
        "toggle_labels": bool(_setting(s, "palette_toggle_labels")),
    }
    look["key"] = repr(sorted((k, v) for k, v in look.items() if k != "key"))
    return look


def _slider_style(s: dict, colors: dict) -> tuple:
    """Habillage propre aux sliders des barres (« Propre aux barres ») : les clés de `_SLIDER_STYLE`, en tuple trié (il
    entre dans la clé de l'habillage) ; `slider_style()` en refait le dict."""
    from fm_theme.tokens import _SLIDER_STYLE
    track = _color(s, "palette_slider_track_color", "field_border", colors)
    fill, thumb = _color(s, "palette_slider_fill_color", None, colors), _color(s, "palette_slider_thumb_color", None, colors)
    radius = dict.fromkeys(CORNERS, scaled(_int(s, "palette_slider_radius", 0, 20), 0))
    style = dict(_SLIDER_STYLE)
    style.update({"track_h": scaled(_int(s, "palette_slider_track_height", 1, 20), 1),
                  "thumb_w": scaled(_int(s, "palette_slider_thumb_width", 1, 30), 1),
                  "thumb_h": scaled(_int(s, "palette_slider_thumb_height", 2, 30), 2),
                  "track_empty": track, "track_fill": fill, "thumb_color": thumb,
                  "track_radius": radius, "thumb_radius": radius,
                  "track_border_enabled": dict.fromkeys(SIDES, False), "thumb_border_enabled": dict.fromkeys(SIDES, False)})
    for side in SIDES:
        style[f"track_border_{side}"], style[f"thumb_border_{side}"] = track, thumb
    return tuple(sorted((k, tuple(sorted(v.items())) if isinstance(v, dict) else v) for k, v in style.items()))


_SLIDER_DICTS: dict = {}


def slider_style() -> dict | None:
    """Habillage des sliders des barres : None = celui des réglages ; sinon un dict (fabriqué une fois par valeur)."""
    if LOOK["slider_mode"] != "palette":
        return None
    spec = LOOK["slider"]
    style = _SLIDER_DICTS.get(spec)
    if style is None:
        style = _SLIDER_DICTS[spec] = {k: dict(v) if isinstance(v, tuple) else v for k, v in spec}
    return style


LOOK: dict = palette_look({})


_LOOK_SETTINGS: dict = {}                 # réglages de l'habillage courant (clic droit : en-têtes)


def toggle_headers() -> None:
    """Clic droit sur une barre : en-têtes affichés / masqués (réglage `palette_header_shown`, enregistré par l'hôte)."""
    from fm_theme.hooks import save_setting
    shown = not LOOK.get("header_shown", True)
    restyle_palettes_in(None, dict(_LOOK_SETTINGS, palette_header_shown=shown))
    save_setting("palette_header_shown", shown)


_ARROWS: dict = {}


def arrow_cursor(direction: str):
    """Curseur flèche vers un bord (« left », « right », « up », « down ») ou vers le milieu (« center ») : Ctrl sur une
    tranche, les barres du bord vont se plaquer de ce côté."""
    cursor = _ARROWS.get(direction)
    if cursor is not None:
        return cursor
    from PySide6.QtGui import QCursor, QPolygonF
    size = 24
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(size / 2, size / 2)
    painter.rotate({"right": 0, "down": 90, "left": 180, "up": 270, "center": 0}[direction])

    def arrow(flip=1):
        shaft = QPolygonF([QPointF(-9 * flip, -1.5), QPointF(2 * flip, -1.5), QPointF(2 * flip, -5),
                           QPointF(8 * flip, 0), QPointF(2 * flip, 5), QPointF(2 * flip, 1.5), QPointF(-9 * flip, 1.5)])
        painter.drawPolygon(shaft)
    painter.setPen(QPen(QColor("#ffffff"), 1.6))
    painter.setBrush(QColor("#000000"))
    if direction == "center":                          # →|←
        painter.scale(0.62, 1)
        painter.translate(-8, 0)
        arrow()
        painter.translate(16, 0)
        arrow(-1)
        painter.resetTransform()
        painter.translate(size / 2, size / 2)
        painter.drawRect(QRectF(-1.2, -9, 2.4, 18))
    else:                                              # →|
        arrow()
        painter.drawRect(QRectF(9, -9, 2.6, 18))
    painter.end()
    cursor = QCursor(pixmap, size // 2, size // 2)
    _ARROWS[direction] = cursor
    return cursor


def set_look(settings: dict | None) -> bool:
    """Pose l'habillage commun depuis les réglages ; faux s'il n'a pas changé (rien à refaire)."""
    global _LOOK_SETTINGS
    _LOOK_SETTINGS = dict(settings or {})
    look = palette_look(settings)
    if look["key"] == LOOK.get("key"):
        return False
    LOOK.clear()
    LOOK.update(look)
    return True


_FONTS: dict = {}


def look_font(name: str):
    """QFont de la police `name` (« title », « bar ») de l'habillage courant, fabriquée une fois par valeur. Chiffres de
    largeur fixe (valeur des sliders, spec § 8)."""
    spec = LOOK[f"{name}_font"]
    font = _FONTS.get(spec)
    if font is None:
        family, size, bold, italic, smoothing, caps, tracking = spec
        font = _font(size, 600 if bold else 400, tracking=tracking, caps=caps, smoothing=smoothing, italic=italic)
        if family:
            from fm_theme.style import _resolve_font_family
            font.setFamily(_resolve_font_family(family, size, 600 if bold else 400))
        try:
            font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError):           # Qt < 6.7 : chiffres de la police
            pass
        _FONTS[spec] = font
    return font


def _alpha(color: str, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def _render(size: QSize, dpr: float, paint) -> QPixmap:
    """Image transparente de `size` (pixels logiques) peinte par `paint(painter)`."""
    pixmap = QPixmap(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    paint(painter)
    painter.end()
    return pixmap


def _dots(painter: QPainter, rect: QRectF, color: str) -> None:
    """Poignée « ⋮⋮ » : deux colonnes de trois points, centrée dans `rect` (laisse le crayon à « aucun »)."""
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    r = max(0.9, min(rect.width() / 8, rect.height() / 12))
    for ix in (0, 1):
        for iy in (0, 1, 2):
            painter.drawEllipse(QPointF(rect.center().x() + (ix - 0.5) * 4 * r, rect.center().y() + (iy - 1) * 4 * r), r, r)


# -- Glyphes d'exemple (aperçu de l'éditeur, tests) : de simples formes dans la couleur du thème ----------------------

def demo_glyph(kind: str):
    """Peintre `(painter, rect, color)` d'un glyphe d'exemple (carré, triangle, tableau, crayon, image, cercle)."""
    def paint(painter, rect: QRectF, color: QColor):
        color = _placeholder_ink(color)                     # icone dessinee par le code : magenta (provisoire)
        pen = QPen(color, max(1.2, rect.width() / 14))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        r = rect.adjusted(rect.width() * .12, rect.height() * .12, -rect.width() * .12, -rect.height() * .12)
        if kind == "triangle":
            path = QPainterPath(r.topLeft())
            path.lineTo(r.bottomLeft())
            path.lineTo(r.bottomRight())
            path.closeSubpath()
            painter.drawPath(path)
        elif kind == "table":
            painter.drawRoundedRect(r, 2, 2)
            for f in (1 / 3, 2 / 3):
                painter.drawLine(QPointF(r.left(), r.top() + r.height() * f), QPointF(r.right(), r.top() + r.height() * f))
                painter.drawLine(QPointF(r.left() + r.width() * f, r.top()), QPointF(r.left() + r.width() * f, r.bottom()))
        elif kind == "pen":
            painter.drawLine(r.bottomLeft(), r.topRight())
            painter.drawLine(r.bottomLeft(), QPointF(r.left() + r.width() * .22, r.bottom() - r.height() * .22))
        elif kind == "image":
            painter.drawRoundedRect(r, 2, 2)
            path = QPainterPath(QPointF(r.left(), r.bottom() - r.height() * .2))
            path.lineTo(r.left() + r.width() * .4, r.top() + r.height() * .5)
            path.lineTo(r.left() + r.width() * .65, r.top() + r.height() * .75)
            path.lineTo(r.right(), r.top() + r.height() * .45)
            painter.drawPath(path)
        elif kind == "circle":
            painter.drawEllipse(r)
        else:
            painter.drawRoundedRect(r, 3, 3)
    return paint


# -- Éléments ------------------------------------------------------------------------------------------------------------

class _ItemMixin:
    """Ce que partagent les éléments d'une barre. Un appui suivi d'un mouvement de plus de `DRAG_SLOP` px démarre le
    déplacement (icône : n'importe où ; contrôle : sa poignée, `_grab_zone`) ; en dessous, le geste garde son sens (clic).
    Pendant le déplacement l'élément sort de la mise en page de sa barre : il est posé hors de vue SANS être caché (il
    garde la souris) et une vignette suit le curseur (gestionnaire)."""

    palette_key = ""
    kind = "icon"
    _press = None                   # point (global) de l'appui qui peut devenir un déplacement
    _dragging = False

    def _palette(self):
        parent = self.parentWidget()
        return parent if isinstance(parent, ToolBar) else None

    def bar_size(self) -> QSize:
        """Taille de l'élément dans une barre : icône = case × case."""
        cell = LOOK["cell"]
        return QSize(cell, cell)

    def _grab_zone(self, pos: QPoint) -> bool:
        return True

    def drag_hide(self, hidden: bool) -> None:
        """Compatibilité (ancienne grille) : rien à faire, l'élément tiré est hors de vue."""

    def _item_press(self, event) -> bool:
        """Appui gauche dans la zone de prise : retenu (le déplacement démarrera au-delà du seuil)."""
        if event.button() == Qt.LeftButton and self._palette() is not None and self._grab_zone(event.position().toPoint()):
            self._press = event.globalPosition().toPoint()
            return True
        self._press = None
        return False

    def _item_move(self, event) -> bool:
        palette = self._palette()
        if self._dragging:
            if palette is not None:
                palette.drag_to(event.globalPosition().toPoint())
            return True
        if self._press is None or not (event.buttons() & Qt.LeftButton) or palette is None:
            return False
        delta = event.globalPosition().toPoint() - self._press
        if math.hypot(delta.x(), delta.y()) < DRAG_SLOP:
            return isinstance(self, PaletteControl)
        start, self._press = self._press, None
        if isinstance(self, QAbstractButton):
            self.setDown(False)                       # plus de clic au relâchement
        self._dragging = True
        palette.begin_drag(self, start)
        palette.drag_to(event.globalPosition().toPoint())
        return True

    def _item_release(self, event) -> bool:
        self._press = None
        if not self._dragging:
            return False
        self._dragging = False
        palette = self._palette()
        if palette is not None:
            palette.end_drag()
        else:                                          # déjà adopté par une autre barre : c'est elle qui finit le geste
            manager = getattr(self, "_manager", None)
            if manager is not None:
                manager.end_item_drag()
        self.update()
        return True


_BOUTONS_SVG = weakref.WeakKeyDictionary()


def _actualiser_boutons_svg(modules):
    for bouton, module in _BOUTONS_SVG.items():
        if module in modules and isValid(bouton):
            bouton.restyle()


icon_library.on_change(_actualiser_boutons_svg)


class PaletteButton(_ItemMixin, QAbstractButton):
    """Une icône : `glyph(painter, rect, color)` peint l'icône ; `active` = l'outil en cours (fond accent à 20 %,
    bordure accent). Image gardée tant que ni la taille, ni l'habillage, ni l'état ne changent."""

    def __init__(self, key: str, tip: str, glyph, parent=None, ink: str | None = None):
        super().__init__(parent)
        self.palette_key = key
        self.glyph = glyph
        self.ink = ink                       # couleur propre de l'icône (sinon celle du thème)
        self.active = False
        self.label = tip
        self._pix = None
        self._pix_key = None
        self._svg_id = None
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def set_library_icon(self, identifiant: str) -> None:
        """Choisit le SVG de ce bouton. Le glyphe d'origine reste disponible comme secours."""
        self._svg_id = identifiant
        _BOUTONS_SVG[self] = identifiant.split("/")[1]
        self.restyle()

    def set_active(self, active: bool) -> None:
        if bool(active) != self.active:
            self.active = bool(active)
            self.update()

    def set_ink(self, ink: str | None) -> None:
        if ink != self.ink:
            self.ink = ink
            self.update()

    def extra_key(self) -> tuple:
        """Ce dont le dessin dépend en plus (sous-classes : texte, pastille, icônes personnalisées)."""
        return ()

    def restyle(self) -> None:
        self._pix_key = None
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._item_press(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._item_move(event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._item_release(event)
        super().mouseReleaseEvent(event)              # (bouton relâché : pas de clic après un déplacement)

    def paintEvent(self, event):
        if self._dragging:
            return
        look = LOOK
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self.active, self.underMouse(), self.ink, look["key"], self.extra_key(),
               _icon_frame.MARGIN)
        if key != self._pix_key:
            self._pix_key = key
            self._pix = _render(self.size(), dpr, self._paint_content)
        QPainter(self).drawPixmap(0, 0, self._pix)

    def ghost_pixmap(self, dpr: float) -> QPixmap:
        """L'icône seule (vignette du déplacement) : sans fond actif ni survol."""
        active, self.active, self._no_hover = self.active, False, True
        try:
            return _render(self.size(), dpr, self._paint_content)
        finally:
            self.active, self._no_hover = active, False

    _no_hover = False

    def _paint_content(self, painter: QPainter) -> None:
        look = LOOK
        rect = QRectF(self.rect())
        radius = look["cell_radius"]
        if QColor(look["cell_bg"]).alpha() or (look["cell_border_w"] and any(look["cell_border_on"].values())):
            _paint_bordered_vector(painter, self.rect(), radius, look["cell_border_on"], look["cell_border_w"],
                                   look["cell_border"], look["cell_bg"])           # fond et bordure de l'icône
        if self.active:
            width = look["active_border_w"]
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["active"]))
            painter.drawRoundedRect(rect, radius, radius)
            if width:                                   # contour DANS la case (demi-épaisseur de chaque côté du tracé)
                painter.setPen(QPen(QColor(look["active_border"]), width))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect.adjusted(width / 2, width / 2, -width / 2, -width / 2),
                                        max(0, radius - width / 2), max(0, radius - width / 2))
        elif self.underMouse() and not self._no_hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["hover"]))
            painter.drawRoundedRect(rect, radius, radius)
        side = min(rect.width(), rect.height()) * look["icon_ratio"] / 100
        target = QRectF(0, 0, side, side)
        target.moveCenter(rect.center())
        color = QColor(self.ink or look["icon_ink"])
        if self._svg_id and self._paint_library_icon(painter, target, color):
            return
        # Cadre des icones (Theme > General > Marge des icones) : sans cache ici, l'image du bouton est deja gardee.
        _icon_frame.paint_framed(painter, target, lambda p, r: self.glyph(p, r, color))

    def _paint_library_icon(self, painter, rect, color):
        normal = self.isEnabled() and color.lightness() >= 60
        style = icon_library.style_affiche(normal)          # flat monochrome : couleur de l'icône du bouton
        return icon_library.peindre(painter, rect, self._svg_id, style=style,
                                     teinte=None if style == icon_library.COULEUR else color)


class PaletteTextButton(PaletteButton):
    """Bouton à TEXTE (police, taille, zoom « 100 % ») : `cells` icônes de large (écarts compris) ; le texte est dans la
    police du libellé des contrôles ; `set_text` le change sans refaire la barre."""

    def __init__(self, key: str, text: str, tip: str, parent=None, cells: int = 2):
        super().__init__(key, tip, lambda *_a: None, parent)
        self._text = text
        self.cells = max(1, cells)

    def bar_size(self) -> QSize:
        look = LOOK
        return QSize(self.cells * look["cell"] + (self.cells - 1) * look["gap"], look["cell"])

    def text_value(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.update()

    def extra_key(self) -> tuple:
        return (self._text,)

    def _paint_content(self, painter: QPainter) -> None:
        look = LOOK
        super()._paint_content(painter)            # fond actif / survol (le glyphe vide ne peint rien)
        painter.setFont(look_font("bar"))
        painter.setPen(QColor(self.ink or look["bar_value"]))
        texte = QRectF(self.rect()).adjusted(4, 0, -4, 0)
        if self._svg_id:
            cote = min(texte.height(), texte.width() / 3) * look["icon_ratio"] / 100
            cadre = QRectF(texte.left(), texte.center().y() - cote / 2, cote, cote)
            if super()._paint_library_icon(painter, cadre, painter.pen().color()):
                texte.setLeft(cadre.right() + 2)
        painter.drawText(texte, Qt.AlignCenter,
                         painter.fontMetrics().elidedText(self._text, Qt.ElideRight, max(1, int(texte.width()))))

    def _paint_library_icon(self, painter, rect, color):
        # L'icône d'un bouton à texte se peint à gauche du libellé.
        return True

    def min_cells(self) -> int:
        return self.cells


class PaletteControl(_ItemMixin, QWidget):
    """Un contrôle (spec § 8) : cadre de 34 px de haut, bordure 1 px, rayon 6 ; poignée de déplacement « ⋮⋮ » de 16 px à
    gauche, libellé, le champ des réglages (`inner` : curseur, saisie, menu ; il s'étire, 40 px au moins), éventuellement
    la valeur (alignée à droite, 36 px au moins) ; poignée de LARGEUR à droite (120 à 520 px, enregistrée par élément).
    Hors d'une barre (un panneau), c'est un simple champ. Les sous-classes donnent le champ et `valueChanged`."""

    valueChanged = Signal(object)
    kind = "slider"
    right_pad = 4

    @property
    def field_min(self) -> int:
        """Largeur la plus petite du champ (réglages de chaque contrôleur)."""
        return 40

    def __init__(self, key: str, label: str, inner: QWidget, value_text: str | None = None, parent=None,
                 width: int = 200):
        super().__init__(parent)
        self.palette_key = key
        self.label = label
        self.inner = inner
        inner.setParent(self)
        self._value_text = value_text            # None : pas de valeur peinte (saisie, menu)
        self._max_text = value_text or ""
        self.default_width = width               # largeur d'origine (spec § 8 : Opacité 220, Nom 180, Police 170…)
        self.bar_width = width
        self.persist_value = False               # la valeur est-elle enregistrée avec la disposition (gestionnaire) ?
        self._chrome = None
        self._chrome_key = None
        self._grip_rect = self._label_rect = self._value_rect = self._handle_rect = QRect()
        self.joined: tuple = ()                  # coins soudés à un contrôleur voisin (barre) : pas d'arrondi
        self.setMouseTracking(True)
        self._width_drag = None

    def set_joined(self, corners) -> None:
        corners = tuple(sorted(corners))
        if corners != self.joined:
            self.joined = corners
            self.update()

    # Taille ------------------------------------------------------------------------------------------------------------
    def min_width(self) -> int:
        """Largeur la plus petite : poignée, libellé, champ minimal, valeur, marge droite ; jamais sous 120 px."""
        look = LOOK
        metrics = QFontMetrics(look_font("bar"))
        need = (GRIP_W if look["bar_grip_on"] else 6) + 6 + metrics.horizontalAdvance(self.label) + 6 + self.field_min
        if self._value_text is not None:
            need += 6 + self._value_width(metrics)
        return max(CONTROL_MIN_WIDTH, need + self.right_pad + 2)

    def bar_size(self) -> QSize:
        return QSize(max(self.min_width(), min(CONTROL_MAX_WIDTH, int(self.bar_width))), LOOK["cell"])

    def set_bar_width(self, width: int) -> int:
        """Largeur du contrôle dans sa barre (bornée à 120..520 px et à son minimum) ; rend la largeur posée."""
        width = max(self.min_width(), min(CONTROL_MAX_WIDTH, int(round(width))))
        self.bar_width = width
        return width

    def min_cells(self) -> int:
        """Largeur minimale en cases de la grille."""
        return need_cells(self)

    # Valeur (enregistrée par le gestionnaire si `persist_value`) ------------------------------------------------------
    def saved_value(self):
        return self.value()

    def load_value(self, value) -> None:
        self.setValue(value)

    def restyle(self) -> None:
        self._chrome_key = None
        self._layout_parts()
        self.update()

    def _value_width(self, metrics: QFontMetrics) -> int:
        return max(LOOK["slider_value_w"], metrics.horizontalAdvance(self._max_text))

    def _set_value_text(self, text: str) -> None:
        if text != self._value_text:
            self._value_text = text
            self.update()

    def resizeEvent(self, event):
        self._layout_parts()
        super().resizeEvent(event)

    def _set_inner_width(self, width: int) -> None:
        if self.inner.width() != width:
            self.inner.setFixedWidth(width)

    def _layout_parts(self) -> None:
        """Place le champ entre le libellé et la valeur (c'est LUI qui s'étire) ; mémorise les zones peintes."""
        look = LOOK
        w, h = self.width(), self.height()
        metrics = QFontMetrics(look_font("bar"))
        x = 1
        self._grip_rect = QRect()
        if look["bar_grip_on"]:
            self._grip_rect = QRect(1, 1, GRIP_W, max(1, h - 2))
            x += GRIP_W
        else:
            x += 5
        x += 6
        self._label_rect = QRect(x, 0, metrics.horizontalAdvance(self.label), h)
        x += self._label_rect.width() + 6
        right = w - 1 - self.right_pad
        if self._value_text is not None:
            value_w = self._value_width(metrics)
            self._value_rect = QRect(right - value_w, 0, value_w, h)
            right = self._value_rect.left() - 6
        else:
            self._value_rect = QRect()
        self._handle_rect = QRect(w - (WIDTH_HANDLE // 2 + 1), 0, WIDTH_HANDLE // 2 + 1, h) \
            if look["bar_handle_on"] and self._palette() is not None else QRect()
        self._set_inner_width(max(self.field_min, right - x))
        self.inner.move(x, (h - self.inner.height()) // 2)

    def paintEvent(self, event):
        if self._dragging:
            return
        look = LOOK
        dpr = self.devicePixelRatioF()
        in_bar = self._palette() is not None
        key = (self.width(), self.height(), dpr, self._value_text, self.label, look["key"], in_bar, self.joined)
        if key != self._chrome_key:
            if self._label_rect.isNull():                 # pas encore de resizeEvent (barre jamais montrée)
                self._layout_parts()
            self._chrome_key = key
            self._chrome = _render(self.size(), dpr, self._paint_chrome)
        QPainter(self).drawPixmap(0, 0, self._chrome)

    def _paint_chrome(self, painter: QPainter) -> None:
        look = LOOK
        radius = {c: (0 if flag in self.joined else look["bar_radius"]) for c, flag in zip(CORNERS, CORNER_FLAGS)}
        _paint_bordered_vector(painter, QRect(self.rect()), radius, look["bar_border_on"], look["bar_border_w"],
                               look["bar_border"], look["bar_bg"])
        if not self._grip_rect.isNull():
            _dots(painter, QRectF(self._grip_rect).adjusted(3, 10, -3, -10), look["bar_grip_ink"])
        painter.setFont(look_font("bar"))
        painter.setPen(QColor(look["bar_ink"]))
        painter.drawText(self._label_rect, Qt.AlignVCenter | Qt.AlignLeft, self.label)
        if self._value_text is not None:
            painter.setPen(QColor(look["bar_value"]))
            painter.drawText(self._value_rect, Qt.AlignVCenter | Qt.AlignRight, self._value_text)
        if not self._handle_rect.isNull():                # trait 2 × 14 sur le bord droit
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["bar_handle_ink"]))
            painter.drawRoundedRect(QRectF(self.width() - 2, self.height() / 2 - 7, 2, 14), 1, 1)

    # Gestes : poignée « ⋮⋮ » = déplacer ; poignée de droite = largeur -------------------------------------------------
    def _grab_zone(self, pos: QPoint) -> bool:
        return not self._grip_rect.isNull() and self._grip_rect.contains(pos)

    def _on_handle(self, pos: QPoint) -> bool:
        return not self._handle_rect.isNull() and self._handle_rect.contains(pos)

    def mousePressEvent(self, event):
        palette = self._palette()
        pos = event.position().toPoint()
        if palette is not None and event.button() == Qt.LeftButton and self._on_handle(pos):
            self._width_drag = (event.globalPosition().x(), self.bar_size().width())
            event.accept()
            return
        if self._item_press(event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._width_drag is not None:
            x0, w0 = self._width_drag
            palette = self._palette()
            if palette is not None:
                palette.set_item_width(self, w0 + event.globalPosition().x() - x0)
            event.accept()
            return
        if self._item_move(event):
            event.accept()
            return
        if not event.buttons():
            pos = event.position().toPoint()
            self.setCursor(Qt.SizeHorCursor if self._on_handle(pos) else Qt.OpenHandCursor if self._grab_zone(pos)
                           else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._width_drag is not None:
            self._width_drag = None
            palette = self._palette()
            if palette is not None:
                palette.end_item_width(self)
            event.accept()
            return
        if self._item_release(event):
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PaletteSliderBar(PaletteControl):
    """Slider (« Opacité 80 % ») : le curseur des réglages (`_MiniSlider`), la valeur et son unité à droite."""

    kind = "slider"
    right_pad = 8

    def __init__(self, key: str, label: str, minimum: int = 0, maximum: int = 100, value: int = 100, unit: str = "%",
                 parent=None, width: int = 220):
        slider = _MiniSlider(minimum, maximum, value, width=40)
        super().__init__(key, label, slider, f"{value} {unit}".strip(), parent, width)
        self.unit = unit
        self.slider = slider
        self._max_text = f"{maximum} {unit}".strip()
        slider.set_style(slider_style())
        slider.valueChanged.connect(self._on_value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(int(value))

    def _text(self) -> str:
        return f"{self.slider.value()} {self.unit}".strip()

    def _on_value(self, value: int) -> None:
        self._set_value_text(self._text())
        self.valueChanged.emit(value)

    def restyle(self) -> None:
        self.slider.set_style(slider_style())
        self.slider.apply_style()
        super().restyle()

    def _set_inner_width(self, width: int) -> None:
        if self.slider._width != width:
            self.slider._width = width
            self.slider._apply_size()


class PaletteInputBar(PaletteControl):
    """Saisie (« Nom : Calque 1 ») : la zone de saisie des réglages (`_TextField`), champ de 24 px ; `valueChanged(texte)`
    à la fin de la saisie. Les touches tapées ne déclenchent AUCUN raccourci (spec § 8)."""

    kind = "input"

    def __init__(self, key: str, label: str, text: str = "", placeholder: str = "", parent=None, width: int = 180):
        from fm_theme.cells import _TextField
        field = _TextField(text, width=40)
        field.setFixedHeight(LOOK["input_h"])
        field.setPlaceholderText(placeholder)
        super().__init__(key, label, field, None, parent, width)
        self.field = field
        field.installEventFilter(self)
        field.editingFinished.connect(lambda: self.valueChanged.emit(field.text()))

    @property
    def field_min(self) -> int:
        return LOOK["input_min"]

    def restyle(self) -> None:
        self.field.setFixedHeight(LOOK["input_h"])
        super().restyle()

    def eventFilter(self, obj, event):
        if obj is self.field and event.type() == QEvent.ShortcutOverride:
            event.accept()                            # la touche va au champ, pas aux raccourcis de l'appli
        return False

    def value(self) -> str:
        return self.field.text()

    def setValue(self, text: str) -> None:
        self.field.setText(str(text))


class PaletteSelectBar(PaletteControl):
    """Menu déroulant (« Police : Inter ») : le menu des réglages (`_SelectField`), 50 px au moins."""

    kind = "select"

    def __init__(self, key: str, label: str, options: list[str], current: str, parent=None, width: int = 170):
        from fm_theme.widgets import _SelectField
        field = _SelectField(list(options), current, width=50)
        field.setFixedHeight(LOOK["select_h"])
        super().__init__(key, label, field, None, parent, width)
        self.field = field
        field.changed.connect(self.valueChanged.emit)

    @property
    def field_min(self) -> int:
        return LOOK["select_min"]

    def restyle(self) -> None:
        self.field.setFixedHeight(LOOK["select_h"])
        super().restyle()

    def value(self) -> str:
        return self.field._value

    def setValue(self, value: str) -> None:
        if value in self.field._options and value != self.field._value:
            self.field._value = value
            self.field._sync_text()

    def set_options(self, options: list[str], current: str) -> None:
        """Choix (une liste qui change : types de ligne réglables…) et valeur affichée, sans signal ; une valeur hors
        des choix (« *varié* » d'une sélection mêlée) est montrée telle quelle."""
        options = list(options)
        if options != self.field._options:
            self.field._options = options
        if current != self.field._value:
            self.field._value = current
            self.field._sync_text()


class PaletteToggleBar(PaletteControl):
    """Toggle (« Grille : ● ») : l'interrupteur des réglages (`_Toggle`, style « Toggle 1 » ou « Toggle 2 » choisi dans
    Contrôleur > Toggle, libellé d'état en option) ; `valueChanged(bool)`."""

    kind = "toggle"

    def __init__(self, key: str, label: str, checked: bool = False, parent=None, width: int = 140):
        from fm_theme.widgets import _Toggle
        look = LOOK
        toggle = _Toggle(bool(checked), parent=None, style_override=look["toggle_style"], show_label=look["toggle_labels"])
        self._toggle_key = (look["toggle_style"], look["toggle_labels"])
        super().__init__(key, label, toggle, None, parent, width)
        self.toggle = toggle
        toggle.toggled.connect(self.valueChanged.emit)

    @property
    def field_min(self) -> int:
        return self.inner.sizeHint().width() if self.inner is not None else 40

    def _set_inner_width(self, width: int) -> None:
        pass                                          # l'interrupteur garde sa taille ; il se pose à gauche du champ

    def restyle(self) -> None:
        look = LOOK
        if (look["toggle_style"], look["toggle_labels"]) != self._toggle_key:      # autre style : interrupteur refait
            from fm_theme.widgets import _Toggle
            old = self.toggle
            self.toggle = self.inner = _Toggle(old.isChecked(), parent=self, style_override=look["toggle_style"],
                                               show_label=look["toggle_labels"])
            self.toggle.toggled.connect(self.valueChanged.emit)
            self.toggle.show()
            old.hide()
            old.deleteLater()
            self._toggle_key = (look["toggle_style"], look["toggle_labels"])
        super().restyle()

    def value(self) -> bool:
        return self.toggle.isChecked()

    def setValue(self, value: bool) -> None:
        if bool(value) != self.toggle.isChecked():
            self.toggle.setChecked(bool(value))


# -- La barre -------------------------------------------------------------------------------------------------------------

_ALL: "weakref.WeakSet[ToolBar]" = weakref.WeakSet()      # toutes les barres vivantes (un habillage COMMUN)

MAX_CELLS = 40                     # plus grande grille (colonnes ou lignes)


def step() -> int:
    """Pas de la grille : une icône et un écart."""
    return LOOK["cell"] + LOOK["gap"]


def cells_px(cells: int) -> int:
    """Largeur en pixels de `cells` cases (écarts intérieurs compris)."""
    return max(1, cells) * step() - LOOK["gap"]


def px_cells(px: float) -> int:
    """Nombre de cases le plus proche d'une largeur en pixels."""
    return max(1, round((px + LOOK["gap"]) / step()))


def need_cells(widget) -> int:
    """Largeur minimale d'un élément en cases : 1 pour une icône, `cells` pour un bouton à texte, le contenu d'un contrôle."""
    if hasattr(widget, "min_width"):
        return max(1, -(-(widget.min_width() + LOOK["gap"]) // step()))
    return max(1, int(getattr(widget, "cells", 1) or 1))


def default_cells(widget) -> int:
    """Largeur d'un élément posé sans largeur connue : celle du contrôle (`bar_width`, 220 px pour un slider…)."""
    if hasattr(widget, "bar_width"):
        return max(need_cells(widget), min(px_cells(CONTROL_MAX_WIDTH), px_cells(widget.bar_width)))
    return need_cells(widget)


class _Placed:
    """Un élément posé : colonne, ligne et largeur en cases (une case de haut)."""
    __slots__ = ("key", "widget", "col", "row", "w")

    def __init__(self, key, widget, col=0, row=0, w=1):
        self.key, self.widget, self.col, self.row, self.w = key, widget, col, row, w


class ToolBar(QWidget):
    """Une barre d'outils (voir l'en-tête du module) : une GRILLE de `cols` × `rows` cases de la taille d'une icône ; un
    élément occupe une case (icône) ou n cases de large (bouton à texte, contrôle), à n'importe quelle place libre.
    Signaux : `layoutChanged()` à la fin d'un geste (taille, largeur d'un contrôle, titre, pivot : l'hôte enregistre),
    `moved(QPoint)` quand la barre a été déplacée hors gestionnaire. Dans un gestionnaire (`self.manager`), les gestes
    de titre et d'éléments lui sont confiés."""

    layoutChanged = Signal()
    moved = Signal(QPoint)

    def __init__(self, title: str = "", cols: int = 3, rows: int = 1, parent=None, orient: str = "h"):
        super().__init__(parent)
        self._title = title
        self.cols, self.rows = max(1, int(cols)), max(1, int(rows))
        self.orient = "v" if orient == "v" else "h"
        self.dock: str | None = None            # bord auquel la barre est clipsée (gestionnaire) : top / bottom / left / right
        self.along = 0                          # position le long de ce bord
        self.manager = None
        self.bar_id = ""
        self._items: dict[str, _Placed] = {}
        self._touch: tuple = ()                 # côtés / coins au contact (gestionnaire, `measure_touch`)
        self._snap_color = ""                   # collée : couleur (fond) de l'élément contre lequel elle est collée
        self._snap_border = ""                  # … et celle de sa bordure (« » : il n'en a pas), son épaisseur
        self._snap_border_w = 0
        self.header_off = False                 # en-tête masqué pour CETTE barre seulement (clic droit)
        self._skip = ""                         # élément tiré : hors de la grille le temps du geste
        self._drop: tuple | None = None         # case visée par un dépôt : (col, ligne, largeur)
        self._free_shown = False                # un élément est tiré quelque part : cases libres en pointillés
        self._target = False                    # barre visée par un dépôt : bordure accent
        self._grid_before = None                # grille d'avant un agrandissement le temps d'un survol
        self._room: dict = {}                   # cases PROVISOIRES des éléments qui glissent pour faire place
        self._anims: dict = {}                  # glissements en cours, par élément
        self.seps: set = set()                  # séparateurs : (col, ligne, « v ») = trait à gauche de la case,
                                                # (col, ligne, « h ») = trait au-dessus
        self._moving = False                    # barre en cours de déplacement : bordure plus claire, ombre forte, 0,94
        self._static = None
        self._static_key = None
        self._hdr = None                        # appui sur le titre : {"ctrl", "start", "off"}
        self._resize = None                     # redimensionnement par un bord : {"mode", "start", "size"}
        self._edit = None
        self._opacity = None
        self.setMouseTracking(True)
        _ALL.add(self)
        self.apply_look()

    # -- Géométrie : tout est multiple d'une case ---------------------------------------------------------------------
    def header_side(self, orient: str | None = None) -> str:
        """Côté de l'en-tête : celui du BORD où la barre est clipsée (demande de l'utilisateur, 2026-11-08 : clipsée en
        bas, l'en-tête est en bas ; à droite, à droite) ; sinon le haut (horizontale) ou la gauche (verticale)."""
        if (orient or self.orient) == "h":
            return "bottom" if self.dock == "bottom" else "top"
        return "right" if self.dock == "right" else "left"

    def origin(self, orient: str | None = None) -> QPoint:
        """Coin haut gauche de la grille. Marges ÉGALES tout autour des cases ; le titre occupe le côté `header_side`."""
        look = LOOK
        bw, m, header = look["border_w"], look["margin"], self.header_px()
        side = self.header_side(orient)
        return QPoint(bw + m + (header if side == "left" else 0), bw + m + (header if side == "top" else 0))

    def frame_px(self, orient: str | None = None) -> tuple[int, int]:
        """Pixels hors des cases, en largeur et en hauteur : bordures, marges et (dans son sens) l'en-tête."""
        look = LOOK
        frame, header = 2 * (look["border_w"] + look["margin"]), self.header_px()
        horizontal = (orient or self.orient) == "h"
        return frame + (0 if horizontal else header), frame + (header if horizontal else 0)

    def grid_size(self, cols: int | None = None, rows: int | None = None, orient: str | None = None) -> QSize:
        """Taille de la barre pour `cols` × `rows` cases : bordure + (titre) + marge + cases + marge + bordure."""
        cols, rows = cols or self.cols, rows or self.rows
        frame_w, frame_h = self.frame_px(orient)
        return QSize(frame_w + cells_px(cols), frame_h + cells_px(rows))

    def natural_size(self, orient: str | None = None) -> QSize:
        return self.grid_size(orient=orient)

    def cell_rect(self, col: int, row: int, w: int = 1) -> QRect:
        origin = self.origin()
        return QRect(origin.x() + col * step(), origin.y() + row * step(), cells_px(w), LOOK["cell"])

    def _title_cells(self, orient: str | None = None) -> int:
        """Cases nécessaires pour que le titre tienne sur la longueur de la barre."""
        look = LOOK
        text = QFontMetrics(look_font("title")).horizontalAdvance(self._title)
        length = 6 + ((12 + 4) if look["grip_on"] else 0) + text + 8
        return max(1, -(-(length - 2 * look["border_w"] - 2 * look["margin"] + look["gap"]) // step()))

    def min_grid(self, orient: str | None = None) -> tuple[int, int]:
        """Plus petite grille permise : aucun élément coupé, le titre entier — sauf un titre VERTICAL (barre « v ») :
        il ne retient pas la hauteur (une rangée vide sous les éléments doit pouvoir partir, demande du 2026-11-03),
        coupé d'un « … » au besoin."""
        cols, rows = 1, 1
        for item in self._items.values():
            if item.key == self._skip:
                continue
            cols, rows = max(cols, item.col + item.w), max(rows, item.row + 1)
        if (orient or self.orient) == "h":
            cols = max(cols, self._title_cells())
        return cols, rows

    def pack(self, cells: dict, cols: int, rows: int, grow: str) -> tuple[int, int]:
        """RETASSE les éléments dans une grille `cols` × `rows` (barre rétrécie) : chacun garde sa case d'origine
        (`cells` : {clé: (col, ligne, largeur)}) si elle tient, sinon il va à la première case libre en ordre de lecture ;
        sans place, la grille gagne une ligne (`grow` = "rows") ou une colonne ("cols"). Rend la grille obtenue."""
        cols = max(cols, max((w for _c, _r, w in cells.values()), default=1))
        placed: list[_Placed] = []
        later = []
        for key in sorted(cells, key=lambda k: (cells[k][1], cells[k][0])):
            item = self._items.get(key)
            if item is None:
                continue
            col, row, w = cells[key]
            item.col, item.row, item.w = col, row, w
            if col + w <= cols and row < rows and not any(_overlap(item, o) for o in placed):
                placed.append(item)
            else:
                later.append(item)
        for item in later:
            while True:
                spot = next(((c, r) for r in range(rows) for c in range(cols - item.w + 1)
                             if not any(_overlap(_Placed("", None, c, r, item.w), o) for o in placed)), None)
                if spot is not None:
                    item.col, item.row = spot
                    placed.append(item)
                    break
                if grow == "rows":
                    rows += 1
                else:
                    cols += 1
        return cols, rows

    def snap(self, width: float, height: float) -> tuple[int, int]:
        """Grille la plus proche d'une taille en pixels, bornée par le contenu."""
        frame_w, frame_h = self.frame_px()
        cols = px_cells(width - frame_w)
        rows = px_cells(height - frame_h)
        min_cols, min_rows = self.min_grid()
        return max(min_cols, min(MAX_CELLS, cols)), max(min_rows, min(MAX_CELLS, rows))

    def set_grid(self, cols: int, rows: int) -> bool:
        """Nouvelle grille (jamais plus petite que le contenu) ; faux si rien n'a changé."""
        min_cols, min_rows = self.min_grid()
        cols, rows = max(min_cols, min(MAX_CELLS, int(cols))), max(min_rows, min(MAX_CELLS, int(rows)))
        if (cols, rows) == (self.cols, self.rows) and self.size() == self.grid_size():
            return False
        self.cols, self.rows = cols, rows
        self._apply_size()
        return True

    def _apply_size(self, animate: bool = False) -> None:
        size = self.grid_size()
        self._place_all(animate)
        if self.size() != size:
            self.setFixedSize(size)
            if self.manager is not None:
                self.manager.bar_resized(self)
        self._static_key = None
        self.update()

    def relayout(self) -> None:
        """Compatibilité : la grille garde au moins le contenu, les éléments sont reposés."""
        min_cols, min_rows = self.min_grid()
        self.cols, self.rows = max(self.cols, min_cols), max(self.rows, min_rows)
        self._apply_size()

    def set_orient(self, orient: str, transpose: bool = True) -> bool:
        """Horizontale (« h ») ou verticale (« v ») : le titre passe en haut / à gauche et la grille est TRANSPOSÉE (une
        barre 3 × 2 devient 2 × 3 : une barre clipsée à gauche reste une colonne) ; un élément large qui ne tient pas à sa
        place transposée va à la première place libre."""
        orient = "v" if orient == "v" else "h"
        if orient == self.orient:
            return False
        self.orient = orient
        if transpose:
            self.seps = {(r, c, "h" if k == "v" else "v") for c, r, k in self.seps}
            items = sorted(self._items.values(), key=lambda i: (i.w, i.col, i.row))
            self.cols, self.rows = self.rows, self.cols
            placed = []
            for item in items:
                item.col, item.row = item.row, item.col
                if any(_overlap(item, other) for other in placed) or item.col + item.w > self.cols:
                    self.cols = max(self.cols, item.w)
                    item.col, item.row = self._first_free(item.w, placed)
                    self.rows = max(self.rows, item.row + 1)
                placed.append(item)
        self.relayout()
        return True

    def layout_snapshot(self) -> tuple:
        return (self.orient, self.cols, self.rows, {k: (i.col, i.row, i.w) for k, i in self._items.items()},
                frozenset(self.seps))

    def apply_snapshot(self, snapshot: tuple) -> None:
        """Remet exactement une disposition retenue (fin d'un aller-retour vers un bord latéral pendant un déplacement)."""
        orient, cols, rows, cells = snapshot[:4]
        if len(snapshot) > 4:
            self.seps = set(snapshot[4])
        self.orient = orient
        self.cols, self.rows = cols, rows
        for key, (col, row, w) in cells.items():
            if key in self._items:
                self._items[key].col, self._items[key].row, self._items[key].w = col, row, w
        self.relayout()

    def set_dock(self, dock: str | None) -> None:
        """Bord de clipsage (gestionnaire) : l'ombre disparaît, les bords redimensionnables changent ; l'en-tête passe du
        côté du bord (les cases suivent)."""
        if dock != self.dock:
            side = self.header_side()
            self.dock = dock
            if self.header_side() != side and self.header_px():
                self.relayout()
            self._static_key = None
            self.update()
            self._sync_shadow()

    def header_px(self) -> int:
        """Épaisseur de l'en-tête : celle des réglages, 0 s'ils les masquent ou si cette barre masque le sien."""
        return 0 if self.header_off else LOOK["header"]

    def set_header_off(self, off: bool) -> None:
        off = bool(off)
        if off != self.header_off:
            self.header_off = off
            self._static_key = None
            self.relayout()
            self.update()

    def _toggle_own_header(self) -> None:
        self.set_header_off(not self.header_off)
        if self.manager is not None:
            self.manager.relayout()
            self.manager.remember()
            self.manager.layoutChanged.emit()
        else:
            self.layoutChanged.emit()

    def header_rect(self) -> QRect:
        bw, header = LOOK["border_w"], self.header_px()
        return {"top": QRect(0, bw, self.width(), header),
                "bottom": QRect(0, self.height() - bw - header, self.width(), header),
                "left": QRect(bw, 0, header, self.height()),
                "right": QRect(self.width() - bw - header, 0, header, self.height())}[self.header_side()]

    def set_touch(self, touch: dict) -> None:
        """Côtés / coins en contact (gestionnaire) : coins carrés, bordure partagée tracée par une seule barre."""
        key = tuple(sorted((k, v if k[0] == "g" else bool(v)) for k, v in (touch or {}).items() if v))
        if key != self._touch:
            self._touch = key
            self._static_key = None
            self.update()

    def _spans(self, touch: dict) -> dict:
        """Côtés collés à une autre barre : {côté: None (tout le côté) | ((début, fin), …) (une partie)}."""
        out = {}
        for side in SIDES:
            parts = touch.get("g" + side[0])
            if not touch.get("s" + side[0]) or not parts:
                continue
            length = self.height() if side in ("left", "right") else self.width()
            whole = min(lo for lo, _ in parts) <= 1 and max(hi for _, hi in parts) >= length - 1
            out[side] = None if whole else parts
        return out

    def _side_strip(self, side: str, lo: int, hi: int, width: int, border_on: dict) -> QRect:
        """Bande de la bordure du côté `side` entre `lo` et `hi` (sans mordre sur les bordures perpendiculaires)."""
        if side in ("top", "bottom"):
            lo = max(lo, width if border_on["left"] else 0)
            hi = min(hi, self.width() - (width if border_on["right"] else 0))
            y = 0 if side == "top" else self.height() - width
            return QRect(lo, y, max(0, hi - lo), width)
        lo = max(lo, width if border_on["top"] else 0)
        hi = min(hi, self.height() - (width if border_on["bottom"] else 0))
        x = 0 if side == "left" else self.width() - width
        return QRect(x, lo, width, max(0, hi - lo))

    def _contacts(self, touch: dict, spans: dict, edges: bool):
        """(côté, parties) des côtés collés que CETTE barre trace : contre une autre barre, celle qui garde la bordure
        commune (pas de « n* ») ; avec `edges`, aussi les côtés plaqués contre un bord de la zone."""
        for side in SIDES:
            length = self.height() if side in ("left", "right") else self.width()
            if edges and touch.get("e" + side[0]):
                yield side, ((0, length),)
            elif side in spans and not touch.get("n" + side[0]):
                yield side, ((0, length),) if spans[side] is None else spans[side]

    def _paint_side_color(self, painter: QPainter, touch: dict, spans: dict, border_on: dict) -> None:
        """« Clipsée : comportement du côté collé » = couleur de bordure : UN trait de cette couleur le long de la partie
        collée (la bordure du voisin y est ôtée par le gestionnaire ; entre deux barres, une seule le trace)."""
        width, color = max(1, LOOK["border_w"]), QColor(LOOK["snap_side_color"])
        for side, parts in self._contacts(touch, spans, edges=True):
            for lo, hi in parts:
                painter.fillRect(self._side_strip(side, lo, hi, width, border_on), color)

    def _paint_snap_separators(self, painter: QPainter, touch: dict, spans: dict) -> None:
        """Séparateur entre deux barres collées (réglage « Séparateur entre barres collées ») : un trait de la couleur
        des séparateurs, le long de la partie collée, à hauteur des cases (même retrait que ceux de la grille)."""
        look = LOOK
        origin, inset = self.origin(), max(3, look["cell"] // 6)
        grid = QRect(origin.x(), origin.y(), cells_px(self.cols), cells_px(self.rows))
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(look["separator"]))
        for side, parts in self._contacts(touch, spans, edges=False):
            for lo, hi in parts:
                if side in ("left", "right"):
                    lo, hi = max(lo, grid.top() + inset), min(hi, grid.top() + grid.height() - inset)
                    x = 0 if side == "left" else self.width() - 1
                    rect = QRectF(x, lo, 1, hi - lo)
                else:
                    lo, hi = max(lo, grid.left() + inset), min(hi, grid.left() + grid.width() - inset)
                    y = 0 if side == "top" else self.height() - 1
                    rect = QRectF(lo, y, hi - lo, 1)
                if hi > lo:
                    painter.drawRect(rect)
        painter.restore()

    def borderless(self) -> bool:
        """Collée contre un élément SANS bordure (demande de l'utilisateur, 2026-11-04 : « la barre est attachée à un
        élément qui n'a pas de bordure : il ne devrait pas y en avoir non plus sur la barre ») : aucune bordure, dès
        qu'un réglage de bordure de barre clipsée est allumé (« pas de bordure du côté collé » ou « bordure de la
        couleur de l'élément voisin »). Pas pendant un geste (bordure d'accent / de déplacement)."""
        look = LOOK
        return bool(self._snap_color and not self._snap_border and not self._target and not self._moving
                    and (look["snap_side"] == "no_border" or look["snap_border_match"]))

    def set_snap_color(self, color: str, border: str = "", border_w: int = 0) -> None:
        """Couleurs de l'élément contre lequel la barre est collée (gestionnaire) : son fond, sa bordure et l'épaisseur
        de celle-ci ; « » : aucune."""
        if (color, border, border_w) != (self._snap_color, self._snap_border, self._snap_border_w):
            self._snap_color, self._snap_border, self._snap_border_w = color, border, border_w
            self._static_key = None
            self.update()

    # -- Cases ---------------------------------------------------------------------------------------------------------
    def free(self, col: int, row: int, w: int, ignore: str = "", grow: bool = False) -> bool:
        """La zone de `w` cases à (col, ligne) est libre (sauf l'élément `ignore`) ; `grow` : la grille peut grandir."""
        if col < 0 or row < 0 or (not grow and (col + w > self.cols or row >= self.rows)):
            return False
        for item in self._items.values():
            if item.key in (ignore, self._skip):
                continue
            if row == item.row and col < item.col + item.w and item.col < col + w:
                return False
        return True

    def nearest_free(self, col: int, row: int, w: int, ignore: str = "") -> tuple[int, int]:
        """Place libre de `w` cases la plus proche de (col, ligne) ; à défaut, juste derrière la grille (elle grandira)."""
        best, best_d = None, None
        for c in range(0, max(1, self.cols - w + 1)):
            for r in range(self.rows):
                if self.free(c, r, w, ignore):
                    d = abs(c - col) + abs(r - row)
                    if best_d is None or d < best_d:
                        best, best_d = (c, r), d
        if best is not None:
            return best
        if self.orient == "h":                             # pleine : la grille s'allongera vers la droite…
            return self.cols, max(0, min(row, self.rows - 1))
        return max(0, min(col, self.cols - w)), self.rows  # … ou vers le bas (barre verticale)

    def _first_free(self, w: int, among=None) -> tuple[int, int]:
        """Première place libre en ordre de lecture ; à défaut, la grille s'allonge (vers la droite d'une barre
        horizontale, vers le bas d'une barre verticale)."""
        others = list(self._items.values()) if among is None else among
        probe = _Placed("", None, 0, 0, w)
        for r in range(self.rows):
            for c in range(0, max(0, self.cols - w) + 1):
                probe.col, probe.row = c, r
                if c + w <= self.cols and not any(_overlap(probe, o) for o in others if o.key != self._skip):
                    return c, r
        return (self.cols, 0) if self.orient == "h" else (0, self.rows)

    def add_item(self, key: str, widget: QWidget, col: int | None = None, row: int | None = None, w: int | None = None,
                 *_compat, **_kw) -> QWidget:
        """Pose `widget` (il devient un enfant de la barre) à (col, ligne) si c'est libre, sinon à la première place libre ;
        la grille grandit s'il le faut. `w` : largeur en cases (défaut : celle de l'élément ; jamais moins que son contenu)."""
        widget.setParent(self)
        self._items.pop(key, None)
        w = max(need_cells(widget), int(w) if w else default_cells(widget))
        if col is None or row is None or not self.free(int(col), int(row), w, grow=True):
            col, row = self._first_free(w)
        item = _Placed(key, widget, int(col), int(row), w)
        self._items[key] = item
        self.cols, self.rows = max(self.cols, item.col + w), max(self.rows, item.row + 1)
        self._sync_width(item)
        widget.show()
        self.relayout()
        return widget

    def move_item(self, key: str, col: int, row: int) -> None:
        item = self._items[key]
        item.col, item.row = col, row
        self.relayout()

    def detach_item(self, key: str) -> _Placed | None:
        """Retire un élément (son widget reste un enfant, à reposer ailleurs) ; la grille garde sa taille."""
        return self._items.pop(key, None)

    def item(self, key: str) -> QWidget | None:
        placed = self._items.get(key)
        return placed.widget if placed else None

    def keys(self) -> list[str]:
        """Clés des éléments en ordre de lecture."""
        return [i.key for i in sorted(self._items.values(), key=lambda i: (i.row, i.col))]

    @property
    def order(self) -> list[str]:
        return self.keys()

    def cell_of(self, key: str) -> tuple[int, int, int]:
        item = self._items[key]
        return item.col, item.row, item.w

    def item_rects(self) -> list:
        return [(k, self._items[k].widget.geometry()) for k in self.keys() if k != self._skip]

    def _sync_width(self, item: _Placed) -> None:
        if hasattr(item.widget, "bar_width"):
            item.widget.bar_width = cells_px(item.w)

    def _place(self, item: _Placed, animate: bool = False) -> None:
        if item.key == self._skip:
            return
        col, row = self._room.get(item.key, (item.col, item.row))
        rect = self.cell_rect(col, row, item.w)
        widget = item.widget
        anim = self._anims.get(item.key)
        if anim is not None and anim.endValue() == rect.topLeft():
            return                                     # déjà en route vers sa case
        if anim is not None:
            anim.stop()
            self._anims.pop(item.key, None)
        if widget.geometry() == rect:
            return
        ms = LOOK["slide_ms"]
        if not animate or not ms or widget.size() != rect.size() or not self.isVisible():
            widget.setGeometry(rect)
            return
        anim = QPropertyAnimation(widget, b"pos", self)  # il GLISSE vers sa nouvelle case
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setEndValue(rect.topLeft())
        anim.finished.connect(lambda k=item.key: self._anims.pop(k, None))
        self._anims[item.key] = anim
        anim.start()

    def finish_slides(self) -> None:
        """Glissements en cours : chacun posé tout de suite à sa case (fin d'un geste)."""
        for key, anim in list(self._anims.items()):
            end = anim.endValue()
            anim.stop()
            placed = self._items.get(key)
            if placed is not None:
                placed.widget.move(end)
        self._anims.clear()

    def _make_room(self, col: int, row: int, w: int) -> tuple[dict, int, int]:
        """Cases provisoires pour qu'un élément de `w` cases tienne en (col, ligne) : les éléments qui sont DÉJÀ avant
        cette case (ordre de lecture) et ne la gênent pas restent ; les autres GLISSENT, chacun à la première case libre
        à partir de la sienne (la grille gagne une ligne s'il le faut). Rend ({clé: (col, ligne)}, colonnes, lignes)."""
        cols, rows = max(self.cols, col + w), max(self.rows, row + 1)
        placed = [_Placed("", None, col, row, w)]
        room = {}
        others = sorted((i for i in self._items.values() if i.key != self._skip), key=lambda i: (i.row, i.col))
        for item in others:
            probe = _Placed(item.key, None, item.col, item.row, item.w)
            if item.col + item.w <= cols and not any(_overlap(probe, o) for o in placed):
                placed.append(probe)
                continue
            r, c = item.row, item.col + 1
            while True:
                if c + item.w > cols:
                    r, c = r + 1, 0
                    if r >= rows:
                        rows = r + 1
                probe.col, probe.row = c, r
                if not any(_overlap(probe, o) for o in placed):
                    break
                c += 1
            placed.append(probe)
            room[item.key] = (probe.col, probe.row)
        return room, cols, rows

    def commit_room(self) -> None:
        """Dépôt : les éléments qui ont glissé gardent leur nouvelle case."""
        for key, (col, row) in self._room.items():
            if key in self._items:
                self._items[key].col, self._items[key].row = col, row
        self._room = {}
        self.finish_slides()

    def _place_all(self, animate: bool = False) -> None:
        for item in self._items.values():
            self._place(item, animate)
        self._join_controls()

    def _join_controls(self) -> None:
        """Deux contrôleurs qui se touchent (ou séparés de `palette_bar_join_gap` px au plus) : pas d'arrondi entre eux.
        Côte à côte : les coins du côté commun ; l'un sur l'autre : les coins que le voisin couvre."""
        look = LOOK
        controls = [i for i in self._items.values() if isinstance(i.widget, PaletteControl) and i.key != self._skip]
        joins = {i.key: set() for i in controls}
        if look["gap"] <= look["join_gap"]:
            for a in controls:
                for b in controls:
                    if a is b:
                        continue
                    if a.row == b.row and b.col == a.col + a.w:              # b juste à droite de a
                        joins[a.key] |= {"tr", "br"}
                        joins[b.key] |= {"tl", "bl"}
                    elif b.row == a.row + 1 and b.col < a.col + a.w and a.col < b.col + b.w:     # b juste sous a
                        if b.col <= a.col:
                            joins[a.key].add("bl")
                        if b.col + b.w >= a.col + a.w:
                            joins[a.key].add("br")
                        if a.col <= b.col:
                            joins[b.key].add("tl")
                        if a.col + a.w >= b.col + b.w:
                            joins[b.key].add("tr")
        for item in controls:
            item.widget.set_joined(joins[item.key])

    # -- Enregistrement de la disposition ---------------------------------------------------------------------------
    def layout_state(self) -> dict:
        state = {"cols": self.cols, "rows": self.rows,
                 "items": {k: [i.col, i.row, i.w] for k, i in self._items.items()}}
        if self.seps:
            state["seps"] = [list(s) for s in sorted(self.seps)]
        if self.header_off:
            state["header_off"] = True
        return state

    def set_seps(self, seps) -> None:
        clean = set()
        for entry in seps or ():
            try:
                col, row, kind = int(entry[0]), int(entry[1]), str(entry[2])
            except (TypeError, ValueError, IndexError):
                continue
            if kind in ("v", "h"):
                clean.add((col, row, kind))
        if clean != self.seps:
            self.seps = clean
            self._static_key = None
            self.update()

    def boundary_at(self, pos: QPoint):
        """Limite entre deux cases sous `pos` (clic droit) : (col, ligne, « v ») entre deux cases côte à côte (barre
        horizontale), (col, ligne, « h ») entre deux cases l'une sur l'autre (barre verticale) ; None au bord de la grille."""
        origin, stp = self.origin(), step()
        fx, fy = (pos.x() - origin.x() + LOOK["gap"] / 2) / stp, (pos.y() - origin.y() + LOOK["gap"] / 2) / stp
        col, row = int(fx // 1), int(fy // 1)
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return None
        if self.orient == "h":
            col += 1 if fx - col >= 0.5 else 0
            return (col, row, "v") if 0 < col < self.cols else None
        row += 1 if fy - row >= 0.5 else 0
        return (col, row, "h") if 0 < row < self.rows else None

    def contextMenuEvent(self, event):
        """Clic droit : ajouter / retirer un séparateur entre deux icônes (menu contextuel de fm_theme)."""
        from fm_theme.menu import Menu
        pos = event.pos()
        boundary = self.boundary_at(pos)
        menu = Menu(self, key="palette:bar", editable=False)
        if boundary is not None:
            if boundary in self.seps:
                menu.addAction("Retirer le séparateur", lambda b=boundary: self._toggle_sep(b))
            else:
                menu.addAction("Ajouter un séparateur ici", lambda b=boundary: self._toggle_sep(b))
        if self.seps:
            menu.addAction("Retirer tous les séparateurs", lambda: self._clear_seps())
        if not menu.actions():
            action = menu.addAction("Clic droit entre deux icônes : séparateur")
            action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Masquer les en-têtes" if LOOK.get("header_shown", True) else "Afficher les en-têtes",
                       toggle_headers)
        if LOOK.get("header_shown", True):
            menu.addAction("Afficher l'en-tête de cette barre" if self.header_off else "Masquer l'en-tête de cette barre",
                           self._toggle_own_header)
        menu.exec(event.globalPos())
        event.accept()

    def _toggle_sep(self, boundary) -> None:
        seps = set(self.seps)
        seps.symmetric_difference_update({boundary})
        self.set_seps(seps)
        if self.manager is not None:
            self.manager.status("Séparateur ajouté" if boundary in seps else "Séparateur retiré")
        self.layoutChanged.emit()

    def _clear_seps(self) -> None:
        self.set_seps(())
        self.layoutChanged.emit()

    # -- Habillage --------------------------------------------------------------------------------------------------
    def apply_look(self) -> None:
        """L'habillage commun a changé : tailles, ombre, éléments (sur place)."""
        key = LOOK["key"]
        if key == getattr(self, "_look_key", None):
            return
        self._look_key = key
        self._static_key = None
        for placed in self._items.values():
            restyle = getattr(placed.widget, "restyle", None)
            if restyle is not None:
                restyle()
            placed.w = max(placed.w, need_cells(placed.widget))
        self.relayout()
        self._sync_shadow()
        self.update()

    def shadow_now(self):
        """Ombre du moment : barre flottante seulement ; plus forte pendant le déplacement (spec § 4)."""
        look = LOOK["shadow"]
        if look is None or self.dock:
            return None
        if not self._moving:
            return look
        strong = {side: _alpha(color, min(255, round(QColor(color).alpha() * 1.6))).name(QColor.NameFormat.HexArgb)
                  for side, color in look["colors"].items()}
        return {"on": look["on"], "colors": strong, "size": round(look["size"] * 1.6)}

    def _sync_shadow(self) -> None:
        if self.parentWidget() is None:
            return
        underlay = attach_shadow(self, self.shadow_now, lambda: self._corner_radius())
        underlay.sync()
        underlay.update()

    def _corner_radius(self) -> dict:
        touch = dict(self._touch)
        return {c: (0 if touch.get(flag) else LOOK["radius"][c]) for c, flag in zip(CORNERS, ("tl", "tr", "br", "bl"))}

    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        if title != self._title:
            self._title = title
            self._static_key = None
            self.relayout()
            self.update()

    def set_moving(self, moving: bool) -> None:
        """Barre tirée : bordure plus claire, ombre forte, opacité 0,94 (spec § 4)."""
        if moving == self._moving:
            return
        self._moving = moving
        self._static_key = None
        if moving:
            self._opacity = QGraphicsOpacityEffect(self)
            self._opacity.setOpacity(DRAG_OPACITY)
            self.setGraphicsEffect(self._opacity)
        else:
            self.setGraphicsEffect(None)
            self._opacity = None
        self._sync_shadow()
        self.update()

    def set_target(self, on: bool, drop: tuple | None = None) -> None:
        """Barre visée par un dépôt : bordure accent et case de dépôt (col, ligne, largeur) ; rien si inchangé. Une case
        hors de la grille l'agrandit le temps du survol (pas avant : la barre ne bouge pas pendant le geste)."""
        if on != self._target or drop != self._drop:
            self._target, self._drop = on, drop
            if drop is not None:                           # les éléments GLISSENT pour lui faire place (animés)
                if self._grid_before is None:
                    self._grid_before = (self.cols, self.rows)
                self.cols, self.rows = self._grid_before
                self._room, cols, rows = self._make_room(*drop)
                self.cols, self.rows = cols, rows
                self._apply_size(animate=True)
            elif self._grid_before is not None:            # plus visée : chacun revient, la grille d'avant
                self.cols, self.rows = self._grid_before
                self._grid_before = None
                self._room = {}
                min_cols, min_rows = self.min_grid()
                self.cols, self.rows = max(self.cols, min_cols), max(self.rows, min_rows)
                self._apply_size(animate=True)
            self._static_key = None
            self.update()

    def show_free(self, on: bool) -> None:
        """Un élément est tiré : les cases libres apparaissent en pointillés."""
        if on != self._free_shown:
            self._free_shown = on
            self._static_key = None
            self.update()

    def set_skip(self, key: str) -> None:
        """Élément tiré : sa case est libre le temps du geste (le widget est posé hors de vue SANS être caché : il garde
        la souris)."""
        if key == self._skip:
            return
        old, self._skip = self._skip, key
        if key and key in self._items:
            self._items[key].widget.move(-10000, -10000)
        if old and old in self._items:
            self._place(self._items[old])
        self._static_key = None
        self.update()

    # -- Peinture ---------------------------------------------------------------------------------------------------
    def _paint_static(self, painter: QPainter) -> None:
        """Cadre, titre, cases libres et case de dépôt : une image, refaite seulement si l'un d'eux change."""
        look = LOOK
        touch = dict(self._touch)
        # côté collé (bord de la zone « e », autre barre « s ») : sans bordure au réglage, des DEUX côtés
        # (contre une autre barre : seulement le long de la partie collée, `_spans`, demande du 2026-11-03)
        spans = self._spans(touch)
        stuck = {side: touch.get("e" + side[0]) or (side in spans and spans[side] is None) for side in SIDES}
        partial = {side for side, parts in spans.items() if parts is not None}
        shared = {side: touch.get("n" + side[0]) and side not in partial for side in SIDES}   # (partiel : ôtée après)
        border_w = look["border_w"]
        match = look["snap_border_match"] and self._snap_border and not self._target and not self._moving
        if match:                                          # voisin à bordure : la barre en a une, de sa couleur
            border_w = max(border_w, self._snap_border_w or 1)
            border_on = {side: not stuck[side] and not shared[side] for side in SIDES}
        elif self.borderless():                            # voisin SANS bordure : la barre n'en a pas non plus
            border_on = dict.fromkeys(SIDES, False)
        else:
            border_on = {side: look["border_on"][side] and not shared[side]
                         and not (look["snap_border_off"] and stuck[side]) for side in SIDES}
        snap = self._snap_color
        if self._target:
            colors = dict.fromkeys(SIDES, look["drop"])
        elif self._moving:
            colors = dict.fromkeys(SIDES, look["drag_border"])
        elif match:
            colors = dict.fromkeys(SIDES, self._snap_border)
        else:
            colors = look["border"]
        fill = snap if snap and look["snap_bg_color"] else look["bg"]
        _paint_bordered_vector(painter, QRect(self.rect()), self._corner_radius(), border_on, border_w, colors, fill)
        if not self._target and not self._moving:
            for side in partial:                           # bordure ôtée le long de la partie collée seulement
                if not border_on[side] or not (match or look["snap_border_off"] or touch.get("n" + side[0])):
                    continue
                parts = spans[side]
                for lo, hi in parts:
                    painter.fillRect(self._side_strip(side, lo, hi, border_w, border_on), QColor(fill))
            if look["snap_side"] == "color" and not match:
                self._paint_side_color(painter, touch, spans, border_on)
            if look["snap_separator"]:
                self._paint_snap_separators(painter, touch, spans)
        header = self.header_rect()
        header_bg = snap if snap and look["snap_header_color"] else look["header_bg"]
        if header.width() > 0 and header.height() > 0 and QColor(header_bg).alpha():
            painter.save()                                 # fond du titre, dans les coins arrondis de la barre
            inset = look["border_w"]
            painter.setClipPath(_rounded_rect_path(self.rect().adjusted(inset, inset, -inset, -inset),
                                                   self._corner_radius()))
            band = QRect(header)
            side = self.header_side()
            if side == "top":
                band.setTop(0)
            elif side == "bottom":
                band.setBottom(self.height() - 1)
            elif side == "left":
                band.setLeft(0)
            else:
                band.setRight(self.width() - 1)
            painter.fillRect(band.intersected(self.rect().adjusted(inset, inset, -inset, -inset)), QColor(header_bg))
            painter.restore()
        if header.width() > 0 and header.height() > 0:
            painter.save()
            if self.orient == "h":
                painter.translate(header.left(), header.top())
                length = header.width()
            else:                                          # écrit de bas en haut : on tourne de -90° autour du bas
                painter.translate(header.left(), header.bottom() + 1)
                painter.rotate(-90)
                length = header.height()
            thick = self.header_px()
            x = 6
            top = min(6, max(0, thick - 12))               # padding haut de 6 px (prototype), la ligne en dessous
            if self.header_side() in ("bottom", "right"):  # en-tête en bas / à droite : le padding passe dehors
                top = 0
                thick -= min(6, max(0, self.header_px() - 12))
            if look["grip_on"]:
                _dots(painter, QRectF(x, top, 12, thick - top), look["grip_ink"])     # (laisse le crayon à « aucun »)
                x += 12 + 4
            painter.setFont(look_font("title"))
            painter.setPen(QColor(look["title_ink"]))
            align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[look["title_align"]]
            room = max(0, length - x - 8)
            painter.drawText(QRect(x, top, room, thick - top), Qt.AlignVCenter | align,
                             painter.fontMetrics().elidedText(self._title, Qt.ElideRight, room))
            painter.restore()
        radius = look["cell_radius"]
        if self._free_shown:                               # cases libres pendant un déplacement d'élément
            painter.setPen(QPen(QColor(look["bar_handle_ink"]), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            for row in range(self.rows):
                for col in range(self.cols):
                    if self.free(col, row, 1):
                        painter.drawRoundedRect(QRectF(self.cell_rect(col, row)).adjusted(.5, .5, -.5, -.5), radius, radius)
        if self.seps:                                      # séparateurs : un trait dans l'écart entre deux cases
            gap, inset = look["gap"], max(3, look["cell"] // 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["separator"]))
            for col, row, kind in self.seps:
                cell = self.cell_rect(col, row)
                if kind == "v":
                    x = cell.left() - gap / 2 - 0.5
                    painter.drawRect(QRectF(x, cell.top() + inset, 1, cell.height() - 2 * inset))
                else:
                    y = cell.top() - gap / 2 - 0.5
                    painter.drawRect(QRectF(cell.left() + inset, y, cell.width() - 2 * inset, 1))
        if self._drop is not None:                         # case de dépôt : pointillés accent, fond accent à 8 %
            col, row, w = self._drop
            painter.setPen(QPen(QColor(look["drop"]), 1.5, Qt.DashLine))
            painter.setBrush(_alpha(look["drop"], 20))
            painter.drawRoundedRect(QRectF(self.cell_rect(col, row, w)).adjusted(.75, .75, -.75, -.75), radius, radius)

    def paintEvent(self, event):
        look = LOOK
        dpr = self.devicePixelRatioF()
        occupied = tuple(sorted((i.col, i.row, i.w) for i in self._items.values() if i.key != self._skip)) \
            if self._free_shown else ()
        key = (self.width(), self.height(), dpr, self._title, self.orient, self.dock, self._touch, self._snap_color,
               self._snap_border, self._snap_border_w, self.header_off,
               self._target,
               self._moving, self._drop, self._free_shown, occupied, tuple(sorted(self.seps)), look["key"])
        if key != self._static_key:
            self._static_key = key
            self._static = _render(self.size(), dpr, self._paint_static)
        QPainter(self).drawPixmap(0, 0, self._static)

    # -- Éléments : déplacement (confié au gestionnaire) et largeur des contrôles, en cases --------------------------
    def dragging(self, widget: QWidget) -> bool:
        return self.manager is not None and self.manager.item_dragging(widget)

    def begin_drag(self, widget: QWidget, global_pos: QPoint) -> None:
        key = getattr(widget, "palette_key", "")
        if self.manager is not None and key in self._items:
            widget._manager = self.manager
            self.manager.begin_item_drag(self, self._items[key], global_pos)

    def drag_to(self, global_pos: QPoint) -> None:
        if self.manager is not None:
            self.manager.item_drag_to(global_pos)

    def end_drag(self) -> None:
        if self.manager is not None:
            self.manager.end_item_drag()

    def set_item_width(self, widget, width: float) -> None:
        """Poignée de droite d'un contrôle : largeur accrochée à la grille (cases entières, 120 à 520 px, jamais sous son
        contenu ni sur un voisin) ; la grille s'élargit s'il le faut."""
        item = next((i for i in self._items.values() if i.widget is widget), None)
        if item is None:
            return
        span = max(need_cells(widget), min(px_cells(CONTROL_MAX_WIDTH), px_cells(width)))
        while span > item.w and not self.free(item.col, item.row, span, item.key, grow=True):
            span -= 1
        if span == item.w:
            return
        item.w = span
        self._sync_width(item)
        self.cols = max(self.cols, item.col + span)
        self.relayout()
        if self.manager is not None:
            self.manager.widths[item.key] = cells_px(span)
            self.manager.status(f"{getattr(widget, 'label', item.key)} : largeur {cells_px(span)} px ({span} cases)")

    def end_item_width(self, widget) -> None:
        self.layoutChanged.emit()

    # -- Bords (redimensionner, accroché à la grille), titre (déplacer, renommer, pivoter) ---------------------------
    def _edge(self, pos: QPoint) -> str:
        """Bord sous `pos` : « h » (droit), « v » (bas), « hv » (coin), « -h » / « -v » (gauche / haut d'une barre clipsée
        à droite / en bas : le bord qui ne touche pas la fenêtre) ; vide sinon. Un bord plaqué contre la fenêtre ne
        se tire pas."""
        zone = max(LOOK["margin"] - 1, 4)
        right = pos.x() >= self.width() - zone and self.dock != "right"
        left = pos.x() < zone and self.dock == "right"
        bottom = pos.y() >= self.height() - zone and self.dock != "bottom"
        top = pos.y() < zone and self.dock == "bottom"
        if left:
            return "-hv" if bottom else "-h"
        if top:
            return "-vh" if right else "-v"
        return "hv" if right and bottom else "h" if right else "v" if bottom else ""

    _CURSORS = {"h": Qt.SizeHorCursor, "-h": Qt.SizeHorCursor, "v": Qt.SizeVerCursor, "-v": Qt.SizeVerCursor,
                "hv": Qt.SizeFDiagCursor, "-hv": Qt.SizeBDiagCursor, "-vh": Qt.SizeBDiagCursor}

    def grab_at(self, pos: QPoint) -> bool:
        """`pos` saisit la barre (la déplacer, la centrer, la pivoter) : son en-tête ; sans en-tête, sa TRANCHE (la marge
        libre autour des cases : le bord qui redimensionne reste au redimensionnement)."""
        if self.header_px() > 0:
            return self.header_rect().contains(pos)
        return self.rect().contains(pos) and not self._edge(pos)

    def _ctrl_cursor(self, pos: QPoint):
        """Ctrl au-dessus d'une barre clipsée : flèche du côté où ses barres vont se plaquer (Ctrl + clic milieu)."""
        if not self.dock:
            return None
        side = self.side_at(pos)
        if side:
            return arrow_cursor({"left": "left", "right": "right", "top": "up", "bottom": "down"}[side])
        if self.grab_at(pos):
            return arrow_cursor("center")
        return None

    def side_at(self, pos: QPoint) -> str:
        """Tranche sous `pos` : « left » / « right » (barre horizontale), « top » / « bottom » (barre verticale)."""
        zone = max(LOOK["margin"] + LOOK["border_w"], 6)
        if self.orient == "h":
            return "left" if pos.x() < zone else "right" if pos.x() >= self.width() - zone else ""
        return "top" if pos.y() < zone else "bottom" if pos.y() >= self.height() - zone else ""

    def mousePressEvent(self, event):
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        pos = event.position().toPoint()
        if ctrl and self.dock and self.manager is not None and event.button() == Qt.MiddleButton:
            side = self.side_at(pos)                   # Ctrl + clic milieu : sur une tranche, tout pousser de ce côté ;
            if side or self.grab_at(pos):                               # sur l'en-tête, centrer (fenêtre entière)
                self.manager.align_edge(self.dock, "end" if side in ("right", "bottom") else
                                        "start" if side else "center")
                event.accept()
                return
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        mode = self._edge(pos)
        if mode:
            self._resize = {"mode": mode, "start": event.globalPosition().toPoint(), "size": self.size(),
                            "grid": (self.cols, self.rows), "cells": {k: (i.col, i.row, i.w) for k, i in self._items.items()},
                            "last": None}
            event.accept()
            return
        if self.grab_at(pos):
            ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
            start = event.globalPosition().toPoint()
            self._hdr = {"ctrl": ctrl, "start": start, "off": start - self.pos()}
            if not ctrl and self.manager is not None:
                self.manager.begin_bar_drag(self, start)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-clic sur le titre d'une barre flottante : elle pivote (une barre clipsée suit son bord)."""
        if event.button() == Qt.LeftButton and self.grab_at(event.position().toPoint()):
            if self.dock is None and self.set_orient("v" if self.orient == "h" else "h"):
                if self.manager is not None:
                    self.manager.bar_resized(self)
                self.layoutChanged.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        global_pos = event.globalPosition().toPoint()
        if self._resize is not None:
            drag = self._resize
            delta = global_pos - drag["start"]
            mode = drag["mode"]
            width = drag["size"].width() + (delta.x() if "h" in mode and not mode.startswith("-h") else
                                            -delta.x() if mode.startswith("-h") else 0)
            height = drag["size"].height() + (delta.y() if "v" in mode and not mode.startswith("-v") else
                                              -delta.y() if mode.startswith("-v") else 0)
            frame_w, frame_h = self.frame_px()
            cols = px_cells(width - frame_w) if "h" in mode else drag["grid"][0]
            rows = px_cells(height - frame_h) if "v" in mode else drag["grid"][1]
            title = self._title_cells()                # le titre entier ; la largeur d'un élément ; sinon tout retasse
            cols, rows = max(1, min(MAX_CELLS, cols)), max(1, min(MAX_CELLS, rows))
            if self.orient == "h":                     # (titre vertical : coupé d'un « … », voir `min_grid`)
                cols = max(cols, title)
            if (cols, rows) != drag["last"]:
                drag["last"] = (cols, rows)
                before = (self.cols, self.rows, self.layout_snapshot()[3])
                self.cols, self.rows = self.pack(drag["cells"], cols, rows, "rows" if "h" in mode else "cols")
                if (self.cols, self.rows, self.layout_snapshot()[3]) != before:
                    self._apply_size()
                    if self.manager is not None:
                        self.manager.status(f"« {self._title} » : {self.cols} × {self.rows} cases")
            event.accept()
            return
        if self._hdr is not None:
            if self._hdr["ctrl"] is True and self.manager is not None and (
                    global_pos - self._hdr["start"]).manhattanLength() >= QApplication.startDragDistance():
                self._hdr["ctrl"] = "solo"                 # Ctrl + glisser : la barre part SEULE (sans ses liées)
                self.manager.begin_bar_drag(self, self._hdr["start"], linked=False)
            if self._hdr["ctrl"] == "solo":
                self.manager.bar_drag_to(self, global_pos)
            elif not self._hdr["ctrl"]:
                if self.manager is not None:
                    self.manager.bar_drag_to(self, global_pos)
                else:
                    parent = self.parentWidget()
                    target = global_pos - self._hdr["off"]
                    if parent is not None:
                        target.setX(max(0, min(parent.width() - self.width(), target.x())))
                        target.setY(max(0, min(parent.height() - self.height(), target.y())))
                    self.move(target)
            event.accept()
            return
        if not event.buttons():
            pos = event.position().toPoint()
            mode = self._edge(pos)
            arrow = self._ctrl_cursor(pos) if QApplication.keyboardModifiers() & Qt.ControlModifier else None
            if arrow is not None:
                self.setCursor(arrow)
            elif mode:
                self.setCursor(self._CURSORS[mode])
            elif self.grab_at(pos):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize is not None:
            drag, self._resize = self._resize, None
            if (self.cols, self.rows) != drag["grid"] or {k: (i.col, i.row, i.w) for k, i in self._items.items()} \
                    != drag["cells"]:
                self.layoutChanged.emit()
            event.accept()
            return
        if self._hdr is not None:
            hdr, self._hdr = self._hdr, None
            if hdr["ctrl"] is True:                        # Ctrl + clic sans glisser : renommer
                self.start_rename()
            elif self.manager is not None:
                self.manager.end_bar_drag(self)
            else:
                self.moved.emit(self.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- Renommer : Ctrl + clic sur le titre ------------------------------------------------------------------------
    def start_rename(self) -> None:
        """Zone de saisie des réglages à la place du titre ; Entrée ou clic ailleurs valide, Échap annule, un texte vide
        ne change rien."""
        if self._edit is not None:
            return
        from fm_theme.cells import _TextField
        header = self.header_rect()
        edit = _TextField(self._title, width=110)
        edit.setParent(self)
        if self.orient == "h":
            edit.move(6, header.top() + max(0, (header.height() + LOOK["margin"] - edit.height()) // 2))
        else:
            edit.move(header.left(), LOOK["margin"])
        edit.installEventFilter(self)
        edit.editingFinished.connect(self._commit_rename)
        edit.show()
        edit.raise_()
        edit.setFocus()
        edit.selectAll()
        self._edit = edit

    def eventFilter(self, obj, event):
        if obj is self._edit:
            if event.type() == QEvent.ShortcutOverride:
                event.accept()
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._end_rename(commit=False)
                return True
        return super().eventFilter(obj, event)

    def _commit_rename(self) -> None:
        self._end_rename(commit=True)

    def _end_rename(self, commit: bool) -> None:
        edit, self._edit = self._edit, None
        if edit is None:
            return
        text = edit.text().strip()
        edit.hide()
        edit.setParent(None)
        edit.deleteLater()
        if commit and text and text != self._title:
            self.set_title(text)
            if self.manager is not None:
                self.manager.status(f"Barre renommée « {text} »")
            self.layoutChanged.emit()


def _overlap(a: _Placed, b: _Placed) -> bool:
    return a.row == b.row and a.col < b.col + b.w and b.col < a.col + a.w


GridPalette = ToolBar                       # ancien nom : mêmes usages pour les modules


def restyle_palettes_in(root: QWidget | None, settings: dict) -> None:
    """Habillage des barres changé (section Palette de l'éditeur, preset) : pose l'habillage commun et refait TOUTES
    les barres vivantes SUR PLACE (elles le partagent), seulement si une valeur a changé. Registre plutôt que
    `findChildren(root)` : sur la fenêtre de réglages entière (~24 000 widgets) le parcours coûtait plus que le travail.
    `root` n'est là que pour la signature commune des `restyle_*_in`."""
    if set_look(settings):
        managers = []
        for palette in list(_ALL):
            try:
                palette.apply_look()
                if palette.manager is not None and palette.manager not in managers:
                    managers.append(palette.manager)
            except RuntimeError:                      # widget déjà détruit
                _ALL.discard(palette)
        for manager in managers:                      # contacts et couleur de l'élément voisin (barres clipsées)
            try:
                manager.relayout()
            except RuntimeError:
                pass


def sample_palette(title: str = "Créer", parent=None, cols: int = 6, rows: int = 2) -> ToolBar:
    """Barre d'exemple (tests) : six icônes, un contrôle « Opacité »."""
    palette = ToolBar(title, cols, rows, parent)
    for kind in ("square", "triangle", "image", "table", "pen", "circle"):
        button = PaletteButton(kind, kind, demo_glyph(kind), palette)
        palette.add_item(kind, button)
        button.set_active(kind == "pen")
    palette.add_item("opacity", PaletteSliderBar("opacity", "Opacité", 0, 100, 80, "%"))
    return palette
