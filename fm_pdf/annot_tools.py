"""Outil « Commentaires » (Qt) : surcouche de la vue pour tracer les annotations (rectangle, ellipse, ligne,
flèche, dessin à main levée, note, zone de texte, tampon, coche, croix) et balisage du texte sélectionné
(surligner, souligner, barrer). Le geste n'est qu'un aperçu ; au relâchement, UNE édition annulable (annots.py)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from . import annots, ui_kit

COLORS = (("Jaune", "#ffd400"), ("Vert", "#43a047"), ("Bleu", "#1e88e5"), ("Rouge", "#d32f2f"),
          ("Violet", "#8e24aa"), ("Noir", "#000000"))


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[k:k + 2], 16) / 255 for k in (0, 2, 4))


class AnnotOverlay:
    def __init__(self, ctl):
        self.ctl = ctl
        self._drag = None

    def paint(self, painter, view):
        d = self._drag
        if not d:
            return
        painter.setPen(QPen(QColor(self.ctl.color), max(1.0, self.ctl.width * view.zoom)))
        kind = self.ctl.tool
        if kind == "ink" and len(d["points"]) > 1:
            path = QPainterPath(d["points"][0])
            for p in d["points"][1:]:
                path.lineTo(p)
            painter.drawPath(path)
        elif d.get("end") is not None:
            r = QRectF(d["start"], d["end"]).normalized()
            if kind in ("line", "arrow"):
                painter.drawLine(d["start"], d["end"])
            elif kind == "circle":
                painter.drawEllipse(r)
            else:
                painter.drawRect(r)

    def press(self, view, event, hit):
        if event.button() != Qt.LeftButton or hit is None or not self.ctl.tool:
            return False
        self._drag = {"page": hit[0], "start": event.position(), "end": None, "points": [event.position()]}
        return True

    def move(self, view, event, hit):
        if self._drag is None:
            view.viewport().setCursor(Qt.CrossCursor if self.ctl.tool else Qt.ArrowCursor)
            return bool(self.ctl.tool)
        self._drag["end"] = event.position()
        self._drag["points"].append(event.position())
        view.viewport().update()
        return True

    def release(self, view, event, hit):
        d, self._drag = self._drag, None
        if d is None:
            return False
        page = d["page"]
        pr = view.page_rect(page)

        def pts(p):
            return view.to_engine(page, (p.x() - pr.left()) / view.zoom, (p.y() - pr.top()) / view.zoom)
        start = pts(d["start"])
        end = pts(d["end"] or d["start"])
        rect = (min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1]))
        kind = self.ctl.tool
        if rect[2] - rect[0] < 4 and rect[3] - rect[1] < 4 and kind not in ("note", "ink"):
            w, h = {"stamp": (150, 45), "freetext": (180, 40), "check": (16, 16), "cross": (16, 16)}.get(kind,
                                                                                                         (60, 40))
            rect = (start[0], start[1], start[0] + w, start[1] + h)
        props = {}
        if kind == "ink":
            props["strokes"] = [[pts(p) for p in d["points"]]]
        elif kind in ("line", "arrow"):
            props["points"] = (start, end)
        elif kind == "note":
            text = ui_kit.ask_text(view, "Note", "Texte de la note", action="Ajouter")
            if text is None:
                return True
            props["point"] = start
            props["contents"] = text
        elif kind == "freetext":
            text = ui_kit.ask_text(view, "Zone de texte", "Texte", action="Ajouter")
            if not text:
                return True
            props["rect"] = rect
            props["text"] = text
        elif kind == "stamp":
            props["rect"] = rect
            props["stamp"] = self.ctl.stamp
        else:
            props["rect"] = rect
        self.ctl.add(page, kind, props)
        view.viewport().update()
        return True

    def double(self, view, event, hit):
        return bool(self.ctl.tool)

    def key(self, view, event):
        if event.key() == Qt.Key_Escape and self.ctl.tool:
            self.ctl.set_tool(None)
            return True
        return False


class AnnotController(QObject):
    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.tool = None
        s = pane.settings
        self.color = s.get("pdf_annot_color", "#ffd400")
        self.ink_color = s.get("pdf_annot_ink_color", "#d32f2f")
        self.width = float(s.get("pdf_annot_width", 2.0))
        self.opacity = float(s.get("pdf_annot_opacity", 1.0))
        self.author = s.get("pdf_annot_author", "") or _user_name()
        self.stamp = "Approuvé"
        self.overlay = AnnotOverlay(self)

    def set_tool(self, kind) -> None:
        if kind in ("highlight", "underline", "strikeout", "squiggly"):
            self.markup_selection(kind)
            kind = None
        if kind == "stamp":
            m = ui_kit.menu(self.pane)
            for name in annots.STAMPS:
                m.addAction(name).triggered.connect(lambda _c=False, n=name: setattr(self, "stamp", n))
            m.exec(self.pane.mapToGlobal(self.pane.rect().center()))
        self.tool = kind
        view = self.pane.view
        if kind:
            view.set_overlay(self.overlay)
            self.pane.status("Commentaires : tracez sur la page (Échap : arrêter l'outil)")
        elif view.overlay is self.overlay:
            view.set_overlay(None)
        self.pane.sync_annot_tools(kind)

    def _props(self, kind, props) -> dict:
        color = self.ink_color if kind in ("ink", "line", "arrow", "rect", "circle", "check", "cross") else self.color
        out = {"color": _rgb(color), "width": self.width, "opacity": self.opacity, "author": self.author}
        if kind == "highlight":
            out["opacity"] = min(self.opacity, 1.0)
        out.update(props)
        return out

    def add(self, page, kind, props) -> None:
        props = self._props(kind, props)
        self.pane.session.edit("Commentaire « %s »" % annots.KINDS.get(kind, kind),
                               lambda data: annots.add(data, page, kind, props),
                               lambda _x, err: self.pane.refresh_comments() if err is None else None)

    def markup_selection(self, kind) -> None:
        sel = self.pane.view.selection
        if not sel:
            self.pane.status("Sélectionnez d'abord du texte (outil Remplir), puis choisissez le balisage")
            return
        page, _start, _count, rects = sel
        self.add(page, kind, {"rects": [tuple(r) for r in rects]})
        self.pane.view.clear_selection()

    def color_menu(self, anchor) -> None:
        m = ui_kit.menu(self.pane)
        for name, hex_color in COLORS:
            a = m.addAction(name)
            a.triggered.connect(lambda _c=False, h=hex_color: self._set_color(h))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor is not None else
               self.pane.mapToGlobal(self.pane.rect().center()))

    def _set_color(self, hex_color) -> None:
        self.color = self.ink_color = hex_color


def _user_name() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:                                      # noqa: BLE001
        return ""
