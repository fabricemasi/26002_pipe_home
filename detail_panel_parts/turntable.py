"""Inspecteur : médias 3D rendus (image / turntable), curseur et lecture du turntable.

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtGui import QPixmap

from config import RENDERABLE_3D_EXTENSIONS
from previews import TURNTABLE_EXTENSIONS, _PREVIEW_DECODE_MANAGER, _cached_file_image_pixmap, _turntable_frames


class TurntableMixin:
    """Méthodes de DetailPanel : inspecteur : médias 3D rendus (image / turntable), curseur et lecture du turntable."""

    def _selected_preview_media(self) -> str:
        return "turntable" if self.preview_turntable_button.isChecked() else "image"

    def _render_preview_media(self, media: str, render_mode: str):
        if not self._current_path:
            return
        path = Path(self._current_path)
        if path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS:
            return
        if self._current_path in _PREVIEW_DECODE_MANAGER.active:
            return
        self._preview_render_modes[(self._current_path, media)] = render_mode
        self._select_preview_media(media)
        if media == "turntable":
            self._render_turntable(render_mode)
        else:
            self._start_3d_preview(path, render_mode)

    def _refresh_render_action_buttons(self):
        enabled = bool(self._current_path and self._current_path not in _PREVIEW_DECODE_MANAGER.active)
        for button in self.render_action_buttons.values():
            button.setEnabled(enabled)

    def _select_preview_media(self, media: str | None = None):
        self._turntable_timer.stop()
        self._turntable_frame_paths = []
        media = media or self._selected_preview_media()
        button = self.preview_media_buttons.get(media, self.preview_image_button)
        button.setChecked(True)
        if not self._current_path:
            return
        path = Path(self._current_path)
        if path.suffix.lower() not in TURNTABLE_EXTENSIONS:
            return
        self._preview_media_preferences[self._current_path] = media
        is_turntable = media == "turntable"
        self.turntable_controls.setVisible(is_turntable)
        self.turntable_play_button.setText("▶")
        if not is_turntable:
            mode = self._preview_render_modes.get((self._current_path, "image"), "low")
            self._preview_pixmap = _cached_file_image_pixmap(path, mode)
            self._update_preview()
            self._refresh_preview_stale_badge(path)
            return
        try:
            mode = self._preview_render_modes.get((self._current_path, "turntable"), "low")
            self._turntable_frame_paths = _turntable_frames(path, path.stat().st_mtime,
                                                           allow_stale=True, render_mode=mode)
        except OSError:
            pass
        self._turntable_frame_index = 0
        if self._turntable_frame_paths:
            self.turntable_slider.blockSignals(True)
            self.turntable_slider.setValue(0)
            self.turntable_slider.blockSignals(False)
            self._show_turntable_frame()
            self._turntable_timer.start()
            self.turntable_play_button.setText("Ⅱ")
            self._update_turntable_control_state(True)
        else:
            self._preview_pixmap = None
            self._update_preview()
            self.well_label.setText("Turntable en attente du rendu automatique\n↻ pour le calculer maintenant")
            self.turntable_counter.setText("— / 72")
            self.turntable_play_button.setText("▶")
            self._update_turntable_control_state(False)
        self._refresh_preview_stale_badge(path)

    def _update_turntable_control_state(self, has_frames: bool):
        for button in (self.turntable_play_button, self.turntable_stop_button,
                       self.turntable_previous_button, self.turntable_next_button):
            button.setEnabled(has_frames)
        self.turntable_slider.setEnabled(has_frames)

    def _on_turntable_slider_changed(self, index: int):
        if not self._turntable_frame_paths:
            return
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_index = max(0, min(len(self._turntable_frame_paths) - 1, index))
        self._show_turntable_frame()

    def _step_turntable(self, step: int):
        if not self._turntable_frame_paths:
            return
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_index = (self._turntable_frame_index + step) % len(self._turntable_frame_paths)
        self._show_turntable_frame()

    def _stop_turntable_playback(self):
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        if self._turntable_frame_paths:
            self._turntable_frame_index = 0
            self._show_turntable_frame()

    def _show_turntable_frame(self):
        if not self._turntable_frame_paths:
            return
        frame = self._turntable_frame_paths[self._turntable_frame_index]
        pixmap = QPixmap(str(frame))
        if not pixmap.isNull():
            self._preview_pixmap = pixmap
            self._update_preview()
            self.turntable_counter.setText(f"{self._turntable_frame_index + 1} / 72")
            self.turntable_slider.blockSignals(True)
            self.turntable_slider.setValue(self._turntable_frame_index)
            self.turntable_slider.blockSignals(False)

    def _advance_turntable(self):
        if self._turntable_frame_paths and not self.preview_log.isVisible():
            self._turntable_frame_index = (self._turntable_frame_index + 1) % len(self._turntable_frame_paths)
            self._show_turntable_frame()

    def _toggle_turntable_playback(self):
        if self._turntable_timer.isActive():
            self._turntable_timer.stop()
            self.turntable_play_button.setText("▶")
        elif self._turntable_frame_paths:
            self._turntable_timer.start()
            self.turntable_play_button.setText("Ⅱ")

    def _render_turntable(self, render_mode: str | None = None):
        if not self._current_path:
            return
        path = Path(self._current_path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        self._turntable_timer.stop()
        render_mode = render_mode or self._preview_render_modes.get((self._current_path, "turntable"), "low")
        root_field = getattr(self.window(), "root_field", None)
        _PREVIEW_DECODE_MANAGER.request(path, mtime, force_render=True, media_type="turntable",
                                       render_mode=render_mode,
                                       log_directory=Path(root_field.text()) if root_field is not None else None)

    def _on_turntable_ready(self, path_str, mtime, image):
        self._refresh_render_action_buttons()
        self._preview_generation_paths.discard(path_str)
        self._auto_preview_paths.discard(path_str)
        if not self._preview_generation_paths:
            self.preview_log.hide()
            self.preview_progress.hide()
            self.well_label.show()
        if path_str == self._current_path and self._selected_preview_media() == "turntable":
            self._select_preview_media()
            if image is None and not self._turntable_frame_paths:
                self.well_label.setText("Turntable indisponible — consulter le journal de rendu")
        else:
            self._update_preview()
