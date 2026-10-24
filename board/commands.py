"""Annulation : UNE commande pour tout changement — l'etat des elements touches avant et apres
(`{identifiant: dictionnaire, ou None = absent}` ; identifiant `__page__` = reglages de la page). Ajouter,
supprimer, deplacer, redimensionner, modifier un texte, une couleur ou la page passent tous par elle
(`BoardScene.push`). La scene garde la liste des commandes vivantes (`BoardScene.commands`) : les images
qu'elles referencent ne sont jamais retirees du dossier du board tant qu'on peut y revenir."""
from __future__ import annotations

from PySide6.QtGui import QUndoCommand


class StateCommand(QUndoCommand):
    def __init__(self, scene, before: dict, after: dict, text: str):
        super().__init__(text)
        self._scene = scene
        self.before = before
        self.after = after
        self._done = True             # deja applique a l'ecran quand la commande est poussee

    def redo(self):
        if self._done:
            self._done = False
            return
        self._scene.apply_states(self.after)

    def undo(self):
        self._scene.apply_states(self.before)

    def states(self):
        yield from self.before.values()
        yield from self.after.values()
