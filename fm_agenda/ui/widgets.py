"""Briques peintes de l'agenda, à l'image du design (`.btn`, `.grp`, `.seg`, `.search`, `.mnav`, icônes SVG du
design redessinées au QPainter) : un seul widget par contrôle, aucune feuille de style à repolir, couleurs lues dans
le thème courant (`ThemeHolder`)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLineEdit, QSizePolicy, QWidget

from fm_theme.placeholder import ink as _placeholder_ink
from fm_theme import icon_library
from fm_theme.icon_frame import framed as _framed
from . import theme as th


class ThemeHolder:
    """Thème partagé par tous les widgets d'un panneau (changé en place : `set`)."""

    def __init__(self, t: th.AgendaTheme):
        self.t = t
        self.listeners: list = []

    def set(self, t: th.AgendaTheme) -> None:
        self.t = t
        for fn in list(self.listeners):
            fn()


def rounded_path(rect: QRectF, radii) -> QPainterPath:
    """Rectangle à coins arrondis indépendants (haut-gauche, haut-droit, bas-droit, bas-gauche)."""
    tl, tr, br, bl = radii if isinstance(radii, (tuple, list)) else (radii,) * 4
    path = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path.moveTo(x + tl, y)
    path.lineTo(x + w - tr, y)
    if tr:
        path.arcTo(x + w - 2 * tr, y, 2 * tr, 2 * tr, 90, -90)
    path.lineTo(x + w, y + h - br)
    if br:
        path.arcTo(x + w - 2 * br, y + h - 2 * br, 2 * br, 2 * br, 0, -90)
    path.lineTo(x + bl, y + h)
    if bl:
        path.arcTo(x, y + h - 2 * bl, 2 * bl, 2 * bl, 270, -90)
    path.lineTo(x, y + tl)
    if tl:
        path.arcTo(x, y, 2 * tl, 2 * tl, 180, -90)
    path.closeSubpath()
    return path


def brighter(c: QColor, factor: float = 1.12) -> QColor:
    """`filter: brightness(1.12)` du design."""
    return QColor(min(255, round(c.red() * factor)), min(255, round(c.green() * factor)),
                  min(255, round(c.blue() * factor)), c.alpha())


_ICONES_CATALOGUE = {
    "search": "general/recherche_02",
    "plus": "general/ajouter_02",
    "gear": "general/parametres_01",
    "repeat": "modules/agenda/recurrence_03",
}


def draw_icon(p: QPainter, kind: str, rect: QRectF, color: QColor, width: float = 1.6) -> None:
    identifiant = _ICONES_CATALOGUE.get(kind)
    if identifiant and icon_library.peindre(p, rect, identifiant,
                                            style=icon_library.MONOCHROME, teinte=color):
        return
    _draw_glyph(p, kind, rect, color, width)


@_framed("agenda")
def _draw_glyph(p: QPainter, kind: str, rect: QRectF, color: QColor, width: float = 1.6) -> None:
    """Icônes du design (viewBox 16 × 16) mises à l'échelle de `rect`."""
    color = _placeholder_ink(color)                     # icone dessinee par le code : magenta (provisoire)
    s = min(rect.width(), rect.height()) / 16.0
    ox = rect.x() + (rect.width() - 16 * s) / 2
    oy = rect.y() + (rect.height() - 16 * s) / 2

    def pt(x, y):
        return QPointF(ox + x * s, oy + y * s)

    pen = QPen(color, width * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if kind == "prev":
        p.drawPolyline([pt(10, 3.5), pt(5.5, 8), pt(10, 12.5)])
    elif kind == "next":
        p.drawPolyline([pt(6, 3.5), pt(10.5, 8), pt(6, 12.5)])
    elif kind == "up":
        p.drawPolyline([pt(3.5, 10), pt(8, 5.5), pt(12.5, 10)])
    elif kind == "down":
        p.drawPolyline([pt(3.5, 6), pt(8, 10.5), pt(12.5, 6)])
    elif kind == "plus":
        p.drawLine(pt(8, 3), pt(8, 13))
        p.drawLine(pt(3, 8), pt(13, 8))
    elif kind == "search":
        p.drawEllipse(pt(7, 7), 4.5 * s, 4.5 * s)
        p.drawLine(pt(10.5, 10.5), pt(14, 14))
    elif kind == "sun":
        p.drawEllipse(pt(8, 8), 3 * s, 3 * s)
        for a, b in (((8, 1.5), (8, 3)), ((8, 13), (8, 14.5)), ((1.5, 8), (3, 8)), ((13, 8), (14.5, 8)),
                     ((3.4, 3.4), (4.46, 4.46)), ((11.54, 11.54), (12.6, 12.6)), ((3.4, 12.6), (4.46, 11.54)),
                     ((11.54, 4.46), (12.6, 3.4))):
            p.drawLine(pt(*a), pt(*b))
    elif kind == "moon":
        # Croissant du design (arc de 5,6 évidé par un arc de 4,5).
        outer = QPainterPath()
        outer.addEllipse(pt(7.9, 8.1), 5.6 * s, 5.6 * s)
        inner = QPainterPath()
        inner.addEllipse(pt(10.9, 5.0), 4.5 * s, 4.5 * s)
        p.drawPath(outer.subtracted(inner))
    elif kind == "close":
        p.drawLine(pt(4, 4), pt(12, 12))
        p.drawLine(pt(12, 4), pt(4, 12))
    elif kind == "check":
        p.drawPolyline([pt(3.5, 8.5), pt(6.5, 11.5), pt(12.5, 4.5)])
    elif kind == "repeat":
        p.drawArc(QRectF(pt(3, 3), pt(13, 13)), 30 * 16, 240 * 16)
        p.drawPolyline([pt(11.2, 2.2), pt(12.6, 4.6), pt(10.2, 5.6)])
    elif kind == "bell":
        path = QPainterPath()
        path.moveTo(pt(4, 11))
        path.cubicTo(pt(5, 9.5), pt(4.5, 5), pt(8, 4))
        path.cubicTo(pt(11.5, 5), pt(11, 9.5), pt(12, 11))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(pt(7, 13), pt(9, 13))
    elif kind == "folder":
        p.drawPolyline([pt(2.5, 5), pt(2.5, 12.5), pt(13.5, 12.5), pt(13.5, 6), pt(7.5, 6), pt(6.5, 4.5),
                        pt(2.5, 4.5), pt(2.5, 5)])
    elif kind == "gear":
        p.drawEllipse(pt(8, 8), 2.2 * s, 2.2 * s)
        p.drawEllipse(pt(8, 8), 5 * s, 5 * s)
    elif kind == "list":
        for y in (4.5, 8, 11.5):
            p.drawLine(pt(5.5, y), pt(13, y))
            p.drawPoint(pt(3, y))
    p.restore()


class AgendaButton(QAbstractButton):
    """`.btn` du design : 32 px de haut, arrondi 6, fond `--btn`, filet `--btn-line`, survol `brightness(1.12)`.
    `kind` : normal, primary (accent), icon (32 × 32), nav (`.mnav` : 28 × 28 transparent). `group` : place dans
    un groupe `.grp` (first / mid / last : coins arrondis du bord extérieur seulement)."""

    def __init__(self, holder: ThemeHolder, text: str = "", icon: str | None = None, kind: str = "normal",
                 group: str | None = None, parent=None, tip: str = ""):
        super().__init__(parent)
        self.holder = holder
        self._icon = icon
        self.kind = kind
        self.group = group
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        if tip:
            self.setToolTip(tip)
            self.setAccessibleName(tip)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_icon(self, icon: str | None) -> None:
        self._icon = icon
        self.update()

    def sizeHint(self) -> QSize:
        t = self.holder.t
        if self.kind == "nav":
            return QSize(t.m["mini_nav"], t.m["mini_nav"])
        h = t.m["btn_h"]
        if self.kind == "icon" or not self.text():
            return QSize(h, h)
        fm = th.metrics(13, 600 if self.kind == "primary" else 400)
        w = fm.horizontalAdvance(self.text()) + 24 + (20 if self._icon else 0)
        return QSize(max(h, w), h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse() and self.isEnabled()
        # Aspect : celui des boutons de fm_theme (`painted_button_look`, la même source que le QSS commun ; demande de
        # l'utilisateur 2026-11-12). Seules la taille et la forme des groupes restent celles de l'agenda.
        from fm_theme.style import painted_button_look
        primary = self.kind == "primary" or self.isChecked() and self.isCheckable()
        state = ("active" if self.isDown() else "checked" if self.isChecked() and self.isCheckable()
                 else "hover" if hover else "standard")
        look = painted_button_look(state)
        bg, line, fg, r = look["bg"], look["line"], look["fg"], look["radius"]
        if self.kind == "nav":
            if hover or self.isDown():
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(rect, r, r)
            draw_icon(p, self._icon or "prev", QRectF(self.rect()).adjusted(7, 7, -7, -7), fg)
            return
        if not self.isEnabled():
            fg = th.with_alpha(fg, 0.45)
        radii = {"first": (r, 0, 0, r), "mid": (0, 0, 0, 0), "last": (0, r, r, 0)}.get(self.group, (r, r, r, r))
        path = rounded_path(rect, radii)
        p.fillPath(path, bg)
        p.setPen(QPen(line, 1))
        p.drawPath(path)
        text = self.text()
        if self._icon and not text:
            size = 16
            draw_icon(p, self._icon, QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size), fg,
                      1.6 if self._icon not in ("sun", "moon") else 1.5)
            return
        f = th.font(13, 600 if primary else 400)
        p.setFont(f)
        fm = th.metrics(13, 600 if primary else 400)
        tw = fm.horizontalAdvance(text)
        dx, dy = look["text_offset"]                     # Bouton : décalage du texte (fm_theme)
        x = (self.width() - tw - (20 if self._icon else 0)) / 2 + dx
        if self._icon:
            draw_icon(p, self._icon, QRectF(x, (self.height() - 14) / 2 + dy, 14, 14), fg, 1.8)
            x += 20
        p.setPen(fg)
        p.drawText(QRectF(x, dy, tw + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)


class ButtonGroup(QWidget):
    """`.grp` : boutons accolés (filets superposés de 1 px)."""

    def __init__(self, buttons: list[AgendaButton], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(-1)
        for i, b in enumerate(buttons):
            b.group = "first" if i == 0 else ("last" if i == len(buttons) - 1 else "mid")
            lay.addWidget(b)


class Segmented(QWidget):
    """`.seg` : choix exclusif (vue de l'agenda). Fond `--seg`, filet `--field-line`, choix actif en accent."""
    changed = Signal(str)

    def __init__(self, holder: ThemeHolder, items: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self.holder = holder
        self.items = items                           # (clé, libellé, info-bulle)
        self.current = items[0][0]
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAccessibleName("Vue de l'agenda")

    def _widths(self) -> list[int]:
        fm = th.metrics(13, 600)
        pad = self.holder.t.m["seg_item_pad"]
        return [fm.horizontalAdvance(label) + 2 * pad for _k, label, _t in self.items]

    def sizeHint(self) -> QSize:
        m = self.holder.t.m
        widths = self._widths()
        return QSize(sum(widths) + 2 * m["seg_pad"] + 2 * (len(widths) - 1) + 2, m["seg_h"] + 2 * m["seg_pad"] + 2)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _rects(self) -> list[QRectF]:
        m = self.holder.t.m
        x = 1 + m["seg_pad"]
        out = []
        for w in self._widths():
            out.append(QRectF(x, 1 + m["seg_pad"], w, m["seg_h"]))
            x += w + 2
        return out

    def set_current(self, key: str) -> None:
        if key != self.current:
            self.current = key
            self.update()

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(t.c("field_line"), 1))
        p.setBrush(t.c("seg"))
        p.drawRoundedRect(rect, t.m["seg_radius"], t.m["seg_radius"])
        for i, (r, (key, label, _tip)) in enumerate(zip(self._rects(), self.items)):
            on = key == self.current
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("accent"))
                p.drawRoundedRect(r, t.m["seg_item_radius"], t.m["seg_item_radius"])
            p.setFont(th.font(13, 600 if on else 400))
            p.setPen(t.c("on_accent") if on else (t.c("strong") if i == self._hover else t.c("muted")))
            p.drawText(r, Qt.AlignCenter, label)

    def _index_at(self, pos) -> int:
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, event):
        i = self._index_at(event.position())
        if i != self._hover:
            self._hover = i
            self.setToolTip(self.items[i][2] if i >= 0 else "")
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        i = self._index_at(event.position())
        if i >= 0 and event.button() == Qt.LeftButton:
            key = self.items[i][0]
            self.set_current(key)
            self.changed.emit(key)


class _SearchEdit(QLineEdit):
    escaped = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.text():
                self.clear()
            self.escaped.emit()
            return
        super().keyPressEvent(event)


class SearchBox(QWidget):
    """`.search` : 220 × 32, arrondi 6, fond `--field`, filet `--field-line` (accent au focus), loupe 14 px."""
    textChanged = Signal(str)
    submitted = Signal(str)
    escaped = Signal()

    def __init__(self, holder: ThemeHolder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.edit = _SearchEdit(self)
        self.edit.setPlaceholderText("Rechercher")
        self.edit.setAccessibleName("Rechercher un événement")
        self.edit.setFrame(False)
        self.edit.textChanged.connect(self.textChanged)
        self.edit.returnPressed.connect(lambda: self.submitted.emit(self.edit.text()))
        self.edit.escaped.connect(self.escaped)
        self.edit.installEventFilter(self)
        self.setFixedHeight(holder.t.m["btn_h"])
        self.setMinimumWidth(120)
        self.setMaximumWidth(holder.t.m["search_w"])
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.restyle()

    def sizeHint(self) -> QSize:
        return QSize(self.holder.t.m["search_w"], self.holder.t.m["btn_h"])

    def restyle(self) -> None:
        t = self.holder.t
        self.edit.setFont(th.font(13))
        self.edit.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {t.hexc('text')}; "
                                f"selection-background-color: {t.hexc('accent')}; }}")
        pal = self.edit.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, t.c("dim"))
        self.edit.setPalette(pal)
        self.update()

    def resizeEvent(self, event):
        self.edit.setGeometry(30, 1, max(10, self.width() - 38), self.height() - 2)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() in (event.Type.FocusIn, event.Type.FocusOut):
            self.update()
        return False

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(t.c("accent") if self.edit.hasFocus() else t.c("field_line"), 1))
        p.setBrush(t.c("field"))
        p.drawRoundedRect(rect, 6, 6)
        draw_icon(p, "search", QRectF(10, (self.height() - 14) / 2, 14, 14), t.c("dim"))

    def text(self) -> str:
        return self.edit.text()

    def focus(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()


def paint_check(p: QPainter, rect: QRectF, checked: bool, color: QColor, border: QColor, radius: float = 3.0,
                mark: QColor | None = None) -> None:
    """Case à cocher peinte (`accent-color` du design : la couleur du calendrier)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    if checked:
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(rect, radius, radius)
        draw_icon(p, "check", rect.adjusted(1, 1, -1, -1), mark or QColor("#ffffff"), 2.2)
    else:
        p.setPen(QPen(border, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    p.restore()


def elide(text: str, px: int, weight: int, width: float) -> str:
    fm = th.metrics(px, weight)
    if fm.horizontalAdvance(text) <= width:
        return text
    return fm.elidedText(text, Qt.ElideRight, max(0, int(width)))
