"""Inspecteur : notes Markdown (rendu de fm_markdown, édition, enregistrement fidèle).

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QWidget,
)

from app_style import C, font, role_color, scaled
from fm_markdown import preview as markdown_preview


class MarkdownMixin:
    """Méthodes de DetailPanel : inspecteur : notes Markdown (rendu de fm_markdown, édition, enregistrement fidèle)."""

    # -- Notes Markdown : rendu du module Markdown (markdown_preview, habillage de l'onglet Markdown) et edition --

    _MD_AUTOSAVE_MS = 800

    def _md_widgets(self) -> list:
        return [w for w in (getattr(self, "markdown_bar", None), getattr(self, "markdown_slot", None),
                            getattr(self, "markdown_editor", None)) if w is not None]

    def _text_shown(self) -> bool:
        """Un apercu texte (brut ou note Markdown, lue ou editee) occupe la place de l'image."""
        return self.text_preview.isVisible() or any(w.isVisible() for w in self._md_widgets())

    def _hide_markdown(self):
        self._flush_markdown()
        self._md_path = None                   # plus de note active (Ctrl+E / Ctrl+S sans effet)
        for widget in self._md_widgets():
            widget.hide()

    def _hide_text_views(self):
        self.text_preview.hide()
        self._hide_markdown()

    def _ensure_markdown_widgets(self) -> bool:
        """Barre (Modifier / Lecture + etat d'enregistrement), vue web (lecture) et editeur
        (source), crees au premier .md ; ils prennent toute la hauteur de l'apercu."""
        if getattr(self, "markdown_view", None) is not None:
            return True
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtGui import QKeySequence, QShortcut
        except ImportError:
            return False
        self._md_path = None          # note affichee
        self._md_info = None          # encodage / fins de ligne / date lue (markdown_preview.read_note)
        self._md_dirty = False
        self._md_editing = False      # mode garde d'une note a l'autre, comme un onglet d'Obsidian
        self._md_save_timer = QTimer(self)
        self._md_save_timer.setSingleShot(True)
        self._md_save_timer.setInterval(self._MD_AUTOSAVE_MS)
        self._md_save_timer.timeout.connect(self._save_markdown)

        bar = self.markdown_bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        button = self.markdown_mode_button = QPushButton("Modifier")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(scaled(24))
        button.setToolTip("Basculer lecture / edition (Ctrl+E) ; enregistrement automatique (Ctrl+S pour forcer)")
        button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; padding: 0 10px; "
            f"border: 1px solid {C['btn_border']}; border-radius: 3px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}")
        button.clicked.connect(self._toggle_markdown_mode)
        status = self.markdown_status = QLabel("")
        status.setStyleSheet(f"color: {role_color('info', '#aab1b6')}; background: transparent;")
        bar_layout.addWidget(button)
        bar_layout.addWidget(status)
        bar_layout.addStretch(1)

        # La vue web n'est PAS dans la carte : la carte est decoupee a ses coins arrondis par un
        # QGraphicsEffect (_RoundedCornersEffect), et une vue web sous un effet reste figee a
        # l'ecran sur sa premiere image (la page defile, l'affichage non). Elle est donc enfant
        # direct du panneau, posee sur `markdown_slot`, qui lui garde sa place dans la mise en
        # page (voir _place_markdown_view) ; sa visibilite est celle de la place.
        slot = self.markdown_slot = QWidget()
        slot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        view = self.markdown_view = QWebEngineView(self)
        view.hide()
        view.page().setBackgroundColor(QColor(C["well"]))
        view.setContextMenuPolicy(Qt.NoContextMenu)

        editor = self.markdown_editor = QPlainTextEdit()
        editor.setFrameShape(QFrame.NoFrame)
        editor.setFont(font(11, 400, mono=True))
        editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        editor.setTabStopDistance(4 * editor.fontMetrics().horizontalAdvance(" "))
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {C['well']}; color: {C['text']};"
            f" border: 1px solid #282c30; padding: 10px; }}")
        editor.textChanged.connect(self._on_markdown_edited)

        layout = self._content_layout
        index = layout.indexOf(self.text_preview) + 1
        layout.insertWidget(index, bar)
        layout.insertWidget(index + 1, slot, 1)
        layout.insertWidget(index + 2, editor, 1)
        for widget in (bar, slot, editor):
            widget.hide()
        self._md_slot_watch = (slot, self._inner, self.card)   # la place bouge avec eux
        for widget in self._md_slot_watch:
            if widget is not self.card:                         # deja filtre (redimensionnement)
                widget.installEventFilter(self)
        for keys, slot in (("Ctrl+E", self._toggle_markdown_mode), ("Ctrl+S", self._flush_markdown)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda slot=slot: self._md_path is not None and slot())
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._flush_markdown)      # rien de perdu en quittant
        return True

    def _show_markdown(self, path: Path) -> bool:
        """Note .md : lue comme dans le mode lecture du module Markdown (meme rendu, memes reglages) ou
        editee en texte source, au choix (bouton Modifier / Lecture, Ctrl+E). Faux si ce n'est pas
        une note ou si QtWebEngine / markdown-it manquent : l'extrait texte brut prend le relais."""
        if path.suffix.lower() not in markdown_preview.MARKDOWN_EXTENSIONS or not markdown_preview.available():
            return False
        if not self._ensure_markdown_widgets():
            return False
        if (self._md_path == path and self.markdown_bar.isVisible()
                and not markdown_preview.changed_on_disk(path, self._md_info)):
            return True                        # meme note reaffichee : edition (curseur, annulation) intacte
        self._flush_markdown()                 # la note precedente d'abord
        try:
            text, info = markdown_preview.read_note(path)
        except OSError:
            return False
        self._md_path, self._md_info, self._md_dirty = path, info, False
        self.text_preview.hide()
        self.markdown_bar.show()
        self._load_markdown_editor(text)
        self._apply_markdown_mode(text)
        return True

    def _load_markdown_editor(self, text: str, keep_cursor: bool = False):
        """Texte de la note dans l'editeur ; `keep_cursor` : rechargement de la meme note (curseur
        garde a sa place, borne a la nouvelle longueur)."""
        editor = self.markdown_editor
        position = editor.textCursor().position() if keep_cursor else 0
        editor.blockSignals(True)
        editor.setPlainText(text)
        editor.blockSignals(False)
        editor.document().clearUndoRedoStacks()
        if keep_cursor:
            cursor = editor.textCursor()
            cursor.setPosition(min(position, len(text)))
            editor.setTextCursor(cursor)

    def refresh_markdown_style(self):
        """Onglet Markdown des reglages change : la note affichee en lecture est rendue a nouveau (meme habillage
        que le module Markdown)."""
        if getattr(self, "_md_path", None) is not None and not self._md_editing and \
                getattr(self, "markdown_view", None) is not None and self.markdown_view.isVisible():
            self._apply_markdown_mode()

    def _apply_markdown_mode(self, text: str | None = None):
        """Affiche la note dans le mode courant ; en lecture, rendu du texte `text` (celui de
        l'editeur : ce qu'on vient d'ecrire, sans relire le disque)."""
        path = self._md_path
        if path is None:
            return
        editing = self._md_editing
        self.markdown_mode_button.setText("Lecture" if editing else "Modifier")
        self.markdown_slot.setVisible(not editing)
        self.markdown_editor.setVisible(editing)
        if editing:
            self.markdown_editor.setFocus()
        else:
            page = markdown_preview.render_page(path, text if text is not None else self.markdown_editor.toPlainText())
            self.markdown_view.setHtml(page, QUrl.fromLocalFile(str(path.parent) + "/"))
        self._update_markdown_status()

    def _place_markdown_view(self):
        """Pose la vue web sur sa place (`markdown_slot`) : meme rectangle, meme visibilite."""
        slot, view = self.markdown_slot, self.markdown_view
        shown = slot.isVisibleTo(self)
        if shown:
            view.setGeometry(QRect(slot.mapTo(self, QPoint(0, 0)), slot.size()))
            handle = getattr(self, "_resize_handle", None)
            if not view.isVisibleTo(self):
                view.show()
                view.raise_()
                if handle is not None:
                    handle.raise_()             # la poignee de redimensionnement reste au-dessus
        elif view.isVisibleTo(self):
            view.hide()

    def _toggle_markdown_mode(self):
        if self._md_path is None:
            return
        if self._md_editing and not self._flush_markdown():
            return                             # enregistrement refuse (conflit) : on reste en edition
        if not self._md_editing and markdown_preview.changed_on_disk(self._md_path, self._md_info):
            # Modifiee ailleurs pendant la lecture : on edite la version du disque.
            try:
                text, self._md_info = markdown_preview.read_note(self._md_path)
                self._load_markdown_editor(text, keep_cursor=True)
            except OSError:
                pass
        self._md_editing = not self._md_editing
        self._apply_markdown_mode()

    def _on_markdown_edited(self):
        self._md_dirty = True
        self._md_save_timer.start()
        self._update_markdown_status()

    def _update_markdown_status(self):
        if not self._md_editing:
            text = ""
        elif self._md_dirty:
            text = "Modifications en cours…"
        else:
            text = "Enregistré"
        self.markdown_status.setText(text)

    def _flush_markdown(self) -> bool:
        """Enregistre tout de suite les modifications en attente (changement de fichier, retour en
        lecture, Ctrl+S, fermeture). Faux si l'enregistrement a ete refuse."""
        timer = getattr(self, "_md_save_timer", None)
        if timer is not None:
            timer.stop()
        return self._save_markdown()

    def _save_markdown(self) -> bool:
        """Ecrit la note si elle a change. Si le fichier a ete modifie ailleurs depuis sa lecture
        (Obsidian, synchro), on demande : garder ma version, ou recharger celle du disque."""
        path, info = getattr(self, "_md_path", None), getattr(self, "_md_info", None)
        if path is None or info is None or not self._md_dirty:
            return True
        if markdown_preview.changed_on_disk(path, info):
            box = QMessageBox(QMessageBox.Warning, "Note modifiée ailleurs",
                              f"« {path.name} » a été modifiée en dehors de l'inspecteur "
                              "(Obsidian, synchronisation…) depuis son ouverture.", parent=self)
            keep = box.addButton("Garder ma version", QMessageBox.AcceptRole)
            reload = box.addButton("Recharger le fichier", QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is reload:
                try:
                    text, self._md_info = markdown_preview.read_note(path)
                except OSError:
                    return False
                self._md_dirty = False
                self._load_markdown_editor(text, keep_cursor=True)
                self._update_markdown_status()
                return True
            if box.clickedButton() is not keep:
                return False
        try:
            markdown_preview.write_note(path, self.markdown_editor.toPlainText(), info)
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", f"{path.name} :\n{exc}")
            return False
        self._md_dirty = False
        self._update_markdown_status()
        return True
