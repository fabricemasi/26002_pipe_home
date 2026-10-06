"""Moteur de tableaux A CELLULES des fenetres de reglages (utilise par settings_window_v2).

Generique : ne depend d'aucun reglage propre a l'appli (comme settings_layout/
settings_widgets, a copier tel quel dans une nouvelle appli).

- `_Cell` : une cellule de ligne. Clic droit = justification horizontale
  (gauche/centre/droite) et verticale (haut/centre/bas), conservee dans les
  dimensions du tableau (`table_dims`, voir `_CellsState`).
- `SplitCell` : une cellule DIVISEE en sous-cellules (legende en entete + filets
  verticaux), dont les bordures se tirent a la souris.
- `build_cells_table` : tableau a entete (`_ResizableTableHeader`) dont CHAQUE
  bordure de colonne se saisit aussi sur les cellules des lignes (`_CellEdgeDrag`),
  pas seulement sur l'entete.
- `attach_range_menu` : clic droit sur un curseur = modifier sa plage (min/max).
- `normalize_toggles` : tous les interrupteurs d'un tableau sont de type 2, sans texte.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QSpinBox, QVBoxLayout, QWidget,
)

from settings_layout import (
    _ReorderOverlay,
    _TABLE_HEAD, _lock_min_height, _prestyle_flat_frame, _prestyle_flat_row, _register_cells_table,
    _ResizableTableHeader, _reflow_ancestors, _table_row, _wire_resizable_columns,
)
from settings_store import M
from settings_theme import _set_text_role
from settings_widgets import _TABLE_INNER_BORDER, _Toggle, _table_frame

_H = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
_V = {"top": Qt.AlignTop, "center": Qt.AlignVCenter, "bottom": Qt.AlignBottom}
_H_LABELS = (("left", "Gauche"), ("center", "Centre"), ("right", "Droite"))
_V_LABELS = (("top", "Haut"), ("center", "Centre"), ("bottom", "Bas"))


def _vline_color() -> QColor:
    return QColor(_TABLE_INNER_BORDER["v"]["color"] or M["panel_border"])


# ==========================================================================
# Cellule + justification
# ==========================================================================

def add_align_menus(menu: QMenu, h: str, v: str, set_h: Callable, set_v: Callable):
    """Ajoute au menu les deux sous-menus de justification (horizontale, verticale)."""
    for title, choices, current, setter in (
        ("Justification horizontale", _H_LABELS, h, set_h),
        ("Justification verticale", _V_LABELS, v, set_v),
    ):
        sub = QMenu(title, menu)          # parente explicitement : le sous-menu doit survivre a l'appelant
        menu.addMenu(sub)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for key, label in choices:
            action = sub.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == current)
            group.addAction(action)
            action.triggered.connect(lambda _c=False, k=key, f=setter: f(k))


class _Cell(QWidget):
    """Cellule d'une ligne (objectName "TableCell" : les filets verticaux de
    `_TableRow` se peignent a sa position). Contient UN widget, justifie dans la
    cellule ; un contenu qui sait se justifier lui-meme (`setCellAlign`, voir
    SplitCell) recoit la justification a la place."""

    alignChanged = Signal()

    def __init__(self, content: QWidget, h: str = "left", v: str = "center", parent=None):
        super().__init__(parent)
        self.setObjectName("TableCell")
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        self._h, self._v = h, v
        self._content = content
        layout = QHBoxLayout(self)
        # Une cellule divisee n'a AUCUN padding : son contenu est colle aux bordures de la cellule.
        fill = bool(getattr(content, "_fill_cell", False))
        layout.setContentsMargins(*((0, 0, 0, 0) if fill else (14, 8, 14, 8)))
        layout.setSpacing(0)
        layout.addWidget(content)
        self._apply()

    def content(self) -> QWidget:
        return self._content

    def align(self) -> tuple[str, str]:
        return self._h, self._v

    def setAlign(self, h: str, v: str, notify: bool = True):
        if (h, v) == (self._h, self._v):
            return
        self._h, self._v = h, v
        self._apply()
        if notify:
            self.alignChanged.emit()

    def _apply(self):
        if getattr(self._content, "_fill_cell", False):
            # Une cellule divisee remplit toute la cellule (largeur ET hauteur) ; ce sont ses
            # sous-cellules qui se justifient.
            self.layout().setAlignment(self._content, Qt.Alignment())
            return
        self.layout().setAlignment(self._content, _V[self._v] | _H[self._h])

    def populate_menu(self, menu: QMenu):
        extra = getattr(self._content, "populate_extra_menu", None)     # actions propres au contenu
        if extra is not None:
            extra(menu)
            menu.addSeparator()
        add_align_menus(menu, self._h, self._v, lambda k: self.setAlign(k, self._v),
                        lambda k: self.setAlign(self._h, k))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.populate_menu(menu)
        menu.exec(event.globalPos())
        event.accept()


# ==========================================================================
# Cellule divisee
# ==========================================================================

class SplitCell(QWidget):
    """Une cellule divisee en sous-cellules : une LEGENDE par sous-cellule (bande
    d'entete, comme celle du tableau) puis ses widgets, separees par des filets
    verticaux. AUCUN padding : le contenu est colle aux bordures. Une grille partage
    les largeurs entre legendes et contenus ; chaque sous-cellule a au moins la
    largeur de son contenu, la derniere prend le reste. Chaque bordure se tire a la
    souris (sur la legende, ou sur le bord d'une sous-cellule) : cela impose une
    largeur MINIMALE a la sous-cellule de gauche (0 = naturelle).

    Chaque sous-cellule a SA justification (clic droit dessus), jamais commune.

    `parts` : [(legende, [widgets...])] — les widgets d'une sous-cellule sont
    empiles. Les widgets sont REUTILISES tels quels (un champ existant, ses
    valeurs et signaux, change juste de disposition)."""

    changed = Signal()

    _GRAB = 4          # demi-largeur de la zone de saisie d'une bordure
    _CAPTION_H = 20

    def __init__(self, parts: list[tuple[str, list[QWidget]]], parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._parts = parts
        self._aligns: list[tuple[str, str]] = [("center", "center")] * len(parts)
        self._cap_aligns: list[str] = ["center"] * len(parts)      # justification de chaque TITRE
        self._selected: set[int] = set()                           # sous-cellules selectionnees (entete)
        self._press_pos: QPoint | None = None
        self._press_shift = False
        self._padding = (0, 0, 0, 0)                               # gauche, haut, droite, bas
        self.snap_provider: Callable[[], list[int]] | None = None  # abscisses GLOBALES a aimanter
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(0)
        self._cap_labels: list[QLabel] = []
        self._cap_texts = [caption.upper() for caption, _w in parts]
        self._cells: list[QWidget] = []
        for i, (caption, widgets) in enumerate(parts):
            label = QLabel(caption.upper())
            _set_text_role(label, "side_letter")
            label.setAlignment(Qt.AlignCenter)
            label.setFixedHeight(self._CAPTION_H)
            label.setContentsMargins(6, 0, 6, 0)       # la legende ne rogne plus sa premiere/derniere lettre
            # Une legende n'a pas d'enfant : transparente aux clics, la bande reste saisissable.
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._cap_labels.append(label)
            self._grid.addWidget(label, 0, i)
            cell = QWidget()
            cell.setStyleSheet("background: transparent;")
            # PAS de WA_TransparentForMouseEvents ici : l'attribut vaut aussi pour les ENFANTS, et
            # rendait tous les controles inaccessibles. Les bords sont saisis par un filtre.
            cell.setMouseTracking(True)
            cell.installEventFilter(self)
            cell._split_owner, cell._split_index = self, i
            cell_l = QVBoxLayout(cell)
            cell_l.setContentsMargins(0, 0, 0, 0)
            cell_l.setSpacing(0)
            for widget in widgets:
                widget.setParent(cell)
            self._cells.append(cell)
            self._grid.addWidget(cell, 1, i)
        self._grid.setColumnStretch(len(parts) - 1, 1)
        self._grid.setRowStretch(1, 1)
        self._widths: list[int] = [0] * len(parts)      # largeur minimale imposee a la main (0 = naturelle)
        self._order: list[int] = list(range(len(parts)))  # ordre d'affichage (indices LOGIQUES des sous-cellules)
        self._reorder = None                              # deplacement de sous-cellule en cours
        self._drag: tuple[int, int, int] | None = None   # (sous-cellule, x de depart, largeur de depart)
        for i in range(len(parts)):
            self._arrange(i)

    # -- largeurs --

    def widths(self) -> list[int]:
        return list(self._widths)

    def setWidths(self, widths: list[int]):
        for i, w in enumerate(widths[:len(self._widths)]):
            self._widths[i] = max(0, int(w or 0))
        for pos, i in enumerate(self._order):
            self._grid.setColumnMinimumWidth(pos, self._widths[i])
        self.updateGeometry()

    # -- ordre des sous-cellules (comme les colonnes d'un tableau) --

    def order(self) -> list[int]:
        return list(self._order)

    def setOrder(self, order: list[int], notify: bool = True):
        order = [int(i) for i in order]
        if sorted(order) != list(range(len(self._cells))) or order == self._order:
            return
        self._order = order
        for label, cell in zip(self._cap_labels, self._cells):
            self._grid.removeWidget(label)
            self._grid.removeWidget(cell)
        for pos, i in enumerate(order):
            self._grid.addWidget(self._cap_labels[i], 0, pos)
            self._grid.addWidget(self._cells[i], 1, pos)
            self._grid.setColumnStretch(pos, 1 if pos == len(order) - 1 else 0)
        self.setWidths(self._widths)
        self.update()
        if notify:
            self.changed.emit()

    def _column_spans(self) -> list[tuple[int, int]]:
        return [(c.x(), c.x() + c.width()) for c in self._cells]

    def _begin_reorder(self, x: int):
        index = self._index_at(x)
        left, right = self._column_spans()[index]
        ghost = self.grab(QRect(left, 0, right - left, self.height()))
        self._reorder = _ReorderOverlay(self, self, index, ghost, 0, x - left)
        self.setCursor(Qt.ClosedHandCursor)

    def _end_reorder(self):
        overlay, self._reorder = self._reorder, None
        self.unsetCursor()
        gap = overlay.target
        overlay.hide()
        overlay.deleteLater()
        if gap is None:
            return
        order = [i for i in self._order if i != overlay.source]
        order.insert(gap - (1 if gap > self._order.index(overlay.source) else 0), overlay.source)
        self.setOrder(order)

    # -- justification : propre a chaque sous-cellule --

    def aligns(self) -> list[tuple[str, str]]:
        return list(self._aligns)

    def setSubAlign(self, index: int, h: str, v: str, notify: bool = True):
        if self._aligns[index] == (h, v):
            return
        self._aligns[index] = (h, v)
        self._arrange(index)
        if notify:
            self.changed.emit()

    def capAligns(self) -> list[str]:
        return list(self._cap_aligns)

    def setCapAlign(self, index: int, h: str, notify: bool = True):
        if self._cap_aligns[index] == h:
            return
        self._cap_aligns[index] = h
        self._cap_labels[index].setAlignment(_H[h] | Qt.AlignVCenter)
        if notify:
            self.changed.emit()

    def setContentPadding(self, left: int, top: int, right: int, bottom: int):
        """Meme padding que les cellules normales (Tableaux > Padding des cellules) pour le contenu
        de chaque sous-cellule."""
        self._padding = (left, top, right, bottom)
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        self.updateGeometry()

    def selected(self) -> set[int]:
        return set(self._selected)

    def _select_click(self, index: int, shift: bool):
        """Comme l'entete d'un tableau : clic seul = cette sous-cellule (re-clic = deselection) ;
        Maj = ajoute/retire. Plusieurs selectionnees = meme largeur pendant le glissement."""
        if shift:
            self._selected ^= {index}
        elif self._selected == {index}:
            self._selected = set()
        else:
            self._selected = {index}
        self.update()

    def _arrange(self, index: int):
        cell, (_c, widgets) = self._cells[index], self._parts[index]
        h, v = self._aligns[index]
        lay = cell.layout()
        while lay.count():
            lay.takeAt(0)
        if v in ("center", "bottom"):
            lay.addStretch(1)
        for widget in widgets:
            lay.addWidget(widget, 0, _H[h])
        if v in ("center", "top"):
            lay.addStretch(1)

    def populate_caption_menu(self, menu: QMenu, index: int):
        sub = QMenu("Justification du titre", menu)
        menu.addMenu(sub)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for key, label in _H_LABELS:
            action = sub.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == self._cap_aligns[index])
            group.addAction(action)
            action.triggered.connect(lambda _c=False, k=key: self.setCapAlign(index, k))

    def populate_menu(self, menu: QMenu, index: int):
        h, v = self._aligns[index]
        add_align_menus(menu, h, v, lambda k: self.setSubAlign(index, k, self._aligns[index][1]),
                        lambda k: self.setSubAlign(index, self._aligns[index][0], k))

    def _index_at(self, x: int) -> int:
        index = self._order[0]
        for i in self._order:
            if x >= self._cells[i].x():
                index = i
        return index

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        index = self._index_at(event.pos().x())
        if event.pos().y() < self._CAPTION_H:
            self.populate_caption_menu(menu, index)      # clic droit sur le titre : sa justification
        else:
            self.populate_menu(menu, index)
        menu.exec(event.globalPos())
        event.accept()

    # -- peinture : bande de legendes + filets verticaux --

    def _edges(self) -> list[int]:
        """Abscisse du bord gauche de chaque sous-cellule, hors la premiere."""
        return [self._cells[i].x() for i in self._order[1:]]

    def paintEvent(self, event):
        p = QPainter(self)
        head = QColor(_TABLE_HEAD["bg"] or M["table_head_bg"])
        p.fillRect(0, 0, self.width(), self._CAPTION_H, head)
        for i in self._selected:
            if i < len(self._cells):
                p.fillRect(self._cells[i].x(), 0, self._cells[i].width(), self._CAPTION_H,
                           QColor(95, 155, 208, 56))
        line = _vline_color()
        p.fillRect(0, self._CAPTION_H - 1, self.width(), 1, line)
        for x in self._edges():
            p.fillRect(x, 0, 1, self.height(), line)
        p.end()

    def event(self, event):
        handled = super().event(event)
        if event.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self.update()           # les filets suivent les cellules apres chaque layout
        return handled

    # -- glisser une bordure --

    def _edge_at(self, x: int) -> int | None:
        for k, edge in enumerate(self._edges()):
            if abs(x - edge) <= self._GRAB:
                return self._order[k]          # la sous-cellule situee a GAUCHE de la bordure
        return None

    _SNAP = 9

    def _end_drag(self):
        self._drag = None
        for label, text in zip(self._cap_labels, self._cap_texts):
            label.setText(text)

    def _snapped(self, index: int, width: int) -> int:
        """Aimante la bordure droite de la sous-cellule aux bordures verticales des autres lignes
        (colonnes du tableau, sous-cellules des autres cellules divisees) quand elle passe a moins de
        `_SNAP` px."""
        if self.snap_provider is None:
            return width
        left = self._cells[index].mapToGlobal(QPoint(0, 0)).x()
        edge = left + width
        best = min(self.snap_provider(), key=lambda x: abs(x - edge), default=None)
        if best is not None and abs(best - edge) <= self._SNAP and best - left >= 24:
            return best - left
        return width

    def _press(self, x: int, global_x: int) -> bool:
        i = self._edge_at(x)
        if i is None:
            return False
        self._drag = (i, global_x, self._cells[i].width())
        return True

    def _move(self, x: int, global_x: int, widget: QWidget) -> bool:
        if self._drag is not None:
            i, x0, w0 = self._drag
            width = max(24, w0 + global_x - x0)
            width = self._snapped(i, width)
            widths = list(self._widths)
            group = sorted(self._selected) if i in self._selected and len(self._selected) > 1 else [i]
            for k in group:                  # plusieurs selectionnees : EXACTEMENT la meme largeur, en direct
                widths[k] = width
            self.setWidths(widths)
            for k in group:                  # indication de largeur dans la legende pendant le glissement
                self._cap_labels[k].setText(f"{width} px")
            self.changed.emit()
            return True
        if self._edge_at(x) is not None:
            widget.setCursor(Qt.SizeHorCursor)
        else:
            widget.unsetCursor()
        return False

    def eventFilter(self, obj, event):
        """Les cellules de contenu laissent passer leurs controles ; seuls leurs propres bords
        (zone libre, hors controle) saisissent une bordure."""
        etype = event.type()
        if etype not in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            return False
        gpos = event.globalPosition().toPoint()
        x = self.mapFromGlobal(gpos).x()
        if etype == QEvent.MouseMove:
            return self._move(x, gpos.x(), obj)
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            return self._press(x, gpos.x())
        if etype == QEvent.MouseButtonRelease and self._drag is not None:
            self._end_drag()
            return True
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._press(event.position().toPoint().x(),
                                                             event.globalPosition().toPoint().x()):
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.position().toPoint().y() < self._CAPTION_H:
            self._press_pos = event.position().toPoint()
            self._press_shift = bool(event.modifiers() & Qt.ShiftModifier)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and event.buttons() & Qt.LeftButton and self._drag is None:
            if self._reorder is None and (event.position().toPoint() - self._press_pos).manhattanLength() > 6:
                self._begin_reorder(self._press_pos.x())
            if self._reorder is not None:
                self._reorder.follow(event.position().toPoint().x())
                event.accept()
                return
        if self._move(event.position().toPoint().x(), event.globalPosition().toPoint().x(), self):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._end_drag()
            event.accept()
            return
        if self._reorder is not None:
            self._end_reorder()
            self._press_pos = None
            event.accept()
            return
        pos, self._press_pos = self._press_pos, None
        if event.button() == Qt.LeftButton and pos is not None and (
                event.position().toPoint() - pos).manhattanLength() <= 4:
            self._select_click(self._index_at(pos.x()), self._press_shift)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ==========================================================================
# Bordures de colonnes saisissables sur les cellules
# ==========================================================================

class _RowHeights:
    """Hauteur de chaque ligne d'un tableau : naturelle (celle du contenu) ou imposee a la main
    (bordure basse de la ligne tiree a la souris). `equal` : toutes les lignes ont la meme hauteur
    (menu de l'entete). Jamais plus petite que le contenu."""

    def __init__(self, frame: QWidget, rows: list[QWidget]):
        self.frame, self.rows = frame, rows
        self.user: list[int] = [0] * len(rows)      # 0 = naturelle
        self.equal = False

    def natural(self, i: int) -> int:
        return max(36, self.rows[i].layout().sizeHint().height())

    def _sync_size(self):
        """`rows` se remplit apres la creation de l'objet : `user` suit sa longueur."""
        self.user = (self.user + [0] * len(self.rows))[:len(self.rows)]

    def apply(self):
        self._sync_size()
        targets = [max(self.natural(i), self.user[i]) for i in range(len(self.rows))]
        if self.equal and targets:
            targets = [max(targets)] * len(targets)
        for i, (row, target) in enumerate(zip(self.rows, targets)):
            fixed = self.equal or self.user[i] > 0
            row.setMinimumHeight(target)
            row.setMaximumHeight(target if fixed else 16777215)
        self.frame.setMinimumHeight(0)
        _lock_min_height(self.frame)
        self.frame.updateGeometry()
        _reflow_ancestors(self.frame)       # les sections qui contiennent le tableau suivent

    def set_height(self, i: int, height: int):
        self._sync_size()
        if self.equal:
            self.user = [max(0, height)] * len(self.rows)
        else:
            self.user[i] = max(0, height)
        self.user = [h if h > self.natural(k) else 0 for k, h in enumerate(self.user)]
        self.apply()
        self.frame.dimsChanged.emit()

    def set_equal(self, equal: bool):
        if self.equal == bool(equal):
            return
        self.equal = bool(equal)
        if not self.equal:
            self.user = [0] * len(self.rows)
        self.apply()
        self.frame.dimsChanged.emit()


class _CellEdgeDrag(QObject):
    """Filtre d'evenements pose sur les lignes ET leurs cellules : la bordure d'une
    colonne se saisit n'importe ou sur sa hauteur, pas seulement sur l'entete ; la
    bordure BASSE d'une ligne se tire pour changer sa hauteur.
    Reprend la logique de l'entete (`_boundary_at`/`beginDrag`/`dragTo`), donc les
    memes limites, la meme colonne extensible et les memes colonnes « egales »."""

    _GRAB = 4

    def __init__(self, head: _ResizableTableHeader, heights: _RowHeights):
        super().__init__(head)
        self._head = head
        self._heights = heights
        self._vdrag: tuple[int, int, int] | None = None     # (ligne, y de depart, hauteur de depart)

    def _row_hit(self, obj, event) -> int | None:
        """Index de la ligne dont la bordure basse est sous le curseur."""
        row = obj if obj in self._heights.rows else obj.parentWidget()
        if row not in self._heights.rows:
            return None
        y = obj.mapTo(row, event.position().toPoint()).y()
        return self._heights.rows.index(row) if row.height() - y <= self._GRAB else None

    def watch(self, widget: QWidget):
        widget.setMouseTracking(True)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype not in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            return False
        head = self._head
        gpos = event.globalPosition().toPoint()
        gx = gpos.x()
        if etype == QEvent.MouseMove:
            if head.isDragging():
                head.dragTo(gx)
                return True
            if self._vdrag is not None:
                row, y0, h0 = self._vdrag
                self._heights.set_height(row, h0 + gpos.y() - y0)
                return True
            if head._boundary_at(head.mapFromGlobal(gpos).x()) is not None:
                obj.setCursor(Qt.SizeHorCursor)
            elif self._row_hit(obj, event) is not None:
                obj.setCursor(Qt.SizeVerCursor)
            else:
                obj.unsetCursor()
            return False
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            hit = head._boundary_at(head.mapFromGlobal(gpos).x())
            if hit is not None:
                head.beginDrag(hit, gx)
                return True
            row = self._row_hit(obj, event)
            if row is not None:
                self._vdrag = (row, gpos.y(), self._heights.rows[row].height())
                return True
            return False
        if etype == QEvent.MouseButtonRelease:
            if head.isDragging():
                head.endDrag()
                return True
            if self._vdrag is not None:
                self._vdrag = None
                return True
        return False


def split_of(widget: QWidget) -> "SplitCell | None":
    """La cellule divisee d'un contenu de cellule (lui-meme ou le champ qui l'enveloppe)."""
    if isinstance(widget, SplitCell):
        return widget
    return getattr(widget, "_split", None)


def wrap_split(split: SplitCell, holder: QWidget | None = None) -> QWidget:
    """Enveloppe une cellule divisee dans un champ (`holder`, ou un QWidget neuf) qui la remplit
    et lui transmet la justification de la cellule."""
    holder = holder or QWidget()
    holder.setStyleSheet("background: transparent;")
    layout = holder.layout() or QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(split)
    holder._split = split
    holder._fill_cell = True
    return holder


# ==========================================================================
# Etat enregistre d'un tableau (justifications, cellules divisees)
# ==========================================================================

class _CellsState:
    """Pendant de `_TableFrame.collectDims/applyDims` pour ce que le tableau a de
    plus que ses largeurs de colonnes : justification de chaque cellule et largeurs
    des sous-cellules. Cle d'une cellule : `r<ligne>c<colonne>`."""

    def __init__(self):
        self.cells: dict[str, _Cell] = {}
        self.heights: _RowHeights | None = None
        self.head: _ResizableTableHeader | None = None
        self.head_default: list[str] = []
        self.on_head_align: Callable | None = None

    def collect(self) -> dict:
        align = {k: f"{c._h},{c._v}" for k, c in self.cells.items() if (c._h, c._v) != c._default}
        split = {k: split_of(c.content()).widths() for k, c in self.cells.items() if split_of(c.content())}
        sub = {k: [f"{h},{v}" for h, v in split_of(c.content()).aligns()]
               for k, c in self.cells.items()
               if split_of(c.content()) and any(a != ("center", "center") for a in split_of(c.content()).aligns())}
        out = {}
        if self.head is not None:
            head_align = {str(i): a for i, a in enumerate(self.head_aligns()) if a != self.head_default[i]}
            if head_align:
                out["head_align"] = head_align
        cap = {k: split_of(c.content()).capAligns() for k, c in self.cells.items()
               if split_of(c.content()) and any(a != "center" for a in split_of(c.content()).capAligns())}
        if cap:
            out["split_head_align"] = cap
        if align:
            out["align"] = align
        if split:
            out["split"] = split
        moved = {k: split_of(c.content()).order() for k, c in self.cells.items()
                 if split_of(c.content()) and split_of(c.content()).order() != sorted(split_of(c.content()).order())}
        if moved:
            out["split_order"] = moved
        if sub:
            out["split_align"] = sub
        if self.head is not None and self.head.order() != sorted(self.head.order()):
            out["col_order"] = self.head.order()
        if self.heights is not None:
            if any(self.heights.user):
                out["row_heights"] = list(self.heights.user)
            if self.heights.equal:
                out["equal_rows"] = True
        return out

    def head_aligns(self) -> list[str]:
        out = []
        for label in self.head._cells:
            flag = label.alignment()
            out.append("right" if flag & Qt.AlignRight else "center" if flag & Qt.AlignHCenter else "left")
        return out

    def set_head_align(self, index: int, key: str, notify: bool = True) -> None:
        self.head._cells[index].setAlignment(_H[key] | Qt.AlignVCenter)
        if notify and self.on_head_align is not None:
            self.on_head_align()

    reflow: Callable | None = None

    def apply(self, dims: dict):
        order = dims.get("col_order")
        if self.head is not None and isinstance(order, list):
            self.head.setOrder(order, notify=False)
        elif self.head is not None:
            self.head.setOrder(list(range(len(self.head_default))), notify=False)
        if self.reflow is not None:
            self.reflow()
        for i in range(len(self.head_default) if self.head is not None else 0):
            saved = (dims.get("head_align") or {}).get(str(i))
            self.set_head_align(i, saved if saved in _H else self.head_default[i], notify=False)
        for key, aligns in (dims.get("split_head_align") or {}).items():
            cell = self.cells.get(key)
            split = split_of(cell.content()) if cell is not None else None
            for i, h in enumerate(aligns if split is not None else ()):
                if i < len(split._cells) and h in _H:
                    split.setCapAlign(i, h, notify=False)
        for key, value in (dims.get("align") or {}).items():
            cell = self.cells.get(key)
            if cell is not None and "," in str(value):
                h, v = str(value).split(",", 1)
                if h in _H and v in _V:
                    cell.setAlign(h, v, notify=False)
        for key, cell in self.cells.items():
            split = split_of(cell.content())
            if split is not None:
                saved = (dims.get("split_order") or {}).get(key)
                split.setOrder(saved if isinstance(saved, list) else list(range(len(split._cells))), notify=False)
        for key, widths in (dims.get("split") or {}).items():
            cell = self.cells.get(key)
            if cell is not None and split_of(cell.content()) is not None:
                split_of(cell.content()).setWidths(list(widths))
        for key, aligns in (dims.get("split_align") or {}).items():
            cell = self.cells.get(key)
            split = split_of(cell.content()) if cell is not None else None
            for i, value in enumerate(aligns if split is not None else ()):
                h, _, v = str(value).partition(",")
                if i < len(split._cells) and h in _H and v in _V:
                    split.setSubAlign(i, h, v, notify=False)
        heights = self.heights
        if heights is not None:
            saved = dims.get("row_heights") or []
            heights.user = [int(saved[i]) if i < len(saved) else 0 for i in range(len(heights.rows))]
            heights.equal = bool(dims.get("equal_rows", False))
            heights.apply()


# ==========================================================================
# Le tableau
# ==========================================================================

def build_cells_table(columns: list[tuple[str, int]], rows: list[list], first_col_width: int | None = None,
                      head_align: dict | None = None):
    """Tableau a entete et a cellules. `columns` : [(titre, largeur)] (0 = colonne
    extensible) ; `rows` : une liste de cellules par ligne, chacune un widget ou
    `(widget, justif_h, justif_v)`. Retourne (frame, head, cells) ; `frame` suit le
    style commun des tableaux (arrondi, bordure, padding, couleur d'entete) et
    enregistre ses dimensions comme les autres (`_TableFrame`)."""
    frame, layout = _table_frame()
    _prestyle_flat_frame(frame)
    head = _ResizableTableHeader([(title, width) for title, width in columns])
    head.setCellPadding(14, 14)
    layout.addWidget(head)
    for index, align in (head_align or {}).items():
        head._cells[index].setAlignment(align)
    state = _CellsState()
    state.head = head
    state.head_default = state.head_aligns()
    state.on_head_align = frame.dimsChanged.emit
    frame._extra_dims = state
    row_widgets: list[QWidget] = []
    heights = state.heights = _RowHeights(frame, row_widgets)
    grips = _CellEdgeDrag(head, heights)
    row_meta, cells = [], []
    column_cells: dict[int, list[QWidget]] = {}
    for r, spec_row in enumerate(rows):
        bg = M["table_row_a"] if r % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(r == 0))
        _prestyle_flat_row(row, r, len(rows))
        row_meta.append((row, bg, r == 0))
        grips.watch(row)
        row_widgets.append(row)
        row_cells = []
        for c, spec in enumerate(spec_row):
            widget, h, v = spec if isinstance(spec, tuple) else (spec, None, None)
            h = h or ("left" if c == 0 else "right" if not columns[c][1] else "center")
            cell = _Cell(widget, h, v or "center")
            cell._default = (h, v or "center")
            width = columns[c][1]
            if width:
                cell.setFixedWidth(width)
                row_l.addWidget(cell, 0)
            else:
                row_l.addWidget(cell, 1)
            column_cells.setdefault(c, []).append(cell)
            grips.watch(cell)
            cell.alignChanged.connect(frame.dimsChanged)
            if split_of(widget) is not None:
                split_of(widget).changed.connect(frame.dimsChanged)
                split_of(widget).snap_provider = lambda me=split_of(widget): snap_edges(me)
                grips.watch(split_of(widget))      # sa derniere ligne reste saisissable en bas
            state.cells[f"r{r}c{c}"] = cell
            row_cells.append(cell)
        cells.append(row_cells)
        _lock_min_height(row)
        layout.addWidget(row)
    _wire_resizable_columns(head, column_cells)
    head.disableEqualToggle(len(columns) - 1) if not columns[-1][1] else None

    def reflow_columns():
        """Replace les cellules de chaque ligne dans l'ordre d'affichage des colonnes."""
        for r, row_cells in enumerate(cells):
            lay = row_widgets[r].layout()
            for cell in row_cells:
                lay.removeWidget(cell)
            for pos, c in enumerate(head.order()):
                lay.insertWidget(pos, row_cells[c], 0 if columns[c][1] else 1)
            row_widgets[r].update()
        head.update()

    state.reflow = reflow_columns
    head.setReorderable(True)

    def on_moved():
        reflow_columns()
        frame.dimsChanged.emit()

    head.columnMoved.connect(on_moved)

    def snap_edges(me: SplitCell) -> list[int]:
        """Bordures verticales (abscisses globales) des AUTRES lignes : colonnes du tableau et
        sous-cellules des autres cellules divisees."""
        xs = [head.mapToGlobal(QPoint(edge, 0)).x() for edge in head._column_edges()]
        for row_cells in cells:
            for cell in row_cells:
                other = split_of(cell.content())
                if other is not None and other is not me:
                    xs.extend(other.mapToGlobal(QPoint(e, 0)).x() for e in other._edges())
        return xs

    def cell_padding(padding: tuple):
        left, top, right, bottom = padding
        h_edge = _TABLE_INNER_BORDER["h"]
        v_edge = _TABLE_INNER_BORDER["v"]
        # Epaisseur des filets interieurs : une cellule divisee rentre de cette epaisseur pour ne pas les recouvrir.
        inset_top = h_edge["thickness"] if h_edge["enabled"] else 0
        inset_left = v_edge["thickness"] - v_edge["thickness"] // 2 if v_edge["enabled"] else 0
        for r, row_cells in enumerate(cells):
            has_fill = any(getattr(c.content(), "_fill_cell", False) for c in row_cells)
            row_layout = row_widgets[r].layout()
            # Ligne avec cellule divisee : plus de marge haute/basse, elle va de filet a filet.
            row_layout.setContentsMargins(0, (inset_top if r > 0 else 0) if has_fill else 6, 0, 0 if has_fill else 6)
            for c, cell in enumerate(row_cells):
                if getattr(cell.content(), "_fill_cell", False):
                    cell.layout().setContentsMargins(inset_left if c > 0 else 0, 0, 0, 0)
                    if split_of(cell.content()) is not None:       # meme padding que les cellules normales
                        split_of(cell.content()).setContentPadding(left, top, right, bottom)
                else:
                    cell.layout().setContentsMargins(left, top, right, bottom)
        heights.apply()

    frame._flat_cell_padding = cell_padding

    # Clic droit sur l'entete : option de tableau « lignes : hauteurs egales ».
    def head_menu(pos):
        menu = QMenu(head)
        column = head._column_at(pos.x())
        if column is not None:
            sub = QMenu("Justification du titre", menu)
            menu.addMenu(sub)
            group = QActionGroup(sub)
            group.setExclusive(True)
            current = state.head_aligns()[column]
            for key, label in _H_LABELS:
                act = sub.addAction(label)
                act.setCheckable(True)
                act.setChecked(key == current)
                group.addAction(act)
                act.triggered.connect(lambda _c=False, k=key, i=column: state.set_head_align(i, k))
            menu.addSeparator()
        action = menu.addAction("Lignes : hauteurs égales")
        action.setCheckable(True)
        action.setChecked(heights.equal)
        action.toggled.connect(heights.set_equal)
        menu.exec(head.mapToGlobal(pos))

    head.setContextMenuPolicy(Qt.CustomContextMenu)
    head.customContextMenuRequested.connect(head_menu)
    _register_cells_table(frame, head, row_meta)     # applique tout de suite le style courant
    _lock_min_height(frame)
    return frame, head, cells


def natural_label_width(labels: list[str], extra: int = 0) -> int:
    """Largeur de depart de la colonne des libelles : le plus long, plus les marges de cellule."""
    probe = QLabel()
    _set_text_role(probe, "row_label")
    widest = 0
    for text in labels:
        probe.setText(text)
        widest = max(widest, probe.sizeHint().width())
    probe.deleteLater()
    return widest + 28 + extra + 6


# ==========================================================================
# Interrupteurs de tableau : type 2, sans texte
# ==========================================================================

def normalize_toggles(root: QWidget):
    """Tous les interrupteurs d'un tableau sont de type 2 et sans texte (« actif »/
    « sans ») : la regle des tableaux des reglages (voir AGENTS.md)."""
    for toggle in root.findChildren(_Toggle):
        if toggle._style_override != "toggle2" or toggle._show_label:
            toggle._style_override = "toggle2"
            toggle._show_label = False
            toggle.apply_style()


# ==========================================================================
# Plage d'un curseur (clic droit)
# ==========================================================================

def set_field_range(field, low, high):
    """Change la plage d'un champ curseur (`_SliderField`/`_RatioSliderField`) en gardant sa valeur
    si elle y tient, sinon en la ramenant dans la plage."""
    field.slider._min, field.slider._max = low, high
    field._min, field._max = low, high
    field.slider.setValue(max(low, min(high, field.slider.value())))
    field.slider.update()


def apply_saved_range(field, saved, scale: int = 1):
    """Applique une plage enregistree [min, max] SANS toucher a la valeur courante : la plage
    est elargie au besoin pour la contenir (un reglage sur disque n'est jamais modifie en
    silence)."""
    if not saved or len(saved) != 2:
        return
    value = field.slider.value()
    low, high = int(saved[0]), int(saved[1])
    set_field_range(field, min(low, value), max(high, value))


class _RangeDialog(QDialog):
    def __init__(self, parent, low, high, scale: int):
        super().__init__(parent)
        self.setWindowTitle("Plage du curseur")
        self.setModal(True)
        form = QFormLayout(self)
        box_cls = QSpinBox if scale == 1 else QDoubleSpinBox
        self.low, self.high = box_cls(), box_cls()
        for box, value in ((self.low, low), (self.high, high)):
            if scale == 1:
                box.setRange(-100000, 100000)
            else:
                box.setDecimals(2)
                box.setRange(-1000.0, 1000.0)
            box.setValue(value / scale if scale != 1 else value)
        form.addRow("Minimum", self.low)
        form.addRow("Maximum", self.high)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._scale = scale

    def values(self):
        return round(self.low.value() * self._scale), round(self.high.value() * self._scale)


class _RangeMenuFilter(QObject):
    def __init__(self, slider, field, key: str, on_range: Callable | None, scale: int):
        super().__init__(slider)
        self._field, self._key, self._on_range, self._scale = field, key, on_range, scale

    def eventFilter(self, obj, event):
        if event.type() != QEvent.ContextMenu:
            return False
        menu = QMenu(obj)
        low, high = self._field._min, self._field._max
        shown = f"{low / self._scale:g} – {high / self._scale:g}"
        action = menu.addAction(f"Modifier la plage ({shown})…")
        action.triggered.connect(self._edit)
        parent = obj.parentWidget()
        while parent is not None and not isinstance(parent, _Cell) and not hasattr(parent, "_split_owner"):
            parent = parent.parentWidget()
        if parent is not None:
            menu.addSeparator()
            if hasattr(parent, "_split_owner"):         # sous-cellule : SA justification
                parent._split_owner.populate_menu(menu, parent._split_index)
            else:
                parent.populate_menu(menu)
        menu.exec(event.globalPos())
        return True

    def _edit(self):
        field = self._field
        dialog = _RangeDialog(field.window(), field._min, field._max, self._scale)
        if dialog.exec() != QDialog.Accepted:
            return
        low, high = dialog.values()
        if low >= high:
            return
        set_field_range(field, low, high)
        if self._on_range is not None:
            self._on_range(self._key, low, high)


def attach_range_menu(field, key: str, on_range: Callable | None, scale: int = 1):
    """Clic droit sur le curseur de `field` : « Modifier la plage ». `on_range(cle, min, max)`
    est appele a chaque changement (la fenetre l'enregistre aussitot). `scale` : 100 pour un
    ratio stocke en centiemes."""
    slider = field.slider
    slider.installEventFilter(_RangeMenuFilter(slider, field, key, on_range, scale))
    field._range_key = key


def slider_fields(widget: QWidget) -> list:
    """Champs curseur d'un widget (lui-meme compris), dans l'ordre de creation."""
    found = [widget] if hasattr(widget, "slider") and hasattr(widget, "_min") else []
    found += [w for w in widget.findChildren(QWidget) if hasattr(w, "slider") and hasattr(w, "_min")]
    return found
