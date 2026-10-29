"""Inspecteur : PDF (zoom, pages) et planches PureRef (navigation, export).

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPixmap

from config import PREVIEW_MAX_HEIGHT
from preview_column import _PUR_EXPORT_POOL, _PureRefExportTask, read_pur_embedded_image, read_pur_exported_image
from previews import _render_pdf_page


class PdfPurMixin:
    """Méthodes de DetailPanel : inspecteur : PDF (zoom, pages) et planches PureRef (navigation, export)."""

    def _pdf_geometry(self):
        """(largeur, hauteur) de la page telle qu'affichee a zoom 1, et coin haut-gauche
        de cette zone dans well_label."""
        pix = self._preview_pixmap
        if pix is None or pix.isNull():
            return None
        scale = min(1.0, max(self.width() - 32, 50) / pix.width(), PREVIEW_MAX_HEIGHT / pix.height())
        w, h = max(1, round(pix.width() * scale)), max(1, round(pix.height() * scale))
        label = self.well_label.size()
        return w, h, (label.width() - w) / 2, (label.height() - h) / 2

    def _pdf_clamp_view(self):
        span = 1.0 / self._pdf_zoom
        self._pdf_view[0] = max(0.0, min(1.0 - span, self._pdf_view[0]))
        self._pdf_view[1] = max(0.0, min(1.0 - span, self._pdf_view[1]))

    def _pdf_set_zoom(self, zoom: float, u: float = 0.5, v: float = 0.5):
        """Zoom (1 = page entiere) en gardant fixe le point (u, v) de la zone visible."""
        old = self._pdf_zoom
        zoom = max(1.0, min(8.0, zoom))
        if zoom == old:
            return
        self._pdf_view[0] += u * (1 / old - 1 / zoom)
        self._pdf_view[1] += v * (1 / old - 1 / zoom)
        self._pdf_zoom = zoom
        self._pdf_clamp_view()
        self._update_preview()

    def _pdf_event(self, event) -> bool:
        """Molette = page suivante/precedente (ou defilement si zoome), Ctrl+molette =
        zoom, glisser = deplacer la page zoomee, clic milieu = zoom 1."""
        etype = event.type()
        if etype == QEvent.Wheel:
            delta = event.angleDelta().y()
            if not delta:
                return False
            if event.modifiers() & Qt.ControlModifier:
                geo = self._pdf_geometry()
                u = v = 0.5
                if geo:
                    pos = self.well_label.mapFromGlobal(event.globalPosition().toPoint())
                    u = max(0.0, min(1.0, (pos.x() - geo[2]) / geo[0]))
                    v = max(0.0, min(1.0, (pos.y() - geo[3]) / geo[1]))
                self._pdf_set_zoom(self._pdf_zoom * 1.2 ** (delta / 120), u, v)
            elif self._pdf_zoom > 1.0:
                self._pdf_view[1] -= delta / 120 * 0.1 / self._pdf_zoom
                self._pdf_clamp_view()
                self._update_preview()
            else:
                self._pdf_wheel += delta
                steps = int(self._pdf_wheel / 120)
                if steps:
                    self._pdf_wheel -= steps * 120
                    self._navigate_pdf_page(-steps)
            return True
        if etype == QEvent.MouseButtonPress:
            if event.button() == Qt.MiddleButton:
                self._pdf_set_zoom(1.0)
                return True
            if event.button() == Qt.LeftButton and self._pdf_zoom > 1.0:
                self._pdf_drag = event.globalPosition().toPoint()
                return True
        elif etype == QEvent.MouseMove and self._pdf_drag is not None:
            geo = self._pdf_geometry()
            now = event.globalPosition().toPoint()
            if geo:
                self._pdf_view[0] -= (now.x() - self._pdf_drag.x()) / geo[0] / self._pdf_zoom
                self._pdf_view[1] -= (now.y() - self._pdf_drag.y()) / geo[1] / self._pdf_zoom
                self._pdf_clamp_view()
                self._update_preview()
            self._pdf_drag = now
            return True
        elif etype == QEvent.MouseButtonRelease and self._pdf_drag is not None:
            self._pdf_drag = None
            return True
        return False

    def _navigate_pdf_page(self, step: int):
        """Affiche la page courante + `step` du PDF selectionne (0 = recharger)."""
        if self._pdf_path != self._current_path:
            return
        page = max(0, min(self._pdf_pages - 1, self._pdf_page + step))
        image = _render_pdf_page(Path(self._pdf_path), 1800, page)
        if image is None:
            self.pur_image_counter.setText("Page illisible")
        else:
            self._pdf_page = page
            self._preview_pixmap = QPixmap.fromImage(image)
            self.well.show()
            self.well_label.show()
            self._update_preview()
        self.pur_image_counter.setText(f"Page {self._pdf_page + 1} / {self._pdf_pages}")
        self.pur_previous_button.setEnabled(self._pdf_page > 0)
        self.pur_next_button.setEnabled(self._pdf_page + 1 < self._pdf_pages)

    def select_pur_image(self, path_str: str, index: int):
        """Visionneuse -> inspecteur : la planche `path_str` montre son image n° `index` (celle regardee),
        pas la premiere. Images pas encore connues (extraction en cours) : rang retenu, applique des qu'il
        existe (_apply_pur_wanted)."""
        self._pur_wanted = (path_str, int(index))
        if self._pur_image_path == path_str and self._apply_pur_wanted(path_str):
            self._navigate_pur_image(0)

    def _apply_pur_wanted(self, path_str: str) -> bool:
        wanted = self._pur_wanted
        if wanted is None or wanted[0] != path_str:
            return False
        total = len(self._pur_exported_images) or len(self._pur_image_ranges)
        if wanted[1] >= total:
            return False                       # pas encore extraite : on attend
        self._pur_image_index = wanted[1]
        self._pur_wanted = None
        return True

    def _navigate_pur_image(self, step: int):
        if self._pdf_path is not None:
            self._navigate_pdf_page(step)
            return
        if self._pur_image_path != self._current_path:
            return
        direction = -1 if step < 0 else 1
        index = self._pur_image_index + step if step else self._pur_image_index
        total = len(self._pur_exported_images) or len(self._pur_image_ranges)
        while 0 <= index < total:
            if self._pur_exported_images:
                image = read_pur_exported_image(Path(self._pur_exported_images[index]))
            else:
                image = read_pur_embedded_image(Path(self._pur_image_path), self._pur_image_ranges[index])
            if image is not None and not image.isNull():
                self._pur_image_index = index
                self._preview_pixmap = QPixmap.fromImage(image)
                suffix = " (extraction en cours)" if self._pur_export_task is not None else ""
                self.pur_image_counter.setText(f"Image {index + 1} / {total}{suffix}")
                self.pur_previous_button.setEnabled(index > 0)
                self.pur_next_button.setEnabled(index + 1 < total)
                self.well.show()
                self.well_label.show()
                self._update_preview()
                return
            index += direction
        self.pur_previous_button.setEnabled(index > 0)
        self.pur_next_button.setEnabled(False if direction > 0 else index + 1 < total)

    def _start_pur_export(self, path: Path, mtime: float):
        current = self._pur_export_task
        if current is not None and str(current.path) == str(path) and current.mtime == mtime:
            return
        task = _PureRefExportTask(path, mtime)
        task.signals.progress.connect(self._on_pur_export_progress)
        task.signals.finished.connect(self._on_pur_export_finished)
        self._pur_export_task = task
        _PUR_EXPORT_POOL.start(task)

    def _on_pur_export_progress(self, path_str: str, mtime: float, files):
        if path_str != self._current_path or path_str != self._pur_image_path:
            return
        try:
            if Path(path_str).stat().st_mtime != mtime:
                return
        except OSError:
            return
        self._pur_exported_images = list(files)
        self._apply_pur_wanted(path_str)
        self.pur_next_button.setEnabled(self._pur_image_index + 1 < len(files))
        self._navigate_pur_image(0)

    def _on_pur_export_finished(self, path_str: str, mtime: float, files, error: str):
        if self._pur_export_task is not None and str(self._pur_export_task.path) == path_str:
            self._pur_export_task = None
        if path_str != self._current_path or path_str != self._pur_image_path:
            return
        try:
            current_mtime = Path(path_str).stat().st_mtime
        except OSError:
            return
        if current_mtime != mtime:
            return
        if files:
            self._pur_exported_images = list(files)
            self._apply_pur_wanted(path_str)
            self._pur_image_index = min(self._pur_image_index, len(files) - 1)
            self.pur_next_button.setEnabled(self._pur_image_index + 1 < len(files))
            self._navigate_pur_image(0)
        elif error:
            self.pur_image_counter.setText(error)
            self.pur_previous_button.setEnabled(False)
            self.pur_next_button.setEnabled(False)
