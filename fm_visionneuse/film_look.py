"""Aspect commun pellicule / planche : réglages de cellule, cadre, marques de focus / survol et de couleur.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap

from app_style import C


def placeholder_pixmap(path: Path, note: str = "Aperçu pas encore rendu") -> QPixmap:
    """Carte montree au centre (etat focus) pour un fichier sans apercu disponible, typiquement un
    fichier 3D jamais rendu : son type en grand, son nom, `note`. Le diaporama ne le saute pas."""
    width, height = 960, 600
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setPen(QPen(QColor(C["border"]), 2))
    painter.setBrush(QColor(C["well"]))
    painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 18, 18)
    font = QFont(painter.font())
    font.setPixelSize(132)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(C["dim"]))
    painter.drawText(QRect(0, 70, width, 260), Qt.AlignCenter, path.suffix.lstrip(".").upper() or "?")
    font.setPixelSize(30)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor(C["text"]))
    name = QFontMetrics(font).elidedText(path.name, Qt.ElideMiddle, width - 80)
    painter.drawText(QRect(40, 350, width - 80, 60), Qt.AlignCenter, name)
    font.setPixelSize(22)
    painter.setFont(font)
    painter.setPen(QColor(C["dim"]))
    painter.drawText(QRect(40, 420, width - 80, 50), Qt.AlignCenter, note)
    painter.end()
    return pix


_FILM_SIDES = ("top", "right", "bottom", "left")


def film_text_ratio() -> float:
    """Hauteur de la sous-cellule texte d'une diapositive / celle de sa sous-cellule image
    (`viewer_film_text_ratio`, Ctrl + tirer la bordure entre les deux)."""
    import ui_state
    from .filmstrip import FocusFilmstrip      # import tardif : filmstrip importe film_look
    try:
        ratio = float((ui_state.APPLIED_SETTINGS or {}).get("viewer_film_text_ratio", 0.32))
    except (TypeError, ValueError):
        ratio = 0.32
    return max(FocusFilmstrip.RATIO_MIN, min(FocusFilmstrip.RATIO_MAX, ratio))


def _film_look() -> dict:
    """Habillage des diapositives = Reglages > Visionneuse > Tableau / Sous cellule image / Sous cellule
    texte (cles `viewer_film_*`), lu dans les reglages appliques : par partie, bordures (cotes, couleurs,
    epaisseur), border radius, fond, police et couleur du texte."""
    import ui_state
    from app_style import font as app_font, resolve_color_ref
    from settings_store import DEFAULT_SETTINGS, _coerce_corner_radius, _coerce_side_enabled
    from settings_widgets import shadow_look
    values = dict(DEFAULT_SETTINGS)
    values.update(ui_state.APPLIED_SETTINGS or {})

    def box(pre: str, bg: bool = True) -> dict:
        raw = values.get(f"{pre}_border")
        colors = {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, "#2a2e32") for s in _FILM_SIDES}
        fill = QColor(resolve_color_ref(values.get(f"{pre}_bg"), "#00000000")) if bg else QColor(0, 0, 0, 0)
        try:
            thick = max(0, int(values.get(f"{pre}_border_thickness", 1)))
        except (TypeError, ValueError):
            thick = 1
        sides = _coerce_side_enabled(values.get(f"{pre}_border_enabled"), False)
        return {"on": sides, "colors": colors, "thick": thick if any(sides.values()) else 0,
                "radius": _coerce_corner_radius(values.get(f"{pre}_border_radius", 0)),
                "fill": fill.name(QColor.NameFormat.HexArgb) if fill.alpha() else None}

    def text(pre: str) -> tuple:
        smooth = values.get(f"{pre}_font_smoothing", "current") if values.get(f"{pre}_font_smoothing_enabled") \
            else "current"
        try:
            size = max(4, int(values.get(f"{pre}_font_size", 11)))
        except (TypeError, ValueError):
            size = 11
        weight = 700 if values.get(f"{pre}_font_bold") else 400
        # Choix « app » = un ROLE de Polices principales (« Police principale »...), a traduire en vraie
        # famille comme partout ailleurs (sinon Qt recevait ce libelle et prenait une police de repli :
        # bug signale) ; « Systeme » / vide = police par defaut.
        label = (values.get(f"{pre}_font_family") or "").strip()
        family = None
        if label and label != "Systeme":
            from browser_core import _resolve_font_family
            family = _resolve_font_family(label, size, weight)
        qfont = app_font(size, weight, family=family, smoothing=smooth,
                         italic=bool(values.get(f"{pre}_font_italic")))
        return qfont, QColor(resolve_color_ref(values.get(f"{pre}_font_color"), C["text"]))

    def mark(key: str, default: str) -> QColor:
        return QColor(resolve_color_ref(values.get(key), default))

    def inner(axis: str) -> tuple:
        # Planche : filets entre les cellules (actif, couleur, epaisseur), Visionneuse > Tableau.
        pre = f"viewer_film_table_inner_{axis}"
        try:
            thick = max(0, int(values.get(f"{pre}_thickness", 1) or 0))
        except (TypeError, ValueError):
            thick = 1
        return bool(values.get(f"{pre}_enabled")), mark(f"{pre}_color", "#2a2e32"), thick

    def pad(key: str) -> dict:
        raw = values.get(key)
        raw = raw if isinstance(raw, dict) else {}
        out = {}
        for side in _FILM_SIDES:
            try:
                out[side] = max(0, int(raw.get(side, 0) or 0))
            except (TypeError, ValueError):
                out[side] = 0
        return out

    return {"table": box("viewer_film_table"), "image_cell": box("viewer_film_image_cell"),
            "bg_padding": pad("viewer_film_bg_padding"),            # fond de la cellule dans la case
            "image_padding": pad("viewer_film_image_padding"),      # image dans le fond
            "attr_padding": pad("viewer_film_attr_padding"),        # icones d'attribut : calque a part

            "image": box("viewer_film_image", bg=False), "text_cell": box("viewer_film_text_cell"),
            "rank_font": text("viewer_film_table"), "ext_font": text("viewer_film_image_cell"),
            "name_font": text("viewer_film_text_cell"),
            "focus": mark("viewer_film_table_focus_color", "#465f9bd0"),
            "hover": mark("viewer_film_table_hover_color", "#165f9bd0"),
            "inner_h": inner("h"), "inner_v": inner("v"),
            "focus_image": box("viewer_focus_image", bg=False),
            # Ombres (lignes « Ombres » : settings_widgets.shadow_look ; None = aucune).
            "image_shadow": shadow_look(values, "viewer_film_image_shadow", resolve_color_ref),
            "table_shadow": shadow_look(values, "viewer_film_table_shadow", resolve_color_ref),
            "focus_shadow": shadow_look(values, "viewer_focus_image_shadow", resolve_color_ref),
            # Couleur attribuee a un fichier (Visionneuse > Filtres > « Opacite des couleurs attribuees »).
            "color_mark": {"opacity": max(0, min(100, int(values.get("viewer_filter_mark_opacity", 35) or 0))),
                           "border": bool(values.get("viewer_filter_mark_border")),
                           "thick": max(1, int(values.get("viewer_filter_mark_border_thickness", 2) or 1))}}


def _paint_film_box(painter: QPainter, rect: QRectF, look: dict):
    """Fond + bordures (par cote) + border radius d'une partie de diapositive (tableau, sous-cellule,
    image) : le trace des reglages (settings_widgets._paint_bordered_vector), jamais un style a part."""
    if look["fill"] is None and not look["thick"]:
        return
    from settings_widgets import _paint_bordered_vector
    _paint_bordered_vector(painter, rect.toRect(), look["radius"], look["on"], look["thick"], look["colors"],
                           look["fill"])


def _film_inner(rect: QRectF, look: dict) -> QRectF:
    """`rect` moins l'epaisseur des bordures actives de `look`."""
    t = look["thick"]
    on = look["on"]
    return rect.adjusted(t if on["left"] else 0, t if on["top"] else 0,
                         -(t if on["right"] else 0), -(t if on["bottom"] else 0))


def _gallery_mark_on_sub_cells(look: dict) -> bool:
    """Ou se pose le focus / survol d'une case de la planche : sur ses DEUX sous-cellules quand leurs
    deux fonds sont affiches, ou quand le tableau est sans fond (opacite 0) et sans border radius —
    un border radius que rien ne dessine (ni fond ni bordure) compte comme absent ; sinon (au moins
    un fond de sous-cellule absent) sur toute la cellule du tableau."""
    table = look["table"]
    if not look.get("split"):
        # Case non divisee (demande de l'utilisateur) : focus / survol / couleur suivent le FOND DE LA CELLULE
        # quand le fond du tableau est 100 % transparent, sinon la cellule du tableau (4 coins de la cellule
        # = seulement ceux du tableau, `corners`).
        return table["fill"] is None
    if look["image_cell"]["fill"] is not None and look["text_cell"]["fill"] is not None:
        return True
    return table["fill"] is None and (not table["thick"] or not any(table["radius"].values()))


def _paint_gallery_mark(painter: QPainter, look: dict, rect: QRect, which: str, corners: frozenset = frozenset()):
    """Case en cours (`which` = "focus") ou survolee ("hover") : couleur de Visionneuse > Tableau, sans
    bordure. Sur les sous-cellules (`rect` = les deux) : coins du haut = ceux de la sous-cellule image,
    du bas = ceux de la sous-cellule texte ; sur la cellule : border radius du tableau, mais seulement aux
    coins que la cellule partage avec le tableau (`corners`, FocusGallery.table_corners : la premiere
    case en haut a gauche n'arrondit que son coin haut gauche...)."""
    color = look[which]
    if color.alpha() == 0 or rect.width() <= 0 or rect.height() <= 0:
        return
    radius = _gallery_mark_radius(look, corners)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if any(radius.values()):
        from settings_widgets import _rounded_rect_path
        painter.fillPath(_rounded_rect_path(rect, radius), color)
    else:
        painter.fillRect(rect, color)
    painter.restore()


def _paint_color_mark(painter: QPainter, look: dict, rect: QRect, color: str, corners: frozenset = frozenset()):
    """Couleur ATTRIBUEE au fichier (file_attributes) : calque de cette couleur a la place des marques
    focus / survol (meme rectangle, memes coins), opacite et bordure de Visionneuse > Filtres."""
    mark = look["color_mark"]
    if rect.width() <= 0 or rect.height() <= 0:
        return
    radius = _gallery_mark_radius(look, corners)
    fill = QColor(color)
    fill.setAlphaF(fill.alphaF() * mark["opacity"] / 100.0)
    from settings_widgets import _rounded_rect_path
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if fill.alpha():
        if any(radius.values()):
            painter.fillPath(_rounded_rect_path(rect, radius), fill)
        else:
            painter.fillRect(rect, fill)
    if mark["border"]:
        t = mark["thick"]
        inner = QRectF(rect).adjusted(t / 2, t / 2, -t / 2, -t / 2)
        pen = QPen(QColor(color), t)
        pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if any(radius.values()):
            # Chemin sur le rectangle EXACT (demi-pixels compris) : arrondi par toRect(), une epaisseur
            # impaire decalait le cadre d'un demi-pixel — bords gauche / haut plus epais, droite / bas
            # rognes par la case (signale).
            painter.drawPath(_rounded_rect_path(inner, {k: max(0, v - t / 2) for k, v in radius.items()}))
        else:
            painter.drawRect(inner)
    painter.restore()


def _gallery_mark_radius(look: dict, corners: frozenset) -> dict:
    """Coins des marques d'une case (focus, survol, couleur attribuee) : voir _paint_gallery_mark."""
    if _gallery_mark_on_sub_cells(look):
        if not look.get("split"):
            return dict(look["image_cell"]["radius"])        # les 4 coins du fond de la cellule
        top, bottom = look["image_cell"]["radius"], look["text_cell"]["radius"]
        return {"top_left": top["top_left"], "top_right": top["top_right"],
                "bottom_right": bottom["bottom_right"], "bottom_left": bottom["bottom_left"]}
    return {k: (v if k in corners else 0) for k, v in look["table"]["radius"].items()}


# -- Encart « Source du proxy » (Maj + survol d'une diapositive) ------------------------------------

_PROXY_SOURCES: dict[str, str] = {}      # chemin -> source du proxy (lue en fond, voir ProxySourceTip)
