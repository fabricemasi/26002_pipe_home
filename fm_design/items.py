"""Éléments du module Design dans la scène du board : page (plan de travail), forme, texte, image.

Ils héritent de `fm_miro.items.BoardItem` (identifiant, `data`, `to_dict` / `apply`, annulation, griser / masquer par
module) mais n'ont NI poignées NI déplacement Qt : en mode Design, le contrôleur (`controller.py`) reçoit la souris et
dessine la sélection (`overlay.py`). Un élément est ENFANT de sa page (`added_to_scene`) : coordonnées relatives,
découpé par la page (`ItemClipsChildrenToShape`), déplacé avec elle.

Fluidité : chaque élément est gardé en image à l'écran (`DeviceCoordinateCache`, comme le reste du board) ; ombres,
dégradés et images retouchées sont calculés une fois par réglage (caches `_shadow_cache`, `_image_cache`)."""
from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject

from fm_miro.items import ITEM_CLASSES, BoardItem, asset_pixmap, pen_style, shape_path
from . import design_model as dm

PAGE_Z = -200000.0                     # sous les cadres de Miro (FRAME_Z = -100000)
ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight, "justify": Qt.AlignJustify}


# ---------------------------------------------------------------- peinture commune
def fill_brush(data: dict, rect: QRectF, color_key="fill", type_key="fill_type", second_key="fill2",
               angle_key="gradient_angle") -> QBrush:
    """Couleur unie, dégradé linéaire (angle en degrés, 90 = de haut en bas) ou radial ; « none » = aucun fond."""
    kind = data.get(type_key, "solid")
    first = QColor(data.get(color_key) or "#ffffff")
    if kind == "none":
        return QBrush(Qt.NoBrush)
    if kind in ("linear", "radial"):
        second = QColor(data.get(second_key) or "#ffffff")
        c = rect.center()
        if kind == "radial":
            gradient = QRadialGradient(c, max(rect.width(), rect.height()) / 2 or 1.0)
        else:
            a = math.radians(float(data.get(angle_key, 90.0)))
            dx, dy = math.cos(a), math.sin(a)
            half = (abs(rect.width() * dx) + abs(rect.height() * dy)) / 2 or 1.0
            gradient = QLinearGradient(c - QPointF(dx, dy) * half, c + QPointF(dx, dy) * half)
        gradient.setColorAt(0.0, first)
        gradient.setColorAt(1.0, second)
        return QBrush(gradient)
    return QBrush(first)


_SHADOW_CACHE: OrderedDict = OrderedDict()


def shadow_pixmap(path: QPainterPath, color: str, blur: float, key) -> tuple[QPixmap, QRectF]:
    """Ombre floue d'un contour : peinte en BASSE résolution puis agrandie avec lissage (flou à moindre coût),
    gardée (au plus 200). Retourne l'image et sa place (coordonnées du contour)."""
    blur = max(0.0, float(blur))
    rect = path.boundingRect().adjusted(-blur * 1.5, -blur * 1.5, blur * 1.5, blur * 1.5)
    full = (key, color, round(blur, 2))
    kept = _SHADOW_CACHE.get(full)
    if kept is not None:
        _SHADOW_CACHE.move_to_end(full)
        return kept, rect
    k = min(1.0, 6.0 / blur) if blur > 0 else 1.0
    k = min(k, 400.0 / max(1.0, rect.width(), rect.height()))
    w, h = max(1, int(math.ceil(rect.width() * k))), max(1, int(math.ceil(rect.height() * k)))
    image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(k, k)
    p.translate(-rect.topLeft())
    p.fillPath(path, QColor(color))
    p.end()
    if blur > 0:                                        # deux passes réduction / agrandissement : flou doux
        small = image.scaled(max(1, w // 2), max(1, h // 2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        image = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pixmap = QPixmap.fromImage(image)
    _SHADOW_CACHE[full] = pixmap
    while len(_SHADOW_CACHE) > 200:
        _SHADOW_CACHE.popitem(last=False)
    return pixmap, rect


def paint_shadow(painter: QPainter, data: dict, path: QPainterPath, key):
    shadow = data.get("shadow") or {}
    if not shadow.get("enabled"):
        return
    pixmap, rect = shadow_pixmap(path, shadow.get("color", "#59000000"), shadow.get("blur", 0.0), key)
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(rect.translated(float(shadow.get("dx", 0.0)), float(shadow.get("dy", 0.0))), pixmap,
                       QRectF(pixmap.rect()))
    painter.restore()


def shadow_extent(data: dict) -> float:
    shadow = data.get("shadow") or {}
    if not shadow.get("enabled"):
        return 0.0
    return float(shadow.get("blur", 0.0)) * 1.5 + max(abs(float(shadow.get("dx", 0.0))),
                                                      abs(float(shadow.get("dy", 0.0))))


def cap_polygon(kind: str, tip: QPointF, back: QPointF, size: float) -> tuple[QPainterPath, bool]:
    """Pointe d'un trait : (contour, plein ?)."""
    dx, dy = tip.x() - back.x(), tip.y() - back.y()
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    path = QPainterPath()
    if kind == "circle":
        path.addEllipse(tip, size / 2, size / 2)
        return path, True
    base = QPointF(tip.x() - ux * size, tip.y() - uy * size)
    left = QPointF(base.x() - uy * size * 0.55, base.y() + ux * size * 0.55)
    right = QPointF(base.x() + uy * size * 0.55, base.y() - ux * size * 0.55)
    if kind == "filled":
        path.addPolygon(QPolygonF([tip, left, right, tip]))
        return path, True
    path.moveTo(left)
    path.lineTo(tip)
    path.lineTo(right)
    return path, False


# ---------------------------------------------------------------- base
class DesignItem(BoardItem):
    MODULE = "design"
    CONNECTABLE = False

    def __init__(self, data: dict):
        super().__init__(data)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    def _place_from_data(self):
        super()._place_from_data()
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    # PySide6 ne sait pas rendre un QGraphicsItem depuis un itemChange écrit en Python : un changement de PARENT
    # passé par `BoardItem.itemChange` revenait None et annulait le rattachement à la page (même en rendant
    # la valeur reçue). Les éléments Design gardent donc l'itemChange de Qt ; ce que faisait celui du board
    # (index de la scène, lots du CAD) est appelé à la main (`added_to_scene`, fin des gestes : `item_moved`).
    itemChange = QGraphicsObject.itemChange

    # pas de poignées ni de connexions de Miro : la sélection est dessinée par l'overlay du module
    def _margin(self) -> float:
        return 2.0 / self._zoom()

    def handle_at(self, pos):
        return None

    def connection_dot_at(self, scene_pos) -> bool:
        return False

    def paint_selection(self, painter):
        pass

    def boundingRect(self) -> QRectF:
        # Gardée : Qt la demande ~3 fois par élément et par image (index, peinture) ; la calculer en Python à
        # chaque fois coûtait ~10 ms par image avec 300 éléments. Refaite au changement de géométrie ou de zoom.
        scene = self.scene()
        key = getattr(scene, "zoom", None) if scene is not None else None     # (sans _zoom : appelée ~800 fois
        kept = getattr(self, "_bounds", None)                                  # par peinture à 1 000 éléments)
        if kept is not None and kept[0] == key:
            return kept[1]
        m = 2.0 / self._zoom()
        rect = self.paint_margin().united(self.content_rect()).adjusted(-m, -m, m, m)
        self._bounds = (key, rect)
        return rect

    def prepareGeometryChange(self):
        self._bounds = None
        super().prepareGeometryChange()

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.content_rect())
        return path


class DesignPageItem(DesignItem):
    """Plan de travail : fond (uni / dégradé), découpe ses éléments ; titre et sélection peints par l'overlay."""
    RESIZABLE = False

    def __init__(self, data: dict):
        super().__init__(data)
        self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.snapshot: QPixmap | None = None     # image de la page entière pendant un zoom continu (voir controller)

    def snapshot_on(self) -> bool:
        return self.snapshot is not None

    def paint(self, painter, option, widget=None):
        if self.snapshot is None:
            super().paint(painter, option, widget)
            return
        # Zoom continu : la page et tous ses éléments en UNE image (les éléments ne peignent rien, voir
        # DesignElement.paint) ; image nette refaite à la fin du geste.
        rect = self.content_rect()
        path = QPainterPath()
        path.addRect(rect)
        page_shadow = {"shadow": {"enabled": True, "color": "#33000000", "dx": 0.0, "dy": 6.0, "blur": 14.0}}
        paint_shadow(painter, page_shadow, path, ("page", rect.width(), rect.height()))
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(rect, self.snapshot, QRectF(self.snapshot.rect()))

    def _place_from_data(self):
        super()._place_from_data()
        self.setZValue(PAGE_Z + float(self.data.get("index", 0)))

    def _apply_rotation(self):
        if self.rotation():
            self.setRotation(0.0)

    def paint_margin(self) -> QRectF:
        return self.content_rect().adjusted(-24, -16, 24, 40)

    def module_opacity(self, faded: bool) -> float:
        from fm_cad.cad_items import FADE_OPACITY
        return FADE_OPACITY if faded else 1.0

    def added_to_scene(self, scene):
        """Adopte ses éléments déjà présents (lecture d'un fichier : ordre quelconque ; annulation)."""
        _notify_cad_layer(scene)
        known = getattr(scene, "design_pages", None)        # liste des pages gardée (document.pages)
        if known is not None:
            known.add(self)
        for item in scene.board_items():
            if isinstance(item, DesignElement) and item.parentItem() is None and item.data.get("page") == self.item_id:
                item.setParentItem(self)

    def removing_from_scene(self, scene):
        known = getattr(scene, "design_pages", None)
        if known is not None:
            known.discard(self)
        for child in list(self.childItems()):
            if isinstance(child, DesignElement):
                child.setParentItem(None)

    def dependent_ids(self, scene) -> set:
        """Supprimer une page supprime ses éléments (même étape)."""
        return {i.item_id for i in scene.board_items()
                if isinstance(i, DesignElement) and i.data.get("page") == self.item_id}

    def elements(self) -> list["DesignElement"]:
        return sorted((c for c in self.childItems() if isinstance(c, DesignElement)), key=lambda i: i.zValue())

    def paint_content(self, painter):
        rect = self.content_rect()
        path = QPainterPath()
        path.addRect(rect)
        page_shadow = {"shadow": {"enabled": True, "color": "#33000000", "dx": 0.0, "dy": 6.0, "blur": 14.0}}
        paint_shadow(painter, page_shadow, path, ("page", rect.width(), rect.height()))
        self.paint_background(painter)

    def paint_background(self, painter, transparent: bool = False, bleed: float = 0.0):
        """Fond de la page (uni, dégradé, image de fond) ; `transparent` = export sans fond blanc sous-jacent ;
        `bleed` = fond prolongé au-delà des bords (fond perdu de l'impression)."""
        rect = self.content_rect().adjusted(-bleed, -bleed, bleed, bleed)
        painter.setPen(Qt.NoPen)
        if not transparent:
            painter.fillRect(rect, QColor("#ffffff"))
        painter.setBrush(fill_brush(self.data, rect, "background", "bg_type", "bg2", "bg_angle"))
        painter.drawRect(rect)
        asset = self.data.get("bg_asset") or ""
        if asset:
            pixmap = asset_pixmap(getattr(self.scene(), "board_path", None), asset)
            if pixmap is not None:
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawPixmap(rect, pixmap, _cover(QRectF(pixmap.rect()), rect))


def design_shape_path(kind: str, rect: QRectF, radius: float = 0.0) -> QPainterPath:
    """Contour d'une forme : celles de Miro (`shape_path`) + cœur et anneau, propres au module."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    if kind == "heart":
        path = QPainterPath()
        path.moveTo(x + w / 2, y + h * 0.28)
        path.cubicTo(x + w * 0.5, y, x, y, x, y + h * 0.32)
        path.cubicTo(x, y + h * 0.62, x + w * 0.38, y + h * 0.78, x + w / 2, y + h)
        path.cubicTo(x + w * 0.62, y + h * 0.78, x + w, y + h * 0.62, x + w, y + h * 0.32)
        path.cubicTo(x + w, y, x + w * 0.5, y, x + w / 2, y + h * 0.28)
        path.closeSubpath()
        return path
    if kind == "ring":
        path = QPainterPath()
        path.addEllipse(rect)
        t = min(w, h) * 0.22
        path.addEllipse(rect.adjusted(t, t, -t, -t))
        path.setFillRule(Qt.OddEvenFill)
        return path
    return shape_path(kind or "rect", rect, radius)


def _notify_cad_layer(scene):
    """Lignes CAD peintes par lots : un élément qui arrive peut couper un lot (ce que fait `BoardItem.itemChange`)."""
    layer = getattr(scene, "cad_layer", None)
    if layer is not None:
        layer.structure_changed()


def _cover(source: QRectF, target: QRectF) -> QRectF:
    """Partie de `source` qui couvre `target` sans déformation (recadrée au centre)."""
    if source.isEmpty() or target.isEmpty():
        return source
    sr, tr = source.width() / source.height(), target.width() / target.height()
    if sr > tr:
        w = source.height() * tr
        return QRectF(source.x() + (source.width() - w) / 2, source.y(), w, source.height())
    h = source.width() / tr
    return QRectF(source.x(), source.y() + (source.height() - h) / 2, source.width(), h)


class DesignElement(DesignItem):
    """Élément d'une page : rotation, miroir, opacité, ombre ; enfant de sa page."""
    live = False                              # manipulé pendant que sa page est figée en image (gestures.py)

    def _place_from_data(self):
        super()._place_from_data()
        self._sync_opacity()

    def _apply_rotation(self):
        w, h = self.size()
        self.setTransformOriginPoint(w / 2, h / 2)
        angle = float(self.data.get("rotation", 0.0))
        if self.rotation() != angle:
            self.setRotation(angle)

    def _sync_opacity(self):
        scene = self.scene()
        if scene is not None and hasattr(scene, "item_opacity"):
            self.setOpacity(scene.item_opacity(self))
        else:
            self.setOpacity(self.module_opacity(False))

    def module_opacity(self, faded: bool) -> float:
        from fm_cad.cad_items import FADE_OPACITY
        base = float(self.data.get("opacity", 1.0))
        return base * (FADE_OPACITY if faded and self.parentItem() is None else 1.0)

    def added_to_scene(self, scene):
        _notify_cad_layer(scene)
        page = scene.item(self.data.get("page", ""))
        if isinstance(page, DesignPageItem) and self.parentItem() is not page:
            self.setParentItem(page)
        self._sync_opacity()

    def page_item(self) -> DesignPageItem | None:
        parent = self.parentItem()
        return parent if isinstance(parent, DesignPageItem) else None

    def outline(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.content_rect())
        return path

    def paint_margin(self) -> QRectF:
        e = shadow_extent(self.data) + float(self.data.get("stroke_width", 0.0) or 0.0)
        return self.content_rect().adjusted(-e, -e, e, e)

    def paint(self, painter, option, widget=None):
        page = self.parentItem()
        if page is not None and getattr(page, "snapshot", None) is not None and not self.live:
            return                                  # zoom continu / geste : peint dans l'image de sa page
        painter.setRenderHint(QPainter.Antialiasing, True)
        flip_h, flip_v = bool(self.data.get("flip_h")), bool(self.data.get("flip_v"))
        painter.save()
        if flip_h or flip_v:
            c = self.content_rect().center()
            painter.translate(c)
            painter.scale(-1 if flip_h else 1, -1 if flip_v else 1)
            painter.translate(-c)
        self.paint_content(painter)
        painter.restore()                           # (resetTransform effaçait la place de l'élément à l'écran)
        self.paint_badges(painter)


class DesignShapeItem(DesignElement):
    def outline(self) -> QPainterPath:
        rect = self.content_rect()
        if self.data.get("shape") == "line":
            path = QPainterPath()
            y = rect.center().y()
            path.moveTo(rect.left(), y)
            path.lineTo(rect.right(), y)
            return path
        return design_shape_path(self.data.get("shape", "rect"), rect, float(self.data.get("radius", 0.0)))

    def shape(self) -> QPainterPath:
        path = self.outline()
        if self.data.get("shape") == "line":
            stroker = QPainterPathStroker()
            stroker.setWidth(max(float(self.data.get("stroke_width", 4.0)), 10.0 / self._zoom()))
            return stroker.createStroke(path)
        return path

    def paint_content(self, painter):
        rect = self.content_rect()
        path = self.outline()
        line = self.data.get("shape") == "line"
        key = ("shape", self.data.get("shape"), rect.width(), rect.height(), self.data.get("radius"),
               self.data.get("stroke_width") if line else 0)
        if line:
            stroker = QPainterPathStroker()
            stroker.setWidth(max(1.0, float(self.data.get("stroke_width", 4.0))))
            stroker.setCapStyle(Qt.RoundCap)
            paint_shadow(painter, self.data, stroker.createStroke(path), key)
            self._paint_line(painter, rect)
            return
        paint_shadow(painter, self.data, path, key)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_brush(self.data, rect))
        painter.drawPath(path)
        width = float(self.data.get("stroke_width", 0.0) or 0.0)
        if width > 0:
            pen = QPen(QColor(self.data.get("stroke", dm.INK)), width, pen_style(self.data.get("stroke_style")))
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def _paint_line(self, painter, rect):
        width = max(1.0, float(self.data.get("stroke_width", 4.0)))
        color = QColor(self.data.get("stroke", dm.INK))
        y = rect.center().y()
        a, b = QPointF(rect.left(), y), QPointF(rect.right(), y)
        size = 3.0 * width + 6.0
        starts = []
        for kind, tip, back in ((self.data.get("cap_start", "none"), a, b), (self.data.get("cap_end", "none"), b, a)):
            if kind and kind != "none":
                starts.append((kind, tip, back))
        pen = QPen(color, width, pen_style(self.data.get("stroke_style")))
        pen.setCapStyle(Qt.RoundCap if self.data.get("stroke_style", "solid") == "solid" else Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # trait raccourci sous une pointe pleine (le bout reste net)
        start = a + QPointF(size * 0.8, 0) if self.data.get("cap_start") == "filled" else a
        end = b - QPointF(size * 0.8, 0) if self.data.get("cap_end") == "filled" else b
        painter.drawLine(start, end)
        for kind, tip, back in starts:
            path, filled = cap_polygon(kind, tip, back, size)
            if filled:
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
            else:
                cap_pen = QPen(color, width)
                cap_pen.setCapStyle(Qt.RoundCap)
                cap_pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(cap_pen)
                painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def paint_margin(self) -> QRectF:
        e = shadow_extent(self.data) + float(self.data.get("stroke_width", 0.0) or 0.0)
        if self.data.get("shape") == "line":
            e += 3.0 * float(self.data.get("stroke_width", 4.0)) + 6.0
        return self.content_rect().adjusted(-e, -e, e, e)


_IMAGE_CACHE: OrderedDict = OrderedDict()
WORK_SIDE = 1600                        # retouches calculées sur une image de travail au plus de cette taille


def adjusted_image(board_path, data: dict) -> QPixmap | None:
    """Image affichée : recadrage (partie visible), réglages (luminosité, contraste, saturation, noir et blanc,
    flou), calculée UNE fois par jeu de réglages (au plus 40 gardées)."""
    asset = data.get("asset", "")
    crop = tuple(dm.valid_crop(data.get("crop")))
    adjust = (float(data.get("brightness", 0.0)), float(data.get("contrast", 0.0)),
              float(data.get("saturation", 0.0)), float(data.get("blur", 0.0)), bool(data.get("grayscale")))
    key = (str(board_path), asset, crop, adjust)
    if key in _IMAGE_CACHE:
        _IMAGE_CACHE.move_to_end(key)
        return _IMAGE_CACHE[key]
    source = asset_pixmap(board_path, asset) if board_path is not None else None
    if source is None:
        return None
    sw, sh = source.width(), source.height()
    part = QRectF(crop[0] * sw, crop[1] * sh, (crop[2] - crop[0]) * sw, (crop[3] - crop[1]) * sh).toRect()
    pixmap = source.copy(part)
    if adjust != (0.0, 0.0, 0.0, 0.0, False):
        pixmap = QPixmap.fromImage(apply_adjustments(pixmap.toImage(), *adjust))
    _IMAGE_CACHE[key] = pixmap
    while len(_IMAGE_CACHE) > 40:
        _IMAGE_CACHE.popitem(last=False)
    return pixmap


def apply_adjustments(image: QImage, brightness: float, contrast: float, saturation: float, blur: float,
                      gray: bool) -> QImage:
    """Réglages locaux (-100..100). numpy si présent (rapide) ; sinon seuls noir et blanc et flou."""
    if max(image.width(), image.height()) > WORK_SIDE:
        image = image.scaled(WORK_SIDE, WORK_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    image = image.convertToFormat(QImage.Format_ARGB32)
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None and (brightness or contrast or saturation or gray):
        w, h = image.width(), image.height()
        buffer = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
        arr = buffer.reshape(h, image.bytesPerLine())[:, :w * 4].reshape(h, w, 4).astype(np.float32)
        rgb = arr[..., :3]                             # ordre B, G, R (ARGB32 petit-boutiste)
        if brightness:
            rgb += brightness * 1.28
        if contrast:
            f = (100.0 + contrast) / 100.0
            rgb[:] = (rgb - 128.0) * (f * f if contrast > 0 else f) + 128.0
        luma = rgb[..., 0:1] * 0.114 + rgb[..., 1:2] * 0.587 + rgb[..., 2:3] * 0.299
        if gray:
            rgb[:] = luma
        elif saturation:
            rgb[:] = luma + (rgb - luma) * (1.0 + saturation / 100.0)
        arr[..., :3] = np.clip(rgb, 0, 255)
        out = np.ascontiguousarray(arr.astype(np.uint8))
        image = QImage(out.data, w, h, w * 4, QImage.Format_ARGB32).copy()
    elif gray:
        alpha = image.convertToFormat(QImage.Format_Alpha8)
        image = image.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_ARGB32)
        image.setAlphaChannel(alpha)
    if blur > 0:
        k = max(1.0, blur / 4.0)
        w, h = image.width(), image.height()
        small = image.scaled(max(1, int(w / k)), max(1, int(h / k)), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        image = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return image


class DesignImageItem(DesignElement):
    def _paint_placeholder(self, painter, rect, path):
        """Cadre sans image (grille, emplacement) ou image introuvable : à remplir par un dépôt de fichier."""
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#d9d9e3"))
        painter.drawPath(path)
        side = min(rect.width(), rect.height()) * 0.18
        c = rect.center()
        pen = QPen(QColor("#8a8aa0"), max(1.0, side * 0.08))
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        box = QRectF(c.x() - side, c.y() - side * 0.75, side * 2, side * 1.5)
        painter.drawRoundedRect(box, side * 0.12, side * 0.12)
        painter.drawPolyline(QPolygonF([QPointF(box.left() + side * 0.2, box.bottom() - side * 0.2),
                                        QPointF(c.x() - side * 0.2, c.y()), QPointF(c.x() + side * 0.3, c.y() + side * 0.4),
                                        QPointF(box.right() - side * 0.2, box.bottom() - side * 0.5)]))
        if self.data.get("asset"):
            painter.drawLine(box.topLeft(), box.bottomRight())       # référence perdue : image introuvable

    def is_empty(self) -> bool:
        return not self.data.get("asset")

    def outline(self) -> QPainterPath:
        rect = self.content_rect()
        mask = self.data.get("mask") or ""
        if mask:
            return design_shape_path(mask, rect, float(self.data.get("radius", 0.0)))
        path = QPainterPath()
        r = min(float(self.data.get("radius", 0.0)), rect.width() / 2, rect.height() / 2)
        if r > 0:
            path.addRoundedRect(rect, r, r)
        else:
            path.addRect(rect)
        return path

    def paint_content(self, painter):
        rect = self.content_rect()
        path = self.outline()
        paint_shadow(painter, self.data, path, ("image", rect.width(), rect.height(), self.data.get("radius")))
        pixmap = adjusted_image(getattr(self.scene(), "board_path", None), self.data)
        if pixmap is None:
            self._paint_placeholder(painter, rect, path)
            return
        painter.save()
        painter.setClipPath(path, Qt.IntersectClip)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        painter.restore()
        width = float(self.data.get("stroke_width", 0.0) or 0.0)
        if width > 0:
            painter.setPen(QPen(QColor(self.data.get("stroke", dm.INK)), width))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)


ITEM_CLASSES[dm.PAGE] = DesignPageItem
ITEM_CLASSES[dm.SHAPE] = DesignShapeItem
ITEM_CLASSES[dm.IMAGE] = DesignImageItem

from .text_items import DesignTextItem  # noqa: E402 - textes (importent DesignElement d'ici)
from . import datavis as _datavis  # noqa: E402,F401 - enregistre tableaux et graphiques

__all__ = ["_datavis", "DesignTextItem"]
