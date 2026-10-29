"""Méthodes de colonne : géométrie, redimensionnement et événements."""

from pathlib import Path
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, Qt, QVariantAnimation
from PySide6.QtWidgets import QApplication, QDialog
from app_style import columns_resizable, scaled, ui_scale, column_style_for
import ui_state
from browser_core import COLUMN_MAX_WIDTH, COLUMN_MIN_WIDTH, COLUMN_RESIZE_MARGIN, COLUMN_SETTINGS, GROUP_COLUMN_DEFAULT_HEIGHT, GROUP_COLUMN_MAX_HEIGHT, GROUP_COLUMN_MIN_HEIGHT, ROLE_ISDIR, ROLE_PATH, ROW_RESIZE_MAX_HEIGHT, ROW_RESIZE_MIN_HEIGHT, _WIDGET_SIZE_MAX, _col_key, _hide_resize_width, _make_group_drag_ghost, _persist_column_width, _persist_row_height, _row_preview_left_x, _show_resize_width, _show_row_resize_indicator, _step_badge_rect, _update_layout_setting, col_row_height, col_spacing, col_width, load_project_columns
from column_config import ColumnConfigDialog
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from column import Column


class ColumnGeometryMixin:
    def set_active(self, active: bool):
        if self.is_active != active:
            self.is_active = active
            self.list.viewport().update()
    def set_collapsed(self, collapsed: bool, animate: bool = True):
        """Replie entierement la colonne (largeur animee jusqu'a 0, voir
        _animate_width) ou la redeploie a sa largeur precedente. Ignore
        silencieusement les colonnes non repliables (voir `collapsible`,
        pose a la construction) : PipelineBrowser peut appeler ceci sur
        toutes ses colonnes sans avoir a filtrer lui-meme — pilote par
        l'icone unique de la colonne des vignettes (voir
        PipelineBrowser._toggle_project_columns), pas par une icone propre
        a chaque colonne."""
        if not self.collapsible or self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        if collapsed:
            self._expanded_width = self.width()
            target = 0
        else:
            target = self._expanded_width or self._pin_column_width or self._user_width or col_width(self.style_title)
        if animate:
            self._animate_width(target)
        else:
            if not collapsed:
                self.show()
            self.setFixedWidth(target)
            if collapsed:
                self.hide()
    def _animate_width(self, target_width: int, duration: int = 200):
        if getattr(self, "_width_anim", None) is not None:
            self._width_anim.stop()
        start_width = self.width()
        if start_width == target_width:
            return

        if not self.collapsed:
            self.show()

        anim = QVariantAnimation(self)
        anim.setDuration(duration)
        anim.setStartValue(start_width)
        anim.setEndValue(target_width)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        if hasattr(self, "list") and self.list is not None:
            self.list.setUpdatesEnabled(False)

        def on_step(val):
            w = int(val)
            self.setFixedWidth(w)

        def on_finished():
            if hasattr(self, "list") and self.list is not None:
                self.list.setUpdatesEnabled(True)
            if self.collapsed:
                self.hide()

        anim.valueChanged.connect(on_step)
        anim.finished.connect(on_finished)
        self._width_anim = anim
        anim.start()
    def refresh_all(self):
        """Rafraichit toutes les colonnes de la fenetre (utilise apres un
        glisser-deposer, qui peut affecter la colonne source ET la cible)."""
        win = self.window()
        if hasattr(win, "refresh_all_columns"):
            win.refresh_all_columns()
        else:
            self.refresh()
    def _in_resize_zone(self, x: int) -> bool:
        # Une colonne repliee (largeur nulle, voir set_collapsed) ne se
        # redimensionne pas a la main. columns_resizable() : Fenetre de
        # parametres > Tableaux > Colonnes dimensionnables (voir
        # app_style.set_columns_resizable) — desactive, ni le curseur ni le
        # glisser ne s'activent plus sur cette bordure.
        if self.collapsed or not columns_resizable():
            return False
        return self.width() - COLUMN_RESIZE_MARGIN <= x <= self.width()
    def resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        _show_resize_width(self, self.width())
    def _throttled_layout(self):
        """Voir le commentaire pres de _layout_throttle_timer (__init__) —
        appelle doItemsLayout() tout de suite si aucun appel n'est deja "en
        vol" dans les 16ms courantes, sinon note juste qu'un rattrapage
        sera necessaire (_flush_layout_throttle, au timeout)."""
        if self._layout_throttle_timer.isActive():
            self._layout_pending = True
            return
        self.list.doItemsLayout()
        self._layout_throttle_timer.start()
    def _flush_layout_throttle(self):
        if self._layout_pending:
            self._layout_pending = False
            self.list.doItemsLayout()
    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self._user_width = new_width
        self.setFixedWidth(new_width)
        self._throttled_layout()
        self._update_card_mask()   # voir sa docstring — self.card change de largeur ici aussi
        if self._on_resize is not None:
            self._on_resize(new_width)
        _show_resize_width(self, new_width)
    def resize_end(self):
        self._resizing = False
        _hide_resize_width(self)
        # Purge immediate (pas d'attente du prochain timeout a 16ms, voir
        # _throttled_layout) : le tout DERNIER mouvement avant le relachement
        # doit se voir sans le moindre delai perceptible.
        self._layout_throttle_timer.stop()
        self._layout_pending = False
        self.list.doItemsLayout()
        if self.style_title == "Type":
            # "Type" n'a jamais de bouton punaise (voir __init__) mais doit
            # neanmoins s'enregistrer automatiquement — voir la remarque de
            # l'utilisateur, "les seules colonnes dont les parametres sont
            # enregistrees automatiquement sont : colonne type, colonnes
            # focus, colonne inspecteur".
            _persist_column_width(self.window(), "Type", self.width())
        elif self._pin_active:
            # Punaise ACTIVE (voir _toggle_pin) : la largeur qu'on vient de
            # glisser a la main REMPLACE automatiquement celle figee — voir la
            # remarque de l'utilisateur, "quand on modifie une valeur quand une
            # punaise est pinnee, cette valeur doit etre enregistree
            # automatiquement" (sans repincer/depincer a la main).
            self._pin_column_width = self.width()
            _update_layout_setting(self.directory, "pinned_column_width", self._pin_column_width)
        if self._on_resize_end is not None:
            self._on_resize_end()
        # Sans punaise et hors "Type" : la largeur n'est PLUS persistee du
        # tout (voir la remarque de l'utilisateur, "les hauteurs ne peuvent
        # pas etre enregistrees sauf si on met la punaise" — meme principe
        # etendu a la largeur) ; elle reste ajustable pour la session
        # courante via self._user_width (voir refresh_all_columns).

    def _in_height_resize_zone(self, y: int) -> bool:
        """Bord BAS d'une colonne du groupe IN/OVER/OUT/LOGICIELS (voir
        group_kind) — EXACTEMENT le meme principe que _in_resize_zone (bord
        DROIT), mais applique a la hauteur : ces 4 colonnes empilees ont une
        hauteur FIXE (voir __init__), contrairement a une colonne NORMALE
        toujours etiree sur toute la hauteur disponible — glisser ce bord
        n'a donc de sens QUE pour elles, et PAS pour la DERNIERE colonne de
        l'ordre courant (voir fill_height, TOUJOURS etiree jusqu'en bas —
        rien a redimensionner puisqu'elle n'a justement PAS de hauteur
        fixe). Priorite sur _in_row_resize_zone (Ctrl+glisser entre 2
        lignes) : gate sur `group_kind`, jamais actif en meme temps que
        celle-ci (styles "Contenu"/"Logiciels", hors
        _ROW_HEIGHT_RESIZABLE_TITLES)."""
        if self._group_kind is None or self._group_fill_height or self.collapsed or not columns_resizable():
            return False
        return self.height() - COLUMN_RESIZE_MARGIN <= y <= self.height()
    def height_resize_begin(self, global_y: int):
        self._group_height_resizing = True
        self._group_height_resize_start_y = global_y
        self._group_height_resize_start_height = self.height()
        if self._on_height_resize_begin is not None:
            self._on_height_resize_begin(self._group_kind)
        _show_resize_width(self, self.height())
    def height_resize_update(self, global_y: int):
        # PAS de calcul de hauteur ICI (voir la remarque de tete sur
        # `on_height_resize`) : seul PipelineBrowser._on_group_height_resized
        # connait les 2 colonnes concernees (celle-ci ET sa voisine
        # suivante) et leurs hauteurs de depart — il applique lui-meme
        # setFixedHeight() sur les DEUX, jamais Column elle-meme.
        delta = global_y - self._group_height_resize_start_y
        if self._on_height_resize is not None:
            self._on_height_resize(self._group_kind, delta)
        _show_resize_width(self, self.height())
    def set_group_fill_height(self, fill: bool):
        """Bascule cette colonne du groupe entre hauteur FIXE (voir
        _group_user_height/GROUP_COLUMN_DEFAULT_HEIGHT) et hauteur ETIREE
        jusqu'en bas (voir fill_height, __init__) — appele quand l'ordre
        change (voir PipelineBrowser._reorder_group_columns_animated) et
        qu'une AUTRE colonne devient la derniere : celle qui redevient
        derniere doit se liberer de sa hauteur fixe (setMaximumHeight a
        _WIDGET_SIZE_MAX, valeur par defaut de Qt), celle qui ne l'est plus
        doit en reprendre une."""
        if fill == self._group_fill_height:
            return
        self._group_fill_height = fill
        if fill:
            # 0 (PAS GROUP_COLUMN_MIN_HEIGHT) : voir la remarque de
            # l'utilisateur, "la colonne du bas (out) a une hauteur
            # minimum. supprime cette limite" — SEULE la colonne fill
            # (toujours la DERNIERE de l'ordre courant) perd cette borne ;
            # les AUTRES colonnes du groupe gardent la leur (voir
            # _on_group_height_resized, `max(GROUP_COLUMN_MIN_HEIGHT, ...)`
            # sur `new_above`, INCHANGE).
            self.setMinimumHeight(0)
            self.setMaximumHeight(_WIDGET_SIZE_MAX)
        else:
            self.setMinimumHeight(0)
            self.setFixedHeight(self._group_user_height or GROUP_COLUMN_DEFAULT_HEIGHT)
    def height_resize_end(self):
        self._group_height_resizing = False
        if self._on_height_resize_end is not None:
            self._on_height_resize_end()
        _hide_resize_width(self)
    def _in_row_resize_zone(self, y: int) -> bool:
        """Vrai si `y` (coordonnee LOCALE au viewport de self.list) tombe
        dans la marge de redimensionnement entre 2 lignes, Ctrl enfonce —
        voir la remarque de l'utilisateur, "appuyer sur la touche controle
        du clavier et cliquer entre deux lignes et glisser ... doit etre
        sur toutes les colonnes". Disponible sur TOUTE colonne (plus de
        liste de titres fixe — anciennement limite a Type/Projets/Sous-
        projet, ce qui excluait aussi bien Logiciels/Contenu que toute
        colonne d'une chaine CONFIGUREE comme "test1"/"test2") : ajuste
        TOUJOURS `COLUMN_SETTINGS[_col_key(title)]["height"]` (voir
        row_resize_begin/update, deja generique), c'est-a-dire la hauteur
        des lignes AVEC vignette/dossier — Logiciels/Contenu melangent 2
        hauteurs (voir col_plain_height pour les lignes fichier SANS
        apercu), mais cette 2e hauteur n'est simplement jamais celle que ce
        geste modifie, aucune ambiguite reelle (voir _persist_row_height
        pour la persistance, qui ecrit dans le defaut GENERAL pour ces
        titres-la, faute d'onglet de surcharge dedie)."""
        if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
            return False
        above = self.list.indexAt(QPoint(1, y - COLUMN_RESIZE_MARGIN))
        if not above.isValid():
            return False
        below = self.list.indexAt(QPoint(1, y + COLUMN_RESIZE_MARGIN))
        return not below.isValid() or below.row() != above.row()
    def effective_row_height(self) -> int:
        """Hauteur de ligne EFFECTIVE de cette colonne (voir sizeHint des
        delegates) : la punaise (voir __init__/_pin_row_height/_toggle_pin)
        d'ABORD si active (prioritaire sur tout le reste), sinon celle
        propre a `self.directory` si elle a deja ete ajustee a la main
        (voir __init__/_folder_row_height) — MEME mecanisme pour une
        colonne du groupe IN/OVER/OUT/LOGICIELS que pour une colonne
        normale depuis que ces 4 colonnes recoivent une identite de
        dossier STABLE (voir PipelineBrowser.update_preview_stack,
        add_group_column) et ne sont plus reconstruites a chaque
        navigation — plus besoin d'un bucket separe (GROUP_ROW_HEIGHT,
        supprime) qui les faisait toutes partager la MEME hauteur via le
        style "Contenu" — voir la remarque de l'utilisateur, "elle
        intervient sur plusieurs colonnes en meme temps" ; sinon la valeur
        GENERALE du bucket de style (voir col_row_height/_col_key)."""
        if self._pin_row_height is not None:
            return scaled(self._pin_row_height)
        if self._folder_row_height is not None:
            return scaled(self._folder_row_height)
        return col_row_height(self.style_title)
    def group_content_height_hint(self) -> int:
        """Hauteur NECESSAIRE pour afficher tout le contenu de cette
        colonne SANS scroll (entete + toutes les lignes + espacement) —
        voir PipelineBrowser._on_group_maximize, la remarque de
        l'utilisateur, "agrandir au maximum ... et de minimiser les
        autres au maximum en fonction de leur contenu". Bornee a
        GROUP_COLUMN_MIN_HEIGHT/GROUP_COLUMN_MAX_HEIGHT (memes bornes que
        le redimensionnement manuel, voir _on_group_height_resized) —
        jamais 0 (colonne vide) ni demesuree (des centaines de lignes)."""
        header_h = self.header.height()
        if header_h <= 0:
            header_h = scaled(int(column_style_for(self.style_title).get("header_height", ui_state.HEADER_HEIGHT)))
        count = self.list.count()
        row_h = self.effective_row_height()
        spacing = col_spacing(self.style_title)
        content_h = count * row_h + max(0, count - 1) * spacing
        return max(GROUP_COLUMN_MIN_HEIGHT, min(GROUP_COLUMN_MAX_HEIGHT, header_h + content_h + 8))
    def row_resize_begin(self, global_y: int, local_y: int | None = None):
        self._row_resizing = True
        self._row_resize_start_y = global_y
        # Ligne au-dessus du bord glisse (voir _in_row_resize_zone, MEME
        # calcul) : memorisee ICI pour ancrer l'indicateur de hauteur juste
        # SOUS elle pendant tout le glisser (voir _show_row_resize_
        # indicator) — voir la remarque de l'utilisateur, "je veux que la
        # position de l'indicateur de hauteur soit juste au dessous de la
        # ligne que l'on redimensionne".
        self._row_resize_row_index = -1
        if local_y is not None:
            above = self.list.indexAt(QPoint(1, local_y - COLUMN_RESIZE_MARGIN))
            if above.isValid():
                self._row_resize_row_index = above.row()
        # MEME PRIORITE que effective_row_height() (punaise D'ABORD) : sans
        # ca, demarrer un glisser sur une colonne PINNEE repartait d'une
        # hauteur DIFFERENTE de celle reellement affichee (_folder_row_
        # height/generale, jamais _pin_row_height), faisant "sauter" la
        # ligne des le tout premier mouvement — voir la remarque de
        # l'utilisateur, "le redimensionnement des lignes dans les
        # colonnes se fait mal".
        # MEME calcul pour une colonne du groupe IN/OVER/OUT/LOGICIELS que
        # pour une colonne normale (voir effective_row_height, sa remarque) :
        # ces 4 colonnes ont desormais une identite de dossier STABLE, plus
        # besoin d'un chemin separe.
        self._row_resize_start_height = (
            self._pin_row_height if self._pin_row_height is not None
            else self._folder_row_height if self._folder_row_height is not None
            else COLUMN_SETTINGS[_col_key(self.style_title)]["height"])
        _show_row_resize_indicator(self, self._row_resize_row_index, self.effective_row_height())
    def row_resize_update(self, global_y: int):
        delta_screen = global_y - self._row_resize_start_y
        delta_logical = round(delta_screen * 100 / max(1, ui_scale()))
        new_height = max(
            ROW_RESIZE_MIN_HEIGHT, min(ROW_RESIZE_MAX_HEIGHT, self._row_resize_start_height + delta_logical))
        # Colonne de navigation REELLE OU colonne du groupe IN/OVER/OUT/
        # LOGICIELS (voir effective_row_height, sa remarque) : la valeur
        # choisie ici reste PROPRE a ce dossier (identite STABLE meme pour
        # les 4 colonnes de groupe, voir update_preview_stack/
        # add_group_column), JAMAIS ecrite dans le bucket de style GLOBAL
        # (COLUMN_SETTINGS) partage par toutes les colonnes du meme style —
        # voir la remarque de l'utilisateur, "jamais les mm suivant le sous
        # dossier precedent"/"elle intervient sur plusieurs colonnes en
        # meme temps" : une AUTRE colonne du meme style (naviguee vers un
        # AUTRE dossier, ou un AUTRE kind du groupe) ne doit PAS bouger.
        self._folder_row_height = new_height
        # Punaise ACTIVE : _pin_row_height doit AUSSI suivre EN DIRECT (pas
        # seulement au relachement, voir row_resize_end) — effective_row_
        # height() le priorise sur _folder_row_height, le laisser fige
        # pendant tout le glisser figeait l'AFFICHAGE (rien ne bougeait a
        # l'ecran) meme si la valeur interne changeait bien — voir la
        # remarque de l'utilisateur, "quand on modifie la hauteur de la
        # ligne, elle ne se modifie pas en temps reelle tant que la
        # punaise est activee".
        if self._pin_active:
            self._pin_row_height = new_height
        # doItemsLayout() (pas juste un repaint) : sizeHint() de CHAQUE ligne
        # depend de col_row_height(), qu'on vient de changer — un simple
        # viewport().update() garderait les anciennes tailles/positions.
        # _throttled_layout() (pas un appel direct) : voir son commentaire,
        # limite ce recalcul a ~60/s pendant le glisser.
        self._throttled_layout()
        _show_row_resize_indicator(self, self._row_resize_row_index, new_height)
    def row_resize_end(self):
        self._row_resizing = False
        _hide_resize_width(self, "row_height")
        # Purge immediate (voir resize_end, meme raison) : la hauteur du
        # tout dernier mouvement doit s'appliquer sans attendre le prochain
        # timeout de _layout_throttle_timer.
        self._layout_throttle_timer.stop()
        self._layout_pending = False
        self.list.doItemsLayout()
        if self.style_title == "Type":
            # "Type" n'a jamais de bouton punaise mais doit neanmoins
            # s'enregistrer automatiquement — voir la remarque de
            # l'utilisateur, "les seules colonnes dont les parametres
            # sont enregistrees automatiquement sont : colonne type,
            # colonnes focus, colonne inspecteur". Pas de notion de
            # dossier ici (voir _persist_row_height) : la valeur GLOBALE
            # de style est mise a jour directement.
            _persist_row_height(self.window(), "Type", self._folder_row_height)
        elif self._pin_active:
            # Punaise ACTIVE (voir _toggle_pin/resize_end, MEME raison) :
            # persiste DANS CE DOSSIER (voir __init__/_folder_row_height,
            # la remarque de l'utilisateur, "jamais les mm suivant le
            # sous dossier precedent") et remplace automatiquement la
            # valeur figee — voir la remarque de l'utilisateur, "quand
            # on modifie une valeur quand une punaise est pinnee, cette
            # valeur doit etre enregistree automatiquement". MEME chemin
            # pour une colonne du groupe IN/OVER/OUT/LOGICIELS (identite
            # de dossier STABLE, voir update_preview_stack).
            _update_layout_setting(self.directory, "row_height", self._folder_row_height)
            self._pin_row_height = self._folder_row_height
            _update_layout_setting(self.directory, "pinned_row_height", self._pin_row_height)
        # Sans punaise et hors "Type" : la hauteur n'est PLUS persistee
        # (voir la remarque de l'utilisateur, "les hauteurs ne peuvent
        # pas etre enregistrees sauf si on met la punaise") ; elle reste
        # ajustable pour la session courante via self._folder_row_height,
        # qui persiste desormais avec l'INSTANCE (les 4 colonnes de groupe
        # ne sont plus reconstruites a chaque navigation, voir
        # update_preview_stack).

    def eventFilter(self, obj, event):
        etype = event.type()
        # Glisser-deposer de l'ENTETE (voir group_kind/on_reorder, __init__)
        # : SEULEMENT pour une colonne du groupe IN/OVER/OUT/LOGICIELS, sur
        # header/header_fill/les 2 labels (voir _group_header_widgets — ils
        # COUVRENT header, sans eux la souris le touche presque jamais) —
        # jamais sur self.list.viewport()/sa scrollbar (deja pris par
        # FileListWidget pour glisser des FICHIERS). SUIVI A LA MAIN (pas de
        # QDrag/OLE natif) : sur une fenetre SANS decoration systeme et
        # translucide (voir PipelineBrowser.__init__, WA_TranslucentBackground/
        # FramelessWindowHint), le glisser-deposer natif Windows s'est avere
        # peu fiable — voir la remarque de l'utilisateur, "il y a encore des
        # cas ou ca ne fonctionne pas" (deja apres le correctif de couverture
        # de l'entete). Repose ICI sur le SEUL mecanisme deja fiable dans ce
        # fichier pour ce genre de geste (voir resize_begin/_row_resizing) :
        # la capture implicite Qt du bouton par le widget qui a recu le
        # QMouseEvent.Press, qui continue a recevoir MouseMove/Release tant
        # que le bouton reste enfonce, MEME hors de ce widget — aucun DnD
        # necessaire. Traite EN PREMIER, avant le reste (resize de bordure/
        # de ligne) : le seuil de demarrage du drag (MouseMove) doit passer
        # AVANT le test de zone de redimensionnement pour ne pas lui faire
        # concurrence au centre de l'entete (hors de cette zone).
        if self._group_kind is not None and obj in self._group_header_widgets:
            if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                local_x = obj.mapTo(self, event.position().toPoint()).x()
                # Deplacer une colonne du groupe = Ctrl + glisser (demande de l'utilisateur, pour tout
                # deplacement de l'appli).
                if not self._in_resize_zone(local_x) and event.modifiers() & Qt.ControlModifier:
                    self._group_drag_start = event.globalPosition().toPoint()
            elif etype == QEvent.MouseMove and self._group_drag_start is not None:
                global_pos = event.globalPosition().toPoint()
                if self._group_ghost is not None:
                    self._group_ghost.move(global_pos - self._group_ghost_offset)
                    return True
                moved = global_pos - self._group_drag_start
                if moved.manhattanLength() >= QApplication.startDragDistance():
                    self._group_ghost_offset = global_pos - self.mapToGlobal(QPoint(0, 0))
                    self._group_ghost = _make_group_drag_ghost(self)
                    self._group_ghost.move(global_pos - self._group_ghost_offset)
                    return True
            elif etype == QEvent.MouseButtonRelease:
                self._group_drag_start = None
                if self._group_ghost is not None:
                    self._group_ghost.close()
                    self._group_ghost = None
                    target = self._find_group_drop_target(event.globalPosition().toPoint())
                    if target is not None and target is not self and self._on_reorder is not None:
                        self._on_reorder(self._group_kind, target._group_kind)
                    return True
        if etype == QEvent.MouseMove:
            if self._row_resizing:
                self.row_resize_update(event.globalPosition().toPoint().y())
                return True
            if self._group_height_resizing:
                self.height_resize_update(event.globalPosition().toPoint().y())
                return True
            if obj is self.list.viewport() and self._in_row_resize_zone(int(event.position().y())):
                obj.setCursor(Qt.SizeVerCursor)
                return False
            local_point = obj.mapTo(self, event.position().toPoint())
            if self._in_height_resize_zone(local_point.y()):
                obj.setCursor(Qt.SizeVerCursor)
                return False
            if self._resizing:
                self.resize_update(event.globalPosition().toPoint().x())
                return True
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_point.x()) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # Badge numerote (voir _step_badge_rect/_row_preview_left_x/
            # ProjectTileDelegate.paint, project_step_count) : SEULEMENT sur
            # "Projets", avant tout autre test de cette branche (desormais
            # juste AVANT l'apercu, voir _paint_unified_row, PLUS au bord
            # haut-droit de la ligne — meme calcul de position ici, pour
            # que le hit-test reste synchronise avec le dessin) — consomme
            # le clic (return True), aucune selection/navigation ne doit se
            # declencher.
            if obj is self.list.viewport() and self.column_title == "Projets":
                pos = event.position().toPoint()
                idx = self.list.indexAt(pos)
                if idx.isValid() and bool(idx.data(ROLE_ISDIR)):
                    row_rect = self.list.visualRect(idx)
                    preview_left = _row_preview_left_x(row_rect, column_style_for(self.style_title))
                    badge_rect = _step_badge_rect(row_rect, preview_left)
                    # Le badge reste petit visuellement, mais sa cible de clic
                    # est portée à 36 px et limitée à la ligne. Cela évite de
                    # devoir viser précisément le disque orange, sans empiéter
                    # sur une autre ligne ni sortir de la colonne.
                    hit_size = 36
                    extra_x = max(0, (hit_size - badge_rect.width() + 1) // 2)
                    extra_y = max(0, (hit_size - badge_rect.height() + 1) // 2)
                    hit_rect = badge_rect.adjusted(-extra_x, -extra_y, extra_x, extra_y).intersected(row_rect)
                    if hit_rect.contains(pos):
                        self._open_column_config(Path(idx.data(ROLE_PATH)))
                        return True
            if obj is self.list.viewport() and self._in_row_resize_zone(int(event.position().y())):
                self.row_resize_begin(event.globalPosition().toPoint().y(), int(event.position().y()))
                return True
            local_point = obj.mapTo(self, event.position().toPoint())
            if self._in_height_resize_zone(local_point.y()):
                self.height_resize_begin(event.globalPosition().toPoint().y())
                return True
            if self._in_resize_zone(local_point.x()):
                self.resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.RightButton and obj is self.list.viewport():
            # Consomme le clic DROIT AVANT qu'il n'atteigne
            # QAbstractItemView.mousePressEvent (comportement Qt PAR
            # DEFAUT sinon : TOUT clic, gauche OU droit, change la
            # selection COURANTE de l'item sous le curseur) — voir la
            # remarque de l'utilisateur, "absolument rien ne se passe,
            # aucun menu n'apparait du tout" (clic droit sur un fichier/
            # dossier des colonnes IN/OVER/OUT/LOGICIELS) : CONFIRME —
            # pour une colonne du groupe (group_kind is not None), un
            # simple clic droit sur un DOSSIER changeait la selection,
            # declenchant Column._on_current_changed -> self.selected ->
            # PipelineBrowser._on_group_item_selected -> _open_group_
            # folder -> update_preview_stack(), qui DETRUIT ET RECONSTRUIT
            # tout le groupe — Y COMPRIS CETTE COLONNE ELLE-MEME — AVANT
            # meme que le QContextMenuEvent (qui suit normalement le
            # MouseButtonPress droit, PAS lie a lui) n'ait la moindre
            # chance d'etre livre au widget entre-temps deja detruit : le
            # clic droit "ne faisait absolument rien" de visible. Retourner
            # True ICI empeche desormais tout changement de selection au
            # clic droit (comportement standard des explorateurs de
            # fichiers, de toute facon plus coherent que le declenchement
            # de navigation involontaire que ca provoquait deja, sans
            # degat visible, sur les colonnes NORMALES) — le menu
            # contextuel (voir customContextMenuRequested/_on_context_menu,
            # policy Qt.CustomContextMenu deja posee sur self.list) suit
            # ensuite normalement, sans aucun rapport avec ce MousePress.
            return True
        elif etype == QEvent.MouseButtonRelease and (self._resizing or self._row_resizing or self._group_height_resizing):
            if self._row_resizing:
                self.row_resize_end()
            elif self._group_height_resizing:
                self.height_resize_end()
            else:
                self.resize_end()
            return True
        elif etype == QEvent.Leave and not (self._resizing or self._row_resizing or self._group_height_resizing):
            obj.unsetCursor()
        return False
    def _open_column_config(self, project_path: Path):
        """Ouvre ColumnConfigDialog pour `project_path` (clic sur le badge
        numerote, voir eventFilter) — a la fermeture par Enregistrer :
        `refresh()` (le badge affiche le nouveau project_step_count) et, si
        `project_path` est ACTUELLEMENT selectionne dans cette colonne,
        re-emet `selected` pour forcer PipelineBrowser.on_selected a
        recharger la config et reconstruire la chaine avec les nouveaux
        niveaux — sans ca, un projet deja ouvert garderait son ancienne
        chaine jusqu'a un clic explicite ailleurs puis retour."""
        config = load_project_columns(project_path)
        dlg = ColumnConfigDialog(project_path, config, self.window())
        if dlg.exec() == QDialog.Accepted:
            self.refresh()
            current = self.list.currentItem()
            if current is not None and Path(current.data(ROLE_PATH)) == project_path:
                self.selected.emit(self, project_path)
    def _find_group_drop_target(self, global_pos: QPoint) -> "Column | None":
        """Colonne du groupe IN/OVER/OUT/LOGICIELS (voir group_kind) dont le
        rectangle ECRAN contient `global_pos` (voir eventFilter, appele au
        relachement du glisser d'en-tete) — hit-test A LA MAIN plutot que
        `QApplication.widgetAt()` : celui-ci renverrait la ghost window
        elle-meme (voir _make_group_drag_ghost) si elle n'etait pas
        WA_TransparentForMouseEvents, ou tout widget ENFANT de la colonne
        (liste, labels...) sinon — on veut la COLONNE entiere, quel que soit
        l'enfant precis survole. `self.window()` : PipelineBrowser, seul
        detenteur de la liste a jour des colonnes du groupe (voir
        update_preview_stack)."""
        win = self.window()
        for column in getattr(win, "group_columns", []):
            top_left = column.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, column.size())
            if rect.contains(global_pos):
                return column
        return None
    # Gestionnaires DIRECTS sur self, EN PLUS de l'eventFilter ci-dessus
    # (installe sur header/self.list.viewport()/sa scrollbar — voir
    # __init__) : Padding (voir refresh_header/self._outer_layout) peut
    # desormais retrecir self.card (et tout son contenu, header/liste
    # compris) EN DECA du bord droit REEL de self — la zone de
    # redimensionnement, elle, reste TOUJOURS a ce bord reel (largeur
    # ALLOUEE, jamais retrecie par Padding, voir _in_resize_zone/self.
    # width()). Sans ces 2 gestionnaires, cette bande (le "vide" du
    # padding, visible entre le bord de la carte et le bord reel de la
    # colonne) n'etait couverte par AUCUN widget enfant — donc par aucun
    # eventFilter — rendant le redimensionnement tout simplement
    # INACCESSIBLE a la souris des que Padding > 0 — voir la remarque de
    # l'utilisateur, "il est impossible de redimensionner la colonne quand
    # on commence a toucher aux settings".
    def mouseMoveEvent(self, event):
        if self._resizing:
            self.resize_update(event.globalPosition().toPoint().x())
            return
        if self._group_height_resizing:
            self.height_resize_update(event.globalPosition().toPoint().y())
            return
        pos = event.position().toPoint()
        if self._in_height_resize_zone(pos.y()):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(pos.x()) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if self._in_height_resize_zone(pos.y()):
                self.height_resize_begin(event.globalPosition().toPoint().y())
                return
            if self._in_resize_zone(pos.x()):
                self.resize_begin(event.globalPosition().toPoint().x())
                return
        super().mousePressEvent(event)
    def mouseReleaseEvent(self, event):
        if self._resizing:
            self.resize_end()
            return
        if self._group_height_resizing:
            self.height_resize_end()
            return
        super().mouseReleaseEvent(event)
    def leaveEvent(self, event):
        if not (self._resizing or self._group_height_resizing):
            self.unsetCursor()
        super().leaveEvent(event)
