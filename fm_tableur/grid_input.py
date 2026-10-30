"""Souris et clavier de la grille (mélangé à `grid.GridWidget`) : gestes et raccourcis d'Excel.

Souris : clic = cellule ; Maj + clic = étendre ; Ctrl + clic = ajouter une plage ; glisser = plage ; en-têtes =
lignes / colonnes entières ; bord d'en-tête = taille (double-clic : ajustée au contenu) ; poignée de recopie ;
pendant la saisie d'une formule, clic / glisser = référence insérée (mode pointage). Aucun DÉPLACEMENT d'élément
ici (règle Ctrl de l'appli sans objet : couper / coller déplace les cellules).
Clavier : flèches (Maj : étendre, Ctrl : bord des données), Entrée / Tab dans la sélection, F2, Suppr, Échap,
Ctrl+C / X / V / Z / Y / A / B / I / U / D / R / ; / F / H / S / +/-, Ctrl+Espace, Maj+Espace, F4, F9,
Ctrl+` (formules), Ctrl+PgUp / PgDn (feuilles), PgUp / PgDn, Début, Ctrl+Début / Fin, Ctrl+Entrée."""
from __future__ import annotations

import bisect
import datetime as _dt

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt

from PySide6.QtWidgets import QApplication

from . import numfmt, ops, refs as R, render

WHEEL_ROWS = 3

RESIZE_GRIP = 4
_CLIP = {"block": None, "text": None}          # presse-papiers interne (formules, styles) + texte publié


def _cells_rows(sheet, col):
    return sorted(r for (r, c), cell in sheet.cells.items() if c == col and not cell.is_blank())


def _cells_cols(sheet, row):
    return sorted(c for (r, c), cell in sheet.cells.items() if r == row and not cell.is_blank())


def data_edge(sheet, row, col, dr, dc):
    """Ctrl + flèche : bord du bloc de données (Excel)."""
    filled = (lambda r, c: (cell := sheet.cells.get((r, c))) is not None and not cell.is_blank())
    if dr:
        line = _cells_rows(sheet, col)
        here = row
        limit = R.MAX_ROWS - 1
    else:
        line = _cells_cols(sheet, row)
        here = col
        limit = R.MAX_COLS - 1
    step = dr or dc
    nxt = here + step
    if 0 <= nxt <= limit and filled(*((nxt, col) if dr else (row, nxt))) and \
            filled(*((here, col) if dr else (row, here))):
        pos = nxt
        while 0 <= pos + step <= limit and filled(*((pos + step, col) if dr else (row, pos + step))):
            pos += step
        return pos
    if step > 0:
        i = bisect.bisect_right(line, here)
        return line[i] if i < len(line) else limit
    i = bisect.bisect_left(line, here) - 1
    return line[i] if i >= 0 else 0


class GridInput:
    # ------------------------------------------------------------ sélection
    def select(self, row, col, extend=False, add=False, keep_scroll=False):
        view = self.view
        before = (list(view.ranges), view.current)
        row = max(0, min(R.MAX_ROWS - 1, row))
        col = max(0, min(R.MAX_COLS - 1, col))
        if extend:
            ar, ac = view.anchor
            rect = self._expand_merges((min(ar, row), min(ac, col), max(ar, row), max(ac, col)))
            view.ranges[-1] = rect
            if not keep_scroll:
                self.ensure_visible(row, col)
            self._end_point = (row, col)
        else:
            m = self.sheet.merge_at(row, col)
            if m:
                row, col = m[0], m[1]
            view.current = (row, col)
            view.anchor = (row, col)
            rect = m if m else (row, col, row, col)
            if add:
                view.ranges.append(rect)
            else:
                view.ranges = [rect]
            self._end_point = (row, col)
            if not keep_scroll:
                self.ensure_visible(row, col)
        self.update_selection_area(before)            # après un défilement : zones déjà décalées avec l'image
        self.currentChanged.emit()

    def select_range(self, rect, current=None):
        rect = ops.norm(rect)
        view = self.view
        view.ranges = [rect]
        view.current = current or (rect[0], rect[1])
        view.anchor = view.current
        self.ensure_visible(*view.current)
        self.viewport().update()
        self.currentChanged.emit()

    def selection(self):
        return ops.norm(self.view.ranges[-1]) if self.view.ranges else (*self.view.current, *self.view.current)

    def _expand_merges(self, rect):
        r0, c0, r1, c1 = rect
        changed = True
        while changed:
            changed = False
            for m in self.sheet.merges:
                if not (m[2] < r0 or m[0] > r1 or m[3] < c0 or m[1] > c1):
                    nr0, nc0, nr1, nc1 = min(r0, m[0]), min(c0, m[1]), max(r1, m[2]), max(c1, m[3])
                    if (nr0, nc0, nr1, nc1) != (r0, c0, r1, c1):
                        r0, c0, r1, c1 = nr0, nc0, nr1, nc1
                        changed = True
        return r0, c0, r1, c1

    def move_in_selection(self, dr, dc):
        """Entrée / Tab : dans une sélection de plusieurs cellules, la cellule active la parcourt (Excel)."""
        view = self.view
        r0, c0, r1, c1 = self.selection()
        if (r0, c0) == (r1, c1) or len(view.ranges) > 1:
            r, c = view.current
            rows, cols = self.sheet.rows, self.sheet.cols
            nr = rows.next_visible(r, dr) if dr else r
            nc = cols.next_visible(c, dc) if dc else c
            m = self.sheet.merge_at(r, c)
            if m and dr > 0:
                nr = rows.next_visible(m[2], 1)
            if m and dc > 0:
                nc = cols.next_visible(m[3], 1)
            self.select(nr, nc)
            return
        r, c = view.current
        if dc:
            c += dc
            if c > c1:
                c, r = c0, r + 1
            elif c < c0:
                c, r = c1, r - 1
            if r > r1:
                r = r0
            elif r < r0:
                r = r1
        else:
            r += dr
            if r > r1:
                r, c = r0, c + 1
            elif r < r0:
                r, c = r1, c - 1
            if c > c1:
                c = c0
            elif c < c0:
                c = c1
        view.current = (r, c)
        self.ensure_visible(r, c)
        self.viewport().update()
        self.currentChanged.emit()

    # ------------------------------------------------------------ souris
    def _zone(self, pos: QPointF):
        g = self.geo()
        x, y = pos.x(), pos.y()
        if x < g["hw"] and y < g["hh"]:
            return ("corner", None)
        if y < g["hh"]:
            col = self.col_at(x)
            right = self.x_of(col) + self.sheet.cols.size(col) * g["z"]
            left = self.x_of(col)
            if abs(x - right) <= RESIZE_GRIP:
                return ("col_resize", col)
            if abs(x - left) <= RESIZE_GRIP and col > 0:
                prev = self.sheet.cols.next_visible(col, -1)
                return ("col_resize", prev)
            return ("col_header", col)
        if x < g["hw"]:
            row = self.row_at(y)
            bottom = self.y_of(row) + self.sheet.rows.size(row) * g["z"]
            top = self.y_of(row)
            if abs(y - bottom) <= RESIZE_GRIP:
                return ("row_resize", row)
            if abs(y - top) <= RESIZE_GRIP and row > 0:
                return ("row_resize", self.sheet.rows.next_visible(row, -1))
            return ("row_header", row)
        r0, c0, r1, c1 = self.selection()
        if len(self.view.ranges) == 1:
            corner = self.range_rect((r0, c0, r1, c1)).bottomRight()
            if abs(x - corner.x()) <= 5 and abs(y - corner.y()) <= 5:
                return ("fill_handle", None)
        return ("cell", (self.row_at(y), self.col_at(x)))

    def mousePressEvent(self, event):
        pos = event.position()
        self._last_mouse = pos
        zone, info = self._zone(pos)
        mods = event.modifiers()
        if event.button() == Qt.RightButton:
            if zone == "cell" and not self._in_selection(*info):
                self.select(*info)
            elif zone == "col_header" and not self._col_selected(info):
                self._select_cols(info, info)
            elif zone == "row_header" and not self._row_selected(info):
                self._select_rows(info, info)
            kind = {"col_header": "cols", "row_header": "rows"}.get(zone, "cells")
            self.contextMenuWanted.emit(event.globalPosition().toPoint(), kind)
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if zone == "cell" and not self.is_editing():
            drop = self.dropdown_rect()
            if drop is not None and drop.contains(pos):
                self.dropdownWanted.emit(*self.view.current, event.globalPosition().toPoint())
                event.accept()
                return
            fb = self.filter_button_rect(info[1])
            if fb is not None and fb.contains(pos):
                self.filterMenuWanted.emit(info[1], event.globalPosition().toPoint())
                event.accept()
                return
        if self.is_editing() and zone == "cell" and self._can_point():
            self._point_at(*info, start=True)
            self._drag = {"kind": "point", "start": info}
            event.accept()
            return
        if self.is_editing() and zone != "fill_handle":
            if not self.commit_edit(move=None):
                return
        self.setFocus()
        if zone == "corner":
            self.select_range((0, 0, R.MAX_ROWS - 1, R.MAX_COLS - 1), current=self.view.current)
        elif zone in ("col_resize", "row_resize"):
            axis = self.sheet.cols if zone == "col_resize" else self.sheet.rows
            self._drag = {"kind": zone, "index": info, "start": pos, "size": axis.size(info)}
        elif zone == "col_header":
            if mods & Qt.ShiftModifier:
                self._select_cols(self.view.anchor[1], info)
            else:
                self._select_cols(info, info, add=bool(mods & Qt.ControlModifier))
            self._drag = {"kind": "cols", "anchor": self.view.anchor[1]}
        elif zone == "row_header":
            if mods & Qt.ShiftModifier:
                self._select_rows(self.view.anchor[0], info)
            else:
                self._select_rows(info, info, add=bool(mods & Qt.ControlModifier))
            self._drag = {"kind": "rows", "anchor": self.view.anchor[0]}
        elif zone == "fill_handle":
            self._drag = {"kind": "fill", "source": self.selection(), "target": None}
        else:
            row, col = info
            if mods & Qt.ShiftModifier:
                self.select(row, col, extend=True)
            else:
                self.select(row, col, add=bool(mods & Qt.ControlModifier))
            self._drag = {"kind": "cells"}
        event.accept()

    def _select_cols(self, a, b, add=False):
        lo, hi = min(a, b), max(a, b)
        rect = (0, lo, R.MAX_ROWS - 1, hi)
        view = self.view
        r = view.current[0] if not add else 0
        if add:
            view.ranges.append(rect)
        else:
            view.ranges = [rect]
        view.current = (self.row_at(self.geo()["hh"] + self.geo()["fh"] + 1) if r == 0 else r, a)
        view.current = (view.current[0], lo if a == b else a)
        view.anchor = (0, a)
        self.viewport().update()
        self.currentChanged.emit()

    def _select_rows(self, a, b, add=False):
        lo, hi = min(a, b), max(a, b)
        rect = (lo, 0, hi, R.MAX_COLS - 1)
        view = self.view
        if add:
            view.ranges.append(rect)
        else:
            view.ranges = [rect]
        view.current = (lo if a == b else a, self.col_at(self.geo()["hw"] + self.geo()["fw"] + 1))
        view.anchor = (a, 0)
        self.viewport().update()
        self.currentChanged.emit()

    def _in_selection(self, r, c):
        return any(x[0] <= r <= x[2] and x[1] <= c <= x[3] for x in (ops.norm(x) for x in self.view.ranges))

    def _col_selected(self, c):
        return any(x[0] == 0 and x[2] == R.MAX_ROWS - 1 and x[1] <= c <= x[3]
                   for x in (ops.norm(x) for x in self.view.ranges))

    def _row_selected(self, r):
        return any(x[1] == 0 and x[3] == R.MAX_COLS - 1 and x[0] <= r <= x[2]
                   for x in (ops.norm(x) for x in self.view.ranges))

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._last_mouse = pos
        drag = self._drag
        if drag is None:
            zone, _info = self._zone(pos)
            note = self.sheet.comments.get(_info) if zone == "cell" else None
            if note != getattr(self, "_shown_note", None):
                self._shown_note = note
                from PySide6.QtWidgets import QToolTip
                if note:
                    QToolTip.showText(event.globalPosition().toPoint(), note, self)
                else:
                    QToolTip.hideText()
            cursor = {"col_resize": Qt.SplitHCursor, "row_resize": Qt.SplitVCursor,
                      "fill_handle": Qt.CrossCursor}.get(zone, Qt.ArrowCursor if zone != "cell" else Qt.CrossCursor)
            if cursor != self._hover_cursor:
                self._hover_cursor = cursor
                self.viewport().setCursor(cursor)
            return
        kind = drag["kind"]
        if kind in ("col_resize", "row_resize"):
            delta = (pos.x() - drag["start"].x()) if kind == "col_resize" else (pos.y() - drag["start"].y())
            size = max(0.0, drag["size"] + delta) / self.zoom
            axis = self.sheet.cols if kind == "col_resize" else self.sheet.rows
            drag["new"] = size
            axis.sizes[drag["index"]] = size                 # aperçu en direct, validé au relâché
            axis.changed()
            self._layout_key = None
            self.viewport().update()
            return
        self._ensure_autoscroll(pos)
        self._drag_to(pos)

    def _drag_to(self, pos):
        drag = self._drag
        if drag is None:
            return
        kind = drag["kind"]
        row, col = self.row_at(pos.y()), self.col_at(pos.x())
        if kind == "cells":
            self.select(row, col, extend=True, keep_scroll=True)
        elif kind == "cols":
            self._select_cols(drag["anchor"], col)
        elif kind == "rows":
            self._select_rows(drag["anchor"], row)
        elif kind == "point":
            self._point_at(row, col, start=False)
        elif kind == "fill":
            r0, c0, r1, c1 = drag["source"]
            down = max(0, row - r1)
            up = max(0, r0 - row)
            right = max(0, col - c1)
            left = max(0, c0 - col)
            if max(down, up) >= max(right, left):
                target = (r0, c0, r1 + down, c1) if down else (r0 - up, c0, r1, c1)
            else:
                target = (r0, c0, r1, c1 + right) if right else (r0, c0 - left, r1, c1)
            drag["target"] = None if target == (r0, c0, r1, c1) else target
            self.viewport().update()

    def _ensure_autoscroll(self, pos):
        vp = self.viewport().rect()
        if not vp.contains(pos.toPoint()):
            if not self._autoscroll.isActive():
                self._autoscroll.start()
        else:
            self._autoscroll.stop()

    def _autoscroll_tick(self):
        if self._drag is None or not (QApplication.mouseButtons() & Qt.LeftButton):
            self._autoscroll.stop()
            return
        pos = self._last_mouse
        vp = self.viewport().rect()
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        if pos.y() > vp.bottom():
            self._update_scrollbars()
            vbar.setMaximum(vbar.maximum() + int(40 * self.zoom))
            vbar.setValue(vbar.value() + int(20 * self.zoom))
        elif pos.y() < self.geo()["hh"]:
            vbar.setValue(vbar.value() - int(20 * self.zoom))
        if pos.x() > vp.right():
            hbar.setMaximum(hbar.maximum() + int(64 * self.zoom))
            hbar.setValue(hbar.value() + int(40 * self.zoom))
        elif pos.x() < self.geo()["hw"]:
            hbar.setValue(hbar.value() - int(40 * self.zoom))
        clamped = QPointF(min(max(pos.x(), self.geo()["hw"] + 1), vp.right() - 1),
                          min(max(pos.y(), self.geo()["hh"] + 1), vp.bottom() - 1))
        self._drag_to(clamped)

    def mouseReleaseEvent(self, event):
        drag = self._drag
        self._drag = None
        self._autoscroll.stop()
        if drag is None:
            super().mouseReleaseEvent(event)
            return
        kind = drag["kind"]
        if kind in ("col_resize", "row_resize") and "new" in drag:
            axis_name = "col" if kind == "col_resize" else "row"
            axis = self.sheet.cols if axis_name == "col" else self.sheet.rows
            axis.sizes[drag["index"]] = drag["size"] / self.zoom          # état d'avant, puis la commande
            axis.changed()
            indices = self._resize_targets(axis_name, drag["index"])
            ops.set_sizes(self.book, self.session.stack, self.sheet, axis_name, indices, drag["new"])
        elif kind == "fill" and drag.get("target"):
            ops.fill(self.book, self.session.stack, self.sheet, drag["source"], drag["target"],
                     copy_only=bool(event.modifiers() & Qt.ControlModifier))
            self.select_range(drag["target"], current=self.view.current)
        elif kind == "point":
            self._editor.setFocus()
        self.viewport().update()
        event.accept()

    def _resize_targets(self, axis, index):
        """Toutes les colonnes / lignes sélectionnées si la séparation tirée en fait partie (Excel)."""
        out = []
        for r0, c0, r1, c1 in (ops.norm(x) for x in self.view.ranges):
            if axis == "col" and r0 == 0 and r1 == R.MAX_ROWS - 1 and c0 <= index <= c1:
                out.extend(range(c0, c1 + 1))
            if axis == "row" and c0 == 0 and c1 == R.MAX_COLS - 1 and r0 <= index <= r1:
                out.extend(range(r0, r1 + 1))
        return sorted(set(out)) or [index]

    def mouseDoubleClickEvent(self, event):
        zone, info = self._zone(event.position())
        if zone in ("col_resize", "row_resize"):
            axis = "col" if zone == "col_resize" else "row"
            size = ops.autofit(self.book, self.sheet, axis, info,
                               lambda text, style: render.text_size(self.book, style, text))
            if size is None:
                size = None if axis == "row" else self.sheet.cols.default
            ops.set_sizes(self.book, self.session.stack, self.sheet, axis, self._resize_targets(axis, info),
                          None if axis == "row" and size is None else max(size or 0, 12))
        elif zone == "fill_handle":
            self._fill_down_to_neighbour()
        elif zone == "cell":
            self.select(*info)
            self.begin_edit(mode="edit")
        event.accept()

    def _fill_down_to_neighbour(self):
        """Double-clic sur la poignée : recopie jusqu'au bas des données de la colonne voisine (Excel)."""
        r0, c0, r1, c1 = self.selection()
        for neighbour in (c0 - 1, c1 + 1):
            if neighbour < 0:
                continue
            last = r1
            while self.sheet.cell(last + 1, neighbour) is not None and last < R.MAX_ROWS - 2:
                last += 1
            if last > r1:
                ops.fill(self.book, self.session.stack, self.sheet, (r0, c0, r1, c1), (r0, c0, last, c1))
                self.select_range((r0, c0, last, c1), current=self.view.current)
                return

    def wheelEvent(self, event):
        mods = event.modifiers()
        delta = event.angleDelta()
        if mods & Qt.ControlModifier and self.extra_zoom == 1.0 and not getattr(self, "embedded", False):
            steps = delta.y() / 120.0
            if steps:
                self.set_zoom(round(self.sheet.zoom * (1.1 ** steps), 2))
            event.accept()
            return
        pixel = event.pixelDelta()
        if not pixel.isNull():
            dx, dy = -pixel.x(), -pixel.y()
        else:
            notches_y = delta.y() / 120.0
            notches_x = delta.x() / 120.0
            row_px = self.sheet.rows.default * self.zoom
            dy = -notches_y * WHEEL_ROWS * row_px
            dx = -notches_x * 64 * self.zoom
            if mods & Qt.ShiftModifier:
                dx, dy = dy, 0
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        if dy > 0 and vbar.value() + dy > vbar.maximum():
            vbar.setMaximum(int(vbar.value() + dy + vbar.pageStep()))
        if dx > 0 and hbar.value() + dx > hbar.maximum():
            hbar.setMaximum(int(hbar.value() + dx + hbar.pageStep()))
        vbar.setValue(int(vbar.value() + dy))
        hbar.setValue(int(hbar.value() + dx))
        event.accept()

    # ------------------------------------------------------------ pointage des références
    def _can_point(self) -> bool:
        if not self.is_editing():
            return False
        text = self._editor.toPlainText()
        if not text.startswith("="):
            return False
        cursor = self._editor.textCursor()
        if self._point is not None:
            return True
        before = text[:cursor.position()].rstrip()
        return bool(before) and before[-1] in "=(,;+-*/^&<>:"

    def _point_at(self, row, col, start):
        """Mode pointage : la référence de la cellule (ou de la plage tirée) est insérée dans la formule."""
        cursor = self._editor.textCursor()
        text = self._editor.toPlainText()
        if start or self._point is None:
            pos = cursor.position()
            if self._point is not None:
                a, b = self._point
                text = text[:a] + text[b:]
                pos = a
            self._point_anchor = (row, col)
            ref = R.cell_name(row, col)
            new = text[:pos] + ref + text[pos:]
            self._point = (pos, pos + len(ref))
        else:
            a, b = self._point
            ar, ac = self._point_anchor
            rect = (min(ar, row), min(ac, col), max(ar, row), max(ac, col))
            ref = R.range_name(*rect)
            new = text[:a] + ref + text[b:]
            self._point = (a, a + len(ref))
        self._editor.blockSignals(True)
        self._editor.setPlainText(new)
        self._editor.blockSignals(False)
        cursor = self._editor.textCursor()
        cursor.setPosition(self._point[1])
        self._editor.setTextCursor(cursor)
        self._place_editor()
        self.editTextChanged.emit(new)
        self.viewport().update()

    def _toggle_absolute(self):
        """F4 : A1 -> $A$1 -> A$1 -> $A1 -> A1 sur la référence sous le curseur."""
        text = self._editor.toPlainText()
        pos = self._editor.textCursor().position()
        for ref in R.iter_refs(text):
            if ref.start <= pos <= ref.end:
                def cycle(p):
                    states = [(False, False), (True, True), (True, False), (False, True)]
                    i = states.index((p.row_abs, p.col_abs))
                    ra, ca = states[(i + 1) % 4]
                    return p.__class__(p.row, p.col, ra if p.row is not None else False,
                                       ca if p.col is not None else False)
                new_ref = ref.__class__(ref.start, ref.end, ref.sheet, cycle(ref.a),
                                        cycle(ref.b) if ref.b is not None else None)
                body = new_ref.text(text[ref.start:ref.end].split("!")[0] if ref.sheet else None)
                new = text[:ref.start] + body + text[ref.end:]
                self._editor.setPlainText(new)
                cursor = self._editor.textCursor()
                cursor.setPosition(ref.start + len(body))
                self._editor.setTextCursor(cursor)
                return

    # ------------------------------------------------------------ clavier de l'éditeur
    def _editor_key(self, event) -> bool:
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if mods & Qt.AltModifier:
                self._editor.insertPlainText("\n")
                return True
            if mods & Qt.ControlModifier:
                self.commit_edit(move=None, whole_selection=True)
                return True
            self.commit_edit(move=(-1, 0) if mods & Qt.ShiftModifier else self._enter_move())
            return True
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            self.commit_edit(move=(0, -1) if key == Qt.Key_Backtab or mods & Qt.ShiftModifier else (0, 1))
            return True
        if key == Qt.Key_Escape:
            self.cancel_edit()
            return True
        if key == Qt.Key_F4:
            self._toggle_absolute()
            return True
        if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right) and self._edit_mode == "enter":
            dr, dc = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}[key]
            if self._can_point():
                base = getattr(self, "_point_cursor", None) if self._point is not None else None
                r, c = base if base else self._editing
                r, c = max(0, r + dr), max(0, c + dc)
                if mods & Qt.ShiftModifier and self._point is not None:
                    self._point_at(r, c, start=False)
                else:
                    self._point_at(r, c, start=True)
                self._point_cursor = (r, c)
                self.ensure_visible(r, c)
                return True
            self.commit_edit(move=(dr, dc))
            return True
        if key == Qt.Key_F2:
            self._edit_mode = "edit" if self._edit_mode == "enter" else "enter"
            return True
        return False

    def _enter_move(self):
        return {"down": (1, 0), "right": (0, 1), "up": (-1, 0), "left": (0, -1), "none": (0, 0)}.get(
            self.enter_moves, (1, 0))

    # ------------------------------------------------------------ clavier de la grille
    _HANDLED_CTRL = {Qt.Key_C, Qt.Key_X, Qt.Key_V, Qt.Key_Z, Qt.Key_Y, Qt.Key_A, Qt.Key_B, Qt.Key_I, Qt.Key_U,
                     Qt.Key_D, Qt.Key_R, Qt.Key_F, Qt.Key_H, Qt.Key_S, Qt.Key_Semicolon, Qt.Key_Plus,
                     Qt.Key_Minus, Qt.Key_Equal, Qt.Key_Space, Qt.Key_Home, Qt.Key_End, Qt.Key_Up, Qt.Key_Down,
                     Qt.Key_Left, Qt.Key_Right, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_QuoteLeft,
                     Qt.Key_Return, Qt.Key_Enter, Qt.Key_1, Qt.Key_5, Qt.Key_9, Qt.Key_0, Qt.Key_T, Qt.Key_L}

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and not self.is_editing():
            key, mods = event.key(), event.modifiers()
            if (mods & Qt.ControlModifier and key in self._HANDLED_CTRL) or (
                    not mods & (Qt.ControlModifier | Qt.AltModifier) and (
                    event.text() and event.text().isprintable() or key in (
                        Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Escape, Qt.Key_F2, Qt.Key_F4, Qt.Key_F9,
                        Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp,
                        Qt.Key_PageDown, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_Space))):
                event.accept()
                return True
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab) \
                and not self.is_editing():
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if self.is_editing():
            self._editor.setFocus()
            self._editor.keyPressEvent(event)
            return
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        view = self.view
        r, c = getattr(self, "_end_point", None) if shift and getattr(self, "_end_point", None) else view.current
        stack = self.session.stack
        arrows = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}
        if key in arrows:
            dr, dc = arrows[key]
            if ctrl:
                if dr:
                    r = data_edge(self.sheet, r, c, dr, 0)
                else:
                    c = data_edge(self.sheet, r, c, 0, dc)
            else:
                m = self.sheet.merge_at(r, c)
                if m and not shift:
                    r = m[2] if dr > 0 else (m[0] if dr < 0 else r)
                    c = m[3] if dc > 0 else (m[1] if dc < 0 else c)
                r = self.sheet.rows.next_visible(r, dr) if dr else r
                c = self.sheet.cols.next_visible(c, dc) if dc else c
            self.select(r, c, extend=shift)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            if ctrl:
                self.begin_edit(mode="edit")
            else:
                self.move_in_selection(*((-1, 0) if shift else self._enter_move()))
        elif key in (Qt.Key_Tab, Qt.Key_Backtab):
            self.move_in_selection(0, -1 if (key == Qt.Key_Backtab or shift) else 1)
        elif key == Qt.Key_Home:
            if ctrl:
                g = self.geo()
                self.select(g["fr"], g["fc"], extend=shift)
            else:
                self.select(r, 0, extend=shift)
        elif key == Qt.Key_End and ctrl:
            used = self.sheet.used_range()
            if used:
                self.select(used[2], used[3], extend=shift)
        elif key in (Qt.Key_PageDown, Qt.Key_PageUp):
            if ctrl:
                self.sheetSwitch.emit(1 if key == Qt.Key_PageDown else -1)
            else:
                g = self.geo()
                page = max(1, int((self.viewport().height() - g["hh"] - g["fh"]) /
                                  (self.sheet.rows.default * self.zoom)) - 1)
                step = page if key == Qt.Key_PageDown else -page
                if mods & Qt.AltModifier:
                    self.select(r, max(0, c + (10 if step > 0 else -10)), extend=shift)
                else:
                    vbar = self.verticalScrollBar()
                    self._update_scrollbars()
                    target = max(0, min(R.MAX_ROWS - 1, r + step))
                    vbar.setMaximum(max(vbar.maximum(), int(vbar.value() + vbar.pageStep())))
                    vbar.setValue(vbar.value() + (vbar.pageStep() if step > 0 else -vbar.pageStep()))
                    self.select(target, c, extend=shift)
        elif key == Qt.Key_Escape:
            if self._copied is not None:
                self.set_copied(None)
            else:
                self.escapeIdle.emit()
        elif key == Qt.Key_F2:
            self.begin_edit(mode="edit")
        elif key == Qt.Key_F9:
            self.book.engine.recalc(force=True) if self.book.engine is not None else None
            self.book.notify("cells", self.sheet)
        elif key in (Qt.Key_Delete,):
            self.clear_selection("contents")
        elif key == Qt.Key_Backspace:
            self.begin_edit("", mode="enter")
        elif ctrl and key == Qt.Key_Space:
            r0, c0, r1, c1 = self.selection()
            self._select_cols(c0, c1)
        elif shift and key == Qt.Key_Space and not ctrl:
            r0, c0, r1, c1 = self.selection()
            self._select_rows(r0, r1)
        elif ctrl and key == Qt.Key_A:
            region = self.current_region()
            if region != self.selection() and region[0] != region[2] or (region[1] != region[3]):
                self.select_range(region, current=view.current)
            else:
                self.select_range((0, 0, R.MAX_ROWS - 1, R.MAX_COLS - 1), current=view.current)
        elif ctrl and key == Qt.Key_C:
            self.copy()
        elif ctrl and key == Qt.Key_X:
            self.copy(cut=True)
        elif ctrl and key == Qt.Key_V:
            self.paste()
        elif ctrl and key == Qt.Key_Z:
            stack.undo()
        elif ctrl and key == Qt.Key_Y or (ctrl and shift and key == Qt.Key_Z):
            stack.redo()
        elif ctrl and key in (Qt.Key_B, Qt.Key_I, Qt.Key_U, Qt.Key_5):
            name = {Qt.Key_B: "bold", Qt.Key_I: "italic", Qt.Key_U: "underline", Qt.Key_5: "strike"}[key]
            self.toggle_style(name)
        elif ctrl and key == Qt.Key_D:
            r0, c0, r1, c1 = self.selection()
            if r1 > r0:
                ops.fill(self.book, stack, self.sheet, (r0, c0, r0, c1), (r0, c0, r1, c1), copy_only=True)
            elif r0 > 0:
                ops.paste_block(self.book, stack, self.sheet, r0, c0,
                                ops.copy_block(self.book, self.sheet, (r0 - 1, c0, r0 - 1, c1)),
                                source_sheet=self.sheet)
        elif ctrl and key == Qt.Key_R:
            r0, c0, r1, c1 = self.selection()
            if c1 > c0:
                ops.fill(self.book, stack, self.sheet, (r0, c0, r1, c0), (r0, c0, r1, c1), copy_only=True)
        elif ctrl and key == Qt.Key_Semicolon:
            today = _dt.date.today()
            if shift:
                now = _dt.datetime.now()
                text = now.strftime("%H:%M")
            else:
                text = today.strftime("%d/%m/%Y" if self.date_order == "dmy" else "%m/%d/%Y")
            ops.set_input(self.book, stack, self.sheet, *view.current, text, self.loc, date_order=self.date_order)
        elif ctrl and key in (Qt.Key_T, Qt.Key_L):
            self.tableRequested.emit()
        elif ctrl and key == Qt.Key_F:
            self.findRequested.emit(False)
        elif ctrl and key == Qt.Key_H:
            self.findRequested.emit(True)
        elif ctrl and key == Qt.Key_S:
            self.saveRequested.emit()
        elif ctrl and key in (Qt.Key_Plus, Qt.Key_Equal) and (shift or key == Qt.Key_Plus):
            self.insert_cells()
        elif ctrl and key == Qt.Key_Minus:
            self.delete_cells()
        elif ctrl and key == Qt.Key_QuoteLeft:
            self.session.show_formulas = not self.session.show_formulas
            self.cache.clear()
            self.viewport().update()
        elif ctrl and key == Qt.Key_9:
            r0, _c0, r1, _c1 = self.selection()
            ops.set_hidden(self.book, stack, self.sheet, "row", range(r0, r1 + 1), not shift)
        elif ctrl and key == Qt.Key_0:
            _r0, c0, _r1, c1 = self.selection()
            ops.set_hidden(self.book, stack, self.sheet, "col", range(c0, c1 + 1), not shift)
        elif event.text() and event.text().isprintable() and not ctrl and not (mods & Qt.AltModifier):
            self.begin_edit(event.text(), mode="enter")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def inputMethodEvent(self, event):
        if not self.is_editing() and event.commitString():
            self.begin_edit(event.commitString(), mode="enter")
            event.accept()
            return
        super().inputMethodEvent(event)

    def current_region(self):
        """Zone de données contiguë autour de la cellule active (Ctrl+A, tri, filtre, graphique)."""
        r, c = self.view.current
        cells = self.sheet.cells
        r0 = r1 = r
        c0 = c1 = c
        grown = True
        while grown:
            grown = False
            if r0 > 0 and any((r0 - 1, x) in cells for x in range(max(0, c0 - 1), c1 + 2)):
                r0 -= 1
                grown = True
            if r1 < R.MAX_ROWS - 1 and any((r1 + 1, x) in cells for x in range(max(0, c0 - 1), c1 + 2)):
                r1 += 1
                grown = True
            if c0 > 0 and any((x, c0 - 1) in cells for x in range(max(0, r0 - 1), r1 + 2)):
                c0 -= 1
                grown = True
            if c1 < R.MAX_COLS - 1 and any((x, c1 + 1) in cells for x in range(max(0, r0 - 1), r1 + 2)):
                c1 += 1
                grown = True
        return r0, c0, r1, c1

    # ------------------------------------------------------------ commandes
    def toggle_style(self, name):
        r, c = self.view.current
        current = bool(self.book.styles.get(self.sheet.style_index(r, c)).get(name))
        self.apply_style({name: None if current else True})

    def apply_style(self, changes, text="Mise en forme"):
        stack = self.session.stack
        stack.begin(text)
        for rect in self.view.ranges:
            ops.apply_style(self.book, stack, self.sheet, rect, changes, text)
        stack.end()

    def clear_selection(self, what="contents"):
        stack = self.session.stack
        stack.begin("Effacer")
        for rect in self.view.ranges:
            target = ops.clip_to_used(self.sheet, rect) if what != "formats" else rect
            if target is not None:
                ops.clear(self.book, stack, self.sheet, target, what)
        stack.end()

    def copy(self, cut=False):
        rect = self.selection()
        block = ops.copy_block(self.book, self.sheet, rect, cut=cut)
        text = ops.block_to_text(self.book, self.sheet, rect, self.loc)
        _CLIP["block"] = (block, self.sheet.uid, self.session)
        _CLIP["text"] = text
        mime = QMimeData()
        mime.setText(text)
        mime.setHtml(_html_table(text))
        QApplication.clipboard().setMimeData(mime)
        self.set_copied(rect)

    def paste(self, mode="all"):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        r, c = self.view.current
        stack = self.session.stack
        own = _CLIP["block"]
        if own is not None and _CLIP["text"] is not None and text == _CLIP["text"]:
            block, uid, session = own
            source = session.book.sheet_by_uid(uid)
            target = self.selection()
            done = ops.paste_block(self.book, stack, self.sheet, r, c, block, mode,
                                   source_sheet=source, target_rect=target)
            if block.cut:
                _CLIP["block"] = None
                self.set_copied(None)
            self.select_range(done, current=(done[0], done[1]))
            return
        if text:
            changes = ops.text_to_cells(self.book, self.sheet, r, c, text, self.loc, self.date_order)
            if changes:
                from .commands import SetCells
                stack.push(SetCells(self.sheet, changes, "Coller"))
                rows = max(k[0] for k in changes)
                cols = max(k[1] for k in changes)
                self.select_range((r, c, rows, cols), current=(r, c))

    def insert_cells(self):
        r0, c0, r1, c1 = self.selection()
        if c0 == 0 and c1 == R.MAX_COLS - 1:
            ops.insert_lines(self.book, self.session.stack, self.sheet, "row", r0, r1 - r0 + 1)
        elif r0 == 0 and r1 == R.MAX_ROWS - 1:
            ops.insert_lines(self.book, self.session.stack, self.sheet, "col", c0, c1 - c0 + 1)
        else:
            ops.insert_lines(self.book, self.session.stack, self.sheet, "row", r0, r1 - r0 + 1)

    def delete_cells(self):
        r0, c0, r1, c1 = self.selection()
        if r0 == 0 and r1 == R.MAX_ROWS - 1 and not (c0 == 0 and c1 == R.MAX_COLS - 1):
            ops.delete_lines(self.book, self.session.stack, self.sheet, "col", c0, c1 - c0 + 1)
        else:
            ops.delete_lines(self.book, self.session.stack, self.sheet, "row", r0, r1 - r0 + 1)


def _html_table(text: str) -> str:
    import html
    rows = [line.split("\t") for line in text.replace("\r\n", "\n").split("\n") if line != ""]
    body = "".join("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f"<table>{body}</table>"


__all__ = ["GridInput", "data_edge", "numfmt"]
