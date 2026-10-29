"""Méthodes de colonne : menu contextuel et réglages par ligne."""

import json
import time
from pathlib import Path
from PySide6.QtCore import QMimeData, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox
from app_style import font, column_style_for
import ui_state
from config import PREVIEWABLE_EXTENSIONS, RENDERABLE_3D_EXTENSIONS, _MANUAL_3D_PREVIEW_MODE, _MANUAL_3D_PREVIEW_REQUESTS, _STALE_PREVIEW_PATHS
from previews import _PREVIEW_DECODE_MANAGER
from settings_widgets import Menu, menu_row, _SliderField, run_space_menu_hooks
from browser_core import ROLE_ISDIR, ROLE_IS_SHORTCUT, ROLE_LIGHTROOM_SHORTCUT, ROLE_SPACE_ABOVE, ROLE_SPACE_BELOW, ROLE_PIN_BOTTOM, ROLE_PATH, _update_layout_setting, project_thumbnail_path, remove_shortcut, reveal_in_file_manager


class ColumnContextMenuMixin:
    def _on_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is not None and self.title_area_hit(item, pos):
            self._title_menu(item, pos)
            return
        if not item:
            menu = Menu(self)
            menu.setFont(font(11, 400))
            act_new_folder = menu.addAction("Nouveau dossier")
            act_new_text_file = menu.addAction("Nouveau document texte") if self._show_files else None
            # Board facon Miro (paquet board/) : fichier .mro (JSON), ouvert dans l'appli au double-clic.
            act_new_board = menu.addAction("Créer un mro") if self._show_files else None
            act_add_shortcut = menu.addAction("Ajouter un raccourci...")
            act_paste = None
            if QApplication.clipboard().mimeData().hasUrls():
                menu.addSeparator()
                act_paste = menu.addAction("Coller")
            chosen = menu.exec(self.list.mapToGlobal(pos))
            if chosen is act_new_folder:
                # QTimer.singleShot(0, ...) (PAS un appel direct) : ouvrir
                # une QInputDialog SYNCHRONE juste apres la fermeture du
                # QMenu (meme pile d'appel, meme evenement souris) lui
                # laissait parfois recevoir le RELACHEMENT de CE MEME clic
                # (celui qui vient de fermer le menu), la refermant aussitot
                # — voir la remarque de l'utilisateur, "des fois (notamment
                # quand on vient juste de creer un repertoire) la petite
                # fenetre qui demande le nom du repertoire apparait et
                # disparait aussitot". Reporter d'un tour de boucle
                # d'evenements laisse ce relachement etre traite normalement
                # AVANT que la boite de dialogue n'existe.
                QTimer.singleShot(0, self._create_folder)
            elif chosen is act_new_text_file:
                QTimer.singleShot(0, self._create_text_file)
            elif act_new_board is not None and chosen is act_new_board:
                QTimer.singleShot(0, self._create_board_file)
            elif chosen is act_add_shortcut:
                # 150ms (PAS 0) : ce menu ouvre un QFileDialog (via
                # _add_shortcut), pas seulement une QInputDialog — voir
                # _prompt_change_thumbnail, la MEME remarque ("un simple
                # tour de boucle Qt ne suffit pas a laisser Windows
                # relacher completement le grab souris/clavier NATIF du
                # menu contextuel tout juste ferme").
                QTimer.singleShot(150, self._add_shortcut)
            elif act_paste is not None and chosen is act_paste:
                self._paste_items()
            return
        path = Path(item.data(ROLE_PATH))
        is_shortcut = bool(item.data(ROLE_IS_SHORTCUT))
        menu = Menu(self)
        menu.setFont(font(11, 400))
        act_open = menu.addAction("Ouvrir")
        act_rename = menu.addAction("Renommer le raccourci…" if is_shortcut else "Renommer")
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        act_viewer = act_recursive = None
        if item.data(ROLE_ISDIR):
            # Visionneuse sur CE dossier, directement en planche (aucune image en focus), et « Récursif » :
            # les photos des sous-dossiers aussi (même réglage que le bouton de la visionneuse).
            act_viewer = menu.addAction("Ouvrir la visionneuse à cet endroit")
            act_recursive = menu.addAction("Récursif (photos des sous-dossiers)")
            act_recursive.setCheckable(True)
            act_recursive.setChecked(bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_recursive", False)))
        act_render_preview_low = None
        act_render_preview_high = None
        act_auto_preview = None
        if not item.data(ROLE_ISDIR):
            act_auto_preview = menu.addAction("Créer un aperçu automatique")
            act_auto_preview.setEnabled(path.suffix.lower() in PREVIEWABLE_EXTENSIONS)
        if path.is_file() and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
            menu.addSeparator()
            act_render_preview_low = menu.addAction("Générer un rendu low poly")
            act_render_preview_high = menu.addAction("Générer un rendu high resolution")
        act_change_thumb = None
        act_capture_thumb = None
        act_reset_thumb = None
        # `item.data(ROLE_ISDIR)` seul (PAS `self.has_thumbnails and ...`) :
        # cette fonctionnalite (deja generique, voir project_thumbnail_path/
        # _save_thumbnail_pixmap, aucune modification necessaire) etait
        # jusqu'ici reservee aux colonnes Projets/Sous-projet — voir la
        # remarque de l'utilisateur, "pouvoir integrer des images sur
        # n'importe quelle ligne de n'importe quelle colonne, comme par
        # exemple type ... en cliquant droit sur une ligne, ajouter un
        # apercu". Libelle "Ajouter" tant qu'aucun apercu personnalise
        # n'existe encore, "Changer" une fois qu'il y en a un (voir
        # _paint_unified_row, qui l'affiche a la place de l'icone toggle sur
        # la colonne "Type").
        has_custom = project_thumbnail_path(path).is_file()
        if item.data(ROLE_ISDIR):
            menu.addSeparator()
            act_change_thumb = menu.addAction("Changer l'image..." if has_custom else "Ajouter un apercu...")
            act_capture_thumb = menu.addAction("Capturer une zone d'ecran...")
            if has_custom:
                act_reset_thumb = menu.addAction("Reinitialiser l'image")

        menu.addSeparator()
        # "Afficher l'apercu"/"Afficher l'icone"/"Taille de l'icone" (voir
        # __init__ _show_icon_override/_show_preview_override/
        # _icon_size_override, _paint_unified_row) — valeur de depart =
        # celle EFFECTIVEMENT affichee (override deja actif, sinon le
        # reglage GENERAL) ; toute modification s'applique tout de suite
        # (session courante), et n'est ENREGISTREE (.pipeline_layout.json)
        # que si la punaise est active — voir la remarque de l'utilisateur,
        # "la valeur doit etre celle par defaut, et s'il y a changement
        # elle doit etre enregistree quand la colonne est pinnee
        # seulement".
        current_icon_visible = (
            self._show_icon_override if self._show_icon_override is not None
            else bool(column_style_for(self.style_title).get("item_icon_enabled", True)))
        current_preview_visible = (
            self._show_preview_override if self._show_preview_override is not None else True)
        act_show_icon = menu.addAction("Afficher l'icone")
        act_show_icon.setCheckable(True)
        act_show_icon.setChecked(current_icon_visible)
        act_show_icon.toggled.connect(self._set_show_icon_override)
        act_show_preview = menu.addAction("Afficher l'apercu")
        act_show_preview.setCheckable(True)
        act_show_preview.setChecked(current_preview_visible)
        act_show_preview.toggled.connect(self._set_show_preview_override)

        default_icon_size = int(column_style_for(self.style_title).get("item_icon_size") or 0) or 32
        self._add_context_slider(
            menu, "Taille de l'icone", self._icon_size_override or default_icon_size,
            8, 128, self._set_icon_size_override)

        default_icon_pad = int(column_style_for(self.style_title).get("item_icon_padding_left") or 0)
        self._add_context_slider(
            menu, "Padding gauche de l'icone", self._icon_padding_left_override or default_icon_pad,
            0, 64, self._set_icon_padding_left_override)

        default_text_pad = int(column_style_for(self.style_title).get("item_text_padding") or 8)
        self._add_context_slider(
            menu, "Padding gauche du texte", self._text_padding_left_override or default_text_pad,
            0, 64, self._set_text_padding_left_override)

        # Espace au-dessus de CETTE ligne (retenu dans le .pipeline_layout.json, voir set_item_space).
        # « Ajouter un titre au-dessus » se place dans cet espace : grise tant qu'il est trop petit
        # (suit le curseur ci-dessus en direct).
        title_holder = []

        def on_space(value, it=item):
            self.set_item_space(it, value)
            if title_holder:
                title_holder[0].setEnabled(self.can_add_title(it))

        self._add_context_slider(
            menu, "Ajouter une espace au-dessus", int(item.data(ROLE_SPACE_ABOVE) or 0), 0, 200, on_space)
        self._add_context_slider(
            menu, "Ajouter une espace en dessous", int(item.data(ROLE_SPACE_BELOW) or 0), 0, 200,
            lambda value, it=item: self.set_item_space(it, value, below=True))
        # « Override settings » (settings_element_style), comme partout ou il y a ces lignes d'espace.
        run_space_menu_hooks(self.list.viewport(), menu, {
            "above": int(item.data(ROLE_SPACE_ABOVE) or 0), "below": int(item.data(ROLE_SPACE_BELOW) or 0),
            "set_above": on_space, "set_below": lambda value, it=item: self.set_item_space(it, value, below=True),
            "maximum": 200})
        act_add_title = menu.addAction("Ajouter un titre au-dessus…")
        act_add_title.setEnabled(self.can_add_title(item))
        title_holder.append(act_add_title)
        act_bottom = menu.addAction("Positionner au bas de la colonne")
        act_bottom.setCheckable(True)
        act_bottom.setChecked(bool(item.data(ROLE_PIN_BOTTOM)))
        act_bottom.setEnabled(self._order_store()[0] is not None)

        menu.addSeparator()
        act_copy_file = menu.addAction("Copier")
        act_copy_path = menu.addAction("Copier le chemin")
        # « Supprimer » (demande de l'utilisateur) : pas sur un raccourci, qui supprimerait sa CIBLE
        # (« Retirer le raccourci » retire l'entree).
        act_delete = menu.addAction("Supprimer") if not is_shortcut else None
        menu.addSeparator()
        # Meme menu qu'un dossier standard (renommer/image/copier agissent sur
        # le dossier CIBLE) ; "Retirer le raccourci" retire seulement l'ENTREE.
        act_remove_shortcut = menu.addAction("Retirer le raccourci") if is_shortcut else None
        act_lightroom = menu.addAction("Associer ce dossier à Lightroom…") if is_shortcut and path.is_dir() else None
        act_obsidian_app = None
        if not item.data(ROLE_ISDIR) and path.suffix.lower() == ".md":
            from fm_markdown import preview as markdown_preview
            if markdown_preview.vault_containing(path) is not None:
                act_obsidian_app = menu.addAction("Ouvrir dans l'application Obsidian")
        act_add_shortcut = menu.addAction("Ajouter un raccourci...")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if act_viewer is not None and chosen is act_viewer:
            QTimer.singleShot(0, lambda p=path: self.folder_gallery_requested.emit(p))
            return
        if act_recursive is not None and chosen is act_recursive:
            self.recursive_requested.emit(act_recursive.isChecked())
            return
        if chosen is act_bottom:
            pinned = act_bottom.isChecked()
            QTimer.singleShot(0, lambda it=item: self.set_item_bottom(it, pinned))
            return
        if chosen is act_add_title:
            key = self._item_key(item)
            if key is not None:
                QTimer.singleShot(0, lambda: self._prompt_item_title(key))
            return
        if chosen is act_open:
            self.activated.emit(path)
        elif chosen is act_rename:
            if is_shortcut:
                self._rename_shortcut(path, item.text())
            else:
                self._rename_item(path)
        elif chosen is act_reveal:
            reveal_in_file_manager(path)
        elif act_auto_preview is not None and chosen is act_auto_preview:
            QTimer.singleShot(0, lambda p=path: self._create_automatic_preview(p))
        elif act_render_preview_low is not None and chosen is act_render_preview_low:
            try:
                path_key = str(path)
                _MANUAL_3D_PREVIEW_REQUESTS.add(path_key)
                _MANUAL_3D_PREVIEW_MODE[path_key] = "low"
                _STALE_PREVIEW_PATHS.add(path_key)
                self.selected.emit(self, path)
            except OSError:
                pass
        elif act_render_preview_high is not None and chosen is act_render_preview_high:
            try:
                path_key = str(path)
                _MANUAL_3D_PREVIEW_REQUESTS.add(path_key)
                _MANUAL_3D_PREVIEW_MODE[path_key] = "high"
                _STALE_PREVIEW_PATHS.add(path_key)
                self.selected.emit(self, path)
            except OSError:
                pass
        elif act_change_thumb is not None and chosen is act_change_thumb:
            self._change_thumbnail(path)
        elif act_capture_thumb is not None and chosen is act_capture_thumb:
            self._capture_thumbnail(path)
        elif act_reset_thumb is not None and chosen is act_reset_thumb:
            self._reset_thumbnail(path)
        elif chosen is act_copy_file:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(path))
        elif act_delete is not None and chosen is act_delete:
            QTimer.singleShot(0, lambda p=path: self.delete_path(p))     # apres la fermeture du menu
        elif act_remove_shortcut is not None and chosen is act_remove_shortcut:
            for source in (self._source_dirs if self._source_dirs is not None else [self.directory]):
                remove_shortcut(source, path)
            self.refresh()
        elif act_lightroom is not None and chosen is act_lightroom:
            self._configure_lightroom_folder(path)
        elif act_obsidian_app is not None and chosen is act_obsidian_app:
            from fm_markdown import preview as markdown_preview
            url = markdown_preview.obsidian_open_url(path)
            if url:
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(url))
        elif chosen is act_add_shortcut:
            QTimer.singleShot(150, self._add_shortcut)
    def _configure_lightroom_folder(self, path: Path):
        """Associe le dossier cible du raccourci à son catalogue Lightroom."""
        current = {}
        marker = path / ".pipeline_lightroom.json"
        try:
            current = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Catalogue Lightroom Classic", str(current.get("catalog", path)), "Catalogue Lightroom (*.lrcat)"
        )
        if not chosen:
            return
        catalog = Path(chosen)
        if not catalog.is_file():
            QMessageBox.warning(self, "Association Lightroom", "Le fichier catalogue n’existe pas.")
            return
        temp = marker.with_name(marker.name + ".tmp")
        try:
            association = dict(current) if isinstance(current, dict) else {}
            association.update({
                "catalog": str(catalog.resolve()),
                "set_defaults_at_ns": time.time_ns(),
            })
            temp.write_text(json.dumps(association, indent=2), encoding="utf-8")
            temp.replace(marker)
        except OSError as exc:
            QMessageBox.warning(self, "Association Lightroom", f"Impossible d’enregistrer l’association :\n{exc}")
            return
        from previews import _set_hidden
        _set_hidden(marker)
        from browser_core import invalidate_project_columns_cache
        invalidate_project_columns_cache()
        import lightroom_bridge
        lightroom_bridge._managed_directory.cache_clear()
        lightroom_bridge._write_connection(lightroom_bridge._cache_root(catalog), catalog.resolve())
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(str(lightroom_bridge.PLUGIN))
        bus = lightroom_bridge._signal_bus()
        owner = self.window()
        if not getattr(owner, "_lightroom_error_connected", False):
            bus.failed.connect(lambda _path, message: owner.path_label.setText("Lightroom : " + message))
            owner._lightroom_error_connected = True
        QMessageBox.information(
            self, "Dossier associé à Lightroom",
            "Le catalogue est associé à ce dossier. Les réglages de set de la capture sont appliqués à ses "
            "dossiers existants et futurs. Les aperçus Lightroom déjà en cache seront lus directement.\n\n"
            "Le chemin du module SDK a aussi été copié pour les échanges d'attributs avec Lightroom :\n\n"
            f"{lightroom_bridge.PLUGIN}\n\n"
            "Dans Lightroom Classic, ajoutez ce module via Fichier > Gestionnaire de modules externes > Ajouter."
        )
        for row in range(self.list.count()):
            shortcut_item = self.list.item(row)
            if shortcut_item.data(ROLE_PATH) == str(path):
                shortcut_item.setData(ROLE_LIGHTROOM_SHORTCUT, True)
                self.list.viewport().update(self.list.visualItemRect(shortcut_item))
                break
        self.list.viewport().update()
    def _create_automatic_preview(self, path: Path):
        """Lance le décodeur habituel en fond, y compris pour les MKV à la demande."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        _PREVIEW_DECODE_MANAGER.request(path, mtime, force_render=True)
    def _add_context_slider(self, menu: QMenu, label_text: str, value: int, vmin: int, vmax: int, on_change):
        """Ligne "slider + valeur px en temps reel" du menu contextuel
        (voir _on_context_menu, "Taille de l'icone"/"Padding gauche de
        l'icone"/"Padding gauche du texte") — reutilise TEL QUEL le
        _SliderField de la fenetre de parametres (slider + boite de
        saisie px, deja avec sa valeur en temps reel) — voir la remarque
        de l'utilisateur, "je veux que le style [du slider] soit celui des
        settings" (remplace l'ancien QSlider habille a la main). Ligne alignee
        comme toutes celles des menus contextuels (settings_menu.menu_row)."""
        field = _SliderField(vmin, vmax, value, slider_width=120, box_width=60)
        field.valueChanged.connect(on_change)
        menu_row(menu, label_text, field)
    def _should_autosave_context_override(self) -> bool:
        """Vrai si CE reglage du menu contextuel doit s'enregistrer SANS
        punaise — "Type" n'a jamais de bouton punaise (voir __init__) mais
        doit neanmoins s'enregistrer automatiquement, comme sa largeur/sa
        hauteur de ligne (voir _persist_column_width/row_resize_end) — voir
        la remarque de l'utilisateur, "tous les parametres du menu
        contextuel ne s'enregistrent pas automatiquement dans la colonne
        de type"."""
        return self._pin_active or self.style_title == "Type"
    def _set_show_icon_override(self, value: bool):
        self._show_icon_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "show_icon", value)
    def _set_show_preview_override(self, value: bool):
        self._show_preview_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "show_preview", value)
    def _set_icon_size_override(self, value: int):
        self._icon_size_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "icon_size", value)
    def _set_icon_padding_left_override(self, value: int):
        self._icon_padding_left_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "icon_padding_left", value)
    def _set_text_padding_left_override(self, value: int):
        self._text_padding_left_override = value
        self.list.viewport().update()
        if self._should_autosave_context_override():
            _update_layout_setting(self.directory, "text_padding_left", value)
