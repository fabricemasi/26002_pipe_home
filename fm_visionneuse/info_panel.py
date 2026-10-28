"""Panneau d'informations de la visionneuse (FocusInfoPanel).

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QWidget

from app_style import scaled
import previews

from .loader import display_name
from .attributes_ui import FileAttributesEditor
from .info import _InfoSignals, _InfoTask


class FocusInfoPanel(QWidget):
    """Tableau de TOUS les parametres de l'image en cours, a droite de l'image (Reglages >
    Visionneuse > « Parametres de l'image », touche I). Lu en fond (_InfoTask, cache par fichier).
    Habillage = celui des REGLAGES, jamais un style a part : cadre de panneau (`_PanelFrame`,
    M["panel_bg"] / M["panel_border"]), titres de section (police / couleur des titres de niveau 1),
    tableaux Parametre | Valeur de la v2 (`_flat_cells_table`, roles de texte row_label / value),
    style commun pose par `seed_window_look` (comme settings_quick_style.QuickStyleWindow). Les
    dimensions des tableaux (largeurs, hauteurs, justifications) s'enregistrent comme dans les
    reglages (`table_dims`, cle `Paramètres de l'image/<section>#0`). La visionneuse lui RESERVE sa
    bande (PipelineBrowser._viewer_area) : l'image n'est jamais couverte."""

    WIDTH = 380
    DIMS = "Paramètres de l'image"
    _VALUE_WIDTH = 190          # valeurs plus longues : abregees (texte entier en info-bulle)

    def __init__(self, parent):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout
        from settings_window import _PanelFrame
        self._signals = _InfoSignals(self)
        self._signals.done.connect(self._on_done)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._cache: OrderedDict = OrderedDict()
        self._path: Path | None = None
        self._sections: list = []
        self._shape = None                    # (titre, libelles) des tableaux affiches
        self._values: list = []               # etiquettes des valeurs, dans l'ordre des lignes
        self._tables: list = []
        # Attributs du fichier en focus (note, couleur, j'aime, mots cles, statut), en tete du tableau.
        self._attributes = FileAttributesEditor(self)
        self._frame = _PanelFrame(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)
        box = QVBoxLayout(self._frame)
        box.setContentsMargins(1, 1, 1, 1)
        self._scroller = QScrollArea()
        self._scroller.setFrameShape(QFrame.NoFrame)
        self._scroller.setWidgetResizable(True)
        self._scroller.setStyleSheet("QScrollArea { background: transparent; }")
        self._scroller.viewport().setStyleSheet("background: transparent;")
        box.addWidget(self._scroller)
        self._dims_timer = QTimer(self)
        self._dims_timer.setSingleShot(True)
        self._dims_timer.setInterval(400)
        self._dims_timer.timeout.connect(self._save_dims)
        self.restyle()

    @staticmethod
    def panel_width() -> int:
        return scaled(FocusInfoPanel.WIDTH)

    def restyle(self):
        """(Re)pose le style commun des reglages et reconstruit les tableaux (reglages changes)."""
        import ui_state
        from settings_store import M
        from settings_widgets import _TABLE_DIMS
        import settings_window_v2 as v2
        settings = dict(ui_state.APPLIED_SETTINGS or {})
        if "colors" in settings:
            v2.seed_window_look(settings)
        for key, dims in (settings.get("table_dims") or {}).items():
            if key.startswith(self.DIMS + "/"):
                _TABLE_DIMS.setdefault(key, dims)
        self._frame.setColors(M["panel_bg"], M["panel_border"])
        self._shape = None
        self._show(self._sections)

    def set_path(self, path: Path | None):
        if path == self._path and self._sections:
            return
        self._attributes.set_path(path)
        self._path = path
        if path is None:
            self._show([])
            return
        mtime = previews.cached_mtime(path)
        hit = self._cache.get(str(path))
        if hit is not None and hit[0] == mtime:
            self._show(hit[1])
        else:
            # En attendant la lecture : le tableau reste en place, valeurs en attente.
            self._show([(title, [(label, "…") for label, _v in rows]) for title, rows in self._sections]
                       or [("Fichier", [("Nom", display_name(path))])])
            self._pool.clear()
            self._pool.start(_InfoTask(path, mtime, self._signals))

    def refresh(self, path: Path):
        """Relit les parametres de `path` (sources des apercus changees : apercu Lightroom ou proxy
        arrive apres coup) ; le tableau garde sa forme, seules les valeurs changent."""
        self._cache.pop(str(path), None)
        if self._path is not None and str(self._path) == str(path):
            self._pool.start(_InfoTask(path, previews.cached_mtime(path), self._signals))

    def sections(self) -> list:
        return self._sections

    def wait_done(self, msecs: int = 5000) -> bool:
        return self._pool.waitForDone(msecs)

    def _on_done(self, key: str, mtime: float, info):
        self._cache[key] = (mtime, info)
        self._cache.move_to_end(key)
        while len(self._cache) > 512:
            self._cache.popitem(last=False)
        if self._path is not None and str(self._path) == key:
            self._show(info)

    def _value_text(self, label: QWidget, value) -> None:
        text = str(value)
        metrics = QFontMetrics(label.font())
        width = scaled(self._VALUE_WIDTH)
        label.setText(metrics.elidedText(text, Qt.ElideMiddle, width))
        label.setToolTip(text if metrics.horizontalAdvance(text) > width else "")

    def _show(self, sections: list):
        """Meme forme qu'avant (memes sections, memes libelles : cas courant d'un dossier) : seules
        les valeurs changent, aucun widget n'est reconstruit. Sinon : tableaux reconstruits."""
        from fm_visionneuse import file_attributes
        self._sections = sections
        shape = (file_attributes.eligible(self._path),
                 tuple((title, tuple(label for label, _v in rows)) for title, rows in sections))
        if shape == self._shape:
            values = [value for _t, rows in sections for _l, value in rows]
            for label, value in zip(self._values, values):
                self._value_text(label, value)
            return
        from PySide6.QtWidgets import QLabel, QVBoxLayout
        import settings_window_v2 as v2
        from settings_store import _title_color, _title_font
        from settings_theme import _text_label
        self._shape = shape
        self._values, self._tables = [], []
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(scaled(14), scaled(10), scaled(14), scaled(14))
        layout.setSpacing(scaled(6))
        if shape[0] and sections:                      # fichier a apercu : ses attributs, modifiables
            head = QLabel(FileAttributesEditor.TITLE)
            head.setFont(_title_font(1))
            head.setStyleSheet(f"color: {_title_color(1)}; background: transparent;")
            layout.addWidget(head)
            table = v2._flat_cells_table(self._attributes.build_rows())
            table._dims_key = f"{self.DIMS}/{FileAttributesEditor.TITLE}#0"
            table.dimsChanged.connect(self._dims_timer.start)
            self._tables.append(table)
            layout.addWidget(table, 0, Qt.AlignLeft)
            layout.addSpacing(scaled(8))
        for title, rows in sections:
            head = QLabel(title)
            head.setFont(_title_font(1))
            head.setStyleSheet(f"color: {_title_color(1)}; background: transparent;")
            layout.addWidget(head)
            table_rows = []
            for label, value in rows:
                cell = _text_label("", "value")
                self._value_text(cell, value)
                self._values.append(cell)
                table_rows.append((label, cell, None))
            table = v2._flat_cells_table(table_rows)
            table._dims_key = f"{self.DIMS}/{title}#0"
            table.dimsChanged.connect(self._dims_timer.start)
            self._tables.append(table)
            layout.addWidget(table, 0, Qt.AlignLeft)       # tableaux justifies a gauche
            layout.addSpacing(scaled(8))
        layout.addStretch(1)
        old = self._scroller.takeWidget()
        self._scroller.setWidget(inner)
        if old is not None:
            old.deleteLater()

    def _save_dims(self):
        """Dimensions des tableaux tirees a la main : sur le disque aussitot (comme les reglages)."""
        from settings_store import load_settings, save_settings
        from settings_widgets import _TABLE_DIMS
        import ui_state
        changed = {}
        for table in self._tables:
            try:
                changed[table._dims_key] = table.collectDims()
            except RuntimeError:
                continue
        if not changed:
            return
        _TABLE_DIMS.update(changed)
        settings = load_settings()
        all_dims = dict(settings.get("table_dims") or {})
        all_dims.update(changed)
        settings["table_dims"] = all_dims
        save_settings(settings)
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["table_dims"] = dict(all_dims)
