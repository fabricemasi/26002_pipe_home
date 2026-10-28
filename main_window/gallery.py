"""Planche des images du dossier (état focus) et ses filtres.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from app_style import C, resolve_color_ref, PREVIEW_STACK_TITLE, role_color, scaled, column_style_for
from config import PREVIEWABLE_EXTENSIONS, RENDERABLE_3D_EXTENSIONS, PUR_PREVIEW_EXTENSIONS
from settings_store import DEFAULT_SETTINGS, load_settings
from settings_widgets import Menu
from browser_core import ROLE_ISDIR, ROLE_PATH
from preview_column import IconButton, style_focus_button
from fm_visionneuse.focus import FilterChips, FocusGallery, filter_window, placeholder_pixmap
from fm_visionneuse import file_filters, focus as _focus
import ui_state
import previews as _previews


class GalleryMixin:
    """Méthodes de PipelineBrowser : planche des images du dossier (état focus) et ses filtres."""

    # -- Planche des images du dossier (etat focus) --

    def _toggle_focus_gallery(self):
        """Bouton voisin de « masquer » (etat focus seulement) : image en cours <-> planche de
        toutes les images du dossier de l'image en cours."""
        if self._focus_gallery is not None:
            self._close_focus_gallery()
        else:
            self._open_focus_gallery()

    def _focus_file_column(self):
        """(colonne, chemin) du fichier affiche par l'inspecteur ; colonne None si introuvable. Double-clic
        sur une ligne en cours : CE fichier et sa colonne (`_viewer_entry_path`), quoi que montre
        l'inspecteur."""
        entry = getattr(self, "_viewer_entry_path", None)
        if entry is not None:
            return entry
        current = getattr(self.detail, "_current_path", None)
        if not current:
            return None, None
        path = Path(current)
        for column in [*self.columns, *self.group_columns]:
            if column.current_path() == path:
                return column, path
        return None, path

    def _gallery_paths(self, rescan: bool = True) -> tuple:
        """Fichiers de la planche et fichier en cours : ceux de la visionneuse s'ils sont connus
        (l'image montree peut avoir devance la colonne, voir _viewer_sync), sinon relus ; filtre applique
        (voir _filtered_gallery)."""
        if 0 <= self._viewer_index < len(self._viewer_paths):
            paths = list(self._viewer_base or self._viewer_paths)
            current = str(self._viewer_paths[self._viewer_index])
        else:
            paths, current = self._scan_viewer_paths()
        return self._filtered_gallery(paths, current, rescan)

    # -- Filtres de la planche (demande de l'utilisateur) --

    def _filtered_gallery(self, paths: list, current: str | None, rescan: bool = True) -> tuple:
        """Filtre de la planche applique a `paths` (colonne en cours) ou, portee plus large, aux fichiers
        du dossier de la portee : parcourus EN FOND (`rescan` : relus a l'ouverture de la planche), la
        colonne filtree en attendant le premier parcours. Fichier en cours : None s'il est ecarte."""
        spec = file_filters.normalized(self._viewer_filter)
        if not self._viewer_filter_active():
            return paths, current
        folder = self._filter_scope_folder(spec["scope"])
        entries = paths
        if folder is not None:
            known = self._scope_files.get(str(folder))
            if rescan or known is None:
                self._start_filter_scan(folder)
            if known is not None:
                entries = known
        found = file_filters.filter_entries(entries, spec, self._filter_root())
        return found, (current if current is not None and any(str(p) == current for p in found) else None)

    def _filter_root(self) -> Path:
        return Path(self.root_field.text())

    def _filter_provenances(self) -> list:
        """Provenances proposees : les fixes, puis les sous-dossiers de in / over / out des fichiers connus
        (colonne en cours et portees deja parcourues)."""
        entries = list(self._viewer_base or self._viewer_paths)
        for known in self._scope_files.values():
            entries.extend(known)
        return file_filters.provenance_choices(entries, self._filter_root())

    def _filter_scopes(self) -> list:
        """(cle, libelle) des portees : la colonne en cours, chaque dossier de la chaine du set (Type,
        Projet, Sous-projet…), toute la racine."""
        scopes = [(file_filters.SCOPE_LOCAL, "Local (colonne en cours)")]
        for index in range(min(len(self.columns), self._chain_expected_total())):
            column = self.columns[index]
            chosen = column.current_path()
            if chosen is None or not chosen.is_dir():
                break
            title = column.title_label.text() or column.column_title
            scopes.append((f"level:{index}", f"{title.capitalize()} : {chosen.name}"))
        scopes.append((file_filters.SCOPE_ROOT, "Toute la racine"))
        self._filter_scopes_cache = scopes
        return scopes

    def _filter_scope_folder(self, scope: str) -> Path | None:
        """Dossier parcouru pour une portee large ; None = la colonne en cours."""
        if scope == file_filters.SCOPE_ROOT:
            return Path(self.root_field.text())
        if scope.startswith("level:"):
            try:
                column = self.columns[int(scope.split(":", 1)[1])]
            except (ValueError, IndexError):
                return None
            chosen = column.current_path()
            return chosen if chosen is not None and chosen.is_dir() else None
        return None

    def _filter_scope_label(self, scope: str) -> str:
        labels = dict(self._filter_scopes_cache)
        if scope not in labels:
            labels = dict(self._filter_scopes())
        return labels.get(scope, "")

    def _start_filter_scan(self, folder: Path):
        task = self._filter_task
        if task is not None:
            if task.folder == folder and not task.cancel:
                return                                   # deja en cours
            task.cancel = True
        task = self._filter_task = file_filters.FilterScanTask(folder)
        task.signals.finished.connect(self._on_filter_scan_done)
        file_filters.pool().start(task)

    def _on_filter_scan_done(self, folder: str, entries):
        task = self._filter_task
        if task is not None and str(task.folder) == folder:
            self._filter_task = None
        self._scope_files[folder] = entries
        pending = self._pending_folder_view
        if pending is not None and str(pending[0]) == folder:
            self._pending_folder_view = None
            self._view_folder_in_viewer(*pending)             # double-clic sur un dossier : parcours fini
        elif self._project_columns_hidden and self._recursive_on() and self._viewer_folder is not None \
                and str(self._viewer_folder) == folder:
            self._apply_viewer_base()                         # mode récursif : liste complète arrivée
        # Images des planches PureRef parcourues : rangees comme celles de la visionneuse (nom affiche
        # « planche.pur · n/N », planche retrouvee au retour aux colonnes, attributs de la planche).
        boards: dict = {}
        for entry in entries:
            if len(entry) > 3:
                boards.setdefault(entry[3], []).append(entry[0])
        for (pur, mtime), images in boards.items():
            self._remember_pur(pur, mtime, images)
        self._refresh_focus_gallery(rescan=False)
        self._sync_filter_button()

    def _sync_filter_button(self):
        """Planche ouverte : bouton filtre a la suite des autres boutons (rouge quand un filtre agit), et les
        elements du filtre ecrits a cote, en « style code » (FilterChips) ; puis les boutons PureRef."""
        spec = file_filters.normalized(self._viewer_filter)
        configured = file_filters.is_active(spec)
        active = configured and self._viewer_filter_enabled
        # Le filtre reste une action de la visionneuse, même lorsqu'on est
        # revenu à l'image seule : l'icône doit alors rester dans la rangée
        # pour signaler l'état actif et permettre de le modifier.
        viewer_mode = self._focus_gallery is not None or self._viewer_active()
        want = viewer_mode and (self._focus_gallery is not None or configured)
        button, chips = self._filter_btn, self._filter_chips
        if not want:
            for widget in (button, chips):
                if widget is not None:
                    widget.hide()
            self._sync_pur_buttons()
            return
        viewport = self.scroll.viewport()
        if button is None:
            button = self._filter_btn = IconButton("filter", role_color("buttons", "#c4cacf"), C["text"],
                                                   parent=viewport)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._on_filter_button_clicked)
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(self._filter_button_menu)
            chips = self._filter_chips = FilterChips(viewport)
        style_focus_button(button)
        settings = ui_state.APPLIED_SETTINGS or {}
        button.set_alert(resolve_color_ref(settings.get("viewer_filter_active_color") or "#c62828")
                         if active else None)
        button.setToolTip(("Filtres actifs — cliquer pour désactiver (clic droit : retirer)" if active
                           else "Filtres en mémoire, désactivés — cliquer pour réactiver"
                           if configured else "Filtres de la planche"))
        button.show()
        button.raise_()
        if active and self._focus_gallery is not None:
            items = file_filters.describe(spec, [name for name, _c in _focus.filter_colors()],
                                          self._filter_scope_label(spec["scope"]))
            if self._filter_task is not None:
                items.append("recherche…")
            else:
                count = len(self._gallery_list)
                items.append(f"{count} fichier{'s' if count > 1 else ''}")
            chips.restyle()
            chips.set_items(items)
            chips.show()
            chips.raise_()
        else:
            chips.hide()
        self._sync_pur_buttons()

    def _filter_button_menu(self, pos):
        if not file_filters.is_active(self._viewer_filter):
            return
        menu = Menu(self)
        menu.addAction("Retirer le filtre", self._clear_viewer_filter)
        menu.exec(self._filter_btn.mapToGlobal(pos))

    def _clear_viewer_filter(self):
        if self._filter_window is not None:
            self._filter_window.close()          # rouverte, elle repart des valeurs vides
        self._set_viewer_filter(dict(file_filters.DEFAULT_FILTER))

    def _on_filter_button_clicked(self):
        """Sans critères, ouvre leur réglage ; avec des critères, active/désactive leur application."""
        if file_filters.is_active(self._viewer_filter):
            self._viewer_filter_enabled = not self._viewer_filter_enabled
            self._refresh_focus_gallery(rescan=True)
            self._sync_filter_button()
            return
        self._open_filter_window()

    def _open_filter_window(self):
        window = self._filter_window
        if window is not None:
            window.raise_()
            window.activateWindow()
            return
        window = self._filter_window = filter_window(
            self._viewer_filter, self._filter_scopes(), settings=ui_state.APPLIED_SETTINGS, parent=self,
            provenances=self._filter_provenances())
        window.styleChanged.connect(self._on_filter_window_changed)
        window.destroyed.connect(lambda *_a: setattr(self, "_filter_window", None))
        window.on_row_style = self._open_filter_row_style      # clic droit > « Style des filtres actives… »
        window.show()

    def _open_filter_row_style(self):
        """Style des lignes ou un filtre est applique (fond, bordures) : fenetre « a la volee », valeurs
        appliquees en direct et enregistrees comme les styles des diapositives (_on_filmstrip_style)."""
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        previous = getattr(self, "_filter_row_window", None)
        if previous is not None:
            try:
                previous.raise_()
                previous.activateWindow()
                return
            except RuntimeError:
                pass
        settings = dict(DEFAULT_SETTINGS)
        settings.update(ui_state.APPLIED_SETTINGS or load_settings())
        window = self._filter_row_window = QuickStyleWindow(
            "Filtres actifs", v2.FILTER_ROW_SPECS, settings, title="Style des filtres activés",
            settings=settings, parent=self)
        window.styleChanged.connect(self._on_filter_row_style)
        window.destroyed.connect(lambda *_a: setattr(self, "_filter_row_window", None))
        window.show()

    def _on_filter_row_style(self, values: dict):
        self._on_filmstrip_style(values, light=True)          # applique + enregistre (et preset actif)
        # Enregistre EN TEMPS REEL (demande de l'utilisateur) : tout de suite, sauf pendant un geste
        # (curseur tire) ou l'ecriture attend le relachement (minuteur de _on_filmstrip_style).
        if QApplication.mouseButtons() == Qt.NoButton:
            self._flush_filmstrip_style()
        window = self._filter_window
        if window is not None:
            try:
                window.refresh_marks()
            except RuntimeError:
                pass

    def _on_filter_window_changed(self, values: dict):
        """Changement dans la fenetre des filtres : applique apres une courte pause (frappe au clavier)."""
        self._pending_filter = values
        if self._filter_timer is None:
            self._filter_timer = QTimer(self)
            self._filter_timer.setSingleShot(True)
            self._filter_timer.setInterval(250)
            self._filter_timer.timeout.connect(lambda: self._set_viewer_filter(self._pending_filter))
        self._filter_timer.start()

    def _set_viewer_filter(self, spec: dict | None):
        self._viewer_filter = file_filters.normalized(spec)
        self._viewer_filter_enabled = file_filters.is_active(self._viewer_filter)
        self._refresh_focus_gallery(rescan=True)
        self._sync_filter_button()

    def _viewer_filter_active(self) -> bool:
        return self._viewer_filter_enabled and file_filters.is_active(self._viewer_filter)

    def _refresh_focus_gallery(self, rescan: bool = True):
        """Filtre change (ou parcours termine) : la planche est refaite sur place avec les fichiers retenus,
        en fondu (sans vague)."""
        old = self._focus_gallery
        if old is None:
            return
        paths, current = self._gallery_paths(rescan=rescan)
        if [str(p) for p in paths] == [str(p) for p in self._gallery_list]:
            return
        gallery = self._make_focus_gallery(paths, current)
        self._focus_gallery = gallery
        gallery.show()
        gallery.reveal_current(None)
        gallery.warm_cells(False)
        gallery.start_ripple(wave=False)
        gallery.raise_()
        old.blockSignals(True)
        old.hide()
        old.deleteLater()
        self._raise_gallery_buttons()

    def _scan_viewer_paths(self) -> tuple:
        """Fichiers a apercu (images, 3D, PSD, plans, videos...) du dossier du fichier en cours,
        dans l'ordre de sa colonne (ordre choisi a la main compris) ; a defaut de colonne, ceux du
        dossier, tries par nom. Aucune lecture disque par fichier (les lignes savent si elles
        sont des dossiers)."""
        column, current = self._focus_file_column()
        if current is None:
            return [], None
        recursive = self._recursive_known() if self._project_columns_hidden or self._viewer_entry_folder else None
        if recursive and str(current) in {str(p) for p in recursive}:
            return list(recursive), str(current)          # mode récursif : tout le dossier et dessous
        if column is not None:
            items = [column.list.item(i) for i in range(column.list.count())]
            paths = [Path(item.data(ROLE_PATH)) for item in items if not item.data(ROLE_ISDIR)]
        else:
            try:
                paths = sorted((p for p in current.parent.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
            except OSError:
                paths = []
        # Planches PureRef comprises : leurs images y entrent (voir _expand_viewer_pureref).
        images = [p for p in paths if p.suffix.lower() in PREVIEWABLE_EXTENSIONS | PUR_PREVIEW_EXTENSIONS]
        return images, str(current)

    def _gallery_rect(self) -> QRect:
        """Zone des colonnes, sous les boutons (qui restent cliquables)."""
        area = self._focus_area()
        top = max((r.bottom() for r in self._button_rects()), default=0) + 10
        return QRect(area.x() + 16, top, max(1, area.width() - 32), max(1, area.bottom() - top))

    def _sync_floating_gallery_btn(self):
        """Focus SANS colonne Focus (donc sans bouton « masquer », retour par double-clic) : le
        bouton de la planche flotte seul en haut a gauche de la zone des colonnes, meme style.
        Avec une colonne Focus, c'est elle qui le porte (PreviewColumn.gallery_btn)."""
        self._sync_viewer_chrome()
        # Bouton de passage image / planche SUPPRIME (demande de l'utilisateur) : la touche G, le clic sur l'image
        # et Ctrl+molette restent.
        want = False
        button = self._floating_gallery_btn
        if not want:
            if button is not None:
                button.hide()
            return
        if button is None:
            button = self._floating_gallery_btn = IconButton(
                "gallery", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._toggle_focus_gallery)
        style_focus_button(button)
        style = column_style_for(PREVIEW_STACK_TITLE)
        button.move(scaled(int(style.get("preview_toggle_x", 8)), 0) + scaled(8, 0), scaled(10, 0))
        self._set_gallery_buttons_state(self._focus_gallery is not None)
        button.show()
        button.raise_()
        self._layout_viewer_buttons()

    def _set_gallery_buttons_state(self, shown: bool):
        if self.image_preview_columns:
            self.image_preview_columns[0].set_gallery_state(shown)
        button = self._floating_gallery_btn
        if button is not None:
            button.set_kind("single_image" if shown else "gallery")
            button.setToolTip("Revenir a l'image en cours" if shown else "Toutes les images du dossier")
        self._sync_filter_button()

    def _open_focus_gallery(self):
        if not self._project_columns_hidden:
            return
        paths, current = self._gallery_paths()
        if getattr(self, "_gallery_no_focus", False):
            current = None                 # ouverte depuis un dossier : aucune image en focus
        if not paths and not self._viewer_filter_active():
            return
        viewport = self.scroll.viewport()
        gallery = self._make_focus_gallery(paths, current)
        self._focus_gallery = gallery
        self._sync_viewer_chrome()                 # pellicule et raccourcis de l'image : retires
        gallery.show()
        memory = getattr(self, "_gallery_memory", None)
        gallery.reveal_current(memory[1] if memory is not None and memory[0] == gallery.path_keys() else None)
        # Les cases apparaissent en vague depuis l'image ; vague coupee (Reglages > Visionneuse) :
        # toutes ensemble, en fondu. Leurs images sont faites avant qu'elles ne se montrent.
        wave = bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_gallery_ripple_enabled", True))
        gallery.warm_cells(wave)
        gallery.start_ripple(wave=wave)
        self._return_grab.start()          # au repos : sortie vers les colonnes preparee d'avance
        gallery.raise_()
        gallery.setFocus()
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.finish_now()
            # L'image en focus se pose dans sa vignette (et la case reste vide pendant le vol) ;
            # sa place dans l'inspecteur est gardee pour le retour des colonnes.
            tile = gallery.image_rect_in(viewport, current, overlay._base)
            if tile is None:
                overlay.hide()
            else:
                self._focus_home = overlay._source
                gallery.set_hidden_path(current)
                overlay._source = QRectF(tile)
                overlay._duration = self._GALLERY_FLIGHT_MS
                overlay.retarget(0.0, self._on_focus_landed_in_gallery)
                overlay.raise_()
        self._set_gallery_buttons_state(True)
        self._raise_gallery_buttons()

    def _make_focus_gallery(self, paths: list, current: str | None):
        gallery = FocusGallery(self.scroll.viewport(), paths, current, on_split=self._on_gallery_split,
                               on_menu=self._filmstrip_menu)
        gallery.setGeometry(self._gallery_rect())
        gallery.chosen.connect(self._on_gallery_chosen)
        gallery.zoomed_into.connect(self._on_gallery_chosen)
        gallery.closed.connect(self._close_focus_gallery)
        self._gallery_list = [Path(p) for p in paths]
        return gallery

    def _raise_gallery_buttons(self):
        for button in (self._floating_gallery_btn, self._filter_btn, self._filter_chips, *self._pur_buttons):
            if button is not None and button.isVisible():
                button.raise_()

    _GALLERY_FLIGHT_MS = 380

    def _on_focus_landed_in_gallery(self):
        """L'image est dans sa case : la planche la dessine, l'objet en focus se cache."""
        if self._focus_overlay is not None:
            self._focus_overlay.hide()
        if self._focus_gallery is not None:
            self._focus_gallery.set_hidden_path(None)

    def _close_focus_gallery(self, animate: bool = True, path: str | None = None):
        """Retour a l'image : elle quitte sa vignette (`path`, par defaut le fichier de
        l'inspecteur) pour le centre pendant que la planche s'estompe. `animate=False` : tout de
        suite (les colonnes reviennent : l'objet doit etre au centre, avec sa place d'origine)."""
        gallery = self._focus_gallery
        if gallery is None:
            overlay = self._focus_overlay
            if not animate and overlay is not None and self._focus_home is not None:
                # Retour de vignette encore en vol : l'objet est pose au centre avec sa vraie place.
                overlay.jump(1.0)
                overlay._source = self._focus_home
                self._focus_home = None
            return
        self._focus_gallery = None
        self._request_crumbs()                   # l'image regardee revient au bout du cheminement
        if self._gallery_deselected:
            # Retour a l'image depuis la planche : la colonne et l'inspecteur la reprennent (deselectionnes
            # d'avance pour la sortie, _pregrab_columns).
            self._gallery_deselected = False
            self._viewer_sync.start()
        # Position de la planche (premiere ligne visible), retrouvee a sa prochaine ouverture sur le
        # meme dossier (_open_focus_gallery) : jamais recentree sur l'image.
        self._gallery_memory = (gallery.path_keys(), gallery.first_visible_row())
        self._set_gallery_buttons_state(False)
        self._sync_viewer_chrome()
        self._park_keyboard_focus()
        gallery.blockSignals(True)
        gallery.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay = self._focus_overlay
        viewport = self.scroll.viewport()
        if path is None:
            path = self._focus_path or getattr(self.detail, "_current_path", None)
        tile = gallery.image_rect_in(viewport, path, overlay._base) if (animate and overlay is not None) else None
        home = self._focus_home

        def restore_home():
            if self._focus_overlay is overlay and overlay is not None and home is not None:
                overlay._source = home       # au centre (valeur 1) : rien ne bouge a l'ecran
            if self._focus_home is home:
                self._focus_home = None

        def drop_gallery():
            gallery.hide()
            gallery.deleteLater()

        if overlay is None:
            drop_gallery()
            restore_home()
            return
        if tile is None:
            overlay.jump(1.0)
            restore_home()
            overlay.show()
            overlay.raise_()
            if animate:
                gallery.fade(0.0, self._GALLERY_FLIGHT_MS, drop_gallery)
            else:
                drop_gallery()
            return
        gallery.set_hidden_path(path)
        overlay.jump(0.0)
        overlay._source = QRectF(tile)
        overlay._duration = self._GALLERY_FLIGHT_MS
        overlay.show()
        overlay.raise_()
        overlay.retarget(1.0, restore_home)
        gallery.fade(0.0, self._GALLERY_FLIGHT_MS, drop_gallery)

    def _on_gallery_chosen(self, path: Path):
        """Vignette choisie : elle devient le fichier selectionne (colonne + inspecteur) et
        l'image en focus au centre."""
        gallery = self._focus_gallery
        self._focus_on_file(path, gallery.tile_pixmap(path, None) if gallery is not None else None)
        # La vignette choisie s'envole vers le centre (voir _close_focus_gallery).
        if gallery is not None:
            gallery.current = str(path)          # son cadre d'accent pendant que la planche s'estompe
        self._close_focus_gallery(path=str(path))

    def _focus_on_file(self, path: Path, fallback: QPixmap | None = None):
        """`path` (choisi dans la planche) devient l'image au centre ; la colonne et l'inspecteur
        suivent au repos (voir _viewer_sync)."""
        listed = self._gallery_list if self._focus_gallery is not None else []
        if path in listed and listed != self._viewer_paths:
            # Planche filtree (ou filtre retire) : la visionneuse parcourt les fichiers de la planche.
            self._viewer_paths = list(listed)
            if self._filmstrip is not None:
                self._filmstrip.set_paths(self._viewer_paths, listed.index(path))
        index = next((i for i, p in enumerate(self._viewer_paths) if p == path), -1)
        if index < 0:
            paths, _current = self._scan_viewer_paths()
            index = next((i for i, p in enumerate(paths) if p == path), -1)
            if index < 0:
                return
            self._viewer_paths = paths
            if self._filmstrip is not None:
                self._filmstrip.set_paths(paths, index)
        self._viewer_go(index, 0, fallback)

    def _focus_pixmap(self, path: Path, fallback: QPixmap | None = None) -> QPixmap:
        """Image a montrer au centre pour `path` en attendant mieux, SANS rien decoder ici.
        Les formats image attendent le decodage plein format : ne jamais agrandir une vignette
        au centre. Pour les autres fichiers, utiliser l'apercu en cache ou le fallback fourni."""
        self._focus_path = str(path)
        if self._focus_images.supports(path):
            return placeholder_pixmap(path, "Chargement de l’image…")
        mtime = _previews.cached_mtime(path)
        if mtime is not None:
            cached = _previews._file_image_cache.get(str(path))
            if cached is not None and cached[0] == mtime and not cached[1].isNull():
                return cached[1]
            pixmap, _stale = _previews._read_preview_pixmap(path, mtime)
            if pixmap is not None and not pixmap.isNull():
                return pixmap
            small = _previews.file_image_pixmap(path, asynchronous=True)     # demande l'apercu en fond
            if fallback is None and small is not None and not small.isNull():
                fallback = small
        if fallback is not None and not fallback.isNull():
            return fallback
        if path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
            note = "Aperçu pas encore rendu (clic droit dans la colonne pour le rendre)"
        else:
            note = "Aperçu en cours de chargement…"
        return placeholder_pixmap(path, note)

    def _on_focus_preview_ready(self, path_str: str, mtime: float, image):
        """Apercu du pipeline arrive : vignette de la pellicule, voisine du ruban, ou image au
        centre qui n'avait encore rien de mieux (il remplace la carte / la petite vignette)."""
        from fm_visionneuse import focus
        focus._FILM.pop(path_str, None)
        focus._FILM_FAILED.pop(path_str, None)
        focus._CELLS.pop(path_str, None)
        focus._PROXY_SOURCES.pop(path_str, None)     # le proxy a pu changer de source
        self._focus_images.invalidate(Path(path_str))
        for mark in ("focus", "hover"):
            focus._MARKED.pop((path_str, mark), None)
        for key in [key for key in focus._THUMBS if key[0] == path_str]:
            focus._THUMBS.pop(key, None)
        if not self._project_columns_hidden:
            return
        if self._filmstrip is not None and self._filmstrip.isVisible():
            self._filmstrip.update()
        if self._focus_gallery is not None:
            self._focus_gallery.preview_ready(path_str)
        if image is not None and not image.isNull() and path_str in self._viewer_paths:
            self._focus_images.request(Path(path_str), urgent=path_str == self._focus_path)
            if path_str == self._focus_path and self._focus_images.get(Path(path_str)) is None:
                self._set_focus_origin_badge(Path(path_str), application_preview=True)
        overlay = self._focus_overlay
        if overlay is None or image is None or image.isNull():
            return
        if path_str != self._focus_path:
            if overlay.animating():
                overlay.update()
            return
        path = Path(path_str)
        if self._focus_images.supports(path):
            return  # le chargeur plein format remplacera l'image, jamais la vignette du pipeline
        if self._focus_images.get(path) is not None:
            return                                  # deja en pleine definition
        overlay.upgrade(QPixmap.fromImage(image), self._focus_images.known_natural(path))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and watched is self.scroll.viewport() and self._on_focus_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def _on_focus_wheel(self, event) -> bool:
        """Etat focus (image seule au centre) : la molette passe d'une image a l'autre du dossier,
        vers le bas = suivante. Recue sur l'image elle-meme (FocusOverlay, on_wheel) ou n'importe
        ou dans la zone des colonnes masquees. Crans cumules (pave tactile : petits deltas)."""
        if not self._project_columns_hidden or self._focus_gallery is not None:
            return False
        if event.modifiers() & Qt.ControlModifier:
            self._viewer_ctrl_wheel(event)
            return True
        self._focus_wheel += event.angleDelta().y() or event.angleDelta().x()
        steps = int(self._focus_wheel / 120)
        if steps:
            self._focus_wheel -= steps * 120
            self._step_focus_image(-steps)
        return True

    def _step_focus_image(self, step: int):
        """Fichier `step` places plus loin (negatif : avant) parmi les fichiers a apercu de la
        colonne du fichier en cours (images, mais aussi .ma, .obj, .blend, PSD, plans, videos...),
        dans son ordre ; aux extremites, l'image rebondit (bump) au lieu de changer."""
        count = len(self._viewer_paths)
        if not step or not 0 <= self._viewer_index < count:
            return
        overlay = self._focus_overlay
        if overlay is not None and overlay.running:
            overlay.finish_now()
        target = max(0, min(count - 1, self._viewer_index + step))
        if target == self._viewer_index:
            if overlay is not None:
                overlay.bump(step)
            return
        self._viewer_go(target, target - self._viewer_index)
