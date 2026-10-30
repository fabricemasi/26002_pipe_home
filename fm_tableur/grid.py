"""Grille interactive d'une feuille (Qt) : géométrie (volets figés, zoom, défilement), peinture, édition.

Choix : un `QAbstractScrollArea` PEINT, pas un `QTableView` — Excel fait déborder le texte sur les cellules vides,
fige des volets, fusionne, dessine des bordures partagées, une poignée de recopie et le surlignage des références
pendant la saisie d'une formule ; et l'aperçu de l'élément dans le Board doit être peint par le MÊME code
(`render.paint_cells`). Seules les lignes / colonnes visibles sont parcourues (feuille de 1 048 576 x 16 384).

La souris et le clavier sont dans `grid_input.GridInput` (mélangé ici). L'état de navigation (cellule active,
sélections, défilement) vit dans la session (`session.SheetView`) : partagé par le Board et le mode Standard."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRegion, QTextOption
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QPlainTextEdit

from . import numfmt, ops, refs as R, render
from . import values as V
from .engine import check_formula
from .formula_lang import to_english, to_local
from .grid_input import GridInput

HEADER_H = 20.0
WHEEL_ROWS = 3


class CellEditor(QPlainTextEdit):
    """Éditeur posé sur la cellule (Entrée valide, Alt+Entrée = nouvelle ligne, Échap annule)."""

    def __init__(self, grid):
        super().__init__(grid.viewport())
        self.grid = grid
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.NoWrap)
        self.document().setDocumentMargin(1)
        self.textChanged.connect(grid._editor_changed)
        self.hide()

    def keyPressEvent(self, event):
        if self.grid._editor_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.grid._editor_focus_out()


class GridWidget(GridInput, QAbstractScrollArea):
    currentChanged = Signal()                 # cellule active / sélection changée (barre de formule, état)
    editTextChanged = Signal(str)             # texte en cours de saisie (barre de formule)
    editingChanged = Signal(bool)
    escapeIdle = Signal()                     # Échap sans rien à annuler (Board : sortir de l'édition)
    saveRequested = Signal()
    findRequested = Signal(bool)              # rechercher (False) / remplacer (True)
    message = Signal(str)                     # message de la barre d'état (formule refusée…)
    zoomChanged = Signal(float)
    contextMenuWanted = Signal(object, str)   # (position globale, "cells" / "rows" / "cols")
    sheetSwitch = Signal(int)                 # Ctrl+PgUp / PgDn : -1 / +1
    tableRequested = Signal()                 # Ctrl+T / Ctrl+L : créer un tableau
    filterMenuWanted = Signal(int, object)    # (colonne, position globale) : bouton du filtre automatique
    dropdownWanted = Signal(int, int, object)  # (ligne, colonne, position globale) : liste déroulante

    def __init__(self, session, parent=None, settings: dict | None = None):
        super().__init__(parent)
        self.session = session
        self.book = session.book
        self.settings = dict(settings or {})
        self.look = dict(render.LOOK)
        self.cache = render.DisplayCache(self.book)
        self.extra_zoom = 1.0                 # zoom de la présentation (Board : celui de la scène = 1)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.viewport().setMouseTracking(True)
        self.viewport().setAutoFillBackground(False)
        # opaque : Qt peut DÉCALER l'image au défilement au lieu de tout repeindre (voir _scrolled)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().setSingleStep(32)
        self._editor = CellEditor(self)
        self._editing = None                  # (ligne, colonne) en cours d'édition
        self._edit_mode = "enter"             # "enter" (frappe : flèches = valider / pointer) ou "edit" (F2)
        self._edit_rect = None                # Ctrl+Entrée : plage remplie par la saisie
        self._point = None                    # (début, fin) de la référence insérée en mode pointage
        self._copied = None                   # plage copiée (pointillés) : (uid de la feuille, rect)
        self._drag = None                     # geste souris en cours
        self._hover_cursor = None
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(40)
        self._autoscroll.timeout.connect(self._autoscroll_tick)
        self._last_mouse = QPointF()
        self._layout_key = None
        self._geo = None
        self.validate = None                  # (ligne, colonne, texte) -> message si la saisie est refusée
        self.apply_settings(self.settings)
        self.book.listeners.append(self._on_book_event)
        self.session.owners.append(self)
        self._restore_view()

    # -- réglages / vie --
    def apply_settings(self, settings: dict):
        self.settings = dict(settings or {})
        g = self.settings.get
        dec = g("tableur_decimal_sep", ",")
        thousands = {"espace": " ", "point": ".", "virgule": ",", "aucun": ""}.get(
            g("tableur_thousands_sep", "espace"), " ")
        lang = g("tableur_lang", "fr")
        self.loc = numfmt.Locale(dec if dec in (",", ".") else ",", thousands, lang)
        self.cache.loc = self.loc
        self.look = render.look_from(self.settings)
        self.date_order = "mdy" if g("tableur_date_order") == "mdy" else "dmy"
        self.formula_lang = "en" if g("tableur_formula_lang") == "en" else "fr"
        self.cache.formula_lang = self.formula_lang
        self.enter_moves = g("tableur_enter_moves", "down")
        self.viewport().update()

    def detach(self):
        """À appeler avant de jeter la grille (la session survit)."""
        self._save_view()
        if self._on_book_event in self.book.listeners:
            self.book.listeners.remove(self._on_book_event)
        if self in self.session.owners:
            self.session.owners.remove(self)

    def set_session(self, session):
        self.detach()
        self.session = session
        self.book = session.book
        self.cache = render.DisplayCache(self.book)
        self.cache.loc = self.loc
        self.cache.formula_lang = self.formula_lang
        self.book.listeners.append(self._on_book_event)
        self.session.owners.append(self)
        self._restore_view()

    @property
    def sheet(self):
        return self.session.sheet

    @property
    def view(self):
        return self.session.view(self.sheet)

    @property
    def zoom(self) -> float:
        return max(0.1, min(4.0, float(self.sheet.zoom or 1.0))) * self.extra_zoom

    def set_zoom(self, value: float):
        value = max(0.1, min(4.0, value))
        if abs(value - self.sheet.zoom) > 1e-6:
            self._save_view()
            self.sheet.zoom = value
            self._layout_key = None
            self._restore_view()
            self.zoomChanged.emit(value)
            self.viewport().update()

    def _on_book_event(self, kind, sheet):
        if kind in ("structure", "sheets", "active"):
            self._layout_key = None
            if kind != "structure":
                self._restore_view()
            self._update_scrollbars()
        if kind == "sheets" and self._copied and self.book.sheet_by_uid(self._copied[0]) is None:
            self._copied = None
        if kind == "cells" and sheet is not None and sheet is self.sheet:
            self._keep_valid()
        self.viewport().update()
        self.currentChanged.emit()

    def _keep_valid(self):
        view = self.view
        r, c = view.current
        view.current = (min(r, R.MAX_ROWS - 1), min(c, R.MAX_COLS - 1))

    # -- géométrie --
    def geo(self):
        sheet = self.sheet
        z = self.zoom
        key = (id(sheet), z, sheet.freeze, self.book.revision, self.viewport().size().toTuple())
        if self._layout_key != key or self._geo is None:
            fr, fc = sheet.freeze
            digits = max(3, len(str(self._extent()[0] + 1)))
            font = QFont(self.font())
            font.setPixelSize(max(6, round(11 * z)))
            hw = round(max(26.0, (digits * 7.5 + 10)) * z)
            hh = round(HEADER_H * z)
            self._geo = {"z": z, "hw": hw, "hh": hh, "fr": fr, "fc": fc,
                         "fw": sheet.cols.pos(fc) * z, "fh": sheet.rows.pos(fr) * z, "font": font}
            self._layout_key = key
        return self._geo

    def _extent(self):
        """(dernière ligne, dernière colonne) que les barres de défilement couvrent."""
        used = self.sheet.used_range()
        last_r, last_c = (used[2], used[3]) if used else (0, 0)
        view = self.view
        last_r = max(last_r, view.current[0], 200)
        last_c = max(last_c, view.current[1], 40)
        return min(R.MAX_ROWS - 1, last_r + 100), min(R.MAX_COLS - 1, last_c + 20)

    def scroll_xy(self):
        return float(self.horizontalScrollBar().value()), float(self.verticalScrollBar().value())

    def x_of(self, col: int) -> float:
        g = self.geo()
        cols = self.sheet.cols
        if col < g["fc"]:
            return g["hw"] + cols.pos(col) * g["z"]
        return g["hw"] + g["fw"] + (cols.pos(col) - cols.pos(g["fc"])) * g["z"] - self.scroll_xy()[0]

    def y_of(self, row: int) -> float:
        g = self.geo()
        rows = self.sheet.rows
        if row < g["fr"]:
            return g["hh"] + rows.pos(row) * g["z"]
        return g["hh"] + g["fh"] + (rows.pos(row) - rows.pos(g["fr"])) * g["z"] - self.scroll_xy()[1]

    def col_at(self, x: float) -> int:
        g = self.geo()
        cols = self.sheet.cols
        lx = x - g["hw"]
        if lx < g["fw"]:
            return cols.index_at(max(0.0, lx) / g["z"])
        return cols.index_at((lx - g["fw"] + self.scroll_xy()[0]) / g["z"] + cols.pos(g["fc"]))

    def row_at(self, y: float) -> int:
        g = self.geo()
        rows = self.sheet.rows
        ly = y - g["hh"]
        if ly < g["fh"]:
            return rows.index_at(max(0.0, ly) / g["z"])
        return rows.index_at((ly - g["fh"] + self.scroll_xy()[1]) / g["z"] + rows.pos(g["fr"]))

    def cell_rect(self, row: int, col: int, merged: bool = True) -> QRectF:
        sheet = self.sheet
        z = self.zoom
        if merged:
            m = sheet.merge_at(row, col)
            if m is not None:
                x, y = self.x_of(m[1]), self.y_of(m[0])
                return QRectF(x, y, (sheet.cols.pos(m[3] + 1) - sheet.cols.pos(m[1])) * z,
                              (sheet.rows.pos(m[2] + 1) - sheet.rows.pos(m[0])) * z)
        return QRectF(self.x_of(col), self.y_of(row), sheet.cols.size(col) * z, sheet.rows.size(row) * z)

    def range_rect(self, rect) -> QRectF:
        r0, c0, r1, c1 = ops.norm(rect)
        a = self.cell_rect(r0, c0, merged=False)
        b = self.cell_rect(r1, c1, merged=False)
        return QRectF(a.topLeft(), b.bottomRight())

    def _main_origin(self):
        """(première ligne, première colonne) visibles de la zone qui défile."""
        g = self.geo()
        return self.row_at(g["hh"] + g["fh"] + 0.5), self.col_at(g["hw"] + g["fw"] + 0.5)

    # -- défilement --
    def _update_scrollbars(self):
        g = self.geo()
        sheet = self.sheet
        last_r, last_c = self._extent()
        vw = max(1, self.viewport().width() - g["hw"] - g["fw"])
        vh = max(1, self.viewport().height() - g["hh"] - g["fh"])
        total_w = (sheet.cols.pos(last_c + 1) - sheet.cols.pos(g["fc"])) * g["z"]
        total_h = (sheet.rows.pos(last_r + 1) - sheet.rows.pos(g["fr"])) * g["z"]
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        hbar.blockSignals(True)
        vbar.blockSignals(True)
        hbar.setRange(0, max(0, int(total_w - vw * 0.5)))
        hbar.setPageStep(int(vw))
        vbar.setRange(0, max(0, int(total_h - vh * 0.5)))
        vbar.setPageStep(int(vh))
        vbar.setSingleStep(max(1, int(sheet.rows.default * g["z"])))
        hbar.blockSignals(False)
        vbar.blockSignals(False)

    def _scrolled(self, _value):
        """Défilement : l'image déjà peinte est DÉCALÉE (`QWidget.scroll`), seule la bande découverte est peinte
        (molette de 3 lignes : ~1/12 de l'écran au lieu de tout)."""
        self._save_view()
        sx, sy = self.scroll_xy()
        last = getattr(self, "_last_scroll", None)
        self._last_scroll = (sx, sy)
        if self._editing is not None:
            self._place_editor()
        vp = self.viewport()
        if last is None or self._editing is not None or self._drag is not None:
            vp.update()
            return
        dx, dy = int(round(sx - last[0])), int(round(sy - last[1]))
        g = self.geo()
        if (dx and dy) or abs(dx) >= vp.width() // 2 or abs(dy) >= vp.height() // 2 or (sx - last[0]) % 1 or                 (sy - last[1]) % 1:
            vp.update()
            return
        if dy:
            top = int(g["hh"] + g["fh"])
            vp.scroll(0, -dy, QRect(0, top, vp.width(), vp.height() - top))
        if dx:
            left = int(g["hw"] + g["fw"])
            vp.scroll(-dx, 0, QRect(left, 0, vp.width() - left, vp.height()))

    def scrollContentsBy(self, dx, dy):
        pass                                           # QAbstractScrollArea repeindrait TOUT : voir _scrolled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_key = None
        self._update_scrollbars()
        if self._editing is not None:
            self._place_editor()

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_key = None
        self._update_scrollbars()
        self._restore_view()

    def _save_view(self):
        view = self.session.view(self.sheet) if self.book.sheets else None
        if view is not None:
            z = self.zoom or 1.0
            sx, sy = self.scroll_xy()
            view.scroll = (sx / z, sy / z)

    def _restore_view(self):
        if not self.book.sheets:
            return
        self._layout_key = None
        self._update_scrollbars()
        view = self.view
        z = self.zoom
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        for bar, value in ((hbar, view.scroll[0] * z), (vbar, view.scroll[1] * z)):
            if value > bar.maximum():
                bar.setMaximum(int(value) + 1)
            bar.blockSignals(True)
            bar.setValue(int(value))
            bar.blockSignals(False)
        self.viewport().update()

    def ensure_visible(self, row: int, col: int):
        g = self.geo()
        rect = self.cell_rect(row, col)
        vw, vh = self.viewport().width(), self.viewport().height()
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        if col >= g["fc"]:
            left = g["hw"] + g["fw"]
            if rect.left() < left:
                hbar.setValue(int(hbar.value() - (left - rect.left())))
            elif rect.right() > vw:
                need = hbar.value() + rect.right() - vw + 2
                if need > hbar.maximum():
                    self._update_scrollbars()
                    hbar.setMaximum(max(hbar.maximum(), int(need)))
                hbar.setValue(int(min(need, hbar.value() + rect.left() - left)))
        if row >= g["fr"]:
            top = g["hh"] + g["fh"]
            if rect.top() < top:
                vbar.setValue(int(vbar.value() - (top - rect.top())))
            elif rect.bottom() > vh:
                need = vbar.value() + rect.bottom() - vh + 2
                if need > vbar.maximum():
                    self._update_scrollbars()
                    vbar.setMaximum(max(vbar.maximum(), int(need)))
                vbar.setValue(int(min(need, vbar.value() + rect.top() - top)))

    # -- peinture --
    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setClipRegion(event.region())
        for area in event.region():                    # chaque morceau de la région (sélection, bande de défilement)
            self.paint_to(painter, area)
        painter.end()

    def paint_to(self, painter, area):
        g = self.geo()
        sheet = self.sheet
        z = g["z"]
        painter.fillRect(area, QColor(self.look["background"]))
        width, height = area.right() + 1, area.bottom() + 1        # peint jusqu'au bord de la zone exposée
        top_rows = render.visible_span(sheet.rows, 0, g["hh"], g["hh"] + g["fh"], z, stop=g["fr"])
        left_cols = render.visible_span(sheet.cols, 0, g["hw"], g["hw"] + g["fw"], z, stop=g["fc"])
        r_main, c_main = self._main_origin()
        # zone exposée seulement (défilement : une bande) ; 3 colonnes de plus à gauche pour le débordement du texte
        r_first = max(r_main, self.row_at(max(area.top(), g["hh"] + g["fh"]) + 0.5))
        c_first = max(c_main, self.col_at(max(area.left(), g["hw"] + g["fw"]) + 0.5))
        for _i in range(3):
            if c_first > c_main:
                c_first = sheet.cols.next_visible(c_first, -1)
        main_rows = render.visible_span(sheet.rows, r_first, self.y_of(r_first), height, z)
        main_cols = render.visible_span(sheet.cols, c_first, self.x_of(c_first), width, z)
        body = QRectF(g["hw"] + g["fw"], g["hh"] + g["fh"], width, height)
        regions = [(main_rows, main_cols, body)]
        if g["fr"]:
            regions.append((top_rows, main_cols, QRectF(g["hw"] + g["fw"], g["hh"], width, g["fh"])))
        if g["fc"]:
            regions.append((main_rows, left_cols, QRectF(g["hw"], g["hh"] + g["fh"], g["fw"], height)))
        if g["fr"] and g["fc"]:
            regions.append((top_rows, left_cols, QRectF(g["hw"], g["hh"], g["fw"], g["fh"])))
        self.cache.show_formulas = self.session.show_formulas
        for rows, cols, clip in regions:
            render.paint_cells(painter, self.book, sheet, rows, cols, z, self.cache, self.look, clip=clip)
            painter.save()
            painter.setClipRect(clip)
            self._paint_selection(painter, rows, cols)
            painter.restore()
        self._paint_marks(painter)
        if g["fr"] or g["fc"]:
            painter.setPen(QPen(QColor("#9a9a9a"), 1))
            if g["fr"]:
                y = g["hh"] + g["fh"] - 0.5
                painter.drawLine(QPointF(g["hw"], y), QPointF(width, y))
            if g["fc"]:
                x = g["hw"] + g["fw"] - 0.5
                painter.drawLine(QPointF(x, g["hh"]), QPointF(x, height))
        self._paint_headers(painter, top_rows, main_rows, left_cols, main_cols, width, height)

    def filter_button_rect(self, col) -> QRectF | None:
        af = self.sheet.autofilter
        if af is None or not af[1] <= col <= af[3]:
            return None
        rect = self.cell_rect(af[0], col, merged=False)
        size = min(rect.height() - 2, 16 * self.zoom)
        return QRectF(rect.right() - size - 2, rect.bottom() - size - 1, size, size)

    def dropdown_rect(self) -> QRectF | None:
        r, c = self.view.current
        validator = getattr(self.parent(), "validation_at", None)
        if validator is None or not validator(r, c):
            return None
        rect = self.cell_rect(r, c)
        size = min(rect.height(), 18 * self.zoom)
        return QRectF(rect.right() + 1, rect.bottom() - size, size, size)

    def _paint_marks(self, painter):
        """Boutons du filtre automatique, flèche de liste déroulante, coins des commentaires."""
        sheet = self.sheet
        painter.save()
        if sheet.autofilter is not None:
            af = sheet.autofilter
            for col in range(af[1], min(af[3], af[1] + 200) + 1):
                rect = self.filter_button_rect(col)
                if rect is None or rect.right() < 0 or rect.left() > self.viewport().width():
                    continue
                on = col in sheet.filters
                painter.setPen(QPen(QColor("#8a8a8a"), 1))
                painter.setBrush(QColor("#ddeedd" if on else "#f7f7f7"))
                painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
                c = rect.center()
                s = rect.width() * 0.22
                painter.setBrush(QColor("#107c41" if on else "#444444"))
                painter.setPen(Qt.NoPen)
                painter.drawPolygon([QPointF(c.x() - s, c.y() - s / 2), QPointF(c.x() + s, c.y() - s / 2),
                                     QPointF(c.x(), c.y() + s / 1.2)])
        if sheet.comments:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#d13438"))
            width = self.viewport().width()
            height = self.viewport().height()
            for (r, c) in sheet.comments:
                rect = self.cell_rect(r, c)
                if rect.right() < 0 or rect.left() > width or rect.bottom() < 0 or rect.top() > height:
                    continue
                s = 6 * self.zoom
                painter.drawPolygon([QPointF(rect.right() - s - 1, rect.top() + 1),
                                     QPointF(rect.right() - 1, rect.top() + 1),
                                     QPointF(rect.right() - 1, rect.top() + s + 1)])
        drop = self.dropdown_rect()
        if drop is not None and self._editing is None:
            painter.setPen(QPen(QColor("#8a8a8a"), 1))
            painter.setBrush(QColor("#f7f7f7"))
            painter.drawRect(drop.adjusted(0.5, 0.5, -0.5, -0.5))
            c = drop.center()
            s = drop.width() * 0.22
            painter.setBrush(QColor("#444444"))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon([QPointF(c.x() - s, c.y() - s / 2), QPointF(c.x() + s, c.y() - s / 2),
                                 QPointF(c.x(), c.y() + s / 1.2)])
        painter.restore()

    def _paint_headers(self, painter, top_rows, main_rows, left_cols, main_cols, width, height):
        g = self.geo()
        look = self.look
        bg, line = QColor(look["header_bg"]), QColor(look["header_line"])
        sel_bg, sel_text, text = QColor(look["header_sel_bg"]), QColor(look["header_sel_text"]), \
            QColor(look["header_text"])
        accent = QColor(look["selection"])
        painter.save()
        painter.setFont(g["font"])
        rows_sel, cols_sel, full_rows, full_cols = self._header_selection()
        painter.fillRect(QRectF(0, 0, width, g["hh"]), bg)
        painter.fillRect(QRectF(0, 0, g["hw"], height), bg)
        for span, clip in ((left_cols, QRectF(g["hw"], 0, g["fw"], g["hh"])),
                           (main_cols, QRectF(g["hw"] + g["fw"], 0, width, g["hh"]))):
            painter.setClipRect(clip)
            for c, x, w in span.items:
                rect = QRectF(x, 0, w, g["hh"])
                on = c in cols_sel
                if on:
                    painter.fillRect(rect, accent if c in full_cols else sel_bg)
                painter.setPen(line)
                painter.drawLine(QPointF(x + w - 0.5, 0), QPointF(x + w - 0.5, g["hh"]))
                painter.setPen(QColor("#ffffff") if c in full_cols else (sel_text if on else text))
                painter.drawText(rect, Qt.AlignCenter, R.col_name(c))
                if on and c not in full_cols:
                    painter.fillRect(QRectF(x, g["hh"] - 2, w, 2), accent)
        for span, clip in ((top_rows, QRectF(0, g["hh"], g["hw"], g["fh"])),
                           (main_rows, QRectF(0, g["hh"] + g["fh"], g["hw"], height))):
            painter.setClipRect(clip)
            for r, y, h in span.items:
                rect = QRectF(0, y, g["hw"], h)
                on = r in rows_sel
                if on:
                    painter.fillRect(rect, accent if r in full_rows else sel_bg)
                painter.setPen(line)
                painter.drawLine(QPointF(0, y + h - 0.5), QPointF(g["hw"], y + h - 0.5))
                painter.setPen(QColor("#ffffff") if r in full_rows else (sel_text if on else text))
                painter.drawText(rect.adjusted(0, 0, -4 * g["z"], 0), Qt.AlignRight | Qt.AlignVCenter, str(r + 1))
                if on and r not in full_rows:
                    painter.fillRect(QRectF(g["hw"] - 2, y, 2, h), accent)
        painter.setClipping(False)
        painter.setPen(line)
        painter.drawLine(QPointF(0, g["hh"] - 0.5), QPointF(width, g["hh"] - 0.5))
        painter.drawLine(QPointF(g["hw"] - 0.5, 0), QPointF(g["hw"] - 0.5, height))
        corner = QRectF(0, 0, g["hw"], g["hh"])
        painter.fillRect(corner.adjusted(0, 0, -1, -1), bg)
        tri = [QPointF(corner.right() - 4, corner.bottom() - 12 * g["z"]), QPointF(corner.right() - 4,
                                                                                  corner.bottom() - 4),
               QPointF(corner.right() - 12 * g["z"], corner.bottom() - 4)]
        painter.setBrush(QColor("#b8b8b8"))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(tri)
        painter.restore()

    def _header_selection(self):
        rows, cols, full_rows, full_cols = set(), set(), set(), set()
        for r0, c0, r1, c1 in (ops.norm(x) for x in self.view.ranges):
            whole_cols = r0 == 0 and r1 == R.MAX_ROWS - 1
            whole_rows = c0 == 0 and c1 == R.MAX_COLS - 1
            if r1 - r0 < 5000:
                rows.update(range(r0, r1 + 1))
                if whole_rows:
                    full_rows.update(range(r0, r1 + 1))
            else:
                rows.update(range(r0, min(r1, r0 + 5000) + 1))
            if c1 - c0 < 2000:
                cols.update(range(c0, c1 + 1))
                if whole_cols:
                    full_cols.update(range(c0, c1 + 1))
            else:
                cols.update(range(c0, min(c1, c0 + 2000) + 1))
        return rows, cols, full_rows, full_cols

    def _paint_selection(self, painter, rows, cols):
        if not rows.items or not cols.items:
            return
        view = self.view
        accent = QColor(self.look["selection"])
        fill = QColor(self.look["selection_fill"])
        many = len(view.ranges) > 1
        for rect in view.ranges:
            r0, c0, r1, c1 = ops.norm(rect)
            if (r0, c0) == (r1, c1) and not many:
                continue
            area = self.range_rect(rect)
            painter.fillRect(area, fill)
        cur = self.cell_rect(*view.current)
        painter.fillRect(cur, QColor(self.look["background"]))
        r, c = view.current
        last =ops.norm(view.ranges[-1]) if view.ranges else (r, c, r, c)
        if not many:
            outline = self.range_rect(last)
            painter.setPen(QPen(accent, 2 * max(0.75, min(1.5, self.zoom))))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(outline.adjusted(0, 0, -1, -1))
            handle = QRectF(outline.right() - 3.5, outline.bottom() - 3.5, 6, 6)
            painter.fillRect(handle.adjusted(-1, -1, 1, 1), QColor(self.look["background"]))
            painter.fillRect(handle, accent)
        else:
            painter.setPen(QPen(accent, 1.5))
            painter.drawRect(cur.adjusted(0, 0, -1, -1))
        # contenu de la cellule active repeint par-dessus le blanc
        self._repaint_current(painter)
        if self._copied and self._copied[0] == self.sheet.uid:
            pen = QPen(accent, 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.range_rect(self._copied[1]).adjusted(1, 1, -2, -2))
        if self._editing is not None:
            self._paint_formula_refs(painter)
        if self._drag and self._drag.get("kind") == "fill" and self._drag.get("target"):
            painter.setPen(QPen(QColor("#707070"), 1.2, Qt.DashLine))
            painter.drawRect(self.range_rect(self._drag["target"]).adjusted(0, 0, -1, -1))

    def _repaint_current(self, painter):
        """La cellule active n'est pas teintée : son contenu est repeint (fond, texte, bordures)."""
        r, c = self.view.current
        m = self.sheet.merge_at(r, c)
        r0, c0, r1, c1 = m if m else (r, c, r, c)
        z = self.zoom
        rows = render.Span([(i, self.y_of(i), self.sheet.rows.size(i) * z) for i in range(r0, r1 + 1)
                            if self.sheet.rows.size(i) > 0])
        cols = render.Span([(i, self.x_of(i), self.sheet.cols.size(i) * z) for i in range(c0, c1 + 1)
                            if self.sheet.cols.size(i) > 0])
        if rows.items and cols.items:
            render.paint_cells(painter, self.book, self.sheet, rows, cols, z, self.cache, self.look,
                               clip=self.cell_rect(r, c).intersected(painter.clipBoundingRect()
                                                                     if painter.hasClipping()
                                                                     else self.cell_rect(r, c)))

    def _paint_formula_refs(self, painter):
        text = self._editor.toPlainText()
        if not text.startswith("="):
            return
        colors = self.look["ref_colors"]
        name = self.sheet.name.lower()
        for i, (sheet_name, bounds, _ref) in enumerate(R.referenced_ranges(text, self.sheet.name)):
            if sheet_name.lower() != name:
                continue
            r0, c0, r1, c1 = bounds
            r1, c1 = min(r1, r0 + 5000), min(c1, c0 + 2000)
            color = QColor(colors[i % len(colors)])
            rect = self.range_rect((r0, c0, r1, c1))
            fill = QColor(color)
            fill.setAlpha(28)
            painter.fillRect(rect, fill)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0.5, 0.5, -1, -1))

    # -- édition --
    def is_editing(self) -> bool:
        return self._editing is not None

    def edit_text(self) -> str:
        return self._editor.toPlainText() if self._editing is not None else ""

    def current_input_text(self) -> str:
        """Texte de la cellule active tel qu'il s'édite (barre de formule)."""
        r, c = self.view.current
        cell = self.sheet.cell(r, c)
        if cell is None:
            return ""
        fmt = self.book.styles.get(cell.style).get("fmt")
        if cell.formula:
            return to_local(cell.formula, self.formula_lang)
        return V.edit_text(cell.value, cell.formula, fmt, self.loc)

    def begin_edit(self, text: str | None = None, mode: str = "edit", focus: bool = True):
        if self.sheet.protected and self.book.styles.get(self.sheet.style_index(*self.view.current)).get(
                "locked", True) is not False:
            self.message.emit("Feuille protégée : cellule verrouillée.")
            return
        self._editing = self.view.current
        self._edit_mode = mode
        self._point = None
        self._edit_rect = None
        self._editor.blockSignals(True)
        self._editor.setPlainText(self.current_input_text() if text is None else text)
        self._editor.blockSignals(False)
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._editor.setTextCursor(cursor)
        self._place_editor()
        self._editor.show()
        if focus:
            self._editor.setFocus()
        self.editingChanged.emit(True)
        self.editTextChanged.emit(self._editor.toPlainText())
        self.viewport().update()

    def _place_editor(self):
        if self._editing is None:
            return
        r, c = self._editing
        rect = self.cell_rect(r, c)
        style = self.book.styles.get(self.sheet.style_index(r, c))
        font, metrics = render.fonts().font(self.book, style, self.zoom)
        self._editor.setFont(font)
        width = max(rect.width(), metrics.horizontalAdvance(self._editor.toPlainText() + "MM"))
        width = min(width, self.viewport().width() - rect.left())
        lines = max(1, self._editor.toPlainText().count("\n") + 1)
        height = max(rect.height(), metrics.height() * lines + 4)
        self._editor.setGeometry(int(rect.left()) + 1, int(rect.top()) + 1, int(width) - 2, int(height) - 2)
        fill = style.get("fill") or self.look["background"]
        self._editor.setStyleSheet(f"QPlainTextEdit {{ background: {fill}; color: {style.get('color') or '#000'};"
                                   f" border: none; }}")

    def set_edit_text(self, text: str):
        """Texte tapé dans la barre de formule pendant l'édition."""
        if self._editing is None:
            self.begin_edit(text, mode="edit", focus=False)
            return
        if self._editor.toPlainText() != text:
            self._editor.blockSignals(True)
            self._editor.setPlainText(text)
            self._editor.blockSignals(False)
            self._place_editor()
            self.viewport().update()

    def _editor_changed(self):
        self._point = None if not self._editor.textCursor().hasSelection() else self._point
        self._place_editor()
        self.editTextChanged.emit(self._editor.toPlainText())
        self.viewport().update()

    def _editor_focus_out(self):
        pass                                           # la barre de formule peut prendre le clavier

    def commit_edit(self, move=(1, 0), whole_selection: bool = False) -> bool:
        if self._editing is None:
            return True
        text = self._editor.toPlainText()
        if text.startswith("=") and len(text) > 1:
            text = to_english(_close_parens(text), self.formula_lang)
            problem = check_formula(text)
            if problem:
                self.message.emit(f"Formule refusée : {problem}")
                return False
        r, c = self._editing
        if self.validate is not None:
            problem = self.validate(r, c, text)
            if problem:
                self.message.emit(problem)
                return False
        rect = ops.norm(self.view.ranges[-1]) if whole_selection and self.view.ranges else None
        self._finish_edit()
        old = self.sheet.cell(r, c)
        old_text = self.current_input_text() if old is not None else ""
        if text != old_text or rect is not None:
            stack = self.session.stack
            stack.begin("Saisir")
            ops.set_input(self.book, stack, self.sheet, r, c, text, self.loc, rect=rect, date_order=self.date_order)
            self._widen_for_number(r, c)
            stack.end()
        if move and move != (0, 0) and not whole_selection:
            self.move_in_selection(*move)
        self.setFocus()
        return True

    def _widen_for_number(self, r, c):
        """Comme Excel : un NOMBRE saisi qui ne tient pas dans une colonne de largeur par défaut l'élargit (au lieu
        d'afficher « #### ») ; une largeur choisie par l'utilisateur n'est jamais touchée."""
        sheet = self.sheet
        if c in sheet.cols.sizes or sheet.merge_at(r, c):
            return
        text, _color, value = ops.display_text(self.book, sheet, r, c, self.loc)
        if not text or isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        style = self.book.styles.get(sheet.style_index(r, c))
        width = render.text_size(self.book, style, text)[0] + 10
        if width > sheet.cols.size(c):
            ops.set_sizes(self.book, self.session.stack, sheet, "col", [c], min(width, 400))

    def cancel_edit(self):
        if self._editing is None:
            return
        self._finish_edit()
        self.setFocus()

    def _finish_edit(self):
        self._editing = None
        self._point = None
        self._editor.hide()
        self.editingChanged.emit(False)
        self.currentChanged.emit()
        self.viewport().update()

    def update_selection_area(self, before):
        """Après un changement de sélection : seules les zones de l'ancienne et de la nouvelle sélection (et les
        bandes d'en-têtes) sont repeintes — tout repeindre coûtait ~30 ms par flèche en 2400 x 1300."""
        vp = self.viewport()
        if before is None or len(before[0]) > 4 or len(self.view.ranges) > 4:
            vp.update()
            return
        g = self.geo()
        region = QRegion()                             # région (pas un rectangle englobant)
        for ranges, current in (before, (self.view.ranges, self.view.current)):
            for rect in list(ranges) + [(*current, *current)]:
                r0, c0, r1, c1 = ops.norm(rect)
                if r1 - r0 > 400 or c1 - c0 > 100:
                    vp.update()
                    return
                area = self.range_rect((r0, c0, r1, c1)).adjusted(-4, -4, 5, 5).toAlignedRect()
                region += area
                region += QRect(0, area.top(), int(g["hw"]) + 1, area.height())
                region += QRect(area.left(), 0, area.width(), int(g["hh"]) + 1)
        vp.update(region)

    # -- presse-papiers (marque) --
    def set_copied(self, rect):
        self._copied = (self.sheet.uid, ops.norm(rect)) if rect is not None else None
        self.viewport().update()


def _close_parens(text: str) -> str:
    """Parenthèses fermantes manquantes ajoutées à la validation (Excel le propose)."""
    depth = 0
    in_str = False
    for ch in text:
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            depth += (ch == "(") - (ch == ")")
    if in_str:
        text += '"'
    return text + ")" * max(0, depth)
