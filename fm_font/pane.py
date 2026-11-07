"""Espace de travail plein écran du module typographique (Qt) : recouvre la zone des colonnes comme les modules à
affichage standard (fm_markdown, mode Standard du Tableur). Barre du haut (projet, enregistrer, exporter, annuler,
pages), pages Glyphes / Éditeur / Aperçu / Features / Diagnostic, panneaux à droite, barre d'état.

Le module n'importe RIEN de la fenêtre principale : elle pose `HOOKS` (réglages, enregistrement d'un réglage,
fenêtre de réglages du module, barre d'état de la fenêtre)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from . import actions, components, glyph_info
from .canvas import GlyphCanvas
from .compile import CompileError, export
from .document import FontProject, ProjectError
from .glyph_grid import FILTERS, GlyphGrid
from .panels import (DiagnosticsPage, FeaturesPage, FontPanel, GlyphPanel, KerningPanel, MastersPanel, _label,
                     button)
from .preview import MODES, PreviewWidget
from .render import PathCache
from .settings_defaults import TYPO_DEFAULTS
from .tools import TOOLS


def tool_cells(label: str) -> int:
    """Largeur (en cases) du bouton à texte d'un outil."""
    from PySide6.QtGui import QFont, QFontMetrics
    from fm_theme.palette import step
    return max(2, -(-(QFontMetrics(QFont()).horizontalAdvance(label) + 18) // step()))


def default_bars_state() -> dict:
    """Barre « Outils » de l'éditeur par défaut (demande de l'utilisateur, 2026-11-03) : clipsée en haut, à gauche."""
    items, col = {}, 0
    for ident, cls in TOOLS.items():
        cells = tool_cells(cls.label)
        items[ident] = [col, 0, cells]
        col += cells
    return {"next": 2, "bars": [{"id": "b1", "title": "Outils", "dock": "top", "orient": "h", "along": 0, "x": 0,
                                 "y": 0, "cols": col, "rows": 1, "items": items}]}

# Posés par la fenêtre principale (main_window/font_module.py) ; défauts utilisables seuls (tests, lanceur).
HOOKS: dict = {
    "settings": lambda: {},                 # réglages appliqués (dict complet de l'appli)
    "status": lambda text: None,            # barre d'état de la fenêtre
    "open_settings": None,                  # fenêtre « Réglages : Typographie »
    "autosave_dir": None,                   # dossier des sauvegardes de secours (None : autosave.default_dir)
    # Vrai : la fenêtre principale montre annuler / rétablir / enregistrer / exporter / réglages / fermer dans le
    # cadre « Typographie » de sa barre de navigation ; le module ne les répète pas dans sa barre du haut.
    "navbar_frame": False,
}

PAGES = ("Glyphes", "Éditeur", "Aperçu", "Features", "Diagnostic")
EXPORT_FORMATS = (("otf", "OpenType CFF (.otf)"), ("otf-hinted", "OpenType CFF hinté, otfautohint (.otf)"),
                  ("ttf", "TrueType (.ttf)"), ("woff", "WOFF (.woff)"),
                  ("woff2", "WOFF2 (.woff2)"), ("ttf-hinted", "TrueType hinté, ttfautohint (.ttf)"),
                  ("woff2-hinted", "WOFF2 hinté (.woff2)"), ("variable-ttf", "Police variable TrueType (.ttf)"),
                  ("variable-woff2", "Police variable WOFF2 (.woff2)"))


class _ExportRelay(QObject):
    done = Signal(object, object)                         # diagnostics, erreur (texte) : retour du fil d'export


def confirm(parent, title: str, message: str, action: str) -> bool:
    from fm_theme.dialogs import confirm as theme_confirm
    return theme_confirm(parent, "TYPOGRAPHIE", title, message, action=action)


def _settings() -> dict:
    settings = dict(TYPO_DEFAULTS)
    try:
        settings.update(HOOKS["settings"]() or {})
    except Exception:                                       # noqa: BLE001 - réglages illisibles : défauts
        pass
    return settings


class FontPane(QWidget):
    closeRequested = Signal()
    dirtyChanged = Signal(bool)
    stateChanged = Signal()           # annuler / rétablir possibles ou « modifié » ont changé (cadre de la barre)
    pageChanged = Signal(str)         # page montrée (planche « Glyphes », « Éditeur »…) : bouton planche de la barre

    def __init__(self, parent=None, project: FontProject | None = None):
        super().__init__(parent)
        from fm_theme.tokens import M
        self.settings = _settings()
        self._seed_look()
        self.setObjectName("FontPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#FontPane {{ background: {M.get('panel_bg', '#16181a')}; }}")
        self.project = project or self._new_project()
        self.cache = PathCache(self.project)
        self.current_name: str | None = None
        self._last_dirty = False
        self._last_state = None
        from .autosave import Autosaver
        self.autosaver = Autosaver(HOOKS.get("autosave_dir"))
        self._autosaved_revision = None
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._restart_autosave()
        self._build()
        self._attach_project()
        self.show_page("Glyphes")
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

    # -- construction --

    def _seed_look(self) -> None:
        """Style commun des briques (zones de saisie, tableaux) lu à leur création, comme le panneau du CAD."""
        try:
            import settings_window_v2 as v2
            full = self.settings if "colors" in self.settings else None
            if full is None:
                from settings_store import load_settings
                full = load_settings()
            v2.seed_window_look(full)
        except Exception:                                   # noqa: BLE001 - seul : défauts des briques
            pass

    def _new_project(self) -> FontProject:
        s = self.settings
        return FontProject.new("Nouvelle famille", upm=int(s["typo_new_upm"]), ascender=int(s["typo_new_ascender"]),
                               descender=int(s["typo_new_descender"]), cap_height=int(s["typo_new_cap_height"]),
                               x_height=int(s["typo_new_x_height"]))

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(8, 4, 8, 2)
        self.title = _label("", "value")
        top.addWidget(self.title, 1)
        self.page_buttons = {}
        for page in PAGES:
            tip = ("Planche des glyphes (Ctrl+1 ; Échap depuis une lettre)" if page == "Glyphes"
                   else f"Page {page} (Ctrl+{PAGES.index(page) + 1})")
            b = button(page, tip, lambda p=page: self.show_page(p))
            b.setCheckable(True)
            self.page_buttons[page] = b
            top.addWidget(b)
        top.addSpacing(10)
        self.master_button = button("", "Master affiché (clic : choisir)", self.master_menu)
        top.addWidget(self.master_button)
        self.undo_button = button("Annuler", "Annuler (Ctrl+Z)", lambda: self.project.undo.undo())
        self.redo_button = button("Rétablir", "Rétablir (Ctrl+Y)", lambda: self.project.undo.redo())
        top.addWidget(self.undo_button)
        top.addWidget(self.redo_button)
        top.addSpacing(10)
        top.addWidget(button("Nouveau", "Nouveau projet (famille vide)", self.new_project))
        top.addWidget(button("Ouvrir…", "Ouvrir une source (.ufo, .designspace) ou importer une police "
                                        "(.ttf, .otf, .woff, .woff2)", self.open_dialog))
        self.save_button = button("Enregistrer", "Enregistrer la source (Ctrl+S)", self.save)
        top.addWidget(self.save_button)
        top.addWidget(button("Enregistrer sous…", "Enregistrer la source ailleurs (.designspace ou .ufo)",
                             self.save_as_dialog))
        self.export_button = button("Exporter…", "Compiler une police (OTF, TTF, WOFF, WOFF2, variable)",
                                    self.export_menu)
        top.addWidget(self.export_button)
        self.settings_button = None
        if HOOKS.get("open_settings"):
            self.settings_button = button("Réglages", "Réglages du module typographique",
                                          lambda: HOOKS["open_settings"]())
            top.addWidget(self.settings_button)
        self.close_button = button("Fermer", "Fermer le module (Échap depuis la grille)", self.request_close)
        top.addWidget(self.close_button)
        if HOOKS.get("navbar_frame"):                       # déjà dans le cadre « Typographie » de la barre
            for b in (self.undo_button, self.redo_button, self.save_button, self.export_button,
                      self.settings_button, self.close_button):
                if b is not None:
                    b.hide()
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal, self)
        self.pages = QStackedWidget()
        # Glyphes
        grid_page = QWidget()
        gl = QVBoxLayout(grid_page)
        gl.setContentsMargins(8, 4, 8, 4)
        bar = QHBoxLayout()
        from fm_theme.cells import _TextField
        self.search = _TextField("", 220)
        self.search.setPlaceholderText("Rechercher : nom, caractère, U+00E9")
        self.search.textChanged.connect(lambda t: self.grid.set_filter(query=t))
        bar.addWidget(self.search)
        self.filter_button = button("Tous", "Filtrer par catégorie Unicode", self.filter_menu)
        bar.addWidget(self.filter_button)
        self.charset_button = button("Manquants : aucun", "Montrer les glyphes manquants d'un jeu de caractères",
                                     self.charset_menu)
        bar.addWidget(self.charset_button)
        bar.addStretch(1)
        self.new_field = _TextField("", 160)
        self.new_field.setPlaceholderText("Nouveau : nom, é ou U+0041")
        self.new_field.returnPressed.connect(self.create_from_field)
        bar.addWidget(self.new_field)
        bar.addWidget(button("Créer", "Créer le glyphe (tous les masters)", self.create_from_field))
        gl.addLayout(bar)
        self.grid = GlyphGrid(self.project, self.cache, self.settings)
        gl.addWidget(self.grid, 1)
        self.pages.addWidget(grid_page)
        # Éditeur
        self.canvas = GlyphCanvas(self.project, self.cache, self.settings)
        self.pages.addWidget(self.canvas)
        # Aperçu
        preview_page = QWidget()
        pl = QVBoxLayout(preview_page)
        pl.setContentsMargins(8, 4, 8, 4)
        pbar = QHBoxLayout()
        self.preview_field = _TextField(self.settings["typo_preview_text"], 360)
        self.preview_field.setToolTip("Texte de l'aperçu (/nom = glyphe par son nom)")
        self.preview_field.textChanged.connect(lambda t: self.preview.set_text(t))
        pbar.addWidget(self.preview_field)
        self.mode_button = button("ligne", "Mode : ligne, paragraphe, cascade, masters", self.mode_menu)
        pbar.addWidget(self.mode_button)
        self.size_field = _TextField(str(self.settings["typo_preview_size"]), 54)
        self.size_field.setToolTip("Taille (px)")
        self.size_field.editingFinished.connect(self._preview_size)
        pbar.addWidget(self.size_field)
        self.hb_button = button("HarfBuzz", "Aperçu FIDÈLE : police compilée en fond et mise en forme par HarfBuzz "
                                            "(features ci-contre)", lambda: self.preview.set_hb(self.hb_button.isChecked()))
        self.hb_button.setCheckable(True)
        pbar.addWidget(self.hb_button)
        self.features_button = button("Features…", "Activer / désactiver des features (HarfBuzz)", self.features_menu)
        pbar.addWidget(self.features_button)
        self.exception_button = button("Exception", "Crénage : écrire une exception (paire de glyphes) au lieu de "
                                                    "la paire de classes", self._toggle_exception)
        self.exception_button.setCheckable(True)
        pbar.addWidget(self.exception_button)
        pbar.addStretch(1)
        pl.addLayout(pbar)
        hint = _label("Clic sur un glyphe : paire avec le précédent ; Alt + ← / → : crénage ±10 (Maj : ±1) ; "
                      "Ctrl + glisser : crénage à la souris.", "note")
        pl.addWidget(hint)
        self.preview = PreviewWidget(self.project, self.cache, self.settings)
        pl.addWidget(self.preview, 1)
        self.pages.addWidget(preview_page)
        self.features_page = FeaturesPage(self)
        self.pages.addWidget(self.features_page)
        self.diagnostics_page = DiagnosticsPage(self)
        self.pages.addWidget(self.diagnostics_page)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(6, 4, 6, 4)
        self.glyph_panel = GlyphPanel(self)
        self.font_panel = FontPanel(self)
        self.kerning_panel = KerningPanel(self)
        self.masters_panel = MastersPanel(self)
        for panel in (self.glyph_panel, self.font_panel, self.masters_panel, self.kerning_panel):
            sl.addWidget(panel)
            panel.message.connect(self.status)
        self.features_page.message.connect(self.status)
        self.diagnostics_page.glyphRequested.connect(self.show_glyph)
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setFrameShape(QScrollArea.NoFrame)
        split.addWidget(self.pages)
        split.addWidget(scroll)
        split.setStretchFactor(0, 1)
        split.setSizes([1020, 340])
        self._build_bars()
        root.addWidget(split, 1)
        self.status_label = _label("", "value_muted")
        self.status_label.setContentsMargins(10, 2, 10, 4)
        root.addWidget(self.status_label)

        self.grid.glyphActivated.connect(self.show_glyph)
        self.grid.missingActivated.connect(self.create_missing_code)
        self.grid.selectionChanged.connect(self._grid_selection)
        self.grid.contextRequested.connect(lambda pos: actions.grid_menu(self, pos.toPoint()))
        self.canvas.selectionChanged.connect(self.glyph_panel.refresh)
        self.canvas.glyphEdited.connect(self.glyph_panel.refresh)
        self.canvas.statusMessage.connect(self.status)
        self.canvas.toolChanged.connect(self._sync_tools)
        self.canvas.contextRequested.connect(lambda g, l: actions.canvas_menu(self, g.toPoint(), l))
        self.canvas.backRequested.connect(lambda: self.show_page("Glyphes"))
        self.preview.statusMessage.connect(self.status)
        self.preview.pairChanged.connect(lambda _p: self.kerning_panel.refresh())
        for keys, slot in (("Ctrl+Z", lambda: self.project.undo.undo()), ("Ctrl+Y", lambda: self.project.undo.redo()),
                           ("Ctrl+Shift+Z", lambda: self.project.undo.redo()), ("Ctrl+S", self.save),
                           ("Ctrl+1", lambda: self.show_page("Glyphes")), ("Ctrl+2", lambda: self.show_page("Éditeur")),
                           ("Ctrl+3", lambda: self.show_page("Aperçu")), ("Ctrl+4", lambda: self.show_page("Features")),
                           ("Ctrl+5", lambda: self.show_page("Diagnostic")),
                           ("Ctrl+Return", self._apply_features_if_open)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self._sync_tools("select")

    # -- projet --

    def _attach_project(self) -> None:
        self.project.listeners.append(self._on_change)
        if getattr(self, "_refresh_timer", None) is None:  # regroupe les notifications d'une même action
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.setInterval(30)
            self._refresh_timer.timeout.connect(self._refresh_views)
        for message in self.project.messages:
            self.status(message)
        self._refresh_views()

    def set_project(self, project: FontProject) -> None:
        """Remplace le projet (le précédent est détaché ; son état « modifié » a été traité par l'appelant)."""
        old = self.project
        if self._on_change in old.listeners:
            old.listeners.remove(self._on_change)
        self.cache.detach()
        self.preview.detach()
        self.project = project
        self.cache = PathCache(project)
        for widget in (self.grid, self.canvas, self.preview):
            widget.project = project
            widget.cache = self.cache
        project.listeners.append(self.preview._on_change)
        self.canvas.master = 0
        self.grid.master = 0
        self.current_name = None
        self.canvas.set_glyph(None, fit=False)
        self._attach_project()
        self.show_page("Glyphes")

    def _on_change(self, kind, payload) -> None:
        if kind == "glyphs" and self.current_name and self.current_name not in self.canvas.font:
            self.current_name = None
            self.canvas.set_glyph(None, fit=False)
        if kind == "masters":
            self.masters_changed()
        self._refresh_timer.start()                       # regroupe les notifications d'une même action

    def _refresh_views(self) -> None:
        if self.pages.currentWidget() is self.grid.parentWidget():
            self.grid.refresh()
        self.canvas.update()
        self.preview.update()
        self.glyph_panel.refresh()
        self.font_panel.refresh()
        self.kerning_panel.refresh()
        self.masters_panel.refresh()
        self._sync_title()

    def _sync_title(self) -> None:
        p = self.project
        where = p.path.name if p.path else (f"importé de {p.source.name}" if p.source else "non enregistré")
        dirty = p.is_dirty()
        self.title.setText(f"{p.family_name} — {where}" + (" — modifié" if dirty else ""))
        self.undo_button.setEnabled(p.undo.can_undo())
        self.redo_button.setEnabled(p.undo.can_redo())
        self.undo_button.setToolTip(f"Annuler : {p.undo.undo_label()} (Ctrl+Z)" if p.undo.can_undo() else "Annuler")
        self.redo_button.setToolTip(f"Rétablir : {p.undo.redo_label()} (Ctrl+Y)" if p.undo.can_redo() else "Rétablir")
        self.master_button.setText(f"Master : {p.masters[self.canvas.master].name}")
        if dirty != self._last_dirty:
            self._last_dirty = dirty
            self.dirtyChanged.emit(dirty)
        state = (p.undo.can_undo(), p.undo.can_redo(), dirty)
        if state != self._last_state:
            self._last_state = state
            self.stateChanged.emit()

    def status(self, text: str) -> None:
        self.status_label.setText(text)
        try:
            HOOKS["status"](text)
        except Exception:                                   # noqa: BLE001
            pass

    # -- pages --

    def current_page(self) -> str:
        return PAGES[self.pages.currentIndex()]

    def show_page(self, page: str) -> None:
        index = PAGES.index(page)
        self.pages.setCurrentIndex(index)
        for name, b in self.page_buttons.items():
            b.setChecked(name == page)
        self.tool_bars.set_visible(page == "Éditeur")
        if page != "Éditeur":
            self.pageChanged.emit(page)
        if page == "Glyphes":
            self.grid.refresh()
            if self.current_name is not None:
                self.grid.ensure_visible(self.current_name)    # la lettre quittée reste en vue
            self.grid.setFocus()
        elif page == "Éditeur":
            if self.current_name is None:
                names = self.grid.selected_names() or [n for n in self.project.glyph_order() if n != ".notdef"][:1]
                if names:
                    self.show_glyph(names[0])
                    return
            self.canvas.setFocus()
            self.pageChanged.emit(page)
        elif page == "Aperçu":
            self.preview.setFocus()
            if self.preview.use_hb:
                self.preview._compile_timer.start(0)
        elif page == "Features":
            self.features_page.refresh()
        elif page == "Diagnostic":
            self.diagnostics_page.run()

    def show_glyph(self, name: str) -> None:
        if name not in self.canvas.font:
            return
        self.current_name = name
        self.grid.select({name}, name)
        self.pages.setCurrentIndex(PAGES.index("Éditeur"))
        for page, b in self.page_buttons.items():
            b.setChecked(page == "Éditeur")
        self.tool_bars.set_visible(True)
        self.canvas.set_glyph(name)
        self.canvas.setFocus()
        self.pageChanged.emit("Éditeur")
        self.glyph_panel.refresh()
        self.kerning_panel.refresh()

    def _grid_selection(self) -> None:
        if self.grid.current:
            self.current_name = self.grid.current
            self.glyph_panel.refresh()
            self.kerning_panel.refresh()

    def _build_bars(self) -> None:
        """Outils de l'éditeur : barre FLOTTANTE de fm_theme (aspect : section « Palette » ; disposition retenue dans
        `typo_bars`), posée sur la page de l'éditeur, visible seulement sur elle."""
        from fm_theme.bar_manager import BarManager
        from fm_theme.palette import PaletteTextButton
        self.tool_bars = BarManager(self.pages)
        self.tool_bars.default_state = default_bars_state()
        self.tool_buttons = {}
        for ident, cls in TOOLS.items():
            b = PaletteTextButton(ident, cls.label, cls.tip, cells=tool_cells(cls.label))
            b.clicked.connect(lambda _c=False, i=ident: self.canvas.set_tool(i))
            self.tool_bars.register(ident, b)
            self.tool_buttons[ident] = b
        saved = self.settings.get("typo_bars")
        self.tool_bars.restore(saved if isinstance(saved, dict) and saved.get("bars") else None)
        self.tool_bars.layoutChanged.connect(self._save_bars)
        self.tool_bars.set_visible(False)

    def _save_bars(self) -> None:
        state = self.tool_bars.state()
        self.settings["typo_bars"] = state
        try:
            from settings_store import save_live_state
            save_live_state("typo_bars", state)
        except Exception:                                  # noqa: BLE001 - la session garde la disposition
            pass

    def _sync_tools(self, ident: str) -> None:
        for key, b in self.tool_buttons.items():
            b.set_active(key == ident)

    def masters_changed(self) -> None:
        self.cache.clear()
        self.masters_panel.refresh()
        self._sync_title()

    def set_master(self, index: int) -> None:
        self.canvas.set_master(index)
        self.grid.master = self.canvas.master
        self.preview.master = self.canvas.master
        self.cache.clear()
        self._refresh_views()

    # -- menus --

    def _popup(self, menu, anchor):
        menu.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def master_menu(self) -> None:
        from fm_theme.menu import Menu
        menu = Menu(self)
        for i, m in enumerate(self.project.masters):
            menu.addAction(m.name).triggered.connect(lambda _c=False, k=i: self.set_master(k))
        menu.addSeparator()
        compare = menu.addMenu("Comparer avec")
        compare.addAction("Aucun").triggered.connect(lambda: self._compare(None))
        for i, m in enumerate(self.project.masters):
            compare.addAction(m.name).triggered.connect(lambda _c=False, k=i: self._compare(k))
        self._popup(menu, self.master_button)

    def _compare(self, index) -> None:
        self.canvas.compare_master = index
        self.canvas.update()

    def filter_menu(self) -> None:
        from fm_theme.menu import Menu
        menu = Menu(self)
        for name in FILTERS:
            menu.addAction(name).triggered.connect(lambda _c=False, n=name: self._set_category(n))
        self._popup(menu, self.filter_button)

    def _set_category(self, name: str) -> None:
        self.filter_button.setText(name)
        self.grid.set_filter(category=name)

    def charset_menu(self) -> None:
        from fm_theme.menu import Menu
        menu = Menu(self)
        menu.addAction("Aucun").triggered.connect(lambda: self._set_charset(None))
        for name in glyph_info.CHARSETS:
            menu.addAction(name).triggered.connect(lambda _c=False, n=name: self._set_charset(n))
        self._popup(menu, self.charset_button)

    def _set_charset(self, name) -> None:
        self.charset_button.setText(f"Manquants : {name or 'aucun'}")
        self.grid.set_filter(charset=name)

    def mode_menu(self) -> None:
        from fm_theme.menu import Menu
        menu = Menu(self)
        for mode in MODES:
            menu.addAction(mode).triggered.connect(lambda _c=False, m=mode: self._set_mode(m))
        menu.addSeparator()
        strings = menu.addMenu("Chaînes de contrôle")
        from .metrics import CONTROL_STRINGS
        for label, text in CONTROL_STRINGS.items():
            strings.addAction(label).triggered.connect(lambda _c=False, t=text: self.preview_field.setText(t))
        if self.current_name:
            name = self.current_name
            strings.addAction(f"Glyphe courant entre n et o ({name})").triggered.connect(
                lambda: self.preview_field.setText(f"nn/{name} nono/{name} oo"))
        self._popup(menu, self.mode_button)

    def _set_mode(self, mode: str) -> None:
        self.mode_button.setText(mode)
        self.preview.set_mode(mode)

    def _preview_size(self) -> None:
        try:
            self.preview.set_size(int(float(self.size_field.text().replace(",", "."))))
        except ValueError:
            self.size_field.setText(str(self.preview.size))

    def features_menu(self) -> None:
        from fm_theme.menu import Menu
        from . import features as F
        menu = Menu(self)
        tags = list(dict.fromkeys(["kern", "liga", "mark", "mkmk", "calt"] + F.features_in(
            self.canvas.font.features.text or "")))
        for tag in tags:
            state = self.preview.features.get(tag)
            label = {None: "défaut", True: "activée", False: "désactivée"}[state]
            nxt = {None: True, True: False, False: None}[state]
            menu.addAction(f"{tag} : {label}").triggered.connect(
                lambda _c=False, t=tag, v=nxt: self.preview.set_feature(t, v))
        self._popup(menu, self.features_button)

    def _toggle_exception(self) -> None:
        self.preview.exception = self.exception_button.isChecked()

    def export_menu(self, anchor=None) -> None:
        from fm_theme.menu import Menu
        menu = Menu(self)
        for fmt, label in EXPORT_FORMATS:
            action = menu.addAction(label)
            action.setEnabled(not fmt.startswith("variable") or len(self.project.masters) > 1)
            action.triggered.connect(lambda _c=False, f=fmt: self.export_dialog(f))
        if len(self.project.masters) > 1 and self.project.axes:
            # Instances STATIQUES interpolées (une par instance nommée du Designspace, sinon une par master et
            # une à mi-chemin) : OTF, masters compatibles exigés (sinon le message dit pourquoi).
            menu.addSeparator()
            sub = menu.addMenu("Instance statique interpolée (.otf)")
            for label, location in self.instance_locations():
                sub.addAction(label).triggered.connect(
                    lambda _c=False, n=label, loc=location: self.export_dialog("otf", instance=(n, loc)))
        self._popup(menu, anchor if anchor is not None else self.export_button)

    def instance_locations(self) -> list[tuple[str, dict]]:
        p = self.project
        if p.instances:
            return [(i.styleName or i.name or "Instance", dict(i.location)) for i in p.instances]
        from .axes import design_value
        default = p.default_location()
        out = [(m.name, {a.name: m.location.get(a.name, default[a.name]) for a in p.axes}) for m in p.masters]
        axis = p.axes[0]
        middle = (axis.minimum + axis.maximum) / 2
        out.append((f"Mi-chemin ({axis.name} {middle:g})", dict(default, **{axis.name: design_value(axis, middle)})))
        return out

    def _apply_features_if_open(self) -> None:
        if self.pages.currentWidget() is self.features_page:
            self.features_page.apply()

    # -- glyphes --

    def create_from_field(self) -> None:
        text = self.new_field.text().strip()
        if not text:
            return
        code = None
        if text.upper().startswith("U+"):
            try:
                code = int(text[2:], 16)
            except ValueError:
                self.status("Code Unicode invalide.")
                return
        elif len(text) == 1:
            code = ord(text)
        name = glyph_info.name_for_unicode(code) if code is not None else text
        try:
            self.project.add_glyph(name, [code] if code is not None else None)
        except ProjectError as exc:
            self.status(str(exc))
            return
        self.new_field.clear()
        self.grid.refresh()
        self.grid.select({name}, name)
        self.grid.ensure_visible(name)
        self.status(f"Glyphe « {name} » créé.")

    def create_missing_code(self, code: int) -> None:
        names = self.project.add_glyphs_for_unicodes([code])
        if names:
            self.grid.refresh()
            self.show_glyph(names[0])

    def create_missing(self, charset: str) -> None:
        names = self.project.add_glyphs_for_unicodes(glyph_info.CHARSETS[charset])
        self.grid.refresh()
        self.status(f"{len(names)} glyphe(s) créé(s) ({charset}).")

    def duplicate_selected(self) -> None:
        for name in self.grid.selected_names():
            self.project.duplicate_glyph(name)
        self.grid.refresh()

    def delete_selected(self) -> None:
        names = self.grid.selected_names()
        if not names:
            return
        if not confirm(self, "Supprimer des glyphes", f"Supprimer {len(names)} glyphe(s) de tous les masters ?",
                       "Supprimer"):
            return
        try:
            self.project.delete_glyphs(names)
        except ProjectError as exc:
            self.status(str(exc))
        self.grid.refresh()

    def build_accented(self, codes) -> None:
        built, messages = components.build_accented(self.project, codes)
        self.grid.refresh()
        self.status(f"{len(built)} accentué(s) construit(s)." + (f" {messages[0]}" if messages else ""))

    def add_component_from_grid(self) -> None:
        names = [n for n in self.grid.selected_names() if n != self.current_name]
        if not names or self.canvas.glyph is None:
            self.status("Choisissez d'abord le glyphe de base dans la grille (clic), puis revenez à l'éditeur.")
            return
        try:
            self.canvas.edit("Composant", lambda g: components.add_component(self.canvas.font, g, names[0]))
        except (ValueError, components.CycleError) as exc:
            self.status(str(exc))

    # -- secours --

    def _restart_autosave(self) -> None:
        seconds = int(self.settings.get("typo_autosave_seconds", 60))
        if seconds > 0:
            self._autosave_timer.start(seconds * 1000)
        else:
            self._autosave_timer.stop()

    def _autosave_tick(self) -> None:
        """Travail non enregistré copié en fond (instantané de quelques ms ici, écriture dans un fil)."""
        p = self.project
        if p.is_dirty() and p.revision != self._autosaved_revision:
            self._autosaved_revision = p.revision
            self.autosaver.write(p)

    def _discard_autosave(self, *keys_of) -> None:
        for project in keys_of or (self.project,):
            self.autosaver.discard(project)

    # -- fichiers --

    def confirm_leave(self) -> bool:
        """Projet modifié : enregistrer, ou fermer sans enregistrer (deux questions), sinon annulé."""
        if not self.project.is_dirty():
            return True
        if confirm(self, "Projet modifié", "Enregistrer les modifications du projet typographique ?", "Enregistrer"):
            return self.save()
        return confirm(self, "Projet modifié", "Fermer sans enregistrer (les modifications seront perdues) ?",
                       "Fermer sans enregistrer")

    def request_close(self) -> None:
        if self.confirm_leave():
            self.autosaver.wait(5)
            self._discard_autosave()                          # enregistré, ou fermé sans enregistrer : voulu
            self.closeRequested.emit()

    def new_project(self) -> None:
        if self.confirm_leave():
            self.set_project(self._new_project())

    def open_path(self, path) -> bool:
        from .importer import open_any
        try:
            project = open_any(path)
        except ProjectError as exc:
            self.status(str(exc))
            return False
        rescue = self.autosaver.find(project.path, project.source)
        if rescue is not None:
            if confirm(self, "Version de secours", f"Une version de secours plus récente de « {Path(path).name} » "
                       "existe (travail non enregistré lors d'une fermeture inattendue). La récupérer ?",
                       "Récupérer"):
                try:
                    project = self.autosaver.restore(rescue)
                except ProjectError as exc:
                    self.status(f"Secours illisible : {exc}")
            else:
                self.autosaver.discard(folder=rescue)
        self.set_project(project)
        self.status(f"{Path(path).name} ouvert." + (" Police IMPORTÉE : « Enregistrer » demande où écrire la "
                                                     "source (le fichier d'origine n'est jamais réécrit)."
                                                     if project.source and project.path is None else ""))
        return True

    def open_dialog(self) -> None:
        if not self.confirm_leave():
            return
        path, _f = QFileDialog.getOpenFileName(self, "Ouvrir une source ou une police", "",
                                               "Sources et polices (*.designspace *.ufoz *.ttf *.otf *.woff *.woff2 "
                                               "fontinfo.plist metainfo.plist)")
        if path:
            p = Path(path)
            if p.name in ("fontinfo.plist", "metainfo.plist"):          # un .ufo est un dossier
                p = p.parent
            self.open_path(p)

    def save(self) -> bool:
        if self.project.path is None:
            return self.save_as_dialog()
        try:
            self.project.save()
        except ProjectError as exc:
            self.status(str(exc))
            return False
        self.autosaver.wait(5)
        self._discard_autosave()
        self.status(f"Enregistré : {self.project.path}")
        self._sync_title()
        return True

    def save_as_dialog(self) -> bool:
        suggested = f"{self.project.family_name.replace(' ', '')}" + (".designspace" if len(self.project.masters) > 1
                                                                       else ".ufo")
        path, _f = QFileDialog.getSaveFileName(self, "Enregistrer la source", suggested,
                                               "Designspace (*.designspace);;UFO (*.ufo)")
        if not path:
            return False
        from .autosave import project_key
        old_key = project_key(self.project)
        try:
            self.project.save(path)
        except ProjectError as exc:
            self.status(str(exc))
            return False
        self.autosaver.wait(5)
        self.autosaver.discard(folder=self.autosaver.directory / old_key)
        self._discard_autosave()
        self.status(f"Enregistré : {path}")
        self._sync_title()
        return True

    def export_dialog(self, fmt: str, instance: tuple | None = None) -> None:
        base = fmt.replace("-hinted", "")
        ext = ".woff2" if base.endswith("woff2") else ".ttf" if base.endswith("ttf") else f".{base}"
        style = (instance[0] if instance else self.project.masters[self.canvas.master].name).replace(" ", "")
        suffix = "-VF" if fmt.startswith("variable") else f"-{style}"
        name = f"{self.project.family_name.replace(' ', '')}{suffix}{ext}"
        path, _f = QFileDialog.getSaveFileName(self, "Exporter la police", name, f"Police (*{ext})")
        if path:
            self.export_to(path, fmt, instance, background=True)

    def export_to(self, path, fmt: str, instance: tuple | None = None, background: bool = False):
        """Compile et écrit la police. `background` : instantané du projet ici (quelques ms), compilation dans un
        fil (~2 s pour 1000 glyphes) : l'interface reste fluide ; le résultat arrive dans la barre d'état.
        Renvoie True / False (synchrone) ou le fil lancé."""
        kwargs = {"master": self.canvas.master, "instance": instance[1] if instance else None,
                  "instance_name": instance[0] if instance else "Instance"}
        if not background:
            try:
                notes = export(self.project, path, fmt, **kwargs)
            except CompileError as exc:
                self.status(str(exc))
                return False
            self._exported(path, notes, None)
            return True
        import threading
        from .autosave import project_from_snapshot, snapshot
        snap = snapshot(self.project)
        relay = self._export_relay = _ExportRelay()
        relay.done.connect(lambda notes, error: self._exported(path, notes, error))
        self.status(f"Export de {Path(path).name} en cours…")

        def work():
            try:
                relay.done.emit(export(project_from_snapshot(snap), path, fmt, **kwargs), None)
            except CompileError as exc:
                relay.done.emit(None, str(exc))
            except Exception as exc:                        # noqa: BLE001 - message dans la barre d'état
                relay.done.emit(None, f"{type(exc).__name__} : {exc}")
        thread = threading.Thread(target=work, name="fm_font export", daemon=True)
        thread.start()
        return thread

    def _exported(self, path, notes, error) -> None:
        if error is not None:
            self.status(error)
            return
        warnings = [n for n in notes if n.level != "suggestion"]
        self.status(f"Exporté : {path}" + (f" ({len(warnings)} avertissement(s), voir Diagnostic)" if warnings else ""))

    # -- fenêtre --

    def apply_settings(self, settings: dict) -> None:
        self.settings.update({k: v for k, v in settings.items() if k.startswith("typo_")})
        self.canvas.apply_settings(self.settings)
        self.grid.colors = self.settings
        self.grid.set_cell_size(int(self.settings["typo_cell_size"]))
        self.preview.settings = self.settings
        self.preview.update()
        if "typo_autosave_seconds" in settings:
            self._restart_autosave()

    side_left = 0

    def _side_geometry(self, host):
        """Zone du panneau : toute celle des colonnes, ou à droite de la colonne cliquée (`side_left`, simple clic)."""
        rect = host.rect()
        return rect.adjusted(min(self.side_left, max(0, rect.width() - 200)), 0, 0, 0)

    def set_side_left(self, left: int) -> None:
        """Ouvert à côté des colonnes à partir de `left` (0 : plein, les colonnes sont recouvertes)."""
        self.side_left = max(0, int(left))
        if self.parentWidget() is not None:
            self.setGeometry(self._side_geometry(self.parentWidget()))

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(self._side_geometry(obj))
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.pages.currentWidget() is not self.canvas:
            return                                      # Echap ne fait jamais sortir du module (2026-11-05)
        super().keyPressEvent(event)

    def shutdown(self) -> None:
        self._autosave_timer.stop()
        self.cache.detach()
        self.preview.detach()
        if self._on_change in self.project.listeners:
            self.project.listeners.remove(self._on_change)


__all__ = ["FontPane", "HOOKS", "QPointF"]
