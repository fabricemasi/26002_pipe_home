"""Éléments du module Illustrator dans la scène du board : plan de travail, tracé.

Ils héritent de `fm_miro.items.BoardItem` (identifiant, `data`, `to_dict` / `apply`, annulation, griser / masquer par
module) mais n'ont NI poignées NI déplacement Qt : en mode Illustrator, le contrôleur (`controller.py`) reçoit la
souris et dessine la sélection (`overlay.py`).

Fluidité : le chemin Qt d'un tracé est construit UNE fois par changement de géométrie (`sync`), son contour de
recherche une fois par zoom ; chaque élément est gardé en image à l'écran (`DeviceCoordinateCache` du board)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QPolygonF, QRadialGradient, QTransform)
from PySide6.QtWidgets import QGraphicsItem

from fm_miro.items import ITEM_CLASSES, POSITION_HAS_CHANGED, BoardItem, CommentItem, ConnectorItem, clone_data
from . import appearance, bezier as bz, brushes, model

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
    snapshot_ids = None                 # zoom continu : objets peints par l'image de la vue (`snapshot.py`)

    def snap_inner(self) -> bool:
        """Magnétisme du board (`fm_board.snap_guides`) : un objet d'Illustrator est INTERNE au document (le plan de
        travail, lui, en est le bord : `IllArtboardItem`)."""
        return True

    def paint(self, painter, option, widget=None):
        ids = IllItem.snapshot_ids
        if ids is not None and self.item_id in ids:
            return                                      # dans l'image reposée à l'échelle : rien à peindre
        super().paint(painter, option, widget)

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
        key = getattr(scene, "pad_zoom", None) if scene is not None else None
        kept = getattr(self, "_bounds", None)
        if kept is not None and kept[0] == key:
            return kept[1]
        m = 2.0 / self._pad_zoom()     # par paliers : voir BoardScene.set_zoom (sinon plantage a l'effacement)
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

    def snap_inner(self) -> bool:
        return False                    # bord du document (magnétisme du board)

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

    def _build_geometry(self):
        self.path = qpath(self.data.get("subpaths") or [], self.data.get("fill_rule", "nonzero"))
        box = bz.bounds(self.data.get("subpaths") or [])
        self._box = QRectF() if box is None else QRectF(box[0], box[1], box[2] - box[0], box[3] - box[1])

    def bake(self, m):
        """Matrice (repère de la scène décalé de la place de l'élément) appliquée aux nœuds : fin d'un geste de
        transformation, symétrie, rotation."""
        bz.transform(self.data["subpaths"], m)

    # -- masques (objet `mask` du groupe : `scene.ill_masks` = {groupe: masque}) --
    def mask_item(self):
        """Masque qui s'applique à cet objet (masque de son groupe, pas lui-même), ou None."""
        group = self.data.get("group")
        scene = self.scene()
        if not group or scene is None:
            return None
        mask = getattr(scene, "ill_masks", {}).get(group)
        return mask if mask is not None and mask is not self and mask.scene() is scene else None

    def _register_mask(self):
        scene = self.scene()
        if scene is None:
            return
        masks = getattr(scene, "ill_masks", None)
        if masks is None:
            masks = scene.ill_masks = {}
        group, kind = self.data.get("group") or "", self.data.get("mask") or ""
        touched = set()
        for g, m in list(masks.items()):
            if m is self and (g != group or not kind):
                del masks[g]
                touched.add(g)
        if kind and group and masks.get(group) is not self:
            masks[group] = self
            touched.add(group)
        if kind and group:
            touched.add(group)
        for g in touched:
            self._refresh_members(scene, g)

    def _refresh_members(self, scene, group):
        for item in scene.board_items():
            if isinstance(item, IllPathItem) and item is not self and item.data.get("group") == group:
                item.setCacheMode(QGraphicsItem.NoCache)    # image gardée jetée (update() ne suffit pas
                item._apply_mask_cache()                    # pour le rendu hors vue : export, aperçus)
                item.update()

    def _apply_mask_cache(self):
        """Image gardée, masqué ou non : l'écrêtage / la composition ne sont refaits qu'au zoom ou quand le masque
        change (`_refresh_members`) ; un membre déplacé SANS son masque (ou l'inverse) est peint sans image pendant le
        geste (`tools.MoveGesture`). Mesure, 200 objets écrêtés : image 34 ms -> voir docs/agents/fm_illustrator.md."""
        if self.cacheMode() != QGraphicsItem.DeviceCoordinateCache:
            self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def removing_from_scene(self, scene):
        masks = getattr(scene, "ill_masks", {})
        for g, m in list(masks.items()):
            if m is self:
                del masks[g]
                self._refresh_members(scene, g)

    def sync(self):
        self._build_geometry()
        self._register_mask()
        mask = self.mask_item()
        key = (self.data.get("group"), id(mask) if mask is not None else 0)
        old = getattr(self, "_mask_key", None)
        if key != old:                                        # entré dans un groupe masqué ou sorti : image jetée
            self._mask_key = key
            if old is not None:
                self.setCacheMode(QGraphicsItem.NoCache)
        self._apply_mask_cache()
        self.draw_path = self._effect_path()
        self._extra_pens = [(QPen(qcolor(s["color"]), s["width"], Qt.SolidLine, CAPS.get(self.data.get("cap"),
                                                                                  Qt.FlatCap),
                                  JOINS.get(self.data.get("join"), Qt.MiterJoin)), s["opacity"])
                            for s in self.data.get("extra_strokes") or [] if s["width"] > 0]
        self._raster = appearance.has_raster(self.data)
        self._fx_generation = getattr(self, "_fx_generation", 0) + 1     # image d'effets gardée : périmée
        self._hit = None
        fill_g = self.data.get("fill_gradient")
        self._fill_brush = gradient_brush(fill_g, self._box) if fill_g else (
            QBrush(qcolor(self.data["fill"])) if self.data.get("fill") else None)
        self._pen = stroke_pen(self.data, self._box) if self.data.get("stroke") and \
            float(self.data.get("stroke_width", 0.0)) > 0 else None
        self._brushed = False                           # contour à largeur variable / calligraphique : une surface
        if self._pen is not None and self.data.get("subpaths") and brushes.has_brush(self.data):
            self._brushed = True                        # calculée au 1er affichage / clic (`_brush_shape`)
            self._brush_fill = gradient_brush(self.data["stroke_gradient"], self._box) \
                if self.data.get("stroke_gradient") else QBrush(qcolor(self.data["stroke"]))
            self._pen = None
        # Limites gardées jetées APRÈS la nouvelle géométrie : `prepareGeometryChange` (index BSP) relit les limites
        # AVANT le changement et les gardait ; le tracé modifié n'était repeint que dans son ancien cadre.
        self._bounds = None
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

    def _effect_path(self) -> QPainterPath:
        """Chemin DESSINÉ : effets vectoriels (décalage, arrondis) appliqués ; sinon le chemin de l'objet."""
        if not appearance.active(self.data, appearance.VECTOR):
            return self.path
        return qpath(appearance.render_subpaths(self.data), self.data.get("fill_rule", "nonzero"))

    def paint_margin(self) -> QRectF:
        w = brushes.stroke_hit_width(self.data) if self.data.get("stroke") else 0.0
        m = w * max(1.0, float(self.data.get("miter", 10.0)) / 2) if self.data.get("join") == "miter" else w
        m = max(m, w) / 2 + 1.0 + appearance.margin(self.data)
        drawn = getattr(self, "draw_path", None)
        box = self._box if drawn is None or drawn is self.path else self._box.united(drawn.boundingRect())
        return box.adjusted(-m, -m, m, m)

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
        drawn = getattr(self, "draw_path", self.path)
        hit = stroker.createStroke(drawn)
        if self.data.get("fill"):
            hit = hit.united(drawn)
        if self._brushed:
            hit = hit.united(self._brush_shape())
        self._hit = ((zoom, tolerance_px), hit)
        return hit

    def contains_scene_point(self, scene_pos: QPointF, tolerance_px: float = 4.0) -> bool:
        local = scene_pos - self.pos()
        if not self.boundingRect().adjusted(-20, -20, 20, 20).contains(local):
            return False
        return self.hit_path(tolerance_px).contains(local) and self._inside_mask(scene_pos)

    def _inside_mask(self, scene_pos: QPointF) -> bool:
        """Écrêté : seule la partie visible (dans le masque) se clique."""
        mask = self.mask_item()
        if mask is None or mask.data.get("mask") != "clip":
            return True
        return mask.path.contains(mask.mapFromScene(scene_pos))

    def paint_content(self, painter: QPainter):
        outline = bool(getattr(self.scene(), "ill_outline", False))
        if self.data.get("mask") and not outline:
            return                                      # un masque ne se peint pas (mode Tracés : son contour)
        mask = None if outline else self.mask_item()
        if mask is None:
            self.paint_path(painter, outline=outline)
        elif mask.data.get("mask") == "clip":
            painter.save()
            painter.setClipPath(self.mapFromItem(mask, mask.path), Qt.IntersectClip)
            self.paint_path(painter)
            painter.restore()
        else:
            self._paint_through_opacity_mask(painter, mask)

    MAX_MASK_PIXELS = 4096 * 4096

    def _paint_through_opacity_mask(self, painter: QPainter, mask):
        """Masque d'opacité : l'objet est peint dans une image, le masque (avec ses couleurs) dans une autre dont la
        luminance devient l'alpha (hors du masque : caché, comme l'option « Écrêter » d'Illustrator, active par
        défaut). Une fois par image gardée de l'élément (zoom, changement), pas à chaque image du board."""
        world = painter.worldTransform()
        device = world.mapRect(self.boundingRect()).toAlignedRect()
        if device.isEmpty() or device.width() * device.height() > self.MAX_MASK_PIXELS:
            self.paint_path(painter)
            return
        shift = QTransform.fromTranslate(-device.x(), -device.y())
        art = QImage(device.size(), QImage.Format_ARGB32_Premultiplied)
        art.fill(Qt.transparent)
        p = QPainter(art)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setTransform(world * shift)
        self.paint_path(p)
        p.end()
        lum = QImage(device.size(), QImage.Format_ARGB32_Premultiplied)
        lum.fill(QColor("#000000"))
        p = QPainter(lum)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setTransform(mask.itemTransform(self)[0] * world * shift)
        mask.paint_path(p)
        p.end()
        gray = lum.convertToFormat(QImage.Format_Grayscale8)
        if mask.data.get("mask_invert"):
            gray.invertPixels()
        alpha = QImage(device.size(), QImage.Format_ARGB32_Premultiplied)
        alpha.fill(Qt.white)
        alpha.setAlphaChannel(gray)
        p = QPainter(art)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, alpha)
        p.end()
        painter.save()
        painter.resetTransform()
        painter.drawImage(device.topLeft(), art)
        painter.restore()

    draw_path = QPainterPath()
    _brushed = False
    _extra_pens: list = []

    def _brush_shape(self):
        """Surface du contour-pinceau, calculée À LA DEMANDE (affichage, clic) et gardée tant que la géométrie et le
        pinceau ne changent pas : à l'ouverture d'un dessin, les traits hors de l'écran ne coûtent rien (~1 ms
        chacun sinon : 500 traits au pinceau ajoutaient ~1 s)."""
        if not self._brushed:
            return None
        key = self._fx_generation                       # augmenté à chaque `sync` (tout changement y passe)
        kept = getattr(self, "_brush_kept", None)
        if kept is None or kept[0] != key:
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)
            for poly in brushes.outline_polygons(self.data):     # d'un bloc : pas nœud par nœud
                path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
                path.closeSubpath()
            kept = self._brush_kept = (key, path)
        return kept[1]
    _raster = False

    def paint_path(self, painter: QPainter, outline: bool = False):
        """Aspect : contours supplémentaires, fond puis contour (ordre d'Illustrator par défaut), puis effets tramés ;
        `outline` = mode Tracés (Ctrl+Y) : filet noir fin de la géométrie."""
        if outline:
            painter.setPen(QPen(QColor("#000000"), 0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path)
            return
        if self._raster:
            from .effects import paint_with_effects
            paint_with_effects(self, painter, self._paint_vector)
        else:
            self._paint_vector(painter)

    def _paint_vector(self, painter: QPainter):
        path = self.draw_path
        for pen, opacity in self._extra_pens:
            painter.save()
            painter.setOpacity(painter.opacity() * opacity)
            painter.strokePath(path, pen)
            painter.restore()
        if self._fill_brush is not None:
            painter.fillPath(path, self._fill_brush)
        if self._pen is not None:
            painter.strokePath(path, self._pen)
        elif self._brushed:
            painter.fillPath(self._brush_shape(), self._brush_fill)


class IllTextItem(IllPathItem):
    """Texte (`text.py`) : le chemin des lettres est peint comme un tracé (fond, contour, dégradés) ; zone cliquable =
    son cadre ; rotation propre (`rotation`, point et captif) ; ne se peint pas pendant l'édition sur place."""
    editing = False
    _layout = None

    def _build_geometry(self):
        from .text import layout
        self._layout = layout(self.data)
        self.path = self._layout.path
        self._box = QRectF(self._layout.box)

    def layout_box(self) -> QRectF:
        return QRectF(self._box)

    def _effect_path(self) -> QPainterPath:
        return self.path                                # effets vectoriels : pas sur un texte (Créer les contours)

    def overflow(self) -> bool:
        return bool(self._layout is not None and self._layout.overflow)

    def _apply_rotation(self):
        angle = float(self.data.get("rotation", 0.0)) if self.data.get("mode") != "path" else 0.0
        self.setTransformOriginPoint(0.0, 0.0)
        if self.rotation() != angle:
            self.setRotation(angle)

    def geometry_rect(self) -> QRectF:
        return self.mapRectToScene(self._box)

    def outline_polygon(self):
        return self.mapToScene(self._box)

    def hit_path(self, tolerance_px: float = 4.0) -> QPainterPath:
        t = tolerance_px / self._zoom()
        path = QPainterPath()
        path.addRect(self._box.adjusted(-t, -t, t, t))
        return path

    def contains_scene_point(self, scene_pos: QPointF, tolerance_px: float = 4.0) -> bool:
        return self.hit_path(tolerance_px).contains(self.mapFromScene(scene_pos))

    def paint_content(self, painter: QPainter):
        if not self.editing:
            super().paint_content(painter)

    def bake(self, m):
        """Point : taille × l'échelle moyenne, origine déplacée, rotation ajoutée ; captif : cadre redimensionné (la
        taille reste) ; sur tracé : tracé de base transformé, taille × l'échelle. Une symétrie ne retourne pas les
        lettres (seule la place suit)."""
        import math
        a, b, c, d, _e, _f = m
        det = abs(a * d - b * c)
        data = self.data
        if data.get("mode") == "path" and data.get("subpaths"):
            bz.transform(data["subpaths"], m)
            data["font_size"] = max(0.5, data["font_size"] * math.sqrt(det))
            return
        ox, oy = bz.apply(m, 0.0, 0.0)
        data["x"] = round(data["x"] + ox, 3)
        data["y"] = round(data["y"] + oy, 3)
        sx, sy = math.hypot(a, b), math.hypot(c, d)
        if data.get("mode") == "area":
            data["w"] = max(1.0, data["w"] * sx)
            data["h"] = max(1.0, data["h"] * sy)
        else:
            data["font_size"] = max(0.5, data["font_size"] * math.sqrt(sx * sy))
        if a * d - b * c > 0:
            angle = math.degrees(math.atan2(b, a))
            data["rotation"] = round((float(data.get("rotation", 0.0)) + angle + 180.0) % 360.0 - 180.0, 4)


class IllImageItem(IllPathItem):
    """Image placée : le rectangle (0, 0, w, h) transformé par `matrix` ; image décodée une fois et partagée
    (`fm_miro.items.asset_pixmap`), peinte lissée dans l'image gardée de l'élément (refaite au zoom seulement).
    Effets tramés, masques, opacité : comme un tracé ; pas d'effets vectoriels ni de fond / contour."""

    def _matrix(self):
        return tuple(self.data.get("matrix") or (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))

    def _build_geometry(self):
        m = self._matrix()
        w, h = float(self.data.get("w", 100.0)), float(self.data.get("h", 100.0))
        pts = [QPointF(*bz.apply(m, x, y)) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        path.closeSubpath()
        self.path = path
        self._box = path.boundingRect()

    def _effect_path(self) -> QPainterPath:
        return self.path

    def hit_path(self, tolerance_px: float = 4.0) -> QPainterPath:
        return self.path                                # toute l'image se clique

    def bake(self, m):
        self.data["matrix"] = [round(v, 9) for v in bz.multiply(self._matrix(), m)]

    export_images = None                # export PDF en cours : {asset: image en PLEINE résolution} (`pdf.py`)

    def pixmap(self):
        from fm_miro.items import asset_pixmap
        scene = self.scene()
        path = getattr(scene, "board_path", None) if scene is not None else None
        if path is None:
            return None
        cache = IllImageItem.export_images
        if cache is not None:                           # export : l'image d'origine, pas la réduite de l'affichage
            name = self.data.get("asset", "")
            if name not in cache:
                from PySide6.QtGui import QImageReader, QPixmap
                from fm_board.serialization import asset_path, is_asset_name
                reader = QImageReader(str(asset_path(path, name))) if is_asset_name(name) else None
                if reader is not None:
                    reader.setAutoTransform(True)
                image = reader.read() if reader is not None else None
                cache[name] = QPixmap.fromImage(image) if image is not None and not image.isNull() else None
            if cache[name] is not None:
                return cache[name]
        return asset_pixmap(path, self.data.get("asset", ""))

    def _paint_vector(self, painter: QPainter):
        w, h = float(self.data.get("w", 100.0)), float(self.data.get("h", 100.0))
        target = QRectF(0, 0, w, h)
        painter.save()
        painter.setTransform(QTransform(*self._matrix()), True)
        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        else:                                           # image absente : cadre barré (comme Illustrator)
            painter.fillRect(target, QColor(230, 230, 230))
            painter.setPen(QPen(QColor(150, 150, 150), 0))
            painter.drawRect(target)
            painter.drawLine(target.topLeft(), target.bottomRight())
            painter.drawLine(target.topRight(), target.bottomLeft())
        painter.restore()


ITEM_CLASSES[model.ARTBOARD] = IllArtboardItem
ITEM_CLASSES[model.IMAGE] = IllImageItem
ITEM_CLASSES[model.TEXT] = IllTextItem
ITEM_CLASSES[model.PATH] = IllPathItem
ITEM_CLASSES[model.LAYER] = IllLayerItem
