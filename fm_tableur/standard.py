"""Mode STANDARD (Qt) : le classeur d'un élément du Board en plein cadre, sur le modèle de fm_markdown (le module
recouvre toute la zone de travail, une barre en haut, un bouton pour revenir).

Même session que l'élément (document, pile d'annulation, feuille active, sélection, défilement) : l'ouvrir ne
recharge ni ne recalcule rien, ne copie aucune donnée ; revenir au Board rend la main à l'élément, qui affiche
l'endroit où l'on travaillait. Le panneau recouvre le `BoardPane` (enfant de celui-ci) : les barres et raccourcis
du Board sont dessous, intacts ; Ctrl+S enregistre le board."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .widget import SpreadsheetWidget


class StandardPane(QWidget):
    _open: "StandardPane | None" = None

    @classmethod
    def open(cls, board, item):
        current = getattr(board, "_tableur_standard", None)
        if current is not None:
            current.close_pane()
        pane = cls(board, item)
        board._tableur_standard = pane
        pane.show()
        pane.raise_()
        pane.widget.grid.setFocus()
        return pane

    def __init__(self, board, item):
        super().__init__(board)
        from settings_store import M
        from settings_theme import _set_text_role
        self.board = board
        self.item = item
        self.setObjectName("TableurStandard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TableurStandard {{ background: {M.get('panel_bg', '#1e1f22')}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(8, 4, 8, 2)
        from .ribbon import _button
        self.back = _button("↩ Retour au Board", "Revenir au Board (le classeur reste ouvert dans son élément)",
                            self.close_pane, self)
        self.title = QLabel(self)
        _set_text_role(self.title, "value")
        self.state = QLabel(self)
        _set_text_role(self.state, "value_muted")
        top.addWidget(self.back)
        top.addSpacing(12)
        top.addWidget(self.title, 1)
        top.addWidget(self.state)
        top.addWidget(_button("Enregistrer", "Ctrl+S", self._save, self))
        top.addWidget(_button("Exporter…", "Classeur Excel (.xlsx) ou CSV : un nouveau fichier",
                              lambda: self.widget.export_file(), self))
        layout.addLayout(top)
        self.widget = SpreadsheetWidget(item.session, getattr(board, "_settings", {}), self, compact=False)
        self.widget.saveRequested.connect(self._save)
        layout.addWidget(self.widget, 1)
        self._sync_title()
        item.session.book.listeners.append(self._on_event)
        board.installEventFilter(self)
        self.setGeometry(board.rect())
        if hasattr(board, "dirtyChanged"):
            board.dirtyChanged.connect(self._sync_title)

    def _on_event(self, kind, _sheet):
        QTimer.singleShot(0, self._sync_title)

    def _sync_title(self, *_args):
        try:
            where = getattr(self.board, "path", None) or getattr(self.board, "source", None)
            self.title.setText(f"{self.item.data.get('title') or 'Classeur'} — {where.name}"
                               if where is not None else self.item.data.get("title") or "Classeur")
            self.state.setText("modifié" if getattr(self.board, "is_dirty", lambda: False)() else "enregistré")
        except RuntimeError:
            pass

    def _save(self):
        hook = getattr(self.board, "import_save_hook", None)
        if hook is not None and getattr(self.board, "path", None) is None:
            hook()                                         # classeur de l'explorateur (files_mode.save)
        elif hasattr(self.board, "save"):
            self.board.save()
        self._sync_title()

    def eventFilter(self, obj, event):
        if obj is self.board and event.type() == QEvent.Resize:
            self.setGeometry(self.board.rect())
        return super().eventFilter(obj, event)

    def close_pane(self):
        """Retour au Board : rien n'est recopié, l'élément affiche la même session."""
        try:
            self.board.removeEventFilter(self)
        except RuntimeError:
            pass
        if self._on_event in self.item.session.book.listeners:
            self.item.session.book.listeners.remove(self._on_event)
        if self.widget.grid.is_editing():
            self.widget.grid.commit_edit(move=None)
        self.widget.detach()
        if getattr(self.board, "_tableur_standard", None) is self:
            self.board._tableur_standard = None
        self.hide()
        self.deleteLater()
        try:
            self.item.update()
            view = getattr(self.board, "view", None)
            if view is not None:
                view.setFocus()
        except RuntimeError:
            pass
