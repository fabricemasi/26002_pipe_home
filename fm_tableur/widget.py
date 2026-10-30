"""Classeur complet (Qt) : ruban, barre de formule, grille, onglets de feuilles, barre d'état, recherche, menus.

UNE classe pour les deux présentations : dans le Board (`compact=True` : ruban réduit, posé dans l'élément) et en
mode Standard (plein cadre). Deux instances peuvent afficher la MÊME session (`session.Session`) : elles lisent et
modifient le même document, la même pile d'annulation, la même navigation."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QColorDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QVBoxLayout, QWidget)

from . import commands as C
from . import numfmt, ops, refs as R
from . import values as V
from .document import valid_sheet_name
from .grid import GridWidget
from .ribbon import Ribbon, menu


class SheetTabs(QWidget):
    """Onglets des feuilles (bas du classeur, comme Excel) : clic = feuille active, double-clic = renommer, clic
    droit = menu, Ctrl + glisser = déplacer (règle de l'appli), « + » = nouvelle feuille."""

    def __init__(self, sw):
        super().__init__(sw)
        self.sw = sw
        self.setFixedHeight(26)
        self.setMouseTracking(True)
        self._rects = []
        self._drag = None
        self._offset = 0

    def sizeHint(self):
        return QSize(400, 26)

    def _layout(self):
        font = QFont(self.font())
        font.setPixelSize(12)
        from PySide6.QtGui import QFontMetrics
        metrics = QFontMetrics(font)
        x = 4 - self._offset
        rects = []
        for sheet in self.sw.book.sheets:
            if sheet.hidden:
                continue
            w = metrics.horizontalAdvance(sheet.name) + 24
            rects.append((sheet, QRectF(x, 0, w, 24)))
            x += w + 1
        self._plus = QRectF(x + 4, 2, 22, 20)
        self._rects = rects
        return font

    def paintEvent(self, _event):
        from settings_store import M
        font = self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(font)
        active = self.sw.session.sheet
        for sheet, rect in self._rects:
            on = sheet is active
            bg = QColor("#ffffff") if on else QColor(M.get("panel_bg", "#2b2d30"))
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect.adjusted(0, 0, 0, 4), 4, 4)
            if sheet.tab_color:
                p.fillRect(QRectF(rect.left() + 3, rect.bottom() - 4, rect.width() - 6, 3), QColor(sheet.tab_color))
            p.setPen(QColor("#107c41") if on else QColor(M.get("text", "#d6d9dc")))
            if on:
                f = QFont(font)
                f.setBold(True)
                p.setFont(f)
            p.drawText(rect, Qt.AlignCenter, sheet.name)
            p.setFont(font)
        p.setPen(QPen(QColor(M.get("text", "#d6d9dc")), 1.4))
        c = self._plus.center()
        p.drawLine(c.x() - 5, c.y(), c.x() + 5, c.y())
        p.drawLine(c.x(), c.y() - 5, c.x(), c.y() + 5)
        if self._drag and self._drag.get("target") is not None:
            p.setPen(QPen(QColor("#107c41"), 2))
            x = self._drag["target_x"]
            p.drawLine(x, 2, x, 22)
        p.end()

    def _sheet_at(self, pos):
        self._layout()
        for sheet, rect in self._rects:
            if rect.contains(pos):
                return sheet
        return None

    def mousePressEvent(self, event):
        pos = event.position()
        if self._plus.contains(pos):
            self.sw.add_sheet()
            return
        sheet = self._sheet_at(pos)
        if sheet is None:
            return
        if event.button() == Qt.RightButton:
            self.sw.set_sheet(sheet)
            self._menu(sheet, event.globalPosition().toPoint())
            return
        from PySide6.QtWidgets import QApplication
        self.sw.set_sheet(sheet)
        if QApplication.keyboardModifiers() & Qt.ControlModifier:     # Ctrl + glisser = déplacer (appli)
            self._drag = {"sheet": sheet, "target": None, "target_x": 0}

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        x = event.position().x()
        index = 0
        tx = 4
        for i, (_sheet, rect) in enumerate(self._rects):
            if x > rect.center().x():
                index = i + 1
                tx = rect.right() + 1
            elif i == 0:
                tx = rect.left()
        self._drag["target"] = index
        self._drag["target_x"] = tx
        self.update()

    def mouseReleaseEvent(self, event):
        drag = self._drag
        self._drag = None
        if drag and drag.get("target") is not None:
            visible = [s for s, _r in self._rects]
            target = drag["target"]
            current = visible.index(drag["sheet"])
            if target > current:
                target -= 1
            if target != current:
                ops.move_sheet(self.sw.book, self.sw.session.stack, drag["sheet"],
                               self.sw.book.index_of(visible[target]))
        self.update()

    def mouseDoubleClickEvent(self, event):
        sheet = self._sheet_at(event.position())
        if sheet is not None:
            self.sw.rename_sheet(sheet)

    def wheelEvent(self, event):
        self._offset = max(0, self._offset - event.angleDelta().y() // 4)
        self.update()

    def _menu(self, sheet, pos):
        sw = self.sw
        m = menu(self, "feuilles")
        m.addAction("Insérer une feuille").triggered.connect(sw.add_sheet)
        m.addAction("Renommer…").triggered.connect(lambda: sw.rename_sheet(sheet))
        m.addAction("Dupliquer").triggered.connect(lambda: sw.duplicate_sheet(sheet))
        m.addAction("Supprimer").triggered.connect(lambda: sw.remove_sheet(sheet))
        m.addSeparator()
        m.addAction("Couleur d'onglet…").triggered.connect(lambda: sw.tab_color(sheet))
        m.addAction("Masquer").triggered.connect(lambda: sw.hide_sheet(sheet, True))
        hidden = [s for s in sw.book.sheets if s.hidden]
        if hidden:
            m.addAction("Afficher…").triggered.connect(sw.unhide_sheet)
        m.addAction("Protéger / ôter la protection").triggered.connect(lambda: sw.toggle_protect(sheet))
        m.popup(pos)


class FindBar(QWidget):
    def __init__(self, sw):
        super().__init__(sw)
        self.sw = sw
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(4)
        self.needle = QLineEdit(self)
        self.needle.setPlaceholderText("Rechercher")
        self.repl = QLineEdit(self)
        self.repl.setPlaceholderText("Remplacer par")
        from .ribbon import _button
        self.info = QLabel("", self)
        row.addWidget(self.needle, 2)
        row.addWidget(_button("Suivant", "Entrée", self.find_next, self))
        row.addWidget(self.repl, 2)
        row.addWidget(_button("Remplacer tout", "Dans la feuille active", self.replace_all, self))
        row.addWidget(self.info, 1)
        row.addWidget(_button("✕", "Fermer (Échap)", self.close_bar, self, 26))
        self.needle.returnPressed.connect(self.find_next)
        self._results = []
        self._index = -1
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(event)

    def close_bar(self):
        self.hide()
        self.sw.grid.setFocus()

    def find_next(self):
        sw = self.sw
        text = self.needle.text()
        self._results = ops.find_all(sw.book, [sw.grid.sheet], text, loc=sw.grid.loc)
        if not self._results:
            self.info.setText("Aucun résultat")
            return
        cur = sw.grid.view.current
        after = [i for i, (_s, r, c) in enumerate(self._results) if (r, c) > cur]
        self._index = after[0] if after else 0
        _sheet, r, c = self._results[self._index]
        sw.grid.select(r, c)
        self.info.setText(f"{self._index + 1} / {len(self._results)}")

    def replace_all(self):
        sw = self.sw
        count = ops.replace_all(sw.book, sw.session.stack, [sw.grid.sheet], self.needle.text(), self.repl.text(),
                                loc=sw.grid.loc)
        self.info.setText(f"{count} remplacement(s)")


class SpreadsheetWidget(QWidget):
    standardRequested = Signal()             # « Mode Standard » (depuis le Board)
    boardRequested = Signal()                # « Retour au Board » (depuis le mode Standard)
    saveRequested = Signal()
    leaveRequested = Signal()                # Échap sans rien à annuler (Board : sortir de l'édition)
    message = Signal(str)

    def __init__(self, session, settings: dict | None = None, parent=None, compact: bool = False):
        super().__init__(parent)
        self.session = session
        self.compact = compact
        self.settings = dict(settings or {})
        self.setObjectName("TableurWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.grid = GridWidget(session, self, self.settings)
        self.ribbon = Ribbon(self, self, compact=compact)
        layout.addWidget(self.ribbon)
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(4)
        self.name_box = QLineEdit(self)
        self.name_box.setFixedWidth(96)
        self.name_box.setToolTip("Adresse de la cellule active ; tapez une adresse (B12, A1:C4, Feuil2!A1) ou "
                                 "un nom défini puis Entrée")
        self.name_box.returnPressed.connect(self._goto_name_box)
        fx = QLabel("fx", self)
        fx.setFixedWidth(18)
        fx.setAlignment(Qt.AlignCenter)
        self.formula = QLineEdit(self)
        self.formula.setToolTip("Contenu réel de la cellule (formule ou valeur saisie)")
        self.formula.textEdited.connect(self._formula_edited)
        self.formula.returnPressed.connect(self._formula_enter)
        self.formula.installEventFilter(self)
        bar.addWidget(self.name_box)
        bar.addWidget(fx)
        bar.addWidget(self.formula, 1)
        layout.addLayout(bar)
        self.find_bar = FindBar(self)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.grid, 1)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(2, 0, 4, 0)
        bottom.setSpacing(6)
        self.tabs = SheetTabs(self)
        self.status = QLabel("", self)
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.tabs, 3)
        bottom.addWidget(self.status, 2)
        layout.addLayout(bottom)
        self.grid.currentChanged.connect(self._sync)
        self.grid.editTextChanged.connect(self._grid_text)
        self.grid.editingChanged.connect(lambda _on: self._sync())
        self.grid.message.connect(self._message)
        self.grid.escapeIdle.connect(self.leaveRequested)
        self.grid.saveRequested.connect(self.saveRequested)
        self.grid.findRequested.connect(self.show_find)
        self.grid.contextMenuWanted.connect(self._context_menu)
        self.grid.sheetSwitch.connect(self._switch_sheet)
        self.grid.validate = self._validate
        self.grid.filterMenuWanted.connect(self._filter_menu)
        self.grid.dropdownWanted.connect(self._dropdown_menu)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(60)
        self._status_timer.timeout.connect(self._update_status)
        self._listener = self._on_book_event
        session.book.listeners.append(self._listener)
        from .charts import ChartLayer
        self.charts = ChartLayer(self.grid)
        self._sync()

    # -- propriétés --
    @property
    def book(self):
        return self.session.book

    @property
    def stack(self):
        return self.session.stack

    def detach(self):
        self.grid.detach()
        self.charts.detach()
        if self._listener in self.book.listeners:
            self.book.listeners.remove(self._listener)

    def apply_settings(self, settings):
        self.settings = dict(settings or {})
        self.grid.apply_settings(self.settings)

    def _on_book_event(self, kind, sheet):
        if kind in ("sheets", "active"):
            self.tabs.update()
        self._status_timer.start()

    # -- synchronisation --
    def _sync(self):
        grid = self.grid
        r, c = grid.view.current
        r0, c0, r1, c1 = grid.selection()
        if (r0, c0) == (r1, c1):
            self.name_box.setText(R.cell_name(r, c))
        else:
            self.name_box.setText(f"{r1 - r0 + 1}L x {c1 - c0 + 1}C" if grid._drag else R.cell_name(r, c))
        if not grid.is_editing() and not self.formula.hasFocus():
            cell = grid.sheet.cell(r, c)
            hidden = cell is not None and cell.formula and self.current_style().get("hidden_formula") and \
                grid.sheet.protected
            self.formula.setText("" if hidden else grid.current_input_text())
        self.ribbon.sync(self.current_style(), self.book)
        self._status_timer.start()
        self.tabs.update()

    def current_style(self) -> dict:
        r, c = self.grid.view.current
        return self.book.style_of(self.grid.sheet, r, c)

    def _grid_text(self, text):
        if self.formula.text() != text:
            self.formula.setText(text)

    def _formula_edited(self, text):
        self.grid.set_edit_text(text)

    def _formula_enter(self):
        if self.grid.is_editing():
            self.grid.set_edit_text(self.formula.text())
            self.grid.commit_edit()
        self.grid.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.formula and event.type() == event.Type.KeyPress and event.key() == Qt.Key_Escape:
            self.grid.cancel_edit()
            self._sync()
            self.grid.setFocus()
            return True
        if obj is self.formula and event.type() == event.Type.FocusIn and not self.grid.is_editing():
            self.grid.begin_edit(mode="edit", focus=False)
        return super().eventFilter(obj, event)

    def _message(self, text):
        self.status.setText(text)
        self.message.emit(text)

    def _update_status(self):
        """Somme / moyenne / nombre de la sélection (barre d'état d'Excel) ; plages énormes : cellules existantes."""
        grid = self.grid
        total = 0.0
        count = numbers = 0
        for rect in grid.view.ranges:
            for _key, _cell in ops.cells_in(grid.sheet, rect):
                value = ops.cell_value(self.book, grid.sheet, *_key)
                if value is None:
                    continue
                count += 1
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    total += value
                    numbers += 1
        engine = self.book.engine
        parts = []
        if count > 1:
            loc = grid.loc
            if numbers:
                parts.append("Somme : " + numfmt.format_value(total, "#,##0.##########", loc)[0].rstrip(loc.decimal))
                parts.append("Moyenne : " + numfmt.general(total / numbers, loc))
            parts.append(f"Nombre : {count}")
        if engine is not None and not engine.available:
            parts.append("⚠ moteur de calcul absent : formules non recalculées")
        elif engine is not None and engine.error:
            parts.append("⚠ " + engine.error)
        if self.book.calc_mode == "manual":
            parts.append("Calcul manuel (F9)")
        self.status.setText("   ".join(parts))

    # -- feuilles --
    def set_sheet(self, sheet):
        if self.grid.is_editing():
            self.grid.commit_edit(move=None)
        self.grid._save_view()
        self.session.set_active(sheet)
        self.grid.setFocus()
        self._sync()

    def _switch_sheet(self, step):
        visible = [s for s in self.book.sheets if not s.hidden]
        if self.grid.sheet in visible:
            index = (visible.index(self.grid.sheet) + step) % len(visible)
            self.set_sheet(visible[index])

    def add_sheet(self):
        sheet = ops.add_sheet(self.book, self.stack, self.book.index_of(self.grid.sheet) + 1)
        self.set_sheet(sheet)

    def duplicate_sheet(self, sheet):
        self.set_sheet(ops.duplicate_sheet(self.book, self.stack, sheet))

    def remove_sheet(self, sheet):
        if len([s for s in self.book.sheets if not s.hidden]) <= 1:
            self._message("Un classeur garde au moins une feuille visible.")
            return
        box = QMessageBox(QMessageBox.Warning, "Supprimer la feuille",
                          f"Supprimer « {sheet.name} » ? (Ctrl+Z pour annuler)", parent=self)
        yes = box.addButton("Supprimer", QMessageBox.DestructiveRole)
        box.addButton("Annuler", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        index = self.book.index_of(sheet)
        ops.remove_sheet(self.book, self.stack, sheet)
        self.set_sheet(self.book.sheets[max(0, min(index, len(self.book.sheets) - 1))])

    def rename_sheet(self, sheet):
        name, ok = QInputDialog.getText(self, "Renommer la feuille", "Nom :", text=sheet.name)
        if not ok or name.strip() == sheet.name:
            return
        problem = valid_sheet_name(name, self.book, sheet)
        if problem:
            self._message(problem)
            return
        ops.rename_sheet(self.book, self.stack, sheet, name)
        self.tabs.update()

    def tab_color(self, sheet):
        color = QColorDialog.getColor(QColor(sheet.tab_color or "#107c41"), self, "Couleur d'onglet")
        if color.isValid():
            ops.set_sheet_attr(self.book, self.stack, sheet, "Couleur d'onglet", tab_color=color.name())

    def hide_sheet(self, sheet, hidden):
        if hidden and len([s for s in self.book.sheets if not s.hidden]) <= 1:
            return
        ops.set_sheet_attr(self.book, self.stack, sheet, "Masquer la feuille", hidden=hidden)
        if hidden:
            visible = [s for s in self.book.sheets if not s.hidden]
            self.set_sheet(visible[0])

    def unhide_sheet(self):
        hidden = [s.name for s in self.book.sheets if s.hidden]
        name, ok = QInputDialog.getItem(self, "Afficher une feuille", "Feuille :", hidden, 0, False)
        if ok:
            sheet = self.book.sheet(name)
            ops.set_sheet_attr(self.book, self.stack, sheet, "Afficher la feuille", hidden=False)
            self.set_sheet(sheet)

    def toggle_protect(self, sheet):
        ops.set_sheet_attr(self.book, self.stack, sheet, "Protection", protected=not sheet.protected)
        self._message("Feuille protégée (cellules verrouillées non modifiables)" if sheet.protected
                      else "Protection ôtée")

    # -- commandes du ruban --
    def undo(self):
        self.stack.undo()

    def redo(self):
        self.stack.redo()

    def toggle_align(self, key, value):
        current = self.current_style().get(key)
        self.grid.apply_style({key: None if current == value else value})

    def change_decimals(self, delta):
        code = self.current_style().get("fmt") or numfmt.GENERAL
        self.grid.apply_style({"fmt": numfmt.change_decimals(code, delta)})

    def ask_font_size(self):
        size, ok = QInputDialog.getDouble(self, "Taille du texte", "Points :", 11, 1, 409, 1)
        if ok:
            self.grid.apply_style({"size": size})

    def pick_color(self, key):
        color = QColorDialog.getColor(QColor(self.current_style().get(key) or "#000000"), self, "Couleur")
        if color.isValid():
            self.grid.apply_style({key: color.name()})

    def set_borders(self, kind):
        self.stack.begin("Bordures")
        for rect in self.grid.view.ranges:
            ops.set_borders(self.book, self.stack, self.grid.sheet, rect, kind)
        self.stack.end()

    def merge(self, center=False, across=False):
        ops.merge(self.book, self.stack, self.grid.sheet, self.grid.selection(), across=across, center=center)

    def unmerge(self):
        ops.unmerge(self.book, self.stack, self.grid.sheet, self.grid.selection())

    def ask_number_format(self):
        code, ok = QInputDialog.getText(self, "Format personnalisé",
                                        "Code de format (comme Excel : 0.00, #,##0 \"€\", dd/mm/yyyy, 0%…) :",
                                        text=self.current_style().get("fmt") or numfmt.GENERAL)
        if ok and code.strip():
            self.grid.apply_style({"fmt": code.strip()})

    def add_cond_rule(self, rule, ask=False):
        if ask:
            label = {"cell": "Valeur", "text": "Texte", "formula": "Formule (pour la cellule en haut à gauche)"}[
                rule["type"]]
            value, ok = QInputDialog.getText(self, "Mise en forme conditionnelle", label + " :")
            if not ok or not value.strip():
                return
            if rule["type"] == "formula":
                rule["formula"] = value if value.startswith("=") else "=" + value
            else:
                rule["value"] = value
        if rule["type"] not in ("bar", "scale"):
            rule.setdefault("style", {"fill": "#ffc7ce", "color": "#9c0006"})
        rule["ranges"] = [ops.norm(r) for r in self.grid.view.ranges]
        ops_rule = dict(rule)
        self.stack.push(C.SheetState(self.grid.sheet, lambda s: s.cond_formats.append(ops_rule),
                                     "Mise en forme conditionnelle", kind="cells"))

    def clear_cond_rules(self):
        sel = self.grid.selection()

        def mutate(s):
            s.cond_formats = [r for r in s.cond_formats if not any(
                not (x[2] < sel[0] or x[0] > sel[2] or x[3] < sel[1] or x[1] > sel[3]) for x in r.get("ranges", []))]
        self.stack.push(C.SheetState(self.grid.sheet, mutate, "Effacer les règles", kind="cells"))

    def insert_lines(self, axis):
        r0, c0, r1, c1 = self.grid.selection()
        at, count = (r0, r1 - r0 + 1) if axis == "row" else (c0, c1 - c0 + 1)
        ops.insert_lines(self.book, self.stack, self.grid.sheet, axis, at, count)

    def delete_lines(self, axis):
        r0, c0, r1, c1 = self.grid.selection()
        at, count = (r0, r1 - r0 + 1) if axis == "row" else (c0, c1 - c0 + 1)
        ops.delete_lines(self.book, self.stack, self.grid.sheet, axis, at, count)

    def ask_size(self, axis):
        r0, c0, r1, c1 = self.grid.selection()
        target = self.grid.sheet.rows if axis == "row" else self.grid.sheet.cols
        first = r0 if axis == "row" else c0
        value, ok = QInputDialog.getDouble(self, "Taille", "Pixels (à 100 %) :", target.raw_size(first), 0, 2000, 0)
        if ok:
            indices = range(r0, r1 + 1) if axis == "row" else range(c0, c1 + 1)
            ops.set_sizes(self.book, self.stack, self.grid.sheet, axis, list(indices)[:20000], value)

    def hide_lines(self, axis, hidden):
        r0, c0, r1, c1 = self.grid.selection()
        indices = range(r0, r1 + 1) if axis == "row" else range(c0, c1 + 1)
        if hidden is False and len(indices) == 1:                     # afficher : les voisines masquées aussi
            axis_obj = self.grid.sheet.rows if axis == "row" else self.grid.sheet.cols
            lo, hi = indices[0], indices[0]
            while lo - 1 in axis_obj.hidden:
                lo -= 1
            while hi + 1 in axis_obj.hidden:
                hi += 1
            indices = range(lo, hi + 1)
        ops.set_hidden(self.book, self.stack, self.grid.sheet, axis, list(indices)[:100000], hidden)

    def edit_comment(self):
        r, c = self.grid.view.current
        sheet = self.grid.sheet
        text, ok = QInputDialog.getMultiLineText(self, "Commentaire", f"Note sur {R.cell_name(r, c)} :",
                                                 sheet.comments.get((r, c), ""))
        if not ok:
            return

        def mutate(s):
            if text.strip():
                s.comments[(r, c)] = text
            else:
                s.comments.pop((r, c), None)
        self.stack.push(C.SheetState(sheet, mutate, "Commentaire", kind="cells"))

    def insert_function(self):
        from .functions import catalog
        names = [f"{name} — {desc}" if desc else name for name, desc in catalog()]
        item, ok = QInputDialog.getItem(self, "Insérer une fonction", "Fonction :", names, 0, True)
        if not ok or not item:
            return
        name = item.split(" — ")[0].strip().upper()
        self.grid.begin_edit(f"={name}(", mode="enter")

    def auto_function(self, fn):
        """Σ : fonction sur la plage de nombres au-dessus (ou à gauche) de la cellule active, comme Excel."""
        grid = self.grid
        r0, c0, r1, c1 = grid.selection()
        sheet = grid.sheet
        if (r0, c0) != (r1, c1):
            target_row = r1 + 1
            changes = {}
            for c in range(c0, c1 + 1):
                changes[(target_row, c)] = ops.input_cell(self.book, sheet, target_row, c,
                                                          f"={fn}({R.range_name(r0, c, r1, c)})", grid.loc)
            self.stack.push(C.SetCells(sheet, changes, "Somme automatique"))
            return
        r, c = r0, c0
        top = r - 1
        while top >= 0 and isinstance(ops.cell_value(self.book, sheet, top, c), (int, float)):
            top -= 1
        if top < r - 1:
            text = f"={fn}({R.range_name(top + 1, c, r - 1, c)})"
        else:
            left = c - 1
            while left >= 0 and isinstance(ops.cell_value(self.book, sheet, r, left), (int, float)):
                left -= 1
            text = f"={fn}({R.range_name(r, left + 1, r, c - 1)})" if left < c - 1 else f"={fn}()"
        grid.begin_edit(text, mode="enter")

    def edit_names(self):
        current = "\n".join(f"{k} = {v}" for k, v in sorted(self.book.names.items()))
        text, ok = QInputDialog.getMultiLineText(
            self, "Noms définis", "Un nom par ligne : Nom = Feuil1!$A$1:$A$10 (vide = supprimé)", current)
        if not ok:
            return
        names = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key and value and R.parse_cell(key) is None:
                    names[key] = value
        self.stack.push(C.Names(names))

    def toggle_formulas(self):
        self.session.show_formulas = not self.session.show_formulas
        self.grid.cache.clear()
        self.grid.viewport().update()

    def recalc(self):
        if self.book.engine is not None:
            self.book.engine.recalc(force=True)
        self.book.notify("cells", self.grid.sheet)

    def toggle_calc_mode(self):
        self.book.calc_mode = "manual" if self.book.calc_mode == "auto" else "auto"
        if self.book.calc_mode == "auto":
            self.recalc()
        self.book.notify("cells", self.grid.sheet)
        self._sync()

    def _sort_area(self):
        r0, c0, r1, c1 = self.grid.selection()
        if (r0, c0) == (r1, c1) or (r0 == 0 and r1 == R.MAX_ROWS - 1):
            return self.grid.current_region(), True
        return (r0, c0, r1, c1), False

    def sort(self, ascending):
        area, header = self._sort_area()
        col = self.grid.view.current[1]
        header = header and self._looks_like_header(area)
        ops.sort_range(self.book, self.stack, self.grid.sheet, area, [(col, ascending)], header=header)

    def _looks_like_header(self, area):
        r0, c0, _r1, c1 = area
        first = [ops.cell_value(self.book, self.grid.sheet, r0, c) for c in range(c0, c1 + 1)]
        second = [ops.cell_value(self.book, self.grid.sheet, r0 + 1, c) for c in range(c0, c1 + 1)]
        return all(isinstance(v, str) for v in first if v is not None) and any(
            isinstance(v, (int, float)) for v in second)

    def custom_sort(self):
        area, _header = self._sort_area()
        text, ok = QInputDialog.getText(
            self, "Tri personnalisé", "Colonnes, dans l'ordre (ex. « B, C- » : B croissant puis C décroissant) :",
            text=R.col_name(self.grid.view.current[1]))
        if not ok:
            return
        keys = []
        for part in text.replace(";", ",").split(","):
            part = part.strip().upper()
            if not part:
                continue
            desc = part.endswith("-")
            col = R.col_index(part.rstrip("-+").strip())
            if col >= 0:
                keys.append((col, not desc))
        if keys:
            ops.sort_range(self.book, self.stack, self.grid.sheet, area, keys,
                           header=self._looks_like_header(area))

    def toggle_filter(self):
        sheet = self.grid.sheet
        if sheet.autofilter is not None:
            ops.set_autofilter(self.book, self.stack, sheet, None)
        else:
            area, _h = self._sort_area()
            ops.set_autofilter(self.book, self.stack, sheet, area)

    def _filter_menu(self, col, pos):
        from settings_menu import menu_row
        from PySide6.QtWidgets import QCheckBox, QScrollArea
        sheet = self.grid.sheet
        values = ops.filter_values(self.book, sheet, col)
        current = sheet.filters.get(col, {}).get("values")
        m = menu(self, "filtre")
        m.addAction("Trier A → Z").triggered.connect(
            lambda: ops.sort_range(self.book, self.stack, sheet, sheet.autofilter, [(col, True)], header=True))
        m.addAction("Trier Z → A").triggered.connect(
            lambda: ops.sort_range(self.book, self.stack, sheet, sheet.autofilter, [(col, False)], header=True))
        m.addAction("Effacer le filtre de cette colonne").triggered.connect(
            lambda: ops.apply_filter(self.book, self.stack, sheet, col, None))
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 2, 4, 2)
        checks = []
        for value in values[:2000]:
            check = QCheckBox(value or "(vides)", box)
            check.setChecked(current is None or value in current)
            check.value = value
            lay.addWidget(check)
            checks.append(check)
        scroll = QScrollArea()
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)
        scroll.setFixedSize(220, min(260, 24 * len(checks) + 8))
        menu_row(m, "", scroll)
        m.addAction("Appliquer").triggered.connect(lambda: ops.apply_filter(
            self.book, self.stack, sheet, col, {c.value for c in checks if c.isChecked()}
            if not all(c.isChecked() for c in checks) else None))
        m.popup(pos)

    def ask_validation(self):
        text, ok = QInputDialog.getText(self, "Liste déroulante",
                                        "Valeurs permises, séparées par des points-virgules (vide = retirer) :")
        if not ok:
            return
        rects = [ops.norm(r) for r in self.grid.view.ranges]
        items = [v.strip() for v in text.split(";") if v.strip()]

        def mutate(s):
            s.validations = [v for v in s.validations if v.get("ranges") != rects]
            if items:
                s.validations.append({"type": "list", "values": items, "ranges": rects})
        self.stack.push(C.SheetState(self.grid.sheet, mutate, "Validation", kind="cells"))

    def validation_at(self, r, c):
        for rule in self.grid.sheet.validations:
            if any(x[0] <= r <= x[2] and x[1] <= c <= x[3] for x in rule.get("ranges", [])):
                return rule
        return None

    def _validate(self, r, c, text):
        rule = self.validation_at(r, c)
        if rule and rule.get("type") == "list" and text and not text.startswith("="):
            allowed = {str(v).casefold() for v in rule.get("values", [])}
            if text.strip().casefold() not in allowed:
                return "Valeur non permise (liste : " + "; ".join(rule.get("values", [])[:10]) + ")"
        return None

    def _dropdown_menu(self, r, c, pos):
        rule = self.validation_at(r, c)
        if not rule or rule.get("type") != "list":
            return
        m = menu(self, "liste")
        for value in rule.get("values", [])[:500]:
            m.addAction(str(value)).triggered.connect(lambda _c=False, v=value: ops.set_input(
                self.book, self.stack, self.grid.sheet, r, c, str(v), self.grid.loc))
        m.popup(pos)

    def remove_duplicates(self):
        area, _h = self._sort_area()
        header = self._looks_like_header(area)
        n = ops.remove_duplicates(self.book, self.stack, self.grid.sheet, area,
                                  list(range(area[1], area[3] + 1)), header=header)
        self._message(f"{n} ligne(s) en double supprimée(s)")

    def text_to_columns(self):
        sep, ok = QInputDialog.getText(self, "Convertir", "Séparateur :", text=";")
        if ok and sep:
            ops.text_to_columns(self.book, self.stack, self.grid.sheet, self.grid.selection(), sep, self.grid.loc)

    def freeze(self, how):
        r, c = self.grid.view.current
        value = {"cell": (r, c), "row": (1, 0), "col": (0, 1), None: (0, 0)}[how]
        ops.set_sheet_attr(self.book, self.stack, self.grid.sheet, "Figer les volets", freeze=value)

    def toggle_grid_lines(self):
        sheet = self.grid.sheet
        ops.set_sheet_attr(self.book, self.stack, sheet, "Quadrillage", show_grid=not sheet.show_grid)

    def show_find(self, replace=False):
        self.find_bar.show()
        self.find_bar.repl.setVisible(True)
        self.find_bar.needle.setFocus()
        self.find_bar.needle.selectAll()

    # -- graphiques --
    def insert_chart(self, kind):
        self.charts.insert(kind, self.grid.selection() if self.grid.selection()[0] != self.grid.selection()[2]
                           else self.grid.current_region())

    # -- fichiers --
    def import_file(self):
        from . import io_files
        path, _f = QFileDialog.getOpenFileName(self, "Importer", "", io_files.OPEN_FILTER)
        if path:
            io_files.import_into(self, path)

    def export_file(self):
        from . import io_files
        path, chosen = QFileDialog.getSaveFileName(self, "Exporter", "", io_files.SAVE_FILTER)
        if path:
            io_files.export_to(self, path, chosen)

    # -- menu contextuel --
    def _context_menu(self, pos: QPoint, kind: str):
        grid = self.grid
        m = menu(self, "cellules")
        m.addAction("Couper").triggered.connect(lambda: grid.copy(cut=True))
        m.addAction("Copier").triggered.connect(grid.copy)
        m.addAction("Coller").triggered.connect(lambda: grid.paste())
        special = m.addMenu("Collage spécial")
        for text, mode in (("Valeurs", "values"), ("Formules", "formulas"), ("Mise en forme", "formats")):
            special.addAction(text).triggered.connect(lambda _c=False, md=mode: grid.paste(md))
        m.addSeparator()
        if kind == "rows":
            m.addAction("Insérer des lignes").triggered.connect(lambda: self.insert_lines("row"))
            m.addAction("Supprimer les lignes").triggered.connect(lambda: self.delete_lines("row"))
            m.addAction("Hauteur de ligne…").triggered.connect(lambda: self.ask_size("row"))
            m.addAction("Masquer").triggered.connect(lambda: self.hide_lines("row", True))
            m.addAction("Afficher").triggered.connect(lambda: self.hide_lines("row", False))
        elif kind == "cols":
            m.addAction("Insérer des colonnes").triggered.connect(lambda: self.insert_lines("col"))
            m.addAction("Supprimer les colonnes").triggered.connect(lambda: self.delete_lines("col"))
            m.addAction("Largeur de colonne…").triggered.connect(lambda: self.ask_size("col"))
            m.addAction("Masquer").triggered.connect(lambda: self.hide_lines("col", True))
            m.addAction("Afficher").triggered.connect(lambda: self.hide_lines("col", False))
        else:
            m.addAction("Insérer des lignes").triggered.connect(lambda: self.insert_lines("row"))
            m.addAction("Insérer des colonnes").triggered.connect(lambda: self.insert_lines("col"))
            m.addAction("Supprimer les lignes").triggered.connect(lambda: self.delete_lines("row"))
            m.addAction("Supprimer les colonnes").triggered.connect(lambda: self.delete_lines("col"))
        m.addAction("Effacer le contenu").triggered.connect(lambda: grid.clear_selection("contents"))
        m.addSeparator()
        sort = m.addMenu("Trier")
        sort.addAction("Trier A → Z").triggered.connect(lambda: self.sort(True))
        sort.addAction("Trier Z → A").triggered.connect(lambda: self.sort(False))
        m.addAction("Filtrer").triggered.connect(self.toggle_filter)
        m.addSeparator()
        m.addAction("Commentaire…").triggered.connect(self.edit_comment)
        m.addAction("Format de nombre…").triggered.connect(self.ask_number_format)
        m.addAction("Liste déroulante…").triggered.connect(self.ask_validation)
        m.popup(pos)

    def _goto_name_box(self):
        text = self.name_box.text().strip()
        target = self.book.names.get(text) or next((v for k, v in self.book.names.items()
                                                    if k.lower() == text.lower()), None)
        parsed = R.parse_range(target or text)
        if parsed is None:
            self._message(f"Adresse inconnue : {text}")
            return
        sheet_name, rect = parsed
        if sheet_name:
            sheet = self.book.sheet(sheet_name)
            if sheet is None:
                self._message(f"Feuille inconnue : {sheet_name}")
                return
            self.set_sheet(sheet)
        self.grid.select_range(rect)
        self.grid.setFocus()

    def focus_grid(self):
        self.grid.setFocus()


__all__ = ["SpreadsheetWidget", "SheetTabs", "V"]
