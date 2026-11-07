"""Vue Année d'après le design (`.yv`, `.ym`, `.yd`) : douze mois en grille (4 colonnes, 3 en fenêtre étroite),
intensité des jours selon le nombre d'événements (accent à 22 / 40 / 62 %), aujourd'hui en pastille, légende
« Moins … Plus ». Clic sur le nom d'un mois = vue Mois ; clic sur un jour = vue Jour."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..core import timeutil as tu
from . import theme as th
from .context import ViewContext

PAD_T, PAD_H, PAD_B = 18, 24, 8
GAP_V, GAP_H = 20, 28
TITLE_H = 24
HEAD_H = 18
DAY_H = 22
LEGEND_H = 36


class YearView(QWidget):
    monthActivated = Signal(object)
    dayActivated = Signal(object)

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.year = date.today().year
        self.counts: dict[date, int] = {}
        self._hover_title = -1
        self._hover_day: date | None = None
        self.setMouseTracking(True)

    def set_data(self, year: int, counts: dict[date, int]) -> None:
        self.year = year
        self.counts = counts
        self.updateGeometry()
        self.update()

    def _ncols(self) -> int:
        w = self.width()
        return 4 if w >= 880 else (3 if w >= 640 else 2)

    def _month_h(self) -> int:
        return TITLE_H + 4 + HEAD_H + 6 * (DAY_H + 2)

    def sizeHint(self) -> QSize:
        return QSize(900, self._height_for(4))

    def _height_for(self, ncols: int) -> int:
        rows = (12 + ncols - 1) // ncols
        return PAD_T + rows * self._month_h() + (rows - 1) * GAP_V + PAD_B + LEGEND_H

    def minimumSizeHint(self) -> QSize:
        return QSize(480, self._height_for(self._ncols()))

    def resizeEvent(self, event):
        self.setMinimumHeight(self._height_for(self._ncols()))

    def _month_rect(self, mi: int) -> QRectF:
        n = self._ncols()
        mw = (self.width() - 2 * PAD_H - (n - 1) * GAP_H) / n
        r, c = divmod(mi, n)
        return QRectF(PAD_H + c * (mw + GAP_H), PAD_T + r * (self._month_h() + GAP_V), mw, self._month_h())

    def _day_cells(self, mi: int):
        rect = self._month_rect(mi)
        first = date(self.year, mi + 1, 1)
        cw = rect.width() / 7
        out = []
        for r, row in enumerate(tu.month_grid(first, self.ctx.first_weekday)):
            for c, d in enumerate(row):
                if d.month != mi + 1:
                    continue
                y = rect.top() + TITLE_H + 4 + HEAD_H + r * (DAY_H + 2)
                out.append((QRectF(rect.left() + c * cw, y, cw, DAY_H), d))
        return out

    def _title_rect(self, mi: int) -> QRectF:
        rect = self._month_rect(mi)
        fm = th.metrics(14, 600)
        return QRectF(rect.left() - 4, rect.top(), fm.horizontalAdvance(tu.cap(tu.MONTHS[mi])) + 8, TITLE_H)

    def paintEvent(self, event):
        ctx, t = self.ctx, self.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), t.c("bg"))
        today = ctx.today()
        letters = [tu.DAYS_LETTER[i] for i in tu.weekday_order(ctx.first_weekday)]
        for mi in range(12):
            rect = self._month_rect(mi)
            if not rect.adjusted(-4, -4, 4, 4).intersects(QRectF(event.rect())):
                continue
            title = self._title_rect(mi)
            if mi == self._hover_title:
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("btn"))
                p.drawRoundedRect(title, 5, 5)
            is_cur = self.year == today.year and mi == today.month - 1
            p.setFont(th.font(14, 600))
            p.setPen(t.c("today_text") if is_cur else t.c("strong"))
            p.drawText(title.adjusted(4, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, tu.cap(tu.MONTHS[mi]))
            cw = rect.width() / 7
            p.setFont(th.font(10, 600))
            p.setPen(t.c("dim"))
            for c, letter in enumerate(letters):
                p.drawText(QRectF(rect.left() + c * cw, rect.top() + TITLE_H + 4, cw, HEAD_H), Qt.AlignCenter, letter)
            for cell, d in self._day_cells(mi):
                n = self.counts.get(d, 0)
                pill = cell.adjusted(0.5, 0, -0.5, 0)
                fg = t.c("text")
                weight = 400
                if d == today:
                    p.setPen(Qt.NoPen)
                    p.setBrush(t.c("today"))
                    p.drawRoundedRect(pill, 11, 11)
                    fg, weight = QColor("#ffffff"), 700
                elif n:
                    level = 3 if n >= 4 else (2 if n >= 2 else 1)
                    p.setPen(Qt.NoPen)
                    p.setBrush(t.heat(level))
                    p.drawRoundedRect(pill, 11, 11)
                    if level == 3:
                        fg = t.c("strong")
                if d == self._hover_day and d != today:
                    p.setPen(QPen(t.c("accent"), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
                p.setFont(th.font(11, weight))
                p.setPen(fg)
                p.drawText(cell, Qt.AlignCenter, str(d.day))
        # Légende « Moins ○ ● ● ● Plus » en bas à droite.
        y = self.height() - LEGEND_H + 8
        x = self.width() - PAD_H
        p.setFont(th.font(11))
        fm = th.metrics(11)
        p.setPen(t.c("dim"))
        w_plus = fm.horizontalAdvance("Plus")
        x -= w_plus
        p.drawText(QRectF(x, y, w_plus + 2, 16), Qt.AlignVCenter | Qt.AlignLeft, "Plus")
        for level in (3, 2, 1, 0):
            x -= 6 + 12
            r = QRectF(x, y + 2, 12, 12)
            if level:
                p.setPen(Qt.NoPen)
                p.setBrush(t.heat(level))
            else:
                p.setPen(QPen(t.c("line"), 1))
                p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
        w_less = fm.horizontalAdvance("Moins")
        x -= 6 + w_less
        p.setPen(t.c("dim"))
        p.drawText(QRectF(x, y, w_less + 2, 16), Qt.AlignVCenter | Qt.AlignLeft, "Moins")

    def _hit(self, pos: QPointF):
        for mi in range(12):
            if self._title_rect(mi).contains(pos):
                return "title", mi
            if self._month_rect(mi).contains(pos):
                for cell, d in self._day_cells(mi):
                    if cell.contains(pos):
                        return "day", d
        return None, None

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            kind, value = self._hit(QPointF(e.pos()))
            if kind == "day":
                n = self.counts.get(value, 0)
                QToolTip.showText(e.globalPos(), f"{tu.fmt_day_short(value)} : "
                                                 f"{n or 'aucun'} événement{'s' if n > 1 else ''}", self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mouseMoveEvent(self, event):
        kind, value = self._hit(event.position())
        title = value if kind == "title" else -1
        day = value if kind == "day" else None
        if title != self._hover_title or day != self._hover_day:
            self._hover_title, self._hover_day = title, day
            self.setCursor(Qt.PointingHandCursor if kind else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover_title, self._hover_day = -1, None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        kind, value = self._hit(event.position())
        if kind == "title":
            self.monthActivated.emit(date(self.year, value + 1, 1))
        elif kind == "day":
            self.dayActivated.emit(value)
