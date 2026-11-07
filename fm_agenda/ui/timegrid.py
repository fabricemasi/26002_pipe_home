"""Vues horaires (Jour, Semaine, Semaine de travail) d'après le design : en-tête des jours (`.dh`, ou grand numéro
de la vue Jour), bande « Journée » (`.ad`), grille de 52 px par heure (filets des heures et demi-heures, colonnes
des week-ends et d'aujourd'hui teintées, indicateur de l'heure courante) dans une zone défilante.

Tout est PEINT (un widget par zone) : une semaine chargée coûte une passe de peinture, le survol et le glisser ne
repeignent que les rectangles touchés. Disposition (voies des événements simultanés) recalculée seulement quand les
données, la largeur ou le zoom changent.

Gestes : clic = sélection ; double-clic = ouvrir (événement) ou créer (case vide) ; tracer dans une case vide =
créer sur la plage tracée ; glisser un événement = le déplacer (y compris vers un autre jour) ; glisser son bord
haut / bas = changer sa durée ; Échap annule le geste ; Ctrl + molette = hauteur des heures.

Événements longs (`agenda_long_bars`, à partir de `agenda_long_threshold` heures, y compris ceux de plus de 24 h) :
barres fléchées sans texte au bord gauche de la colonne (géométrie et peinture : `longbars.py`), blocs décalés à
leur droite. Survol = encart à la hauteur du curseur (il le suit, retiré quand le curseur quitte la barre) ; clic =
encart épinglé (reclic, × ou Échap : retiré) ; poignées début / fin / milieu = changer le début, la fin, décaler
(pas `agenda_snap_minutes`, autre jour en vue Semaine), encart en direct avec les nouveaux horaires."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea, QToolTip, QVBoxLayout, QWidget

from ..core import layout as lay
from ..core import timeutil as tu
from ..core.model import Occurrence
from . import longbars as lb
from . import theme as th
from .context import ViewContext
from .painting import paint_bar, paint_event_block
from .widgets import elide

BAR_ROW = 32          # ligne de la bande « Journée » (grid-template-rows minmax(32px, auto))
BAR_H = 22            # barre `.ad` (margin 5 px)
EDGE = 5              # bord saisissable pour changer la durée
DRAG_START = 4        # px avant qu'un appui devienne un glisser


class Geom:
    def __init__(self, width: float, gutter: float, n: int):
        self.gutter = gutter
        self.n = max(1, n)
        self.colw = max(1.0, (width - gutter) / self.n)

    def x(self, i: int) -> float:
        return self.gutter + i * self.colw

    def col_at(self, x: float) -> int:
        return max(0, min(self.n - 1, int((x - self.gutter) // self.colw)))


def _scrollbar_qss(t) -> str:
    return (f"QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {t.hexc('btn_line')}; border-radius: 4px; min-height: 30px; "
            f"margin: 2px; }} QScrollBar::handle:vertical:hover {{ background: {t.hexc('off')}; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }} "
            f"QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}"
            f"QScrollBar:horizontal {{ height: 0; }}")


class TimeGridView(QWidget):
    selected = Signal(object)                 # Occurrence | None
    activated = Signal(object)                # double-clic sur un événement
    createRequested = Signal(object, object, bool)     # début, fin, journée
    dayActivated = Signal(object)             # clic sur un en-tête de jour (vue Semaine)
    moveRequested = Signal(object, object, object)     # occurrence, nouveau début, nouvelle fin
    contextRequested = Signal(object, object, object)  # occurrence | None, case (datetime | date), QPoint global
    toggleDone = Signal(object)

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.days: list[date] = []
        self.mode = "week"
        self.selected_key: str | None = None
        self.timed: list[Occurrence] = []
        self.bars: list[Occurrence] = []
        self.header = _DayHeader(self)
        self.band = _AllDayBand(self)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setWidgetResizable(False)
        self.canvas = _Canvas(self)
        self.scroll.setWidget(self.canvas)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda *_a: self._sync_widths())
        lay_ = QVBoxLayout(self)
        lay_.setContentsMargins(0, 0, 0, 0)
        lay_.setSpacing(0)
        lay_.addWidget(self.header)
        lay_.addWidget(self.band)
        lay_.addWidget(self.scroll, 1)
        self._now_timer = QTimer(self)
        self._now_timer.timeout.connect(self._tick)
        self._now_timer.start(30_000)
        self.restyle()

    # -- données --

    def set_data(self, days: list[date], occs: list[Occurrence], mode: str, selected_key: str | None) -> None:
        self.days = list(days)
        self.mode = mode
        self.selected_key = selected_key
        # barres fléchées : un événement horaire de plus de 24 h reste dans la grille (maquette), pas dans « Journée »
        long_on = bool(self.ctx.s("agenda_long_bars", True))
        self.bars = [o for o in occs if o.all_day or (not long_on and o.spans_days())]
        self.timed = [o for o in occs if not o.all_day and (long_on or not o.spans_days())]
        self.header.updateGeometry()
        self.header.update()
        self.band.relayout()
        self._resize_canvas()
        self.canvas.relayout()

    def set_selected(self, key: str | None) -> None:
        if key != self.selected_key:
            self.selected_key = key
            self.band.update()
            self.canvas.update()

    def restyle(self) -> None:
        """Fond et barres de défilement : feuille du panneau (`AgendaPane.restyle`, sélecteur `AgendaViewport`)."""
        self.scroll.viewport().setObjectName("AgendaViewport")
        self.header.updateGeometry()
        for w in (self.header, self.band, self.canvas):
            w.update()

    def zoom_changed(self) -> None:
        center = self.visible_minute()
        self._resize_canvas()
        self.canvas.relayout()
        self.scroll_to_minute(center, center=True)

    # -- géométrie --

    def content_width(self) -> int:
        return self.scroll.viewport().width()

    def geom(self) -> Geom:
        return Geom(self.content_width(), self.ctx.t.m["gutter"], len(self.days))

    def _resize_canvas(self) -> None:
        h0, h1 = self.ctx.hour_range
        height = int(round((h1 - h0) * self.ctx.hour_h)) + 1
        size = QSize(self.content_width(), height)
        if self.canvas.size() != size:
            self.canvas.resize(size)

    def _sync_widths(self) -> None:
        bar = self.scroll.verticalScrollBar()
        right = bar.width() if bar.isVisible() else 0
        for w in (self.header, self.band):
            if w._right != right:
                w._right = right
                w.update()

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Resize:
            self._resize_canvas()
            self.canvas.relayout()
            self.band.relayout()
            self._sync_widths()
        return False

    def minute_y(self, minute: float) -> float:
        h0, _h1 = self.ctx.hour_range
        return (minute - h0 * 60) / 60.0 * self.ctx.hour_h

    def y_minute(self, y: float) -> float:
        h0, _h1 = self.ctx.hour_range
        return h0 * 60 + y / self.ctx.hour_h * 60.0

    def scroll_to_minute(self, minute: float, center: bool = False) -> None:
        y = self.minute_y(minute)
        if center:
            y -= self.scroll.viewport().height() / 2
        self.scroll.verticalScrollBar().setValue(int(max(0, y)))

    def visible_minute(self) -> float:
        bar = self.scroll.verticalScrollBar()
        return self.y_minute(bar.value() + self.scroll.viewport().height() / 2)

    def scroll_to_start(self) -> None:
        start = int(self.ctx.s("agenda_day_start", 8))
        h0, _h1 = self.ctx.hour_range
        self.scroll_to_minute(max(h0 * 60, start * 60 - 15))

    def ensure_visible(self, occ: Occurrence) -> None:
        if occ.spans_days():
            return
        y = self.minute_y(occ.start.hour * 60 + occ.start.minute)
        bar = self.scroll.verticalScrollBar()
        view_h = self.scroll.viewport().height()
        if y < bar.value() or y > bar.value() + view_h - 40:
            bar.setValue(int(max(0, y - view_h / 3)))

    def _tick(self) -> None:
        if self.ctx.today() in self.days:
            self.canvas.update()

    def occurrence_at_key(self, key: str) -> Occurrence | None:
        for o in self.timed + self.bars:
            if o.key == key:
                return o
        return None


class _DayHeader(QWidget):
    """En-tête : jours de la semaine (`.dh`) ou grand numéro du jour (vue Jour)."""

    def __init__(self, view: TimeGridView):
        super().__init__(view)
        self.view = view
        self._right = 0
        self._hover = -1
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(100, 64 + 1 if self.view.mode == "day" else self.view.ctx.t.m["day_head_h"] + 1)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _geom(self) -> Geom:
        return Geom(self.width() - self._right, self.view.ctx.t.m["gutter"], len(self.view.days))

    def paintEvent(self, event):
        view, t = self.view, self.view.ctx.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), t.c("bg"))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), t.c("line"))
        today = view.ctx.today()
        if not view.days:
            return
        if view.mode == "day":
            d = view.days[0]
            is_today = d == today
            circle = QRectF(64, 10, 44, 44)
            if is_today:
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("today"))
                p.drawEllipse(circle)
                p.setFont(th.font(21, 600))
                p.setPen(QColor("#ffffff"))
            else:
                p.setFont(th.font(26, 300))
                p.setPen(t.c("strong"))
            p.drawText(circle, Qt.AlignCenter, str(d.day))
            x = circle.right() + 12
            p.setFont(th.font(15, 600))
            p.setPen(t.c("strong"))
            weekday = tu.cap(tu.DAYS_LONG[d.weekday()]) + (" · aujourd'hui" if is_today else "")
            p.drawText(QRectF(x, 13, self.width() - x - 10, 20), Qt.AlignLeft | Qt.AlignVCenter, weekday)
            p.setFont(th.font(12))
            p.setPen(t.c("dim"))
            p.drawText(QRectF(x, 33, self.width() - x - 10, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{tu.cap(tu.MONTHS[d.month - 1])} {d.year} · semaine {tu.iso_week(d)}")
            return
        g = self._geom()
        week = tu.iso_week(view.days[0])
        p.setFont(th.font(11, 700))
        p.setPen(t.c("dim"))
        p.drawText(QRectF(0, 0, g.gutter - 8, self.height() - 12), Qt.AlignRight | Qt.AlignBottom, f"S{week}")
        for i, d in enumerate(view.days):
            x = g.x(i)
            cell = QRectF(x, 0, g.colw, self.height() - 1)
            if i == self._hover:
                p.fillRect(cell, t.c("hover"))
            p.fillRect(QRectF(x, 0, 1, self.height() - 1), t.c("line"))
            weekend = d.weekday() >= 5
            is_today = d == today
            label = tu.DAYS_SHORT[d.weekday()]
            f = th.font(11, 600)
            f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0.66)
            p.setFont(f)
            p.setPen(t.c("today_text") if is_today else (t.c("dim") if weekend else t.c("muted")))
            fm = th.metrics(11, 600)
            lw = fm.horizontalAdvance(label) + 0.66 * len(label)
            cy = 10 + 16
            p.drawText(QRectF(x + 10, cy - 10, lw + 4, 20), Qt.AlignLeft | Qt.AlignVCenter, label)
            nx = x + 10 + lw + 8
            if is_today:
                circle = QRectF(nx, cy - 16, 32, 32)
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("today"))
                p.drawEllipse(circle)
                p.setFont(th.font(17, 600))
                p.setPen(QColor("#ffffff"))
                p.drawText(circle, Qt.AlignCenter, str(d.day))
            else:
                p.setFont(th.font(22, 300))
                p.setPen(t.c("dim") if weekend else t.c("strong"))
                p.drawText(QRectF(nx, cy - 16, g.colw, 32), Qt.AlignLeft | Qt.AlignVCenter, str(d.day))

    def mouseMoveEvent(self, event):
        if self.view.mode == "day":
            return
        g = self._geom()
        i = g.col_at(event.position().x()) if event.position().x() >= g.gutter else -1
        if i != self._hover:
            self._hover = i
            if i >= 0:
                d = self.view.days[i]
                self.setToolTip(f"Ouvrir le {tu.DAYS_LONG[d.weekday()]} {d.day} {tu.MONTHS[d.month - 1]}")
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        if self.view.mode == "day" or event.button() != Qt.LeftButton:
            return
        g = self._geom()
        if event.position().x() >= g.gutter:
            self.view.dayActivated.emit(self.view.days[g.col_at(event.position().x())])


class _AllDayBand(QWidget):
    """Bande « Journée » : barres des événements journée / de plus de 24 h, rangées en lignes."""

    def __init__(self, view: TimeGridView):
        super().__init__(view)
        self.view = view
        self._right = 0
        self._items: list[tuple[QRectF, Occurrence, bool, bool]] = []
        self._rows = 1
        self._hover: str | None = None
        self._press = None
        self._drag = None
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(100, max(1, self._rows) * BAR_ROW + 1)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _geom(self) -> Geom:
        return Geom(self.width() - self._right, self.view.ctx.t.m["gutter"], len(self.view.days))

    def relayout(self) -> None:
        view = self.view
        g = self._geom()
        items = []
        if not view.days:
            self._items, rows = [], 1
        elif view.mode == "day":
            # Vue Jour : barres côte à côte, retour à la ligne (flex-wrap du design).
            x0, x1 = g.gutter + 3, g.gutter + g.colw - 3
            x, row = x0, 0
            for occ in view.bars:
                w = min(x1 - x0, th.metrics(12, 600).horizontalAdvance(occ.title or "(Sans titre)") + 16)
                if x + w > x1 and x > x0:
                    row += 1
                    x = x0
                items.append((QRectF(x, row * BAR_ROW + 5, w, BAR_H), occ, False, False))
                x += w + 6
            rows = row + 1 if view.bars else 1
        else:
            first_day, last_day = view.days[0], view.days[-1]
            index = {d: i for i, d in enumerate(view.days)}
            spans = []
            for occ in view.bars:
                days = [d for d in occ.days() if d in index]
                if not days:
                    continue
                s = lay.Span(occ, index[days[0]], index[days[-1]])
                s.cut_left = occ.days()[0] < first_day
                s.cut_right = occ.days()[-1] > last_day
                spans.append(s)
            spans.sort(key=lambda s: (s.first, -(s.last - s.first)))
            rows = max(1, lay.pack_spans(spans))
            for s in spans:
                rect = QRectF(g.x(s.first) + 3, s.row * BAR_ROW + 5, (s.last - s.first + 1) * g.colw - 6, BAR_H)
                items.append((rect, s.item, s.cut_left, s.cut_right))
        self._items = items
        if rows != self._rows:
            self._rows = rows
            self.updateGeometry()
        self.setFixedHeight(max(1, self._rows) * BAR_ROW + 1)
        self.update()

    def resizeEvent(self, event):
        self.relayout()

    def paintEvent(self, event):
        view, t = self.view, self.view.ctx.t
        p = QPainter(self)
        p.fillRect(self.rect(), t.c("bg"))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), t.c("line"))
        g = self._geom()
        p.setFont(th.font(11))
        p.setPen(t.c("dim"))
        p.drawText(QRectF(0, 9, g.gutter - 8, 16), Qt.AlignRight | Qt.AlignTop, "Journée")
        for i in range(len(view.days) if view.mode != "day" else 1):
            p.fillRect(QRectF(g.x(i), 0, 1, self.height() - 1), t.c("line"))
        drag_key = self._drag["occ"].key if self._drag and self._drag.get("moved") else None
        for rect, occ, cut_l, cut_r in self._items:
            paint_bar(p, rect, view.ctx.colors(occ), occ.title, occ.key == view.selected_key, occ.key == self._hover,
                      t.c("accent"), cut_l, cut_r, dim=0.35 if occ.key == drag_key else 1.0)
        if drag_key:
            rect = self._drag["ghost"]
            if rect is not None:
                paint_bar(p, rect, view.ctx.colors(self._drag["occ"]), self._drag["occ"].title, True, False,
                          t.c("accent"))

    def _item_at(self, pos):
        for rect, occ, _l, _r in reversed(self._items):
            if rect.contains(pos):
                return occ, rect
        return None, None

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            occ, _rect = self._item_at(QPointF(e.pos()))
            if occ is not None:
                QToolTip.showText(e.globalPos(), _tooltip(self.view.ctx, occ), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._press is not None and event.buttons() & Qt.LeftButton:
            occ = self._press["occ"]
            if occ is not None and not occ.read_only and self.view.mode != "day" and (
                    self._drag or (pos - self._press["pos"]).manhattanLength() > DRAG_START):
                if self._drag is None and self.view.ctx.drag_needs_ctrl and not self._press["ctrl"]:
                    return
                g = self._geom()
                dcol = g.col_at(pos.x()) - g.col_at(self._press["pos"].x())
                rect = QRectF(self._press["rect"])
                rect.translate(dcol * g.colw, 0)
                self._drag = {"occ": occ, "moved": True, "dcol": dcol, "ghost": rect}
                self.update()
            return
        occ, _rect = self._item_at(pos)
        key = occ.key if occ else None
        if key != self._hover:
            self._hover = key
            self.setCursor(Qt.PointingHandCursor if occ else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        if self._hover:
            self._hover = None
            self.update()

    def mousePressEvent(self, event):
        pos = event.position()
        occ, rect = self._item_at(pos)
        if event.button() == Qt.RightButton:
            slot = self._day_at(pos.x())
            self.view.contextRequested.emit(occ, slot, event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._press = {"occ": occ, "pos": pos, "rect": rect, "ctrl": ctrl}
        self._drag = None

    def mouseReleaseEvent(self, event):
        press, drag = self._press, self._drag
        self._press = self._drag = None
        if press is None or event.button() != Qt.LeftButton:
            return
        if drag and drag.get("moved") and drag["dcol"]:
            occ = drag["occ"]
            days = timedelta(days=drag["dcol"])
            if occ.all_day:
                self.view.moveRequested.emit(occ, occ.start_date + days, occ.end_date + days)
            else:
                self.view.moveRequested.emit(occ, occ.start + days, occ.end + days)
            self.update()
            return
        self.update()
        self.view.selected.emit(press["occ"])

    def mouseDoubleClickEvent(self, event):
        occ, _rect = self._item_at(event.position())
        if occ is not None:
            self.view.activated.emit(occ)
            return
        d = self._day_at(event.position().x())
        if d is not None:
            self.view.createRequested.emit(d, d + timedelta(days=1), True)

    def _day_at(self, x: float):
        g = self._geom()
        if not self.view.days or x < g.gutter:
            return None
        return self.view.days[0 if self.view.mode == "day" else g.col_at(x)]

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._drag:
            self._press = self._drag = None
            self.update()
            return
        super().keyPressEvent(event)


def _tooltip(ctx: ViewContext, occ: Occurrence) -> str:
    if occ.all_day:
        days = occ.days()
        when = (tu.fmt_day_short(days[0]) if len(days) == 1 else
                f"Du {days[0].day} {tu.MONTHS_SHORT[days[0].month - 1]} au {days[-1].day} "
                f"{tu.MONTHS_SHORT[days[-1].month - 1]}") + " · journée"
    else:
        when = f"{tu.fmt_day_short(occ.start.date())} · {tu.fmt_range(occ.start, occ.end, ctx.h24)}"
    lines = [f"<b>{_esc(occ.title or '(Sans titre)')}</b>", _esc(when)]
    if occ.location:
        lines.append(_esc(occ.location))
    cal = ctx.calendar_name(occ.calendar_id)
    if cal:
        lines.append(f"<span style='color:#8a9197'>{_esc(cal)}{' · récurrent' if occ.recurring else ''}</span>")
    return "<br>".join(lines)


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _Canvas(QWidget):
    """Grille horaire défilante : graduations, colonnes, événements, heure courante, gestes."""

    def __init__(self, view: TimeGridView):
        super().__init__()
        self.view = view
        self.boxes: list[tuple[QRectF, Occurrence, bool, str, str]] = []   # rect, occ, une ligne, heure, sous-titre
        self.lines: list[lb.BarSeg] = []          # événements longs en barres (un morceau par jour)
        self._T, self._A = 10.0, 9.0              # épaisseurs de la barre et de la flèche (réglages)
        self._bar_hover: dict | None = None       # barre survolée : clé, colonne, hauteur du curseur, poignée
        self._pin: dict | None = None             # encart épinglé : clé, colonne, minute du clic
        self._mute_key: str | None = None         # encart retiré par un reclic : pas de survol avant d'avoir quitté
        self._pop_hot: str | None = None          # bouton survolé de l'encart épinglé (« close » / « open »)
        self._hover: str | None = None
        self._press = None
        self._gesture = None
        self._auto = QTimer(self)
        self._auto.setInterval(30)
        self._auto.timeout.connect(self._auto_scroll)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    # -- disposition --

    def relayout(self) -> None:
        view, ctx = self.view, self.view.ctx
        g = view.geom()
        h0, h1 = ctx.hour_range
        lo, hi = h0 * 60, h1 * 60
        index = {d: i for i, d in enumerate(view.days)}
        per_day: dict[int, list] = {i: [] for i in range(len(view.days))}
        tz = ctx.tz
        for occ in view.timed:
            for d in occ.days():
                i = index.get(d)
                if i is None:
                    continue
                day0 = tu.day_start(d, tz)
                a = (occ.start - day0).total_seconds() / 60
                b = (occ.end - day0).total_seconds() / 60
                a, b = max(a, 0), min(b, 1440)
                if occ.end == occ.start:
                    b = a
                per_day[i].append((a, b, occ))
        boxes = []
        lines: list[lb.BarSeg] = []
        hour_h = ctx.hour_h
        long_on, threshold, T, A = self._long_params()
        self._T, self._A = T, A
        lane_w = lb.lane_width(T, A)
        for i, items in per_day.items():
            longs = []
            if long_on:
                longs = [it for it in items if self._is_long(it[2], threshold) and min(it[1], hi) > max(it[0], lo)]
                items = [it for it in items if not any(it is lg for lg in longs)]
            x = g.x(i)
            off = 0.0
            if longs:
                placed_l = lay.lay_timed(longs)
                off = max(pl.lane + 1 for pl in placed_l) * lane_w
                for pl in placed_l:
                    seg = self._bar_segment(pl.item, i, x + 1 + pl.lane * lane_w, pl.item.start, pl.item.end, T, A,
                                            grips=not pl.item.read_only)
                    if seg is not None:
                        lines.append(seg)
            placed = lay.lay_timed(items)
            for pl in placed:
                occ = pl.item
                a, b = max(pl.a, lo), min(pl.b, hi)
                if pl.a >= hi or pl.b <= lo:
                    a, b = (hi - 30, hi) if pl.a >= hi else (lo, lo + 30)
                task = occ.is_task and occ.end == occ.start
                top = view.minute_y(a)
                height = 22 if task else max(22.0, (b - a) / 60 * hour_h)
                one = task or height < 40
                if off:
                    avail = g.colw - off - 4                 # blocs à droite des barres (maquette : calc(off …))
                    left = x + 1 + off + pl.lane * avail / pl.lanes
                    width = avail / pl.lanes - 3
                else:
                    left = x + pl.lane * g.colw / pl.lanes + 3
                    width = g.colw / pl.lanes - 7
                rect = QRectF(left, top + 1, max(8.0, width), height - 1)
                if occ.end > occ.start and height >= 78:
                    time_text = tu.fmt_range(occ.start, occ.end, ctx.h24)
                else:
                    time_text = tu.fmt_time(occ.start, ctx.h24)
                sub = occ.project if view.mode == "day" else ""
                boxes.append((rect, occ, one, time_text, sub))
        self.boxes = boxes
        self.lines = lines
        self._bar_hover = None
        if self._pin is not None and not any(s.occ.key == self._pin["key"] for s in lines):
            self._pin = None
        self.update()

    # -- événements longs en barres --

    def _long_params(self) -> tuple[bool, float, float, float]:
        ctx = self.view.ctx
        return (bool(ctx.s("agenda_long_bars", True)), float(ctx.s("agenda_long_threshold", 4)) * 60,
                float(max(2, int(ctx.s("agenda_bar_width", 10)))), float(max(2, int(ctx.s("agenda_arrow_width", 9)))))

    @staticmethod
    def _is_long(occ: Occurrence, threshold: float) -> bool:
        return not (occ.is_task and occ.end == occ.start) and (occ.end - occ.start).total_seconds() / 60 >= threshold

    def _bar_segment(self, occ, i: int, x: float, start, end, T: float, A: float, grips: bool = True):
        """Morceau de barre de [start, end) dans la colonne `i` (None s'il n'y a rien de visible ce jour-là)."""
        view, ctx = self.view, self.view.ctx
        h0, h1 = ctx.hour_range
        lo, hi = max(0, h0 * 60), min(1440, h1 * 60)
        day0 = tu.day_start(view.days[i], ctx.tz)
        a = (start - day0).total_seconds() / 60
        b = (end - day0).total_seconds() / 60
        a_vis, b_vis = max(a, lo), min(b, hi)
        if b_vis <= a_vis:
            return None
        mid = a + (b - a) / 2
        mid_y = view.minute_y(mid) if lo <= mid < hi else None
        return lb.build_seg(occ, i, x, view.minute_y(a_vis), view.minute_y(b_vis), a >= lo, b <= hi, T, A, mid_y,
                            grips)

    def _bar_at(self, pos: QPointF):
        for seg in reversed(self.lines):
            part = lb.hit(seg, pos)
            if part is not None:
                return seg, part
        return None, None

    def _seg_for(self, key: str, col: int):
        first = None
        for seg in self.lines:
            if seg.occ.key == key:
                if seg.col == col:
                    return seg
                first = first or seg
        return first

    def _make_popover(self, occ, x_left: float, y: float, start, end, pinned: bool) -> lb.Popover:
        view, ctx = self.view, self.view.ctx
        x_right = x_left + self._T
        flip = x_right + lb.POP_FLIP > self.width()
        below = y - view.scroll.verticalScrollBar().value() < lb.POP_BELOW
        cal = ctx.calendar_name(occ.calendar_id)
        meta = " · ".join(x for x in (cal, occ.project) if x)
        return lb.layout_popover(x_left, x_right, y, flip, below, occ.title, lb.when_text(start, end, ctx.h24), meta,
                                 ctx.colors(occ), pinned, pinned and view.mode != "day")

    def _pin_popover(self) -> lb.Popover | None:
        pin = self._pin
        seg = self._seg_for(pin["key"], pin["col"]) if pin else None
        if seg is None:
            return None
        return self._make_popover(seg.occ, seg.x, self.view.minute_y(pin["minute"]), seg.occ.start, seg.occ.end, True)

    def _bar_gesture(self):
        gst = self._gesture
        return gst if gst and gst.get("active") and gst["kind"].startswith("bar_") else None

    def _popovers(self) -> list:
        """Encarts à peindre : l'épinglé (sauf pendant le glisser de son événement), puis celui du survol ou du
        glisser en cours."""
        out = []
        gst = self._bar_gesture()
        pin = self._pin
        if pin is not None and not (gst and gst["occ"].key == pin["key"]):
            pop = self._pin_popover()
            if pop is not None:
                out.append((pop, self._pop_hot))
        if gst is not None:
            g = self.view.geom()
            out.append((self._make_popover(gst["occ"], g.x(gst["col"]) + 1, gst["y"], gst["start"], gst["end"],
                                           False), None))
        else:
            hv = self._bar_hover
            if hv is not None and hv["key"] != self._mute_key and not (pin and pin["key"] == hv["key"]):
                seg = hv["seg"]
                out.append((self._make_popover(seg.occ, seg.x, hv["y"], seg.occ.start, seg.occ.end, False), None))
        return out

    def _overlay_rects(self) -> list[QRectF]:
        """Ce qui change avec le survol / l'épinglé / le glisser : encarts, barres concernées, fantôme."""
        rects = [pop.rect() for pop, _hot in self._popovers()]
        keys = {k for k in ((self._bar_hover or {}).get("key"), (self._pin or {}).get("key")) if k}
        rects += [s.bounds for s in self.lines if s.occ.key in keys]
        gst = self._bar_gesture()
        if gst is not None:
            rects += [s.bounds for s in gst["ghost"]]
        return rects

    def _repaint(self, before: list[QRectF]) -> None:
        for r in before + self._overlay_rects():
            self.update(r.toAlignedRect().adjusted(-2, -2, 2, 2))

    def _set_bar_hover(self, seg, part: str | None = None, y: float = 0.0) -> None:
        if seg is None:
            if self._bar_hover is None and self._mute_key is None:
                return
            before = self._overlay_rects()
            self._bar_hover = None
            self._mute_key = None                   # quitter la barre réarme le survol
            self._repaint(before)
            return
        key = seg.occ.key
        hv = self._bar_hover
        same = bool(hv) and hv["key"] == key and hv["col"] == seg.col and hv["part"] == part
        if same and abs(hv["y"] - y) < 0.5:
            return
        if same:
            # le curseur glisse le long de la même barre : seul l'encart de survol se déplace
            before = [pop.rect() for pop, _hot in self._popovers()]
            hv["y"] = y
            for r in before + [pop.rect() for pop, _hot in self._popovers()]:
                self.update(r.toAlignedRect().adjusted(-2, -2, 2, 2))
            return
        before = self._overlay_rects()
        if self._mute_key is not None and self._mute_key != key:
            self._mute_key = None
        self._bar_hover = {"key": key, "col": seg.col, "y": y, "part": part, "seg": seg}
        self._repaint(before)

    def _set_pin(self, pin: dict | None) -> None:
        before = self._overlay_rects()
        self._pin = pin
        self._pop_hot = None
        self._repaint(before)

    def _build_ghost(self, gst: dict) -> None:
        g = self.view.geom()
        segs = []
        for i in range(len(self.view.days)):
            seg = self._bar_segment(gst["occ"], i, g.x(i) + 1, gst["start"], gst["end"], self._T, self._A)
            if seg is not None:
                segs.append(seg)
        gst["ghost"] = segs

    def _begin_bar_gesture(self, press: dict) -> None:
        occ, part = press["occ"], press["part"]
        if part not in ("s", "e", "m") or occ.read_only:
            return
        if self.view.ctx.drag_needs_ctrl and not press["ctrl"]:
            return
        before = self._overlay_rects()
        self._bar_hover = None
        self._gesture = {"kind": "bar_" + part, "occ": occ, "col0": press["col"], "col": press["col"],
                         "minute0": self.view.y_minute(press["pos"].y()), "start": occ.start, "end": occ.end,
                         "y": press["pos"].y(), "ghost": [], "active": True}
        self._build_ghost(self._gesture)
        self._repaint(before)
        self.setCursor(Qt.ClosedHandCursor if part == "m" else Qt.SizeVerCursor)

    def _update_bar_gesture(self, pos: QPointF) -> None:
        gst, view, ctx = self._gesture, self.view, self.view.ctx
        before = self._overlay_rects()
        h0, h1 = ctx.hour_range
        col = view.geom().col_at(pos.x()) if view.mode != "day" else gst["col0"]
        minute = max(h0 * 60, min(h1 * 60, view.y_minute(pos.y())))
        delta = timedelta(days=col - gst["col0"], minutes=self._snap(minute - gst["minute0"]))
        occ, kind, tz = gst["occ"], gst["kind"], ctx.tz

        def shift(dt):
            return tu.localize(dt.replace(tzinfo=None) + delta, tz)

        start, end = occ.start, occ.end
        least = timedelta(minutes=lb.MIN_MINUTES)
        if kind == "bar_m":
            start, end = shift(occ.start), shift(occ.end)
        elif kind == "bar_s":
            start = min(shift(occ.start), occ.end - least)
        else:
            end = max(shift(occ.end), occ.start + least)
        gst["col"], gst["y"] = col, pos.y()
        if (start, end) != (gst["start"], gst["end"]):
            gst["start"], gst["end"] = start, end
            self._build_ghost(gst)                     # un nouveau pas : seul le fantôme est recalculé
        self._repaint(before)

    def _finish_bar_gesture(self, gst: dict, pos: QPointF) -> None:
        occ = gst["occ"]
        if self._pin is not None and self._pin["key"] == occ.key:
            # l'encart épinglé suit l'événement : réancré là où la poignée a été lâchée
            self._pin = {"key": occ.key, "col": gst["col"], "minute": self.view.y_minute(pos.y())}
        self.update()
        if (gst["start"], gst["end"]) != (occ.start, occ.end):
            self.view.moveRequested.emit(occ, gst["start"], gst["end"])

    # -- peinture --

    def paintEvent(self, event):
        view, ctx, t = self.view, self.view.ctx, self.view.ctx.t
        p = QPainter(self)
        clip = QRectF(event.rect())
        p.fillRect(clip, t.c("bg"))
        g = view.geom()
        h0, h1 = ctx.hour_range
        hour_h = ctx.hour_h
        today = ctx.today()
        height = self.height()
        weekend_c, today_c = t.c("weekend"), t.c("todaycol")
        for i, d in enumerate(view.days):
            col = QRectF(g.x(i), 0, g.colw, height)
            if not col.intersects(clip):
                continue
            if d.weekday() >= 5:
                p.fillRect(col, weekend_c)
            if d == today:
                p.fillRect(col, today_c)
        grid, half = t.c("grid"), t.c("grid_half")
        first = max(h0, int(h0 + clip.top() / hour_h))
        last = min(h1, int(h0 + clip.bottom() / hour_h) + 1)
        for h in range(first, last + 1):
            y = (h - h0) * hour_h
            if h < h1:
                p.fillRect(QRectF(g.gutter, y + hour_h / 2, self.width() - g.gutter, 1), half)
            p.fillRect(QRectF(g.gutter, y, self.width() - g.gutter, 1), grid)
        for i in range(len(view.days)):
            p.fillRect(QRectF(g.x(i), 0, 1, height), t.c("line"))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setFont(th.font(11))
        p.setPen(t.c("dim"))
        for h in range(first, min(last, h1)):
            y = (h - h0) * hour_h
            top = y + 3 if h == h0 else y - 7
            p.drawText(QRectF(0, top, g.gutter - 8, 14), Qt.AlignRight | Qt.AlignTop, tu.fmt_hour(h, ctx.h24))
        gesture = self._gesture if self._gesture and self._gesture.get("active") else None
        moving_key = gesture["occ"].key if gesture and gesture.get("occ") is not None else None
        accent = t.c("accent")
        for rect, occ, one, time_text, sub in self.boxes:
            if not rect.intersects(clip.adjusted(-3, -3, 3, 3)):
                continue
            paint_event_block(p, rect, ctx.colors(occ), occ.title, time_text, sub, one,
                              occ.key == view.selected_key and not moving_key, occ.key == self._hover, accent,
                              task=occ.is_task, done=occ.done, dim=0.35 if occ.key == moving_key else 1.0,
                              tentative=occ.status == "tentative")
        if self.lines:
            hv, pin = self._bar_hover, self._pin
            hov_key = hv["key"] if hv else None
            pin_key = pin["key"] if pin else None
            T, A = self._T, self._A
            for seg in self.lines:
                if not seg.bounds.intersects(clip):
                    continue
                key = seg.occ.key
                lb.paint_seg(p, seg, ctx.colors(seg.occ)[1], T, A, key == view.selected_key and not moving_key,
                             key == hov_key, accent, dim=0.35 if key == moving_key else 1.0,
                             grips=key in (hov_key, pin_key) and not gesture and not seg.occ.read_only,
                             hot=hv["part"] if key == hov_key else None)
        if gesture:
            self._paint_gesture(p, gesture, g)
        if today in view.days:
            now = ctx.now()
            minute = now.hour * 60 + now.minute
            if h0 * 60 <= minute <= h1 * 60:
                y = view.minute_y(minute)
                i = view.days.index(today) if view.mode != "day" else 0
                x = g.x(i)
                p.setPen(Qt.NoPen)
                p.setBrush(t.c("today"))
                p.drawRect(QRectF(x, y - 1, g.colw, 2))
                p.drawEllipse(QRectF(x - 1, y - 5, 10, 10))
                label = tu.fmt_time(now, ctx.h24)
                f = th.font(11, 700)
                fm = th.metrics(11, 700)
                w = fm.horizontalAdvance(label) + 6
                box = QRectF(g.gutter - 5 - w, y - 8, w, 15)
                p.fillRect(box, t.c("bg"))
                p.setFont(f)
                p.setPen(t.c("today_text"))
                p.drawText(box, Qt.AlignCenter, label)
        for pop, hot in self._popovers():                # encarts des barres : au-dessus de tout
            if pop.rect().intersects(clip):
                lb.paint_popover(p, t, pop, hot)

    def _paint_gesture(self, p: QPainter, gesture: dict, g: Geom) -> None:
        ctx, t = self.view.ctx, self.view.ctx.t
        if gesture["kind"].startswith("bar_"):
            bar = ctx.colors(gesture["occ"])[1]
            hot = gesture["kind"][4:]
            for seg in gesture["ghost"]:
                lb.paint_seg(p, seg, bar, self._T, self._A, True, False, t.c("accent"), grips=True, hot=hot)
            return
        col, a, b = gesture["col"], gesture["a"], gesture["b"]
        top, bottom = self.view.minute_y(a), self.view.minute_y(b)
        rect = QRectF(g.x(col) + 3, top + 1, g.colw - 7, max(22.0, bottom - top) - 1)
        day = self.view.days[col]
        tz = ctx.tz
        start = tu.localize(datetime.combine(day, datetime.min.time()) + timedelta(minutes=a), tz)
        end = tu.localize(datetime.combine(day, datetime.min.time()) + timedelta(minutes=b), tz)
        label = tu.fmt_range(start, end, ctx.h24)
        if gesture["kind"] == "create":
            colors = t.event(ctx.service.default_calendar().color if ctx.service.default_calendar() else "bleu")
            paint_event_block(p, rect, colors, "Nouvel événement", label, "", rect.height() < 40, True, False,
                              t.c("accent"), dim=0.9)
        else:
            occ = gesture["occ"]
            paint_event_block(p, rect, ctx.colors(occ), occ.title, label, "", rect.height() < 40, True, False,
                              t.c("accent"), task=occ.is_task, done=occ.done)

    # -- gestes --

    def _box_at(self, pos: QPointF):
        for rect, occ, one, _t, _s in reversed(self.boxes):
            if rect.contains(pos):
                part = "body"
                if not one and not (occ.is_task and occ.end == occ.start):
                    if pos.y() - rect.top() <= EDGE:
                        part = "top"
                    elif rect.bottom() - pos.y() <= EDGE:
                        part = "bottom"
                return occ, rect, part
        return None, None, None

    def _minute_at(self, y: float) -> float:
        h0, h1 = self.view.ctx.hour_range
        return max(h0 * 60, min(h1 * 60, self.view.y_minute(y)))

    def _snap(self, minute: float, mode: str = "round") -> int:
        s = self.view.ctx.snap
        import math
        if mode == "floor":
            return int(math.floor(minute / s) * s)
        if mode == "ceil":
            return int(math.ceil(minute / s) * s)
        return int(round(minute / s) * s)

    def _slot(self, pos: QPointF) -> datetime | None:
        g = self.view.geom()
        if not self.view.days or pos.x() < g.gutter:
            return None
        day = self.view.days[g.col_at(pos.x())]
        minute = self._snap(self._minute_at(pos.y()), "floor")
        return tu.localize(datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute), self.view.ctx.tz)

    def event(self, e):
        if e.type() == QEvent.ToolTip and not self._gesture:
            pos = QPointF(e.pos())
            pin_pop = self._pin_popover() if self._pin else None
            if self._bar_at(pos)[0] is not None or (pin_pop is not None and pin_pop.box.contains(pos)):
                QToolTip.hideText()                  # barre : l'encart remplace l'infobulle
                return True
            occ, _rect, _part = self._box_at(pos)
            if occ is not None:
                QToolTip.showText(e.globalPos(), _tooltip(self.view.ctx, occ), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mousePressEvent(self, event):
        pos = event.position()
        if event.button() == Qt.LeftButton and self._pin is not None:
            pop = self._pin_popover()
            where = lb.popover_hit(pop, pos) if pop is not None else None
            if where is not None:                    # l'encart épinglé absorbe le clic
                if where == "close":
                    self._set_pin(None)
                elif where == "open":
                    col = self._pin["col"]
                    self._set_pin(None)
                    if 0 <= col < len(self.view.days):
                        self.view.dayActivated.emit(self.view.days[col])
                return
        seg, bar_part = self._bar_at(pos)
        if seg is not None:
            if event.button() == Qt.RightButton:
                self.view.contextRequested.emit(seg.occ, self._slot(pos), event.globalPosition().toPoint())
            elif event.button() == Qt.LeftButton:
                ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
                self._press = {"occ": seg.occ, "bar": seg, "part": bar_part, "pos": pos, "rect": None,
                               "col": seg.col, "minute": self._minute_at(pos.y()), "ctrl": ctrl, "in_grid": True}
                self._gesture = None
            return
        occ, rect, part = self._box_at(pos)
        if event.button() == Qt.RightButton:
            self.view.contextRequested.emit(occ, self._slot(pos), event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        if occ is not None and occ.is_task and rect is not None and pos.x() < rect.left() + 22 and (
                occ.end == occ.start or rect.height() < 40):
            self.view.toggleDone.emit(occ)                   # clic sur la case de la tâche
            return
        g = self.view.geom()
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._press = {"occ": occ, "part": part, "pos": pos, "rect": rect, "col": g.col_at(pos.x()),
                       "minute": self._minute_at(pos.y()), "ctrl": ctrl, "in_grid": pos.x() >= g.gutter}
        self._gesture = None

    def mouseMoveEvent(self, event):
        pos = event.position()
        press = self._press
        if press is not None and event.buttons() & Qt.LeftButton:
            if self._gesture is None:
                if (pos - press["pos"]).manhattanLength() <= DRAG_START:
                    return
                if press.get("bar") is not None:
                    self._begin_bar_gesture(press)
                else:
                    self._begin_gesture(press)
                if self._gesture is None:
                    return
            self._update_gesture(pos)
            self._last_pos = pos
            self._auto.start()
            return
        if self._pin is not None:                    # boutons de l'encart épinglé
            pop = self._pin_popover()
            where = lb.popover_hit(pop, pos) if pop is not None else None
            hot = where if where in ("close", "open") else None
            if hot != self._pop_hot:
                self._pop_hot = hot
                if pop is not None:
                    self.update(pop.rect().toAlignedRect())
            if where is not None:
                self.setCursor(Qt.PointingHandCursor if hot else Qt.ArrowCursor)
                self._set_bar_hover(None)
                return
        seg, bar_part = self._bar_at(pos)
        if seg is not None:
            ro = seg.occ.read_only
            self.setCursor(Qt.SizeVerCursor if bar_part in ("s", "e") and not ro else
                           Qt.OpenHandCursor if bar_part == "m" and not ro else Qt.PointingHandCursor)
            self._set_bar_hover(seg, bar_part, pos.y())
            if self._hover:
                old = self._rect_of(self._hover)
                self._hover = None
                if old is not None:
                    self.update(old.adjusted(-4, -4, 4, 4).toAlignedRect())
            return
        self._set_bar_hover(None)
        occ, _rect, part = self._box_at(pos)
        key = occ.key if occ else None
        if occ is not None and not occ.read_only:
            self.setCursor(Qt.SizeVerCursor if part in ("top", "bottom") else Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        if key != self._hover:
            old = self._rect_of(self._hover)
            self._hover = key
            new = self._rect_of(key)
            for r in (old, new):
                if r is not None:
                    self.update(r.adjusted(-4, -4, 4, 4).toAlignedRect())

    def _rect_of(self, key):
        if key is None:
            return None
        union = None
        for rect, occ, *_rest in self.boxes:
            if occ.key == key:
                union = rect if union is None else union.united(rect)
        return union

    def leaveEvent(self, event):
        if not self._gesture:
            self._set_bar_hover(None)
            if self._pop_hot:
                self._pop_hot = None
                pop = self._pin_popover()
                if pop is not None:
                    self.update(pop.rect().toAlignedRect())
        if self._hover and not self._gesture:
            old = self._rect_of(self._hover)
            self._hover = None
            if old is not None:
                self.update(old.adjusted(-4, -4, 4, 4).toAlignedRect())

    def _begin_gesture(self, press: dict) -> None:
        occ = press["occ"]
        if occ is None:
            if press["in_grid"]:
                m = self._snap(press["minute"], "floor")
                self._gesture = {"kind": "create", "occ": None, "col": press["col"], "a": m,
                                 "b": m + self.view.ctx.snap, "anchor": m, "active": True}
            return
        if occ.read_only:
            return
        if self.view.ctx.drag_needs_ctrl and not press["ctrl"]:
            return
        day0 = tu.day_start(self.view.days[press["col"]], self.view.ctx.tz)
        a = (occ.start - day0).total_seconds() / 60
        b = (occ.end - day0).total_seconds() / 60
        kind = {"top": "resize_top", "bottom": "resize_bottom"}.get(press["part"], "move")
        self._gesture = {"kind": kind, "occ": occ, "col": press["col"], "a": a, "b": b, "a0": a, "b0": b,
                         "col0": press["col"], "minute0": press["minute"], "active": True}

    def _update_gesture(self, pos: QPointF) -> None:
        gst = self._gesture
        if gst["kind"].startswith("bar_"):
            self._update_bar_gesture(pos)
            return
        g = self.view.geom()
        minute = self._minute_at(pos.y())
        dirty_before = self._gesture_rect(gst)
        if gst["kind"] == "create":
            anchor = gst["anchor"]
            if minute >= anchor:
                gst["a"], gst["b"] = anchor, max(anchor + self.view.ctx.snap, self._snap(minute, "ceil"))
            else:
                gst["a"], gst["b"] = self._snap(minute, "floor"), anchor + self.view.ctx.snap
        elif gst["kind"] == "move":
            dur = gst["b0"] - gst["a0"]
            start = self._snap(gst["a0"] + (minute - gst["minute0"]))
            start = max(0, min(1440 - max(dur, self.view.ctx.snap), start))
            gst["a"], gst["b"] = start, start + dur
            gst["col"] = g.col_at(pos.x())
        elif gst["kind"] == "resize_bottom":
            gst["b"] = max(gst["a0"] + self.view.ctx.snap, min(1440, self._snap(minute)))
        elif gst["kind"] == "resize_top":
            gst["a"] = min(gst["b0"] - self.view.ctx.snap, max(0, self._snap(minute)))
        dirty = self._gesture_rect(gst)
        self.update((dirty.united(dirty_before) if dirty_before else dirty).adjusted(-6, -12, 6, 12).toAlignedRect())
        if gst.get("occ") is not None and not self._gesture.get("dimmed"):
            self._gesture["dimmed"] = True
            r = self._rect_of(gst["occ"].key)
            if r is not None:
                self.update(r.adjusted(-4, -4, 4, 4).toAlignedRect())

    def _gesture_rect(self, gst) -> QRectF | None:
        if not gst:
            return None
        g = self.view.geom()
        top, bottom = self.view.minute_y(gst["a"]), self.view.minute_y(gst["b"])
        return QRectF(g.x(gst["col"]), top - 2, g.colw, max(24.0, bottom - top) + 4)

    def _auto_scroll(self) -> None:
        if not self._gesture or not (QApplication.mouseButtons() & Qt.LeftButton):
            self._auto.stop()
            return
        vp = self.view.scroll.viewport()
        local = vp.mapFromGlobal(QCursor.pos())
        bar = self.view.scroll.verticalScrollBar()
        step = 0
        if local.y() < 24:
            step = -max(4, (24 - local.y()) // 2)
        elif local.y() > vp.height() - 24:
            step = max(4, (local.y() - vp.height() + 24) // 2)
        if step:
            bar.setValue(bar.value() + step)
            self._update_gesture(QPointF(self.mapFromGlobal(QCursor.pos())))

    def mouseReleaseEvent(self, event):
        self._auto.stop()
        press, gesture = self._press, self._gesture
        self._press = self._gesture = None
        if event.button() != Qt.LeftButton or press is None:
            return
        if gesture is None:
            occ = press["occ"]
            if press.get("bar") is not None:         # clic sur une barre : épingle / retire l'encart
                if self._pin is not None and self._pin["key"] == occ.key:
                    self._set_pin(None)
                    self._mute_key = occ.key          # pas d'encart de survol avant d'avoir quitté la barre
                else:
                    self._set_pin({"key": occ.key, "col": press["col"], "minute": self.view.y_minute(press["pos"].y())})
            self.view.selected.emit(occ)
            return
        if gesture["kind"].startswith("bar_"):
            self._finish_bar_gesture(gesture, event.position())
            return
        self.update()
        tz = self.view.ctx.tz
        day = self.view.days[gesture["col"]]
        base = datetime.combine(day, datetime.min.time())
        start = tu.localize(base + timedelta(minutes=gesture["a"]), tz)
        end = tu.localize(base + timedelta(minutes=gesture["b"]), tz)
        if gesture["kind"] == "create":
            self.view.createRequested.emit(start, end, False)
            return
        occ = gesture["occ"]
        if gesture["kind"] == "move":
            if gesture["col"] == gesture["col0"] and abs(gesture["a"] - gesture["a0"]) < 0.5:
                self.view.selected.emit(occ)
                return
            end = start + (occ.end - occ.start)
        elif gesture["kind"] == "resize_top":
            end = occ.end
            if abs(gesture["a"] - gesture["a0"]) < 0.5:
                return
        else:
            start = occ.start
            if abs(gesture["b"] - gesture["b0"]) < 0.5:
                return
        self.view.moveRequested.emit(occ, start, end)

    def mouseDoubleClickEvent(self, event):
        pos = event.position()
        occ, _rect, _part = self._box_at(pos)
        if event.button() != Qt.LeftButton:
            return
        self._press = self._gesture = None
        if occ is not None:
            self.view.activated.emit(occ)
            return
        slot = self._slot(pos)
        if slot is not None:
            minute = self._snap(slot.hour * 60 + slot.minute, "floor")
            minutes = int(self.view.ctx.s("agenda_default_duration", 60))
            start = slot.replace(hour=minute // 60, minute=minute % 60)
            self.view.createRequested.emit(start, start + timedelta(minutes=minutes), False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and (self._gesture or self._press):
            self._auto.stop()
            self._press = self._gesture = None
            self.update()
            return
        if event.key() == Qt.Key_Escape and self._pin is not None:
            self._set_pin(None)                      # Échap retire l'encart épinglé (jamais le module)
            return
        event.ignore()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            pane = self.view.parent()
            step = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
            ctx = self.view.ctx
            ctx.zoom = max(0.5, min(3.0, ctx.zoom * step))
            self.view.zoom_changed()
            if ctx.service is not None:
                ctx.service.set_pref("hour_zoom", round(ctx.zoom, 3))
            event.accept()
            return
        event.ignore()
