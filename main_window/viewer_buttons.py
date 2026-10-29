"""Rangée des boutons de la visionneuse / planche : ordre choisi à la main (Ctrl + glisser).

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget

from app_style import C, role_color, scaled
from preview_column import IconButton, style_focus_button
from settings_store import save_live_state
import ui_state
import shiboken6


def _shown_or_pending(widget) -> bool:
    """Visible, ou sur le point de l'etre : un widget tout juste (re)construit (ex. colonne Focus
    rebatie par une navigation pendant que les colonnes sont masquees) n'est pas encore visible
    mais Qt l'affichera de lui-meme, faute d'avoir ete masque explicitement. Un widget masque
    expres par ailleurs (WA_WState_ExplicitShowHide + cache) n'est pas concerne."""
    return widget.isVisible() or not widget.testAttribute(Qt.WA_WState_ExplicitShowHide)


class _ViewerButtonDrag(QObject):
    """Ctrl + glisser un bouton de la rangee de la visionneuse / planche (masquer, planche, filtre,
    PureRef) : regle de l'appli pour tout deplacement — le bouton suit le curseur a 75 %
    (DRAG_GHOST_OPACITY), son emplacement d'origine reste a 25 %, le seul emplacement vise est en
    surbrillance (`settings_layout._ReorderOverlay`, axe x, pose sur une bande de la hauteur de la
    rangee). Sans Ctrl, le clic garde son sens."""

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.press = None                    # (bouton, position globale de l'appui)
        self.overlay = None
        self.strip = None
        self.keys: list = []

    def hook(self, button):
        if not getattr(button, "_row_drag_hooked", False):
            button._row_drag_hooked = True
            button.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.press = (obj, event.globalPosition().toPoint())
                return True                  # Ctrl : pas de clic
            return False
        if self.press is None or self.press[0] is not obj:
            return False
        if kind == QEvent.MouseMove:
            pos = event.globalPosition().toPoint()
            if self.overlay is None and (pos - self.press[1]).manhattanLength() >= 4:
                self._start(obj)
            if self.overlay is not None:
                self.overlay.follow(self.strip.mapFromGlobal(pos).x())
            return True
        if kind == QEvent.MouseButtonRelease:
            self._finish()
            return True
        return kind == QEvent.MouseButtonDblClick

    def _start(self, button):
        from types import SimpleNamespace
        from settings_layout import _ReorderOverlay
        browser = self.browser
        items = browser._viewer_row_items()
        widgets = [w for _k, w in items]
        if button not in widgets:
            self.press = None
            return
        viewport = button.parentWidget()          # le cadre « Visionneuse » de la barre de navigation
        self.keys = [k for k, _w in items]
        rects = [QRect(w.mapTo(viewport, QPoint(0, 0)), w.size()) for w in widgets]
        top = min(r.top() for r in rects)
        bottom = max(r.bottom() for r in rects)
        left = max(0, min(r.left() for r in rects) - scaled(8, 0))
        right = min(viewport.width(), max(r.right() for r in rects) + scaled(8, 0))
        strip = self.strip = QWidget(viewport)
        strip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        strip.setStyleSheet("background: transparent;")     # les autres boutons restent visibles dessous
        strip.setGeometry(left, top, max(1, right - left), bottom - top + 1)
        strip.show()
        strip.raise_()
        spans = [(r.left() - left, r.right() + 1 - left) for r in rects]
        head = SimpleNamespace(_column_spans=lambda: spans, _order=list(range(len(spans))))
        source = widgets.index(button)
        grab_dx = strip.mapFromGlobal(self.press[1]).x() - spans[source][0]
        # Voile de l'emplacement d'origine : la couleur du fond juste a gauche de la rangee.
        probe = viewport.grab(QRect(max(0, left - 2), top + (bottom - top) // 2, 1, 1)).toImage()
        self.overlay = _ReorderOverlay(strip, head, source, button.grab(), 0, grab_dx)
        self.overlay.setStyleSheet("background: transparent;")
        self.overlay.veil_color = probe.pixelColor(0, 0).name() if not probe.isNull() else C["void"]

    def _finish(self):
        overlay, strip = self.overlay, self.strip
        self.press = self.overlay = self.strip = None
        if overlay is None:
            return
        target, source = overlay.target, overlay.source
        strip.hide()
        strip.deleteLater()
        if target is not None:
            self.browser._move_viewer_button(self.keys, source, target)


class ViewerButtonsMixin:
    """Méthodes de PipelineBrowser : rangée des boutons de la visionneuse / planche : ordre choisi à la main (Ctrl + glisser)."""

    # -- Rangee des boutons de la visionneuse / planche : ordre choisi a la main (Ctrl + glisser) --

    _BUTTON_DEFAULT_ORDER = ("hide", "gallery", "zoom100", "lightroom", "filter", "recursive", "pur", "settings")

    def _viewer_row_items(self) -> list:
        """(identifiant, bouton) des boutons deplacables de la rangee, dans l'ordre retenu
        (`viewer_button_order`) ; ceux qui n'y sont pas encore suivent, dans l'ordre par defaut. Le bouton
        de repliement reste en tete (sa place est un reglage)."""
        items = []
        if self.image_preview_columns:
            pc = self.image_preview_columns[0]
            for key, button in (("hide", pc.hide_btn), ("gallery", pc.gallery_btn)):
                if button is not None and not button.isHidden():
                    items.append((key, button))
        for key, button in (("gallery", self._floating_gallery_btn),
                            ("zoom100", self._viewer_100_btn),
                            ("lightroom", self._lightroom_btn), ("filter", self._filter_btn),
                            ("recursive", self._recursive_btn)):
            if button is not None and not button.isHidden():
                items.append((key, button))
        items.extend((f"pur:{b._pur_path.name}", b) for b in self._pur_buttons if not b.isHidden())
        items.append(("settings", self._viewer_settings_button()))
        order = list((ui_state.APPLIED_SETTINGS or {}).get("viewer_button_order") or [])
        defaults = self._BUTTON_DEFAULT_ORDER

        def rank(pair):
            index, (key, _button) = pair
            if key in order:
                return (0, order.index(key), index)
            return (1, defaults.index(key.split(":", 1)[0]), index)
        return [item for _i, item in sorted(enumerate(items), key=rank)]

    def _viewer_settings_button(self):
        """Bouton « Réglages de la visionneuse », ne de son cadre (il n'a pas d'autre place que la rangee)."""
        button = getattr(self, "_viewer_settings_btn", None)
        if button is None or not shiboken6.isValid(button):
            button = self._viewer_settings_btn = IconButton(
                "gear", role_color("buttons", "#c4cacf"), C["text"], parent=self.titlebar.viewer_group())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.setToolTip("Réglages de la visionneuse")
            button.clicked.connect(lambda: self.open_module_settings("viewer"))
            style_focus_button(button)
        return button

    def _layout_viewer_buttons(self):
        """Pose la rangee dans l'ordre retenu DANS le cadre « Visionneuse » de la barre de navigation (demande de
        l'utilisateur) ; les elements du filtre suivent son bouton. Colonnes masquees seulement : sinon les
        boutons retournent chez eux (la colonne Focus place elle-meme les siens)."""
        if not self._project_columns_hidden:
            self._release_viewer_buttons()
            return
        group = self.titlebar.viewer_group()
        items = self._viewer_row_items()
        chips = self._filter_chips
        hosted = []
        origin = group.content_origin()
        x = origin.x()
        gap = scaled(4, 0)
        height = max((button.height() for _k, button in items), default=0)
        for key, button in items:
            self._host_in_group(button, group)
            hosted.append(button)
            button.move(x, origin.y() + (height - button.height()) // 2)
            x += button.width() + gap
            self._button_drag.hook(button)
            if key == "filter" and chips is not None and not chips.isHidden():
                self._host_in_group(chips, group)
                hosted.append(chips)
                chips.move(x - gap + scaled(6), origin.y() + (height - chips.height()) // 2)
                x = chips.x() + chips.width() + scaled(6)
        for widget in list(getattr(self, "_group_hosted", ())):  # n'est plus dans la rangee : rendu a son parent
            if widget not in hosted:
                self._send_home(widget)
        self._group_hosted = hosted
        if not hosted:
            group.hide()
            return
        group.fit(x - gap, height)
        group.show()
        self.titlebar.place_viewer_group()
        for widget in hosted:
            widget.show()
            widget.raise_()
        pc = self.image_preview_columns[0] if self.image_preview_columns else None
        if pc is not None:
            pc.fit_buttons()

    @staticmethod
    def _host_in_group(widget: QWidget, group: QWidget):
        if widget.parentWidget() is not group:
            if not hasattr(widget, "_viewer_home"):
                widget._viewer_home = widget.parentWidget()
            widget.setParent(group)

    def _send_home(self, widget: QWidget):
        """Bouton sorti du cadre « Visionneuse » : rendu a son parent d'origine (colonne Focus, zone des colonnes) ;
        son parent a disparu (colonne Focus refaite) : detruit."""
        try:
            home = getattr(widget, "_viewer_home", None)
            if home is not None and shiboken6.isValid(home):
                widget.setParent(home)
                widget.hide()
                del widget._viewer_home
            else:
                widget.hide()
                widget.deleteLater()
        except RuntimeError:
            pass

    def _release_viewer_buttons(self):
        """Colonnes revenues : tous les boutons du cadre « Visionneuse » repartent chez eux, le cadre se cache ; le
        bouton « masquer » de la colonne Focus y redevient visible a sa place."""
        hosted = list(getattr(self, "_group_hosted", ()))
        self._group_hosted = []
        group = getattr(getattr(self, "titlebar", None), "_viewer_group", None)
        if group is not None and not group.isHidden():
            group.hide()
        if not hosted:
            return
        for widget in hosted:
            self._send_home(widget)
        for pc in self.image_preview_columns:
            if not shiboken6.isValid(pc):
                continue
            if pc.hide_btn is not None and pc.hide_btn.parentWidget() is pc:
                pc.hide_btn.show()
            pc._place_hide_btn()

    def _move_viewer_button(self, keys: list, source: int, target: int):
        """Glisser termine : le bouton `source` passe devant l'emplacement `target` (0..len) ; ordre
        enregistre aussitot (etat temps reel), les boutons absents gardent leur rang relatif a la fin."""
        keys = list(keys)
        moved = keys.pop(source)
        keys.insert(target - (1 if target > source else 0), moved)
        settings = ui_state.APPLIED_SETTINGS if isinstance(ui_state.APPLIED_SETTINGS, dict) else {}
        saved = list(settings.get("viewer_button_order") or [])
        order = keys + [k for k in saved if k not in keys]
        settings["viewer_button_order"] = order
        from settings_store import save_live_state
        save_live_state("viewer_button_order", order)
        self._layout_viewer_buttons()

    @staticmethod
    def _filmstrip_enabled() -> bool:
        """Reglages > Visionneuse > « Diapositives sous l'image en focus » (la pellicule)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_filmstrip_enabled", True))

    @staticmethod
    def _info_enabled() -> bool:
        """Reglages > Visionneuse > « Parametres de l'image » (tableau a droite de l'image)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_info_enabled", False))

    @staticmethod
    def _viewer_slide_enabled() -> bool:
        """Reglages > Visionneuse > « Effet slide entre les images » (le ruban)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_slide_enabled", True))

    def _apply_viewer_settings(self):
        """Reglages de la visionneuse appliques en direct : pellicule affichee ou non, et l'image
        au centre recalee sur la zone qui lui revient (la bande de la pellicule est liberee)."""
        self._sync_viewer_toggle_keys()
        recursive = self._recursive_on()
        if recursive != getattr(self, "_recursive_applied", recursive):
            self._recursive_applied = recursive                  # ligne « Recursif » des reglages
            self._refresh_recursive_list(recursive)
        self._recursive_applied = recursive
        group = getattr(getattr(self, "titlebar", None), "_viewer_group", None)
        if group is not None:
            group.restyle()                     # Reglages > Visionneuse > Regroupement
            if not group.isHidden():
                self._layout_viewer_buttons()
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.restyle()                     # habillage des reglages : suit leurs changements
        self._sync_viewer_chrome()
        strip = self._filmstrip
        if strip is not None and strip.isVisible():
            # Habillage des diapositives (Reglages > Visionneuse > Tableau / sous-cellules) : la
            # bande suit la hauteur des cellules (image + texte).
            if strip.height() != strip.strip_height():
                strip.setGeometry(self._filmstrip_rect())
            strip.update()
            strip.reveal()                       # montree pendant qu'on la regle (sinon effacee)
        if self._focus_gallery is not None:
            self._focus_gallery.restyle()        # la planche : memes reglages
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.restyle()                    # Reglages > Visionneuse > Focus : cadre de l'image
        if overlay is not None and self._project_columns_hidden:
            overlay.set_geometry_target(self._viewer_area())
            self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
