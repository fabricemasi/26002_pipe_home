"""Branchement du board (fm_board / fm_cad) : cadre « Board », ouverture, dessins DXF / DWG.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from app_style import C, role_color, scaled
from previews import custom_ui_icon_pixmap
from preview_column import IconButton, style_focus_button
import ui_state


class _DrawingRelay(QObject):
    """Retour d'une lecture de dessin DXF / DWG faite dans un fil a part (signal en file d'attente)."""
    done = Signal(object, object, object)               # donnees du board, compte rendu, erreur


class BoardModuleMixin:
    """Méthodes de PipelineBrowser : branchement du board (fm_board / fm_cad) : cadre « Board », ouverture, dessins DXF / DWG."""

    # -- Mode « Board » (paquet board/, facon Miro) --

    @staticmethod
    def _board_icon(kind: str, size: int):
        """Icone perso d'un bouton du board (Reglages > Module MRO > Icones), sinon None (glyphe peint)."""
        from previews import custom_ui_icon_pixmap
        return custom_ui_icon_pixmap(f"ui_board_{kind}", size)

    def _toggle_board(self):
        if self._board is not None:
            self._close_board()
            return
        import fm_board as board
        _column, path = self._selected_path()
        if path is not None and path.is_file() and board.is_board_file(path):
            self._open_board(path)
        elif path is not None and path.is_file() and board.is_cad_drawing(path):
            self._open_cad_drawing(path)
        elif path is not None and path.is_file() and self._is_spreadsheet(path):
            self._open_spreadsheet(path)

    @staticmethod
    def _is_spreadsheet(path) -> bool:
        return path is not None and Path(path).suffix.lower() in (".xlsx", ".xlsm", ".csv", ".tsv")

    def _open_spreadsheet(self, path: Path):
        """Classeur Excel / CSV dans le module Tableur, en mode Standard (fm_tableur/files_mode.py) : lu HORS du fil
        de l'interface, ouvert en board en memoire ; le fichier n'est jamais reecrit sans le demander."""
        path = Path(path)
        if self._board is not None and self._board.source == path:
            return
        relay = _DrawingRelay(self)
        self._drawing_relay = relay
        relay.done.connect(lambda data, _r, error: self._spreadsheet_read(relay, path, data, error))
        self.path_label.setText(f"Lecture de {path.name}…")

        def work():
            try:
                from fm_tableur import files_mode
                relay.done.emit(files_mode.read_as_board(path), None, None)
            except Exception as exc:                        # noqa: BLE001 - fichier refuse : message
                relay.done.emit(None, None, f"{type(exc).__name__} : {exc}")
        threading.Thread(target=work, name="lecture classeur", daemon=True).start()

    def _spreadsheet_read(self, relay, path: Path, data, error):
        relay.deleteLater()
        if relay is not self._drawing_relay:
            return
        self._drawing_relay = None
        if error is not None:
            self.path_label.setText(f"{path.name} : {error}")
            return
        if self._open_board(path, imported=data):
            from fm_tableur import files_mode
            files_mode.attach(self._board, path)

    def _open_cad_drawing(self, path: Path):
        """Dessin DXF / DWG dans le module MRO (demande de l'utilisateur) : lu et converti HORS du fil de
        l'interface (`fm_cad.cad_import`, conversion ODA pour un DWG : plusieurs secondes possibles), puis ouvert
        comme un board en memoire (le dessin d'origine n'est jamais reecrit ; voir `BoardPane.open_import`)."""
        import threading
        from fm_cad import cad_import
        path = Path(path)
        if self._board is not None and self._board.source == path:
            return
        relay = _DrawingRelay(self)
        self._drawing_relay = relay                        # seule la derniere demande est ouverte
        relay.done.connect(lambda data, report, error: self._cad_drawing_read(relay, path, data, report, error))
        self.path_label.setText(f"Lecture de {path.name}…")

        def work():
            try:
                data, report = cad_import.read_drawing(path)
                relay.done.emit(data, report, None)
            except cad_import.DrawingError as exc:
                relay.done.emit(None, None, str(exc))
            except Exception as exc:                        # noqa: BLE001 - fichier inattendu : message
                relay.done.emit(None, None, f"{type(exc).__name__} : {exc}")
        threading.Thread(target=work, name="lecture DXF", daemon=True).start()

    def _cad_drawing_read(self, relay, path: Path, data, report, error):
        relay.deleteLater()
        if relay is not self._drawing_relay:
            return                                          # une autre ouverture a ete demandee depuis
        self._drawing_relay = None
        from fm_cad import cad_import
        if error is not None:
            self.path_label.setText(f"{path.name} : {error}")
            return
        if self._open_board(path, imported=data):
            self.path_label.setText(cad_import.describe(report))

    def _open_board(self, path: Path, imported: dict | None = None) -> bool:
        """Le board recouvre les colonnes (comme l'editeur de texte) ; ses boutons dans le cadre « Board » de la
        barre de navigation. Un autre board ouvert est d'abord enregistre et ferme. `imported` : dessin DXF / DWG
        deja lu (`_open_cad_drawing`), ouvert en memoire."""
        import fm_board.ui
        from fm_board.ui import BoardPane
        fm_board.ui.ICON_PROVIDER = self._board_icon
        fm_board.ui.SETTING_WRITER = self._write_setting_now
        import fm_cad.cad_export
        from previews import _oda_file_converter
        fm_cad.cad_export.ODA_PROVIDER = _oda_file_converter     # meme recherche que les apercus DWG
        # Overrides des menus du board (Reglages > Module MRO > Menus contextuels) : la correspondance des lignes est
        # dans le catalogue des reglages (deja charge par le prechargement de la fenetre, sinon ~0,1 s une fois).
        import settings_window_v2  # noqa: F401
        if self._project_columns_hidden:
            return False
        if not self._close_md_editor():
            return False
        self._close_video()
        if self._board is not None:
            if (self._board.source if imported is not None else self._board.path) == Path(path):
                return True
            if not self._close_board():
                return False
        pane = BoardPane(self.scroll.viewport(), ui_state.APPLIED_SETTINGS or {})
        if not (pane.open_import(imported, path) if imported is not None else pane.open(path)):
            pane.deleteLater()
            return False
        self._board = pane
        pane.closeRequested.connect(self._close_board)
        pane.stateChanged.connect(self._layout_board_buttons)
        pane.dirtyChanged.connect(lambda _d: self._layout_board_buttons())
        pane.fade_in()
        self._layout_board_buttons()
        self._sync_collapse_button()
        self.path_label.setText(str(path))
        return True

    def _close_board(self) -> bool:
        """Retour aux colonnes (le board est enregistre, avec sa vue). False = annule."""
        pane = self._board
        if pane is None:
            return True
        if not pane.confirm_leave():
            return False
        self._board = None
        self.titlebar.board_group().hide()
        pane.fade_out(pane.deleteLater)
        self._sync_collapse_button()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()
        return True

    def _layout_board_buttons(self):
        """Boutons du cadre « Board » : annuler, retablir, tout voir, exporter, fermer."""
        pane = self._board
        group = self.titlebar.board_group()
        if pane is None:
            group.hide()
            return
        if not self._board_buttons:
            for kind, tip, slot in (
                    ("undo", "Annuler (Ctrl+Z)", lambda: self._board and self._board.undo()),
                    ("redo", "Rétablir (Ctrl+Y)", lambda: self._board and self._board.redo()),
                    ("fit", "Tout voir (Maj+1)", lambda: self._board and self._board.view.fit_all()),
                    ("export", "Exporter (PNG, SVG, PDF)…", lambda: self._board and self._board.export_dialog()),
                    ("gear", "Réglages du board (MRO, CAD)", lambda: self.open_module_settings("board")),
                    ("close", "Fermer le board (Échap)", self._close_board)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._board_kind = kind
                self._board_buttons.append(button)
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in self._board_buttons:
            style_focus_button(button)
            kind = button._board_kind
            if kind == "undo":
                self._set_button_usable(button, pane.can_undo())
            elif kind == "redo":
                self._set_button_usable(button, pane.can_redo())
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()
