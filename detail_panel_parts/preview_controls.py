"""Inspecteur : boutons et menu contextuel de l'aperçu (supprimer, Lightroom, vidéo).

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtCore import QMimeData, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox

from app_style import C, font
from config import IMAGE_EXTENSIONS, RENDERABLE_3D_EXTENSIONS
from settings_widgets import Menu
from previews import delete_preview_cache, _file_image_cache_path, _find_stale_preview_cache
from browser_core import reveal_in_file_manager


class PreviewControlsMixin:
    """Méthodes de DetailPanel : inspecteur : boutons et menu contextuel de l'aperçu (supprimer, Lightroom, vidéo)."""

    def _delete_preview(self, path: Path):
        """Supprime l'APERCU en cache (image, turntable) du fichier affiche,
        apres confirmation ; le fichier lui-meme n'est jamais touche."""
        answer = QMessageBox.question(
            self, "Supprimer l'apercu",
            f"Supprimer l'apercu (image et turntable) de « {path.name} » ?\n\n"
            "Le fichier lui-meme n'est pas touche.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        delete_preview_cache(path)
        reload_browser = getattr(self.window(), "reload", None)
        if reload_browser is not None:
            reload_browser()

    def _set_preview_controls_visible(self, visible: bool):
        """Affiche/masque la ligne des boutons du tableau ; masquee, elle sort aussi des lignes du
        tableau (le style commun arrondit alors le bas de la ligne des valeurs)."""
        row = getattr(self, "_controls_row", None)
        if row is None:
            return
        meta = self.preview_info_table._flat_rows
        entry = self._controls_row_meta
        if visible and entry not in meta:
            meta.append(entry)
        elif not visible and entry in meta:
            meta.remove(entry)
        row.setVisible(visible)
        self._restyle_info_table()

    def _request_lightroom_preview(self):
        if not self._current_path:
            return
        import lightroom_bridge
        self.lightroom_preview_button.setEnabled(False)
        self.lightroom_preview_button.setText("Demande envoyée…")
        lightroom_bridge.create_preview(Path(self._current_path))
        QTimer.singleShot(25000, self._restore_lightroom_preview_button)

    def _restore_lightroom_preview_button(self):
        self.lightroom_preview_button.setText("Créer l’aperçu Lightroom")
        self.lightroom_preview_button.setEnabled(True)

    def _reflow_preview_controls(self, wide: bool):
        """Range les boutons sur UNE ligne (panneau large) ou sur plusieurs
        (panneau etroit)."""
        if getattr(self, "_preview_controls_wide", None) == wide:
            return
        self._preview_controls_wide = wide
        layout = self._preview_controls_layout
        for item in self._preview_controls_items:
            layout.removeWidget(item)
        media, lr_preview, low_i, high_i, low_t, high_t, protection, badge, meta_badges = self._preview_controls_items
        if wide:
            for column, item in enumerate(self._preview_controls_items):
                layout.addWidget(item, 0, column)
            layout.setColumnStretch(len(self._preview_controls_items), 1)
        else:
            layout.setColumnStretch(len(self._preview_controls_items), 0)
            layout.addWidget(media, 0, 0, 1, 2)
            layout.addWidget(lr_preview, 0, 2, 1, 2)
            layout.addWidget(badge, 0, 4)
            layout.addWidget(meta_badges, 0, 5, 1, 2)
            layout.addWidget(low_i, 1, 0)
            layout.addWidget(high_i, 1, 1)
            layout.addWidget(low_t, 2, 0)
            layout.addWidget(high_t, 2, 1)
            layout.addWidget(protection, 3, 0, 1, 6)

    def _show_preview_context_menu(self, global_pos):
        """Menu clic droit de l'apercu (image, turntable ou video) du fichier
        affiche dans l'inspecteur."""
        path_text = getattr(self, "_current_path", None)
        if not path_text:
            return
        path = Path(path_text)
        menu = Menu(self)
        menu.setFont(font(11, 400))
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        menu.addSeparator()
        act_copy_file = menu.addAction("Copier l'apercu")
        act_copy_path = menu.addAction("Copier le chemin de l'apercu")
        menu.addSeparator()
        act_delete = menu.addAction("Supprimer l'apercu...")
        chosen = menu.exec(global_pos)
        if chosen is act_delete:
            self._delete_preview(path)
        elif chosen is act_reveal:
            reveal_in_file_manager(self._preview_image_path(path))
        elif chosen is act_copy_file:
            image_path = self._preview_image_path(path)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(image_path))])
            image = QImage(str(image_path)) if image_path.suffix.lower() in IMAGE_EXTENSIONS else QImage()
            if not image.isNull():
                mime.setImageData(image)
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(self._preview_image_path(path)))

    def _preview_image_path(self, path: Path) -> Path:
        """Chemin du fichier IMAGE affiche : image du cache d'un modele 3D (ou
        image courante de son turntable) ; sinon le fichier lui-meme (image,
        video...)."""
        if path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS:
            return path
        if self._selected_preview_media() == "turntable":
            if self._turntable_frame_paths:
                index = max(0, min(len(self._turntable_frame_paths) - 1, self._turntable_frame_index))
                return Path(self._turntable_frame_paths[index])
            return path
        try:
            mode = self._preview_render_modes.get((self._current_path, "image"), "low")
            mtime = path.stat().st_mtime
            current = _file_image_cache_path(path, mtime, render_mode=mode)
            if current.is_file():
                return current
            return _find_stale_preview_cache(path, mtime, current) or path
        except OSError:
            return path

    def _stop_video(self):
        """Coupe la lecture en cours et cache le lecteur : appele avant
        toute selection (voir show_path/clear), pas seulement pour un
        fichier non-video — quitter la selection d'une video ne doit
        jamais la laisser jouer en arriere-plan, invisible."""
        if self._video_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._video_player.stop()
        self._video_player.setSource(QUrl())
        self.video_widget.hide()

    @staticmethod
    def _well_qss() -> str:
        """Cadre de l'apercu : fond, filet et coins arrondis (3 px), sur lui seul (selecteur par nom)."""
        return f"#PreviewWell {{ background: {C['well']}; border: 1px solid #282c30; border-radius: 3px; }}"
