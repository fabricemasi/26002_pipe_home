"""Petits outils de la fenêtre principale : filtres d'événements (bouton « précédent » de la souris, activité), QSS.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QEvent, QObject, Qt

import shiboken6

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pipeline_browser import PipelineBrowser      # annotations seulement (pipeline_browser importe ce module)


def _anim_running(overlay) -> bool:
    """Overlay d'animation (fondu, glissement) reellement en cours. Un overlay
    detruit sans etre alle au bout (objet Qt supprime) ne compte pas : sinon
    son drapeau `running` reste vrai et bloque toutes les animations suivantes."""
    return overlay is not None and overlay.running and shiboken6.isValid(overlay)


# ==========================================================================
# Barre de titre intrinseque : la fenetre principale est sans decoration
# systeme (voir PipelineBrowser.__init__), donc cette barre en tient lieu —
# deplacement, reduction/agrandissement/fermeture — avec le meme habillage
# sombre que le reste de l'appli plutot que le chrome blanc/bleu de Windows.
# ==========================================================================

def _set_qss(widget, qss: str) -> None:
    """setStyleSheet seulement si la feuille change : sur un conteneur qui
    porte toute la fenetre, Qt repolit tous les descendants meme pour un
    texte identique (~7 ms par appel, rejoue a chaque cran de slider)."""
    if widget.styleSheet() != qss:
        widget.setStyleSheet(qss)


class _MouseBackFilter(QObject):
    """Bouton « precedent » : de l'image en focus vers les diapositives, puis vers les colonnes."""

    def __init__(self, browser: "PipelineBrowser"):
        super().__init__(browser)
        self._browser = browser

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        if event.button() != Qt.BackButton or not self._browser._project_columns_hidden:
            return False
        if not (watched.isWidgetType() and watched.window() is self._browser):
            return False
        if kind == QEvent.MouseButtonPress:
            if self._browser._viewer_active():
                self._browser._open_focus_gallery()
            elif self._browser._focus_gallery is not None:
                self._browser._set_columns_hidden(False)
        return True                       # avale aussi le relachement (rien d'autre ne le voit)


class _AppInputWatch(QObject):
    """Filtre d'application pose SEULEMENT pendant le chargement des reglages sur inactivite : le premier geste
    reel (evenement spontane : clavier, souris, molette) sur l'appli l'arrete aussitot."""

    def __init__(self, kinds, on_input):
        super().__init__()
        self._kinds, self._on_input = kinds, on_input

    def eventFilter(self, watched, event):
        if event.type() in self._kinds and event.spontaneous():
            self._on_input()
        return False
