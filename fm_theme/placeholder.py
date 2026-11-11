"""Icones PROVISOIRES en magenta (demande de l'utilisateur, 2026-11-08).

Toute icone DESSINEE par le code (glyphes des boutons, des barres d'outils des modules, badges de logiciel...) est
peinte en MAGENTA : elle se repere d'un coup d'oeil, a remplacer par une vraie icone. Une icone CHARGEE par
l'utilisateur (fichier choisi dans les reglages, `data/software_icons/`, PNG de `icons/`) n'y passe jamais et reste
telle quelle. Chaque dessinateur de glyphe appelle `ink(couleur)` sur la couleur recue : le magenta garde son alpha
(grise, estompe, desactive restent lisibles)."""
from __future__ import annotations

from PySide6.QtGui import QColor

MAGENTA = "#ff00ff"


def ink(color=None) -> QColor:
    """Le magenta, avec l'alpha de `color` (QColor ou texte ; absent ou illisible : opaque)."""
    out = QColor(MAGENTA)
    if color is not None:
        source = QColor(color)
        if source.isValid():
            out.setAlpha(source.alpha())
    return out
