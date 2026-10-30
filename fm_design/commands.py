"""Commandes du module Design (mélangées au contrôleur, `CommandMixin`) : créer une page, une forme, un texte,
une image (fichiers, dépôt, presse-papiers), dupliquer, verrouiller, copier / coller, copier / coller le style,
présenter, couleurs du document."""
from __future__ import annotations

import copy

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from . import design_model as dm, document as doc, geometry
from .items import DesignPageItem, DesignTextItem


class CommandMixin:
    # ------------------------------------------------------------------ commandes
    def ensure_page(self) -> DesignPageItem:
        page = self.current_page()
        if page is None:
            w, h = dm.FORMAT_SIZES["square"]
            page = doc.add_page(self.scene, w, h, origin=self.view.view_center(), values={"format": "square"},
                                text="Nouveau design")
            self.set_current_page(page, show=True)
            self.pagesChanged.emit()
        return page

    def add_shape(self, shape: str, values: dict | None = None):
        page = self.ensure_page()
        w, h = page.size()
        side = round(min(w, h) * 0.3, 2)
        data = {"shape": shape, "w": side, "h": side}
        if shape == "line":
            data.update(w=round(w * 0.4, 2), h=24.0, stroke_width=6.0, fill_type="none", stroke=dm.INK)
        data.update(values or {})
        item = doc.add_element(self.scene, page, dm.SHAPE, data, "Ajouter une forme")
        self._select([item])
        return item

    TEXT_PRESETS = {"heading": ("Ajouter un titre", 96.0, True), "subheading": ("Ajouter un sous-titre", 56.0, True),
                    "body": ("Ajouter un peu de texte", 32.0, False)}

    def add_text(self, preset: str = "body", values: dict | None = None, edit: bool = True):
        page = self.ensure_page()
        text, size, bold = self.TEXT_PRESETS.get(preset, self.TEXT_PRESETS["body"])
        w = round(min(page.size()[0] * 0.8, max(200.0, size * len(text) * 0.55)), 2)
        data = {"text": text, "font_size": size, "bold": bold, "w": w, "h": size * 1.3}
        data.update(values or {})
        item = doc.add_element(self.scene, page, dm.TEXT, data, "Ajouter un texte")
        self._select([item])
        if edit:
            self.edit_text(item, select_all=True)
        return item

    def add_image_asset(self, asset: str, width: int, height: int, at: QPointF | None = None):
        page = self.ensure_page()
        pw, ph = page.size()
        w, h = geometry.fit_inside(float(width), float(height), pw, ph)
        values = {"asset": asset, "w": round(w, 2), "h": round(h, 2)}
        if at is not None:
            local = page.mapFromScene(at)
            values.update(x=round(local.x() - w / 2, 2), y=round(local.y() - h / 2, 2))
        item = doc.add_element(self.scene, page, dm.IMAGE, values, "Ajouter une image")
        self._select([item])
        return item

    def add_image_files(self, paths, at: QPointF | None = None) -> bool:
        from PySide6.QtGui import QImageReader
        from fm_board import serialization
        board_path = self.scene.board_path
        if board_path is None:
            return False
        added = False
        for n, path in enumerate(paths):
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if not size.isValid():
                continue
            try:
                name = serialization.import_asset(board_path, path)
            except OSError:
                continue
            point = None if at is None else at + QPointF(30 * n, 30 * n)
            self.add_image_asset(name, size.width(), size.height(), point)
            added = True
        return added

    def drop_files(self, paths, at: QPointF) -> bool:
        page = self._page_at(at)
        if page is not None:
            self.set_current_page(page)
        return self.add_image_files(paths, at if page is not None else None)

    def duplicate(self):
        sel = self.selection()
        page = sel[0].page_item() if sel else None
        if page is None:
            return
        copies = doc.insert_elements(self.scene, page, self.scene.serialize(sel), offset=(20.0, 20.0),
                                     text="Dupliquer")
        self._select(copies)

    def toggle_lock(self):
        sel = self.selection()
        if sel:
            lock = not all(i.locked() for i in sel)
            self.scene.change_items(sel, lambda i: i.data.update(locked=lock),
                                    "Verrouiller" if lock else "Déverrouiller", include_locked=True)
            self.stateChanged.emit()

    def copy(self):
        from PySide6.QtCore import QByteArray, QMimeData
        from fm_board.view import CLIPBOARD_MIME
        sel = self.selection()
        if not sel:
            return
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, QByteArray(self.scene.clipboard_payload(self.scene.serialize(sel))))
        texts = [i.data.get("text", "") for i in sel if isinstance(i, DesignTextItem)]
        if texts:
            mime.setText("\n".join(texts))
        QApplication.clipboard().setMimeData(mime)

    def paste(self):
        from fm_board.view import CLIPBOARD_MIME
        mime = QApplication.clipboard().mimeData()
        page = self.ensure_page()
        if mime.hasFormat(CLIPBOARD_MIME):
            dicts, source = self.scene.read_payload(mime.data(CLIPBOARD_MIME).data())
            dicts = [d for d in dicts if d.get("type") in dm.ELEMENT_TYPES]
            if dicts:
                same = all(self.scene.item(d["id"]) is not None and d.get("page") == page.item_id for d in dicts)
                for d in dicts:
                    if d.get("asset") and source and self.scene.board_path is not None:
                        self.scene._bring_asset(d, source)
                copies = doc.insert_elements(self.scene, page, dicts, offset=(20.0, 20.0) if same else (0.0, 0.0))
                self._select(copies)
                return
        if mime.hasUrls():
            from pathlib import Path
            if self.add_image_files([Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]):
                return
        if mime.hasImage() and self.scene.board_path is not None:
            from PySide6.QtCore import QBuffer, QIODevice
            from fm_board import serialization
            image = mime.imageData()
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer, "PNG")
            name = serialization.import_image_bytes(self.scene.board_path, bytes(buffer.data()), ".png")
            self.add_image_asset(name, image.width(), image.height())
            return
        if mime.hasText() and mime.text().strip():
            self.add_text("body", {"text": mime.text().strip(), "bold": False}, edit=False)

    # ------------------------------------------------------------------ style, présentation
    STYLE_KEYS = ("fill", "fill_type", "fill2", "gradient_angle", "stroke", "stroke_width", "stroke_style", "radius",
                  "opacity", "shadow", "font_family", "font_size", "color", "bold", "italic", "underline", "strike",
                  "uppercase", "align", "line_height", "letter_spacing", "text_bg", "text_stroke",
                  "text_stroke_width", "brightness", "contrast", "saturation", "blur", "grayscale", "mask")

    def copy_style(self):
        """Copier le style (Ctrl+Alt+C, comme Canva) : propriétés d'aspect du premier élément choisi."""
        sel = self.selection()
        if sel:
            data = sel[0].to_dict()
            self.style_clipboard = {k: copy.deepcopy(data[k]) for k in self.STYLE_KEYS if k in data}
            self.pane._state.setText("Style copié : Ctrl+Alt+V pour l'appliquer")
            self.stateChanged.emit()

    def paste_style(self):
        """Coller le style (Ctrl+Alt+V) sur la sélection : seulement les propriétés que chaque élément possède."""
        style = getattr(self, "style_clipboard", None)
        sel = self.selection()
        if not style or not sel:
            return

        def mutate(item):
            for key, value in style.items():
                if key in dm.DEFAULTS.get(item.kind, {}):
                    item.data[key] = copy.deepcopy(value)
        doc.change(self.scene, sel, mutate, "Coller le style")

    def present(self, start_page=None):
        """Présentation plein écran (Ctrl+Alt+P), à partir de la page courante."""
        from .present import PresentationWindow
        pages = self.pages()
        if not pages:
            return None
        current = start_page or self.current_page()
        window = PresentationWindow(pages, pages.index(current) if current in pages else 0, self.pane.window())
        window.start()
        return window

    def document_colors(self) -> list[str]:
        """Couleurs utilisées dans le design (« Couleurs du document » de Canva), les plus fréquentes d'abord."""
        counts: dict[str, int] = {}
        keys = ("fill", "fill2", "stroke", "color", "background", "bg2", "text_bg", "text_stroke")
        for item in doc.pages(self.scene) + doc.elements(self.scene):
            for key in keys:
                value = item.data.get(key)
                if isinstance(value, str) and value.startswith("#") and len(value) == 7:
                    counts[value.lower()] = counts.get(value.lower(), 0) + 1
        return [c for c, _n in sorted(counts.items(), key=lambda kv: -kv[1])][:12]
