"""Actions d'édition sur la session (Qt léger : presse-papiers) : sélection, remplir, effacer, copier / couper / coller,
calque via copier / couper, réglages et filtres, transformations du calque, taille de l'image, recadrage.
Chaque action modifie le document ET pousse UNE étape d'annulation ; les menus, les raccourcis et les tests appellent
les mêmes méthodes.

COMPORTEMENT EXPLICITE du « déplacer une sélection et son contenu » : « Calque via copier » (Ctrl+J) et « Calque via
couper » (Ctrl+Maj+J) isolent le contenu sélectionné dans un NOUVEAU calque (à son emplacement) que l'outil Déplacer
(Ctrl + glisser) déplace ; rien n'est déplacé à l'insu de l'utilisateur."""
from __future__ import annotations

import numpy as np

from . import adjust, compose as C, ops, selection as S, transform as T
from .history import Compound, SelectionCommand, TilesCommand
from .planes import rect_intersect

_CLIP = {"rgba": None, "origin": (0, 0)}                  # presse-papiers interne du module (toutes sessions)


class Actions:
    def __init__(self, session):
        self.s = session
        self.last_message = ""

    # -- aides --
    @property
    def doc(self):
        return self.s.doc

    REFUSED = "Calque de texte ou de forme : convertissez-le d'abord en pixels (menu Calque)."

    def _say(self, text):
        self.last_message = text
        return text

    def _region(self, layer):
        """Zone de travail d'une action sur `layer` : sélection ∩ document (sinon le document)."""
        sel = self.s.selection
        if sel is not None and not sel.is_empty():
            return rect_intersect(sel.bounds(), self.doc.rect())
        return self.doc.rect()

    # -- sélection --
    def set_selection(self, sel, label="Sélection"):
        before = self.s.selection

        def apply(value):
            self.s.selection = value
            self.s.notify("selection", None)
        apply(sel)
        self.s.do(SelectionCommand(label, apply, before, sel), notified=True)
        return sel

    def select_all(self):
        return self.set_selection(S.select_all(self.doc.rect()), "Tout sélectionner")

    def deselect(self):
        if self.s.selection is None:
            return None
        return self.set_selection(None, "Désélectionner")

    def invert_selection(self):
        sel = self.s.selection
        if sel is None:
            return self.select_all()
        return self.set_selection(S.invert(self.doc.rect(), sel), "Inverser la sélection")

    def feather(self, radius: float):
        if self.s.selection is None:
            return self._say("Aucune sélection.")
        return self.set_selection(S.feather(self.doc.rect(), self.s.selection, radius), "Contour progressif")

    def grow(self, pixels: int):
        if self.s.selection is None:
            return self._say("Aucune sélection.")
        return self.set_selection(S.resize(self.doc.rect(), self.s.selection, abs(int(pixels))), "Agrandir la sélection")

    def shrink(self, pixels: int):
        if self.s.selection is None:
            return self._say("Aucune sélection.")
        return self.set_selection(S.resize(self.doc.rect(), self.s.selection, -abs(int(pixels))),
                                  "Contracter la sélection")

    def combine_selection(self, new, mode="replace", label="Sélection"):
        return self.set_selection(S.combine(self.doc.rect(), self.s.selection, new, mode) if new is not None else None,
                                  label)

    def wand_at(self, x, y, tolerance=32, contiguous=True, mode="replace", sample="layer"):
        rect = self.doc.rect()
        if sample == "layer":
            rgba = self.s.layer().pix.read(rect) if self.s.layer().pix is not None else None
        else:
            rgba = C.flatten_u8(self.doc)
        if rgba is None:
            return None
        new = S.wand(rect, rgba, int(x), int(y), tolerance, contiguous)
        return self.combine_selection(new, mode, "Baguette magique")

    def select_color_range(self, tolerance=32, mode="replace"):
        """Sélection par couleur : tous les pixels du calque proches de la couleur de premier plan (contigus ou non)."""
        layer = self.s.layer()
        if layer.is_group() or layer.pix is None or layer.pix.rect() is None:
            return self._say("Choisissez un calque de pixels.")
        rgba = layer.pix.read(self.doc.rect())
        return self.combine_selection(S.color_range(self.doc.rect(), rgba, self.s.fg, int(tolerance)), mode,
                                      "Plage de couleurs")

    # -- remplir / effacer --
    def fill(self, color, label="Remplir"):
        layer = self.s.layer()
        if layer.source and self.s.target != "mask":
            return self._say(self.REFUSED)
        if layer.locked or layer.is_group() or (layer.pix is None and self.s.target != "mask"):
            return self._say("Calque verrouillé, groupe ou réglage : rien à remplir.")
        region = self._region(layer)
        if region is None:
            return None
        if self.s.target == "mask" and layer.mask is not None:
            value = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            plane = layer.mask.plane
            before = plane.read(region)
            cover = (np.ones(before.shape[:2], np.float32) if not self.s.selection else
                     self.s.selection.coverage(region))
            after = np.clip(before[..., 0] + (value - before[..., 0]) * cover + 0.5, 0, 255).astype(np.uint8)[..., None]
            if np.array_equal(before, after):
                return None
            plane.write(region, after)
            self.s.notify("paint", region)
            return self.s.do(TilesCommand(label + " (masque)", layer, "mask", [(region, before, after)]), notified=True)
        rgba = tuple(color[:3]) + (color[3] if len(color) > 3 else 255,)
        command = ops.fill_rect(layer, region, rgba, self.s.selection, label)
        self.s.notify("paint", region)
        return self.s.do(command, notified=True)

    def fill_foreground(self):
        return self.fill(self.s.fg, "Remplir avec le premier plan")

    def fill_background(self):
        return self.fill(self.s.bg, "Remplir avec l'arrière-plan")

    def delete(self):
        layer = self.s.layer()
        if layer.source and self.s.target != "mask":
            return self._say(self.REFUSED)
        if layer.locked or layer.is_group() or layer.pix is None:
            return self._say("Calque verrouillé ou groupe : rien à effacer.")
        if self.s.target == "mask" and layer.mask is not None:
            return self.fill(self.s.bg, "Effacer")
        command = self._cut_content(layer, "Effacer")
        if command is None:
            return None
        self.s.notify("paint", command.rect)
        return self.s.do(command, notified=True)

    def _cut_content(self, layer, label="Couper"):
        """Efface (alpha × (1 − couverture)) le contenu sélectionné du calque ; rend l'étape SANS la pousser."""
        mine = layer.pix.rect()
        if mine is None:
            return None
        sel = self.s.selection
        region = rect_intersect(mine, sel.bounds()) if sel is not None and sel.bounds() else mine
        if region is None:
            return None
        before = layer.pix.read(region)
        cover = sel.coverage(region) if sel is not None else np.ones(before.shape[:2], np.float32)
        after = before.copy()
        after[..., 3] = np.clip(before[..., 3] * (1.0 - cover) + 0.5, 0, 255).astype(np.uint8)
        return ops.replace_pixels(layer, region, after, label)

    # -- presse-papiers --
    def _selected_pixels(self, layer):
        """(RGBA droit avec alpha × couverture, origine) du contenu sélectionné du calque, ou None."""
        mine = layer.pix.rect() if layer.pix is not None else None
        if mine is None:
            return None
        sel = self.s.selection
        region = rect_intersect(mine, sel.bounds()) if sel is not None and sel.bounds() else mine
        if region is None:
            return None
        data = layer.pix.read(region)
        if sel is not None:
            data[..., 3] = np.clip(data[..., 3] * sel.coverage(region) + 0.5, 0, 255).astype(np.uint8)
        if not data[..., 3].any():
            return None
        return data, (region[0], region[1])

    def copy(self):
        got = self._selected_pixels(self.s.layer())
        if got is None:
            return self._say("Rien à copier.")
        _CLIP["rgba"], _CLIP["origin"] = got
        self._to_system_clipboard(got[0])
        return True

    def copy_merged(self):
        """« Copier avec fusion » (Ctrl+Maj+C) : l'image FINALE affichée, tous les calques visibles composés (masques, modes et
        réglages compris), dans la sélection s'il y en a une, sinon le document entier. Ctrl+C copie, lui, le seul calque en cours."""
        region = self._region(self.s.layer())
        if region is None:
            return self._say("Rien à copier.")
        data = C.flatten_u8(self.doc, region)
        sel = self.s.selection
        if sel is not None and not sel.is_empty():
            data[..., 3] = np.clip(data[..., 3] * sel.coverage(region) + 0.5, 0, 255).astype(np.uint8)
        if not data[..., 3].any():
            return self._say("Rien à copier : l'image est transparente.")
        _CLIP["rgba"], _CLIP["origin"] = data, (region[0], region[1])
        self._to_system_clipboard(data)
        return True

    def cut(self):
        if self.copy() is not True:
            return None
        return self.delete()

    @staticmethod
    def _to_system_clipboard(rgba):
        from PySide6.QtGui import QGuiApplication, QImage
        app = QGuiApplication.instance()
        if app is None:
            return
        data = np.ascontiguousarray(rgba)
        image = QImage(data.data, data.shape[1], data.shape[0], data.shape[1] * 4, QImage.Format_RGBA8888).copy()
        app.clipboard().setImage(image)

    @staticmethod
    def _from_system_clipboard():
        from PySide6.QtGui import QGuiApplication, QImage
        app = QGuiApplication.instance()
        if app is None:
            return None
        image = app.clipboard().image()
        if image.isNull():
            return None
        image = image.convertToFormat(QImage.Format_RGBA8888)
        ptr = image.constBits()
        array = np.frombuffer(ptr, np.uint8, image.height() * image.bytesPerLine()).reshape(image.height(),
                                                                                          image.bytesPerLine())
        return array[:, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()   # COPIE : le tampon appartient a QImage

    def paste(self):
        """Colle dans un NOUVEAU calque : image du presse-papiers du système si elle y est, sinon la copie interne."""
        rgba = self._from_system_clipboard()
        origin = None
        if rgba is None and _CLIP["rgba"] is not None:
            rgba, origin = _CLIP["rgba"], _CLIP["origin"]
        if rgba is None:
            return self._say("Le presse-papiers ne contient pas d'image.")
        h, w = rgba.shape[:2]
        if origin is None or (_CLIP["rgba"] is not None and _CLIP["rgba"].shape != rgba.shape):
            origin = (max(0, (self.doc.width - w) // 2), max(0, (self.doc.height - h) // 2))
        return self._new_layer_with(rgba, origin, "Calque collé")

    def _new_layer_with(self, rgba, origin, name):
        index = self.doc.parent_list(self.s.layer())[1] + 1
        layer, command = ops.add_layer_with_pixels(self.doc, rgba, origin[0], origin[1], name, index=index)
        self.s.do(command)
        self.s.select_layer(layer)
        return layer

    def layer_via_copy(self):
        got = self._selected_pixels(self.s.layer())
        if got is None:
            return self._say("Rien à copier dans un nouveau calque.")
        return self._new_layer_with(got[0], got[1], self.s.layer().name + " copie")

    def layer_via_cut(self):
        layer = self.s.layer()
        if layer.source:
            return self._say(self.REFUSED)
        got = self._selected_pixels(layer)
        if got is None or layer.locked:
            return self._say("Rien à couper dans un nouveau calque.")
        data, origin = got
        cut = self._cut_content(layer)
        index = self.doc.parent_list(layer)[1] + 1
        created, add = ops.add_layer_with_pixels(self.doc, data, origin[0], origin[1], layer.name + " découpé",
                                                 index=index)
        self.s.do(Compound("Calque via couper", [c for c in (cut, add) if c is not None]))
        self.s.select_layer(created)
        return created

    # -- réglages et filtres --
    def apply_effect(self, name, params=None, seed=0):
        layer = self.s.layer()
        if layer.source:
            return self._say(self.REFUSED)
        if layer.locked or layer.is_group() or layer.pix is None:
            return self._say("Choisissez un calque de pixels non verrouillé.")
        got = adjust.run(layer, name, params, self.s.selection, self.doc.rect(), seed)
        if got is None:
            return self._say("Ce réglage ne change rien.")
        rect, _before, after = got
        command = ops.replace_pixels(layer, rect, after, adjust.EFFECTS[name][0])
        self.s.notify("paint", rect)
        return self.s.do(command, notified=True)

    # -- transformations --
    def transform_layer(self, matrix, quality="bicubic", label="Transformation"):
        layer = self.s.layer()
        if layer.locked:
            return self._say("Le calque est verrouillé.")
        if layer.source:
            return self._say(self.REFUSED)
        session = T.TransformSession(layer)
        session.render(matrix, quality)
        return self.s.do(session.command(quality, label))

    def layer_flip(self, horizontal: bool):
        layer = self.s.layer()
        rect = ops.layer_rect(layer)
        if rect is None:
            return None
        cx, cy = (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0
        return self.transform_layer(T.flip(horizontal, cx, cy), "nearest",
                                    "Symétrie horizontale du calque" if horizontal else "Symétrie verticale du calque")

    # -- texte et formes --
    def _insert_source_layer(self, source, name):
        from . import vector
        index = self.doc.parent_list(self.s.layer())[1] + 1
        layer, command = ops.add_layer(self.doc, name, parent=self.doc.parent_of(self.s.layer()), index=index)
        vector.apply_source(layer, source)
        return layer, command

    def add_text(self, source: dict):
        """Nouveau calque de texte éditable (une étape d'annulation)."""
        from . import vector
        source = vector.normalize(dict(source, kind="text"))
        name = (source["content"].strip().splitlines() or ["Texte"])[0][:24] or "Texte"
        layer, command = self._insert_source_layer(source, name)
        self.s.do(command)
        self.s.select_layer(layer)
        return layer

    def add_shape(self, source: dict):
        from . import vector
        source = vector.normalize(dict(source, kind="shape"))
        name = {"rect": "Rectangle", "ellipse": "Ellipse", "line": "Ligne"}[source["shape"]]
        layer, command = self._insert_source_layer(source, name)
        self.s.do(command)
        self.s.select_layer(layer)
        return layer

    def edit_source(self, layer, new_source: dict, label="Modifier le calque"):
        """Remplace la source d'un calque de texte / forme et refait ses pixels (une étape)."""
        from . import vector
        old = self._source_state(layer)
        vector.apply_source(layer, new_source)
        new = self._source_state(layer)
        if old[0] == new[0]:
            return None
        rect = ops.layer_rect(layer)
        for state in (old, new):
            if state[2] is not None:
                r = (state[1][0], state[1][1], state[1][0] + state[2].shape[1], state[1][1] + state[2].shape[0])
                rect = r if rect is None else (min(rect[0], r[0]), min(rect[1], r[1]), max(rect[2], r[2]),
                                               max(rect[3], r[3]))
        from .history import CallCommand
        command = CallCommand(label, lambda: self._restore_source(layer, new), lambda: self._restore_source(layer, old),
                              rect=rect)
        self.s.notify("edit", rect)
        return self.s.do(command, notified=True)

    @staticmethod
    def _source_state(layer):
        import copy
        data = None if layer.pix.data is None else layer.pix.data.copy()
        return copy.deepcopy(layer.source), (layer.pix.x, layer.pix.y), data, layer.name

    @staticmethod
    def _restore_source(layer, state):
        import copy
        source, (x, y), data, name = state
        layer.source = copy.deepcopy(source)
        layer.name = name
        if data is None:
            layer.pix.clear()
        else:
            layer.pix.set_all(x, y, data.copy())

    def rasterize(self, layer=None):
        """Conversion EXPLICITE en pixels : le calque perd sa source (plus modifiable comme texte / forme)."""
        layer = layer or self.s.layer()
        if not layer.source:
            return self._say("Ce calque est déjà en pixels.")
        old = layer.source
        from .history import CallCommand

        def do():
            layer.source = None

        def undo():
            layer.source = old
        do()
        return self.s.do(CallCommand("Convertir en pixels", do, undo))

    def add_adjustment(self, effect: str, params: dict | None = None):
        """Nouveau calque de réglage au-dessus du calque actif ; rend (calque, étape non poussée)."""
        index = self.doc.parent_list(self.s.layer())[1] + 1
        return ops.add_adjustment(self.doc, effect, params, self.doc.parent_of(self.s.layer()), index)

    # -- plusieurs calques sélectionnés --
    def group_selected(self):
        layers = self.s.selected_layers()
        if len(layers) < 2:
            return self._say("Sélectionnez au moins deux calques (Ctrl + clic dans la liste).")
        try:
            group, command = ops.group_layers(self.doc, layers)
        except ValueError as exc:
            return self._say(str(exc))
        self.s.do(command)
        self.s.select_layer(group)
        return group

    def remove_selected(self):
        layers = self.s.selected_layers()
        commands = []
        for layer in layers:
            try:
                commands.append(ops.remove_layer(self.doc, layer))
            except ValueError as exc:
                self._say(str(exc))
                break
        if not commands:
            return None
        self.s.do(commands[0] if len(commands) == 1 else Compound("Supprimer les calques", commands))
        self.s.select_layer(self.doc.layers[-1])
        return len(commands)

    def duplicate_selected(self):
        twins, commands = [], []
        for layer in self.s.selected_layers():
            twin, command = ops.duplicate_layer(self.doc, layer)
            twins.append(twin)
            commands.append(command)
        if not commands:
            return None
        self.s.do(commands[0] if len(commands) == 1 else Compound("Dupliquer les calques", commands))
        self.s.select_layer(twins[-1])
        self.s.multi = [t.uid for t in twins]
        self.s.notify("view", None)
        return twins

    def image_size(self, width, height, quality="bicubic"):
        return self.s.do(T.resize_image(self.doc, width, height, quality))

    def canvas_size(self, width, height, anchor=(0.5, 0.5)):
        return self.s.do(T.canvas_size(self.doc, width, height, anchor))

    def crop_to_selection(self):
        sel = self.s.selection
        bounds = sel.bounds() if sel is not None else None
        if bounds is None:
            return self._say("Faites d'abord une sélection à recadrer.")
        selection_cmd = self.deselect()
        return self.s.do(T.crop(self.doc, bounds))

    def flip_document(self, horizontal: bool):
        return self.s.do(T.flip_canvas(self.doc, horizontal))
