"""Elements d'un board : un `QGraphicsObject` par type (post-it, texte, forme, image, trait, cadre, connecteur,
commentaire).

Chaque element garde ses valeurs dans `self.data` (le dictionnaire du fichier, voir `model`) ; `to_dict()` le
rend avec sa place du moment, `apply(d)` pose un etat (annulation, chargement). La scene (`scene.BoardScene`)
fournit l'echelle de la vue (`zoom` : poignees de taille constante a l'ecran), la couleur de selection et le
dossier du board (images).

Selection (comme Miro, capture 4 de l'utilisateur) : contour bleu, poignees rondes blanches aux coins, bords
tirables, poignee de ROTATION en bas a gauche (formes, textes, images), points de CONNEXION bleus au milieu des
cotes, a l'exterieur (tirer = une fleche, voir `view`). Un element VERROUILLE ne bouge plus, ne se
redimensionne plus et ne se modifie plus (cadenas affiche). Fluidite : chaque element est garde en image a
l'echelle de l'ecran (`DeviceCoordinateCache`) ; l'ombre des post-it est une image floutee calculee UNE fois et
posee etiree (aucun flou par image)."""
from __future__ import annotations

import copy
import math
from collections import OrderedDict

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QImage, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF, QTextCharFormat,
                           QTextCursor, QTextOption, QTransform)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsTextItem, QStyle

from . import model

HANDLE_PX = 9          # poignees de redimensionnement, en pixels d'ecran
EDGE_PX = 6            # zone tirable des bords
ROTATE_PX = 22         # poignee de rotation : decalage sous le coin bas gauche
CONNECT_PX = 20        # points de connexion : distance hors des cotes
MIN_SIZE = 16.0
TEXT_PAD = 12.0
IMAGE_MAX_SIDE = 2400  # image decodee au plus a cette taille (memoire) ; le fichier garde l'original

_FAMILY_CACHE: dict[str, str] = {}


def resolve_family(family: str) -> str:
    """Police demandee si elle est installee ; sinon Noto Sans (police par defaut de Miro), sinon Segoe UI."""
    key = family or ""
    if key not in _FAMILY_CACHE:
        installed = set(QFontDatabase.families())
        for candidate in (family, "Noto Sans", "Segoe UI", "Arial"):
            if candidate and candidate in installed:
                _FAMILY_CACHE[key] = candidate
                break
        else:
            _FAMILY_CACHE[key] = family or "Segoe UI"
    return _FAMILY_CACHE[key]


def text_font(data: dict, size: float) -> QFont:
    font = QFont(resolve_family(str(data.get("font_family") or "")))
    font.setPixelSize(max(4, int(round(size))))
    font.setBold(bool(data.get("bold", False)))
    font.setItalic(bool(data.get("italic", False)))
    font.setUnderline(bool(data.get("underline", False)))
    font.setStrikeOut(bool(data.get("strike", False)))
    return font


def _plain_font(size: float, bold: bool = False) -> QFont:
    """Police en unites du board ; tailles fractionnaires permises (titre de cadre de taille constante a
    l'ecran : 14 / zoom vaut 0,7 a 2 000 %) — une taille en pixels entiers aurait ete arrondie a 4 et le titre
    serait devenu enorme."""
    font = QFont(resolve_family(""))
    if size >= 4:
        font.setPixelSize(int(round(size)))
    else:
        font.setPointSizeF(max(0.01, size * 0.75))
    font.setBold(bold)
    return font


ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


def pen_style(name: str) -> Qt.PenStyle:
    return {"dashed": Qt.DashLine, "dotted": Qt.DotLine}.get(name, Qt.SolidLine)


class _Text(QGraphicsTextItem):
    """Texte d'un element, modifiable sur place. L'element parent decide de sa place (`layout_text`)."""

    def __init__(self, owner: "BoardItem"):
        super().__init__(owner)
        self.owner = owner
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.NoButton)            # les clics vont a l'element (deplacer, selectionner)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.document().setDocumentMargin(0)
        self.document().contentsChanged.connect(owner.text_changed)

    def editing(self) -> bool:
        return bool(self.textInteractionFlags() & Qt.TextEditorInteraction)

    def start(self):
        self.setCacheMode(QGraphicsItem.NoCache)             # curseur et frappe dessines en direct
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setFocus(Qt.MouseFocusReason)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

    def stop(self):
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.editing():
            self.owner.finish_edit()


    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            return
        super().keyPressEvent(event)


class BoardItem(QGraphicsObject):
    """Base commune : identifiant, valeurs, selection et poignees, rotation, verrou, notification des
    deplacements."""

    RESIZABLE = True
    KEEP_RATIO = False
    CONNECTABLE = True
    TEXT_KEY: str | None = None          # champ de `data` montre / modifie par le texte sur place

    def __init__(self, data: dict):
        super().__init__()
        self.data = copy.deepcopy(data)
        self.item_id = self.data["id"]
        self.kind = self.data["type"]
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        # Fluidite : chaque element est garde en image a l'echelle de l'ecran ; deplacer le canvas ne fait que
        # les reposer (mesure, 400 elements en 2400 x 1300 : ~32 -> ~15 ms par image). Refait au zoom.
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self._gesture = None            # ("resize", poignee, ...) | ("rotate", ...)
        self._edit_before = None
        self._laying = False
        self.text_item = _Text(self) if self.TEXT_KEY else None
        self._place_from_data()

    # -- etat --
    def to_dict(self) -> dict:
        data = copy.deepcopy(self.data)
        data["x"], data["y"] = round(self.pos().x(), 2), round(self.pos().y(), 2)
        data["z"] = self.zValue()
        if self.text_item is not None and self.TEXT_KEY:
            data[self.TEXT_KEY] = self.text_item.toPlainText()
        return data

    def apply(self, data: dict):
        self.prepareGeometryChange()
        self.data = copy.deepcopy(data)
        self._place_from_data()
        self.update()

    def locked(self) -> bool:
        return bool(self.data.get("locked", False))

    def _place_from_data(self):
        self.setPos(float(self.data.get("x", 0.0)), float(self.data.get("y", 0.0)))
        self.setZValue(float(self.data.get("z", 0.0)))
        self.setFlag(QGraphicsItem.ItemIsMovable, not self.locked())
        if self.text_item is not None:
            text = str(self.data.get(self.TEXT_KEY, ""))
            if self.text_item.toPlainText() != text:
                self.text_item.setPlainText(text)
        self.sync()
        self._apply_rotation()

    def _apply_rotation(self):
        w, h = self.size()
        self.setTransformOriginPoint(w / 2, h / 2)
        angle = float(self.data.get("rotation", 0.0)) if self.kind in model.ROTATABLE else 0.0
        if self.rotation() != angle:
            self.setRotation(angle)

    def sync(self):
        """Apparence recalculee depuis `data` (police, texte...)."""
        self.layout_text()

    # -- geometrie --
    def size(self) -> tuple[float, float]:
        return float(self.data.get("w", 0.0)), float(self.data.get("h", 0.0))

    def content_rect(self) -> QRectF:
        w, h = self.size()
        return QRectF(0, 0, w, h)

    def scene_rect(self) -> QRectF:
        return self.mapRectToScene(self.content_rect())

    def _zoom(self) -> float:
        scene = self.scene()
        return max(0.05, float(getattr(scene, "zoom", 1.0))) if scene is not None else 1.0

    def _margin(self) -> float:
        extra = ROTATE_PX + HANDLE_PX if self.kind in model.ROTATABLE else 0
        return (max(HANDLE_PX + 3, CONNECT_PX + 6 if self.CONNECTABLE else 0, extra)) / self._zoom()

    def paint_margin(self) -> QRectF:
        """Zone peinte au-dela du contenu (ombre des post-it...)."""
        return self.content_rect()

    def boundingRect(self) -> QRectF:
        m = self._margin() if self.isSelected() else 3 / self._zoom()
        return self.paint_margin().united(self.content_rect()).adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        rect = self.content_rect()
        if self._handles_shown():
            m = HANDLE_PX / self._zoom()
            rect = rect.adjusted(-m, -m, m, m)
            if self.kind in model.ROTATABLE:
                path.addEllipse(self._rotate_handle_center(), HANDLE_PX / self._zoom(), HANDLE_PX / self._zoom())
        path.addRect(rect)
        return path

    def anchor_points(self) -> list[QPointF]:
        """Points d'accroche des connecteurs (milieux des cotes), en coordonnees de scene."""
        r = self.content_rect()
        return [self.mapToScene(p) for p in (QPointF(r.center().x(), r.top()), QPointF(r.right(), r.center().y()),
                                             QPointF(r.center().x(), r.bottom()), QPointF(r.left(), r.center().y()))]

    def connection_dots(self) -> list[QPointF]:
        """Points de connexion affiches (hors des cotes), en coordonnees de l'element."""
        r = self.content_rect()
        d = CONNECT_PX / self._zoom()
        return [QPointF(r.center().x(), r.top() - d), QPointF(r.right() + d, r.center().y()),
                QPointF(r.center().x(), r.bottom() + d), QPointF(r.left() - d, r.center().y())]

    def connection_dot_at(self, scene_pos: QPointF) -> bool:
        if not (self.CONNECTABLE and self._handles_shown()):
            return False
        local = self.mapFromScene(scene_pos)
        reach = 7 / self._zoom()
        return any(QLineF(local, dot).length() <= reach for dot in self.connection_dots())

    def zoom_changed(self):
        self.prepareGeometryChange()

    # -- selection / poignees --
    def _accent(self) -> QColor:
        return QColor(getattr(self.scene(), "accent", model.MIRO_ACCENT))

    def _handles_shown(self) -> bool:
        scene = self.scene()
        return (self.isSelected() and not self.locked() and scene is not None
                and len(scene.selectedItems()) == 1)

    def _corner_rects(self) -> list[tuple[str, QRectF]]:
        size = HANDLE_PX / self._zoom()
        r = self.content_rect()
        return [(name, QRectF(p.x() - size / 2, p.y() - size / 2, size, size))
                for name, p in (("tl", r.topLeft()), ("tr", r.topRight()), ("br", r.bottomRight()),
                                ("bl", r.bottomLeft()))]

    def _rotate_handle_center(self) -> QPointF:
        r = self.content_rect()
        d = ROTATE_PX / self._zoom()
        return QPointF(r.left() - d * 0.75, r.bottom() + d * 0.75)

    def handle_at(self, pos: QPointF) -> str | None:
        """Poignee sous `pos` (coordonnees de l'element) : coins, bords (l, r, t, b), rotation."""
        if not self._handles_shown():
            return None
        zoom = self._zoom()
        if self.kind in model.ROTATABLE and QLineF(pos, self._rotate_handle_center()).length() <= HANDLE_PX / zoom:
            return "rotate"
        if not self.RESIZABLE:
            return None
        grow = 2 / zoom
        for name, rect in self._corner_rects():
            if rect.adjusted(-grow, -grow, grow, grow).contains(pos):
                return name
        if self.KEEP_RATIO:
            return None
        r = self.content_rect()
        edge = EDGE_PX / zoom
        inside_y = r.top() <= pos.y() <= r.bottom()
        inside_x = r.left() <= pos.x() <= r.right()
        if inside_y and abs(pos.x() - r.left()) <= edge:
            return "l"
        if inside_y and abs(pos.x() - r.right()) <= edge:
            return "r"
        if inside_x and abs(pos.y() - r.top()) <= edge:
            return "t"
        if inside_x and abs(pos.y() - r.bottom()) <= edge:
            return "b"
        return None

    def paint_selection(self, painter: QPainter):
        if not self.isSelected():
            return
        zoom = self._zoom()
        painter.setPen(QPen(self._accent(), 1.5 / zoom))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.content_rect())
        if not self._handles_shown():
            return
        if self.RESIZABLE:
            painter.setPen(QPen(QColor("#9a9a9a"), 1.2 / zoom))
            painter.setBrush(QColor("#ffffff"))
            for _name, rect in self._corner_rects():
                painter.drawEllipse(rect)
        if self.CONNECTABLE:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._accent())
            for dot in self.connection_dots():
                painter.drawEllipse(dot, 3.2 / zoom, 3.2 / zoom)
        if self.kind in model.ROTATABLE:
            c = self._rotate_handle_center()
            r = 6.0 / zoom
            pen = QPen(QColor("#1a1a1a"), 1.4 / zoom)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 60 * 16, 280 * 16)
            tip = QPointF(c.x() + r * math.cos(math.radians(60)), c.y() - r * math.sin(math.radians(60)))
            painter.drawLine(tip, tip + QPointF(-3.5 / zoom, -0.8 / zoom))
            painter.drawLine(tip, tip + QPointF(0.6 / zoom, 3.4 / zoom))

    def paint_badges(self, painter: QPainter):
        """Cadenas (verrouille) et lien, en haut a droite, taille constante a l'ecran."""
        badges = []
        if self.locked():
            badges.append("lock")
        if self.data.get("link"):
            badges.append("link")
        if not badges:
            return
        zoom = self._zoom()
        r = self.content_rect()
        size = 14 / zoom
        x = r.right() - size - 4 / zoom
        for badge in badges:
            box = QRectF(x, r.top() + 4 / zoom, size, size)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.drawRoundedRect(box, 3 / zoom, 3 / zoom)
            painter.setPen(QPen(QColor("#1a1a1a"), 1.2 / zoom))
            painter.setBrush(Qt.NoBrush)
            c = box.center()
            if badge == "lock":
                painter.drawRect(QRectF(c.x() - 3.5 / zoom, c.y() - 0.5 / zoom, 7 / zoom, 5 / zoom))
                painter.drawArc(QRectF(c.x() - 2.5 / zoom, c.y() - 4.5 / zoom, 5 / zoom, 6 / zoom), 0, 180 * 16)
            else:
                for dx in (-1.6, 1.6):
                    painter.drawRoundedRect(QRectF(c.x() + dx / zoom - 2.6 / zoom, c.y() - 1.6 / zoom,
                                                   5.2 / zoom, 3.2 / zoom), 1.6 / zoom, 1.6 / zoom)
            x -= size + 3 / zoom

    def paint(self, painter, option, widget=None):
        option.state = option.state & ~QStyle.State_Selected
        painter.setRenderHint(QPainter.Antialiasing, True)
        self.paint_content(painter)
        self.paint_badges(painter)
        self.paint_selection(painter)

    def paint_content(self, painter: QPainter):
        pass

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            self.prepareGeometryChange()
        elif change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None and hasattr(scene, "item_moved"):
                scene.item_moved(self)
        return super().itemChange(change, value)

    # -- redimensionnement / rotation a la souris --
    def hoverMoveEvent(self, event):
        handle = self.handle_at(event.pos())
        cursors = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                   "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor,
                   "b": Qt.SizeVerCursor, "rotate": Qt.CrossCursor}
        if handle in cursors:
            self.setCursor(cursors[handle])
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        handle = self.handle_at(event.pos()) if event.button() == Qt.LeftButton else None
        if handle is not None:
            scene = self.scene()
            if handle == "rotate":
                center = self.mapToScene(self.content_rect().center())
                start = QLineF(center, event.scenePos()).angle()
                self._gesture = ("rotate", center, start, self.rotation())
            else:
                w, h = self.size()
                self._gesture = ("resize", handle, QRectF(0, 0, w, h), QTransform(self.sceneTransform()))
            if scene is not None:
                scene.begin_change([self])
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        gesture = self._gesture
        if gesture is None:
            super().mouseMoveEvent(event)
            return
        self._last_move = (QPointF(event.scenePos()), event.modifiers())
        self._resize_to(event.scenePos(), event.modifiers())
        event.accept()

    def refresh_gesture(self, modifiers):
        """Touche enfoncee / relachee pendant un geste (Maj sur un cadre : aimantation coupee / reprise) : le
        dernier mouvement est rejoue avec les nouvelles touches, sans attendre que la souris bouge."""
        last = getattr(self, "_last_move", None)
        if self._gesture is not None and self._gesture[0] == "resize" and last is not None:
            self._resize_to(last[0], modifiers)

    def _snap_off_key(self, modifiers) -> bool:
        """Cadre : Maj tenu coupe l'aimantation le temps du geste (demande de l'utilisateur)."""
        return self.kind == "frame" and bool(modifiers & Qt.ShiftModifier)

    def _resize_to(self, scene_pos, modifiers):
        gesture = self._gesture
        if gesture[0] == "rotate":
            _kind, center, start, angle0 = gesture
            angle = angle0 - (QLineF(center, scene_pos).angle() - start)
            if modifiers & Qt.ShiftModifier:
                angle = round(angle / 15.0) * 15.0
            angle = ((angle + 180.0) % 360.0) - 180.0
            self.data["rotation"] = round(angle, 2)
            self._apply_rotation()
            scene = self.scene()
            if scene is not None:
                scene.item_moved(self)
            return
        _kind, handle, start, transform = gesture
        inverse, _ok = transform.inverted()
        local = inverse.map(scene_pos)                     # coordonnees de l'element AU DEBUT du geste
        left, top, right, bottom = start.left(), start.top(), start.right(), start.bottom()
        if "l" in handle:
            left = min(local.x(), right - MIN_SIZE)
        if "r" in handle:
            right = max(local.x(), left + MIN_SIZE)
        if "t" in handle:
            top = min(local.y(), bottom - MIN_SIZE)
        if "b" in handle:
            bottom = max(local.y(), top + MIN_SIZE)
        # Maj = garder les proportions (sauf un cadre : Maj y coupe l'aimantation ; son ratio verrouille reste).
        shift_ratio = bool(modifiers & Qt.ShiftModifier) and self.kind != "frame"
        if handle in ("tl", "tr", "bl", "br") and (self.KEEP_RATIO or shift_ratio):
            ratio = start.width() / max(1.0, start.height())
            w, h = right - left, bottom - top
            if w / ratio > h:
                h = w / ratio
            else:
                w = h * ratio
            if "l" in handle:
                left = right - w
            else:
                right = left + w
            if "t" in handle:
                top = bottom - h
            else:
                bottom = top + h
        rect = QRectF(QPointF(left, top), QPointF(right, bottom))
        scene = self.scene()
        keep = handle in ("tl", "tr", "bl", "br") and (self.KEEP_RATIO or shift_ratio)
        if self._snap_off_key(modifiers):
            if scene is not None:
                scene.clear_guides()
        elif scene is not None and hasattr(scene, "snap_resize") and self.rotation() == 0:
            ratio = start.width() / max(1e-9, start.height()) if keep else None
            rect = scene.snap_resize(self, rect, transform, handle, modifiers, ratio=ratio)
        self.set_local_rect(rect, transform)

    def mouseReleaseEvent(self, event):
        if self._gesture is not None:
            kind = self._gesture[0]
            self._gesture = None
            scene = self.scene()
            if scene is not None:
                scene.clear_guides()
                scene._snap_cache = None
                scene.end_change("Rotation" if kind == "rotate" else "Redimensionner")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_local_rect(self, rect: QRectF, transform: QTransform):
        """Nouvelle taille : `rect` en coordonnees de l'element au debut du geste (`transform`) ; la rotation est
        gardee autour du nouveau centre."""
        target_center = transform.map(rect.center())
        self.prepareGeometryChange()
        if self.KEEP_RATIO:                                 # proportions verrouillees : pas d'arrondi (ratio exact)
            w, h = rect.width(), rect.height()
        else:
            w, h = round(rect.width(), 2), round(rect.height(), 2)
        self.data["w"], self.data["h"] = w, h
        self.sync()
        w, h = self.size()                                  # un texte recale sa hauteur sur son contenu
        self.setTransformOriginPoint(w / 2, h / 2)
        self.setPos(target_center - QPointF(w / 2, h / 2))
        scene = self.scene()
        if scene is not None and hasattr(scene, "item_moved"):
            scene.item_moved(self)

    def set_rect(self, rect: QRectF):
        """Place et taille en coordonnees de scene (element sans rotation)."""
        self.prepareGeometryChange()
        self.data["w"], self.data["h"] = round(rect.width(), 2), round(rect.height(), 2)
        self.sync()
        self.setTransformOriginPoint(rect.width() / 2, rect.height() / 2)
        self.setPos(rect.topLeft())
        scene = self.scene()
        if scene is not None and hasattr(scene, "item_moved"):
            scene.item_moved(self)

    # -- texte sur place --
    def mouseDoubleClickEvent(self, event):
        if self.text_item is not None and event.button() == Qt.LeftButton and not self.locked():
            self.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def start_edit(self):
        if self.text_item is None or self.text_item.editing() or self.locked():
            return
        scene = self.scene()
        if scene is not None:
            scene.clearSelection()
            self.setSelected(True)
            self._edit_before = scene.snapshot([self.item_id])
        self.text_item.start()

    def finish_edit(self):
        if self.text_item is None:
            return
        self.text_item.stop()
        self.data[self.TEXT_KEY] = self.text_item.toPlainText()
        scene = self.scene()
        before, self._edit_before = self._edit_before, None
        if scene is not None and before is not None:
            scene.push(before, scene.snapshot([self.item_id]), "Modifier le texte")

    def layout_text(self):
        pass

    def text_changed(self):
        """Texte modifie (frappe) : mise en place refaite, connecteurs recales."""
        if self._laying:
            return
        self._laying = True
        try:
            self.layout_text()
        finally:
            self._laying = False
        self.update()
        scene = self.scene()
        if scene is not None and hasattr(scene, "item_moved"):
            scene.item_moved(self)

    def _style_text(self, size: float, color: str, width: float):
        """Police, couleur, alignement et surlignage du texte (tout le texte, comme les objets de Miro)."""
        item = self.text_item
        option = QTextOption(ALIGN.get(self.data.get("align", "center"), Qt.AlignHCenter))
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        document = item.document()
        document.setDefaultTextOption(option)
        item.setDefaultTextColor(QColor(color))
        item.setFont(text_font(self.data, size))
        item.setTextWidth(max(10.0, width))
        highlight = self.data.get("text_bg") or ""
        key = (highlight, item.toPlainText())
        if getattr(self, "_highlight_key", None) != key:
            self._highlight_key = key
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(highlight) if highlight else QBrush(Qt.NoBrush))
            cursor = QTextCursor(document)
            cursor.select(QTextCursor.Document)
            was = self._laying
            self._laying = True
            try:
                cursor.mergeCharFormat(fmt)
            finally:
                self._laying = was

    def _place_text_block(self, pad: float):
        """Bloc de texte cale en haut / au milieu / en bas de l'element."""
        item = self.text_item
        _w, h = self.size()
        height = item.document().size().height()
        valign = self.data.get("valign", "middle")
        if valign == "top":
            y = pad
        elif valign == "bottom":
            y = h - pad - height
        else:
            y = (h - height) / 2
        item.setPos(pad, max(pad * 0.5, y))

    def _fit_text(self, fixed_size: float, color: str, auto: bool):
        """Texte dans l'element ; `auto` = la plus grande taille qui tient (64 au plus), sinon la taille
        demandee, reduite seulement si le texte deborderait."""
        w, h = self.size()
        width = w - 2 * TEXT_PAD
        limit = max(10.0, h - 2 * TEXT_PAD)
        size = 64.0 if auto else float(fixed_size)
        self._style_text(size, color, width)
        item = self.text_item
        while size > 6 and item.document().size().height() > limit:
            size = max(6.0, size * 0.88)
            item.setFont(text_font(self.data, size))
        self._place_text_block(TEXT_PAD)


_SHADOW_TEMPLATE: QImage | None = None
SHADOW_BASE = 256.0
SHADOW_BOX = (-0.06, -0.02, 1.06, 1.14)     # zone de l'image d'ombre, en fractions du post-it (g, h, d, b)
# Valeurs AJUSTEES sur la capture 2 (profil de l'ombre sous / a droite du post-it de 318 x 330 px, recherche par
# moindres carres, octobre 2026, avec RIEN au-dessus) : noir a 32/255 flou de 6 % du cote, trapeze partant a
# 6 % sous le haut du post-it (retrait 2 %) jusqu'a 2 % sous son bord bas, debordant de 0,8 % sur les cotes.
# Ecart restant avec la capture : 0 a 3 niveaux de gris (6 au bord droit, ou la capture a aussi l'anticrenelage).
SHADOW_ALPHA = 32
SHADOW_BLUR = 0.06
SHADOW_SHAPE = (0.06, 0.02, 0.02, 0.008)    # haut du trapeze, retrait en haut, debord en bas, debord des cotes


def _sticky_shadow() -> QImage:
    """Ombre douce d'un post-it de reference (256 x 256), floutee UNE fois, posee ensuite etiree a la taille de
    chaque post-it. Forme calee sur la capture 2 de l'utilisateur (post-it de 318 x 330 px) : rien au-dessus,
    presque rien en haut des cotes, de plus en plus large vers le bas (bord releve), ~7 % de la hauteur sous le
    post-it ; noir ~9 % juste sous le bord."""
    global _SHADOW_TEMPLATE
    if _SHADOW_TEMPLATE is not None:
        return _SHADOW_TEMPLATE
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPolygonItem, QGraphicsScene
    left, top, right, bottom = SHADOW_BOX
    s = SHADOW_BASE
    width, height = int((right - left) * s), int((bottom - top) * s)
    scene = QGraphicsScene(0, 0, width, height)
    ox, oy = -left * s, -top * s
    top_y, inset, below, side = SHADOW_SHAPE
    polygon = QPolygonF([QPointF(ox + inset * s, oy + top_y * s), QPointF(ox + (1 - inset) * s, oy + top_y * s),
                         QPointF(ox + (1 + side) * s, oy + (1 + below) * s),
                         QPointF(ox - side * s, oy + (1 + below) * s)])
    item = QGraphicsPolygonItem(polygon)
    item.setPen(Qt.NoPen)
    item.setBrush(QColor(0, 0, 0, SHADOW_ALPHA))
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(SHADOW_BLUR * s)
    blur.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(blur)
    scene.addItem(item)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    scene.render(painter, QRectF(0, 0, width, height), QRectF(0, 0, width, height))
    painter.end()
    _SHADOW_TEMPLATE = image
    return image


class StickyItem(BoardItem):
    TEXT_KEY = "text"

    def layout_text(self):
        if self.text_item is not None:
            size = float(self.data.get("font_size", 0) or 0)
            self._fit_text(size or 20.0, self.data.get("text_color", model.MIRO_INK), auto=size <= 0)

    def paint_margin(self) -> QRectF:
        w, h = self.size()
        left, top, right, bottom = SHADOW_BOX
        return QRectF(left * w, top * h, (right - left) * w, (bottom - top) * h)

    def paint_content(self, painter):
        rect = self.content_rect()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(self.paint_margin(), _sticky_shadow())
        base = QColor(self.data.get("color", model.MIRO_STICKY))
        # Degrade vertical leger (capture 2 : #fae57c en haut, #fde884 au milieu, #fdea8f en bas).
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top_color = QColor.fromRgbF(base.redF() * 0.988, base.greenF() * 0.98, base.blueF() * 0.94)
        bottom = QColor.fromRgbF(base.redF(), min(1.0, base.greenF() + 0.008), min(1.0, base.blueF() * 1.07 + 0.01))
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(0.5, base)
        gradient.setColorAt(1.0, bottom)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(rect)


class TextItem(BoardItem):
    """Texte libre : largeur reglee, hauteur = celle du texte."""

    TEXT_KEY = "text"

    def layout_text(self):
        item = self.text_item
        if item is None:
            return
        width = max(20.0, float(self.data.get("w", 280.0)))
        self._style_text(float(self.data.get("font_size", 24)), self.data.get("text_color", model.MIRO_INK), width)
        item.setPos(0, 0)
        height = max(float(self.data.get("font_size", 24)) * 1.4, item.document().size().height())
        if abs(height - float(self.data.get("h", 0.0))) > 0.5:
            self.prepareGeometryChange()
            self.data["h"] = round(height, 2)

    def paint_content(self, painter):
        if not self.text_item.toPlainText() and not self.text_item.editing():
            painter.setPen(QPen(QColor(0, 0, 0, 70), 1 / self._zoom(), Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.content_rect())


def _poly(*points) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    path.closeSubpath()
    return path


def max_radius(w: float, h: float) -> float:
    return max(0.0, min(w, h) / 2.0)


def shape_path(kind: str, rect: QRectF, radius: float = 0.0) -> QPainterPath:
    """Contour d'une forme dans `rect` ; `radius` = arrondi des angles (formes de `model.RADIUS_SHAPES`)."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    r = max(0.0, min(float(radius), max_radius(w, h)))
    path = QPainterPath()
    if kind == "ellipse":
        path.addEllipse(rect)
    elif kind in ("rect", "round"):
        if r > 0:
            path.addRoundedRect(rect, r, r)
        else:
            path.addRect(rect)
    elif kind == "triangle":
        path = _poly((x + w / 2, y), (x + w, y + h), (x, y + h))
    elif kind == "diamond":
        path = _poly((x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2))
    elif kind == "parallelogram":
        d = w * 0.2
        path = _poly((x + d, y), (x + w, y), (x + w - d, y + h), (x, y + h))
    elif kind == "trapezoid":
        d = w * 0.2
        path = _poly((x + d, y), (x + w - d, y), (x + w, y + h), (x, y + h))
    elif kind in ("pentagon", "hexagon", "octagon"):
        n = {"pentagon": 5, "hexagon": 6, "octagon": 8}[kind]
        start = -90.0 if kind == "pentagon" else (0.0 if kind == "hexagon" else 22.5)
        path = _poly(*[(x + w / 2 + w / 2 * math.cos(math.radians(start + i * 360 / n)),
                        y + h / 2 + h / 2 * math.sin(math.radians(start + i * 360 / n))) for i in range(n)])
    elif kind == "star":
        pts = []
        for i in range(10):
            radius_f = 0.5 if i % 2 == 0 else 0.2
            angle = math.radians(-90 + i * 36)
            pts.append((x + w / 2 + w * radius_f * math.cos(angle), y + h / 2 + h * radius_f * math.sin(angle)
                        + h * 0.05))
        path = _poly(*pts)
    elif kind == "cross":
        a, b = 0.33, 0.67
        path = _poly((x + a * w, y), (x + b * w, y), (x + b * w, y + a * h), (x + w, y + a * h), (x + w, y + b * h),
                     (x + b * w, y + b * h), (x + b * w, y + h), (x + a * w, y + h), (x + a * w, y + b * h),
                     (x, y + b * h), (x, y + a * h), (x + a * w, y + a * h))
    elif kind == "right_arrow":
        head = min(w * 0.4, h)
        path = _poly((x, y + h * 0.25), (x + w - head, y + h * 0.25), (x + w - head, y), (x + w, y + h / 2),
                     (x + w - head, y + h), (x + w - head, y + h * 0.75), (x, y + h * 0.75))
    elif kind == "left_arrow":
        head = min(w * 0.4, h)
        path = _poly((x + w, y + h * 0.25), (x + head, y + h * 0.25), (x + head, y), (x, y + h / 2),
                     (x + head, y + h), (x + head, y + h * 0.75), (x + w, y + h * 0.75))
    elif kind == "left_right_arrow":
        head = min(w * 0.3, h)
        path = _poly((x, y + h / 2), (x + head, y), (x + head, y + h * 0.25), (x + w - head, y + h * 0.25),
                     (x + w - head, y), (x + w, y + h / 2), (x + w - head, y + h), (x + w - head, y + h * 0.75),
                     (x + head, y + h * 0.75), (x + head, y + h))
    elif kind == "callout":
        body = QRectF(x, y, w, h * 0.78)
        rr = min(r, body.height() / 2, body.width() / 2)
        if rr > 0:
            path.addRoundedRect(body, rr, rr)
        else:
            path.addRect(body)
        path = path.united(_poly((x + w * 0.18, y + h * 0.7), (x + w * 0.38, y + h * 0.7), (x + w * 0.12, y + h)))
    elif kind == "cloud":
        path.setFillRule(Qt.WindingFill)
        for cx, cy, rx, ry in ((0.3, 0.55, 0.22, 0.25), (0.5, 0.38, 0.25, 0.3), (0.72, 0.52, 0.22, 0.26),
                               (0.5, 0.68, 0.32, 0.22), (0.2, 0.68, 0.16, 0.18), (0.82, 0.68, 0.16, 0.18)):
            path.addEllipse(QPointF(x + cx * w, y + cy * h), rx * w, ry * h)
        path = path.simplified()
    elif kind == "can":
        e = min(h * 0.18, w * 0.3)
        path.moveTo(x, y + e / 2)
        path.arcTo(QRectF(x, y, w, e), 180, -180)
        path.lineTo(x + w, y + h - e / 2)
        path.arcTo(QRectF(x, y + h - e, w, e), 0, -180)
        path.closeSubpath()
        path.moveTo(x, y + e / 2)
        path.arcTo(QRectF(x, y, w, e), 180, 180)
    elif kind == "predefined_process":
        if r > 0:
            path.addRoundedRect(rect, r, r)
        else:
            path.addRect(rect)
        d = w * 0.1
        path.moveTo(x + d, y)
        path.lineTo(x + d, y + h)
        path.moveTo(x + w - d, y)
        path.lineTo(x + w - d, y + h)
    elif kind in ("left_brace", "right_brace"):
        sign = 1 if kind == "left_brace" else -1
        x0 = x + w if kind == "left_brace" else x
        xm = x0 - sign * w * 0.5
        xt = x0 - sign * w
        path.moveTo(x0, y)
        path.quadTo(xm, y, xm, y + h * 0.2)
        path.lineTo(xm, y + h * 0.4)
        path.quadTo(xm, y + h / 2, xt, y + h / 2)
        path.quadTo(xm, y + h / 2, xm, y + h * 0.6)
        path.lineTo(xm, y + h * 0.8)
        path.quadTo(xm, y + h, x0, y + h)
    else:
        path.addRect(rect)
    return path


OPEN_SHAPES = ("left_brace", "right_brace")


class ShapeItem(BoardItem):
    TEXT_KEY = "text"

    def layout_text(self):
        if self.text_item is not None:
            self._fit_text(float(self.data.get("font_size", 14)), self.data.get("text_color", model.MIRO_INK), False)

    def outline(self) -> QPainterPath:
        """Contour, garde tant que forme / taille / arrondi / epaisseur ne changent pas (peinture fluide)."""
        rect = self.content_rect()
        stroke_width = float(self.data.get("stroke_width", 2.0))
        key = (self.data.get("shape", "rect"), rect.width(), rect.height(), float(self.data.get("radius", 0.0)),
               stroke_width)
        cached = getattr(self, "_outline", None)
        if cached is None or cached[0] != key:
            inner = rect.adjusted(stroke_width / 2, stroke_width / 2, -stroke_width / 2, -stroke_width / 2)
            cached = self._outline = (key, shape_path(key[0], inner, key[3]))
        return cached[1]

    def paint_content(self, painter):
        kind = self.data.get("shape", "rect")
        path = self.outline()
        fill = QColor(self.data.get("fill", "#ffffff"))
        fill.setAlphaF(max(0.0, min(1.0, float(self.data.get("fill_opacity", 0.0)))))
        stroke_width = float(self.data.get("stroke_width", 2.0))
        painter.setBrush(Qt.NoBrush if kind in OPEN_SHAPES else fill)
        if stroke_width > 0:
            color = QColor(self.data.get("stroke", model.MIRO_INK))
            color.setAlphaF(max(0.0, min(1.0, float(self.data.get("stroke_opacity", 1.0)))))
            pen = QPen(color, stroke_width, pen_style(self.data.get("stroke_style", "solid")))
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.NoPen)
        painter.drawPath(path)


class FrameItem(BoardItem):
    """Cadre titre : toujours SOUS les autres elements ; le deplacer emporte ce qu'il contient."""

    TEXT_KEY = "title"
    TITLE_GAP = 8.0
    CONNECTABLE = False

    @property
    def KEEP_RATIO(self):
        """Proportions verrouillees (format choisi + verrou) : coins seulement, ratio garde."""
        return bool(self.data.get("ratio_locked")) and model.frame_ratio(self.data) is not None

    def __init__(self, data: dict):
        self._carry: list[QGraphicsItem] = []
        self._last = None
        super().__init__(data)

    def layout_text(self):
        item = self.text_item
        if item is None:
            return
        size = 14.0 / self._zoom()                      # titre de taille constante a l'ecran
        item.setFont(_plain_font(size))
        item.setDefaultTextColor(QColor("#5f5f5f"))
        option = QTextOption(Qt.AlignLeft)
        item.document().setDefaultTextOption(option)
        item.setTextWidth(-1)
        item.setPos(0, -item.boundingRect().height() - self.TITLE_GAP / self._zoom())

    def zoom_changed(self):
        super().zoom_changed()
        self.layout_text()

    def boundingRect(self) -> QRectF:
        rect = super().boundingRect()
        title = self.text_item.mapRectToParent(self.text_item.boundingRect()) if self.text_item else QRectF()
        return rect.united(title)

    def shape(self) -> QPainterPath:
        path = super().shape()
        if self.text_item is not None:
            path.addRect(self.text_item.mapRectToParent(self.text_item.boundingRect()))
        return path

    def contains_item(self, other: "BoardItem") -> bool:
        return self.scene_rect().contains(other.scene_rect())

    def paint_content(self, painter):
        rect = self.content_rect()
        fill = QColor(self.data.get("fill", "#ffffff"))
        fill.setAlphaF(max(0.0, min(1.0, float(self.data.get("fill_opacity", 1.0)))))
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1.0 / self._zoom()))
        painter.drawRect(rect)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._carry = []
        self._last = QPointF(self.pos())
        scene = self.scene()
        if self._gesture is None and scene is not None and event.button() == Qt.LeftButton:
            self._carry = [item for item in scene.board_items()
                           if item is not self and not item.isSelected() and not item.locked()
                           and item.kind not in ("frame", "connector", "comment") and self.contains_item(item)]

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._carry = []

    def carried(self) -> list:
        return list(self._carry)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemPositionHasChanged and self._carry and self._last is not None:
            delta = self.pos() - self._last
            for item in self._carry:
                item.moveBy(delta.x(), delta.y())
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._last = QPointF(self.pos())
        return result


_PIXMAPS: "OrderedDict[tuple, QPixmap | None]" = OrderedDict()
_PIXMAP_LIMIT = 64


def asset_pixmap(board_path, name: str) -> QPixmap | None:
    """Image d'un asset, decodee une fois (partagee par les copies d'une meme image) : les peintures suivantes
    ne lisent plus le disque."""
    key = (str(board_path), name)
    if key in _PIXMAPS:
        _PIXMAPS.move_to_end(key)
        return _PIXMAPS[key]
    from .serialization import asset_path, is_asset_name
    pixmap = None
    if is_asset_name(name):
        reader = QImageReader(str(asset_path(board_path, name)))
        reader.setAutoTransform(True)
        natural = reader.size()
        if natural.isValid() and max(natural.width(), natural.height()) > IMAGE_MAX_SIDE:
            natural.scale(IMAGE_MAX_SIDE, IMAGE_MAX_SIDE, Qt.KeepAspectRatio)
            reader.setScaledSize(natural)
        image = reader.read()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
    _PIXMAPS[key] = pixmap
    while len(_PIXMAPS) > _PIXMAP_LIMIT:
        _PIXMAPS.popitem(last=False)
    return pixmap


class ImageItem(BoardItem):
    KEEP_RATIO = True

    def paint_content(self, painter):
        scene = self.scene()
        board_path = getattr(scene, "board_path", None)
        pixmap = asset_pixmap(board_path, self.data.get("asset", "")) if board_path is not None else None
        rect = self.content_rect()
        if pixmap is None:
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1 / self._zoom(), Qt.DashLine))
            painter.setBrush(QColor(0, 0, 0, 12))
            painter.drawRect(rect)
            painter.setFont(_plain_font(13 / self._zoom()))
            painter.drawText(rect, Qt.AlignCenter, "image introuvable")
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))


def ink_path(points) -> QPainterPath:
    """Trait lisse (milieux relies par des courbes) a partir des points enregistres."""
    path = QPainterPath()
    pts = [QPointF(float(x), float(y)) for x, y in points]
    if not pts:
        return path
    path.moveTo(pts[0])
    if len(pts) == 1:
        path.lineTo(pts[0] + QPointF(0.01, 0.01))
        return path
    for i in range(1, len(pts) - 1):
        mid = (pts[i] + pts[i + 1]) / 2
        path.quadTo(pts[i], mid)
    path.lineTo(pts[-1])
    return path


def ink_pen(data: dict) -> QPen:
    color = QColor(data.get("color", model.MIRO_INK))
    if data.get("tool") == "highlighter":
        color.setAlphaF(max(0.05, min(1.0, float(data.get("opacity", 0.45)))))
    pen = QPen(color, float(data.get("width", 2.0)))
    pen.setCapStyle(Qt.FlatCap if data.get("tool") == "highlighter" else Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


class InkItem(BoardItem):
    """Trait a main levee (stylo, surligneur). Points relatifs a la place de l'element."""

    RESIZABLE = False
    CONNECTABLE = False
    _path = QPainterPath()

    def sync(self):
        self.prepareGeometryChange()
        self._path = ink_path(self.data.get("points") or [])

    def content_rect(self) -> QRectF:
        width = float(self.data.get("width", 2.0))
        return self._path.boundingRect().adjusted(-width / 2, -width / 2, width / 2, width / 2)

    def boundingRect(self) -> QRectF:
        m = 3 / self._zoom()
        return self.content_rect().adjusted(-m, -m, m, m)

    def ink_shape(self, tolerance_px: float = 10.0) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(float(self.data.get("width", 2.0)) + tolerance_px / self._zoom())
        stroker.setCapStyle(Qt.RoundCap)
        return stroker.createStroke(self._path)

    def shape(self) -> QPainterPath:
        return self.ink_shape()

    def paint_content(self, painter):
        if self.data.get("tool") == "highlighter":
            painter.setCompositionMode(QPainter.CompositionMode_Multiply)   # le dessous reste lisible
        painter.setPen(ink_pen(self.data))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._path)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def paint_selection(self, painter):
        if self.isSelected():
            painter.setPen(QPen(self._accent(), 1.2 / self._zoom(), Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.content_rect())


class ConnectorItem(BoardItem):
    """Fleche entre deux elements (ou points libres) ; suit les elements quand ils bougent. Accroche = milieu du
    cote le plus proche de l'autre extremite."""

    RESIZABLE = False
    CONNECTABLE = False

    def __init__(self, data: dict):
        self._line = QLineF()
        self._path = QPainterPath()
        super().__init__(data)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    def _place_from_data(self):
        self.setPos(0, 0)
        self.setZValue(float(self.data.get("z", 0.0)))
        self.sync()

    def to_dict(self) -> dict:
        data = copy.deepcopy(self.data)
        data["x"] = data["y"] = 0.0
        data["z"] = self.zValue()
        start, end = self.caps()
        data["start_cap"], data["end_cap"] = start, end
        data["arrow_start"], data["arrow_end"] = start != "none", end != "none"   # lecture par les anciennes versions
        return data

    def attached_ids(self) -> set:
        return {end.get("item") for end in (self.data.get("src") or {}, self.data.get("dst") or {})
                if end.get("item")}

    # -- extremites : saisir, deplacer librement, rattacher a un objet (demande de l'utilisateur) --
    END_PX = 9.0             # rayon de saisie d'une extremite, en pixels d'ecran

    def end_at(self, scene_pos: QPointF) -> str | None:
        """« src » / « dst » si `scene_pos` est sur une extremite (a END_PX pixels d'ecran pres)."""
        reach = self.END_PX / self._zoom()
        d_src = QLineF(scene_pos, self._line.p1()).length()
        d_dst = QLineF(scene_pos, self._line.p2()).length()
        if min(d_src, d_dst) > reach:
            return None
        return "src" if d_src <= d_dst else "dst"

    def hoverMoveEvent(self, event):
        if self.end_at(event.scenePos()) is not None:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()
        QGraphicsObject.hoverMoveEvent(self, event)

    def mousePressEvent(self, event):
        end = self.end_at(event.scenePos()) if event.button() == Qt.LeftButton else None
        scene = self.scene()
        if end is None or scene is None or self.locked():
            super().mousePressEvent(event)
            return
        if not self.isSelected():
            scene.clearSelection()
            self.setSelected(True)
        scene.begin_change([self])
        self._gesture = ("end", end)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._gesture is None or self._gesture[0] != "end":
            super().mouseMoveEvent(event)
            return
        end = self._gesture[1]
        scene = self.scene()
        other = (self.data.get("dst" if end == "src" else "src") or {}).get("item")
        target = scene.connect_target(event.scenePos(), exclude={self.item_id, other}) if scene else None
        from PySide6.QtWidgets import QApplication
        free = (event.modifiers() | QApplication.keyboardModifiers()) & Qt.AltModifier   # Alt = laisser libre
        if target is not None and not free:
            self.data[end] = {"item": target.item_id}      # rattachee : suit l'objet
            scene.set_highlight(target.scene_rect())
        else:
            point = event.scenePos()
            self.data[end] = {"x": round(point.x(), 2), "y": round(point.y(), 2)}
            if scene is not None:
                scene.set_highlight(None)
        self.sync()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._gesture is not None and self._gesture[0] == "end":
            self._gesture = None
            scene = self.scene()
            if scene is not None:
                scene.set_highlight(None)
                scene.end_change("Déplacer l'extrémité")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _end_point(self, end: dict, toward: QPointF | None) -> QPointF:
        scene = self.scene()
        target = scene.item(end.get("item")) if scene is not None and end.get("item") else None
        if target is not None:
            anchors = target.anchor_points()
            if toward is None:
                return target.scene_rect().center()
            return min(anchors, key=lambda p: QLineF(p, toward).length())
        return QPointF(float(end.get("x", 0.0)), float(end.get("y", 0.0)))

    def sync(self):
        self.prepareGeometryChange()
        src, dst = self.data.get("src") or {}, self.data.get("dst") or {}
        a0 = self._end_point(src, None)
        b0 = self._end_point(dst, None)
        a = self._end_point(src, b0)
        b = self._end_point(dst, a0)
        self._line = QLineF(a, b)
        path = QPainterPath(a)
        style = self.data.get("style")
        if style == "elbow":
            mid = (a.x() + b.x()) / 2
            path.lineTo(mid, a.y())
            path.lineTo(mid, b.y())
            path.lineTo(b)
        elif style == "curved":
            dx = (b.x() - a.x()) / 2
            path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        else:
            path.lineTo(b)
        self._path = path

    def content_rect(self) -> QRectF:
        return self._path.boundingRect()

    # -- pointes (formes et taille ; taille commune aux deux extremites, distincte de l'epaisseur) --
    def caps(self) -> tuple[str, str]:
        return (cap_kind(self.data, "start"), cap_kind(self.data, "end"))

    def _geometry(self):
        """(trait raccourci, [(contour de pointe, pleine)], polygone du trait) — garde tant que le trace et les
        pointes ne changent pas."""
        key = (self._path, self.caps(), float(self.data.get("cap_size", 12.0)), self.data.get("style"))
        cached = getattr(self, "_geom", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        points = path_points(self._path, self.data.get("style") == "curved")
        length = polyline_length(points)
        start_kind, end_kind = self.caps()
        count = (start_kind != "none") + (end_kind != "none")
        size = min(float(self.data.get("cap_size", 12.0)), length * 0.45 / max(1, count)) if length > 0 else 0.0
        heads, trim_start, trim_end = [], 0.0, 0.0
        if len(points) >= 2 and size > 0.5:
            for kind, tip, toward in ((start_kind, points[0], points[1]), (end_kind, points[-1], points[-2])):
                if kind == "none":
                    continue
                outline, back, filled = cap_shape(kind, tip, toward, size)
                heads.append((outline, filled))
                if tip is points[0]:
                    trim_start = back
                else:
                    trim_end = back
        line = trim_polyline(points, trim_start, trim_end)
        result = (line, heads, points)
        self._geom = (key, result)
        return result

    def boundingRect(self) -> QRectF:
        m = ((14 + self.END_PX) / self._zoom() + float(self.data.get("width", 2.0))
             + float(self.data.get("cap_size", 12.0)))
        return self.content_rect().adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(float(self.data.get("width", 2.0)) + 10 / self._zoom())
        area = stroker.createStroke(self._path)
        for outline, _filled in self._geometry()[1]:
            area.addPath(outline)                          # la pointe se clique aussi
        reach = self.END_PX / self._zoom()
        for point in (self._line.p1(), self._line.p2()):  # extremites faciles a saisir
            area.addEllipse(point, reach, reach)
        return area

    def paint(self, painter, option, widget=None):
        option.state = option.state & ~QStyle.State_Selected
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = self._accent() if self.isSelected() else QColor(self.data.get("color", model.MIRO_INK))
        width = float(self.data.get("width", 2.0))
        line, heads, _points = self._geometry()
        pen = QPen(color, width, pen_style(self.data.get("stroke_style", "solid")))
        pen.setCapStyle(Qt.FlatCap if heads else Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF(line))
        solid = QPen(color, width)
        solid.setJoinStyle(Qt.MiterJoin)
        solid.setCapStyle(Qt.RoundCap)
        background = getattr(self.scene(), "background", QColor(model.MIRO_BACKGROUND))
        for outline, filled in heads:
            painter.setPen(solid)
            # pleine : couleur du trait ; vide : fond de la page (le trait ne se voit pas dedans) ; ouverte : rien
            painter.setBrush(color if filled is True else (QColor(background) if filled is False else Qt.NoBrush))
            painter.drawPath(outline)
        if self.isSelected():
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(self._accent(), 1.6 / self._zoom()))
            r = 5.5 / self._zoom()
            for point in (self._line.p1(), self._line.p2()):
                painter.drawEllipse(point, r, r)


CAP_KINDS = ("none", "open", "filled", "circle", "circle_open", "diamond", "diamond_open")
CAP_LABELS = {"none": "Aucune", "open": "Flèche ouverte", "filled": "Flèche pleine", "circle": "Cercle",
              "circle_open": "Cercle vide", "diamond": "Losange", "diamond_open": "Losange vide"}


def cap_kind(data: dict, end: str) -> str:
    """Pointe d'une extremite ; anciennes fleches (sans `start_cap` / `end_cap`) : `arrow_start` /
    `arrow_end` -> fleche pleine (leur dessin d'avant)."""
    kind = data.get(f"{end}_cap")
    if kind in CAP_KINDS:
        return kind
    legacy = data.get("arrow_start", False) if end == "start" else data.get("arrow_end", True)
    return "filled" if legacy else "none"


def cap_shape(kind: str, tip: QPointF, toward: QPointF, size: float):
    """(contour, recul du trait, remplissage : True plein, False vide (fond blanc), None ouvert)."""
    line = QLineF(tip, toward)
    length = max(1e-9, line.length())
    ux, uy = line.dx() / length, line.dy() / length          # de la pointe vers l'interieur du trait
    px, py = -uy, ux

    def at(along, side):
        return QPointF(tip.x() + ux * along + px * side, tip.y() + uy * along + py * side)
    path = QPainterPath()
    if kind in ("open", "filled"):
        spread = size * math.tan(0.45)
        left, right = at(size, spread), at(size, -spread)
        if kind == "open":
            path.moveTo(left)
            path.lineTo(tip)
            path.lineTo(right)
            return path, 0.0, None
        path.addPolygon(QPolygonF([tip, left, right]))
        path.closeSubpath()
        return path, size * 0.9, True
    if kind in ("circle", "circle_open"):
        r = size * 0.38
        path.addEllipse(at(r, 0), r, r)
        path.setFillRule(Qt.WindingFill)
        return path, 2 * r, kind == "circle" or False
    half = size * 0.32
    path.addPolygon(QPolygonF([tip, at(size / 2, half), at(size, 0), at(size / 2, -half)]))
    path.closeSubpath()
    path.setFillRule(Qt.WindingFill)
    return path, size, kind == "diamond" or False


def path_points(path: QPainterPath, curved: bool) -> list[QPointF]:
    """Points du trace : sommets (droit, coude), ou 48 points d'une courbe."""
    if curved:
        return [path.pointAtPercent(n / 48) for n in range(49)]
    return [QPointF(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())]


def polyline_length(points) -> float:
    return sum(QLineF(a, b).length() for a, b in zip(points, points[1:]))


def trim_polyline(points, start: float, end: float) -> list[QPointF]:
    """Trait raccourci de `start` au debut et `end` a la fin (sous les pointes pleines)."""
    if len(points) < 2:
        return list(points)

    def cut_front(pts, amount):
        out = list(pts)
        while amount > 0 and len(out) >= 2:
            seg = QLineF(out[0], out[1])
            if seg.length() > amount:
                t = amount / seg.length()
                out[0] = QPointF(out[0].x() + seg.dx() * t, out[0].y() + seg.dy() * t)
                return out
            amount -= seg.length()
            out.pop(0)
        return out
    trimmed = cut_front(points, start)
    trimmed = list(reversed(cut_front(list(reversed(trimmed)), end)))
    return trimmed if len(trimmed) >= 2 else [points[0], points[0]]


class CommentItem(BoardItem):
    """Commentaire local : bulle de taille constante a l'ecran (le zoom ne la change pas), nombre de messages ;
    accroche a un element, elle le suit (dans Miro, un commentaire accroche reste sur place quand l'objet bouge
    — choix plus utile ici). Resolu : cache, sauf « Afficher les commentaires resolus »."""

    RESIZABLE = False
    CONNECTABLE = False
    SIZE = 28.0

    def __init__(self, data: dict):
        super().__init__(data)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCacheMode(QGraphicsItem.NoCache)

    def size(self):
        return self.SIZE, self.SIZE

    def content_rect(self) -> QRectF:
        return QRectF(0, -self.SIZE, self.SIZE, self.SIZE)    # la pointe de la bulle est sur sa place

    def scene_rect(self) -> QRectF:
        scene = self.scene()
        z = max(0.05, float(getattr(scene, "zoom", 1.0))) if scene is not None else 1.0
        return QRectF(self.pos().x(), self.pos().y() - self.SIZE / z, self.SIZE / z, self.SIZE / z)

    def _zoom(self) -> float:
        return 1.0                                           # ignore les transformations : pixels d'ecran

    def boundingRect(self) -> QRectF:
        return self.content_rect().adjusted(-3, -3, 3, 3)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.content_rect())
        return path

    def _handles_shown(self) -> bool:
        return False

    def _apply_rotation(self):
        pass

    def follow_target(self):
        scene = self.scene()
        target = scene.item(self.data.get("target")) if scene is not None and self.data.get("target") else None
        if target is not None:
            r = target.scene_rect()
            self.setPos(r.left() + float(self.data.get("dx", 0.0)), r.top() + float(self.data.get("dy", 0.0)))

    def to_dict(self) -> dict:
        data = super().to_dict()
        scene = self.scene()
        target = scene.item(self.data.get("target")) if scene is not None and self.data.get("target") else None
        if target is not None:
            r = target.scene_rect()
            data["dx"], data["dy"] = round(self.pos().x() - r.left(), 2), round(self.pos().y() - r.top(), 2)
        return data

    def sync(self):
        scene = self.scene()
        show = (not self.data.get("resolved")) or bool(getattr(scene, "show_resolved", False))
        self.setVisible(show)

    def paint(self, painter, option, widget=None):
        option.state = option.state & ~QStyle.State_Selected
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.content_rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + rect.height() / 2)
        path.arcTo(QRectF(rect.left(), rect.top(), rect.width(), rect.height()), 180, -270)
        path.closeSubpath()
        resolved = bool(self.data.get("resolved"))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(QColor("#9a9a9a") if resolved else (self._accent() if self.isSelected()
                                                            else QColor("#fac710")))
        painter.drawPath(path)
        count = len(self.data.get("messages") or [])
        painter.setPen(QColor("#1a1a1a") if not resolved else QColor("#ffffff"))
        painter.setFont(_plain_font(12, True))
        painter.drawText(rect, Qt.AlignCenter, "✓" if resolved else (str(count) if count else "+"))


ITEM_CLASSES = {"sticky": StickyItem, "text": TextItem, "shape": ShapeItem, "image": ImageItem, "ink": InkItem,
                "frame": FrameItem, "connector": ConnectorItem, "comment": CommentItem}


def make_item(data: dict) -> BoardItem:
    return ITEM_CLASSES[data["type"]](data)
