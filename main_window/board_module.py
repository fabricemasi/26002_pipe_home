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
        self._open_selected_in(("board", "cad", "sheet"))

    @staticmethod
    def _is_spreadsheet(path) -> bool:
        from .module_targets import SPREADSHEET_SUFFIXES
        return path is not None and Path(path).suffix.lower() in SPREADSHEET_SUFFIXES

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
        import fm_cad.cad_export
        from fm_cad import cad_import
        from previews import _oda_file_converter
        fm_cad.cad_export.ODA_PROVIDER = _oda_file_converter     # avant la lecture : meme recherche que les apercus
        import ui_state
        cad_import.NATIVE_BLOCKS = bool((ui_state.APPLIED_SETTINGS or {}).get("board_cad_import_blocks", True))
        path = Path(path)
        if self._board is not None and self._board.source == path:
            return
        relay = _DrawingRelay(self)
        self._drawing_relay = relay                        # seule la derniere demande est ouverte
        relay.done.connect(lambda data, report, error: self._cad_drawing_read(relay, path, data, report, error))
        self.path_label.setText(f"Lecture de {path.name}…")

        def work():
            from fm_board.scene import hold_gc
            key = ("lecture", id(relay))
            hold_gc(key, True)                      # passes completes du ramasse-miettes : a-coups de l'interface
            try:
                # Lu, converti et normalise ici (pas sur le fil de l'interface), ou repris du cache disque des
                # dessins convertis (`fm_cad/cad_cache.py` : ~11 s -> ~0,2 s pour 81 000 entites).
                data, report = cad_import.open_drawing(path)
                relay.done.emit(data, report, None)
            except cad_import.DrawingError as exc:
                relay.done.emit(None, None, str(exc))
            except Exception as exc:                        # noqa: BLE001 - fichier inattendu : message
                relay.done.emit(None, None, f"{type(exc).__name__} : {exc}")
            finally:
                hold_gc(key, False)
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
        note = self._board_load_note = cad_import.describe(report)  # remontre une fois tout charge (par tranches)
        if self._open_board(path, imported=data, normalized=True):
            self.path_label.setText(note)
        if self._board is None or not self._board.scene.loading():
            self.__dict__.pop("_board_load_note", None)

    def _open_board(self, path: Path, imported: dict | None = None, normalized: bool = False) -> bool:
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
        if not self._leave_font():
            return False
        leave_pdf = getattr(self, "_leave_pdf", None)          # éditeur PDF ouvert : fermé d'abord (fm_pdf)
        if leave_pdf is not None and not leave_pdf():
            return False
        leave_agenda = getattr(self, "_leave_agenda", None)    # agenda ouvert : rangé d'abord (fm_agenda)
        if leave_agenda is not None:
            leave_agenda()
        if self._board is not None:
            if (self._board.source if imported is not None else self._board.path) == Path(path):
                return True
            if not self._close_board():
                return False
        pane = BoardPane(self.scroll.viewport(), ui_state.APPLIED_SETTINGS or {})
        if not (pane.open_import(imported, path, normalized) if imported is not None else pane.open(path)):
            pane.deleteLater()
            return False
        self._board = pane
        pane.scene.loadProgress.connect(lambda done, total, name=Path(path).name:
                                        self._board_load_progress(name, done, total))
        pane.closeRequested.connect(self._close_board)
        # Fluidite (journal des blocages, 2026-11-05) : les colonnes restaient affichees SOUS le board ; chaque
        # repeinture d'un element transparent du board (reticule CAD, barres flottantes) repeignait aussi les
        # colonnes dessous, a travers leurs effets de coins arrondis (image complete de chaque carte) : 50 a 100 ms
        # par geste. Cachees une fois le fondu fini, remontrees avant le fondu de fermeture.
        pane.coveringShown.connect(lambda p=pane: self._board is p and self.columns_host.hide())
        pane.stateChanged.connect(self._layout_board_buttons)
        pane.dirtyChanged.connect(lambda _d: self._layout_board_buttons())
        pane.saveStateChanged.connect(self._show_board_state)
        self._show_board_state(*pane.save_state())
        self._attach_render_badge(pane)
        pane.fade_in()
        self._layout_board_buttons()
        self._sync_collapse_button()
        self.path_label.setText(str(path))
        return True

    def _show_board_state(self, text: str | None, dirty: bool):
        """Etat d'enregistrement du board (« modifié », « enregistré »…, sans le nom du fichier) a la place de
        « read-only » dans la barre d'etat ; None : « read-only » revient (board ferme)."""
        from settings_store import M
        color = M["dirty_frame"] if (dirty and text) else role_color("info2", C["dim"])
        self.status_right.setStyleSheet(f"color: {color}; background: transparent;")
        self.status_right.setText("read-only" if text is None else text)

    def _attach_render_badge(self, pane):
        """Encart du mode de rendu (OPEN GL / CLASSIQUE) accroche en bas de la barre de navigation, coins du bas
        droits ; celui du board se cache."""
        from fm_board.ui import RenderBadge
        badge = getattr(self, "_board_render_badge", None)
        if badge is None:
            badge = self._board_render_badge = RenderBadge(self.titlebar, hanging=True)
            badge.clicked.connect(lambda: self._board is not None and self._board.toggle_render_mode())
        pane.view.renderModeChanged.connect(badge.set_gl)
        pane.view.renderModeChanged.connect(lambda _gl: self.titlebar.place_bottom_badge())
        badge.set_gl(pane.view.gpu_active())
        pane.set_external_badge(True)
        badge.show()
        self.titlebar.set_bottom_badge(badge)

    def _board_load_progress(self, name: str, done: int, total: int):
        """Gros board / dessin charge par tranches (`BoardScene.load_data`) : avancement dans la barre du bas,
        puis le compte rendu de l'import (DXF / DWG) ou le chemin."""
        if done < total:
            self.path_label.setText(f"Chargement de {name} : {done * 100 // total} % ({done} / {total} éléments)…")
            return
        note = self.__dict__.pop("_board_load_note", None)
        board = self._board
        self.path_label.setText(note or str(getattr(board, "path", None) or getattr(board, "source", "") or name))

    def _close_board(self) -> bool:
        """Retour aux colonnes (le board est enregistre, avec sa vue). False = annule."""
        pane = self._board
        if pane is None:
            return True
        if not pane.confirm_leave():
            return False
        self._board = None
        self.titlebar.board_group().hide()
        self.titlebar.set_bottom_badge(None)
        self._show_board_state(None, False)
        self.columns_host.show()                 # cachees pendant le board (voir _open_board)
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
