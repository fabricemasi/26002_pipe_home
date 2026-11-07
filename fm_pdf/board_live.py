"""Document VIVANT d'un élément PDF du Board (Qt) : la vue du module (`PdfView`, toutes les pages en défilement
continu) posée DANS l'élément quand le module PDF est actif (demande de l'utilisateur, 2026-11-06 : « je veux que le
document apparaisse et qu'il soit modifiable quand le module est actif, avec toutes ses pages et avec sa barre des
outils »). La barre d'outils est celle du module (barres flottantes « Document » et « Affichage », `board_ui.py`).

- `EmbeddedPdf` (QGraphicsProxyWidget marqué `EMBEDDED`, même mécanisme que le classeur du Tableur) : la vue du Board
  lui laisse souris, double-clic et molette (Ctrl + molette = zoom du Board) ; le clavier passe par `editing()`.
- Netteté : la vue rend ses tuiles au zoom du Board (`PdfView.render_scale`) et seulement pour la partie visible à
  l'écran (`clip_to_exposed`).
- Tab / Maj + Tab : Qt les remet au widget embarqué : champ suivant / précédent (vérifié par un vrai Tab envoyé à
  la vue du Board, `test_fill_a_form_in_the_board_tab_and_save_to_the_linked_file`).
- Ctrl + S (enregistrer le PDF), Ctrl + Z / Ctrl + Y (saisie : PDFium ; sinon pile du document), F11 (plein écran) :
  réclamés par la vue tant qu'elle a le focus (sinon les raccourcis de la fenêtre les prendraient).
- PLEIN ÉCRAN : le même widget (même session, même zoom, même page) quitte l'élément et recouvre tout le Board ; la
  fenêtre passe en plein écran (état d'avant rendu à la sortie : maximisée reste maximisée). Échap (rien d'autre à
  annuler), F11 ou le bouton en sortent (règle de l'appli : Échap annule, ne ferme jamais le module)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import QGraphicsProxyWidget, QVBoxLayout, QWidget

from .view import PdfView
from .worker import PRIO_SAVE


class EmbeddedPdf(QGraphicsProxyWidget):
    """Le document posé dans l'élément : la vue du Board lui laisse souris et clavier."""
    EMBEDDED = True

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def editing(self) -> bool:
        return True

    def focusInEvent(self, event):
        super().focusInEvent(event)
        scene = self.scene()
        if scene is not None:
            scene.embedded_item = self.owner                 # clic ailleurs : `stop_edit` (le focus seulement)


class LiveDoc(QWidget):
    """La vue d'UN document (session de l'élément, `board_docs.DocEntry`). `state` = affichage enregistré dans
    l'élément (fit, zoom, scroll en points)."""
    stateChanged = Signal()          # zoom, ajustement, page, plein écran, modifié : la barre « Document » suit
    fullscreenChanged = Signal(bool)

    def __init__(self, entry, settings: dict, state: dict, host=None):
        super().__init__()
        self.entry = entry
        self.session = entry.session
        self.settings = dict(settings)
        self.host = host                                    # le BoardPane (fenêtres, plein écran)
        self.item = None
        self.fullscreen = False
        self._win_state = None
        self._state = dict(state)
        self._begun = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)   # seulement les pages : le Board se voit autour
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        settings = dict(self.settings)
        settings["pdf_default_mode"] = "continuous"         # le Board montre TOUTES les pages
        view = PdfView(self.session, settings, self)
        view.mode = "continuous"
        view.fit = state.get("fit") or None
        if not view.fit:
            view.zoom = max(0.05, float(state.get("zoom") or 1.0))
        view.clip_to_exposed = True
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # comme l'aperçu : mêmes pages, même zoom
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.set_transparent()
        lay.addWidget(view)
        self.view = view
        view.zoomChanged.connect(lambda _z: self.stateChanged.emit())
        view.pageChanged.connect(lambda _p: self.stateChanged.emit())
        view.linkRequested.connect(self._open_link)
        view.contextMenuAt.connect(self._menu)
        view.escapePressed.connect(self._escape)
        view.installEventFilter(self)
        self.session.stateChanged.connect(self.stateChanged)
        self.session.opened.connect(self._opened)
        self.session.ask_handler = self._script_question
        self._recovery = QTimer(self)
        delay = int(self.settings.get("pdf_autosave_recovery_s", 60))
        if delay > 0:
            self._recovery.timeout.connect(self.session.write_recovery)
            self._recovery.start(delay * 1000)

    # -- mise en route --

    def begin(self) -> None:
        """Après la taille posée (`PdfItem.sync`) : pages, ajustement et défilement de l'élément repris."""
        if self._begun or not self.session.info.get("page_count"):
            return
        self._begun = True
        self.view._on_document(self.session.info)
        self._apply_highlight()
        scroll = float(self._state.get("scroll") or 0.0)
        if scroll:
            self.view.verticalScrollBar().setValue(int(round(scroll * self.view.zoom)))
        self.stateChanged.emit()

    def _opened(self, _info) -> None:
        if not self._begun:
            QTimer.singleShot(0, self.begin)                 # la vue reçoit `opened` elle aussi : après elle

    def _apply_highlight(self) -> None:
        on = bool(self.settings.get("pdf_forms_highlight", True))
        color = str(self.settings.get("pdf_forms_highlight_color", "#dde4ff")).lstrip("#")
        rgb = int(color, 16) if len(color) == 6 else 0xDDE4FF
        alpha = int(self.settings.get("pdf_forms_highlight_alpha", 100)) if on else 0

        def job(doc):
            if doc.form:
                doc.c.FPDF_SetFormFieldHighlightColor(doc.form, 0, ((rgb & 0xFF) << 16) | (rgb & 0xFF00) | (rgb >> 16))
                doc.c.FPDF_SetFormFieldHighlightAlpha(doc.form, alpha)
            return True
        self.session.run(job, PRIO_SAVE)

    # -- état retenu dans l'élément --

    def view_state(self) -> dict:
        v = self.view
        zoom = max(0.05, v.zoom)
        return {"fit": v.fit or "", "zoom": round(zoom, 4), "page": int(v.current),
                "scroll": round(v.verticalScrollBar().value() / zoom, 2)}

    # -- commandes (barre « Document » / « Affichage ») --

    def fit_page(self) -> None:
        self.view.fit_page()
        self.stateChanged.emit()

    def fit_width(self) -> None:
        self.view.fit_width()
        self.stateChanged.emit()

    def zoom_by(self, factor: float) -> None:
        self.view.zoom_by(factor)

    def set_tool(self, tool: str) -> None:
        self.view.set_tool(tool)
        self.stateChanged.emit()

    def undo(self) -> None:
        if self.view.form_focus:
            self.session.run(lambda doc: doc.form_undo(doc.current_page), PRIO_SAVE)
        else:
            self.session.undo()

    def redo(self) -> None:
        if self.view.form_focus:
            self.session.run(lambda doc: doc.form_undo(doc.current_page, True), PRIO_SAVE)
        else:
            self.session.redo()

    def save(self) -> None:
        from . import board_docs
        board_docs.save(self.entry, self.host, settings=self.settings)

    # -- plein écran --

    def set_fullscreen(self, on: bool) -> None:
        """Le document recouvre tout le Board (même widget : rien n'est rechargé) et la fenêtre passe en plein
        écran ; la sortie le remet dans son élément, à la même page."""
        on = bool(on)
        item, host = self.item, self.host
        if on == self.fullscreen or item is None or host is None:
            return
        scroll = self.view_state()
        proxy = getattr(item, "_proxy", None)
        self.fullscreen = on
        if on:
            if proxy is not None:
                proxy.setWidget(None)
            self.setParent(host)
            self.setGeometry(host.rect())
            host.installEventFilter(self)
            self.view.clip_to_exposed = False
            self.view.set_render_scale(1.0)
            self.show()
            self.raise_()
            win = host.window()
            self._win_state = win.windowState()
            if not self._win_state & Qt.WindowFullScreen:
                win.setWindowState(self._win_state | Qt.WindowFullScreen)
        else:
            host.removeEventFilter(self)
            self.hide()
            self.setParent(None)
            self.view.clip_to_exposed = True
            if proxy is not None:
                proxy.setWidget(self)
                self.show()
            if self._win_state is not None:
                win = host.window()
                if not self._win_state & Qt.WindowFullScreen:
                    win.setWindowState(self._win_state)
                self._win_state = None
            item.sync()
        QTimer.singleShot(0, lambda s=scroll: self._restore_position(s))   # après le nouvel ajustement (taille)
        self.view.setFocus()
        self.fullscreenChanged.emit(on)
        self.stateChanged.emit()

    def _restore_position(self, state: dict) -> None:
        """Même endroit du document après un changement de taille (plein écran) : défilement en points."""
        v = self.view
        if v.fit == "page":
            v.go_to_page(state["page"], record=False)
        else:
            v.verticalScrollBar().setValue(int(round(state["scroll"] * v.zoom)))

    def _escape(self) -> None:
        if self.fullscreen:
            self.set_fullscreen(False)

    def paintEvent(self, event):
        """Dans l'élément : rien (le Board se voit autour des pages). Plein écran : la couleur du fond du Board (pas
        les autres éléments du Board, qui seraient derrière)."""
        if not self.fullscreen:
            return
        scene = getattr(self.host, "scene", None)
        color = getattr(scene, "background", None)
        from PySide6.QtGui import QColor, QPainter
        QPainter(self).fillRect(event.rect(), color if isinstance(color, QColor) else QColor("#212830"))

    # -- évènements --

    def eventFilter(self, obj, event):
        kind = event.type()
        if obj is self.host and kind == QEvent.Resize and self.fullscreen:
            self.setGeometry(self.host.rect())
            return False
        if obj is self.view and kind in (QEvent.ShortcutOverride, QEvent.KeyPress):
            action = self._shortcut(event)
            if action is not None:
                event.accept()
                if kind == QEvent.KeyPress:
                    action()
                return True
        return False

    def _shortcut(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if ctrl and key == Qt.Key_S:
            return self.save
        if key == Qt.Key_F11:
            return lambda: self.set_fullscreen(not self.fullscreen)
        if self.view.form_focus:                            # saisie : Ctrl + Z / Y = PDFium (vue)
            return None
        if event.matches(QKeySequence.Undo):
            return self.undo
        if event.matches(QKeySequence.Redo) or (ctrl and key == Qt.Key_Y):
            return self.redo
        return None

    def _menu(self, global_pos, _page, _x, _y) -> None:
        from . import ui_kit
        m = ui_kit.menu(self.host)
        a = m.addAction("Copier")
        a.setEnabled(self.view.selection is not None)
        a.triggered.connect(self.view.copy_selection)
        m.addSeparator()
        m.addAction("Pleine page").triggered.connect(self.fit_page)
        m.addAction("Pleine largeur").triggered.connect(self.fit_width)
        m.addAction("Quitter le plein écran" if self.fullscreen else "Plein écran").triggered.connect(
            lambda: self.set_fullscreen(not self.fullscreen))
        m.exec(global_pos)

    def _open_link(self, uri: str) -> None:
        from . import ui_kit
        url = QUrl(uri)
        if url.scheme().lower() not in ("http", "https", "mailto"):
            return
        if self.settings.get("pdf_confirm_links", True) and not ui_kit.confirm(
                self.host, "Lien externe", "Le document veut ouvrir :\n%s" % uri, "Ouvrir"):
            return
        QDesktopServices.openUrl(url)

    def _script_question(self, kind, title_text, message, extra):
        from . import ui_kit
        if kind == "alert":
            if self.settings.get("pdf_js_alerts", True):
                ui_kit.confirm(self.host, title_text or "Message du document", message, "OK")
            return 1
        return ui_kit.ask_text(self.host, title_text or "Question du document", message, default=str(extra or ""))

    # -- fin --

    def release(self) -> None:
        """Sortie de l'édition : le DOCUMENT reste ouvert (aperçu, saisies non enregistrées) ; la vue libère ses
        tuiles et ses tâches."""
        if self.fullscreen:
            self.set_fullscreen(False)
        self._recovery.stop()
        if self.session.ask_handler == self._script_question:
            self.session.ask_handler = None
        for job in list(self.view._pending.values()) + list(self.view._thumb_jobs.values()):
            job.cancel()
        self.view._pending.clear()
        self.view.cache.clear()
        self.view.thumbs.clear()
