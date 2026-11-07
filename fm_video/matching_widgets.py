"""Widgets PEINTS de l'onglet Matching / LUT (seconde maquette « Matching / LUT — Image 4207 ») : cartes source /
référence, viewer avec rideau avant / après, étapes, encadré d'information, curseur d'intensité. Briques communes
(boutons, sélecteurs, titres, polices, icônes) : `analysis_widgets.py` ; assemblage : `matching_view.py`.

Fluidité : le rideau ne fait que repeindre deux images déjà réduites à la taille affichée (mises en cache par taille) ;
aucune image n'est lue ni recalculée sur le fil de l'interface."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap

from fm_video.analysis_widgets import Button, _Painted, font, icon, rgba, text_width


def _cover(image: QImage, rect: QRectF, dpr: float) -> QPixmap:
    """Image recadrée pour REMPLIR `rect` (object-fit: cover)."""
    w, h = round(rect.width() * dpr), round(rect.height() * dpr)
    scaled = image.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    pm = QPixmap.fromImage(scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h))
    pm.setDevicePixelRatio(dpr)
    return pm


class PairCard(_Painted):
    """Carte « Source » ou « Référence » : vignette, étiquette, nom, sous-titre, bouton (Changer / Retirer).
    Référence absente : contour pointillé accent, « Choisir une référence… », clic ou dépôt d'une image."""
    picked = Signal()               # clic sur la carte vide
    dropped = Signal(str)           # image déposée
    action = Signal()               # bouton de la carte

    def __init__(self, parent, look, label, button_text):
        super().__init__(parent, look)
        self.label = label
        self.name = self.subtitle = ""
        self.thumb = None
        self.empty = False
        self._pix = self._pix_key = None
        self.button = Button(self, look, button_text, kind="small", height_key=32)
        self.button.clicked.connect(self.action)
        self.setAcceptDrops(True)
        self.setFixedHeight(54 + 16 + 2)
        self.setMinimumWidth(200)

    def _look_changed(self):
        self.button.set_look(self.look)

    def set_content(self, name, subtitle, thumb=None, empty=False):
        self.name, self.subtitle, self.thumb, self.empty = name, subtitle, thumb, empty
        self.button.setVisible(not empty)
        self.setCursor(Qt.PointingHandCursor if empty else Qt.ArrowCursor)
        self._pix_key = None
        self.update()

    def resizeEvent(self, event):
        self.button.setGeometry(self.width() - 9 - self.button.sizeHint().width(), (self.height() - 32) // 2,
                                self.button.sizeHint().width(), 32)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.empty:
            p.setPen(QPen(QColor(lk["accent_color"]), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
        else:
            p.setPen(QPen(QColor(lk["control_border"]), 1))
            p.setBrush(QColor(lk["card_color"]))
        p.drawRoundedRect(frame, 10, 10)
        tw = lk["thumb_width"]
        thumb = QRectF(9, (self.height() - 54) / 2, tw, 54)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 6, 6)
        if self.empty:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lk["card_color"]))
            p.drawPath(clip)
            p.drawPixmap(QPointF(thumb.center().x() - 10, thumb.center().y() - 10),
                         icon("plus", lk["accent_color"], 20, self.devicePixelRatioF()))
        elif self.thumb is not None and not self.thumb.isNull():
            dpr = self.devicePixelRatioF()
            key = (tw, dpr, self.thumb.cacheKey())
            if key != self._pix_key:
                self._pix, self._pix_key = _cover(self.thumb, thumb, dpr), key
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(thumb.topLeft(), self._pix)
            p.restore()
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lk["well_color"]))
            p.drawPath(clip)
        x = thumb.right() + 12
        right = self.width() - (12 if self.empty else 9 + self.button.sizeHint().width() + 12)
        y = (self.height() - 52) / 2
        p.setFont(font(lk, 11, spacing=0.66))
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(QRectF(x, y, right - x, 16), Qt.AlignLeft | Qt.AlignVCenter, self.label.upper())
        f = font(lk, lk["font_size"], 500)
        p.setFont(f)
        p.setPen(QColor(lk["accent_light" if self.empty else "strong_color"]))
        p.drawText(QRectF(x, y + 17, right - x, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(f).elidedText(self.name, Qt.ElideMiddle, max(1.0, right - x)))
        f = font(lk, 11)
        p.setFont(f)
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(QRectF(x, y + 36, right - x, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(f).elidedText(self.subtitle, Qt.ElideRight, max(1.0, right - x)))

    def mouseReleaseEvent(self, event):
        if self.empty and event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.picked.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return


class PairArrow(_Painted):
    """Flèche entre la source et la référence."""

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.setFixedWidth(20)

    def paintEvent(self, event):
        QPainter(self).drawPixmap(QPointF(0, (self.height() - 20) / 2),
                                  icon("arrow", self.look["arrow_color"], 20, self.devicePixelRatioF()))


VIEWS = (("before", "Avant"), ("split", "Avant / après"), ("after", "Après"))


class ViewToolbar(_Painted):
    """Avant / Avant-après / Après, en bas au centre du viewer ; inactif tant qu'aucun matching n'est calculé."""
    picked = Signal(str)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.view, self.active = "split", False
        self._relayout()

    def _look_changed(self):
        self._relayout()

    def set_state(self, view, active):
        if (view, active) != (self.view, self.active):
            self.view, self.active = view, active
            self.setCursor(Qt.PointingHandCursor if active else Qt.ForbiddenCursor)
            self.update()

    def _relayout(self):
        f = font(self.look, 12, 500)
        self._rects, x = [], 4.0
        for vid, label in VIEWS:
            w = 24 + text_width(f, label)
            self._rects.append((vid, label, QRectF(x, 4, w, 34)))
            x += w + 2
        self.setFixedSize(round(x - 2 + 4), 42)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(lk["control_border"]), 1))
        p.setBrush(rgba(lk["panel_color"], .92))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12, 12)
        p.setFont(font(lk, 12, 500))
        for vid, label, rect in self._rects:
            on = self.active and vid == self.view
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(lk["active_color"]))
                p.drawRoundedRect(rect, 8, 8)
            p.setPen(QColor(lk["strong_color"] if on else lk["muted_color"]))
            p.drawText(rect, Qt.AlignCenter, label)

    def mousePressEvent(self, event):
        if not self.active:
            return
        for vid, _label, rect in self._rects:
            if rect.contains(event.position()):
                self.picked.emit(vid)
                return


class MatchViewer(_Painted):
    """Image source ; une fois le matching calculé, l'image corrigée à droite du rideau (glisser = déplacer le
    rideau, n'importe où sur l'image). Sans référence : message en bas de l'image."""
    posChanged = Signal(float)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.before = QImage()
        self.after = None
        self.pos = 50.0
        self.intensity = 100
        self.message = ""
        self.bg = QColor(look["viewer_bg_2"])
        self._pix = {}
        self._dragging = False
        self.toolbar = ViewToolbar(self, look)
        self.setMinimumHeight(420)

    def _look_changed(self):
        self.toolbar.set_look(self.look)
        self._place_toolbar()

    def set_images(self, before, after):
        self.before = before if before is not None else QImage()
        self.after = after
        self.setCursor(Qt.SizeHorCursor if after is not None else Qt.ArrowCursor)
        self.update()

    def set_pos(self, pos):
        pos = max(0.0, min(100.0, float(pos)))
        if pos != self.pos:
            self.pos = pos
            self.update()

    def set_bg(self, color: QColor):
        if color != self.bg:
            self.bg = color
            self.update()

    def image_rect(self) -> QRectF:
        if self.before.isNull():
            return QRectF()
        avail = QRectF(self.rect()).adjusted(32, 32, -32, -72)
        height = max(1, min(avail.height(), self.look["match_image_max_height"]))
        size = self.before.size().scaled(round(max(1, avail.width())), round(height), Qt.KeepAspectRatio)
        return QRectF(round(avail.center().x() - size.width() / 2), round(avail.center().y() - size.height() / 2),
                      size.width(), size.height())

    def _pixmap(self, which, image, rect, dpr):
        key = (rect.width(), rect.height(), dpr, image.cacheKey())
        cached = self._pix.get(which)
        if cached is None or cached[0] != key:                   # redimensionnée UNE fois par taille / image
            pm = QPixmap.fromImage(image.scaled(round(rect.width() * dpr), round(rect.height() * dpr),
                                                Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            pm.setDevicePixelRatio(dpr)
            cached = self._pix[which] = (key, pm)
        return cached[1]

    def resizeEvent(self, event):
        self._place_toolbar()

    def _place_toolbar(self):
        self.toolbar.move(round((self.width() - self.toolbar.width()) / 2), self.height() - 16 - self.toolbar.height())

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        if self.before.isNull():
            return
        rect = self.image_rect()
        dpr = self.devicePixelRatioF()
        p.setPen(QPen(rgba("#ffffff", .06), 1))
        p.drawRect(rect.adjusted(-.5, -.5, .5, .5))
        p.drawPixmap(rect.topLeft(), self._pixmap("before", self.before, rect, dpr))
        p.setRenderHint(QPainter.Antialiasing)
        if self.after is not None:
            x = rect.x() + rect.width() * self.pos / 100
            p.save()
            p.setClipRect(QRectF(x, rect.y(), rect.right() - x, rect.height()))
            p.drawPixmap(rect.topLeft(), self._pixmap("after", self.after, rect, dpr))
            p.restore()
            p.fillRect(QRectF(x - 2, rect.y(), 4, rect.height()), rgba("#000000", .4))
            p.fillRect(QRectF(x - 1, rect.y(), 2, rect.height()), QColor(lk["strong_color"]))
            c = QPointF(x, rect.center().y())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lk["strong_color"]))
            p.drawEllipse(c, 16, 16)
            p.drawPixmap(QPointF(c.x() - 8, c.y() - 8), icon("wipe", lk["panel_color"], 16, dpr))
            self._tag(p, rect, "Avant", lk["text_color"], left=True)
            self._tag(p, rect, f"Après · {self.intensity} %", lk["accent_light"], left=False)
        elif self.message:
            f = font(lk, lk["font_size"])
            w = 14 + 16 + 10 + text_width(f, self.message) + 14
            box = QRectF(rect.center().x() - w / 2, rect.bottom() - 16 - 38, w, 38)
            p.setPen(QPen(QColor(lk["control_border"]), 1))
            p.setBrush(rgba(lk["bg_color"], .88))
            p.drawRoundedRect(box.adjusted(.5, .5, -.5, -.5), 10, 10)
            p.drawPixmap(QPointF(box.x() + 14, box.center().y() - 8), icon("alert", lk["accent_color"], 16, dpr))
            p.setFont(f)
            p.setPen(QColor(lk["text_color"]))
            p.drawText(box.adjusted(40, 0, -14, 0), Qt.AlignLeft | Qt.AlignVCenter, self.message)

    def _tag(self, p, rect, text, color, left):
        f = font(self.look, 11)
        w = text_width(f, text) + 16
        box = QRectF(rect.x() + 10 if left else rect.right() - 10 - w, rect.y() + 10, w, 21)
        p.setPen(Qt.NoPen)
        p.setBrush(rgba(self.look["bg_color"], .8))
        p.drawRoundedRect(box, 6, 6)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(box, Qt.AlignCenter, text)

    def _drag_to(self, x):
        rect = self.image_rect()
        if rect.width() > 0:
            self.posChanged.emit(max(0.0, min(100.0, (x - rect.x()) * 100 / rect.width())))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.after is not None and \
                self.image_rect().contains(event.position()):
            self._dragging = True
            self._drag_to(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._drag_to(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = False


class Steps(_Painted):
    """État en trois étapes : pastille 22 px (✓ faite, numéro accent en cours, numéro gris à venir), libellé, note."""

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.steps = []             # (état « done » / « current » / « todo », marque, libellé, note)
        self.setFixedHeight(3 * 22 + 2 * 8)

    def set_steps(self, steps):
        if steps != self.steps:
            self.steps = steps
            self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base, small = font(lk, lk["font_size"]), font(lk, 11)
        for k, (state, mark, label, note) in enumerate(self.steps):
            y = k * 30
            c = QPointF(11, y + 11)
            if state == "done":
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(lk["accent_color"]))
                ink, text = lk["accent_ink"], lk["text_color"]
            else:
                ring = lk["accent_color"] if state == "current" else lk["todo_ring"]
                p.setPen(QPen(QColor(ring), 1.5))
                p.setBrush(Qt.NoBrush)
                ink = lk["accent_color"] if state == "current" else lk["muted_color"]
                text = lk["strong_color"] if state == "current" else lk["muted_color"]
            p.drawEllipse(c, 10.25 if state != "done" else 11, 10.25 if state != "done" else 11)
            p.setFont(font(lk, 11, 600))
            p.setPen(QColor(ink))
            p.drawText(QRectF(0, y, 22, 22), Qt.AlignCenter, mark)
            p.setFont(small)
            p.setPen(QColor(lk["muted_color"]))
            note_w = text_width(small, note) + 2
            p.drawText(QRectF(self.width() - note_w, y, note_w, 22), Qt.AlignRight | Qt.AlignVCenter, note)
            p.setFont(base)
            p.setPen(QColor(text))
            p.drawText(QRectF(32, y, self.width() - 32 - note_w - 8, 22), Qt.AlignLeft | Qt.AlignVCenter, label)


class InfoBox(_Painted):
    """Encadré d'information (fond carte, icône i, texte 12 px qui passe à la ligne)."""

    def __init__(self, parent, look, text=""):
        super().__init__(parent, look)
        self.text = text
        self.setMinimumHeight(38)

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.updateGeometry()
            self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        f = font(self.look, 12)
        r = QFontMetricsF(f).boundingRect(QRectF(0, 0, max(10, width - 50), 1000), Qt.TextWordWrap, self.text)
        return max(38, round(r.height()) + 20)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(lk["card_color"]))
        p.drawRoundedRect(QRectF(self.rect()), lk["radius"], lk["radius"])
        p.drawPixmap(QPointF(12, 11), icon("info", lk["muted_color"], 16, self.devicePixelRatioF()))
        p.setFont(font(lk, 12))
        p.setPen(QColor(lk["label_color"]))
        p.drawText(QRectF(self.rect()).adjusted(38, 10, -12, -10), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                   self.text)


class Slider(_Painted):
    """Curseur 0-`maximum` couleur d'accent (piste, partie remplie, poignée) ; `valueChanged` pendant le geste.
    `detent` : cran (trait sur la piste) qui aimante la poignée à moins de `SNAP` px pendant le glisser."""
    valueChanged = Signal(int)
    SNAP = 6

    def __init__(self, parent, look, value=100, maximum=100, detent=None):
        super().__init__(parent, look)
        self.value, self.maximum, self.detent = int(value), int(maximum), detent
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def setValue(self, value):
        value = max(0, min(self.maximum, int(value)))
        if value != self.value:
            self.value = value
            self.update()

    def _set_from(self, x):
        span = max(1.0, self.width() - 16)
        value = round(max(0.0, min(1.0, (x - 8) / span)) * self.maximum)
        if self.detent is not None and abs(x - (8 + span * self.detent / self.maximum)) <= self.SNAP:
            value = self.detent
        if value != self.value:
            self.value = value
            self.update()
            self.valueChanged.emit(value)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(8, self.height() / 2 - 2, self.width() - 16, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(lk["control_border"]))
        p.drawRoundedRect(track, 2, 2)
        if self.detent is not None:                              # cran : trait vertical sur la piste
            d = track.x() + track.width() * self.detent / self.maximum
            p.fillRect(QRectF(d - .75, track.y() - 4, 1.5, track.height() + 8), QColor(lk["muted_color"]))
        x = track.x() + track.width() * self.value / self.maximum
        p.setBrush(QColor(lk["accent_color"]))
        p.drawRoundedRect(QRectF(track.x(), track.y(), x - track.x(), track.height()), 2, 2)
        p.drawEllipse(QPointF(x, self.height() / 2), 8, 8)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._set_from(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._set_from(event.position().x())

    def keyPressEvent(self, event):
        step = {Qt.Key_Left: -1, Qt.Key_Down: -1, Qt.Key_Right: 1, Qt.Key_Up: 1,
                Qt.Key_PageDown: -10, Qt.Key_PageUp: 10}.get(event.key())
        if step is None:
            return super().keyPressEvent(event)
        old = self.value
        self.setValue(self.value + step)
        if self.value != old:
            self.valueChanged.emit(self.value)


class Note(_Painted):
    """Texte 11 px atténué qui passe à la ligne ; `link` : lien 12 px couleur d'accent (clic = `clicked`)."""
    clicked = Signal()

    def __init__(self, parent, look, text, link=False):
        super().__init__(parent, look)
        self.text, self.link = text, link
        if link:
            self.setCursor(Qt.PointingHandCursor)

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.updateGeometry()
            self.update()

    def _font(self):
        return font(self.look, 12 if self.link else 11)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if not self.text:
            return 0
        r = QFontMetricsF(self._font()).boundingRect(QRectF(0, 0, max(10, width), 1000), Qt.TextWordWrap, self.text)
        return round(r.height()) + 1

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(200, self.heightForWidth(max(self.width(), 200)))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self._font())
        p.setPen(QColor(self.look["accent_color" if self.link else "muted_color"]))
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.text)

    def mouseReleaseEvent(self, event):
        if self.link and event.button() == Qt.LeftButton:
            self.clicked.emit()
