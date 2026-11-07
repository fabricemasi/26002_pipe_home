"""Palette de l'analyse colorimétrique (maquette « Analyse — Image 4207 », 2e version, 2026-10-31) : pastilles
jointives avec leurs nuances, barre de couverture, barres de couverture par couleur ; bouton « Localiser sur l'image » et
barre de rendu des couleurs isolées (sélection d'origine / aplat, autres couleurs ajustées / unies).

Widgets PEINTS (habillage `analysis_look`, posé par `set_look`) ; la logique de sélection est dans `analysis_ui.py`,
l'image recomposée dans `analysis_isolate.py`. Clic : choisir ; Ctrl + clic : ajouter / retirer (pastille, nuance)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from fm_video.analysis_widgets import Segmented, _Painted, font, fr, icon, rgba, text_width
from fm_video.matching_widgets import Slider

# Couleurs unies proposées pour les autres couleurs (maquette).
SOLIDS = (("#000000", "Noir"), ("#767676", "Gris moyen 18 %"), ("#ffffff", "Blanc"), ("#ff00ff", "Magenta"),
          ("#00c853", "Vert incrustation"))


def _ctrl(event) -> bool:
    return bool(event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))


class PaletteStrip(_Painted):
    """Pastilles jointives (filet clair), nuances de la couleur choisie en bas de sa pastille, barre de couverture,
    barres de couverture à l'échelle de la plus grande + pourcentages. Double-clic sur une pastille : copier le HEX."""
    tilePicked = Signal(int, bool)          # couleur, Ctrl
    subPicked = Signal(int, int, bool)      # couleur, nuance, Ctrl
    copied = Signal(str)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.colors = []            # dicts triés : i, hex, L, weight, subs (dicts : hex, weight)
        self.current = None
        self.picks = set()
        self.show_subs = True
        self.hover = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._look_changed()

    def _look_changed(self):
        lk = self.look
        self.setFixedHeight(lk["swatch_height"] + 2 + 10 + lk["coverage_height"] + 10 + lk["bars_height"] + 4 + 15)

    def set_data(self, colors, current, picks, show_subs):
        self.colors, self.current, self.picks, self.show_subs = colors, current, set(picks), show_subs
        self.update()

    # -- géométrie --
    def _tiles(self):
        n = len(self.colors)
        if not n:
            return []
        w = (self.width() - 2 - (n - 1)) / n
        return [QRectF(1 + i * (w + 1), 1, w, self.look["swatch_height"]) for i in range(n)]

    def _sub_rects(self, tile, count):
        # Carrés de la maquette (6 par pastille), jamais plus hauts que le tiers de la pastille (demande de
        # l'utilisateur : avec peu de couleurs, les pastilles larges donnaient des nuances trop hautes).
        size = min((tile.width() - 5) / 6, tile.height() / 3)
        w = (tile.width() - (count - 1)) / max(1, count)
        y = tile.bottom() - size
        return [QRectF(tile.x() + k * (w + 1), y, w, size) for k in range(count)]

    def _hit(self, pos):
        for i, (c, tile) in enumerate(zip(self.colors, self._tiles())):
            if not tile.adjusted(-.5, -1, .5, 0).contains(pos):
                continue
            if c["i"] == self.current and self.show_subs:
                for k, rect in enumerate(self._sub_rects(tile, len(c["subs"]))):
                    if rect.adjusted(-.5, -1, .5, 0).contains(pos):
                        return i, k
            return i, None
        bar, segments = self._segments()                         # 2e ligne : la barre de couverture
        if bar.adjusted(0, -3, 0, 3).contains(pos):
            for i, (_c, rect) in enumerate(segments):
                if pos.x() <= rect.right() + 1:
                    return i, None
        return None

    # -- peinture --
    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        tiles = self._tiles()
        if not tiles:
            return
        strong = QColor(lk["strong_color"])
        p.fillRect(QRectF(0, 0, self.width(), lk["swatch_height"] + 2), QColor(lk["swatch_frame"]))
        mono = font(lk, 10, mono=True)
        p.setFont(mono)
        for i, (c, tile) in enumerate(zip(self.colors, tiles)):
            p.fillRect(tile, QColor(c["hex"]))
            group = {c["i"] * 6 + k for k in range(len(c["subs"]))}
            on = c["i"] == self.current
            subs = on and self.show_subs
            pad = (min((tile.width() - 5) / 6, tile.height() / 3) + 9) if subs else 6
            if (on or i == self.hover) and text_width(mono, c["hex"]) <= tile.width() - 2:
                p.setPen(QColor("#1a1814" if c["L"] > .62 else "#f2f0eb"))
                p.drawText(tile.adjusted(0, 0, 0, -pad), Qt.AlignHCenter | Qt.AlignBottom, c["hex"].upper())
            if subs:
                rects = self._sub_rects(tile, len(c["subs"]))
                p.fillRect(QRectF(tile.x(), rects[0].y() - 1, tile.width(), rects[0].height() + 1), strong)
                every = group <= self.picks
                for k, (sub, rect) in enumerate(zip(c["subs"], rects)):
                    p.fillRect(rect, QColor(sub["hex"]))
                    if c["i"] * 6 + k in self.picks and not every:
                        self._ring(p, rect, strong)
            if group & self.picks:
                self._ring(p, tile, strong)
        # Barre de couverture : part de l'image assignée à chaque couleur ; cadre blanc d'1 px, angles droits, posé
        # AUTOUR du segment des couleurs choisies (non coupé par la barre) : demande de l'utilisateur.
        bar, segments = self._segments()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(bar, 4, 4)
        p.setClipPath(clip)
        for c, rect in segments:
            p.fillRect(rect.adjusted(0, 0, .4, 0), QColor(c["hex"]))
        p.restore()
        p.setRenderHint(QPainter.Antialiasing, False)                  # trait net d'1 px
        p.setPen(QPen(strong, 1))
        p.setBrush(Qt.NoBrush)
        for c, rect in segments:
            if {c["i"] * 6 + k for k in range(len(c["subs"]))} & self.picks:
                if rect.width() < 4:                             # part minime : 4 px au moins
                    rect = QRectF(rect.center().x() - 2, rect.y(), 4, rect.height())
                left = max(0, round(rect.left()) - 1)
                right = min(self.width() - 1, round(rect.right()))
                p.drawRect(QRect(left, round(rect.top()) - 1, right - left, round(rect.height()) + 1))
        self._paint_bars(p, bar.bottom() + 10)

    def _segments(self):
        """Barre de couverture et segment (couleur, rectangle) de chaque couleur."""
        lk = self.look
        bar = QRectF(0, lk["swatch_height"] + 2 + 10, self.width(), lk["coverage_height"])
        total = sum(c["weight"] for c in self.colors) or 1.0
        usable = bar.width() - (len(self.colors) - 1)
        out, x = [], bar.x()
        for c in self.colors:
            w = usable * c["weight"] / total
            out.append((c, QRectF(x, bar.y(), w, bar.height())))
            x += w + 1
        return bar, out

    @staticmethod
    def _ring(p, rect, color):
        """Anneau intérieur de 2 px (maquette : inset 0 0 0 2px)."""
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect.adjusted(1, 1, -1, -1))

    def _paint_bars(self, p, top):
        lk = self.look
        n, gap, area = len(self.colors), lk["swatch_gap"], lk["bars_height"]
        w = (self.width() - gap * (n - 1)) / n
        biggest = max(c["weight"] for c in self.colors) or 1.0
        p.setRenderHint(QPainter.Antialiasing)
        mono = font(lk, 11, mono=True)
        bold = font(lk, 11, 600, mono=True)
        for i, c in enumerate(self.colors):
            x = i * (w + gap)
            p.setPen(QColor(lk["control_border"]))
            p.drawLine(QPointF(x, top + area - .5), QPointF(x + w, top + area - .5))
            h = max(2, round(c["weight"] / biggest * (area - 4)))
            bar = QRectF(x + w * .15, top + area - 1 - h, w * .7, h)
            path = QPainterPath()
            path.addRoundedRect(bar.adjusted(0, 0, 0, 3), 3, 3)          # coins arrondis en haut seulement
            p.save()
            p.setClipRect(bar)
            p.setPen(QPen(rgba("#ffffff", .14), 1))
            p.setBrush(QColor(c["hex"]))
            p.drawPath(path.translated(0, 0))
            p.restore()
            on = c["i"] == self.current
            p.setFont(bold if on else mono)
            p.setPen(QColor(lk["strong_color" if on else "muted_color"]))
            p.drawText(QRectF(x - 2, top + area + 4, w + 4, 15), Qt.AlignCenter, f'{fr(c["weight"] * 100, 1)} %')

    # -- souris --
    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        i = hit[0] if hit else None
        if hit:
            c = self.colors[i]
            tip = (f'Nuance {c["subs"][hit[1]]["hex"].upper()}' if hit[1] is not None
                   else f'{c["hex"].upper()}, {fr(c["weight"] * 100, 1)} %')
            if tip != self.toolTip():
                self.setToolTip(tip)
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, event):
        if self.hover is not None:
            self.hover = None
            self.update()

    def mousePressEvent(self, event):
        hit = self._hit(event.position())
        if hit is None or event.button() != Qt.LeftButton:
            return
        i, k = hit
        if k is None:
            self.tilePicked.emit(self.colors[i]["i"], _ctrl(event))
        else:
            self.subPicked.emit(self.colors[i]["i"], k, _ctrl(event))

    def mouseDoubleClickEvent(self, event):
        hit = self._hit(event.position())
        if hit is not None and hit[1] is None:
            self.copied.emit(self.colors[hit[0]]["hex"].upper())


class PillToggle(_Painted):
    """Bouton bascule arrondi (« Localiser sur l'image ») : 30 px, icône 14 px, texte 12 px."""
    toggled = Signal(bool)

    def __init__(self, parent, look, text, icon_name):
        super().__init__(parent, look)
        self.text, self.icon_name, self.on = text, icon_name, False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)

    def set_on(self, on):
        if bool(on) != self.on:
            self.on = bool(on)
            self.update()

    def sizeHint(self):
        return QSize(round(12 + 14 + 8 + text_width(font(self.look, 12), self.text) + 12), 30)

    minimumSizeHint = sizeHint

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(lk["toggle_on_border" if self.on else "control_border"]), 1))
        p.setBrush(QColor(lk["active_color"]) if self.on else Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 15, 15)
        ink = lk["strong_color" if self.on else "muted_color"]
        p.drawPixmap(QPointF(12, 8), icon(self.icon_name, ink, 14, self.devicePixelRatioF()))
        p.setFont(font(lk, 12))
        p.setPen(QColor(ink))
        p.drawText(QRectF(34, 0, self.width() - 34, 30), Qt.AlignLeft | Qt.AlignVCenter, self.text)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.on = not self.on
            self.update()
            self.toggled.emit(self.on)


class _Text(_Painted):
    """Libellé 11 px atténué de la barre de rendu, à la largeur de son texte."""

    def __init__(self, parent, look, text):
        super().__init__(parent, look)
        self.text = text
        self._look_changed()

    def _look_changed(self):
        self.setFixedSize(round(text_width(font(self.look, 11), self.text) + 2), 34)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(font(self.look, 11))
        p.setPen(QColor(self.look["muted_color"]))
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, self.text)


class _Divider(_Painted):
    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.setFixedSize(1, 34)

    def paintEvent(self, event):
        QPainter(self).fillRect(QRectF(0, 6, 1, 22), QColor(self.look["control_border"]))


class SliderField(_Painted):
    """« Luminosité ━━●━━ 30 % » : libellé 12 px, curseur de 140 px, valeur mono."""
    valueChanged = Signal(int)

    def __init__(self, parent, look, label, value, maximum):
        super().__init__(parent, look)
        self.label = label
        self.slider = Slider(self, look, value, maximum, detent=100)          # cran à 100 % (demande de l'utilisateur)
        self.slider.valueChanged.connect(self._changed)
        self._look_changed()

    def _label_w(self):
        return text_width(font(self.look, 12), self.label)

    def _look_changed(self):
        self.slider.set_look(self.look)
        x = round(self._label_w()) + 8
        self.slider.setGeometry(x - 8, 5, 140 + 16, 24)                  # piste de 140 px (8 px de poignée de part et d'autre)
        self.setFixedSize(x + 140 + 8 + 40, 34)

    def setValue(self, value):
        self.slider.setValue(value)
        self.update()

    def value(self):
        return self.slider.value

    def _changed(self, value):
        self.update()
        self.valueChanged.emit(value)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setFont(font(lk, 12))
        p.setPen(QColor(lk["label_color"]))
        p.drawText(QRectF(0, 0, self._label_w() + 2, 34), Qt.AlignLeft | Qt.AlignVCenter, self.label)
        p.setFont(font(lk, 12, mono=True))
        p.setPen(QColor(lk["strong_color"]))
        p.drawText(QRectF(self.width() - 40, 0, 40, 34), Qt.AlignLeft | Qt.AlignVCenter, f"{self.slider.value} %")


class SolidPicker(_Painted):
    """Couleurs unies : 5 pastilles rondes de 14 px (demande de l'utilisateur : bien plus petites que les 24 px de la
    maquette), « Autre » (sélecteur de couleur de l'appli) et son HEX. L'anneau de la couleur choisie (rayon + 4 px)
    tient dans le widget : le 1er centre est décalé de ce rayon (avant : anneau coupé à gauche)."""
    R = 7                       # rayon d'une pastille
    RING = R + 4                # rayon extérieur de l'anneau (2 px de fond de carte + 2 px d'accent)
    picked = Signal(str)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.color = "#000000"
        self._popup = None
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._look_changed()

    def _rects(self):
        f = font(self.look, 12)
        pitch = 2 * self.RING + 2
        circles = [QRectF(self.RING - self.R + i * pitch, 17 - self.R, 2 * self.R, 2 * self.R)
                   for i in range(len(SOLIDS))]
        x = circles[-1].center().x() + self.RING + 6
        other = QRectF(x + text_width(f, "Autre") + 6, 4, 32, 26)
        return circles, x, other

    def _look_changed(self):
        _c, _x, other = self._rects()
        self.setFixedSize(round(other.right() + 8 + text_width(font(self.look, 11, mono=True), "#FFFFFF") + 2), 34)

    def set_color(self, color):
        if color != self.color:
            self.color = color
            self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        circles, x, other = self._rects()
        for (hex_color, _label), rect in zip(SOLIDS, circles):
            c = rect.center()
            if hex_color == self.color.lower():
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(lk["accent_color"]))
                p.drawEllipse(c, self.RING, self.RING)
                p.setBrush(QColor(lk["card_color"]))
                p.drawEllipse(c, self.R + 2, self.R + 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(hex_color))
            p.drawEllipse(c, self.R, self.R)
            if hex_color != self.color.lower():
                p.setPen(QPen(rgba("#ffffff", .25), 1))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, self.R - .5, self.R - .5)
        p.setFont(font(lk, 12))
        p.setPen(QColor(lk["label_color"]))
        p.drawText(QRectF(x, 0, other.x() - x, 34), Qt.AlignLeft | Qt.AlignVCenter, "Autre")
        p.setPen(QPen(QColor(lk["control_border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(other.adjusted(.5, .5, -.5, -.5), 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(other.adjusted(4, 4, -4, -4), 2, 2)
        p.setFont(font(lk, 11, mono=True))
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(QRectF(other.right() + 8, 0, 80, 34), Qt.AlignLeft | Qt.AlignVCenter, self.color.upper())

    def mouseMoveEvent(self, event):
        circles, _x, other = self._rects()
        tip = next((label for (_h, label), r in zip(SOLIDS, circles) if r.contains(event.position())), "")
        if other.contains(event.position()):
            tip = "Autre couleur"
        if tip != self.toolTip():
            self.setToolTip(tip)

    def mousePressEvent(self, event):
        circles, _x, other = self._rects()
        for (hex_color, _label), rect in zip(SOLIDS, circles):
            if rect.adjusted(-4, -4, 4, 4).contains(event.position()):
                self.picked.emit(hex_color)
                return
        if other.contains(event.position()):
            self._pick_other()

    def _pick_other(self):
        """Sélecteur de couleur de l'appli (fm_theme), en direct ; Annuler rend la couleur de départ."""
        before = self.color
        try:
            from fm_theme.widgets import _ColorPickerPopup
        except Exception:                                    # noqa: BLE001 - appli absente : sélecteur de Qt
            from PySide6.QtWidgets import QColorDialog
            color = QColorDialog.getColor(QColor(self.color), self, "Autre couleur")
            if color.isValid():
                self.picked.emit(color.name())
            return
        self._popup = _ColorPickerPopup(self.color, "Autres couleurs", self)
        self._popup.colorChanged.connect(self.picked)
        self._popup.committed.connect(self.picked)
        self._popup.cancelled.connect(lambda: self.picked.emit(before))
        self._popup.show_near(self)


class IsoBar(_Painted):
    """Carte « Rendu des autres couleurs » : Sélection [Couleurs d'origine | Aplat] · Autres couleurs [Ajustées |
    Unies] + Luminosité / Saturation, ou couleurs unies. Les éléments passent à la ligne (10 px entre les lignes,
    20 px entre les éléments). Atténuée et inactive quand « Localiser sur l'image » est coupé."""
    pickModeChanged = Signal(str)
    restChanged = Signal(str)
    lightChanged = Signal(int)
    satChanged = Signal(int)
    colorPicked = Signal(str)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.pick_mode = Segmented(self, look, (("orig", "Couleurs d'origine"), ("flat", "Aplat")), "orig", "small")
        self.pick_mode.picked.connect(self.pickModeChanged)
        self.rest = Segmented(self, look, (("adj", "Ajustées"), ("uni", "Unies")), "adj", "small")
        self.rest.picked.connect(self._rest)
        self.light = SliderField(self, look, "Luminosité", 30, 150)
        self.light.valueChanged.connect(self.lightChanged)
        self.sat = SliderField(self, look, "Saturation", 0, 200)
        self.sat.valueChanged.connect(self.satChanged)
        self.solids = SolidPicker(self, look)
        self.solids.picked.connect(self.colorPicked)
        self._items = [_Text(self, look, "Sélection"), self.pick_mode, _Divider(self, look),
                       _Text(self, look, "Autres couleurs"), self.rest, self.light, self.sat, self.solids]
        self._effect = None
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._set_rest_visible("adj")

    def set_look(self, look):
        super().set_look(look)
        for w in self._items:
            w.set_look(look)
        self._relayout()

    def set_state(self, pick_mode, rest, light, sat, color, swatch, enabled):
        self.pick_mode.set_current(pick_mode)
        self.pick_mode.set_swatch("flat", swatch)
        self.rest.set_current(rest)
        self._set_rest_visible(rest)
        if self.light.value() != light:
            self.light.setValue(light)
        if self.sat.value() != sat:
            self.sat.setValue(sat)
        self.solids.set_color(color)
        if enabled != self.isEnabled() or (self._effect is None) != enabled:
            self.setEnabled(enabled)
            if enabled:
                self.setGraphicsEffect(None)
                self._effect = None
            else:                                           # maquette : opacité 0,35, rien de cliquable
                self._effect = QGraphicsOpacityEffect(self)
                self._effect.setOpacity(.35)
                self.setGraphicsEffect(self._effect)

    def _rest(self, rest):
        self._set_rest_visible(rest)
        self.restChanged.emit(rest)

    def _set_rest_visible(self, rest):
        for w, on in ((self.light, rest == "adj"), (self.sat, rest == "adj"), (self.solids, rest == "uni")):
            w.setVisible(on)
        self._relayout()

    # -- disposition en ligne avec retour à la ligne --
    def _place(self, width, apply):
        x, y, row_h = 12, 8, 0
        for w in self._items:
            if w.isHidden():
                continue
            size = w.sizeHint() if isinstance(w, Segmented) else w.size()
            if x > 12 and x + size.width() > width - 12:
                x, y = 12, y + row_h + 10
                row_h = 0
            if apply:
                w.setGeometry(x, y + (34 - size.height()) // 2, size.width(), size.height())
            x += size.width() + 20
            row_h = max(row_h, 34)
        return y + row_h + 8

    def _relayout(self):
        if self.width() > 0:
            self._place(self.width(), True)
        self.updateGeometry()

    # Hauteur selon la largeur (jamais figée : une largeur provisoire étroite ne doit pas grandir la fenêtre).
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(width, False)

    def sizeHint(self):
        return QSize(600, self._place(600, False))

    def minimumSizeHint(self):
        return QSize(200, 50)

    def resizeEvent(self, event):
        self._place(self.width(), True)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(lk["control_border"]), 1))
        p.setBrush(QColor(lk["card_color"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 10, 10)
