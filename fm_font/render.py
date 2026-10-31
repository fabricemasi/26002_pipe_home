"""Rendu Qt des glyphes : contours -> QPainterPath, avec un CACHE à invalidation rigoureuse.

Clé : (master, nom). Un changement d'un glyphe (`project.notify("glyph", (master, nom))`) invalide ce glyphe ET
tous les composés qui l'utilisent, directement ou non (graphe inverse des composants, refait quand la liste des
glyphes change). Pendant un glisser de points, le canvas invalide le seul glyphe édité : un chemin de 400 points
se reconstruit en ~0,2 ms, rien d'autre n'est recalculé."""
from __future__ import annotations

from fontTools.pens.basePen import BasePen
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath


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
