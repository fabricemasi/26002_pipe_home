"""Colonne active, chaîne de colonnes, pile d'aperçus (colonnes IN / OVER / OUT / LOGICIELS).

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app_style import PREVIEW_STACK_TITLE, column_gap, scaled, column_style_for
from browser_core import (
    DEFAULT_WORK_DIR_TYPE, STATUS_FOLDERS, WORK_DIR_TYPES, _named_subdir, load_layout_settings,
    project_thumbnail_pixmap, status_folder_state, _HoverPrime, entry_is_dir,
)
from column import Column, _FOCUS_LEVEL_LABEL
from preview_column import PreviewColumn
import shiboken6


class PreviewStackMixin:
    """Méthodes de PipelineBrowser : colonne active, chaîne de colonnes, pile d'aperçus (colonnes IN / OVER / OUT / LOGICIELS)."""

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        # Un clic dans une colonne du groupe IN/OVER/OUT/LOGICIELS (dossier OU
        # fichier) y laisse le focus brillant TANT QU'AUCUNE colonne ouverte
        # apres la chaine n'a de selection — comme une colonne normale, ou la
        # ligne cliquee reste en focus avant qu'on choisisse plus loin. Sans
        # ca, revenir cliquer un dossier du groupe donnait le focus a la
        # ligne de la colonne PRECEDENTE.
        group_focus = None
        group_column = self._last_active_group_column
        if group_column is not None and group_column.current_path() is not None:
            first_opened = self._chain_expected_total()
            if not any(c.current_path() is not None for c in self.columns[first_opened:]):
                group_focus = group_column
        for i, column in enumerate(self.columns):
            column.set_active(group_focus is None and i == last_selected)
        # Colonnes du groupe IN/OVER/OUT/LOGICIELS : UNE SEULE a la fois
        # doit apparaitre "focus" (voir _last_active_group_column, mis a
        # jour par _on_group_item_selected a CHAQUE clic sur l'une d'elles)
        # — pas les 4 independamment des qu'elles ont chacune une
        # selection (1ere version de ce correctif, revenue sur elle : voir
        # la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir").
        for column in self.group_columns:
            column.set_active(column is group_focus)

    def _chain_expected_total(self) -> int:
        """Nombre de colonnes REELLES requises pour que la chaine de
        navigation soit complete (Type + Projets + niveaux configures, voir
        load_project_columns/self._active_project_config) — 3 (Type,
        Projets, Sous-projet) si aucune config (chaine legacy). Utilise a
        la fois par update_preview_stack (position des vignettes/du groupe)
        et _open_group_folder (position ou du contenu ouvert depuis ce
        groupe doit s'inserer) — voir leurs remarques, "ancrer sur la FIN
        DE LA CHAINE REQUISE, pas sur le dernier niveau focus"."""
        active_config = self._active_project_config
        if active_config is None:
            return 3
        # Toggle "set" DESACTIVE (voir ColumnConfigDialog, la remarque de
        # l'utilisateur, "si il est a 0, le set ne se fait pas, et on passe
        # directement de la colonne projets a la colonne apres les
        # logiciels/in/out/over") : ignore les niveaux configures, comme
        # une chaine "base 2" (Type+Projets seuls).
        if not active_config.get("set_enabled", True):
            return 2
        return 2 + len(active_config["columns"])

    def _chain_terminal_path(self) -> Path | None:
        """Chemin actuellement selectionne dans la DERNIERE colonne requise
        de la chaine (voir _chain_expected_total) — None tant que la chaine
        n'est pas COMPLETEMENT settee jusqu'au repertoire de travail (soit
        pas assez de colonnes reelles encore ouvertes, soit rien de
        selectionne dans la derniere). self.columns[expected_total - 1]
        (position FIXE), PAS self.columns[-1] : une fois du contenu ouvert
        depuis le groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder),
        self.columns contient des colonnes SUPPLEMENTAIRES apres la chaine
        — voir update_preview_stack, meme remarque. Partagee par
        update_preview_stack (afficher ou non les vignettes/le groupe) ET
        _sync_collapse_state (repli automatique des colonnes de set, voir
        la remarque de l'utilisateur, "une fois que l'on est sur l'espace
        de travail")."""
        expected_total = self._chain_expected_total()
        if len(self.columns) < expected_total:
            return None
        path = self.columns[expected_total - 1].current_path()
        # Un FICHIER selectionne dans cette colonne ne "sette" PAS le
        # projet — seul un REPERTOIRE marque l'espace de travail atteint
        # (voir update_preview_stack/_sync_collapse_state/_on_group_
        # height_resize_end, tous les 3 appelants) — voir la remarque de
        # l'utilisateur, "les fichiers ne sont pas des elements de set".
        if path is not None and not entry_is_dir(path):
            return None
        return path

    def _chain_set_name(self) -> str | None:
        """Nom lisible du set complet, compose de tous les dossiers choisis
        dans la chaine, de la racine du pipeline jusqu'au terminal.

        Le dossier racine lui-meme n'est pas inclus : un set
        `PIPELINE/3d/_assets/airplane` devient donc
        « 3d - _assets - airplane ».
        """
        terminal = self._chain_terminal_path()
        if terminal is None:
            return None
        root = Path(self.root_field.text())
        try:
            parts = terminal.relative_to(root).parts
        except ValueError:
            # Repli pour un chemin qui ne serait plus sous la racine courante.
            parts = (terminal.name,)
        return " - ".join(part for part in parts if part)

    def _preview_style_snapshot(self) -> str:
        """Signature LEGERE de tout ce dont depend le RENDU (pas le
        contenu/la selection, jamais impactes par un simple reglage
        cosmetique) de update_preview_stack — les 3 styles resolus qu'elle
        utilise pour construire ses widgets (vignettes Focus, groupe IN/
        OVER/OUT au style "Contenu", groupe LOGICIELS) plus l'espacement
        entre colonnes. Comparee par refresh_all_columns(rescan=False,
        voir sa remarque) pour sauter une reconstruction complete —
        detruire/recreer jusqu'a 6 widgets et RE-SCANNER LE DISQUE
        (vignettes/in/over/out/logiciels) — quand AUCUNE de ces 4 valeurs
        n'a reellement change depuis le dernier rendu, plutot qu'a CHAQUE
        cran de glisser d'un slider quelconque de la fenetre de parametres,
        meme sans aucun rapport avec ces colonnes — voir la remarque de
        l'utilisateur, "gros ralentissements ... les manips sont donc tres
        lourdes". json.dumps (pas un simple tuple) : ces styles sont des
        dict (parfois imbriques, bordures/rayons par cote/coin), non
        hashables tels quels — sort_keys=True pour une representation
        STABLE (ordre d'iteration du dict sans importance)."""
        return json.dumps(
            [
                column_style_for(PREVIEW_STACK_TITLE),
                column_style_for("Contenu"),
                column_style_for("Logiciels"),
                column_gap(),
            ],
            sort_keys=True, default=str,
        )

    def update_preview_stack(self, if_changed: bool = False):
        """La pile (vignettes Focus, groupe IN/OVER/OUT/LOGICIELS) ne depend que de la CHAINE des dossiers
        selectionnes et de l'habillage : inchangee (selection d'un fichier, navigation dans le contenu ouvert
        APRES le groupe, a n'importe quelle profondeur), elle n'est ni reconstruite ni relue. Avant, chaque clic
        sur un dossier la refaisait : 2 colonnes Focus recreees et les 4 colonnes du groupe relues sur le disque
        (~65 ms par clic en local, 4 allers-retours de plus sur un partage reseau). `if_changed` : garde pour
        les appelants, meme comportement."""
        self._columns_epoch += 1
        self._prewarm_timer.start()
        key = self._preview_stack_key()
        if not (key == getattr(self, "_preview_stack_built", None) and self._preview_stack_in_place()):
            self._update_preview_stack_impl()
            self._preview_stack_built = key
        self._enforce_hidden_columns(final=True)

    def _preview_stack_key(self):
        """Ce dont depend la pile d'apercus : colonnes de la chaine (objet, dossier, selection), config du
        projet, habillage des colonnes Focus. Les colonnes ouvertes APRES la chaine n'y sont pas : elles
        s'ajoutent a la suite du groupe sans le deplacer (voir add_column)."""
        chain = self.columns[:self._chain_expected_total()]
        return (tuple((id(c), str(c.directory), str(c.current_path())) for c in chain),
                id(self._active_project_config), self._preview_style_snapshot())

    def _preview_stack_in_place(self) -> bool:
        """Conteneurs de la pile toujours vivants et poses dans la rangee des colonnes."""
        for wrapper in (getattr(self, "_preview_stack_wrapper", None), self._group_stack_wrapper):
            if wrapper is None:
                continue
            if not shiboken6.isValid(wrapper) or self.columns_layout.indexOf(wrapper) < 0:
                return False
        return True

    def _update_preview_stack_impl(self):
        """Recalcule l'apercu empile : un bloc par colonne a vignettes
        (Projets, Sous-projet) actuellement selectionnee, dans l'ordre de
        navigation, reparti sur DEUX emplacements juste apres la derniere
        colonne A VIGNETTES :

        1. Les vignettes (voir _PreviewBlock) : DEUX colonnes fantomes
           PERMANENTES SEPAREES (image_preview_columns), une par niveau
           selectionne (Projets, Sous-projet), empilees VERTICALEMENT dans
           un conteneur commun (voir _preview_stack_wrapper), reconstruites
           ici a chaque fois a la bonne position — il n'y a pas de
           "dossier" pour des images, donc jamais de vraie colonne a cet
           endroit. Les 2 partagent le MEME style (fond/bordure/rayon/
           entete), TOUJOURS celui de l'onglet "Focus" des reglages (voir
           PreviewColumn.display_title) — voir la remarque de
           l'utilisateur, "il doit y avoir deux colonnes, une focus projet
           et l'autre focus sous projet, je veux aucune autre entete ...
           les settings 'focus' doivent controler les deux colonnes".
        2. Le groupe IN/OVER/OUT/LOGICIELS (voir group_columns) : 4 VRAIES
           colonnes fantomes (liste cliquable/navigable comme n'importe
           quelle Column, pas un simple detail statique), empilees
           VERTICALEMENT juste apres les vignettes, RECONSTRUITES ici a
           chaque fois — remplace l'ancien detail "Fichiers pour X" +
           l'ancienne colonne reelle "Logiciels" (melangeant blocs de
           statut et liste de logiciels) — voir la remarque de
           l'utilisateur, "je veux creer 4 colonnes empilees les unes sur
           les autres : colonne IN, OVER, OUT et LOGICIEL". IN/OVER/OUT :
           contenu FUSIONNE du dossier correspondant du Projet ET du
           Sous-projet selectionnes (voir status_folder_state) — voir la
           remarque de l'utilisateur, "contenu de tous les dossiers des
           repertoires IN des sections projet et sous projets". LOGICIELS :
           SEUL le niveau le plus profond (Sous-projet si selectionne,
           sinon Projet), meme source que l'ancienne colonne reelle "Logi-
           ciels" (voir _softs_subdir) — voir la remarque de l'utilisateur,
           "identique au contenu actuel". Cliquer une ligne ouvre son
           contenu dans une VRAIE colonne juste apres le groupe (voir
           _open_group_folder), navigation normale comme partout ailleurs
           dans l'appli."""
        # Signature du RENDU en cours (voir _preview_style_snapshot/
        # refresh_all_columns) : mise a jour ICI, EN PREMIER, quel que soit
        # le chemin de sortie ci-dessous (chaine incomplete -> vide, ou
        # reconstruction complete) — reste ainsi TOUJOURS en phase avec ce
        # qui est REELLEMENT affiche, peu importe quel appelant a declenche
        # ce rendu (navigation normale, glisser-deposer, ou previsualisation
        # de reglages).
        self._last_preview_style_snapshot = self._preview_style_snapshot()
        self._clear_image_preview_columns()
        if not self.columns:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # Rien n'apparait (ni vignettes, ni groupe IN/OVER/OUT/LOGICIELS)
        # tant que la chaine n'est pas COMPLETEMENT settee jusqu'au
        # repertoire de travail (voir load_project_columns/on_selected,
        # expected_total = Type+Projets+niveaux configures) — voir la
        # remarque de l'utilisateur, "ne pas faire apparaitre les colonnes
        # focus tant que le set n'est pas fini jusqu'a l'espace de
        # travail". AVANT (pas seulement pour softs_dirs comme avant) :
        # deplace ici, calcule EN PREMIER, pour pouvoir couper court avant
        # meme de construire les vignettes — un focus PARTIEL (ex.
        # seulement "Projets" selectionne, avant tout choix dans "Sous-
        # projet") ne doit plus rien afficher du tout.
        active_config = self._active_project_config
        expected_total = self._chain_expected_total()
        # Toggles "focus"/"in_over_out" (voir ColumnConfigDialog, la
        # remarque de l'utilisateur, "si il est a 0, on n'affiche pas la
        # colonne focus"/"in over et out") — True par defaut (chaine legacy
        # OU champ absent d'une config plus ancienne). Toggle "logiciels"
        # SUPPRIME (voir la remarque de l'utilisateur, "supprime le toggle
        # logiciels") — la colonne LOGICIELS du groupe est desormais
        # TOUJOURS affichee, sans condition.
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        in_over_out_enabled = True if active_config is None else active_config.get("in_over_out_enabled", True)
        if active_config is None:
            work_dir_info = WORK_DIR_TYPES[DEFAULT_WORK_DIR_TYPE]
        else:
            work_dir_info = WORK_DIR_TYPES.get(
                active_config["work_dir"]["type"], WORK_DIR_TYPES[DEFAULT_WORK_DIR_TYPE])
        # _chain_terminal_path (voir sa remarque de tete) : PAS
        # self.columns[-1] — une fois du contenu ouvert depuis le groupe
        # IN/OVER/OUT/LOGICIELS (voir _open_group_folder), self.columns
        # contient des colonnes SUPPLEMENTAIRES apres la chaine, dont le
        # dernier ne represente plus le niveau REEL terminal.
        terminal_path = self._chain_terminal_path()
        if terminal_path is None:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # Hauteurs des colonnes du groupe IN/OVER/OUT/LOGICIELS PROPRES a
        # CE dossier terminal (voir load_layout_settings/
        # _on_group_height_resize_end) — remplace INTEGRALEMENT le dict en
        # memoire (jamais fusionne avec l'ancien contenu) : ce dict est
        # TOUJOURS synchronise avec le disque a la fin de chaque glisser
        # (_on_group_height_resize_end persiste immediatement, "temps
        # reel"), donc jamais de valeur "en attente" a preserver ici — voir
        # la remarque de l'utilisateur, "le dimensionnement en hauteur des
        # colonnes de focus doit etre enregistre en temps reel et ce
        # dependant du [sous-]dossier ... d'un sous dossier a l'autre, les
        # dimensionnements seront differents".
        raw_group_heights = load_layout_settings(terminal_path).get("group_heights")
        self._group_column_user_heights = {}
        if isinstance(raw_group_heights, dict):
            for kind, height in raw_group_heights.items():
                if isinstance(height, (int, float)):
                    self._group_column_user_heights[kind] = int(height)

        entries: list[tuple[str, QPixmap, Path, object, str, Column]] = []
        for column in self.columns if focus_enabled else ():
            if not column.is_focus_level:
                continue
            path = column.current_path()
            if path is None:
                continue
            open_status = lambda p: self._open_group_folder(p)
            # `column.column_title` (5e element, "Projets"/"Sous-projet") :
            # niveau REEL de ce bloc empile — voir _PreviewBlock/la remarque
            # de l'utilisateur, "ce n'est pas deux blocs empiles, mais deux
            # colonnes empilees" (chaque bloc doit reprendre l'entete REEL
            # de SA colonne, pas un entete generique commun aux deux).
            # `column` (6e element, la VRAIE Column source) : voir
            # _PreviewBlock._rename/set_preview_block, la remarque de
            # l'utilisateur, "je veux que le comportement des colonnes
            # fonctionne de la meme maniere sur tous les points" — permet
            # au bloc Focus de retrouver la VRAIE colonne dont il reprend
            # la selection, pour y appliquer un Renommer avec la MEME
            # resynchronisation de la navigation qu'une ligne normale
            # (voir Column._rename_item : renommer puis re-selectionner
            # l'item renomme retriggue on_selected/prune_after tout seul).
            entries.append((path.name, project_thumbnail_pixmap(path), path, open_status, column.column_title, column))

        if focus_enabled and not entries:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # 1. Vignettes : juste APRES LA FIN DE LA CHAINE REQUISE (Type +
        # Projets + niveaux configures, voir expected_total plus haut) —
        # PAS le dernier niveau FOCUS (un niveau configure peut avoir
        # focus=False, y compris le DERNIER juste avant le repertoire de
        # travail : dans ce cas le dernier focus-level est plus TOT dans la
        # chaine, et ancrer dessus inserait les vignettes/le groupe AU
        # MILIEU des colonnes reelles au lieu d'apres toutes — voir la
        # remarque de l'utilisateur, "si nous sommes en presence d'un
        # projet a 4 etapes avant set, les colonnes de focus devront etre a
        # la 5eme place"). PAS len(self.columns) non plus : cet indice peut
        # DEPASSER expected_total une fois du contenu ouvert depuis le
        # groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) — les
        # vignettes/le groupe doivent rester COLLES juste apres la chaine
        # requise, pas glisser plus loin derriere ce contenu deja ouvert.
        # A cet instant columns_layout contient exactement self.columns,
        # dans l'ordre : l'indice de colonne vaut l'indice de layout.
        anchor = expected_total - 1
        # Toggle "focus" DESACTIVE (voir ColumnConfigDialog, la remarque de
        # l'utilisateur, "si il est a 0, on n'affiche pas la colonne
        # focus") : aucune vignette construite, le groupe IN/OVER/OUT/
        # LOGICIELS vient alors s'inserer JUSTE apres la chaine (anchor+1)
        # au lieu de anchor+2 (pas de gap laisse par des vignettes
        # absentes).
        group_anchor_offset = 2
        if focus_enabled:
            # Conteneur vertical UNIQUE (voir _preview_stack_wrapper) : occupe
            # UNE SEULE place dans columns_layout (horizontal), mais empile ses
            # colonnes fantomes VERTICALEMENT en son sein — voir la remarque de
            # l'utilisateur, "deux colonnes separees, une en dessous de
            # l'autre". Espacement VERTICAL entre elles : meme reglage GENERAL
            # que "Distance entre colonnes" (column_gap), transpose a la
            # verticale — coherent avec l'espacement HORIZONTAL habituel entre
            # colonnes.
            wrapper = QWidget(self.columns_host)
            wrapper.setStyleSheet("background: transparent;")
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(scaled(max(0, column_gap()), 0))
            wrapper_layout.setAlignment(Qt.AlignTop)
            # EXACTEMENT une colonne par entree (Projets, Sous-projet), AUCUNE
            # autre entete (ni entete generique "Focus" a part, ni 3e colonne
            # vide) — texte d'entete "Focus <niveau>" (voir _FOCUS_LEVEL_LABEL),
            # mais STYLE (fond/bordure/rayon/police/padding/image/zone titre/
            # bouton repliement) TOUJOURS celui de PREVIEW_STACK_TITLE (l'onglet
            # "Focus" des reglages, PAS "Projets"/"Sous-projets") pour LES DEUX
            # — voir la remarque de l'utilisateur, "il doit y avoir deux
            # colonnes, une focus projet et l'autre focus sous projet, je veux
            # aucune autre entete. a savoir que les settings 'focus' doivent
            # controler les deux colonnes".
            for offset, (title, pixmap, path, open_status, level_title, source_column) in enumerate(entries):
                column = PreviewColumn(
                    PREVIEW_STACK_TITLE, parent=wrapper, on_toggle=None,
                    on_hide_columns=None,
                    on_gallery=None,     # plus de bouton image / planche (demande de l'utilisateur : touche G)
                    user_width=self._preview_column_user_width,
                    on_resize=self._on_preview_column_resized, fit_height=True,
                    display_title=_FOCUS_LEVEL_LABEL.get(level_title, PREVIEW_STACK_TITLE))
                if offset == 0:
                    column.on_buttons_placed = self._layout_viewer_buttons
                    column.set_toggle_state(self._project_columns_collapsed)
                    column.set_hide_state(self._project_columns_hidden)
                    column.set_gallery_state(self._focus_gallery is not None)
                    if column.toggle_btn is not None:
                        _HoverPrime(column.toggle_btn, self._prime_slide_snapshot)
                    if column.hide_btn is not None:
                        _HoverPrime(column.hide_btn, self._prime_fade_snapshot)
                wrapper_layout.addWidget(column)
                column.set_preview_block(title, pixmap, path, open_status, source_column)
                self.image_preview_columns.append(column)
            self._preview_stack_wrapper = wrapper
            self.columns_layout.insertWidget(anchor + 1, wrapper)
        else:
            group_anchor_offset = 1

        # 2. Groupe IN/OVER/OUT/LOGICIELS : insere JUSTE APRES LES VIGNETTES
        # (anchor + group_anchor_offset), PAS ajoute en fin (`addWidget`) — meme raison que
        # pour les vignettes ci-dessus : une colonne ouverte depuis une
        # PRECEDENTE navigation dans le groupe peut deja trainer en fin de
        # columns_layout (voir _open_group_folder) au moment ou ce groupe
        # est reconstruit, il doit malgre tout rester colle juste apres les
        # vignettes, pas relegue derriere.
        # IN/OVER/OUT : fusionne le contenu de CHAQUE colonne "de set"
        # actuellement selectionnee (Type + Projets + tout niveau
        # intermediaire configure, FOCUS ou non), pas seulement les niveaux
        # FOCUS (voir `entries` ci-dessus, qui reste lui limite aux
        # vignettes) — voir la remarque de l'utilisateur, "que si a
        # l'interieur des colonnes de set il y a un repertoire in out ou
        # over, son contenu doit se retrouver dans les colonnes
        # correspondantes". Borne a expected_total (pas self.columns en
        # entier) : au-dela, self.columns contient du contenu deja OUVERT
        # depuis le groupe IN/OVER/OUT/LOGICIELS lui-meme (voir
        # _open_group_folder) — jamais une source a refusionner ici.
        status_levels: list[Path] = []
        level_labels: list[str] = []
        for column in self.columns[:expected_total]:
            level_path = column.current_path()
            if level_path is None:
                continue
            status_levels.append(level_path)
            if column.column_title == "Projets":
                level_labels.append("projet")
            elif column.column_title == "Type":
                level_labels.append("Type")
            else:
                level_labels.append(level_path.name)
        levels = status_levels or [path for (_name, _pix, path, _open, _level, _col) in entries]
        # LOGICIELS/"Repertoire de travail" (voir add_group_column plus bas) :
        # `terminal_path`/`expected_total`/`work_dir_info` deja calcules et
        # verifies EN HAUT de la methode (voir la remarque de tete) — le
        # groupe n'est construit que lorsque la chaine est deja complete,
        # `terminal_path` est donc garanti non-None ici.
        softs_dirs = [_named_subdir(terminal_path, work_dir_info["folder_name"])]
        work_dir_display = (
            terminal_path.name if work_dir_info.get("display_from_selection")
            else work_dir_info["display"]
        )
        work_dir_style = work_dir_info["style_title"]
        work_dir_only_recognized_software = work_dir_info["only_recognized_software"]

        # Reconstruction EVITEE si le contexte de navigation n'a pas change
        # (meme dossier terminal, memes niveaux fusionnes, meme type de
        # repertoire de travail) — voir la remarque de tete de cette
        # methode et celle de l'utilisateur, "leur comportement ne
        # fonctionne pas du tout ... base toi sur les colonnes creees
        # avant les focus". AVANT ce correctif, les 4 colonnes etaient
        # DETRUITES ET RECONSTRUITES a CHAQUE appel de update_preview_stack
        # (a chaque selection, a chaque previsualisation de reglages en
        # direct) — exactement comme si Type/Projets/Sous-projet etaient
        # recrees a chaque clic — leur faisant perdre punaise/overrides de
        # menu contextuel/etat "actif" en permanence, et forçant un dict
        # separe (GROUP_ROW_HEIGHT, desormais supprime) pour simuler une
        # persistance qu'une VRAIE colonne stable obtient gratuitement.
        # `column.refresh()` (pas un no-op) : capte quand meme un
        # changement de CONTENU sur le disque (ex. refresh_all_columns
        # (rescan=True)) sans reconstruire les objets.
        # Toggle "in_over_out" DESACTIVE (voir ColumnConfigDialog, la
        # remarque de l'utilisateur, "si il est a 0, on n'affiche pas les
        # colonnes in over et out") : filtre localement,
        # self._group_column_order (ordre PERSISTE, voir _on_group_reorder)
        # reste INCHANGE pour retrouver la meme disposition une fois le
        # toggle reactive.
        active_group_order = list(self._group_column_order)
        if not in_over_out_enabled:
            active_group_order = [k for k in active_group_order if k not in ("in", "over", "out")]
        # `in_over_out_enabled` DANS la cle (pas seulement la longueur
        # comparee juste apres) : sans lui, basculer ce toggle SANS changer
        # de dossier terminal semblait "contexte inchange" et ne rejouait
        # que column.refresh() sur les colonnes DEJA existantes, sans
        # jamais ajouter/retirer les colonnes concernees.
        context_key = (terminal_path, tuple(levels), work_dir_style, in_over_out_enabled)
        if context_key == self._group_context_key and len(self.group_columns) == len(active_group_order):
            for column in self.group_columns:
                column.refresh()
            if self._group_stack_wrapper is not None:
                self.columns_layout.removeWidget(self._group_stack_wrapper)
                self.columns_layout.insertWidget(anchor + group_anchor_offset, self._group_stack_wrapper)
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.maximum())
            return

        self._clear_group_stack()
        self._group_context_key = context_key
        group_wrapper = QWidget(self.columns_host)
        group_wrapper.setStyleSheet("background: transparent;")
        group_layout = QVBoxLayout(group_wrapper)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(scaled(max(0, column_gap()), 0))
        # PAS de setAlignment(Qt.AlignTop) ici (contrairement a wrapper_
        # layout ci-dessus) : la DERNIERE colonne de l'ordre (voir
        # fill_height plus bas) porte un facteur d'etirement (stretch=1)
        # pour absorber tout l'espace restant jusqu'en bas de group_wrapper
        # — AlignTop l'en empecherait, en tassant les 4 colonnes en haut et
        # laissant un vide sous la derniere — voir la remarque de
        # l'utilisateur, "il est important que la derniere colonne aille
        # bien jusqu'en bas de la page".
        last_kind = active_group_order[-1] if active_group_order else None

        # Annotation "(projet)"/"(<nom de la colonne>)" (voir Column.
        # __init__ source_labels/ROLE_SOURCE_LABEL) : UNE par colonne "de
        # set" fusionnee, PARALLELE a `levels`/`level_labels` deja calcules
        # plus haut (voir leur remarque) — SEULEMENT pour IN/OVER/OUT (voir
        # add_group_column) : LOGICIELS n'a qu'UNE SEULE source (le niveau
        # le plus profond, voir softs_dirs), une annotation n'y aurait aucun
        # sens.

        def add_group_column(kind: str, display: str, source_dirs: list[Path], style_title: str,
                              source_labels: list[str] | None = None):
            fill = kind == last_kind
            # Identite de dossier STABLE (pas "source_dirs[0]", qui varie
            # selon la selection courante ET l'ordre des sources fusionnees)
            # : "in"/"over"/"out" pointent vers le dossier statut du niveau
            # le plus profond (deja l'une des sources fusionnees, jamais
            # synthetique), "logiciels" vers son unique source (softs_dirs,
            # deja stable) — voir la remarque de l'utilisateur, "base toi
            # sur les colonnes creees avant les focus" : necessaire pour que
            # la punaise/la hauteur de ligne/les overrides de menu
            # contextuel persistent correctement sur le MEME dossier d'une
            # navigation a l'autre, exactement comme une colonne normale.
            stable_directory = softs_dirs[0] if kind == "logiciels" else terminal_path / kind
            column = Column(
                stable_directory, style_title, parent=group_wrapper, async_load=True,
                source_dirs=source_dirs, source_labels=source_labels, display_title=display,
                user_width=self._group_column_user_width, on_resize=self._on_group_column_resized,
                on_resize_end=self._on_group_column_resize_end,
                group_kind=kind, on_reorder=self._on_group_reorder,
                user_height=self._group_column_user_heights.get(kind), on_height_resize=self._on_group_height_resized,
                on_height_resize_begin=self._on_group_height_resize_begin,
                on_height_resize_end=self._on_group_height_resize_end,
                fill_height=fill,
                only_recognized_software=(kind == "logiciels" and work_dir_only_recognized_software),
                on_group_maximize=self._on_group_maximize, on_group_equalize=self._on_group_equalize)
            column.selected.connect(lambda col, p, k=kind: self._on_group_item_selected(col, p, k))
            column.loaded.connect(self._column_loaded)
            column.activated.connect(self.on_activated)
            column.view_requested.connect(lambda path, c=column: self._view_in_viewer(path, c))
            column.folder_view_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c))
            column.folder_gallery_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c, True))
            column.recursive_requested.connect(self._set_recursive)
            group_layout.addWidget(column, 1 if fill else 0)
            self.group_columns.append(column)

        # Chaque groupe (kind -> libelle/sources/style/annotations) construit
        # une fois, puis ajoute dans l'ORDRE COURANT (voir
        # _group_column_order, LOGICIELS premiere par defaut, reordonnable
        # par glisser-deposer de l'entete — voir la remarque de
        # l'utilisateur, "la colonne logiciel doit etre en premiere position
        # en haut ... possible de pouvoir glisser deposer ces colonnes afin
        # de pouvoir interchanger leur place ?").
        groups = {
            "logiciels": (work_dir_display, softs_dirs, work_dir_style, None),
        }
        for status_name in STATUS_FOLDERS:
            source_dirs = [status_folder_state(level, status_name)[1] for level in levels]
            # style_title = "IN"/"OVER"/"OUT" (PLUS "Contenu" partage) :
            # onglet de surcharge DEDIE desormais disponible pour chacune
            # (voir SettingsWindow._build_columns_page, la remarque de
            # l'utilisateur, "ajoute ... in over et out"). Le contenu
            # ouvert AU-DELA (voir _open_group_folder/on_selected, clic
            # sur une ligne DE ce groupe) reste lui sur le bucket generique
            # "Contenu", INCHANGE — seule la ligne DU groupe elle-meme
            # devient independamment stylable.
            groups[status_name] = (status_name.upper(), source_dirs, status_name.upper(), level_labels)
        for kind in active_group_order:
            display, source_dirs, style_title, source_labels = groups[kind]
            add_group_column(kind, display, source_dirs, style_title, source_labels)
        self._sync_group_widths()

        self._group_stack_wrapper = group_wrapper
        self.columns_layout.insertWidget(anchor + group_anchor_offset, group_wrapper)

        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())
