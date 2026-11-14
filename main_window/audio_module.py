"""Branchement de FM Audio (fm_audio) et FM Music (fm_music) : menu « Ouvrir dans … », double-clic sur un son ou
un projet d'une colonne (réglages `audio_open_double_click`, `music_open_double_click`), ouverture plein cadre
(colonnes masquées), fermeture prudente (projet modifié), autre module qui les ferme. Une PRISE EN COURS n'est
jamais coupée par la navigation : le pane est seulement masqué, le moteur partagé continue d'écrire.
Désactivable : réglage `audio_enabled`. Carte : docs/agents/fm_audio.md."""
from pathlib import Path

from PySide6.QtCore import Qt

import ui_state
from app_style import C, role_color, scaled
from settings_store import load_settings


def _enabled() -> bool:
    return bool((ui_state.APPLIED_SETTINGS or {}).get("audio_enabled", True))


def audio_target(path, is_dir: bool) -> bool:
    if is_dir or path is None or not _enabled():
        return False
    import fm_audio
    return fm_audio.opens(path)


def music_target(path, is_dir: bool) -> bool:
    if is_dir or path is None or not _enabled():
        return False
    import fm_music
    return fm_music.opens(path)


class AudioModuleMixin:
    """Méthodes de PipelineBrowser : éditeurs FM Audio / FM Music recouvrant les colonnes."""

    def _sound_hooks(self, module: str) -> dict:
        from settings_store import save_live_state

        def save(key, value):
            save_live_state(key, value)
            if ui_state.APPLIED_SETTINGS is not None:
                ui_state.APPLIED_SETTINGS[key] = value
        return {
            "settings": lambda: ui_state.APPLIED_SETTINGS or load_settings(),
            "status": self.path_label.setText,
            "open_settings": lambda: self.open_module_settings(module),
            "save_live_state": save,
            "navbar_frame": True,                # outils du transport dans le cadre de la barre (_layout_sound_buttons)
        }

    def _sound_pane(self, kind: str):
        return getattr(self, "_audio_pane" if kind == "audio" else "_music_pane", None)

    def _sound_claims(self, path) -> bool:
        """Double-clic : un son ou un projet .fmaudio = FM Audio ; .fmmusic / .mid = FM Music."""
        settings = ui_state.APPLIED_SETTINGS or {}
        path = Path(path)
        if music_target(path, False) and settings.get("music_open_double_click", True):
            return self._open_music(path)
        if audio_target(path, False) and settings.get("audio_open_double_click", True):
            return self._open_audio(path)
        return False

    def _toggle_audio(self) -> None:
        self._toggle_sound("audio")

    def _toggle_music(self) -> None:
        self._toggle_sound("music")

    def _toggle_sound(self, kind: str) -> None:
        """Bouton de la barre : ouvert = rangé ; sinon s'ouvre sur le fichier choisi s'il est de son type
        (son / .fmaudio, .mid / .fmmusic), sinon sur le projet en cours ou un projet neuf."""
        pane = self._sound_pane(kind)
        if pane is not None and pane.isVisible():
            self._leave_sound(kind)
            self._sync_mode_buttons()
            return
        _column, path, is_dir = self._module_path()
        target = audio_target if kind == "audio" else music_target
        self._open_sound(kind, path if path is not None and target(path, is_dir) else None)

    def _open_audio(self, path=None) -> bool:
        return self._open_sound("audio", path)

    def _open_music(self, path=None) -> bool:
        return self._open_sound("music", path)

    def _open_sound(self, kind: str, path=None) -> bool:
        if not _enabled():
            self.path_label.setText("FM Audio / FM Music désactivés (réglage « audio_enabled »)")
            return False
        if self._project_columns_hidden:
            self._set_columns_hidden(False, animate=False)
        if not self._close_md_editor():
            return False
        if self._board is not None and not self._close_board():
            return False
        if not self._leave_font():
            return False
        for name in ("_leave_agenda", "_leave_taches"):
            fn = getattr(self, name, None)
            if fn is not None:
                fn()
        leave_pdf = getattr(self, "_leave_pdf", None)
        if leave_pdf is not None and not leave_pdf():
            return False
        self._close_video()
        other = "music" if kind == "audio" else "audio"
        if not self._leave_sound(other):
            return False
        pane = self._sound_pane(kind)
        if pane is None:
            if kind == "audio":
                import fm_audio.pane as mod
                cls = mod.AudioPane
            else:
                import fm_music.pane as mod
                cls = mod.MusicPane
            mod.HOOKS.update(self._sound_hooks("audio" if kind == "audio" else "music"))
            pane = cls(self.scroll.viewport(), hooks=mod.HOOKS)
            pane.closeRequested.connect(lambda k=kind: self._close_sound(k))
            pane.transportChanged.connect(self._layout_sound_buttons)
            setattr(self, "_audio_pane" if kind == "audio" else "_music_pane", pane)
        if path is not None and not pane.open_path(path):
            if not pane.isVisible():
                self._close_sound(kind)
            return False
        pane.setGeometry(self.scroll.viewport().rect())
        pane.show()
        pane.raise_()
        pane.view.setFocus()
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._sound_hid_columns = True
        self._sync_collapse_button()
        if path is not None:
            self.path_label.setText(str(path))
        self._layout_sound_buttons()
        self._sync_mode_buttons()
        return True

    def _leave_sound(self, kind: str) -> bool:
        pane = self._sound_pane(kind)
        if pane is None or not pane.isVisible():
            return True
        if pane.recording:                       # la prise continue : le pane est seulement masqué
            pane.hide()
            self._restore_columns_after_sound()
            self._layout_sound_buttons()
            return True
        if not pane.confirm_leave():
            return False
        self._close_sound(kind)
        return True

    def _leave_audio(self) -> bool:
        """Un autre mode s'ouvre : FM Audio et FM Music se rangent (projet modifié : enregistrer / ne pas
        enregistrer / annuler). False = annulé."""
        return self._leave_sound("audio") and self._leave_sound("music")

    def _restore_columns_after_sound(self) -> None:
        if getattr(self, "_sound_hid_columns", False):
            self._sound_hid_columns = False
            host = self.scroll.widget()
            if host is not None and not getattr(self, "_columns_user_hidden", False):
                host.show()
        self._sync_collapse_button()

    def _close_sound(self, kind: str) -> None:
        pane = self._sound_pane(kind)
        if pane is None:
            return
        if pane.recording:
            pane.hide()
            self._restore_columns_after_sound()
            self._layout_sound_buttons()
            return
        setattr(self, "_audio_pane" if kind == "audio" else "_music_pane", None)
        self._restore_columns_after_sound()
        pane.shutdown()
        pane.hide()
        pane.deleteLater()
        self._layout_sound_buttons()
        self._sync_mode_buttons()

    # Outils du cadre : (genre d'icône, infobulle, action sur le pane). Icônes : preview_column.NAV_LIBRARY_ICONS
    # (catalogue : modules/audio/*), aussi dans la liste ICÔNES des réglages.
    _SOUND_TOOLS = (
        ("undo", "Annuler (Ctrl+Z)", lambda p: p.project.history.undo()),
        ("redo", "Rétablir (Ctrl+Y)", lambda p: p.project.history.redo()),
        ("sound_play", "Lecture / arrêt (Espace)", lambda p: p.session.toggle_play()),
        ("sound_record", "Enregistrer les pistes armées (R dans l'en-tête de piste)", lambda p: p.toggle_record()),
        ("sound_loop", "Boucle (L ; Maj + glisser dans la règle pour la placer)", lambda p: p.toggle_loop()),
        ("sound_metronome", "Métronome", lambda p: p.flip_metronome()),
        ("sound_mixer", "Afficher / masquer le mixer", lambda p: p.toggle_mixer()),
        ("gear", None, lambda p: p.open_settings()),
        ("close", None, lambda p: p.request_close()),
    )

    def _layout_sound_buttons(self) -> None:
        """Cadres « FM Audio » / « FM Music » de la barre : annuler, rétablir, lecture, enregistrer, boucle,
        métronome, mixer, réglages, fermer. Outil actif (lecture, prise, boucle, métronome, mixer) : couleur de
        module ouvert, comme les boutons de mode. Appelé à l'ouverture, à la fermeture et aux changements d'état
        du transport seulement (quelques boutons)."""
        from preview_column import IconButton
        on = self._mode_on_color()
        for kind in ("audio", "music"):
            group = self.titlebar.audio_group() if kind == "audio" else self.titlebar.music_group()
            pane = self._sound_pane(kind)
            if pane is None or not pane.isVisible():
                group.hide()
                continue
            buttons = self.__dict__.setdefault(f"_{kind}_frame_buttons", [])
            if not buttons:
                title = "FM Audio" if kind == "audio" else "FM Music"
                for icon, tip, action in self._SOUND_TOOLS:
                    button = IconButton(icon, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                    button.setCursor(Qt.ArrowCursor)
                    button.setFlat(True)
                    button.setToolTip(tip or (f"Réglages de {title}" if icon == "gear" else f"Fermer {title}"))
                    button.clicked.connect(lambda _c=False, k=kind, a=action: self._sound_frame_action(k, a))
                    button._sound_kind = icon
                    buttons.append(button)
            st = pane.transport_state()
            active = {"sound_play": st["playing"], "sound_record": st["recording"], "sound_loop": st["loop"],
                      "sound_metronome": st["metronome"], "sound_mixer": st["mixer"]}
            origin = group.content_origin()
            x, height = origin.x(), 0
            for button in buttons:
                self.titlebar.style_group_button(button)
                icon = button._sound_kind
                if icon == "undo":
                    self._set_button_usable(button, st["can_undo"])
                elif icon == "redo":
                    self._set_button_usable(button, st["can_redo"])
                elif icon in active:
                    button.set_alert(on if active[icon] else None)
                button.move(x, origin.y())
                button.show()
                x += button.width() + scaled(6, 0)
                height = max(height, button.height())
            group.restyle()
            group.fit(x - scaled(6, 0), height)
            group.show()
            group.raise_()
        self.titlebar.place_viewer_group()

    def _sound_frame_action(self, kind: str, action) -> None:
        pane = self._sound_pane(kind)
        if pane is not None:
            action(pane)
            self._layout_sound_buttons()

    def _close_sound_panes_for_exit(self) -> bool:
        """Fermeture de l'application : projets modifiés confirmés, prises finalisées, moteur arrêté."""
        for kind in ("audio", "music"):
            pane = self._sound_pane(kind)
            if pane is None:
                continue
            if pane.recording:
                pane.session.stop_recording()
            if not pane.confirm_leave():
                return False
        for kind in ("audio", "music"):
            pane = self._sound_pane(kind)
            if pane is not None:
                setattr(self, "_audio_pane" if kind == "audio" else "_music_pane", None)
                pane.shutdown()
        try:
            from fm_audio_engine import client
            client.shutdown_shared()
        except Exception:
            pass
        return True
