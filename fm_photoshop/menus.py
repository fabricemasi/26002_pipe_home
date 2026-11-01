"""Menus de l'éditeur Standard (Qt) : Édition, Sélection, Image, Calque, Réglages, Filtre — une ligne de boutons sous la
barre du haut. Chaque entrée appelle une méthode de `actions.Actions` ou ouvre une fenêtre de `dialogs` : aucune entrée
sans effet. Menus : brique `Menu` du Board (clé « board:ps_<nom> », réglable comme les autres menus contextuels)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QWidget

from . import adjust, dialogs
from .panels import _button


class MenuBar(QWidget):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.session = pane.session
        self.canvas = pane.canvas
        self.actions = pane.canvas.actions
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 8, 2)
        row.setSpacing(2)
        self.buttons = {}
        for key, text in (("edit", "Édition"), ("selection", "Sélection"), ("image", "Image"), ("layer", "Calque"),
                          ("adjust", "Réglages"), ("filter", "Filtre")):
            button = _button(text + " ▾", f"Menu {text}", lambda k=key: self.show_menu(k), self)
            self.buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)

    # -- construction --
    def menu_for(self, key: str):
        from fm_board.ui import _menu
        menu = _menu(self.pane, f"ps_{key}")
        a = self.actions
        add = lambda text, slot: menu.addAction(text).triggered.connect(lambda _c=False, f=slot: QTimer.singleShot(0, f))
        if key == "edit":
            add("Annuler\tCtrl+Z", self.canvas.undo)
            add("Rétablir\tCtrl+Y", self.canvas.redo)
            menu.addSeparator()
            add("Couper\tCtrl+X", a.cut)
            add("Copier\tCtrl+C", a.copy)
            add("Coller dans un nouveau calque\tCtrl+V", a.paste)
            menu.addSeparator()
            add("Remplir avec le premier plan\tAlt+Retour arrière", a.fill_foreground)
            add("Remplir avec l'arrière-plan\tCtrl+Retour arrière", a.fill_background)
            add("Effacer\tSuppr", a.delete)
        elif key == "selection":
            add("Tout sélectionner\tCtrl+A", a.select_all)
            add("Désélectionner\tCtrl+D", a.deselect)
            add("Inverser\tCtrl+Maj+I", a.invert_selection)
            menu.addSeparator()
            add("Contour progressif…", lambda: self._value("Contour progressif", "Rayon", 1, 250, 8, a.feather))
            add("Agrandir…", lambda: self._value("Agrandir la sélection", "Pixels", 1, 100, 4, a.grow))
            add("Contracter…", lambda: self._value("Contracter la sélection", "Pixels", 1, 100, 4, a.shrink))
            menu.addSeparator()
            add("Calque via copier\tCtrl+J", a.layer_via_copy)
            add("Calque via couper\tCtrl+Maj+J", a.layer_via_cut)
            menu.addSeparator()
            add("Plage de couleurs (couleur de premier plan)", lambda: a.select_color_range(
                self.session.options["tolerance"]))
            add("Baguette : tolérance…", self._wand_options)
        elif key == "image":
            add("Taille de l'image…", lambda: self._size(False))
            add("Taille de la zone de travail…", lambda: self._size(True))
            add("Recadrer sur la sélection", a.crop_to_selection)
            menu.addSeparator()
            add("Profil colorimétrique…", self._profile)
            add("Informations et diagnostic…", self._diagnostic)
            menu.addSeparator()
            add("Symétrie horizontale du document", lambda: a.flip_document(True))
            add("Symétrie verticale du document", lambda: a.flip_document(False))
            menu.addSeparator()
            add("Aplatir l'image", self.pane.layers_panel.flatten)
        elif key == "layer":
            add("Transformation libre\tCtrl+T", self.canvas.start_free_transform)
            add("Transformer (valeurs)…", self._transform)
            add("Modifier le texte / la forme…", self._edit_source)
            add("Convertir en pixels", a.rasterize)
            add("Symétrie horizontale du calque", lambda: a.layer_flip(True))
            add("Symétrie verticale du calque", lambda: a.layer_flip(False))
            menu.addSeparator()
            add("Nouveau calque", self.pane.layers_panel.add)
            add("Nouveau groupe / grouper la sélection\tCtrl+G", self.pane.layers_panel.add_group)
            add("Dupliquer le calque", self.pane.layers_panel.duplicate)
            add("Supprimer le calque", self.pane.layers_panel.remove)
            add("Fusionner avec le calque inférieur", self.pane.layers_panel.merge)
            menu.addSeparator()
            add("Exporter ce calque…", self._export_layer)
        else:
            for name, (label, kind, *_rest) in adjust.EFFECTS.items():
                if (key == "adjust") == (kind == "rgb"):
                    add(label + "…" if adjust.EFFECTS[name][2] or name in ("curves", "color_balance") else label,
                        lambda n=name: self.effect(n))
            if key == "adjust":
                menu.addSeparator()
                for name, (label, kind, *_rest) in adjust.EFFECTS.items():
                    if kind == "rgb":
                        add("Nouveau calque de réglage : " + label + "…", lambda n=name: self.adjustment_layer(n))
        return menu

    def show_menu(self, key: str):
        menu = self.menu_for(key)
        button = self.buttons[key]
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))
        self._menu = menu

    # -- entrées avec fenêtre --
    def effect(self, name: str):
        layer = self.session.layer()
        if layer.locked or layer.is_group() or layer.pix is None:
            self.canvas.message.emit("Choisissez un calque de pixels non verrouillé.")
            return None
        if not adjust.EFFECTS[name][2] and name not in ("curves", "color_balance"):
            return self.actions.apply_effect(name)                  # sans paramètre (négatif) : appliqué tout de suite
        dialog = dialogs.EffectDialog(self.session, name, self.pane)
        self._dialog = dialog
        dialog.exec()
        return dialog

    def _value(self, title, label, low, high, value, action):
        dialog = dialogs.ValueDialog(title, label, low, high, value, parent=self.pane)
        if dialog.exec():
            action(dialog.value())

    def _size(self, canvas: bool):
        dialog = dialogs.SizeDialog(self.session.doc, canvas, self.pane)
        if dialog.exec():
            w, h = dialog.values()
            if canvas:
                self.actions.canvas_size(w, h, dialog.anchor.currentData())
            else:
                self.actions.image_size(w, h, dialog.quality.currentData())

    def _transform(self):
        layer = self.session.layer()
        if layer.locked:
            self.canvas.message.emit("Le calque est verrouillé.")
            return
        if layer.source:
            self.canvas.message.emit(self.actions.REFUSED)
            return
        dialog = dialogs.TransformDialog(self.session, self.pane)
        self._dialog = dialog
        dialog.exec()

    def _wand_options(self):
        dialog = dialogs.ValueDialog("Baguette magique", "Tolérance", 0, 255, self.session.options["tolerance"], "",
                                     self.pane)
        if dialog.exec():
            self.session.options["tolerance"] = dialog.value()

    def _export_layer(self):
        self.pane.export(None, self.session.layer())

    def adjustment_layer(self, name: str):
        """Nouveau calque de réglage (non destructif) au-dessus du calque actif, avec sa fenêtre."""
        layer, command = self.actions.add_adjustment(name)
        self.session.notify("structure", None)
        dialog = dialogs.AdjustmentLayerDialog(self.session, self.actions, layer, command, self.pane)
        self._dialog = dialog
        dialog.exec()
        return dialog

    def _edit_source(self):
        layer = self.session.layer()
        if layer.is_adjustment():
            dialog = dialogs.AdjustmentLayerDialog(self.session, self.actions, layer, None, self.pane)
            self._dialog = dialog
            dialog.exec()
            return
        kind = (layer.source or {}).get("kind")
        if kind == "text":
            dialog = dialogs.TextDialog(self.session, self.actions, layer, (0, 0), self.pane)
        elif kind == "shape":
            dialog = dialogs.ShapeDialog(self.session, self.actions, layer, self.pane)
        else:
            self.canvas.message.emit("Ce calque n'est ni un texte ni une forme.")
            return
        self._dialog = dialog
        dialog.exec()

    def _profile(self):
        dialog = dialogs.ProfileDialog(self.session, self.pane)
        self._dialog = dialog
        dialog.exec()

    def _diagnostic(self):
        from PySide6.QtWidgets import QMessageBox
        from . import diagnostics
        QMessageBox.information(self.pane, "Informations et diagnostic",
                                diagnostics.report(self.session.doc, self.session))
