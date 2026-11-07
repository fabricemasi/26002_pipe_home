"""Outil « Contenu » (Qt) : choisir un objet de la page (texte, image, tracé) au clic, le déplacer (glisser), le
redimensionner (poignées ; Maj : proportions), le supprimer (Suppr), modifier son texte (double-clic), ses couleurs,
son ordre ; ajouter texte, image, rectangle, ellipse, ligne. Le geste n'est qu'un aperçu ; au relâchement, UNE
édition annulable (`PdfSession.edit_doc` + content.py). Échap : désélectionner (jamais fermer le module)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPen

from . import content, ui_kit
from .worker import PRIO_INPUT

HANDLE = 6.0


class ContentOverlay:
    def __init__(self, ctl):
        self.ctl = ctl
        self.selected = None              # (page, objet dict)
        self._drag = None

    def _vr(self, view):
        page, item = self.selected
        return view.engine_rect_to_view(page, item["rect"])

    def paint(self, painter, view):
        if self._drag and self._drag.get("kind") == "draw" and self._drag.get("end") is not None:
            painter.setPen(QPen(QColor(255, 140, 0), 1, Qt.DashLine))
            painter.drawRect(QRectF(self._drag["start"], self._drag["end"]).normalized())
        if not self.selected or self.selected[0] not in view._visible_indexes():
            return
        r = self._vr(view)
        if self._drag and self._drag.get("moved"):
            r = self._preview(r)
        painter.setPen(QPen(QColor(0, 150, 255), 1.5))
        painter.drawRect(r)
        painter.setBrush(Qt.white)
        for h in self._handles(r).values():
            painter.drawRect(h)
        painter.setBrush(Qt.NoBrush)

    @staticmethod
    def _handles(r):
        pts = {"nw": r.topLeft(), "ne": r.topRight(), "se": r.bottomRight(), "sw": r.bottomLeft()}
        return {k: QRectF(p.x() - HANDLE / 2, p.y() - HANDLE / 2, HANDLE, HANDLE) for k, p in pts.items()}

    def _preview(self, r):
        d = self._drag
        if d["kind"] == "move":
            return r.translated(d["dx"], d["dy"])
        q = QRectF(r)
        h = d["handle"]
        if "w" in h:
            q.setLeft(min(q.right() - 4, q.left() + d["dx"]))
        if "e" in h:
            q.setRight(max(q.left() + 4, q.right() + d["dx"]))
        if "n" in h:
            q.setTop(min(q.bottom() - 4, q.top() + d["dy"]))
        if "s" in h:
            q.setBottom(max(q.top() + 4, q.bottom() + d["dy"]))
        return q

    def press(self, view, event, hit):
        if event.button() != Qt.LeftButton or hit is None:
            return event.button() == Qt.RightButton
        pos = event.position()
        page, x, y = hit
        if self.ctl.add_kind:
            self._drag = {"kind": "draw", "page": page, "start": pos, "end": None}
            return True
        if self.selected:
            for name, h in self._handles(self._vr(view)).items():
                if h.adjusted(-2, -2, 2, 2).contains(pos):
                    self._drag = {"kind": "resize", "handle": name, "start": pos, "dx": 0, "dy": 0, "moved": False}
                    return True
            if self._vr(view).contains(pos):
                self._drag = {"kind": "move", "start": pos, "dx": 0, "dy": 0, "moved": False}
                return True
        ex, ey = view.to_engine(page, x, y)
        self.ctl.pick(page, ex, ey)
        self._drag = {"kind": "move", "start": pos, "dx": 0, "dy": 0, "moved": False}
        return True

    def move(self, view, event, hit):
        d = self._drag
        if d is None:
            view.viewport().setCursor(Qt.CrossCursor if self.ctl.add_kind else Qt.ArrowCursor)
            return True
        pos = event.position()
        if d["kind"] == "draw":
            d["end"] = pos
        else:
            d["dx"], d["dy"] = pos.x() - d["start"].x(), pos.y() - d["start"].y()
            d["moved"] = d["moved"] or abs(d["dx"]) + abs(d["dy"]) > 2
        view.viewport().update()
        return True

    def release(self, view, event, hit):
        d, self._drag = self._drag, None
        if d is None:
            return True
        if d["kind"] == "draw":
            page = d["page"]
            pr = view.page_rect(page)
            r = QRectF(d["start"], d["end"] or d["start"]).normalized()
            a = view.to_engine(page, (r.left() - pr.left()) / view.zoom, (r.top() - pr.top()) / view.zoom)
            b = view.to_engine(page, (r.right() - pr.left()) / view.zoom, (r.bottom() - pr.top()) / view.zoom)
            self.ctl.add(page, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])),
                         line_points=(a, b))
        elif d.get("moved") and self.selected:
            page, item = self.selected
            z = view.zoom
            if d["kind"] == "move":
                self.ctl.apply("Déplacer", lambda doc, idx=item["index"]: content.move(doc, page, idx, d["dx"] / z,
                                                                                      d["dy"] / z))
            else:
                nr = self._preview(self._vr(view))
                pr = view.page_rect(page)
                rect = ((nr.left() - pr.left()) / z, (nr.top() - pr.top()) / z, (nr.right() - pr.left()) / z,
                        (nr.bottom() - pr.top()) / z)
                keep = bool(event.modifiers() & Qt.ShiftModifier) or item["type"] == 1
                self.ctl.apply("Redimensionner", lambda doc, idx=item["index"]: content.resize(doc, page, idx, rect,
                                                                                               keep))
        view.viewport().update()
        return True

    def double(self, view, event, hit):
        if self.selected and self.selected[1]["type"] == 1:
            self.ctl.edit_text()
        return True

    def key(self, view, event):
        if event.key() == Qt.Key_Escape:
            self.ctl.add_kind = None
            self.selected = None
            view.viewport().update()
            return True
        if self.selected and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.ctl.delete()
            return True
        if self.selected and event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10.0 if event.modifiers() & Qt.ShiftModifier else 1.0
            dx, dy = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step),
                      Qt.Key_Down: (0, step)}[event.key()]
            page, item = self.selected
            self.ctl.apply("Décaler", lambda doc, idx=item["index"]: content.move(doc, page, idx, dx, dy))
            return True
        return False


class ContentController(QObject):
    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.overlay = ContentOverlay(self)
        self.add_kind = None              # "text", "image", "rect", "ellipse", "line"
        self._image = None
        pane.session.reloaded.connect(lambda _i: self._reselect())

    def set_active(self, on: bool) -> None:
        view = self.pane.view
        if on:
            view.set_overlay(self.overlay)
        elif view.overlay is self.overlay:
            self.overlay.selected = None
            view.set_overlay(None)

    def pick(self, page, x, y) -> None:
        def done(item, error):
            self.overlay.selected = (page, item) if error is None and item else None
            if item:
                label = item["type_name"] + ((" : « %s »" % item["text"][:40]) if item.get("text") else "")
                self.pane.status("Objet choisi — %s (glisser : déplacer, poignées : taille, double-clic : texte, "
                                 "Suppr : supprimer)" % label)
            self.pane.view.viewport().update()
        self.pane.session.run(lambda doc: content.object_at(doc, page, x, y), PRIO_INPUT, done)

    def _reselect(self) -> None:
        sel = self.overlay.selected
        if not sel:
            return
        page, item = sel
        x0, y0, x1, y1 = item["rect"]
        self.overlay.selected = None
        if self.pane.view.overlay is self.overlay:
            self.pick(page, (x0 + x1) / 2, (y0 + y1) / 2)

    def apply(self, label, fn) -> None:
        def done(extra, error):
            if error is not None:
                self.pane.status("%s impossible : %s" % (label, error))
            elif isinstance(extra, dict) and extra.get("fallback"):
                self.pane.status("Texte remplacé avec la police standard « %s » : la police incorporée n'avait pas "
                                 "tous les caractères demandés" % extra["fallback"])
        self.pane.session.edit_doc(label, fn, done)

    def delete(self) -> None:
        page, item = self.overlay.selected
        self.overlay.selected = None
        self.apply("Supprimer un objet", lambda doc: content.delete(doc, page, item["index"]))

    def edit_text(self) -> None:
        page, item = self.overlay.selected
        text = ui_kit.ask_text(self.pane, "Modifier le texte", "Texte de l'objet (police d'origine si elle a les "
                               "caractères, sinon Helvetica)", default=item.get("text", ""), action="Remplacer")
        if text is not None and text != item.get("text"):
            self.apply("Modifier le texte", lambda doc: content.set_text(doc, page, item["index"], text))

    def font_size(self) -> None:
        if not self.overlay.selected or self.overlay.selected[1]["type"] != 1:
            return
        page, item = self.overlay.selected
        value = ui_kit.ask_text(self.pane, "Taille du texte", "Taille (pt)", default="%g" % item.get("size", 12))
        try:
            size = float((value or "").replace(",", "."))
        except ValueError:
            return
        self.apply("Taille du texte", lambda doc: content.set_font_size(doc, page, item["index"], size))

    def color(self, which: str) -> None:
        if not self.overlay.selected:
            return
        page, item = self.overlay.selected
        value = ui_kit.ask_text(self.pane, "Couleur", "Couleur (#rrvvbb)", default="#000000")
        if not value or not value.startswith("#") or len(value) != 7:
            return
        rgb = tuple(int(value[k:k + 2], 16) for k in (1, 3, 5))
        kw = {"fill": rgb} if which == "fill" else {"stroke": rgb}
        self.apply("Couleur", lambda doc: content.set_colors(doc, page, item["index"], **kw))

    def restack(self, where: str) -> None:
        if not self.overlay.selected:
            return
        page, item = self.overlay.selected
        to = 0 if where == "back" else 10 ** 6
        self.apply("Ordre de superposition", lambda doc: content.restack(doc, page, item["index"], to))

    def set_add(self, kind) -> None:
        if kind == "image":
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self.pane, "Image à ajouter", "",
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
            if not path:
                return
            img = QImage(path).convertToFormat(QImage.Format_ARGB32)
            if img.isNull():
                self.pane.status("Image illisible")
                return
            self._image = img
        self.add_kind = kind
        self.pane.status("Tracez l'emplacement sur la page (Échap : annuler)")

    def add(self, page, rect, line_points=None) -> None:
        kind, self.add_kind = self.add_kind, None
        if kind == "text":
            text = ui_kit.ask_text(self.pane, "Ajouter du texte", "Texte (Entrée dans le texte : non ; utilisez "
                                   "« \\n » pour aller à la ligne)", action="Ajouter")
            if not text:
                return
            text = text.replace("\\n", "\n")
            size = max(6.0, min(72.0, (rect[3] - rect[1]) * 0.8)) if rect[3] - rect[1] > 6 else 12.0
            self.apply("Ajouter du texte", lambda doc: content.add_text(doc, page, rect[0], rect[1] + size, text,
                                                                        size))
        elif kind == "image" and self._image is not None:
            img = self._image
            if rect[2] - rect[0] < 4:
                w = 150.0
                rect = (rect[0], rect[1], rect[0] + w, rect[1] + w * img.height() / max(1, img.width()))
            raw = bytes(img.constBits())
            self.apply("Ajouter une image", lambda doc: content.add_image(doc, page, rect, raw, img.width(),
                                                                          img.height(), img.bytesPerLine()))
        elif kind in ("rect", "ellipse"):
            self.apply("Ajouter une forme", lambda doc: content.add_shape(doc, page, kind, rect, width=1.5))
        elif kind == "line" and line_points is not None:
            (ax, ay), (bx, by) = line_points
            self.apply("Ajouter une ligne", lambda doc: content.add_shape(doc, page, "line", (ax, ay, bx, by),
                                                                          width=1.5))
