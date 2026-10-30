"""Tableaux et graphiques du module Design (comme les tableaux et graphiques de Canva, en local).

- TABLEAU (`design_table`) : grille `rows` × `cols`, textes des cellules (`cells`), largeurs de colonnes
  (`col_widths`, fractions ; vide = égales), ligne d'en-tête, couleurs (en-tête, fond, lignes alternées, bordure),
  police / taille / couleur / alignement du texte. Double-clic sur une cellule = la modifier SUR PLACE (éditeur de
  texte posé sur la cellule ; Tab / Maj+Tab = cellule suivante / précédente, Échap ou clic dehors = fin ; UNE étape
  d'annulation par cellule).
- GRAPHIQUE (`design_chart`) : barres, courbe, secteurs, anneau ; une série (`labels`, `values`), couleurs
  (`colors`, vide = palette du module), valeurs et grille affichables. Données modifiées par « Libellé ; valeur »
  (une ligne par point).
Peints au QPainter (pas de widgets), gardés en image comme les autres éléments ; exportés comme eux."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen, QTextCursor
from PySide6.QtWidgets import QGraphicsItem, QGraphicsTextItem

from fm_miro.items import resolve_family
from . import design_model as dm
from .design_model import column_fractions, table_grid
from .items import DesignElement

CHART_COLORS = ["#8b3dff", "#22d3ee", "#ff66c4", "#ffbd59", "#00bf63", "#5170ff", "#ff5757", "#737373"]
PAD = 0.35                                   # marge intérieure d'une cellule (fraction de la taille du texte)


# ---------------------------------------------------------------- tableau
class _CellEditor(QGraphicsTextItem):
    """Éditeur posé sur une cellule (vu par la vue comme un texte en édition : `editing`, `owner`)."""

    def __init__(self, table: "DesignTableItem", row: int, col: int):
        super().__init__(table)
        self.owner = table
        self.row, self.col = row, col
        self._closing = False
        self.document().setDocumentMargin(0)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setZValue(10)

    def editing(self) -> bool:
        return not self._closing

    def sceneEvent(self, event):
        # Tab : QGraphicsItem.sceneEvent le donnerait à la chaîne de focus de la scène (l'éditeur perdait le focus) ;
        # ici il passe à la cellule suivante.
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(event)
            return True
        return super().sceneEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            return
        if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            step = -1 if event.key() == Qt.Key_Backtab or event.modifiers() & Qt.ShiftModifier else 1
            self.owner.edit_next(step)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() != Qt.PopupFocusReason:
            self.owner.finish_cell(self)


class DesignTableItem(DesignElement):
    editor: _CellEditor | None = None

    def _style_font(self) -> QFont:
        font = QFont(resolve_family(str(self.data.get("font_family") or "")))
        font.setPixelSize(max(4, int(round(float(self.data.get("font_size", 22.0))))))
        return font

    def cell_rects(self) -> list[list[QRectF]]:
        w, h = self.size()
        rows = int(self.data.get("rows", 1))
        row_h = h / rows
        out, top = [], 0.0
        for _r in range(rows):
            line, left = [], 0.0
            for fraction in column_fractions(self.data):
                line.append(QRectF(left, top, fraction * w, row_h))
                left += fraction * w
            out.append(line)
            top += row_h
        return out

    def cell_at(self, local: QPointF) -> tuple[int, int] | None:
        for r, line in enumerate(self.cell_rects()):
            for c, rect in enumerate(line):
                if rect.contains(local):
                    return r, c
        return None

    def paint_content(self, painter):
        data = self.data
        rect = self.content_rect()
        grid = table_grid(data)
        rects = self.cell_rects()
        header = bool(data.get("header", True))
        font = self._style_font()
        pad = float(data.get("font_size", 22.0)) * PAD
        align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}.get(
            data.get("align", "left"), Qt.AlignLeft)
        painter.setPen(Qt.NoPen)
        for r, line in enumerate(rects):
            fill = data.get("header_fill") if header and r == 0 else (
                data.get("alt_fill") if r % 2 == 0 and data.get("alt_fill") else data.get("fill"))
            for c, cell in enumerate(line):
                if fill:
                    painter.fillRect(cell, QColor(fill))
        for r, line in enumerate(rects):
            head = header and r == 0
            cell_font = QFont(font)
            cell_font.setBold(head or bool(data.get("bold")))
            painter.setFont(cell_font)
            painter.setPen(QColor(data.get("header_color") if head else data.get("color", dm.INK)))
            for c, cell in enumerate(line):
                editing = self.editor is not None and (self.editor.row, self.editor.col) == (r, c)
                if grid[r][c] and not editing:
                    painter.drawText(cell.adjusted(pad, pad * 0.6, -pad, -pad * 0.6),
                                     align | Qt.AlignVCenter | Qt.TextWordWrap, grid[r][c])
        width = float(data.get("stroke_width", 1.5) or 0.0)
        if width > 0:
            pen = QPen(QColor(data.get("stroke", "#d0c6e8")), width)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for r in range(1, len(rects)):
                y = rects[r][0].top()
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            for c in range(1, len(rects[0])):
                x = rects[0][c].left()
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawRect(rect)

    # -- édition d'une cellule --
    def edit_cell(self, row: int, col: int):
        scene = self.scene()
        if scene is None or self.locked():
            return
        if self.editor is not None:
            self.finish_cell(self.editor)
        self._cell_before = scene.snapshot([self.item_id])
        editor = _CellEditor(self, row, col)
        rect = self.cell_rects()[row][col]
        pad = float(self.data.get("font_size", 22.0)) * PAD
        editor.setFont(self._style_font())
        editor.setDefaultTextColor(QColor(self.data.get("color", dm.INK)))
        editor.setPlainText(table_grid(self.data)[row][col])
        editor.setTextWidth(max(4.0, rect.width() - 2 * pad))
        editor.setPos(rect.left() + pad, rect.top() + pad * 0.6)
        self.editor = editor
        self.setCacheMode(QGraphicsItem.NoCache)
        self.update()
        editor.setFocus(Qt.MouseFocusReason)
        cursor = editor.textCursor()
        cursor.select(QTextCursor.Document)
        editor.setTextCursor(cursor)

    def edit_at(self, scene_pos: QPointF) -> bool:
        cell = self.cell_at(self.mapFromScene(scene_pos))
        if cell is None:
            return False
        if self.editor is not None and (self.editor.row, self.editor.col) == cell:
            return False                          # dans la cellule éditée : curseur du texte
        self.edit_cell(*cell)
        return True

    def edit_next(self, step: int):
        editor = self.editor
        if editor is None:
            return
        rows, cols = int(self.data["rows"]), int(self.data["cols"])
        index = (editor.row * cols + editor.col + step) % (rows * cols)
        self.edit_cell(index // cols, index % cols)

    def finish_cell(self, editor: _CellEditor):
        if editor._closing or editor is not self.editor:
            return
        editor._closing = True
        self.editor = None
        scene = self.scene()
        text = editor.toPlainText()
        editor.setParentItem(None)
        if scene is not None and editor.scene() is scene:
            scene.removeItem(editor)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        grid = table_grid(self.data)
        if grid[editor.row][editor.col] != text:
            self.data = self.to_dict()
            grid[editor.row][editor.col] = text
            self.data["cells"] = grid
            self.apply(self.data)
            before = getattr(self, "_cell_before", None)
            if scene is not None and before is not None:
                scene.push(before, scene.snapshot([self.item_id]), "Modifier une cellule")
        self.update()


# ---------------------------------------------------------------- graphique
class DesignChartItem(DesignElement):
    def _colors(self) -> list[str]:
        return [c for c in self.data.get("colors") or [] if isinstance(c, str)] or CHART_COLORS

    def paint_content(self, painter):
        data = self.data
        rect = self.content_rect()
        series, names = dm.chart_series(data)
        values = [float(v) for v in series[0]]
        labels = list(data.get("labels") or [])
        size = float(data.get("font_size", 18.0))
        font = QFont(resolve_family(str(data.get("font_family") or "")))
        font.setPixelSize(max(4, int(round(size))))
        painter.setFont(font)
        ink = QColor(data.get("color", dm.INK))
        if not values:
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1, Qt.DashLine))
            painter.drawRect(rect)
            return
        kind = data.get("chart", "bar")
        if kind in ("pie", "donut"):
            self._paint_pie(painter, rect, values, labels, size, ink, kind == "donut")
        else:
            self._paint_axes_chart(painter, rect, series, names, labels, size, ink, kind)

    def _paint_legend(self, painter, rect, names, colors, size, ink) -> float:
        """Légende des séries sur une ligne en haut (centrée) ; hauteur prise."""
        metrics = painter.fontMetrics()
        widths = [size * 1.4 + metrics.horizontalAdvance(n) + size for n in names]
        x = rect.left() + max(0.0, (rect.width() - sum(widths) + size) / 2)
        for n, name in enumerate(names):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors[n % len(colors)]))
            painter.drawRoundedRect(QRectF(x, rect.top() + size * 0.2, size, size), size * 0.2, size * 0.2)
            painter.setPen(ink)
            painter.drawText(QRectF(x + size * 1.4, rect.top(), widths[n], size * 1.4),
                             Qt.AlignVCenter | Qt.AlignLeft, name)
            x += widths[n]
        return size * 1.8

    def _paint_axes_chart(self, painter, rect, series, names, labels, size, ink, kind):
        colors = self._colors()
        values = series[0]
        many = len(series) > 1
        if names:
            legend = self._paint_legend(painter, rect, [n or f"Série {k + 1}" for k, n in enumerate(names)], colors,
                                        size, ink)
            rect = rect.adjusted(0, legend, 0, 0)
        every = [v for serie in series for v in serie]
        top = max(every + [0.0])
        bottom = min(every + [0.0])
        span = (top - bottom) or 1.0
        show_values = self.data.get("show_values", True)
        plot = rect.adjusted(size * 0.5, size * 1.6 if show_values else size * 0.5, -size * 0.5,
                             -size * (3.2 if show_values and bottom < 0 else 1.8))   # valeur sous une barre négative
        if plot.width() <= 4 or plot.height() <= 4:
            return

        def y_of(v):
            return plot.bottom() - (v - bottom) / span * plot.height()
        if self.data.get("show_grid", True):
            painter.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 40), max(1.0, size * 0.05)))
            for n in range(1, 5):
                y = plot.top() + plot.height() * n / 4
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        zero = y_of(0.0)
        count = len(values)
        slot = plot.width() / count
        group = slot * 0.64                  # barres d'un même libellé côte à côte dans 64 % de la case
        bar_w = group / len(series) if kind == "bar" else slot
        for n in range(count):
            cx = plot.left() + slot * (n + 0.5)
            for k, serie in enumerate(series):
                value = serie[n] if n < len(serie) else 0.0
                y = y_of(value)
                x = cx - group / 2 + bar_w * (k + 0.5) if kind == "bar" else cx
                if kind == "bar":
                    bar = QRectF(x - bar_w / 2 + (bar_w * 0.06 if many else 0), min(y, zero),
                                 bar_w * (0.88 if many else 1.0), abs(zero - y))
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(colors[(k if many else n) % len(colors)]))
                    path = QPainterPath()
                    r = min(bar.width() * 0.12, bar.height() / 2)
                    path.addRoundedRect(bar, r, r)
                    painter.drawPath(path)
                if show_values and (kind == "bar" or not many):
                    painter.setPen(ink)
                    width = bar_w if kind == "bar" else slot
                    painter.drawText(QRectF(x - width / 2, y - size * 1.5 if value >= 0 else y + size * 0.1, width,
                                            size * 1.4), Qt.AlignCenter, f"{value:g}")
            if n < len(labels):
                painter.setPen(ink)
                painter.drawText(QRectF(cx - slot / 2, rect.bottom() - size * 1.5, slot, size * 1.4),
                                 Qt.AlignCenter, labels[n])
        if kind == "line":
            for k, serie in enumerate(series):
                points = [QPointF(plot.left() + slot * (n + 0.5), y_of(serie[n] if n < len(serie) else 0.0))
                          for n in range(count)]
                pen = QPen(QColor(colors[k % len(colors)]), max(1.5, size * 0.18))
                pen.setJoinStyle(Qt.RoundJoin)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                for a, b in zip(points, points[1:]):
                    painter.drawLine(a, b)
                painter.setBrush(QColor("#ffffff"))
                for p in points:
                    painter.drawEllipse(p, size * 0.25, size * 0.25)
        painter.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 140), max(1.0, size * 0.06)))
        painter.drawLine(QPointF(plot.left(), zero), QPointF(plot.right(), zero))

    def _paint_pie(self, painter, rect, values, labels, size, ink, donut):
        colors = self._colors()
        total = sum(abs(v) for v in values) or 1.0
        legend = bool(labels) and any(labels) and rect.width() > rect.height() * 1.3
        side = min(rect.height(), rect.width() * (0.6 if legend else 1.0)) - size
        if side <= 4:
            return
        pie = QRectF(rect.left() + size / 2, rect.top() + (rect.height() - side) / 2, side, side)
        start = 90.0
        painter.setPen(QPen(QColor("#ffffff"), max(1.0, size * 0.08)))
        for n, value in enumerate(values):
            sweep = -360.0 * abs(value) / total
            painter.setBrush(QColor(colors[n % len(colors)]))
            painter.drawPie(pie, int(start * 16), int(sweep * 16))
            if self.data.get("show_values", True) and abs(sweep) > 12:
                middle = math.radians(start + sweep / 2)
                radius = side * (0.38 if donut else 0.32)
                c = pie.center() + QPointF(math.cos(middle) * radius, -math.sin(middle) * radius)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(c.x() - size * 2, c.y() - size, size * 4, size * 2), Qt.AlignCenter,
                                 f"{round(abs(value) / total * 100)} %")
                painter.setPen(QPen(QColor("#ffffff"), max(1.0, size * 0.08)))
            start += sweep
        if donut:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.data.get("hole", "#ffffff")))
            hole = side * 0.55
            painter.drawEllipse(pie.center(), hole / 2, hole / 2)
        if legend:
            x = pie.right() + size
            y = rect.top() + (rect.height() - len(values) * size * 1.5) / 2
            for n, label in enumerate(labels):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(colors[n % len(colors)]))
                painter.drawRoundedRect(QRectF(x, y + size * 0.2, size, size), size * 0.2, size * 0.2)
                painter.setPen(ink)
                painter.drawText(QRectF(x + size * 1.4, y, rect.right() - x - size * 1.4, size * 1.4),
                                 Qt.AlignVCenter | Qt.AlignLeft, label)
                y += size * 1.5


from fm_miro.items import ITEM_CLASSES  # noqa: E402

ITEM_CLASSES[dm.TABLE] = DesignTableItem
ITEM_CLASSES[dm.CHART] = DesignChartItem
