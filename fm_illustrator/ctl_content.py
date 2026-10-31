"""Contenu du document, côté contrôleur Illustrator (mélangé à `IllustratorController`) : calques, textes
(création, édition sur place, attributs, contours), images placées et vectorisation, plans de travail,
export SVG / PDF, import SVG."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer

from fm_board import model as board_model
from . import bezier as bz, layers as lay, look, model
from .items import IllArtboardItem, IllImageItem, IllLayerItem, IllPathItem, IllTextItem


class ContentMixin:
    """Contenu, côté `IllustratorController` (voir le docstring du fichier)."""

    # -- images placées --
    IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")


    def place_image(self, path, at: QPointF | None = None, asset: str | None = None) -> IllImageItem | None:
        """Importer (Ctrl+Maj+P) : l'image est copiée dans le dossier du board (incorporée), posée à 100 % (1 pixel =
        1 unité), centrée sur `at` (le centre de la vue par défaut) ; une étape (calque créé au besoin compris)."""
        from PySide6.QtGui import QImageReader
        from fm_board import serialization
        board = getattr(self.scene, "board_path", None)
        if board is None:
            return None
        try:
            name = asset or serialization.import_asset(board, path)
        except OSError:
            return None
        size = QImageReader(str(serialization.asset_path(board, name))).size()
        if not size.isValid():
            return None
        w, h = float(size.width()), float(size.height())
        at = at or self.view.view_center()
        layer = self.ensure_layer()
        data = board_model.new_item(model.IMAGE, asset=name, w=w, h=h, x=round(at.x() - w / 2, 3),
                                    y=round(at.y() - h / 2, 3), layer=layer.item_id)
        data["z"] = lay.top_z(self.scene, layer, self.objects())
        item = self.scene._add(data)
        self.commit_new(item, "Importer une image")
        return item


    def place_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        start = getattr(self.scene, "board_path", None)
        patterns = " ".join("*" + s for s in self.IMAGE_SUFFIXES + (".svg",))
        paths, _f = QFileDialog.getOpenFileNames(self.pane, "Importer", str(start.parent) if start else "",
                                                 f"Images et SVG ({patterns})")
        at = self.view.view_center()
        for n, path in enumerate(paths):
            from pathlib import Path
            p = Path(path)
            if p.suffix.lower() == ".svg":
                self.import_svg(p, at)
            else:
                self.place_image(p, at + QPointF(20 * n, 20 * n))


    # -- vectorisation (trace.py) --
    def image_pixels(self, image: IllImageItem, detail: int):
        """Pixels RVBA (tableau numpy H × W × 4) de l'image, réduite à `detail` px de grand côté au plus, et la
        matrice qui ramène la grille tracée au repère de l'élément."""
        import numpy as np
        from PySide6.QtGui import QImage, QImageReader
        from fm_board import serialization
        board = getattr(self.scene, "board_path", None)
        if board is None:
            return None, None
        reader = QImageReader(str(serialization.asset_path(board, image.data.get("asset", ""))))
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid():
            return None, None
        if max(size.width(), size.height()) > detail:
            size.scale(detail, detail, Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        picture = reader.read()
        if picture.isNull():
            return None, None
        picture = picture.convertToFormat(QImage.Format_RGBA8888)
        w, h = picture.width(), picture.height()
        raw = np.frombuffer(picture.constBits(), dtype=np.uint8, count=picture.sizeInBytes())
        pixels = raw.reshape(h, picture.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()
        to_item = bz.multiply(bz.scale(float(image.data["w"]) / w, float(image.data["h"]) / h),
                              tuple(image.data.get("matrix") or bz.IDENTITY))
        return pixels, to_item


    def trace_image(self, settings: dict | None = None, background: bool = True, image=None):
        """Vectoriser l'image choisie (ou `image`) : calcul en FIL DE FOND (l'interface reste libre ; la bulle montre
        l'avancement), puis l'image est remplacée par un groupe de tracés, une étape. `background=False` : tout de
        suite (tests)."""
        from . import trace as tr
        if image is None:
            images = [i for i in self.selection() if isinstance(i, IllImageItem)]
            if not images:
                return None
            image = images[-1]
        settings = dict(settings or self.trace_settings)
        pixels, to_item = self.image_pixels(image, int(settings.get("detail", 500)))
        if pixels is None:
            return None
        if not background:
            return self._apply_trace(image, tr.trace(pixels, settings), to_item)
        import threading
        from PySide6.QtCore import QObject as _QObject, Signal as _Signal

        class Relay(_QObject):
            done = _Signal(object)
            step = _Signal(int, int)
        relay = Relay(self)
        self._trace_relay = relay                           # gardé : le fil lui envoie le résultat
        relay.step.connect(lambda n, total: self._trace_tip(image, f"Vectorisation… {n} / {total}"))
        relay.done.connect(lambda result: self._finish_trace(image, result, to_item))
        self._trace_tip(image, "Vectorisation…")

        def work():
            try:
                result = tr.trace(pixels, settings, progress=lambda n, total: relay.step.emit(n, total))
            except Exception as exc:                        # noqa: BLE001 - montré dans la bulle
                result = exc
            relay.done.emit(result)
        threading.Thread(target=work, daemon=True, name="vectorisation").start()
        return True


    def _trace_tip(self, image, text: str):
        if image.scene() is not None:
            self.tip = (image.geometry_rect().center(), text)
            self.refresh()


    def _finish_trace(self, image, result, to_item):
        self.tip = None
        self._trace_relay = None
        if isinstance(result, Exception) or image.scene() is None:
            self.refresh()
            return None
        return self._apply_trace(image, result, to_item)


    def _apply_trace(self, image, result, to_item):
        if not result:
            return []
        gid = board_model.new_id()
        z = image.zValue()
        added = []
        for n, (color, subs) in enumerate(result):
            subs = bz.copy_subpaths(subs)
            bz.transform(subs, to_item)
            added.append(board_model.new_item(model.PATH, x=image.data["x"], y=image.data["y"], z=z + n * 0.001,
                                              subpaths=subs, fill=color, stroke="", group=gid,
                                              layer=image.data.get("layer", ""), opacity=image.data.get("opacity", 1.0)))
        new = self.scene.replace_items([image], added, "Vectoriser l'image")
        self.select(new)
        self.refresh()
        return new


    def crop_with_mask(self):
        """Recadrer une image : un rectangle à sa taille devient son masque d'écrêtage (à modifier ensuite en
        Sélection directe), groupe et masque en une étape."""
        images = [i for i in self.selection() if isinstance(i, IllImageItem) and not i.mask_item()]
        if not images:
            return
        before, added = {}, []
        for image in images:
            before[image.item_id] = image.to_dict()
            r = image.geometry_rect()
            gid = board_model.new_id()
            image.data = image.to_dict()
            image.data["group"] = gid
            image.apply(image.data)
            mask = board_model.new_item(model.PATH, x=r.x(), y=r.y(), z=image.zValue() + 0.5, group=gid, mask="clip",
                                        subpaths=bz.rect(0, 0, r.width(), r.height()), fill="", stroke="",
                                        layer=image.data.get("layer", ""))
            before[mask["id"]] = None
            added.append(self.scene._add(mask))
        self.scene.push(before, self.scene.snapshot(list(before)), "Recadrer l'image")
        self.select(images + added)


    def _image_href(self, data: dict) -> str:
        """Image incorporée au SVG (URI data:, comme l'option « Incorporer » d'Illustrator)."""
        import base64
        import mimetypes
        from fm_board import serialization
        board = getattr(self.scene, "board_path", None)
        if board is None or not serialization.is_asset_name(data.get("asset", "")):
            return ""
        path = serialization.asset_path(board, data["asset"])
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


    def _resolve_href(self, href: str, base) -> str | None:
        """`<image>` d'un SVG importé -> image du dossier du board (URI data: ou fichier relatif au SVG)."""
        import base64
        import re
        from pathlib import Path
        from urllib.parse import unquote
        from fm_board import serialization
        board = getattr(self.scene, "board_path", None)
        if board is None or not href:
            return None
        m = re.match(r"data:image/([a-z0-9.+-]+);base64,(.*)", href, re.S)
        try:
            if m:
                suffix = {"jpeg": ".jpg", "svg+xml": ".svg"}.get(m.group(1), "." + m.group(1)[:5])
                return serialization.import_image_bytes(board, base64.b64decode(m.group(2)), suffix)
            target = Path(unquote(href.replace("file:///", "")))
            if not target.is_absolute() and base is not None:
                target = Path(base).parent / target
            if target.is_file():
                return serialization.import_asset(board, target)
        except (OSError, ValueError):
            pass
        return None


    # -- texte (text.py) --
    def new_text(self, origin: QPointF, **values) -> IllTextItem:
        """Texte créé SANS étape d'annulation : l'édition qui suit l'enregistre (vide = retiré)."""
        layer = self.ensure_layer()
        style = {k: v for k, v in self.style.items() if k in model.DEFAULTS[model.TEXT]}
        style["fill"] = style.get("fill") or "#000000"
        style.update(font_family=look.value("font"), font_size=round(look.value("text_size") * model.PT, 4))
        if style["fill"] == model.DEFAULT_FILL and self.style.get("stroke"):
            style["fill"] = "#000000"                      # style par défaut (fond blanc) : texte noir, lisible
        style.update(stroke="", stroke_gradient=None)
        if "fill" in values and "fill_gradient" not in values:
            style["fill_gradient"] = None                  # couleur demandée : pas le dégradé du style courant
        style.update(values)
        data = board_model.new_item(model.TEXT, x=round(origin.x(), 3), y=round(origin.y(), 3), **style)
        data["layer"] = layer.item_id
        data["z"] = lay.top_z(self.scene, layer, self.objects())
        return self.scene._add(data)


    def begin_text_edit(self, item: IllTextItem, at: QPointF | None = None, new: bool = False, replaced=None):
        from .text import TextEditor
        self.end_text_edit()
        before = None if new else self.scene.snapshot([item.item_id])
        self._edit = (item, before, new, replaced)
        item.editing = True
        item.update()
        self.select([item])
        self.editor = TextEditor(self, item)
        self.editor.setFocus(Qt.MouseFocusReason)
        self.editor.place_cursor(at)
        self.refresh()
        self.stateChanged.emit()


    def end_text_edit(self):
        """Fin de l'édition : une étape (texte neuf : création ; tracé remplacé par un texte curviligne : les deux)."""
        editor, self.editor = self.editor, None
        edit, self._edit = self._edit, None
        if editor is None or edit is None:
            return
        item, before, new, replaced = edit
        text = editor.toPlainText()
        editor.owner = None
        editor.setVisible(False)
        # Retiré de la scène au passage suivant de la boucle : cette fonction est aussi appelée depuis le
        # focusOutEvent de l'éditeur (le retirer pendant son propre événement ferait planter Qt).
        QTimer.singleShot(0, lambda e=editor: e.scene() is not None and e.scene().removeItem(e))
        item.editing = False
        if item.scene() is None:
            return
        if new and not text.strip():
            self.discard(item)
            if replaced is not None:
                replaced.setVisible(True)
            self.refresh()
            return
        item.prepareGeometryChange()
        item.data["text"] = text
        item.sync()
        item.update()
        if new:
            ids = [item.item_id]
            layer, self._pending_layer = self._pending_layer, None
            if layer is not None and layer.scene() is not None:
                ids.insert(0, layer.item_id)
            before = {i: None for i in ids}
            if replaced is not None:
                before[replaced.item_id] = replaced.to_dict()
                self.scene._remove(replaced.item_id)
            after = self.scene.snapshot(ids)
            if replaced is not None:
                after[replaced.item_id] = None
            self.scene.push(before, after, "Texte")
        else:
            self.scene.push(before, self.scene.snapshot([item.item_id]), "Modifier le texte")
        self.refresh()
        self.stateChanged.emit()


    def set_text_attr(self, key: str, value, text: str = "Texte"):
        items = self.texts()
        if items:
            self.change(items, lambda i: i.data.update({key: value}), text)


    def outline_text(self) -> list:
        """Créer les contours (Ctrl+Maj+O) : chaque texte choisi devient un tracé (lettres en sous-tracés, même
        style, même place) ; le texte n'est plus modifiable (comme Illustrator)."""
        from PySide6.QtGui import QTransform
        from .text import outline_subpaths
        items = self.texts()
        if not items:
            return []
        added = []
        for item in items:
            transform = QTransform().rotate(item.rotation()) if item.rotation() else QTransform()
            subs = outline_subpaths(transform.map(item.path))
            if not subs:
                continue
            data = board_model.new_item(model.PATH, **{k: v for k, v in item.to_dict().items()
                                                     if k in model.DEFAULTS[model.PATH] and k != "subpaths"})
            data.update(x=item.data["x"], y=item.data["y"], z=item.zValue(), subpaths=subs, fill_rule="nonzero")
            added.append(data)
        new = self.scene.replace_items(items, added, "Créer les contours")
        self.select(new)
        return new


    # -- calques (layers.py) --
    def current_layer(self) -> IllLayerItem | None:
        layers = getattr(self.scene, "ill_layers", {})
        if self.layer_id in layers:
            return layers[self.layer_id]
        ordered = lay.layers(self.scene)
        return ordered[-1] if ordered else None


    def set_current_layer(self, layer):
        self.layer_id = layer.item_id if layer is not None else ""
        self.stateChanged.emit()


    def ensure_layer(self) -> IllLayerItem:
        """Calque courant ; le 1er objet d'un dessin crée « Calque 1 » (enregistré avec lui : `_pending_layer`)."""
        layer = self.current_layer()
        if layer is None:
            layer = self.scene._add(lay.new_layer_data(self.scene))
            self._pending_layer = layer
            self.layer_id = layer.item_id
        return layer


    def _flush_pending_layer(self, text: str = "Calque"):
        layer, self._pending_layer = self._pending_layer, None
        if layer is not None and layer.scene() is not None:
            self.scene.push({layer.item_id: None}, self.scene.snapshot([layer.item_id]), text)


    def new_layer(self):
        self.scene.commit_live()
        item = self.scene.add_new(lay.new_layer_data(self.scene), "Nouveau calque", select=False)
        self.set_current_layer(item)
        self.ui.sync_layers()
        return item


    def delete_layer(self, layer):
        if layer is None:
            return
        self.scene.delete_items([layer])
        if self.layer_id == layer.item_id:
            self.layer_id = ""
        self.ui.sync_layers()
        self.refresh()


    def set_layer_flag(self, layer, key: str):
        value = not bool(layer.data.get(key))
        self.scene.change_items([layer], lambda l: l.data.update({key: value}),
                                "Masquer le calque" if key == "hidden" else "Verrouiller le calque",
                                include_locked=True)
        if value:
            self.select([i for i in self.selection() if lay.layer_of(self.scene, i) is not layer])
        self.ui.sync_layers()
        self.refresh()


    def move_layer(self, layer, position: int):
        """Change l'ordre (position dans la liste du panneau, 0 = en haut) ; les objets suivent (bandes de hauteur)."""
        order = list(reversed(lay.layers(self.scene)))
        order.remove(layer)
        order.insert(max(0, min(len(order), position)), layer)
        bottom_up = list(reversed(order))
        index_of = {l.item_id: float(n) for n, l in enumerate(bottom_up)}
        objects = self.objects()
        z_of = {}
        for l in bottom_up:
            base = lay.BAND * (index_of[l.item_id] + 1)
            for rank, item in enumerate(lay.members(self.scene, l, objects)):
                z_of[item.item_id] = base + 1 + rank

        def change(item):
            if isinstance(item, IllLayerItem):
                item.data["index"] = index_of[item.item_id]
            elif item.item_id in z_of:
                item.data["z"] = z_of[item.item_id]
        self.scene.change_items(bottom_up + [o for o in objects if o.item_id in z_of], change, "Ordre des calques",
                                include_locked=True)
        self.ui.sync_layers()
        self.refresh()


    def move_to_layer(self, layer, items=None):
        """Déplace les objets choisis en haut du calque `layer`."""
        items = self.selection() if items is None else items
        if not items or layer is None:
            return
        z = lay.top_z(self.scene, layer, [o for o in self.objects() if o not in items])
        ordered = sorted(items, key=lambda i: i.zValue())
        z_of = {item.item_id: z + n for n, item in enumerate(ordered)}
        self.change(ordered, lambda i: i.data.update(layer=layer.item_id, z=z_of[i.item_id]), "Changer de calque")
        self.ui.sync_layers()


    def select_layer_objects(self, layer):
        self.select([i for i in lay.members(self.scene, layer, self.objects()) if self.editable(i)])


    def layer_menu(self, layer, global_pos):
        from fm_board.ui import _menu
        menu = _menu(self.pane, "ill_layer")
        menu.addAction("Nouveau calque").triggered.connect(self.new_layer)
        menu.addAction("Choisir les objets du calque").triggered.connect(lambda: self.select_layer_objects(layer))
        action = menu.addAction("Déplacer la sélection dans ce calque")
        action.setEnabled(bool(self.selection()))
        action.triggered.connect(lambda: self.move_to_layer(layer))
        menu.addSeparator()
        menu.addAction("Supprimer le calque (et ses objets)").triggered.connect(lambda: self.delete_layer(layer))
        menu.popup(global_pos)


    # -- plans de travail --
    def add_artboard(self, rect: QRectF | None = None, name: str = "", size=None) -> IllArtboardItem:
        boards = self.artboards()
        index = (max(float(b.data.get("index", 0)) for b in boards) + 1) if boards else 0
        if rect is None:
            w, h = size or look.artboard_size()
            if boards:                                       # à droite du dernier, comme Illustrator
                last = boards[-1].scene_rect()
                rect = QRectF(last.right() + 40, last.top(), w, h)
            else:
                c = self.view.view_center()
                rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        data = board_model.new_item(model.ARTBOARD, x=round(rect.x(), 3), y=round(rect.y(), 3),
                                    w=round(rect.width(), 3), h=round(rect.height(), 3), index=index,
                                    name=name or f"Plan de travail {len(boards) + 1}")
        item = self.scene.add_new(data, "Nouveau plan de travail", select=False)
        self.artboard_id = item.item_id
        self.refresh()
        return item


    def current_artboard(self) -> IllArtboardItem | None:
        """Plan choisi, sinon celui qui contient la sélection, sinon celui au centre de la vue, sinon le premier."""
        board = self.selected_artboard()
        if board is not None:
            return board
        rect = self.selection_rect()
        boards = self.artboards()
        for point in ([rect.center()] if rect is not None else []) + [self.view.view_center()]:
            for b in boards:
                if b.scene_rect().contains(point):
                    return b
        return boards[0] if boards else None


    # -- export / import SVG --
    def export_data(self, area: QRectF | None, only_selection: bool = False) -> list[dict]:
        items = self.selection() if only_selection else self.objects()
        out = []
        for item in items:
            if area is not None and not item.sceneBoundingRect().intersects(area):
                continue
            out.append(item.to_dict())
        return out


    def export_pdf(self, path, boards=None):
        """PDF : une page par plan de travail de `boards` (tous si None) ; sans plan de travail, une page au cadre de
        tout le dessin (marge de 20 unités)."""
        from . import pdf
        boards = self.artboards() if boards is None else list(boards)
        if boards:
            pages = [(b.scene_rect(), b.data.get("fill", "#ffffff")) for b in boards]
            title = str(boards[0].data.get("name", "")) if len(boards) == 1 else "Plans de travail"
        else:
            rect = self.selection_rect(self.objects())
            if rect is None:
                return None
            pages = [(rect.adjusted(-20, -20, 20, 20), "")]
            title = "Dessin"
        return pdf.export_pdf(self, path, pages, title)


    def export_svg(self, path, board: IllArtboardItem | None = None, only_selection: bool = False):
        from pathlib import Path
        from . import svg
        from .text import svg_text
        if board is not None:
            r = board.scene_rect()
            area = (r.x(), r.y(), r.width(), r.height())
            text = svg.export_svg(self.export_data(r, only_selection), area,
                                  background="", title=str(board.data.get("name", "")), text_svg=svg_text,
                                  image_href=self._image_href)
        else:
            text = svg.export_svg(self.export_data(None, only_selection), text_svg=svg_text,
                                  image_href=self._image_href)
        target = Path(path)
        part = target.with_name(target.name + ".part")
        part.write_text(text, encoding="utf-8")
        part.replace(target)                                 # écriture atomique
        return target


    def import_svg(self, path, at: QPointF | None = None) -> list[IllPathItem]:
        """Objets d'un fichier SVG posés au centre de la vue (une étape) ; groupes gardés."""
        from pathlib import Path
        from . import svg
        entities = svg.import_svg(Path(path).read_text(encoding="utf-8"))
        box = bz.union_bounds(svg._object_bounds(e) for e in entities)
        if box is None:
            return []
        at = at or self.view.view_center()
        dx, dy = at.x() - (box[0] + box[2]) / 2, at.y() - (box[1] + box[3]) / 2
        groups = {}
        added = []
        layer = self.ensure_layer()
        self._flush_pending_layer("Nouveau calque")
        z = lay.top_z(self.scene, layer, self.objects())
        resolved = []
        for e in entities:
            if e.get("type") == model.IMAGE:
                name = self._resolve_href(e.pop("_href", ""), path)
                if not name:
                    continue                                 # image introuvable : ignorée (compte rendu : rien)
                e["asset"] = name
            resolved.append(e)
        for e in resolved:
            e = dict(e)
            if e.get("group"):
                e["group"] = groups.setdefault(e["group"], board_model.new_id())
            values = {k: v for k, v in e.items() if k not in ("id", "type")}
            data = board_model.new_item(e.get("type") or model.PATH, **values)      # texte / image : leur type
            data["x"], data["y"], data["z"] = e.get("x", 0.0) + dx, e.get("y", 0.0) + dy, z
            data["layer"] = layer.item_id
            z += 1
            added.append(data)
        items = self.scene.replace_items([], added, "Importer un SVG")
        self.select(items)
        return items
