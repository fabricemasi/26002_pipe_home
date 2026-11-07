"""Vue Mois d'après le design (`.mvh`, `.mvr`, `.mc`, `.chip`) : en-tête des jours, numéro de semaine, cases du
mois (numéro, pastilles des événements, « +N autres »), jours hors du mois estompés, aujourd'hui en pastille.

Clic sur une case = vue Jour de ce jour (design) ; réglage `agenda_month_click` = « selection » : le clic
sélectionne, le double-clic ouvre / crée. Glisser une pastille vers un autre jour = déplacer l'événement."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

from ..core import timeutil as tu
from ..core.model import Occurrence
from . import theme as th
from .context import ViewContext
from .painting import paint_chip
from .timegrid import DRAG_START, _tooltip

HEAD_H = 32


class MonthView(QWidget):
    dayActivated = Signal(object, object)      # date, occurrence | None (ouvrir la vue Jour)
    daySelected = Signal(object)
    selected = Signal(object)
    activated = Signal(object)
    createRequested = Signal(object, object, bool)
    moveRequested = Signal(object, object, object)
    contextRequested = Signal(object, object, object)
    wheelStep = Signal(int)                       # molette : mois précédent / suivant

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._wheel = 0
        self.month = date.today().replace(day=1)
        self.cur: date | None = None
        self.weeks: list[list[date]] = []
        self.by_day: dict[date, list[Occurrence]] = {}
        self.selected_key: str | None = None
        self.chips: list[tuple[QRectF, Occurrence, date]] = []
        self.more: list[tuple[QRectF, date]] = []
        self._hover_day: date | None = None
        self._hover_key: str | None = None
        self._press = None
        self._drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    def set_data(self, month_first: date, occs: list[Occurrence], selected_key: str | None, cur: date | None) -> None:
        self.month = month_first
        self.cur = cur
        self.selected_key = selected_key
        grid = tu.month_grid(month_first, self.ctx.first_weekday)
        mm = month_first.month
        self.weeks = [row for row in grid if row[0].month == mm or row[6].month == mm]
        by_day: dict[date, list[Occurrence]] = {}
        first, last = self.weeks[0][0], self.weeks[-1][-1]
        for occ in occs:
            for d in occ.days():
                if first <= d <= last:
                    by_day.setdefault(d, []).append(occ)
        for lst in by_day.values():
            lst.sort(key=lambda o: (not o.spans_days(), o.start, o.title))
        self.by_day = by_day
        self.setMinimumHeight(HEAD_H + len(self.weeks) * self.ctx.t.m["month_row_min"])
        self.relayout()

    def set_selected(self, key):
        if key != self.selected_key:
            self.selected_key = key
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(720, HEAD_H + max(5, len(self.weeks)) * self.ctx.t.m["month_row_min"])

    # -- géométrie --

    def _cols(self):
        wk = self.ctx.t.m["month_week_col"]
        colw = (self.width() - wk) / 7
        return wk, colw

    def _row_h(self) -> float:
        n = max(1, len(self.weeks))
        return max(self.ctx.t.m["month_row_min"], (self.height() - HEAD_H) / n)

    def cell_rect(self, r: int, c: int) -> QRectF:
        wk, colw = self._cols()
        rh = self._row_h()
        return QRectF(wk + c * colw, HEAD_H + r * rh, colw, rh)

    def day_at(self, pos: QPointF) -> date | None:
        wk, colw = self._cols()
        if pos.x() < wk or pos.y() < HEAD_H or not self.weeks:
            return None
        r = int((pos.y() - HEAD_H) // self._row_h())
        c = int((pos.x() - wk) // colw)
        if 0 <= r < len(self.weeks) and 0 <= c < 7:
            return self.weeks[r][c]
        return None

    def relayout(self) -> None:
        chips, more = [], []
        for r, row in enumerate(self.weeks):
            for c, d in enumerate(row):
                cell = self.cell_rect(r, c)
                evs = self.by_day.get(d, [])
                fit = max(1, int((cell.height() - 30) // 20))
                shown = evs if len(evs) <= fit else evs[:max(0, fit - 1)]
                y = cell.top() + 6 + 26 + 2
                for occ in shown:
                    chips.append((QRectF(cell.left() + 6, y, cell.width() - 12, 18), occ, d))
                    y += 20
                if len(evs) > len(shown):
                    more.append((QRectF(cell.left() + 6, y, cell.width() - 12, 16), d))
        self.chips, self.more = chips, more
        self.update()

    def resizeEvent(self, event):
        self.relayout()

    # -- peinture --

    def paintEvent(self, event):
        ctx, t = self.ctx, self.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), t.c("bg"))
        wk, colw = self._cols()
        p.fillRect(QRectF(0, HEAD_H - 1, self.width(), 1), t.c("line"))
        f = th.font(11, 600)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0.66)
        p.setFont(f)
        p.setPen(t.c("muted"))
        for c, wd in enumerate(tu.weekday_order(ctx.first_weekday)):
            p.drawText(QRectF(wk + c * colw + 10, 0, colw - 10, HEAD_H), Qt.AlignVCenter | Qt.AlignLeft,
                       tu.DAYS_SHORT[wd])
        today = ctx.today()
        rh = self._row_h()
        for r, row in enumerate(self.weeks):
            y = HEAD_H + r * rh
            p.setFont(th.font(11))
            p.setPen(t.c("dim"))
            p.drawText(QRectF(0, y + 10, wk, 14), Qt.AlignHCenter | Qt.AlignTop, str(tu.iso_week(row[0])))
            p.fillRect(QRectF(0, y + rh - 1, wk, 1), t.c("line"))
            for c, d in enumerate(row):
                cell = self.cell_rect(r, c)
                if d.weekday() >= 5:
                    p.fillRect(cell, t.c("weekend"))
                if d == self._hover_day and not self._drag:
                    p.fillRect(cell, t.c("hover"))
                if self._drag and self._drag.get("target") == d:
                    p.fillRect(cell, th.with_alpha(t.c("accent"), 0.16))
                p.fillRect(QRectF(cell.left(), cell.top(), 1, cell.height()), t.c("line"))
                p.fillRect(QRectF(cell.left(), cell.bottom() - 1, cell.width(), 1), t.c("line"))
                out = d.month != self.month.month
                label = f"1 {tu.MONTHS_SHORT[d.month - 1]}" if d.day == 1 else str(d.day)
                is_today = d == today
                fw = 700 if is_today else 500
                fm = th.metrics(13, fw)
                badge = QRectF(cell.left() + 6, cell.top() + 6, max(24, fm.horizontalAdvance(label) + 10), 24)
                if is_today:
                    p.setPen(Qt.NoPen)
                    p.setBrush(t.c("today"))
                    p.drawRoundedRect(badge, 12, 12)
                    p.setPen(QColor("#ffffff"))
                elif self.cur == d and ctx.s("agenda_month_click", "jour") == "selection":
                    p.setPen(th.with_alpha(t.c("accent"), 1.0))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(badge.adjusted(0.75, 0.75, -0.75, -0.75), 12, 12)
                    p.setPen(t.c("off") if out else t.c("text"))
                else:
                    p.setPen(t.c("off") if out else t.c("text"))
                p.setFont(th.font(13, fw))
                p.drawText(badge, Qt.AlignCenter, label)
        drag_key = self._drag["occ"].key if self._drag else None
        for rect, occ, d in self.chips:
            out = d.month != self.month.month
            paint_chip(p, rect, t, ctx.colors(occ), occ.title,
                       "" if occ.spans_days() else tu.fmt_time(occ.start, ctx.h24) if occ.start.date() == d else "",
                       occ.spans_days(), occ.key == self.selected_key, occ.key == self._hover_key,
                       faded=out or occ.key == drag_key, done=occ.done)
        p.setFont(th.font(11))
        p.setPen(t.c("dim"))
        for rect, d in self.more:
            n = len(self.by_day.get(d, [])) - sum(1 for _r, _o, dd in self.chips if dd == d)
            p.drawText(rect.adjusted(4, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, f"+{n} autre{'s' if n > 1 else ''}")
        if self._drag and self._drag.get("pos") is not None:
            occ = self._drag["occ"]
            pos = self._drag["pos"]
            rect = QRectF(pos.x() - colw / 2 + 6, pos.y() - 9, colw - 12, 18)
            paint_chip(p, rect, t, ctx.colors(occ), occ.title, "", True, True, False)

    # -- gestes --

    def _chip_at(self, pos: QPointF):
        for rect, occ, d in self.chips:
            if rect.contains(pos):
                return occ, d
        return None, None

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            occ, _d = self._chip_at(QPointF(e.pos()))
            if occ is not None:
                QToolTip.showText(e.globalPos(), _tooltip(self.ctx, occ), self)
                return True
            for rect, d in self.more:
                if rect.contains(QPointF(e.pos())):
                    names = [o.title for o in self.by_day.get(d, [])]
                    QToolTip.showText(e.globalPos(), "<br>".join(_html(n) for n in names[:20]), self)
                    return True
            QToolTip.hideText()
            return True
        return super().event(e)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._press is not None and event.buttons() & Qt.LeftButton:
            occ = self._press["occ"]
            if occ is not None and not occ.read_only and (
                    self._drag or (pos - self._press["pos"]).manhattanLength() > DRAG_START):
                if self._drag is None and self.ctx.drag_needs_ctrl and not self._press["ctrl"]:
                    return
                self._drag = {"occ": occ, "from": self._press["day"], "target": self.day_at(pos), "pos": pos}
                self.update()
            return
        d = self.day_at(pos)
        occ, _d = self._chip_at(pos)
        key = occ.key if occ else None
        if d != self._hover_day or key != self._hover_key:
            self._hover_day, self._hover_key = d, key
            self.setCursor(Qt.PointingHandCursor if d is not None else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover_day = self._hover_key = None
        self.update()

    def mousePressEvent(self, event):
        pos = event.position()
        occ, d = self._chip_at(pos)
        day = d or self.day_at(pos)
        if event.button() == Qt.RightButton:
            self.contextRequested.emit(occ, day, event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._press = {"occ": occ, "day": day, "pos": pos, "ctrl": ctrl}

    def mouseReleaseEvent(self, event):
        press, drag = self._press, self._drag
        self._press = self._drag = None
        if press is None or event.button() != Qt.LeftButton:
            return
        if drag is not None:
            target = self.day_at(event.position())
            self.update()
            if target is not None and drag["from"] is not None and target != drag["from"]:
                occ = drag["occ"]
                delta = timedelta(days=(target - drag["from"]).days)
                if occ.all_day:
                    self.moveRequested.emit(occ, occ.start_date + delta, occ.end_date + delta)
                else:
                    self.moveRequested.emit(occ, occ.start + delta, occ.end + delta)
            return
        day = press["day"]
        if day is None:
            return
        if self.ctx.s("agenda_month_click", "jour") == "selection":
            if press["occ"] is not None:
                self.selected.emit(press["occ"])
            else:
                self.daySelected.emit(day)
            return
        self.dayActivated.emit(day, press["occ"])

    def mouseDoubleClickEvent(self, event):
        if self.ctx.s("agenda_month_click", "jour") != "selection" or event.button() != Qt.LeftButton:
            return
        occ, d = self._chip_at(event.position())
        if occ is not None:
            self.activated.emit(occ)
            return
        day = self.day_at(event.position())
        if day is not None:
            self.createRequested.emit(day, day + timedelta(days=1), True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._drag:
            self._press = self._drag = None
            self.update()
            return
        event.ignore()

    def wheelEvent(self, event):
        """Molette : la page défile d'abord si le mois dépasse la fenêtre, sinon mois précédent / suivant (un cran
        de souris = un mois ; le pavé tactile cumule ses petits pas)."""
        area = self.parent().parent() if self.parent() is not None else None
        bar = area.verticalScrollBar() if hasattr(area, "verticalScrollBar") else None
        dy = event.angleDelta().y()
        if bar is not None and bar.maximum() > 0 and not (
                (dy > 0 and bar.value() == 0) or (dy < 0 and bar.value() == bar.maximum())):
            event.ignore()
            return
        self._wheel += dy
        if abs(self._wheel) >= 120:
            self.wheelStep.emit(-1 if self._wheel > 0 else 1)
            self._wheel = 0
        event.accept()


def _html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;")
