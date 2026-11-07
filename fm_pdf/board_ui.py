"""Module « PDF » du Board (Qt) : bouton de la barre des modules, barres flottantes du module, éléments `pdf_doc`,
édition SUR PLACE du document (`board_live.LiveDoc`, un seul à la fois) et l'éditeur PDF PLEIN CADRE au-dessus du
Board (même `PdfPane` que celui ouvert depuis les colonnes ; fermé = retour au Board, documents rafraîchis).

Barres (fm_theme, disposition retenue dans `board_bars["pdf"]`) :
- « PDF » : insérer un PDF, nouveau formulaire, éditeur plein cadre ;
- « Document » (le document édité, sinon celui choisi) : Remplir (sélection, formulaires), Main, Annuler,
  Rétablir, Enregistrer (accent tant que le fichier lié n'est pas enregistré) ;
- « Affichage » : zoom − / % / +, PLEINE PAGE, PLEINE LARGEUR, PLEIN ÉCRAN (demande de l'utilisateur, 2026-11-06),
  page précédente, numéro de page (clic : aller à…), page suivante."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtWidgets import QFileDialog, QWidget

from fm_board import model
from fm_board.bars import BoardBars
from fm_theme.palette import PaletteTextButton

from . import board_docs
from . import board_model as bm

BUTTONS = [("insert", "Insérer un PDF…", "Poser un PDF (lien vers le fichier) au centre de la vue", 5),
           ("new", "Nouveau formulaire…", "Créer un PDF vierge (A4), le poser et le concevoir dans l'éditeur", 5),
           ("open", "Éditeur PDF", "Ouvrir le PDF choisi dans l'éditeur plein cadre (conception, commentaires, "
                                   "pages, protection)", 4)]
DOC_BUTTONS = [("fill", "Remplir", "Remplir les formulaires, sélectionner et copier du texte", 3),
               ("hand", "Main", "Faire défiler le document à la souris (Espace : main temporaire)", 2),
               ("undo", "Annuler", "Annuler (Ctrl+Z)", 3),
               ("redo", "Rétablir", "Rétablir (Ctrl+Y)", 3),
               ("save", "Enregistrer", "Enregistrer le fichier PDF lié (Ctrl+S)", 4)]
VIEW_BUTTONS = [("zoom_out", "−", "Zoom arrière (Ctrl + −)", 1),
                ("zoom", "100 %", "Zoom du document", 2),
                ("zoom_in", "+", "Zoom avant (Ctrl + +)", 1),
                ("fit_page", "Pleine page", "Une page entière dans l'élément (Ctrl+0)", 4),
                ("fit_width", "Pleine largeur", "La largeur de la page dans l'élément", 5),
                ("fullscreen", "Plein écran", "Le document sur tout l'écran (F11 ; Échap pour revenir)", 4),
                ("prev", "◀", "Page précédente", 1),
                ("pages", "– / –", "Page courante (clic : aller à la page…)", 3),
                ("next", "▶", "Page suivante", 1)]


def default_state() -> dict:
    def row(buttons):
        items, col = {}, 0
        for key, _t, _tip, cells in buttons:
            items[key] = [col, 0, cells]
            col += cells
        return items, col
    pdf, pdf_cols = row(BUTTONS)
    doc, doc_cols = row(DOC_BUTTONS)
    view, view_cols = row(VIEW_BUTTONS)
    return {"next": 4, "bars": [
        {"id": "b1", "title": "PDF", "dock": "top", "orient": "h", "along": 260, "x": 0, "y": 0, "cols": pdf_cols,
         "rows": 1, "items": pdf},
        {"id": "b2", "title": "Document", "dock": "top", "orient": "h", "along": 260, "after": "b1", "x": 0, "y": 0,
         "cols": doc_cols, "rows": 1, "items": doc},
        {"id": "b3", "title": "Affichage", "dock": "bottom", "orient": "h", "along": 0, "end": True, "x": 0, "y": 0,
         "cols": view_cols, "rows": 1, "items": view}]}


def _status(text: str) -> None:
    from .pane import HOOKS
    try:
        HOOKS["status"](text)
    except Exception:                                      # noqa: BLE001 - barre d'état absente (tests)
        pass


class PdfBoardController(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.active = False
        self.ui = self
        self.editor = None
        self.live_item = None
        self.bars = BoardBars(pane, "pdf", default_state())
        self.buttons: dict[str, PaletteTextButton] = {}
        slots = {"insert": self.insert_dialog, "new": self.new_form, "open": self.open_selected,
                 "fill": lambda: self._do(lambda live: live.set_tool("select")),
                 "hand": lambda: self._do(lambda live: live.set_tool("hand")),
                 "undo": lambda: self._do(lambda live: live.undo()),
                 "redo": lambda: self._do(lambda live: live.redo()),
                 "save": lambda: self._do(lambda live: live.save()),
                 "zoom_out": lambda: self._do(lambda live: live.zoom_by(0.8)),
                 "zoom": lambda: self._do(lambda live: live.view.set_zoom(1.0)),
                 "zoom_in": lambda: self._do(lambda live: live.zoom_by(1.25)),
                 "fit_page": lambda: self._do(self._fit_page_screen),
                 "fit_width": lambda: self._do(self._fit_width_screen),
                 "fullscreen": lambda: self._do(lambda live: live.set_fullscreen(not live.fullscreen)),
                 "prev": lambda: self._do(lambda live: live.view.next_page(-1)),
                 "pages": lambda: self._do(self._ask_page),
                 "next": lambda: self._do(lambda live: live.view.next_page(1))}
        for key, text, tip, cells in BUTTONS + DOC_BUTTONS + VIEW_BUTTONS:
            button = PaletteTextButton(key, text, tip, cells=cells)
            button.clicked.connect(lambda _c=False, s=slots[key]: s())
            self.buttons[key] = button
            self.bars.register(key, button)
        self.bars.restore()
        self.bars.set_visible(False)
        self._no_bar = QWidget(pane)
        self._no_bar.hide()

    @property
    def bar(self):
        bar = self.bars.manager.bar_of("insert") or self.bars.bar("b1")
        return bar if bar is not None else self._no_bar

    def activate(self):
        self.active = True
        self.bars.set_visible(True)
        self.place()
        self.bars.raise_all()
        selected = self.selected_items()
        if selected:                                       # document choisi : éditable tout de suite
            self.make_live(selected[0])
        self.sync_bar()

    def deactivate(self):
        self.active = False
        self.stop_live()
        self.bars.set_visible(False)

    def place(self):
        live = self.live()
        full = live is not None and live.fullscreen
        if self.active:
            self.bars.set_area(0 if full else self.pane.left_edge())
        if full:
            live.setGeometry(self.pane.rect())
            live.raise_()
            self.bars.raise_all()
        if self.editor is not None:
            self.editor.setGeometry(self.pane.rect())
            self.editor.raise_()

    def apply_settings(self, settings: dict):
        if self.editor is not None:
            self.editor.apply_settings(settings)

    # -- document édité sur place --

    def live(self):
        item = self.live_item
        try:
            return item.live if item is not None else None
        except RuntimeError:                               # élément détruit
            self.live_item = None
            return None

    def make_live(self, item):
        """Édite `item` sur place (le précédent revient à son aperçu, son document reste ouvert)."""
        if self.live_item is item and item.is_live():
            return item.start_live()
        self.stop_live()
        live = item.start_live()
        if live is None:
            return None
        self.live_item = item
        live.stateChanged.connect(self.sync_bar)
        live.fullscreenChanged.connect(self._fullscreen_changed)
        session = live.session
        session.saved.connect(self._saved, Qt.UniqueConnection)
        session.saveFailed.connect(self._save_failed, Qt.UniqueConnection)
        self.sync_bar()
        return live

    def stop_live(self):
        item, self.live_item = self.live_item, None
        if item is not None:
            try:
                item.stop_live()
            except RuntimeError:
                pass
        self.sync_bar()

    def _fullscreen_changed(self, _on: bool):
        self.place()
        self.sync_bar()

    def _saved(self, text: str):
        _status("PDF : " + text)
        self.sync_bar()

    def _save_failed(self, message: str):
        from . import ui_kit
        _status("PDF : enregistrement impossible : %s" % message)
        ui_kit.confirm(self.pane, "Enregistrement impossible", message, "OK")

    def target(self):
        """Le document des barres : celui édité, sinon le PDF choisi (ou le seul du Board), mis en édition."""
        live = self.live()
        if live is not None:
            return live
        items = self.selected_items() or self.pdf_items()
        if len(items) == 1 or self.selected_items():
            return self.make_live(items[0])
        _status("PDF : choisissez un document du Board (clic dessus)")
        return None

    def _do(self, fn):
        live = self.target()
        if live is not None:
            fn(live)
            self.sync_bar()

    def _fit_page_screen(self, live):
        """« Pleine page » (demande de l'utilisateur 2026-11-06 : « recentrer la page en cours de manière à remplir
        l'écran ») : une page entière dans l'élément, puis la vue du Board recadrée sur la page EN COURS."""
        live.fit_page()
        page, board_view = self._page_on_board(live)
        if page is not None:
            board_view.fit_rect(page)

    def _fit_width_screen(self, live):
        """« Pleine largeur » (demande de l'utilisateur 2026-11-06 : « mettre le document en pleine largeur à
        l'écran ») : le document en pleine largeur dans l'élément, puis la vue du Board recadrée pour que sa largeur
        remplisse l'écran, le haut de la page EN COURS en haut de l'écran."""
        live.fit_width()
        page, board_view = self._page_on_board(live)
        if page is not None:
            board_view.fit_width_rect(page)

    def _page_on_board(self, live):
        """(page EN COURS dans la scène du Board, vue du Board) ; (None, None) hors du Board."""
        item = live.item
        proxy = getattr(item, "_proxy", None) if item is not None else None
        board_view = getattr(self.pane, "view", None)
        if proxy is None or board_view is None or not hasattr(board_view, "fit_rect"):
            return None, None
        view = live.view
        page = view.page_rect(view.current)                  # pixels logiques du viewport de la vue embarquée
        origin = view.viewport().mapTo(live, page.topLeft())
        return proxy.mapRectToScene(QRectF(origin, page.size())), board_view

    def _ask_page(self, live):
        from . import ui_kit
        count = live.view.page_count()
        text = ui_kit.ask_text(self.pane, "Aller à la page", "Numéro de page (1 à %d) :" % count,
                               default=str(live.view.current + 1), action="Aller")
        try:
            live.view.go_to_page(int(str(text).strip()) - 1)
        except (TypeError, ValueError):
            pass

    def sync_bar(self):
        """Textes et états des barres (zoom, page, ajustement, plein écran, outil, « modifié »)."""
        live = self.live()
        b = self.buttons
        if live is None:
            b["zoom"].set_text("– %")
            b["pages"].set_text("– / –")
            for key in ("fill", "hand", "fit_page", "fit_width", "fullscreen", "save"):
                b[key].set_active(False)
            return
        v = live.view
        b["zoom"].set_text("%d %%" % round(v.zoom * 100))
        b["pages"].set_text("%d / %d" % (min(v.page_count(), v.current + 1), v.page_count()))
        b["fill"].set_active(v.tool == "select")
        b["hand"].set_active(v.tool == "hand")
        b["fit_page"].set_active(v.fit == "page")
        b["fit_width"].set_active(v.fit == "width")
        b["fullscreen"].set_active(live.fullscreen)
        b["save"].set_active(live.session.dirty)

    # -- commandes --

    def _center(self) -> QPointF:
        return self.pane.view.view_center()

    def insert(self, path, page: int = 0):
        """Pose un élément lié au PDF `path` (taille aux proportions de sa page)."""
        from .worker import get_engine
        from . import fileio
        try:
            def size():
                doc = get_engine().open_document(fileio.read_file(path), str(path), javascript=False, xfa=False)
                try:
                    return doc.page_size(min(page, doc.page_count() - 1))
                finally:
                    get_engine().close_document(doc)
            pw, ph = get_engine().call(size, timeout=30)
        except Exception:                                   # noqa: BLE001 - illisible : taille par défaut
            pw, ph = 595.0, 842.0
        w, h = bm.fit_size(pw, ph)                             # le cadre = la page (aucun écart, rien dessous)
        center = self._center()
        data = model.new_item(bm.PDF_DOC, x=round(center.x() - w / 2, 2), y=round(center.y() - h / 2, 2), w=w,
                              h=h, page=page, framed=True, **bm.link_values(path, getattr(self.pane, "path", None)))
        data["z"] = self.pane.scene.next_z()
        return self.pane.scene.add_new(data, "Insérer un PDF")

    def insert_dialog(self):
        start = str(Path(self.pane.path).parent) if getattr(self.pane, "path", None) else ""
        paths, _ = QFileDialog.getOpenFileNames(self.pane, "Insérer des PDF", start, "Documents PDF (*.pdf)")
        for path in paths:
            self.insert(path)

    def new_form(self):
        from . import acroform, fileio
        start = str(Path(self.pane.path).with_name("formulaire.pdf")) if getattr(self.pane, "path", None) else \
            "formulaire.pdf"
        path, _ = QFileDialog.getSaveFileName(self.pane, "Nouveau formulaire PDF", start, "Documents PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        fileio.write_atomic(path, acroform.new_blank_document())
        item = self.insert(path)
        editor = self.open_editor(Path(path), item)
        if editor is not None:
            editor.set_mode("design")
        return item

    def pdf_items(self):
        from .board_item import PdfItem
        return [i for i in self.pane.scene.board_items() if isinstance(i, PdfItem)]

    def selected_items(self):
        from .board_item import PdfItem
        return [i for i in self.pane.scene.selectedItems() if isinstance(i, PdfItem)]

    def open_selected(self):
        items = ([self.live_item] if self.live() is not None else []) or self.selected_items()
        if items:
            items[0].open_editor()
        else:
            self.insert_dialog()

    def open_editor(self, path, item=None):
        """Éditeur plein cadre au-dessus du Board (Échap ne le ferme pas ; « Fermer » revient au Board). Le
        document de l'élément a des saisies non enregistrées : enregistrées d'abord (l'éditeur relit le fichier)."""
        from .pane import PdfPane
        entry = board_docs.existing_entry(item) if item is not None else None
        if entry is not None and entry.session.dirty:
            from . import ui_kit
            if not ui_kit.confirm(self.pane, "Document modifié", "« %s » a des saisies non enregistrées : les "
                                  "enregistrer pour l'ouvrir dans l'éditeur ?" % Path(path).name, "Enregistrer"):
                return None
            if not board_docs.save_and_wait(entry, self.pane):
                return None
        if self.editor is not None:
            if self.editor.session.path == Path(path):
                self.editor.raise_()
                return self.editor
            if not self.editor.confirm_leave():
                return None
            self.close_editor()
        live = self.live()
        if live is not None and live.fullscreen:
            live.set_fullscreen(False)
        editor = PdfPane(self.pane)
        editor.closeRequested.connect(self.close_editor)
        editor.open_path(path)
        editor.show()
        editor.raise_()
        editor.view.setFocus()
        self.editor = editor
        return editor

    def close_editor(self):
        editor, self.editor = self.editor, None
        if editor is None:
            return
        path = editor.session.path
        editor.shutdown()
        editor.hide()
        editor.deleteLater()
        if path is not None:                                 # le fichier a pu changer : documents rouverts
            board_docs.reopen_path(self.pane.scene, path)
        for item in self.pdf_items():
            item.update()

    def confirm_leave(self) -> bool:
        """Fermeture du Board : éditeur plein cadre puis documents des éléments (modifiés : enregistrer ?)."""
        if self.editor is not None and not self.editor.confirm_leave():
            return False
        if not board_docs.confirm_leave(self.pane, self.pane.scene):
            return False
        self.stop_live()                                   # plein écran : la fenêtre reprend son état d'avant
        return True
