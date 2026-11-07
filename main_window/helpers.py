"""Petits outils de la fenêtre principale : filtres d'événements (bouton « précédent » de la souris, activité), QSS.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QPainter
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
    """Cadre central de la fenetre principale : fond `C['window']`, bordure du pourtour (Theme > General >
    « Bordure des fenetres », `ui_state.WINDOW_BORDER` : cotes, couleurs, epaisseur), coins
    `ui_state.WINDOW_RADIUS`, PEINTS ici. En QSS (#CentralFrame), changer le rayon ou une de ces couleurs
    repolissait TOUTE la fenetre (~35 ms par cran de curseur) ; ici : un simple `update()`."""

    def paintEvent(self, event):
        from app_style import C
        from fm_theme.widgets import _paint_bordered_vector
        import ui_state
        border = ui_state.WINDOW_BORDER
        colors = {k: border["colors"].get(k) or C["border"] for k in ("top", "right", "bottom", "left")}
        painter = QPainter(self)
        _paint_bordered_vector(painter, self.rect(), int(ui_state.WINDOW_RADIUS), border["sides"],
                               border["thickness"], colors, C["window"])
        painter.end()

    def sync_margins(self):
        """Marges du contenu = epaisseur de la bordure sur chaque cote allume : sinon les enfants (bord franc)
        la recouvrent. Rien si elles n'ont pas change."""
        import ui_state
        border = ui_state.WINDOW_BORDER
        t = {k: border["thickness"] if border["sides"].get(k) else 0 for k in ("left", "top", "right", "bottom")}
        layout = self.layout()
        margins = (t["left"], t["top"], t["right"], t["bottom"])
        if layout is not None:
            current = layout.contentsMargins()
            if (current.left(), current.top(), current.right(), current.bottom()) != margins:
                layout.setContentsMargins(*margins)


class _MouseBackFilter(QObject):
    """Bouton « precedent » : de l'image en focus vers les diapositives, puis vers les colonnes ; module Markdown ou
    typographique ouvert (simple clic sur un fichier) : retour aux colonnes."""

    def __init__(self, browser: "PipelineBrowser"):
        super().__init__(browser)
        self._browser = browser

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        if event.button() != Qt.BackButton:
            return False
        if not (watched.isWidgetType() and watched.window() is self._browser):
            return False
        browser = self._browser
        if not browser._project_columns_hidden:
            font = getattr(browser, "_font", None)
            if getattr(browser, "_side_viewer", None) is not None:
                if kind == QEvent.MouseButtonPress:
                    browser._close_side_viewer()
                return True
            if getattr(browser, "_md_open", False):
                if kind == QEvent.MouseButtonPress:
                    browser._close_md_editor()
                return True
            if font is not None:
                if kind == QEvent.MouseButtonPress and font.confirm_leave():
                    browser._close_font()
                return True
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
