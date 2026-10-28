"""Planche : aspect des cellules, délégué de dessin, étoiles / drapeaux / couleurs peints sur les vignettes.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import math
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from app_style import scaled
import previews

from .loader import display_name
from .film_look import (
    _FILM_SIDES, _film_inner, _gallery_mark_on_sub_cells, _paint_color_mark, _paint_film_box, _paint_gallery_mark,
)
from .attributes_ui import _StatusFlags, filter_colors

if TYPE_CHECKING:
    from .gallery import FocusGallery      # annotations seulement (gallery importe ce module)


def _gallery_look() -> dict:
    """Padding des cellules de la planche = celui des tableaux des reglages (Reglages > Tableaux), lu
    dans les reglages appliques (ui_state.APPLIED_SETTINGS)."""
    import ui_state
    from settings_store import DEFAULT_SETTINGS
    values = dict(DEFAULT_SETTINGS)
    values.update(ui_state.APPLIED_SETTINGS or {})

    def side_dict(key, fallback):
        raw = values.get(key)
        return {side: (raw.get(side, fallback) if isinstance(raw, dict) else raw if raw is not None else fallback)
                for side in ("left", "top", "right", "bottom")}

    # Fond, bordures et border radius du tableau sont ceux de Visionneuse > Tableau, et la planche n'a PLUS de
    # filets interieurs (ceux des tableaux des reglages restaient visibles tableau sans fond ni bordure :
    # demande de l'utilisateur). Elle n'a PLUS non plus le padding des cellules de Reglages > Tableaux (8 / 14 px
    # qui laissaient un espace autour de l'image, signale malgre des paddings a 0) : seuls comptent Visionneuse >
    # Cellules > « Padding de l'image » et « Padding des icônes d'attribut ».
    return {"padding": {side: 0 for side in ("left", "top", "right", "bottom")}}


class _GalleryDelegate(QStyledItemDelegate):
    """Cellule de la planche (un fichier par cellule du tableau) : image ajustee dans sa place,
    nom puis type et poids du fichier dessous ; la cellule de l'image en cours et la cellule survolee
    sont marquees (Couleur focus / survol, _paint_gallery_mark). A l'ouverture, les cellules
    apparaissent en vague depuis l'image en cours (FocusGallery.ripple_state)."""

    def __init__(self, gallery: "FocusGallery"):
        super().__init__(gallery)
        self.gallery = gallery

    def sizeHint(self, option, index) -> QSize:
        return self.gallery.gridSize()

    def paint(self, painter: QPainter, option, index):
        gallery = self.gallery
        key = index.data(Qt.UserRole)
        is_current = key == gallery.current
        opacity, scale = gallery.ripple_state(option.rect)
        if opacity <= 0.0:
            return
        hovered = bool(option.state & QStyle.State_MouseOver) and gallery.attr_editing_allowed()
        mark = "focus" if is_current else "hover" if option.state & QStyle.State_MouseOver else None
        painter.save()
        if opacity < 1.0 or scale != 1.0:
            painter.setOpacity(opacity)
            centre = QRectF(option.rect).center()
            painter.translate(centre)
            painter.scale(scale, scale)
            painter.translate(-centre)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # Toute la case (sous-cellules, image, textes) est une image gardee : une peinture ne fait que
        # la poser (la vague et le vol de l'image repeignent la planche a chaque image).
        painter.drawPixmap(option.rect.topLeft(), gallery.cell_pixmap(index, option.rect.size(), mark, hovered))
        if hovered and opacity >= 1.0:
            # Controles des attributs de la case survolee, directement sur la photo.
            room = gallery.photo_room(key, option.rect)
            hover = gallery._attr_hover[1:] if gallery._attr_hover and gallery._attr_hover[0] == key else None
            painter.translate(option.rect.topLeft())
            _paint_attr_controls(painter, room, gallery.attr_values(key), hover)
        painter.restore()

    @staticmethod
    def paint_content(painter: QPainter, gallery: "FocusGallery", rect: QRect, path: Path, info: str,
                      pix: QPixmap | None, hidden: bool, mark: str | None = None,
                      corners: frozenset = frozenset(), color: str | None = None, insets: tuple | None = None,
                      attrs: dict | None = None, hovered: bool = False):
        """Contenu d'une case dans `rect` : sous-cellule image puis sous-cellule texte dessous
        (Reglages > Visionneuse > Sous cellule image / Sous cellule texte, _film_look). `mark` = "focus" /
        "hover" : case en cours / survolee (_paint_gallery_mark) : sous les fonds des sous-cellules quand
        il couvre la cellule, par-dessus quand il couvre les sous-cellules (jamais sur l'image ni le texte)."""
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        look = gallery.film_look_for(str(path))
        cell_outer, cell, box = gallery.edited_cell_boxes(rect, look)
        cell_style = look.get("cell")
        if cell_style is not None:
            _paint_film_box(painter, QRectF(cell_outer), cell_style)
        text_box = QRect(cell.x(), box.bottom() + 1, cell.width(), max(0, cell.bottom() - box.bottom()))
        # Marques (couleur attribuee au fichier, puis focus / survol par-dessus) : sous les fonds des
        # sous-cellules quand elles couvrent la cellule, par-dessus quand elles couvrent les sous-cellules.
        on_cells = _gallery_mark_on_sub_cells(look)
        if not on_cells:
            if color:
                # Hors de ce que la planche peint par-dessus (filets, bordure du tableau : FocusGallery.mark_insets).
                left, top, right, bottom = insets or (0, 0, 0, 0)
                _paint_color_mark(painter, look, rect.adjusted(left, top, -right, -bottom), color, corners)
            if mark is not None:
                _paint_gallery_mark(painter, look, rect, mark, corners)
        bg_pad = look["bg_padding"]                  # fond de la cellule : retrait dans la case, images et icones suivent
        bg_box = QRect(box).adjusted(bg_pad["left"], bg_pad["top"], -bg_pad["right"], -bg_pad["bottom"])
        _paint_film_box(painter, QRectF(bg_box), look["image_cell"])
        if text_box.height() > 0:
            _paint_film_box(painter, QRectF(text_box), look["text_cell"])
        if on_cells:
            target = cell if look.get("split") else bg_box          # fond de la cellule (padding du fond compris)
            if color:
                _paint_color_mark(painter, look, target, color)
            if mark is not None:
                _paint_gallery_mark(painter, look, target, mark)
        attr_pad = look["attr_padding"]                                    # calque des icones d'attribut
        frame = QRect(bg_box).adjusted(attr_pad["left"], attr_pad["top"], -attr_pad["right"], -attr_pad["bottom"])
        room = _film_inner(QRectF(bg_box), look["image_cell"]).toRect()    # calque de l'image : son propre padding
        image_pad = look["image_padding"]
        room = room.adjusted(image_pad["left"], image_pad["top"], -image_pad["right"], -image_pad["bottom"])
        band = gallery.photo_band(look)
        if room.height() > 2 * band + 20:
            room = room.adjusted(0, band, 0, -band)      # place des attributs, au-dessus et au-dessous
        strip_room = room
        if pix is not None and not pix.isNull():
            target = gallery.fit_in_box(pix, room)
            strip_room = target              # attributs poses SUR la photo
            image = look["image"]
            if look["image_shadow"] is not None:
                from settings_widgets import paint_shadow
                paint_shadow(painter, QRectF(target), image["radius"], look["image_shadow"])
            painter.save()
            if any(image["radius"].values()):
                from settings_widgets import _rounded_rect_path
                painter.setClipPath(_rounded_rect_path(target, image["radius"]))
            painter.drawPixmap(target, pix)
            painter.restore()
            _paint_film_box(painter, QRectF(target), image)
        elif not hidden:
            # Pas (encore) d'apercu, ex. fichier 3D jamais rendu : son type au milieu de la case.
            ext_font, ext_color = look["ext_font"]
            painter.setFont(ext_font)
            painter.setPen(ext_color)
            painter.drawText(room, Qt.AlignCenter, path.suffix.lstrip(".").upper())
        if hasattr(gallery, "_photo_rects"):
            gallery._photo_rects[str(path)] = QRect(frame)           # coins de la diapo (controles du survol)
        if attrs:
            _paint_attrs(painter, frame, attrs, look, hovered, SHOW_KEYWORDS, strip_room)
        if text_box.height() <= 0:
            return                           # case non divisee : pas de sous-cellule texte
        # Nom (police de la sous-cellule texte) puis type et poids (police du tableau), centres ensemble.
        text_room = _film_inner(QRectF(text_box), look["text_cell"]).toRect()
        name_font, name_color = look["name_font"]
        info_font, info_color = look["rank_font"]
        name_m, info_m = QFontMetrics(name_font), QFontMetrics(info_font)
        block = name_m.height() + (info_m.height() if info else 0)
        top = text_room.y() + max(0, (text_room.height() - block) // 2)
        painter.save()
        painter.setClipRect(text_room)
        painter.setFont(name_font)
        painter.setPen(name_color)
        name = name_m.elidedText(display_name(path), Qt.ElideMiddle, text_room.width())
        offsets = getattr(gallery, "_edit_offsets", {}).get(str(path), {})
        name_width = min(text_room.width(), name_m.horizontalAdvance(name))
        name_rect = QRect(text_room.center().x() - name_width // 2, top, name_width, name_m.height())
        name_rect.translate(offsets.get("gallery-name", QPoint()))
        _paint_gallery_text_override(painter, name_rect, look.get("name_style"))
        painter.drawText(name_rect, Qt.AlignCenter, name)
        if info:
            painter.setFont(info_font)
            painter.setPen(info_color)
            shown_info = info_m.elidedText(info, Qt.ElideRight, text_room.width())
            info_width = min(text_room.width(), info_m.horizontalAdvance(shown_info))
            info_rect = QRect(text_room.center().x() - info_width // 2,
                              top + name_m.height(), info_width, info_m.height())
            info_rect.translate(offsets.get("gallery-info", QPoint()))
            _paint_gallery_text_override(painter, info_rect, look.get("info_style"))
            painter.drawText(info_rect, Qt.AlignCenter, shown_info)
        painter.restore()


_FLAG_PIXMAPS: dict = {}       # (statut, cote px) -> icone du drapeau (fichiers PNG lourds : lus une fois)


def _flag_pixmap(status: str, side: int) -> QPixmap | None:
    custom_key = {"keep": previews.UI_ICON_VIEWER_FLAG_KEEP, "delete": previews.UI_ICON_VIEWER_FLAG_DELETE}.get(status)
    if custom_key is not None:
        custom = previews.custom_ui_icon_pixmap(custom_key, side)       # Reglages > Visionneuse > Icones
        if custom is not None:
            return custom
    key = (status, side)
    if key not in _FLAG_PIXMAPS:
        icon_path = _StatusFlags.ICONS.get(status, ("", ""))[0]
        pix = QPixmap(icon_path) if icon_path else QPixmap()
        _FLAG_PIXMAPS[key] = None if pix.isNull() else pix.scaled(side, side, Qt.KeepAspectRatio,
                                                                   Qt.SmoothTransformation)
    return _FLAG_PIXMAPS[key]


def _star_polygon(cx: float, cy: float, radius: float):
    from PySide6.QtGui import QPolygonF
    return QPolygonF([QPointF(cx + (radius if k % 2 == 0 else radius * 0.45) * math.sin(k * math.pi / 5),
                              cy - (radius if k % 2 == 0 else radius * 0.45) * math.cos(k * math.pi / 5))
                      for k in range(10)])


SHOW_KEYWORDS = False          # touche I dans la planche : mots cles ecrits sur les photos (session)


def attr_unit() -> int:
    return scaled(14)


def attr_gap() -> int:
    """Espace entre la photo et ses attributs."""
    return scaled(5)


def attr_inset() -> int:
    """Retrait des attributs par rapport au calque des icones (0 : leur padding, Reglages > Visionneuse >
    Cellules > « Padding des icônes d'attribut », fait le reste)."""
    return 0


def attr_layout(frame: QRect) -> dict:
    """Place des controles d'attributs, dans les COINS de la diapo `frame` (sa zone image, demande de
    l'utilisateur : plus collés à la photo), a `attr_gap` des bords : couleurs en haut a gauche, drapeaux en
    haut a droite, note en bas a gauche, « + » (mots cles) en bas a droite. Memes places pour ce qui est
    dessine (attributs appliques) et pour ce qui se manipule au survol. La bande au-dessus / au-dessous de la
    photo est reservee dans la case (`FocusGallery.photo_band`), la photo ne les recouvre jamais."""
    u = attr_unit()
    gap = scaled(2)
    inset = attr_inset()
    left, right = frame.left() + inset, frame.right() - inset
    above, below = frame.top() + inset, frame.bottom() + 1 - inset - u
    colors = [QRect(left + i * (u + gap), above, u, u) for i in range(COLOR_SLOTS)]
    flags = {"delete": QRect(right - u + 1, above, u, u), "keep": QRect(right - 2 * u - gap + 1, above, u, u)}
    stars = [QRect(left + i * u, below, u, u) for i in range(5)]
    plus = QRect(right - u + 1, below, u, u)
    return {"colors": colors, "flags": flags, "stars": stars, "plus": plus, "unit": u, "pad": scaled(5)}


COLOR_SLOTS = 5


def _backdrop(painter: QPainter, rect: QRectF, strength: int = 185):
    from settings_store import M
    back = QColor(M["panel_bg"])
    back.setAlpha(strength)
    painter.setPen(Qt.NoPen)
    painter.setBrush(back)
    painter.drawRoundedRect(rect, rect.height() / 2 if rect.width() <= rect.height() * 1.2 else scaled(5),
                            rect.height() / 2 if rect.width() <= rect.height() * 1.2 else scaled(5))


def _paint_star(painter: QPainter, rect: QRect, lit: bool, preview: bool = False):
    from settings_store import M
    from settings_widgets import _selection_color
    side = rect.height()
    on = previews.custom_ui_icon_pixmap(previews.UI_ICON_VIEWER_STAR_ON, side)
    off = previews.custom_ui_icon_pixmap(previews.UI_ICON_VIEWER_STAR_OFF, side)
    if on is not None or off is not None:               # icones perso (Reglages > Visionneuse > Icones)
        pix, opacity = (on or off) if lit else (off or on), 1.0
        if not lit and off is None:
            opacity = 0.3                               # pas d'etoile vide choisie : l'allumee, estompee
        if preview:
            opacity *= 0.6
        painter.save()
        painter.setOpacity(painter.opacity() * opacity)
        target = QRect(0, 0, pix.width(), pix.height())
        target.moveCenter(rect.center())
        painter.drawPixmap(target, pix)
        painter.restore()
        return
    color = QColor(_selection_color(255) if lit else M["value_fg"])
    if not lit:
        color.setAlpha(120)                 # etoile vide : contour discret mais visible sur la photo
    if preview:
        color.setAlpha(150)
    painter.setPen(QPen(color, 1.2))
    painter.setBrush(color if lit else Qt.NoBrush)
    painter.drawPolygon(_star_polygon(rect.center().x() + 0.5, rect.center().y() + 0.5, rect.height() * 0.4))


def _paint_flag(painter: QPainter, rect: QRect, status: str, dim: bool = False):
    from settings_store import M
    side = rect.width() - scaled(2)
    pix = _flag_pixmap(status, side)
    painter.save()
    if dim:
        painter.setOpacity(0.45)
    if pix is not None:
        painter.drawPixmap(rect.adjusted(scaled(1), scaled(1), -scaled(1), -scaled(1)), pix)
    else:
        painter.setPen(QColor(M["value_fg"]))
        painter.drawText(rect, Qt.AlignCenter, "✓" if status == "keep" else "✕")
    painter.restore()


def _paint_attrs(painter: QPainter, room: QRect, attrs: dict, look: dict, hovered: bool = False,
                 show_keywords: bool = False, photo: QRect | None = None):
    """Attributs APPLIQUES d'une case de la planche, directement sur la photo (demande de l'utilisateur :
    seulement ceux qui sont appliques ; manipulables au survol, `_paint_attr_controls`). Note en bas a
    gauche, couleur en haut a gauche, drapeau en haut a droite ; mots cles (un par ligne, a partir du haut
    a gauche, sous la rangee des couleurs) seulement quand la touche I les affiche. Au survol, note /
    couleur / drapeau sont repris par les controles (`hovered`) : les mots cles restent dessines ici."""
    layout = attr_layout(room)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if not hovered:
        rating = int(attrs.get("rating") or 0)
        if rating:
            lit = layout["stars"][:rating]
            for rect in lit:
                _paint_star(painter, rect, True)
        color = int(attrs.get("color") or 0)
        palette = filter_colors()
        if 1 <= color <= min(len(palette), COLOR_SLOTS):
            slot = layout["colors"][0]          # coin haut gauche (au survol : sa pastille, parmi les 5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(palette[color - 1][1]))
            painter.drawEllipse(QRectF(slot).adjusted(scaled(2), scaled(2), -scaled(2), -scaled(2)))
        status = attrs.get("status") or ""
        if status in layout["flags"]:
            slot = layout["flags"]["delete"]         # collé au coin de la photo, quel que soit le drapeau
            _paint_flag(painter, slot, status)
    words = attrs.get("keywords") or []
    if show_keywords and words:
        font, text_color = look["rank_font"]
        metrics = QFontMetrics(font)
        line = metrics.height() + scaled(3)
        photo = photo or room                 # mots cles DANS la photo, a partir de son coin haut gauche
        x = photo.left() + layout["pad"]
        y = photo.top() + layout["pad"]
        limit = photo.bottom() - layout["pad"]
        painter.setFont(font)
        for index, word in enumerate(words):
            if y + line > limit:
                more = f"+{len(words) - index}"
                painter.setPen(text_color)
                painter.drawText(QRect(x, y, photo.width(), line), Qt.AlignVCenter | Qt.AlignLeft, more)
                break
            text = metrics.elidedText(word, Qt.ElideRight, max(10, photo.width() - 2 * layout["pad"] - scaled(8)))
            box = QRectF(x, y, metrics.horizontalAdvance(text) + scaled(8), line - scaled(1))
            _backdrop(painter, box, 200)
            painter.setPen(text_color)
            painter.drawText(box, Qt.AlignCenter, text)
            y += line
    painter.restore()


def _paint_attr_controls(painter: QPainter, room: QRect, attrs: dict, hover: tuple | None):
    """Controles d'attributs de la case SURVOLEE, sur la photo : 5 etoiles (la note, apercu de la note
    visee), 5 pastilles de couleur, drapeaux « marquee » / « rejetee », « + » des mots cles. `hover` =
    (genre, valeur) de l'element sous le curseur."""
    from settings_store import M
    layout = attr_layout(room)
    rating = int(attrs.get("rating") or 0)
    color = int(attrs.get("color") or 0)
    status = attrs.get("status") or ""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Note
    shown = rating
    if hover and hover[0] == "star":
        shown = hover[1]
    for i, rect in enumerate(layout["stars"]):
        _paint_star(painter, rect, i < shown, preview=bool(hover and hover[0] == "star" and i >= rating))
    # Couleurs
    palette = filter_colors()
    swatches = layout["colors"][:len(palette)]
    for i, slot in enumerate(swatches):
        inner = QRectF(slot).adjusted(scaled(2.5), scaled(2.5), -scaled(2.5), -scaled(2.5))
        if hover and hover[0] == "color" and hover[1] == i + 1:
            inner = inner.adjusted(-scaled(1), -scaled(1), scaled(1), scaled(1))
        fill = QColor(palette[i][1])
        if color and color != i + 1:
            fill.setAlphaF(fill.alphaF() * 0.45)
        if color == i + 1:
            painter.setPen(QPen(QColor(M["value_fg"]), 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(inner.adjusted(-scaled(1.5), -scaled(1.5), scaled(1.5), scaled(1.5)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(inner)
    # Drapeaux
    for name, slot in layout["flags"].items():
        active = status == name
        if active or (hover and hover[0] == "flag" and hover[1] == name):
            painter.setPen(QPen(QColor("#55aaff"), 1.4))
            painter.setBrush(QColor(85, 170, 255, 45))
            painter.drawRoundedRect(QRectF(slot).adjusted(0.5, 0.5, -0.5, -0.5), scaled(3), scaled(3))
        _paint_flag(painter, slot, name, dim=bool(status) and not active)
    # « + » : mots cles
    plus = layout["plus"]
    hot = bool(hover and hover[0] == "plus")
    custom_plus = previews.custom_ui_icon_pixmap(previews.UI_ICON_VIEWER_PLUS, plus.height())
    if custom_plus is not None:
        target = QRect(0, 0, custom_plus.width(), custom_plus.height())
        target.moveCenter(plus.center())
        painter.setOpacity(1.0 if hot else 0.75)
        painter.drawPixmap(target, custom_plus)
        painter.restore()
        return
    painter.setPen(QPen(QColor(M["value_fg"] if hot else M["row_label"]), 1.6, Qt.SolidLine, Qt.RoundCap))
    cx, cy, arm = plus.center().x() + 0.5, plus.center().y() + 0.5, plus.width() * 0.3
    painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
    painter.restore()


def attr_hit(room: QRect, pos: QPoint) -> tuple | None:
    """Element de `attr_layout` sous `pos` : ("star", n) / ("color", n) / ("flag", nom) / ("plus", 0)."""
    layout = attr_layout(room)
    for i, rect in enumerate(layout["stars"]):
        if rect.contains(pos):
            return ("star", i + 1)
    for i, rect in enumerate(layout["colors"][:len(filter_colors())]):
        if rect.contains(pos):
            return ("color", i + 1)
    for name, rect in layout["flags"].items():
        if rect.contains(pos):
            return ("flag", name)
    if layout["plus"].contains(pos):
        return ("plus", 0)
    return None


def _paint_gallery_text_override(painter, rect: QRect, values: dict | None):
    if not values:
        return
    from app_style import resolve_color_ref
    from settings_store import _coerce_corner_radius
    pad = values.get("text_padding") or {}
    box = rect.adjusted(-max(0, int(pad.get("left", 0))), -max(0, int(pad.get("top", 0))),
                        max(0, int(pad.get("right", 0))), max(0, int(pad.get("bottom", 0))))
    fill = QColor(resolve_color_ref(values.get("text_background_color"), "#00000000")) \
        if values.get("text_background_enabled") else QColor(0, 0, 0, 0)
    enabled = values.get("text_border_enabled") or {}
    if fill.alpha() or any(enabled.values()):
        colors = {side: QColor(resolve_color_ref((values.get("text_border") or {}).get(side), "#00000000"))
                  for side in _FILM_SIDES}
        corners = _coerce_corner_radius(values.get("text_border_radius") or 0)
        from settings_widgets import _paint_bordered_vector
        _paint_bordered_vector(painter, box, corners, enabled,
                               max(0, int(values.get("text_border_thickness", 1) or 0)), colors,
                               fill.name(QColor.NameFormat.HexArgb) if fill.alpha() else None)
