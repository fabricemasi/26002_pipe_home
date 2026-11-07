"""Onglet « Matching / LUT » de l'analyse colorimétrique (seconde maquette « Matching / LUT — Image 4207 »,
demande de l'utilisateur, 2026-10-31) : paire source -> référence, viewer avec rideau avant / après, état en trois
étapes, méthode + intensité, résolution de la LUT 3D, export LUT / preset, chargement d'un preset.

Moteur inchangé : `matching.py` (ajustement, export .cube) et les tâches de fond `matching_ui._Job` (une à la fois,
une demande remplace la précédente). L'INTENSITÉ ne refait pas l'ajustement : elle réapplique le modèle à l'image
déjà réduite (~quelques ms, en fond) ; la méthode et la référence le refont. Habillage : `analysis_look.py`
(mêmes clés que l'onglet Analyse) ; widgets : `matching_widgets.py`."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from fm_video import analysis_widgets as aw
from fm_video import matching_widgets as mw
from fm_video.matching_ui import _Job, _Signals

METHODS = ("Scènes différentes : statistiques RGB", "Paire source / résultat alignée")
INFOS = ("Scènes différentes : seules les statistiques RGB (moyennes, covariances) sont transférées ; "
         "les cadrages peuvent différer.",
         "La paire exige le même cadrage et des pixels correspondants.")
SIZES = (17, 33, 65, 129)
IMAGES = 'Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)'
METRICS = {'rgb_rmse': 'RMSE RGB (pixels réservés)', 'before_rgb_rmse': 'RMSE RGB avant',
           'out_of_range': 'Hors [0,1] avant limitation', 'before_mean_rgb_distance': 'Écart des moyennes avant',
           'after_mean_rgb_distance': 'Écart des moyennes après'}


def table_size(n: int) -> str:
    """Taille de la table n³ × 3 float32 (format de la maquette : « 1,50 Mio », « 57,6 Kio »)."""
    size = n ** 3 * 12
    value, unit = (size / 1048576, "Mio") if size >= 1048576 else (size / 1024, "Kio")
    return f"{value:.{2 if value < 10 else 1}f} {unit}".replace(".", ",")


class MatchingView(QWidget):
    settingsChanged = Signal(str, object)
    statusChanged = Signal()            # texte de droite de la barre d'état
    modelChanged = Signal(bool)         # un matching est calculé (bouton d'export de la barre du haut)

    def __init__(self, parent, owner):
        super().__init__(parent)
        self.owner = owner              # ColorAnalysis : habillage, aide, réglages, fond du viewer
        self.look = owner.look
        self.source = None              # QImage (proxy du moodboard) ou chemin choisi par « Changer »
        self.source_name = ""
        self.reference = None           # chemin
        self.preset_name = None
        self.cache = {}
        self.model = self.result = None
        self.busy = False
        self.error = ""
        self.view, self.pos = "split", 50.0
        self.revision = 0
        self.cancel = threading.Event()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = _Signals(self)
        self.signals.ready.connect(self._ready)
        self.signals.failed.connect(self._failed)
        self.fit_timer = QTimer(self, singleShot=True, interval=120)
        self.fit_timer.timeout.connect(self._fit)
        self.preview_timer = QTimer(self, singleShot=True, interval=30)
        self.preview_timer.timeout.connect(self._preview)
        self._build()
        self.apply_settings(owner.settings)

    # -- construction --

    def _build(self):
        lk = self.look
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        main = QVBoxLayout()
        main.setSpacing(0)
        pair = aw.Section(self, lk, bg="panel_color")
        lay = QHBoxLayout(pair)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        self.source_card = mw.PairCard(pair, lk, "Source", "Changer")
        self.source_card.action.connect(self._choose_source)
        self.reference_card = mw.PairCard(pair, lk, "Référence", "Retirer")
        self.reference_card.picked.connect(self._choose_reference)
        self.reference_card.dropped.connect(self.set_reference)
        self.reference_card.action.connect(self.clear_reference)
        lay.addWidget(self.source_card, 1)
        lay.addWidget(mw.PairArrow(pair, lk))
        lay.addWidget(self.reference_card, 1)
        main.addWidget(pair)
        self.viewer = mw.MatchViewer(self, lk)
        self.viewer.posChanged.connect(self._drag_pos)
        self.viewer.toolbar.picked.connect(self._pick_view)
        main.addWidget(self.viewer, 1)
        row.addLayout(main, 1)
        self.inspector = QScrollArea(self)
        self.inspector.setWidgetResizable(True)
        self.inspector.setFrameShape(QScrollArea.NoFrame)
        self.inspector.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = aw.Section(None, lk, bg="panel_color", bottom=False)
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        section, lay = self._section(content, "État", spacing=10)
        self.steps = mw.Steps(section, lk)
        lay.addWidget(self.steps)
        col.addWidget(section)
        section, lay = self._section(content, "Méthode")
        mode = QVBoxLayout()
        mode.setSpacing(4)
        mode.addWidget(aw.Caption(section, lk, "Mode de matching"))
        self.method = aw.Combo(section, lk)
        self.method.addItems(METHODS)
        self.method.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.method.currentIndexChanged.connect(self._method_changed)
        mode.addWidget(self.method)
        lay.addLayout(mode)
        self.info = mw.InfoBox(section, lk, INFOS[1])
        lay.addWidget(self.info)
        line = QHBoxLayout()
        self.intensity_label = _Label(section, lk, "Intensité", "100 %")
        line.addWidget(self.intensity_label)
        intensity = QVBoxLayout()
        intensity.setSpacing(6)
        intensity.addLayout(line)
        self.intensity = mw.Slider(section, lk)
        self.intensity.valueChanged.connect(self._intensity_changed)
        intensity.addWidget(self.intensity)
        lay.addLayout(intensity)
        col.addWidget(section)
        section, lay = self._section(content, "LUT 3D", "Table : " + table_size(33))
        self.lut_section = section
        self.size = aw.Segmented(section, lk, [(str(n), str(n)) for n in SIZES], "33", style="res")
        self.size.picked.connect(self._size_changed)
        lay.addWidget(self.size)
        self.size_caption = aw.Caption(section, lk, "")
        lay.addWidget(self.size_caption)
        col.addWidget(section)
        section, lay = self._section(content, "LUT et presets", spacing=8)
        lay.addSpacing(4)                                       # maquette : titre + 4 px
        self.export = aw.Button(section, lk, "Exporter LUT / preset…", "download", kind="primary", height_key=38,
                                wide=True)
        self.export.clicked.connect(self.export_lut)
        self.restore = aw.Button(section, lk, "Charger un preset…", "upload", height_key=38, wide=True,
                                 ink_key="text_color")
        self.restore.clicked.connect(self.load_preset)
        lay.addWidget(self.export)
        lay.addWidget(self.restore)
        col.addWidget(section)
        notes = aw.Section(content, lk, bottom=False)
        lay = QVBoxLayout(notes)
        pad = lk["section_padding"]
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(6)
        self.metrics = mw.Note(notes, lk, "")
        lay.addWidget(self.metrics)
        lay.addWidget(mw.Note(notes, lk, "Entrée : sRGB SDR encodé. Profil ICC converti s'il est présent, "
                                         "sinon sRGB supposé."))
        self.help_link = mw.Note(notes, lk, "Aide matching / LUT", link=True)
        self.help_link.clicked.connect(lambda: self.owner.help.open_glossary('matching'))
        lay.addWidget(self.help_link)
        lay.addStretch(1)
        col.addWidget(notes, 1)
        self.inspector.setWidget(content)
        row.addWidget(self.inspector)
        self._apply_look()

    def _section(self, parent, title, caption="", spacing=12):
        section = aw.Section(parent, self.look)
        lay = QVBoxLayout(section)
        pad = self.look["section_padding"]
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(spacing)
        section.title_widget = aw.Title(section, self.look, title, caption)
        lay.addWidget(section.title_widget)
        return section, lay

    # -- habillage / réglages --

    def set_look(self, look):
        if look["key"] != self.look["key"]:
            self.look = look
            self._apply_look()

    def _apply_look(self):
        lk = self.look
        for w in self.findChildren(aw._Painted):
            w.set_look(lk)
        self.method.set_look(lk)
        self.method.setFont(aw.font(lk, lk["font_size"]))
        self.inspector.setFixedWidth(lk["inspector_width"])
        self.inspector.setStyleSheet(aw.inspector_stylesheet(lk))
        self.sync_bg()

    def sync_bg(self):
        self.viewer.set_bg(QColor(self.look[f"viewer_bg_{int(self.owner.state['viewer_bg']) % 3 + 1}"]))

    def apply_settings(self, settings):
        method = int(settings.get('video_match_method', 0)) % 2
        if method != self.method.currentIndex():
            self.method.blockSignals(True)
            self.method.setCurrentIndex(method)
            self.method.blockSignals(False)
        self.info.set_text(INFOS[method])
        self.intensity.setValue(int(settings.get('video_match_intensity', 100)))
        size = int(settings.get('video_match_lut_size', 33))
        self.size.set_current(str(size if size in SIZES else 33))
        self._show()

    # -- source / référence --

    def set_source(self, image: QImage, title: str):
        """Nouvelle image du moodboard : la référence et le matching précédents ne s'appliquent plus."""
        self.source, self.source_name = image, title
        self.cache.clear()
        self.reference = self.preset_name = None
        self._reset_result()
        self.viewer.set_images(image, None)

    def _reset_result(self):
        self.cancel.set()
        self.revision += 1
        self.pool.clear()
        self.fit_timer.stop()
        self.preview_timer.stop()
        self.model = self.result = None
        self.busy, self.error = False, ""
        self.modelChanged.emit(False)
        self._show()

    def _choose_source(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Image source', '', IMAGES)
        if path:
            self.source, self.source_name = path, Path(path).name
            self.cache.clear()
            self.preset_name = None
            self._schedule_fit()

    def _choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Image de référence', '', IMAGES)
        if path:
            self.set_reference(path)

    def set_reference(self, path):
        self.reference, self.preset_name = str(path), None
        self._schedule_fit()

    def clear_reference(self):
        self.reference = self.preset_name = None
        self._reset_result()
        self.viewer.set_images(self.source if isinstance(self.source, QImage) else self.viewer.before, None)

    # -- calculs (fond) --

    def _start(self, options):
        self.cancel = threading.Event()
        self.pool.start(_Job(self.revision, options, self.signals, self.cancel, self.cache))

    def _schedule_fit(self):
        self.cancel.set()
        self.revision += 1
        self.pool.clear()
        self.model = None
        self.modelChanged.emit(False)
        self.busy, self.error = self.reference is not None, ""
        self._show()
        self.fit_timer.start()

    def _fit(self):
        if self.reference is None or self.source is None:
            return
        self._fit_intensity = self.intensity.value
        self._start(dict(source=self.source, reference=self.reference, paired=self.method.currentIndex() == 1,
                         intensity=self._fit_intensity / 100))

    def _preview(self):
        if self.model is None or self.result is None:
            return
        self.cancel.set()
        self.revision += 1
        self.pool.clear()
        self._start(dict(preview_model=self.model, source=self.result['before'], intensity=self.intensity.value / 100))

    def _ready(self, revision, result):
        if revision != self.revision:
            return
        if 'export' in result:
            self.owner._flash(result['export'])
            return
        if 'intensity' in result:                               # preset chargé
            self.intensity.setValue(round(result['intensity'] * 100))
            self.settingsChanged.emit('video_match_intensity', self.intensity.value)
        reference = result.get('reference', (self.result or {}).get('reference'))
        self.result = dict(result, reference=reference)
        self.model = result['model']
        self.busy, self.error = False, ""
        self.viewer.set_images(result['before'], result['after'])
        self.modelChanged.emit(True)
        self._show()
        if 'reference' in result and self.intensity.value != getattr(self, '_fit_intensity', self.intensity.value):
            self.preview_timer.start()                          # intensité bougée pendant l'ajustement

    def _failed(self, revision, message):
        if revision == self.revision:
            self.busy, self.error = False, message
            self._show()
            self.owner._flash(message)

    # -- contrôles --

    def _method_changed(self, index):
        self.info.set_text(INFOS[index])
        self.settingsChanged.emit('video_match_method', index)
        if self.reference is not None:
            self._schedule_fit()
        else:
            self._show()

    def _intensity_changed(self, value):
        self.intensity_label.set_value(f"{value} %")
        self.viewer.intensity = value
        self.settingsChanged.emit('video_match_intensity', value)
        if self.model is not None and not self.busy:            # pendant l'ajustement : repris à son arrivée
            self.preview_timer.start()
        self.viewer.update()

    def _size_changed(self, size):
        self.settingsChanged.emit('video_match_lut_size', int(size))
        self._show()

    def _pick_view(self, view):
        self.view = view
        self.pos = {"before": 100.0, "after": 0.0}.get(view, 50.0)
        self.viewer.set_pos(self.pos)
        self._show()

    def _drag_pos(self, pos):
        self.view, self.pos = "split", pos
        self.viewer.set_pos(pos)
        self.viewer.toolbar.set_state("split", self.model is not None)

    def export_lut(self):
        if self.model is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Exporter le matching', 'matching.cube',
                                              'LUT 3D (*.cube);;Preset PIPE FMZ (*.json)')
        if path:
            self.owner._flash('Export et vérification de l’interpolation…')
            self._start(dict(export=path, model=self.model, size=int(self.size.current),
                             intensity=self.intensity.value / 100))

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Preset de matching', '', 'Preset PIPE FMZ (*.json)')
        if path and self.source is not None:
            self.cancel.set()
            self.revision += 1
            self.pool.clear()
            self.reference, self.preset_name = None, Path(path).name
            self.busy, self.error = True, ""
            self._show()
            self._start(dict(preset=path, source=self.source))

    # -- affichage --

    def has_match(self):
        return self.model is not None

    def footer_text(self):
        if self.busy:
            return "Calcul du matching…"
        if self.model is not None:
            return "Glisser sur l’image : rideau avant / après"
        return "Référence manquante : matching non calculé" if self.reference is None and not self.preset_name \
            else "Matching non calculé"

    def _show(self):
        """Recale les zones sur l'état (rien n'est recalculé)."""
        paired = self.method.currentIndex() == 1
        size = int(self.size.current)
        before = (self.result or {}).get('before')
        thumb = before if before is not None else (self.source if isinstance(self.source, QImage) else None)
        self.source_card.set_content(self.source_name, "Image sélectionnée du moodboard"
                                     if isinstance(self.source, QImage) else "Fichier choisi", thumb)
        has_ref = self.reference is not None or self.preset_name is not None
        if has_ref:
            name = Path(self.reference).name if self.reference else f"Preset : {self.preset_name}"
            sub = ("Cadrage identique · paire alignée" if paired else "Scène différente · statistiques RGB") \
                if self.reference else "Modèle chargé"
            self.reference_card.set_content(name, sub, (self.result or {}).get('reference'))
        else:
            self.reference_card.set_content("Choisir une référence…", "Glisser une image ou cliquer", empty=True)
        done = self.model is not None
        source_step = ("done", "✓", "Source", self.source_name)
        ref_step = ("done", "✓", "Référence", ("paire alignée" if paired else "statistiques") if self.reference
                    else "preset") if has_ref else ("current", "2", "Référence", "à choisir")
        if done:
            match_step = ("done", "✓", "Matching calculé", f"LUT {size}³")
        elif self.busy:
            match_step = ("current", "3", "Matching", "calcul…")
        elif self.error:
            match_step = ("current", "3", "Matching", "erreur")
        else:
            match_step = ("todo", "3", "Matching", "en attente")
        self.steps.set_steps([source_step, ref_step, match_step])
        self.lut_section.title_widget.set_text("LUT 3D", "Table : " + table_size(size))
        self.size_caption.set_text(f"Points par axe · {size}³ entrées RGB float32")
        self.export.set_active(done)
        self.viewer.intensity = self.intensity.value
        self.intensity_label.set_value(f"{self.intensity.value} %")
        self.viewer.message = "" if done else ("Calcul du matching…" if self.busy else
                                               (self.error or "Choisis une référence pour calculer le matching."))
        self.viewer.set_pos(self.pos)
        self.viewer.toolbar.set_state(self.view, done)
        self.viewer.update()
        metrics = self.model.metrics if done else {}
        text = " · ".join(f"{label} : {metrics[k]:.4g}".replace(".", ",") for k, label in METRICS.items()
                          if isinstance(metrics.get(k), (int, float)))
        self.metrics.set_text(f"{self.model.method} · {text}" if done else "")
        self.metrics.setVisible(done)
        self.statusChanged.emit()

    def stop(self):
        self.cancel.set()
        self.revision += 1
        self.fit_timer.stop()
        self.preview_timer.stop()
        self.pool.clear()


class _Label(aw._Painted):
    """« Intensité » (13 px) à gauche, valeur mono 13 px forte à droite."""

    def __init__(self, parent, look, text, value):
        super().__init__(parent, look)
        self.text, self.value = text, value
        self.setFixedHeight(18)

    def set_value(self, value):
        if value != self.value:
            self.value = value
            self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        from PySide6.QtCore import QRectF
        lk = self.look
        p = QPainter(self)
        p.setFont(aw.font(lk, lk["font_size"]))
        p.setPen(QColor(lk["text_color"]))
        p.drawText(QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter, self.text)
        p.setFont(aw.font(lk, 13, mono=True))
        p.setPen(QColor(lk["strong_color"]))
        p.drawText(QRectF(self.rect()), Qt.AlignRight | Qt.AlignVCenter, self.value)
