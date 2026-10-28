"""Sélection dans une colonne : navigation, fondus, animation d'apparition, état replié.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QTimer

from app_style import auto_collapse_set_columns
from config import COLUMN_LABELS, SOFTWARE_COLUMN_LABEL
from browser_core import STATUS_FOLDERS, _named_subdir, load_project_columns, _FadeOverlay, _SlideOverlay, entry_is_dir
from column import Column
import previews as _previews
import shiboken6

from .helpers import _anim_running


class SelectionMixin:
    """Méthodes de PipelineBrowser : sélection dans une colonne : navigation, fondus, animation d'apparition, état replié."""

    def on_selected(self, column: Column, path: Path | None):
        """Si des colonnes sont deja deployees apres `column`, elles s'estompent
        toutes ensemble pendant que la navigation s'applique
        et que la nouvelle colonne sort de dessous."""
        if column not in self.columns:
            # Colonne deja retiree (signal emis pendant sa destruction, ou focus
            # passe a une liste pendant une reconstruction) : rien a naviguer.
            return
        if not getattr(self, "_navigating_step", False):
            self._nav_plan = None
        previous = getattr(self, "_remote_selection", None)
        if previous is not None:
            from column_loading import loader
            loader().cancel(previous[0], self)
            self._remote_selection = None
        if path is not None and _previews.is_remote_path(path) and entry_is_dir(path):
            from column_loading import loader
            service = loader()
            if not getattr(self, "_remote_selection_connected", False):
                service.ready.connect(self._navigation_data_ready)
                self._remote_selection_connected = True
            excluded = frozenset(STATUS_FOLDERS)
            key = service.key([path], excluded)
            cached = service.cached(key)
            if cached is None:
                self._remote_selection = (key, column, path)
                self.path_label.setText(str(path))
                self._request_crumbs()
                service.request(key, [path], excluded, self)
                return
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        overlay = None if self._bulk_navigation else self._fade_before_select(column)
        self._on_selected_now(column, path)
        if overlay is not None:
            # Au-dessus de l'apparition (creee en differe par _on_selected_now) : l'ancien
            # contenu s'estompe PENDANT que la nouvelle colonne sort de dessous.
            QTimer.singleShot(0, lambda: self._raise_select_fade(overlay))

    def _navigation_data_ready(self, key, data, error):
        pending = getattr(self, "_remote_selection", None)
        if pending is None or pending[0] != key:
            return
        self._remote_selection = None
        from column_loading import loader
        loader().cancel(key, self)
        _, column, path = pending
        if column not in self.columns or column.current_path() != path:
            return
        if data is None or data.errors.get(str(path)):
            error = error or data.errors.get(str(path), "")
            self.path_label.setText(f"{path} — {error}")
            self._nav_plan = None
            return
        self._navigating_step = bool(getattr(self, "_nav_plan", None))
        try:
            self.on_selected(column, path)
        finally:
            self._navigating_step = False
        self._resume_path_navigation()

    def _column_loaded(self):
        """Métadonnées de l'inspecteur reprises du scan ; jamais un second scan GUI."""
        path = getattr(self.detail, "_current_path", None)
        if path:
            self.detail._fill_folder_count(path, scan=False)
        if getattr(self, "_nav_plan", None):
            QTimer.singleShot(0, self._resume_path_navigation)

    def on_reclicked(self, column: Column):
        """Clic sur la ligne DEJA selectionnee de `column` (voir FileListWidget.mouseReleaseEvent) :
        elle est deselectionnee (la colonne perd son focus) et TOUTES les colonnes ouvertes apres elle
        se referment, en fondu ; l'inspecteur se vide. Colonne normale : meme chemin qu'une selection
        vide (on_selected avec None). Colonne du groupe IN/OVER/OUT/LOGICIELS : le contenu ouvert
        depuis elle se ferme, le groupe reste."""
        if column.current_path() is None:
            return
        if column in self.columns:
            column.list.clearSelection()
            column.list.setCurrentItem(None)        # -> on_selected(column, None) : fondu + fermeture
            return
        if column not in self.group_columns:
            return
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        keep_index = self._chain_expected_total() - 1
        fade = self._fade_before_select(self._group_stack_wrapper) if len(self.columns) > keep_index + 1 else None
        self.prune_after(keep_index)
        column.list.blockSignals(True)
        column.list.clearSelection()
        column.list.setCurrentItem(None)
        column.list.blockSignals(False)
        column.list.viewport().update()
        self._last_active_group_column = None
        self.detail.clear()
        self.update_active_column()
        self._sync_collapse_state()
        self._slide_snapshot = None
        if fade is not None:
            QTimer.singleShot(0, lambda: self._raise_select_fade(fade))

    def _raise_select_fade(self, overlay):
        try:
            if _anim_running(overlay):
                overlay.raise_()
        except RuntimeError:
            pass

    def _fade_before_select(self, column):
        """`column` : widget apres lequel le contenu deja ouvert s'estompe (une colonne,
        ou le bloc IN/OVER/OUT/LOGICIELS)."""
        try:
            if (column is None or not self.isVisible() or self._project_columns_hidden
                    or _anim_running(self._columns_fade)):
                return None
            if _anim_running(self._columns_slide):
                # Clic pendant un glissement (apparition de la colonne precedente,
                # repli auto...) : on le termine (etat final pose) puis on capture.
                # L'abandonner faisait disparaitre l'ancien contenu sans fondu.
                self._columns_slide.finish_now()
            self.columns_layout.activate()
            rect = self._columns_visible_rect()
            viewport = self.scroll.viewport()
            if rect.isEmpty() or not column.isVisible():
                return None
            column_right = column.mapTo(viewport, QPoint(0, 0)).x() - rect.x() + column.width()
            spans = [span for span in self._column_spans(rect) if span[0] >= column_right]
            if not spans:
                return None
            x0 = spans[0][0]
            target = QRect(rect.x() + x0, rect.y(), rect.width() - x0, rect.height())
            # Seulement la partie qui s'estompe (capturer toute la zone puis la recouper repeignait aussi les
            # colonnes de gauche, de plus en plus nombreuses avec la profondeur).
            pixmap = viewport.grab(target)
            overlay = _FadeOverlay(viewport, pixmap, target, 1.0, 0.0, 520,
                                   on_done=lambda: setattr(self, "_select_fade", None))
            # Pas de set_spans : l'ancien contenu s'estompe d'un bloc (et non colonne apres colonne).
            overlay.show()
            overlay.raise_()
            self._select_fade = overlay
            return overlay
        except RuntimeError:
            return None

    def _on_selected_now(self, column: Column, path: Path | None):
        index = self.columns.index(column)
        # Une selection dans une colonne NORMALE reprend le focus brillant au
        # groupe IN/OVER/OUT/LOGICIELS (voir update_active_column).
        self._last_active_group_column = None
        # Revenir sur une colonne de la CHAINE (pas sur un contenu ouvert
        # apres le groupe) ferme le contenu ouvert : la selection restee dans
        # IN/OVER/OUT/LOGICIELS n'a plus lieu d'etre (sinon "Claude" gardait
        # un fond de selection apres un clic sur "notes").
        if index < self._chain_expected_total():
            for group_column in self.group_columns:
                if group_column.current_path() is not None:
                    group_column.list.clearSelection()
                    group_column.list.setCurrentItem(None)
        self.prune_after(index)
        # Configuration de chaine (voir load_project_columns) : (re)lue
        # UNIQUEMENT quand c'est la colonne Projets elle-meme qui vient
        # d'etre cliquee — None si aucune selection (repli legacy) ou si ce
        # projet n'a pas de fichier de configuration — voir la remarque de
        # tete de _active_project_config. REMISE A None des que "Type"
        # change de selection : sans ca, une configuration "base 2" (voir
        # ColumnConfigDialog.MIN_STEPS) restait ACCROCHEE au projet
        # PRECEDENT tant que "Projets" n'avait pas encore ete recliquee —
        # voir la remarque de l'utilisateur, "quand je suis sette par
        # exemple dans bib/houdini en base 2 et que je reviens en 3d des
        # colonnes disparaissent" : reselectionner "Type" (depth=1,
        # ajoute TOUJOURS "Projets" via la logique GENERIQUE, jamais
        # pilotee par une config de projet) tombait alors, a tort, dans la
        # branche "chaine configuree" du bloc plus bas (index=0 < expected_
        # total-1, calcule depuis ce config PERIME) avec level_index=-1 —
        # `config["columns"][-1]` levait IndexError sur une liste VIDE
        # (base 2), interrompant on_selected APRES le prune_after mais
        # AVANT de rajouter la nouvelle colonne "Projets" : elle
        # disparaissait alors purement et simplement, sans jamais
        # revenir.
        if column.column_title == "Type":
            self._active_project_config = None
        elif column.column_title == "Projets":
            self._active_project_config = load_project_columns(path) if path is not None else None
        if path is None:
            self.detail.clear()
            self.update_active_column()
            self._sync_mode_buttons()
            # Deselection : la pile n'est refaite que si la chaine a change (deselectionner un fichier, ex.
            # sortie de la planche, la reconstruisait pour rien : ~95 ms au clic).
            self.update_preview_stack(if_changed=True)
            self._sync_collapse_state()
            return
        self.path_label.setText(str(path))
        self._request_crumbs()
        if not self._bulk_navigation:
            self.detail.show_path(path)
        self._sync_mode_buttons()
        is_dir = entry_is_dir(path)          # type connu par la lecture du dossier : pas d'acces disque
        if is_dir:
            depth = index + 1
            config = self._active_project_config
            # `index < expected_total - 1` (PAS juste `config is not None`) :
            # la chaine CONFIGUREE ne pilote QUE les colonnes ENCORE DANS
            # la chaine elle-meme (avant le repertoire de travail) — au-
            # dela (contenu ouvert depuis le groupe fantome IN/OVER/OUT/
            # LOGICIELS, voir _open_group_folder, ou tout niveau descendu
            # ENSUITE), la navigation doit rester GENERIQUE et illimitee,
            # exactement comme en legacy — voir la remarque de
            # l'utilisateur, "quand on navigue de dossier en dossier, au
            # bout d'un moment tu ne crees plus de colonnes, comme si tu
            # avais mis une limite, je veux supprimer cette limite" :
            # AVANT ce correctif, `level_index < len(columns_cfg)` restait
            # FAUX pour TOUJOURS des qu'on descendait plus loin que la
            # chaine configuree elle-meme (son index ne fait QUE croitre),
            # bloquant silencieusement toute colonne suivante dans une
            # BRANCHE de contenu ouverte apres le groupe.
            expected_total = self._chain_expected_total()
            # `index >= 1` (garde-fou EN PLUS de la remise a None ci-dessus,
            # voir sa remarque) : depth=1 (index=0, "Type") ajoute TOUJOURS
            # "Projets" par la logique GENERIQUE plus bas, jamais par la
            # chaine configuree d'un projet — quel que soit `config`,
            # level_index (= depth - 2) y serait negatif.
            if config is not None and index >= 1 and index < expected_total - 1:
                # Chaine CONFIGUREE (voir ColumnConfigDialog) : depth 2 =
                # 1er niveau configure (config["columns"][0]), etc. Chaque
                # niveau pointe vers un sous-dossier au nom FIXE (voir
                # _named_subdir) — la colonne liste ensuite son CONTENU
                # (filtre par show_dirs/show_files/omit_dirs/omit_files),
                # l'utilisateur clique une entree pour descendre — voir la
                # remarque de l'utilisateur, "chaque colonne configuree
                # pointe vers un nom de dossier fixe ... la colonne liste
                # le contenu ... filtre par les options Afficher/Omettre".
                level_index = depth - 2
                col_cfg = config["columns"][level_index]
                child_dir = _named_subdir(path, col_cfg["name"])
                # style_title="Sous-projet" (voir Column.style_title,
                # settings_window "INTERMEDIAIRE") : le NOM affiche
                # reste celui choisi par l'utilisateur (title=col_cfg
                # ["name"], ex. "test1" — identite/annotations
                # inchangees), mais l'APPARENCE (hauteur de ligne,
                # police, couleurs, bordures, padding...) suit TOUJOURS
                # le MEME reglage General > Colonnes > INTERMEDIAIRE,
                # quel que soit le nombre de niveaux configures — voir
                # la remarque de l'utilisateur, "doit controler toutes
                # les colonnes entre celle de projet et focus" : sans
                # ca, un titre inconnu retombait sur le bucket
                # generique "Contenu" (voir _col_key), partage a tort
                # avec les colonnes fantomes IN/OVER/OUT.
                self.add_column(
                    child_dir, depth, title=col_cfg["name"],
                    is_focus_level=col_cfg["focus"], style_title="Sous-projet",
                    show_dirs=col_cfg["show_dirs"], show_files=col_cfg["show_files"],
                    omit_dirs=frozenset(n.lower() for n in col_cfg["omit_dirs"]),
                    omit_files=frozenset(n.lower() for n in col_cfg["omit_files"]),
                    # En-tete DYNAMIQUE (voir add_column/la remarque de
                    # l'utilisateur, "le nom des colonnes correspond au nom
                    # du repertoire selectionne dans la colonne
                    # precedente") : `path` est le dossier SELECTIONNE dans
                    # la colonne precedente — `child_dir` (son contenu
                    # FIXE, ex. "test1") n'aurait ici aucun rapport.
                    display_title=path.name)
            elif config is not None and index == expected_total - 1:
                # Dernier niveau configure ATTEINT (`column` EST le niveau
                # terminal, pas encore de contenu ouvert au-dela) — comme
                # "Logiciels" en legacy, pas de vraie colonne ici, le
                # groupe fantome (update_preview_stack) gere le
                # "Repertoire de travail" (config["work_dir"]).
                pass
            else:
                # Legacy (config is None) : `depth` reste ALIGNE sur
                # COLUMN_LABELS par construction (Type/Projets/Sous-projet/
                # Logiciels/Contenu, expected_total TOUJOURS 3) — depth 3
                # ("Logiciels") reste donc le seul et unique endroit ou
                # sauter l'ajout d'une VRAIE colonne : elle fait partie du
                # groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
                # stack), reconstruit a partir de la selection courante.
                #
                # Chaine CONFIGUREE (config is not None) : tout ce qui
                # atteint CETTE branche est du contenu ouvert AU-DELA du
                # terminal (voir _open_group_folder, puis toute descente
                # ulterieure) — le terminal lui-meme est deja gere par le
                # "elif index == expected_total - 1" ci-dessus. `depth` n'y
                # est PLUS forcement aligne avec COLUMN_LABELS des que "set"
                # est desactive ou que le nombre de niveaux configures
                # differe de 1 (voir _chain_expected_total) : y reappliquer
                # le lookup COLUMN_LABELS/le test SOFTWARE_COLUMN_LABEL
                # pouvait a tort retomber sur "Logiciels" et sauter
                # l'ajout — voir la remarque de l'utilisateur, "on ne doit
                # pas avoir de limite de repertoire quand le set est
                # desactive, actuellement je ne peux pas aller dans plus de
                # deux repertoire". Toujours le bucket generique "Contenu"
                # ici (comme _open_group_folder), jamais de lookup par depth.
                if config is None:
                    title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
                    if title != SOFTWARE_COLUMN_LABEL:
                        self.add_column(path, depth)
                else:
                    self.add_column(path, depth, title="Contenu")
        self.update_active_column()
        self._sync_collapse_state()
        self.update_preview_stack(if_changed=not is_dir)   # un fichier : pile refaite si la chaine change
        self._slide_snapshot = None   # les colonnes de droite ont change : capture perimee
        if self._bulk_navigation:
            return                     # navigation directe (_navigate_to) : seule la derniere colonne apparait
        if len(self.columns) > index + 1:
            QTimer.singleShot(0, lambda c=self.columns[index + 1]: self._animate_column_in(c))
        else:
            # Pas de nouvelle vraie colonne (dernier niveau atteint) : c'est le groupe
            # IN/OVER/OUT/LOGICIELS ou les colonnes Focus qui apparaissent ; ils sortent
            # de dessous de la meme facon (sinon ils surgissaient sous le fondu).
            QTimer.singleShot(0, lambda c=column: self._animate_column_in(self._widget_after(c)))

    def _widget_after(self, widget):
        """Premier widget visible place apres `widget` dans columns_layout, ou None."""
        found = False
        for i in range(self.columns_layout.count()):
            item = self.columns_layout.itemAt(i).widget()
            if item is None:
                continue
            if found and item.isVisible() and item.width() > 0:
                return item
            if item is widget:
                found = True
        return None

    def _animate_column_in(self, column):
        """Apparition d'une colonne nouvellement ajoutee : meme mouvement que le
        depliage des colonnes de set (voir _SlideOverlay) — la colonne et ce qui la
        suit sortent de SOUS la colonne precedente (fixe), avec une ombre portee. Joue sur des
        captures de l'etat final ; les colonnes de gauche ne bougent pas."""
        try:
            # `column` : une colonne, ou le bloc IN/OVER/OUT/LOGICIELS ou Focus (voir _widget_after).
            if column is None or not shiboken6.isValid(column):
                return
            if (not (column in self.columns or column in (self._group_stack_wrapper, self._preview_stack_wrapper))
                    or not self.isVisible() or self._project_columns_hidden
                    or column.width() <= 0 or getattr(column, "collapsed", False)
                    or _anim_running(self._columns_slide)):
                return
            self.columns_layout.activate()
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.maximum())
            viewport = self.scroll.viewport()
            x = column.mapTo(viewport, QPoint(0, 0)).x()
            # Le fondu de l'ancien contenu (voir on_selected) est un enfant du viewport :
            # il serait recopie dans la capture. On le retire le temps de la prise.
            fade = self._select_fade
            fade_up = _anim_running(fade) and fade.isVisible()
            if fade_up:
                fade.hide()
            # Seule la zone a partir de la colonne sous laquelle la nouvelle sort bouge : rien a capturer ni a
            # couvrir a sa gauche (les captures de TOUTES les colonnes visibles coutaient de plus en plus cher
            # avec la profondeur, ~50 ms a 10 niveaux).
            origin = max(0, x - column.width())
            try:
                snapshot = self._grab_set_columns_at(x, start=origin)
            finally:
                if fade_up:
                    fade.show()
            if snapshot is None:
                return
            left, right, x, background, limit = snapshot
            overlay = _SlideOverlay(
                viewport, left, right, x - column.width(), x, background, 0.0, 1.0, 200,
                None, on_done=lambda: setattr(self, "_columns_slide", None), limit=limit,
                emerge=True, origin=origin)
            overlay.show()
            overlay.raise_()
            self._columns_slide = overlay
            if fade_up:
                # La colonne qui sort reste 100 % opaque : le fondu ne la recouvre pas
                # (son dernier emplacement est conserve une fois l'animation finie).
                last = {}
                # Largeur du contenu REEL qui sort (colonne + ce qui la suit), SANS
                # l'inspecteur : l'inclure etendait la zone exclue a toute la droite et
                # l'ancien contenu disparaissait d'un coup au lieu de s'estomper.
                content_w = max(1, self._columns_content_right() - x)

                def covered(slide=overlay):
                    try:
                        last["rect"] = slide.right_rect(content_w)
                    except RuntimeError:
                        pass
                    return last.get("rect")
                fade.set_exclude(covered)
                fade.raise_()
        except RuntimeError:
            pass

    def _sync_collapse_state(self):
        """Replie automatiquement TOUTES les colonnes de la chaine requise
        (voir _chain_expected_total/Column.collapsible, PAS une liste de
        titres fixe — N quelconque : 3 en legacy, ou le nombre de niveaux
        configures, voir la remarque de l'utilisateur, "si un projet est
        sur une base 3 etapes, 3 colonnes devront se rabattre, si c'est une
        base 4, 4 colonnes ... en fait c'est toutes les colonnes avant les
        colonnes de focus") des que la chaine est COMPLETEMENT settee
        jusqu'au repertoire de travail (voir _chain_terminal_path) : ce
        contexte devient fixe, ces colonnes de navigation n'ont plus besoin
        de rester deployees. Desactivable entierement (voir General >
        Application, "un toggle qui permet ou pas de rabattre les colonnes
        de set" — auto_collapse_set_columns()) : dans ce cas, jamais replie
        automatiquement, mais l'icone de repli MANUEL sur la colonne des
        vignettes reste disponible (voir _toggle_project_columns). Ne force
        ce repli qu'UNE fois par selection (voir _auto_collapse_armed) : un
        depli manuel ensuite (icone sur la colonne des vignettes) n'est pas
        systematiquement annule tant que la selection reste la meme.
        Redeploie tout automatiquement des que la chaine n'est plus
        complete (retour en arriere dans la navigation), pour laisser le
        choix a nouveau visible, et rearme alors le repli automatique pour
        la prochaine selection."""
        self._enforce_hidden_columns()
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        has_selection = self._chain_terminal_path() is not None
        if not has_selection or not focus_enabled:
            # Sans colonne Focus (voir ColumnConfigDialog, toggle "Focus" a
            # 0), replier les colonnes d'avant n'a plus aucun but (voir sa
            # remarque de tete : ce repli sert a REVELER la colonne Focus,
            # qui n'existe pas ici) — les colonnes de la chaine restent donc
            # TOUJOURS deployees dans ce cas.
            self._auto_collapse_armed = True
            if self._project_columns_collapsed:
                # Differe aussi (voir plus bas) : jamais de capture ni de boucle
                # d'evenements au milieu d'une navigation.
                QTimer.singleShot(0, self._auto_expand_now)
        elif auto_collapse_set_columns() and self._auto_collapse_armed and not self._project_columns_collapsed:
            # Differe d'un tour de boucle : _sync_collapse_state est appelee AVANT que
            # update_preview_stack ait reconstruit les vignettes/le groupe ; capturer
            # maintenant figerait un etat intermediaire (puis un saut a l'ecran).
            self._auto_collapse_armed = False
            # Navigation directe (_navigate_to) : repli pose sans animation (rien n'a ete montre entre-temps).
            animate = not self._bulk_navigation
            QTimer.singleShot(0, lambda: self._auto_collapse_now(animate))
