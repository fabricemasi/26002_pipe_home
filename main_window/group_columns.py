"""Colonnes de groupe (Logiciels / IN / OVER / OUT) : sélection, largeur, hauteur, agrandir / égaliser, ordre.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QTimer

from browser_core import (
    GROUP_COLUMN_DEFAULT_HEIGHT, GROUP_COLUMN_MAX_HEIGHT, GROUP_COLUMN_MIN_HEIGHT, ROLE_SOURCE_LABEL, _WIDGET_SIZE_MAX,
    _hide_resize_width, _show_resize_width, _update_layout_setting, entry_is_dir,
)
from column import Column

from .helpers import _anim_running


class GroupColumnsMixin:
    """Méthodes de PipelineBrowser : colonnes de groupe (Logiciels / IN / OVER / OUT) : sélection, largeur, hauteur, agrandir / égaliser, ordre."""

    def _on_group_item_selected(self, column: Column, path: Path | None, kind: str) -> None:
        """Reagit a un clic sur une ligne du groupe IN/OVER/OUT/LOGICIELS
        (voir update_preview_stack) : un dossier ouvre son contenu dans une
        VRAIE colonne suivante (voir _open_group_folder) — navigation
        normale, pas l'explorateur Windows. Un fichier n'ouvre rien mais
        s'affiche dans l'inspecteur (Column.selected n'est pas branche sur
        on_selected pour ce groupe : c'est fait ici) ; double-clic l'ouvre
        via l'application par defaut (voir Column.activated/on_activated).
        `column` (colonne SOURCE, IN/OVER/OUT/LOGICIELS) : recupere
        l'etiquette d'origine (ROLE_SOURCE_LABEL) de la ligne cliquee sur
        SON item courant, pour l'ajouter entre parentheses a l'en-tete de
        la colonne ouverte — voir _open_group_folder/la remarque de
        l'utilisateur, "pour les titres dans les entetes de colonnes apres
        in over et out, j'aimerais ajouter aussi la mention entre
        parenthese"."""
        # Une SEULE selection de groupe a la fois : les 3 AUTRES groupes
        # n'ont plus rien a voir avec le point courant des qu'on clique
        # dans CELUI-CI — deselectionnes ENTIEREMENT (pas seulement rendus
        # "non focus"), sinon une vieille selection sans rapport (ex.
        # OVER > textures cliquee il y a longtemps) restait affichee
        # coloree indefiniment — voir la remarque de l'utilisateur, capture
        # a l'appui, "le repertoire textures est encore en selection alors
        # qu'il ne devrait pas du tout".
        if path is not None and not getattr(self, "_navigating_step", False):
            self._nav_plan = None
            pending = getattr(self, "_remote_selection", None)
            if pending is not None:
                from column_loading import loader
                loader().cancel(pending[0], self)
                self._remote_selection = None
        if path is not None:
            for other in self.group_columns:
                if other is not column:
                    other.list.clearSelection()
                    other.list.setCurrentItem(None)
        # Focus brillant : la ligne cliquee (dossier ou fichier) le garde tant
        # qu'aucune colonne ouverte plus loin n'a de selection (voir
        # update_active_column) ; il passe ensuite a cette colonne, et la ligne
        # redevient "chemin" (bleu FONCE) comme une colonne ancestrale.
        if path is not None:
            self._last_active_group_column = column
        self.update_active_column()
        if path is None:
            return
        # Inspecteur (apercu image/turntable, rendu manuel du menu contextuel) :
        # comme une colonne normale (voir _on_selected_now), la ligne cliquee,
        # dossier ou fichier, y est affichee.
        self.path_label.setText(str(path))
        self._request_crumbs()
        self.detail.show_path(path)
        if not entry_is_dir(path):
            # Un fichier n'ouvre rien : le contenu deja ouvert depuis ce groupe
            # (dossier clique avant) se ferme, comme apres un fichier d'une colonne normale.
            keep_index = self._chain_expected_total() - 1
            if len(self.columns) > keep_index + 1:
                pending = self._select_fade
                if _anim_running(pending):
                    pending.finish_now()
                fade = self._fade_before_select(self._group_stack_wrapper)
                self.prune_after(keep_index)
                self.update_active_column()
                self._slide_snapshot = None
                if fade is not None:
                    QTimer.singleShot(0, lambda: self._raise_select_fade(fade))
            return
        current_item = column.list.currentItem()
        source_label = current_item.data(ROLE_SOURCE_LABEL) if current_item is not None else None
        self._open_group_folder(path, source_label=source_label)

    def _open_group_folder(self, path: Path, title: str | None = None, source_label: str | None = None) -> None:
        """Ouvre `path` (indicateur in/over/out d'un _PreviewBlock, ou une
        ligne de dossier du groupe IN/OVER/OUT/LOGICIELS, voir
        update_preview_stack/_on_group_item_selected) dans une VRAIE
        colonne juste apres la FIN DE LA CHAINE REQUISE (voir
        _chain_expected_total, PAS le dernier niveau focus — meme raison
        que dans update_preview_stack, un niveau configure peut ne pas etre
        focus meme en derniere position) — jamais `Column_index`, une
        colonne arbitraire plus loin : ce groupe est TOUJOURS positionne
        juste apres la chaine, quoi que la navigation ait deja ouvert plus
        loin. STYLE toujours le bucket generique "Contenu" (comme toute
        colonne "au-dela de la chaine", voir on_selected/COLUMN_LABELS) —
        avant ce correctif, le nom du dossier lui-meme (en capitales)
        servait AUSSI de cle de style, creant une entree COLUMN_SETTINGS
        orpheline par nom de dossier different. En-tete AFFICHE, lui,
        dynamique (voir add_column/display_title) — le nom du dossier
        SELECTIONNE dans la colonne precedente (ici, la ligne cliquee dans
        IN/OVER/OUT/LOGICIELS) — voir la remarque de l'utilisateur, "le
        titre dans les colonnes apres focus doit aussi etre le nom du
        repertoire de la colonne precedente sauf les colonnes LOGICIELS IN
        OVER OUT" (ces 4-la restent des colonnes FANTOMES distinctes,
        jamais construites ici)."""
        insert_index = self._chain_expected_total() - 1
        # Contenu deja ouvert apres le groupe : il s'estompe (voir on_selected).
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        fade = self._fade_before_select(self._group_stack_wrapper)
        self.prune_after(insert_index)
        # "(<etiquette d'origine>)" (voir source_label/ROLE_SOURCE_LABEL) —
        # MEME texte que l'annotation de la ligne cliquee dans IN/OVER/OUT,
        # mais rendu ici dans la couleur STANDARD de l'en-tete (un seul
        # QLabel, une seule couleur) — voir la remarque de l'utilisateur,
        # "avec la couleur standard de texte pour l'entete" (PAS la couleur
        # dediee aux annotations de ligne).
        display_title = f"{path.name} ({source_label})" if source_label else path.name
        self.add_column(path, insert_index + 1, title=title or "Contenu", display_title=display_title)
        self.update_active_column()
        self.update_preview_stack()
        self._sync_collapse_state()
        self._slide_snapshot = None
        if len(self.columns) > insert_index + 1:
            QTimer.singleShot(0, lambda c=self.columns[insert_index + 1]: self._animate_column_in(c))
        if fade is not None:
            QTimer.singleShot(0, lambda: self._raise_select_fade(fade))

    def _on_group_column_resized(self, new_width: int) -> None:
        """Relais de Column.resize_update pour une colonne du groupe
        IN/OVER/OUT/LOGICIELS (voir Column.__init__ user_width/on_resize,
        MEME principe que PipelineBrowser._on_preview_column_resized) :
        conserve la largeur choisie a la main pour qu'elle survive a la
        PROCHAINE reconstruction du groupe (update_preview_stack, appelee a
        chaque navigation), ET la repercute TOUT DE SUITE sur les 3 AUTRES
        colonnes du groupe — voir la remarque de l'utilisateur, "les 4
        colonnes doivent avoir la meme largeur constamment"."""
        self._group_column_user_width = new_width
        for column in self.group_columns:
            # Une colonne pinnee suit aussi : la largeur du groupe est commune,
            # punaise ou non (sinon les autres reprenaient leur largeur a la
            # reconstruction suivante). Enregistree au relachement, voir
            # _on_group_column_resize_end.
            if column._pin_active:
                column._pin_column_width = new_width
            if column.width() != new_width:
                column._user_width = new_width
                column.setFixedWidth(new_width)

    def _on_group_column_resize_end(self) -> None:
        """Fin d'un glisser de largeur dans le groupe : enregistre la largeur
        commune dans le dossier de CHAQUE colonne pinnee du groupe."""
        for column in self.group_columns:
            if column._pin_active and column._pin_column_width:
                _update_layout_setting(column.directory, "pinned_column_width", column._pin_column_width)

    def _sync_group_widths(self) -> None:
        """Largeur COMMUNE aux colonnes du groupe IN/OVER/OUT/LOGICIELS apres
        leur (re)construction : la largeur figee de la premiere colonne pinnee
        (ordre courant) l'emporte, sinon la derniere largeur choisie a la main."""
        pinned = [c._pin_column_width for c in self.group_columns if c._pin_active and c._pin_column_width]
        width = pinned[0] if pinned else self._group_column_user_width
        if not width:
            return
        self._group_column_user_width = width
        for column in self.group_columns:
            column._user_width = width
            if column._pin_active:
                column._pin_column_width = width
            column.setFixedWidth(width)

    def _on_group_height_resize_begin(self, kind: str) -> None:
        """Debut d'un glisser du bord bas d'une colonne du groupe (voir
        Column.height_resize_begin) : identifie les 2 SEULES colonnes
        concernees — `kind` ET sa voisine IMMEDIATEMENT SUIVANTE dans
        l'ordre COURANT (voir group_columns, deja dans cet ordre) — et fige
        leurs 2 hauteurs de depart. Aucune 3e colonne n'est jamais
        impliquee — voir la remarque de l'utilisateur, "les deux colonnes
        concernees doivent etre seulement les deux colonnes de part et
        d'autre de la zone de selection pour le slide" (redemande apres
        une tentative de simplification "hauteur independante par colonne"
        qui avait par erreur remplace cette regle — voir _on_group_height_
        resize_end pour la persistance par dossier, elle INCHANGEE, seule
        la MECANIQUE du glisser lui-meme revient ici a la regle d'origine)."""
        columns = self.group_columns
        idx = next((i for i, c in enumerate(columns) if c._group_kind == kind), None)
        if idx is None or idx + 1 >= len(columns):
            self._group_height_drag = None
            return
        above, below = columns[idx], columns[idx + 1]
        self._group_height_drag = (above, below, above.height(), below.height())
        # Badge de mesure (voir _show_resize_width) SUR LES 2 colonnes
        # concernees, pas seulement celle dont le bord est glisse (voir
        # Column.height_resize_begin, qui affiche deja le sien avec la cle
        # par defaut) — voir la remarque de l'utilisateur, "je veux le
        # cadre de mesure de la hauteur pour les deux colonnes concernees
        # par le redimensionnement".
        _show_resize_width(below, below.height(), key="group_below")

    def _on_group_height_resized(self, kind: str, delta: int) -> None:
        """Relais de Column.height_resize_update (voir sa remarque de tete —
        transmet un DELTA brut, ne se redimensionne pas elle-meme) : reporte
        `delta` sur la colonne du dessus (grandit/retrecit) et applique
        l'INVERSE exact a sa voisine du dessous (retrecit/grandit d'autant)
        — la somme des 2 hauteurs reste CONSTANTE, donc AUCUNE autre colonne
        ne bouge, ni en taille ni en position (contrairement a une seule
        colonne redimensionnee dans son coin, qui aurait pousse tout ce qui
        suit vers le bas) — voir la remarque de l'utilisateur, "ne pas
        descendre l'ensemble des colonnes vers le bas". Voisine du dessous
        = colonne fill_height (la derniere, voir set_group_fill_height) :
        elle n'a pas de hauteur PROPRE a faire varier en retour, son
        minimumHeight (deja pose par set_group_fill_height) suffit a lui
        seul a borner `delta` via le layout — rien a lui appliquer ici."""
        drag = self._group_height_drag
        if drag is None:
            return
        above, below, start_above, start_below = drag
        if above._group_kind != kind:
            return
        new_above = max(GROUP_COLUMN_MIN_HEIGHT, min(GROUP_COLUMN_MAX_HEIGHT, start_above + delta))
        if not below._group_fill_height:
            # Le delta REELLEMENT applicable est borne par la place que
            # peut ceder la voisine (jusqu'a SON minimum) — au-dela, la
            # colonne du dessus s'arrete de grandir plutot que de pousser
            # la voisine sous son minimum.
            max_above = start_above + (start_below - GROUP_COLUMN_MIN_HEIGHT)
            new_above = min(new_above, max_above)
            new_below = start_above + start_below - new_above
            below._group_user_height = new_below
            below.setFixedHeight(new_below)
            self._group_column_user_heights[below._group_kind] = new_below
        above._group_user_height = new_above
        above.setFixedHeight(new_above)
        # Force la mise a jour REELLE des positions/tailles AVANT de lire
        # below.mapToGlobal(...) dans _show_resize_width juste apres (voir
        # sa remarque, ancre sur le coin de `below`) — voir la remarque de
        # l'utilisateur, "pourquoi lorsque l'on change la hauteur
        # l'indication de hauteur de la colonne du bas change de position
        # si on monte ou si on descend" : SANS ce activate() ICI (deja fait
        # pour la branche fill_height, mais PAS pour celle-ci), la position
        # de `below` lue par mapToGlobal restait celle d'AVANT que `above`
        # n'ait sa NOUVELLE hauteur (setFixedHeight, juste au-dessus, ne
        # reflue le layout QUE de facon DIFFEREE) — d'ou un badge qui
        # "sautait" d'une quantite differente selon le sens du glisser (le
        # decalage accumule dependait de l'historique des positions
        # PRECEDEMMENT lues, pas de la position REELLE courante).
        wrapper = self._group_stack_wrapper
        if wrapper is not None:
            wrapper.layout().activate()
        _show_resize_width(below, below.height(), key="group_below")
        self._group_column_user_heights[kind] = new_above

    def _on_group_height_resize_end(self) -> None:
        self._group_height_drag = None
        _hide_resize_width(self, key="group_below")
        # Persiste EN TEMPS REEL (voir load_layout_settings/
        # update_preview_stack, la remarque de l'utilisateur "doit etre
        # enregistre en temps reel") dans le dossier TERMINAL courant (voir
        # _chain_terminal_path) — chaque relachement de glisser ecrit
        # immediatement le dict COMPLET (les 2 colonnes concernees, voir
        # _on_group_height_resized) : la PROCHAINE fois que ce MEME dossier
        # sera navigue, ces hauteurs seront retrouvees telles quelles.
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_maximize(self, kind: str) -> None:
        """Bouton d'entete "⤢" (voir Column.__init__ on_group_maximize) :
        agrandit `kind` au maximum, reduit les 3 AUTRES colonnes du groupe
        a la hauteur necessaire pour montrer TOUT leur contenu sans scroll
        (voir Column.group_content_height_hint) — voir la remarque de
        l'utilisateur, "un bouton qui me permette d'agrandir au maximum la
        fenetre en cours et de minimiser les autres au maximum en fonction
        de leur contenu". `layout.setStretchFactor` (PAS de reconstruction,
        voir _reorder_group_columns_animated pour le meme principe) :
        seule `kind` recoit desormais le facteur d'etirement, quelle que
        soit sa position dans l'ordre COURANT (independant de `fill_
        height`/set_group_fill_height, normalement lie a la DERNIERE
        position — ce bouton doit fonctionner sur N'IMPORTE LAQUELLE)."""
        columns = self.group_columns
        target = next((c for c in columns if c._group_kind == kind), None)
        wrapper = self._group_stack_wrapper
        if target is None or wrapper is None:
            return
        layout = wrapper.layout()
        for c in columns:
            if c is target:
                continue
            content_h = c.group_content_height_hint()
            c._group_fill_height = False
            c.setMinimumHeight(0)
            c.setMaximumHeight(_WIDGET_SIZE_MAX)
            c.setFixedHeight(content_h)
            c._group_user_height = content_h
            self._group_column_user_heights[c._group_kind] = content_h
            layout.setStretchFactor(c, 0)
        target._group_fill_height = True
        target.setMinimumHeight(0)
        target.setMaximumHeight(_WIDGET_SIZE_MAX)
        layout.setStretchFactor(target, 1)
        self._group_column_user_heights.pop(kind, None)
        layout.activate()
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_equalize(self) -> None:
        """Bouton d'entete "≡" (voir Column.__init__ on_group_equalize) :
        repartit la hauteur TOTALE actuelle du groupe (deja exactement
        celle du conteneur, une colonne l'occupant TOUJOURS en entier —
        voir fill_height) a PARTS EGALES entre les 4 — voir la remarque de
        l'utilisateur, "je veux un autre bouton pour mettre les 4 colonnes
        a exactement la meme hauteur". Aucune des 4 ne garde le facteur
        d'etirement ensuite (`setStretchFactor(c, 0)` partout) : un
        redimensionnement MANUEL derriere resterait sans effet sur le
        conteneur sinon (les 4 sont desormais TOUTES a hauteur FIXE)."""
        columns = self.group_columns
        wrapper = self._group_stack_wrapper
        if not columns or wrapper is None:
            return
        layout = wrapper.layout()
        total = sum(c.height() for c in columns) or GROUP_COLUMN_DEFAULT_HEIGHT * len(columns)
        equal = max(GROUP_COLUMN_MIN_HEIGHT, total // len(columns))
        for c in columns:
            c._group_fill_height = False
            c.setMinimumHeight(0)
            c.setMaximumHeight(_WIDGET_SIZE_MAX)
            c.setFixedHeight(equal)
            c._group_user_height = equal
            self._group_column_user_heights[c._group_kind] = equal
            layout.setStretchFactor(c, 0)
        layout.activate()
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_reorder(self, source_kind: str, target_kind: str) -> None:
        """Reagit au depot de l'entete `source_kind` sur l'entete
        `target_kind` (voir Column.__init__ group_kind/on_reorder,
        eventFilter) : deplace `source_kind` juste devant `target_kind` dans
        _group_column_order, puis reordonne les colonnes EXISTANTES en
        animant leur glissement (voir _reorder_group_columns_animated) —
        voir la remarque de l'utilisateur, "possible de pouvoir glisser
        deposer ces colonnes afin de pouvoir interchanger leur place ?"."""
        if source_kind == target_kind or source_kind not in self._group_column_order:
            return
        order = self._group_column_order
        order.remove(source_kind)
        order.insert(order.index(target_kind), source_kind)
        self._reorder_group_columns_animated()

    def _reorder_group_columns_animated(self, duration: int = 220) -> None:
        """Reordonne les widgets DEJA CONSTRUITS du groupe IN/OVER/OUT/
        LOGICIELS (voir group_columns) selon le nouvel ordre de
        _group_column_order, SANS reconstruction (leur contenu ne change
        pas, seule leur place change) : chacune glisse de son ancienne
        position vers la nouvelle plutot que de sauter instantanement — voir
        la remarque de l'utilisateur, "j'aimerai egalement une animation des
        colonnes qui s'interchange lorsque l'on depose la colonne".

        removeWidget()+addWidget() (pas insertWidget a un index precis) :
        reordonne le layout ENTIER, dans l'ordre d'iteration de
        _group_column_order, en une passe — plus simple qu'un deplacement
        relatif d'UN SEUL item. Le role fill_height (voir Column.
        set_group_fill_height) suit aussi l'ordre : si la colonne qui
        devient DERNIERE change, celle qui l'etait perd sa place etiree
        (reprend une hauteur fixe) et la nouvelle derniere l'acquiert —
        voir la remarque de l'utilisateur, "il est important que la
        derniere colonne aille bien jusqu'en bas de la page". Anime la
        geometrie ENTIERE (pas seulement la position) : la colonne qui
        change de role fill_height change aussi de TAILLE, pas seulement de
        place. layout.activate() force le recalcul SYNCHRONE des geometries
        (sinon les nouvelles valeurs ne seraient connues qu'au prochain
        passage par la boucle d'evenements, une fois l'animation deja
        demarree sur les anciennes)."""
        wrapper = self._group_stack_wrapper
        if wrapper is None or not self.group_columns:
            self.update_preview_stack()
            return
        by_kind = {c._group_kind: c for c in self.group_columns}
        old_geometries = {c: c.geometry() for c in self.group_columns}
        layout = wrapper.layout()
        new_last_kind = self._group_column_order[-1] if self._group_column_order else None
        for kind in self._group_column_order:
            column = by_kind.get(kind)
            if column is None:
                continue
            layout.removeWidget(column)
            layout.addWidget(column, 1 if kind == new_last_kind else 0)
            column.set_group_fill_height(kind == new_last_kind)
        layout.activate()
        self.group_columns = [by_kind[k] for k in self._group_column_order if k in by_kind]

        if getattr(self, "_group_reorder_anim", None) is not None:
            self._group_reorder_anim.stop()
        group = QParallelAnimationGroup(self)
        for column, old_geom in old_geometries.items():
            new_geom = column.geometry()
            if new_geom == old_geom:
                continue
            column.setGeometry(old_geom)
            anim = QPropertyAnimation(column, b"geometry")
            anim.setDuration(duration)
            anim.setStartValue(old_geom)
            anim.setEndValue(new_geom)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)
        # Garder la reference : sans elle, le GC Python peut detruire le
        # groupe avant la fin de l'animation (meme piege que Column.
        # _animate_width).
        self._group_reorder_anim = group
        group.start()
