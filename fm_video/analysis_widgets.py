"""Widgets PEINTS de l'analyse colorimétrique (maquette « Analyse — Image 4207 »). Habillage : `analysis_look.py`
(dict `look` posé par `set_look`) ; assemblage et données : `analysis_ui.py`.

Fluidité : une peinture ne calcule rien. Les tracés de l'histogramme, l'image redimensionnée du viewer, l'image du
waveform et les icônes sont gardés tant que leurs entrées (taille, données, couleurs) n'ont pas changé ; un clic ne
repeint que le widget touché."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from fm_video.analysis_look import LOOK

_WEIGHTS = {400: QFont.Weight.Normal, 500: QFont.Weight.Medium, 600: QFont.Weight.DemiBold}
_FONTS: dict = {}
_FAMILIES: set | None = None


def _family(name: str, mono: bool) -> str:
    global _FAMILIES
    if _FAMILIES is None:
        _FAMILIES = set(QFontDatabase.families())
    for candidate in (name, *(("Cascadia Mono", "Consolas", "Courier New") if mono else ())):
        if candidate in _FAMILIES:
            return candidate
    return QApplication.font().family()


def font(look: dict, px: int, weight: int = 400, mono: bool = False, spacing: float = 0.0) -> QFont:
    """Police de la maquette (Inter / JetBrains Mono, sinon la plus proche installée), gardée en cache."""
    key = (look["mono_family"] if mono else look["font_family"], mono, px, weight, spacing)
    f = _FONTS.get(key)
    if f is None:
        f = QFont(_family(key[0], mono))
        f.setPixelSize(px)
        f.setWeight(_WEIGHTS.get(weight, QFont.Weight.Normal))
        if spacing:
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        _FONTS[key] = f
    return f


def rgba(hex_color: str, alpha: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def text_width(f: QFont, text: str) -> float:
    return QFontMetricsF(f).horizontalAdvance(text)


def fr(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


# --- icônes de la maquette (SVG 24 x 24, trait = couleur du texte) ---------------------------------------------------
_ICONS = {
    "back": '<path d="M15 18l-6-6 6-6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7"/>'
            '<path d="M12 17h.01"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
    "pipette": '<path d="M2 22l1-1h3l9-9"/><path d="M3 21v-3l9-9"/>'
               '<path d="M15 6l3-3a2.1 2.1 0 0 1 3 3l-3 3 .5.5a1.4 1.4 0 0 1-2 2L12 7a1.4 1.4 0 0 1 2-2z"/>',
    "region": '<rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 3"/>',
    "whole": '<path d="M4 9V4h5"/><path d="M20 9V4h-5"/><path d="M4 15v5h5"/><path d="M20 15v5h-5"/>',
    "arrow": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "upload": '<path d="M12 20V9"/><path d="M7 14l5-5 5 5"/><path d="M5 4h14"/>',
    "wipe": '<path d="M9 6l-6 6 6 6"/><path d="M15 6l6 6-6 6"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
}
_ICON_CACHE: dict = {}


def icon(name: str, color: str, size: int, dpr: float) -> QPixmap:
    key = (name, color, size, dpr)
    pm = _ICON_CACHE.get(key)
    if pm is None:
        from PySide6.QtSvg import QSvgRenderer
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="2" '
               'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (color, _ICONS[name]))
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        QSvgRenderer(svg.encode()).render(p)
        p.end()
        pm.setDevicePixelRatio(dpr)
        _ICON_CACHE[key] = pm
    return pm


class _Painted(QWidget):
    """Base : habillage `look`, repeint seulement s'il a changé."""

    def __init__(self, parent=None, look=None):
        super().__init__(parent)
        self.look = look or LOOK

    def set_look(self, look: dict):
        if look["key"] != self.look["key"]:
            self.look = look
            self._look_changed()
            self.updateGeometry()
            self.update()

    def _look_changed(self):
        pass


# --- boutons, sélecteurs ----------------------------------------------------------------------------------------------
class Button(_Painted):
    """Bouton de la maquette : « outline » (contour), « primary » (fond accent ; gris tant qu'il est inactif),
    « icon » (carré à contour), « small » (contour, texte 12 px, sans icône). `wide` : contenu centré."""
    clicked = Signal()

    def __init__(self, parent, look, text="", icon_name=None, kind="outline", height_key="button_height",
                 wide=False, ink_key=None):
        super().__init__(parent, look)
        self.text, self.icon_name, self.kind, self.height_key = text, icon_name, kind, height_key
        self.wide, self.ink_key, self.active = wide, ink_key, True
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)

    def set_active(self, on: bool):
        """Inactif : couleurs « indisponible » de la maquette, clic ignoré."""
        if bool(on) != self.active:
            self.active = bool(on)
            self.setCursor(Qt.PointingHandCursor if on else Qt.ForbiddenCursor)
            self.update()

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.updateGeometry()
            self.update()

    def _height(self):
        return self.look[self.height_key] if isinstance(self.height_key, str) else self.height_key

    def _font(self):
        px = 12 if self.kind == "small" else self.look["font_size"]
        return font(self.look, px, 600 if self.kind == "primary" else 400)

    def sizeHint(self):
        h = self._height()
        if self.kind == "icon":
            return QSize(h, h)
        if self.kind == "small":
            return QSize(round(24 + text_width(self._font(), self.text)), h)
        pad_l, pad_r = (8, 12) if self.kind == "outline" and not self.wide else (14, 14)
        return QSize(round(pad_l + 16 + 8 + text_width(self._font(), self.text) + pad_r), h)

    minimumSizeHint = sizeHint

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        radius = lk["radius"]
        if self.kind == "primary":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lk["accent_color" if self.active else "disabled_bg"]))
            ink = lk["accent_ink" if self.active else "disabled_fg"]
        else:
            p.setPen(QPen(QColor(lk["control_border"]), 1))
            p.setBrush(Qt.NoBrush)
            ink = lk[self.ink_key or "label_color"]
        p.drawRoundedRect(r, radius, radius)
        size = 14 if self.icon_name == "copy" else 16
        dpr = self.devicePixelRatioF()
        if self.kind == "icon":
            p.drawPixmap(QPointF((self.width() - size) / 2, (self.height() - size) / 2),
                         icon(self.icon_name, ink, size, dpr))
            return
        f = self._font()
        p.setFont(f)
        if self.kind == "small":
            p.setPen(QColor(ink))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, self.text)
            return
        x = 8 if self.kind == "outline" and not self.wide else 14
        if self.wide:                                            # icône + texte centrés
            x = (self.width() - (16 + 8 + text_width(f, self.text))) / 2
        if self.icon_name:
            p.drawPixmap(QPointF(x, (self.height() - 16) / 2), icon(self.icon_name, ink, 16, dpr))
            x += 16 + 8
        p.setPen(QColor(ink))
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.active and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self.active:
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class Segmented(_Painted):
    """Sélecteur segmenté (onglets Analyse / Matching, types de scope). `style` : « tabs », « scopes », « res » ou
    « small » (rendu des couleurs isolées : 28 px, 12 px, largeur du texte). `swatches` : {segment: couleur}
    (pastille 10 px devant le texte, « Aplat »)."""
    picked = Signal(str)

    def __init__(self, parent, look, items, current, style="tabs"):
        super().__init__(parent, look)
        self.items, self.current, self.style = list(items), current, style
        self.swatches = {}
        self.setCursor(Qt.PointingHandCursor)

    def _geom(self):
        if self.style == "tabs":
            return 32, 7, 10, 16, self.look["font_size"]
        if self.style == "small":
            return 28, 6, 8, 12, 12
        return (32, 6, 8, 0, 12) if self.style == "res" else (30, 6, 8, 0, 12)

    def _natural(self):
        return self.style in ("tabs", "small")

    def _font(self):
        """« res » (résolution de la LUT) : chiffres mono 12 px ; « small » : 400 ; sinon 500."""
        return font(self.look, self._geom()[4], 400 if self.style in ("res", "small") else 500,
                    mono=self.style == "res")

    def _item_width(self, f, item_id, label):
        return text_width(f, label) + 2 * self._geom()[3] + (16 if item_id in self.swatches else 0)

    def set_swatch(self, item_id, color):
        if self.swatches.get(item_id) != color:
            self.swatches[item_id] = color
            self.update()

    def sizeHint(self):
        item_h, _r, _R, pad, px = self._geom()
        f = self._font()
        w = sum(self._item_width(f, i, label) for i, label in self.items) + 2 * (len(self.items) - 1) + 6
        return QSize(round(w) + 2, item_h + 8)

    def minimumSizeHint(self):
        # Les types de scope se partagent la largeur de l'inspecteur : jamais de largeur imposée.
        return QSize(60, self._geom()[0] + 8) if not self._natural() else self.sizeHint()

    def _rects(self):
        item_h, _r, _R, pad, px = self._geom()
        inner = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if not self._natural():
            w = (inner.width() - 2 * (len(self.items) - 1)) / len(self.items)
            return [QRectF(inner.x() + i * (w + 2), inner.y(), w, item_h) for i in range(len(self.items))]
        f = self._font()
        rects, x = [], inner.x()
        for item_id, label in self.items:
            w = self._item_width(f, item_id, label)
            rects.append(QRectF(x, inner.y(), w, item_h))
            x += w + 2
        return rects

    def set_current(self, current):
        if current != self.current:
            self.current = current
            self.update()

    def paintEvent(self, event):
        lk = self.look
        item_h, r, R, _pad, px = self._geom()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(lk["line_color"]), 1))
        p.setBrush(QColor(lk["well_color"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), R, R)
        p.setFont(self._font())
        for (item_id, label), rect in zip(self.items, self._rects()):
            on = item_id == self.current
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(lk["active_color"]))
                p.drawRoundedRect(rect, r, r)
            text_rect = rect
            if item_id in self.swatches:
                chip = QRectF(rect.x() + self._geom()[3], rect.center().y() - 5, 10, 10)
                p.setPen(QPen(rgba("#ffffff", .25), 1))
                p.setBrush(QColor(self.swatches[item_id]))
                p.drawRoundedRect(chip.adjusted(.5, .5, -.5, -.5), 2, 2)
                text_rect = rect.adjusted(16, 0, 0, 0)
            p.setPen(QColor(lk["strong_color"] if on else lk["muted_color"]))
            p.drawText(text_rect, Qt.AlignCenter, label)

    def mousePressEvent(self, event):
        for (item_id, _label), rect in zip(self.items, self._rects()):
            if rect.contains(event.position()):
                if item_id != self.current:
                    self.set_current(item_id)
                    self.picked.emit(item_id)
                return


class Title(_Painted):
    """Titre de section (majuscules 12 px, 600, interlettrage 0,06 em) + légende à droite (11 px, atténuée)."""

    def __init__(self, parent, look, text, caption=""):
        super().__init__(parent, look)
        self.text, self.caption = text, caption
        self.setFixedHeight(18)

    def set_text(self, text, caption=None):
        if text != self.text or (caption is not None and caption != self.caption):
            self.text = text
            self.caption = self.caption if caption is None else caption
            self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setFont(font(lk, 12, 600, spacing=0.72))
        p.setPen(QColor(lk["label_color"]))
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, self.text.upper())
        if self.caption:
            p.setFont(font(lk, 11))
            p.setPen(QColor(lk["muted_color"]))
            p.drawText(QRectF(self.rect()), Qt.AlignRight | Qt.AlignVCenter, self.caption)


class Caption(_Painted):
    """Légende 11 px atténuée, une ligne (coupée par « … » si trop longue)."""

    def __init__(self, parent, look, text=""):
        super().__init__(parent, look)
        self.text = text
        self.setFixedHeight(16)

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        f = font(self.look, 11)
        p.setFont(f)
        p.setPen(QColor(self.look["muted_color"]))
        text = QFontMetricsF(f).elidedText(self.text, Qt.ElideRight, self.width())
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, text)


class Section(_Painted):
    """Zone de l'inspecteur / de la palette : fond, filet haut ou bas ; les enfants sont posés par un layout."""

    def __init__(self, parent, look, bg=None, top=False, bottom=True):
        super().__init__(parent, look)
        self.bg_key, self.top, self.bottom = bg, top, bottom

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        if self.bg_key:
            p.fillRect(self.rect(), QColor(lk[self.bg_key]))
        p.setPen(QColor(lk["line_color"]))
        if self.top:
            p.drawLine(0, 0, self.width(), 0)
        if self.bottom:
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class TitleBlock(_Painted):
    """Titre de l'image (14 px, 600) et sous-titre (11 px) de la barre du haut."""

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.title, self.subtitle = "", ""
        self.setMinimumWidth(60)

    def set_texts(self, title, subtitle):
        if (title, subtitle) != (self.title, self.subtitle):
            self.title, self.subtitle = title, subtitle
            self.updateGeometry()
            self.update()

    def sizeHint(self):
        w = max(text_width(font(self.look, 14, 600), self.title), text_width(font(self.look, 11), self.subtitle))
        return QSize(round(w) + 2, 36)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        f = font(lk, 14, 600)
        p.setFont(f)
        p.setPen(QColor(lk["strong_color"]))
        p.drawText(QRectF(0, 0, self.width(), 20), Qt.AlignLeft | Qt.AlignBottom,
                   QFontMetricsF(f).elidedText(self.title, Qt.ElideRight, self.width()))
        f = font(lk, 11)
        p.setFont(f)
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(QRectF(0, 20, self.width(), 16), Qt.AlignLeft | Qt.AlignTop,
                   QFontMetricsF(f).elidedText(self.subtitle, Qt.ElideRight, self.width()))


class Bar(_Painted):
    """Barre du haut (fond panneau, filet bas) ou barre d'état (fond pied, filet haut, deux textes)."""

    def __init__(self, parent, look, footer=False):
        super().__init__(parent, look)
        self.footer = footer
        self.left = self.right = ""
        if footer:
            self.setFixedHeight(30)

    def set_texts(self, left, right):
        if (left, right) != (self.left, self.right):
            self.left, self.right = left, right
            self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(lk["footer_color" if self.footer else "panel_color"]))
        p.setPen(QColor(lk["line_color"]))
        y = 0 if self.footer else self.height() - 1
        p.drawLine(0, y, self.width(), y)
        if self.footer:
            p.setFont(font(lk, 11))
            p.setPen(QColor(lk["muted_color"]))
            r = QRectF(self.rect()).adjusted(16, 0, -16, 0)
            right_w = text_width(p.font(), self.right) + 2
            p.drawText(r.adjusted(0, 0, -right_w - 16, 0), Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetricsF(p.font()).elidedText(self.left, Qt.ElideRight, r.width() - right_w - 16))
            p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, self.right)


# --- viewer -----------------------------------------------------------------------------------------------------------
TOOLS = (("P", "Pipette", "pipette"), ("R", "Région", "region"), ("I", "Image entière", "whole"))
BG_LABELS = ("Noir", "Gris foncé", "Gris moyen 18 %")
RENDERS = (("orig", "Original"), ("pal", "Palette seule"))
STRIP = ("#2e2f28", "#85563b", "#a5966a", "#d3cebb")      # pictogramme « Palette seule » tant qu'il n'y a pas de palette


class Toolbar(_Painted):
    """Outils du viewer (pipette, région, image entière), rendu de l'image (original / palette seule) et fond du viewer,
    posés en bas au centre de l'image."""
    toolPicked = Signal(str)
    bgPicked = Signal(int)
    renderPicked = Signal(str)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.tool, self.bg, self.render = "P", 1, "orig"
        self.strip = STRIP
        self._hits = []
        self.setCursor(Qt.PointingHandCursor)
        self._relayout()

    def _look_changed(self):
        self._relayout()

    def set_state(self, tool, bg, render="orig"):
        if (tool, bg, render) != (self.tool, self.bg, self.render):
            self.tool, self.bg, self.render = tool, bg, render
            self.update()

    def set_strip(self, colors):
        """Quatre couleurs de la palette pour le pictogramme « Palette seule »."""
        colors = tuple(colors) or STRIP
        if colors != self.strip:
            self.strip = colors
            self.update()

    def _relayout(self):
        """Rectangles des boutons (une fois par habillage) et taille du bandeau."""
        f = font(self.look, self.look["font_size"])
        hits, x, y = [], 6.0, 6.0
        for tool_id, label, _icon in TOOLS:
            w = 10 + 15 + 6 + text_width(f, label) + 10
            hits.append(("tool", tool_id, QRectF(x, y, w, 34)))
            x += w + 2
        x += 10                                          # 12 de séparation (-2 du dernier écart)
        self._dividers = [x]
        x += 1 + 12
        for render_id, label in RENDERS:
            w = 10 + (18 + 6 if render_id == "pal" else 0) + text_width(f, label) + 10
            hits.append(("render", render_id, QRectF(x, y, w, 34)))
            x += w + 2
        x += 10
        self._dividers.append(x)
        x += 1 + 12
        self._fond = QRectF(x, y, text_width(font(self.look, 11), "Fond") + 8, 34)
        x += self._fond.width() + 6
        for i in range(3):
            hits.append(("bg", i, QRectF(x, y + 6, 22, 22)))
            x += 22 + 6
        self._hits = hits
        self.setFixedSize(round(x - 6 + 6 + 6), 46)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(lk["control_border"]), 1))
        p.setBrush(rgba(lk["panel_color"], .92))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12, 12)
        dpr = self.devicePixelRatioF()
        f = font(lk, lk["font_size"])
        for kind, item, rect in self._hits:
            if kind == "tool":
                on = item == self.tool
                if on:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(lk["active_color"]))
                    p.drawRoundedRect(rect, 8, 8)
                ink = lk["strong_color"] if on else lk["muted_color"]
                label, name = next((lab, ic) for t, lab, ic in TOOLS if t == item)
                p.drawPixmap(QPointF(rect.x() + 10, rect.center().y() - 7.5), icon(name, ink, 15, dpr))
                p.setFont(f)
                p.setPen(QColor(ink))
                p.drawText(rect.adjusted(31, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, label)
            elif kind == "render":
                on = item == self.render
                if on:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(lk["active_color"]))
                    p.drawRoundedRect(rect, 8, 8)
                x = rect.x() + 10
                if item == "pal":                                # 4 couleurs de la palette, 18 x 10
                    strip = QRectF(x, rect.center().y() - 5, 18, 10)
                    clip = QPainterPath()
                    clip.addRoundedRect(strip, 2, 2)
                    p.save()
                    p.setClipPath(clip)
                    for k, hex_color in enumerate(self.strip[:4]):
                        p.fillRect(QRectF(strip.x() + k * 4.5, strip.y(), 4.5, 10), QColor(hex_color))
                    p.restore()
                    x += 18 + 6
                p.setFont(f)
                p.setPen(QColor(lk["strong_color"] if on else lk["muted_color"]))
                p.drawText(QRectF(x, rect.y(), rect.right() - x, rect.height()), Qt.AlignLeft | Qt.AlignVCenter,
                           dict(RENDERS)[item])
            else:
                center = rect.center()
                if item == self.bg:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(lk["accent_color"]))
                    p.drawEllipse(center, 15, 15)
                    p.setBrush(QColor(lk["panel_color"]))
                    p.drawEllipse(center, 13, 13)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(lk[f"viewer_bg_{item + 1}"]))
                p.drawEllipse(center, 11, 11)
                if item != self.bg:
                    p.setPen(QPen(rgba("#ffffff", .25), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(center, 10.5, 10.5)
        p.setPen(QColor(lk["control_border"]))
        for x in self._dividers:
            p.drawLine(QPointF(x + .5, 12), QPointF(x + .5, 34))
        p.setFont(font(lk, 11))
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(self._fond, Qt.AlignCenter, "Fond")

    def mousePressEvent(self, event):
        for kind, item, rect in self._hits:
            if rect.contains(event.position()):
                if kind == "tool":
                    self.toolPicked.emit(item)
                elif kind == "render":
                    self.renderPicked.emit(item)
                else:
                    self.bgPicked.emit(item)
                return

    def mouseMoveEvent(self, event):
        for kind, item, rect in self._hits:
            if kind == "bg" and rect.contains(event.position()):
                self.setToolTip(BG_LABELS[item])
                return
        self.setToolTip("")


class Viewer(_Painted):
    """Image analysée, centrée (jamais agrandie au-delà du proxy), outils en bas. Pipette : clic (Ctrl : ajoute /
    retire) ; région : glisser ; double-clic : image entière. `display` : image recomposée (isolement, palette seule)
    montrée à la place de l'image ; `marker` : pixel de la pipette ; `tag` : étiquette de la sélection en haut à gauche."""
    picked = Signal(int, int, bool)
    regionChanged = Signal(object)

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.image = QImage()
        self.natural_width = 1500
        self.region = None
        self.tool = "P"
        self.bg = QColor(look["viewer_bg_2"])
        self._start = self._now = None
        self._pix = None
        self._pix_key = None
        self.display = None
        self.marker = None
        self.tag = None
        self.toolbar = Toolbar(self, look)
        self.setMinimumHeight(420)
        self.setMouseTracking(True)
        self._cursor()

    def _look_changed(self):
        self.toolbar.set_look(self.look)
        self._place_toolbar()

    def set_image(self, image: QImage):
        self.image = image
        self.region = None
        self._pix = None
        self.display = self.marker = self.tag = None
        self.update()

    def set_display(self, image):
        """Image montrée à la place de l'image analysée (None : l'image elle-même)."""
        if image is not self.display:
            self.display = image
            self.update()

    def set_marker(self, pixel):
        if pixel != self.marker:
            self.marker = pixel
            self.update()

    def set_tag(self, tag):
        """(hex, texte, couverture) ou None."""
        if tag != self.tag:
            self.tag = tag
            self.update()

    def set_tool(self, tool):
        self.tool = tool
        self._cursor()

    def _cursor(self):
        self.setCursor(Qt.CrossCursor if self.tool in ("P", "R") else Qt.ArrowCursor)

    def set_bg(self, color: QColor):
        if color != self.bg:
            self.bg = color
            self.update()

    def image_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        avail = QRectF(self.rect()).adjusted(32, 40, -32, -72)
        width = max(1, min(1500, avail.width(), self.image.width(), self.natural_width))
        height = max(1, min(avail.height(), self.look["image_max_height"]))
        size = self.image.size().scaled(round(width), round(height), Qt.KeepAspectRatio)
        return QRectF(round(avail.center().x() - size.width() / 2), round(avail.center().y() - size.height() / 2),
                      size.width(), size.height())

    def pixel_at(self, position):
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(position):
            return None
        return (min(self.image.width() - 1, int((position.x() - rect.x()) * self.image.width() / rect.width())),
                min(self.image.height() - 1, int((position.y() - rect.y()) * self.image.height() / rect.height())))

    def _to_view(self, region: QRect, rect: QRectF) -> QRectF:
        sx, sy = rect.width() / self.image.width(), rect.height() / self.image.height()
        return QRectF(rect.x() + region.x() * sx, rect.y() + region.y() * sy, region.width() * sx,
                      region.height() * sy)

    def resizeEvent(self, event):
        self._place_toolbar()

    def _place_toolbar(self):
        self.toolbar.move(round((self.width() - self.toolbar.width()) / 2), self.height() - 16 - self.toolbar.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        if self.image.isNull():
            return
        rect = self.image_rect()
        dpr = self.devicePixelRatioF()
        shown = self.display if self.display is not None else self.image
        key = (rect.width(), rect.height(), dpr, shown.cacheKey())
        if key != self._pix_key:                                 # redimensionné UNE fois par taille / image
            self._pix = QPixmap.fromImage(shown.scaled(round(rect.width() * dpr), round(rect.height() * dpr),
                                                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            self._pix.setDevicePixelRatio(dpr)
            self._pix_key = key
        p.setPen(QPen(rgba("#ffffff", .06), 1))
        p.drawRect(rect.adjusted(-.5, -.5, .5, .5))
        p.drawPixmap(rect.topLeft(), self._pix)
        lk = self.look
        if self.region is not None:
            p.setPen(QPen(QColor(lk["accent_color"]), 1.5, Qt.DashLine))
            p.drawRect(self._to_view(self.region, rect))
        if self._start is not None and self._now is not None and self.tool == "R":
            p.setPen(QPen(QColor(lk["strong_color"]), 1, Qt.DashLine))
            p.setBrush(rgba(lk["accent_color"], .08))
            x0, y0 = self._start
            x1, y1 = self._now
            p.drawRect(self._to_view(QRect(min(x0, x1), min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1), rect))
        p.setRenderHint(QPainter.Antialiasing)
        if self.marker is not None:                              # anneau clair cerné de noir, 16 px
            c = QPointF(rect.x() + (self.marker[0] + .5) * rect.width() / self.image.width(),
                        rect.y() + (self.marker[1] + .5) * rect.height() / self.image.height())
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(rgba("#000000", .6), 1.5))
            p.drawEllipse(c, 10.25, 10.25)
            p.setPen(QPen(QColor(lk["strong_color"]), 1.5))
            p.drawEllipse(c, 8.75, 8.75)
        if self.tag is not None:
            self._paint_tag(p, rect)

    def _paint_tag(self, p, rect):
        """Étiquette de la sélection (maquette : pastille 12 px, HEX mono, part de l'image)."""
        lk = self.look
        hex_color, text, cov = self.tag
        mono, f = font(lk, 12, mono=True), font(lk, 12)
        w = 10 + 12 + 8 + text_width(mono, text) + 8 + text_width(f, cov) + 10
        box = QRectF(rect.x() + 10, rect.y() + 10, w, 27)
        p.setPen(QPen(QColor(lk["control_border"]), 1))
        p.setBrush(rgba(lk["bg_color"], .88))
        p.drawRoundedRect(box.adjusted(.5, .5, -.5, -.5), 8, 8)
        chip = QRectF(box.x() + 10, box.center().y() - 6, 12, 12)
        p.setPen(QPen(rgba("#ffffff", .2), 1))
        p.setBrush(QColor(hex_color))
        p.drawRoundedRect(chip.adjusted(.5, .5, -.5, -.5), 3, 3)
        x = chip.right() + 8
        p.setFont(mono)
        p.setPen(QColor(lk["strong_color"]))
        p.drawText(QRectF(x, box.y(), box.right() - x, box.height()), Qt.AlignLeft | Qt.AlignVCenter, text)
        x += text_width(mono, text) + 8
        p.setFont(f)
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(QRectF(x, box.y(), box.right() - x, box.height()), Qt.AlignLeft | Qt.AlignVCenter, cov)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pixel = self.pixel_at(event.position())
        if pixel is None:
            return
        if self.tool == "P":
            self.picked.emit(pixel[0], pixel[1], bool(event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)))
        elif self.tool == "R":
            self._start = self._now = pixel

    def mouseMoveEvent(self, event):
        if self._start is not None:
            rect = self.image_rect()
            pos = QPointF(min(max(event.position().x(), rect.left()), rect.right() - .01),
                          min(max(event.position().y(), rect.top()), rect.bottom() - .01))
            pixel = self.pixel_at(pos)
            if pixel is not None and pixel != self._now:
                self._now = pixel
                self.update()

    def mouseReleaseEvent(self, event):
        if self._start is not None and self._now is not None:
            (x0, y0), (x1, y1) = self._start, self._now
            if abs(x1 - x0) + abs(y1 - y0) > 4:
                self.region = QRect(min(x0, x1), min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1)
                self.regionChanged.emit(self.region)
        self._start = self._now = None
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.clear_region()

    def clear_region(self):
        if self.region is not None:
            self.region = None
            self.regionChanged.emit(None)
            self.update()


class SelectedColor(_Painted):
    """Couleur sélectionnée (palette ou pipette) : aplat 88 px, HEX, RGB, couverture, OKLab L / C / h."""
    copyRequested = Signal()

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.data = None
        self.copy = Button(self, look, icon_name="copy", kind="icon", height_key=32)
        self.copy.setToolTip("Copier le HEX")
        self.copy.clicked.connect(self.copyRequested)
        self._look_changed()

    def _look_changed(self):
        self.copy.set_look(self.look)
        self.setFixedHeight(2 * self.look["section_padding"] + 32 + 6 + 3 * 15 + 2 * 4 + 1)

    def set_data(self, data):
        self.data = data
        self.update()

    def resizeEvent(self, event):
        pad = self.look["section_padding"]
        self.copy.setGeometry(self.width() - pad - 32, pad, 32, 32)

    def paintEvent(self, event):
        lk = self.look
        pad = lk["section_padding"]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(lk["line_color"]))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        d = self.data
        chip = QRectF(pad, pad, 88, self.height() - 1 - 2 * pad)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(d["hex"]) if d else QColor(lk["well_color"]))
        p.drawRoundedRect(chip, 10, 10)
        p.setPen(QPen(rgba("#ffffff", .08), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(chip.adjusted(.5, .5, -.5, -.5), 10, 10)
        x = chip.right() + 14
        right = self.width() - pad
        p.setFont(font(lk, 18, 500, mono=True))
        p.setPen(QColor(lk["strong_color"]))
        p.drawText(QRectF(x, pad, right - 40 - x, 32), Qt.AlignLeft | Qt.AlignVCenter,
                   d["hex"].upper() if d else "—")
        if not d:
            return
        rgb = " ".join(str(v) for v in d["rgb"])
        cov = "—" if d.get("weight") is None else f'{fr(d["weight"] * 100, d.get("digits", 1))} %'
        cells = (("RGB", rgb), ("Couv.", cov), ("L", fr(d["L"], 2)), ("C", fr(d["C"], 3)),
                 ("h", f'{round(d["h"])}°'), ("OKLab", ""))
        mono = font(lk, 11, mono=True)
        p.setFont(mono)
        col_w = (right - x - 12) / 2
        for k, (label, value) in enumerate(cells):
            cx = x + (k % 2) * (col_w + 12)
            cy = pad + 32 + 6 + (k // 2) * 19
            p.setPen(QColor(lk["muted_color"]))
            p.drawText(QRectF(cx, cy, col_w, 15), Qt.AlignLeft | Qt.AlignVCenter, label)
            if value:
                p.setPen(QColor(lk["text_color"]))
                p.drawText(QRectF(cx + text_width(mono, label + " "), cy, col_w, 15), Qt.AlignLeft | Qt.AlignVCenter,
                           value)


# --- inspecteur -------------------------------------------------------------------------------------------------------
TONES = (("Ombres", "Y < 0,09"), ("Tons moyens", "0,09–0,5"), ("Hautes lumières", "Y ≥ 0,5"))


class ToneView(_Painted):
    """Répartition tonale : barre proportionnelle + une ligne par zone (couleur moyenne, HEX, part)."""

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.tones = []
        self._look_changed()

    def _look_changed(self):
        self.setFixedHeight(self.look["tone_height"] + 12 + 3 * 18 + 2 * 6)

    def set_tones(self, tones):
        self.tones = tones or []
        self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bar = QRectF(0, 0, self.width(), lk["tone_height"])
        shown = [(rgb, w) for rgb, w in self.tones if rgb is not None and w > 0]
        if shown:
            clip = QPainterPath()
            clip.addRoundedRect(bar, 4, 4)
            p.save()
            p.setClipPath(clip)
            usable = bar.width() - 2 * (len(shown) - 1)
            x = 0.0
            for rgb, w in shown:
                p.fillRect(QRectF(x, 0, usable * w + .4, bar.height()), QColor(*rgb))
                x += usable * w + 2
            p.restore()
        base = font(lk, lk["font_size"])
        small = font(lk, 11)
        mono11, mono12 = font(lk, 11, mono=True), font(lk, 12, mono=True)
        for k, (name, hint) in enumerate(TONES):
            rgb, weight = self.tones[k] if k < len(self.tones) else (None, 0.0)
            y = bar.height() + 12 + k * 24
            row = QRectF(0, y, self.width(), 18)
            sw = QRectF(0, y + 3, 12, 12)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*rgb) if rgb else Qt.NoBrush)
            p.drawRoundedRect(sw, 3, 3)
            p.setPen(QPen(rgba("#ffffff", .12), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(sw.adjusted(.5, .5, -.5, -.5), 3, 3)
            pct = f"{fr(weight * 100, 1)} %"
            hex_text = QColor(*rgb).name().upper() if rgb else "—"
            right = row.right()
            p.setFont(mono12)
            p.setPen(QColor(lk["text_color"]))
            p.drawText(QRectF(right - 48, y, 48, 18), Qt.AlignRight | Qt.AlignVCenter, pct)
            pct_w = max(48.0, text_width(mono12, pct))
            p.setFont(mono11)
            p.setPen(QColor(lk["muted_color"]))
            hex_w = text_width(mono11, hex_text)
            p.drawText(QRectF(right - pct_w - 10 - hex_w, y, hex_w, 18), Qt.AlignRight | Qt.AlignVCenter, hex_text)
            x = 22
            p.setFont(base)
            p.setPen(QColor(lk["text_color"]))
            p.drawText(QRectF(x, y, 400, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
            p.setFont(small)
            p.setPen(QColor(lk["muted_color"]))
            p.drawText(QRectF(x + text_width(base, name + " "), y, 400, 18), Qt.AlignLeft | Qt.AlignVCenter, hint)


class LumaGauge(_Painted):
    """Luminance Y linéaire : jauge noir -> blanc (P5–P95, P50, moyenne, P99) + six cartes de valeurs."""
    CARDS = (("Moyenne", "mean"), ("P50", 2), ("P99", 4), ("P1", 0), ("P5", 1), ("P95", 3))

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.stats = None
        self.setFixedHeight(44 + 12 + 2 * 51 + 6)

    def set_stats(self, stats):
        self.stats = stats
        self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, QColor("#000000"))
        grad.setColorAt(1, QColor("#ffffff"))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(0, 20, w, 6), 3, 3)
        s = self.stats
        mono10 = font(lk, 10, mono=True)
        if s:
            pct = s["percentiles"]
            px = lambda v: max(0.0, min(1.0, v)) * w           # noqa: E731
            p.setPen(QPen(QColor(lk["accent_color"]), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(px(pct[1]) + .75, 18.75, max(1.0, px(pct[3]) - px(pct[1]) - 1.5), 8.5), 3, 3)
            p.setFont(mono10)
            for value, color, label, top in ((pct[2], "text_color", "P50", False),
                                             (s["mean"], "accent_color", "moy.", True),
                                             (pct[4], "text_color", "P99", False)):
                x = px(value)
                p.fillRect(QRectF(min(x, w - 2), 14, 2, 18), QColor(lk[color]))
                p.setPen(QColor(lk["accent_color" if top else "label_color"]))
                lw = text_width(mono10, label)
                lx = max(0.0, min(w - lw, x + 1 - lw / 2))
                p.drawText(QRectF(lx, 0 if top else 32, lw + 1, 12), Qt.AlignCenter, label)
        card_w = (w - 12) / 3
        label_f, value_f = font(lk, 11), font(lk, 13, mono=True)
        for k, (label, index) in enumerate(self.CARDS):
            r = QRectF((k % 3) * (card_w + 6), 56 + (k // 3) * 57, card_w, 51)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lk["card_color"]))
            p.drawRoundedRect(r, lk["radius"], lk["radius"])
            p.setFont(label_f)
            p.setPen(QColor(lk["muted_color"]))
            p.drawText(r.adjusted(8, 8, -8, 0), Qt.AlignLeft | Qt.AlignTop, label)
            if s:
                value = s["mean"] if index == "mean" else s["percentiles"][index]
                p.setFont(value_f)
                p.setPen(QColor(lk["accent_color" if index == "mean" else "text_color"]))
                p.drawText(r.adjusted(8, 0, -8, -8), Qt.AlignLeft | Qt.AlignBottom, fr(value, 4))


def _scope_frame(p: QPainter, lk: dict, rect: QRectF):
    p.setPen(QPen(QColor(lk["line_color"]), 1))
    p.setBrush(QColor(lk["scope_bg"]))
    p.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 8, 8)


def _scope_message(p: QPainter, lk: dict, rect: QRectF, text: str):
    p.setFont(font(lk, 11))
    p.setPen(QColor(lk["muted_color"]))
    p.drawText(rect.adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, text)


class HistView(_Painted):
    """Histogramme R / V / B / Y′ (0-255), aires translucides ; tracés gardés tant que taille / données / options
    n'ont pas changé."""
    CHANNELS = ("r", "g", "b", "y")

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.hist = None
        self.log = True
        self.channels = "rgb"
        self._paths = None
        self._key = None
        self._look_changed()

    def _look_changed(self):
        self.setFixedHeight(self.look["hist_height"])

    def set_data(self, hist, log, channels):
        if (hist is not self.hist) or log != self.log or channels != self.channels:
            self.hist, self.log, self.channels = hist, log, channels
            self._key = None
            self.update()

    def _build(self, rect: QRectF):
        import numpy as np
        shown = [c for c in self.CHANNELS if c in self.channels]
        arrays = {c: np.asarray(self.hist[i], dtype=np.float64) for i, c in enumerate(self.CHANNELS)}
        if self.log:
            arrays = {c: np.log1p(a) for c, a in arrays.items()}
        peak = max((float(arrays[c][1:255].max()) for c in shown), default=0.0) or 1.0
        top = rect.height() * .04
        xs = np.linspace(rect.left(), rect.right(), 256)
        paths = []
        for c in ("y", "r", "g", "b"):                          # Y dessous, comme la maquette
            if c not in shown:
                continue
            ys = rect.bottom() - np.minimum(arrays[c] / peak, 1.0) * (rect.height() - top)
            path = QPainterPath(QPointF(rect.left(), rect.bottom()))
            for x, y in zip(xs.tolist(), ys.tolist()):
                path.lineTo(x, y)
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            paths.append((c, path))
        return paths

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect())
        _scope_frame(p, lk, frame)
        inner = frame.adjusted(1, 1, -1, -1)
        p.setPen(QPen(rgba("#ffffff", .06), 1))
        for k in (1, 2, 3):
            x = inner.left() + inner.width() * k / 4
            p.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
        if self.hist is None:
            _scope_message(p, lk, frame, "Histogramme indisponible")
        else:
            key = (inner.width(), inner.height(), self.log, self.channels)
            if key != self._key:
                self._paths, self._key = self._build(inner), key
            clip = QPainterPath()
            clip.addRoundedRect(inner, 7, 7)
            p.setClipPath(clip)
            for c, path in self._paths:
                color = lk["hist_" + c]
                p.setBrush(rgba(color, .16))
                p.setPen(QPen(rgba(color, .8 if c == "y" else 1.0), 1))
                p.drawPath(path)
            p.setClipping(False)
        p.setFont(font(lk, 10, mono=True))
        p.setPen(QColor(lk["axis_color"]))
        label = frame.adjusted(6, 0, -6, -4)
        p.drawText(label, Qt.AlignLeft | Qt.AlignBottom, "0")
        p.drawText(label, Qt.AlignRight | Qt.AlignBottom, "255")


class Chips(_Painted):
    """Canaux de l'histogramme (pastilles R / V / B / Y) et case « Log » à droite."""
    toggled = Signal(str)
    logToggled = Signal(bool)
    ITEMS = (("r", "R"), ("g", "V"), ("b", "B"), ("y", "Y"))

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.channels, self.log = "rgb", True
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)

    def set_state(self, channels, log):
        if (channels, log) != (self.channels, self.log):
            self.channels, self.log = channels, log
            self.update()

    def _rects(self):
        f = font(self.look, 12)
        rects, x = [], 0.0
        for cid, label in self.ITEMS:
            w = 10 + 8 + 6 + text_width(f, label) + 10
            rects.append((cid, label, QRectF(x, 0, w, 28)))
            x += w + 6
        lw = 14 + 6 + text_width(f, "Log")
        return rects, QRectF(self.width() - lw, 0, lw, 28)

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = font(lk, 12)
        p.setFont(f)
        rects, log_rect = self._rects()
        for cid, label, r in rects:
            on = cid in self.channels
            p.setPen(QPen(QColor(lk["chip_on_border" if on else "control_border"]), 1))
            p.setBrush(QColor(lk["chip_on_bg"]) if on else Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), 14, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(lk["hist_" + cid] if on else lk["chip_off_dot"]))
            p.drawEllipse(QPointF(r.x() + 14, r.center().y()), 4, 4)
            p.setPen(QColor(lk["strong_color" if on else "muted_color"]))
            p.drawText(r.adjusted(24, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, label)
        paint_check(p, lk, QRectF(log_rect.x(), 7, 14, 14), self.log)
        p.setPen(QColor(lk["label_color"]))
        p.drawText(log_rect.adjusted(20, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, "Log")

    def mousePressEvent(self, event):
        rects, log_rect = self._rects()
        if log_rect.contains(event.position()):
            self.log = not self.log
            self.update()
            self.logToggled.emit(self.log)
            return
        for cid, _label, r in rects:
            if r.contains(event.position()):
                self.channels = "".join(c for c in "rgby" if (c in self.channels) != (c == cid))
                self.update()
                self.toggled.emit(self.channels)
                return


def paint_check(p: QPainter, lk: dict, box: QRectF, on: bool):
    """Case à cocher de la maquette (couleur d'accent)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if on:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(lk["accent_color"]))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(QPen(QColor(lk["accent_ink"]), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        w = box.width()
        path = QPainterPath(QPointF(box.x() + w * .24, box.y() + w * .52))
        path.lineTo(box.x() + w * .43, box.y() + w * .70)
        path.lineTo(box.x() + w * .78, box.y() + w * .32)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    else:
        p.setPen(QPen(QColor(lk["muted_color"]), 1))
        p.setBrush(QColor(lk["well_color"]))
        p.drawRoundedRect(box.adjusted(.5, .5, -.5, -.5), 3, 3)
    p.restore()


class WaveView(_Painted):
    """Waveform de luminance (densité log, teinte réglable) + repères 25 / 50 / 75 %."""

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.alpha = None
        self.message = ""
        self._image = None
        self._key = None
        self._look_changed()

    def _look_changed(self):
        self.setFixedHeight(self.look["wave_height"])

    def set_data(self, alpha, message=""):
        self.alpha, self.message = alpha, message
        self._key = None
        self.update()

    def _tinted(self):
        import numpy as np
        key = (id(self.alpha), self.look["wave_color"])
        if key != self._key:
            c = QColor(self.look["wave_color"])
            a = self.alpha.astype(np.float32) / 255.0
            h, w = a.shape
            out = np.empty((h, w, 4), np.uint8)
            out[..., 0] = (a * c.blue()).astype(np.uint8)
            out[..., 1] = (a * c.green()).astype(np.uint8)
            out[..., 2] = (a * c.red()).astype(np.uint8)
            out[..., 3] = self.alpha
            self._image = QImage(out.data, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()
            self._key = key
        return self._image

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect())
        _scope_frame(p, lk, frame)
        inner = frame.adjusted(1, 1, -1, -1)
        if self.alpha is None:
            _scope_message(p, lk, frame, self.message or "Waveform indisponible")
        else:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(inner, self._tinted())
        p.setPen(QPen(rgba("#ffffff", .07), 1))
        for level in (.25, .5, .75):
            y = round(inner.top() + inner.height() * level) + .5
            p.drawLine(QPointF(inner.left(), y), QPointF(inner.right(), y))
        p.setFont(font(lk, 10, mono=True))
        p.setPen(QColor(lk["axis_color"]))
        label = frame.adjusted(6, 4, -6, -4)
        p.drawText(label, Qt.AlignLeft | Qt.AlignTop, "100")
        p.drawText(label, Qt.AlignLeft | Qt.AlignBottom, "0")


class VecView(_Painted):
    """Vectorscope Cb / Cr (chaque point de la couleur de ses pixels) + ligne des teintes chair."""

    def __init__(self, parent, look):
        super().__init__(parent, look)
        self.image = None
        self.message = ""
        self._look_changed()

    def _look_changed(self):
        self.setFixedHeight(self.look["vec_size"] + 18)

    def set_data(self, image, message=""):
        self.image, self.message = image, message
        self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect())
        _scope_frame(p, lk, frame)
        size = lk["vec_size"]
        box = QRectF((self.width() - size) / 2, 9, size, size)
        if self.image is None:
            _scope_message(p, lk, frame, self.message or "Vectorscope indisponible")
            return
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(box, self.image)
        angle = math.radians(123)                               # teintes chair : ~123° depuis l'axe Cb
        c = box.center()
        p.setPen(QPen(rgba(lk["skin_color"], .75), 1))
        p.drawLine(c, QPointF(c.x() + math.cos(angle) * size / 2, c.y() - math.sin(angle) * size / 2))


class CheckRow(_Painted):
    """Ligne « Exclure les noirs ≤ 8 » : libellé, indice mono atténué, case à droite. Clic n'importe où = bascule."""
    toggled = Signal(bool)

    def __init__(self, parent, look, text, hint, checked=False):
        super().__init__(parent, look)
        self.text, self.hint, self.checked = text, hint, checked
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self.checked

    def setChecked(self, on):
        if bool(on) != self.checked:
            self.checked = bool(on)
            self.update()

    def paintEvent(self, event):
        lk = self.look
        p = QPainter(self)
        base = font(lk, lk["font_size"])
        p.setFont(base)
        p.setPen(QColor(lk["text_color"]))
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, self.text)
        p.setFont(font(lk, 11, mono=True))
        p.setPen(QColor(lk["muted_color"]))
        p.drawText(QRectF(self.rect()).adjusted(text_width(base, self.text + " "), 0, 0, 0),
                   Qt.AlignLeft | Qt.AlignVCenter, self.hint)
        paint_check(p, lk, QRectF(self.width() - 16, (self.height() - 16) / 2, 16, 16), self.checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.checked = not self.checked
            self.update()
            self.toggled.emit(self.checked)


def inspector_stylesheet(lk: dict) -> str:
    """Inspecteur défilant (fond panneau, filet à gauche, barre de défilement fine) : onglets Analyse et Matching."""
    return (f"QScrollArea {{ background: {lk['panel_color']}; border: none; border-left: 1px solid {lk['line_color']}; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{ background: {lk['control_border']}; border-radius: 3px; min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}")


def field_stylesheet(lk: dict) -> str:
    """Champs « Couleurs » / « Ordre » de la maquette (posé sur ces deux champs seulement)."""
    return (f"QSpinBox, QComboBox {{ min-height: 32px; max-height: 32px; padding: 0 10px; border-radius: {lk['radius']}px;"
            f" border: 1px solid {lk['control_border']}; background: {lk['well_color']}; color: {lk['text_color']};"
            f" selection-background-color: {lk['active_color']}; }}"
            f"QComboBox {{ padding: 0 8px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}"
            f"QComboBox QAbstractItemView {{ background: {lk['well_color']}; color: {lk['text_color']};"
            f" border: 1px solid {lk['control_border']}; selection-background-color: {lk['active_color']};"
            f" outline: 0; }}")


class Combo(QComboBox):
    """Liste déroulante de la maquette : feuille `field_stylesheet` + chevron dessiné (le triangle en CSS ne
    s'affiche pas sous Qt)."""

    def __init__(self, parent, look):
        super().__init__(parent)
        self.look = look

    def set_look(self, look):
        self.look = look
        self.setStyleSheet(field_stylesheet(look))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.drawPixmap(QPointF(self.width() - 22, (self.height() - 14) / 2),
                     icon("chevron", self.look["muted_color"], 14, self.devicePixelRatioF()))
