"""Graphiques LIÉS aux données (pas des images) : rangés dans la feuille (`Sheet.charts`), relus à chaque peinture.

Graphique = dictionnaire : `id`, `type` (CHART_TYPES), `data` (plage A1, ex. « A1:C12 »), `header` (1re ligne =
noms des séries, 1re colonne = catégories), `series_in` (« cols » / « rows »), `title`, `legend`, `anchor` (ligne,
colonne du coin), `size` (largeur, hauteur en px à 100 %). La plage suit les insertions / suppressions de lignes
(`commands.Lines`) et les renommages de feuilles.

Peinture QPainter (aucune dépendance) ; dans la grille, un calque d'objets (`ChartLayer`) : clic = choisir,
Ctrl + glisser = déplacer (règle de l'appli), poignée en bas à droite = taille, double-clic / clic droit =
modifier, Suppr = supprimer — chaque geste est UNE étape d'annulation du classeur. Export : vrais graphiques Excel
(openpyxl.chart) branchés sur les mêmes plages."""
from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QInputDialog, QWidget

from . import commands as C
from . import refs as R
from .engine import cell_value

CHART_TYPES = [("column", "Histogramme"), ("bar", "Barres"), ("line", "Courbes"), ("area", "Aires"),
               ("pie", "Secteurs"), ("scatter", "Nuage de points"), ("combo", "Combiné (histogramme + courbe)")]
COLORS = ["#4472c4", "#ed7d31", "#a5a5a5", "#ffc000", "#5b9bd5", "#70ad47", "#264478", "#9e480e"]


def new_chart(kind, rect, anchor) -> dict:
    return {"id": uuid.uuid4().hex[:10], "type": kind, "data": R.range_name(*rect), "header": True,
            "series_in": "cols" if (rect[2] - rect[0]) >= (rect[3] - rect[1]) else "rows",
            "title": "", "legend": True, "anchor": list(anchor), "size": [480, 288]}


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    return None


def chart_data(book, sheet, chart):
    """(catégories, [(nom, [valeurs])]) lues dans la plage (valeurs calculées)."""
    parsed = R.parse_range(chart.get("data") or "")
    if parsed is None:
        return [], []
    sheet_name, (r0, c0, r1, c1) = parsed
    if sheet_name:
        sheet = book.sheet(sheet_name) or sheet
    used = sheet.used_range()
    if used:
        r1, c1 = min(r1, used[2]), min(c1, used[3])
    r1, c1 = min(r1, r0 + 5000), min(c1, c0 + 200)
    header = chart.get("header", True)
    grid = [[cell_value(book, sheet, r, c) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
    if not grid or not grid[0]:
        return [], []
    if chart.get("series_in") == "rows":
        grid = [list(col) for col in zip(*grid)]
    first_row_text = header and any(isinstance(v, str) for v in grid[0])
    first_col_text = header and any(isinstance(row[0], str) for row in grid[1 if first_row_text else 0:])
    names = grid[0][1 if first_col_text else 0:] if first_row_text else None
    body = grid[1:] if first_row_text else grid
    categories = [str(row[0]) if row[0] is not None else "" for row in body] if first_col_text else \
        [str(i + 1) for i in range(len(body))]
    series = []
    start = 1 if first_col_text else 0
    width = len(body[0]) if body else 0
    for j in range(start, width):
        name = str(names[j - start]) if names and names[j - start] is not None else f"Série {j - start + 1}"
        series.append((name, [_number(row[j]) for row in body]))
    if chart.get("type") == "scatter" and len(series) >= 2 and not first_col_text:
        xs = series[0][1]
        categories = xs
        series = series[1:]
    return categories, series


def _nice(lo, hi):
    if lo == hi:
        hi = lo + 1
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / 5))
    for mult in (1, 2, 2.5, 5, 10):
        if span / (step * mult) <= 6:
            step *= mult
            break
    return math.floor(lo / step) * step, math.ceil(hi / step) * step, step


def _fmt(v):
    if abs(v) >= 1e6:
        return f"{v / 1e6:g} M"
    if abs(v) >= 1e4:
        return f"{v / 1e3:g} k"
    return f"{v:g}".replace(".", ",")


def paint_chart(painter: QPainter, rect: QRectF, book, sheet, chart, zoom: float = 1.0):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.fillRect(rect, QColor("#ffffff"))
    painter.setPen(QPen(QColor("#d0d0d0"), 1))
    painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
    categories, series = chart_data(book, sheet, chart)
    font = QFont("Segoe UI")
    font.setPixelSize(max(6, round(11 * zoom)))
    painter.setFont(font)
    pad = 10 * zoom
    inner = rect.adjusted(pad, pad, -pad, -pad)
    title = chart.get("title") or (series[0][0] if len(series) == 1 else "")
    if title:
        tf = QFont(font)
        tf.setPixelSize(max(7, round(15 * zoom)))
        painter.setFont(tf)
        painter.setPen(QColor("#404040"))
        painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), 22 * zoom), Qt.AlignCenter, title)
        painter.setFont(font)
        inner.setTop(inner.top() + 26 * zoom)
    kind = chart.get("type", "column")
    if chart.get("legend", True) and series and kind != "pie":
        legend_h = 18 * zoom
        x = inner.left()
        y = inner.bottom() - legend_h
        for i, (name, _vals) in enumerate(series):
            painter.fillRect(QRectF(x, y + 5 * zoom, 9 * zoom, 9 * zoom), QColor(COLORS[i % len(COLORS)]))
            painter.setPen(QColor("#595959"))
            w = painter.fontMetrics().horizontalAdvance(name) + 22 * zoom
            painter.drawText(QRectF(x + 12 * zoom, y, w, legend_h), Qt.AlignVCenter | Qt.AlignLeft, name)
            x += w
        inner.setBottom(inner.bottom() - legend_h - 4 * zoom)
    if not series:
        painter.setPen(QColor("#909090"))
        painter.drawText(inner, Qt.AlignCenter, "Aucune donnée numérique dans la plage")
        painter.restore()
        return
    if kind == "pie":
        _paint_pie(painter, inner, categories, series[0][1], zoom)
    else:
        _paint_axes_chart(painter, inner, kind, categories, series, zoom)
    painter.restore()


def _paint_pie(painter, rect, categories, values, zoom):
    vals = [max(0.0, v or 0.0) for v in values]
    total = sum(vals)
    if not total:
        return
    size = min(rect.width() * 0.6, rect.height())
    pie = QRectF(rect.left(), rect.center().y() - size / 2, size, size)
    angle = 90 * 16
    for i, v in enumerate(vals):
        span = -int(round(v / total * 360 * 16))
        painter.setBrush(QColor(COLORS[i % len(COLORS)]))
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.drawPie(pie, angle, span)
        angle += span
    y = rect.top()
    for i, (cat, v) in enumerate(zip(categories, vals)):
        if y > rect.bottom() - 14 * zoom:
            break
        painter.fillRect(QRectF(pie.right() + 14 * zoom, y + 4 * zoom, 9 * zoom, 9 * zoom),
                         QColor(COLORS[i % len(COLORS)]))
        painter.setPen(QColor("#595959"))
        painter.drawText(QRectF(pie.right() + 27 * zoom, y, rect.right() - pie.right(), 17 * zoom),
                         Qt.AlignVCenter, f"{cat} ({v / total * 100:.0f} %)")
        y += 18 * zoom


def _paint_axes_chart(painter, rect, kind, categories, series, zoom):
    values = [v for _n, vals in series for v in vals if v is not None]
    if not values:
        return
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    lo, hi, step = _nice(lo, hi)
    horizontal = kind == "bar"
    label_w = 44 * zoom
    plot = rect.adjusted(label_w if not horizontal else 70 * zoom, 4 * zoom, -6 * zoom, -18 * zoom)
    painter.setPen(QPen(QColor("#e6e6e6"), 1))
    ticks = int(round((hi - lo) / step))
    for i in range(ticks + 1):
        v = lo + i * step
        if horizontal:
            x = plot.left() + (v - lo) / (hi - lo) * plot.width()
            painter.setPen(QPen(QColor("#e6e6e6"), 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(QColor("#7f7f7f"))
            painter.drawText(QRectF(x - 30 * zoom, plot.bottom() + 2, 60 * zoom, 14 * zoom), Qt.AlignCenter, _fmt(v))
        else:
            y = plot.bottom() - (v - lo) / (hi - lo) * plot.height()
            painter.setPen(QPen(QColor("#e6e6e6"), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor("#7f7f7f"))
            painter.drawText(QRectF(rect.left(), y - 7 * zoom, label_w - 4 * zoom, 14 * zoom),
                             Qt.AlignRight | Qt.AlignVCenter, _fmt(v))
    n = max(1, len(categories))
    if kind == "scatter":
        xs = [_number(c) if not isinstance(c, str) else None for c in categories]
        xs = [x if x is not None else float(i) for i, x in enumerate(xs)]
        xlo, xhi, _s = _nice(min(xs), max(xs))
        for si, (_name, vals) in enumerate(series):
            painter.setBrush(QColor(COLORS[si % len(COLORS)]))
            painter.setPen(Qt.NoPen)
            for x, v in zip(xs, vals):
                if v is None:
                    continue
                px = plot.left() + (x - xlo) / (xhi - xlo) * plot.width()
                py = plot.bottom() - (v - lo) / (hi - lo) * plot.height()
                painter.drawEllipse(QPointF(px, py), 3.5 * zoom, 3.5 * zoom)
        return
    band = (plot.height() if horizontal else plot.width()) / n
    bar_series = [s for i, s in enumerate(series) if kind in ("column", "bar") or (kind == "combo" and i == 0)]
    line_series = [(i, s) for i, s in enumerate(series) if kind in ("line", "area") or (kind == "combo" and i > 0)]
    zero = (0 - lo) / (hi - lo)
    if bar_series:
        width = band * 0.7 / len(bar_series)
        for si, (_name, vals) in enumerate(bar_series):
            painter.setBrush(QColor(COLORS[si % len(COLORS)]))
            painter.setPen(Qt.NoPen)
            for ci, v in enumerate(vals):
                if v is None:
                    continue
                frac = (v - lo) / (hi - lo)
                if horizontal:
                    y = plot.top() + ci * band + band * 0.15 + si * width
                    x0 = plot.left() + zero * plot.width()
                    x1 = plot.left() + frac * plot.width()
                    painter.drawRect(QRectF(min(x0, x1), y, abs(x1 - x0), width))
                else:
                    x = plot.left() + ci * band + band * 0.15 + si * width
                    y0 = plot.bottom() - zero * plot.height()
                    y1 = plot.bottom() - frac * plot.height()
                    painter.drawRect(QRectF(x, min(y0, y1), width, abs(y1 - y0)))
    for si, (_name, vals) in line_series:
        color = QColor(COLORS[si % len(COLORS)])
        path = QPainterPath()
        points = []
        for ci, v in enumerate(vals):
            if v is None:
                continue
            x = plot.left() + (ci + 0.5) * band
            y = plot.bottom() - (v - lo) / (hi - lo) * plot.height()
            points.append(QPointF(x, y))
        if not points:
            continue
        path.moveTo(points[0])
        for p in points[1:]:
            path.lineTo(p)
        if kind == "area":
            area = QPainterPath(path)
            base = plot.bottom() - zero * plot.height()
            area.lineTo(points[-1].x(), base)
            area.lineTo(points[0].x(), base)
            area.closeSubpath()
            fill = QColor(color)
            fill.setAlpha(110)
            painter.fillPath(area, fill)
        painter.setPen(QPen(color, 2 * zoom))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
    painter.setPen(QColor("#7f7f7f"))
    every = max(1, int(n / max(1, (plot.width() if not horizontal else plot.height()) / (60 * zoom))))
    for ci, cat in enumerate(categories):
        if ci % every:
            continue
        if horizontal:
            y = plot.top() + ci * band
            painter.drawText(QRectF(rect.left(), y, 66 * zoom, band), Qt.AlignRight | Qt.AlignVCenter, str(cat))
        else:
            x = plot.left() + ci * band
            painter.drawText(QRectF(x, plot.bottom() + 2, band * every, 14 * zoom), Qt.AlignCenter, str(cat)[:14])


def chart_rect(sheet, chart, x_of, y_of, zoom) -> QRectF:
    r, c = chart.get("anchor", [0, 0])
    w, h = chart.get("size", [480, 288])
    return QRectF(x_of(int(c)), y_of(int(r)), float(w) * zoom, float(h) * zoom)


# ---------------------------------------------------------------- calque dans la grille
class ChartView(QWidget):
    changed = Signal()

    def __init__(self, layer, chart_id):
        super().__init__(layer.grid.viewport())
        self.layer = layer
        self.chart_id = chart_id
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self._drag = None
        self.selected = False

    def chart(self):
        for chart in self.layer.grid.sheet.charts:
            if chart.get("id") == self.chart_id:
                return chart
        return None

    def paintEvent(self, _event):
        chart = self.chart()
        if chart is None:
            return
        painter = QPainter(self)
        grid = self.layer.grid
        paint_chart(painter, QRectF(self.rect()), grid.book, grid.sheet, chart, grid.zoom)
        if self.selected:
            painter.setPen(QPen(QColor("#107c41"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))
            painter.fillRect(QRectF(self.width() - 9, self.height() - 9, 8, 8), QColor("#107c41"))
        painter.end()

    def mousePressEvent(self, event):
        self.layer.select(self)
        if event.button() == Qt.RightButton:
            self.layer.edit_menu(self, event.globalPosition().toPoint())
            return
        pos = event.position()
        if pos.x() > self.width() - 12 and pos.y() > self.height() - 12:
            self._drag = ("size", event.globalPosition(), (self.width(), self.height()))
        elif QApplication.keyboardModifiers() & Qt.ControlModifier:      # Ctrl + glisser = déplacer (appli)
            self._drag = ("move", event.globalPosition(), self.pos())
        event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag is None:
            corner = pos.x() > self.width() - 12 and pos.y() > self.height() - 12
            self.setCursor(Qt.SizeFDiagCursor if corner else (
                Qt.SizeAllCursor if QApplication.keyboardModifiers() & Qt.ControlModifier else Qt.ArrowCursor))
            return
        kind, start, base = self._drag
        delta = event.globalPosition() - start
        if kind == "size":
            self.resize(max(120, int(base[0] + delta.x())), max(80, int(base[1] + delta.y())))
        else:
            self.move(int(base.x() + delta.x()), int(base.y() + delta.y()))

    def mouseReleaseEvent(self, event):
        drag = self._drag
        self._drag = None
        if drag is None:
            return
        grid = self.layer.grid
        z = grid.zoom
        if drag[0] == "size":
            size = [round(self.width() / z), round(self.height() / z)]
            self.layer.change(self.chart_id, {"size": size}, "Taille du graphique")
        else:
            r = grid.row_at(self.y() + 1)
            c = grid.col_at(self.x() + 1)
            self.layer.change(self.chart_id, {"anchor": [r, c]}, "Déplacer le graphique")

    def mouseDoubleClickEvent(self, _event):
        self.layer.edit_menu(self, self.mapToGlobal(self.rect().center()))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.layer.remove(self.chart_id)
            return
        if event.key() == Qt.Key_Escape:
            self.layer.select(None)
            self.layer.grid.setFocus()
            return
        super().keyPressEvent(event)


class ChartLayer:
    def __init__(self, grid):
        self.grid = grid
        self.views: dict[str, ChartView] = {}
        grid.book.listeners.append(self._on_event)
        self._orig_scrolled = None
        grid.horizontalScrollBar().valueChanged.connect(self.place)
        grid.verticalScrollBar().valueChanged.connect(self.place)
        self.sync()

    def detach(self):
        if self._on_event in self.grid.book.listeners:
            self.grid.book.listeners.remove(self._on_event)

    def _on_event(self, kind, sheet):
        self.sync()

    def sync(self):
        sheet = self.grid.sheet
        wanted = {c.get("id") for c in sheet.charts}
        for cid in list(self.views):
            if cid not in wanted:
                self.views.pop(cid).deleteLater()
        for chart in sheet.charts:
            if chart.get("id") not in self.views:
                view = ChartView(self, chart["id"])
                view.show()
                self.views[chart["id"]] = view
        self.place()
        for view in self.views.values():
            view.update()

    def place(self, *_args):
        grid = self.grid
        g = grid.geo()
        for cid, view in self.views.items():
            chart = view.chart()
            if chart is None:
                continue
            rect = chart_rect(grid.sheet, chart, grid.x_of, grid.y_of, grid.zoom)
            view.setGeometry(rect.toAlignedRect())
            view.setVisible(rect.right() > g["hw"] and rect.bottom() > g["hh"])

    def select(self, view):
        for v in self.views.values():
            v.selected = v is view
            v.update()
        if view is not None:
            view.setFocus()

    def change(self, chart_id, changes, text):
        def mutate(s):
            for chart in s.charts:
                if chart.get("id") == chart_id:
                    chart.update(changes)
        self.grid.session.stack.push(C.SheetState(self.grid.sheet, mutate, text, kind="cells"))

    def remove(self, chart_id):
        def mutate(s):
            s.charts = [c for c in s.charts if c.get("id") != chart_id]
        self.grid.session.stack.push(C.SheetState(self.grid.sheet, mutate, "Supprimer le graphique",
                                                  kind="cells"))

    def insert(self, kind, rect):
        grid = self.grid
        r0, c0, r1, c1 = rect
        chart = new_chart(kind, rect, (r0, c1 + 2))
        self.grid.session.stack.push(C.SheetState(grid.sheet, lambda s: s.charts.append(dict(chart)),
                                                  "Insérer un graphique", kind="cells"))
        view = self.views.get(chart["id"])
        if view is not None:
            self.select(view)

    def edit_menu(self, view, pos):
        from .ribbon import menu
        m = menu(self.grid, "graphique")
        types = m.addMenu("Type")
        for kind, label in CHART_TYPES:
            types.addAction(label).triggered.connect(
                lambda _c=False, k=kind: self.change(view.chart_id, {"type": k}, "Type de graphique"))
        m.addAction("Titre…").triggered.connect(lambda: self._ask(view, "title", "Titre du graphique"))
        m.addAction("Plage de données…").triggered.connect(lambda: self._ask(view, "data", "Plage (ex. A1:C12)"))
        chart = view.chart() or {}
        m.addAction("Séries en lignes" if chart.get("series_in") == "cols" else "Séries en colonnes").triggered\
            .connect(lambda: self.change(view.chart_id, {"series_in": "rows" if chart.get("series_in") == "cols"
                                                         else "cols"}, "Séries"))
        m.addAction("Masquer la légende" if chart.get("legend", True) else "Afficher la légende").triggered.connect(
            lambda: self.change(view.chart_id, {"legend": not chart.get("legend", True)}, "Légende"))
        m.addSeparator()
        m.addAction("Supprimer").triggered.connect(lambda: self.remove(view.chart_id))
        m.popup(pos)

    def _ask(self, view, key, label):
        chart = view.chart() or {}
        text, ok = QInputDialog.getText(self.grid, "Graphique", label + " :", text=str(chart.get(key) or ""))
        if not ok:
            return
        if key == "data" and R.parse_range(text.strip()) is None:
            self.grid.message.emit(f"Plage non valable : {text}")
            return
        self.change(view.chart_id, {key: text.strip()}, "Graphique")


# ---------------------------------------------------------------- export Excel
def export_charts(ws, sheet, warnings):
    from openpyxl.chart import AreaChart, BarChart, LineChart, PieChart, Reference, ScatterChart, Series
    for chart in sheet.charts:
        parsed = R.parse_range(chart.get("data") or "")
        if parsed is None:
            warnings.append("graphique sans plage valable non exporté")
            continue
        _name, (r0, c0, r1, c1) = parsed
        kind = chart.get("type", "column")
        try:
            if kind in ("column", "bar", "combo"):
                xc = BarChart()
                xc.type = "bar" if kind == "bar" else "col"
            elif kind == "line":
                xc = LineChart()
            elif kind == "area":
                xc = AreaChart()
            elif kind == "pie":
                xc = PieChart()
            else:
                xc = ScatterChart()
            by_cols = chart.get("series_in", "cols") == "cols"
            header = bool(chart.get("header", True))
            if kind == "scatter":
                xs = Reference(ws, min_col=c0 + 1, min_row=r0 + 1 + header, max_row=r1 + 1)
                for col in range(c0 + 2, c1 + 2):
                    ys = Reference(ws, min_col=col, min_row=r0 + 1, max_row=r1 + 1)
                    series = Series(ys, xs, title_from_data=header)
                    xc.series.append(series)
            else:
                data = Reference(ws, min_col=c0 + 2 if by_cols else c0 + 1, min_row=r0 + 1,
                                 max_col=c1 + 1, max_row=r1 + 1) if by_cols else \
                    Reference(ws, min_col=c0 + 1, min_row=r0 + 2, max_col=c1 + 1, max_row=r1 + 1)
                cats = Reference(ws, min_col=c0 + 1, min_row=r0 + 1 + header, max_row=r1 + 1) if by_cols else \
                    Reference(ws, min_col=c0 + 1 + header, min_row=r0 + 1, max_col=c1 + 1)
                xc.add_data(data, titles_from_data=header, from_rows=not by_cols)
                xc.set_categories(cats)
                if kind == "combo" and len(xc.series) > 1:
                    line = LineChart()
                    for extra in xc.series[1:]:
                        line.series.append(extra)
                    xc.series = xc.series[:1]
                    xc += line
            if chart.get("title"):
                xc.title = chart["title"]
            if not chart.get("legend", True):
                xc.legend = None
            w, h = chart.get("size", [480, 288])
            xc.width, xc.height = w / 37.8, h / 37.8           # centimètres
            ar, ac = chart.get("anchor", [0, 0])
            ws.add_chart(xc, R.cell_name(int(ar), int(ac)))
        except Exception as exc:                           # noqa: BLE001
            warnings.append(f"graphique non exporté ({kind}) : {exc}")
