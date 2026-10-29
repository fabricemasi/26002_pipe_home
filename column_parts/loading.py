"""Méthodes de colonne : chargement et affichage des entrées."""

import time
from pathlib import Path
from PySide6.QtWidgets import QListWidgetItem
from previews import is_remote_path, software_icon_key
from config import GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_EXTENSIONS, GLOBAL_OMIT_FILE_NAMES
from browser_core import ROLE_ISDIR, ROLE_IS_SHORTCUT, ROLE_LIGHTROOM_SHORTCUT, ROLE_SPACE_ABOVE, ROLE_SPACE_BELOW, ROLE_PIN_BOTTOM, ROLE_TITLE_ABOVE, ROLE_META, ROLE_MEDIA_COUNTS, ROLE_PATH, ROLE_SOURCE_LABEL, ROLE_SOURCE_STEP, _STATUS_FOLDER_SET, _is_globally_omitted_dir, _is_globally_omitted_file, count_entries, entry_is_dir, entry_size, human_size, list_entries, remember_entry, load_layout_settings, load_shortcuts
from capture_widgets import item_order_key
from .shared import _MediaCountTask, _MEDIA_COUNT_POOL, _shortcut_present


class ColumnLoadingMixin:
    def cancel_loading(self):
        """Retrait d'une colonne : aucune attente du disque, aucun résultat tardif."""
        self._load_timer.stop()
        self._revalidate_timer.stop()
        self._row_timer.stop()
        self._row_iterator = None
        self._media_counts_generation += 1
        task = getattr(self, "_media_task", None)
        if task is not None:
            task.cancelled.set()
        if self._load_key is not None:
            from column_loading import loader
            loader().cancel(self._load_key, self)
        self._load_key = None
        self.loading = False
    def _revalidate_if_visible(self):
        if not self.loading and self.isVisible() and not self.visibleRegion().isEmpty():
            self._start_load(force=False)
    def _start_load(self, force=True):
        from column_loading import loader
        service = loader()
        directories = self._source_dirs if self._source_dirs is not None else [self.directory]
        # Le dossier stable d'un groupe peut être absent des sources fusionnées.
        directories = list(dict.fromkeys([*directories, self.directory]))
        exclude = None if self._source_dirs is not None else _STATUS_FOLDER_SET
        key = service.key(directories, exclude)
        if self._load_key is not None and self._load_key != key:
            service.cancel(self._load_key, self)
        self._load_key = key
        cached = service.cached(key)
        if not force and cached is not None:
            if cached is not self._loaded_data:
                self._apply_column_data(cached)
            if time.monotonic() - cached.stamp < service.FRESH_S:
                return
        self.loading = True
        self._load_error = ""
        self.list.setToolTip("Actualisation en cours…" if self.list.count() else "Lecture du dossier…")
        service.request(key, directories, exclude, self, force=force)
    def _column_data_ready(self, key, data, error):
        if key != self._load_key:
            return
        from column_loading import loader
        directories = self._source_dirs if self._source_dirs is not None else [self.directory]
        directories = list(dict.fromkeys([*directories, self.directory]))
        exclude = None if self._source_dirs is not None else _STATUS_FOLDER_SET
        if key != loader().key(directories, exclude):
            self._start_load(force=False)       # preset / configuration changés pendant la lecture
            return
        if data is not None and self._source_dirs is None and data.errors.get(str(self.directory)):
            error, data = data.errors[str(self.directory)], None
        self.loading = False
        self._load_error = error
        self.list.setToolTip(error)
        if data is not None:
            self._apply_column_data(data)
        else:
            self.loaded.emit()
    def _apply_column_data(self, data):
        previous = self._loaded_data
        self._loaded_data = data
        self._load_error = data.errors.get(str(self.directory), "") if self._source_dirs is None else ""
        self.list.setToolTip(self._load_error)
        if previous is not None and all(getattr(previous, name) == getattr(data, name)
                                        for name in ("entries", "layouts", "shortcuts", "info", "lightroom", "errors")):
            self.loaded.emit()
            return
        for path, info in data.info.items():
            remember_entry(path, *info)
        self.reload_pin_state(data.layouts.get(str(self.directory), {}))
        self._row_timer.stop()
        self._render_entries()
    def _layout_for(self, directory):
        if self._async_load:
            return self._loaded_data.layouts.get(str(directory), {}) if self._loaded_data else {}
        return load_layout_settings(directory)
    def _entries_for(self, directory, exclude=None):
        if self._async_load:
            paths = self._loaded_data.entries.get(str(directory), ())
            return [p for p in paths if p.name.lower() not in exclude] if exclude else paths
        return list_entries(directory, exclude)
    def _shortcuts_for(self, directory):
        if self._async_load:
            return self._loaded_data.shortcuts.get(str(directory), ())
        return load_shortcuts(directory)
    def refresh(self):
        if self._async_load:
            # Coalesce les demandes d'un même geste / rafraîchissement global.
            self._load_timer.start(0)
            return
        self._render_entries()
    def _render_entries(self):
        task = getattr(self, "_media_task", None)
        if task is not None:
            task.cancelled.set()
        current = self.current_path()
        self._selection_before_load = current
        self.list.blockSignals(True)
        self.list.clear()
        aliases: dict[str, str] = {}      # nom d'affichage des raccourcis (cle = chemin cible)
        if self._source_dirs is not None:
            # IN/OVER/OUT (voir __init__/PipelineBrowser.update_preview_
            # stack) : simple concatenation, dans l'ordre des sources
            # fournies (Projet puis Sous-projet) — pas de deduplication,
            # chaque source garde ses propres entrees meme en cas
            # d'homonymie. `label` (voir source_labels) : annotation
            # associee a CETTE source, reportee sur chacune de ses entrees.
            entries = []
            for i, source in enumerate(self._source_dirs):
                label = self._source_labels[i] if self._source_labels else None
                # Position de CETTE source dans la chaine (2 = Type, voir
                # ROLE_SOURCE_STEP) : PAS d'etiquette -> pas de palier non
                # plus (LOGICIELS, source_labels=None).
                step = (i + 2) if self._source_labels else None
                entries.extend((path, label, step, False) for path in self._entries_for(source))
                # Raccourcis propres a CHAQUE source (voir _add_shortcut, qui
                # enregistre dans la source choisie) : sinon un raccourci cree
                # depuis IN/OVER/OUT/LOGICIELS restait invisible.
                for shortcut in self._shortcuts_for(source):
                    target = Path(shortcut.get("target", ""))
                    if self._async_load or _shortcut_present(target):
                        entries.append((target, label, step, True))
                        if shortcut.get("name"):
                            aliases[str(target)] = str(shortcut["name"])
            # Ordre choisi a la main (voir save_item_order) : rangé dans la 1re source, sous une cle
            # propre a CETTE colonne (la meme source peut etre affichee ailleurs avec son propre ordre).
            store, key = self._order_store()
            order = self._layout_for(store).get(key) if store is not None else None
            if isinstance(order, list) and order:
                rank = {k: i for i, k in enumerate(order)}
                entries.sort(key=lambda e: rank.get(item_order_key(store, e[0]), len(rank)))
            if self._only_recognized_software:
                # Uniquement des REPERTOIRES DE LOGICIEL reconnus (voir
                # software_icon_key/app_style.custom_softwares) — pas de
                # fichier isole ni de dossier non reconnu qui trainerait
                # dans le dossier de travail — voir la remarque de
                # l'utilisateur, "dans la colonne logiciel, il ne doit y
                # avoir que des repertoires logiciel".
                entries = [
                    (path, label, step, is_shortcut) for path, label, step, is_shortcut in entries
                    if entry_is_dir(path) and software_icon_key(path.name) is not None
                ]
        else:
            # Colonnes REELLES (Type/Projets/Sous-projet/toute colonne "de
            # set" configuree, focus ou non) : in/over/out ne sont jamais
            # des lignes normales, ils deviennent des colonnes dediees (voir
            # IN/OVER/OUT ci-dessus, STATUS_FOLDERS) — INCONDITIONNEL (plus
            # seulement self.has_thumbnails) : voir la remarque de
            # l'utilisateur, "si a l'interieur des colonnes de set il y a
            # un repertoire in out ou over, il n'apparaisse pas dans la
            # colonne concernee".
            entries = [(path, None, None, False) for path in self._entries_for(self.directory, _STATUS_FOLDER_SET)]
            # Raccourcis (voir load_shortcuts/ROLE_IS_SHORTCUT, Column._on_
            # context_menu "Ajouter un raccourci") : fichiers et dossiers
            # d'AILLEURS sur le disque, affiches comme s'ils etaient
            # physiquement ICI —
            # propres a CE dossier (jamais pour une colonne du groupe IN/
            # OVER/OUT/LOGICIELS, source_dirs deja exclu par ce `else`) —
            # voir la remarque de l'utilisateur, "faire comme si il etait
            # au meme endroit que les autres repertoires de l'emplacement
            # actuel". Cible manquante (dossier deplace/supprime depuis) :
            # ignoree silencieusement, pas d'entree fantome.
            for shortcut in self._shortcuts_for(self.directory):
                target = Path(shortcut.get("target", ""))
                if self._async_load or _shortcut_present(target):
                    entries.append((target, None, None, True))
                    if shortcut.get("name"):
                        aliases[str(target)] = str(shortcut["name"])
            # Ordre choisi a la main (colonne Type, voir FileListWidget/save_item_order) ; tri
            # stable : une entree inconnue de l'ordre (nouveau dossier) garde son rang par defaut,
            # apres celles qui y sont.
            order = self._layout_for(self.directory).get("item_order")
            if isinstance(order, list) and order:
                rank = {key: i for i, key in enumerate(order)}
                entries.sort(key=lambda e: rank.get(item_order_key(self.directory, e[0]), len(rank)))
        # Filtres de contenu (voir __init__ show_dirs/show_files/omit_dirs/
        # omit_files, ColumnConfigDialog) : SEULEMENT pour un niveau de la
        # chaine CONFIGUREE — toute colonne NORMALE garde ses valeurs par
        # defaut (True/True/vide), donc ce bloc ne change RIEN pour elle
        # (le `if` court-circuite direct au cas commun, entries INCHANGE).
        if (not self._show_dirs or not self._show_files or self._omit_dirs or self._omit_files
                or GLOBAL_OMIT_DIR_NAMES or GLOBAL_OMIT_FILE_NAMES or GLOBAL_OMIT_FILE_EXTENSIONS):
            filtered = []
            for path, label, step, is_shortcut in entries:
                is_dir = entry_is_dir(path)
                if is_dir and not self._show_dirs:
                    continue
                if not is_dir and not self._show_files:
                    continue
                name_lower = path.name.lower()
                if is_dir and _is_globally_omitted_dir(path.name):
                    continue
                if is_dir and name_lower in self._omit_dirs:
                    continue
                if not is_dir and name_lower in self._omit_files:
                    continue
                if not is_dir and _is_globally_omitted_file(path.name):
                    continue
                filtered.append((path, label, step, is_shortcut))
            entries = filtered
        space_store, _key = self._order_store()
        spaces = self._item_spaces(space_store)
        spaces_below = self._item_spaces(space_store, below=True)
        titles = self._item_titles(space_store)
        # « Positionner au bas de la colonne » : ces lignes passent apres les autres (tri stable, leur
        # ordre entre elles est garde), puis sync_bottom_gap les colle en bas.
        bottom = self._item_bottom(space_store)
        self._rows_known_uniform = not bool(spaces or spaces_below or bottom)
        self._bottom_known_empty = not bottom
        # Les deux délégués ont maintenant une hauteur commune, images comprises.
        # Poser cette propriété AVANT l'insertion évite de recalculer les N
        # sizeHint à chaque tranche d'un gros dossier (156 797 appels / 5 000 lignes).
        self.list.setUniformItemSizes(not bool(spaces or spaces_below or bottom))
        if bottom:
            entries.sort(key=lambda e: item_order_key(space_store, e[0]) in bottom)
        self._media_counts_generation += 1
        media_generation = self._media_counts_generation
        media_folders = [path for path, _label, _step, _shortcut in entries if entry_is_dir(path)]
        def rows():
            for path, label, step, is_shortcut in entries:
                # Un raccourci peut porter un NOM D'AFFICHAGE (clic droit > Renommer le raccourci) : le
                # dossier cible garde le sien.
                item = QListWidgetItem(aliases.get(str(path)) if is_shortcut and str(path) in aliases else path.name)
                item.setData(ROLE_PATH, str(path))
                is_dir = entry_is_dir(path)
                item.setData(ROLE_ISDIR, is_dir)
                item.setData(ROLE_SOURCE_LABEL, label)
                item.setData(ROLE_SOURCE_STEP, step)
                item.setData(ROLE_IS_SHORTCUT, is_shortcut)
                item.setData(ROLE_LIGHTROOM_SHORTCUT,
                             bool(is_shortcut and (str(path) in self._loaded_data.lightroom if self._async_load
                                  else not is_remote_path(path) and (path / ".pipeline_lightroom.json").is_file())))
                item.setData(ROLE_MEDIA_COUNTS, None)
                if space_store is not None:
                    okey = item_order_key(space_store, path)
                    item.setData(ROLE_SPACE_ABOVE, int(spaces.get(okey, 0) or 0))
                    item.setData(ROLE_SPACE_BELOW, int(spaces_below.get(okey, 0) or 0))
                    title = titles.get(okey)
                    if isinstance(title, dict) and title.get("text"):
                        item.setData(ROLE_TITLE_ABOVE, title)
                    if okey in bottom:
                        item.setData(ROLE_PIN_BOTTOM, True)
                meta = ""
                if not is_dir:
                    size = entry_size(path)
                    if size is not None:
                        meta = human_size(size)
                elif self.has_thumbnails and not self._async_load and not is_remote_path(path):
                    # Réseau : pas de lecture de chaque sous-dossier pour « N éléments » (un aller-retour par ligne).
                    count = count_entries(path, _STATUS_FOLDER_SET)
                    meta = f"{count} element{'s' if count != 1 else ''}"
                item.setData(ROLE_META, meta)
                self.list.addItem(item)
                if current and path == current and self.current_path() is None:
                    self.list.setCurrentItem(item)
                yield
            self.list.blockSignals(False)
            self.sync_uniform_sizes()
            self.sync_bottom_gap()
            # Les lignes peintes à l'écran demandent leurs aperçus à la volée ;
            # amorcer quelques fichiers évite cependant un dossier vide au premier affichage.
            try:
                import lightroom_bridge
                lightroom_bridge.request_previews(path for path, _label, _step, _shortcut in entries)
            except (ImportError, OSError, ValueError):
                pass
            if media_folders:
                task = self._media_task = _MediaCountTask(media_generation, media_folders,
                                                         entry_counts=self.has_thumbnails and self._async_load)
                task.signals.finished.connect(self._apply_media_counts)
                _MEDIA_COUNT_POOL.start(task)

        self._row_iterator = rows()
        if self._async_load:
            self.loading = True
            self.list.blockSignals(False)
            self._advance_rows()
        else:
            for _ in self._row_iterator:
                pass
    def _advance_rows(self):
        started = time.perf_counter()
        self.list.blockSignals(True)
        try:
            while time.perf_counter() - started < 0.006:
                next(self._row_iterator)
        except StopIteration:
            self._row_iterator = None
            self.loading = False
            self._row_timer.stop()
            if self._selection_before_load is not None and self.current_path() is None:
                self.selected.emit(self, None)
            self.loaded.emit()
        finally:
            self.list.blockSignals(False)
        if self._row_iterator is not None:
            self._row_timer.start(0)
    def _apply_media_counts(self, generation: int, media_counts: dict):
        """Applique uniquement les résultats de la dernière actualisation."""
        if generation != self._media_counts_generation:
            return
        entries = {}
        if isinstance(media_counts, tuple):
            media_counts, entries = media_counts
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.data(ROLE_ISDIR):
                continue
            item.setData(ROLE_MEDIA_COUNTS, media_counts.get(str(item.data(ROLE_PATH))))
            count = entries.get(str(item.data(ROLE_PATH)))
            if count is not None:
                item.setData(ROLE_META, f"{count} element{'s' if count != 1 else ''}")
    def _order_store(self) -> tuple[Path | None, str]:
        """(dossier, cle) ou s'enregistre l'ordre choisi a la main : le dossier de la colonne
        (`item_order`) ; pour une colonne a plusieurs sources (IN/OVER/OUT, Logiciels), la 1re source,
        sous `item_order@<titre de la colonne>`."""
        if self._source_dirs is None:
            return self.directory, "item_order"
        if not self._source_dirs:
            return None, ""
        return Path(self._source_dirs[0]), f"item_order@{self.column_title}"
