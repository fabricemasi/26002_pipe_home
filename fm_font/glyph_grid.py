"""Grille des glyphes (Qt, peinte, virtualisée : seules les cases visibles se dessinent, des milliers de glyphes
restent fluides). Recherche (nom, caractère, U+XXXX), filtres (catégorie Unicode, sans Unicode, vides,
composés), glyphes MANQUANTS d'un jeu de caractères (cases en pointillé : double-clic = créer)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import QAbstractScrollArea

from . import glyph_info

FILTERS = ("Tous", "Lettre", "Marque", "Chiffre", "Ponctuation", "Symbole", "Séparateur", "Sans Unicode", "Vides",
           "Composés")


def matches(glyph, query: str) -> bool:
    if not query:
        return True
    q = query.strip()
    if q.lower().startswith("u+"):
        try:
            return int(q[2:], 16) in glyph.unicodes
        except ValueError:
            return False
    if len(q) == 1 and ord(q) in glyph.unicodes:
        return True
    return q.lower() in glyph.name.lower()


def keep(glyph, category: str) -> bool:
    if category in ("", "Tous"):
        return True
    if category == "Sans Unicode":
        return not glyph.unicodes
    if category == "Vides":
        return not glyph.contours and not glyph.components
    if category == "Composés":
        return bool(glyph.components)
    return bool(glyph.unicodes) and glyph_info.category(glyph.unicodes[0]) == category


class GlyphGrid(QAbstractScrollArea):
    glyphActivated = Signal(str)
    missingActivated = Signal(int)
    selectionChanged = Signal()
    contextRequested = Signal(QPointF)

    def __init__(self, project, cache, settings: dict, parent=None):
        super().__init__(parent)
        self.project = project
        self.cache = cache
        self.master = 0
        self.cell = int(settings.get("typo_cell_size", 72))
        self.colors = settings
        self.query = ""
        self.category = "Tous"
        self.charset: str | None = None
        self.entries: list[tuple[str, object]] = []
        self.selected: set[str] = set()
        self.current: str | None = None
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.refresh()

    # -- contenu --

    def refresh(self) -> None:
        font = self.project.masters[self.master].font
        names = self.project.glyph_order()
        entries = [("glyph", n) for n in names if n in font and keep(font[n], self.category)
                   and matches(font[n], self.query)]
        if self.charset:
            cmap = self.project.cmap()
            for code in glyph_info.CHARSETS.get(self.charset, []):
                if code not in cmap and (not self.query or self.query in (chr(code), f"U+{code:04X}")
                                         or self.query.lower() in glyph_info.name_for_unicode(code).lower()):
                    entries.append(("missing", code))
        self.entries = entries
        self.selected &= {n for kind, n in entries if kind == "glyph"}
        self._layout()
        self.viewport().update()

    def set_filter(self, query: str | None = None, category: str | None = None, charset: str | None = "keep"):
        if query is not None:
            self.query = query
        if category is not None:
            self.category = category
        if charset != "keep":
            self.charset = charset or None
        self.refresh()

    def set_cell_size(self, size: int) -> None:
        self.cell = max(32, min(int(size), 256))
        self._layout()
        self.viewport().update()

    def _columns(self) -> int:
        return max(1, self.viewport().width() // self.cell)

    def _layout(self) -> None:
        rows = (len(self.entries) + self._columns() - 1) // self._columns()
        bar = self.verticalScrollBar()
        bar.setRange(0, max(0, rows * (self.cell + 16) - self.viewport().height()))
        bar.setPageStep(self.viewport().height())
        bar.setSingleStep(self.cell // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()

    def index_at(self, pos) -> int | None:
        cols = self._columns()
        col = int(pos.x()) // self.cell
        row = (int(pos.y()) + self.verticalScrollBar().value()) // (self.cell + 16)
        if col >= cols:
            return None
        index = row * cols + col
        return index if 0 <= index < len(self.entries) else None

    def cell_rect(self, index: int) -> QRect:
        cols = self._columns()
        row, col = divmod(index, cols)
        return QRect(col * self.cell, row * (self.cell + 16) - self.verticalScrollBar().value(),
                     self.cell, self.cell + 16)

    def selected_names(self) -> list[str]:
        order = [n for kind, n in self.entries if kind == "glyph"]
        return [n for n in order if n in self.selected]

    def select(self, names, current: str | None = None) -> None:
        self.selected = set(names)
        self.current = current if current is not None else (next(iter(names)) if names else None)
        self.selectionChanged.emit()
        self.viewport().update()

    # -- dessin --

    def paintEvent(self, _event):
        p = QPainter(self.viewport())
        bg = QColor(self.colors.get("typo_canvas_bg", "#f4f4f2"))
        p.fillRect(self.viewport().rect(), bg)
        if not self.entries:
            p.setPen(QColor(self.colors.get("typo_handle", "#8a8f98")))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, "Aucun glyphe (filtre, ou projet vide).")
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        font = self.project.masters[self.master].font
        info = font.info
        upm = info.unitsPerEm or 1000
        top = max(info.ascender or 800, (info.capHeight or 700) + 100)
        bottom = min(info.descender or -200, 0)
        cols = self._columns()
        first_row = self.verticalScrollBar().value() // (self.cell + 16)
        last_row = (self.verticalScrollBar().value() + self.viewport().height()) // (self.cell + 16) + 1
        fill = QColor(self.colors.get("typo_fill", "#1b1b1b"))
        grid = QColor(self.colors.get("typo_grid", "#e2e2de"))
        sel = QColor(self.colors.get("typo_selection", "#e2572b"))
        muted = QColor(self.colors.get("typo_handle", "#8a8f98"))
        label_font = QFont(p.font().family(), 7)
        p.setFont(label_font)
        scale = (self.cell - 12) / max(top - bottom, upm)
        for index in range(first_row * cols, min(len(self.entries), (last_row + 1) * cols)):
            kind, value = self.entries[index]
            rect = self.cell_rect(index)
            box = rect.adjusted(1, 1, -1, -1)
            if kind == "missing":
                p.setPen(QPen(muted, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(box)
                p.drawText(QRect(box.x(), box.y(), box.width(), self.cell), Qt.AlignCenter, chr(value))
                p.drawText(QRect(box.x(), box.bottom() - 14, box.width(), 14), Qt.AlignCenter,
                           f"+ {glyph_info.name_for_unicode(value)}")
                continue
            glyph = font[value]
            selected = value in self.selected
            p.setPen(QPen(sel if selected else grid, 2 if selected else 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(box)
            if glyph.contours or glyph.components:
                width = glyph.width or upm * 0.5
                s = min(scale, (self.cell - 8) / max(width, 1))
                ox = rect.x() + (self.cell - width * s) / 2
                oy = rect.y() + 6 + top * s
                p.save()
                p.setTransform(QTransform(s, 0, 0, -s, ox, oy), True)
                p.setPen(Qt.NoPen)
                p.setBrush(fill)
                p.drawPath(self.cache.path(self.master, value))
                p.restore()
            elif glyph.unicodes:
                p.setPen(muted)
                p.drawText(QRect(box.x(), box.y(), box.width(), self.cell), Qt.AlignCenter, chr(glyph.unicodes[0]))
            p.setPen(sel if selected else muted)
            label = value if len(value) <= 12 else value[:11] + "…"
            p.drawText(QRect(box.x(), box.bottom() - 14, box.width(), 14), Qt.AlignCenter, label)
        p.end()

    # -- souris / clavier --

    def mousePressEvent(self, event):
        index = self.index_at(event.position())
        if index is None:
            if not event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
                self.select(set())
            return
        kind, value = self.entries[index]
        if kind != "glyph":
            return
        if event.button() == Qt.RightButton and value in self.selected:
            pass
        elif event.modifiers() & Qt.ControlModifier:
            self.select(self.selected ^ {value}, value)
        elif event.modifiers() & Qt.ShiftModifier and self.current is not None:
            names = [n for k, n in self.entries if k == "glyph"]
            a, b = names.index(self.current) if self.current in names else 0, names.index(value)
            self.select(set(names[min(a, b):max(a, b) + 1]) | self.selected, value)
        else:
            self.select({value}, value)
        if event.button() == Qt.RightButton:
            self.contextRequested.emit(event.globalPosition())

    def mouseDoubleClickEvent(self, event):
        index = self.index_at(event.position())
        if index is None:
            return
        kind, value = self.entries[index]
        if kind == "glyph":
            self.glyphActivated.emit(value)
        else:
            self.missingActivated.emit(value)

    def keyPressEvent(self, event):
        names = [n for k, n in self.entries if k == "glyph"]
        if not names:
            return
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.current:
            self.glyphActivated.emit(self.current)
            return
        moves = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_Up: -self._columns(), Qt.Key_Down: self._columns()}
        if key in moves:
            i = names.index(self.current) if self.current in names else 0
            i = max(0, min(len(names) - 1, i + moves[key]))
            self.select({names[i]}, names[i])
            self.ensure_visible(names[i])
            return
        super().keyPressEvent(event)

    def ensure_visible(self, name: str) -> None:
        index = next((i for i, (k, n) in enumerate(self.entries) if k == "glyph" and n == name), None)
        if index is None:
            return
        rect = self.cell_rect(index)
        bar = self.verticalScrollBar()
        if rect.top() < 0:
            bar.setValue(bar.value() + rect.top())
        elif rect.bottom() > self.viewport().height():
            bar.setValue(bar.value() + rect.bottom() - self.viewport().height())

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()
