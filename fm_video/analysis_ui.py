"""Vue « Analyse colorimétrique » du moodboard (maquette « Analyse — Image 4207 », demande de l'utilisateur,
2026-10-31) : barre du haut (retour au moodboard, image, onglets Analyse / Matching / LUT, aide, export), viewer
(pipette, région, image entière, rendu original / palette seule, fond), palette + nuances + couverture, « Localiser
sur l'image » (2e version de la maquette : couleurs choisies isolées sur l'image), inspecteur (couleur sélectionnée,
répartition tonale, luminance Y, scopes, réglages de la palette), barre d'état.

Moteur (fil de fond, une demande remplace la précédente) : `analysis.py` ; widgets peints : `analysis_widgets.py` ;
habillage réglable : `analysis_look.py` ; palette et barre d'isolement : `analysis_palette.py` ; image recomposée :
`analysis_isolate.py`. Rien n'est recalculé pour un changement d'affichage (ordre, sélection, canaux, échelle log, type
de scope, fond, isolement) : seul le widget concerné est repeint, l'image isolée est recomposée au plus une fois par
passage de la boucle d'événements. États de la vue (outil, fond, scope, canaux, log, ordre, isolement) :
`settingsChanged` -> `VideoPane._analysis_setting` (écriture différée)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QGridLayout, QHBoxLayout, QScrollArea,
                               QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget, QAbstractSpinBox)

from fm_video.analysis import SUBS, _Signals, _Task, oklch
from fm_video.analysis_isolate import Isolation
from fm_video.analysis_look import ANALYSIS_LOOK_DEFAULTS, LOOK, PREFIX, analysis_look
from fm_video import analysis_palette as ap
from fm_video import analysis_widgets as aw

ORDERS = (("L", "Clarté"), ("cov", "Couverture"), ("h", "Teinte"), ("C", "Chroma"))
SCOPES = (("hist", "Histogramme"), ("wave", "Waveform"), ("vec", "Vectorscope"))
HINTS = {"P": "Pipette : clic sur l’image", "R": "Région : glisser sur l’image",
         "I": "Image entière : analyse de tout le cadre"}
FOOTER = "Pixels du proxy affiché · hypothèse sRGB SDR · distances OKLab"
STATES = ("order", "viewer_bg", "scope", "log", "channels", "tool",
          "pick_mode", "rest", "rest_light", "rest_sat", "rest_color")
# Demande de l'utilisateur : chaque ouverture repart avec « Localiser sur l'image » coupé et le rendu « Original » ;
# ces deux états ne sont donc PAS enregistrés (une valeur enregistrée rétablissait « Palette seule »).
SESSION = {"iso": False, "render": "orig"}
ISO_STATES = ("iso", "pick_mode", "rest", "rest_light", "rest_sat", "rest_color", "render")


def _entry(i, rgb, weight):
    L, C, h = oklch(rgb)
    return dict(i=i, rgb=tuple(int(v) for v in rgb), weight=weight, hex=QColor(*rgb).name(), L=L, C=C, h=h)


def sort_colors(colors, order):
    key = {"cov": lambda c: -c["weight"], "C": lambda c: -c["C"], "h": lambda c: c["h"]}.get(order, lambda c: c["L"])
    return sorted(colors, key=key)


class _Page(QWidget):
    """Fond de la page (la couleur de la maquette), sans feuille de style (rien ne cascade sur les enfants)."""

    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), QColor(self.owner.look["bg_color"]))


class ColorAnalysis(_Page):
    back = Signal()
    settingsChanged = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent, self)
        self.look = LOOK
        self.settings = {}
        self.revision = 0
        self.cancel = threading.Event()
        self.latest = {}
        self.colors = []                       # palette triée (dicts : i, rgb, weight, hex, L, C, h, subs)
        self.selected = None                   # indice de la couleur choisie (ou None : pipette sans carte)
        self.sub = None                        # nuance choisie de cette couleur (None : la couleur entière)
        self.picks = set()                     # nuances choisies (j * SUBS + k), isolées sur l'image
        self.sample = None                     # couleur de la pipette (carte des pixels pas encore prête)
        self.isolation = None                  # `Isolation` de la dernière analyse
        self.state = {**{k: ANALYSIS_LOOK_DEFAULTS[PREFIX + k] for k in STATES}, **SESSION}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = _Signals(self)
        self.signals.ready.connect(self._ready)
        self.signals.failed.connect(self._failed)
        self.debounce = QTimer(self, singleShot=True, interval=100)
        self.debounce.timeout.connect(self._start)
        self.render_timer = QTimer(self, singleShot=True, interval=0)     # une recomposition par passage
        self.render_timer.timeout.connect(self._render)
        self._hint_timer = QTimer(self, singleShot=True, interval=1600)
        self._hint_timer.timeout.connect(self._update_footer)
        self.matching = None                   # onglet Matching / LUT (créé au 1er clic)
        self.tab = "A"
        from fm_video.help_ui import HelpController, annotate
        ancestor = self.parentWidget()
        self.help = None
        while ancestor is not None and self.help is None:
            self.help = getattr(ancestor, '_color_help', None)
            ancestor = ancestor.parentWidget()
        if self.help is None:
            self.help = HelpController(self)
        self._build()
        for widget, key in ((self.count, 'palette'), (self.black, 'palette'), (self.white, 'palette'),
                            (self.order, 'palette'), (self.palette, 'palette'), (self.image, 'region'),
                            (self.hist, 'histogram'), (self.chips, 'histogram'), (self.gauge, 'histogram'),
                            (self.wave, 'scopes'), (self.vec, 'scopes'), (self.scope_tabs, 'scopes'),
                            (self.tabs, 'matching'), (self.export, 'palette')):
            annotate(widget, key)
        self.setToolTip('Maintenir Ctrl + Shift sur un outil pour son aide détaillée ; F1 pour l’explication complète.')

    # -- construction --

    def _build(self):
        lk = self.look
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # Barre du haut : retour + titre | onglets (centrés) | aide + export.
        self.header = aw.Bar(self, lk)
        grid = QGridLayout(self.header)
        grid.setContentsMargins(16, 8, 16, 8)
        grid.setHorizontalSpacing(20)
        left = QHBoxLayout()
        left.setSpacing(10)
        self.back_button = aw.Button(self.header, lk, "Moodboard", "back")
        self.back_button.clicked.connect(self.back)
        self.title = aw.TitleBlock(self.header, lk)
        left.addWidget(self.back_button)
        left.addWidget(self.title, 1)
        grid.addLayout(left, 0, 0)
        self.tabs = aw.Segmented(self.header, lk, (("A", "Analyse"), ("M", "Matching / LUT")), "A")
        self.tabs.picked.connect(self._tab)
        grid.addWidget(self.tabs, 0, 1, Qt.AlignCenter)
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        self.help_button = aw.Button(self.header, lk, icon_name="help", kind="icon")
        self.help_button.setToolTip("Aide et glossaire")
        self.help_button.clicked.connect(lambda: self.help.open_glossary('matching' if self.tab == "M" else None))
        self.export = aw.Button(self.header, lk, "Exporter la palette", "download", kind="primary")
        self.export.clicked.connect(lambda: self.matching.export_lut() if self.tab == "M" else self.export_palette())
        right.addWidget(self.help_button)
        right.addWidget(self.export)
        grid.addLayout(right, 0, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        root.addWidget(self.header)
        # Corps : analyse (viewer + palette | inspecteur) ou matching.
        self.body = QStackedWidget(self)
        root.addWidget(self.body, 1)
        analysis = QWidget(self.body)
        row = QHBoxLayout(analysis)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        main = QVBoxLayout()
        main.setSpacing(0)
        self.image = aw.Viewer(analysis, lk)
        self.image.picked.connect(self._picked)
        self.image.regionChanged.connect(self._region)
        self.image.toolbar.toolPicked.connect(self._tool)
        self.image.toolbar.bgPicked.connect(self._viewer_bg)
        self.image.toolbar.renderPicked.connect(lambda v: self._set_state("render", v))
        main.addWidget(self.image, 1)
        self.palette_section = aw.Section(analysis, lk, bg="panel_color", top=True, bottom=False)
        pal = QVBoxLayout(self.palette_section)
        pal.setContentsMargins(20, 16, 20, 20)
        pal.setSpacing(10)
        head = QHBoxLayout()
        self.palette_title = aw.Title(self.palette_section, lk, "Palette")
        self.iso_toggle = ap.PillToggle(self.palette_section, lk, "Localiser sur l'image", "eye")
        self.iso_toggle.toggled.connect(lambda on: self._set_state("iso", on))
        head.addWidget(self.palette_title, 1)
        head.addWidget(self.iso_toggle)
        pal.addLayout(head)
        self.iso_bar = ap.IsoBar(self.palette_section, lk)
        self.iso_bar.pickModeChanged.connect(lambda v: self._set_state("pick_mode", v))
        self.iso_bar.restChanged.connect(lambda v: self._set_state("rest", v))
        self.iso_bar.lightChanged.connect(lambda v: self._set_state("rest_light", v))
        self.iso_bar.satChanged.connect(lambda v: self._set_state("rest_sat", v))
        self.iso_bar.colorPicked.connect(lambda v: self._set_state("rest_color", v))
        self.palette = ap.PaletteStrip(self.palette_section, lk)
        self.palette.tilePicked.connect(self._select)
        self.palette.subPicked.connect(self._select_sub)
        self.palette.copied.connect(self._copy)
        self.coverage_caption = aw.Caption(self.palette_section, lk, "Part de l'image couverte par chaque couleur "
                                           "(pixel assigné à la couleur la plus proche en OKLab) · barres à l'échelle "
                                           "de la plus grande")
        for w in (self.iso_bar, self.palette, self.coverage_caption):
            pal.addWidget(w)
        main.addWidget(self.palette_section)
        row.addLayout(main, 1)
        row.addWidget(self._build_inspector(analysis))
        self.body.addWidget(analysis)
        self.footer = aw.Bar(self, lk, footer=True)
        root.addWidget(self.footer)
        self._apply_look()

    def _section(self, parent, title, caption="", spacing=12, bottom=True):
        section = aw.Section(parent, self.look, bottom=bottom)
        lay = QVBoxLayout(section)
        pad = self.look["section_padding"]
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(spacing)
        section.title_widget = aw.Title(section, self.look, title, caption)
        lay.addWidget(section.title_widget)
        self._sections.append(section)
        return section, lay

    def _build_inspector(self, parent):
        lk = self.look
        self._sections = []
        self.inspector = QScrollArea(parent)
        self.inspector.setWidgetResizable(True)
        self.inspector.setFrameShape(QScrollArea.NoFrame)
        self.inspector.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = aw.Section(None, lk, bg="panel_color", bottom=False)
        self.inspector_content = content
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.selection = aw.SelectedColor(content, lk)
        self.selection.copyRequested.connect(lambda: self.selection.data and self._copy(self.selection.data["hex"].upper()))
        col.addWidget(self.selection)
        section, lay = self._section(content, "Répartition tonale")
        self.tones = aw.ToneView(section, lk)
        lay.addWidget(self.tones)
        col.addWidget(section)
        section, lay = self._section(content, "Luminance Y", "linéaire · Rec.709")
        self.gauge = aw.LumaGauge(section, lk)
        lay.addWidget(self.gauge)
        col.addWidget(section)
        section, lay = self._section(content, "Scopes", spacing=10)
        self.scope_tabs = aw.Segmented(section, lk, SCOPES, self.state["scope"], style="scopes")
        self.scope_tabs.picked.connect(self._scope)
        lay.addWidget(self.scope_tabs)
        self.hist = aw.HistView(section, lk)
        self.chips = aw.Chips(section, lk)
        self.chips.toggled.connect(lambda v: self._set_state("channels", v))
        self.chips.logToggled.connect(lambda v: self._set_state("log", v))
        self.wave = aw.WaveView(section, lk)
        self.wave_caption = aw.Caption(section, lk, "Luma par colonne · densité log")
        self.vec = aw.VecView(section, lk)
        self.vec_caption = aw.Caption(section, lk, "")
        for w in (self.hist, self.chips, self.wave, self.wave_caption, self.vec, self.vec_caption):
            lay.addWidget(w)
        col.addWidget(section)
        section, lay = self._section(content, "Réglages de la palette", bottom=False)
        fields = QGridLayout()
        fields.setHorizontalSpacing(10)
        fields.setVerticalSpacing(4)
        self.count = QSpinBox(section)
        self.count.setRange(2, 32)
        self.count.setValue(16)
        self.count.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.count.valueChanged.connect(self._submit)
        self.order = aw.Combo(section, lk)
        for oid, label in ORDERS:
            self.order.addItem(label, oid)
        self.order.currentIndexChanged.connect(lambda _i: self._set_state("order", self.order.currentData()))
        self._field_labels = [aw.Caption(section, lk, "Couleurs"), aw.Caption(section, lk, "Ordre")]
        fields.addWidget(self._field_labels[0], 0, 0)
        fields.addWidget(self._field_labels[1], 0, 1)
        fields.addWidget(self.count, 1, 0)
        fields.addWidget(self.order, 1, 1)
        for field in (self.count, self.order):
            field.setMinimumWidth(40)
            field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        lay.addLayout(fields)
        self.black = aw.CheckRow(section, lk, "Exclure les noirs", "≤ 8")
        self.white = aw.CheckRow(section, lk, "Exclure les blancs", "≥ 247")
        for control in (self.black, self.white):
            control.toggled.connect(self._submit)
            lay.addWidget(control)
        lay.addStretch(1)
        col.addWidget(section, 1)
        self.inspector.setWidget(content)
        return self.inspector

    # -- habillage / réglages --

    def _apply_look(self):
        lk = self.look
        for w in self.findChildren(aw._Painted):
            w.set_look(lk)
        sheet = aw.field_stylesheet(lk)
        self.order.set_look(lk)
        for field in (self.count, self.order):
            if field is self.count:
                field.setStyleSheet(sheet)
            field.setFont(aw.font(lk, lk["font_size"], mono=field is self.count))
        self.inspector.setFixedWidth(lk["inspector_width"])
        self.inspector.setStyleSheet(aw.inspector_stylesheet(lk))
        if self.matching is not None:
            self.matching.set_look(lk)
        self.vec_caption.set_text(f"Cb/Cr Rec.709 · zoom ×{aw.fr(lk['vec_zoom'], 1)} · ligne : teintes chair")
        self._show_state()
        self.update()

    def apply_settings(self, settings):
        self.settings = dict(settings)
        self.help.settings = self.settings
        look = analysis_look(settings)
        if look["key"] != self.look["key"]:
            old_zoom = self.look["vec_zoom"]
            self.look = look
            self._apply_look()
            if look["vec_zoom"] != old_zoom:
                self._submit()
        for key in STATES:
            self.state[key] = settings.get(PREFIX + key, self.state[key])
        for control, key, default in ((self.count, 'video_analysis_colors', 16),
                                      (self.black, 'video_analysis_exclude_black', False),
                                      (self.white, 'video_analysis_exclude_white', False)):
            control.blockSignals(True)
            if isinstance(control, QSpinBox):
                control.setValue(int(settings.get(key, default)))
            else:
                control.setChecked(bool(settings.get(key, default)))
            control.blockSignals(False)
        if self.matching is not None:
            self.matching.apply_settings(settings)
        self._show_state()
        self._resort()

    def _show_state(self):
        """Recale les contrôles sur `self.state` (sans rien recalculer)."""
        s = self.state
        self.image.set_tool(s["tool"])
        self.image.toolbar.set_state(s["tool"], int(s["viewer_bg"]), s["render"])
        self.image.set_bg(QColor(self.look[f"viewer_bg_{int(s['viewer_bg']) % 3 + 1}"]))
        if self.matching is not None:
            self.matching.sync_bg()
        self.scope_tabs.set_current(s["scope"])
        self.chips.set_state(s["channels"], bool(s["log"]))
        self.hist.set_data(self.latest.get("hist"), bool(s["log"]), s["channels"])
        for widgets, scope in (((self.hist, self.chips), "hist"), ((self.wave, self.wave_caption), "wave"),
                               ((self.vec, self.vec_caption), "vec")):
            for w in widgets:
                w.setVisible(s["scope"] == scope)
        index = self.order.findData(s["order"])
        if index >= 0 and index != self.order.currentIndex():
            self.order.blockSignals(True)
            self.order.setCurrentIndex(index)
            self.order.blockSignals(False)
        self._show_iso()
        self._update_footer()

    def _show_iso(self):
        """Contrôles de l'isolement recalés sur l'état ; l'image est recomposée au prochain passage."""
        s = self.state
        self.iso_toggle.set_on(bool(s["iso"]))
        data = self._selection_data()
        self.iso_bar.set_state(s["pick_mode"], s["rest"], int(s["rest_light"]), int(s["rest_sat"]),
                               s["rest_color"], data["hex"] if data else "#000000", bool(s["iso"]))
        self.palette.set_data(self.colors, self.selected, self.picks, not (s["iso"] and s["pick_mode"] == "flat"))
        self.render_timer.start()

    def _set_state(self, key, value):
        if self.state.get(key) == value:
            return
        self.state[key] = value
        if key not in SESSION:
            self.settingsChanged.emit(PREFIX + key, value)
        if key == "order":
            self._resort()
        elif key in ISO_STATES:
            if key == "pick_mode" and value == "flat":
                self.sub = None                                  # aplat : la couleur entière
                self._show_selection()
            self._show_iso()
            if key == "render":
                self.image.toolbar.set_state(self.state["tool"], int(self.state["viewer_bg"]), value)
        else:
            self._show_state()

    def _tool(self, tool):
        self._set_state("tool", tool)
        if tool == "I":
            self.image.clear_region()

    def _viewer_bg(self, index):
        self._set_state("viewer_bg", index)

    def _scope(self, scope):
        self._set_state("scope", scope)

    def _tab(self, tab):
        self.tab = tab
        self.tabs.set_current(tab)
        if tab == "M":
            self._open_matching()
            self.body.setCurrentWidget(self.matching)
            self.export.set_text("Exporter la LUT")
            self.export.set_active(self.matching.has_match())
            self.help_button.setToolTip("Aide matching / LUT")
        else:
            self.body.setCurrentWidget(self.body.widget(0))
            self.export.set_text("Exporter la palette")
            self.export.set_active(True)
            self.help_button.setToolTip("Aide et glossaire")
        self._update_footer()

    # -- image, analyse --

    def show_image(self, image, title):
        image = image.copy()
        self.image.set_image(image)
        self.title.set_texts(title, f"Proxy {image.width()} × {image.height()} · sRGB SDR")
        self.latest = {}
        self.colors = []
        self.selected = self.sample = self.sub = self.isolation = None
        self.picks = set()
        self.state.update(SESSION)
        self.image.toolbar.set_state(self.state["tool"], int(self.state["viewer_bg"]), "orig")
        self.palette.set_data([], None, set(), True)
        self.selection.set_data(None)
        self.tones.set_tones([])
        self.gauge.set_stats(None)
        self.hist.set_data(None, bool(self.state["log"]), self.state["channels"])
        self.wave.set_data(None)
        self.vec.set_data(None)
        if self.matching is not None:
            self.matching.set_source(image, title)
        self._update_footer()
        self._submit()

    def _submit(self, *_):
        if self.image.image.isNull():
            return
        self.cancel.set()
        self.revision += 1
        self.pool.clear()
        self.debounce.start()

    def _start(self):
        self.cancel = threading.Event()
        options = dict(region=self.image.region, exclude_black=self.black.isChecked(),
                       exclude_white=self.white.isChecked(), scopes=True, vec_zoom=self.look["vec_zoom"])
        self.pool.start(_Task(self.image.image, self.count.value(), self.revision, self.signals, options, self.cancel))
        for key, value in (('video_analysis_colors', self.count.value()),
                           ('video_analysis_exclude_black', self.black.isChecked()),
                           ('video_analysis_exclude_white', self.white.isChecked())):
            self.settingsChanged.emit(key, value)

    def stop(self):
        self.help.dismiss()
        if self.matching is not None:
            self.matching.stop()
        self.cancel.set()
        self.debounce.stop()
        self.revision += 1
        self.pool.clear()

    def _failed(self, revision, message):
        if revision == self.revision:
            self._flash(f"Analyse impossible : {message}")

    def _ready(self, revision, result):
        if revision != self.revision:
            return
        self.latest = result
        result["region"] = self.image.region                    # région de cette analyse (titre de la palette)
        subs = result.get('subs') or [[] for _ in result.get('colors', [])]
        entries = [dict(_entry(i, rgb, w), subs=[dict(_entry(-1, srgb, sw), digits=2) for srgb, sw in shades])
                   for i, ((rgb, w), shades) in enumerate(zip(result.get('colors', []), subs))]
        if self.selected is not None and self.selected >= len(entries):
            self.selected = None
        if self.selected is None and self.sample is None and entries:
            self.selected = max(entries, key=lambda c: c["weight"])["i"]
        self._entries = entries
        iso = result.get('iso')
        self.isolation = Isolation(iso['rgba'], iso['labels'], [c["rgb"] for c in entries]) if iso else None
        self.sub = None
        self.picks = self._group(self.selected) if self.selected is not None else set()
        self.image.set_marker(None)
        by_l = sorted(entries, key=lambda c: c["L"])
        if len(by_l) >= 5:                                       # pictogramme « Palette seule » : 4 couleurs
            by_l = [by_l[round(1 + k * (len(by_l) - 2) / 3)] for k in range(4)]
        self.image.toolbar.set_strip([c["hex"] for c in by_l[:4]])
        self._resort()
        self.tones.set_tones(result.get('tones'))
        self.gauge.set_stats(result.get('luminance'))
        self.hist.set_data(result.get('hist'), bool(self.state["log"]), self.state["channels"])
        scopes = result.get('scopes')
        why = "Région partiellement transparente : scope indisponible" if result.get('samples') else "Aucun pixel"
        self.wave.set_data(scopes["wave_alpha"] if scopes else None, "" if scopes else why)
        self.vec.set_data(scopes["vec"] if scopes else None, "" if scopes else why)

    def _resort(self):
        entries = getattr(self, "_entries", [])
        self.colors = sort_colors(entries, self.state["order"])
        # La palette ne décrit que la région quand il y en a une : le titre le dit (l'utilisateur ne retrouvait pas
        # les tons du reste de l'image).
        region = self.latest.get("region")
        where = f" · région {region.width()} × {region.height()} px" if region is not None else ""
        self.palette_title.set_text(f"Palette · {len(self.colors)} couleurs{where}")
        self._show_selection()

    # -- sélection : couleurs, nuances, pipette (maquette : Ctrl + clic ajoute / retire) --

    def _color(self, index):
        return next((c for c in getattr(self, "_entries", ()) if c["i"] == index), None)

    def _group(self, index):
        color = self._color(index)
        return {index * SUBS + k for k in range(len(color["subs"]) if color else 0)}

    def _selection_data(self):
        if self.selected is None:
            return self.sample
        color = self._color(self.selected)
        if color is not None and self.sub is not None and self.sub < len(color["subs"]):
            return color["subs"][self.sub]
        return color

    def _show_selection(self):
        self.selection.set_data(self._selection_data())
        self._show_iso()

    def _select(self, index, ctrl=False):
        group = self._group(index)
        if ctrl:
            rest = self.picks - group
            self.picks = rest if group <= self.picks else rest | group
        else:
            self.picks = group
        self.selected, self.sub, self.sample = index, None, None
        self.image.set_marker(None)
        self._show_selection()

    def _select_sub(self, index, k, ctrl=False):
        v = index * SUBS + k
        if ctrl:
            self.picks = self.picks ^ {v}
            self.sub = k
        elif self.sub == k and self.picks == {v}:              # 2e clic : retour à la couleur entière
            self.picks, self.sub = self._group(index), None
        else:
            self.picks, self.sub = {v}, k
        self.selected, self.sample = index, None
        self._show_selection()

    def _picked(self, x, y, ctrl=False):
        """Pipette : couleur et nuance du pixel (aplat : la couleur entière) ; sans carte, la couleur brute."""
        if self.isolation is None:
            self._sampled(self.image.image.pixelColor(x, y))
            return
        v = self.isolation.label_at((x + .5) / self.image.image.width(), (y + .5) / self.image.image.height())
        j = v // SUBS
        flat = self.state["iso"] and self.state["pick_mode"] == "flat"
        add = self._group(j) if flat else {v}
        if ctrl:
            self.picks = self.picks - add if add <= self.picks else self.picks | add
        else:
            self.picks = add
        self.selected, self.sub, self.sample = j, None if flat else v % SUBS, None
        self.image.set_marker((x, y))
        self._show_selection()

    def _sampled(self, color):
        rgb = (color.red(), color.green(), color.blue())
        self.sample = dict(_entry(-1, rgb, None), weight=None)
        self.selected = self.sub = None
        self.picks = set()
        self._show_selection()

    def _render(self):
        """Image montrée : isolée (couleurs choisies), palette seule ou originale ; étiquette de la sélection."""
        s, iso = self.state, self.isolation
        if iso is None:
            self.image.set_display(None)
            self.image.set_tag(None)
            return
        if not s["iso"]:
            self.image.set_display(iso.plain(s["render"] == "pal"))
            self.image.set_tag(None)
            return
        self.image.set_display(iso.render(self.picks, s["pick_mode"] == "flat", s["rest"] == "uni",
                                          int(s["rest_light"]), int(s["rest_sat"]), s["rest_color"],
                                          s["render"] == "pal"))
        data = self._selection_data()
        if data is None:
            self.image.set_tag(None)
            return
        weights = {c["i"] * SUBS + k: sub["weight"] for c in self.colors for k, sub in enumerate(c["subs"])}
        total = sum(weights.get(v, 0.0) for v in self.picks) * 100
        single = len(self.picks) == 1 or (self.selected is not None and self.picks == self._group(self.selected))
        self.image.set_tag((data["hex"], data["hex"].upper() if single else f"{len(self.picks)} sélections",
                            f"{aw.fr(total, 2 if total < 1 else 1)} % de l'image"))

    def _region(self, region):
        self._update_footer()
        self._submit()

    # -- barre d'état, presse-papiers --

    def _update_footer(self):
        left = FOOTER
        region = self.image.region
        if self.tab == "M" and self.matching is not None:
            self.footer.set_texts(left, self.matching.footer_text())
            return
        if region is not None:
            left += f" · région {region.width()} × {region.height()} px"
        self.footer.set_texts(left, HINTS.get(self.state["tool"], ""))

    def _flash(self, text):
        self.footer.set_texts(self.footer.left, text)
        self._hint_timer.start()

    def _copy(self, hex_text):
        QApplication.clipboard().setText(hex_text)
        self._flash(f"Copié : {hex_text}")

    # -- export, matching --

    def export_palette(self):
        if not self.colors:
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'Exporter la palette', 'palette.json',
                                                 'JSON (*.json);;CSS (*.css);;PNG (*.png)')
        if not filename:
            return
        import json
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        path = Path(filename)
        colors = [dict(hex=c["hex"], rgb=list(c["rgb"]), weight=c["weight"], oklch=[c["L"], c["C"], c["h"]])
                  for c in self.colors]
        try:
            if path.suffix.lower() == '.png':
                image = QImage(len(colors) * 80, 80, QImage.Format_RGB888)
                painter = QPainter(image)
                for i, item in enumerate(colors):
                    painter.fillRect(i * 80, 0, 80, 80, QColor(item['hex']))
                painter.end()
                if not image.save(str(path), 'PNG'):
                    raise OSError('Impossible de sauvegarder la palette')
            elif path.suffix.lower() == '.css':
                path.write_text(':root {\n' + '\n'.join(f'  --palette-{i + 1}: {item["hex"]};'
                                                        for i, item in enumerate(colors)) + '\n}\n', encoding='utf-8')
            else:
                path.write_text(json.dumps(dict(space='sRGB SDR (hypothèse du proxy affiché)', clustering='OKLab',
                                                colors=colors), indent=2), encoding='utf-8')
        except OSError as exc:
            QMessageBox.warning(self, 'Export de palette', str(exc))

    def _open_matching(self):
        """Onglet Matching / LUT (`matching_view.MatchingView`), créé au 1er clic : rien n'est construit avant."""
        if self.matching is not None:
            return
        from fm_video.matching_view import MatchingView
        self.matching = MatchingView(self.body, self)
        self.matching.settingsChanged.connect(self.settingsChanged.emit)
        self.matching.statusChanged.connect(self._update_footer)
        self.matching.modelChanged.connect(lambda on: self.tab == "M" and self.export.set_active(on))
        self.body.addWidget(self.matching)
        if not self.image.image.isNull():
            self.matching.set_source(self.image.image, self.title.title)
