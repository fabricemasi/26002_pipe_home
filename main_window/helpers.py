"""Petits outils de la fenêtre principale : filtres d'événements (bouton « précédent » de la souris, activité), QSS.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

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

from app_style import set_qss as _set_qss  # noqa: E402,F401  (setStyleSheet seulement si la feuille change)


class CentralFrame(QWidget):
    """Cadre central de la fenetre principale : fond `C['window']`, filet 1 px `C['border']`, coins
    `ui_state.WINDOW_RADIUS`, PEINTS ici. En QSS (#CentralFrame), changer le rayon ou une de ces couleurs
    repolissait TOUTE la fenetre (~35 ms par cran de curseur) ; ici : un simple `update()`."""

    def paintEvent(self, event):
        from app_style import C
        import ui_state
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        radius = max(0.0, float(ui_state.WINDOW_RADIUS) - 0.5)
        painter.setPen(QPen(QColor(C["border"]), 1))
        painter.setBrush(QColor(C["window"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


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
