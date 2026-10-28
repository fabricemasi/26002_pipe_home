"""Cheminement de la barre de navigation : entrées, clics, dossier de la visionneuse.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import Qt

from fm_visionneuse import focus as _focus
import shiboken6


class CrumbsMixin:
    """Méthodes de PipelineBrowser : cheminement de la barre de navigation : entrées, clics, dossier de la visionneuse."""

    def _request_crumbs(self):
        timer = getattr(self, "_crumb_timer", None)
        if timer is not None:
            timer.start()

    def _refresh_crumbs(self):
        """Barre de navigation : le choix (nom) de chaque colonne, dans l'ordre, jusqu'au premier sans choix ;
        visionneuse ouverte : le dossier central puis l'image regardee (`_viewer_crumb_items`)."""
        if self._project_columns_hidden and self._viewer_folder is not None:
            self.titlebar.set_crumbs(self._viewer_crumb_items())
        else:
            self.titlebar.set_crumbs(self._crumb_items())

    def _viewer_crumb_items(self) -> list:
        """Cheminement de la visionneuse, calcule sur SON etat (jamais sur les colonnes cachees, qui ne suivent
        qu'au repos — le cheminement arrivait 700 ms et plus apres l'image, signale) : les reperes des colonnes
        jusqu'au DOSSIER CENTRAL (`_viewer_folder` : la visionneuse montre ses images, sous-dossiers compris en
        mode recursif), qui a le FOCUS, puis — genre « after_focus », l'image garde tout son cheminement — les
        sous-dossiers de l'image regardee et l'image. Clic sur un dossier = il devient le dossier central
        (`_set_viewer_folder`)."""
        folder = Path(self._viewer_folder)
        items, last = [], None
        for kind, path, _column in self._crumb_entries():
            if path != folder and path not in folder.parents:
                break
            items.append((kind, path.name or str(path), lambda _c=False, p=path: self._set_viewer_folder(p)))
            last = path
        if last != folder:
            # Dossiers entre le dernier repere des colonnes (ou la racine) et le dossier central.
            base = last if last is not None else Path(self.root_field.text())
            try:
                parts = folder.relative_to(base).parts
            except ValueError:
                base, parts = folder.parent, (folder.name,)
            for part in parts:
                base = base / part
                items.append(("after", part, lambda _c=False, p=base: self._set_viewer_folder(p)))
        if items:
            kind, name, callback = items[-1]
            items[-1] = (kind + "!", name, callback)             # le dossier central a le focus
        if self._focus_gallery is None and 0 <= self._viewer_index < len(self._viewer_paths):
            path = Path(self._viewer_paths[self._viewer_index])
            if self._pur_sources.get(str(path)) is not None:     # image d'une planche PureRef
                pur = self._pur_sources[str(path)][0]
                parts, shown = self._relative_parts(Path(pur).parent, folder), _focus.display_name(path)
            else:
                parts, shown = self._relative_parts(path.parent, folder), path.name
            base = folder
            for part in parts:
                base = base / part
                items.append(("after_focus", part, lambda _c=False, p=base: self._set_viewer_folder(p)))
            items.append(("after_focus", shown, lambda _c=False: None))
        return items

    @staticmethod
    def _relative_parts(path: Path, folder: Path) -> tuple:
        try:
            return Path(path).relative_to(folder).parts
        except ValueError:
            return ()

    def _set_viewer_folder(self, folder: Path):
        """Clic sur un dossier du cheminement, visionneuse ouverte : il devient le dossier CENTRAL — la
        visionneuse (pellicule, planche) montre ses images, celles des sous-dossiers aussi si « Récursif » est
        coche ; l'image regardee est gardee si elle y est encore, sinon la 1re."""
        folder = Path(folder)
        if not self._project_columns_hidden or self._viewer_folder is None:
            return
        if folder == Path(self._viewer_folder):
            return
        if self._recursive_on():
            self._start_filter_scan(folder)                      # liste a jour, lue en fond
        elif not self._viewer_folder_files(folder):
            self.path_label.setText(f"Aucune photo directement dans {folder.name} (cocher « Récursif » "
                                    "pour celles des sous-dossiers)")
            return
        self._viewer_folder = folder
        self._viewer_base = []                                   # liste refaite meme si identique
        self._apply_viewer_base()
        self.path_label.setText(str(folder))
        self._request_crumbs()

    def _crumb_entries(self) -> list:
        """[(genre, chemin, colonne)] : voir `_crumb_items`."""
        config = self._active_project_config
        settable = config is None or bool(config.get("set_enabled", True))
        total = self._chain_expected_total()
        entries = []

        def add(kind, column):
            path = column.current_path()
            if path is None:
                return False
            entries.append((kind, path, column))
            return True

        try:
            chain = self.columns[:total]
            for column in chain:
                if not add("set" if settable else "after", column):
                    return entries
            if len(chain) < total:
                return entries
            for column in self.group_columns:
                if add("after", column):
                    break
            for column in self.columns[total:]:
                if not add("after", column):
                    break
        except RuntimeError:
            pass
        return entries

    def _crumb_items(self) -> list:
        """[(genre, nom, rappel)] : le choix de chaque colonne de la chaine (genre « set », ou « after » quand le
        projet choisi n'a pas de set), puis le dossier choisi dans LOGICIELS / IN / OVER / OUT, puis les colonnes
        ouvertes a leur suite (« after »). Le dernier a le FOCUS (genre suffixe « ! ») ; les reperes du chemin
        parcouru AU-DELA de lui sont gardes (demande de l'utilisateur : l'image affichee garde tout son
        cheminement), genre « after_focus » — tant que le chemin actuel en est le debut (`_crumb_trail`). Un clic =
        focus sur l'element de sa colonne ; sur un repere apres le focus : les colonnes vont jusqu'a lui."""
        entries = self._crumb_entries()
        items = [(kind, path.name or str(path), lambda _c=False, col=column: self._crumb_clicked(col))
                 for kind, path, column in entries]
        paths = [path for _k, path, _c in entries]
        trail = getattr(self, "_crumb_trail", None) or []
        if len(trail) > len(paths) and [p for p, _n in trail[:len(paths)]] == paths:
            beyond = trail[len(paths):]                          # meme debut : le reste est garde
        else:
            beyond = []
            self._crumb_trail = [(path, path.name or str(path)) for path in paths]
        if items:
            kind, name, callback = items[-1]
            items[-1] = (kind + "!", name, callback)
        for path, name in beyond:
            items.append(("after_focus", name, lambda _c=False, p=path: self._crumb_go(p)))
        return items

    def _crumb_go(self, path: Path):
        """Clic sur un repere APRES le focus : les colonnes vont jusqu'a lui (il prend le focus)."""
        self._navigate_to(Path(path))
        column = next((c for c in reversed([*self.columns, *self.group_columns])
                       if shiboken6.isValid(c) and c.current_path() == Path(path)), None)
        if column is not None:
            column.list.setFocus(Qt.MouseFocusReason)
            self.update_active_column()

    def _crumb_clicked(self, column):
        """Clic sur un repere du cheminement = FOCUS sur lui (demande de l'utilisateur ; avant : defocus, comme un
        re-clic) : sa ligne reste selectionnee et devient la ligne en focus, les colonnes ouvertes apres elle se
        referment et son contenu est reaffiche (meme chemin qu'une selection, `reselect_current`)."""
        if not shiboken6.isValid(column) or column.current_path() is None:
            return
        column.reselect_current()
        if shiboken6.isValid(column):
            column.list.setFocus(Qt.MouseFocusReason)
            self.update_active_column()
