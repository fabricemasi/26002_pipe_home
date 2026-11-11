"""Liste des tâches PEINTE (un seul widget, jamais un widget par tâche) dans une zone de défilement : seules les
lignes visibles sont peintes ; changer de liste = remplacer un tableau de lignes déjà calculé par le service.

Ligne : flèche de repli (tâche à sous-tâches), cercle à cocher (couleur de la liste), priorité « ! », titre (barré
si terminée), seconde ligne (échéance colorée, liste dans les vues intelligentes, début des notes), drapeau.

Gestes : clic = sélection (Ctrl : ajouter / retirer, Maj : plage), clic sur le cercle = cocher, double-clic = renommer
(sous les lignes : nouvelle tâche), Ctrl + glisser = déplacer (règle de l'appli ; haut / bas d'une ligne = avant /
après elle, milieu = sous-tâche ; réglage `taches_drag_requires_ctrl`), clic droit = menu. Clavier : ↑ ↓, Espace
(cocher), Entrée (nouvelle tâche après), F2 (renommer), Suppr, Tab / Maj + Tab (indenter), Ctrl + ↑ ↓ (déplacer).
Échap annule le geste en cours (édition, glisser) et ne ferme jamais le module."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QLineEdit, QSizePolicy, QWidget

from fm_agenda.ui.widgets import draw_icon, elide, paint_check
from . import theme as th

try:
    from fm_theme.widgets import DRAG_GHOST_OPACITY
except Exception:                                        # noqa: BLE001 - hors de l'appli
    DRAG_GHOST_OPACITY = 0.75


@dataclass
class Row:
    task: object                 # TaskRecord ; None = ligne de saisie d'une nouvelle tâche
    depth: int = 0
    has_kids: bool = False
    collapsed: bool = False


class _InlineEdit(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class TaskListView(QWidget):
    selectionChanged = Signal(object)                    # id de la tâche courante (None : aucune)
    toggleDone = Signal(str)
    renamed = Signal(str, str)                           # (id, titre)
    newCommitted = Signal(str, object, object, bool)     # (titre, parent_id, after_id, en_tete)
    moveRequested = Signal(str, object, object, bool)    # (id, parent_id, after_id, en_tete)
    contextRequested = Signal(object, QPoint)            # (id | None, position globale)
    collapseToggled = Signal(str)
    keyAction = Signal(str)                              # toggle, new, delete, indent, outdent, move_up, move_down

    def __init__(self, holder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.rows: list[Row] = []
        self.lists: dict = {}
        self.show_list = False
        self.show_notes = True
        self.reorderable = True
        self.drag_needs_ctrl = True
        self.empty_text = ""
        self.today = date.today()
        self.current: str | None = None
        self.selected: set[str] = set()
        self._anchor: str | None = None
        self._hover = -1
        self._press = None                               # (position, id, ctrl, sur le cercle)
        self._drag = None                                # {"id", "pos", "target"}
        self._new = None                                 # (index d'insertion, parent, after, en_tete, profondeur)
        self._edit_id: str | None = None
        self.area = None                                 # QScrollArea (posée par le panneau)
        self.editor = _InlineEdit(self)
        self.editor.hide()
        self.editor.setFrame(False)
        self.editor.returnPressed.connect(self._commit_edit)
        self.editor.cancelled.connect(self.cancel_edit)
        self.editor.editingFinished.connect(self._edit_focus_lost)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Liste des tâches")
        self.restyle()

    # -- données --

    def restyle(self) -> None:
        t = self.holder.t
        self.editor.setFont(th.font(13))
        self.editor.setStyleSheet(f"QLineEdit {{ background: {t.hexc('field')}; border: 1px solid {t.hexc('accent')};"
                                  f" border-radius: 4px; color: {t.hexc('strong')}; padding: 0 4px;"
                                  f" selection-background-color: {t.hexc('accent')}; }}")
        self._resize()
        self.update()

    @property
    def row_h(self) -> int:
        return self.holder.t.m.get("row_h", th.ROW_H["normal"])

    def set_rows(self, rows: list[Row], lists: dict, show_list: bool, reorderable: bool) -> None:
        self.rows = rows
        self.lists = lists
        self.show_list = show_list
        self.reorderable = reorderable
        ids = {r.task.id for r in rows}
        self.selected &= ids
        if self.current not in ids:
            self.current = next(iter(self.selected), None)
        if self._new is not None and self._new[0] > len(rows):
            self._new = None
        self._resize()
        self.update()
        if self._edit_id is not None or self._new is not None:
            self._place_editor()

    def _display(self) -> list[Row]:
        if self._new is None:
            return self.rows
        idx = self._new[0]
        return self.rows[:idx] + [Row(None, self._new[4])] + self.rows[idx:]

    def _resize(self) -> None:
        h = len(self._display()) * self.row_h + self.row_h * 2
        if self.minimumHeight() != h:
            self.setFixedHeight(h)

    def sizeHint(self) -> QSize:
        return QSize(400, self.height())

    def index_of(self, task_id: str | None) -> int:
        for i, r in enumerate(self._display()):
            if r.task is not None and r.task.id == task_id:
                return i
        return -1

    # -- sélection --

    def select(self, task_id: str | None, mode: str = "set") -> None:
        if mode == "toggle" and task_id is not None:
            self.selected ^= {task_id}
            self.current = task_id if task_id in self.selected else next(iter(self.selected), None)
        elif mode == "range" and task_id is not None and self._anchor is not None:
            a, b = self.index_of(self._anchor), self.index_of(task_id)
            lo, hi = min(a, b), max(a, b)
            disp = self._display()
            self.selected = {disp[i].task.id for i in range(lo, hi + 1) if disp[i].task is not None}
            self.current = task_id
        else:
            self.selected = {task_id} if task_id else set()
            self.current = task_id
            self._anchor = task_id
        self.update()
        self.ensure_visible(self.current)
        self.selectionChanged.emit(self.current)

    def step(self, delta: int, extend: bool = False) -> None:
        disp = [r for r in self._display() if r.task is not None]
        if not disp:
            return
        idx = next((i for i, r in enumerate(disp) if r.task.id == self.current), -1)
        idx = max(0, min(len(disp) - 1, (idx + delta) if idx >= 0 else (0 if delta > 0 else len(disp) - 1)))
        self.select(disp[idx].task.id, "range" if extend else "set")

    def ensure_visible(self, task_id: str | None) -> None:
        idx = self.index_of(task_id)
        if idx >= 0 and self.area is not None:
            self.area.ensureVisible(0, idx * self.row_h + self.row_h // 2, 0, self.row_h)

    def selected_ids(self) -> list[str]:
        """Sélection dans l'ordre d'affichage."""
        return [r.task.id for r in self.rows if r.task.id in self.selected]

    # -- édition en place --

    def begin_rename(self, task_id: str) -> None:
        self._finish_new(commit=False)
        idx = self.index_of(task_id)
        if idx < 0:
            return
        self._edit_id = task_id
        self.editor.setText(self._display()[idx].task.title)
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def begin_new(self, parent_id=None, after_id=None, on_top: bool = False) -> None:
        """Ligne de saisie d'une nouvelle tâche (rien n'est créé avant Entrée)."""
        self._edit_id = None
        if after_id is not None:
            idx = self.index_of(after_id)
            # après la tâche ET ses sous-tâches affichées
            depth = self.rows[idx].depth if 0 <= idx < len(self.rows) else 0
            j = idx + 1
            while j < len(self.rows) and self.rows[j].depth > depth:
                j += 1
            insert, depth = j, (self.rows[idx].depth if idx >= 0 else 0)
        elif parent_id is not None:
            idx = self.index_of(parent_id)
            pdepth = self.rows[idx].depth if idx >= 0 else 0
            j = idx + 1
            while j < len(self.rows) and self.rows[j].depth > pdepth:
                j += 1
            insert, depth = (idx + 1 if on_top else j), pdepth + 1
        else:
            insert, depth = (0 if on_top else len(self.rows)), 0
        self._new = (insert, parent_id, after_id, on_top, depth)
        self._resize()
        self.editor.setText("")
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        self.update()
        QTimer.singleShot(0, self, lambda: self.area and self.area.ensureVisible(0, insert * self.row_h, 0,
                                                                                    self.row_h * 2))

    def editing(self) -> bool:
        return self._new is not None or self._edit_id is not None

    def _title_x(self, depth: int) -> float:
        return 16 + depth * th.INDENT + th.CHECK + 10

    def _place_editor(self) -> None:
        if self._new is not None:
            idx, depth = self._new[0], self._new[4]
        else:
            idx = self.index_of(self._edit_id)
            if idx < 0:
                self.cancel_edit()
                return
            depth = self._display()[idx].depth
        x = int(self._title_x(depth)) - 5
        h = 26
        y = idx * self.row_h + (self.row_h - h) // 2
        self.editor.setGeometry(x, y, max(120, self.width() - x - 40), h)

    def _commit_edit(self) -> None:
        text = self.editor.text().strip()
        if self._new is not None:
            _idx, parent, after, on_top, _depth = self._new
            self._new = None
            self.editor.hide()
            self._resize()
            self.update()
            if text:
                self.newCommitted.emit(text, parent, after, on_top)      # le panneau rouvre la ligne suivante
            else:
                self.setFocus()
            return
        task_id, self._edit_id = self._edit_id, None
        self.editor.hide()
        self.setFocus()
        if task_id and text:
            self.renamed.emit(task_id, text)

    def _edit_focus_lost(self) -> None:
        if self.editor.isVisible() and not self.editor.hasFocus():
            if self._new is not None and not self.editor.text().strip():
                self.cancel_edit()
            else:
                self._commit_edit()

    def _finish_new(self, commit: bool) -> None:
        if self._new is not None:
            if commit:
                self._commit_edit()
            else:
                self._new = None
                self.editor.hide()
                self._resize()

    def cancel_edit(self) -> None:
        self._new = None
        self._edit_id = None
        self.editor.blockSignals(True)
        self.editor.hide()
        self.editor.blockSignals(False)
        self._resize()
        self.update()
        self.setFocus()

    # -- peinture --

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        rh = self.row_h
        disp = self._display()
        clip = event.rect()
        p.fillRect(clip, t.c("bg"))
        first = max(0, clip.top() // rh)
        last = min(len(disp) - 1, clip.bottom() // rh)
        width = self.width()
        for i in range(first, last + 1):
            self._paint_row(p, t, disp[i], i, QRectF(0, i * rh, width, rh))
        if not disp and self.empty_text:
            p.setPen(t.c("dim"))
            p.setFont(th.font(13))
            p.drawText(QRectF(0, rh * 0.5, width, rh), Qt.AlignHCenter | Qt.AlignVCenter, self.empty_text)
        if self._drag and self._drag.get("target"):
            self._paint_drop(p, t)
        if self._drag and self._drag.get("moved"):
            self._paint_ghost(p, t)

    def _paint_row(self, p: QPainter, t, row: Row, i: int, rect: QRectF, ghost: bool = False) -> None:
        task = row.task
        if task is None:
            return                                         # ligne de saisie : l'éditeur la couvre
        sel = task.id in self.selected
        if sel:
            p.fillRect(rect, th.with_alpha(t.c("accent"), 0.20 if self.hasFocus() or ghost else 0.13))
        elif i == self._hover and not ghost:
            p.fillRect(rect, t.c("hover"))
        x0 = rect.x() + 16 + row.depth * th.INDENT
        cy = rect.center().y()
        lst = self.lists.get(task.list_id)
        color = t.event(lst.color if lst else "bleu")[1]
        if row.has_kids:
            draw_icon(p, "next" if row.collapsed else "down", QRectF(x0 - 15, cy - 6, 12, 12), t.c("dim"), 1.6)
        box = QRectF(x0, cy - th.CHECK / 2, th.CHECK, th.CHECK)
        paint_check(p, box, task.done, color, color if task.priority < 3 else t.c("today"), th.CHECK / 2)
        tx = x0 + th.CHECK + 10
        right = rect.right() - 14
        if task.flagged:
            self._paint_flag(p, QPointF(right - 8, cy), QColor("#d39a45"))
            right -= 22
        meta = self._meta(task, t)
        # Deux lignes : titre au-dessus du milieu, détails en dessous ; une seule : titre centré.
        title_rect = QRectF(0, cy - 19, 0, 19) if meta else QRectF(0, rect.y(), 0, rect.height())
        if task.priority:
            mark = th.PRIORITY_MARKS[task.priority]
            p.setFont(th.font(13, 700))
            p.setPen(t.c("today") if task.priority == 3 else t.c("accent"))
            mw = th.metrics(13, 700).horizontalAdvance(mark) + 5
            p.drawText(QRectF(tx, title_rect.y(), mw, title_rect.height()), Qt.AlignLeft | Qt.AlignVCenter, mark)
            tx += mw
        f = QFont(th.font(13, 400))             # copie : la police en cache est partagée
        f.setStrikeOut(task.done)
        p.setFont(f)
        p.setPen(t.c("dim") if task.done else t.c("strong"))
        title = task.title or "Sans titre"
        if self._edit_id != task.id:
            p.drawText(QRectF(tx, title_rect.y(), right - tx, title_rect.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(title, 13, 400, right - tx))
        if meta:
            mx = x0 + th.CHECK + 10
            my = cy + 1
            for text, col, dot in meta:
                if dot is not None:
                    p.setPen(Qt.NoPen)
                    p.setBrush(dot)
                    p.drawEllipse(QPointF(mx + 3, my + 8.5), 3, 3)
                    mx += 10
                p.setFont(th.font(12))
                p.setPen(col)
                avail = right - mx
                if avail <= 10:
                    break
                shown = elide(text, 12, 400, avail)
                w = th.metrics(12).horizontalAdvance(shown)
                p.drawText(QRectF(mx, my, w + 2, 17), Qt.AlignLeft | Qt.AlignVCenter, shown)
                mx += w + 12
        p.setPen(QPen(t.c("grid"), 1))
        p.drawLine(QPointF(x0 + th.CHECK + 10, rect.bottom() - 0.5), QPointF(rect.right(), rect.bottom() - 0.5))

    def _meta(self, task, t) -> list:
        out = []
        text, state = th.due_text(task.due_date, task.due_time, self.today)
        if text:
            col = {"late": t.c("today"), "today": t.c("accent"), "soon": t.c("text")}.get(state, t.c("muted"))
            out.append((text, col, None))
        if self.show_list:
            lst = self.lists.get(task.list_id)
            if lst is not None:
                out.append((lst.name, t.c("muted"), t.event(lst.color)[1]))
        if self.show_notes and task.notes.strip():
            out.append((task.notes.strip().splitlines()[0], t.c("dim"), None))
        if task.reminder_at and not task.done:
            from datetime import datetime
            out.append(("Rappel " + datetime.fromtimestamp(task.reminder_at).strftime("%d/%m %H:%M"),
                        t.c("muted"), None))
        if task.url:
            out.append(("🔗", t.c("dim"), None))
        return out

    @staticmethod
    def _paint_flag(p: QPainter, at: QPointF, color: QColor) -> None:
        p.save()
        p.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(at.x() - 4, at.y() - 7), QPointF(at.x() - 4, at.y() + 7))
        path = QPainterPath()
        path.addPolygon(QPolygonF([QPointF(at.x() - 4, at.y() - 7), QPointF(at.x() + 5, at.y() - 4.5),
                                   QPointF(at.x() - 4, at.y() - 1)]))
        p.fillPath(path, color)
        p.restore()

    def _paint_drop(self, p: QPainter, t) -> None:
        kind, idx, depth = self._drag["target"][4:7]
        rh = self.row_h
        if kind == "into":
            p.setPen(QPen(t.c("accent"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(2, idx * rh + 1, self.width() - 4, rh - 2), 5, 5)
            return
        y = idx * rh
        x = 16 + depth * th.INDENT
        p.setPen(QPen(t.c("accent"), 2))
        p.drawLine(QPointF(x, y), QPointF(self.width() - 10, y))
        p.setBrush(t.c("accent"))
        p.drawEllipse(QPointF(x, y), 3.5, 3.5)

    def _paint_ghost(self, p: QPainter, t) -> None:
        idx = self.index_of(self._drag["id"])
        if idx < 0:
            return
        y = self._drag["pos"].y() - self.row_h / 2
        p.save()
        p.setOpacity(DRAG_GHOST_OPACITY)
        rect = QRectF(0, y, self.width(), self.row_h)
        p.fillRect(rect, t.c("bar"))
        self._paint_row(p, t, self.rows[idx], idx, rect, ghost=True)
        p.restore()

    # -- souris --

    def _row_at(self, y: float) -> int:
        idx = int(y // self.row_h)
        return idx if 0 <= idx < len(self._display()) else -1

    def _check_hit(self, row: Row, idx: int, pos) -> str | None:
        x0 = 16 + row.depth * th.INDENT
        if x0 - 4 <= pos.x() <= x0 + th.CHECK + 4:
            return "check"
        if row.has_kids and x0 - 18 <= pos.x() < x0 - 4:
            return "arrow"
        return None

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._press is not None and self._drag is None and event.buttons() & Qt.LeftButton:
            start, task_id, ctrl, _hit = self._press
            if task_id and self.reorderable and (ctrl or not self.drag_needs_ctrl) and \
                    (pos - start).manhattanLength() >= QApplication.startDragDistance():
                self._drag = {"id": task_id, "pos": pos, "target": None, "moved": True}
        if self._drag is not None:
            self._drag["pos"] = pos
            self._drag["target"] = self._drop_target(pos)
            self.update()
            return
        idx = self._row_at(pos.y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, event):
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position()
        idx = self._row_at(pos.y())
        disp = self._display()
        row = disp[idx] if idx >= 0 else None
        if event.button() == Qt.RightButton:
            if row is not None and row.task is not None and row.task.id not in self.selected:
                self.select(row.task.id)
            self.contextRequested.emit(row.task.id if row is not None and row.task is not None else None,
                                       event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        if row is None or row.task is None:
            self._press = None
            if self.editing():
                self._edit_focus_lost()
            return
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        hit = self._check_hit(row, idx, pos)
        self._press = (pos, row.task.id, ctrl, hit)
        if hit == "check":
            self.toggleDone.emit(row.task.id)
            self._press = None
        elif hit == "arrow":
            self.collapseToggled.emit(row.task.id)
            self._press = None
        elif event.modifiers() & Qt.ShiftModifier:
            self.select(row.task.id, "range")
        elif not ctrl:
            self.select(row.task.id)

    def mouseReleaseEvent(self, event):
        drag, self._drag = self._drag, None
        press, self._press = self._press, None
        if drag is not None:
            target = drag.get("target")
            self.update()
            if target is not None:
                self.moveRequested.emit(drag["id"], target[0], target[1], target[2])
            return
        if press is not None and press[2] and event.button() == Qt.LeftButton:
            self.select(press[1], "toggle")               # Ctrl + clic sans glisser : ajouter / retirer

    def mouseDoubleClickEvent(self, event):
        idx = self._row_at(event.position().y())
        disp = self._display()
        if idx < 0:
            if event.position().y() >= len(disp) * self.row_h:
                self.keyAction.emit("new_end")
            return
        row = disp[idx]
        if row.task is not None and self._check_hit(row, idx, event.position()) is None:
            self.begin_rename(row.task.id)

    def _drop_target(self, pos) -> tuple | None:
        """(parent, after, en_tete, id, genre, index, profondeur) ; None si interdit (sur sa propre descendance)."""
        drag_id = self._drag["id"]
        rows = self.rows
        banned = {drag_id}
        i0 = self.index_of(drag_id)
        if 0 <= i0 < len(rows):
            j = i0 + 1
            while j < len(rows) and rows[j].depth > rows[i0].depth:
                banned.add(rows[j].task.id)
                j += 1
        rh = self.row_h
        idx = int(pos.y() // rh)
        if idx >= len(rows) or not rows:
            last_root = next((r.task.id for r in reversed(rows) if r.depth == 0 and r.task.id != drag_id), None)
            return (None, last_root, last_root is None, None, "line", len(rows), 0)
        idx = max(0, idx)
        row = rows[idx]
        if row.task.id in banned:
            return None
        frac = (pos.y() - idx * rh) / rh
        parent = row.task.parent_id if row.depth > 0 else None
        if frac < 0.28:
            prev = next((rows[k].task.id for k in range(idx - 1, -1, -1)
                         if rows[k].depth == row.depth and (rows[k].task.parent_id if rows[k].depth else None) ==
                         parent and rows[k].task.id != drag_id), None) if idx > 0 else None
            # s'arrêter au parent : chercher une sœur seulement au-dessus, avant de remonter d'un niveau
            if prev is not None:
                k = next(k for k in range(idx - 1, -1, -1) if rows[k].task.id == prev)
                if any(rows[m].depth < row.depth for m in range(k + 1, idx)):
                    prev = None
            return (parent, prev, prev is None, row.task.id, "line", idx, row.depth)
        if frac > 0.72:
            if row.has_kids and not row.collapsed:
                return (row.task.id, None, True, row.task.id, "line", idx + 1, row.depth + 1)
            return (parent, row.task.id, False, row.task.id, "line", idx + 1, row.depth)
        return (row.task.id, None, False, row.task.id, "into", idx, row.depth + 1)

    # -- clavier --

    def focusNextPrevChild(self, nxt: bool) -> bool:
        return False if self.hasFocus() else super().focusNextPrevChild(nxt)

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if key == Qt.Key_Escape:
            if self._drag is not None:
                self._drag = None
                self._press = None
                self.update()
            elif self.selected:
                self.select(None)
            return
        actions = {Qt.Key_Space: "toggle", Qt.Key_Return: "new", Qt.Key_Enter: "new", Qt.Key_F2: "rename",
                   Qt.Key_Delete: "delete", Qt.Key_Backspace: "delete"}
        if key in (Qt.Key_Up, Qt.Key_Down):
            if ctrl:
                self.keyAction.emit("move_up" if key == Qt.Key_Up else "move_down")
            else:
                self.step(-1 if key == Qt.Key_Up else 1, bool(mods & Qt.ShiftModifier))
            return
        if key == Qt.Key_Tab:
            self.keyAction.emit("indent")
            return
        if key == Qt.Key_Backtab:
            self.keyAction.emit("outdent")
            return
        if key in (Qt.Key_Home, Qt.Key_End):
            self.step(-10 ** 6 if key == Qt.Key_Home else 10 ** 6)
            return
        if key in actions and not ctrl:
            self.keyAction.emit(actions[key])
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.editing():
            self._place_editor()
