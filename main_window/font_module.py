"""Branchement du module typographique (fm_font) : ouverture plein cadre (double-clic sur une source .ufo /
.designspace ou une police .ttf / .otf / .woff / .woff2, menu « Créer un projet typographique » d'une colonne),
hooks, réglages. Carte du module : docs/agents/fm_font.md ; de la fenêtre : docs/agents/fm_browser.md."""
from pathlib import Path

import ui_state
from settings_store import load_settings


class FontModuleMixin:
    """Méthodes de PipelineBrowser : module typographique (fm_font) recouvrant les colonnes."""

    def _font_claims(self, path) -> bool:
        """Le double-clic va-t-il au module ? Source (un .ufo est un DOSSIER) ou police compilée, réglage
        « Double-clic sur une source… » (Réglages : Typographie)."""
        import fm_font
        path = Path(path)
        if not fm_font.is_font_file(path):
            return False
        if not (ui_state.APPLIED_SETTINGS or {}).get("typo_open_double_click", True):
            return False
        return path.is_dir() if path.suffix.lower() == ".ufo" else path.is_file()

    def _install_font_hooks(self):
        import fm_font.pane as font_pane
        font_pane.HOOKS.update({
            "settings": lambda: ui_state.APPLIED_SETTINGS or load_settings(),
            "status": self.path_label.setText,
            "open_settings": lambda: self.open_module_settings("font"),
        })

    def _toggle_font(self):
        """Bouton « Typographie » de la barre : module ouvert = retour aux colonnes (projet modifié : enregistrer /
        fermer sans enregistrer / annuler) ; sinon il s'ouvre sur la source ou la police sélectionnée."""
        pane = getattr(self, "_font", None)
        if pane is not None:
            if pane.confirm_leave():
                self._close_font()
            return
        import fm_font
        _column, path = self._selected_path()
        if path is not None and fm_font.is_font_file(path):
            self._open_font(path)

    def _open_font(self, path=None) -> bool:
        """Le module recouvre les colonnes (modes exclusifs : éditeur, board, vidéo, visionneuse). `path` : source
        ou police à ouvrir (une police compilée est IMPORTÉE, jamais réécrite) ; None = projet vierge."""
        if self._project_columns_hidden:
            return False
        if not self._close_md_editor():
            return False
        if self._board is not None and not self._close_board():
            return False
        self._close_video()
        self._install_font_hooks()
        pane = getattr(self, "_font", None)
        if pane is not None and path is not None and pane.project.path == Path(path):
            pane.raise_()
            return True
        if pane is not None and not pane.confirm_leave():
            return False
        if pane is None:
            from fm_font.pane import FontPane
            pane = FontPane(self.scroll.viewport())
            pane.closeRequested.connect(self._close_font)
            self._font = pane
        if path is not None and not pane.open_path(path):
            if pane.project.path is None and not pane.project.is_dirty():
                self._close_font()
            return False
        pane.show()
        pane.raise_()
        # Colonnes VRAIMENT masquées sous le module (comme la vidéo) : rien ne les repeint pendant l'édition.
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._font_hid_columns = True
        self._sync_collapse_button()
        if path is not None:
            self.path_label.setText(str(path))
        return True

    def _leave_font(self) -> bool:
        """Un autre mode s'ouvre (éditeur, board, vidéo) : le module typographique se ferme d'abord (projet
        modifié : enregistrer / fermer sans enregistrer / annuler). False = annulé."""
        pane = getattr(self, "_font", None)
        if pane is None:
            return True
        if not pane.confirm_leave():
            return False
        self._close_font()
        return True

    def _close_font(self):
        """Retour aux colonnes (l'état « modifié » a été traité par `FontPane.request_close`)."""
        pane = getattr(self, "_font", None)
        if pane is None:
            return
        self._font = None
        if getattr(self, "_font_hid_columns", False):
            self._font_hid_columns = False
            host = self.scroll.widget()
            if host is not None:
                host.show()
        pane.shutdown()
        pane.hide()
        pane.deleteLater()
        self._sync_collapse_button()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()
