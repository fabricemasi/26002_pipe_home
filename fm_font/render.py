"""Rendu Qt des glyphes : contours -> QPainterPath, avec un CACHE à invalidation rigoureuse.

Clé : (master, nom). Un changement d'un glyphe (`project.notify("glyph", (master, nom))`) invalide ce glyphe ET
tous les composés qui l'utilisent, directement ou non (graphe inverse des composants, refait quand la liste des
glyphes change). Pendant un glisser de points, le canvas invalide le seul glyphe édité : un chemin de 400 points
se reconstruit en ~0,2 ms, rien d'autre n'est recalculé."""
from __future__ import annotations

from fontTools.pens.basePen import BasePen
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QRadialGradient

from . import color as colr


def color_layers(font, name: str) -> list:
    """Calques couleur (COLR) de `name` si la famille a une palette, sinon []."""
    return colr.layers(font, name) if colr.PALETTES_KEY in font.lib else []


def color_brush(palette, paint, path: QPainterPath, fill, alpha: int = 255):
    """Pinceau d'un calque couleur, en unités de la police : aplat (indice de palette) ou dégradé (COLR v1) sur
    la boîte du chemin du calque. Indice hors palette (ex. 0xFFFF, couleur du texte) : `fill`."""
    def qcolor(index):
        c = QColor.fromRgbF(*palette[index]) if 0 <= index < len(palette) else QColor(fill)
        c.setAlpha(round(c.alpha() * alpha / 255))
        return c
    if not isinstance(paint, tuple):
        return qcolor(paint)
    r = path.boundingRect()
    geo = colr.gradient_geometry((r.left(), r.top(), r.right(), r.bottom()), paint)
    if paint[0] == "lin":
        gradient = QLinearGradient(geo["x0"], geo["y0"], geo["x1"], geo["y1"])
    else:
        gradient = QRadialGradient(geo["x0"], geo["y0"], geo["r1"])
    gradient.setColorAt(0, qcolor(paint[1]))
    gradient.setColorAt(1, qcolor(paint[2]))
    return gradient


class QPathPen(BasePen):
    """Stylo fontTools -> QPainterPath (composants décomposés par le glyphSet)."""

    def __init__(self, glyph_set, path: QPainterPath):
        super().__init__(glyph_set)
        self.path = path

    def _moveTo(self, p):
        self.path.moveTo(QPointF(*p))

    def _lineTo(self, p):
        self.path.lineTo(QPointF(*p))

    def _curveToOne(self, p1, p2, p3):
        self.path.cubicTo(QPointF(*p1), QPointF(*p2), QPointF(*p3))

    def _qCurveToOne(self, p1, p2):
        self.path.quadTo(QPointF(*p1), QPointF(*p2))

    def _closePath(self):
        self.path.closeSubpath()


def glyph_path(glyph, font, contours: bool = True, components: bool = True) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    pen = QPathPen(font, path)
    if contours:
        for contour in glyph.contours:
            contour.draw(pen)
    if components:
        for comp in glyph.components:
            comp.draw(pen)
    return path


class PathCache:
    """Chemins des glyphes par (master, nom), complets (composants décomposés) ou contours seuls."""

    def __init__(self, project):
        self.project = project
        self._paths: dict[tuple, QPainterPath] = {}
        self._users: dict[int, dict[str, set]] | None = None
        project.listeners.append(self._on_change)

    def detach(self) -> None:
        if self._on_change in self.project.listeners:
            self.project.listeners.remove(self._on_change)

    def path(self, master: int, name: str, part: str = "all") -> QPainterPath:
        key = (master, name, part)
        path = self._paths.get(key)
        if path is None:
            font = self.project.masters[master].font
            glyph = font[name]
            path = glyph_path(glyph, font, contours=part != "components", components=part != "contours")
            self._paths[key] = path
        return path

    def invalidate(self, master: int, name: str) -> None:
        for part in ("all", "contours", "components"):
            self._paths.pop((master, name, part), None)
        for user in self._dependents(master, name):
            for part in ("all", "components"):
                self._paths.pop((master, user, part), None)

    def clear(self) -> None:
        self._paths.clear()
        self._users = None

    def _dependents(self, master: int, name: str) -> set:
        if self._users is None:
            self._users = {}
        users = self._users.get(master)
        if users is None:
            users = {}
            for glyph in self.project.masters[master].font:
                for comp in glyph.components:
                    users.setdefault(comp.baseGlyph, set()).add(glyph.name)
            self._users[master] = users
        out, todo = set(), [name]
        while todo:
            for user in users.get(todo.pop(), ()):
                if user not in out:
                    out.add(user)
                    todo.append(user)
        return out

    def _on_change(self, kind: str, payload) -> None:
        if kind == "glyph":
            master, name = payload
            self._users = None if self._users is None else {k: v for k, v in self._users.items() if k != master}
            self.invalidate(master, name)
        elif kind in ("glyphs", "masters", "undo-all"):
            self.clear()
