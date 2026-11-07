"""Modules ouverts À CÔTÉ des colonnes (simple clic sur un fichier, demande de l'utilisateur du 2026-11-03) : une image
dans une visionneuse posée à droite de la colonne cliquée, une note dans le module Markdown, une police dans le module
typographique, les colonnes restant visibles à gauche. Le double-clic (sur la ligne, ou sur l'image) passe au module
plein (colonnes parties) ; Échap, le bouton « précédent » de la souris ou un clic sur un dossier / un autre fichier le
referment."""

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt
from PySide6.QtWidgets import QWidget


class _SideViewer(QWidget):
    """Visionneuse à côté des colonnes : le fond de la zone des colonnes, l'image au centre (elle y vole depuis la
    ligne) ; double-clic sur l'image : la visionneuse pleine."""

    def __init__(self, host: QWidget, left: int, path: Path, pixmap, source: QRect | None, on_double_click):
        from fm_visionneuse.focus import FocusOverlay
        super().__init__(host)
        self.path = Path(path)
        self._left = left
        self.setAutoFillBackground(True)
        self.setPalette(host.palette())
        self.setBackgroundRole(host.backgroundRole())
        self.setGeometry(self.side_rect())
        start = QRectF(self.mapFromGlobal(source.topLeft()), source.size()) if source is not None else None
        target = FocusOverlay.target_rect(pixmap, self.rect())
        self.overlay = FocusOverlay(self, pixmap, start or target, target, 0.0, 1.0, 260,
                                    on_double_click=on_double_click)
        self.overlay.hold = False
        self.overlay.show()
        host.installEventFilter(self)
        self.show()
        self.raise_()

    def side_rect(self) -> QRect:
        rect = self.parentWidget().rect()
        return rect.adjusted(min(self._left, max(0, rect.width() - 80)), 0, 0, 0)

    def upgrade(self, pixmap, natural=None, full=None) -> None:
        self.overlay.set_natural(natural, self.rect())
        self.overlay.upgrade(pixmap, natural, full)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(self.side_rect())
            self.overlay.set_geometry_target(self.rect())
        return False

    def close_now(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.overlay.dispose()
        self.hide()
        self.deleteLater()


class SideModuleMixin:
    """Modules à côté des colonnes (voir le module)."""

    def _side_left(self, column) -> int:
        """Bord droit de la colonne cliquée, dans la zone des colonnes : le module commence là."""
        if column is None:
            return 0
        viewport = self.scroll.viewport()
        return max(0, column.mapTo(viewport, QPoint(column.width(), 0)).x())

    def _open_side(self, key: str, path, column) -> None:
        """Simple clic : `path` dans le module `key` (« viewer », « md », « font ») à droite de la colonne."""
        path = Path(path)
        left = self._side_left(column)
        if key == "viewer":                       # une note / une police ouverte à côté laisse place à l'image
            if getattr(self, "_md_open", False) and self._md_side_left() and not self._close_md_editor():
                return
            font = getattr(self, "_font", None)
            if font is not None and font.side_left:
                if not font.confirm_leave():
                    return
                self._close_font()
            self._open_side_viewer(path, column, left)
            return
        self._close_side_viewer()
        self._module_side_left = left
        try:
            self.open_in_module(key, path, column)
        finally:
            self._module_side_left = 0

    def _side_module_open(self) -> bool:
        """Un module est ouvert à côté des colonnes (le bouton « précédent » / Échap le referme)."""
        if getattr(self, "_side_viewer", None) is not None:
            return True
        return bool(getattr(self, "_md_open", False) and self._md_side_left()) or bool(
            getattr(self, "_font", None) is not None and getattr(self._font, "side_left", 0))

    def _md_side_left(self) -> int:
        import fm_markdown.pane as md_pane
        pane = md_pane.instance(create=False)
        return getattr(pane, "side_left", 0) if pane is not None else 0

    def _close_side_modules(self) -> None:
        """Clic sur un dossier ou un fichier sans module : ce qui est ouvert à côté des colonnes se referme."""
        self._close_side_viewer()
        if getattr(self, "_md_open", False) and self._md_side_left():
            self._close_md_editor()
        font = getattr(self, "_font", None)
        if font is not None and getattr(font, "side_left", 0) and font.confirm_leave():
            self._close_font()

    def _make_module_full(self, path) -> bool:
        """Double-clic sur la ligne d'un fichier ouvert à côté : le module passe plein (les colonnes partent)."""
        path = Path(path)
        if getattr(self, "_md_open", False) and self._md_side_left():
            import fm_markdown.pane as md_pane
            pane = md_pane.instance(create=False)
            if pane is not None and Path(getattr(pane, "path", "") or "") == path:
                pane.set_side_left(0)
                return True
        font = getattr(self, "_font", None)
        if font is not None and getattr(font, "side_left", 0) and font.project.path == path:
            font.set_side_left(0)
            return True
        return False

    # -- Visionneuse à côté -------------------------------------------------------------------------------------------

    def _open_side_viewer(self, path: Path, column, left: int) -> None:
        source = column.preview_source(path) if column is not None else None
        if source is None:                        # rien à montrer tout de suite : la visionneuse pleine s'en charge
            self._close_side_viewer()
            self._view_in_viewer(path, column)
            return
        pixmap, rect = source
        self._close_side_viewer()
        viewer = _SideViewer(self.scroll.viewport(), left, path, pixmap, rect,
                             lambda p=path, c=column: self._side_viewer_to_full(p, c))
        self._side_viewer = viewer
        images = self._focus_images
        if not getattr(self, "_side_images_hooked", False):
            images.ready.connect(self._on_side_image_ready)
            self._side_images_hooked = True
        hit = images.get(path)
        if hit is not None:
            viewer.upgrade(hit[0], hit[2], hit[1])
        else:
            images.request(path, urgent=True)
        self._sync_mouse_back()

    def _on_side_image_ready(self, key: str) -> None:
        viewer = getattr(self, "_side_viewer", None)
        if viewer is None or str(viewer.path) != key:
            return
        hit = self._focus_images.get(viewer.path)
        if hit is not None:
            viewer.upgrade(hit[0], hit[2], hit[1])

    def _side_viewer_to_full(self, path: Path, column) -> None:
        self._close_side_viewer()
        self._view_in_viewer(path, column)

    def _close_side_viewer(self) -> bool:
        viewer = getattr(self, "_side_viewer", None)
        if viewer is None:
            return False
        self._side_viewer = None
        viewer.close_now()
        self._sync_mouse_back()
        return True
