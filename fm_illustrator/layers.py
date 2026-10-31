"""Calques du module Illustrator : éléments `ill_layer` du `.mro` (nom, ordre `index`, couleur, masqué, verrouillé),
chaque objet porte `layer` = identifiant de son calque (vide = le calque le plus bas).

Ordre de dessin : chaque calque a sa BANDE de hauteurs (`BAND` × (index + 1)) ; un objet neuf va en haut de la bande
de son calque, la disposition (Ctrl+] …) reste dans la bande, changer l'ordre des calques re-range leurs objets.
Masquer / verrouiller un calque agit sur l'affichage et la sélection de ses objets (pas sur leurs propres valeurs).

Panneau (`LayersPanel`, à droite) : le calque le plus haut en premier ; clic = calque courant ; œil / cadenas =
masquer / verrouiller ; double-clic = renommer ; Ctrl + glisser = changer l'ordre (règle de l'appli) ; carré de
sélection à droite = le calque contient des objets choisis ; clic droit = menu (nouveau, supprimer, déplacer la
sélection ici, choisir les objets du calque)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QInputDialog, QWidget

from fm_board import model as board_model
from . import model

BAND = 100000.0
LAYER_COLORS = ["#2f7cf6", "#e8423b", "#29b34a", "#2d5be3", "#f0a21b", "#21b7c9", "#c739c0", "#7d7d7d"]


# ---------------------------------------------------------------- accès
def layers(scene) -> list:
    """Calques du bas vers le haut."""
    return sorted(getattr(scene, "ill_layers", {}).values(), key=lambda l: float(l.data.get("index", 0)))


def layer_of(scene, item):
    found = getattr(scene, "ill_layers", {}).get(item.data.get("layer") or "")
    if found is not None:
        return found
    ordered = layers(scene)
    return ordered[0] if ordered else None


def band_base(layer) -> float:
    return BAND * (float(layer.data.get("index", 0)) + 1) if layer is not None else 0.0


def members(scene, layer, objects) -> list:
    return [o for o in objects if layer_of(scene, o) is layer]


def top_z(scene, layer, objects) -> float:
    zs = [o.zValue() for o in members(scene, layer, objects)]
    return (max(zs) + 1.0) if zs else band_base(layer) + 1.0


def new_layer_data(scene) -> dict:
    existing = layers(scene)
    index = (max(float(l.data.get("index", 0)) for l in existing) + 1) if existing else 0.0
    return board_model.new_item(model.LAYER, name=f"Calque {len(existing) + 1}", index=index,
                                color=LAYER_COLORS[len(existing) % len(LAYER_COLORS)])


# ---------------------------------------------------------------- panneau
class LayersPanel(QWidget):
    ROW = 28
    reorder = Signal(str, int)              # identifiant, nouvelle position (0 = en haut de la liste)

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.rows: list = []
        self._press = None
        self._drag_to = None
        self.setMouseTracking(True)
        self.setMinimumWidth(220)
        self.sync()

    def sync(self):
        self.rows = list(reversed(layers(self.ctl.scene)))
        self.setFixedHeight(max(self.ROW, len(self.rows) * self.ROW))
        self.update()

    def _row_at(self, y: float) -> int:
        return int(y // self.ROW)

    def paintEvent(self, _event):
        from app_style import C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        current = self.ctl.current_layer()
        selected_layers = {id(layer_of(self.ctl.scene, i)) for i in self.ctl.selection()}
        if not self.rows:
            p.setPen(QColor(C["text"]))
            p.drawText(QRectF(0, 0, self.width(), self.ROW), Qt.AlignCenter, "Aucun calque (créé au 1er objet)")
        for n, layer in enumerate(self.rows):
            r = QRectF(0, n * self.ROW, self.width(), self.ROW - 2)
            if layer is current:
                p.fillRect(r, QColor(C.get("hover", "#3a3f44")))
            hidden = bool(layer.data.get("hidden"))
            locked = bool(layer.data.get("content_locked"))
            ink = QColor(C["text"])
            p.setPen(QPen(ink, 1.3))
            p.setBrush(Qt.NoBrush)
            eye = QRectF(6, r.top() + 7, 16, 12)                 # œil : ouvert / barré
            p.drawEllipse(eye)
            if not hidden:
                p.setBrush(ink)
                p.drawEllipse(eye.center(), 2.5, 2.5)
                p.setBrush(Qt.NoBrush)
            else:
                p.drawLine(eye.bottomLeft(), eye.topRight())
            lock = QRectF(30, r.top() + 10, 11, 9)               # cadenas
            if locked:
                p.drawRect(lock)
                p.drawArc(QRectF(lock.left() + 2, lock.top() - 5, 7, 9), 0, 180 * 16)
            else:
                p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 60), 1.0))
                p.drawRect(lock)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(layer.data.get("color") or model.ACCENT))
            p.drawRect(QRectF(50, r.top() + 6, 4, r.height() - 12))
            p.setPen(ink)
            p.drawText(QRectF(60, r.top(), self.width() - 90, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       str(layer.data.get("name", "")))
            if id(layer) in selected_layers:                     # carré de sélection (couleur du calque)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(layer.data.get("color") or model.ACCENT))
                p.drawRect(QRectF(self.width() - 18, r.center().y() - 4, 8, 8))
        if self._drag_to is not None:
            p.setPen(QPen(QColor(model.ACCENT), 2))
            y = self._drag_to * self.ROW
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
        p.end()

    def mousePressEvent(self, event):
        n = self._row_at(event.position().y())
        if n < 0 or n >= len(self.rows):
            return
        layer = self.rows[n]
        x = event.position().x()
        if event.button() == Qt.RightButton:
            self.ctl.layer_menu(layer, event.globalPosition().toPoint())
            return
        if x < 26:
            self.ctl.set_layer_flag(layer, "hidden")
        elif x < 46:
            self.ctl.set_layer_flag(layer, "content_locked")
        else:
            self.ctl.set_current_layer(layer)
            self._press = (event.position(), n, bool(QApplication.keyboardModifiers() & Qt.ControlModifier))
        self.update()

    def mouseMoveEvent(self, event):
        if self._press is not None and self._press[2] and \
                (event.position() - self._press[0]).manhattanLength() > 4:
            self._drag_to = max(0, min(len(self.rows), round(event.position().y() / self.ROW)))
            self.update()

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        target, self._drag_to = self._drag_to, None
        if press is not None and target is not None:
            layer = self.rows[press[1]]
            position = target if target <= press[1] else target - 1
            if position != press[1]:
                self.ctl.move_layer(layer, position)
        self.update()

    def mouseDoubleClickEvent(self, event):
        n = self._row_at(event.position().y())
        if 0 <= n < len(self.rows) and event.position().x() >= 46:
            layer = self.rows[n]
            name, ok = QInputDialog.getText(self, "Calque", "Nom :", text=str(layer.data.get("name", "")))
            if ok and name.strip():
                self.ctl.change([layer], lambda l: l.data.update(name=name.strip()), "Renommer le calque")
