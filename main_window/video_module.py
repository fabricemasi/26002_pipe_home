"""Branchement du module vidéo (fm_video) : cadre « Vidéo », ouverture, hooks, réglages.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import threading
from pathlib import Path

from PySide6.QtCore import Qt

from app_style import C, resolve_color_ref, role_color, scaled
from settings_store import load_settings, save_live_state, save_settings
from settings_widgets import Menu
from browser_core import _resolve_font_family
from preview_column import IconButton, style_focus_button
import ui_state


class VideoModuleMixin:
    """Méthodes de PipelineBrowser : branchement du module vidéo (fm_video) : cadre « Vidéo », ouverture, hooks, réglages."""

    # -- Module video (paquet fm_video/) --

    def _preload_video(self):
        """Bibliotheques lourdes du module video (PyOpenGL ~1,2 s, PyAV, OpenImageIO, OpenColorIO + configuration
        ACES integree) importees dans un fil de fond : la 1re ouverture du module ne les attend plus."""
        import threading
        import fm_video as video
        threading.Thread(target=video.preload, name="video-preload", daemon=True).start()

    def _video_claims(self, path) -> bool:
        """Le double-clic va-t-il au module video ? Videos (reglage « Double-clic sur une video ») ; images EXR /
        TIFF / DPX numerotees d'une sequence (reglage « … sa sequence »)."""
        import fm_video as video
        settings = ui_state.APPLIED_SETTINGS or {}
        path = Path(path)
        if not path.is_file():
            return False
        if video.is_video_file(path):
            return bool(settings.get("video_open_videos", True))
        if path.suffix.lower() in video.PRO_IMAGE_EXTENSIONS and settings.get("video_open_sequences", True):
            from fm_video.media import find_sequence
            return find_sequence(path) is not None
        return False

    def _install_video_hooks(self):
        import fm_video.pane as video_pane
        from app_style import resolve_color_ref
        from browser_core import _resolve_font_family
        video_pane.HOOKS.update({
            "settings": lambda: ui_state.APPLIED_SETTINGS or load_settings(),
            "save_state": self._save_video_state,
            "write_setting": self._write_video_setting,
            "resolve_color": resolve_color_ref,
            "resolve_font": lambda family: _resolve_font_family(family, 12),
            "status": self.path_label.setText,
        })

    def _write_video_setting(self, key: str, value):
        """Valeur vidéo choisie dans le module : fichier, preset et réglages ouverts."""
        settings = load_settings()
        settings[key] = value
        save_settings(settings)
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.__setitem__(key, value))
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        dialog = getattr(self, '_settings_dialog_v2', None)
        if dialog is not None:
            try:
                dialog.external_values({key: value})
            except RuntimeError:
                pass

    def _save_video_state(self, key: str, value):
        """Etat temps reel du module (corrections, presets, derniers parametres d'export, I, boucle, volume) :
        enregistre aussitot, et suivi par les reglages appliques."""
        from settings_store import save_live_state
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        save_live_state(key, value)

    def _toggle_video(self):
        if self._video is not None:
            self._close_video()
            return
        import fm_video as video
        _column, path = self._selected_path()
        if path is not None and path.is_file() and video.is_media_file(path):
            self._open_video(path)

    def _open_video(self, path: Path) -> bool:
        """Le module video recouvre les colonnes ; ses boutons dans le cadre « Vidéo » de la barre de navigation.
        Modes exclusifs (editeur, board, visionneuse)."""
        if self._project_columns_hidden:
            return False
        if not self._close_md_editor():
            return False
        if self._board is not None and not self._close_board():
            return False
        self._install_video_hooks()
        if self._video is None:
            from fm_video.pane import VideoPane
            pane = VideoPane(self.scroll.viewport(), ui_state.APPLIED_SETTINGS or {})
            pane.closeRequested.connect(self._close_video)
            pane.stateChanged.connect(self._layout_video_buttons)
            self._video = pane
        pane = self._video
        if not pane.open(path):
            if pane.source is None:
                pane.shutdown()
                pane.deleteLater()
                self._video = None
            return False
        pane.fade_in()
        # Colonnes VRAIMENT masquees sous le module : sinon Qt les repeignait a chaque image de la lecture
        # (composition OpenGL : ~20 ms par image, lecture 1080p saccadee). Remontrees a la fermeture.
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._video_hid_columns = True
        self._layout_video_buttons()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        self.path_label.setText(str(path))
        return True

    def _close_video(self):
        """Retour aux colonnes : lecture et fils de fond arretes, memoire du cache rendue."""
        pane = self._video
        if pane is None:
            return
        self._video = None
        self.titlebar.video_group().hide()
        if getattr(self, "_video_hid_columns", False):
            self._video_hid_columns = False
            host = self.scroll.widget()
            if host is not None:
                host.show()
        pane.shutdown()
        pane.hide()
        pane.deleteLater()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()

    def _video_menu(self, button):
        """Bouton « Corrections » : fenetres de corrections, presets de corrections, reinitialiser."""
        from settings_menu import Menu
        pane = self._video
        if pane is None:
            return
        menu = Menu(self)
        menu.addAction("Corrections colorimétriques et LUT…").triggered.connect(
            lambda: pane.open_grade_window("grade_main"))
        menu.addAction("Corrections par canal et niveaux…").triggered.connect(
            lambda: pane.open_grade_window("grade_channels"))
        menu.addSeparator()
        presets = pane.grade_presets()
        load = menu.addMenu("Charger un preset de corrections")
        load.setEnabled(bool(presets))
        for name in sorted(presets):
            load.addAction(name).triggered.connect(lambda _c=False, n=name: pane.load_grade_preset(n))
        menu.addAction("Enregistrer les corrections comme preset…").triggered.connect(
            lambda: self._ask_video_preset(pane))
        menu.addAction("Réinitialiser les corrections").triggered.connect(pane.reset_grade)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _ask_video_preset(self, pane):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Preset de corrections", "Nom du preset :")
        if ok and name.strip():
            pane.save_grade_preset(name.strip())

    def _layout_video_buttons(self):
        """Boutons du cadre « Vidéo » : corrections, exporter, informations, plein ecran, fermer."""
        pane = self._video
        group = self.titlebar.video_group()
        if pane is None:
            group.hide()
            return
        if not self._video_buttons:
            for kind, tip, slot in (
                    ("grade", "Corrections colorimétriques, LUT, presets", None),
                    ("export", "Exporter (sélection IN / OUT ou média complet)…",
                     lambda: self._video and self._video.open_export_window()),
                    ("info", "Informations en surimpression (I)", lambda: self._video and self._video.toggle_info()),
                    ("fullscreen", "Plein écran (F, Échap pour sortir)",
                     lambda: self._video and self._video.toggle_fullscreen()),
                    ("close", "Fermer le module vidéo (Échap)", self._close_video)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                if slot is None:
                    button.clicked.connect(lambda _c=False, b=button: self._video_menu(b))
                else:
                    button.clicked.connect(slot)
                button._video_kind = kind
                self._video_buttons.append(button)
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in self._video_buttons:
            style_focus_button(button)
            if button._video_kind == "info":
                button.set_alert(self._mode_on_color() if pane.info_visible() else None)
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()
