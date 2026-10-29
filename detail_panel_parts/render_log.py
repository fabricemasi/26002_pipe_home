"""Inspecteur : rendus 3D (lancement, progression, protection) et journal de rendu.

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from datetime import datetime
from config import IMAGE_EXTENSIONS, PREVIEW_MIN_HEIGHT, RENDERABLE_3D_EXTENSIONS, _STALE_PREVIEW_PATHS
from previews import (
    _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES, _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM, _IdlePreviewScheduler,
    _PREVIEW_DECODE_MANAGER, _RenderLogTable, _bounded_cache_set, _cache_file_preview, _file_image_column_cache,
    _file_image_high_cache, _read_preview_pixmap, _read_render_log_entries, _render_log_line, _render_log_path,
    _set_preview_protected, _write_render_log,
)
from browser_core import entry_mtime


class RenderLogMixin:
    """Méthodes de DetailPanel : inspecteur : rendus 3D (lancement, progression, protection) et journal de rendu."""

    def _start_3d_preview(self, path: Path, render_mode: str = "low"):
        """Affiche la barre d'activite et lance le rendu 3D en arriere-plan."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        self._preview_request_path = str(path)
        self._preview_pixmap = None
        self.well_label.clear()
        root_field = getattr(self.window(), "root_field", None)
        _PREVIEW_DECODE_MANAGER.request(path, mtime, force_render=True, render_mode=render_mode,
                                       log_directory=Path(root_field.text()) if root_field is not None else None)
        if str(path) in _PREVIEW_DECODE_MANAGER.active and str(path) not in self._preview_generation_paths:
            self._on_preview_generation_started(str(path))

    def prepare_auto_preview_log(self, path: Path):
        """Marque le prochain rendu automatique avant le signal started."""
        self._auto_preview_paths.add(str(path))

    def open_preview_render_log(self):
        """Affiche les journaux disponibles, avec choix du jour."""
        window = self.window()
        root_field = getattr(window, "root_field", None)
        if root_field is None:
            QMessageBox.warning(self, "Journal des rendus", "La racine du navigateur est introuvable.")
            return
        root = Path(root_field.text().strip())
        try:
            path = _render_log_path(root)
            if not path.is_file():
                path = _write_render_log(root)
            days = sorted((item.stem.removeprefix("pipeline_preview_render_")
                           for item in root.glob("pipeline_preview_render_????-??-??.html")
                           if item.is_file()), reverse=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Journal des rendus", f"Impossible de lire le journal :\n{exc}")
            return
        dialog = getattr(self, "_render_log_dialog", None)
        if dialog is None:
            dialog = QDialog(self)
            dialog.resize(1400, 650)
            layout = QVBoxLayout(dialog)
            day_row = QHBoxLayout()
            day_row.addWidget(QLabel("Jour :", dialog))
            day_combo = QComboBox(dialog)
            day_combo.currentIndexChanged.connect(self._load_selected_render_log)
            day_row.addWidget(day_combo)
            day_row.addStretch(1)
            layout.addLayout(day_row)
            table = _RenderLogTable(dialog)
            layout.addWidget(table)
            buttons = QHBoxLayout()
            refresh = QPushButton("Actualiser", dialog)
            refresh.clicked.connect(self.open_preview_render_log)
            buttons.addWidget(refresh)
            buttons.addStretch(1)
            close = QPushButton("Fermer", dialog)
            close.clicked.connect(dialog.close)
            buttons.addWidget(close)
            layout.addLayout(buttons)
            self._render_log_dialog = dialog
            self._render_log_dialog_table = table
            self._render_log_day_combo = day_combo
            self._render_log_refresh_timer = QTimer(dialog)
            self._render_log_refresh_timer.setInterval(500)
            self._render_log_refresh_timer.timeout.connect(self._refresh_open_render_log)
            dialog.finished.connect(lambda _result: self._render_log_refresh_timer.stop())
        combo = self._render_log_day_combo
        selected = combo.currentData() if getattr(self, "_render_log_root", None) == root else None
        self._render_log_root = root
        combo.blockSignals(True)
        combo.clear()
        for day in days:
            combo.addItem("/".join(reversed(day.split("-"))), day)
        index = combo.findData(selected or datetime.now().strftime("%Y-%m-%d"))
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)
        self._load_selected_render_log()
        self._render_log_refresh_timer.start()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _load_selected_render_log(self, *_):
        day = self._render_log_day_combo.currentData()
        if not day:
            return
        path = self._render_log_root / f"pipeline_preview_render_{day}.html"
        try:
            entries = _read_render_log_entries(path)
        except (OSError, ValueError) as exc:
            self._render_log_dialog_table.clear()
            QMessageBox.warning(self, "Journal des rendus", f"Impossible de lire le journal :\n{exc}")
            return
        self._render_log_dialog.setWindowTitle(f"Journal des rendus — {day}")
        self._render_log_dialog.setToolTip(str(path))
        self._render_log_dialog_table.load_entries(entries)
        self._render_log_dialog_table.ensureCursorVisible()
        stamp = path.stat()
        self._render_log_loaded_signature = (stamp.st_mtime_ns, stamp.st_size)

    def _refresh_open_render_log(self):
        day = self._render_log_day_combo.currentData()
        if not day:
            return
        path = self._render_log_root / f"pipeline_preview_render_{day}.html"
        try:
            stamp = path.stat()
            signature = (stamp.st_mtime_ns, stamp.st_size)
            if signature == getattr(self, "_render_log_loaded_signature", None):
                return
            entries = _read_render_log_entries(path)
        except (OSError, ValueError):
            return
        table = self._render_log_dialog_table
        vertical = table.verticalScrollBar()
        at_bottom = vertical.value() >= vertical.maximum() - 2
        old_position = vertical.value()
        table.load_entries(entries)
        vertical.setValue(vertical.maximum() if at_bottom else old_position)
        self._render_log_loaded_signature = signature

    def _on_preview_generation_started(self, path_str: str):
        self._refresh_render_action_buttons()
        was_idle = not self._preview_generation_paths
        self._preview_generation_paths.add(path_str)
        automatic = path_str in self._auto_preview_paths
        if self._text_shown() or self.video_widget.isVisible():
            if not automatic:
                return
            self._hide_text_views()
            self._stop_video()
            self.well.show()
        if was_idle:
            if automatic:
                if self._auto_preview_log_count == 0:
                    self.preview_log.clear()
                else:
                    self.preview_log.appendPlainText(_IdlePreviewScheduler.LOG_SEPARATOR)
            else:
                self.preview_log.clear()
                self._auto_preview_log_count = 0
        if automatic:
            self._auto_preview_log_count += 1
        self.well.show()
        self.preview_log.show()
        self.preview_progress.hide()
        self.well_label.hide()
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.preview_log.appendPlainText(_render_log_line(f"> Aperçu en cours : {path_str}"),
                                         **self._preview_log_metadata(path_str))
        self.preview_log.ensureCursorVisible()

    def _on_preview_generation_progress(self, path_str: str, percent: int, message: str):
        if path_str not in self._preview_generation_paths:
            return
        if self._text_shown() or self.video_widget.isVisible():
            if path_str not in self._auto_preview_paths:
                return
            self._hide_text_views()
            self._stop_video()
            self.well.show()
        if not self.preview_log.isVisible():
            self.well.show()
            self.preview_log.show()
            self.well_label.hide()
            self.preview_progress.hide()
        self.preview_log.appendPlainText(_render_log_line(f"[{percent:3d}%] {Path(path_str).name} — {message}"),
                                         **self._preview_log_metadata(path_str))
        self.preview_log.ensureCursorVisible()

    def _preview_log_metadata(self, path_str):
        task = _PREVIEW_DECODE_MANAGER.active.get(path_str)
        root_field = getattr(self.window(), "root_field", None)
        return {"source": path_str, "media_type": getattr(task, "media_type", "image"),
                "render_mode": getattr(task, "render_mode", ""),
                "output_path": getattr(task, "output_path", ""),
                "root": Path(root_field.text()) if root_field is not None else None}

    def _on_3d_preview_ready(self, path_str: str, mtime: float, image):
        """Met en cache le resultat du worker, puis l'affiche s'il est toujours selectionne."""
        if path_str == self._current_path:
            self._restore_lightroom_preview_button()
            self._refresh_preview_origin_badge(path_str, force=True)
        self._refresh_render_action_buttons()
        was_requested = path_str == self._preview_request_path or path_str in self._preview_generation_paths
        self._preview_generation_paths.discard(path_str)
        self._auto_preview_paths.discard(path_str)
        path = Path(path_str)
        try:
            from previews import cached_mtime, is_remote_path
            still_current_file = (cached_mtime(path) if is_remote_path(path) else entry_mtime(path)) == mtime
        except OSError:
            still_current_file = False
        pix = None
        completed_mode = _PREVIEW_DECODE_MANAGER.last_completed_mode.get(path_str, "low")
        if still_current_file and image is not None and not image.isNull():
            pix = QPixmap.fromImage(image)
            if completed_mode == "high" and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
                _bounded_cache_set(_file_image_high_cache, path_str, (mtime, pix))
                small = pix.scaled(_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM, _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM,
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
                _bounded_cache_set(_file_image_column_cache, path_str, (mtime, small),
                                   _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES)
            else:
                _cache_file_preview(path_str, mtime, pix, path_str in _STALE_PREVIEW_PATHS)
            # Les delegates des colonnes consultent le meme cache; les
            # repeindre leur fait afficher le rendu qui vient d'etre produit.
            for widget in QApplication.allWidgets():
                if isinstance(widget, QAbstractItemView):
                    # Une vue qui sait ne repeindre que la case concernee (la planche de la visionneuse,
                    # qui ne doit rien refaire pendant son animation d'ouverture) le fait elle-meme.
                    hook = getattr(widget, "preview_ready", None)
                    if hook is not None:
                        hook(path_str)
                    else:
                        widget.viewport().update()
        selected_mode = self._preview_render_modes.get((path_str, "image"), "low")
        show_result = completed_mode == selected_mode or path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS
        if (self._preview_request_path == path_str or self._current_path == path_str) and show_result:
            if pix is None and path_str in _STALE_PREVIEW_PATHS and still_current_file:
                pix, _is_stale = _read_preview_pixmap(path, mtime)
            self._preview_request_path = None
            if pix is not None and path.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    import lightroom_bridge
                    managed = lightroom_bridge.is_managed(path)
                except (ImportError, OSError, ValueError):
                    managed = False
                if managed:
                    self._preview_pixmap = pix
                else:
                    source_pix = QPixmap(path_str)
                    self._preview_pixmap = source_pix if not source_pix.isNull() else pix
            else:
                self._preview_pixmap = pix
            self._update_preview()
            self._refresh_preview_stale_badge(path)
        elif self._preview_request_path == path_str:
            self._preview_request_path = None
        if not was_requested:
            return
        if self._preview_generation_paths:
            if not self._text_shown() and not self.video_widget.isVisible():
                completion_percent = 100 if pix is not None else 0
                completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
                self.preview_log.appendPlainText(
                    _render_log_line(f"[{completion_percent:3d}%] {path.name} — {completion_message}")
                )
                self.preview_log.ensureCursorVisible()
            return
        if not self._text_shown() and not self.video_widget.isVisible():
            completion_percent = 100 if pix is not None else 0
            completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
            self.preview_log.appendPlainText(
                _render_log_line(f"[{completion_percent:3d}%] {path.name} — {completion_message}")
            )
            self.preview_log.ensureCursorVisible()
            self.preview_log.hide()
        self.preview_progress.hide()
        self.well_label.show()
        self._update_preview()
        if path_str == self._current_path and self._selected_preview_media() == "turntable":
            self._select_preview_media()

    def _on_render_protection_toggled(self, protected: bool):
        if not self._current_path:
            return
        path = Path(self._current_path)
        if path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS:
            return
        _set_preview_protected(path, protected)
        if protected and _PREVIEW_DECODE_MANAGER.active.get(str(path)) is not None:
            # Une protection active pendant un rendu automatique annule la
            # prochaine étape dès que le worker consulte son cancel_event.
            scheduler = getattr(self.window(), "_idle_preview_scheduler", None)
            if scheduler is not None and scheduler.active_key == str(path):
                if scheduler.cancel_event is not None:
                    scheduler.cancel_event.set()
