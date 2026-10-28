"""Colonnes : rechargement, ajout, boutons des logiciels, rafraîchissement de toutes les colonnes.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from config import COLUMN_LABELS
from browser_core import col_width, entry_is_dir
from column import Column
import previews as _previews
import software_launch
import shiboken6


class ColumnsMixin:
    """Méthodes de PipelineBrowser : colonnes : rechargement, ajout, boutons des logiciels, rafraîchissement de toutes les colonnes."""

    # -- gestion des colonnes ------------------------------------------

    def reload(self):
        import browser_core
        browser_core.forget_all_config()     # F5 : relecture réelle, même cache encore frais
        self._nav_plan = None
        pending = getattr(self, "_remote_selection", None)
        if pending is not None:
            from column_loading import loader
            loader().cancel(pending[0], self)
            self._remote_selection = None
        root = Path(self.root_field.text())
        self.prune_after(-1)
        self.detail.clear()
        if not _previews.is_remote_path(root) and not root.is_dir():
            self.path_label.setText(f"Introuvable : {root}")
            return
        self._project_columns_collapsed = False
        self._project_columns_hidden = False
        self._sync_viewer_chrome()
        self._auto_collapse_armed = True
        self.add_column(root, 0)
        self.path_label.setText(str(root))
        self._request_crumbs()
        self.update_preview_stack()
        self._sync_collapse_state()

    def _detach_group_stack(self):
        """Retire le groupe fantome de columns_layout SANS le detruire
        (voir add_column) — contrairement a _clear_group_stack, garde
        `self.group_columns`/`self._group_context_key` intacts : le
        prochain update_preview_stack (toujours appele juste apres, voir
        add_column) le REINSERE tel quel si le contexte de navigation n'a
        pas change, ou le detruira lui-meme via _clear_group_stack si
        besoin d'une reconstruction complete."""
        if self._group_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._group_stack_wrapper)

    def _clear_group_stack(self):
        for column in self.group_columns:
            if hasattr(column, "cancel_loading"):
                column.cancel_loading()
        wrapper = self._group_stack_wrapper
        if wrapper is not None:
            # Remis a None AVANT setParent(None) : le focus qui quitte le conteneur
            # peut relancer une navigation (reentrante) qui repasse par ici.
            self._group_stack_wrapper = None
            self.columns_layout.removeWidget(wrapper)
            wrapper.setParent(None)
            wrapper.deleteLater()
        self.group_columns = []
        self._group_context_key = None
        self._last_active_group_column = None

    def _clear_image_preview_columns(self):
        wrapper = self._preview_stack_wrapper
        if wrapper is not None:
            # Remis a None AVANT setParent(None) : le focus qui quitte le conteneur
            # peut relancer une navigation (reentrante) qui repasse par ici.
            self._preview_stack_wrapper = None
            self.columns_layout.removeWidget(wrapper)
            wrapper.setParent(None)
            wrapper.deleteLater()
        self.image_preview_columns = []

    def add_column(self, directory: Path, depth: int, title: str | None = None,
                   is_focus_level: bool | None = None,
                   show_dirs: bool = True, show_files: bool = True,
                   omit_dirs: frozenset = frozenset(), omit_files: frozenset = frozenset(),
                   style_title: str | None = None, display_title: str | None = None):
        # `title` : impose un intitule (voir _open_group_folder, qui ouvre
        # un dossier in/over/out/logiciel sans rapport avec ce que la profondeur
        # suggererait normalement — pas question d'afficher "SOUS-PROJET" au
        # dessus du contenu de "in"). None (cas normal) : intitule deduit de
        # la profondeur, comme avant. `is_focus_level`/`show_dirs`/`show_files`/
        # `omit_dirs`/`omit_files` (voir Column.__init__, on_selected) :
        # SEULEMENT fournis pour un niveau de la chaine CONFIGUREE (voir
        # load_project_columns) — valeurs par defaut = comportement INCHANGE
        # pour tout le reste (Type/Sous-projet legacy/Logiciels/Contenu).
        # `style_title` (voir Column.style_title/on_selected) : cle de STYLE
        # SEPAREE du nom affiche — utilisee pour qu'un niveau de chaine
        # CONFIGUREE (nom quelconque, ex. "test1") suive quand meme le
        # reglage General > Colonnes > INTERMEDIAIRE (voir la remarque de
        # l'utilisateur, "doit controler toutes les colonnes entre celle de
        # projet et focus"). None (repli, comportement INCHANGE) : style_title
        # = title, comme avant ce reglage.
        normal_navigation = title is None
        if title is None:
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        if display_title is None and normal_navigation and depth > 1:
            # En-tete DYNAMIQUE pour toute colonne "de set" APRES Type ET
            # Projets (Type garde son titre fixe, aucune colonne
            # PRECEDENTE dont reprendre le nom ; "Projets" doit lui
            # TOUJOURS s'appeler ainsi — voir la remarque de l'utilisateur,
            # "la deuxieme colonne doit toujours s'appeler PROJETS", une
            # correction de la demande initiale "dans les colonnes de set
            # le nom des colonnes correspond au nom du repertoire
            # selectionne") : `directory` EST precisement le dossier
            # SELECTIONNE dans la colonne precedente (celui dont cette
            # nouvelle colonne liste le contenu). Seulement en navigation
            # NORMALE (`title` deja None avant l'affectation ci-dessus) :
            # PAS pour _open_group_folder, qui fixe deja lui-meme son
            # propre display_title (voir sa remarque).
            display_title = directory.name
        column = Column(
            directory, title, parent=self.columns_host, is_focus_level=is_focus_level, style_title=style_title, async_load=True,
            display_title=display_title,
            show_dirs=show_dirs, show_files=show_files, omit_dirs=omit_dirs, omit_files=omit_files)
        column.selected.connect(self.on_selected)
        column.loaded.connect(self._column_loaded)
        column.activated.connect(self.on_activated)
        column.view_requested.connect(lambda path, c=column: self._view_in_viewer(path, c))
        column.folder_view_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c))
        column.folder_gallery_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c, True))
        column.recursive_requested.connect(self._set_recursive)
        beyond_chain = len(self.columns) >= self._chain_expected_total()
        self.columns.append(column)
        # Le groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
        # stack) peut occuper cet emplacement depuis la selection
        # precedente : le RETIRER (pas le DETRUIRE, voir _detach_group_
        # stack) avant d'ajouter la vraie colonne, sinon celle-ci se
        # retrouverait ajoutee APRES lui dans columns_layout (ordre visuel
        # casse). image_preview_column, elle, n'est PAS retiree ici : c'est
        # une colonne permanente qui doit rester juste avant celle qu'on
        # ajoute (voir update_preview_stack, qui la reconstruit a la bonne
        # position a chaque appel). update_preview_stack (appele juste
        # apres, a la fin de on_selected/_open_group_folder) le REINSERE
        # a la bonne position SANS le reconstruire si le contexte de
        # navigation n'a pas change (voir sa remarque, la remarque de
        # l'utilisateur "base toi sur les colonnes creees avant les
        # focus") — un _clear_group_stack() (destructeur) ici aurait
        # recree les 4 colonnes a CHAQUE _open_group_folder, y compris pour
        # une simple creation de dossier qui re-selectionne l'element cree.
        if not (beyond_chain and self._group_stack_wrapper is not None
                and self.columns_layout.indexOf(self._group_stack_wrapper) >= 0):
            self._detach_group_stack()
        # Contenu ouvert APRES la chaine : il se pose a la suite du groupe, deja a sa place (pas de retrait :
        # la pile n'est alors plus refaite, voir update_preview_stack).
        self.columns_layout.addWidget(column)
        # _suppress_left() (voir Column._containing_layout) a besoin que la
        # colonne soit DEJA dans columns_layout pour detecter correctement
        # sa voisine de gauche — au moment de Column.__init__ (donc de son
        # 1er refresh_header()/refresh_colors(), voir plus haut), elle n'a
        # encore AUCUN parent, _suppress_left() y renvoie donc TOUJOURS
        # False, figeant a tort un padding/bordure gauche PLEIN (jamais
        # supprime) pour toute colonne qui n'est pourtant PAS la premiere
        # de la rangee — voir la remarque de l'utilisateur, "la distance
        # entre deux colonnes est toujours deux fois plus grande que la
        # valeur du padding" : rejouer les 2 ICI, une fois REELLEMENT
        # inseree, recalcule enfin la bonne valeur.
        column.refresh_header()
        column.refresh_colors()
        self.update_active_column()
        self._sync_software_buttons()
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _sync_software_buttons(self) -> None:
        """Dans un set, un logiciel choisi dans la colonne LOGICIELS (dossier reconnu, ex. « blender ») qui a
        un lanceur (`software_launch.LAUNCHERS`, Blender seulement pour l'instant) : TOUTES les colonnes
        ouvertes sous son dossier ont, a cote de leur punaise, un bouton a son icone qui l'ouvre dans LEUR
        dossier (« Enregistrer sous » y est deja) — demande de l'utilisateur. Les autres colonnes n'en ont pas."""
        software = None
        for group_column in self.group_columns:
            if getattr(group_column, "_group_kind", None) != "logiciels" or not shiboken6.isValid(group_column):
                continue
            selected = group_column.current_path()
            if selected is not None and entry_is_dir(selected):
                key = _previews.software_icon_key(selected.name)
                if software_launch.can_launch(key):
                    software = (key, selected)
        # Nom COMPLET du SET (tous les dossiers de la chaine, de la racine au
        # terminal) : nom du favori ajoute dans le logiciel (demande de
        # l'utilisateur), par exemple « 3d - _assets - airplane ».
        set_name = self._chain_set_name() if software is not None else None
        for column in self.columns:
            if not shiboken6.isValid(column):
                continue
            directory = column.directory
            if software is not None and (directory == software[1] or software[1] in directory.parents):
                column.set_launcher(software[0], lambda k=software[0], d=directory, n=set_name:
                                    self._launch_software(k, d, n))
            else:
                column.set_launcher(None)

    def _launch_software(self, key: str, folder: Path, set_name: str | None = None) -> None:
        """Bouton logiciel d'une colonne (voir _sync_software_buttons) : le logiciel s'ouvre dans `folder`
        (favori de sa fenetre de fichiers au nom du set)."""
        if not software_launch.launch(key, folder, set_name):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Logiciel introuvable",
                                f"Impossible de lancer {key.capitalize()} (installation introuvable).")

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            column.cancel_loading()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()
        self._request_crumbs()

    def refresh_all_columns(self, rescan: bool = True, relayout_titles: set | None = None):
        """Reapplique aux colonnes existantes (largeur, delegate, polices)
        les reglages globaux courants, SANS reconstruire l'arborescence : la
        navigation en cours (profondeur, selection) reste intacte. Utilise
        par le glisser-deposer (rescan=True : le contenu du dossier a change
        sur le disque), et par la previsualisation en direct des parametres
        (voir _apply_settings, rescan=False : aucun reglage cosmetique
        (police, largeur, hauteur de ligne...) ne change le contenu d'un
        dossier — retourner sur le disque, y compris le comptage recursif
        des colonnes a vignettes, a chaque cran de slider n'apporterait
        rien et coute cher sur un partage reseau).

        `relayout_titles` (uniquement pertinent avec rescan=False, voir
        _apply_settings) : titres de colonne dont col_row_height()/
        col_spacing() ont REELLEMENT change depuis le dernier appel — les
        AUTRES colonnes sautent le doItemsLayout() de Column.relayout()
        (voir sa docstring), puisqu'un cran de slider qui ne touche qu'a une
        couleur/bordure/rayon n'a aucune raison de recalculer le sizeHint()
        de CHAQUE ligne — None (comportement par defaut, tous les autres
        appelants) relayoute TOUJOURS tout, sans cette optimisation — voir
        la remarque de l'utilisateur, "il y a des ralentissements dans les
        animations, optimise un maximum"."""
        for column in self.columns:
            # Une colonne repliee (voir Column.set_collapsed) garde une
            # largeur nulle : col_width(...) est la largeur DEPLOYEE, la
            # reappliquer ici la ferait rebondir a pleine largeur a chaque
            # glisser-deposer/reglage sans que column.collapsed n'ait change.
            # Largeur choisie a la main (voir Column._user_width) prioritaire
            # sur col_width(...) : sinon repasser sur N'IMPORTE quel reglage
            # (y compris Colonnes > Padding/Bordure, rejoue a chaque cran de
            # slider pour la previsualisation en direct) ecrasait aussitot
            # tout redimensionnement manuel par la largeur par defaut.
            if not column.collapsed:
                # _pin_column_width (voir Column._toggle_pin) EN PREMIER :
                # sans lui, tout changement de reglage (n'importe quel
                # champ de la fenetre de parametres, voir _apply_settings)
                # ecrasait aussitot la largeur FIGEE d'une colonne pinnee —
                # voir la remarque de l'utilisateur, "quand on fait une
                # modif dans les settings, ca annule toutes les valeurs
                # des colonnes qui sont pinnees".
                column.setFixedWidth(
                    column._pin_column_width or column._user_width or col_width(column.style_title))
            else:
                column.setFixedWidth(0)
            column.refresh_header()
            column.sync_uniform_sizes()            # pas uniforme si une ligne a un espace au-dessus
            delegate = column.list.itemDelegate()
            if hasattr(delegate, "refresh_fonts"):
                delegate.refresh_fonts()
            if rescan:
                column.refresh()
                # doItemsLayout() supplementaire : refresh() ci-dessus vide
                # puis repeuple la liste (clear()+addItem() par entree), sans
                # jamais rejouer explicitement la mise en page finale — voir
                # relayout() juste en dessous, qui elle le fait DEJA (pas de
                # doItemsLayout() double dans ce cas, voir la remarque de
                # l'utilisateur, "il y a des ralentissements dans les
                # animations, optimise un maximum" : ce 2e appel tournait
                # inutilement a CHAQUE cran de slider pendant la
                # previsualisation en direct, voir rescan=False plus bas).
                column.list.doItemsLayout()
            else:
                do_layout = relayout_titles is None or column.style_title in relayout_titles
                column.relayout(do_layout=do_layout)
        if rescan:
            self.update_preview_stack()
        else:
            # Gate (voir _preview_style_snapshot/la remarque de tete de
            # cette methode) : SEULEMENT pour la previsualisation en direct
            # des parametres (rescan=False, seul appelant de cette
            # branche) — sauter la reconstruction complete du groupe IN/
            # OVER/OUT/LOGICIELS/des vignettes Focus (destruction/recreation
            # de jusqu'a 6 widgets + RE-SCAN DU DISQUE) quand rien de ce
            # qu'elle utilise n'a change depuis le dernier rendu, au lieu de
            # la rejouer a CHAQUE cran de glisser de N'IMPORTE quel slider
            # de la fenetre de parametres — voir la remarque de
            # l'utilisateur, "gros ralentissements ... les manips sont donc
            # tres lourdes".
            snapshot = self._preview_style_snapshot()
            if snapshot != self._last_preview_style_snapshot:
                self.update_preview_stack()
