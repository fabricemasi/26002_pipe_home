"""Inspecteur : largeur tirée à la souris sur la bordure gauche, curseur et survol.

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from PySide6.QtCore import QEvent, Qt

from app_style import scaled
from browser_core import (
    DETAIL_PANEL_MAX_WIDTH, DETAIL_PANEL_MIN_WIDTH, _hide_resize_width, _persist_detail_panel_width,
    _show_resize_width,
)


class ResizeMixin:
    """Méthodes de DetailPanel : inspecteur : largeur tirée à la souris sur la bordure gauche, curseur et survol."""

    # -- redimensionnement par glisser-deposer sur la bordure gauche,
    # comme n'importe quelle colonne (voir Column.resize_begin/update/end) --

    def _max_width(self) -> int:
        """Largeur maximale ATTEIGNABLE au glisser : toute la place
        disponible jusqu'a la colonne d'en face (la rangee Type/Projets/...
        a gauche), PAS une constante fixe — voir la remarque de
        l'utilisateur, "augmente cette limite a la place disponible jusqu'a
        la colonne en face". `win.scroll`/`win.columns_layout` (voir
        PipelineBrowser.__init__) : largeur du viewport visible moins la
        largeur REELLE actuelle de la rangee de colonnes (sizeHint() d'un
        QHBoxLayout aux enfants a largeur fixe = leur somme + espacements) —
        DETAIL_PANEL_MIN_WIDTH en repli si l'un des deux manque (fenetre pas
        encore construite) ou si le resultat tombe en-dessous."""
        win = self.window()
        scroll = getattr(win, "scroll", None)
        columns_layout = getattr(win, "columns_layout", None)
        if scroll is None or columns_layout is None:
            return DETAIL_PANEL_MAX_WIDTH
        available = scroll.viewport().width() - columns_layout.sizeHint().width()
        return max(DETAIL_PANEL_MIN_WIDTH, available)

    def _in_resize_zone(self, x: int) -> bool:
        """Bord GAUCHE (contrairement a Column/PreviewColumn, bord DROIT —
        l'inspecteur est TOUJOURS la DERNIERE colonne de la rangee, voir
        _suppress_left)."""
        return 0 <= x < scaled(16)

    def _resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        self.grabMouse()
        self.setCursor(Qt.SizeHorCursor)
        _show_resize_width(self, self.width())

    def _resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(
            DETAIL_PANEL_MIN_WIDTH,
            min(self._max_width(), self._resize_start_width - delta),
        )
        self.setFixedWidth(new_width)
        self._natural_width = new_width
        win = self.window()
        if hasattr(win, "_slide_snapshot"):
            win._slide_snapshot = None   # largeur changee : capture du depliage perimee
        _show_resize_width(self, new_width)

    def _resize_end(self):
        self._resizing = False
        self.releaseMouse()
        self.unsetCursor()
        _hide_resize_width(self)
        _persist_detail_panel_width(self.window(), self.width())

    def eventFilter(self, obj, event):
        """MEME mecanique que PreviewColumn.eventFilter/Column.eventFilter
        (voir leur docstring de tete) : installe sur self.card/self.header
        (voir __init__) — sans cela, ces widgets ENFANTS, qui couvrent TOUTE
        la surface de self, interceptent l'evenement souris AVANT que self
        ne le voie, rendant la bordure de redimensionnement inaccessible —
        voir la remarque de l'utilisateur, "la selection du bord de la
        colonne inspecteur est toujours aussi peinible a selectionner pour
        la redimension"."""
        etype = event.type()
        if etype in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide) and                 obj in getattr(self, "_md_slot_watch", ()):
            self._place_markdown_view()
            return False
        if obj in getattr(self, "_preview_widgets", ()):
            # Apercu : seul le double-clic est intercepte (voir
            # preview_double_clicked), le reste suit son cours normal.
            if etype == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.preview_double_clicked.emit()
                return True
            if self._pdf_path is not None and self._pdf_path == self._current_path:
                if self._pdf_event(event):
                    return True
            return False
        if etype == QEvent.MouseMove:
            if self._resizing:
                self._resize_update(event.globalPosition().toPoint().x())
                return True
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_x) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._in_resize_zone(local_x):
                self._resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonRelease and self._resizing:
            self._resize_end()
            return True
        elif etype == QEvent.Leave and not self._resizing:
            obj.unsetCursor()
        return False

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._resizing:
            self._resize_update(event.globalPosition().toPoint().x())
            return
        self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(x) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        x = event.position().toPoint().x()
        if event.button() == Qt.LeftButton and self._in_resize_zone(x):
            self._resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resize_end()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._resizing:
            self.unsetCursor()
        super().leaveEvent(event)
