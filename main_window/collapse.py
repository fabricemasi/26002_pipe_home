"""Repli des colonnes de projet : glissement, instantanés préparés, largeur de l'inspecteur.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import time

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from app_style import C, auto_collapse_set_columns
from browser_core import _SlideOverlay, DETAIL_PANEL_MIN_WIDTH

from .helpers import _anim_running
from .viewer_buttons import _shown_or_pending


class CollapseMixin:
    """Méthodes de PipelineBrowser : repli des colonnes de projet : glissement, instantanés préparés, largeur de l'inspecteur."""

    def _enforce_hidden_columns(self, final: bool = False):
        try:
            self._enforce_hidden_columns_now(final)
        finally:
            # Colonnes Focus apparues / disparues, ou retour force : le bouton flottant suit.
            self._sync_floating_gallery_btn()

    def _enforce_hidden_columns_now(self, final: bool = False):
        """Garde tout masque pendant que le bouton « masquer » est actif, y
        compris ce que la navigation vient de (re)construire. Sans colonne
        Focus (donc sans bouton pour revenir) ni objet au centre (double-clic
        pour revenir), tout est reaffiche — decision prise uniquement apres une
        reconstruction COMPLETE des vignettes (`final`), pas pendant l'etat
        transitoire d'une navigation."""
        if not self._project_columns_hidden:
            return
        if self._focus_gallery is not None:
            # Planche ouverte (ex. « Ouvrir la visionneuse à cet endroit » : aucune image en focus, donc aucun
            # objet au centre) : tout reste masqué, c'est la planche qui est le contenu.
            return
        if not self.image_preview_columns and self._focus_overlay is not None:
            # Masque par double-clic sur un apercu, sans colonnes Focus : rien a
            # reconstruire, on garde juste tout masque.
            if not _anim_running(self._columns_fade):
                self._apply_columns_hidden(True)
            return
        if not self.image_preview_columns:
            if final:
                self._project_columns_hidden = False
                self._apply_columns_hidden(False)
                self._clear_focus_overlay()
                self._focus_src = None
            else:
                for widget in self._toggled_widgets():
                    if _shown_or_pending(widget):
                        widget._hidden_by_toggle = True
                        widget.setVisible(False)
            return
        if _anim_running(self._columns_fade):
            return
        self._apply_columns_hidden(True)
        for preview_column in self.image_preview_columns:
            preview_column.set_hide_state(True)

    def _auto_expand_now(self):
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        if self._project_columns_collapsed and (self._chain_terminal_path() is None or not focus_enabled):
            self._apply_project_columns_collapsed(False)

    def _auto_collapse_now(self, animate: bool = True):
        """Repli automatique differe (voir _sync_collapse_state), re-verifie : la
        navigation a pu changer entre-temps."""
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        if (self._chain_terminal_path() is not None and focus_enabled and auto_collapse_set_columns()
                and not self._project_columns_collapsed):
            self._apply_project_columns_collapsed(True, animate=animate)

    def _toggle_project_columns(self):
        """Reagit a l'icone unique portee par la colonne des vignettes
        (voir PreviewColumn/update_preview_stack) : bascule les colonnes de
        la chaine (voir _apply_project_columns_collapsed), et desarme le
        repli automatique pour que ce choix manuel ne soit pas aussitot
        ecrase par _sync_collapse_state tant que la chaine reste la meme.
        Toujours disponible, MEME si le repli automatique est desactive
        (voir auto_collapse_set_columns/_sync_collapse_state) : c'est un
        geste manuel independant."""
        self._apply_project_columns_collapsed(not self._project_columns_collapsed)

    def _on_preview_column_resized(self, new_width: int):
        """Relais de PreviewColumn.resize_update (voir _preview_column_
        user_width, sa remarque de tete) : conserve la largeur choisie a la
        main pour qu'elle survive a la PROCHAINE reconstruction des
        colonnes Focus (update_preview_stack, appelee a chaque navigation),
        ET la repercute TOUT DE SUITE sur les AUTRES colonnes Focus (voir
        PreviewColumn.set_width_external) : ce sont des colonnes SEPAREES
        (voir la remarque de l'utilisateur, "deux colonnes separees, une
        en dessous de l'autre") mais elles doivent rester alignees a la
        meme largeur, glisser le bord de L'UNE suffit a redimensionner
        les autres."""
        self._preview_column_user_width = new_width
        for column in self.image_preview_columns:
            if column.width() != new_width:
                column.set_width_external(new_width)
        self._auto_collapse_armed = False

    def _apply_project_columns_collapsed(self, collapsed: bool, animate: bool = True):
        """Replie/deplie EXACTEMENT les N premieres colonnes de self.columns
        (voir _chain_expected_total), N = le nombre d'etapes du projet
        courant — jamais au-dela : une colonne de contenu ouverte depuis le
        groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) reste
        TOUJOURS deployee, quoi qu'il arrive aux colonnes de set — voir la
        remarque de l'utilisateur, "attention a bien rabattre toutes
        colonnes ... c'est toutes les colonnes avant les colonnes de
        focus". Le mouvement est joue sur des captures (voir _SlideOverlay) :
        l'etat final est applique tout de suite, sans animer de largeur reelle
        (ce qui recalculait toutes les colonnes a chaque image)."""
        was_collapsed = self._project_columns_collapsed
        self._project_columns_collapsed = collapsed
        self._columns_snapshot = None   # le contenu des colonnes change : capture du fondu perimee
        if self.image_preview_columns:
            self.image_preview_columns[0].set_toggle_state(collapsed)
        self._sync_collapse_button()
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        slide = self._columns_slide
        if _anim_running(slide) and slide.emerge:
            slide.finish_now()   # apparition d'une colonne : on la termine, elle ne se « retourne » pas
            slide = None
        if _anim_running(slide):
            # Clic pendant le mouvement : repart de la position courante.
            slide.retarget(0.0 if collapsed else 1.0, None if collapsed else self._expand_columns_now)
            return
        if (not animate or self._project_columns_hidden or not targets or was_collapsed == collapsed
                or not self.isVisible()):
            self._set_columns_collapsed_now(collapsed)
            return
        viewport = self.scroll.viewport()
        cached = self._slide_snapshot
        valid = (cached is not None and cached[5] == self._columns_epoch and cached[6] == viewport.size()
                 and cached[7] == len(targets))
        if collapsed:
            self._detail_state_width[False] = self.detail.width()   # etat deplie reel, avant repli
            if valid and time.monotonic() - cached[8] < 8.0:
                snapshot = cached[:5]             # amorcee au survol du bouton
            else:
                self.columns_layout.activate()
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                snapshot = self._grab_set_columns()   # etat deplie actuel
            self._set_columns_collapsed_now(True)
        elif valid:
            snapshot = cached[:5]                 # capture deja prise au repli : aucun cout au depart
        else:
            snapshot = self._grab_expanded_silently()   # etat deplie final, jamais affiche
        if snapshot is not None and self._snapshot_blank(snapshot):
            # Capture vide (colonnes pas encore peintes) : on ne l'anime jamais sur un fond
            # vide. Nouvelle capture, cette fois sans suspendre les mises a jour.
            self._slide_snapshot = None
            snapshot = None if collapsed else self._grab_expanded_silently(suspend=False)
            if snapshot is not None and self._snapshot_blank(snapshot):
                snapshot = None
        if snapshot is None:
            self._set_columns_collapsed_now(collapsed)
            return
        self._slide_snapshot = (*snapshot, self._columns_epoch, viewport.size(), len(targets), time.monotonic())
        left, right, x_expanded, background, limit = snapshot
        self.columns_layout.activate()
        x_collapsed = self._set_columns_anchor_x()
        follow = None
        overlay_ref = []
        if self.detail.isVisible():
            # w_expanded : largeur de l'inspecteur dans la capture (colonnes depliees) ;
            # w_collapsed : sa largeur colonnes repliees (deja appliquee ici).
            widths = self._detail_state_width
            follow = self._detail_follow(
                overlay_ref, self.detail.width(),
                widths.get(False, self.detail.width()), limit)
        overlay = _SlideOverlay(
            viewport, left, right, x_collapsed, x_expanded, background,
            0.0 if collapsed is False else 1.0, 0.0 if collapsed else 1.0, 200,
            None if collapsed else self._expand_columns_now,
            on_done=self._slide_done, limit=limit, on_progress=follow)
        overlay_ref.append(overlay)
        if follow is not None:
            follow(overlay._value)
        overlay.show()
        overlay.raise_()
        self._columns_slide = overlay

    def _slide_done(self):
        self._columns_slide = None
        self._columns_snapshot = None   # etat final change : toute capture du fondu est perimee

    def _prime_slide_snapshot(self):
        """Au survol du bouton de repli : prepare la capture de l'etat deplie."""
        if (self._project_columns_hidden or _anim_running(self._columns_slide)
                or not self.isVisible()):
            return
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        if self._project_columns_collapsed:
            # Replie : il faut deplier un instant (sans rien afficher) pour capturer
            # l'etat deplie. Differe et conditionne a un survol qui dure, pour ne
            # pas figer l'interface quand la souris ne fait que passer.
            QTimer.singleShot(60, self._prime_expanded_snapshot)
            return
        cached = self._slide_snapshot
        size = self.scroll.viewport().size()
        if (not targets or (cached is not None and cached[5] == self._columns_epoch and cached[6] == size
                            and cached[7] == len(targets) and time.monotonic() - cached[8] < 8.0)):
            return
        self.columns_layout.activate()
        snapshot = self._grab_set_columns()
        if snapshot is not None:
            self._slide_snapshot = (*snapshot, self._columns_epoch, size, len(targets), time.monotonic())

    def _prime_expanded_snapshot(self, force: bool = False):
        column = self.image_preview_columns[0] if self.image_preview_columns else None
        if (column is None or not (force or self.btn_collapse.underMouse())
                or not self._project_columns_collapsed or self._project_columns_hidden
                or _anim_running(self._columns_slide)):
            return
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        size = self.scroll.viewport().size()
        cached = self._slide_snapshot
        if not targets or (cached is not None and cached[5] == self._columns_epoch and cached[6] == size
                           and cached[7] == len(targets) and time.monotonic() - cached[8] < 8.0):
            return
        snapshot = self._grab_expanded_silently()
        if snapshot is not None:
            self._slide_snapshot = (*snapshot, self._columns_epoch, size, len(targets), time.monotonic())

    def _prewarm_snapshots(self):
        """Apres 700 ms sans navigation : prepare les captures des deux boutons, en
        deux temps (chacun court) et seulement si l'utilisateur n'est pas en train
        d'agir (bouton de souris, menu, animation en cours)."""
        if (not self.isVisible() or self._project_columns_hidden or not self.image_preview_columns
                or QApplication.mouseButtons() != Qt.NoButton or QApplication.activePopupWidget() is not None
                or _anim_running(self._columns_slide)
                or _anim_running(self._columns_fade)):
            return
        self._prime_fade_snapshot()
        QTimer.singleShot(40, self._prewarm_slide)

    def _prewarm_slide(self):
        if (not self.isVisible() or self._project_columns_hidden or QApplication.mouseButtons() != Qt.NoButton
                or QApplication.activePopupWidget() is not None):
            return
        if self._project_columns_collapsed:
            self._prime_expanded_snapshot(force=True)
        else:
            self._prime_slide_snapshot()

    def _prime_fade_snapshot(self):
        """Au survol du bouton « masquer » : prepare la capture des colonnes."""
        if (self._project_columns_hidden or not self.image_preview_columns or not self.isVisible()
                or _anim_running(self._columns_fade)
                or _anim_running(self._columns_slide)):
            return
        if self._fade_snapshot_fresh():
            return
        self.columns_layout.activate()
        self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)

    @staticmethod
    def _snapshot_blank(snapshot) -> bool:
        """True si la capture des colonnes de set ne contient que la couleur de fond."""
        left, _right, _x, background, _limit = snapshot
        if left.isNull():
            return True
        image = left.toImage().scaled(48, 48, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        bg = background.rgb()
        return all((image.pixel(i, j) & 0xFFFFFF) == (bg & 0xFFFFFF)
                   for i in range(image.width()) for j in range(image.height()))

    def _grab_expanded_silently(self, suspend: bool = True):
        """Capture l'etat DEPLIE alors que les colonnes sont repliees, sans que cet etat
        ne soit jamais affiche : aucun retour a la boucle d'evenements entre le depli
        et le repli (sinon l'ecran se repeint et les colonnes « clignotent »), et les
        mises a jour sont suspendues par precaution."""
        viewport = self.scroll.viewport()
        host = self.columns_host
        if suspend:
            viewport.setUpdatesEnabled(False)
            host.setUpdatesEnabled(False)
        try:
            self._set_columns_collapsed_now(False)
            self.columns_layout.activate()
            snapshot = self._grab_set_columns()
        finally:
            self._set_columns_collapsed_now(True)
            if suspend:
                host.setUpdatesEnabled(True)
                viewport.setUpdatesEnabled(True)
        return snapshot

    def _set_columns_collapsed_now(self, collapsed: bool):
        for column in self.columns[:self._chain_expected_total()]:
            column.set_collapsed(collapsed, animate=False)
        self._fit_detail_now()
        # Largeur de l'inspecteur dans chaque etat, memorisee pour l'animation du depliage.
        self._detail_state_width[collapsed] = self.detail.width()

    def _fit_detail_width(self) -> int:
        """Largeur de l'inspecteur qui evite tout debordement (donc toute barre de
        defilement) avec les colonnes dans leur etat actuel : sa largeur voulue, reduite
        au besoin jusqu'a DETAIL_PANEL_MIN_WIDTH."""
        self.columns_layout.invalidate()   # sizeHint() est mis en cache : largeurs des colonnes qui viennent de changer
        available = self.scroll.viewport().width() - self.columns_layout.sizeHint().width()
        return max(DETAIL_PANEL_MIN_WIDTH, min(self.detail._natural_width, available))

    def _fit_detail_now(self):
        if not self.detail.isVisible() or self.detail._resizing:
            return
        width = self._fit_detail_width()
        if self.detail.width() != width:
            self.detail.setFixedWidth(width)
        self.columns_host.layout().activate()   # replace l'inspecteur (capture, limite)

    def _detail_follow(self, overlay_ref: list, w_collapsed: int, w_expanded: int, limit: int):
        """Callback de progression du depliage : l'inspecteur se redimensionne en meme
        temps que les colonnes qui arrivent contre lui, et la capture (limitee a son bord
        gauche, `limit` quand il vaut `w_expanded`) suit."""
        def follow(p: float):
            width = max(1, int(round(w_collapsed + (w_expanded - w_collapsed) * p)))
            if self.detail.width() != width:
                self.detail.setFixedWidth(width)
            overlay = overlay_ref[0] if overlay_ref else None
            if overlay is not None:
                viewport = self.scroll.viewport()
                overlay.setGeometry(QRect(0, 0, max(1, limit + w_expanded - width), viewport.height()))
        return follow

    def _expand_columns_now(self):
        self._set_columns_collapsed_now(False)

    def _set_columns_anchor_x(self) -> int:
        """Abscisse (dans le viewport) du 1er widget place APRES les colonnes de set ;
        a defaut (rien encore a droite, par exemple pendant une navigation), le
        bord droit des colonnes de set elles-memes."""
        viewport = self.scroll.viewport()
        index = self._chain_expected_total()
        if index < self.columns_layout.count():
            widget = self.columns_layout.itemAt(index).widget()
            if widget is not None and widget.isVisible():
                return max(0, widget.mapTo(viewport, QPoint(0, 0)).x())
        edge = 0
        for column in self.columns[:index]:
            if column.isVisible() and column.width() > 0:
                edge = max(edge, column.mapTo(viewport, QPoint(column.width(), 0)).x())
        return edge + self.columns_layout.spacing() if edge else 0

    def _grab_set_columns(self):
        """(colonnes de set, colonnes a droite JUSQU'A L'INSPECTEUR, abscisse de
        separation, couleur de fond, abscisse de l'inspecteur) dans l'etat actuel ;
        None si rien a animer. L'inspecteur n'est jamais capture : il ne bouge pas."""
        return self._grab_set_columns_at(self._set_columns_anchor_x())

    def _grab_set_columns_at(self, x: int, start: int = 0):
        """`start` : la capture de gauche commence a cet x (apparition d'une colonne : seule la zone qui bouge)."""
        viewport = self.scroll.viewport()
        width, height = viewport.width(), viewport.height()
        limit = width
        if self.detail.isVisible():
            limit = min(width, max(0, self.detail.mapTo(viewport, QPoint(0, 0)).x()))
        if x <= 0 or x > limit or height <= 0:
            return None
        start = max(0, min(int(start), x - 1))
        # Une seule peinture : deux grab voisins repassaient dans les effets
        # graphiques des mêmes cartes. Découper ensuite les pixels déjà peints.
        whole = viewport.grab(QRect(start, 0, limit - start, height))
        dpr = whole.devicePixelRatio() or 1.0
        split = round((x - start) * dpr)
        left = whole.copy(0, 0, split, whole.height())
        right = whole.copy(split, 0, whole.width() - split, whole.height()) if limit > x else QPixmap()
        return left, right, x, QColor(C["window"]), limit
