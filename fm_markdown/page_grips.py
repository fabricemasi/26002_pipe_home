"""Module Markdown / code : TRANCHES de la page saisissables (demande de l'utilisateur, 2026-11-12). Deux poignées
invisibles (curseur ↔) posées sur les bords gauche et droit de la page ; les tirer change la MÊME marge que le slider en
bas à droite (`md_module_padding`, symétrique : la page reste centrée). Le panneau applique la marge en direct et émet
`marginDragged(valeur)` ; la fenêtre principale y branche son slider (qui enregistre, 300 ms après le dernier geste).
Pas de Ctrl : c'est un redimensionnement, pas un déplacement d'élément (comme les bords des barres d'outils)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

GRIP_WIDTH = 8                 # px de part et d'autre du bord : 4
MIN_PAGE = 200                 # largeur de page minimale (px) en tirant
MAX_MARGIN = 1000              # borne du slider


class PageGrip(QWidget):
    """Poignée d'un bord de la page (`side` : « left » / « right »)."""

    def __init__(self, pane, side: str):
        super().__init__(pane)
        self.pane, self.side = pane, side
        self._start = None                       # (x global de l'appui, marge au départ)
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip("Tirer pour changer la largeur de la page")
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    # Mécanique (aussi appelée par les tests) ---------------------------------------------------------------------------
    def drag_start(self, global_x: int) -> None:
        self._start = (int(global_x), int(self.pane._module_padding))

    def drag_to(self, global_x: int) -> int | None:
        if self._start is None:
            return None
        x0, margin0 = self._start
        dx = int(global_x) - x0
        margin = margin0 + dx if self.side == "left" else margin0 - dx      # vers le centre : la page rétrécit
        host = self.pane.parentWidget()
        full = host.width() if host is not None else self.pane.width()
        margin = max(0, min(MAX_MARGIN, (full - MIN_PAGE) // 2, margin))
        self.pane.set_module_padding(margin)
        return margin

    def drag_end(self) -> None:
        self._start = None

    # Souris -------------------------------------------------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start(event.globalPosition().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is not None and event.buttons() & Qt.LeftButton:
            self.drag_to(event.globalPosition().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._start is not None:
            self.drag_end()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def place(grips: dict, pane, margin: int, settings: dict, insets: dict | None, zoom: float) -> None:
    """Pose les poignées sur les bords VISIBLES de la page : marge du module + marge de la page (`md_page_margin`) +
    place des barres clipsées sur ce bord (px CSS × zoom)."""
    page_margin = settings.get("md_page_margin") if isinstance(settings, dict) else None
    page_margin = page_margin if isinstance(page_margin, dict) else {}
    insets = insets or {}
    height = pane.height()
    for side, grip in grips.items():
        try:
            css = float(page_margin.get(side) or 0) + float(insets.get(side) or 0)
        except (TypeError, ValueError):
            css = 0.0
        offset = margin + round(css * zoom)
        x = offset if side == "left" else pane.width() - offset
        grip.setGeometry(x - GRIP_WIDTH // 2, 0, GRIP_WIDTH, height)       # sous les barres (créées après)
