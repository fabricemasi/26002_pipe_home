"""Branchement du module Markdown (fm_markdown) : cadre « Éditeur », ouverture, synchro CSS, hooks.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from app_style import C, resolve_color_ref, role_color, scaled
from settings_store import load_settings, save_live_state, save_settings
from browser_core import _resolve_font_family
from preview_column import IconButton, style_focus_button
import ui_state


class MdModuleMixin:
    """Méthodes de PipelineBrowser : branchement du module Markdown (fm_markdown) : cadre « Éditeur », ouverture, synchro CSS, hooks."""

    # -- Module Markdown / code (paquet mdeditor/) --

    def _set_md_margin(self, value):
        settings = ui_state.APPLIED_SETTINGS if isinstance(ui_state.APPLIED_SETTINGS, dict) else {}
        settings["md_module_padding"] = value
        import fm_markdown.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is not None:
            pane._apply_module_padding(settings)
        self._md_margin_timer.start()

    def _persist_md_margin(self):
        value = self.md_margin_slider.value()
        save_live_state("md_module_padding", value)
        import browser_core
        browser_core._sync_default_preset_override(ui_state.APPLIED_SETTINGS or {},
                                                   lambda preset: preset.update(md_module_padding=value))
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values({"md_module_padding": value})
        except RuntimeError:
            pass

    def _md_pane(self):
        """Le module (instance unique, prechargee) : branche une fois sur la barre et les reglages."""
        import fm_markdown.pane as md_pane
        import fm_markdown.style as md_style
        from browser_core import _resolve_font_family
        md_style.FONT_RESOLVER = _resolve_font_family
        md_pane.HOOKS["settings"] = lambda: ui_state.APPLIED_SETTINGS or {}
        md_pane.HOOKS["save_state"] = self._save_md_state
        import fm_markdown.css_sync as css_sync                 # module ouvert avant le demarrage de la synchro
        css_sync.HOOKS["external"] = self._apply_md_external
        pane = md_pane.instance(create=True)
        if not getattr(pane, "_pb_connected", False):
            pane._pb_connected = True
            pane.stateChanged.connect(self._layout_md_buttons)
            pane.pathChanged.connect(lambda path: self.path_label.setText(path))
            pane.closeRequested.connect(self._close_md_editor)
        return pane

    def _save_md_state(self, key: str, value):
        """Etat temps reel du module (dernier mode, taille du texte des fichiers de code) : fichier de reglages."""
        from settings_store import save_live_state
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        save_live_state(key, value)

    def _start_css_sync(self):
        """Feuille CSS partagee avec Obsidian (Reglages > Markdown > CSS) : lue une fois au demarrage — ses valeurs
        (peut-etre modifiees dans Obsidian pendant que l'appli etait fermee) sont reprises dans les reglages —, puis
        suivie sur le disque (fm_markdown/css_sync.py)."""
        import fm_markdown.css_sync as css_sync
        import fm_markdown.style as md_style
        from browser_core import _resolve_font_family
        md_style.FONT_RESOLVER = _resolve_font_family         # polices « de l'appli » comparees sous leur vrai nom
        css_sync.HOOKS["external"] = self._apply_md_external
        css_sync.engine().update(ui_state.APPLIED_SETTINGS or load_settings())

    def _apply_md_external(self, values: dict):
        """Reglages Markdown repris de la feuille partagee (modifiee dans Obsidian ou un editeur) : appliques au
        module et a l'inspecteur, enregistres (fichier + preset actif), montres par la fenetre de reglages ouverte
        — sinon une valeur perimee y resterait et ecraserait la modification a l'enregistrement suivant."""
        if not values:
            return
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS.update(values)
        settings = load_settings()
        settings.update(values)
        save_settings(settings)
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.update(values))
        dialog = getattr(self, "_settings_dialog_v2", None)
        if dialog is not None:
            try:
                dialog.external_values(values)
            except RuntimeError:
                pass
        import fm_markdown.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is not None:
            pane.apply_settings(ui_state.APPLIED_SETTINGS or settings, set(values))
        timer = getattr(self, "_md_inspector_timer", None)
        if timer is not None:
            timer.start()
        else:
            self.detail.refresh_markdown_style()

    def _preload_md_editor(self):
        """Module prepare en fond (page, CodeMirror et feuille charges) : l'ouvrir est ensuite immediat."""
        if not (ui_state.APPLIED_SETTINGS or {}).get("md_preload", True):
            return
        if QApplication.mouseButtons() != Qt.NoButton or self._heavy_foreground_work():
            QTimer.singleShot(1500, self._preload_md_editor)       # souris enfoncee / lecture video : plus tard
            return
        try:
            self._md_pane()
        except ImportError:
            pass

    def _md_opens_on_double_click(self, path: Path) -> bool:
        """Double-clic : extensions de Markdown > Ouverture ; une note .md va a l'application Obsidian si le
        reglage le demande."""
        import fm_markdown.pane as md_pane
        settings = ui_state.APPLIED_SETTINGS or {}
        if path.suffix.lower() == ".md" and settings.get("md_open_md") == "obsidian":
            return False
        return md_pane.opens_on_double_click(path, settings)

    def _toggle_md_editor(self):
        if getattr(self, "_md_open", False):
            self._close_md_editor()
            return
        import fm_markdown as mdeditor
        _column, path = self._selected_path()
        if path is not None and path.is_file() and mdeditor.is_text_file(path):
            self._open_md_editor(path)

    def _open_md_editor(self, path: Path) -> bool:
        """Le fichier recouvre les colonnes ; ses boutons dans le cadre « Éditeur » de la barre de navigation."""
        if self._project_columns_hidden:
            return False
        if self._board is not None and not self._close_board():
            return False
        self._close_video()
        try:
            pane = self._md_pane()
        except ImportError:
            return False
        reason = pane.can_open(Path(path))
        if reason is not None:
            self.path_label.setText(reason)
            return False
        pane.attach(self.scroll.viewport())
        pane.open(Path(path))
        if not getattr(self, "_md_open", False):
            self._md_open = True
            self.status_right.hide()
            self.md_margin_slider.show()
            self.titlebar.refresh_look()
            pane.fade_in()
        else:
            pane.raise_()
        self._layout_md_buttons()
        self._sync_collapse_button()
        self.path_label.setText(str(path))
        return True

    def _close_md_editor(self) -> bool:
        """Retour aux colonnes (tout est enregistre ; un conflit demande a l'utilisateur). False = annule. La page
        reste chargee (cachee) : la rouvrir est immediat."""
        if not getattr(self, "_md_open", False):
            return True
        import fm_markdown.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is not None and not pane.confirm_leave():
            return False
        self._md_open = False
        self.md_margin_slider.hide()
        self.status_right.show()
        self.titlebar.refresh_look()
        self.titlebar.editor_group().hide()
        if pane is not None:
            pane.fade_out()
        self._sync_collapse_button()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()
        return True

    def _layout_md_buttons(self):
        """Cadre « Éditeur » de la barre : precedent, suivant, lecture / edition, rechercher, enregistrer, ouvrir dans
        l'application Obsidian (note d'un coffre), fermer."""
        group = self.titlebar.editor_group()
        if not getattr(self, "_md_open", False):
            group.hide()
            return
        import fm_markdown.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is None:
            group.hide()
            return
        self.titlebar.refresh_look()       # le trait partagé suit le mode lecture/édition et le type de fichier
        if not self._editor_buttons:
            current = lambda: md_pane.instance(create=False)          # noqa: E731
            for kind, tip, slot in (
                    ("nav_back", "Précédent (Alt+←)", lambda: current() and current().go(-1)),
                    ("nav_forward", "Suivant (Alt+→)", lambda: current() and current().go(1)),
                    ("reading", "Lecture / édition (Ctrl+E)", lambda: current() and current().toggle_mode()),
                    ("find", "Rechercher (Ctrl+F)", lambda: current() and current().find()),
                    ("save", "Enregistrer (Ctrl+S)", lambda: current() and current().flush()),
                    ("external", "Ouvrir dans l'application Obsidian",
                     lambda: current() and current().open_in_obsidian()),
                    ("close", "Fermer l'éditeur (Échap)", self._close_md_editor)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._editor_kind = kind
                self._editor_buttons.append(button)
        from fm_markdown import preview as markdown_preview
        on = self._mode_on_color()
        if pane.path != getattr(self, "_md_vault_path", None):        # une fois par fichier (lecture du disque)
            self._md_vault_path = pane.path
            self._md_in_vault = pane.path is not None and pane.kind == "markdown" and \
                markdown_preview.vault_containing(pane.path) is not None
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in self._editor_buttons:
            kind = button._editor_kind
            visible = not (kind == "external" and not self._md_in_vault) and \
                not (kind == "reading" and pane.kind != "markdown")
            button.setVisible(visible)
            if not visible:
                continue
            style_focus_button(button)
            if kind == "nav_back":
                self._set_button_usable(button, pane.can_back)
            elif kind == "nav_forward":
                self._set_button_usable(button, pane.can_forward)
            elif kind == "reading":
                button.set_alert(on if pane.mode == "reading" else None)
            elif kind == "save":
                button.set_alert(resolve_color_ref("#c62828") if pane.is_dirty() else None)
            button.move(x, origin.y())
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()
