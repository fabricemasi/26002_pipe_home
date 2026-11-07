"""Branchement du module PDF (fm_pdf) : bouton « PDF » de la barre (dégrisé sur un .pdf), double-clic sur un .pdf
d'une colonne (réglage `pdf_open_double_click`), menu « Ouvrir dans l'éditeur PDF », ouverture plein cadre
(colonnes masquées), cadre « PDF » de la barre de navigation (enregistrer, annuler, rétablir, imprimer, réglages,
fermer), fermeture prudente (document modifié : enregistrer / ne pas enregistrer / annuler), autre module qui le
ferme. Carte du module : docs/agents/fm_pdf.md ; de la fenêtre : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import Qt

import ui_state
from app_style import C, role_color, scaled
from settings_store import load_settings


def pdf_target(path, is_dir: bool) -> bool:
    import fm_pdf
    return not is_dir and path is not None and fm_pdf.is_pdf_file(path)


class PdfModuleMixin:
    """Méthodes de PipelineBrowser : éditeur PDF (fm_pdf) recouvrant les colonnes."""

    def _install_pdf_hooks(self):
        import fm_pdf.pane as pdf_pane
        pdf_pane.HOOKS.update({
            "settings": lambda: ui_state.APPLIED_SETTINGS or load_settings(),
            "status": self.path_label.setText,
            "open_settings": lambda: self.open_module_settings("pdf"),
            "navbar_frame": True,
            "fullscreen": self._pdf_fullscreen,
        })

    def _pdf_claims(self, path) -> bool:
        """Double-clic sur un .pdf : l'éditeur PDF (sinon : visionneuse / logiciel, comme avant)."""
        return pdf_target(Path(path), False) and bool((ui_state.APPLIED_SETTINGS or {}).get("pdf_open_double_click",
                                                                                               True))

    def _toggle_pdf(self):
        pane = getattr(self, "_pdf", None)
        if pane is not None:
            if pane.confirm_leave():
                self._close_pdf()
            return
        self._open_selected_in(("pdf",))

    def _open_pdf(self, path=None) -> bool:
        """L'éditeur recouvre les colonnes (modes exclusifs : éditeur, board, vidéo, typographie, visionneuse)."""
        if self._project_columns_hidden:
            self._set_columns_hidden(False, animate=False)
        if not self._close_md_editor():
            return False
        if self._board is not None and not self._close_board():
            return False
        if not self._leave_font():
            return False
        leave_agenda = getattr(self, "_leave_agenda", None)    # agenda ouvert : rangé d'abord (fm_agenda)
        if leave_agenda is not None:
            leave_agenda()
        self._close_video()
        self._install_pdf_hooks()
        pane = getattr(self, "_pdf", None)
        if pane is not None and path is not None and pane.session.path == Path(path):
            pane.raise_()
            return True
        if pane is not None and not pane.confirm_leave():
            return False
        if pane is None:
            from fm_pdf.pane import PdfPane
            pane = PdfPane(self.scroll.viewport())
            pane.closeRequested.connect(self._close_pdf)
            pane.stateChanged.connect(self._layout_pdf_buttons)
            self._pdf = pane
        if path is not None:
            pane.open_path(path)
        pane.show()
        pane.raise_()
        pane.view.setFocus()
        self._layout_pdf_buttons()
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._pdf_hid_columns = True
        self._sync_collapse_button()
        if path is not None:
            self.path_label.setText(str(path))
        return True

    def _leave_pdf(self) -> bool:
        """Un autre mode s'ouvre : l'éditeur PDF se ferme d'abord (document modifié : enregistrer / ne pas
        enregistrer / annuler). False = annulé."""
        pane = getattr(self, "_pdf", None)
        if pane is None:
            return True
        if not pane.confirm_leave():
            return False
        self._close_pdf()
        return True

    def _close_pdf(self):
        pane = getattr(self, "_pdf", None)
        if pane is None:
            return
        self._pdf = None
        self.titlebar.pdf_group().hide()
        if getattr(self, "_pdf_hid_columns", False):
            self._pdf_hid_columns = False
            host = self.scroll.widget()
            if host is not None and not getattr(self, "_columns_user_hidden", False):
                host.show()
        pane.shutdown()
        pane.hide()
        pane.deleteLater()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()

    def _pdf_fullscreen(self, on=None):
        on = not self.isFullScreen() if on is None else on
        self.showFullScreen() if on else self.showNormal()

    def _layout_pdf_buttons(self):
        """Cadre « PDF » de la barre : annuler, rétablir, enregistrer (accent si modifié), imprimer, réglages,
        fermer. Rappelé seulement quand annuler / rétablir / « modifié » changent (`PdfPane.stateChanged`)."""
        from preview_column import IconButton, style_focus_button
        pane = getattr(self, "_pdf", None)
        group = self.titlebar.pdf_group()
        if pane is None:
            group.hide()
            return
        buttons = self.__dict__.setdefault("_pdf_buttons", [])
        if not buttons:
            for kind, tip, slot in (
                    ("undo", "Annuler (Ctrl+Z)", lambda: self._pdf and self._pdf.undo()),
                    ("redo", "Rétablir (Ctrl+Y)", lambda: self._pdf and self._pdf.redo()),
                    ("save", "Enregistrer (Ctrl+S)", lambda: self._pdf and self._pdf.save()),
                    ("print", "Imprimer (Ctrl+P)", lambda: self._pdf and self._pdf.print_dialog()),
                    ("gear", "Réglages du module PDF", lambda: self.open_module_settings("pdf")),
                    ("close", "Fermer l'éditeur PDF", lambda: self._pdf and self._pdf.request_close())):
                button = IconButton(kind if kind != "print" else "export", role_color("buttons", "#c4cacf"),
                                    C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._pdf_kind = kind
                buttons.append(button)
        session = pane.session
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in buttons:
            style_focus_button(button)
            kind = button._pdf_kind
            if kind == "undo":
                self._set_button_usable(button, session.can_undo())
                button.setToolTip("Annuler : %s (Ctrl+Z)" % session.undo_label() if session.can_undo() else "Annuler")
            elif kind == "redo":
                self._set_button_usable(button, session.can_redo())
                button.setToolTip("Rétablir : %s (Ctrl+Y)" % session.redo_label() if session.can_redo()
                                  else "Rétablir")
            elif kind == "save":
                button.set_alert(self._mode_on_color() if session.dirty else None)
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()
