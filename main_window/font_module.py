"""Branchement du module typographique (fm_font) : ouverture plein cadre par le bouton « Typographie » de la barre
ou le menu d'une ligne « Ouvrir dans le module typographique » (source .ufo / .designspace, police .ttf / .otf /
.woff / .woff2 ; JAMAIS au double-clic, demande de l'utilisateur), menu « Créer un projet typographique » d'une
colonne, hooks, réglages. Carte du module : docs/agents/fm_font.md ; de la fenêtre : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import Qt

import ui_state
from app_style import C, role_color, scaled
from settings_store import load_settings


def font_target(path, is_dir: bool) -> bool:
    """Le module sait-il ouvrir `path` ? Source ou police (un .ufo est un DOSSIER, le reste des fichiers) ; `is_dir`
    vient de la lecture du dossier (aucun accès disque)."""
    import fm_font
    return fm_font.is_font_file(path) and is_dir == (Path(path).suffix.lower() == ".ufo")


class FontModuleMixin:
    """Méthodes de PipelineBrowser : module typographique (fm_font) recouvrant les colonnes."""

    def _install_font_hooks(self):
        import fm_font.pane as font_pane
        font_pane.HOOKS.update({
            "settings": lambda: ui_state.APPLIED_SETTINGS or load_settings(),
            "status": self.path_label.setText,
            "open_settings": lambda: self.open_module_settings("font"),
            "navbar_frame": True,
        })

    def _toggle_font(self):
        """Bouton « Typographie » de la barre : module ouvert = retour aux colonnes (projet modifié : enregistrer /
        fermer sans enregistrer / annuler) ; sinon il s'ouvre sur la source ou la police sélectionnée (colonnes ou
        visionneuse)."""
        pane = getattr(self, "_font", None)
        if pane is not None:
            if pane.confirm_leave():
                self._close_font()
            return
        self._open_selected_in(("font",))

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
            pane.stateChanged.connect(self._layout_font_buttons)
            pane.pageChanged.connect(lambda _page: self._layout_font_buttons())
            self._font = pane
        if path is not None and not pane.open_path(path):
            if pane.project.path is None and not pane.project.is_dirty():
                self._close_font()
            return False
        pane.show()
        pane.raise_()
        self._layout_font_buttons()
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
        self.titlebar.font_group().hide()
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

    def _layout_font_buttons(self):
        """Boutons du cadre « Typographie » de la barre (comme « Vidéo » / « Board ») : planche / lettre (comme
        le bouton planche de la visionneuse), annuler, rétablir, enregistrer (accent si modifié), exporter, réglages
        du module, fermer. Rappelé seulement quand annuler / rétablir / « modifié » ou la page changent
        (`FontPane.stateChanged`, `pageChanged`), jamais à chaque geste."""
        from preview_column import IconButton, style_focus_button
        pane = getattr(self, "_font", None)
        group = self.titlebar.font_group()
        if pane is None:
            group.hide()
            return
        buttons = self.__dict__.setdefault("_font_buttons", [])
        if not buttons:
            for kind, tip, slot in (
                    ("gallery", "Planche des glyphes", self._toggle_font_gallery),
                    ("undo", "Annuler (Ctrl+Z)", lambda: self._font and self._font.project.undo.undo()),
                    ("redo", "Rétablir (Ctrl+Y)", lambda: self._font and self._font.project.undo.redo()),
                    ("save", "Enregistrer la source (Ctrl+S)", lambda: self._font and self._font.save()),
                    ("export", "Exporter une police (OTF, TTF, WOFF, WOFF2, variable)…", None),
                    ("gear", "Réglages du module typographique", lambda: self.open_module_settings("font")),
                    ("close", "Fermer le module typographique (Échap depuis la grille)",
                     lambda: self._font and self._font.request_close())):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                if slot is None:
                    button.clicked.connect(lambda _c=False, b=button: self._font and self._font.export_menu(b))
                else:
                    button.clicked.connect(slot)
                button._font_kind = kind
                buttons.append(button)
        undo = pane.project.undo
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in buttons:
            style_focus_button(button)
            kind = button._font_kind
            if kind == "gallery":
                on_grid = pane.current_page() == "Glyphes"
                button.set_kind("single_image" if on_grid else "gallery")
                button.setToolTip("Ouvrir la lettre choisie (Ctrl+2)" if on_grid
                                  else "Revenir à la planche des glyphes (Échap, Ctrl+1)")
            elif kind == "undo":
                self._set_button_usable(button, undo.can_undo())
                button.setToolTip(f"Annuler : {undo.undo_label()} (Ctrl+Z)" if undo.can_undo() else "Annuler")
            elif kind == "redo":
                self._set_button_usable(button, undo.can_redo())
                button.setToolTip(f"Rétablir : {undo.redo_label()} (Ctrl+Y)" if undo.can_redo() else "Rétablir")
            elif kind == "save":
                button.set_alert(self._mode_on_color() if pane.project.is_dirty() else None)
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()

    def _toggle_font_gallery(self):
        """Bouton planche du cadre « Typographie » : lettre ouverte = retour à la planche des glyphes ; planche
        montrée = la lettre choisie (ou la première)."""
        pane = getattr(self, "_font", None)
        if pane is not None:
            pane.show_page("Éditeur" if pane.current_page() == "Glyphes" else "Glyphes")
