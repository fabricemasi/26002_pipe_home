"""Historique (SANS Qt) : annuler / rétablir.

Deux sortes d'étapes : un PATCH de pixels (zone modifiée seulement : avant / après, jamais une copie du document) et
une étape de STRUCTURE (deux fonctions faire / défaire : ajout, suppression, ordre, réglages d'un calque…). Les
patches sont plafonnés en mémoire (`LIMIT_BYTES`) : les plus anciennes étapes sont oubliées."""
from __future__ import annotations

LIMIT_BYTES = 384 << 20


class Command:
    label = ""
    rect = None                 # zone du document à repeindre (None : structure, tout repeindre)
    structural = False

    def undo(self):
        raise NotImplementedError

    def redo(self):
        raise NotImplementedError

    def nbytes(self) -> int:
        return 0


class PatchCommand(Command):
    """Pixels d'un plan (calque ou masque) remplacés dans `rect` : `before` -> `after`."""

    def __init__(self, label, layer, which, rect, before, after):
        self.label, self.layer, self.which = label, layer, which
        self.rect, self.before, self.after = tuple(rect), before, after

    def _plane(self):
        return self.layer.pix if self.which == "pixels" else self.layer.mask.plane

    def undo(self):
        self._plane().write(self.rect, self.before, margin=0)

    def redo(self):
        self._plane().write(self.rect, self.after, margin=0)

    def nbytes(self):
        return int(self.before.nbytes + self.after.nbytes)


class TilesCommand(Command):
    """Comme `PatchCommand` mais par MORCEAUX (un long trait en diagonale ne garde pas son rectangle englobant) :
    `pieces` = [(rect, avant, après)]."""

    def __init__(self, label, layer, which, pieces):
        self.label, self.layer, self.which, self.pieces = label, layer, which, list(pieces)
        rect = None
        for r, _b, _a in self.pieces:
            rect = r if rect is None else (min(rect[0], r[0]), min(rect[1], r[1]), max(rect[2], r[2]),
                                           max(rect[3], r[3]))
        self.rect = rect

    def _plane(self):
        return self.layer.pix if self.which == "pixels" else self.layer.mask.plane

    def undo(self):
        plane = self._plane()
        for r, before, _after in self.pieces:
            plane.write(r, before, margin=0)

    def redo(self):
        plane = self._plane()
        for r, _before, after in self.pieces:
            plane.write(r, after, margin=0)

    def nbytes(self):
        return sum(int(b.nbytes + a.nbytes) for _r, b, a in self.pieces)


class CallCommand(Command):
    structural = True

    def __init__(self, label, do, undo, rect=None):
        self.label, self._do, self._undo, self.rect = label, do, undo, rect
        self.structural = rect is None

    def undo(self):
        self._undo()

    def redo(self):
        self._do()


class Compound(Command):
    def __init__(self, label, commands):
        self.label, self.commands = label, list(commands)
        self.structural = any(c.structural for c in self.commands)
        rect = None
        for c in self.commands:
            if c.rect is not None:
                rect = c.rect if rect is None else (min(rect[0], c.rect[0]), min(rect[1], c.rect[1]),
                                                    max(rect[2], c.rect[2]), max(rect[3], c.rect[3]))
        self.rect = None if self.structural else rect

    def undo(self):
        for c in reversed(self.commands):
            c.undo()

    def redo(self):
        for c in self.commands:
            c.redo()

    def nbytes(self):
        return sum(c.nbytes() for c in self.commands)


class History:
    def __init__(self, limit_bytes: int = LIMIT_BYTES):
        self.limit = limit_bytes
        self.done: list[Command] = []
        self.undone: list[Command] = []
        self.version = 0                    # +1 à chaque changement du contenu (faire, annuler, rétablir)
        self.saved_version = 0

    def push(self, command: Command | None):
        """Enregistre une étape DÉJÀ appliquée."""
        if command is None:
            return
        self.done.append(command)
        self.undone.clear()
        self.version += 1
        total = sum(c.nbytes() for c in self.done)
        while total > self.limit and len(self.done) > 1:
            total -= self.done.pop(0).nbytes()

    def can_undo(self) -> bool:
        return bool(self.done)

    def can_redo(self) -> bool:
        return bool(self.undone)

    def undo(self):
        if not self.done:
            return None
        command = self.done.pop()
        command.undo()
        self.undone.append(command)
        self.version += 1
        return command

    def redo(self):
        if not self.undone:
            return None
        command = self.undone.pop()
        command.redo()
        self.done.append(command)
        self.version += 1
        return command

    def mark_saved(self):
        self.saved_version = self.version

    def dirty(self) -> bool:
        return self.version != self.saved_version

    def labels(self):
        return (self.done[-1].label if self.done else None, self.undone[-1].label if self.undone else None)
