"""Éditeur STANDARD (Qt) : le document d'un élément du Board en plein cadre, sur le modèle du Tableur et de fm_markdown
(le module recouvre toute la zone de travail, une barre en haut, un bouton pour revenir).

Même session que l'élément (document, historique, outil, brosse, calque actif, zoom, position) : l'ouvrir ne recharge
ni ne copie rien ; revenir au Board rend la main à l'élément, qui affiche la même composition (mêmes tuiles). Le
panneau est enfant du `BoardPane` : barres et raccourcis du Board sont dessous, intacts ; Ctrl+S enregistre le board."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from . import io_images
from .canvas import CanvasView
from .panels import BrushPanel, LayersPanel, _button

TOOL_ROWS = (("brush", "Pinceau", "Pinceau (B)"), ("eraser", "Gomme", "Gomme (E)"),
             ("eyedropper", "Pipette", "Pipette (I) — Alt + clic avec le pinceau"),
             ("move", "Déplacer", "Déplacer le calque (V) : Ctrl + glisser"), ("hand", "Main", "Main (H, ou Espace)"))


class StandardPane(QWidget):
    @classmethod
    def open(cls, board, item):
        current = getattr(board, "_photoshop_standard", None)
        if current is not None:
            if current.item is item:
                return current
            current.close_pane()
        pane = cls(board, item)
        board._photoshop_standard = pane
        pane.show()
        pane.raise_()
        pane.canvas.setFocus()
        return pane

    def __init__(self, board, item):
        super().__init__(board)
        from settings_store import M
        from settings_theme import _set_text_role
        self.board, self.item = board, item
        self.session = item.session
        self.session.standard_open = True
        self.setObjectName("PhotoshopStandard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#PhotoshopStandard {{ background: {M.get('panel_bg', '#1e1f22')}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(8, 4, 8, 2)
        self.back = _button("↩ Retour au Board", "Revenir au Board (le document reste ouvert dans son élément)",
                            self.close_pane, self)
        self.title = QLabel(self)
        _set_text_role(self.title, "value")
        self.state = QLabel(self)
        _set_text_role(self.state, "value_muted")
        self.status = QLabel(self)
        _set_text_role(self.status, "value_muted")
        top.addWidget(self.back)
        top.addSpacing(12)
        top.addWidget(self.title, 1)
        top.addWidget(self.status)
        top.addWidget(self.state)
        top.addWidget(_button("Annuler", "Ctrl+Z", lambda: self.canvas.undo(), self))
        top.addWidget(_button("Rétablir", "Ctrl+Y", lambda: self.canvas.redo(), self))
        top.addWidget(_button("Ajuster", "Tout voir (Ctrl+0)", lambda: self.canvas.fit(), self))
        top.addWidget(_button("100 %", "Taille réelle (Ctrl+1)", lambda: self.canvas.set_zoom(1.0), self))
        top.addWidget(_button("Importer…", "Ajouter une image comme nouveau calque", self.import_layer, self))
        top.addWidget(_button("Enregistrer", "Ctrl+S", self._save, self))
        top.addWidget(_button("Exporter…", "Composition ou calque : PNG, TIFF, JPEG, WebP", self.export, self))
        layout.addLayout(top)
        body = QHBoxLayout()
        body.setContentsMargins(6, 2, 6, 6)
        body.setSpacing(6)
        tools = QVBoxLayout()
        tools.setSpacing(2)
        self.tool_buttons = {}
        for tool, text, tip in TOOL_ROWS:
            button = _button(text, tip, lambda t=tool: self.canvas.set_tool(t), self, True)
            button.setFixedWidth(78)
            self.tool_buttons[tool] = button
            tools.addWidget(button)
        tools.addStretch(1)
        body.addLayout(tools)
        self.canvas = CanvasView(self.session, self)
        body.addWidget(self.canvas, 1)
        side = QVBoxLayout()
        side.setSpacing(8)
        self.brush_panel = BrushPanel(self.session, self.canvas, self)
        self.layers_panel = LayersPanel(self.session, self.canvas, self)
        side.addWidget(self.brush_panel)
        side.addWidget(self.layers_panel, 1)
        holder = QWidget(self)
        holder.setLayout(side)
        holder.setFixedWidth(330)
        body.addWidget(holder)
        layout.addLayout(body, 1)
        self.canvas.toolChanged.connect(self._sync_tools)
        self.canvas.message.connect(self.status.setText)
        self.session.listeners.append(self._on_session)
        self._sync_tools()
        self._sync_title()
        board.installEventFilter(self)
        self.setGeometry(board.rect())
        if hasattr(board, "dirtyChanged"):
            board.dirtyChanged.connect(self._sync_title)

    # -- état --
    def _sync_tools(self, *_):
        for tool, button in self.tool_buttons.items():
            button.setChecked(tool == self.session.tool)

    def _on_session(self, kind, _rect):
        if kind in ("committed", "structure", "edit"):
            QTimer.singleShot(0, self._sync_title)

    def _sync_title(self, *_args):
        try:
            where = getattr(self.board, "path", None) or getattr(self.board, "source", None)
            name = self.item.data.get("title") or self.session.doc.name
            self.title.setText(f"{name} — {where.name}" if where is not None else name)
            dirty = getattr(self.board, "is_dirty", lambda: False)() or self.session.is_dirty()
            self.state.setText("modifié" if dirty else "enregistré")
        except RuntimeError:
            pass

    # -- fichiers --
    def _save(self):
        self.layers_panel.commit_live()
        if hasattr(self.board, "save"):
            self.board.save()
        self._sync_title()

    def import_layer(self, path: str | None = None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, "Importer une image", "", io_images.OPEN_FILTER)
            if not path:
                return None
        from . import ops
        try:
            rgba, _dpi, _icc, notes = io_images.import_image(path)
        except io_images.ImageError as exc:
            QMessageBox.warning(self, "Import impossible", str(exc))
            return None
        s = self.session
        layer, cmd = ops.add_layer_with_pixels(s.doc, rgba, 0, 0, Path(path).stem,
                                               index=s.doc.parent_list(s.layer())[1] + 1)
        s.do(cmd)
        s.select_layer(layer)
        if notes:
            self.status.setText(" ".join(notes))
        return layer

    def export(self, path: str | None = None, layer=None):
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self, "Exporter", f"{self.session.doc.name}.png",
                                                   io_images.SAVE_FILTER)
            if not path:
                return None
        try:
            notes = io_images.export_document(self.session.doc, path, layer=layer)
        except (io_images.ImageError, OSError) as exc:
            QMessageBox.warning(self, "Export impossible", f"{Path(path).name} :\n{exc}")
            return None
        self.status.setText(" ".join(notes) or f"Exporté : {Path(path).name}")
        return notes

    def eventFilter(self, obj, event):
        if obj is self.board and event.type() == QEvent.Resize:
            self.setGeometry(self.board.rect())
        return super().eventFilter(obj, event)

    def close_pane(self):
        """Retour au Board : rien n'est recopié, l'élément affiche la même session."""
        self.layers_panel.commit_live()
        try:
            self.board.removeEventFilter(self)
        except RuntimeError:
            pass
        if self._on_session in self.session.listeners:
            self.session.listeners.remove(self._on_session)
        self.canvas.detach()
        self.layers_panel.detach()
        self.session.standard_open = False
        if getattr(self.board, "_photoshop_standard", None) is self:
            self.board._photoshop_standard = None
        self.hide()
        self.deleteLater()
        try:
            self.item.standard_closed()
            view = getattr(self.board, "view", None)
            if view is not None:
                view.setFocus()
        except RuntimeError:
            pass
