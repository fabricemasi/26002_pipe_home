"""Masquer / montrer les colonnes de projet (fondu, instantanés) et l'image focus qui en sort.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

from browser_core import _FadeOverlay
from fm_visionneuse.focus import FocusOverlay

from .helpers import _anim_running
from .viewer_buttons import _shown_or_pending


class ColumnsHiddenMixin:
    """Méthodes de PipelineBrowser : masquer / montrer les colonnes de projet (fondu, instantanés) et l'image focus qui en sort."""

    def _toggle_project_columns_hidden(self):
        """Bouton « masquer les colonnes » (voir PreviewColumn.hide_btn) : TOUTES
        les colonnes disparaissent en fondu puis quittent la mise en page — leur
        place est liberee ; seuls les deux boutons restent. Un nouveau clic
        ramene tout (fondu inverse). Le fondu anime une capture fixe de la zone
        (voir _FadeOverlay) pendant que les vrais widgets sont deja masques."""
        self._set_columns_hidden(not self._project_columns_hidden)

    def _hideable_widgets(self) -> list:
        """Tout ce que columns_layout contient, sauf le conteneur des vignettes
        Focus (qui porte les boutons)."""
        widgets = []
        for i in range(self.columns_layout.count()):
            widget = self.columns_layout.itemAt(i).widget()
            if widget is not None and widget is not self._preview_stack_wrapper:
                widgets.append(widget)
        return widgets

    def _toggled_widgets(self) -> list:
        return self._hideable_widgets() + list(self.image_preview_columns[1:]) + [self.detail]

    def _apply_columns_hidden(self, hidden: bool):
        """Masque/restaure INSTANTANEMENT ; ne restaure que ce que le bouton a
        lui-meme masque (une colonne de set deja repliee reste repliee)."""
        if self.image_preview_columns and self.image_preview_columns[0].hide_btn is not None:
            # Le focus reste sur le bouton : masquer une liste qui l'a le donnerait a
            # une autre liste, qui changerait de selection (et rebatirait les colonnes).
            self.image_preview_columns[0].hide_btn.setFocus()
        elif hidden:
            # Pas de bouton (masquage par double-clic sans colonnes Focus) : le
            # focus est gare sur la zone des colonnes, pour la meme raison.
            self.scroll.viewport().setFocus()
        for widget in self._toggled_widgets():
            if hidden:
                if _shown_or_pending(widget):
                    widget._hidden_by_toggle = True
                    widget.setVisible(False)
            elif getattr(widget, "_hidden_by_toggle", False):
                widget._hidden_by_toggle = False
                widget.setVisible(True)
        if self.image_preview_columns:
            self.image_preview_columns[0].set_buttons_only(hidden)

    def _columns_visible_rect(self) -> QRect:
        viewport = self.scroll.viewport()
        rect = QRect()
        candidates = [*self._hideable_widgets(), *self.image_preview_columns, self.detail]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        for widget in candidates:
            if widget.isVisible():
                rect = rect.united(QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size()))
        return rect.intersected(viewport.rect())

    def _columns_content_right(self) -> int:
        """Bord droit (repere du viewport) de la derniere colonne visible, inspecteur exclu."""
        viewport = self.scroll.viewport()
        right = 0
        candidates = [*self._hideable_widgets(), *self.image_preview_columns]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        for widget in candidates:
            if widget.isVisible() and widget.width() > 0:
                right = max(right, widget.mapTo(viewport, QPoint(0, 0)).x() + widget.width())
        return right

    def _column_spans(self, rect: QRect) -> list:
        """Bandes (x0, x1), dans le repere de `rect`, une par colonne visible, de gauche a
        droite ; elles se touchent (l'espace entre deux colonnes va a la precedente)."""
        viewport = self.scroll.viewport()
        candidates = [*self._hideable_widgets(), *self.image_preview_columns, self.detail]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        starts = sorted({max(0, widget.mapTo(viewport, QPoint(0, 0)).x() - rect.x())
                         for widget in candidates if widget.isVisible() and widget.width() > 0})
        starts = [x for x in starts if x < rect.width()]
        if len(starts) < 2:
            return []
        starts[0] = 0
        return list(zip(starts, [*starts[1:], rect.width()]))

    def _button_rects(self) -> list:
        """Boutons poses SUR la zone des colonnes (trous de l'image, clics a cote) ; ceux du cadre « Visionneuse »
        de la barre de navigation n'y sont pas."""
        viewport = self.scroll.viewport()
        rects = self._base_button_rects()
        for widget in (self._filter_btn, self._filter_chips, self._lightroom_btn, self._viewer_100_btn,
                       self._recursive_btn, *self._pur_buttons):
            if widget is not None and widget.isVisible() and widget.parentWidget() is viewport:
                rects.append(widget.geometry())
        return rects

    def _base_button_rects(self) -> list:
        """Boutons repli / masquer / planche (ou le bouton flottant) : les autres viennent a leur suite."""
        viewport = self.scroll.viewport()
        rects = []
        if self.image_preview_columns:
            pc = self.image_preview_columns[0]
            for button in (pc.toggle_btn, pc.hide_btn, pc.gallery_btn):
                if (button is not None and (button is not pc.gallery_btn or button.isVisible())
                        and viewport.isAncestorOf(button)):
                    rects.append(QRect(button.mapTo(viewport, QPoint(0, 0)), button.size()))
        floating = self._floating_gallery_btn
        if floating is not None and floating.isVisible() and floating.parentWidget() is viewport:
            rects.append(floating.geometry())
        return rects

    def _fade_snapshot_fresh(self) -> bool:
        """La capture « masquer » depend de la taille, de la navigation ET de l'etat
        replie/deplie des colonnes de set."""
        cached = self._columns_snapshot
        return (cached is not None and len(cached) > 5 and cached[2] == self.scroll.viewport().size()
                and cached[3] == self._columns_epoch and cached[5] == self._project_columns_collapsed
                and time.monotonic() - cached[4] < 8.0)

    def _grab_columns(self) -> tuple:
        """Capture de la zone des colonnes dans son etat actuel, avec les boutons
        effaces (transparents) : ils restent reels et ne s'estompent pas. Les
        boutons ne sont PAS masques pour la capture : masquer celui qui a le
        focus le transmettrait a une liste, qui changerait de selection."""
        if _anim_running(self._columns_slide):
            self._columns_slide.finish_now()   # jamais de capture avec un overlay par-dessus
        rect = self._columns_visible_rect()
        viewport = self.scroll.viewport()
        self._columns_spans = self._column_spans(rect)
        image = viewport.grab(rect).toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        for button_rect in self._button_rects():
            painter.fillRect(button_rect.translated(-rect.topLeft()), Qt.transparent)
        painter.end()
        return QPixmap.fromImage(image), rect, viewport.size(), self._columns_epoch

    def _set_columns_hidden(self, hidden: bool, animate: bool = True):
        # Sans colonnes Focus (donc sans bouton), on ne masque que si un objet
        # peut partir au centre : on revient par Echap ou le bouton « precedent » de la souris.
        if hidden == self._project_columns_hidden or (
                hidden and not self.image_preview_columns and self._focus_source() is None
                and getattr(self, "_viewer_entry_source", None) is None
                and not getattr(self, "_viewer_force_hide", False)):
            return
        if not hidden:
            if self._focus_gallery is not None:
                # Sortie depuis la PLANCHE : aucune image n'a le focus, donc aucune selectionnee.
                self._leave_viewer_unselected()
            else:
                self._close_focus_gallery(animate=False)   # l'image revient au centre avant de repartir
                self._flush_viewer_sync()                   # colonne + inspecteur sur l'image montree
                if self._focus_overlay is not None:
                    self._focus_overlay.reset_view()        # repart ajustee, sans zoom
        self._project_columns_hidden = hidden
        self._sync_floating_gallery_btn()
        for preview_column in self.image_preview_columns:
            preview_column.set_hide_state(hidden)
        overlay = self._columns_fade
        if _anim_running(overlay):
            # Clic pendant un fondu : on repart de l'opacite courante, a l'envers.
            overlay.retarget(0.0 if hidden else 1.0, None if hidden else self._show_columns_now)
            if self._focus_overlay is not None:
                self._focus_overlay.retarget(1.0 if hidden else 0.0)
            if hidden:
                self._enter_viewer()
            return
        if not animate:
            self._apply_columns_hidden(hidden)
            if hidden:
                self._enter_viewer()
            return
        if hidden:
            if self._columns_slide is not None:
                self._columns_slide.finish_now()   # on ne capture jamais un mouvement en cours
            self.columns_layout.activate()
            self._clear_focus_overlay()
            home = self._focus_source()
            self._focus_src = self._entry_focus_source(home)      # double-clic : depuis la ligne
            from_row = self._focus_src is not home
            if not self._fade_snapshot_fresh():
                self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)
            self._apply_columns_hidden(True)
            self._start_columns_fade(1.0, 0.0, None)
            self._start_focus_overlay(1.0)
            if from_row:
                self._focus_src = home
                overlay = self._focus_overlay
                if overlay is not None:
                    overlay._on_finished = lambda o=overlay, h=home: self._send_focus_home(o, h)
            self._enter_viewer()
            return
        if not self._fade_snapshot_fresh() and self._columns_snapshot is not None and \
                (self._columns_snapshot[2] != self.scroll.viewport().size()
                 or self._columns_snapshot[3] != self._columns_epoch
                 or (len(self._columns_snapshot) > 5 and self._columns_snapshot[5] != self._project_columns_collapsed)):
            self._columns_snapshot = None
        snapshot = self._columns_snapshot
        if snapshot is None:
            # Capture perimee (navigation, redimensionnement ou visionneuse pendant le masquage) :
            # on affiche, on capture, on re-masque avant tout rendu a l'ecran (aucun retour a la
            # boucle d'evenements entre les deux). PAS de setUpdatesEnabled(False) ici : grab()
            # respecte ce drapeau et rendait une capture VIDE (fond seul) -> pas de fondu, les
            # colonnes surgissaient d'un coup a la fin.
            try:
                self._apply_columns_hidden(False)
                self._settle_columns_layout()
                self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)
                self._retarget_focus_source()
            finally:
                self._apply_columns_hidden(True)
        elif len(snapshot) > 6 and snapshot[6] is not None:
            self._retarget_focus_source(snapshot[6])     # capture faite d'avance : sa place de retour
        self._start_columns_fade(0.0, 1.0, self._show_columns_now)
        self._start_focus_overlay(0.0)

    def _leave_viewer_unselected(self):
        """Sortie de la visionneuse alors que la planche est ouverte (aucune image en grand) : la
        planche disparait, l'image en focus aussi (rien ne repart vers l'inspecteur) et la colonne du
        dossier n'a plus AUCUN fichier selectionne (meme chemin qu'un re-clic sur la ligne : les
        colonnes ouvertes apres elle se ferment, l'inspecteur se vide). Appele colonnes encore
        masquees : la deselection se fait sans fondu, celui du retour des colonnes suffit."""
        gallery = self._focus_gallery
        self._focus_gallery = None
        self._set_gallery_buttons_state(False)
        if gallery is not None:
            self._gallery_memory = (gallery.path_keys(), gallery.first_visible_row())
            gallery.blockSignals(True)
            gallery.hide()
            gallery.deleteLater()
        self._viewer_sync.stop()
        self._clear_focus_overlay()
        self._focus_src = None
        if not self._gallery_deselected:
            self._deselect_viewer_file()
        self._gallery_deselected = False

    def _deselect_viewer_file(self):
        """La colonne du dossier de la visionneuse n'a plus AUCUN fichier selectionne (meme chemin qu'un
        re-clic), l'inspecteur se vide. Colonnes masquees : sans fondu."""
        column, current = self._focus_file_column()
        if column is None:
            # Colonne pas encore alignee sur le fichier (navigation en attente) : celle qui montre
            # un fichier du dossier de la visionneuse.
            folder = Path(self._viewer_paths[0]).parent if self._viewer_paths else None
            column = next((c for c in [*self.columns, *self.group_columns]
                           if folder is not None and c.current_path() is not None
                           and c.current_path().parent == folder), None)
        if column is not None:
            self.on_reclicked(column)
        else:
            self.detail.clear()

    def _retarget_focus_source(self, relevee: tuple | None = None):
        """Capture perimee : l'inspecteur vient d'etre re-affiche pour la refaire,
        on en profite pour relever la vraie place de l'objet en focus (et son
        contenu actuel) comme point d'arrivee du retour. `relevee` : place deja
        relevee lors de la capture faite d'avance (_pregrab_columns), `(source,)`."""
        source = self._focus_source() if relevee is None else relevee[0]
        self._focus_src = source
        overlay = self._focus_overlay
        if source is None:
            self._clear_focus_overlay()
        elif overlay is not None:
            if getattr(self.detail, "_current_path", None) != self._focus_path:
                # Autre fichier que celui montre : son image. Sinon l'image du centre (pleine
                # definition) repart telle quelle, sans passer par l'apercu de l'inspecteur.
                overlay._base = source[0]
                overlay._natural = None
                overlay._cache_key = None
            overlay.set_geometry_target(None, QRectF(source[1]))     # meme zone : l'image ne saute pas

    def _show_columns_now(self):
        self._apply_columns_hidden(False)
        self._clear_focus_overlay()
        self._focus_src = None

    def _start_columns_fade(self, start: float, end: float, on_finished):
        pixmap, rect = self._columns_snapshot[0], self._columns_snapshot[1]
        self.columns_layout.activate()
        spans = getattr(self, "_columns_spans", [])
        overlay = _FadeOverlay(self.scroll.viewport(), pixmap, rect, start, end, 420 if len(spans) > 1 else 260,
                               on_finished, on_done=lambda: setattr(self, "_columns_fade", None))
        overlay.set_spans(spans)
        holes = self._button_rects()
        if self._focus_src is not None:
            holes.append(self._focus_src[1])   # l'objet en focus voyage a part : pas de double dans le fondu
        overlay.set_holes(holes)
        overlay.show()
        overlay.raise_()
        self._columns_fade = overlay
        if self._focus_overlay is not None:
            self._focus_overlay.raise_()
        self._raise_viewer_chrome()

    def _focus_source(self):
        """(pixmap, QRect en coordonnees du viewport) de l'objet en focus tel que
        l'inspecteur l'affiche, ou None. Exige l'inspecteur visible et mis en page."""
        if not self.detail.isVisible():
            return None
        source = self.detail.focus_source()
        if source is None:
            return None
        pixmap, rect = source
        viewport = self.scroll.viewport()
        return pixmap, QRect(self.detail.mapTo(viewport, rect.topLeft()), rect.size())

    def _focus_area(self) -> QRect:
        return self.scroll.viewport().rect()

    def _start_focus_overlay(self, end: float):
        """Fait voyager l'objet en focus : end=1.0 de l'inspecteur vers le centre
        (masquage), end=0.0 du centre vers l'inspecteur (retour). Meme duree que
        le fondu des colonnes."""
        source = self._focus_src
        if source is None:
            return
        pixmap, rect = source
        spans = getattr(self, "_columns_spans", [])
        duration = 420 if len(spans) > 1 else 260
        overlay = self._focus_overlay
        if overlay is not None:
            overlay._duration = duration
            overlay.retarget(end)
            overlay.raise_()
            self._raise_viewer_chrome()
            return
        area = self._viewer_area()
        overlay = FocusOverlay(self.scroll.viewport(), pixmap, QRectF(rect), FocusOverlay.target_rect(pixmap, area),
                                1.0 - end, end, duration,
                                on_double_click=self._toggle_project_columns_hidden,
                                on_wheel=self._on_focus_wheel)
        overlay.show()
        overlay.raise_()
        self._focus_overlay = overlay
        self._raise_viewer_chrome()

    def _clear_focus_overlay(self):
        overlay = self._focus_overlay
        self._focus_overlay = None
        self._focus_home = None
        self._focus_path = None
        if overlay is not None:
            overlay.dispose()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pur_buttons or self._filter_btn is not None:
            self._sync_filter_button()               # bouton filtre puis boutons PureRef : a la suite des autres
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.set_geometry_target(self._viewer_area())
        self._position_focus_origin_badge()
        if self._focus_gallery is not None:
            self._focus_gallery.setGeometry(self._gallery_rect())
        self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
        if self._filmstrip is not None:
            self._filmstrip.setGeometry(self._filmstrip_rect())
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.setGeometry(self._info_rect())
