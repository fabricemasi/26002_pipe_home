"""Annuler / rétablir (sans Qt).

Une ÉTAPE = une action de l'utilisateur (un glisser de points complet, une création de glyphe…), jamais un
mouvement de souris : l'appelant prend l'instantané au début du geste et pousse l'étape à la fin.

Instantané d'un glyphe : tuples Python (pas de deepcopy d'objets attrs : ~20 µs pour un glyphe de 200 points)."""
from __future__ import annotations

from typing import Callable

from fontTools.misc.transform import Transform
from ufoLib2.objects import Anchor, Component, Contour, Guideline, Point


def glyph_snapshot(glyph) -> tuple:
    contours = tuple(tuple((p.x, p.y, p.type, p.smooth, p.name, p.identifier) for p in c) for c in glyph.contours)
    components = tuple((c.baseGlyph, tuple(c.transformation), c.identifier) for c in glyph.components)
    anchors = tuple((a.x, a.y, a.name, a.color, a.identifier) for a in glyph.anchors)
    guides = tuple((g.x, g.y, g.angle, g.name, g.color, g.identifier) for g in glyph.guidelines)
    return (glyph.width, glyph.height, tuple(glyph.unicodes), contours, components, anchors, guides,
            _plain(glyph.lib), glyph.note)


def glyph_restore(glyph, snap: tuple) -> None:
    width, height, unicodes, contours, components, anchors, guides, lib, note = snap
    glyph.width, glyph.height = width, height
    glyph.unicodes = list(unicodes)
    glyph.clearContours()
    for c in contours:
        glyph.contours.append(Contour([Point(x, y, t, s, n, i) for x, y, t, s, n, i in c]))
    glyph.clearComponents()
    for base, matrix, ident in components:
        glyph.components.append(Component(base, Transform(*matrix), ident))
    glyph.clearAnchors()
    for x, y, name, color, ident in anchors:
        glyph.anchors.append(Anchor(x, y, name, color, ident))
    glyph.clearGuidelines()
    for x, y, angle, name, color, ident in guides:
        glyph.guidelines.append(Guideline(x=x, y=y, angle=angle, name=name, color=color, identifier=ident))
    glyph.lib.clear()
    glyph.lib.update(_plain(lib))
    glyph.note = note


def contours_snapshot(glyph) -> tuple:
    """Instantané léger (contours seulement) : sert à comparer avant / après un geste."""
    return tuple(tuple((p.x, p.y, p.type, p.smooth) for p in c) for c in glyph.contours)


def _plain(value):
    """Copie profonde des données de lib (dict / list / scalaires plist)."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class Step:
    __slots__ = ("label", "undo", "redo")

    def __init__(self, label: str, undo: Callable[[], None], redo: Callable[[], None]):
        self.label, self.undo, self.redo = label, undo, redo


class UndoStack:
    """Pile d'annulation : `push` (étape déjà faite), `undo`, `redo`. `listeners` : appelés après chaque changement
    (marque « modifié », interface)."""

    def __init__(self, limit: int = 400):
        self._done: list[Step] = []
        self._undone: list[Step] = []
        self.limit = limit
        self.listeners: list[Callable[[], None]] = []
        self.clean_index = 0          # longueur de `_done` au dernier enregistrement

    def push(self, label: str, undo: Callable[[], None], redo: Callable[[], None]) -> None:
        self._done.append(Step(label, undo, redo))
        self._undone.clear()
        if len(self._done) > self.limit:
            del self._done[0]
            self.clean_index -= 1
        self._notify()

    def can_undo(self) -> bool:
        return bool(self._done)

    def can_redo(self) -> bool:
        return bool(self._undone)

    def undo_label(self) -> str:
        return self._done[-1].label if self._done else ""

    def redo_label(self) -> str:
        return self._undone[-1].label if self._undone else ""

    def undo(self) -> bool:
        if not self._done:
            return False
        step = self._done.pop()
        step.undo()
        self._undone.append(step)
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._undone:
            return False
        step = self._undone.pop()
        step.redo()
        self._done.append(step)
        self._notify()
        return True

    def mark_clean(self) -> None:
        self.clean_index = len(self._done)
        self._notify()

    def is_clean(self) -> bool:
        return self.clean_index == len(self._done)

    def clear(self) -> None:
        self._done.clear()
        self._undone.clear()
        self.clean_index = 0
        self._notify()

    def _notify(self):
        for listener in list(self.listeners):
            listener()
