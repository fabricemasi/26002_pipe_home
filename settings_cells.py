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

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QSizePolicy, QSpacerItem, QSpinBox, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QKeySequence, QShortcut

from settings_layout import (
    _ReorderOverlay,
    _TABLE_HEAD, _lock_min_height, _prestyle_flat_frame, _prestyle_flat_row, _register_cells_table,
    _ResizableTableHeader, _reflow_ancestors, _style_flat_table, _table_row, _wire_resizable_columns,
)
from settings_store import M
from settings_theme import _input_radius, _register_input, _set_text_role
from settings_widgets import (
    Menu, menu_row,
    DRAG_GHOST_OPACITY, _TABLE_INNER_BORDER, _SliderField, _Toggle, _hide_width_badges, _selection_color, _table_frame, _width_badges,
    add_context_extras,
)

_H = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
_V = {"top": Qt.AlignTop, "center": Qt.AlignVCenter, "bottom": Qt.AlignBottom}
_H_LABELS = (("left", "Gauche"), ("center", "Centre"), ("right", "Droite"))
_V_LABELS = (("top", "Haut"), ("center", "Centre"), ("bottom", "Bas"))


def _vline_color() -> QColor:
    return QColor(_TABLE_INNER_BORDER["v"]["color"] or M["panel_border"])


# ==========================================================================
# Cellule + justification
# ==========================================================================

class _TextField(QLineEdit):
    """Zone de saisie d'un texte (habillage de coche...), habillee comme les autres champs."""

    def __init__(self, text: str, width: int = 170):
        super().__init__(text)
        self.setFixedSize(width, 25)
        self._radius = _input_radius()
        _register_input(self)
        self._restyle()

    def _restyle(self):
        self.setStyleSheet(
            f"QLineEdit {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; color: {M['value_fg']}; padding: 0 8px; }}")

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._restyle()


class _WordsField(_TextField):
    """Zone de saisie de MOTS separes par des espaces (mots cles des fichiers, filtres), avec
    autocompletion du mot EN COURS : propositions = `suggestions()` (mots deja employes) moins ceux deja
    saisis, sur une partie du mot, sans tenir compte des majuscules ; choisir une proposition la met a la
    place du mot en cours, suivie d'un espace."""

    SEPARATORS = " ,;\t"

    def __init__(self, words=(), suggestions: Callable | None = None, width: int = 170):
        super().__init__(" ".join(words), width=width)
        from PySide6.QtCore import QStringListModel
        from PySide6.QtWidgets import QCompleter
        self._suggestions = suggestions
        self._model = QStringListModel(self)
        self.completer_ = QCompleter(self._model, self)
        self.completer_.setWidget(self)
        self.completer_.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer_.setFilterMode(Qt.MatchContains)
        self.completer_.setCompletionMode(QCompleter.PopupCompletion)
        self.completer_.activated[str].connect(self._insert)
        self.textEdited.connect(self._update_completion)

    def words(self) -> list[str]:
        out, seen = [], set()
        for word in self.text().replace(",", " ").replace(";", " ").split():
            if word.casefold() not in seen:
                seen.add(word.casefold())
                out.append(word)
        return out

    def set_words(self, words):
        self.setText(" ".join(words))

    def _token_span(self) -> tuple[int, int]:
        """(debut, fin) du mot sous le curseur (fin = curseur)."""
        text, pos = self.text(), self.cursorPosition()
        start = pos
        while start > 0 and text[start - 1] not in self.SEPARATORS:
            start -= 1
        return start, pos

    def _update_completion(self, _text: str = ""):
        popup = self.completer_.popup()
        start, end = self._token_span()
        token = self.text()[start:end]
        if self._suggestions is None or not token:
            popup.hide()
            return
        others = {w.casefold() for w in self.words()} - {token.casefold()}
        self._model.setStringList([w for w in self._suggestions() if w.casefold() not in others])
        self.completer_.setCompletionPrefix(token)
        if self.completer_.completionCount() == 0 or (
                self.completer_.completionCount() == 1 and self.completer_.currentCompletion().casefold() == token.casefold()):
            popup.hide()
            return
        rect = self.cursorRect()
        rect.setWidth(max(self.width() // 2, popup.sizeHintForColumn(0) + 24))
        self.completer_.complete(rect)

    def _insert(self, word: str):
        start, end = self._token_span()
        text = self.text()
        while end < len(text) and text[end] not in self.SEPARATORS:
            end += 1                                     # la fin du mot sous le curseur est remplacee aussi
        rest = text[end:].lstrip(self.SEPARATORS)
        self.setText(text[:start] + word + " " + rest)
        self.setCursorPosition(start + len(word) + 1)



def rename_inline(label: QLabel, on_done: Callable[[str], None]) -> QLineEdit:
    """Renommer un titre SUR PLACE (titre d'entete d'un tableau, legende d'une sous-cellule) : zone de
    saisie des reglages posee sur lui, sa police ; Entree ou clic ailleurs = `on_done(texte)`, Echap =
    annule. Texte vide = titre d'origine (c'est l'appelant qui le decide)."""
    parent = label.parentWidget()
    edit = _TextField(label.text(), width=max(60, label.width()))
    edit.setObjectName("RenameInline")
    edit.setParent(parent)
    edit.setFont(label.font())
    edit.setAlignment(label.alignment())
    geo = label.geometry()
    edit.setFixedSize(max(60, geo.width()), max(18, geo.height()))
    edit.move(geo.x(), geo.y() + (geo.height() - edit.height()) // 2)
    done = [False]

    def finish(accept: bool):
        if done[0]:
            return
        done[0] = True
        text = edit.text().strip()
        edit.hide()
        edit.deleteLater()
        if accept:
            on_done(text)

    edit.editingFinished.connect(lambda: finish(True))
    QShortcut(QKeySequence(Qt.Key_Escape), edit, context=Qt.WidgetShortcut, activated=lambda: finish(False))
    edit.show()
    edit.raise_()
    edit.selectAll()
    edit.setFocus(Qt.OtherFocusReason)
    return edit


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

    def paintEvent(self, event):
        look = getattr(self, "_part_look", None) or {}
        border = look.get("border") or {}
        enabled = border.get("enabled") or {}
        colors = border.get("colors") or {}
        thickness = max(1, int(border.get("thickness", 1) or 1))
        if not any(enabled.values()):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(thickness // 2, thickness // 2,
                                    -(thickness - 1) // 2, -(thickness - 1) // 2)
        for side, start, end in (
            ("top", rect.topLeft(), rect.topRight()),
            ("right", rect.topRight(), rect.bottomRight()),
            ("bottom", rect.bottomLeft(), rect.bottomRight()),
            ("left", rect.topLeft(), rect.bottomLeft()),
        ):
            if not enabled.get(side):
                continue
            painter.setPen(QPen(QColor(colors.get(side, "#ffffff")), thickness))
            painter.drawLine(start, end)
        painter.end()

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
        target = getattr(self._content, "_float_slot", None) or self._content     # contenu detache : sa place
        self.layout().setAlignment(target, _V[self._v] | _H[self._h])

    def populate_menu(self, menu: QMenu):
        extra = getattr(self._content, "populate_extra_menu", None)     # actions propres au contenu
        if extra is not None:
            extra(menu)
            menu.addSeparator()
        add_align_menus(menu, self._h, self._v, lambda k: self.setAlign(k, self._v),
                        lambda k: self.setAlign(self._h, k))
        add_split_menu(self, menu)
        state, key = _state_of(self)
        if state is not None:
            menu.addSeparator()
            if state.head is not None:
                hidden = state.head_hidden
                menu.addAction("Afficher l'entête" if hidden else "Supprimer l'entête",
                               lambda: state.set_head_hidden(not hidden))
            row = int(key[1:].split("c", 1)[0])
            if state.can_text_above(row):
                if row in state.above_texts:
                    menu.addAction("Modifier le texte au-dessus…", lambda: state.edit_above_text(row))
                    menu.addAction("Supprimer le texte au-dessus", lambda: state.set_above_text(row, ""))
                else:
                    menu.addAction("Ajouter un texte au-dessus…", lambda: state.edit_above_text(row))
        floated = [c for c in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                   if getattr(c, "_float_slot", None) is not None]
        if floated:
            menu.addSeparator()
            menu.addAction("Remettre les objets à leur place", self._reset_objects)

    def _reset_objects(self):
        """Objets deplaces / redimensionnes (Ctrl+Maj, Ctrl+Maj+X) : retour a leur place d'origine."""
        state, key = _state_of(self)
        if state is None:
            return
        for name in [k for k in state.objects if k.split("|", 1)[0] == key]:
            push_object_undo(state, name, state.objects[name])          # Ctrl+Z
            state.set_object(name, None)
        if state.frame is not None:
            state.frame.dimsChanged.emit()

    def contextMenuEvent(self, event):
        menu = Menu(self)
        self.populate_menu(menu)
        add_context_extras(self, menu)
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
    largeur de son contenu. Chaque bordure se tire a la souris (sur la legende, ou
    sur le bord d'une sous-cellule) : cela impose une largeur EXACTE a la
    sous-cellule de gauche (0 = naturelle), voir setWidths.

    Chaque sous-cellule a SA justification (clic droit dessus), jamais commune.

    `parts` : [(legende, [widgets...])] — les widgets d'une sous-cellule sont
    empiles. Les widgets sont REUTILISES tels quels (un champ existant, ses
    valeurs et signaux, change juste de disposition)."""

    widthsResized = Signal()   # largeurs changees A LA SOURIS (la colonne du tableau se recale)
    changed = Signal()

    _GRAB = 4          # demi-largeur de la zone de saisie d'une bordure
    _CAPTION_H = 20

    _badge_cols: list = []   # (classe : event() est appele avant la fin de __init__)

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
        self._cap_default = list(self._cap_texts)                  # titres d'origine (renommage : clic droit)
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
        # Colonne vide finale : recoit la place restante quand la derniere sous-cellule a une largeur
        # reglee (sinon Qt la donnait a une sous-cellule libre quelconque, ex. « lier les 4 »).
        self._tail = QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._grid.addItem(self._tail, 0, len(parts))
        self._grid.setRowStretch(1, 1)
        self._widths: list[int] = [0] * len(parts)      # largeur EXACTE reglee a la main (0 = naturelle) : enregistree
        self._shown: list[int] = [0] * len(parts)       # largeur AFFICHEE : la reglee, repliee si la colonne est trop etroite
        self._room: int | None = None                    # place laissee par la colonne du tableau (None = sans limite)
        self._order: list[int] = list(range(len(parts)))  # ordre d'affichage (indices LOGIQUES des sous-cellules)
        self._reorder = None                              # deplacement de sous-cellule en cours
        self._drag: tuple[int, int, int] | None = None   # (sous-cellule, x de depart, largeur de depart)
        self._badge_cols: list[int] = []                  # sous-cellules dont l'encart de largeur est affiche
        for i in range(len(parts)):
            self._arrange(i)

    # -- largeurs --

    def widths(self) -> list[int]:
        return list(self._widths)

    def setWidths(self, widths: list[int]):
        """Largeur EXACTE de chaque sous-cellule reglee a la main (0 = naturelle) : une dimension
        choisie est prioritaire (plusieurs sous-cellules selectionnees ont donc EXACTEMENT la meme
        largeur) ; ce sont les autres qui s'adaptent : la colonne du tableau se cale sur ses
        sous-cellules (colonnes libres, voir build_cells_table) ; s'il reste de la place (ligne moins
        large que la colonne), seule la DERNIERE sous-cellule, si elle n'est pas reglee, la prend —
        jamais une sous-cellule reglee, jamais une sous-cellule du milieu."""
        for i, w in enumerate(widths[:len(self._widths)]):
            self._widths[i] = max(0, int(w or 0))
        self._apply_widths()

    def setRoom(self, room: int | None):
        """Place disponible dans la colonne du tableau. Trop etroite : les sous-cellules reglees se
        PLIENT (toutes du meme facteur, des largeurs egales le restent) ; plus large : elles reviennent
        vers leur largeur reglee, jamais au-dela. La largeur reglee (enregistree) ne change pas."""
        self._room = None if room is None else max(0, int(room))
        self._apply_widths()

    def _free_min(self) -> int:
        """Place mini des sous-cellules libres (non reglees) : leur contenu et leur legende."""
        return sum(max(24, self._cells[k].minimumSizeHint().width(), self._cap_labels[k].minimumSizeHint().width())
                   for k, w in enumerate(self._widths) if not w)

    def naturalWidth(self) -> int:
        """Largeur voulue par les sous-cellules (largeurs reglees + mini des libres), sans pliage."""
        return sum(self._widths) + self._free_min()

    def _apply_widths(self):
        fixed = sum(self._widths)
        shown = list(self._widths)
        if fixed and self._room is not None and fixed + self._free_min() > self._room:
            factor = max(0.0, self._room - self._free_min()) / fixed
            shown = [max(24, int(w * factor)) if w else 0 for w in self._widths]
        self._shown = shown
        last = len(self._order) - 1
        stretch_last = not self._widths[self._order[last]]
        for pos, i in enumerate(self._order):
            width, cell, label = self._shown[i], self._cells[i], self._cap_labels[i]
            self._grid.setColumnMinimumWidth(pos, width)
            if width:
                cell.setFixedWidth(width)
                label.setMinimumWidth(1)          # la legende ne force plus sa largeur de texte
                label.setMaximumWidth(width)
            else:
                cell.setMinimumWidth(0)
                cell.setMaximumWidth(16777215)
                label.setMinimumWidth(0)
                label.setMaximumWidth(16777215)
            self._grid.setColumnStretch(pos, 1 if stretch_last and pos == last else 0)
        self._grid.setColumnStretch(len(self._order), 0 if stretch_last else 1)
        self.updateGeometry()

    def _content_floor(self, index: int) -> int:
        """Largeur mini d'une sous-cellule : celle de son contenu (jamais rogne)."""
        return max(24, self._cells[index].layout().minimumSize().width())

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
        self._apply_widths()                    # largeurs exactes + reste a la derniere libre
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

    def capTexts(self) -> list[str]:
        return list(self._cap_texts)

    def setCapText(self, index: int, text: str, notify: bool = True):
        """Titre (legende) de la sous-cellule `index` ; vide = titre d'origine."""
        text = (text or "").strip().upper() or self._cap_default[index]
        if self._cap_texts[index] == text:
            return
        self._cap_texts[index] = text
        self._cap_labels[index].setText(text)
        self.updateGeometry()
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

    # Ecart entre deux controles EMPILES dans une sous-cellule (toggle d'un cote au-dessus de sa couleur) :
    # 4 px + la marge du dessin du toggle (1 px) + le retrait de la pastille dans son champ (2 px) = 7 px
    # visibles, comme entre la pastille et ses toggles « app » / « sys » (6 px + 1) — demande de
    # l'utilisateur : meme distance au-dessus que de part et d'autre.
    STACK_GAP = 4

    def _arrange(self, index: int):
        cell, (_c, widgets) = self._cells[index], self._parts[index]
        h, v = self._aligns[index]
        lay = cell.layout()
        while lay.count():
            lay.takeAt(0)
        if v in ("center", "bottom"):
            lay.addStretch(1)
        for n, widget in enumerate(widgets):
            if n:
                lay.addSpacing(self.STACK_GAP)
            lay.addWidget(getattr(widget, "_float_slot", None) or widget, 0, _H[h])     # detache : sa place
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
        menu.addAction("Renommer le titre…").triggered.connect(
            lambda: rename_inline(self._cap_labels[index], lambda text: self.setCapText(index, text)))

    def populate_menu(self, menu: QMenu, index: int):
        h, v = self._aligns[index]
        add_align_menus(menu, h, v, lambda k: self.setSubAlign(index, k, self._aligns[index][1]),
                        lambda k: self.setSubAlign(index, self._aligns[index][0], k))
        add_split_menu(self, menu)

    def _index_at(self, x: int) -> int:
        index = self._order[0]
        for i in self._order:
            if x >= self._cells[i].x():
                index = i
        return index

    def contextMenuEvent(self, event):
        menu = Menu(self)
        index = self._index_at(event.pos().x())
        if event.pos().y() < self._CAPTION_H:
            self.populate_caption_menu(menu, index)      # clic droit sur le titre : sa justification
        else:
            self.populate_menu(menu, index)
        add_context_extras(self, menu)
        menu.exec(event.globalPos())
        event.accept()

    # -- peinture : bande de legendes + filets verticaux --

    def _edges(self) -> list[int]:
        """Abscisse du bord gauche de chaque sous-cellule, hors la premiere."""
        return [self._cells[i].x() for i in self._order[1:]]

    def _right_edge(self) -> int | None:
        """Bord droit de la derniere sous-cellule quand elle n'atteint pas le bord de la cellule
        (largeur reglee, place restante dans la colonne vide finale) : il a son filet et se tire."""
        last = self._cells[self._order[-1]]
        right = last.x() + last.width()
        return right if self._widths[self._order[-1]] and right < self.width() - 1 else None

    def paintEvent(self, event):
        p = QPainter(self)
        # Tableaux > Couleur d'entete (cellules) ; a defaut, celle de l'entete des tableaux.
        head = QColor(_TABLE_HEAD.get("cell_bg") or _TABLE_HEAD["bg"] or M["table_head_bg"])
        right = self._right_edge()
        end = self.width() if right is None else right      # bande de legendes jusqu'a la derniere
        p.fillRect(0, 0, end, self._CAPTION_H, head)
        for i in self._selected:
            if i < len(self._cells):
                p.fillRect(self._cells[i].x(), 0, self._cells[i].width(), self._CAPTION_H,
                           _selection_color(56))
        line = _vline_color()
        p.fillRect(0, self._CAPTION_H - 1, end, 1, line)
        for x in self._edges() + ([right] if right is not None else []):
            p.fillRect(x, 0, 1, self.height(), line)
        p.end()

    def event(self, event):
        handled = super().event(event)
        if event.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self.update()           # les filets suivent les cellules apres chaque layout
            if self._badge_cols:
                self._place_width_badges()   # largeur REELLE, connue seulement apres le layout
        return handled

    def _place_width_badges(self):
        """Un encart par sous-cellule redimensionnee, dans SA legende : sa largeur reelle (le minimum
        demande peut etre depasse par le contenu ou par la derniere sous-cellule, extensible)."""
        badges = _width_badges(self, len(self._cells))
        for k, badge in enumerate(badges):
            if k not in self._badge_cols:
                badge.hide()
                continue
            badge.show_on(self._cap_labels[k].geometry(), self._cells[k].width())

    # -- glisser une bordure --

    def _edge_at(self, x: int) -> int | None:
        for k, edge in enumerate(self._edges()):
            if abs(x - edge) <= self._GRAB:
                return self._order[k]          # la sous-cellule situee a GAUCHE de la bordure
        right = self._right_edge()
        if right is not None and abs(x - right) <= self._GRAB:
            return self._order[-1]             # bord droit de la derniere (colonne vide finale)
        return None

    _SNAP = 9

    def _end_drag(self):
        self._drag = None
        self._badge_cols = []
        _hide_width_badges(self)

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
            group = sorted(self._selected) if i in self._selected and len(self._selected) > 1 else [i]
            floor = max(self._content_floor(k) for k in group)    # le plus exigeant du groupe
            width = max(floor, self._snapped(i, max(floor, w0 + global_x - x0)))
            widths = list(self._widths)
            for k in group:                  # plusieurs selectionnees : EXACTEMENT la meme largeur, en direct
                widths[k] = width
            self.setWidths(widths)
            self._badge_cols = group         # encart de largeur dans la legende de chacune, pendant le glissement
            self._grid.activate()
            self.widthsResized.emit()
            self._place_width_badges()
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
            # Deplacer = Ctrl + glisser (demande de l'utilisateur, pour tout deplacement de l'appli).
            if (self._reorder is None and QApplication.keyboardModifiers() & Qt.ControlModifier
                    and (event.position().toPoint() - self._press_pos).manhattanLength() > 6):
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
        # Aucun plancher : la hauteur naturelle = contenu + padding des cellules (padding 0 = ligne collee au texte).
        return max(1, self.rows[i].layout().sizeHint().height())

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


# Tableaux > « Permettre le deplacement des lignes » (pose par la fenetre).
_ROWS_MOVABLE = {"enabled": True}


# ==========================================================================
# « Split au-dessus » (demande de l'utilisateur) : clic droit sur une cellule = couper le tableau
# au-dessus de sa ligne, avec un toggle et l'espace entre les deux parties. Chaque partie garde sa
# bordure complete et ses coins arrondis (_TableFrame.paintEvent, _restyle_table_row) ; memes colonnes.
# ==========================================================================

SPLIT_TEXT = "Split au-dessus"
SPLIT_DEFAULT_SPACE = 15
SPLIT_MAX_SPACE = 200


class _SplitMenuControl(QWidget):
    """Conteneur du toggle et de l'espace du split.

    Dans un QMenu, la ligne d'une QWidgetAction peut récupérer le clic quand
    il tombe dans le vide autour d'un contrôle peint à la main. Toute la zone
    du toggle reste donc cliquable, sans intercepter les clics destinés au
    curseur voisin.
    """

    def __init__(self, toggle: _Toggle, field: QWidget, parent=None):
        super().__init__(parent)
        self.toggle = toggle
        self.label = QLabel(SPLIT_TEXT, self)
        self.label.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.label)
        layout.addWidget(toggle)
        layout.addWidget(field)
        layout.addStretch(1)
        self.setMinimumWidth(self.label.fontMetrics().horizontalAdvance(SPLIT_TEXT) + 220)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.toggle.geometry().contains(event.position().toPoint()):
            self.toggle.setChecked(not self.toggle.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)


def _remove_split_spacers(frame: QWidget) -> None:
    layout = frame.layout()
    for item in list(getattr(frame, "_split_spacers", None) or []):
        layout.removeItem(item)
    frame._split_spacers = []


def apply_row_splits(frame: QWidget, restyle: bool = True) -> None:
    """Pose les coupes retenues (`_CellsState.splits`, lignes LOGIQUES) dans l'ordre d'AFFICHAGE : un
    espace avant chaque ligne coupee (jamais la 1re affichee), et marque les lignes qui ouvrent / ferment
    une partie (style lu par _restyle_table_row)."""
    state = getattr(frame, "_extra_dims", None)
    mover = getattr(state, "rows", None)
    if not isinstance(state, _CellsState) or mover is None:
        return
    _remove_split_spacers(frame)
    layout = frame.layout()
    order = mover.order
    for row in mover.rows:
        row._split_above = row._split_below = False
    spacers = []
    gap_of = {}
    for pos, r in enumerate(order):
        on, space = state.split_of_row(r)
        if not on or pos == 0:
            continue
        row = mover.rows[r]
        row._split_above = True
        mover.rows[order[pos - 1]]._split_below = True
        # +2 : la bordure de chaque partie deborde d'un pixel dans l'espace (contenu en retrait de 1 px).
        item = QSpacerItem(0, space + 2, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.insertItem(layout.indexOf(row), item)
        spacers.append(item)
        gap_of[r] = (item, space)
    # Textes au-dessus des lignes (rien de colle au-dessus : 1re ligne sans entete, ou ligne qui ouvre une
    # partie) : poses dans l'espace, agrandi pour les contenir.
    slots, shown = [], set()
    for pos, r in enumerate(order):
        text = state.above_texts.get(r)
        if not text or not state.can_text_above(r):
            continue
        label = state.above_label(r)
        label.setText(text)
        label.restyle()
        need = label.sizeHint().height() + ABOVE_TEXT_GAP
        row = mover.rows[r]
        if pos == 0:
            row._split_above = True
            item = QSpacerItem(0, need + 2, QSizePolicy.Minimum, QSizePolicy.Fixed)
            layout.insertItem(layout.indexOf(row), item)
            spacers.append(item)
        else:
            item, space = gap_of[r]
            item.changeSize(0, max(space, need) + 2, QSizePolicy.Minimum, QSizePolicy.Fixed)
        label.show()
        slots.append((item, label))
        shown.add(r)
    for r, label in state._above_labels.items():
        if r not in shown:
            label.hide()
    frame._above_slots = slots
    frame._split_spacers = spacers
    frame._refresh_style()
    if restyle:
        _style_flat_table(frame)
    layout.invalidate()
    frame.updateGeometry()
    _reflow_ancestors(frame)
    frame.update()
    if slots:
        frame.installEventFilter(_ABOVE_PLACER)
        QTimer.singleShot(0, lambda f=frame: _place_above_texts(f))


# -- Texte au-dessus d'une ligne (demande de l'utilisateur) : clic droit > « Ajouter un texte au-dessus… »,
# seulement quand rien n'est colle au-dessus de la ligne ; police = Reglages > Tableaux > Texte au dessus. --

ABOVE_TEXT_GAP = 6                  # px entre le texte et la ligne (et au-dessus du texte)
_ABOVE_TEXT_LOOK = {"font": None, "color": "#8d949a"}
_ABOVE_FRAMES: list = []            # tableaux qui ont des textes (restyles quand la police change)


def seed_above_text_look(settings: dict) -> None:
    """Police / couleur des textes au-dessus des lignes (ligne gabarit Tableaux > Texte au dessus)."""
    from settings_menu import _font
    from settings_store import DEFAULT_SETTINGS, _resolve_color_value
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    _ABOVE_TEXT_LOOK["font"] = _font(s, "table_above_text", 11)
    _ABOVE_TEXT_LOOK["color"] = _resolve_color_value(s["table_above_text_font_color"], s.get("colors") or {})
    for frame in list(_ABOVE_FRAMES):
        try:
            apply_row_splits(frame)
        except RuntimeError:                       # tableau detruit
            _ABOVE_FRAMES.remove(frame)


class _AboveText(QLabel):
    """Texte pose au-dessus d'une ligne, hors de la bordure du tableau ; clic droit = modifier / supprimer."""

    def __init__(self, state: "_CellsState", row: int):
        super().__init__(state.frame)
        self._state, self._row = state, row
        self.setObjectName("TableAboveText")

    def restyle(self):
        if _ABOVE_TEXT_LOOK["font"] is None:
            seed_above_text_look({})
        self.setFont(_ABOVE_TEXT_LOOK["font"])
        self.setStyleSheet(f"color: {_ABOVE_TEXT_LOOK['color']}; background: transparent;")

    def contextMenuEvent(self, event):
        menu = Menu(self)
        menu.addAction("Modifier le texte au-dessus…", lambda: self._state.edit_above_text(self._row))
        menu.addAction("Supprimer le texte au-dessus", lambda: self._state.set_above_text(self._row, ""))
        add_context_extras(self, menu)
        menu.exec(event.globalPos())
        event.accept()


def _place_above_texts(frame: QWidget) -> None:
    """Chaque texte au bas de son espace, juste au-dessus de sa ligne, cale sur le padding des cellules."""
    try:
        slots = getattr(frame, "_above_slots", None) or []
        if not slots:
            return
        frame.layout().activate()
        x = 15
        for item, label in slots:
            geo = item.geometry()
            height = label.sizeHint().height()
            label.setGeometry(x, geo.bottom() + 1 - 1 - ABOVE_TEXT_GAP // 2 - height, max(10, frame.width() - 2 * x),
                              height)
            label.raise_()
    except RuntimeError:
        pass


class _AbovePlacer(QObject):
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            QTimer.singleShot(0, lambda f=obj: _place_above_texts(f))
        return False


_ABOVE_PLACER = _AbovePlacer()


def add_split_menu(widget: QWidget, menu: QMenu) -> None:
    """Ligne « Split au-dessus » + toggle + espace (px), en direct, pour la cellule de `widget` (toute
    cellule ou sous-cellule d'un tableau a cellules) ; rien sur la 1re ligne affichee."""
    cell = widget
    while cell is not None and not isinstance(cell, _Cell):
        cell = cell.parentWidget()
    frame = cell.parentWidget() if cell is not None else None
    while frame is not None and not isinstance(getattr(frame, "_extra_dims", None), _CellsState):
        frame = frame.parentWidget()
    if frame is None:
        return
    state = frame._extra_dims
    key = next((k for k, c in state.cells.items() if c is cell), None)
    if state.rows is None or key is None:
        return
    row = int(key[1:].split("c", 1)[0])
    if row not in state.rows.order or state.rows.order.index(row) == 0:
        return
    on, space = state.split_of_row(row)
    toggle = _Toggle(on, show_label=False)
    field = _SliderField(0, SPLIT_MAX_SPACE, space, slider_width=120, box_width=60)
    toggle.toggled.connect(lambda checked: state.set_split(row, checked, field.value()))
    field.valueChanged.connect(lambda value: state.set_split(row, toggle.isChecked(), value))
    box = _SplitMenuControl(toggle, field)
    if menu.actions():
        menu.addSeparator()
    # Le libelle fait partie du controle : ainsi le layout du QMenu reserve
    # explicitement sa largeur avant le toggle, qui ne peut plus le recouvrir.
    menu_row(menu, "", box)


class _RowMover:
    """Deplacement des lignes d'un tableau : Ctrl + glisser sur la PREMIERE cellule (a gauche) d'une
    ligne. Meme retour visuel que les colonnes (_ReorderOverlay, axe vertical). Les lignes gardent leur
    indice LOGIQUE (cles `r<ligne>c<colonne>`, hauteurs) ; seul l'ordre d'affichage change (`order`,
    enregistre dans `row_order`)."""

    def __init__(self, frame: QWidget, head: _ResizableTableHeader, rows: list, cells: list, row_meta: list):
        self.frame, self.head, self.rows, self.cells, self.row_meta = frame, head, rows, cells, row_meta
        self.order: list[int] = list(range(len(rows)))
        self._press: tuple[int, QPoint] | None = None
        self._overlay = None

    # protocole de _ReorderOverlay
    @property
    def _order(self) -> list[int]:
        return self.order

    def _column_spans(self) -> list[tuple[int, int]]:
        spans = []
        for row in self.rows:
            top = row.mapTo(self.frame, QPoint(0, 0)).y()
            spans.append((top, top + row.height()))
        return spans

    def _row_of_first_cell(self, widget) -> int | None:
        first = self.head.order()[0]
        targets = {id(row_cells[first]): r for r, row_cells in enumerate(self.cells) if first < len(row_cells)}
        while widget is not None and widget is not self.frame:
            if id(widget) in targets:
                return targets[id(widget)]
            widget = widget.parentWidget()
        return None

    def press(self, obj, event) -> bool:
        if not _ROWS_MOVABLE["enabled"] or not (event.modifiers() & Qt.ControlModifier) or len(self.rows) < 2:
            return False
        r = self._row_of_first_cell(obj)
        if r is None:
            return False
        self._press = (r, event.globalPosition().toPoint())
        self.frame.setCursor(Qt.ClosedHandCursor)
        return True

    def move(self, gpos: QPoint) -> bool:
        if self._press is None:
            return False
        r, start = self._press
        if self._overlay is None:
            if (gpos - start).manhattanLength() <= 6:
                return True
            row = self.rows[r]
            top = row.mapTo(self.frame, QPoint(0, 0)).y()
            ghost = self.frame.grab(QRect(0, top, self.frame.width(), row.height()))
            self._overlay = _ReorderOverlay(self.frame, self, r, ghost, 0,
                                            self.frame.mapFromGlobal(start).y() - top, axis="y")
        self._overlay.follow(self.frame.mapFromGlobal(gpos).y())
        return True

    def release(self) -> bool:
        if self._press is None:
            return False
        self._press = None
        self.frame.unsetCursor()
        overlay, self._overlay = self._overlay, None
        if overlay is None:
            return True
        gap = overlay.target
        overlay.hide()
        overlay.deleteLater()
        if gap is not None:
            order = [i for i in self.order if i != overlay.source]
            order.insert(gap - (1 if gap > self.order.index(overlay.source) else 0), overlay.source)
            self.set_order(order)
        return True

    def set_order(self, order: list[int], notify: bool = True):
        order = [int(i) for i in order]
        if sorted(order) != list(range(len(self.rows))) or order == self.order:
            return
        self.order = order
        layout = self.frame.layout()
        base = min(layout.indexOf(row) for row in self.rows)
        _remove_split_spacers(self.frame)          # repositionnes apres le nouvel ordre
        base = min(layout.indexOf(row) for row in self.rows)
        for row in self.rows:
            layout.removeWidget(row)
        for pos, r in enumerate(order):
            layout.insertWidget(base + pos, self.rows[r])
        # Style des lignes selon leur place AFFICHEE (alternance, filet du haut, arrondi du bas).
        by_row = {id(meta[0]): meta for meta in self.row_meta}
        self.row_meta[:] = [(self.rows[r], by_row[id(self.rows[r])][1], pos == 0) for pos, r in enumerate(order)]
        apply_row_splits(self.frame, restyle=False)  # la coupe suit sa ligne (indice logique)
        _style_flat_table(self.frame)
        self.frame.updateGeometry()
        _reflow_ancestors(self.frame)
        if notify:
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
        self.mover: _RowMover | None = None                   # Ctrl + glisser la 1re cellule : deplacer la ligne

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
        mover = self.mover
        if mover is not None:
            if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and mover.press(obj, event):
                return True
            if etype == QEvent.MouseMove and mover.move(gpos):
                return True
            if etype == QEvent.MouseButtonRelease and mover.release():
                return True
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
# Objets libres (demande de l'utilisateur) : dans un tableau, Ctrl+Maj + glisser un objet d'une ligne
# (curseur, liste, pastille, toggle, zone de saisie...) = le DEPLACER librement dans sa cellule ;
# Ctrl+Maj+X + glisser un de ses bords = le REDIMENSIONNER, ce bord s'aimantant aux extremites des
# objets de la ligne sous le curseur. Retenu avec les dimensions du tableau (`objects`).
# ==========================================================================

OBJECT_SNAP = 9          # px : distance d'aimantation d'un bord
_OBJECT_MIN = 8          # px : plus petite taille d'un objet redimensionne


class _FloatSlot(QWidget):
    """Place laissee dans la mise en page par un objet DETACHE : garde sa taille d'origine (la ligne ne
    bouge pas) ; l'objet, devenu enfant de la cellule (sinon un champ compose, a peine plus grand que lui,
    le rognerait), se pose par-dessus avec son decalage et sa taille (`_place_object`)."""

    def __init__(self, obj: QWidget, size):
        super().__init__()
        self._obj = obj
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(size)


def _is_object(widget: QWidget) -> bool:
    """Un OBJET de ligne : un controle (bouton, zone de saisie, liste...) ou un widget peint sans mise en
    page (curseur, pastille, etoiles...) ; jamais un conteneur, une legende de cellule divisee, une place ni
    un widget marque `_no_object` (case d'icone, ecart d'une ligne de menu)."""
    if isinstance(widget, (_FloatSlot, SplitCell)) or getattr(widget, "_fill_cell", False) \
            or getattr(widget, "_split_owner", None) is not None or getattr(widget, "_no_object", False):
        return False
    if isinstance(widget, QLabel) and isinstance(widget.parentWidget(), SplitCell):
        return False
    if getattr(widget, "_free_object", False):     # conteneur vu comme UN objet (case de valeur d'un curseur)
        return True
    return widget.layout() is None or isinstance(widget, (QAbstractButton, QLineEdit, QAbstractSpinBox, QComboBox))


def _cell_of(widget):
    """HOTE des objets libres au-dessus de `widget` : cellule d'un tableau, ou tout widget qui porte
    `_objects_host` (() -> (magasin, cle de l'hote) ; ex. ligne de menu contextuel, settings_menu)."""
    while widget is not None and not isinstance(widget, _Cell) and getattr(widget, "_objects_host", None) is None:
        widget = widget.parentWidget()
    return widget


def set_host_object(store, host: QWidget, key: str, path: str, rec) -> None:
    """Pose la place / taille enregistree `rec` (None ou zeros = d'origine) de l'objet `path` de `host` ;
    `store.objects[key]` suit. Commun aux tableaux (_CellsState) et aux menus contextuels."""
    obj = _resolve_object(host, path) if host is not None and path else None
    rec = [int(v) for v in rec][:4] if rec else []
    if obj is None:
        store.objects.pop(key, None)
        return
    if not any(rec):
        _unfloat_object(obj)
        store.objects.pop(key, None)
        return
    if not _float_object(host, obj):
        return
    obj._float_rec = rec + [0] * (4 - len(rec))
    store.objects[key] = list(obj._float_rec)
    _place_object(obj)


def _object_at(widget: QWidget):
    """(cellule, objet) sous un clic : le PLUS HAUT objet entre la cellule et le widget clique."""
    cell = _cell_of(widget)
    if cell is None:
        return None, None
    chain = []
    while widget is not None and widget is not cell:
        chain.append(widget)
        widget = widget.parentWidget()
    for candidate in reversed(chain):
        if _is_object(candidate):
            return cell, candidate
    return cell, None


def _widget_items(layout) -> list:
    return [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget() is not None]


def _object_path(cell, obj: QWidget):
    """Chemin STABLE de l'objet dans sa cellule (enregistre) : rang parmi les widgets de chaque mise en
    page ; sous-cellule d'une cellule divisee = « s<indice logique> » (son ordre affiche peut changer)."""
    widget = getattr(obj, "_float_slot", None) or obj
    parts = []
    while widget is not cell:
        parent = widget.parentWidget()
        if parent is None:
            return None
        if isinstance(parent, SplitCell) and getattr(widget, "_split_owner", None) is parent:
            parts.append(f"s{widget._split_index}")
        else:
            items = _widget_items(parent.layout()) if parent.layout() is not None else []
            if widget not in items:
                return None
            parts.append(str(items.index(widget)))
        widget = parent
    return "/".join(reversed(parts))


def _resolve_object(cell, path: str):
    widget = cell
    for part in path.split("/"):
        if part.startswith("s") and isinstance(widget, SplitCell):
            index = int(part[1:])
            if index >= len(widget._cells):
                return None
            widget = widget._cells[index]
            continue
        items = _widget_items(widget.layout()) if widget.layout() is not None and part.isdigit() else []
        if not part.isdigit() or int(part) >= len(items):
            return None
        widget = items[int(part)]
    return widget._obj if isinstance(widget, _FloatSlot) else widget


class _FloatWatcher(QObject):
    """Recale les objets detaches quand leur place, leur cellule ou leur visibilite change."""

    def eventFilter(self, obj, event):
        etype = event.type()
        if isinstance(obj, _FloatSlot) and etype in (QEvent.Move, QEvent.Resize):
            _place_object(obj._obj)
        elif (isinstance(obj, _Cell) or getattr(obj, "_objects_host", None) is not None) and etype == QEvent.Resize:
            for child in obj.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
                if getattr(child, "_float_slot", None) is not None:
                    _place_object(child)
        elif etype == QEvent.Resize and getattr(obj, "_float_slot", None) is not None                 and not getattr(obj, "_float_placing", False):
            # L'objet a change de taille de lui-meme (ex. style d'un toggle) : c'est sa nouvelle taille
            # d'origine, sa place la suit (sinon il etait peint dans l'ancienne : toggle coupe, signale).
            obj._float_orig = (obj.minimumSize(), obj.maximumSize())
            dx, dy, w, h = obj._float_rec
            slot = obj._float_slot
            slot.setFixedSize(event.size().width() if not w else slot.width(),
                              event.size().height() if not h else slot.height())
            _place_object(obj)
        elif etype in (QEvent.Show, QEvent.Hide) and getattr(obj, "_float_slot", None) is not None:
            obj._float_slot.setVisible(etype == QEvent.Show)     # objet masque par son champ : sa place aussi
        return False


_FLOAT_WATCHER = _FloatWatcher()


def _float_object(cell, obj: QWidget) -> bool:
    """Detache `obj` de sa mise en page (une place de meme taille la garde) et le rend enfant de la cellule."""
    if getattr(obj, "_float_slot", None) is not None:
        return True
    parent = obj.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is None or layout.indexOf(obj) < 0:
        return False
    visible = not obj.isHidden()
    size = obj.size() if obj.width() > 0 and obj.height() > 0 else obj.sizeHint()
    slot = _FloatSlot(obj, size)
    layout.replaceWidget(obj, slot)                 # meme place, meme justification
    obj._float_orig = (obj.minimumSize(), obj.maximumSize())
    obj._float_rec = [0, 0, 0, 0]                   # decalage x, y ; largeur, hauteur (0 = d'origine)
    obj.setParent(cell)
    obj._float_slot = slot
    slot.setVisible(visible)
    obj.setVisible(visible)
    obj.raise_()
    slot.installEventFilter(_FLOAT_WATCHER)
    obj.installEventFilter(_FLOAT_WATCHER)
    cell.installEventFilter(_FLOAT_WATCHER)
    _place_object(obj)
    return True


def _unfloat_object(obj: QWidget) -> None:
    """Remet l'objet a sa place dans sa mise en page, a sa taille d'origine."""
    slot = getattr(obj, "_float_slot", None)
    if slot is None:
        return
    obj.removeEventFilter(_FLOAT_WATCHER)
    low, high = obj._float_orig
    obj.setMinimumSize(low)
    obj.setMaximumSize(high)
    visible = not obj.isHidden()
    parent = slot.parentWidget()
    obj._float_slot = None
    obj.setParent(parent)
    parent.layout().replaceWidget(slot, obj)
    obj.setVisible(visible)
    slot.hide()
    slot.deleteLater()


def _place_object(obj: QWidget) -> None:
    slot = getattr(obj, "_float_slot", None)
    cell = obj.parentWidget()
    if slot is None or cell is None:
        return
    obj._float_placing = True                        # nos propres changements (voir _FloatWatcher)
    try:
        _place_object_now(obj, slot, cell)
    finally:
        obj._float_placing = False


def _place_object_now(obj: QWidget, slot: QWidget, cell: QWidget) -> None:
    dx, dy, w, h = obj._float_rec
    low, high = obj._float_orig
    base = slot.mapTo(cell, QPoint(0, 0))
    width = min(w or slot.width(), max(1, cell.width()))
    height = min(h or slot.height(), max(1, cell.height()))
    if w:
        obj.setFixedWidth(width)
    else:
        obj.setMinimumWidth(low.width())
        obj.setMaximumWidth(high.width())
    if h:
        obj.setFixedHeight(height)
    else:
        obj.setMinimumHeight(low.height())
        obj.setMaximumHeight(high.height())
    # Libre DANS SA CELLULE : jamais au-dela de ses bords.
    x = max(0, min(base.x() + dx, cell.width() - width))
    y = max(0, min(base.y() + dy, cell.height() - height))
    obj.setGeometry(x, y, width, height)


def _objects_in(widget: QWidget, out: list) -> list:
    for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        if child.isHidden() or isinstance(child, _FloatSlot):
            continue
        if _is_object(child):
            out.append(child)
        else:
            _objects_in(child, out)
    return out


def _state_of(cell):
    """(etat du tableau, cle « r<l>c<c> » de la cellule) ou (None, None) ; autre hote : son magasin."""
    hook = getattr(cell, "_objects_host", None)
    if hook is not None:
        return hook()
    widget = cell
    while widget is not None:
        state = getattr(widget, "_extra_dims", None)
        if isinstance(state, _CellsState):
            key = next((k for k, c in state.cells.items() if c is cell), None)
            return (state, key) if key is not None else (None, None)
        widget = widget.parentWidget()
    return None, None


# Ctrl+Z (demande de l'utilisateur) : annule le dernier deplacement / redimensionnement d'objet de la
# fenetre, ou une remise en place. Entrees : (etat du tableau, cle de l'objet, place d'avant ou None).
_OBJECT_UNDO: list = []
_OBJECT_UNDO_MAX = 200


def push_object_undo(state, key: str, before) -> None:
    _OBJECT_UNDO.append((state, key, list(before) if before else None))
    del _OBJECT_UNDO[:-_OBJECT_UNDO_MAX]


def undo_object_change(window: QWidget) -> bool:
    """Annule le dernier changement d'objet d'un tableau de `window` (les autres fenetres gardent les leurs)."""
    for i in range(len(_OBJECT_UNDO) - 1, -1, -1):
        state, key, before = _OBJECT_UNDO[i]
        try:
            mine = state.owner_window() is window
        except RuntimeError:                       # tableau / menu detruit : entree perimee
            del _OBJECT_UNDO[i]
            continue
        if not mine:
            continue
        del _OBJECT_UNDO[i]
        state.set_object(key, before)
        state.commit()
        return True
    return False


def _ensure_undo_shortcut(window: QWidget) -> None:
    if window is None or getattr(window, "_object_undo_shortcut", None) is not None:
        return
    shortcut = QShortcut(QKeySequence.Undo, window)
    shortcut.setContext(Qt.WindowShortcut)
    shortcut.activated.connect(lambda w=window: undo_object_change(w))
    window._object_undo_shortcut = shortcut


EDGE_GRAB = 8            # px : un bord est pris dans cette distance


def _edge_at(pos: QPoint, width: int, height: int) -> str:
    """Bord tire par Ctrl+Maj+X : gauche / droite dans EDGE_GRAB, sinon haut / bas dans EDGE_GRAB, sinon le
    bord gauche ou droit du cote du clic. (Le plus proche des 4 donnait le haut / bas d'un objet peu haut —
    zone de saisie d'un menu : 25 px — des qu'on cliquait a plus de 12 px du bord droit, signale.)"""
    left, right = abs(pos.x()), abs(width - pos.x())
    top, bottom = abs(pos.y()), abs(height - pos.y())
    if min(left, right) <= EDGE_GRAB:
        return "left" if left <= right else "right"
    if min(top, bottom) <= EDGE_GRAB:
        return "top" if top <= bottom else "bottom"
    return "left" if pos.x() < width / 2 else "right"


def resize_key_held() -> bool:
    """X tenue : Ctrl+Maj+X + glisser = redimensionner (demande de l'utilisateur, a la place d'Alt). Qt ne
    donne l'etat que des modificateurs : touche lue chez Windows (GetAsyncKeyState), ou vue pendant un geste."""
    if Qt.Key_X in OBJECT_GESTURES._axis_keys:
        return True
    import sys
    if sys.platform == "win32":
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x58) & 0x8000)      # VK « X »
    return False


class _ObjectGestures(QObject):
    """Filtre pose sur tous les widgets des tableaux a cellules : Ctrl+Maj + glisser = deplacer l'objet
    (+ Q tenue : verticalement seulement ; + Z tenue : horizontalement seulement), Ctrl+Maj+X + glisser =
    tirer son bord le plus proche du clic (aimante). L'objet tire est a `DRAG_GHOST_OPACITY` (regle de
    l'appli) ; rien ne change avant 3 px de mouvement. Ctrl+Z annule (undo_object_change)."""

    def __init__(self):
        super().__init__()
        self._drag = None
        self._axis_keys: set = set()          # Q / Z tenues pendant un deplacement

    def _key_event(self, event) -> bool:
        """Q / Z pendant un deplacement (filtre d'application, pose le temps du geste) : contrainte d'axe."""
        if event.key() not in (Qt.Key_Q, Qt.Key_Z, Qt.Key_X):    # X : touche du redimensionnement
            return False
        if event.type() == QEvent.KeyPress:
            self._axis_keys.add(event.key())
        elif not event.isAutoRepeat():
            self._axis_keys.discard(event.key())
        if self._drag is not None and self._drag.get("last") is not None:
            self._move(self._drag["last"])
        return True                            # ni texte tape ni raccourci pendant le geste

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype in (QEvent.KeyPress, QEvent.KeyRelease):
            return self._key_event(event) if self._drag is not None else False
        if obj is QApplication.instance():
            return False                       # filtre d'application : touches seulement
        if etype not in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease,
                         QEvent.MouseButtonDblClick):
            return False
        drag = self._drag
        if drag is None:
            if etype != QEvent.MouseButtonPress or event.button() != Qt.LeftButton:
                return False
            mods = event.modifiers()
            if not (mods & Qt.ControlModifier and mods & Qt.ShiftModifier):
                return False
            return self._press(obj, event, resize_key_held())
        gpos = event.globalPosition().toPoint()
        if etype == QEvent.MouseMove:
            self._move(gpos)
        elif etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._release()
        return True

    def _press(self, widget, event, resize: bool) -> bool:
        cell, target = _object_at(widget)
        if target is None:
            return False
        state, cell_key = _state_of(cell)
        path = _object_path(cell, target) if state is not None else None
        if path is None:
            return False
        gpos = event.globalPosition().toPoint()
        edge = None
        if resize:
            top_left = target.mapToGlobal(QPoint(0, 0))
            edge = _edge_at(gpos - top_left, target.width(), target.height())
        key = f"{cell_key}|{path}"
        self._drag = {"cell": cell, "obj": target, "state": state, "key": key, "start": gpos,
                      "edge": edge, "moved": False, "before": state.objects.get(key), "last": None}
        self._axis_keys = set()
        QApplication.instance().installEventFilter(self)      # Q / Z : touches lues pendant le geste
        _ensure_undo_shortcut(cell.window())
        cursor = (Qt.SizeHorCursor if edge in ("left", "right") else Qt.SizeVerCursor) if edge else Qt.ClosedHandCursor
        QApplication.setOverrideCursor(cursor)
        return True

    def _move(self, gpos: QPoint):
        drag = self._drag
        drag["last"] = gpos
        obj, cell = drag["obj"], drag["cell"]
        delta = gpos - drag["start"]
        if drag["edge"] is None:                      # deplacement : Q = vertical seul, Z = horizontal seul
            if Qt.Key_Q in self._axis_keys:
                delta.setX(0)
            elif Qt.Key_Z in self._axis_keys:
                delta.setY(0)
        if not drag["moved"]:
            if (gpos - drag["start"]).manhattanLength() < 3 or not _float_object(cell, obj):
                return
            drag["moved"] = True
            drag["rect0"] = obj.geometry()
            drag["base"] = obj._float_slot.mapTo(cell, QPoint(0, 0))
            if obj.graphicsEffect() is None:              # objet tire : 75 % d'opacite (regle de l'appli)
                ghost = QGraphicsOpacityEffect(obj)
                ghost.setOpacity(DRAG_GHOST_OPACITY)
                obj.setGraphicsEffect(ghost)
                drag["ghost"] = True
        rect = QRect(drag["rect0"])
        base = drag["base"]
        edge = drag["edge"]
        if edge is None:
            # Deplacement, AIMANTE (demande de l'utilisateur) : ses bords collent a ceux des objets de la ligne
            # sous le curseur ; seulement sur l'axe libre (Q = vertical seul, Z = horizontal seul).
            rect.moveTo(rect.topLeft() + delta)
            origin = cell.mapToGlobal(QPoint(0, 0))
            if Qt.Key_Q not in self._axis_keys:
                rect.translate(self._snap_shift(origin.x() + rect.left(), origin.x() + rect.left() + rect.width(),
                                                True, gpos, obj, drag["state"]), 0)
            if Qt.Key_Z not in self._axis_keys:
                rect.translate(0, self._snap_shift(origin.y() + rect.top(), origin.y() + rect.top() + rect.height(),
                                                   False, gpos, obj, drag["state"]))
        else:
            horizontal = edge in ("left", "right")
            # Bord tire, en coordonnees globales, aimante aux objets de la ligne sous le curseur.
            origin = cell.mapToGlobal(QPoint(0, 0))
            if horizontal:
                start = rect.left() if edge == "left" else rect.left() + rect.width()
                value = origin.x() + start + delta.x()
            else:
                start = rect.top() if edge == "top" else rect.top() + rect.height()
                value = origin.y() + start + delta.y()
            value = self._snap(value, horizontal, gpos, obj, drag["state"])
            local = value - (origin.x() if horizontal else origin.y())
            if edge == "left":
                right = rect.left() + rect.width()
                local = max(0, min(local, right - _OBJECT_MIN))
                rect = QRect(local, rect.top(), right - local, rect.height())
            elif edge == "right":
                local = min(cell.width(), max(local, rect.left() + _OBJECT_MIN))
                rect.setWidth(local - rect.left())
            elif edge == "top":
                bottom = rect.top() + rect.height()
                local = max(0, min(local, bottom - _OBJECT_MIN))
                rect = QRect(rect.left(), local, rect.width(), bottom - local)
            else:
                local = min(cell.height(), max(local, rect.top() + _OBJECT_MIN))
                rect.setHeight(local - rect.top())
        rec = list(obj._float_rec)
        rec[0], rec[1] = rect.left() - base.x(), rect.top() - base.y()
        if edge in ("left", "right"):
            rec[2] = rect.width()
        elif edge in ("top", "bottom"):
            rec[3] = rect.height()
        obj._float_rec = rec
        _place_object(obj)

    @classmethod
    def _snap_shift(cls, start: int, end: int, horizontal: bool, gpos: QPoint, obj: QWidget, state) -> int:
        """Decalage qui colle le bord `start` ou `end` (le plus proche) a un repere de la ligne ; 0 sinon."""
        marks = cls._marks(horizontal, gpos, obj, state)
        best = None
        for edge in (start, end):
            for mark in marks:
                if abs(mark - edge) <= OBJECT_SNAP and (best is None or abs(mark - edge) < abs(best)):
                    best = mark - edge
        return best or 0

    @classmethod
    def _snap(cls, value: int, horizontal: bool, gpos: QPoint, obj: QWidget, state) -> int:
        marks = cls._marks(horizontal, gpos, obj, state)
        best = min(marks, key=lambda m: abs(m - value), default=None)
        return best if best is not None and abs(best - value) <= OBJECT_SNAP else value

    @staticmethod
    def _marks(horizontal: bool, gpos: QPoint, obj: QWidget, state) -> list:
        """Reperes d'aimantation (globaux) : bords des objets de la ligne sous le curseur, sauf `obj`."""
        rows = state.snap_rows()
        row = next((r for r in rows if r.isVisible()
                    and r.mapToGlobal(QPoint(0, 0)).y() <= gpos.y() < r.mapToGlobal(QPoint(0, r.height())).y()),
                   None)
        if row is None:
            return []
        marks = []
        for other in _objects_in(row, []):
            if other is obj:
                continue
            top_left = other.mapToGlobal(QPoint(0, 0))
            marks += ([top_left.x(), top_left.x() + other.width()] if horizontal
                      else [top_left.y(), top_left.y() + other.height()])
        return marks

    def _release(self):
        drag, self._drag = self._drag, None
        QApplication.instance().removeEventFilter(self)
        self._axis_keys = set()
        QApplication.restoreOverrideCursor()
        if not drag["moved"]:
            return
        obj = drag["obj"]
        if drag.get("ghost"):
            obj.setGraphicsEffect(None)
        state = drag["state"]
        if list(obj._float_rec) != list(drag["before"] or [0, 0, 0, 0]):
            push_object_undo(state, drag["key"], drag["before"])        # Ctrl+Z
        state.objects[drag["key"]] = list(obj._float_rec)
        state.commit()


OBJECT_GESTURES = _ObjectGestures()


def watch_object_gestures(root: QWidget) -> None:
    """Branche les gestes des objets libres sur `root` et tout ce qu'il contient."""
    for widget in [root, *root.findChildren(QWidget)]:
        widget.installEventFilter(OBJECT_GESTURES)

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
        self.head_titles: list[str] = []      # titres d'origine des colonnes
        self.on_head_align: Callable | None = None
        # « Split au-dessus » : ligne LOGIQUE -> espace (px) ; une valeur negative = coupe eteinte (la
        # valeur est gardee pour quand on la rallume). Voir apply_row_splits.
        self.splits: dict[int, int] = {}
        self.frame: QWidget | None = None
        # Objets libres : « r<l>c<c>|<chemin> » -> [decalage x, y, largeur, hauteur] (0 = d'origine).
        self.objects: dict[str, list[int]] = {}
        self.head_hidden = False                   # clic droit > « Supprimer l'entete »
        self.above_texts: dict[int, str] = {}      # ligne LOGIQUE -> texte pose au-dessus
        self._above_labels: dict = {}

    # -- entete supprime, textes au-dessus des lignes --

    def set_head_hidden(self, hidden: bool, notify: bool = True) -> None:
        hidden = bool(hidden)
        if self.head is not None:
            self.head.setVisible(not hidden)
        self.head_hidden = hidden
        if self.frame is not None:
            apply_row_splits(self.frame)              # 1re ligne : coins hauts, texte possible
            if notify:
                self.frame.dimsChanged.emit()

    def can_text_above(self, row: int) -> bool:
        """Rien de colle au-dessus de la ligne : 1re ligne affichee d'un tableau sans entete, ou ligne qui
        ouvre une partie (« Split au-dessus » allume)."""
        if self.rows is None or row not in self.rows.order:
            return False
        if self.rows.order.index(row) == 0:
            return self.head_hidden or self.head is None
        return self.split_of_row(row)[0]

    def above_label(self, row: int) -> "_AboveText":
        label = self._above_labels.get(row)
        if label is None:
            label = self._above_labels[row] = _AboveText(self, row)
            if self.frame not in _ABOVE_FRAMES:
                _ABOVE_FRAMES.append(self.frame)
        return label

    def set_above_text(self, row: int, text: str, notify: bool = True) -> None:
        text = (text or "").strip()
        if text:
            self.above_texts[int(row)] = text
        else:
            self.above_texts.pop(int(row), None)
        if self.frame is not None:
            apply_row_splits(self.frame)
            if notify:
                self.frame.dimsChanged.emit()

    def edit_above_text(self, row: int) -> None:
        """Saisie SUR PLACE du texte (zone de saisie des reglages) ; vide = texte retire."""
        if row not in self.above_texts:
            self.set_above_text(row, "Texte", notify=False)
        label = self._above_labels.get(row)
        if label is None:
            return
        _place_above_texts(self.frame)
        rename_inline(label, lambda text, r=row: self.set_above_text(r, text))

    def set_object(self, key: str, rec) -> None:
        """Place / taille d'un objet de ligne (None ou zeros = sa place d'origine)."""
        cell_key, _sep, path = key.partition("|")
        set_host_object(self, self.cells.get(cell_key), key, path, rec)

    # magasin des objets libres (avec set_object / objects) : fenetre (Ctrl+Z), enregistrement, aimantation
    def owner_window(self):
        return self.frame.window() if self.frame is not None else None

    def commit(self) -> None:
        if self.frame is not None:
            self.frame.dimsChanged.emit()

    def snap_rows(self) -> list:
        return self.heights.rows if self.heights is not None else []

    def set_split(self, row: int, enabled: bool, space: int, notify: bool = True) -> None:
        space = max(0, int(space))
        self.splits[int(row)] = space if enabled else -max(1, space)
        if self.frame is not None:
            apply_row_splits(self.frame)
            if notify:
                self.frame.dimsChanged.emit()

    def split_of_row(self, row: int) -> tuple[bool, int]:
        """(coupe allumee, espace en px) de la ligne logique `row`."""
        value = self.splits.get(int(row))
        if value is None:
            return False, SPLIT_DEFAULT_SPACE
        return value >= 0, abs(value)

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
        if self.head is not None:
            titles = {str(i): label.text() for i, label in enumerate(self.head._cells)
                      if label.text() != self.head_titles[i]}
            if titles:
                out["head_titles"] = titles
        renamed = {k: {str(i): t for i, t in enumerate(split_of(c.content()).capTexts())
                       if t != split_of(c.content())._cap_default[i]}
                   for k, c in self.cells.items() if split_of(c.content())}
        renamed = {k: v for k, v in renamed.items() if v}
        if renamed:
            out["split_titles"] = renamed
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
        if self.rows is not None and self.rows.order != sorted(self.rows.order):
            out["row_order"] = list(self.rows.order)
        if self.heights is not None:
            if any(self.heights.user):
                out["row_heights"] = list(self.heights.user)
            if self.heights.equal:
                out["equal_rows"] = True
        if self.splits:
            out["row_splits"] = {str(r): v for r, v in sorted(self.splits.items())}
        objects = {k: list(v) for k, v in self.objects.items() if any(v)}
        if objects:
            out["objects"] = objects
        if self.head_hidden:
            out["head_hidden"] = True
        if self.above_texts:
            out["above_texts"] = {str(r): t for r, t in sorted(self.above_texts.items())}
        return out

    def head_aligns(self) -> list[str]:
        out = []
        for label in self.head._cells:
            flag = label.alignment()
            out.append("right" if flag & Qt.AlignRight else "center" if flag & Qt.AlignHCenter else "left")
        return out

    def set_head_title(self, index: int, text: str, notify: bool = True) -> None:
        """Titre de la colonne `index` (renommage : clic droit sur l'entete) ; vide = titre d'origine."""
        text = (text or "").strip().upper() or self.head_titles[index]
        label = self.head._cells[index]
        if label.text() == text:
            return
        label.setText(text)
        self.head._titles[index] = text
        if notify and self.on_head_align is not None:
            self.on_head_align()

    def set_head_align(self, index: int, key: str, notify: bool = True) -> None:
        self.head._cells[index].setAlignment(_H[key] | Qt.AlignVCenter)
        if notify and self.on_head_align is not None:
            self.on_head_align()

    reflow: Callable | None = None
    after_apply: Callable | None = None    # apres restauration : les cellules divisees se plient aux colonnes
    rows: "_RowMover | None" = None        # ordre d'affichage des lignes

    def apply(self, dims: dict):
        order = dims.get("col_order")
        if self.head is not None and isinstance(order, list):
            self.head.setOrder(order, notify=False)
        elif self.head is not None:
            self.head.setOrder(list(range(len(self.head_default))), notify=False)
        if self.reflow is not None:
            self.reflow()
        if self.rows is not None:
            saved = dims.get("row_order")
            self.rows.set_order(saved if isinstance(saved, list) else list(range(len(self.rows.rows))), notify=False)
        head_hidden = bool(dims.get("head_hidden", False))
        texts = {}
        for key, value in (dims.get("above_texts") or {}).items():
            try:
                if str(value).strip():
                    texts[int(key)] = str(value).strip()
            except (TypeError, ValueError):
                pass
        relayout = head_hidden != self.head_hidden or texts != self.above_texts
        if head_hidden != self.head_hidden and self.head is not None:
            self.head.setVisible(not head_hidden)
        self.head_hidden, self.above_texts = head_hidden, texts
        splits = {}
        for key, value in (dims.get("row_splits") or {}).items():
            try:
                splits[int(key)] = int(value)
            except (TypeError, ValueError):
                pass
        if splits != self.splits or relayout:
            self.splits = splits
            if self.frame is not None:
                apply_row_splits(self.frame)
        for i in range(len(self.head_default) if self.head is not None else 0):
            saved = (dims.get("head_align") or {}).get(str(i))
            self.set_head_align(i, saved if saved in _H else self.head_default[i], notify=False)
        for i in range(len(self.head_titles) if self.head is not None else 0):
            self.set_head_title(i, str((dims.get("head_titles") or {}).get(str(i)) or ""), notify=False)
        saved_titles = dims.get("split_titles") or {}
        for key, cell in self.cells.items():
            split = split_of(cell.content())
            if split is not None:
                titles = saved_titles.get(key) or {}
                for i in range(len(split._cells)):
                    split.setCapText(i, str(titles.get(str(i)) or ""), notify=False)
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
        saved_objects = dims.get("objects") or {}
        for key in [k for k in self.objects if k not in saved_objects]:
            self.set_object(key, None)
        for key, rec in saved_objects.items():
            if isinstance(rec, list):
                self.set_object(key, rec)
        heights = self.heights
        if heights is not None:
            saved = dims.get("row_heights") or []
            heights.user = [int(saved[i]) if i < len(saved) else 0 for i in range(len(heights.rows))]
            heights.equal = bool(dims.get("equal_rows", False))
            heights.apply()
        if self.after_apply is not None:
            self.after_apply()


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
    state.head_titles = [label.text() for label in head._cells]
    state.on_head_align = frame.dimsChanged.emit
    frame._extra_dims = state
    state.frame = frame                    # « Split au-dessus » : coupes posees sur ce cadre
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
            row_l.addWidget(cell, 0)             # colonnes libres (voir plus bas) : largeur figee partout
            column_cells.setdefault(c, []).append(cell)
            grips.watch(cell)
            cell.alignChanged.connect(frame.dimsChanged)
            grew = getattr(widget, "contentGrew", None)       # contenu agrandi par une action (ex. carte ajoutee)
            if grew is not None:
                grew.connect(lambda c=c: grow_to_content(c))
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

    # -- Colonnes LIBRES : aucune colonne n'est contrainte par une autre ; le tableau prend la somme
    # de ses colonnes (et la page defile a l'horizontale s'il le faut). --
    def content_min(c: int) -> int:
        """Plus large contenu des cellules d'une colonne : sert a caler la colonne quand on tire une
        SOUS-CELLULE (jamais de plancher quand on tire la colonne elle-meme, voir fit_splits)."""
        widest = 0
        for cell in column_cells.get(c, []):
            m = cell.layout().contentsMargins()
            split = split_of(cell.content())
            need = split.naturalWidth() if split is not None else cell.content().minimumSizeHint().width()
            widest = max(widest, need + m.left() + m.right())
        return widest

    def natural(c: int) -> int:
        """Largeur de depart d'une ancienne colonne extensible : son contenu (au repos) et son titre."""
        hints = [cell.sizeHint().width() for cell in column_cells.get(c, [])]
        return max([head._cells[c].sizeHint().width(), 120] + hints) + 28

    head.setFreeColumns({c: natural(c) for c, (_t, w) in enumerate(columns) if not w})

    def fit_columns():
        m = frame.layout().contentsMargins()
        frame.setFixedWidth(sum(head._widths) + m.left() + m.right())

    def legacy_dims(dims: dict) -> dict:
        """Dimensions enregistrees avant les colonnes libres : une colonne extensible (0) recoit ce
        qu'il lui restait de la largeur du tableau enregistree."""
        cols = list(dims.get("cols") or [])
        zeros = [i for i in head._stretch_origin if i < len(cols) and not cols[i]]
        width = int(dims.get("width") or 0)
        if not zeros or not width:
            return dims
        parent = frame.parentWidget()        # l'ancien tableau ne depassait pas la place disponible
        if parent is not None and parent.width() - frame.x() > 200:
            width = min(width, parent.contentsRect().right() + 1 - frame.x())
        m = frame.layout().contentsMargins()
        others = sum(cols[i] if i < len(cols) and cols[i] else head._widths[i]
                     for i in range(len(head._widths)) if i not in zeros)
        each = max(head._FREE_MIN, (width - m.left() - m.right() - others) // len(zeros))
        for i in zeros:
            cols[i] = each
        return dict(dims, cols=cols)

    frame._fit_columns = fit_columns
    frame._legacy_dims = legacy_dims
    frame.setWidthResizable(False)
    head.resized.connect(lambda *_a: fit_columns())
    fit_columns()

    def grow_for_split(c: int):
        """Sous-cellule redimensionnee : sa colonne (donc le tableau) se cale sur la plus large de ses
        cellules divisees — elle grandit ET retrecit — au lieu de serrer ou d'etirer les sous-cellules."""
        need = max(head._FREE_MIN, content_min(c))
        if need != head._widths[c]:
            head._set_width(c, need)

    def grow_to_content(c: int):
        """Un contenu s'est agrandi de lui-meme (pas un redimensionnement a la souris) : sa colonne
        s'elargit pour le montrer en entier, jamais ne retrecit."""
        need = content_min(c)
        if need > head._widths[c]:
            head._set_width(c, need)

    def fit_splits(c: int, width: int):
        """La colonne a ete redimensionnee : ses cellules divisees s'y PLIENT (le contenu des cellules
        ne contraint jamais une colonne) et se DEPLIENT quand elle s'elargit a nouveau, jusqu'a leurs
        largeurs reglees (jamais modifiees par le pliage, voir SplitCell.setRoom)."""
        for cell in column_cells.get(c, []):
            split = split_of(cell.content())
            if split is not None:
                m = cell.layout().contentsMargins()
                split.setRoom(width - m.left() - m.right())

    head.resized.connect(lambda c, w: fit_splits(c, w) if w else None)
    state.after_apply = lambda: [fit_splits(c, head._widths[c]) for c in column_cells]

    for c, column in column_cells.items():
        for cell in column:
            if split_of(cell.content()) is not None:
                split_of(cell.content()).widthsResized.connect(lambda c=c: grow_for_split(c))

    def reflow_columns():
        """Replace les cellules de chaque ligne dans l'ordre d'affichage des colonnes."""
        for r, row_cells in enumerate(cells):
            lay = row_widgets[r].layout()
            for cell in row_cells:
                lay.removeWidget(cell)
            for pos, c in enumerate(head.order()):
                lay.insertWidget(pos, row_cells[c], 0)     # colonnes libres : aucune n'est extensible
            row_widgets[r].update()
        head.update()

    state.reflow = reflow_columns
    head.setReorderable(True)
    mover = state.rows = grips.mover = _RowMover(frame, head, row_widgets, cells, row_meta)

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
            row_layout = row_widgets[r].layout()
            shown_first = mover.order.index(r) == 0          # place AFFICHEE (lignes deplacables)
            # Aucune marge propre a la ligne (seulement l'epaisseur du filet du haut) : l'espace autour
            # du contenu est le padding des cellules, rien d'autre (padding 0 = contenu contre les filets).
            row_layout.setContentsMargins(0, inset_top if not shown_first else 0, 0, 0)
            for c, cell in enumerate(row_cells):
                # Padding PROPRE a la cellule (« Override settings » > cellule / ligne / colonne).
                own = (getattr(cell, "_part_look", None) or {}).get("padding") or (left, top, right, bottom)
                if getattr(cell.content(), "_fill_cell", False):
                    cell.layout().setContentsMargins(inset_left if c > 0 else 0, 0, 0, 0)
                    if split_of(cell.content()) is not None:       # meme padding que les cellules normales
                        split_of(cell.content()).setContentPadding(*own)
                else:
                    cell.layout().setContentsMargins(*own)
                cell.layout().activate()          # tailles a jour AVANT heights.apply (sinon
                cell.updateGeometry()             # la hauteur naturelle garde l'ancien padding)
            row_layout.invalidate()
        heights.apply()

    frame._flat_cell_padding = cell_padding

    # Clic droit sur l'entete : option de tableau « lignes : hauteurs egales ».
    def head_menu(pos):
        menu = Menu(head)
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
            menu.addAction("Renommer le titre…").triggered.connect(
                lambda _c=False, i=column: rename_inline(head._cells[i], lambda text: state.set_head_title(i, text)))
            menu.addSeparator()
        menu.addAction("Supprimer l'entête").triggered.connect(lambda _c=False: state.set_head_hidden(True))
        action = menu.addAction("Lignes : hauteurs égales")
        action.setCheckable(True)
        action.setChecked(heights.equal)
        action.toggled.connect(heights.set_equal)
        head._menu_column = column           # « Override settings » > Cellule en cours (titre clique)
        add_context_extras(head, menu)
        menu.exec(head.mapToGlobal(pos))
        head._menu_column = None

    head.setContextMenuPolicy(Qt.CustomContextMenu)
    head.customContextMenuRequested.connect(head_menu)
    _register_cells_table(frame, head, row_meta)     # applique tout de suite le style courant
    _lock_min_height(frame)
    watch_object_gestures(frame)                     # objets libres : Ctrl+Maj / Ctrl+Maj+X + glisser
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

def _toggle_alone_in_cell(toggle: QWidget) -> bool:
    """Le toggle est-il SEUL dans sa cellule (cellule du tableau, ou sous-cellule d'une cellule divisee) :
    aucun autre controle ni texte a cote (ex. « lier les 4 », un cote d'une ligne Ombres, une ligne
    oui / non) ? Les toggles « app » / « sys » d'une couleur, celui d'un cote au-dessus de sa couleur ou
    celui d'override devant un libelle ne le sont pas."""
    from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QComboBox, QLabel, QLineEdit
    cell = toggle.parentWidget()
    while cell is not None and not isinstance(cell, _Cell) and not hasattr(cell, "_split_owner"):
        cell = cell.parentWidget()
    if cell is None:
        return False
    for widget in cell.findChildren(QWidget):
        if widget is toggle or toggle.isAncestorOf(widget) or widget.isHidden():
            continue
        if isinstance(widget, (_Toggle, QAbstractButton, QLineEdit, QAbstractSlider, QComboBox)):
            return False
        if isinstance(widget, QLabel) and widget.text().strip():
            return False
        if type(widget).__name__ in ("_MiniSlider", "_ColorSwatchButton"):
            return False
    return True


def normalize_toggles(root: QWidget):
    """Interrupteurs d'un tableau, sans texte (« actif »/« sans ») : de TYPE 1 quand ils sont seuls dans
    leur cellule, de type 2 sinon (accoles a une couleur, un libelle...) — regles des tableaux des
    reglages (voir AGENTS.md)."""
    for toggle in root.findChildren(_Toggle):
        # `_table_style` : style impose par la ligne (Spec params["toggle_style"], demande expresse).
        base = getattr(toggle, "_table_style", None) or ("toggle1" if _toggle_alone_in_cell(toggle) else "toggle2")
        if toggle._base_override != base or toggle._show_label:
            # Style d'origine (« Par defaut » du clic droit) ; un style choisi a la main est garde.
            chosen = toggle.chosenStyle()
            toggle._style_override = toggle._base_override = base
            if chosen:
                toggle._style_override = chosen
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
        menu = Menu(obj)
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
        add_context_extras(obj, menu)
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


# ==========================================================================
# Tableau hors de la fenetre de reglages : dimensions retrouvees et enregistrees
# ==========================================================================

def keep_table_dims(frame: QWidget, key: str, settings: dict | None = None) -> None:
    """Tableau construit hors de la fenetre de reglages (fenetre principale...) : il reprend ses
    dimensions enregistrees (`table_dims[key]`) a son affichage et enregistre aussitot celles tirees a
    la main, comme les tableaux des reglages. `key` sert aussi d'identifiant (Override settings)."""
    from PySide6.QtCore import QTimer
    from settings_store import load_settings, save_settings
    from settings_widgets import _TABLE_DIMS
    frame._dims_key = key
    saved = ((settings if settings is not None else load_settings()).get("table_dims") or {}).get(key)
    if saved:
        _TABLE_DIMS.setdefault(key, saved)
    timer = QTimer(frame)
    timer.setSingleShot(True)
    timer.setInterval(400)

    def save():
        try:
            dims = frame.collectDims()
        except RuntimeError:
            return
        _TABLE_DIMS[key] = dims
        current = load_settings()
        all_dims = dict(current.get("table_dims") or {})
        all_dims[key] = dims
        current["table_dims"] = all_dims
        save_settings(current)
        for listener in list(DIMS_SAVED_LISTENERS):
            listener(dict(all_dims))

    timer.timeout.connect(save)
    # `frame._dims_autosave_paused` : largeurs posees par le code (ajustement automatique), pas a la main.
    frame.dimsChanged.connect(lambda: None if getattr(frame, "_dims_autosave_paused", False) else timer.start())


DIMS_SAVED_LISTENERS: list = []     # rappels (table_dims) : l'appli tient ses reglages appliques a jour
