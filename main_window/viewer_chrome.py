"""Visionneuse : pellicule, diapositives, panneau d'infos, navigation d'image, touches, zoom.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, QSize, QSizeF, Qt, QTimer
from PySide6.QtGui import QCursor, QKeySequence, QPixmap, QShortcut

from app_style import scaled
from config import RAW_EXTENSIONS
from settings_store import DEFAULT_SETTINGS, load_settings, save_settings
from settings_widgets import Menu
from browser_core import ROLE_PATH
from fm_visionneuse.focus import FocusInfoPanel, FocusOverlay, fit_rect
import ui_state
import previews as _previews

from .helpers import _anim_running


class ViewerChromeMixin:
    """Méthodes de PipelineBrowser : visionneuse : pellicule, diapositives, panneau d'infos, navigation d'image, touches, zoom."""

    # -- Diapositives : sous-cellules image | texte, tableau a la volee (clic droit) --

    def _on_filmstrip_split(self, ratio: float, final: bool):
        """Ctrl + bordure image | texte d'une diapositive : hauteur du texte, appliquee en direct (seule
        la bande suit pendant le geste ; l'image au centre se recale au relachement) et enregistree."""
        self._on_filmstrip_style({"viewer_film_text_ratio": round(float(ratio), 4)}, light=not final)
        if final:
            self._flush_filmstrip_style()

    def _on_gallery_split(self, height: int, final: bool):
        """Ctrl + bordure image | texte d'une case de la planche : hauteur du texte (px), en direct,
        enregistree."""
        self._on_filmstrip_style({"viewer_gallery_text_height": int(height)}, light=True)
        if self._focus_gallery is not None:
            self._focus_gallery.restyle()
        if final:
            self._flush_filmstrip_style()

    def _filmstrip_menu(self, global_pos):
        """Clic droit sur la pellicule : style du tableau, de la sous-cellule image ou de la sous-cellule
        texte, dans la fenetre « Changement de style a la volee » (pas d'override : une seule visionneuse,
        ce sont les valeurs de Reglages > Visionneuse)."""
        from settings_window_v2 import VIEWER_FILM_GROUPS
        menu = Menu(self)
        head = menu.addAction("Changement de style à la volée")
        head.setEnabled(False)
        menu.addSeparator()
        names = {"Tableau": "Tableau…", "Cellules": "Cellules…", "Sous cellule texte": "Cellule texte…"}
        actions = {menu.addAction(names.get(title, title)): (title, group) for title, group in VIEWER_FILM_GROUPS}
        chosen = menu.exec(global_pos)
        if chosen in actions:
            QTimer.singleShot(0, lambda: self._open_filmstrip_style(*actions[chosen]))

    def _open_filmstrip_style(self, title: str, group: str):
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        previous, self._film_style_window = getattr(self, "_film_style_window", None), None
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:              # deja detruite
                pass
        settings = dict(DEFAULT_SETTINGS)
        settings.update(ui_state.APPLIED_SETTINGS or load_settings())
        window = self._film_style_window = QuickStyleWindow(
            f"Visionneuse : {title}", v2.CATALOG[group], settings, title=f"Diapositives — {title.lower()}",
            settings=settings, parent=self)
        window.styleChanged.connect(self._on_filmstrip_style)
        window.destroyed.connect(lambda *_a, w=window: self._forget_film_style_window(w))
        window.move(QCursor.pos() + QPoint(12, 12))
        window.show()

    def _film_style_open(self) -> bool:
        """Une fenetre qui regle les diapositives est ouverte (tableau a la volee, reglages v2) : la
        pellicule reste affichee pour qu'on voie l'effet."""
        for window in (getattr(self, "_film_style_window", None), getattr(self, "_settings_dialog_v2", None)):
            try:
                if window is not None and window.isVisible():
                    return True
            except RuntimeError:
                pass
        return False

    def _forget_film_style_window(self, window):
        if getattr(self, "_film_style_window", None) is window:
            self._film_style_window = None
        self._flush_filmstrip_style()

    def _on_filmstrip_style(self, values: dict, light: bool = False):
        """Valeurs des diapositives changees (tableau a la volee, bordure image | texte) : appliquees aussitot,
        ecrites sur le disque 300 ms apres la derniere (regroupe un glissement de curseur)."""
        if not isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS = load_settings()
        ui_state.APPLIED_SETTINGS.update(values)
        pending = getattr(self, "_film_style_pending", None)
        if pending is None:
            pending = self._film_style_pending = {}
        pending.update(values)
        timer = getattr(self, "_film_style_timer", None)
        if timer is None:
            timer = self._film_style_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._flush_filmstrip_style)
        timer.start()
        strip = self._filmstrip
        if light:
            if strip is not None and strip.isVisible():
                strip.setGeometry(self._filmstrip_rect())
                strip.update()
        else:
            self._apply_viewer_settings()

    def _flush_filmstrip_style(self):
        """Enregistre les valeurs en attente ; la fenetre de reglages ouverte les reprend (ses tableaux
        Visionneuse sont refaits), sinon elle les ecraserait avec ses anciennes valeurs."""
        timer = getattr(self, "_film_style_timer", None)
        if timer is not None:
            timer.stop()
        pending = getattr(self, "_film_style_pending", None)
        if not pending:
            return
        values, self._film_style_pending = dict(pending), {}
        settings = load_settings()
        settings.update(values)
        save_settings(settings)
        # Preset par defaut actif : le mettre a jour aussi, sinon load_settings le rejoue PAR-DESSUS le
        # fichier au prochain lancement et les valeurs a la volee sont perdues (bug signale).
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.update(values))
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(values)
        except RuntimeError:                  # fenetre de reglages detruite
            pass

    def _on_filmstrip_resized(self):
        """Vignettes de la pellicule zoomees (Ctrl+molette) : sa bande change de hauteur, l'image
        au centre se recale sur la zone qui lui reste."""
        if self._filmstrip is not None and self._filmstrip.isVisible():
            self._filmstrip.setGeometry(self._filmstrip_rect())
        self._apply_viewer_settings()

    def _raise_viewer_chrome(self):
        """La pellicule et le bouton flottant restent au-dessus de l'image et des fondus."""
        for widget in (self._filmstrip, getattr(self, "_info_panel", None), self._floating_gallery_btn,
                       self._lightroom_btn, self._viewer_100_btn, self._recursive_btn,
                       getattr(self, "_focus_origin_badge", None), *self._pur_buttons):
            if widget is not None and widget.isVisible():
                widget.raise_()

    def _park_keyboard_focus(self):
        """Clavier gare sur le bouton « masquer » (ou la zone des colonnes) : jamais sur un champ
        texte visible, qui avalerait les raccourcis de la visionneuse."""
        if not self._project_columns_hidden:
            return
        if self.image_preview_columns and self.image_preview_columns[0].hide_btn is not None:
            self.image_preview_columns[0].hide_btn.setFocus()
        else:
            self.scroll.viewport().setFocus()

    def _filmstrip_rect(self) -> QRect:
        viewport = self.scroll.viewport()
        height = self._filmstrip.strip_height() if self._filmstrip is not None else 0
        return QRect(0, viewport.height() - height, viewport.width(), height)

    def _viewer_area(self) -> QRect:
        """Zone ou l'image se pose au centre : celle des colonnes, moins la bande de la pellicule
        (reservee meme quand elle s'efface : l'image ne bouge jamais et n'est jamais couverte) et
        moins celle du tableau des parametres a droite (Reglages > Visionneuse)."""
        area = QRect(self._focus_area())
        if not (self._project_columns_hidden and 0 <= self._viewer_index < len(self._viewer_paths)):
            return area                     # (planche ouverte comprise : l'image y revient a la meme place)
        strip = self._filmstrip
        if strip is not None and self._filmstrip_enabled():
            area.setHeight(max(1, area.height() - max(0, strip.strip_height() - scaled(30))))
        if self._info_enabled():
            # Bande du tableau retiree des DEUX cotes : l'image reste centree sur toute la largeur,
            # sans jamais passer sous le tableau.
            band = min(FocusInfoPanel.panel_width() + scaled(16), max(0, area.width() // 2 - 1))
            area.adjust(band, 0, -band, 0)
        return area

    def _info_rect(self) -> QRect:
        """Place du tableau des parametres : a droite de l'image, au-dessus de la pellicule."""
        full, area = self._focus_area(), self._viewer_area()
        margin = scaled(16)
        width = FocusInfoPanel.panel_width()
        return QRect(full.right() + 1 - margin - width, area.y() + margin, width,
                     max(1, area.height() - 2 * margin))

    def _sync_info_panel(self, active: bool):
        """Tableau des parametres de l'image (Reglages > Visionneuse > « Parametres de l'image »,
        touche I) : visible visionneuse ouverte, sur le fichier en cours."""
        panel = getattr(self, "_info_panel", None)
        if not (active and self._info_enabled()):
            if panel is not None and not panel.isHidden():
                panel.hide()
            return
        if panel is None:
            panel = self._info_panel = FocusInfoPanel(self.scroll.viewport())
        panel.setGeometry(self._info_rect())
        if 0 <= self._viewer_index < len(self._viewer_paths):
            panel.set_path(self._viewer_paths[self._viewer_index])
        if panel.isHidden():
            panel.show()
        panel.raise_()

    def _viewer_fit_size(self) -> QSize:
        """Zone ou l'image est ajustee, en pixels physiques (marges de fit_rect retirees)."""
        area = self._viewer_area()
        dpr = self.devicePixelRatioF() or 1.0
        return QSize(max(1, round((area.width() - 80) * dpr)), max(1, round((area.height() - 80) * dpr)))

    def _attach_viewer(self, overlay):
        overlay.set_viewer(self._viewer_neighbour, self._on_viewer_moved, self._button_rects(),
                           on_click=self._on_viewer_image_click)

    def _on_viewer_image_click(self, anchor=None):
        """Clic simple sur l'image : bascule entre ajustement ecran et taille reelle (100 %)."""
        if self._viewer_active() and self._focus_overlay is not None:
            self._focus_overlay.zoom_toggle_actual(anchor)

    def _viewer_go(self, index: int, delta: int = 0, fallback: QPixmap | None = None):
        """Montre le fichier de rang `index` ; `delta` = son ecart avec le precedent (le ruban
        glisse de ce cote). Rien de bloquant : image prete, sinon la meilleure en memoire en
        attendant (_on_focus_image_ready la remplace)."""
        paths = self._viewer_paths
        if not 0 <= index < len(paths):
            return
        self._viewer_index = index
        path = paths[index]
        self._sync_lightroom_button()
        self._focus_path = str(path)
        self._request_crumbs()                   # cheminement : l'image suit AUSSITOT (pas la colonne cachee)
        pixmap, natural, full = self._viewer_image(path, fallback)
        self._set_focus_origin_badge(path)     # la source se lit dans « Paramètres de l'image »
        overlay = self._focus_overlay
        if overlay is None and self._project_columns_hidden and not pixmap.isNull():
            # Colonnes masquees sans objet au centre (fichier sans apercu au depart) : on le cree.
            size = natural if natural is not None else QSizeF(pixmap.width(), pixmap.height())
            target = fit_rect(size, self._viewer_area())
            overlay = self._focus_overlay = FocusOverlay(
                self.scroll.viewport(), pixmap, target, target, 1.0, 1.0, 1,
                on_double_click=self._toggle_project_columns_hidden, on_wheel=self._on_focus_wheel)
            self._attach_viewer(overlay)
            overlay.show()
            overlay.raise_()
            self._raise_viewer_chrome()
            delta = 0
        # Reglages > Visionneuse > « Effet slide entre les images » coupe : l'image change sur place
        # (pas de ruban) ; la pellicule, elle, defile comme avant ; `delta` sert aussi au prechargement.
        slide = delta if self._viewer_slide_enabled() else 0
        if overlay is not None and not pixmap.isNull():
            overlay.show_image(pixmap, natural, full, slide)
        # Le retour vers l'inspecteur doit viser la place de la NOUVELLE image : capture refaite.
        self._columns_snapshot = None
        self._prefetch_viewer(index, -1 if delta < 0 else 1)
        strip = self._filmstrip
        if strip is not None:
            strip.set_current(index)
            if not delta:
                strip.set_position(index)
            elif not slide:                          # pas de ruban a suivre : la pellicule glisse seule
                strip.glide_to(index)
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.set_path(path)
            if strip is not None:
                strip.reveal()                   # pas de pellicule (reglage coupe) : rien a montrer
        self._viewer_sync.start()

    def _viewer_image(self, path: Path, fallback: QPixmap | None = None) -> tuple:
        """(pixmap, taille reelle ou None, image pleine definition ou None) pour `path`."""
        hit = self._focus_images.get(path)
        if hit is not None:
            return hit[0], hit[2], hit[1]
        natural = self._focus_images.natural_size(path)
        self._focus_images.request(path, urgent=True)
        return self._focus_pixmap(path, fallback), natural, None

    def _viewer_neighbour(self, k: int):
        """Voisine k du ruban, pour le dessin du glissement : seulement ce qui est deja en memoire."""
        i = self._viewer_index + k
        if not 0 <= i < len(self._viewer_paths):
            return None
        path = self._viewer_paths[i]
        hit = self._focus_images.get(path)
        if hit is not None:
            return hit[0], hit[2]
        pixmap = self._viewer_previews.get(str(path))
        if pixmap is None:
            cached = _previews._file_image_cache.get(str(path))
            pixmap = cached[1] if cached is not None else None
        if pixmap is None or pixmap.isNull():
            # Defilement rapide : la petite vignette des colonnes en attendant, plutot que du vide.
            pixmap = _previews.file_image_pixmap(path, asynchronous=True)
        if pixmap is None or pixmap.isNull():
            return None
        return pixmap, self._focus_images.known_natural(path)

    def _prefetch_viewer(self, index: int, direction: int):
        """Prepare les voisines (d'abord dans le sens de la marche) : decodage en fond des images,
        apercus des autres fichiers lus apres le glissement (lecture disque)."""
        paths = self._viewer_paths
        later = []
        self._focus_images.retain(paths[max(0, index - 3):index + 4])
        for k in (direction, -direction, 2 * direction, 3 * direction, -2 * direction):
            i = index + k
            if not 0 <= i < len(paths):
                continue
            path = paths[i]
            if self._focus_images.supports(path):
                if path.suffix.casefold() in RAW_EXTENSIONS and abs(k) > 1:
                    continue  # grands JPEG embarqués : seulement les deux voisines immédiates
                self._focus_images.natural_size(path)
                self._focus_images.request(path)
            elif str(path) not in self._viewer_previews:
                later.append(path)
        if later:
            QTimer.singleShot(FocusOverlay.SLIDE_MS + 40, lambda: self._prefetch_previews(later))

    def _prefetch_previews(self, paths: list):
        if not self._project_columns_hidden:
            return
        for path in paths:
            key = str(path)
            if key in self._viewer_previews:
                continue
            mtime = _previews.cached_mtime(path)
            if mtime is None:
                continue
            cached = _previews._file_image_cache.get(key)
            pixmap = cached[1] if cached is not None and cached[0] == mtime else None
            if pixmap is None:
                pixmap, _stale = _previews._read_preview_pixmap(path, mtime)
            if pixmap is None or pixmap.isNull():
                _previews.file_image_pixmap(path, asynchronous=True)
                continue
            if len(self._viewer_previews) > 48:
                self._viewer_previews.clear()
            self._viewer_previews[key] = pixmap

    def _on_viewer_moved(self, offset: float):
        """Chaque pas du ruban : la pellicule glisse avec lui (sauf quand elle glisse seule, effet slide
        coupe : un pas sans decalage, zoom ou rebond, l'arreterait net)."""
        strip = self._filmstrip
        if strip is not None and self._viewer_index >= 0 and not (offset == 0 and strip.gliding()):
            strip.set_position(self._viewer_index - offset)

    def _on_focus_image_ready(self, key: str):
        """Image pleine definition prete : celle du centre se precise (sans bouger), une voisine
        en plein glissement apparait."""
        overlay = self._focus_overlay
        if overlay is None or not self._project_columns_hidden:
            return
        if 0 <= self._viewer_index < len(self._viewer_paths) and key == str(self._viewer_paths[self._viewer_index]):
            hit = self._focus_images.get(Path(key))
            if hit is not None:
                self._set_focus_origin_badge(Path(key), decoded=True)
                overlay.upgrade(hit[0], hit[2], hit[1])
        elif overlay.animating():
            overlay.update()

    def _on_filmstrip_chosen(self, index: int):
        if index != self._viewer_index:
            self._viewer_go(index, index - self._viewer_index)

    def _viewer_jump(self, index: int):
        index = max(0, min(len(self._viewer_paths) - 1, index))
        if 0 <= self._viewer_index != index:
            self._viewer_go(index, index - self._viewer_index)

    def _sync_viewer_selection(self):
        """Au repos : la colonne (masquee) et l'inspecteur passent sur l'image montree. Repousse
        tant que l'image bouge (pas d'a-coup en plein glissement)."""
        if not self._viewer_active():
            return
        overlay = self._focus_overlay
        if overlay is not None and overlay.animating():
            self._viewer_sync.start()
            return
        path = self._viewer_paths[self._viewer_index]
        self._select_viewer_file(path)
        self._request_current_lightroom_preview()
        self._return_grab.start()                # colonnes changees : leur capture de retour, au repos

    def _request_current_lightroom_preview(self):
        if not self._viewer_active():
            return
        import lightroom_bridge
        fit = self._viewer_fit_size()
        lightroom_bridge.ensure_large_preview(
            self._viewer_paths[self._viewer_index], fit.width(), fit.height())

    def _settle_columns_layout(self):
        """Colonnes re-affichees le temps d'une capture : leurs mises en page en attente (inspecteur mis a
        jour pendant le masquage : un widget cache ne se remet pas en page) sont faites TOUT DE SUITE, sans
        rien peindre. Sinon capture et place de retour de l'image etaient relevees sur l'ancienne mise en
        page : l'image arrivait 50 a 80 px a cote de l'apercu de l'inspecteur et sautait a la fin."""
        self.columns_layout.activate()
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        self.columns_layout.activate()

    def _pregrab_columns(self):
        """Visionneuse ouverte, au repos : la capture des colonnes pour leur retour est faite D'AVANCE
        (colonnes affichees, capturees, re-masquees sans retour a la boucle d'evenements : rien ne
        s'affiche), avec la place de retour de l'image dans l'inspecteur. Le retour la trouve a jour et
        demarre aussitot ; avant, il la refaisait au clic (~50 ms) apres la synchro de la colonne (~100 ms) :
        la saccade signalee au retour aux colonnes."""
        if not self._project_columns_hidden:
            return
        overlay, gallery = self._focus_overlay, self._focus_gallery
        if (_anim_running(self._columns_fade) or self._viewer_sync.isActive()
                or (overlay is not None and (overlay.running or overlay.animating()))
                or (gallery is not None and gallery._busy())):
            self._return_grab.start()            # une animation tourne : plus tard
            return
        if gallery is not None and not self._gallery_deselected:
            # Planche ouverte : sa sortie vers les colonnes laisse la colonne SANS fichier selectionne. Cette
            # deselection est faite d'avance (colonnes masquees : rien ne se voit) pour que la capture du
            # retour la montre deja ; la sortie demarre alors aussitot (avant : ~90 ms au clic). Revenir a
            # une image la reselectionne (_close_focus_gallery -> synchro).
            self._gallery_deselected = True
            self._deselect_viewer_file()
        cached = self._columns_snapshot
        if (cached is not None and len(cached) > 5 and cached[2] == self.scroll.viewport().size()
                and cached[3] == self._columns_epoch and cached[5] == self._project_columns_collapsed):
            return                               # deja a jour
        try:
            self._apply_columns_hidden(False)
            self._settle_columns_layout()
            snapshot = self._grab_columns()
            source = self._focus_source()        # place de retour (inspecteur affiche le temps de la capture)
            self._columns_snapshot = (*snapshot, time.monotonic(), self._project_columns_collapsed, (source,))
        finally:
            self._apply_columns_hidden(True)

    def _flush_viewer_sync(self):
        """Tout de suite (retour des colonnes) : la colonne et l'inspecteur rattrapent l'image."""
        pending = self._viewer_sync.isActive()
        self._viewer_sync.stop()
        if pending and 0 <= self._viewer_index < len(self._viewer_paths):
            self._select_viewer_file(self._viewer_paths[self._viewer_index])

    def _select_viewer_file(self, path: Path):
        source = self._pur_sources.get(str(path))
        if source is not None:
            # Image d'une planche PureRef : la planche dans sa colonne, l'inspecteur sur cette image.
            self._select_viewer_file(source[0])
            # L'inspecteur va sur CETTE image de la planche, meme si ses images ne sont pas encore listees
            # (extraction en fond : avant, il finissait sur la premiere — signale).
            self.detail.select_pur_image(str(source[0]), source[1])
            return
        key = str(path)
        column, current = self._focus_file_column()
        if current is not None and str(current) == key:
            return
        candidates = [column] if column is not None else []
        candidates += [c for c in [*self.columns, *self.group_columns] if c is not column]
        for candidate in candidates:
            view = candidate.list
            for i in range(view.count()):
                item = view.item(i)
                if item.data(ROLE_PATH) == key:
                    if view.currentItem() is not item:
                        view.setCurrentItem(item)          # navigation : l'inspecteur suit
                    view.scrollToItem(item)
                    return
        # Fichier d'un autre dossier (planche filtree sur une portee large) : les colonnes vont jusqu'a lui.
        self._navigate_to(path)

    def _ensure_viewer_keys(self):
        """Raccourcis de la visionneuse (actifs seulement image seule au centre, voir
        _sync_viewer_chrome) : fleches / Page / Espace / Retour arriere = suivante / precedente,
        Debut / Fin, G = planche, + / - / 0 / 1 = zoom (- sur l'image ajustee : planche), Echap =
        dezoomer puis revenir aux colonnes."""
        def add(keys, slot):
            for key in keys:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WindowShortcut)
                shortcut.setEnabled(False)
                shortcut.activated.connect(slot)
                self._viewer_keys.append(shortcut)
        add(("Right", "Down", "PgDown", "Space"), lambda: self._step_focus_image(1))
        add(("Left", "Up", "PgUp", "Backspace"), lambda: self._step_focus_image(-1))
        add(("Home",), lambda: self._viewer_jump(0))
        add(("End",), lambda: self._viewer_jump(len(self._viewer_paths) - 1))
        add(("G",), self._toggle_focus_gallery)
        add(("+", "="), lambda: self._viewer_zoom(1.25))
        add(("-",), lambda: self._viewer_zoom(0.8))
        add(("0",), lambda: self._focus_overlay is not None and self._focus_overlay.zoom_reset())
        add(("1",), lambda: self._focus_overlay is not None and self._focus_overlay.zoom_toggle_actual())
        add(("Esc",), self._viewer_escape)
        # Touches reglables (Reglages > Visionneuse, colonne Raccourci) : chacune bascule sa ligne.
        self._viewer_toggle_keys = {}
        for setting in self._VIEWER_TOGGLES:
            shortcut = QShortcut(self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setEnabled(False)
            shortcut.activated.connect(lambda setting=setting: self._toggle_viewer_setting(setting))
            self._viewer_keys.append(shortcut)
            self._viewer_toggle_keys[setting] = shortcut
        self._sync_viewer_toggle_keys()

    # Lignes de Reglages > Visionneuse qui ont une touche : reglage -> (cle de la touche, defaut).
    _VIEWER_TOGGLES = {"viewer_filmstrip_enabled": ("viewer_filmstrip_shortcut", True),
                       "viewer_info_enabled": ("viewer_info_shortcut", False)}

    def _on_element_style_saved(self, key: str, value):
        """Override d'un element enregistre (clic droit > Override settings) : les reglages appliques
        le connaissent ; une surcharge de colonne restyle la fenetre (regroupe, 60 ms)."""
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        self._interface_move_mode._on_text_style_saved(key, value)
        if key == "element_style_overrides":
            return
        timer = getattr(self, "_override_apply_timer", None)
        if timer is None:
            timer = self._override_apply_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(lambda: self._apply_settings(dict(ui_state.APPLIED_SETTINGS or {})))
        timer.start()

    def _sync_viewer_toggle_keys(self):
        applied = ui_state.APPLIED_SETTINGS or {}
        for setting, shortcut in (getattr(self, "_viewer_toggle_keys", None) or {}).items():
            shortcut.setKey(QKeySequence(str(applied.get(self._VIEWER_TOGGLES[setting][0]) or "")))

    def _toggle_viewer_setting(self, setting: str):
        """Touche d'une ligne de Reglages > Visionneuse : bascule le reglage, l'enregistre aussitot ;
        la fenetre de reglages ouverte suit (sa ligne est mise a jour)."""
        default = self._VIEWER_TOGGLES[setting][1]
        enabled = not bool((ui_state.APPLIED_SETTINGS or {}).get(setting, default))
        self._write_setting_now(setting, enabled)
        self._apply_viewer_settings()

    def _write_setting_now(self, setting: str, enabled: bool):
        """Reglage oui / non change hors de la fenetre de reglages (touche, bouton du board) : enregistre
        aussitot (fichier + preset par defaut actif) ; la fenetre de reglages ouverte suit (sa ligne)."""
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            for store in (dialog.stores.values() if dialog is not None and dialog.isVisible() else ()):
                for spec, widget in store.get("specs", ()):
                    if getattr(spec, "key", None) == setting:
                        if isinstance(enabled, bool) and hasattr(widget, "setChecked"):
                            widget.setChecked(enabled)
                        elif isinstance(enabled, (int, float)) and hasattr(widget, "setValue"):
                            widget.setValue(int(enabled))   # curseur (module CAD : fenetre des accrochages)
        except (RuntimeError, TypeError):
            pass
        settings = load_settings()
        settings[setting] = enabled
        save_settings(settings)
        import browser_core                       # preset par defaut actif : sinon il rejoue l'ancienne valeur
        browser_core._sync_default_preset_override(settings, lambda preset: preset.__setitem__(setting, enabled))
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[setting] = enabled

    def _viewer_zoom(self, factor: float):
        overlay = self._focus_overlay
        if overlay is None:
            return
        if factor < 1.0 and not overlay.zoomed():
            self._open_focus_gallery()               # dezoomer l'image ajustee = voir tout le dossier
            return
        overlay.zoom_by(factor)

    def _viewer_escape(self):
        overlay = self._focus_overlay
        if overlay is not None and overlay.zoomed():
            overlay.zoom_reset()
        else:
            self._set_columns_hidden(False)

    def _viewer_ctrl_wheel(self, event):
        """Ctrl+molette : zoom autour du curseur ; vers l'arriere sur l'image ajustee, ouvre la
        planche (zoom « semantique », le pendant de Ctrl+molette avant dans la planche)."""
        overlay = self._focus_overlay
        delta = event.angleDelta().y()
        if overlay is None or not delta:
            return
        if delta < 0 and not overlay.zoomed():
            self._focus_pinch += delta
            if self._focus_pinch <= -120:
                self._focus_pinch = 0
                self._open_focus_gallery()
            return
        self._focus_pinch = 0
        anchor = QPointF(overlay.mapFromGlobal(event.globalPosition().toPoint()))
        overlay.zoom_by(1.2 ** (delta / 120), anchor)

    def _poll_viewer_cursor(self):
        """La pellicule s'efface quand la souris ne bouge plus et revient au moindre mouvement
        au-dessus de la fenetre (releve leger, pas de suivi de souris sur toute la zone)."""
        pos = QCursor.pos()
        if pos == self._viewer_cursor:
            return
        moved = self._viewer_cursor is not None
        self._viewer_cursor = pos
        if moved and self._filmstrip is not None and self.rect().contains(self.mapFromGlobal(pos)):
            self._filmstrip.reveal()
