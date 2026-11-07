"""Listes d'événements groupées par jour, d'après l'agenda de la barre latérale du design (`.ag-d`, `.ag`,
`.pill`) : style compact (barre latérale) ou large (vue Planning, résultats de recherche).

Un seul widget peint (hauteur = contenu, placé dans une zone défilante) : des centaines de lignes coûtent une
passe de peinture limitée à la partie visible."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..core import timeutil as tu
from ..core.model import Occurrence
from . import theme as th
from .context import ViewContext
from .timegrid import _tooltip
from .widgets import elide, paint_check


def time_label(occ: Occurrence, day: date | None, h24: bool) -> str:
    if occ.all_day or occ.spans_days():
        return "Journée"
    if occ.end == occ.start:
        return tu.fmt_time(occ.start, h24)
    if day is not None and occ.start.date() != day:
        return f"→ {tu.fmt_time(occ.end, h24)}" if occ.end.date() == day else "Journée"
    return tu.fmt_range(occ.start, occ.end, h24)


class AgendaList(QWidget):
    selected = Signal(object)
    activated = Signal(object)
    toggleDone = Signal(object)
    contextRequested = Signal(object, object, object)
    dayActivated = Signal(object)

    def __init__(self, ctx: ViewContext, large: bool = False, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.large = large
        self.groups: list[tuple[str, str, date | None, list[Occurrence]]] = []
        self.empty_text = ""
        self.selected_key: str | None = None
        self.rows: list[tuple[QRectF, str, object, object]] = []     # rect, type, occ | label, jour
        self._hover: int = -1
        self._height = 40
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_groups(self, groups, selected_key: str | None = None, empty_text: str = "") -> None:
        self.groups = groups
        self.selected_key = selected_key
        self.empty_text = empty_text
        self.relayout()

    def set_selected(self, key):
        if key != self.selected_key:
            self.selected_key = key
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(240, self._height)

    def relayout(self) -> None:
        rows = []
        y = 0.0
        w = self.width()
        large = self.large
        for label, badge, day, items in self.groups:
            y += 18 if large else 14
            rows.append((QRectF(0, y, w, 20 if large else 16), "head", (label, badge), day))
            y += (24 if large else 16) + 4
            for occ in items:
                if (occ.all_day or occ.spans_days()) and not large:
                    rows.append((QRectF(0, y + 2, w, 21), "bar", occ, day))
                    y += 2 + 21 + 4
                else:
                    h = 46 if large else 37
                    rows.append((QRectF(0, y, w, h), "item", occ, day))
                    y += h
        if not self.groups and self.empty_text:
            rows.append((QRectF(6, 14, w - 12, 40), "empty", self.empty_text, None))
            y = 60
        self.rows = rows
        self._height = int(y + 8)
        self.setFixedHeight(max(1, self._height))
        self.update()

    def resizeEvent(self, event):
        if event.oldSize().width() != event.size().width():
            self.relayout()

    def paintEvent(self, event):
        ctx, t = self.ctx, self.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        clip = QRectF(event.rect())
        large = self.large
        today = ctx.today()
        for i, (rect, kind, payload, day) in enumerate(self.rows):
            if not rect.intersects(clip):
                continue
            if kind == "empty":
                p.setFont(th.font(12))
                p.setPen(t.c("dim"))
                p.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, payload)
                continue
            if kind == "head":
                label, badge = payload
                px = 12 if large else 11
                f = th.font(px, 700)
                f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0.55)
                f.setCapitalization(f.Capitalization.AllUppercase)
                p.setFont(f)
                p.setPen(t.c("today_text") if large and day == today else t.c("muted"))
                p.drawText(rect.adjusted(6 if large else 0, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, label)
                if badge:
                    p.setFont(th.font(px, 600))
                    p.setPen(t.c("today_text"))
                    p.drawText(rect.adjusted(0, 0, -6 if large else 0, 0), Qt.AlignRight | Qt.AlignVCenter, badge)
                continue
            occ: Occurrence = payload
            bg, bar, fg = ctx.colors(occ)
            hover = i == self._hover
            sel = occ.key == self.selected_key
            if kind == "bar":
                pill = rect.adjusted(0, 0, 0, 0)
                p.setPen(Qt.NoPen)
                p.setBrush(bg if not hover else bg.lighter(110))
                p.drawRoundedRect(pill, 4, 4)
                p.setFont(th.font(12, 600))
                p.setPen(fg)
                p.drawText(pill.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft,
                           elide(occ.title or "(Sans titre)", 12, 600, pill.width() - 16))
                if sel:
                    p.setPen(t.c("accent"))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(pill.adjusted(-1, -1, 1, 1), 5, 5)
                continue
            if hover or sel:
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("btn"))
                p.drawRoundedRect(rect, 6, 6)
            x = rect.left() + 6
            if occ.is_task:
                paint_check(p, QRectF(x, rect.top() + 8, 12, 12), occ.done, t.event(ctx.color_key(occ))[1],
                            t.c("off"))
                x += 12 + 9
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(bar)
                p.drawEllipse(QRectF(x, rect.top() + 9, 8, 8))
                x += 8 + 9
            avail = rect.right() - 6 - x
            p.setFont(th.font(11))
            p.setPen(t.c("dim"))
            tl = time_label(occ, day, ctx.h24)
            if large:
                cal = ctx.calendar_name(occ.calendar_id)
                extra = " · ".join(v for v in (occ.location, cal) if v)
                p.drawText(QRectF(x, rect.top() + 5, avail, 16), Qt.AlignLeft | Qt.AlignVCenter,
                           elide(tl + ("  ·  " + extra if extra else ""), 11, 400, avail))
            else:
                p.drawText(QRectF(x, rect.top() + 5, avail, 14), Qt.AlignLeft | Qt.AlignVCenter, tl)
            f = th.font(13, 600 if large else 500)
            f.setStrikeOut(occ.done)
            p.setFont(f)
            p.setPen(t.c("strong") if large else t.c("text"))
            p.drawText(QRectF(x, rect.top() + (21 if large else 19), avail, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(occ.title or "(Sans titre)", 13, 600 if large else 500, avail))
            if sel and not hover:
                p.setPen(t.c("accent"))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

    def _row_at(self, pos: QPointF) -> int:
        for i, (rect, kind, _payload, _day) in enumerate(self.rows):
            if kind in ("item", "bar", "head") and rect.contains(pos):
                return i
        return -1

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            i = self._row_at(QPointF(e.pos()))
            if i >= 0 and self.rows[i][1] in ("item", "bar"):
                QToolTip.showText(e.globalPos(), _tooltip(self.ctx, self.rows[i][2]), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mouseMoveEvent(self, event):
        i = self._row_at(event.position())
        if i >= 0 and self.rows[i][1] == "head" and self.rows[i][3] is None:
            i = -1
        if i != self._hover:
            old = self.rows[self._hover][0] if 0 <= self._hover < len(self.rows) else None
            self._hover = i
            new = self.rows[i][0] if i >= 0 else None
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            for r in (old, new):
                if r is not None:
                    self.update(r.adjusted(-2, -2, 2, 2).toAlignedRect())

    def leaveEvent(self, event):
        if self._hover >= 0:
            self._hover = -1
            self.update()

    def mousePressEvent(self, event):
        i = self._row_at(event.position())
        if i < 0:
            return
        rect, kind, payload, day = self.rows[i]
        if event.button() == Qt.RightButton and kind != "head":
            self.contextRequested.emit(payload, day, event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        if kind == "head":
            if day is not None:
                self.dayActivated.emit(day)
            return
        if payload.is_task and event.position().x() < rect.left() + 24:
            self.toggleDone.emit(payload)
            return
        self.selected.emit(payload)

    def mouseDoubleClickEvent(self, event):
        i = self._row_at(event.position())
        if i >= 0 and self.rows[i][1] in ("item", "bar") and event.button() == Qt.LeftButton:
            self.activated.emit(self.rows[i][2])


def group_by_day(occs: list[Occurrence], start: date, end: date, max_groups: int | None = None,
                 today: date | None = None) -> list:
    """[(libellé « Vendredi 6 nov. », badge « Aujourd'hui » / « Demain », jour, occurrences)] des jours de
    [start, end[ qui ont des événements (barres « journée » d'abord, puis par heure)."""
    from datetime import timedelta
    today = today or date.today()
    by_day: dict[date, list[Occurrence]] = {}
    for occ in occs:
        for d in occ.days():
            if start <= d < end:
                by_day.setdefault(d, []).append(occ)
    out = []
    for d in sorted(by_day):
        items = sorted(by_day[d], key=lambda o: (not (o.all_day or o.spans_days()), o.start, o.title))
        badge = "Aujourd'hui" if d == today else ("Demain" if d == today + timedelta(days=1) else "")
        out.append((tu.fmt_day_short(d), badge, d, items))
        if max_groups and len(out) >= max_groups:
            break
    return out
