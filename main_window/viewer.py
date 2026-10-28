"""Visionneuse : entrée, ruban, planches PureRef, dossier + récursif, ouverture d'un fichier (double-clic).

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from app_style import C, resolve_color_ref, role_color, scaled
from config import PREVIEWABLE_EXTENSIONS, PUR_PREVIEW_EXTENSIONS
from settings_store import save_live_state
from browser_core import ROLE_ISDIR, ROLE_PATH, open_in_file_manager, open_path
from preview_column import PureRefImagesTask, _PUR_EXPORT_POOL, pur_image_files, IconButton, style_focus_button
from fm_visionneuse.focus import FocusFilmstrip, thumbnail as focus_thumbnail
from fm_visionneuse import file_attributes, focus as _focus
import ui_state
import previews as _previews
import shiboken6


class ViewerMixin:
    """Méthodes de PipelineBrowser : visionneuse : entrée, ruban, planches PureRef, dossier + récursif, ouverture d'un fichier (double-clic)."""

    # -- Visionneuse : ruban, pellicule, clavier, zoom --

    _VIEWER_SYNC_MS = 700

    def _enter_viewer(self):
        """Colonnes masquees : la visionneuse prend la main. Liste des fichiers du dossier (ordre
        de la colonne), image en cours a sa place definitive (taille reelle lue dans l'entete) et
        demandee en pleine definition, voisines prechargees, pellicule et clavier."""
        _column, first = self._focus_file_column()
        self._viewer_folder = self._viewer_entry_folder or (first.parent if first is not None else None)
        if self._recursive_on() and self._viewer_folder is not None:
            self._start_filter_scan(self._viewer_folder)         # liste à jour : relue en fond
        paths, current = self._scan_viewer_paths()
        self._viewer_purs = [p for p in paths if p.suffix.lower() in PUR_PREVIEW_EXTENSIONS]
        paths, self._viewer_index = self._expand_viewer_pureref(paths, current)
        self._viewer_paths = self._viewer_base = paths
        self._viewer_previews = {}
        if self._filmstrip is not None and self._viewer_index >= 0:
            self._filmstrip.set_paths(paths, self._viewer_index)
        self._sync_viewer_chrome()                       # pellicule creee : sa bande est reservee
        self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
        if self._viewer_index >= 0:
            path = paths[self._viewer_index]
            self._focus_path = str(path)
            overlay = self._focus_overlay
            if overlay is not None:
                self._attach_viewer(overlay)
                # Place definitive (taille reelle, au-dessus de la pellicule), posee en debut de vol :
                # rien ne saute.
                overlay.set_natural(self._focus_images.natural_size(path) or overlay._natural, self._viewer_area())
                hit = self._focus_images.get(path)
                if hit is not None:
                    overlay.upgrade(hit[0], hit[2], hit[1])
                else:
                    self._focus_images.request(path, urgent=True)
            self._prefetch_viewer(self._viewer_index, 1)

    # -- Planches PureRef : leurs images dans la visionneuse --

    def _expand_viewer_pureref(self, paths: list, current: str | None) -> tuple:
        """(liste, rang du fichier en cours) ou chaque planche .pur est remplacee par ses images
        quand elles existent deja en fichiers ; sinon la planche reste (son apercu) et ses images
        sont extraites en fond (_on_pur_images_ready la remplacera). Planche en cours : l'image que
        l'inspecteur montre."""
        out, index = [], -1
        for path in paths:
            files = self._pur_files(path) if path.suffix.lower() in PUR_PREVIEW_EXTENSIONS else None
            if files:
                if str(path) == current:
                    shown = getattr(self.detail, "_pur_image_index", 0) \
                        if getattr(self.detail, "_pur_image_path", None) == str(path) else 0
                    index = len(out) + max(0, min(len(files) - 1, int(shown or 0)))
                out.extend(files)
                continue
            if str(path) == current:
                index = len(out)
            out.append(path)
        return out, index

    def _pur_files(self, pur: Path) -> list | None:
        mtime = _previews.cached_mtime(pur)
        if mtime is None:
            return None
        known = self._pur_expansions.get(str(pur))
        if known is not None and known[0] == mtime:
            return known[1] or None
        files = pur_image_files(pur, mtime)
        if files is None:
            self._start_pur_images(pur, mtime)
            return None
        self._remember_pur(pur, mtime, files)
        return files or None

    def _remember_pur(self, pur: Path, mtime: float, files: list):
        files = [Path(f) for f in files]
        self._pur_expansions[str(pur)] = (mtime, files)
        for rank, image in enumerate(files):
            self._pur_sources[str(image)] = (pur, rank)
            file_attributes.set_alias(image, pur.parent, f"{pur.name}/{image.name}")   # attributs : ceux de la planche
            _focus.DISPLAY_NAMES[str(image)] = f"{pur.name} · {rank + 1}/{len(files)}"

    def _start_pur_images(self, pur: Path, mtime: float):
        task = self._pur_tasks.get(str(pur))
        if task is not None and task.mtime == mtime:
            return
        task = PureRefImagesTask(pur, mtime)
        task.signals.finished.connect(self._on_pur_images_ready)
        self._pur_tasks[str(pur)] = task
        _PUR_EXPORT_POOL.start(task)

    def _on_pur_images_ready(self, pur_str: str, mtime: float, files, error: str):
        """Images d'une planche pretes : si la visionneuse la montre encore, elle est remplacee par
        ses images, sans changer l'image regardee (ou par sa 1re image si c'etait elle)."""
        self._pur_tasks.pop(pur_str, None)
        pur = Path(pur_str)
        if not files:
            self._pur_expansions[pur_str] = (mtime, [])
            return
        self._remember_pur(pur, mtime, files)
        try:
            pos = next(i for i, p in enumerate(self._viewer_paths) if str(p) == pur_str)
        except StopIteration:
            return
        images = self._pur_expansions[pur_str][1]
        self._viewer_paths[pos:pos + 1] = images
        current = self._viewer_index
        if current > pos:
            self._viewer_index = current + len(images) - 1
        if self._filmstrip is not None:
            self._filmstrip.set_paths(self._viewer_paths, self._viewer_index)
        if current == pos and self._viewer_active():
            self._viewer_go(pos, 0)                 # la planche montree devient sa 1re image

    def _viewer_active(self) -> bool:
        return (self._project_columns_hidden and self._focus_gallery is None
                and 0 <= self._viewer_index < len(self._viewer_paths))

    # -- Dossier dans la visionneuse + mode récursif (demande de l'utilisateur) --

    def _recursive_on(self) -> bool:
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_recursive", False))

    def _recursive_known(self) -> list | None:
        """Photos du dossier de la visionneuse ET de ses sous-dossiers (parcours en fond, file_filters.scan_files) ;
        None : mode coupé ou parcours pas encore fait."""
        folder = self._viewer_entry_folder or self._viewer_folder
        if not self._recursive_on() or folder is None:
            return None
        known = self._scope_files.get(str(folder))
        return [Path(entry[0]) for entry in known] if known is not None else None

    def _viewer_folder_files(self, folder: Path) -> list:
        """Fichiers à aperçu DIRECTEMENT dans `folder` : l'ordre de sa colonne si elle est ouverte, sinon le
        nom."""
        kinds = PREVIEWABLE_EXTENSIONS | PUR_PREVIEW_EXTENSIONS
        for column in [*self.columns, *self.group_columns]:
            if Path(column.directory) == folder:
                return [Path(item.data(ROLE_PATH)) for item in
                        (column.list.item(i) for i in range(column.list.count()))
                        if not item.data(ROLE_ISDIR) and Path(item.data(ROLE_PATH)).suffix.lower() in kinds]
        try:
            return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in kinds
                           and not p.name.startswith(".")), key=lambda p: p.name.casefold())
        except OSError:
            return []

    def _view_folder_in_viewer(self, folder: Path, column=None, gallery: bool = False):
        """Double-clic sur un dossier : la visionneuse s'ouvre sur sa première photo (la planche est à une
        touche : G). `gallery` (menu « Ouvrir la visionneuse à cet endroit ») : directement la PLANCHE, sans
        aucune image en focus. Mode récursif : les photos des sous-dossiers aussi (parcours en fond si
        besoin). Sans aucune photo à montrer : l'explorateur, comme avant."""
        if self._project_columns_hidden:
            return
        folder = Path(folder)
        files = self._viewer_folder_files(folder)
        if gallery and not files and not self._recursive_on():
            # Les photos sont dans les sous-dossiers : la planche les montre (mode récursif allumé pour cela,
            # remis si finalement il n'y en a aucune) ; jamais l'explorateur depuis ce menu.
            self._auto_recursive = True
            self._set_recursive(True)
        if self._recursive_on():
            known = self._scope_files.get(str(folder))
            if known is None:
                self._pending_folder_view = (folder, column, gallery)
                self._start_filter_scan(folder)
                return
            files = [Path(entry[0]) for entry in known] or files
        if not files:
            if gallery:
                self.path_label.setText(f"Aucune photo dans {folder.name} ni dans ses sous-dossiers")
                if getattr(self, "_auto_recursive", False):
                    self._set_recursive(False)
                self._auto_recursive = False
                return
            self.on_activated(folder)
            return
        self._auto_recursive = False
        first = files[0]

        def go():
            pixmap = self._focus_pixmap(first, None)
            slot = None
            if column is not None and pixmap is not None and not pixmap.isNull():
                for i in range(column.list.count()):
                    item = column.list.item(i)
                    if item.data(ROLE_PATH) == str(folder):
                        rect = column.list.visualItemRect(item)
                        side = max(8, min(rect.height(), rect.width()))
                        thumb = QRect(0, 0, side, side)
                        thumb.moveCenter(rect.center())
                        viewport = self.scroll.viewport()
                        slot = QRect(viewport.mapFromGlobal(column.list.viewport().mapToGlobal(thumb.topLeft())),
                                     thumb.size())
                        break
            if gallery:
                slot = None                                      # planche directe : aucune image ne vole
            if slot is not None:
                self._viewer_entry_source = (pixmap, slot)       # l'image part de la ligne du dossier
            self._viewer_entry_path = (None, first)
            self._viewer_entry_folder = folder
            # Planche directe : pas d'objet qui part au centre, donc la garde « sans colonne Focus » ne
            # s'applique pas (sinon les colonnes restaient et l'explorateur s'ouvrait).
            self._viewer_force_hide = gallery
            try:
                self._set_columns_hidden(True, animate=not gallery)
            finally:
                self._viewer_force_hide = False
                self._viewer_entry_source = None
                self._viewer_entry_path = None
                self._viewer_entry_folder = None
            if not self._project_columns_hidden:
                self.on_activated(folder)
            elif gallery:
                self._gallery_no_focus = True                    # aucune case « en cours » : pas de focus
                self._open_focus_gallery()
                self._gallery_no_focus = False
            elif self._focus_overlay is None and 0 <= self._viewer_index < len(self._viewer_paths):
                self._viewer_go(self._viewer_index)              # aucun objet au centre au départ : créé ici

        QTimer.singleShot(0, go)

    def _sync_recursive_button(self):
        """Bouton « Récursif » (visionneuse ou planche ouverte) : allumé (couleur du filtre actif) quand les
        photos des sous-dossiers sont montrées aussi."""
        viewer_mode = self._project_columns_hidden and (self._focus_gallery is not None or self._viewer_active())
        button = self._recursive_btn
        if not viewer_mode:
            if button is not None and not button.isHidden():
                button.hide()
                self._layout_viewer_buttons()
            return
        if button is None:
            # Icone (demande de l'utilisateur ; Reglages > Visionneuse > Icones > Recursif), plus un texte.
            button = self._recursive_btn = IconButton(
                "recursive", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._toggle_recursive)
        style_focus_button(button)
        on = self._recursive_on()
        button.set_alert(resolve_color_ref((ui_state.APPLIED_SETTINGS or {}).get("viewer_filter_active_color")
                                           or "#c62828") if on else None)
        button.setToolTip("Récursif : photos des sous-dossiers montrées (clic pour les retirer)" if on
                          else "Récursif : montrer aussi les photos des sous-dossiers")
        button.show()
        button.raise_()
        self._layout_viewer_buttons()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())

    def _toggle_recursive(self):
        """Bouton « Récursif » : bascule (voir `_set_recursive`)."""
        self._set_recursive(not self._recursive_on())

    def _set_recursive(self, value: bool):
        """Mode récursif (bouton « Récursif » ou case du menu d'un dossier), enregistré aussitôt (état temps
        réel) ; la liste de la visionneuse, la pellicule et la planche sont refaites sur place, l'image
        regardée gardée si elle y est encore."""
        value = bool(value)
        if value == self._recursive_on():
            return
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["viewer_recursive"] = value
        from settings_store import save_live_state
        save_live_state("viewer_recursive", value)
        self._recursive_applied = value
        self._sync_settings_row("viewer_recursive", value)      # sa ligne de Reglages > Visionneuse suit
        self._refresh_recursive_list(value)

    def _sync_settings_row(self, setting: str, value):
        """La ligne `setting` de la fenetre de reglages (ouverte ou gardee en memoire) prend `value`."""
        dialog = getattr(self, "_settings_dialog_v2", None)
        if dialog is None:
            return
        try:
            for store in dialog.stores.values():
                for spec, widget in store.get("specs", ()):
                    if getattr(spec, "key", None) == setting and widget.isChecked() != bool(value):
                        widget.blockSignals(True)
                        widget.setChecked(bool(value))
                        widget.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass

    def _refresh_recursive_list(self, value: bool):
        """Liste de la visionneuse / planche refaite pour le mode recursif `value`."""
        folder = self._viewer_folder
        if value and folder is not None:
            self._start_filter_scan(folder)                      # liste complète lue en fond
        self._apply_viewer_base()
        self._sync_recursive_button()

    def _apply_viewer_base(self):
        """Refait la liste de la visionneuse (récursive ou non) sans quitter l'image en cours ; pellicule et
        planche suivent."""
        folder = self._viewer_folder
        if not self._project_columns_hidden or folder is None:
            return
        recursive = self._recursive_on()
        if recursive:
            paths = self._recursive_known()
            if paths is None:
                return                                           # parcours en cours : l'arrivée relancera
        else:
            paths = self._viewer_folder_files(folder)
        if not paths:
            return
        current = (str(self._viewer_paths[self._viewer_index])
                   if 0 <= self._viewer_index < len(self._viewer_paths) else None)
        if not recursive:
            self._viewer_purs = [p for p in paths if p.suffix.lower() in PUR_PREVIEW_EXTENSIONS]
            paths, _index = self._expand_viewer_pureref(paths, current)
        else:
            self._viewer_purs = []
        if [str(p) for p in paths] == [str(p) for p in (self._viewer_base or [])]:
            return
        self._viewer_base = list(paths)
        shown, _found = self._filtered_gallery(list(paths), current, rescan=False)
        self._viewer_paths = list(shown or paths)
        index = next((i for i, p in enumerate(self._viewer_paths) if str(p) == current), -1)
        if self._filmstrip is not None:
            self._filmstrip.set_paths(self._viewer_paths, max(0, index))
        self._viewer_index = index if index >= 0 else 0
        if index < 0 and self._focus_gallery is None:
            self._viewer_go(0)                                   # l'image regardée n'est plus dans la liste
        if self._focus_gallery is not None:
            self._refresh_focus_gallery(rescan=False)
        self._sync_pur_buttons()
        self._sync_recursive_button()

    def _position_focus_origin_badge(self):
        badge = getattr(self, "_focus_origin_badge", None)
        if badge is not None:
            badge.move(scaled(12, 0), scaled(48, 0))

    def _set_focus_origin_badge(self, path: Path | None, *, decoded: bool = False,
                                application_preview: bool = False):
        """La source de l'image au centre (et celle du proxy) est dans le tableau de droite,
        « Paramètres de l'image » (lignes « Source du proxy » / « Source de l'aperçu plein écran »,
        demande de l'utilisateur) — plus d'encart près des boutons : ce tableau est relu quand
        l'image en focus ou son proxy arrive (la source a pu changer)."""
        badge = getattr(self, "_focus_origin_badge", None)
        if badge is not None:
            badge.hide()
        panel = getattr(self, "_info_panel", None)
        if panel is not None and path is not None and (decoded or application_preview):
            panel.refresh(path)

    def _sync_viewer_chrome(self):
        """Pellicule, raccourcis clavier et suivi de la souris : actifs seulement colonnes
        masquees, image seule au centre (pas pendant la planche)."""
        self._sync_collapse_button()
        self._request_crumbs()                   # visionneuse ouverte / fermee : son cheminement ou celui des colonnes
        if not self._project_columns_hidden:
            self._release_viewer_buttons()       # cadre « Visionneuse » de la barre : boutons rendus
            self._viewer_sync.stop()
            self._viewer_paths, self._viewer_index = [], -1
            self._viewer_base = []
            self._viewer_purs = []
            self._viewer_folder = None
            self._pending_folder_view = None
            if hasattr(self, "_focus_origin_badge"):
                self._focus_origin_badge.hide()
        self._sync_recursive_button()
        self._sync_pur_buttons()
        active = self._viewer_active()
        # I bascule l'inspecteur dans la navigation normale; en visionneuse,
        # cette touche reste réservée au tableau « Paramètres de l'image ».
        if hasattr(self, "_inspector_shortcut"):
            self._inspector_shortcut.setEnabled(not self._project_columns_hidden)
        if active and not self._large_lightroom_timer.isActive():
            self._large_lightroom_timer.start()
        elif not active:
            self._large_lightroom_timer.stop()
        if not active and hasattr(self, "_focus_origin_badge"):
            self._focus_origin_badge.hide()
        self._sync_lightroom_button()
        self._sync_viewer_100_button(active)
        if active and not self._viewer_keys:
            self._ensure_viewer_keys()
        for shortcut in self._viewer_keys:
            shortcut.setEnabled(active)
        self._sync_info_panel(active)
        strip = self._filmstrip
        if not active or not self._filmstrip_enabled():
            self._viewer_idle.stop()
            if strip is not None and not strip.isHidden():
                strip.hide()
            if active and self._focus_overlay is not None:
                self._focus_overlay.set_holes(self._button_rects())
            return
        if strip is None:
            strip = self._filmstrip = FocusFilmstrip(
                self.scroll.viewport(), focus_thumbnail, on_wheel=self._on_focus_wheel,
                on_double_click=self._toggle_project_columns_hidden,
                on_resized=self._on_filmstrip_resized, on_split=self._on_filmstrip_split,
                on_menu=self._filmstrip_menu)
            strip.keep_shown = self._film_style_open
            strip.chosen.connect(self._on_filmstrip_chosen)
            strip.set_paths(self._viewer_paths, self._viewer_index)
        if strip.isHidden():
            strip.setGeometry(self._filmstrip_rect())
            strip.set_current(self._viewer_index)
            strip.set_position(self._viewer_index)
            strip.show()
            strip.reveal()
        strip.raise_()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())
        holder = QApplication.focusWidget()
        if holder is None or not holder.isVisible():
            # Le widget qui avait le clavier a disparu (colonnes Focus rebaties par la navigation
            # de la visionneuse) : sans lui, plus aucun raccourci ne repondrait.
            self._park_keyboard_focus()
        if not self._viewer_idle.isActive():
            self._viewer_cursor = None
            self._viewer_idle.start()

    def _toggle_inspector(self):
        """Affiche ou masque l'inspecteur avec I, hors visionneuse."""
        if self._project_columns_hidden:
            return
        self._inspector_visible = not self._inspector_visible
        self.detail.setVisible(self._inspector_visible)

    def _sync_pur_buttons(self):
        """Visionneuse (ou planche) ouverte sur un dossier qui contient des planches PureRef : un
        bouton par fichier, a la suite des autres boutons (repli / masquer / planche, ou le bouton
        flottant), sur leur ligne, qui l'ouvre dans PureRef (logiciel par defaut). Meme habillage
        que ces boutons (style_focus_button), largeur = le nom."""
        purs = self._viewer_purs if self._project_columns_hidden else []
        viewport = self.scroll.viewport()
        while len(self._pur_buttons) < len(purs):
            button = IconButton("text", role_color("buttons", "#c4cacf"), C["text"], parent=viewport)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _c=False, b=button: open_path(b._pur_path))
            self._pur_buttons.append(button)
        for button, pur in zip(self._pur_buttons, purs):
            style_focus_button(button)
            button._pur_path = pur
            button.set_text_label(pur.name)
            button.setToolTip(f"Ouvrir {pur.name} dans PureRef")
            width = button.fontMetrics().horizontalAdvance(pur.name) + scaled(20)
            button.setFixedWidth(max(button.width(), width))
            button.show()
            button.raise_()
        for button in self._pur_buttons[len(purs):]:
            button.hide()
        self._layout_viewer_buttons()

    def _sync_lightroom_button(self):
        """Affiche le bouton uniquement pour une photo gérée par un catalogue Lightroom."""
        button = self._lightroom_btn
        path = (self._viewer_paths[self._viewer_index]
                if self._viewer_active() else None)
        try:
            import lightroom_bridge
            available = path is not None and path.suffix.casefold() in lightroom_bridge._PREFETCH_EXTENSIONS \
                and lightroom_bridge.is_managed(path)
        except (ImportError, OSError, ValueError):
            available = False
        if not available:
            if button is not None:
                button.hide()
                self._layout_viewer_buttons()
            return
        if button is None:
            button = self._lightroom_btn = IconButton(
                "text", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._open_current_in_lightroom)
        style_focus_button(button)
        button.set_text_label("Modifier dans Lightroom")
        button.setToolTip("Ouvrir cette photo dans Lightroom Classic, en mode Développement")
        button.setFixedWidth(button.fontMetrics().horizontalAdvance("Modifier dans Lightroom") + scaled(20))
        button.show()
        button.raise_()
        self._layout_viewer_buttons()
        if self._focus_overlay is not None:
            button_rects = self._button_rects()
            self._focus_overlay.set_holes(button_rects)

    def _open_current_in_lightroom(self):
        if not self._viewer_active():
            return
        import lightroom_bridge
        path = self._viewer_paths[self._viewer_index]
        self.path_label.setText(f"Lightroom · ouverture de {path.name}…")
        lightroom_bridge.open_in_lightroom(path)

    def _sync_viewer_100_button(self, active: bool):
        """Bouton de taille reelle, visible uniquement dans la visionneuse d'image."""
        if not active:
            if self._viewer_100_btn is not None:
                self._viewer_100_btn.hide()
                self._layout_viewer_buttons()
            return
        button = self._viewer_100_btn
        if button is None:
            button = self._viewer_100_btn = IconButton(
                "text", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._viewer_show_actual_size)
        style_focus_button(button)
        button.set_text_label("100 %")
        button.setToolTip("Afficher la photo a sa taille reelle (100 %)")
        button.setFixedWidth(button.fontMetrics().horizontalAdvance("100 %") + scaled(20))
        button.show()
        button.raise_()
        self._layout_viewer_buttons()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())

    def _viewer_show_actual_size(self):
        if self._viewer_active() and self._focus_overlay is not None:
            self._focus_overlay.zoom_toggle_actual()

    def on_activated(self, path: Path):
        # Double-clic (ou "Ouvrir") : un dossier s'ouvre dans l'explorateur
        # Windows, un fichier dans son application par defaut. Une note .md d'un coffre Obsidian
        # s'ouvre dans Obsidian, SUR cette note (demande de l'utilisateur) ; a defaut, son logiciel.
        if path.is_dir():
            open_in_file_manager(path)
            return
        if self._video_claims(path) and self._open_video(path):   # module video : video / sequence d'images
            return
        import fm_board as board
        if board.is_board_file(path):                     # board facon Miro : ouvert DANS l'appli
            if self._open_board(path):
                return
        if board.is_cad_drawing(path) and (ui_state.APPLIED_SETTINGS or {}).get("board_open_cad_drawings", True):
            self._open_cad_drawing(path)                  # dessin DXF / DWG : module MRO (lu en fond)
            return
        if self._md_opens_on_double_click(path):
            if self._open_md_editor(path):                # module Markdown / code : note ou fichier DANS l'appli
                return
        if path.suffix.lower() == ".md":
            from fm_markdown import preview as markdown_preview
            url = markdown_preview.obsidian_open_url(path)
            if url is not None:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                if QDesktopServices.openUrl(QUrl(url)):
                    return
        open_path(path)

    def _view_in_viewer(self, path: Path, column=None):
        """Double-clic sur une ligne d'une colonne (image, planche PureRef, fichier qui a un apercu,
        voir column.opens_in_viewer) : la visionneuse de l'appli (colonnes masquees, l'image au centre),
        une fois que le clic l'a montree dans l'inspecteur. L'image part de l'apercu de la LIGNE
        (pas de celui de l'inspecteur) ; le retour aux colonnes la ramene dans l'inspecteur."""
        if self._project_columns_hidden:
            return
        if self._video_claims(path) and self._open_video(path):   # video / sequence EXR, TIFF… : module video
            return

        def go():
            source = column.preview_source(path) if column is not None else None
            if source is not None:
                pixmap, rect = source
                viewport = self.scroll.viewport()
                self._viewer_entry_source = (pixmap, QRect(viewport.mapFromGlobal(rect.topLeft()), rect.size()))
            # La visionneuse s'ouvre sur CE fichier, meme si l'inspecteur ne le montre pas : double-clic sur
            # la ligne DEJA selectionnee = son 1er clic est un re-clic, qui la deselectionne et vide
            # l'inspecteur ; la visionneuse ne trouvait alors aucun fichier et seule la miniature de la
            # ligne arrivait au centre, a sa petite taille (bug signale). Au retour, la colonne et
            # l'inspecteur reprennent l'image montree (_flush_viewer_sync).
            self._viewer_entry_path = (column, Path(path))
            try:
                self._set_columns_hidden(True)
            finally:
                self._viewer_entry_source = None
                self._viewer_entry_path = None
            if not self._project_columns_hidden:
                self.on_activated(path)          # rien a montrer (planche sans apercu...) : son logiciel

        QTimer.singleShot(0, go)

    def _entry_focus_source(self, home):
        """Depart du vol vers la visionneuse quand on vient d'un double-clic sur une ligne : la place de
        l'apercu de la ligne, avec l'image de l'inspecteur (meme fichier, meilleure definition)."""
        entry = getattr(self, "_viewer_entry_source", None)
        if entry is None:
            return home
        pixmap = home[0] if home is not None else entry[0]
        dpr = pixmap.devicePixelRatio() or 1.0
        size = QSize(round(pixmap.width() / dpr), round(pixmap.height() / dpr))
        size.scale(entry[1].size(), Qt.KeepAspectRatio)
        rect = QRect(0, 0, max(1, size.width()), max(1, size.height()))
        rect.moveCenter(entry[1].center())
        return pixmap, rect

    def _send_focus_home(self, overlay, home):
        """Vol depuis une ligne termine (image au centre, rien ne bouge) : le retour aux colonnes la
        ramenera dans l'inspecteur, sa vraie place, pas sur la ligne."""
        if overlay is self._focus_overlay and home is not None and shiboken6.isValid(overlay):
            overlay.set_geometry_target(None, QRectF(home[1]))

    def browse_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Racine du pipeline", self.root_field.text()
        )
        if chosen:
            self.root_field.setText(chosen)
            self.reload()
