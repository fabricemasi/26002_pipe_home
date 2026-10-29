"""`VideoPane` : le module vidéo posé sur la zone des colonnes (comme le board) — afficheur centré, contrôles de
lecture, timeline, informations en surimpression (touche I), corrections colorimétriques et LUT (fenêtres
« Changement de style à la volée »), export, plein écran.

Deux moteurs de lecture (réglage « Moteur de lecture des vidéos ») :
- LibVLC (`vlc_engine`, par défaut pour les vidéos) : décodage matériel, son, synchronisation audio / vidéo et
  cache réseau de VLC ; ses images arrivent en YUV et passent par notre afficheur (shader) ; le rang affiché vient
  de l'horloge de VLC, interpolée. PyAV ne décode RIEN pendant la lecture (ni l'index des images) ; à la pause,
  l'image EXACTE du rang atteint est décodée par PyAV ; pas à pas, IN / OUT, export : PyAV, exact.
- PyAV (séquences d'images, et vidéos si VLC est absent ou choisi) : horloge précise (`perf_counter`) -> rang voulu ;
  l'image vient du cache (chargeurs en fond, jamais de décodage sur le fil de l'interface). « Fluidité » : une image
  pas encore prête est sautée ; « Précision » : l'horloge attend l'image. Audio : QMediaPlayer calé sur l'horloge des
  images (recalé au-delà de 120 ms d'écart).

Aucune dépendance vers la fenêtre principale : `HOOKS` (réglages courants, enregistrement d'une clé d'état,
couleurs « @pastille » et polices de l'appli résolues, message dans la barre d'état)."""
from __future__ import annotations

import math
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF, QPixmap, QUndoStack, QUndoCommand,
)
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSlider, QStackedLayout, QMenu, QComboBox, QSpinBox,
                               QVBoxLayout, QWidget)


class _MoodFrameCommand(QUndoCommand):
    def __init__(self,callback,slot,old,new):
        super().__init__('Ajuster une image du moodboard')
        self.callback,self.slot,self.old,self.new = callback,slot,old,new
        self.first = True
    def redo(self):
        if self.first:
            self.first = False
        else:
            self.callback(self.slot,self.new)
    def undo(self):
        self.callback(self.slot,self.old)


class _MoodboardCanvas(QWidget):
    """Mosaïque dessinée comme une surface unique, zoomable et déplaçable."""
    clicked = Signal(int)
    doubleClicked = Signal(int)
    zoneSelected = Signal(object)
    zoomChanged = Signal(float)
    detailRequested = Signal(object, float)
    colorRequested = Signal(int)
    frameAdjustRequested = Signal(int,float,bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.positions = {}
        self.pixmaps = {}
        self.detail_pixmaps = OrderedDict()
        self.columns = self.rows = 1
        self.cell = QSize(1, 1)
        self.gap = 0
        self.current = 0
        self.bg = QColor('#202020')
        self.scale = 1.0
        self.pan = QPointF()
        self._drag = None
        self._zone_start = None
        self._zone_end = None
        self._zone_mode = False
        self.info_enabled = False
        self.time_labels = {}
        self.info_look = {}
        self.hover_slot = None
        self.frame_slider = QSlider(Qt.Horizontal,self)
        self.frame_slider.setRange(-1000,1000)
        self.frame_slider.setFocusPolicy(Qt.NoFocus)
        self.frame_slider.setToolTip('Ajuster cette image entre ses voisines ; centre = image actuelle')
        self.frame_slider.hide()
        self.frame_slider.valueChanged.connect(lambda value:self._adjust_frame(value,False))
        self.frame_slider.sliderReleased.connect(lambda:self._adjust_frame(self.frame_slider.value(),True))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background: #202020")

    def viewport(self):
        return self

    def iconSize(self):
        return self.cell

    def count(self):
        return len(self.frames)

    def set_grid(self, frames, columns, rows, cell, gap):
        self.frame_slider.hide()
        self.hover_slot = None
        if list(frames) != self.frames:
            self.pixmaps.clear()
            self.detail_pixmaps.clear()
        self.frames = list(frames)
        self.positions = {index:n for n,index in enumerate(self.frames)}
        self.columns, self.rows = max(1, columns), max(1, rows)
        self.cell, self.gap = QSize(cell), max(0, int(gap))
        self.update()

    def set_pixmap(self, index, pixmap):
        self.pixmaps[int(index)] = QPixmap(pixmap)
        self.update(self.slot_rect(index).toAlignedRect().adjusted(-4,-4,4,4))

    def set_detail_pixmap(self, index, pixmap):
        index = int(index)
        self.detail_pixmaps[index] = QPixmap(pixmap)
        self.detail_pixmaps.move_to_end(index)
        while len(self.detail_pixmaps) > 32:
            self.detail_pixmaps.popitem(last=False)
        self.update(self.slot_rect(index).toAlignedRect().adjusted(-4,-4,4,4))

    def slot_rect(self,index):
        if index not in self.positions:
            return QRectF()
        row,col = divmod(self.positions[index],self.columns)
        size = self.board_size()
        return QRectF((self.width()-size.width()*self.scale)/2+self.pan.x()+(self.gap+col*(self.cell.width()+self.gap))*self.scale,
                      (self.height()-size.height()*self.scale)/2+self.pan.y()+(self.gap+row*(self.cell.height()+self.gap))*self.scale,
                      self.cell.width()*self.scale,self.cell.height()*self.scale)

    def _adjust_frame(self,value,final):
        if self.hover_slot is not None:
            self.frameAdjustRequested.emit(self.hover_slot,value/1000,final)
        if final:
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(0)
            self.frame_slider.blockSignals(False)

    def _hover_frame(self,index):
        if self.frame_slider.isSliderDown():
            return
        if index is None or self._zone_mode:
            self.frame_slider.hide()
            return
        if index!=self.hover_slot:
            self.hover_slot = index
            self.frame_slider.blockSignals(True)
            self.frame_slider.setValue(0)
            self.frame_slider.blockSignals(False)
        rect = self.slot_rect(index)
        self.frame_slider.setGeometry(int(rect.x()+6),int(rect.bottom()-25),max(20,int(rect.width()-12)),20)
        self.frame_slider.show()

    def leaveEvent(self,event):
        if not self.frame_slider.isSliderDown():
            self.frame_slider.hide()
        super().leaveEvent(event)

    def set_current(self, index):
        self.current = int(index)
        self.update()

    def set_region_mode(self, on):
        self._zone_mode = bool(on)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def board_size(self):
        return QSize(self.columns * self.cell.width() + (self.columns + 1) * self.gap,
                     self.rows * self.cell.height() + (self.rows + 1) * self.gap)

    def fit(self):
        self.scale = 1.0
        self.pan = QPointF()
        self.update()
        self.zoomChanged.emit(self.scale)

    def recenter(self):
        self.pan = QPointF()
        self.update()

    def one_to_one(self):
        self.set_zoom(1.0)

    def zoom_by(self, steps, anchor=None):
        self.set_zoom(self.scale * (1.25 ** steps), anchor)

    def set_zoom(self, scale, anchor=None):
        scale = max(0.05, min(16.0, float(scale)))
        anchor = QPointF(self.rect().center()) if anchor is None else QPointF(anchor)
        old = self.scale
        world_x = (anchor.x() - self.width() / 2 - self.pan.x()) / old
        world_y = (anchor.y() - self.height() / 2 - self.pan.y()) / old
        self.scale = scale
        self.pan = QPointF(anchor.x() - self.width() / 2 - world_x * scale,
                           anchor.y() - self.height() / 2 - world_y * scale)
        self._clamp_pan()
        self.update()
        self.zoomChanged.emit(self.scale)
        self._request_detail()

    def _request_detail(self):
        if self.scale < 1.35 or not self.frames:
            return
        size = self.board_size()
        ox = (self.width() - size.width() * self.scale) / 2 + self.pan.x()
        oy = (self.height() - size.height() * self.scale) / 2 + self.pan.y()
        viewport = QRectF(self.rect())
        indices = []
        for n, index in enumerate(self.frames):
            row, col = divmod(n, self.columns)
            cell_rect = QRectF(self.gap + col * (self.cell.width() + self.gap),
                               self.gap + row * (self.cell.height() + self.gap),
                               self.cell.width(), self.cell.height())
            screen_rect = QRectF(ox + cell_rect.x() * self.scale, oy + cell_rect.y() * self.scale,
                                 cell_rect.width() * self.scale, cell_rect.height() * self.scale)
            if screen_rect.intersects(viewport):
                indices.append(index)
        self.detailRequested.emit(indices, self.cell.height() * self.scale * 1.6)

    def _clamp_pan(self):
        # Pan libre : on peut déplacer la grande mosaïque au-delà de ses extrémités.
        pass

    def _cell_at(self, point):
        size = self.board_size()
        x = (point.x() - (self.width() - size.width() * self.scale) / 2 - self.pan.x()) / self.scale
        y = (point.y() - (self.height() - size.height() * self.scale) / 2 - self.pan.y()) / self.scale
        stride_x, stride_y = self.cell.width() + self.gap, self.cell.height() + self.gap
        col, row = int(x // max(1, stride_x)), int(y // max(1, stride_y))
        if x < 0 or y < 0 or col >= self.columns or row >= self.rows:
            return None
        if x - col * stride_x < self.gap or y - row * stride_y < self.gap:
            return None
        i = row * self.columns + col
        return self.frames[i] if i < len(self.frames) else None

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120
        if delta:
            self.zoom_by(delta, event.position())
        event.accept()

    def contextMenuEvent(self, event):
        index = self._cell_at(event.pos())
        if index is None:
            return
        menu = QMenu(self)
        action = menu.addAction('Dominante couleur')
        if menu.exec(event.globalPos()) == action:
            self.colorRequested.emit(index)

    def mousePressEvent(self, event):
        if self._zone_mode and event.button() == Qt.LeftButton:
            self._zone_start = event.position()
            self._zone_end = event.position()
            event.accept()
        elif event.button() in (Qt.LeftButton, Qt.MiddleButton):
            if event.button() == Qt.MiddleButton and event.modifiers() & Qt.ShiftModifier:
                self.one_to_one()
                self.recenter()
                event.accept()
                return
            self._drag = (event.position(), QPointF(self.pan), event.button(), False)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._zone_start is not None:
            self._zone_end = event.position()
            self.update()
        elif self._drag is not None:
            start, pan, button, moved = self._drag
            delta = event.position() - start
            if moved or abs(delta.x()) + abs(delta.y()) > 3:
                self._drag = (start, pan, button, True)
                self.pan = pan + delta
                self._clamp_pan()
                self.update()
                self._request_detail()
        i = self._cell_at(event.position())
        self._hover_frame(i)
        self.setToolTip(f"Image {self.frames.index(i) + 1}" if i in self.frames else "")

    def mouseReleaseEvent(self, event):
        if self._zone_start is not None and event.button() == Qt.LeftButton:
            a, self._zone_start = self._zone_start, None
            self._zone_end = None
            rect = QRect(a.toPoint(), event.position().toPoint()).normalized().intersected(self.rect())
            if rect.width() > 1 and rect.height() > 1:
                self.zoneSelected.emit(rect)
            self.update()
            return
        drag, self._drag = self._drag, None
        if drag and not drag[3] and drag[2] == Qt.LeftButton:
            i = self._cell_at(event.position())
            if i is not None:
                self.clicked.emit(i)

    def mouseDoubleClickEvent(self, event):
        i = self._cell_at(event.position())
        if i is not None:
            self.doubleClicked.emit(i)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        if not self.frames:
            return
        size = self.board_size()
        ox = (self.width() - size.width() * self.scale) / 2 + self.pan.x()
        oy = (self.height() - size.height() * self.scale) / 2 + self.pan.y()
        p.save()
        p.translate(ox, oy)
        p.scale(self.scale, self.scale)
        for n, index in enumerate(self.frames):
            if not self.slot_rect(index).intersects(QRectF(event.rect())):
                continue
            row, col = divmod(n, self.columns)
            rect = QRectF(self.gap + col * (self.cell.width() + self.gap),
                          self.gap + row * (self.cell.height() + self.gap),
                          self.cell.width(), self.cell.height())
            pix = self._pixmap_for(index)
            if pix and not pix.isNull():
                p.drawPixmap(rect, pix, QRectF(pix.rect()))
            if index == self.current:
                p.setPen(QPen(QColor("#ff3030"), max(2.0, 3.0 / self.scale)))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(1, 1, -1, -1))
        p.restore()
        if self.info_enabled:
            font = p.font()
            font.setPixelSize(int(self.info_look.get('font_size',11)))
            p.setFont(font)
            for index,lines in self.time_labels.items():
                cell = self.slot_rect(index)
                if not cell.intersects(QRectF(event.rect())):
                    continue
                padding = int(self.info_look.get('padding',4))
                text = '\n'.join(lines)
                metrics = p.fontMetrics()
                width = min(cell.width(),max((metrics.horizontalAdvance(line) for line in lines),default=0)+2*padding)
                height = len(lines)*metrics.height()+2*padding
                position = self.info_look.get('position','top_right')
                mx,my = self.info_look.get('margin_x',4),self.info_look.get('margin_y',4)
                box = QRectF(cell.left()+mx if position.endswith('left') else cell.right()-width-mx,
                             cell.bottom()-height-my if position.startswith('bottom') else cell.top()+my,width,height)
                p.save()
                p.setClipRect(cell)
                bg = QColor(self.info_look.get('bg','#000000'))
                bg.setAlphaF(float(self.info_look.get('opacity',.75)))
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(box,float(self.info_look.get('radius',2)),float(self.info_look.get('radius',2)))
                p.setPen(QColor(self.info_look.get('color','#ffffff')))
                p.drawText(box.adjusted(padding,padding,-padding,-padding),Qt.AlignRight|Qt.AlignTop,text)
                p.restore()
        if self._zone_start is not None:
            p.setPen(QPen(QColor("#ff3030"), 2, Qt.DashLine))
            p.drawRect(QRectF(self._zone_start, self._zone_end or self._zone_start).normalized())

    def _pixmap_for(self, index):
        pix = self.detail_pixmaps.get(index)
        if pix is not None:
            self.detail_pixmaps.move_to_end(index)
            return pix
        return self.pixmaps.get(index)


from fm_video import color as vcolor
from fm_video import media as vmedia
from fm_video.cache import FrameCache, FrameLoader
from fm_video.timeline import Timeline
from fm_video.viewer import InfoOverlay, create_viewer

HOOKS = {
    "settings": lambda: {},
    "save_state": None,          # (clé, valeur) : clé d'état temps réel écrite aussitôt
    "write_setting": None,       # (clé, valeur) : réglage écrit (fichier + preset actif)
    "resolve_color": None,       # « @pastille/75 » -> « #aarrggbb »
    "resolve_font": None,        # rôle de police de l'appli -> vraie famille
    "status": None,              # message dans la barre d'état
}

# Corrections réglables : (clé, libellé, min, max, échelle, unité). Valeur stockée = valeur réelle × échelle.
GRADE_MAIN = (
    ("exposure", "Exposition", -1000, 1000, 100, "stops"),
    ("contrast", "Contraste", 0, 300, 100, ""),
    ("pivot", "Pivot du contraste", 1, 1000, 1000, ""),
    ("gamma", "Gamma", 20, 500, 100, ""),
    ("saturation", "Saturation", 0, 300, 100, ""),
    ("vibrance", "Vibrance", -100, 100, 100, ""),
    ("hue", "Teinte", -180, 180, 1, "°"),
    ("temperature", "Température", -100, 100, 1, ""),
    ("tint", "Tint (vert / magenta)", -100, 100, 1, ""),
    ("gain", "Gain", 0, 400, 100, ""),
    ("lift", "Lift", -500, 500, 1000, ""),
    ("offset", "Offset", -500, 500, 1000, ""),
    ("highlights", "Hautes lumières", -400, 400, 100, "stops"),
    ("shadows", "Ombres", -400, 400, 100, "stops"),
    ("whites", "Blancs", -400, 400, 100, "stops"),
    ("blacks", "Noirs", -400, 400, 100, "stops"),
    ("brightness", "Luminosité (affichage)", -500, 500, 1000, ""),
)
GRADE_CHANNELS = tuple(
    (f"{name}_{c}", f"{label} {c.upper()}", low, high, scale, "")
    for name, label, low, high, scale in (("lift", "Lift", -500, 500, 1000), ("gamma", "Gamma", 20, 500, 100),
                                          ("gain", "Gain", 0, 400, 100), ("offset", "Offset", -500, 500, 1000))
    for c in "rgb") + (
    ("in_black", "Niveaux : entrée noir", 0, 1000, 1000, ""), ("in_white", "Niveaux : entrée blanc", 0, 1000, 1000, ""),
    ("out_black", "Niveaux : sortie noir", 0, 1000, 1000, ""), ("out_white", "Niveaux : sortie blanc", 0, 1000, 1000, ""),
)
_ALL_GRADE = {row[0]: row for row in GRADE_MAIN + GRADE_CHANNELS}


def _setting(settings: dict, key: str):
    from fm_video.settings_defaults import VIDEO_DEFAULTS
    return settings.get(key, VIDEO_DEFAULTS.get(key))


def _color(settings: dict, key: str) -> str:
    value = str(_setting(settings, key) or "#000000")
    resolve = HOOKS.get("resolve_color")
    if value.startswith("@") and resolve is not None:
        try:
            return resolve(value)
        except Exception:                                    # noqa: BLE001
            return "#808080"
    return value


# ==========================================================================
# Boutons de la barre de contrôle (glyphes peints)
# ==========================================================================

class _CtlButton(QWidget):
    clicked = Signal()
    rightClicked = Signal()

    def __init__(self, kind: str, tip: str, parent=None, checkable=False):
        super().__init__(parent)
        self.kind = kind
        self.checkable = checkable
        self.checked = False
        self.enabled_ = True
        self.color = QColor("#c4cacf")
        self.accent = QColor("#3a6ea5")
        self.setToolTip(tip)
        self.setFixedSize(30, 26)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def set_checked(self, on: bool):
        if on != self.checked:
            self.checked = on
            self.update()

    def set_kind(self, kind: str):
        if kind != self.kind:
            self.kind = kind
            self.update()

    def mouseReleaseEvent(self, event):
        if not self.rect().contains(event.position().toPoint()):
            return
        if event.button() == Qt.LeftButton:
            if self.checkable:
                self.set_checked(not self.checked)
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.rightClicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.checked or self.underMouse():
            bg = QColor(self.accent if self.checked else self.color)
            bg.setAlphaF(0.35 if self.checked else 0.12)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 4, 4)
        color = QColor(self.color)
        if not self.enabled_:
            color.setAlphaF(0.3)
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = r.center().x(), r.center().y()
        s = min(r.width(), r.height()) * 0.22
        k = self.kind
        fill = QColor(color)

        def tri(x, direction=1, size=1.0):
            return QPolygonF([QPointF(x - direction * s * 0.8 * size, cy - s * size),
                              QPointF(x + direction * s * 0.8 * size, cy),
                              QPointF(x - direction * s * 0.8 * size, cy + s * size)])
        if k == "play":
            p.setBrush(fill)
            p.drawPolygon(tri(cx + s * 0.15))
        elif k == "pause":
            p.setBrush(fill)
            p.drawRect(QRectF(cx - s * 0.8, cy - s, s * 0.55, 2 * s))
            p.drawRect(QRectF(cx + s * 0.25, cy - s, s * 0.55, 2 * s))
        elif k == "stop":
            p.setBrush(fill)
            p.drawRect(QRectF(cx - s * 0.85, cy - s * 0.85, s * 1.7, s * 1.7))
        elif k in ("next", "prev"):
            d = 1 if k == "next" else -1
            p.setBrush(fill)
            p.drawPolygon(tri(cx - d * s * 0.25, d, 0.85))
            p.drawLine(QPointF(cx + d * s * 0.85, cy - s * 0.85), QPointF(cx + d * s * 0.85, cy + s * 0.85))
        elif k in ("start", "end"):
            d = 1 if k == "end" else -1
            p.setBrush(fill)
            p.drawPolygon(tri(cx - d * s * 0.6, d, 0.8))
            p.drawPolygon(tri(cx + d * s * 0.25, d, 0.8))
            p.drawLine(QPointF(cx + d * s * 1.15, cy - s * 0.8), QPointF(cx + d * s * 1.15, cy + s * 0.8))
        elif k == "loop":
            p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.addRoundedRect(QRectF(cx - s * 1.3, cy - s * 0.75, s * 2.6, s * 1.5), s * 0.7, s * 0.7)
            p.drawPath(path)
            p.setBrush(fill)
            p.drawPolygon(QPolygonF([QPointF(cx + s * 0.2, cy - s * 1.15), QPointF(cx + s * 0.7, cy - s * 0.75),
                                     QPointF(cx + s * 0.2, cy - s * 0.35)]))
        elif k == "range":
            p.drawLine(QPointF(cx - s * 1.2, cy - s), QPointF(cx - s * 1.2, cy + s))
            p.drawLine(QPointF(cx + s * 1.2, cy - s), QPointF(cx + s * 1.2, cy + s))
            p.drawLine(QPointF(cx - s * 0.8, cy), QPointF(cx + s * 0.8, cy))
            p.drawLine(QPointF(cx + s * 0.4, cy - s * 0.4), QPointF(cx + s * 0.8, cy))
            p.drawLine(QPointF(cx + s * 0.4, cy + s * 0.4), QPointF(cx + s * 0.8, cy))
        elif k in ("in", "out"):
            p.setFont(self.font())
            p.drawText(r, Qt.AlignCenter, "IN" if k == "in" else "OUT")
        elif k == "clear":
            p.drawLine(QPointF(cx - s * 0.8, cy - s * 0.8), QPointF(cx + s * 0.8, cy + s * 0.8))
            p.drawLine(QPointF(cx - s * 0.8, cy + s * 0.8), QPointF(cx + s * 0.8, cy - s * 0.8))
        elif k in ("sound", "mute"):
            p.setBrush(fill)
            p.drawPolygon(QPolygonF([QPointF(cx - s * 1.2, cy - s * 0.4), QPointF(cx - s * 0.6, cy - s * 0.4),
                                     QPointF(cx, cy - s), QPointF(cx, cy + s), QPointF(cx - s * 0.6, cy + s * 0.4),
                                     QPointF(cx - s * 1.2, cy + s * 0.4)]))
            p.setBrush(Qt.NoBrush)
            if k == "sound":
                p.drawArc(QRectF(cx - s * 0.5, cy - s * 0.7, s * 1.4, s * 1.4), -50 * 16, 100 * 16)
            else:
                p.drawLine(QPointF(cx + s * 0.35, cy - s * 0.5), QPointF(cx + s * 1.2, cy + s * 0.5))
                p.drawLine(QPointF(cx + s * 0.35, cy + s * 0.5), QPointF(cx + s * 1.2, cy - s * 0.5))
        elif k == "center":
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(cx - s * 1.3, cy - s * 0.95, s * 2.6, s * 1.9))
            p.setBrush(fill)
            p.drawEllipse(QPointF(cx, cy), s * 0.3, s * 0.3)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p.drawLine(QPointF(cx + dx * s * 0.55, cy + dy * s * 0.45), QPointF(cx + dx * s * 0.95, cy + dy * s * 0.8))
        elif k == "shot":
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(cx - s * 1.3, cy - s * 0.65, s * 2.6, s * 1.6), s * 0.25, s * 0.25)
            p.drawRect(QRectF(cx - s * 0.5, cy - s * 0.95, s * 1.0, s * 0.3))
            p.drawEllipse(QPointF(cx, cy + s * 0.15), s * 0.5, s * 0.5)
        elif k == "zone":
            dash = QPen(p.pen())
            dash.setStyle(Qt.DashLine)
            p.setPen(dash)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(cx - s * 1.3, cy - s * 0.9, s * 2.6, s * 1.8))
            p.setPen(QPen(color, 1.4))
            p.drawLine(QPointF(cx + s * 0.5, cy + s * 0.2), QPointF(cx + s * 1.3, cy + s * 0.9))
        elif k == "thumbs":
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(cx - s * 1.4, cy - s * 0.8, s * 2.8, s * 1.6))
            p.drawLine(QPointF(cx - s * 0.45, cy - s * 0.8), QPointF(cx - s * 0.45, cy + s * 0.8))
            p.drawLine(QPointF(cx + s * 0.45, cy - s * 0.8), QPointF(cx + s * 0.45, cy + s * 0.8))
        elif k == "fit":
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                c = QPointF(cx + sx * s * 1.2, cy + sy * s * 0.9)
                p.drawLine(c, QPointF(c.x() - sx * s * 0.6, c.y()))
                p.drawLine(c, QPointF(c.x(), c.y() - sy * s * 0.6))
        elif k == "one":
            p.setFont(self.font())
            p.drawText(r, Qt.AlignCenter, "1:1")
        elif k == "moodboard":
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(cx - s * 1.25, cy - s, s * 2.5, s * 2), 2, 2)
            p.drawRect(QRectF(cx - s * 0.85, cy - s * 0.6, s * 0.7, s * 0.65))
            p.drawRect(QRectF(cx + s * 0.15, cy - s * 0.6, s * 0.7, s * 0.65))
            p.drawRect(QRectF(cx - s * 0.85, cy + s * 0.25, s * 0.7, s * 0.45))
            p.drawRect(QRectF(cx + s * 0.15, cy + s * 0.25, s * 0.7, s * 0.45))
        elif k == "scopes":
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(cx - s * 1.2, cy - s, s * 2.4, s * 2))
            for i, hh in enumerate((0.5, 1.2, 0.8, 1.5, 0.6)):
                x = cx - s * 0.85 + i * s * 0.42
                p.drawLine(QPointF(x, cy + s * 0.8), QPointF(x, cy + s * 0.8 - s * hh))
        elif k == "reset":
            p.setBrush(Qt.NoBrush)
            rr = s * 1.0
            p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr), 70 * 16, 290 * 16)
            tip = QPointF(cx + rr * 0.35, cy - rr * 0.95)
            p.drawLine(tip, QPointF(tip.x() - s * 0.6, tip.y() - s * 0.35))
            p.drawLine(tip, QPointF(tip.x() - s * 0.2, tip.y() + s * 0.6))
        elif k == "compare":
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(cx - s * 1.3, cy - s * 0.9, s * 2.6, s * 1.8))
            p.setBrush(fill)
            p.drawRect(QRectF(cx, cy - s * 0.9, s * 1.3, s * 1.8))


class _Controls(QWidget):
    """Barre de contrôle (fond réglable) : transport, IN / OUT, position, cadence, calque, zoom, volume."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg = QColor("#16181a")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), self.bg)


# ==========================================================================
# Le module
# ==========================================================================

class VideoPane(QWidget):
    closeRequested = Signal()
    stateChanged = Signal()

    def __init__(self, parent: QWidget, settings: dict | None = None):
        super().__init__(parent)
        self.setObjectName("VideoPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # OPAQUE (fond plein, enfants qui couvrent tout) : sans cela Qt repeignait à CHAQUE image les colonnes
        # cachées dessous (lignes, effets de coins arrondis : ~20 ms par image, lecture 1080p saccadée).
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._settings = dict(settings or {})
        self.path: Path | None = None
        self.source: vmedia.MediaSource | None = None
        self.loader: FrameLoader | None = None
        self.cache = FrameCache(int(_setting(self._settings, "video_cache_mb")) << 20)
        self.index = 0
        self._shown = -1
        self._pending = None
        self._playing = False
        self._clock = (0.0, 0)
        self._last_tick = 0.0
        self._loop = bool(_setting(self._settings, "video_loop"))
        self._loop_range = False
        self._positions: dict[str, int] = {}
        self._input_override: dict[str, str] = {}
        self._pipeline = None
        self._pipeline_key = None
        self._hover = None
        self._message = ""
        self._grade = dict(vcolor.DEFAULT_GRADE)
        self._grade.update({k: v for k, v in (_setting(self._settings, "video_grade") or {}).items()
                            if k in vcolor.DEFAULT_GRADE})
        self._grade_on = True
        self._bypass: set[str] = set()       # fenêtres de corrections montrées « avant » (icône avant / après)
        self._lut: vcolor.Lut | None = None
        self._lut_mix = int(_setting(self._settings, "video_lut_mix")) / 100.0
        self._lut_position = _setting(self._settings, "video_lut_position")
        self._channel = _setting(self._settings, "video_channel")
        self._clipping = bool(_setting(self._settings, "video_clipping"))
        self._compare = "off"
        self._windows = {}
        self._export_job = None
        self._fullscreen = None
        self._fs_home = None
        self._audio = None
        self._audio_out = None
        self._muted = False
        self._volume = int(_setting(self._settings, "video_volume"))     # SEULE source du volume (0-100)
        self._engine = "pyav"                 # moteur du média ouvert : « vlc » ou « pyav »
        self._vlc = None                      # vlc_engine.VlcPlayer, créé à la 1re vidéo, gardé
        self._vlc_anchor = None               # (instant, ms de VLC, dernière lecture) : horloge interpolée
        self._vlc_yuv = None                  # matrice / plage / chromas de la vidéo (images de VLC)
        self._vlc_paused_at = None            # rang où VLC a été mis en pause (reprise sans saut)
        self._vlc_start = None                # [rang, ms, instant et horloge de VLC à la 1re image] du départ
        self._thumbs = None                   # thumbs.ThumbnailLoader du média ouvert
        self._mood_thumbs = None              # chargeur isolé : ses demandes ne sont pas remplacées par celles de la timeline
        self._bypass_buttons: dict = {}       # icône avant / après de chaque fenêtre de corrections ouverte
        self._snapshots = None                # snapshot.SnapshotSaver (captures PNG, en fond)
        self.last_snapshot = ""               # chemin de la dernière capture enregistrée
        self._click_toggle_at = 0.0           # dernier clic sur l'image (lecture / pause), voir le double-clic
        self._vlc_skip = 0                    # images de VLC écartées après un départ (aperçu périmé)
        self._scrub_resume = False
        self._info_at = 0.0
        self._zoom_timer = None
        self._moodboard_on = False
        self._moodboard_paths = []
        self._moodboard_items = {}
        self._moodboard_positions = {}
        self._mood_size = 180
        self._mood_refresh_timer = QTimer(self)
        self._mood_refresh_timer.setSingleShot(True)
        self._mood_refresh_timer.setInterval(140)
        self._mood_refresh_timer.timeout.connect(self._refresh_moodboard_thumbnails)
        self._mood_detail_indices = []
        self._mood_detail_height = 0
        self._mood_detail_timer = QTimer(self)
        self._mood_detail_timer.setSingleShot(True)
        self._mood_detail_timer.setInterval(100)
        self._mood_detail_timer.timeout.connect(self._request_moodboard_detail)
        self._mood_capture = None
        self._mood_capture_timer = QTimer(self)
        self._mood_capture_timer.setSingleShot(True)
        self._mood_capture_timer.setInterval(30000)
        self._mood_capture_timer.timeout.connect(self._finish_moodboard_capture)
        self._build()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(4)
        self._timer.timeout.connect(self._tick)
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.timeout.connect(lambda: self._set_info_visible(False, user=False))
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(2200)
        self._hide_timer.timeout.connect(self._autohide_controls)
        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(250)
        self._cache_timer.timeout.connect(self._sync_cache_marks)
        self._cache_timer.start()
        self.apply_settings(self._settings)
        parent.installEventFilter(self)
        self.hide()

    # -- construction --

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.viewer = create_viewer(_setting(self._settings, "video_backend"), self)
        self._connect_viewer()
        self.content = QWidget(self)
        self.content_layout = QStackedLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addWidget(self.viewer)
        self.moodboard = _MoodboardCanvas(self.content)
        self._mood_selections = {}
        self._mood_edit_slot = None
        self._mood_edit_old = None
        self._mood_edit_history = {}
        self._mood_undo = QUndoStack(self)
        self._mood_adjust_timer = QTimer(self)
        self._mood_adjust_timer.setSingleShot(True)
        self._mood_adjust_timer.setInterval(80)
        self._mood_adjust_timer.timeout.connect(self._send_mood_adjust)
        self._mood_adjust_pending = None
        self.moodboard.frameAdjustRequested.connect(self._adjust_mood_frame)
        self.moodboard.installEventFilter(self)
        self.moodboard.zoomChanged.connect(self._on_moodboard_zoom)
        self.moodboard.detailRequested.connect(self._queue_moodboard_detail)
        self.moodboard.clicked.connect(self._moodboard_clicked)
        self.moodboard.doubleClicked.connect(self._moodboard_double_clicked)
        self.moodboard.zoneSelected.connect(self._moodboard_zone_selected)
        self.moodboard.colorRequested.connect(self._open_color_analysis)
        self.content_layout.addWidget(self.moodboard)
        self._analysis = None
        self._analysis_index = None
        root.addWidget(self.content, 1)
        background_row = QHBoxLayout()
        background_row.addWidget(QLabel('Fond', self))
        self.background_select = QComboBox(self)
        self.background_select.addItems(['Noir', 'Gris 25 %', 'Gris 50 %', 'Gris 75 %', 'Gris 10 10 10', 'Personnalisé'])
        background_row.addWidget(self.background_select)
        self.background_slider = QSlider(Qt.Horizontal, self)
        self.background_slider.setRange(0,255)
        self.background_slider.setFixedWidth(140)
        background_row.addWidget(self.background_slider)
        self.background_value = QSpinBox(self)
        self.background_value.setRange(0,255)
        background_row.addWidget(self.background_value)
        background_row.addStretch(1)
        root.addLayout(background_row)
        self.background_select.currentIndexChanged.connect(self._background_preset)
        self.background_slider.valueChanged.connect(self._background_changed)
        self.background_value.valueChanged.connect(self._background_changed)
        self._background_save_timer = QTimer(self)
        self._background_save_timer.setSingleShot(True)
        self._background_save_timer.setInterval(300)
        self._background_save_timer.timeout.connect(self._save_background)
        self._background_pending = {}
        from fm_video.help_ui import HelpController, annotate
        self._color_help = HelpController(self,self._settings)
        for widget in (self.background_select,self.background_slider,self.background_value):
            annotate(widget,'background')
        self.controls = _Controls(self)
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(2)
        self.buttons = {}

        def add(kind, tip, slot, checkable=False):
            button = _CtlButton(kind, tip, self.controls, checkable)
            button.clicked.connect(slot)
            self.buttons[kind] = button
            row.addWidget(button)
            return button
        add("start", "Première image (Début)", self.go_first)
        add("prev", "Image précédente (←)", lambda: self.step(-1))
        add("play", "Lecture / pause (Espace)", self.toggle_play)
        add("next", "Image suivante (→)", lambda: self.step(1))
        add("end", "Dernière image (Fin)", self.go_last)
        add("stop", "Stop (retour au début de la plage)", self.stop)
        row.addSpacing(8)
        add("loop", "Lecture en boucle", self._toggle_loop, checkable=True)
        add("range", "Boucler sur la sélection IN / OUT", self._toggle_loop_range, checkable=True)
        add("in", "Point IN ici", self.set_in)
        add("out", "Point OUT ici", self.set_out)
        add("clear", "Effacer IN / OUT", self.clear_range)
        row.addSpacing(10)
        self.frame_field = QLineEdit(self.controls)
        self.frame_field.setFixedWidth(70)
        self.frame_field.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.frame_field.setToolTip("Numéro d'image (Entrée = y aller ; accepte aussi un timecode HH:MM:SS:FF)")
        self.frame_field.returnPressed.connect(self._frame_entered)
        row.addWidget(self.frame_field)
        self.count_label = QLabel(self.controls)
        row.addWidget(self.count_label)
        row.addSpacing(10)
        self.tc_label = QLabel(self.controls)
        self.tc_label.setToolTip("Timecode")
        row.addWidget(self.tc_label)
        row.addSpacing(8)
        from settings_widgets import _MiniSlider, _SelectField
        self.unit_select = _SelectField(["Images", "Secondes"], "Images", width=96)
        self.unit_select.setToolTip("Unité de la timeline (affichage seulement)")
        self.unit_select.changed.connect(self._unit_chosen)
        row.addWidget(self.unit_select)
        row.addStretch(1)
        self.layer_select = _SelectField([""], "", width=150)
        self.layer_select.setToolTip("Calque / AOV (EXR)")
        self.layer_select.changed.connect(self._layer_chosen)
        row.addWidget(self.layer_select)
        self.channel_select = _SelectField(["RVB", "R", "V", "B", "Alpha", "Luma"], "RVB", width=80)
        self.channel_select.setToolTip("Canal affiché")
        self.channel_select.changed.connect(self._channel_chosen)
        row.addWidget(self.channel_select)
        self.fps_select = _SelectField([label for _v, label in vmedia.FPS_CHOICES], "24", width=80)
        self.fps_select.setToolTip("FPS de lecture (séquences d'images)")
        self.fps_select.changed.connect(self._fps_chosen)
        row.addWidget(self.fps_select)
        row.addSpacing(6)
        add("compare", "Avant / après (clic : partagé → avant → après ; clic droit : couper)", self._cycle_compare)
        add("reset", "Réinitialiser les corrections", self.reset_grade)
        add("scopes", "Scopes : histogramme, waveform, vectorscope (S)", self.toggle_scopes, checkable=True)
        add("shot", "Capture de l'image en PNG (pleine définition, couleurs affichées) : dossier au nom du film, "
            "à côté du fichier, <film>_001.png…", self.take_snapshot)
        add("zone", "Capture d'une zone : tracer un rectangle sur l'image (z_<film>_001.png, même dossier ; "
            "Échap = annuler)", self.toggle_zone_capture, checkable=True)
        add("thumbs", "Miniatures de la timeline : lire les images de la partie visible (zoom / défilement : "
            "pas de mise à jour automatique, recliquer)", self.request_thumbs)
        add("center", "Recentrer la vidéo / le moodboard (sans changer le zoom)", self._active_recenter)
        add("fit", "Ajuster à l'écran (0)", self._active_fit)
        add("one", "Zoom 1:1 (1)", self._active_one_to_one)
        add("moodboard", "Afficher un moodboard d'images extraites de la vidéo (M)", self.toggle_moodboard,
            checkable=True)
        self.mood_size_label = QLabel(f"Taille : {self._mood_size} px", self.controls)
        row.addWidget(self.mood_size_label)
        self.mood_size_slider = QSlider(Qt.Horizontal, self.controls)
        self.mood_size_slider.setRange(80, 420)
        self.mood_size_slider.setValue(self._mood_size)
        self.mood_size_slider.setFixedWidth(100)
        self.mood_size_slider.setToolTip("Taille des images du moodboard")
        self.mood_size_slider.valueChanged.connect(self._set_moodboard_size)
        row.addWidget(self.mood_size_slider)
        self.mood_gap_label = QLabel("Marge : 0 px", self.controls)
        row.addWidget(self.mood_gap_label)
        self.mood_gap_slider = QSlider(Qt.Horizontal, self.controls)
        self.mood_gap_slider.setRange(0, 80)
        self.mood_gap_slider.setValue(0)
        self.mood_gap_slider.setFixedWidth(90)
        self.mood_gap_slider.setToolTip("Espacement identique en haut, bas, gauche, droite et entre les images")
        self.mood_gap_slider.valueChanged.connect(self._set_moodboard_gap)
        row.addWidget(self.mood_gap_slider)
        self.mood_size_label.hide()
        self.mood_size_slider.hide()
        self.mood_gap_label.hide()
        self.mood_gap_slider.hide()
        self.zoom_label = QLabel(self.controls)
        self.zoom_label.setToolTip("Zoom de l'image")
        self.zoom_label.setFixedWidth(52)
        self.zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.zoom_label)
        row.addSpacing(6)
        add("sound", "Couper / remettre le son", self._toggle_mute)
        self.volume = _MiniSlider(0, 100, self._volume, 80)
        self.volume.setToolTip("Volume")
        self.volume.valueChanged.connect(self._volume_changed)
        row.addWidget(self.volume)
        self.volume_label = QLabel(f"{self._volume} %", self.controls)
        self.volume_label.setToolTip("Volume")
        self.volume_label.setFixedWidth(40)
        self.volume_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.volume_label)
        root.addWidget(self.controls)
        self.timeline = Timeline(self)
        self.timeline.seekRequested.connect(self._seek_from_timeline)
        self.timeline.scrubStarted.connect(self._scrub_started)
        self.timeline.thumbsWanted.connect(self._thumbs_wanted)
        self.timeline.thumbHeightChanged.connect(self._thumb_height_chosen)
        self.timeline.scrubFinished.connect(self._scrub_finished)
        self.timeline.rangeChanged.connect(lambda _a, _b: self._update_info())
        root.addWidget(self.timeline)
        self.overlay = InfoOverlay(self.viewer)
        from fm_video.scopes import ScopesPanel
        self.scopes = ScopesPanel(self.viewer)
        self._scope_worker = None
        self._scope_at = 0.0
        self.message = QLabel(self.viewer)
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.message.hide()

    def _connect_viewer(self):
        self.viewer.zoomChanged.connect(self._on_zoom)
        self.viewer.regionSelected.connect(self._zone_selected)
        self.viewer.viewClicked.connect(self._on_view_clicked)
        self.viewer.pixelHovered.connect(self._on_pixel)
        self.viewer.installEventFilter(self)
        if hasattr(self.viewer, "glFailed"):
            self.viewer.glFailed.connect(self._fallback_cpu)

    def _fallback_cpu(self, message: str):
        """OpenGL indisponible : même module en affichage CPU (message dans les informations)."""
        from fm_video.viewer import CPUViewer
        old = self.viewer
        layout = self.content_layout
        new = CPUViewer(self)
        layout.removeWidget(old)
        layout.insertWidget(0, new)
        self.overlay.setParent(new)
        self.message.setParent(new)
        old.hide()
        old.deleteLater()
        self.viewer = new
        self._connect_viewer()
        self.apply_settings(self._settings)
        self._push_state()
        if self._shown >= 0:
            self._show(self._shown, force=True)
        self._status(f"Affichage CPU (OpenGL indisponible : {message})")

    # -- réglages --

    def apply_settings(self, settings: dict):
        """Réglages > Module vidéo, appliqués tout de suite (rien n'est refait qui n'a pas changé)."""
        self._settings = dict(settings or {})
        s = self._settings
        self._color_help.settings = s
        get = lambda k: _setting(s, k)       # noqa: E731
        if self._mood_thumbs is not None:
            if self._mood_thumbs.set_proxy_width(get("video_moodboard_proxy_width")) and self._moodboard_on:
                self._mood_refresh_timer.start()
        self.viewer.set_look({
            "bg": _color(s, "video_bg_color"), "checker": get("video_checker"),
            "checker_size": get("video_checker_size"), "checker_a": _color(s, "video_checker_a"),
            "checker_b": _color(s, "video_checker_b"), "interpolation": get("video_interpolation"),
            "wheel_zoom": get("video_wheel_zoom"), "zoom_step": get("video_zoom_step"), "pan": get("video_pan"),
            "fit_margin": get("video_fit_margin")})
        self.moodboard.bg = QColor(s.get('video_moodboard_bg_color', '#202020'))
        self.moodboard.info_enabled = bool(s.get('video_mood_info_enabled',False))
        self.moodboard.info_look = dict(font_size=s.get('video_mood_info_font_size',11),
            color=s.get('video_mood_info_color','#ffffff'),bg=s.get('video_mood_info_bg','#000000'),
            opacity=s.get('video_mood_info_opacity',75)/100,radius=s.get('video_mood_info_radius',2),
            padding=s.get('video_mood_info_padding',4),position=s.get('video_mood_info_position','top_right'),
            margin_x=s.get('video_mood_info_margin_x',4),margin_y=s.get('video_mood_info_margin_y',4))
        self.moodboard.update()
        self._sync_background()
        if self._analysis is not None:
            self._analysis.apply_settings(s)
        self.viewer.mipmaps = bool(get("video_mipmaps"))
        self.viewer.set_effects(self._effects())
        self.setStyleSheet(f"#VideoPane {{ background: {_color(s, 'video_bg_color')}; }}")
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(_color(s, "video_bg_color")))
        self.setPalette(palette)
        family = get("video_info_font_family") or ""
        resolve = HOOKS.get("resolve_font")
        if family and resolve is not None:
            try:
                family = resolve(family)
            except Exception:                                # noqa: BLE001
                pass
        self.overlay.set_look({
            "opacity": get("video_info_opacity"), "bg": _color(s, "video_info_bg"), "font": family,
            "font_size": get("video_info_font_size"), "color": _color(s, "video_info_font_color"),
            "label_color": _color(s, "video_info_label_color"), "title_color": _color(s, "video_info_title_color"),
            "corner": get("video_info_corner"), "margin_x": get("video_info_margin_x"),
            "margin_y": get("video_info_margin_y"), "line_spacing": get("video_info_line_spacing"),
            "padding": get("video_info_padding"), "radius": get("video_info_radius"), "width": get("video_info_width"),
            "compact": get("video_info_compact"), "titles": get("video_info_titles")})
        fg = _color(s, "video_controls_color")
        self.controls.bg = QColor(_color(s, "video_controls_bg"))
        self.controls.setFixedHeight(int(get("video_controls_height")))
        for button in self.buttons.values():
            button.color = QColor(fg)
            button.accent = QColor(_color(s, "video_timeline_selection"))
            button.update()
        for label in (self.count_label, self.tc_label, self.zoom_label, self.volume_label):
            label.setStyleSheet(f"color: {fg}; background: transparent;")
        self.frame_field.setStyleSheet(f"color: {fg};")
        self.controls.update()
        show = get("video_time_display")
        self.unit_select.setValue("Secondes" if show == "seconds" else "Images")
        self.timeline.set_look({
            "height": get("video_timeline_height"), "tick": get("video_timeline_tick"),
            "density": get("video_timeline_density"), "show_frames": show in ("frames", "both"),
            "show_tc": show in ("timecode", "both"), "seconds": show == "seconds",
            "zoom_step": get("video_timeline_zoom_step"),
            "zoom_cursor": get("video_timeline_zoom_cursor"), "playhead": _color(s, "video_timeline_playhead"),
            "thumbs": bool(get("video_timeline_thumbs")), "thumb_height": get("video_timeline_thumb_height"),
            "selection": _color(s, "video_timeline_selection"), "in_color": _color(s, "video_timeline_in"),
            "out_color": _color(s, "video_timeline_out"), "bg": _color(s, "video_timeline_bg"),
            "ruler": _color(s, "video_timeline_ruler"), "text": _color(s, "video_timeline_text")})
        self.cache.set_limit(int(get("video_cache_mb")) << 20)
        if self.loader is not None:
            self.loader.set_window(int(get("video_prefetch_ahead")), int(get("video_prefetch_behind")))
        if self.source is not None:
            self._refresh_pipeline()
        self.message.setStyleSheet(f"color: {fg}; background: transparent; font-size: 14px;")
        self._update_info()

    def _status(self, text: str):
        hook = HOOKS.get("status")
        if hook is not None:
            try:
                hook(text)
            except Exception:                                # noqa: BLE001
                pass

    def _save_state(self, key: str, value):
        hook = HOOKS.get("save_state")
        if hook is not None:
            try:
                hook(key, value)
            except Exception:                                # noqa: BLE001
                pass

    def _sync_background(self):
        key = 'video_moodboard_bg_color' if self._moodboard_on else 'video_bg_color'
        value = QColor(self._settings.get(key, '#202020')).red()
        presets = [0,64,128,191,10]
        for widget in (self.background_select,self.background_slider,self.background_value):
            widget.blockSignals(True)
        self.background_select.setCurrentIndex(presets.index(value) if value in presets else 5)
        self.background_slider.setValue(value)
        self.background_value.setValue(value)
        for widget in (self.background_select,self.background_slider,self.background_value):
            widget.blockSignals(False)

    def _background_preset(self, index):
        if index < 5:
            self._background_changed([0,64,128,191,10][index])

    def _background_changed(self, value):
        color = QColor(value,value,value)
        key = 'video_moodboard_bg_color' if self._moodboard_on else 'video_bg_color'
        self._settings[key] = color.name()
        if self._moodboard_on:
            self.moodboard.bg = color
            self.moodboard.update()
        else:
            self.viewer.bg = color
            self.viewer.update()
        if self._analysis is not None:
            self._analysis.setStyleSheet(f'background:{color.name()};')
        self._sync_background()
        self._background_pending[key] = color.name()
        self._background_save_timer.start()

    def _save_background(self):
        pending, self._background_pending = self._background_pending, {}
        write = HOOKS.get('write_setting')
        for key,value in pending.items():
            if write is not None:
                write(key,value)

    def _open_color_analysis(self, index):
        self.pause()
        if self._analysis is None:
            from fm_video.analysis import ColorAnalysis
            self._analysis = ColorAnalysis(self.content)
            self._analysis.back.connect(self._close_color_analysis)
            self._analysis.settingsChanged.connect(self._analysis_setting)
            self.content_layout.addWidget(self._analysis)
        self._analysis.apply_settings(self._settings)
        self._analysis.image.natural_width = max(1,int(getattr(self.source,'width',1500)))
        self._analysis_index = index
        self._analysis.setStyleSheet(f'background:{self.moodboard.bg.name()};')
        self.content_layout.setCurrentWidget(self._analysis)
        image = self.moodboard.detail_pixmaps.get(index) or self.moodboard.pixmaps.get(index)
        if image is not None:
            self._analysis.show_image(image.toImage(), f'Image {index}')
        if self._mood_thumbs:
            self._mood_thumbs.set_height(1500)
            self._mood_thumbs.request([index])

    def _close_color_analysis(self):
        self._analysis_index = None
        self._analysis.stop()
        if self._mood_thumbs is not None:
            self._mood_thumbs.set_height(max(16,self._moodboard_cell.height()))
        self.content_layout.setCurrentWidget(self.moodboard)

    def _analysis_setting(self,key,value):
        if self._settings.get(key) == value:
            return
        self._settings[key] = value
        self._background_pending[key] = value
        self._background_save_timer.start()

    # -- ouverture --

    def open(self, path) -> bool:
        """Ouvre un média (vidéo, image d'une séquence, image seule). False + message si illisible."""
        path = Path(path)
        try:
            source = vmedia.open_media(path, self._settings)
        except vmedia.MediaError as exc:
            self._show_message(str(exc))
            self._status(str(exc))
            return False
        except Exception as exc:                             # noqa: BLE001
            self._show_message(f"Média illisible : {exc}")
            return False
        self._close_source()
        self.path = path
        self.source = source
        if self._moodboard_on:
            self.moodboard.set_grid([], 1, 1, QSize(1, 1), 0)
            self._moodboard_items.clear()
        self.viewer.media_ext = path.suffix.lower()
        self._engine = self._engine_for(source)
        workers = int(_setting(self._settings, "video_workers"))
        self.loader = FrameLoader(source, self.cache, workers, int(_setting(self._settings, "video_prefetch_ahead")),
                                  int(_setting(self._settings, "video_prefetch_behind")), self)
        self.loader.frameReady.connect(self._on_frame_ready)
        self.loader.failed.connect(self._on_frame_failed)
        self.loader.indexReady.connect(self._on_index_ready)
        missing = []
        if getattr(source, "sequence", None) is not None:
            first = source.sequence.first
            missing = [n - first for n in source.sequence.missing()]
        self.timeline.set_media(source.frame_count, source.first_number, source.fps, source.timecode_start, missing)
        self.timeline.set_time_mapping(source.time_of, source.index_at_time)
        self._sync_media_controls()
        if _setting(self._settings, "video_grade_on_change") == "reset":
            self._grade = dict(vcolor.DEFAULT_GRADE)
            self._reopen_grade_windows()          # valeurs (et contours « modifié ») de la fenêtre à jour
        self._lut = None
        if _setting(self._settings, "video_lut_auto") and _setting(self._settings, "video_lut_default"):
            self._load_lut(_setting(self._settings, "video_lut_default"), quiet=True)
        self._refresh_pipeline()
        self._start_thumbs(source)
        if self._moodboard_on:
            self._load_moodboard()
        if self._engine == "vlc":
            self._open_vlc(source)
        else:
            self._setup_audio()
        start = 0
        if getattr(source, "sequence", None) is not None and path.exists():
            parts = vmedia.split_frame_name(path.name)
            if parts:
                start = max(0, int(parts[1]) - source.first_number)
        if not _setting(self._settings, "video_reset_position"):
            start = self._positions.get(str(path), start)
        self._message = ""
        self.message.hide()
        self._shown = -1
        self.go(start)
        self._initial_zoom()
        self._set_info_visible(bool(_setting(self._settings, "video_info_enabled")), user=False)
        if bool(_setting(self._settings, "video_scopes")) != self.scopes.isVisible():
            self.toggle_scopes()                  # scopes retrouvés comme on les a laissés
        if _setting(self._settings, "video_autoplay") and source.frame_count > 1:
            # Une seule demande de lecture (play() ne fait rien si la lecture est déjà en cours).
            QTimer.singleShot(0, lambda src=source: self.play() if self.source is src else None)
        self.stateChanged.emit()
        return True

    def _close_source(self):
        self.pause()
        self._mood_adjust_timer.stop()
        self._mood_adjust_pending = None
        self._mood_edit_slot = None
        self._mood_undo.clear()
        self._mood_selections.clear()
        self._mood_edit_history.clear()
        self._analysis_index = None
        if self._analysis is not None:
            self._analysis.stop()
            if self.content_layout.currentWidget() == self._analysis:
                self.content_layout.setCurrentWidget(self.moodboard if self._moodboard_on else self.viewer)
        if self._mood_thumbs is not None:
            self._mood_thumbs.stop()
            try:
                self._mood_thumbs.ready.disconnect(self._mood_thumb_ready)
            except (RuntimeError, TypeError):
                pass
            self._mood_thumbs = None
        if self.source is not None and self.path is not None:
            self._positions[str(self.path)] = self.index
        if self.loader is not None:
            self.loader.stop()
            try:
                self.loader.frameReady.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.loader.deleteLater()
            self.loader = None
        if self.source is not None:
            self.cache.drop_source(self.source)
        self.source = None
        if self._audio is not None:
            self._audio.stop()
            self._audio.setSource(QUrl())
        if self._vlc is not None:
            self._vlc.stop()
        self._vlc_anchor = None
        self._vlc_paused_at = None
        if self._thumbs is not None:
            self._thumbs.stop()
            self._thumbs = None

    def close_media(self):
        self._close_source()
        for window in list(self._windows.values()):
            try:
                window.close()
            except RuntimeError:
                pass
        self._windows.clear()

    def _sync_media_controls(self):
        src = self.source
        layers = src.layers if src is not None else [""]
        self.layer_select.setOptions([name or "RVBA" for name in layers])
        self.layer_select.setValue(src.layer or "RVBA" if src else "")
        self.layer_select.setVisible(len(layers) > 1)
        is_seq = src is not None and src.kind == "sequence"
        self.fps_select.setVisible(is_seq)
        if is_seq:
            match = next((label for value, label in vmedia.FPS_CHOICES
                          if vmedia.parse_fps(value) == src.fps), None)
            if match:
                self.fps_select.setValue(match)
        has_audio = bool(src is not None and src.has_audio)
        self.buttons["sound"].setVisible(has_audio)
        self.volume.setVisible(has_audio)
        self.volume_label.setVisible(has_audio)
        self.buttons["loop"].set_checked(self._loop)
        self.count_label.setText(f"/ {src.number_of(src.frame_count - 1)}" if src else "")
        self.channel_select.setValue({"rgb": "RVB", "r": "R", "g": "V", "b": "B", "a": "Alpha",
                                      "luma": "Luma"}.get(self._channel, "RVB"))

    def toggle_moodboard(self):
        """Bascule dans le même panneau entre le lecteur en pause et les images extraites du média."""
        self._analysis_index = None
        self._set_zone_mode(False)
        if not self._moodboard_on:
            self.pause()
            self._moodboard_on = True
            self.buttons["moodboard"].set_checked(True)
            self.content_layout.setCurrentWidget(self.moodboard)
            self.timeline.hide()
            self.mood_size_label.show()
            self.mood_size_slider.show()
            self.mood_gap_label.show()
            self.mood_gap_slider.show()
            self._load_moodboard()
        else:
            self.pause()
            self._moodboard_on = False
            self._mood_refresh_timer.stop()
            self.buttons["moodboard"].set_checked(False)
            self.content_layout.setCurrentWidget(self.viewer)
            self.timeline.show()
            self.mood_size_label.hide()
            self.mood_size_slider.hide()
            self.mood_gap_label.hide()
            self.mood_gap_slider.hide()
            self.viewer.setFocus()
        self._sync_background()
        self.stateChanged.emit()

    def _load_moodboard(self):
        self._mood_adjust_timer.stop()
        self._mood_adjust_pending = None
        self._mood_edit_slot = None
        self._mood_edit_history.clear()
        self._mood_undo.clear()
        source = self.source
        if source is None or source.frame_count <= 0:
            self._moodboard_paths = []
            self.moodboard.set_grid([], 1, 1, QSize(1, 1), 0)
            self._moodboard_items.clear()
            return
        self._layout_moodboard_grid()
        count = min(500, source.frame_count, max(1, self.moodboard_grid[0] * self.moodboard_grid[1]))
        indices = ([0] if count == 1 else [round(i * (source.frame_count - 1) / (count - 1))
                                           for i in range(count)])
        self._moodboard_paths = indices
        self._sync_mood_times()
        self._moodboard_positions = {index: n for n, index in enumerate(indices)}
        self.moodboard.setToolTip(f"{len(indices)} images extraites de la vidéo")
        self._moodboard_items = {index: True for index in indices}
        self.moodboard.set_grid(indices, *self.moodboard_grid, self._moodboard_cell,
                                self.mood_gap_slider.value())
        self._sync_moodboard_selection()
        if self._mood_thumbs is None:
            from fm_video.thumbs import ThumbnailLoader
            self._mood_thumbs = ThumbnailLoader(source.path if source.kind == "video" else self.path,
                                                self._settings, self, limit=40, max_height=4096,
                                                exact_video=False, workers=1,
                                                shared_index=getattr(source, "_index", None),
                                                moodboard_proxies=True)
            self._mood_thumbs.set_look(self._pipeline, vcolor.ViewState(dict(vcolor.DEFAULT_GRADE)))
            self._mood_thumbs.ready.connect(self._mood_thumb_ready)
            self._mood_thumbs.ready.connect(self._mood_capture_thumb)
            self._mood_thumbs.selectionReady.connect(self._restore_mood_selection)
            self._mood_thumbs.edited.connect(self._mood_frame_edited)
            self._mood_thumbs.editFailed.connect(self._mood_edit_failed)
        self._mood_thumbs.set_playing(False)
        self._mood_thumbs.set_height(max(16, self._moodboard_cell.height()))
        self._mood_thumbs.set_moodboard(indices, (*self.moodboard_grid,
            self._moodboard_cell.width(), self._moodboard_cell.height(), self.mood_gap_slider.value()))
        self._mood_thumbs.request(indices)
        self.moodboard._request_detail()

    def _refresh_moodboard_thumbnails(self):
        if not self._moodboard_on:
            return
        self.moodboard.pixmaps.clear()
        self.moodboard.detail_pixmaps.clear()
        self._load_moodboard()

    def _mood_thumb_ready(self, index: int, image):
        if index==self._mood_edit_slot or index in self._mood_edit_history:
            return
        if self._analysis is not None and self._analysis_index == index and not image.isNull():
            self._analysis.show_image(image, f'Image {index}')
        if int(index) in self._moodboard_items and not image.isNull():
            target = self._moodboard_cell
            scaled = image.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x, y = max(0, (scaled.width() - target.width()) // 2), max(0, (scaled.height() - target.height()) // 2)
            pixmap = QPixmap.fromImage(image)
            if image.height() > target.height() * 1.35:
                self.moodboard.set_detail_pixmap(index, pixmap)
            else:
                self.moodboard.set_pixmap(index, QPixmap.fromImage(
                    scaled.copy(x, y, target.width(), target.height())))

    def _queue_moodboard_detail(self, indices, height):
        if not self._moodboard_on or not self._mood_thumbs:
            return
        self._mood_detail_indices = list(indices)
        self._mood_detail_height = min(4096, max(16, int(height)))
        self._mood_detail_timer.start()

    def _restore_mood_selection(self,selection):
        self._mood_selections = dict(selection)
        self._sync_mood_times()

    def _mood_edit_failed(self,slot,message):
        old = self._mood_edit_history.pop(slot,self._mood_edit_old if slot==self._mood_edit_slot else None)
        if old is not None:
            self._mood_selections[slot] = old
        if slot==self._mood_edit_slot:
            self._mood_edit_slot = self._mood_edit_old = None
        self._sync_mood_times()
        self._status('Moodboard : '+message)
        if self._mood_thumbs is not None:
            self._mood_thumbs.request([slot])

    def _sync_mood_times(self):
        source = self.source
        if source is None:
            return
        from fm_video.moodboard_timing import timestamp
        exact = source.kind!='video' or source.index_ready
        self.moodboard.frame_slider.setEnabled(source.kind=='video' and exact)
        self.moodboard.frame_slider.setToolTip('Ajuster cette image entre ses voisines' if exact else 'Indexation des timestamps réels en cours…')
        labels = {}
        indices = self._moodboard_paths
        mode = self._settings.get('video_mood_info_format','clock')
        for n,slot in enumerate(indices):
            frame = self._mood_selections.get(slot,slot)
            seconds = source.time_of(frame)
            interval = (source.time_of(self._mood_selections.get(indices[n+1],indices[n+1]))-seconds
                        if n+1<len(indices) else None)
            lines = []
            if self._settings.get('video_mood_info_timestamp',True):
                text = f'{frame} fr' if mode=='frames' else f'{seconds:.3f} s' if mode=='seconds' else timestamp(seconds)
                lines.append(('' if exact else '~ ')+text)
            if self._settings.get('video_mood_info_interval',True):
                if interval is None:
                    lines.append('Δ — dernière image')
                else:
                    text = (f'{self._mood_selections.get(indices[n+1],indices[n+1])-frame} fr' if mode=='frames'
                            else f'{interval:.3f} s' if mode=='seconds' else timestamp(interval))
                    lines.append('Δ '+text)
            labels[slot] = lines
        self.moodboard.time_labels = labels

    def _adjust_mood_frame(self,slot,amount,final):
        source = self.source
        if source is None or self._mood_thumbs is None or source.kind!='video' or not source.index_ready:
            return
        if self._mood_edit_slot!=slot:
            self._mood_edit_slot = slot
            self._mood_edit_old = self._mood_selections.get(slot,slot)
        from fm_video.moodboard_timing import adjusted_frame
        frame = adjusted_frame(source,self._moodboard_paths,self._mood_selections,slot,self._mood_edit_old,amount)
        self._mood_adjust_pending = (slot,frame,final)
        if final:
            self._mood_edit_history[slot] = self._mood_edit_old
            self._mood_adjust_timer.stop()
            self._send_mood_adjust()
        elif not self._mood_adjust_timer.isActive():
            self._mood_adjust_timer.start()

    def _send_mood_adjust(self):
        pending,self._mood_adjust_pending = self._mood_adjust_pending,None
        if pending and self._mood_thumbs is not None:
            self._mood_thumbs.edit_frame(*pending)

    def _replay_mood_frame(self,slot,frame):
        if self._mood_thumbs is not None:
            self._mood_edit_slot = slot
            self._mood_edit_old = None
            self._mood_edit_history[slot] = None
            self._mood_thumbs.edit_frame(slot,frame,True)

    def _mood_frame_edited(self,slot,frame,image,final):
        old = self._mood_edit_history.pop(slot,None) if final else None
        self._mood_selections[slot] = frame
        self._sync_mood_times()
        # L'identifiant de case reste stable ; seule sa texture est remplacée.
        self.moodboard.set_detail_pixmap(slot,QPixmap.fromImage(image))
        self.moodboard.set_pixmap(slot,QPixmap.fromImage(image))
        position = self._moodboard_positions.get(slot,0)
        if position>0:
            previous = self._moodboard_paths[position-1]
            self.moodboard.update(self.moodboard.slot_rect(previous).toAlignedRect())
        if final:
            if self._mood_edit_slot==slot:
                self._mood_edit_slot = None
                self._mood_edit_old = None
            if old is not None and old!=frame:
                self._mood_undo.push(_MoodFrameCommand(self._replay_mood_frame,slot,old,frame))

    def _request_moodboard_detail(self):
        if not self._moodboard_on or not self._mood_thumbs or not self._mood_detail_indices:
            return
        if self._mood_detail_height <= self._moodboard_cell.height() * 1.35:
            return
        self._mood_thumbs.set_height(self._mood_detail_height)
        self._mood_thumbs.request(self._mood_detail_indices)

    def _sync_moodboard_selection(self):
        if self.source is None:
            return
        best = min(self._moodboard_paths, key=lambda i: abs(self._mood_selections.get(i,i) - self.index), default=None)
        if best is not None:
            self.moodboard.set_current(best)

    def _moodboard_clicked(self, index):
        self.go(int(self._mood_selections.get(index,index)))
        self._sync_moodboard_selection()

    def _moodboard_double_clicked(self, index):
        self.toggle_moodboard()
        self.go(int(self._mood_selections.get(index,index)))
        self.play()

    def _moodboard_zone_selected(self, rect):
        self._set_zone_mode(False)
        self._snapshot_moodboard(rect)

    def _set_moodboard_size(self, size: int):
        size = int(size)
        if size == self._mood_size:
            return
        self._mood_size = size
        self.mood_size_label.setText(f"Taille : {size} px")
        if self._moodboard_on:
            self._mood_refresh_timer.start()

    def _set_moodboard_gap(self, gap: int):
        self.mood_gap_label.setText(f"Marge : {int(gap)} px")
        if self._moodboard_on:
            self._mood_refresh_timer.start()

    def _layout_moodboard_grid(self):
        gap = self.mood_gap_slider.value()
        vw, vh = max(1, self.moodboard.width()), max(1, self.moodboard.height())
        source = self.source
        aspect = (float(source.width) / max(1, float(source.height))
                  if source is not None and source.width and source.height else 16 / 9)
        cols = max(1, int((vw + gap) // max(1, self._mood_size + gap)))
        rows = max(1, int((vh + gap) // max(1.0, self._mood_size / aspect + gap)))
        cell_w = max(1, (vw - gap * (cols + 1)) // cols)
        cell_h = max(1, (vh - gap * (rows + 1)) // rows)
        width = max(1, min(cell_w, round(cell_h * aspect)))
        height = max(1, round(width / aspect))
        cell_w, cell_h = width, height
        self.moodboard_grid = (cols, rows)
        self._moodboard_cell = QSize(cell_w, cell_h)
        self.moodboard.set_grid(self._moodboard_paths, cols, rows, self._moodboard_cell, gap)

    def _show_message(self, text: str):
        self._message = text
        self.message.setText(text)
        self.message.setGeometry(self.viewer.rect().adjusted(40, 40, -40, -40))
        self.message.setVisible(bool(text))
        self.message.raise_()

    # -- colorimétrie --

    def _media_kind(self) -> str:
        if self.source is None:
            return "video"
        if self.source.kind == "video":
            return "video"
        ext = self.path.suffix.lower() if self.path else ""
        if ext in (".exr", ".hdr"):
            return "exr"
        spec = getattr(self.source, "spec", None)
        try:
            import OpenImageIO as oiio
            if spec is not None and spec.format.basetype in (oiio.HALF, oiio.FLOAT, oiio.DOUBLE):
                return "float"
        except Exception:                                    # noqa: BLE001
            pass
        return "int"

    def input_space(self) -> str:
        kind = self._media_kind()
        override = self._input_override.get(str(self.path)) if self.path else None
        if override:
            return override
        return str(_setting(self._settings, f"video_input_{kind}") or "")

    def _refresh_pipeline(self):
        if not vcolor.ocio_available():
            self._pipeline = None
            self._push_state()
            return
        kind = self._media_kind()
        view = _setting(self._settings, "video_view_video" if kind == "video" else "video_view_image")
        setup = vcolor.OcioSetup(str(_setting(self._settings, "video_ocio_config") or ""), self.input_space(),
                                 str(_setting(self._settings, "video_display") or ""), str(view or ""))
        key = (setup.config_path, setup.input_space, setup.display, setup.view)
        if key != self._pipeline_key:
            try:
                self._pipeline = vcolor.ColorPipeline(setup)
            except Exception as exc:                         # noqa: BLE001 - configuration invalide : sans OCIO
                self._pipeline = None
                self._status(f"OCIO : {exc}")
            self._pipeline_key = key
            self.viewer.set_pipeline(self._pipeline)
        self._push_state()

    def view_state(self, display: bool = True) -> vcolor.ViewState:
        """État de couleur. `display` : tel qu'affiché, avec les fenêtres en « avant » (icône avant / après)
        contournées ; l'export demande les vraies corrections (`display=False`)."""
        grade = self.display_grade() if display else dict(self._grade)
        return vcolor.ViewState(grade, self._grade_on, self._lut, self._lut_position, self._lut_mix,
                                self._channel, self._clipping, str(_setting(self._settings, "video_alpha_mode")))

    def display_grade(self) -> dict:
        """Corrections affichées : celles d'une fenêtre en « avant » remises à leur valeur d'ORIGINE (aucun autre
        maillon touché : espace d'entrée et affichage OCIO, LUT, niveaux d'une autre fenêtre). Rien n'est
        recalculé : les mêmes uniformes du shader reçoivent d'autres valeurs (bascule immédiate, lecture
        comprise)."""
        grade = dict(self._grade)
        for which, rows in (("grade_main", GRADE_MAIN), ("grade_channels", GRADE_CHANNELS)):
            if which in self._bypass:
                for row in rows:
                    grade[row[0]] = vcolor.DEFAULT_GRADE[row[0]]
        return grade

    def set_bypass(self, which: str, on: bool):
        """Icône avant / après d'une fenêtre de corrections : ses corrections contournées (True) ou rendues."""
        if on:
            self._bypass.add(which)
        else:
            self._bypass.discard(which)
        button = self._bypass_buttons.get(which)
        if button is not None:
            try:
                button.set_checked(on)
                button.setToolTip(self._bypass_tip(which, on))
            except RuntimeError:
                self._bypass_buttons.pop(which, None)
        self._push_state()

    @staticmethod
    def _bypass_tip(which: str, on: bool) -> str:
        what = "corrections de cette fenêtre" if which == "grade_main" else "corrections par canal et niveaux"
        return (f"AVANT : {what} coupées (réglages gardés) — clic : après" if on
                else f"APRÈS : {what} appliquées — clic : voir l'image avant elles")

    def toggle_scopes(self):
        """Scopes (S) : calculés en fond sur l'image affichée, seulement tant que le panneau est visible."""
        visible = not self.scopes.isVisible()
        self.buttons["scopes"].set_checked(visible)
        if visible:
            if self._scope_worker is None:
                from fm_video.scopes import ScopeWorker
                self._scope_worker = ScopeWorker(self)
                self._scope_worker.ready.connect(self.scopes.set_result)
            self.scopes.reposition()
            self.scopes.show()
            self.scopes.raise_()
            self._request_scopes()
        else:
            self.scopes.hide()
        self._save_state("video_scopes", visible)

    def _request_scopes(self):
        if self._scope_worker is not None and self.scopes.isVisible() and self.viewer.frame is not None:
            now = time.perf_counter()
            if self._playing and now - self._scope_at < 0.15:
                return                              # lecture : ~6 par seconde suffisent (le calcul suit)
            self._scope_at = now
            self._scope_worker.request(self._stable_frame(), self._pipeline, self.view_state())

    # -- captures (PNG) --

    def _stable_frame(self):
        """Image affichée, sûre pour un calcul en fond : le tampon de VLC est réécrit pendant la lecture, ses plans
        sont recopiés."""
        frame = self.viewer.frame
        if frame is not None and frame.yuv is not None and self._engine == "vlc" and self._playing:
            y = frame.yuv
            frame = vmedia.Frame(frame.index, None, yuv=vmedia.YuvImage([pl.copy() for pl in y.planes], y.width,
                                                                        y.height, y.sx, y.sy, y.bits, y.kr, y.kb,
                                                                        y.full_range, y.chroma_shift))
        return frame

    def _snapshot(self, region=None):
        if self._moodboard_on:
            self._snapshot_moodboard(region)
            return
        frame = self._stable_frame()
        if self.source is None or frame is None or not frame.has_image:
            return
        from fm_video import snapshot as vsnap
        if self._snapshots is None:
            self._snapshots = vsnap.SnapshotSaver(self)
            self._snapshots.done.connect(self._snapshot_done)
        name = vsnap.media_name(self.source)
        base = (vsnap.ZONE_PREFIX + name) if region is not None else name
        self._snapshots.save(frame, self._pipeline, self.view_state(), vsnap.snapshot_dir(self.source), base, region)

    def take_snapshot(self):
        """Capture l'image vidéo ou la mosaïque affichée."""
        self._snapshot()

    def _snapshot_moodboard(self, region=None):
        if self.source is None:
            return
        from fm_video import snapshot as vsnap
        if self._snapshots is None:
            self._snapshots = vsnap.SnapshotSaver(self)
            self._snapshots.done.connect(self._snapshot_done)
        name = vsnap.media_name(self.source)
        base = f"z_mood_{name}" + ("_crop" if region is not None else "")
        folder = vsnap.snapshot_dir(self.source)
        if region is not None:
            pixmap = self.moodboard.grab().copy(region)
            self._snapshots.save_image(pixmap.toImage(), folder, base)
            return
        if self._mood_capture is not None:
            self._finish_moodboard_capture()
        board = self.moodboard.board_size()
        pixels = max(1, board.width() * board.height())
        scale = max(1.0, float(self.moodboard.scale))
        scale = min(scale, 12000 / max(1, board.width()), 12000 / max(1, board.height()),
                    math.sqrt(60_000_000 / pixels))
        width, height = max(1, round(board.width() * scale)), max(1, round(board.height() * scale))
        output = QImage(width, height, QImage.Format_RGB32)
        output.fill(QColor("#202020"))
        # Les aperçus actuels remplissent tout le rendu immédiatement ; ils sont ensuite remplacés case par case
        # par les décodages pleine définition, sans figer l'interface.
        self._draw_moodboard_capture_tiles(output, scale, self.moodboard.pixmaps)
        pending = set(self._moodboard_paths)
        self._mood_capture = {"image": output, "scale": scale, "remaining": pending,
                              "folder": folder, "base": base}
        self._mood_capture_timer.start()
        target_height = min(4096, max(self._moodboard_cell.height(), round(self._moodboard_cell.height() * scale)))
        self._mood_thumbs.set_height(target_height)
        self._mood_thumbs.request(self._moodboard_paths)
        if not pending:
            self._finish_moodboard_capture()

    def _draw_moodboard_capture_tiles(self, output, scale, images):
        painter = QPainter(output)
        for index, image in images.items():
            if image is None or image.isNull():
                continue
            if isinstance(image, QPixmap):
                image = image.toImage()
            n = self._moodboard_positions.get(index)
            if n is None:
                continue
            row, col = divmod(n, self.moodboard.columns)
            rect = QRectF((self.moodboard.gap + col * (self._moodboard_cell.width() + self.moodboard.gap)) * scale,
                          (self.moodboard.gap + row * (self._moodboard_cell.height() + self.moodboard.gap)) * scale,
                          self._moodboard_cell.width() * scale, self._moodboard_cell.height() * scale)
            painter.drawImage(rect, image)
        painter.end()

    def _mood_capture_thumb(self, index, image):
        capture = self._mood_capture
        if capture is None or int(index) not in capture["remaining"] or image.isNull():
            return
        self._draw_moodboard_capture_tiles(capture["image"], capture["scale"], {int(index): image})
        capture["remaining"].discard(int(index))
        if not capture["remaining"]:
            self._finish_moodboard_capture()

    def _finish_moodboard_capture(self):
        capture, self._mood_capture = self._mood_capture, None
        self._mood_capture_timer.stop()
        if capture is None:
            return
        painter = QPainter(capture["image"])
        n = self._moodboard_paths.index(self.index) if self.index in self._moodboard_paths else -1
        if n >= 0:
            row, col = divmod(n, self.moodboard.columns)
            scale = capture["scale"]
            rect = QRectF((self.moodboard.gap + col * (self._moodboard_cell.width() + self.moodboard.gap)) * scale,
                          (self.moodboard.gap + row * (self._moodboard_cell.height() + self.moodboard.gap)) * scale,
                          self._moodboard_cell.width() * scale, self._moodboard_cell.height() * scale)
            painter.setPen(QPen(QColor("#ff3030"), max(2, 3 * scale)))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.end()
        if capture["remaining"]:
            self._status(f"Capture du moodboard : {len(capture['remaining'])} image(s) gardée(s) en aperçu")
        self._snapshots.save_image(capture["image"], capture["folder"], capture["base"])

    def toggle_zone_capture(self):
        """Le prochain rectangle est capturé dans la vue active."""
        active = self.moodboard if self._moodboard_on else self.viewer
        self._set_zone_mode(not (active._zone_mode if self._moodboard_on else self.viewer.region_mode()))

    def _set_zone_mode(self, on: bool):
        self.viewer.set_region_mode(on and not self._moodboard_on)
        self.moodboard.set_region_mode(on and self._moodboard_on)
        self.buttons["zone"].set_checked(on)

    def _active_view(self):
        return self.moodboard if self._moodboard_on else self.viewer

    def _active_fit(self):
        if self._moodboard_on:
            self._layout_moodboard_grid()
            self.moodboard.fit()
        else:
            self.viewer.fit()

    def _active_recenter(self):
        self._active_view().recenter()

    def _active_one_to_one(self):
        self._active_view().one_to_one()

    def _on_moodboard_zoom(self, scale):
        self.zoom_label.setText(f"{scale * 100:.0f} %")
        self.zoom_label.setToolTip("Zoom de la mosaïque")

    def _zone_selected(self, region):
        self._set_zone_mode(False)
        self._snapshot(region)

    def _snapshot_done(self, path: str, error: str):
        if error:
            self._status(f"Capture impossible : {error}")
            self._show_message(f"Capture impossible : {error}")
            QTimer.singleShot(3000, lambda: self._show_message(""))
            return
        self.last_snapshot = path
        self._status(f"Capture enregistrée : {path}")

    def _push_state(self):
        self.viewer.set_view_state(self.view_state())
        self._request_scopes()
        self.viewer.set_compare(self._compare)
        self.buttons["reset"].setVisible(vcolor.grade_active(self._grade) or self._lut is not None)
        self.buttons["compare"].set_checked(self._compare != "off")
        self._update_info()
        self.stateChanged.emit()

    def set_grade(self, grade: dict, save: bool = True):
        self._grade = {**vcolor.DEFAULT_GRADE, **{k: float(v) for k, v in grade.items() if k in vcolor.DEFAULT_GRADE}}
        self._push_state()
        if save:
            self._save_state("video_grade", {k: v for k, v in self._grade.items() if v != vcolor.DEFAULT_GRADE[k]})

    def reset_grade(self):
        self.set_grade(dict(vcolor.DEFAULT_GRADE))
        self._lut = None
        self._compare = "off"
        self._push_state()
        self._reopen_grade_windows()

    def _reopen_grade_windows(self):
        """Fenêtres de corrections ouvertes refaites sur les valeurs en cours (preset, réinitialisation, média)."""
        for name in ("grade_main", "grade_channels"):
            window = self._windows.get(name)
            if window is not None:
                try:
                    window.close()
                except RuntimeError:
                    pass
                self._windows.pop(name, None)
                self.open_grade_window(name)

    def _load_lut(self, path, quiet=False) -> bool:
        try:
            self._lut = vcolor.load_cube(path)
        except vcolor.LutError as exc:
            self._lut = None
            if not quiet:
                self._show_message(str(exc))
                QTimer.singleShot(3000, lambda: self._show_message(""))
            self._status(str(exc))
            return False
        self._push_state()
        return True

    def _cycle_compare(self):
        self._compare = {"off": "split", "split": "before", "before": "off"}[self._compare]
        self._push_state()

    def _channel_chosen(self, label: str):
        self._channel = {"RVB": "rgb", "R": "r", "V": "g", "B": "b", "Alpha": "a", "Luma": "luma"}.get(label, "rgb")
        self._push_state()

    def _layer_chosen(self, label: str):
        if self.source is None:
            return
        layer = "" if label == "RVBA" else label
        self.source.set_layer(layer)
        self._shown = -1
        self.go(self.index)

    def _fps_chosen(self, label: str):
        if self.source is None or self.source.kind != "sequence":
            return
        value = next((v for v, lab in vmedia.FPS_CHOICES if lab == label), "24")
        self.source.fps = vmedia.parse_fps(value)
        self.timeline.fps = self.source.fps
        if self._playing:
            self._clock = (time.perf_counter(), self.index)
        self._update_info()

    # -- fenêtres « à la volée » (corrections, export) --

    def open_grade_window(self, which: str = "grade_main"):
        """Corrections (Changement de style à la volée) : appliquées en direct, sur toutes les images."""
        from settings_quick_style import QuickStyleWindow
        import settings_window_v2 as v2
        old = self._windows.get(which)
        if old is not None:
            try:
                old.raise_()
                old.activateWindow()
                return old
            except RuntimeError:
                pass
        rows = GRADE_MAIN if which == "grade_main" else GRADE_CHANNELS
        values = {}
        specs = []
        if which == "grade_main":
            specs += self._color_rows(v2, values)
        for key, label, low, high, scale, unit in rows:
            values[f"vg_{key}"] = int(round(self._grade.get(key, vcolor.DEFAULT_GRADE[key]) * scale))
            specs.append(v2.Spec(f"vg_{key}", label, "slider", values[f"vg_{key}"],
                                 {"min": low, "max": high, "unit": unit, "scale": scale, "width": 180, "box": 70,
                                  "reset": int(round(vcolor.DEFAULT_GRADE[key] * scale))}))
        title = "Corrections colorimétriques" if which == "grade_main" else "Corrections par canal et niveaux"
        window = QuickStyleWindow(f"Module vidéo : {title}", specs, values, title=title,
                                  settings=HOOKS["settings"]() or None, parent=self.window())
        window.styleChanged.connect(lambda v, w=which: self._on_grade_window(v, w))
        window.destroyed.connect(lambda _o=None, n=which: self._grade_window_closed(n))
        self._add_bypass_button(window, which)
        self._windows[which] = window
        window.show()
        return window

    def _add_bypass_button(self, window, which: str):
        """Petite icône avant / après dans la barre de titre de la fenêtre, à gauche de la croix (glyphe des
        boutons du module, couleurs de sa barre de contrôle)."""
        bar = getattr(window, "titlebar", None)
        layout = bar.layout() if bar is not None else None
        if layout is None:
            return
        button = _CtlButton("compare", self._bypass_tip(which, which in self._bypass), bar, checkable=True)
        button.color = QColor(self.buttons["play"].color)
        button.accent = QColor(self.buttons["play"].accent)
        button.set_checked(which in self._bypass)
        button.clicked.connect(lambda w=which, b=button: self.set_bypass(w, b.checked))
        close = getattr(bar, "close_btn", None)
        index = layout.indexOf(close) if close is not None else -1
        layout.insertWidget(index if index >= 0 else layout.count(), button, 0, Qt.AlignVCenter)
        self._bypass_buttons[which] = button

    def _grade_window_closed(self, which: str):
        self._windows.pop(which, None)
        self._bypass_buttons.pop(which, None)
        if which in self._bypass:                # fenêtre fermée en « avant » : ses corrections reviennent
            self._bypass.discard(which)
            self._push_state()

    def _color_rows(self, v2, values: dict) -> list:
        """Lignes du haut : espace d'entrée, LUT (bibliothèque ou fichier), position, intensité, corrections,
        comparaison, écrêtage."""
        specs = []
        if self._pipeline is not None:
            names = vcolor.colorspace_names(self._pipeline.config)
            values["vc_input"] = self._pipeline.input_space
            specs.append(v2.Spec("vc_input", "Espace d'entrée (ce média)", "choice", values["vc_input"],
                                 {"choices": tuple((n, n) for n in names), "width": 240}))
        luts = vcolor.list_luts(_setting(self._settings, "video_lut_dir"))
        choices = [("", "Aucune")] + [(str(p), p.stem) for p in luts]
        current = str(self._lut.path) if self._lut else ""
        if current and current not in dict(choices):
            choices.append((current, Path(current).stem))
        choices.append(("__file__", "Choisir un fichier .cube…"))
        values["vc_lut"] = current
        specs.append(v2.Spec("vc_lut", "LUT", "choice", current, {"choices": tuple(choices), "width": 240}))
        values["vc_lut_position"] = self._lut_position
        specs.append(v2.Spec("vc_lut_position", "Position de la LUT", "choice", self._lut_position,
                             {"choices": (("display", "Créative (après affichage)"),
                                          ("source", "Technique (sur le fichier)")), "width": 240}))
        values["vc_lut_mix"] = int(round(self._lut_mix * 100))
        specs.append(v2.Spec("vc_lut_mix", "Intensité de la LUT", "slider", values["vc_lut_mix"],
                             {"min": 0, "max": 100, "unit": "%", "width": 180, "box": 70, "reset": 100}))
        values["vc_on"] = self._grade_on
        specs.append(v2.Spec("vc_on", "Corrections et LUT actives", "bool", self._grade_on))
        values["vc_clip"] = self._clipping
        specs.append(v2.Spec("vc_clip", "Signaler l'écrêtage", "bool", self._clipping))
        return specs

    def _on_grade_window(self, values: dict, which: str | None = None):
        if which in self._bypass:
            # Un réglage bougé pendant l'« avant » : on montre à nouveau le résultat (sinon rien ne bougerait).
            self._bypass.discard(which)
            self.set_bypass(which, False)
        grade = dict(self._grade)
        for key, value in values.items():
            if key.startswith("vg_"):
                name = key[3:]
                grade[name] = value / _ALL_GRADE[name][4]
        if "vc_input" in values and self.path is not None and values["vc_input"] != self.input_space():
            self._input_override[str(self.path)] = values["vc_input"]
            self._refresh_pipeline()
        if "vc_lut" in values:
            chosen = values["vc_lut"]
            if chosen == "__file__":
                path, _f = QFileDialog.getOpenFileName(self, "Choisir une LUT", str(
                    _setting(self._settings, "video_lut_dir") or ""), "LUT (*.cube)")
                if path:
                    self._load_lut(path)
                self._sync_lut_field()           # la liste montre la LUT en cours, plus « Choisir… »
            elif chosen != (str(self._lut.path) if self._lut else ""):
                if chosen:
                    self._load_lut(chosen)
                else:
                    self._lut = None
            self._lut_position = values.get("vc_lut_position", self._lut_position)
            self._lut_mix = values.get("vc_lut_mix", int(self._lut_mix * 100)) / 100.0
            self._grade_on = bool(values.get("vc_on", True))
            self._clipping = bool(values.get("vc_clip", False))
        self.set_grade(grade)

    def _sync_lut_field(self):
        """Ligne « LUT » de la fenêtre de corrections : la LUT en cours (ajoutée à la liste si elle vient d'un
        fichier hors bibliothèque)."""
        window = self._windows.get("grade_main")
        if window is None:
            return
        for spec, field in getattr(window, "_fields", ()):
            if spec.key != "vc_lut":
                continue
            choices = [c for c in getattr(field, "_choices", ()) if c[0] != "__file__"]
            current = str(self._lut.path) if self._lut else ""
            if current and current not in dict(choices):
                choices.append((current, Path(current).stem))
            choices.append(("__file__", "Choisir un fichier .cube…"))
            field._choices = tuple(choices)
            field.setOptions([label for _k, label in choices])
            field.setValue(dict(choices).get(current, "Aucune"))

    def grade_presets(self) -> dict:
        return dict(_setting(self._settings, "video_grade_presets") or {})

    def save_grade_preset(self, name: str):
        presets = self.grade_presets()
        presets[name] = {k: v for k, v in self._grade.items() if v != vcolor.DEFAULT_GRADE[k]}
        self._settings["video_grade_presets"] = presets
        self._save_state("video_grade_presets", presets)

    def load_grade_preset(self, name: str):
        preset = self.grade_presets().get(name)
        if preset is not None:
            self.set_grade({**vcolor.DEFAULT_GRADE, **preset})
            self._reopen_grade_windows()

    def open_export_window(self):
        from fm_video.export_window import ExportWindow
        window = self._windows.get("export")
        if window is not None:
            try:
                window.raise_()
                return window
            except RuntimeError:
                pass
        if self.source is None:
            return None
        window = ExportWindow(self, HOOKS["settings"]() or self._settings)
        window.destroyed.connect(lambda _o=None: self._windows.pop("export", None))
        self._windows["export"] = window
        window.show()
        return window

    # -- navigation --

    def go(self, index: int, direction: int | None = None):
        """Aller EXACTEMENT à l'image `index` (affichée dès qu'elle est décodée)."""
        if self.source is None:
            return
        index = max(0, min(int(index), self.source.frame_count - 1))
        if direction is None:
            direction = 1 if index >= self.index else -1
        self.index = index
        self.timeline.set_current(index)
        self._update_position_labels()
        if self._engine == "vlc" and self._playing:
            # Lecture VLC : saut dans VLC (aucun décodage PyAV pendant la lecture).
            self._vlc.set_time(self._ms_of(index))
            self._vlc_begin(index)
            return
        frame = self.cache.get(self.cache.key(self.source, index))
        if frame is not None:
            self._show(index)
            self.loader.request(index, direction)
        else:
            self._pending = index
            self.loader.request(index, direction)

    def step(self, delta: int):
        self.pause()
        self.go(self.index + delta, 1 if delta > 0 else -1)

    def go_first(self):
        self.pause()
        lo, _hi = self._bounds()
        self.go(lo if self.index != lo else 0)

    def go_last(self):
        self.pause()
        _lo, hi = self._bounds()
        self.go(hi if self.index != hi else self.source.frame_count - 1 if self.source else 0)

    def stop(self):
        self.pause()
        lo, _hi = self._bounds()
        self.go(lo)

    def _bounds(self) -> tuple[int, int]:
        """Plage jouée : la sélection IN / OUT quand « Boucler sur la sélection » est allumé, sinon tout."""
        if self.source is None:
            return 0, 0
        if self._loop_range:
            return self.timeline.range()
        return 0, self.source.frame_count - 1

    def _scrub_started(self):
        """Glisser sur la timeline pendant une lecture VLC : pause le temps du geste (images exactes de PyAV),
        reprise au relâchement."""
        if self._engine == "vlc" and self._playing:
            self._scrub_resume = True
            self.pause()

    def _scrub_finished(self):
        if self._scrub_resume:
            self._scrub_resume = False
            self.play()

    def _seek_from_timeline(self, index: int):
        was = self._playing and self._engine != "vlc"
        if was:
            self._clock = (time.perf_counter(), index)
            self._sync_audio(force=True, index=index)
        self.go(index)

    def _frame_entered(self):
        if self.source is None:
            return
        text = self.frame_field.text().strip()
        index = vmedia.parse_timecode(text, self.source.fps)
        if index is None:
            try:
                index = int(text) - self.source.first_number
            except ValueError:
                self._update_position_labels()
                return
        else:
            index -= self.source.timecode_start
        self.pause()
        self.go(index)
        self.viewer.setFocus()

    def set_in(self):
        self.timeline.set_range(self.index, self.timeline.out_point
                                if self.timeline.out_point is None or self.timeline.out_point >= self.index else None)

    def set_out(self):
        self.timeline.set_range(self.timeline.in_point
                                if self.timeline.in_point is None or self.timeline.in_point <= self.index else None,
                                self.index)

    def clear_range(self):
        self.timeline.set_range(None, None)
        if self._loop_range:
            self._toggle_loop_range()

    def _unit_chosen(self, label: str):
        value = "seconds" if label == "Secondes" else "frames"
        self._settings["video_time_display"] = value
        self.timeline.set_look({**self.timeline.look, "seconds": value == "seconds",
                                "show_frames": True, "show_tc": False})
        self._save_state("video_time_display", value)

    def _toggle_loop(self):
        self._loop = not self._loop
        self.buttons["loop"].set_checked(self._loop)
        self._save_state("video_loop", self._loop)

    def _toggle_loop_range(self):
        self._loop_range = not self._loop_range
        self.buttons["range"].set_checked(self._loop_range)
        if self._loop_range:
            lo, hi = self.timeline.range()
            if not lo <= self.index <= hi:
                self.go(lo)

    # -- lecture --

    def _on_view_clicked(self):
        """Clic sur l'image (sans la déplacer) : lecture / pause."""
        if self.source is None:
            return
        self._click_toggle_at = time.perf_counter()
        self.toggle_play()

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if self.source is None or self.source.frame_count <= 1 or self._playing:
            return
        lo, hi = self._bounds()
        if self.index >= hi:
            self.go(lo)                           # à la fin : la lecture repart du début (boucle ou non)
        if self._engine == "vlc":
            self._play_vlc()
            return
        self._playing = True
        self._clock = (time.perf_counter(), self.index)
        self._last_tick = self._clock[0]
        self.buttons["play"].set_kind("pause")
        self._timer.start()
        self._restart_audio(self.index)
        if self._thumbs is not None:
            self._thumbs.set_playing(True)                  # miniatures : aucune lecture concurrente pendant la lecture
        self._update_info()

    def pause(self):
        if not self._playing:
            return
        self._playing = False
        self._timer.stop()
        self.buttons["play"].set_kind("play")
        if self._engine == "vlc":
            self._pause_vlc()
            self._update_info()
            return
        if self._audio is not None:
            self._audio.pause()
        if self._thumbs is not None:
            self._thumbs.set_playing(False)
        if self._shown >= 0 and self._shown != self.index:
            self.go(self._shown)
        self._update_info()

    # -- moteur LibVLC --

    def _start_thumbs(self, source):
        """Miniatures de la timeline (Réglages > Module vidéo > Timeline) : lecteur en fond, propre à ce média."""
        if (not _setting(self._settings, "video_timeline_thumbs") and not self._moodboard_on) or source.frame_count <= 1:
            return
        from fm_video.thumbs import ThumbnailLoader
        if source.width and source.height:
            self.timeline.thumb_aspect = source.width / source.height
        loader = ThumbnailLoader(source.path if source.kind == "video" else self.path, self._settings, self)
        loader.set_look(self._pipeline, vcolor.ViewState(dict(vcolor.DEFAULT_GRADE)))
        loader.set_height(self._thumb_decode_height())
        loader.ready.connect(self.timeline.add_thumb)
        self._thumbs = loader

    def request_thumbs(self):
        """Bouton « Miniatures » : images de la partie visible de la timeline, lues en fond."""
        if self._thumbs is None and self.source is not None:
            self._start_thumbs(self.source)
        if self._thumbs is not None:
            self.timeline.request_thumbs()

    def _thumbs_wanted(self, indices):
        if self._thumbs is not None:
            self._thumbs.set_height(self._thumb_decode_height())
            self._thumbs.request(indices)

    def _thumb_decode_height(self) -> int:
        """Hauteur de décodage des miniatures = bande de la timeline en pixels PHYSIQUES (nettes sur écran HiDPI)."""
        return int(round(self.timeline.thumb_h * self.timeline.devicePixelRatioF()))

    def _thumb_height_chosen(self, value: int):
        """Hauteur des miniatures tirée à la souris : retenue (Réglages > Module vidéo > Timeline)."""
        self._settings["video_timeline_thumb_height"] = int(value)
        save = HOOKS.get("save_state")
        if save is not None:
            save("video_timeline_thumb_height", int(value))

    def _engine_for(self, source) -> str:
        if source.kind != "video" or _setting(self._settings, "video_engine") == "pyav":
            return "pyav"
        try:
            from fm_video import vlc_engine
            return "vlc" if vlc_engine.available() else "pyav"
        except Exception:                                    # noqa: BLE001 - python-vlc / VLC absents
            return "pyav"

    def _ensure_vlc(self):
        if self._vlc is None:
            from fm_video.vlc_engine import VlcPlayer
            self._vlc = VlcPlayer(self)
            self._vlc.frameReady.connect(self._on_vlc_frame)
            self._vlc.ended.connect(self._on_vlc_ended)
            self._vlc.playing.connect(self._on_vlc_playing)
            self._vlc.failed.connect(self._on_vlc_failed)
        return self._vlc

    def _open_vlc(self, source):
        """Paramètres YUV des images de VLC (I420 8 bits) : matrice et plage du fichier, chromas à gauche — la même
        conversion que les images exactes de PyAV (aucun saut de couleur à la pause)."""
        try:
            player = self._ensure_vlc()
        except Exception as exc:                             # noqa: BLE001 - VLC inutilisable : PyAV
            self._status(f"LibVLC indisponible ({exc}) : lecture par PyAV")
            self._engine = "pyav"
            self._setup_audio()
            return
        ctx = source._stream.codec_context
        kr, kb = vmedia.yuv_coefficients(getattr(ctx, "colorspace", 2), source.height)
        full = (getattr(ctx, "color_range", 0) or 0) == 2 or (ctx.pix_fmt or "").startswith("yuvj")
        self._vlc_yuv = (kr, kb, full, bool(getattr(source, "_chroma_left", True)))
        player.set_volume(self._volume)
        player.set_mute(self._muted)

    def _ms_of(self, index: int) -> int:
        return int(round(self.source.time_of(index) * 1000)) if self.source is not None else 0

    def _vlc_cache_args(self):
        return (int(_setting(self._settings, "video_cache_local_ms")),
                int(_setting(self._settings, "video_cache_network_ms")))

    def _play_vlc(self):
        player = self._vlc
        src = self.source
        self._playing = True
        self.buttons["play"].set_kind("pause")
        gate = getattr(src, "index_gate", None)
        if gate is not None:
            gate.clear()                      # index des images : pas de lecture du fichier pendant la lecture
        if self._thumbs is not None:
            self._thumbs.set_playing(True)              # miniatures : idem
        import vlc
        if player.state() == vlc.State.Paused and player.path == self.path and self._vlc_paused_at == self.index:
            # Reprise là où VLC s'est arrêté : il continue sans saut (son compris).
            self._vlc_anchor = None
            self._vlc_start = None
            self._vlc_skip = 0
            player.player.set_pause(0)
        else:
            # Position changée pendant la pause (pas à pas, timeline) : nouveau départ À cette image. Un saut de VLC
            # en pause (set_time) remontrait une image figée plusieurs fois avant de repartir (mesuré).
            self._vlc_begin(self.index)
            local, network = self._vlc_cache_args()
            player.stop()
            # `:input-repeat` rejoue depuis `:start-time` (mesuré : lancé depuis la dernière image, VLC tournait sur
            # la fin sans plus rien montrer) : boucle confiée à VLC seulement pour un départ au début ; sinon la fin
            # (EndReached) relance au début (`_on_vlc_ended`), puis VLC enchaîne sans coupure.
            player.open(self.path, local, network,
                        repeat=self._loop and not self._loop_range and self.index == 0,
                        start=src.time_of(self.index))
            player.play()
        self._vlc_paused_at = None
        self._update_info()

    def _pause_vlc(self):
        player = self._vlc
        player.pause()
        src = self.source
        gate = getattr(src, "index_gate", None)
        if gate is not None:
            gate.set()
        if self._thumbs is not None:
            self._thumbs.set_playing(False)
        index = self._shown if self._shown >= 0 else self.index
        self._vlc_paused_at = index
        self.index = -1                        # go() ne doit pas croire l'image déjà là
        self.go(index)                         # image EXACTE (PyAV) du rang atteint

    def _vlc_begin(self, index: int):
        """Départ / saut de VLC au rang `index`. Mesuré sur VLC 3.0.21 : la 1re image montrée après un départ ou
        un saut est un APERÇU périmé (rang 16 puis 20 pour un départ à 20), ensuite les images suivent ; elle est
        écartée (l'image exacte de PyAV reste à l'écran). L'horloge de VLC reste un moment à son ancienne valeur
        (0 en MP4) : jusqu'à sa mise à jour, le rang vient de NOTRE horloge depuis la 1re image."""
        self._vlc_anchor = None
        self._vlc_start = [int(index), self._ms_of(index), None, None]
        self._vlc_skip = 1

    def _vlc_index(self) -> int:
        """Rang de l'image que VLC vient de montrer : horloge de VLC (mise à jour par paliers) interpolée ; une
        nouvelle lecture ne recale l'ancre que si elle s'écarte de plus de 120 ms (mesuré : rang exact)."""
        now = time.perf_counter()
        ms = self._vlc.time_ms()
        start = self._vlc_start
        if start is not None and start[2] is not None and start[3] is None:
            start[3] = ms                                            # horloge lue à la 1re image
        if start is not None and start[2] is not None and now - start[2] < 3.0                 and (ms < 0 or ms == start[3] or ms < start[1] - 250):
            seconds = start[1] / 1000.0 + (now - start[2])           # horloge de VLC pas encore à jour
            index = int(round(self.source.index_at_time(seconds)))
            return max(0, min(index, self.source.frame_count - 1))
        a = self._vlc_anchor
        if ms < 0:
            ms = self._ms_of(max(0, self.index))
        if a is None or (ms != a[2] and abs(ms - (a[1] + (now - a[0]) * 1000.0)) > 120):
            a = [now, ms, ms]
        a[2] = ms
        self._vlc_anchor = a
        seconds = (a[1] + (now - a[0]) * 1000.0) / 1000.0
        index = int(round(self.source.index_at_time(seconds)))
        return max(0, min(index, self.source.frame_count - 1))

    def _on_vlc_frame(self):
        if self._engine != "vlc" or self.source is None or self._vlc is None:
            return
        got = self._vlc.take()
        if got is None or not self._playing:
            return
        if self._vlc_skip > 0:
            self._vlc_skip -= 1
            return
        if self._vlc_start is not None and self._vlc_start[2] is None:
            self._vlc_start[2] = time.perf_counter()
        buf, w, h, pitches, lines = got
        # VLC donne la taille CODÉE (2176 lignes pour une 4K, 1090 pour du 1080p) : lignes de remplissage en bas,
        # on ne montre que la partie VISIBLE (taille du flux).
        w = min(w, self.source.width or w)
        h = min(h, self.source.height or h)
        kr, kb, full, left = self._vlc_yuv
        planes = [buf.planes[i].reshape(lines[i], pitches[i]) for i in range(3)]
        shift = 0.25 / max(1, (w + 1) // 2) if left else 0.0
        yuv = vmedia.YuvImage(planes, w, h, 2, 2, 8, kr, kb, full, shift)
        index = self._vlc_index()
        lo, hi = self._bounds()
        previous = self._shown
        if self._loop_range and index >= hi:
            self._vlc.set_time(self._ms_of(lo))  # boucle sur IN / OUT
            self._vlc_begin(lo)
        elif not self._loop and previous > 0 and index < previous - max(10, self.source.frame_count // 2):
            # Média ouvert « en boucle » puis boucle coupée : on s'arrête à la fin au lieu de repartir.
            self._on_vlc_ended()
            return
        self.viewer.set_frame(vmedia.Frame(index, None, number=index, yuv=yuv))
        self.index = self._shown = index
        if self.scopes.isVisible():
            self._request_scopes()
        self.timeline.set_current(index)
        self._update_position_labels()
        now = time.perf_counter()
        if now - self._info_at > 0.25:         # surimpression : 4 fois par seconde suffit pendant la lecture
            self._info_at = now
            self._update_info()

    def _on_vlc_playing(self):
        if self._vlc is not None:
            self._vlc.apply_audio()            # la sortie audio vient d'être créée : volume / muet reposés

    def _on_vlc_ended(self):
        if self._engine != "vlc" or self.source is None:
            return
        lo, hi = self._bounds()
        if self._loop:
            self._playing = False
            self.index = lo
            self._vlc.stop()
            self.play()
            return
        self._playing = False
        self.buttons["play"].set_kind("play")
        gate = getattr(self.source, "index_gate", None)
        if gate is not None:
            gate.set()
        if self._thumbs is not None:
            self._thumbs.set_playing(False)
        self._vlc.stop()
        behavior = _setting(self._settings, "video_end_behavior")
        self.index = -1
        self.go(lo if behavior == "rewind" else hi)
        self._update_info()

    def _on_vlc_failed(self, message: str):
        self._status(message)

    def _tick(self):
        src = self.source
        if src is None:
            self.pause()
            return
        now = time.perf_counter()
        t0, i0 = self._clock
        fps = float(src.fps) or 24.0
        target = i0 + int(math.floor((now - t0) * fps + 1e-6))
        lo, hi = self._bounds()
        if target > hi:
            if self._loop:
                target = lo
                self._clock = (now, lo)
                self._restart_audio(lo)
            else:
                behavior = _setting(self._settings, "video_end_behavior")
                self.pause()
                self.go(lo if behavior == "rewind" else hi)
                return
        self.index = target
        if target != self._shown:
            frame = self.cache.get(self.cache.key(src, target))
            if frame is not None:
                self._show(target)
            elif _setting(self._settings, "video_priority") == "exact":
                # Précision : l'horloge attend l'image (rien n'est sauté).
                self._clock = (t0 + (now - self._last_tick), i0)
            self.loader.request(target, 1)
        self._last_tick = now
        if int(now * 2) != int((now - 0.004) * 2):
            self._sync_audio()

    def _show(self, index: int, force: bool = False):
        src = self.source
        frame = self.cache.get(self.cache.key(src, index)) if src else None
        if frame is None:
            return
        if frame.missing:
            policy = _setting(self._settings, "video_missing")
            if policy == "hold" and self.viewer.frame is not None and not force:
                pass
            else:
                import numpy as np
                black = vmedia.Frame(index, np.zeros((max(1, src.height), max(1, src.width), 3), np.uint8),
                                     number=frame.number)
                self.viewer.set_frame(black)
            self._show_message(f"Image manquante : {frame.number}" if policy == "card" else "")
        else:
            if self._message.startswith("Image manquante"):
                self._show_message("")
            self.viewer.set_frame(frame)
            if self.scopes.isVisible():
                self._request_scopes()
        self._shown = index
        if self._moodboard_on:
            self._sync_moodboard_selection()
        self.timeline.set_current(index)
        self._update_position_labels()
        self._update_info()

    def _on_frame_ready(self, index: int):
        if self._pending is not None and index == self._pending and not self._playing:
            self._pending = None
            self._show(index)

    def _on_frame_failed(self, index: int, message: str):
        if index == self._pending or index == self.index:
            self._show_message(message)
        self._status(message)

    def _on_index_ready(self):
        """Index réel des images construit : nombre exact d'images (cadence variable comprise)."""
        src = self.source
        if src is None:
            return
        if self.timeline.count != src.frame_count:
            # Miniatures GARDÉES : leurs rangs restent justes (les effacer laissait la bande vide jusqu'au défilement).
            self.timeline.set_media(src.frame_count, src.first_number, src.fps, src.timecode_start, keep_thumbs=True)
            self.timeline.set_current(self.index)
        self._sync_media_controls()
        self._update_position_labels()
        self._sync_mood_times()
        self.moodboard.update()

    def _sync_cache_marks(self):
        if self.source is not None and self.isVisible() and _setting(self._settings, "video_timeline_cache"):
            self.timeline.set_cached(self.cache.cached_indices(self.source))

    def _update_position_labels(self):
        src = self.source
        if src is None:
            return
        if not self.frame_field.hasFocus():
            self.frame_field.setText(str(src.number_of(self.index)))
        self.tc_label.setText(vmedia.format_timecode(self.index, src.fps, src.timecode_start))

    # -- audio --

    def _setup_audio(self):
        if self.source is None or not self.source.has_audio:
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception:                                    # noqa: BLE001 - Qt Multimedia absent : sans son
            return
        if self._audio is None:
            self._audio = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._audio.setAudioOutput(self._audio_out)
            self._audio.setVideoOutput(None)
        self._audio_out.setVolume(self._volume / 100.0)
        self._audio_out.setMuted(self._muted)
        self._audio.setSource(QUrl.fromLocalFile(str(self.source.path)))

    def _sync_audio(self, force=False, index=None):
        if self._audio is None or self.source is None or not self.source.has_audio:
            return
        index = self.index if index is None else index
        want = int(index / float(self.source.fps) * 1000)
        if force or abs(self._audio.position() - want) > 120:
            self._audio.setPosition(want)

    def _restart_audio(self, index: int):
        """Audio du moteur PyAV recalé sur `index` et RELANCÉ s'il s'était arrêté : arrivé au bout du fichier,
        QMediaPlayer passe à l'arrêt et un simple changement de position ne le relance pas (plus de son après la
        1re boucle)."""
        if self._audio is None or self.source is None or not self.source.has_audio:
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self._audio.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self._audio.stop()
        self._audio.setPosition(int(index / float(self.source.fps) * 1000))
        if self._playing and self._audio.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._audio.play()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.buttons["sound"].set_kind("mute" if self._muted else "sound")
        self._apply_volume()

    def _volume_changed(self, value: int):
        self._volume = int(value)
        self.volume_label.setText(f"{self._volume} %")
        if self._muted and self._volume > 0:
            self._muted = False                # monter le volume rend le son (comme VLC)
            self.buttons["sound"].set_kind("sound")
        self._apply_volume()
        self._save_state("video_volume", self._volume)

    def _apply_volume(self):
        """Volume et muet posés sur le moteur en cours (une seule valeur : `_volume`, 0-100 ; muet à part : le
        volume est retrouvé tel quel en rétablissant le son)."""
        if self._vlc is not None:
            self._vlc.set_volume(self._volume)
            self._vlc.set_mute(self._muted)
        if self._audio_out is not None:
            self._audio_out.setVolume(self._volume / 100.0)
            self._audio_out.setMuted(self._muted)

    # -- informations --

    def toggle_info(self):
        if self._moodboard_on:
            self.moodboard.info_enabled = not self.moodboard.info_enabled
            self._settings['video_mood_info_enabled'] = self.moodboard.info_enabled
            self._background_pending['video_mood_info_enabled'] = self.moodboard.info_enabled
            self._background_save_timer.start()
            self._sync_mood_times()
            self.moodboard.update()
            return
        self._set_info_visible(not self.overlay.isVisible(), user=True)

    def _set_info_visible(self, visible: bool, user: bool = True):
        self.overlay.setVisible(visible)
        if visible:
            self._update_info()
            self.overlay.raise_()
            if _setting(self._settings, "video_info_temporary"):
                self._info_timer.start(int(_setting(self._settings, "video_info_timeout")) * 1000)
        if user:
            self._save_state("video_info_enabled", visible)
        self.stateChanged.emit()

    def info_visible(self) -> bool:
        return self.overlay.isVisible()

    def _initial_zoom(self):
        """Zoom initial (Réglages > Module vidéo > Affichage) : intelligent (réduit si l'image dépasse la zone,
        sinon 100 % — jamais agrandie), toujours ajusté, toujours 100 %, ou le dernier zoom."""
        mode = _setting(self._settings, "video_default_zoom")
        if mode == "100":
            QTimer.singleShot(0, lambda: self.viewer.one_to_one())
        elif mode == "fit":
            self.viewer.fit()
        elif mode == "last":
            last = _setting(self._settings, "video_last_zoom") or {}
            kind = last.get("mode", "smart")
            if kind == "free" and last.get("scale"):
                QTimer.singleShot(0, lambda z=float(last["scale"]): self.viewer.set_zoom(z))
            elif kind == "fit":
                self.viewer.fit()
            else:
                self.viewer.smart()
        else:
            self.viewer.smart()

    def _remember_zoom(self):
        state = {"mode": self.viewer.zoom_mode(), "scale": round(float(self.viewer.zoom()), 5)}
        if state != self._settings.get("video_last_zoom"):
            self._settings["video_last_zoom"] = state
            self._save_state("video_last_zoom", state)

    def _effects(self) -> dict:
        """Bordure / coins / ombre autour de l'image (Réglages > Module vidéo > Affichage)."""
        s = self._settings

        def col(value):
            value = str(value or "#000000")
            resolve = HOOKS.get("resolve_color")
            if value.startswith("@") and resolve is not None:
                try:
                    return resolve(value)
                except Exception:                            # noqa: BLE001
                    return "#808080"
            return value
        sides = _setting(s, "video_frame_border_enabled")
        if not isinstance(sides, dict):
            sides = {k: bool(sides) for k in ("top", "right", "bottom", "left")}
        colors = _setting(s, "video_frame_border")
        if not isinstance(colors, dict):
            colors = {k: colors for k in ("top", "right", "bottom", "left")}
        radius = _setting(s, "video_frame_radius")
        if not isinstance(radius, dict):
            radius = {k: int(radius or 0) for k in ("top_left", "top_right", "bottom_right", "bottom_left")}
        effects = {"border_on": {k: bool(sides.get(k)) for k in ("top", "right", "bottom", "left")},
                   "border_w": int(_setting(s, "video_frame_border_thickness") or 0),
                   "border_colors": {k: col(colors.get(k)) for k in ("top", "right", "bottom", "left")},
                   "radius": radius, "shadow": None}
        try:
            from settings_widgets import shadow_look
            look = shadow_look({k: _setting(s, k) for k in ("video_frame_shadow_enabled", "video_frame_shadow",
                                                             "video_frame_shadow_size")}, "video_frame_shadow", col)
        except Exception:                                    # noqa: BLE001
            look = None
        if look is not None:
            effects["shadow"] = {"sides": look["on"], "color": next(iter(look["colors"].values())),
                                 "blur": look["size"], "ox": int(_setting(s, "video_frame_shadow_offset_x") or 0),
                                 "oy": int(_setting(s, "video_frame_shadow_offset_y") or 0),
                                 "spread": int(_setting(s, "video_frame_shadow_spread") or 0)}
        return effects

    def _on_zoom(self, scale: float):
        dpr = self.viewer.devicePixelRatioF() or 1.0
        self.zoom_label.setText(f"{scale * 100:.0f} %" if scale >= 0.1 else f"{scale * 100:.1f} %")
        self.zoom_label.setToolTip(f"Zoom de l'image : {scale * 100 / dpr:.0f} % en pixels logiques "
                                   f"(écran à {dpr:.2f}×)")
        if self.source is not None:
            if self._zoom_timer is None:
                self._zoom_timer = QTimer(self)
                self._zoom_timer.setSingleShot(True)
                self._zoom_timer.setInterval(600)
                self._zoom_timer.timeout.connect(self._remember_zoom)
            self._zoom_timer.start()
        self._update_info()

    def _on_pixel(self, x: int, y: int):
        self._hover = (x, y) if x >= 0 else None
        if self.overlay.isVisible() and _setting(self._settings, "video_info_pixel"):
            self._update_info()

    def info_sections(self) -> list:
        src = self.source
        if src is None:
            return []
        s = self._settings
        sections = []
        info = src.info
        if _setting(s, "video_info_media"):
            rows = list(info.get("Média", []))
            rows += [("Images", str(src.frame_count)), ("Image", f"{src.number_of(self.index)}"),
                     ("Timecode", vmedia.format_timecode(self.index, src.fps, src.timecode_start))]
            sections.append(("Média", rows))
        if _setting(s, "video_info_image"):
            rows = list(info.get("Image", []))
            if len(src.layers) > 1:
                rows.append(("Calque", src.layer or "RVBA"))
            sections.append(("Image", rows))
        if _setting(s, "video_info_playback"):
            rows = list(info.get("Lecture", []))
            rows += [("FPS de lecture", vmedia.fps_text(src.fps)),
                     ("Position", f"{src.time_of(max(0, self.index)):.3f} s"),
                     ("Moteur", "LibVLC (VLC)" if self._engine == "vlc" else "PyAV"),
                     ("Accès", self._access_text()),
                     ("Plage", f"{src.number_of(0)} - {src.number_of(src.frame_count - 1)}"),
                     ("État", "lecture" if self._playing else "pause")]
            if self.timeline.in_point is not None or self.timeline.out_point is not None:
                lo, hi = self.timeline.range()
                rows.append(("IN / OUT", f"{src.number_of(lo)} - {src.number_of(hi)} ({hi - lo + 1} images)"))
            sections.append(("Lecture", rows))
        if _setting(s, "video_info_display"):
            rows = [("Zoom", f"{self.viewer.zoom() * 100:.1f} % ({'ajusté' if self.viewer.zoom_mode() == 'fit' else 'libre'})")]
            pipe = self._pipeline
            if pipe is not None:
                rows += [("Espace d'entrée", pipe.input_space), ("Espace de travail", pipe.working),
                         ("Affichage", f"{pipe.display} / {pipe.view}")]
            else:
                rows.append(("Couleur", "OpenColorIO absent : valeurs affichées telles quelles"))
            if self._lut is not None:
                rows.append(("LUT", f"{self._lut.path.name} ({int(self._lut_mix * 100)} %, "
                                    f"{'technique' if self._lut_position == 'source' else 'créative'})"))
            active = [label for key, label, *_r in GRADE_MAIN + GRADE_CHANNELS
                      if abs(self._grade.get(key, 0) - vcolor.DEFAULT_GRADE[key]) > 1e-6]
            if active:
                state = "" if self._grade_on else " (coupées)"
                if self._bypass:
                    state += " (avant : " + ", ".join(
                        "générales" if w == "grade_main" else "par canal" for w in sorted(self._bypass)) + ")"
                rows.append(("Corrections", ", ".join(active) + state))
            if self._compare != "off":
                rows.append(("Comparaison", "avant / après" if self._compare == "split" else "avant"))
            if self._channel != "rgb":
                rows.append(("Canal", self._channel.upper()))
            if _setting(s, "video_diagnostics"):
                if self._engine == "vlc" and self._vlc is not None:
                    from fm_video import vlc_engine
                    rows += [("LibVLC", vlc_engine.version()), ("Images de VLC", str(self._vlc.displayed))]
                rows += [("Moteur d'affichage", getattr(self.viewer, "engine", "?")),
                         ("Cache", f"{self.cache.used_bytes / 2**20:.0f} / {self.cache.max_bytes / 2**20:.0f} Mo")]
                if getattr(self.viewer, "error", ""):
                    rows.append(("Erreur", self.viewer.error))
            sections.append(("Affichage", rows))
        if _setting(s, "video_info_pixel") and self._hover is not None:
            frame = self.viewer.frame
            x, y = self._hover
            value = frame.value_at(x, y) if frame is not None else None
            if value is not None:
                parts = []
                for v in (value if getattr(value, "ndim", 0) else [value]):
                    parts.append(f"{float(v):.4f}" if getattr(v, "dtype", None) is not None
                                 and v.dtype.kind == "f" else str(int(v)))
                sections.append(("Pixel", [("Position", f"{x}, {y}"), ("Valeur source", "  ".join(parts))]))
        return sections

    def _access_text(self) -> str:
        if self.path is None:
            return ""
        from fm_video.vlc_engine import is_remote
        if is_remote(self.path):
            return f"réseau (cache {_setting(self._settings, 'video_cache_network_ms')} ms)"                 if self._engine == "vlc" else "réseau"
        return f"local (cache {_setting(self._settings, 'video_cache_local_ms')} ms)" if self._engine == "vlc"             else "local"

    def _update_info(self):
        if self.overlay.isVisible():
            self._info_at = time.perf_counter()
            self.overlay.set_sections(self.info_sections())

    # -- plein écran --

    def toggle_fullscreen(self):
        if self._fullscreen is not None:
            self.exit_fullscreen()
            return
        home = self.parentWidget()
        screen = self.window().screen()
        window = QWidget(None, Qt.Window | Qt.FramelessWindowHint)
        window.setStyleSheet(f"background: {_color(self._settings, 'video_bg_color')};")
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        self._fs_home = home
        self._fullscreen = window
        self.setParent(window)
        layout.addWidget(self)
        if screen is not None:
            window.setScreen(screen)
            window.setGeometry(screen.geometry())
        window.showFullScreen()
        self.show()
        self.viewer.setFocus()
        if not _setting(self._settings, "video_fullscreen_info") and self.overlay.isVisible():
            self.overlay.hide()
        if _setting(self._settings, "video_fullscreen_autohide"):
            self._hide_timer.start()
        self.stateChanged.emit()

    def exit_fullscreen(self):
        window = self._fullscreen
        if window is None:
            return
        self._fullscreen = None
        home = self._fs_home
        self.setParent(home)
        self.controls.show()
        self.timeline.setVisible(not self._moodboard_on)
        self.fit()
        self.show()
        self.raise_()
        window.close()
        window.deleteLater()
        self.viewer.setFocus()
        self.stateChanged.emit()

    def is_fullscreen(self) -> bool:
        return self._fullscreen is not None

    def _autohide_controls(self):
        if self._fullscreen is not None and _setting(self._settings, "video_fullscreen_autohide"):
            self.controls.hide()
            self.timeline.hide()

    # -- clavier, souris, géométrie --

    def _shortcut(self, key: str, event) -> bool:
        text = str(_setting(self._settings, key) or "")
        if not text:
            return False
        seq = QKeySequence(text)
        if seq.isEmpty():
            return False
        combo = event.keyCombination().toCombined() if hasattr(event, "keyCombination") else event.key()
        return seq[0].toCombined() == combo

    def _key_action(self, event):
        """Action d'une touche du module (None = pas pour lui). Sert aussi à réclamer la touche avant les
        raccourcis de la fenêtre principale (« I » de l'inspecteur, flèches de la visionneuse…)."""
        key = event.key()
        mods = event.modifiers() & ~Qt.KeypadModifier
        if self._moodboard_on and mods==Qt.ControlModifier:
            if key==Qt.Key_Z:
                return self._mood_undo.undo
            if key==Qt.Key_Y:
                return self._mood_undo.redo
        if self._shortcut("video_key_in", event):
            return self.set_in
        if self._shortcut("video_key_out", event):
            return self.set_out
        if self._shortcut("video_key_clear", event):
            return self.clear_range
        if key == Qt.Key_Space and not mods:
            return self.toggle_play
        if key == Qt.Key_Right:
            return lambda: self.step(10 if mods & Qt.ShiftModifier else 1)
        if key == Qt.Key_Left:
            return lambda: self.step(-10 if mods & Qt.ShiftModifier else -1)
        if key == Qt.Key_Home:
            return self.go_first
        if key == Qt.Key_End:
            return self.go_last
        if key == Qt.Key_I and not mods:
            return self.toggle_info
        if key == Qt.Key_S and not mods:
            return self.toggle_scopes
        if key == Qt.Key_M and not mods:
            return self.toggle_moodboard
        if key == Qt.Key_F and not mods:
            return self.toggle_fullscreen
        if key in (Qt.Key_0, Qt.Key_Equal) and not mods & ~Qt.ShiftModifier:
            return self._active_fit
        if key == Qt.Key_1 and not mods:
            return self._active_one_to_one
        if key in (Qt.Key_Plus, Qt.Key_Minus):
            return lambda: self._active_view().zoom_by(1 if key == Qt.Key_Plus else -1)
        if key == Qt.Key_C and not mods:
            return self._cycle_compare
        if key == Qt.Key_Escape:
            if (self.viewer.region_mode() or self.moodboard._zone_mode):
                return lambda: self._set_zone_mode(False)       # tracé de zone annulé
            return self.exit_fullscreen if self._fullscreen is not None else self.closeRequested.emit
        return None

    def handle_key(self, event) -> bool:
        action = self._key_action(event)
        if action is None:
            return False
        action()
        return True

    def keyPressEvent(self, event):
        if not self.handle_key(event):
            super().keyPressEvent(event)

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and self._key_action(event) is not None:
            event.accept()
            return True
        return super().event(event)

    def eventFilter(self, obj, event):
        etype = event.type()
        if obj is self.parentWidget() and etype == QEvent.Resize and self._fullscreen is None:
            self.fit()
        elif obj is self.viewer or obj is self.moodboard:
            if etype == QEvent.ShortcutOverride and self._key_action(event) is not None:
                event.accept()                   # la touche est au module, pas aux raccourcis de la fenêtre
                return True
            if etype == QEvent.KeyPress and self.handle_key(event):
                return True
            if obj is self.viewer and etype == QEvent.Resize:
                self.overlay.reposition()
                self.scopes.reposition()
                if self._message:
                    self.message.setGeometry(self.viewer.rect().adjusted(40, 40, -40, -40))
            elif obj is getattr(self, "moodboard", None) and etype == QEvent.Resize and self._moodboard_on:
                self._mood_refresh_timer.start()
            elif etype == QEvent.MouseMove and self._fullscreen is not None:
                self.controls.show()
                self.timeline.setVisible(not self._moodboard_on)
                self._hide_timer.start()
            elif obj is self.viewer and etype == QEvent.MouseButtonDblClick:
                # Le 1er clic du double-clic a déjà basculé lecture / pause (aussitôt, sans attendre le délai
                # du double-clic) : on le défait, le double-clic ne fait que le plein écran.
                from PySide6.QtWidgets import QApplication
                if time.perf_counter() - self._click_toggle_at < QApplication.doubleClickInterval() / 1000.0:
                    self._click_toggle_at = 0.0
                    self.toggle_play()
                self.toggle_fullscreen()
                return True
        return super().eventFilter(obj, event)

    def fit(self):
        parent = self.parentWidget()
        if parent is not None and self._fullscreen is None:
            self.setGeometry(parent.rect())

    def fade_in(self):
        self.fit()
        self.show()
        self.raise_()
        self._active_view().setFocus()

    def shutdown(self):
        """Fermeture du module : lecture arrêtée, fils de fond arrêtés, fenêtres fermées, mémoire rendue."""
        self._background_save_timer.stop()
        self._color_help.dismiss()
        self._save_background()
        if self._analysis is not None:
            self._analysis.stop()
        if self._fullscreen is not None:
            self.exit_fullscreen()
        job = self._export_job
        if job is not None:
            job.cancel()
        self.close_media()
        self.cache.clear()
        self._cache_timer.stop()
        if self._vlc is not None:
            self._vlc.close()
            self._vlc = None
        if self._scope_worker is not None:
            self._scope_worker.stop()
