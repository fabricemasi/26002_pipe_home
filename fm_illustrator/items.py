"""Éléments du module Illustrator dans la scène du board : plan de travail, tracé.

Ils héritent de `fm_miro.items.BoardItem` (identifiant, `data`, `to_dict` / `apply`, annulation, griser / masquer par
module) mais n'ont NI poignées NI déplacement Qt : en mode Illustrator, le contrôleur (`controller.py`) reçoit la
souris et dessine la sélection (`overlay.py`).

Fluidité : le chemin Qt d'un tracé est construit UNE fois par changement de géométrie (`sync`), son contour de
recherche une fois par zoom ; chaque élément est gardé en image à l'écran (`DeviceCoordinateCache` du board)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QGraphicsItem

from fm_miro.items import ITEM_CLASSES, POSITION_HAS_CHANGED, BoardItem, CommentItem, ConnectorItem, clone_data
from . import bezier as bz, model

ARTBOARD_Z = -300000.0                 # sous les pages Design (-200000) et les cadres de Miro (-100000)
CAPS = {"butt": Qt.FlatCap, "round": Qt.RoundCap, "square": Qt.SquareCap}
JOINS = {"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}


def qcolor(value: str) -> QColor:
    return QColor(value) if value else QColor(0, 0, 0, 0)


def qpath(subpaths, fill_rule: str = "nonzero") -> QPainterPath:
    """Chemin Qt des sous-tracés (coordonnées de l'élément)."""
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill if fill_rule == "evenodd" else Qt.WindingFill)
    for sub in subpaths:
        nodes = sub["nodes"]
        if not nodes:
            continue
        path.moveTo(nodes[0][0], nodes[0][1])
        for p0, c1, c2, p3 in bz.segments(sub):
            if bz.is_straight((p0, c1, c2, p3)):
                path.lineTo(p3[0], p3[1])
            else:
                path.cubicTo(c1[0], c1[1], c2[0], c2[1], p3[0], p3[1])
        if sub.get("closed"):
            path.closeSubpath()
    return path


def gradient_brush(g: dict, box: QRectF) -> QBrush:
    """Pinceau d'un dégradé (`paint.py`) posé sur la boîte de la géométrie."""
    from . import paint
    a = paint.absolute(g, (box.left(), box.top(), box.right(), box.bottom()))
    if g["type"] == "linear":
        gradient = QLinearGradient(a["x1"], a["y1"], a["x2"], a["y2"])
    else:
        gradient = QRadialGradient(a["cx"], a["cy"], a["r"])
    for offset, color in g["stops"]:
        gradient.setColorAt(offset, qcolor(color))
    return QBrush(gradient)


def stroke_pen(data: dict, box: QRectF | None = None) -> QPen:
    width = float(data.get("stroke_width", 1.0))
    pen = QPen(qcolor(data.get("stroke", "")), width)
    if data.get("stroke_gradient") and box is not None:
        pen.setBrush(gradient_brush(data["stroke_gradient"], box))
    pen.setCapStyle(CAPS.get(data.get("cap"), Qt.FlatCap))
    pen.setJoinStyle(JOINS.get(data.get("join"), Qt.MiterJoin))
    pen.setMiterLimit(float(data.get("miter", 10.0)))
    dash = [v for v in data.get("dash") or [] if v > 0]
    if dash and width > 0:
        if len(dash) % 2:
            dash = dash * 2
        pen.setDashPattern([max(0.01, v / width) for v in dash])      # Qt : en multiples de l'épaisseur
    return pen


def notify_moved(scene, items):
    """Fin d'un geste : index de la scène et commentaires / flèches accrochés, en UNE passe (le faire élément par
    élément pendant le geste coûtait ~2 ms par élément et par mouvement à 2 000 éléments : `scene.item_moved` parcourt
    tout le board)."""
    rect = None
    ids = set()
    for item in items:
        r = item.scene_rect()
        rect = r if rect is None else rect.united(r)
        ids.add(item.item_id)
    if rect is None:
        return
    scene.fit_index(rect)
    for other in scene.board_items():
        if isinstance(other, ConnectorItem) and ids & set(other.attached_ids()):
            other.sync()
        elif isinstance(other, CommentItem) and other.data.get("target") in ids:
            other.follow_target()


class IllItem(BoardItem):
    MODULE = "illustrator"
    CONNECTABLE = False
    RESIZABLE = False
    quiet_moves = False                 # vrai pendant un geste : pas de `scene.item_moved` par élément (notify_moved)

    def itemChange(self, change, value):
        if change is POSITION_HAS_CHANGED and IllItem.quiet_moves:
            return value
        return super().itemChange(change, value)

    def to_dict(self) -> dict:
        """Comme `BoardItem.to_dict`, avec `clone_data` au lieu de `copy.deepcopy` (listes de nœuds : ~5 fois plus
        rapide ; enregistrement automatique et annulation de 2 000 tracés : 86 -> 17 ms)."""
        data = clone_data(self.data)
        data["x"], data["y"] = round(self.pos().x(), 3), round(self.pos().y(), 3)
        data["z"] = self.zValue()
        return data

    def __init__(self, data: dict):
        super().__init__(data)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    def _place_from_data(self):
        super()._place_from_data()
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    def _apply_rotation(self):
        if self.rotation():
            self.setRotation(0.0)

    # pas de poignées ni de connexions de Miro : la sélection est dessinée par l'overlay du module
    def handle_at(self, pos):
        return None

    def connection_dot_at(self, scene_pos) -> bool:
        return False

    def paint_selection(self, painter):
        pass

    def boundingRect(self) -> QRectF:
        # Gardée (Qt la demande plusieurs fois par élément et par image) ; refaite au changement de géométrie / zoom.
        scene = self.scene()
        key = getattr(scene, "zoom", None) if scene is not None else None
        kept = getattr(self, "_bounds", None)
        if kept is not None and kept[0] == key:
            return kept[1]
        m = 2.0 / self._zoom()
        rect = self.paint_margin().united(self.content_rect()).adjusted(-m, -m, m, m)
        self._bounds = (key, rect)
        return rect

    def prepareGeometryChange(self):
        self._bounds = None
        super().prepareGeometryChange()

    def zoom_changed(self):
        self.prepareGeometryChange()


class IllArtboardItem(IllItem):
    """Plan de travail : rectangle blanc ombré, sous les objets ; nom et sélection peints par l'overlay."""

    def _place_from_data(self):
        super()._place_from_data()
        self.setZValue(ARTBOARD_Z + float(self.data.get("index", 0)))

    # Liste des plans gardée par la scène (`scene.ill_artboards`) : le contrôleur la lit à chaque image (noms
    # des plans) ; parcourir tout le board coûtait ~1,7 ms par lecture à 2 000 éléments.
    def added_to_scene(self, scene):
        if not hasattr(scene, "ill_artboards"):
            scene.ill_artboards = set()
        scene.ill_artboards.add(self)

    def removing_from_scene(self, scene):
        getattr(scene, "ill_artboards", set()).discard(self)

    def paint_margin(self) -> QRectF:
        return self.content_rect().adjusted(-2, -2, 5, 6)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.content_rect())
        return path

    def paint_content(self, painter):
        rect = self.content_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))                       # ombre portée simple (pas de flou : fluide)
        painter.drawRect(rect.translated(3, 4))
        painter.setBrush(qcolor(self.data.get("fill", "#ffffff")))
        painter.drawRect(rect)
        pen = QPen(QColor(0, 0, 0, 90), 0)                          # filet d'un pixel à tous les zooms
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)


class IllLayerItem(IllItem):
    """Calque : sans dessin ni zone ; tenu dans `scene.ill_layers` ; changer ses valeurs (masqué, verrouillé,
    annulation) remet ses objets à jour."""

    def __init__(self, data: dict):
        super().__init__(data)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemHasNoContents, True)

    def size(self) -> tuple[float, float]:
        return 0.0, 0.0

    def content_rect(self) -> QRectF:
        return QRectF()

    def boundingRect(self) -> QRectF:
        return QRectF()

    def paint(self, painter, option, widget=None):
        pass

    def added_to_scene(self, scene):
        if not hasattr(scene, "ill_layers"):
            scene.ill_layers = {}
        scene.ill_layers[self.item_id] = self
        self._sync_members(scene)

    def removing_from_scene(self, scene):
        getattr(scene, "ill_layers", {}).pop(self.item_id, None)

    def dependent_ids(self, scene) -> set:
        """Supprimer un calque supprime ses objets (même étape), comme Illustrator."""
        from .layers import layer_of
        return {i.item_id for i in scene.board_items() if isinstance(i, IllPathItem) and layer_of(scene, i) is self}

    def sync(self):
        scene = self.scene()
        if scene is not None:
            self._sync_members(scene)

    def _sync_members(self, scene):
        from .layers import layer_of
        for item in scene.board_items():           # visibilité seulement : les chemins ne sont pas refaits
            if isinstance(item, IllPathItem) and layer_of(scene, item) is self:
                item.apply_visibility()


class IllPathItem(IllItem):
    """Tracé : fond et contour peints depuis le chemin gardé (`self.path`)."""

    path = QPainterPath()
    _box = QRectF()
    _hit = None                                         # (zoom et tolérance, chemin de recherche du contour)

    def sync(self):
        self.path = qpath(self.data.get("subpaths") or [], self.data.get("fill_rule", "nonzero"))
        box = bz.bounds(self.data.get("subpaths") or [])
        self._box = QRectF() if box is None else QRectF(box[0], box[1], box[2] - box[0], box[3] - box[1])
        self._hit = None
        fill_g = self.data.get("fill_gradient")
        self._fill_brush = gradient_brush(fill_g, self._box) if fill_g else (
            QBrush(qcolor(self.data["fill"])) if self.data.get("fill") else None)
        self._pen = stroke_pen(self.data, self._box) if self.data.get("stroke") and \
            float(self.data.get("stroke_width", 0.0)) > 0 else None
        self.apply_visibility()

    def apply_visibility(self):
        """Masqué (objet, calque, module) et opacité, sans refaire le chemin."""
        scene = self.scene()
        layer = None
        if scene is not None and getattr(scene, "ill_layers", None):
            from .layers import layer_of
            layer = layer_of(scene, self)
        hidden = bool(self.data.get("hidden")) or (scene is not None and hasattr(scene, "module_hidden")
                                                   and scene.module_hidden(self.MODULE)) or \
            bool(layer is not None and layer.data.get("hidden"))
        self.setVisible(not hidden)
        self.setOpacity(scene.item_opacity(self) if scene is not None and hasattr(scene, "item_opacity")
                        else float(self.data.get("opacity", 1.0)))

    def module_opacity(self, faded: bool) -> float:
        from fm_cad.cad_items import FADE_OPACITY
        return float(self.data.get("opacity", 1.0)) * (FADE_OPACITY if faded else 1.0)

    def size(self) -> tuple[float, float]:
        return self._box.width(), self._box.height()

    def content_rect(self) -> QRectF:
        return QRectF(self._box)

    def geometry_rect(self) -> QRectF:
        """Cadre de la géométrie dans la scène (sans l'épaisseur du contour) : boîte de sélection d'Illustrator."""
        return self._box.translated(self.pos())

    def paint_margin(self) -> QRectF:
        w = float(self.data.get("stroke_width", 0.0)) if self.data.get("stroke") else 0.0
        m = w * max(1.0, float(self.data.get("miter", 10.0)) / 2) if self.data.get("join") == "miter" else w
        m = max(m, w) / 2 + 1.0
        return self._box.adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        return self.hit_path()

    def hit_path(self, tolerance_px: float = 4.0) -> QPainterPath:
        """Zone cliquable : la surface si l'objet a un fond, plus son contour élargi de `tolerance_px` à l'écran."""
        zoom = self._zoom()
        if self._hit is not None and self._hit[0] == (zoom, tolerance_px):
            return self._hit[1]
        stroker = QPainterPathStroker()
        width = float(self.data.get("stroke_width", 0.0)) if self.data.get("stroke") else 0.0
        stroker.setWidth(max(width, 0.0) + 2 * tolerance_px / zoom)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        hit = stroker.createStroke(self.path)
        if self.data.get("fill"):
            hit = hit.united(self.path)
        self._hit = ((zoom, tolerance_px), hit)
        return hit

    def contains_scene_point(self, scene_pos: QPointF, tolerance_px: float = 4.0) -> bool:
        local = scene_pos - self.pos()
        if not self.boundingRect().adjusted(-20, -20, 20, 20).contains(local):
            return False
        return self.hit_path(tolerance_px).contains(local)

    def paint_content(self, painter: QPainter):
        self.paint_path(painter, outline=bool(getattr(self.scene(), "ill_outline", False)))

    def paint_path(self, painter: QPainter, outline: bool = False):
        """Fond puis contour (ordre d'Illustrator par défaut) ; `outline` = mode Tracés (Ctrl+Y) : filet noir fin."""
        if outline:
            painter.setPen(QPen(QColor("#000000"), 0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path)
            return
        if self._fill_brush is not None:
            painter.fillPath(self.path, self._fill_brush)
        if self._pen is not None:
            painter.strokePath(self.path, self._pen)


ITEM_CLASSES[model.ARTBOARD] = IllArtboardItem
ITEM_CLASSES[model.PATH] = IllPathItem
ITEM_CLASSES[model.LAYER] = IllLayerItem
