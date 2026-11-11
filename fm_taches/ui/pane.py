"""Panneau du module Tâches (bouton « Tâches » de la barre de navigation), à l'image de l'agenda : barre du haut
(titre de la vue, recherche, thème, « Nouvelle tâche »), panneau latéral (vues intelligentes, listes), saisie rapide,
liste peinte (`tasklist.py`), détails à droite (`details.py`).

Le panneau n'importe RIEN de la fenêtre principale (elle pose `HOOKS`) et ne parle qu'au service. Rafraîchi UNE fois
par tour de boucle (`_schedule`) quoi qu'il arrive entre-temps ; seule la vue montrée est recalculée, et le service
garde en cache ce qui n'a pas changé.

Clavier (liste) : ↑ ↓, Espace, Entrée, F2, Suppr, Tab / Maj + Tab, Ctrl + ↑ ↓ ; panneau : Ctrl+N (saisie rapide),
Ctrl+F (rechercher), Ctrl+Z / Ctrl+Y, Ctrl+B (panneau latéral), Ctrl+I (détails), Ctrl+1 à Ctrl+5 (vues). Échap
annule (saisie, recherche, sélection) et ne ferme JAMAIS le module (règle de l'appli)."""
from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from fm_agenda.ui import kit
from fm_agenda.ui.timegrid import _scrollbar_qss
from fm_agenda.ui.widgets import AgendaButton, SearchBox, ThemeHolder, draw_icon, elide
from ..core import quickadd, smart
from . import theme as th
from .details import DetailsPanel
from .sidebar import SMART, Sidebar
from .tasklist import Row, TaskListView

log = logging.getLogger("fm_taches.ui")

HOOKS: dict = {
    "settings": lambda: {},              # réglages appliqués (dict complet de l'appli)
    "status": lambda text: None,         # barre d'état de la fenêtre
    "open_settings": None,               # fenêtre « Réglages : Tâches »
    "save_setting": None,                # f(clé, valeur) : réglage modifié depuis le module (thème)
    "navbar_frame": False,               # vrai : annuler / rétablir / réglages / fermer sont dans le cadre « Tâches »
}
VIEW_KEYS = tuple(k for k, _l, _i in SMART)


def _settings() -> dict:
    from ..settings_defaults import TACHES_DEFAULTS
    s = dict(TACHES_DEFAULTS)
    try:
        s.update({k: v for k, v in (HOOKS["settings"]() or {}).items() if k.startswith("taches_")})
    except Exception:                                    # noqa: BLE001
        pass
    return s


class _Title(QWidget):
    def __init__(self, holder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.title = ""
        self.sub = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumWidth(80)

    def set_text(self, title: str, sub: str) -> None:
        if (title, sub) != (self.title, self.sub):
            self.title, self.sub = title, sub
            self.updateGeometry()
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(th.metrics(17, 600).horizontalAdvance(self.title) + 12 +
                     th.metrics(13).horizontalAdvance(self.sub), 32)

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setFont(th.font(17, 600))
        p.setPen(t.c("strong"))
        title = elide(self.title, 17, 600, self.width())
        tw = th.metrics(17, 600).horizontalAdvance(title)
        p.drawText(QRectF(0, 0, tw + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, title)
        if self.sub and tw + 10 < self.width():
            p.setFont(th.font(13))
            p.setPen(t.c("muted"))
            p.drawText(QRectF(tw + 10, 1, self.width() - tw - 10, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       elide(self.sub, 13, 400, self.width() - tw - 10))


class _Header(QWidget):
    def __init__(self, pane: "TasksPane"):
        super().__init__(pane)
        h = pane.holder
        self.holder = h
        self.title = _Title(h)
        self.search = SearchBox(h)
        self.search.edit.setPlaceholderText("Rechercher")
        self.search.edit.setAccessibleName("Rechercher une tâche")
        self.theme_btn = AgendaButton(h, icon="sun", kind="icon", tip="Passer en thème clair")
        self.new_btn = AgendaButton(h, "Nouvelle tâche", icon="plus", kind="primary", tip="Nouvelle tâche (Ctrl+N)")
        lay = QHBoxLayout(self)
        m = h.t.m
        lay.setContentsMargins(m["header_pad_h"], m["header_pad_v"], m["header_pad_h"], m["header_pad_v"])
        lay.setSpacing(12)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.search, 1)
        lay.addWidget(self.theme_btn)
        lay.addWidget(self.new_btn)
        from PySide6.QtWidgets import QLayout
        lay.setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(m["btn_h"] + 2 * m["header_pad_v"] + 1)

    def apply_width(self, w: int) -> None:
        self.new_btn.setText("" if w < 760 else "Nouvelle tâche")
        self.new_btn.updateGeometry()
        self.search.setVisible(w >= 560 or bool(self.search.text()))

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.fillRect(self.rect(), t.c("bar"))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), t.c("line"))


class QuickAdd(SearchBox):
    """Saisie rapide (« Appeler Paul demain 14h #Studio !! ») : champ de la recherche du design, icône « + »."""

    def __init__(self, holder, parent=None):
        super().__init__(holder, parent)
        self.edit.setPlaceholderText("Ajouter une tâche… (demain 14h, #liste, !!, *)")
        self.edit.setAccessibleName("Ajouter une tâche")
        self.setMaximumWidth(16777215)
        self.setToolTip("Saisie rapide : date (demain, lundi, 12/11, dans 3 jours), heure (14h, 9:30), "
                        "liste (#nom), priorité (! !! !!!), marquée (*). Entrée : ajouter.")

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        from PySide6.QtGui import QPen
        p.setPen(QPen(t.c("accent") if self.edit.hasFocus() else t.c("field_line"), 1))
        p.setBrush(t.c("field"))
        p.drawRoundedRect(rect, 6, 6)
        draw_icon(p, "plus", QRectF(10, (self.height() - 14) / 2, 14, 14),
                  t.c("accent") if self.edit.hasFocus() else t.c("dim"))


def _scroller(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setFrameShape(QFrame.NoFrame)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class TasksPane(QWidget):
    closeRequested = Signal()
    stateChanged = Signal()                  # annuler / rétablir (cadre « Tâches » de la barre)

    MIN_CONTENT = 600

    def __init__(self, service, parent=None, settings: dict | None = None):
        super().__init__(parent)
        self.service = service
        self.settings = settings if settings is not None else _settings()
        self.holder = ThemeHolder(th.from_settings(self.settings))
        self.setObjectName("TachesPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._side_margin = 0
        self._pending = False
        self.search_text = ""
        self.collapsed = set(service.pref("collapsed") or [])
        start = self.settings.get("taches_start_view", "last")
        saved = service.pref("view") if start == "last" else None
        self.view = tuple(saved) if isinstance(saved, (list, tuple)) and len(saved) == 2 else \
            ("smart", start if start in VIEW_KEYS else "today")
        if self.view[0] == "list" and service.get_list(self.view[1]) is None:
            self.view = ("smart", "today")
        self._build()
        self._connect()
        self._shortcuts()
        self.restyle()
        self.refresh()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

    # -- construction --

    def _build(self) -> None:
        h = self.holder
        self.header = _Header(self)
        self.sidebar = Sidebar(h)
        self.side_area = _scroller(self.sidebar)
        self.side_area.setObjectName("TachesSideArea")
        self.side_area.setMinimumWidth(180)
        self.side_area.setMaximumWidth(420)
        self.quick = QuickAdd(h)
        self.list = TaskListView(h)
        self.list.drag_needs_ctrl = bool(self.settings.get("taches_drag_requires_ctrl", True))
        self.list.show_notes = bool(self.settings.get("taches_show_notes", True))
        self.list_area = _scroller(self.list)
        self.list.area = self.list_area
        center = QWidget()
        center.setObjectName("TachesCenter")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 12, 0, 0)
        cl.setSpacing(8)
        qrow = QHBoxLayout()
        qrow.setContentsMargins(16, 0, 16, 0)
        qrow.addWidget(self.quick)
        cl.addLayout(qrow)
        cl.addWidget(self.list_area, 1)
        self.details = DetailsPanel(h)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("TachesSplit")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.side_area)
        self.splitter.addWidget(center)
        self.splitter.addWidget(self.details)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        width = int(self.service.pref("sidebar_w", 0) or self.settings.get("taches_sidebar_width", 250))
        self.splitter.setSizes([width, 700, self.details.width()])
        self.splitter.splitterMoved.connect(
            lambda *_a: self.service.set_pref("sidebar_w", self.splitter.sizes()[0]))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.setSizeConstraint(QVBoxLayout.SetNoConstraint)
        root.addWidget(self.header)
        root.addWidget(self.splitter, 1)
        self._sidebar_user = bool(self.service.pref("sidebar_shown", self.settings.get("taches_show_sidebar", True)))
        self._details_user = bool(self.service.pref("details_shown",
                                                    self.settings.get("taches_show_details", True)))
        self.side_area.setVisible(self._sidebar_user)
        self.details.setVisible(self._details_user)

    def _connect(self) -> None:
        hd = self.header
        hd.search.textChanged.connect(self._search_typed)
        hd.search.escaped.connect(self.clear_search)
        hd.theme_btn.clicked.connect(self.toggle_theme)
        hd.new_btn.clicked.connect(self.focus_quick_add)
        self.quick.submitted.connect(self.quick_add)
        self.quick.escaped.connect(self.list.setFocus)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._run_search)
        sb = self.sidebar
        sb.picked.connect(lambda kind, key: self.set_view((kind, key)))
        sb.addList.connect(self.new_list)
        sb.renameList.connect(self.rename_list)
        sb.contextRequested.connect(self._list_menu)
        lv = self.list
        lv.selectionChanged.connect(lambda _id: self._refresh_details())
        lv.toggleDone.connect(self.toggle_done)
        lv.renamed.connect(lambda tid, text: self.service.update_task(tid, label="Renommer la tâche", title=text))
        lv.newCommitted.connect(self._inline_new)
        lv.moveRequested.connect(self._drop_move)
        lv.contextRequested.connect(self._task_menu)
        lv.collapseToggled.connect(self.toggle_collapse)
        lv.keyAction.connect(self._key_action)
        d = self.details
        d.edited.connect(lambda tid, fields: self.service.update_task(tid, **fields))
        d.moveToList.connect(lambda tid, lid: self.service.move(tid, list_id=lid))
        d.addSubtask.connect(self.new_subtask)
        d.deleteRequested.connect(lambda tid: self.delete_tasks([tid]))
        s = self.service
        s.changed.connect(lambda _lists: self._schedule())
        s.listsChanged.connect(self._schedule)
        s.undoChanged.connect(self.stateChanged)
        s.message.connect(self._message)
        self._day_timer = QTimer(self)
        self._day_timer.timeout.connect(self._day_rollover)
        self._day_timer.start(60_000)
        self._today = date.today()

    def _shortcuts(self) -> None:
        def sc(keys, fn):
            for key in keys if isinstance(keys, (list, tuple)) else (keys,):
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(fn)
        sc("Ctrl+N", self.focus_quick_add)
        sc(["Ctrl+F", "/"], self._focus_search)
        sc("Ctrl+Z", self.undo)
        sc(["Ctrl+Y", "Ctrl+Shift+Z"], self.redo)
        sc("Ctrl+B", self.toggle_sidebar)
        sc("Ctrl+I", self.toggle_details)
        for i, key in enumerate(VIEW_KEYS):
            sc(f"Ctrl+{i + 1}", lambda k=key: self.set_view(("smart", k)))

    # -- aspect --

    def restyle(self) -> None:
        """UNE feuille de style pour tout le panneau (sélecteurs par nom d'objet, plus forts que le `QWidget` de la
        feuille de l'appli)."""
        t = self.holder.t
        c = t.hexc
        self.setStyleSheet(
            f"#TachesPane {{ background: {c('bg')}; }}"
            f"#TachesPane QScrollArea {{ background: {c('bg')}; border: none; }}"
            f"QWidget#TachesCenter {{ background: {c('bg')}; }}"
            f"QScrollArea#TachesSideArea, QScrollArea#TachesSideArea > QWidget > QWidget {{ background: {c('side')}; }}"
            f"QSplitter#TachesSplit::handle {{ background: {c('line')}; }}"
            f"#TachesDetails {{ background: {c('side')}; }}"
            f"#TachesDetails QLabel {{ background: transparent; color: {c('text')}; }}"
            f"#TachesDetails QLabel#dMuted {{ color: {c('muted')}; }}"
            f"#TachesDetails QLabel#dDim {{ color: {c('dim')}; }}"
            + _scrollbar_qss(t))
        self.list_area.viewport().setStyleSheet("")
        self.header.theme_btn.set_icon("sun" if t.dark else "moon")
        self.header.theme_btn.setToolTip("Passer en thème clair" if t.dark else "Passer en thème sombre")
        self.header.search.restyle()
        self.quick.restyle()
        self.list.restyle()
        for w in (self.header, self.sidebar, self.quick):
            w.update()
        for w in self.header.findChildren(QWidget):
            w.update()

    def apply_settings(self, settings: dict) -> None:
        """Réglages modifiés (fenêtre « Réglages : Tâches ») : seul ce qui a changé est refait."""
        changed = {k for k, v in settings.items() if k.startswith("taches_") and self.settings.get(k) != v}
        if not changed:
            return
        self.settings.update({k: settings[k] for k in changed})
        self.service.apply_settings({k: settings[k] for k in changed})
        if changed & {"taches_theme", "taches_accent", "taches_density"}:
            self.holder.set(th.from_settings(self.settings))
            self.restyle()
        if "taches_show_sidebar" in changed:
            self._sidebar_user = bool(self.settings["taches_show_sidebar"])
            self._apply_panels()
        if "taches_show_details" in changed:
            self._details_user = bool(self.settings["taches_show_details"])
            self._apply_panels()
        if "taches_sidebar_width" in changed:
            sizes = self.splitter.sizes()
            self.splitter.setSizes([int(self.settings["taches_sidebar_width"]), sizes[1], sizes[2]])
        if "taches_width" in changed:
            self._apply_content_width()
        self.list.drag_needs_ctrl = bool(self.settings.get("taches_drag_requires_ctrl", True))
        self.list.show_notes = bool(self.settings.get("taches_show_notes", True))
        self.refresh()

    def toggle_theme(self) -> None:
        name = "clair" if self.holder.t.dark else "sombre"
        self.settings["taches_theme"] = name
        self.holder.set(th.from_settings(self.settings))
        self.restyle()
        saver = HOOKS.get("save_setting")
        if callable(saver):
            saver("taches_theme", name)

    def toggle_sidebar(self) -> None:
        self._sidebar_user = not self.side_area.isVisible()
        self.service.set_pref("sidebar_shown", self._sidebar_user)
        self._apply_panels()

    def toggle_details(self) -> None:
        self._details_user = not self.details.isVisible()
        self.service.set_pref("details_shown", self._details_user)
        self._apply_panels()

    def _apply_panels(self) -> None:
        width = self.content_width()
        self.side_area.setVisible(self._sidebar_user and not (0 < width < 640))
        self.details.setVisible(self._details_user and not (0 < width < 900))
        if self.details.isVisible():
            self._refresh_details()

    # -- largeur (comme l'agenda) --

    def content_width(self) -> int:
        return max(0, self.width() - 2 * self._side_margin)

    def _apply_content_width(self) -> None:
        try:
            pct = max(20, min(100, int(self.settings.get("taches_width", 100) or 100)))
        except (TypeError, ValueError):
            pct = 100
        total = self.width()
        content = total if pct >= 100 else min(total, max(self.MIN_CONTENT, round(total * pct / 100)))
        margin = max(0, (total - content) // 2)
        if margin != self._side_margin:
            self._side_margin = margin
            self.layout().setContentsMargins(margin, 0, margin, 0)
            self.update()
        self.header.apply_width(total - 2 * margin)
        self._apply_panels()

    def paintEvent(self, event):
        super().paintEvent(event)
        m = self._side_margin
        if m > 0:
            t = self.holder.t
            p = QPainter(self)
            w, h = self.width(), self.height()
            p.fillRect(0, 0, m, h, t.c("bg"))
            p.fillRect(w - m, 0, m, h, t.c("bg"))
            p.fillRect(m - 1, 0, 1, h, t.c("line"))
            p.fillRect(w - m, 0, 1, h, t.c("line"))
            p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_content_width()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self, self.focus_view)

    def focus_view(self) -> None:
        self.list.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == event.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    # -- état --

    def _schedule(self) -> None:
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self, self._flush)

    def _flush(self) -> None:
        self._pending = False
        self.refresh()

    def _day_rollover(self) -> None:
        if date.today() != self._today:
            self._today = date.today()
            self.refresh()

    def set_view(self, view: tuple) -> None:
        self.list.cancel_edit()
        if self.search_text:
            self.header.search.edit.clear()
            self.search_text = ""
        self.view = tuple(view)
        self.service.set_pref("view", list(self.view))
        self.list.select(None)
        self.refresh()
        self.list.setFocus()

    def reveal(self, task_id: str) -> None:
        """Ouvre la liste de la tâche et la sélectionne (depuis l'agenda) ; ses parents repliés sont dépliés."""
        task = self.service.get(task_id)
        if task is None:
            return
        parent = self.service.get(task.parent_id)
        while parent is not None:
            self.collapsed.discard(parent.id)
            parent = self.service.get(parent.parent_id)
        self.set_view(("list", task.list_id))
        self.list.select(task_id)
        self._refresh_details()

    def current_list_id(self) -> str | None:
        return self.view[1] if self.view[0] == "list" else None

    def refresh(self) -> None:
        s = self.service
        today = date.today()
        self.list.today = today
        lists = {lst.id: lst for lst in s.lists()}
        show_done = bool(self.settings.get("taches_show_done", True))
        done_last = bool(self.settings.get("taches_done_last", True))
        if self.search_text:
            found = s.search(self.search_text)
            rows = [Row(t) for t in found]
            title, sub = f"« {self.search_text} »", f"{len(found)} résultat{'s' if len(found) != 1 else ''}"
            show_list, reorder, empty = True, False, "Aucune tâche trouvée."
        elif self.view[0] == "list" and self.view[1] in lists:
            lid = self.view[1]
            flat = s.tasks_of(lid, show_done, done_last, frozenset(self.collapsed))
            parents = {t.parent_id for t, _d in s.tasks_of(lid, show_done, done_last) if t.parent_id}
            rows = [Row(t, d, t.id in parents, t.id in self.collapsed) for t, d in flat]
            open_count = s.counts().get(lid, 0)
            title, sub = lists[lid].name, f"{open_count} à faire"
            show_list, reorder, empty = False, True, "Aucune tâche. Tapez-en une ci-dessus, ou Entrée."
        else:
            key = self.view[1] if self.view[1] in VIEW_KEYS else "today"
            self.view = ("smart", key)
            tasks = s.smart(key, today)
            rows = [Row(t) for t in tasks]
            title = smart.LABELS[key]
            sub = f"{len(tasks)} tâche{'s' if len(tasks) != 1 else ''}"
            show_list, reorder = True, False
            empty = {"today": "Rien pour aujourd'hui.", "planned": "Aucune tâche datée.",
                     "flagged": "Aucune tâche marquée.", "all": "Aucune tâche à faire.",
                     "done": "Aucune tâche terminée."}[key]
        self.list.empty_text = empty
        self.list.set_rows(rows, lists, show_list, reorder)
        self.header.title.set_text(title, sub)
        smart_counts = {k: len(s.smart(k, today)) for k in VIEW_KEYS if k != "done"}
        self.sidebar.set_data(s.lists(), s.counts(), smart_counts, self.view)
        self._refresh_details()
        self.stateChanged.emit()

    def _refresh_details(self) -> None:
        if not self.details.isVisible():
            return
        task = self.service.get(self.list.current)
        if task is None:
            self.details.show_task(None, self.service.lists())
            return
        lst = self.service.get_list(task.list_id)
        self.details.at_due = bool(self.settings.get("taches_remind_at_due", True))
        self.details.show_task(task, self.service.lists(), self.service.children(task.id),
                               self.service.can_have_children(task.id), bool(lst and lst.is_google))

    def _message(self, level: str, text: str) -> None:
        status = HOOKS.get("status")
        if callable(status):
            status(("⚠ " if level == "erreur" else "") + text)

    # -- recherche --

    def _search_typed(self, text: str) -> None:
        self._search_timer.start()

    def _run_search(self) -> None:
        self.search_text = self.header.search.text().strip()
        self.refresh()

    def clear_search(self) -> None:
        self.header.search.edit.clear()
        self.search_text = ""
        self.refresh()
        self.list.setFocus()

    def _focus_search(self) -> None:
        self.header.search.setVisible(True)
        self.header.search.focus()

    # -- création --

    def focus_quick_add(self) -> None:
        self.quick.focus()

    def _target_list(self, parsed_list: str | None) -> str | None:
        if parsed_list:
            return parsed_list
        if self.view[0] == "list":
            return self.view[1]
        default = self.service.default_list()
        return default.id if default else None

    def quick_add(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        lists = [(lst.id, lst.name) for lst in self.service.lists()]
        q = quickadd.parse(text, lists)
        fields = {"priority": q.priority, "flagged": q.flagged or self.view == ("smart", "flagged")}
        if q.due_date:
            fields.update(due_date=q.due_date, due_time=q.due_time)
        elif self.view in (("smart", "today"), ("smart", "planned")):
            fields["due_date"] = date.today().isoformat()        # sinon la tâche disparaîtrait de la vue
        tid = self.service.create_task(self._target_list(q.list_id), q.title,
                                       on_top=bool(self.settings.get("taches_new_on_top", False)), **fields)
        self.quick.edit.clear()
        if tid:
            self.refresh()
            self.list.select(tid)
            self.quick.focus()

    def _inline_new(self, text: str, parent_id, after_id, on_top: bool) -> None:
        """Ligne de saisie validée : la tâche est créée et une nouvelle ligne s'ouvre juste après (saisie
        continue, comme Rappels)."""
        lid = self.current_list_id()
        if lid is None:
            return
        q = quickadd.parse(text, ())
        fields = {"priority": q.priority, "flagged": q.flagged}
        if q.due_date:
            fields.update(due_date=q.due_date, due_time=q.due_time)
        tid = self.service.create_task(lid, q.title, parent_id=parent_id, after_id=after_id, on_top=on_top,
                                       **fields)
        if tid:
            self.refresh()
            self.list.select(tid)
            self.list.begin_new(parent_id=parent_id, after_id=tid)

    def new_subtask(self, task_id: str) -> None:
        task = self.service.get(task_id)
        if task is None:
            return
        if self.view != ("list", task.list_id):
            self.set_view(("list", task.list_id))
        if task_id in self.collapsed:
            self.toggle_collapse(task_id)
        self.list.begin_new(parent_id=task_id)

    # -- actions sur les tâches --

    def toggle_done(self, task_id: str) -> None:
        task = self.service.get(task_id)
        if task is not None:
            self.service.set_done(task_id, not task.done)

    def toggle_collapse(self, task_id: str) -> None:
        self.collapsed ^= {task_id}
        self.collapsed = {i for i in self.collapsed if self.service.get(i) is not None}
        self.service.set_pref("collapsed", sorted(self.collapsed))
        self.refresh()

    def delete_tasks(self, ids: list[str]) -> None:
        ids = [i for i in ids if self.service.get(i) is not None]
        if not ids:
            return
        subs = sum(len(self.service.descendants(i)) for i in ids)
        if self.settings.get("taches_confirm_delete", True) and (subs or len(ids) > 1):
            first = self.service.get(ids[0]).title or "Sans titre"
            what = f"« {first} »" if len(ids) == 1 else f"{len(ids)} tâches"
            extra = f" et {subs} sous-tâche{'s' if subs > 1 else ''}" if subs else ""
            if not kit.confirm(self, "Supprimer", f"Supprimer {what}{extra} ?", "Supprimer"):
                return
        self.service.delete_tasks(ids)

    def _key_action(self, action: str) -> None:
        lv, s = self.list, self.service
        cur = lv.current
        ids = lv.selected_ids()
        in_list = self.view[0] == "list" and not self.search_text
        if action == "toggle" and ids:
            tasks = [s.get(i) for i in ids]
            target = not all(t.done for t in tasks)
            if len(ids) == 1:
                s.set_done(ids[0], target)
            else:
                for i in ids:                                      # une commande par tâche (annulables une à une)
                    s.set_done(i, target)
        elif action == "new":
            if in_list:
                lv.begin_new(after_id=cur) if cur else lv.begin_new(
                    on_top=bool(self.settings.get("taches_new_on_top", False)))
            else:
                self.focus_quick_add()
        elif action == "new_end":
            if in_list:
                lv.begin_new()
            else:
                self.focus_quick_add()
        elif action == "rename" and cur:
            lv.begin_rename(cur)
        elif action == "delete" and ids:
            self.delete_tasks(ids)
        elif action == "indent" and cur and in_list:
            s.indent(cur)
        elif action == "outdent" and cur and in_list:
            s.outdent(cur)
        elif action in ("move_up", "move_down") and cur and in_list:
            self._move_step(cur, -1 if action == "move_up" else 1)

    def _move_step(self, task_id: str, delta: int) -> None:
        task = self.service.get(task_id)
        sibs = self.service.siblings(task_id)
        idx = next(i for i, t in enumerate(sibs) if t.id == task_id)
        new = idx + delta
        if not 0 <= new < len(sibs):
            return
        others = [t for t in sibs if t.id != task_id]
        if new == 0:
            self.service.move(task_id, parent_id=task.parent_id, after_id=None, on_top=True)
        else:
            self.service.move(task_id, parent_id=task.parent_id, after_id=others[new - 1].id)
        QTimer.singleShot(0, self, lambda: self.list.ensure_visible(task_id))

    def _drop_move(self, task_id: str, parent_id, after_id, on_top: bool) -> None:
        if parent_id is not None and parent_id in self.collapsed:
            self.toggle_collapse(parent_id)
        self.service.move(task_id, parent_id=parent_id, after_id=after_id, on_top=on_top)

    def _set_due(self, ids, due: date | None) -> None:
        for i in ids:
            self.service.update_task(i, label="Échéance", due_date=due.isoformat() if due else None)

    def _task_menu(self, task_id, global_pos) -> None:
        s = self.service
        menu = kit.themed_menu(self)
        in_list = self.view[0] == "list" and not self.search_text
        ids = self.list.selected_ids() or ([task_id] if task_id else [])
        task = s.get(task_id)
        if task is not None:
            menu.addAction("Renommer (F2)", lambda: self.list.begin_rename(task_id))
            menu.addAction("Rouvrir" if task.done else "Terminer (Espace)", lambda: self._key_action("toggle"))
            if in_list:
                menu.addAction("Nouvelle tâche après (Entrée)", lambda: self.list.begin_new(after_id=task_id))
                if s.can_have_children(task_id):
                    menu.addAction("Nouvelle sous-tâche", lambda: self.new_subtask(task_id))
                menu.addAction("Indenter (Tab)", lambda: s.indent(task_id))
                if task.parent_id:
                    menu.addAction("Désindenter (Maj + Tab)", lambda: s.outdent(task_id))
            menu.addSeparator()
            menu.addAction("Retirer le drapeau" if task.flagged else "Marquer",
                           lambda: [s.update_task(i, flagged=not task.flagged) for i in ids])
            prio = menu.addMenu("Priorité")
            for value, label in enumerate(th.PRIORITY_LABELS):
                prio.addAction(label, lambda v=value: [s.update_task(i, priority=v) for i in ids])
            due = menu.addMenu("Échéance")
            today = date.today()
            from datetime import timedelta
            due.addAction("Aujourd'hui", lambda: self._set_due(ids, today))
            due.addAction("Demain", lambda: self._set_due(ids, today + timedelta(days=1)))
            due.addAction("Lundi prochain", lambda: self._set_due(ids, th.next_weekday(today, 0)))
            due.addAction("Dans une semaine", lambda: self._set_due(ids, today + timedelta(days=7)))
            due.addAction("Aucune", lambda: self._set_due(ids, None))
            others = [lst for lst in s.lists() if lst.id != task.list_id]
            if others:
                move = menu.addMenu("Déplacer vers la liste")
                for lst in others:
                    move.addAction(lst.name, lambda lid=lst.id: [s.move(i, list_id=lid) for i in ids])
            menu.addSeparator()
            menu.addAction("Supprimer (Suppr)", lambda: self.delete_tasks(ids))
        else:
            menu.addAction("Nouvelle tâche (Ctrl+N)",
                           (lambda: self.list.begin_new()) if in_list else self.focus_quick_add)
        menu.addSeparator()
        menu.addAction("Masquer les terminées" if self.settings.get("taches_show_done", True)
                       else "Montrer les terminées", self._toggle_show_done)
        menu.exec(global_pos)

    def _toggle_show_done(self) -> None:
        value = not self.settings.get("taches_show_done", True)
        self.settings["taches_show_done"] = value
        saver = HOOKS.get("save_setting")
        if callable(saver):
            saver("taches_show_done", value)
        self.refresh()

    # -- listes --

    def new_list(self) -> None:
        name = kit.ask_text(self, "Nouvelle liste", "Nom de la liste :", "", "Créer")
        if name and name.strip():
            lst = self.service.create_list(name.strip())
            self.set_view(("list", lst.id))

    def rename_list(self, list_id: str) -> None:
        lst = self.service.get_list(list_id)
        if lst is None:
            return
        name = kit.ask_text(self, "Renommer la liste", "Nom de la liste :", lst.name, "Renommer")
        if name and name.strip():
            self.service.update_list(list_id, name=name.strip())

    def delete_list(self, list_id: str) -> None:
        lst = self.service.get_list(list_id)
        if lst is None:
            return
        n = self.service.list_size(list_id)
        if self.settings.get("taches_confirm_delete", True) and not kit.confirm(
                self, "Supprimer la liste", f"Supprimer la liste « {lst.name} »"
                + (f" et ses {n} tâche{'s' if n > 1 else ''}" if n else "") + " ? (Ctrl+Z l'annule)", "Supprimer"):
            return
        self.service.delete_list(list_id)
        if self.view == ("list", list_id):
            self.set_view(("smart", "today"))

    def publish_list(self, list_id: str, account: dict) -> None:
        nested = any(t.parent_id and self.service.get(t.parent_id) and self.service.get(t.parent_id).parent_id
                     for t in self.service.tasks_in(list_id))
        if nested and not kit.confirm(self, "Google Tasks", "Google Tasks n'a qu'un niveau de sous-tâches : les "
                                      "niveaux plus profonds de cette liste seront remontés d'un cran. Continuer ?",
                                      "Envoyer"):
            return
        if self.service.publish_list(list_id, account):
            manager = getattr(self.service, "sync", None)
            if manager is not None:
                manager.sync_now()

    def _list_menu(self, list_id: str, global_pos) -> None:
        lst = self.service.get_list(list_id)
        if lst is None:
            return
        menu = kit.themed_menu(self)
        menu.addAction("Renommer…", lambda: self.rename_list(list_id))
        manager = getattr(self.service, "sync", None)
        if lst.synced and manager is not None:
            menu.addAction("Synchroniser maintenant", lambda: manager.sync_now())
        elif lst.source == "local" and manager is not None:
            accounts = [a for a in self.service.accounts() if a.get("status") != "auth_error"]
            if accounts:
                send = menu.addMenu("Envoyer vers Google Tasks")
                for acc in accounts:
                    send.addAction(acc.get("email") or "Compte Google",
                                   lambda a=acc: self.publish_list(list_id, a))
        colors = menu.addMenu("Couleur")
        for key in th.LIST_COLORS:
            colors.addAction(th.LIST_COLOR_LABELS[key], lambda k=key: self.service.update_list(list_id, color=k))
        menu.addSeparator()
        menu.addAction("Supprimer la liste…", lambda: self.delete_list(list_id))
        menu.exec(global_pos)

    # -- annuler / rétablir, fermeture --

    def undo(self) -> None:
        if self.list.editing():
            return
        if self.service.undo():
            self._message("info", "Annulé")

    def redo(self) -> None:
        if self.service.redo():
            self._message("info", "Rétabli")

    def shutdown(self) -> None:
        self.list.cancel_edit()
        self._day_timer.stop()
