"""Panneau de l'agenda (module « Agenda » de la barre de navigation), d'après le design Claude Design : barre du
haut (`header` : précédent / Aujourd'hui / suivant, titre, choix de la vue, recherche, thème, « Nouvel
événement »), panneau latéral redimensionnable (mini-calendrier, prochains jours, calendriers), vues Jour (+
détails), Semaine, Semaine de travail, Mois, Année, Planning, résultats de recherche.

Le panneau n'importe RIEN de la fenêtre principale (elle pose `HOOKS`) et ne parle qu'au service. Rafraîchi
UNE fois par tour de boucle (`_schedule`) quoi qu'il arrive entre-temps ; seule la vue montrée est recalculée.

Clavier : ← → (période), T (aujourd'hui), 1 à 6 (vues), N (nouvel événement), Entrée (modifier), Suppr,
Ctrl+D (dupliquer), Ctrl+C / Ctrl+V, Ctrl+Z / Ctrl+Y, Ctrl+F (rechercher), Ctrl+G (aller à une date), Tab
(événement suivant), Ctrl+B (panneau latéral), Ctrl + molette / Ctrl + + − (hauteur des heures). Échap annule
(geste, recherche, sélection) et ne ferme JAMAIS le module (règle de l'appli)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from ..core import timeutil as tu
from ..core.model import PALETTE, PALETTE_LABELS, Occurrence
from . import kit
from . import theme as th
from .context import ViewContext
from .details import DetailsPanel
from .listview import AgendaList, group_by_day
from .monthview import MonthView
from .sidebar import Sidebar
from .timegrid import TimeGridView, _scrollbar_qss
from .widgets import AgendaButton, ButtonGroup, SearchBox, Segmented, ThemeHolder, elide
from .yearview import YearView

log = logging.getLogger("fm_agenda.ui")

HOOKS: dict = {
    "settings": lambda: {},              # réglages appliqués (dict complet de l'appli)
    "status": lambda text: None,         # barre d'état de la fenêtre
    "open_settings": None,               # fenêtre « Réglages : Agenda »
    "open_folder": None,                 # f(chemin) : montrer un dossier dans les colonnes
    "project_folder": None,              # f(projet) -> dossier du projet sous la racine (« Dossier » des détails)
    "save_setting": None,                # f(clé, valeur) : réglage modifié depuis le module (thème)
    "navbar_frame": False,               # vrai : annuler / rétablir / réglages / fermer sont dans le cadre « Agenda »
}

VIEWS = (("jour", "Jour", "Vue Jour (1)"), ("semaine", "Semaine", "Vue Semaine (2)"),
         ("travail", "Travail", "Semaine de travail : jours ouvrés (3)"), ("mois", "Mois", "Vue Mois (4)"),
         ("annee", "Année", "Vue Année (5)"), ("planning", "Liste", "Prochains événements en liste (6)"))
SHORT_LABELS = {"jour": "J", "semaine": "S", "travail": "T", "mois": "M", "annee": "A", "planning": "L"}
STEP_LABELS = {"jour": ("Jour précédent", "Jour suivant"), "semaine": ("Semaine précédente", "Semaine suivante"),
               "travail": ("Semaine précédente", "Semaine suivante"), "mois": ("Mois précédent", "Mois suivant"),
               "annee": ("Année précédente", "Année suivante"), "planning": ("Période précédente", "Période suivante")}


def _settings() -> dict:
    from ..settings_defaults import AGENDA_DEFAULTS
    s = dict(AGENDA_DEFAULTS)
    try:
        s.update({k: v for k, v in (HOOKS["settings"]() or {}).items() if k.startswith("agenda_")})
    except Exception:                                    # noqa: BLE001
        pass
    return s


class _Title(QWidget):
    """`h1` du design : titre 17 px 600 + sous-titre 13 px (« Semaine 45 »), tronqués si la barre est étroite.
    Un clic : « Aller à une date »."""
    clicked = Signal()

    def __init__(self, holder: ThemeHolder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Aller à une date (Ctrl+G)")
        self.title = ""
        self.sub = ""
        self.compact = False
        self.cap = 300                                     # largeur minimale garantie au titre (`apply_width`)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumWidth(80)

    def set_text(self, title: str, sub: str) -> None:
        if (title, sub) != (self.title, self.sub):
            self.title, self.sub = title, sub
            self.setMinimumWidth(min(self.sizeHint().width(), self.cap))   # le titre passe avant la recherche
            self.updateGeometry()
            self.update()

    def sizeHint(self) -> QSize:
        w = th.metrics(17, 600).horizontalAdvance(self.title) + 4
        if self.sub:
            w += 8 + th.metrics(13).horizontalAdvance(self.sub)
        return QSize(w, 32)

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setFont(th.font(17, 600))
        p.setPen(t.c("strong"))
        title = elide(self.title, 17, 600, self.width())
        tw = th.metrics(17, 600).horizontalAdvance(title)
        p.drawText(QRectF(0, 0, tw + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, title)
        if self.sub and tw + 8 < self.width():
            p.setFont(th.font(13))
            p.setPen(t.c("muted"))
            p.drawText(QRectF(tw + 8, 1, self.width() - tw - 8, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       elide(self.sub, 13, 400, self.width() - tw - 8))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class _Header(QWidget):
    def __init__(self, pane: "AgendaPane"):
        super().__init__(pane)
        self.pane = pane
        h = pane.holder
        self.prev = AgendaButton(h, icon="prev", kind="icon", tip="Semaine précédente")
        self.today = AgendaButton(h, "Aujourd'hui", tip="Aujourd'hui (T)")
        self.next = AgendaButton(h, icon="next", kind="icon", tip="Semaine suivante")
        self.group = ButtonGroup([self.prev, self.today, self.next])
        self.title = _Title(h)
        self.seg = Segmented(h, list(VIEWS))
        self.search = SearchBox(h)
        self.theme_btn = AgendaButton(h, icon="sun", kind="icon", tip="Passer en thème clair")
        self.new_btn = AgendaButton(h, "Nouvel événement", icon="plus", kind="primary",
                                    tip="Nouvel événement (N)")
        lay = QHBoxLayout(self)
        m = h.t.m
        lay.setContentsMargins(m["header_pad_h"], m["header_pad_v"], m["header_pad_h"], m["header_pad_v"])
        lay.setSpacing(16)
        lay.addWidget(self.group)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.seg)
        lay.addStretch(1)
        right = QHBoxLayout()
        right.setSpacing(10)
        right.addWidget(self.search, 1)
        right.addWidget(self.theme_btn)
        right.addWidget(self.new_btn)
        lay.addLayout(right, 0)
        # La barre n'impose aucune largeur au panneau (fenêtre réduite) : elle se compacte (`apply_width`).
        from PySide6.QtWidgets import QLayout
        lay.setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(m["btn_h"] + 2 * m["header_pad_v"] + 1)
        self._compact = -1

    def apply_width(self, w: int) -> None:
        """Fenêtre étroite (largeur du PANNEAU, la barre ne doit rien imposer) : « Nouvel événement » réduit à son
        icône, puis vues en initiales, puis recherche masquée (Ctrl+F la rend) — le flex-wrap du design n'existe
        pas dans une barre d'une ligne."""
        level = 0 if w >= 1180 else (1 if w >= 1000 else (2 if w >= 860 else 3))
        if level == self._compact:
            return
        self._compact = level
        self.new_btn.setText("" if level >= 1 else "Nouvel événement")
        self.new_btn.updateGeometry()
        self.seg.items = [(k, SHORT_LABELS[k] if level >= 2 else label, tip) for k, label, tip in VIEWS]
        self.seg.updateGeometry()
        self.seg.update()
        self.search.setVisible(level < 3 or bool(self.search.text()))
        self.search.setMaximumWidth({0: 220, 1: 190, 2: 150}.get(level, 150))   # le titre passe avant
        self.title.cap = 300 if level == 0 else (200 if level < 3 else 80)
        self.title.setMinimumWidth(min(self.title.sizeHint().width(), self.title.cap))
        self.title.compact = bool(level)

    def paintEvent(self, event):
        t = self.pane.holder.t
        p = QPainter(self)
        p.fillRect(self.rect(), t.c("bar"))
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), t.c("line"))


def _scroller(widget: QWidget, holder: ThemeHolder) -> QScrollArea:
    area = QScrollArea()
    area.setFrameShape(QFrame.NoFrame)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setWidget(widget)
    return area


class AgendaPane(QWidget):
    closeRequested = Signal()
    stateChanged = Signal()                  # annuler / rétablir (cadre « Agenda » de la barre)

    def __init__(self, service, parent=None, settings: dict | None = None):
        super().__init__(parent)
        self.service = service
        self.settings = settings if settings is not None else _settings()
        self._wire_hooks()
        self.holder = ThemeHolder(th.from_settings(self.settings))
        self.ctx = ViewContext(service, self.holder, self.settings)
        self.setObjectName("AgendaPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._side_margin = 0                    # marge gauche = droite : largeur de l'agenda (`agenda_width`)
        restore = bool(self.settings.get("agenda_restore_state", True))
        self.view = (service.pref("view") if restore else None) or self.settings.get("agenda_default_view", "semaine")
        if self.view not in dict((k, 1) for k, _l, _t in VIEWS):
            self.view = "semaine"
        self.cur = self.ctx.today()
        if restore and service.pref("date"):
            try:
                self.cur = date.fromisoformat(service.pref("date"))
            except ValueError:
                pass
        self.sel_key: str | None = None
        self.mini_month: date | None = None
        self.search_text = ""
        self.search_scope = "all"
        self._clipboard: Occurrence | None = None
        self._pending = False
        self._scrolled_once: set[str] = set()
        self._editor = None
        self._build()
        self._connect()
        self._shortcuts()
        self.restyle()
        self.refresh()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

    def _wire_hooks(self) -> None:
        hook = HOOKS.get("project_folder")
        if callable(hook):
            self.settings["_project_folder"] = hook

    # -- construction --

    def _build(self) -> None:
        ctx, h = self.ctx, self.holder
        self.header = _Header(self)
        self.sidebar = Sidebar(ctx)
        self.week = TimeGridView(ctx)
        self.day = TimeGridView(ctx)
        self.details = DetailsPanel(ctx)
        day_page = QWidget()
        dl = QHBoxLayout(day_page)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        dl.addWidget(self.day, 999)
        dl.addWidget(self.details, 1)
        self.month = MonthView(ctx)
        self.month_area = _scroller(self.month, h)
        self.year = YearView(ctx)
        self.year_area = _scroller(self.year, h)
        self.planning = AgendaList(ctx, large=True)
        self.planning_holder = QWidget()
        pl = QVBoxLayout(self.planning_holder)
        pl.setContentsMargins(18, 4, 18, 18)
        pl.addWidget(self.planning)
        pl.addStretch(1)
        self.planning_area = _scroller(self.planning_holder, h)
        self.results = AgendaList(ctx, large=True)
        self.results_holder = QWidget()
        rl = QVBoxLayout(self.results_holder)
        rl.setContentsMargins(18, 4, 18, 18)
        rl.addWidget(self.results)
        rl.addStretch(1)
        self.results_area = _scroller(self.results_holder, h)
        self.stack = QStackedWidget()
        self.pages = {"jour": day_page, "semaine": self.week, "travail": self.week, "mois": self.month_area,
                      "annee": self.year_area, "planning": self.planning_area, "recherche": self.results_area}
        for page in (day_page, self.week, self.month_area, self.year_area, self.planning_area, self.results_area):
            self.stack.addWidget(page)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        width = int(self.service.pref("sidebar_w", 0) or self.settings.get("agenda_sidebar_width", 272))
        self.sidebar.setMinimumWidth(220)
        self.sidebar.setMaximumWidth(480)
        self.splitter.setSizes([width, 900])
        self.splitter.splitterMoved.connect(lambda *_a: self.service.set_pref("sidebar_w", self.splitter.sizes()[0]))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.setSizeConstraint(QVBoxLayout.SetNoConstraint)   # les marges de largeur n'imposent aucun minimum
        root.addWidget(self.header)
        root.addWidget(self.splitter, 1)
        self._sidebar_user = bool(self.service.pref("sidebar_shown", self.settings.get("agenda_show_sidebar", True)))
        self.sidebar.setVisible(self._sidebar_user)

    def _connect(self) -> None:
        hd = self.header
        hd.prev.clicked.connect(lambda: self.step(-1))
        hd.next.clicked.connect(lambda: self.step(1))
        hd.today.clicked.connect(self.go_today)
        hd.seg.changed.connect(self.set_view)
        hd.search.textChanged.connect(self._search_typed)
        hd.search.submitted.connect(self._search_submit)
        hd.search.escaped.connect(self.clear_search)
        hd.theme_btn.clicked.connect(self.toggle_theme)
        hd.new_btn.clicked.connect(lambda: self.new_event())
        hd.title.clicked.connect(self.go_to_date)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(160)
        self._search_timer.timeout.connect(self._run_search)
        sb = self.sidebar
        sb.mini.dayPicked.connect(self._mini_picked)
        sb.upcoming.selected.connect(self._list_picked)
        sb.upcoming.activated.connect(self.edit_occurrence)
        sb.upcoming.toggleDone.connect(self._toggle_done)
        sb.upcoming.contextRequested.connect(self._context)
        sb.upcoming.dayActivated.connect(lambda d: self.open_day(d))
        sb.calendars.toggled.connect(lambda cid, on: self.service.set_visible(cid, on))
        sb.calendars.contextRequested.connect(self._calendar_menu)
        sb.calendars.addRequested.connect(self.new_calendar)
        sb.sync.clicked.connect(self._open_settings)
        for grid in (self.week, self.day):
            grid.selected.connect(self._grid_picked)
            grid.activated.connect(self.edit_occurrence)
            grid.createRequested.connect(self._create_at)
            grid.dayActivated.connect(lambda d: self.open_day(d))
            grid.moveRequested.connect(self.move_occurrence)
            grid.contextRequested.connect(self._context)
            grid.toggleDone.connect(self._toggle_done)
        self.details.editRequested.connect(self.edit_occurrence)
        self.details.openFolder.connect(self._open_folder)
        self.details.linkActivated.connect(self._open_url)
        m = self.month
        m.dayActivated.connect(lambda d, occ: self.open_day(d, occ))
        m.daySelected.connect(self._month_day_selected)
        m.selected.connect(self._select)
        m.activated.connect(self.edit_occurrence)
        m.createRequested.connect(self._create_at)
        m.moveRequested.connect(self.move_occurrence)
        m.contextRequested.connect(self._context)
        m.wheelStep.connect(self.step)
        self.year.monthActivated.connect(lambda d: self._goto(d, "mois"))
        self.year.dayActivated.connect(lambda d: self.open_day(d))
        for lst in (self.planning, self.results):
            lst.selected.connect(self._list_picked)
            lst.activated.connect(self.edit_occurrence)
            lst.toggleDone.connect(self._toggle_done)
            lst.contextRequested.connect(self._context)
            lst.dayActivated.connect(lambda d: self.open_day(d))
        s = self.service
        s.changed.connect(self._schedule)
        s.calendarsChanged.connect(self._schedule)
        s.undoChanged.connect(self.stateChanged)
        s.message.connect(self._message)
        s.syncChanged.connect(self._refresh_sync)
        if getattr(s, "sync", None) is not None:
            s.sync.changed.connect(self._refresh_sync)
        self._now_timer = QTimer(self)
        self._now_timer.timeout.connect(self._day_rollover)
        self._now_timer.timeout.connect(self._refresh_sync)
        self._now_timer.start(60_000)
        self._today = self.ctx.today()

    def _shortcuts(self) -> None:
        def sc(keys, fn):
            for key in keys if isinstance(keys, (list, tuple)) else (keys,):
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(fn)
        typing = self._typing
        sc(["Left", "PgUp"], lambda: typing() or self.step(-1))
        sc(["Right", "PgDown"], lambda: typing() or self.step(1))
        sc("T", lambda: typing() or self.go_today())
        for i, (key, _l, _t) in enumerate(VIEWS):
            sc([str(i + 1)], lambda k=key: typing() or self.set_view(k))
            sc([f"Ctrl+{i + 1}"], lambda k=key: self.set_view(k))
        sc(["N", "Ctrl+N"], lambda: typing() or self.new_event())
        sc(["Return", "Enter"], lambda: typing() or self._edit_selected())
        sc(["Delete", "Backspace"], lambda: typing() or self._delete_selected())
        sc("Ctrl+D", self._duplicate_selected)
        sc("Ctrl+C", lambda: typing() or self._copy_selected())
        sc("Ctrl+V", lambda: typing() or self._paste())
        sc("Ctrl+Z", self.undo)
        sc(["Ctrl+Y", "Ctrl+Shift+Z"], self.redo)
        sc(["Ctrl+F", "/"], self._focus_search)
        sc("Ctrl+G", self.go_to_date)
        sc("Tab", lambda: typing() or self._cycle(1))
        sc("Shift+Tab", lambda: typing() or self._cycle(-1))
        sc("Ctrl+B", self.toggle_sidebar)
        sc(["Ctrl++", "Ctrl+="], lambda: self._zoom(1.1))
        sc("Ctrl+-", lambda: self._zoom(1 / 1.1))
        sc("Escape", self._escape)

    def _typing(self) -> bool:
        from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit))

    # -- aspect --

    def restyle(self) -> None:
        """UNE feuille de style pour tout le panneau (sélecteurs par nom d'objet, plus forts que le `QWidget` de la
        feuille de l'appli) : 76 `setStyleSheet` séparés coûtaient ~47 ms à l'ouverture."""
        t = self.holder.t
        c = t.hexc
        self.setStyleSheet(
            f"#AgendaPane {{ background: {c('bg')}; }}"
            f"#AgendaPane QScrollArea {{ background: {c('bg')}; border: none; }}"
            f"QWidget#AgendaViewport, QWidget#AgendaHolder {{ background: {c('bg')}; }}"
            f"QSplitter#AgendaSplit::handle {{ background: {c('line')}; }}"
            f"#AgendaSidebar {{ background: {c('side')}; }}"
            f"#AgendaSidebar QScrollArea, QWidget#AgendaSideViewport, QWidget#AgendaSideHolder "
            f"{{ background: transparent; border: none; }}"
            f"QWidget#AgendaSep {{ background: {c('line')}; }}"
            f"#AgendaDetails {{ background: {c('side')}; }}"
            f"#AgendaDetails QLabel {{ background: transparent; color: {c('text')}; }}"
            f"#AgendaDetails QLabel#dMuted {{ color: {c('muted')}; }}"
            f"#AgendaDetails QLabel#dStrong {{ color: {c('strong')}; }}"
            f"#AgendaDetails QLabel#dDim {{ color: {c('dim')}; }}"
            f"#AgendaDetails QLabel a {{ color: {c('link')}; }}"
            + _scrollbar_qss(t).replace("QScrollBar:horizontal { height: 0; }", "")
            + f"QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}"
            f"QScrollBar::handle:horizontal {{ background: {c('btn_line')}; border-radius: 4px; margin: 2px; }}")
        for area in (self.month_area, self.year_area, self.planning_area, self.results_area):
            area.viewport().setObjectName("AgendaViewport")
            area.widget().setObjectName("AgendaHolder")
        self.splitter.setObjectName("AgendaSplit")
        self.header.theme_btn.set_icon("sun" if t.dark else "moon")
        self.header.theme_btn.setToolTip("Passer en thème clair" if t.dark else "Passer en thème sombre")
        self.header.search.restyle()
        self.sidebar.restyle()
        self.details.restyle()
        for w in (self.week, self.day):
            w.restyle()
        for w in (self.header, self.month, self.year, self.planning, self.results):
            w.update()
        for w in self.header.findChildren(QWidget):
            w.update()

    def apply_settings(self, settings: dict) -> None:
        """Réglages modifiés (fenêtre « Réglages : Agenda ») : seul ce qui a changé est refait."""
        changed = {k for k, v in settings.items() if k.startswith("agenda_") and self.settings.get(k) != v}
        if not changed:
            return
        self.settings.update({k: settings[k] for k in changed})
        self.service.apply_settings({k: settings[k] for k in changed})
        if changed & {"agenda_theme", "agenda_accent", "agenda_today_color", "agenda_density"}:
            self.holder.set(th.from_settings(self.settings))
            self.restyle()
        if "agenda_show_sidebar" in changed:
            self._sidebar_user = bool(self.settings["agenda_show_sidebar"])
            self._apply_sidebar()
        if "agenda_sidebar_width" in changed:
            self.splitter.setSizes([int(self.settings["agenda_sidebar_width"]), max(400, self.width() - 280)])
        if "agenda_width" in changed:
            self._apply_content_width()
        if changed & {"agenda_hour_height", "agenda_limit_hours", "agenda_day_start", "agenda_day_end"}:
            for grid in (self.week, self.day):
                grid.zoom_changed()
        self.refresh()

    def toggle_theme(self) -> None:
        name = "clair" if self.holder.t.dark else "sombre"
        self.settings["agenda_theme"] = name
        self.holder.set(th.from_settings(self.settings))
        self.restyle()
        saver = HOOKS.get("save_setting")
        if callable(saver):
            saver("agenda_theme", name)

    def toggle_sidebar(self) -> None:
        self._sidebar_user = not self.sidebar.isVisible()
        self.service.set_pref("sidebar_shown", self._sidebar_user)
        self._apply_sidebar()

    def _apply_sidebar(self) -> None:
        width = self.content_width()
        auto_hide = width < 700 and width > 0
        self.sidebar.setVisible(self._sidebar_user and not auto_hide)

    # -- largeur de l'agenda (curseur de la barre d'état, Réglages : Agenda > Affichage) --

    MIN_CONTENT = 600                        # largeur minimale du contenu quand l'agenda est resserré

    def content_width(self) -> int:
        """Largeur réelle de l'agenda (panneau moins les deux marges)."""
        return max(0, self.width() - 2 * self._side_margin)

    def set_width_percent(self, value) -> None:
        """Curseur de la barre d'état : seules les marges changent (la mise en page suit au tour de boucle, les
        changements rapprochés du curseur n'en font qu'une)."""
        self.settings["agenda_width"] = value
        self._apply_content_width()

    def _apply_content_width(self) -> None:
        """Contenu centré, de `agenda_width` % de la place (jamais moins de MIN_CONTENT) ; les bords gardent le fond
        de l'agenda, un filet marque chaque côté."""
        try:
            pct = max(20, min(100, int(self.settings.get("agenda_width", 100) or 100)))
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
        self._apply_sidebar()

    def paintEvent(self, event):
        super().paintEvent(event)
        m = self._side_margin
        if m > 0:                                # bords : fond de l'agenda (le fond QSS n'y est pas peint) + filet
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
        """Le clavier va à la vue (jamais à la recherche à l'ouverture)."""
        target = {"jour": self.day.canvas, "semaine": self.week.canvas, "travail": self.week.canvas,
                  "mois": self.month}.get(self.view, self)
        target.setFocus()

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

    def days_shown(self) -> list[date]:
        fw = self.ctx.first_weekday
        if self.view == "jour":
            return [self.cur]
        start = tu.week_start(self.cur, fw)
        days = [start + timedelta(days=i) for i in range(7)]
        if self.view == "travail" or not self.settings.get("agenda_show_weekends", True):
            work = set(self.settings.get("agenda_work_days") or [0, 1, 2, 3, 4])
            days = [d for d in days if d.weekday() in work] or days
        return days

    def refresh(self) -> None:
        view = self.view
        page = self.pages["recherche" if self.search_text else view]
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
        self.header.seg.set_current(view)
        prev_tip, next_tip = STEP_LABELS[view]
        self.header.prev.setToolTip(prev_tip)
        self.header.next.setToolTip(next_tip)
        self.header.title.set_text(*self._title())
        if self.search_text:
            self._refresh_results()
        elif view in ("jour", "semaine", "travail"):
            self._refresh_grid()
        elif view == "mois":
            first = self.cur.replace(day=1)
            grid = tu.month_grid(first, self.ctx.first_weekday)
            occs = self.service.occurrences(grid[0][0], grid[-1][-1] + timedelta(days=1))
            self.month.set_data(first, occs, self.sel_key, self.cur)
        elif view == "annee":
            self.year.set_data(self.cur.year, self.service.day_counts(self.cur.year))
        elif view == "planning":
            n = int(self.settings.get("agenda_list_days", 30) or 30)
            occs = self.service.occurrences(self.cur, self.cur + timedelta(days=n))
            groups = group_by_day(occs, self.cur, self.cur + timedelta(days=n), today=self.ctx.today())
            self.planning.set_groups(groups, self.sel_key, f"Rien de prévu dans les {n} prochains jours.")
        self._refresh_sidebar()
        QTimer.singleShot(0, self, lambda: self.service.prefetch(self.cur))
        self.stateChanged.emit()

    def _title(self) -> tuple[str, str]:
        cur, view = self.cur, self.view
        if self.search_text:
            return "Recherche", f"« {self.search_text} »"
        if view == "jour":
            return tu.fmt_day_long(cur), f"Semaine {tu.iso_week(cur)}"
        if view in ("semaine", "travail"):
            days = self.days_shown()
            a, b = days[0], days[-1]
            if a.month == b.month:
                title = f"{tu.cap(tu.MONTHS[a.month - 1])} {a.year}"
            elif a.year == b.year:
                title = f"{tu.cap(tu.MONTHS_SHORT[a.month - 1])} – {tu.MONTHS_SHORT[b.month - 1]} {b.year}"
            else:
                title = f"{tu.cap(tu.MONTHS_SHORT[a.month - 1])} {a.year} – {tu.MONTHS_SHORT[b.month - 1]} {b.year}"
            return title, f"Semaine {tu.iso_week(a)}"
        if view == "mois":
            return f"{tu.cap(tu.MONTHS[cur.month - 1])} {cur.year}", ""
        if view == "annee":
            return str(cur.year), ""
        n = int(self.settings.get("agenda_list_days", 30) or 30)
        end = cur + timedelta(days=n - 1)
        return "Prochains événements", (f"du {cur.day} {tu.MONTHS_SHORT[cur.month - 1]} au {end.day} "
                                        f"{tu.MONTHS_SHORT[end.month - 1]}")

    def _refresh_grid(self) -> None:
        days = self.days_shown()
        occs = self.service.occurrences(days[0], days[-1] + timedelta(days=1))
        grid = self.day if self.view == "jour" else self.week
        grid.set_data(days, occs, "day" if self.view == "jour" else "week", self.sel_key)
        key = "day" if self.view == "jour" else "week"
        if key not in self._scrolled_once:
            self._scrolled_once.add(key)
            QTimer.singleShot(0, grid, grid.scroll_to_start)
        if self.view == "jour":
            sel = next((o for o in occs if o.key == self.sel_key), None)
            if sel is None and occs and self.settings.get("agenda_day_autoselect", True):
                timed = [o for o in occs if not o.spans_days()]
                now = self.ctx.now()
                if self.cur == self.ctx.today():
                    sel = next((o for o in timed if o.end > now), None)
                sel = sel or (timed[0] if timed else occs[0])
                self.sel_key = sel.key
                grid.set_selected(sel.key)
            self.details.show_occurrence(sel)

    def _refresh_sidebar(self) -> None:
        if not self.sidebar.isVisible():
            return
        mini = self.mini_month or self.cur.replace(day=1)
        grid = tu.month_grid(mini, self.ctx.first_weekday)
        start, end = grid[0][0], grid[-1][-1] + timedelta(days=1)
        dots: dict[date, list[str]] = {}
        for occ in self.service.occurrences(start, end):
            key = self.ctx.color_key(occ)
            for d in occ.days():
                lst = dots.setdefault(d, [])
                if key not in lst and len(lst) < 3:
                    lst.append(key)
        week_first = self.days_shown()[0] if self.view in ("semaine", "travail") else None
        self.sidebar.mini.set_state(mini, self.cur, self.view, week_first, dots)
        if self.settings.get("agenda_show_upcoming", True):
            occs = self.service.occurrences(self.cur, self.cur + timedelta(days=21))
            groups = group_by_day(occs, self.cur, self.cur + timedelta(days=21), max_groups=3, today=self.ctx.today())
            self.sidebar.upcoming.set_groups(groups, self.sel_key, "Rien de prévu dans les trois semaines.")
        else:
            self.sidebar.upcoming.set_groups([], None, "")
        self.sidebar.calendars.set_calendars(self.service.calendars())
        self._refresh_sync()

    def _refresh_sync(self) -> None:
        """État discret de la synchronisation (bas du panneau latéral)."""
        import time as _time
        manager = getattr(self.service, "sync", None)
        accounts = manager.accounts() if manager is not None else []
        if not accounts:
            self.sidebar.sync.set_state("", "ok")
            return
        pending = self.service.repo.outbox_count()
        conflicts = len(manager.conflicts())
        tail = f" · {pending} en attente" if pending else ""
        if conflicts:
            text, level = f"{conflicts} conflit{'s' if conflicts > 1 else ''} à résoudre{tail}", "conflict"
        elif manager.running:
            text, level = "Synchronisation…", "busy"
        elif any(a.get("status") == "auth_error" for a in accounts):
            text, level = "Google : reconnexion nécessaire", "error"
        elif manager.state.get("offline"):
            text, level = "Hors ligne" + tail, "offline"
        elif manager.state.get("error"):
            text, level = "Erreur de synchronisation" + tail, "error"
        else:
            last = max((a.get("last_sync_at") or 0) for a in accounts)
            text = ("Synchronisé à " + _time.strftime("%H:%M", _time.localtime(last)) if last else "Pas encore synchronisé")
            text, level = text + tail, "ok"
        self.sidebar.sync.set_state(text, level)
        self.sidebar.sync.setToolTip(manager.status_text())

    def _open_settings(self) -> None:
        hook = HOOKS.get("open_settings")
        if callable(hook):
            hook()

    def _persist_nav(self) -> None:
        self.service.set_pref("view", self.view)
        self.service.set_pref("date", self.cur.isoformat())

    # -- navigation --

    def set_view(self, view: str) -> None:
        if self.search_text:
            self.clear_search()
        if view == self.view:
            self.refresh()
            return
        self.view = view
        self.mini_month = None
        self._persist_nav()
        self.refresh()

    def step(self, direction: int) -> None:
        v = self.view
        if v == "jour":
            self.cur += timedelta(days=direction)
        elif v in ("semaine", "travail"):
            self.cur += timedelta(days=7 * direction)
        elif v == "mois":
            self.cur = tu.add_months(self.cur.replace(day=1), direction)
        elif v == "annee":
            self.cur = date(self.cur.year + direction, self.cur.month, 1)
        else:
            self.cur += timedelta(days=7 * direction)
        self.mini_month = None
        self.sel_key = None
        self._persist_nav()
        self.refresh()

    def go_today(self) -> None:
        self.cur = self.ctx.today()
        self.mini_month = None
        self.sel_key = None
        self._persist_nav()
        self.refresh()
        if self.view in ("jour", "semaine", "travail"):
            grid = self.day if self.view == "jour" else self.week
            now = self.ctx.now()
            grid.scroll_to_minute(now.hour * 60 + now.minute, center=True)

    def _goto(self, d: date, view: str | None = None, sel: str | None = None) -> None:
        self.cur = d
        if view:
            self.view = view
        self.sel_key = sel
        self.mini_month = None
        if self.search_text:
            self.search_text = ""
            self.header.search.edit.blockSignals(True)
            self.header.search.edit.clear()
            self.header.search.edit.blockSignals(False)
        self._persist_nav()
        self.refresh()

    def open_day(self, d: date, occ: Occurrence | None = None) -> None:
        self._goto(d, "jour", occ.key if occ else None)
        if occ is not None:
            QTimer.singleShot(0, self, lambda: self.day.ensure_visible(occ))

    def go_to_date(self) -> None:
        text = kit.ask_text(self, "Aller à une date", "Date (6/11/2026, 12 déc., demain…)",
                            tu.fmt_numeric(self.cur), "Aller")
        if text is None:
            return
        d = tu.parse_user_date(text, self.ctx.today())
        if d is None:
            self._status("Date illisible : " + text)
            return
        self._goto(d)

    def mini_month_changed(self, month: date) -> None:
        self.mini_month = month
        self._refresh_sidebar()

    def _mini_picked(self, d: date) -> None:
        self._goto(d, None)

    def _month_day_selected(self, d: date) -> None:
        self.cur = d
        self._persist_nav()
        self.refresh()

    def _day_rollover(self) -> None:
        today = self.ctx.today()
        if today != self._today:
            if self.cur == self._today:
                self.cur = today
            self._today = today
            self.refresh()

    # -- sélection --

    def _select(self, occ: Occurrence | None) -> None:
        self.sel_key = occ.key if occ else None
        for w in (self.week, self.day, self.month, self.planning, self.results, self.sidebar.upcoming):
            w.set_selected(self.sel_key)
        if self.view == "jour" and not self.search_text:
            self.details.show_occurrence(occ if occ else None)

    def _grid_picked(self, occ: Occurrence | None) -> None:
        if occ is not None and self.view in ("semaine", "travail") and \
                self.settings.get("agenda_week_click", "selection") == "jour":
            self.open_day(occ.start_date if occ.all_day else occ.start.date(), occ)
            return
        self._select(occ)

    def _list_picked(self, occ: Occurrence) -> None:
        d = occ.start_date if occ.all_day else occ.start.date()
        if self.search_text or self.view == "planning":
            self._select(occ)
            return
        if self.view in ("jour", "semaine", "travail") and d in self.days_shown():
            self._select(occ)
            grid = self.day if self.view == "jour" else self.week
            grid.ensure_visible(occ)
            return
        self.open_day(d, occ)

    def selected_occurrence(self) -> Occurrence | None:
        if not self.sel_key:
            return None
        for occ in self._visible_occurrences():
            if occ.key == self.sel_key:
                return occ
        return None

    def _visible_occurrences(self) -> list[Occurrence]:
        if self.search_text:
            return [r[2] for r in self.results.rows if r[1] in ("item", "bar")]
        if self.view in ("jour", "semaine", "travail"):
            days = self.days_shown()
            return self.service.occurrences(days[0], days[-1] + timedelta(days=1))
        if self.view == "mois":
            first = self.cur.replace(day=1)
            return self.service.occurrences(first, tu.add_months(first, 1))
        if self.view == "planning":
            n = int(self.settings.get("agenda_list_days", 30) or 30)
            return self.service.occurrences(self.cur, self.cur + timedelta(days=n))
        return self.service.occurrences(self.cur, self.cur + timedelta(days=1))

    def _cycle(self, direction: int) -> None:
        occs = self._visible_occurrences()
        if not occs:
            return
        keys = [o.key for o in occs]
        i = keys.index(self.sel_key) if self.sel_key in keys else (-1 if direction > 0 else 0)
        occ = occs[(i + direction) % len(occs)]
        self._select(occ)
        if self.view in ("jour", "semaine", "travail"):
            (self.day if self.view == "jour" else self.week).ensure_visible(occ)

    def _escape(self) -> None:
        if self.search_text:
            self.clear_search()
        elif self.sel_key:
            self._select(None)

    # -- recherche --

    def _search_typed(self, text: str) -> None:
        self._search_timer.start()

    def _run_search(self) -> None:
        text = self.header.search.text().strip()
        if text == self.search_text:
            return
        self.search_text = text
        self.refresh()

    def _search_submit(self, text: str) -> None:
        self._search_timer.stop()
        self._run_search()
        occs = [r[2] for r in self.results.rows if r[1] in ("item", "bar")]
        if occs:
            occ = occs[0]
            today = self.ctx.today()
            future = [o for o in occs if (o.start_date if o.all_day else o.start.date()) >= today]
            occ = future[0] if future else occ
            self.open_day(occ.start_date if occ.all_day else occ.start.date(), occ)

    def _focus_search(self) -> None:
        self.header.search.show()
        self.header.search.focus()

    def clear_search(self) -> None:
        self._search_timer.stop()
        self.header.search.edit.blockSignals(True)
        self.header.search.edit.clear()
        self.header.search.edit.blockSignals(False)
        self.header._compact = -1
        self.header.apply_width(self.content_width())
        if self.search_text:
            self.search_text = ""
            self.refresh()
        self.focus_view()

    def _refresh_results(self) -> None:
        occs = self.service.search(self.search_text)
        today = self.ctx.today()
        groups = []
        by_day: dict[date, list] = {}
        for o in occs:
            by_day.setdefault(o.start_date if o.all_day else o.start.date(), []).append(o)
        for d in sorted(by_day):
            badge = "Aujourd'hui" if d == today else ("Passé" if d < today else "")
            groups.append((f"{tu.fmt_day_short(d)} {d.year}", badge, d, by_day[d]))
        self.results.set_groups(groups, self.sel_key, f"Aucun événement ne correspond à « {self.search_text} ».")

    # -- création / édition --

    def _editor_window(self):
        if self._editor is None:
            from .editor import EventEditor
            # Sans parent (comme les fenêtres de réglages) : la feuille globale de la fenêtre principale
            # (`QWidget { background… }`) ne déteint pas sur les briques ; centrée sur la fenêtre de l'agenda.
            self._editor = EventEditor(self.service, self.holder, None)
            self._editor.anchor = self
        return self._editor

    def prebuild_editor(self) -> None:
        """Éditeur construit pendant un temps mort : sa première ouverture est immédiate."""
        try:
            self._editor_window()
        except Exception:                                # noqa: BLE001
            log.exception("préparation de l'éditeur")

    def new_event(self, start=None, end=None, all_day: bool = False) -> None:
        if start is None:
            if self.view in ("jour", "semaine", "travail", "mois") and self.cur:
                now = self.ctx.now()
                hour = now.hour + 1 if self.cur == self.ctx.today() else int(self.settings.get("agenda_day_start", 8)) + 1
                hour = min(23, hour)
                start = tu.localize(datetime(self.cur.year, self.cur.month, self.cur.day, hour), self.ctx.tz)
            else:
                start = None
        draft = self.service.new_draft(start, end, all_day)
        if self.settings.get("agenda_create_mode", "editor") == "direct" and start is not None:
            draft.title = "Nouvel événement"
            eid = self.service.create(draft)
            self.sel_key = eid
            self._status("Événement créé")
            return
        self._open_editor(None, draft, True)

    def _create_at(self, start, end, all_day: bool) -> None:
        self.new_event(start, end, all_day)

    def edit_occurrence(self, occ: Occurrence) -> None:
        try:
            draft = self.service.draft_for(occ)
        except KeyError:
            self._status("Événement introuvable (supprimé entre-temps ?)")
            return
        self._open_editor(occ, draft, False)

    def _open_editor(self, occ, draft, is_new: bool) -> None:
        editor = self._editor_window()
        result = editor.edit(occ, draft, is_new)
        action = editor.action
        if action == "delete" and occ is not None:
            self.delete_occurrence(occ, confirm=False)
            return
        if action == "duplicate" and occ is not None:
            self.duplicate(occ)
            return
        if result is None or action != "save":
            return
        scope = "all"
        if occ is not None and occ.recurring:
            original = self.service.draft_for(occ)
            rule_changed = (result.rrule or None) != (original.rrule or None)
            scope = self._ask_scope("Modifier un événement récurrent", allow_this=not rule_changed)
            if scope is None:
                return
        eid = self.service.save_draft(occ, result, scope)
        d = result.start_date if result.all_day else result.start.astimezone(self.ctx.tz).date()
        self._status("Événement enregistré" if not is_new else "Événement créé")
        if is_new:
            self.sel_key = eid
            if self.view in ("jour", "semaine", "travail", "mois") and not self._is_shown(d):
                self._goto(d, None, eid)

    def _is_shown(self, d: date) -> bool:
        if self.view in ("jour", "semaine", "travail"):
            return d in self.days_shown()
        if self.view == "mois":
            return (d.year, d.month) == (self.cur.year, self.cur.month)
        return True

    def _ask_scope(self, title: str, allow_this: bool = True) -> str | None:
        choices = ([("this", "Cette occurrence")] if allow_this else []) + [
            ("following", "Celle-ci et les suivantes"), ("all", "Toute la série")]
        return kit.choose(self, title, "Cet événement fait partie d'une série. Que faut-il modifier ?", choices)

    def move_occurrence(self, occ: Occurrence, start, end) -> None:
        if occ.read_only:
            self._status("Calendrier en lecture seule")
            return
        scope = "all"
        if occ.recurring:
            mode = self.settings.get("agenda_recurring_move", "ask")
            scope = mode if mode in ("this", "all") else self._ask_scope("Déplacer un événement récurrent")
            if scope is None:
                self.refresh()
                return
        self.service.move_occurrence(occ, start, end, scope)
        self.sel_key = occ.key if scope != "following" else None
        self._status("Événement déplacé" if (end - start) == (occ.end - occ.start if not occ.all_day else
                                                                 occ.end_date - occ.start_date) else "Durée modifiée")

    def delete_occurrence(self, occ: Occurrence, confirm: bool = True) -> None:
        if occ.read_only:
            self._status("Calendrier en lecture seule")
            return
        if occ.recurring:
            scope = kit.choose(self, "Supprimer un événement récurrent",
                               f"« {occ.title or '(Sans titre)'} » fait partie d'une série. Que faut-il supprimer ?",
                               [("this", "Cette occurrence"), ("following", "Celle-ci et les suivantes"),
                                ("all", "Toute la série")])
            if scope is None:
                return
        else:
            scope = "all"
            if confirm and self.settings.get("agenda_confirm_delete", True):
                if not kit.confirm(self, "Supprimer l'événement", f"Supprimer « {occ.title or '(Sans titre)'} » ?",
                                   "Supprimer"):
                    return
        self.service.delete_occurrence(occ, scope)
        if self.sel_key == occ.key:
            self.sel_key = None
        self._status("Événement supprimé (Ctrl+Z pour annuler)")

    def duplicate(self, occ: Occurrence, days: int = 0) -> None:
        eid = self.service.duplicate(occ, days)
        self.sel_key = eid
        self._status("Événement dupliqué")

    def _toggle_done(self, occ: Occurrence) -> None:
        if occ.read_only:
            return
        self.service.set_done(occ, not occ.done)

    def _edit_selected(self) -> None:
        occ = self.selected_occurrence()
        if occ is not None:
            self.edit_occurrence(occ)

    def _delete_selected(self) -> None:
        occ = self.selected_occurrence()
        if occ is not None:
            self.delete_occurrence(occ)

    def _duplicate_selected(self) -> None:
        occ = self.selected_occurrence()
        if occ is not None:
            self.duplicate(occ)

    def _copy_selected(self) -> None:
        occ = self.selected_occurrence()
        if occ is not None:
            self._clipboard = occ
            self._status(f"Copié : {occ.title or '(Sans titre)'}")

    def _paste(self, slot=None) -> None:
        occ = self._clipboard
        if occ is None:
            return
        try:
            draft = self.service.draft_for(occ)
        except KeyError:
            return
        target = slot if slot is not None else (self.cur if self.view not in ("jour", "semaine", "travail")
                                                else self.cur)
        copy_ = draft.copy()
        from ..core.model import new_id
        copy_.id = new_id()
        copy_.rrule, copy_.exdates, copy_.series_id, copy_.recurrence_id = None, [], None, None
        copy_.remote_id = copy_.etag = copy_.ical_uid = None
        if isinstance(target, datetime) and not copy_.all_day:
            dur = copy_.end - copy_.start
            copy_.start = target.astimezone(copy_.tz)
            copy_.end = copy_.start + dur
        else:
            d = target.date() if isinstance(target, datetime) else target
            if copy_.all_day:
                dur = copy_.end_date - copy_.start_date
                copy_.start_date, copy_.end_date = d, d + dur
            else:
                dur = copy_.end - copy_.start
                s = copy_.start.astimezone(self.ctx.tz)
                copy_.start = tu.localize(datetime(d.year, d.month, d.day, s.hour, s.minute), self.ctx.tz)
                copy_.end = copy_.start + dur
        self.sel_key = self.service.create(copy_, "Coller l'événement")
        self._status("Événement collé")

    def undo(self) -> None:
        label = self.service.undo_label()
        if self.service.undo():
            self._status(f"Annulé : {label}")

    def redo(self) -> None:
        label = self.service.redo_label()
        if self.service.redo():
            self._status(f"Rétabli : {label}")

    def _zoom(self, factor: float) -> None:
        self.ctx.zoom = max(0.5, min(3.0, self.ctx.zoom * factor))
        self.service.set_pref("hour_zoom", round(self.ctx.zoom, 3))
        for grid in (self.week, self.day):
            grid.zoom_changed()

    # -- menus contextuels --

    def _context(self, occ: Occurrence | None, slot, global_pos) -> None:
        menu = kit.themed_menu(self)
        if occ is not None:
            self._select(occ)
            menu.addAction("Voir" if occ.read_only else "Modifier…", lambda: self.edit_occurrence(occ))
            menu.addAction("Dupliquer", lambda: self.duplicate(occ))
            menu.addAction("Dupliquer au lendemain", lambda: self.duplicate(occ, 1))
            menu.addAction("Copier", lambda: (setattr(self, "_clipboard", occ), self._status("Copié")))
            if occ.is_task and not occ.read_only:
                menu.addAction("Marquer comme non faite" if occ.done else "Marquer comme faite",
                               lambda: self._toggle_done(occ))
            if not occ.read_only:
                colors = menu.addMenu("Couleur")
                colors.addAction("Couleur du calendrier", lambda: self._recolor(occ, None))
                for key in PALETTE:
                    colors.addAction(PALETTE_LABELS[key], lambda k=key: self._recolor(occ, k))
                cals = [c for c in self.service.writable_calendars() if c.id != occ.calendar_id]
                if cals and not occ.recurring:
                    move = menu.addMenu("Déplacer vers le calendrier")
                    for cal in cals:
                        move.addAction(cal.name, lambda c=cal: self._move_calendar(occ, c.id))
            if occ.folder:
                menu.addAction("Ouvrir le dossier", lambda: self._open_folder(occ.folder))
            ev = self.service.get_event(occ.event_id)
            if ev is not None and ev.url:
                menu.addAction("Ouvrir le lien", lambda: self._open_url(ev.url))
            menu.addAction("Exporter en .ics…", lambda: self._export_one(occ))
            if not occ.read_only:
                menu.addSeparator()
                menu.addAction("Supprimer", lambda: self.delete_occurrence(occ))
        else:
            if isinstance(slot, datetime):
                minutes = int(self.settings.get("agenda_default_duration", 60) or 60)
                menu.addAction("Nouvel événement ici", lambda: self.new_event(slot, slot + timedelta(minutes=minutes)))
                menu.addAction("Nouvel événement sur la journée",
                               lambda: self.new_event(slot.date(), slot.date() + timedelta(days=1), True))
            elif isinstance(slot, date):
                menu.addAction("Nouvel événement sur la journée",
                               lambda: self.new_event(slot, slot + timedelta(days=1), True))
                start = tu.localize(datetime(slot.year, slot.month, slot.day,
                                             int(self.settings.get("agenda_day_start", 8)) + 1), self.ctx.tz)
                menu.addAction("Nouvel événement à l'heure", lambda: self.new_event(start))
                menu.addAction("Ouvrir ce jour", lambda: self.open_day(slot))
            if self._clipboard is not None and slot is not None:
                menu.addAction("Coller", lambda: self._paste(slot))
            menu.addSeparator()
            menu.addAction("Aller à une date… (Ctrl+G)", self.go_to_date)
        if not menu.isEmpty():
            menu.exec(global_pos)

    def _recolor(self, occ: Occurrence, color) -> None:
        draft = self.service.draft_for(occ)
        draft.color = color
        scope = "all"
        if occ.recurring:
            scope = self._ask_scope("Changer la couleur")
            if scope is None:
                return
        self.service.save_draft(occ, draft, scope)

    def _move_calendar(self, occ: Occurrence, cal_id: str) -> None:
        draft = self.service.draft_for(occ)
        draft.calendar_id = cal_id
        self.service.save_draft(occ, draft, "all")
        self._status("Événement déplacé vers « %s »" % self.ctx.calendar_name(cal_id))

    def _calendar_menu(self, cal, global_pos) -> None:
        menu = kit.themed_menu(self)
        if cal is not None:
            menu.addAction("Afficher uniquement celui-ci", lambda: self._only_calendar(cal.id))
            menu.addAction("Tout afficher", self._all_calendars)
            menu.addSeparator()
            if not cal.read_only or cal.source == "local":
                menu.addAction("Renommer…", lambda: self._rename_calendar(cal))
            colors = menu.addMenu("Couleur")
            for key in PALETTE:
                colors.addAction(PALETTE_LABELS[key], lambda k=key: self.service.update_calendar(cal.id, color=k))
            if not cal.read_only:
                menu.addAction("Calendrier par défaut", lambda: self._default_calendar(cal.id))
            menu.addAction("Exporter en .ics…", lambda: self._export_calendar(cal))
            if not cal.read_only:
                menu.addAction("Importer un .ics dans ce calendrier…", lambda: self._import_ics(cal.id))
            if cal.source == "local":
                menu.addSeparator()
                menu.addAction("Supprimer le calendrier…", lambda: self._delete_calendar(cal))
            menu.addSeparator()
        menu.addAction("Nouveau calendrier…", self.new_calendar)
        menu.addAction("Synchronisation Google…", self._open_settings)
        menu.exec(global_pos)

    def _only_calendar(self, cal_id: str) -> None:
        for cal in self.service.calendars():
            if cal.visible != (cal.id == cal_id):
                self.service.set_visible(cal.id, cal.id == cal_id)

    def _all_calendars(self) -> None:
        for cal in self.service.calendars():
            if not cal.visible:
                self.service.set_visible(cal.id, True)

    def _rename_calendar(self, cal) -> None:
        name = kit.ask_text(self, "Renommer le calendrier", "Nouveau nom", cal.name, "Renommer")
        if name and name.strip():
            self.service.update_calendar(cal.id, name=name.strip())

    def _default_calendar(self, cal_id: str) -> None:
        self.settings["agenda_default_calendar"] = cal_id
        self.service.apply_settings({"agenda_default_calendar": cal_id})
        saver = HOOKS.get("save_setting")
        if callable(saver):
            saver("agenda_default_calendar", cal_id)
        self._status("Calendrier par défaut : " + self.ctx.calendar_name(cal_id))

    def new_calendar(self) -> None:
        name = kit.ask_text(self, "Nouveau calendrier", "Nom du calendrier (Personnel, Famille, Projets…)", "",
                            "Créer")
        if name and name.strip():
            used = {c.color for c in self.service.calendars()}
            color = next((k for k in PALETTE if k not in used), "bleu")
            self.service.create_calendar(name.strip(), color)

    def _delete_calendar(self, cal) -> None:
        n = sum(1 for _o in self.service.repo.events_of_calendar(cal.id))
        if kit.confirm(self, "Supprimer le calendrier",
                       f"Supprimer « {cal.name} » et ses {n} événement(s) ? Cette suppression ne peut pas être "
                       f"annulée (une sauvegarde automatique de la base existe).", "Supprimer"):
            self.service.delete_calendar(cal.id)

    # -- ICS --

    def _export_one(self, occ: Occurrence) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getSaveFileName(self, "Exporter l'événement", (occ.title or "evenement") + ".ics",
                                               "iCalendar (*.ics)")
        if path:
            from ..services import ics_io
            n = ics_io.export_events(self.service, path, event_ids=[occ.series_id or occ.event_id])
            self._status(f"{n} événement(s) exporté(s) : {path}")

    def _export_calendar(self, cal) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getSaveFileName(self, "Exporter le calendrier", cal.name + ".ics", "iCalendar (*.ics)")
        if path:
            from ..services import ics_io
            n = ics_io.export_events(self.service, path, calendar_ids=[cal.id])
            self._status(f"{n} événement(s) exporté(s) : {path}")

    def _import_ics(self, cal_id: str) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getOpenFileName(self, "Importer un calendrier", "", "iCalendar (*.ics)")
        if path:
            from ..services import ics_io
            try:
                report = ics_io.import_file(self.service, path, cal_id)
            except Exception as exc:                     # noqa: BLE001
                self._status(f"Import impossible : {exc}")
                return
            self._status(report.summary())

    # -- divers --

    def _open_folder(self, path: str) -> None:
        if not path:
            return
        hook = HOOKS.get("open_folder")
        if callable(hook):
            hook(path)
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if url and kit.confirm(self, "Ouvrir le lien", f"Ouvrir {url} dans le navigateur ?", "Ouvrir"):
            QDesktopServices.openUrl(QUrl(url))

    def _status(self, text: str) -> None:
        try:
            HOOKS["status"](text)
        except Exception:                                # noqa: BLE001
            pass

    def _message(self, level: str, text: str) -> None:
        self._status(("⚠ " if level == "erreur" else "") + text)

    def confirm_leave(self) -> bool:
        return True                                      # tout est déjà enregistré (écritures immédiates)

    def request_close(self) -> None:
        self.closeRequested.emit()

    def shutdown(self) -> None:
        self._now_timer.stop()
        if self._editor is not None:
            self._editor.deleteLater()
            self._editor = None
