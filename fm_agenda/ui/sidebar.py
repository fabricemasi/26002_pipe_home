"""Panneau latéral d'après le design : mini-calendrier (`.mgrid`, `.md`, points des calendriers, semaine affichée
surlignée), agenda des prochains jours (`listview.AgendaList` compact), liste des calendriers (cases colorées)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..core import timeutil as tu
from . import theme as th
from .context import ViewContext
from .listview import AgendaList
from .timegrid import _scrollbar_qss
from .widgets import AgendaButton, draw_icon, elide, paint_check

HEAD_H = 32


class MiniCalendar(QWidget):
    dayPicked = Signal(object)

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.month = date.today().replace(day=1)
        self.cur = date.today()
        self.view = "semaine"
        self.week_first: date | None = None
        self.dots: dict[date, list[str]] = {}
        self._hover: date | None = None
        self.prev_btn = AgendaButton(ctx.holder, icon="prev", kind="nav", parent=self,
                                     tip="Mois précédent du mini-calendrier")
        self.next_btn = AgendaButton(ctx.holder, icon="next", kind="nav", parent=self,
                                     tip="Mois suivant du mini-calendrier")
        self.prev_btn.clicked.connect(lambda: self.shift(-1))
        self.next_btn.clicked.connect(lambda: self.shift(1))
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(self._height())

    def _row_h(self) -> int:
        return self.ctx.t.m["mini_row_h"] + 2

    def _height(self) -> int:
        return HEAD_H + 4 + self.ctx.t.m["mini_head_h"] + 6 * self._row_h()

    def sizeHint(self) -> QSize:
        return QSize(240, self._height())

    def set_state(self, month: date, cur: date, view: str, week_first: date | None, dots: dict) -> None:
        self.month = month.replace(day=1)
        self.cur = cur
        self.view = view
        self.week_first = week_first
        self.dots = dots
        self.setFixedHeight(self._height())
        self.update()

    def shift(self, months: int) -> None:
        self.month = tu.add_months(self.month, months)
        self.update()
        pane = self.parent()
        while pane is not None and not hasattr(pane, "mini_month_changed"):
            pane = pane.parent()
        if pane is not None:
            pane.mini_month_changed(self.month)

    def resizeEvent(self, event):
        n = self.ctx.t.m["mini_nav"]
        self.next_btn.setGeometry(self.width() - n, (HEAD_H - n) // 2, n, n)
        self.prev_btn.setGeometry(self.width() - 2 * n - 2, (HEAD_H - n) // 2, n, n)

    def _grid(self):
        return tu.month_grid(self.month, self.ctx.first_weekday)

    def _cell(self, r: int, c: int) -> QRectF:
        wk = self.ctx.t.m["mini_week_col"]
        colw = (self.width() - wk) / 7
        y = HEAD_H + 4 + self.ctx.t.m["mini_head_h"] + r * self._row_h() + 1
        return QRectF(wk + c * colw, y, colw, self._row_h() - 2)

    def paintEvent(self, event):
        ctx, t = self.ctx, self.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        name = tu.cap(tu.MONTHS[self.month.month - 1]) + " "
        p.setFont(th.font(18, 600))
        fm = th.metrics(18, 600)
        p.setPen(t.c("strong"))
        p.drawText(QRectF(0, 0, fm.horizontalAdvance(name) + 2, HEAD_H), Qt.AlignVCenter | Qt.AlignLeft, name)
        p.setPen(t.c("today_text"))
        p.drawText(QRectF(fm.horizontalAdvance(name), 0, 80, HEAD_H), Qt.AlignVCenter | Qt.AlignLeft,
                   str(self.month.year))
        wk = t.m["mini_week_col"]
        colw = (self.width() - wk) / 7
        y = HEAD_H + 4
        f = th.font(10, 600)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0.4)
        p.setFont(f)
        p.setPen(t.c("dim"))
        for c, wd in enumerate(tu.weekday_order(ctx.first_weekday)):
            p.drawText(QRectF(wk + c * colw, y, colw, t.m["mini_head_h"]), Qt.AlignCenter, tu.DAYS_LETTER[wd])
        today = ctx.today()
        for r, row in enumerate(self._grid()):
            row_rect = QRectF(0, self._cell(r, 0).top(), self.width(), self._row_h() - 2)
            if self.view in ("semaine", "travail") and self.week_first is not None and row[0] <= self.week_first <= row[6]:
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("week"))
                p.drawRoundedRect(row_rect, 6, 6)
            p.setFont(th.font(10))
            p.setPen(t.c("dim"))
            p.drawText(QRectF(0, row_rect.top(), wk, row_rect.height()), Qt.AlignCenter, str(tu.iso_week(row[0])))
            for c, d in enumerate(row):
                cell = self._cell(r, c)
                n = t.m["mini_num"]
                dots = self.dots.get(d, [])
                block = n + (2 + 4)
                top = cell.top() + (cell.height() - block) / 2
                num = QRectF(cell.center().x() - n / 2, top, n, n)
                out = d.month != self.month.month
                fg = t.c("off") if out else t.c("text")
                weight = 400
                if d == today:
                    p.setPen(Qt.NoPen)
                    p.setBrush(t.c("today"))
                    p.drawEllipse(num)
                    fg, weight = QColor("#ffffff"), 700
                elif d == self._hover:
                    p.setPen(Qt.NoPen)
                    p.setBrush(t.c("btn"))
                    p.drawEllipse(num)
                if self.view == "jour" and d == self.cur:
                    p.setPen(QPen(t.c("accent"), 1.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(num.adjusted(0.75, 0.75, -0.75, -0.75))
                p.setFont(th.font(12, weight))
                p.setPen(fg)
                p.drawText(num, Qt.AlignCenter, str(d.day))
                if dots:
                    total = len(dots) * 4 + (len(dots) - 1) * 2
                    x = cell.center().x() - total / 2
                    p.setPen(Qt.NoPen)
                    for color in dots:
                        p.setBrush(t.event(color)[1])
                        p.drawEllipse(QRectF(x, num.bottom() + 2, 4, 4))
                        x += 6

    def _day_at(self, pos) -> date | None:
        grid = self._grid()
        for r, row in enumerate(grid):
            for c, d in enumerate(row):
                if self._cell(r, c).contains(pos):
                    return d
        return None

    def mouseMoveEvent(self, event):
        d = self._day_at(event.position())
        if d != self._hover:
            self._hover = d
            self.setCursor(Qt.PointingHandCursor if d else Qt.ArrowCursor)
            if d is not None:
                self.setToolTip(tu.fmt_date(d))
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            d = self._day_at(event.position())
            if d is not None:
                self.dayPicked.emit(d)

    def wheelEvent(self, event):
        self.shift(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()


class CalendarList(QWidget):
    """« CALENDRIERS » : une ligne de 26 px par calendrier, case colorée (visible / masqué)."""
    toggled = Signal(str, bool)
    contextRequested = Signal(object, object)       # calendrier | None, QPoint global
    addRequested = Signal()

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.cals = []
        self._hover = -1
        self.add_btn = AgendaButton(ctx.holder, icon="plus", kind="nav", parent=self, tip="Nouveau calendrier")
        self.add_btn.clicked.connect(self.addRequested)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_calendars(self, cals) -> None:
        self.cals = list(cals)
        self.setFixedHeight(10 + 20 + 26 * len(self.cals) + 4)
        self.update()

    def resizeEvent(self, event):
        self.add_btn.setGeometry(self.width() - 24, 6, 24, 24)

    def _row(self, i: int) -> QRectF:
        return QRectF(0, 10 + 20 + i * 26, self.width(), 26)

    def paintEvent(self, event):
        t = self.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(QRectF(0, 0, self.width(), 1), t.c("line"))
        f = th.font(11, 700)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0.66)
        f.setCapitalization(f.Capitalization.AllUppercase)
        p.setFont(f)
        p.setPen(t.c("section"))
        p.drawText(QRectF(0, 10, self.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, "Calendriers")
        for i, cal in enumerate(self.cals):
            r = self._row(i)
            if i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("hover"))
                p.drawRoundedRect(r.adjusted(-4, 1, 4, -1), 5, 5)
            color = t.event(cal.color)[1]
            paint_check(p, QRectF(0, r.center().y() - 7, 14, 14), cal.visible, color, t.c("off"), 3)
            p.setFont(th.font(13))
            p.setPen(t.c("text") if cal.visible else t.c("dim"))
            suffix = ""
            if cal.source == "google":
                suffix = "  · Google" + (" (lecture)" if cal.read_only else "")
            avail = r.width() - 22
            name = elide(cal.name, 13, 400, avail - th.metrics(11).horizontalAdvance(suffix))
            p.drawText(QRectF(22, r.top(), avail, r.height()), Qt.AlignVCenter | Qt.AlignLeft, name)
            if suffix:
                p.setFont(th.font(11))
                p.setPen(t.c("dim"))
                p.drawText(QRectF(22 + th.metrics(13).horizontalAdvance(name), r.top(), avail, r.height()),
                           Qt.AlignVCenter | Qt.AlignLeft, suffix)

    def _index_at(self, pos) -> int:
        for i in range(len(self.cals)):
            if self._row(i).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, event):
        i = self._index_at(event.position())
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        i = self._index_at(event.position())
        if event.button() == Qt.RightButton:
            self.contextRequested.emit(self.cals[i] if i >= 0 else None, event.globalPosition().toPoint())
            return
        if i >= 0 and event.button() == Qt.LeftButton:
            cal = self.cals[i]
            self.toggled.emit(cal.id, not cal.visible)


class SyncBadge(QWidget):
    """État discret de la synchronisation (bas du panneau latéral) : point coloré + texte ; caché sans compte."""
    clicked = Signal()

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.text = ""
        self.level = "ok"                                # ok | busy | offline | error | conflict
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Synchronisation Google (Réglages : Agenda > Synchronisation)")
        self.hide()

    def set_state(self, text: str, level: str) -> None:
        self.setVisible(bool(text))
        if (text, level) != (self.text, self.level):
            self.text, self.level = text, level
            self.update()

    def paintEvent(self, event):
        t = self.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        color = {"ok": t.event("vert")[1], "busy": t.c("accent"), "offline": t.event("orange")[1],
                 "error": t.event("rouge")[1], "conflict": t.event("rouge")[1]}.get(self.level, t.c("dim"))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(0, 9, 7, 7))
        p.setFont(th.font(11))
        p.setPen(t.c("dim"))
        p.drawText(QRectF(13, 0, self.width() - 13, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   elide(self.text, 11, 400, self.width() - 13))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class Sidebar(QWidget):
    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("AgendaSidebar")
        self.mini = MiniCalendar(ctx, self)
        self.upcoming = AgendaList(ctx, large=False)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.upcoming)
        hl.addStretch(1)
        self.scroll.setWidget(holder)
        self._holder = holder
        self.calendars = CalendarList(ctx, self)
        self.sync = SyncBadge(ctx, self)
        lay = QVBoxLayout(self)
        m = ctx.t.m
        lay.setContentsMargins(m["side_pad_h"], m["side_pad_top"], m["side_pad_h"], m["side_pad_bottom"])
        lay.setSpacing(0)
        lay.addWidget(self.mini)
        lay.addSpacing(4)
        self._sep = QWidget()
        self._sep.setFixedHeight(1)
        lay.addWidget(self._sep)
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.calendars)
        lay.addWidget(self.sync)
        self.restyle()

    def restyle(self) -> None:
        """Couleurs : feuille du panneau (`AgendaPane.restyle`, noms d'objets ci-dessous) ; ici, repeindre."""
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._sep.setObjectName("AgendaSep")
        self._sep.setAttribute(Qt.WA_StyledBackground, True)
        self.scroll.viewport().setObjectName("AgendaSideViewport")
        self._holder.setObjectName("AgendaSideHolder")
        for w in (self.mini, self.upcoming, self.calendars, self.sync):
            w.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(QRectF(self.width() - 1, 0, 1, self.height()), self.ctx.t.c("line"))
