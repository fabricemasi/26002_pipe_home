import shutil
from pathlib import Path
from PySide6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QPoint, QRect, QSize, Qt, QTimer, QUrl,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QIcon,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from app_style import (
    C,
    columns_resizable,
    font,
    header_qss,
    role_color,
    role_font,
    scaled,
    ui_scale,
    resolve_color_ref,
    column_frame_style,
    column_header_qss,
    column_padding_for,
    column_style_for,
)
import ui_state
from config import (
    RENDERABLE_3D_EXTENSIONS,
    THUMBNAIL_COLUMN_LABELS,
    _MANUAL_3D_PREVIEW_MODE,
    _MANUAL_3D_PREVIEW_REQUESTS,
    _STALE_PREVIEW_PATHS,
)
from previews import (
    software_icon_key,
)
from config import (
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
)
from settings_widgets import (
    _radius_dict,
    _radius_shrink,
)
from browser_core import (
    COLUMN_MAX_WIDTH,
    COLUMN_MIN_WIDTH,
    COLUMN_RESIZE_MARGIN,
    COLUMN_SETTINGS,
    GROUP_COLUMN_DEFAULT_HEIGHT,
    GROUP_COLUMN_MAX_HEIGHT,
    GROUP_COLUMN_MIN_HEIGHT,
    ROLE_ISDIR,
    ROLE_IS_SHORTCUT,
    ROLE_META,
    ROLE_PATH,
    ROLE_SOURCE_LABEL,
    ROLE_SOURCE_STEP,
    ROW_RESIZE_MAX_HEIGHT,
    ROW_RESIZE_MIN_HEIGHT,
    _STATUS_FOLDER_SET,
    _WIDGET_SIZE_MAX,
    _col_key,
    _hide_resize_width,
    _is_globally_omitted_dir,
    _is_globally_omitted_file,
    _make_group_drag_ghost,
    _persist_column_width,
    _persist_row_height,
    _pin_icon_pixmap,
    _prompt_capture_thumbnail,
    _prompt_change_thumbnail,
    _prompt_reset_thumbnail,
    _resolve_font_family,
    _row_preview_left_x,
    _save_thumbnail_pixmap_for,
    _show_resize_width,
    _show_row_resize_indicator,
    _step_badge_rect,
    _update_layout_setting,
    add_shortcut,
    col_row_height,
    col_spacing,
    col_width,
    count_entries,
    human_size,
    list_entries,
    load_layout_settings,
    load_project_columns,
    load_shortcuts,
    project_thumbnail_path,
    remove_shortcut,
    save_shortcuts,
    reveal_in_file_manager,
    save_layout_settings,
)
from column_config import (
    ColumnConfigDialog,
)
from capture_widgets import (
    FileListWidget,
    _ColumnCard,
    _RoundedCornersEffect,
    _column_suppress_left,
)
from row_delegates import (
    ProjectTileDelegate,
    RowDelegate,
)


# ==========================================================================
# Colonne
# ==========================================================================

class Column(QWidget):

    selected = Signal(object, object)   # (Column, Path | None)
    activated = Signal(object)          # Path

    def __init__(self, directory: Path, title: str, parent=None,
                 source_dirs: list[Path] | None = None, display_title: str | None = None,
                 style_title: str | None = None,
                 user_width: int | None = None, on_resize=None, on_resize_end=None,
                 group_kind: str | None = None, on_reorder=None,
                 user_height: int | None = None, on_height_resize=None, fill_height: bool = False,
                 on_height_resize_begin=None, on_height_resize_end=None,
                 source_labels: list[str] | None = None,
                 is_focus_level: bool | None = None,
                 show_dirs: bool = True, show_files: bool = True,
                 omit_dirs: frozenset = frozenset(), omit_files: frozenset = frozenset(),
                 only_recognized_software: bool = False,
                 on_group_maximize=None, on_group_equalize=None):
        super().__init__(parent)
        self.directory = directory
        # Filtre "que des repertoires logiciel reconnus" (voir refresh()) —
        # remplace un test litteral `group_kind == "logiciels"` : un simple
        # booleen explicite, sans rapport avec l'identite group_kind (voir
        # la remarque de l'utilisateur, "base toi sur les colonnes creees
        # avant les focus" — group_kind ne pilote plus que le
        # reordonnancement/redimensionnement partage entre colonnes voisines,
        # jamais le contenu affiche).
        self._only_recognized_software = only_recognized_software
        # Hauteur de ligne PROPRE a ce dossier (voir load_layout_settings/
        # row_resize_begin/update/end, Colonnes.effective_row_height) —
        # SEULEMENT pour une colonne de navigation REELLE (group_kind=None,
        # PAS une colonne fantome du groupe IN/OVER/OUT/LOGICIELS, dont
        # `directory` n'est qu'un repli parmi plusieurs sources fusionnees,
        # voir source_dirs) : Ctrl+glisser sur une TELLE colonne enregistre
        # desormais la hauteur choisie DANS ce dossier (fichier cache
        # .pipeline_layout.json), pas dans un reglage GLOBAL partage entre
        # TOUTES les colonnes du meme style — voir la remarque de
        # l'utilisateur, "le dimensionnement en hauteur ... doit etre
        # enregistre en temps reel et ce dependant du [sous-]dossier ...
        # jamais les mm suivant le sous dossier precedent". None (repli) :
        # aucun reglage propre a ce dossier, suit la valeur GENERALE (voir
        # effective_row_height) — comportement INCHANGE tant qu'aucun
        # dossier n'a encore ete ajuste a la main.
        # Punaise d'en-tete (voir _toggle_pin/refresh_header, la remarque de
        # l'utilisateur, "punaise_02.png lorsque l'on clique dessus, les
        # valeurs de dimensions de colonnes et de lignes sont alors
        # overridees par les valeurs du json ... lorsque l'on rappuie ...
        # prend en compte les valeurs par defaut des settings") : couche
        # ADDITIVE et PRIORITAIRE sur tout le reste (largeur/hauteur
        # "normales" ci-dessus/generales) — cles DEDIEES (pinned*, jamais
        # les memes que row_height/_user_width) pour ne RIEN changer au
        # comportement existant tant que la punaise n'a jamais ete
        # activee sur ce dossier precis. CALCULEE AVANT _folder_row_height
        # ci-dessous (voir sa remarque) : la lecture de "row_height" en
        # depend desormais.
        layout_data = load_layout_settings(directory)
        self._pin_active = bool(layout_data.get("pinned", False))
        self._pin_column_width = layout_data.get("pinned_column_width") if self._pin_active else None
        self._pin_row_height = layout_data.get("pinned_row_height") if self._pin_active else None

        self._folder_row_height: int | None = None
        # Ne charge "row_height" QUE si la punaise est active — voir
        # row_resize_end, qui n'ecrit desormais PLUS cette cle du tout hors
        # punaise (seules Type/Focus s'auto-enregistrent, ailleurs). Sans ce
        # garde-fou, une valeur ECRITE AVANT ce changement (ancien
        # comportement : toute colonne auto-enregistrait sans punaise)
        # restait lue indefiniment ici, ce qui affichait une hauteur figee
        # (ex. 80px, le plafond ROW_RESIZE_MAX_HEIGHT) sans rapport avec le
        # reglage general — voir la remarque de l'utilisateur, "certaines
        # de mes colonnes affichent des hauteurs de ligne a 80px et je ne
        # comprends pas d'ou vient cette valeur".
        if self._pin_active:
            raw_height = layout_data.get("row_height")
            if isinstance(raw_height, (int, float)):
                self._folder_row_height = int(raw_height)

        # Menu contextuel "Afficher l'apercu"/"Afficher l'icone"/"Taille de
        # l'icone" (voir _on_context_menu) : None (repli) = valeur GENERALE
        # des reglages (comportement INCHANGE) ; MEME regle de persistance
        # que la hauteur/largeur de ligne ci-dessus — n'est charge que si
        # la punaise est active, SAUF "Type" (jamais de punaise, mais
        # auto-enregistre quand meme, voir _should_autosave_context_
        # override) — voir la remarque de l'utilisateur, "tous les
        # parametres du menu contextuel ne s'enregistrent pas
        # automatiquement dans la colonne de type".
        self._show_icon_override: bool | None = None
        self._show_preview_override: bool | None = None
        self._icon_size_override: int | None = None
        self._icon_padding_left_override: int | None = None
        self._text_padding_left_override: int | None = None
        _style_title_for_gate = style_title if style_title is not None else title
        if self._pin_active or _style_title_for_gate == "Type":
            if isinstance(layout_data.get("show_icon"), bool):
                self._show_icon_override = layout_data["show_icon"]
            if isinstance(layout_data.get("show_preview"), bool):
                self._show_preview_override = layout_data["show_preview"]
            raw_icon_size = layout_data.get("icon_size")
            if isinstance(raw_icon_size, (int, float)):
                self._icon_size_override = int(raw_icon_size)
            raw_icon_pad = layout_data.get("icon_padding_left")
            if isinstance(raw_icon_pad, (int, float)):
                self._icon_padding_left_override = int(raw_icon_pad)
            raw_text_pad = layout_data.get("text_padding_left")
            if isinstance(raw_text_pad, (int, float)):
                self._text_padding_left_override = int(raw_text_pad)
        # `source_dirs` (voir IN/OVER/OUT, PipelineBrowser.update_preview_
        # stack) : colonne dont le contenu est le MERGE de plusieurs
        # dossiers sources (ex. le "in" du Projet ET celui du Sous-projet
        # selectionnes) au lieu d'un dossier unique — voir refresh(), qui
        # bascule sur ce chemin quand source_dirs n'est pas None. `directory`
        # reste le repli utilise pour les operations a CIBLE unique (nouveau
        # dossier, deplacement par glisser-deposer) — voir leurs remarques
        # respectives. `source_labels` (meme longueur/ordre que source_dirs,
        # optionnel) : annotation "(projet)"/"(<nom du sous-projet>)" a
        # afficher a cote du nom de chaque entree venant de CETTE source
        # (voir ROLE_SOURCE_LABEL/refresh/_paint_unified_row) — voir la
        # remarque de l'utilisateur, "je veux une anotation a cote du nom du
        # repertoire ... s'il vient de projet ou de sous projet".
        self._source_dirs = source_dirs
        self._source_labels = source_labels
        # `user_width`/`on_resize` (voir PreviewColumn, MEME convention) :
        # pour une colonne RECONSTRUITE entierement a chaque navigation (le
        # groupe IN/OVER/OUT/LOGICIELS, voir PipelineBrowser.
        # update_preview_stack/_on_group_column_resized) — sans ce relais,
        # tout glisser de bordure serait perdu des le clic suivant, et les 4
        # colonnes du groupe ne resteraient pas alignees a la meme largeur
        # entre elles (voir la remarque de l'utilisateur, "les 4 colonnes
        # doivent avoir la meme largeur constamment"). None/None pour une
        # colonne NORMALE (comportement INCHANGE : `self._user_width` geree
        # localement par resize_update, voir sa remarque).
        self._user_width = user_width
        self._on_resize = on_resize
        # Relais de fin de glisser (groupe : enregistre la largeur commune des
        # colonnes pinnees voisines, voir PipelineBrowser._on_group_column_resize_end).
        self._on_resize_end = on_resize_end
        # `group_kind`/`on_reorder` : active le glisser-deposer de l'ENTETE
        # (pas le contenu de la liste, deja pris par FileListWidget) pour
        # interchanger la place de cette colonne avec une AUTRE colonne du
        # MEME groupe (voir PipelineBrowser.update_preview_stack/
        # _on_group_reorder, eventFilter plus bas) — voir la remarque de
        # l'utilisateur, "possible de pouvoir glisser deposer ces colonnes
        # afin de pouvoir interchanger leur place ?". None pour une colonne
        # NORMALE (pas de glisser d'en-tete du tout).
        self._group_kind = group_kind
        self._on_reorder = on_reorder
        # Boutons d'entete "Agrandir"/"Egaliser" (voir __init__ plus bas,
        # dans header_layout) — SEULEMENT pour une colonne du groupe
        # IN/OVER/OUT/LOGICIELS (group_kind is not None) : voir la remarque
        # de l'utilisateur, "dans les 4 colonnes ... je veux dans l'entete
        # un bouton qui me permette d'agrandir au maximum la fenetre en
        # cours et de minimiser les autres ... je veux un autre bouton pour
        # mettre les 4 colonnes a exactement la meme hauteur". Column ne
        # connait que SES PROPRES voisines via ces callbacks (MEME
        # principe que on_reorder/on_height_resize) — PipelineBrowser seule
        # a acces aux 4 colonnes du groupe a la fois.
        self._on_group_maximize = on_group_maximize
        self._on_group_equalize = on_group_equalize
        # `user_height`/`on_height_resize(_begin/_end)` : glisser le bord
        # BAS de CETTE colonne ne fait bouger qu'ELLE ET sa voisine
        # IMMEDIATEMENT SUIVANTE (voir PipelineBrowser.
        # _on_group_height_resize_begin/_on_group_height_resized, "vraie"
        # poignee de scission entre les 2 colonnes de part et d'autre) —
        # JAMAIS les autres, qui ne bougent ni de taille ni de position —
        # voir la remarque de l'utilisateur, "seulement deux colonnes
        # peuvent etre dimensionnees en hauteur ... les deux colonnes
        # concernees doivent etre seulement les deux colonnes de part et
        # d'autre de la zone de selection pour le slide". Column ne calcule
        # PAS la nouvelle hauteur elle-meme : elle transmet le DELTA brut
        # (voir height_resize_update), PipelineBrowser connait seule les 2
        # voisines et leurs hauteurs de depart pour repartir l'espace entre
        # elles sans toucher au reste. `fill_height` (voir
        # set_group_fill_height) : SEULE la DERNIERE colonne de l'ordre
        # courant (voir PipelineBrowser._group_column_order) l'a a True —
        # pas de hauteur fixe pour elle, reste etiree jusqu'en bas comme une
        # colonne normale, ni poignee de redimensionnement — voir la
        # remarque de l'utilisateur, "il est important que la derniere
        # colonne aille bien jusqu'en bas de la page".
        self._group_user_height = user_height
        self._on_height_resize = on_height_resize
        self._on_height_resize_begin = on_height_resize_begin
        self._on_height_resize_end = on_height_resize_end
        self._group_fill_height = fill_height
        self._group_height_resizing = False
        self._group_height_resize_start_y = 0
        self._group_height_resize_start_height = 0
        self._group_drag_start: QPoint | None = None
        # Fenetre "fantome" (voir _make_group_drag_ghost) affichee pendant
        # le glisser d'un en-tete du groupe, et decalage curseur/coin
        # superieur gauche fixe une fois pour toutes au demarrage du glisser
        # (voir eventFilter) : la ghost doit suivre le curseur au MEME point
        # relatif ou l'utilisateur a saisi la colonne, pas se recaler au
        # coin a chaque mouvement.
        self._group_ghost: QWidget | None = None
        self._group_ghost_offset = QPoint()
        self.is_active = False
        self.column_title = title
        # `display_title` (voir PreviewColumn, meme convention) : texte
        # d'entete affiche, SEPARE de `title`/self.column_title (la cle de
        # STYLE/COLUMN_SETTINGS par defaut) — permet a IN/OVER/OUT de
        # partager le style "Type" (liste plate, sans vignette ni icone
        # logiciel) tout en affichant leur propre libelle.
        # `style_title` (nouveau, voir PipelineBrowser.on_selected chaine
        # CONFIGUREE/settings_window "INTERMEDIAIRE") : repli symetrique a
        # `display_title`, mais pour la cle de STYLE cette fois — un niveau
        # de chaine CONFIGUREE (nom quelconque choisi par l'utilisateur, ex.
        # "test1") garde `column_title`/`display_title` = son propre nom
        # (identite/annotations "(test1)", voir update_preview_stack), MAIS
        # `style_title` = "Sous-projet" pour suivre le MEME reglage que
        # l'onglet General > Colonnes > INTERMEDIAIRE (voir la remarque de
        # l'utilisateur, "le tab sous projets doit maintenant se nommer
        # 'INTERMEDIAIRE', et doit controler toutes les colonnes entre celle
        # de projet et focus") plutot que de retomber sur le bucket
        # generique "Contenu" (voir _col_key) comme n'importe quel titre
        # inconnu. None (repli, TOUTE colonne EXISTANTE avant ce reglage —
        # Type/Projets/Sous-projet legacy/Logiciels/Contenu/groupe) : MEME
        # valeur que `title`, comportement rigoureusement INCHANGE.
        self.style_title = style_title if style_title is not None else title
        # Tuile a vignette de projet (ProjectTileDelegate, compte d'elements) :
        # SEULEMENT "Projets". Toute autre colonne (Sous-projet, niveaux
        # configures, contenu) se comporte comme les colonnes ouvertes apres
        # IN/OVER/OUT : RowDelegate, apercus des fichiers, meme menu.
        self.has_thumbnails = title == "Projets"
        # `is_focus_level` (voir update_preview_stack, group_columns du
        # groupe IN/OVER/OUT/LOGICIELS) : participation a la pile Focus,
        # DECOUPLEE de `has_thumbnails` (qui pilote le RENDU — tuile a
        # vignette vs liste plate) — un niveau de la chaine CONFIGUREE (voir
        # PipelineBrowser.on_selected/load_project_columns) peut etre en
        # liste plate ET quand meme contribuer a la pile Focus (son propre
        # toggle "Focus", voir ColumnConfigDialog). None (repli, colonnes
        # "normales" Type/Projets/Sous-projet/Logiciels/Contenu) : MEME
        # valeur que has_thumbnails — comportement D'AVANT ce reglage
        # INCHANGE (seules Projets/Sous-projet participaient a la pile) —
        # voir la remarque de l'utilisateur, "le toggle focus [est]
        # independant par colonne".
        self.is_focus_level = (title in THUMBNAIL_COLUMN_LABELS) if is_focus_level is None else is_focus_level
        # `show_dirs`/`show_files`/`omit_dirs`/`omit_files` (voir refresh(),
        # ColumnConfigDialog) : filtres de CONTENU d'un niveau de la chaine
        # CONFIGUREE — True/True/vide (comportement INCHANGE, tout est
        # affiche) pour toute colonne NORMALE.
        self._show_dirs = show_dirs
        self._show_files = False if title == "Type" else show_files
        self._omit_dirs = {n.lower() for n in omit_dirs}
        self._omit_files = {n.lower() for n in omit_files}
        # Repli/depli (voir set_collapsed) : toute colonne de navigation
        # NORMALE (group_kind=None — Type/Projets/tout niveau configure,
        # PAS une colonne fantome du groupe IN/OVER/OUT/LOGICIELS) est
        # structurellement repliable — c'est PipelineBrowser.
        # _apply_project_columns_collapsed qui decide LESQUELLES replier
        # (les N premieres de self.columns, voir _chain_expected_total),
        # pas un titre fixe (voir la remarque de l'utilisateur, "toutes les
        # colonnes avant les colonnes de focus", N quelconque).
        self.collapsible = group_kind is None
        self.collapsed = False
        self._expanded_width = None
        self._width_anim = None

        self.title_label = QLabel(display_title or title)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")

        # objectName + selecteur ID : voir la remarque sur #TitleBar dans
        # PipelineBrowser — sans lui, title_label heriterait du border-
        # bottom nu et se retrouverait souligne sur sa largeur de texte au
        # lieu du filet courant sur toute la colonne.
        #
        # header (exterieur, hauteur fixe, JAMAIS stylise) enveloppe
        # header_fill (interieur, c'est LUI qui porte le fond/rayon/cadre de
        # header_qss) avec une marge = HEADER_PADDING sur les 4 cotes : le
        # padding regle "l'espace entre le fond colore et les bords de la
        # colonne" (voir Parametres > Entetes), PAS la marge du texte a
        # l'interieur du fond (qui reste fixe, voir header_fill_layout
        # ci-dessous) — a ne pas confondre, voir la remarque de
        # l'utilisateur qui a precise ce point.
        header = QWidget()
        header.setObjectName("ColumnHeaderOuter")
        header.setFixedHeight(scaled(ui_state.HEADER_HEIGHT))
        self.header = header
        header_outer_layout = QVBoxLayout(header)
        # minimum=0 (voir la docstring de scaled) : un padding regle a 0 doit
        # rester 0, pas remonter a 1px apres arrondi.
        header_outer_layout.setContentsMargins(scaled(ui_state.HEADER_PADDING, 0), scaled(ui_state.HEADER_PADDING, 0),
                                                scaled(ui_state.HEADER_PADDING, 0), scaled(ui_state.HEADER_PADDING, 0))
        header_outer_layout.setSpacing(0)

        header_fill = QWidget()
        header_fill.setObjectName("ColumnHeader")
        header_fill.setStyleSheet(header_qss("ColumnHeader"))
        self.header_fill = header_fill
        header_layout = QHBoxLayout(header_fill)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        # "Agrandir"/"Egaliser" (voir __init__, on_group_maximize/
        # on_group_equalize) : SEULEMENT sur une colonne du groupe
        # IN/OVER/OUT/LOGICIELS — voir la remarque de l'utilisateur, "dans
        # les 4 colonnes ... un bouton qui me permette d'agrandir au
        # maximum ... et un autre bouton pour mettre les 4 colonnes a
        # exactement la meme hauteur". Boutons TEXTE (pas d'icone dediee
        # existante) — meme taille/meme style transparent que la punaise.
        if self._group_kind is not None:
            def _group_header_btn(text: str, tooltip: str, handler) -> QPushButton:
                btn = QPushButton(text)
                btn.setFlat(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFocusPolicy(Qt.NoFocus)
                btn.setFixedSize(18, 18)
                btn.setFont(font(11, 700))
                btn.setToolTip(tooltip)
                btn.setStyleSheet(
                    "QPushButton { background: transparent; border: none; padding: 0; "
                    f"color: {C['label']}; }}"
                    "QPushButton:hover { background: rgba(255,255,255,0.12); border-radius: 3px; "
                    f"color: {C['text']}; }}"
                )
                btn.clicked.connect(handler)
                header_layout.addWidget(btn)
                return btn

            if on_group_maximize is not None:
                _group_header_btn(
                    "⤢", "Agrandir cette colonne au maximum, reduire les autres a leur contenu",
                    lambda: on_group_maximize(self._group_kind))
            if on_group_equalize is not None:
                _group_header_btn(
                    "≡", "Repartir les 4 colonnes du groupe a hauteur egale",
                    lambda: on_group_equalize())
        # Punaise (voir _toggle_pin/_pin_icon_pixmap) : sur TOUTE colonne
        # SAUF "Type" et les colonnes Focus (celles-ci ne passent jamais
        # par Column, voir PreviewColumn/_PreviewBlock — exclusion donc
        # automatique, aucune condition a poser ici pour elles) — voir la
        # remarque de l'utilisateur, "je viens de te coller deux icones
        # que j'aimerai que tu places en haut a droite de chaque colonne
        # sauf : colonne type, colonnes focus".
        self._pin_btn = None
        if title != "Type":
            pin_btn = QPushButton()
            pin_btn.setFlat(True)
            pin_btn.setCursor(Qt.PointingHandCursor)
            pin_btn.setFocusPolicy(Qt.NoFocus)
            pin_btn.setFixedSize(18, 18)
            pin_btn.setIconSize(QSize(14, 14))
            pin_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 0; }"
                "QPushButton:hover { background: rgba(255,255,255,0.12); border-radius: 3px; }"
            )
            pin_btn.setToolTip("Fige la largeur/hauteur de ligne de ce dossier (voir Parametres)")
            pin_btn.clicked.connect(self._toggle_pin)
            self._pin_btn = pin_btn
            header_layout.addWidget(pin_btn)
        self._refresh_pin_icon()
        header_outer_layout.addWidget(header_fill)

        self.list = FileListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        # Uniforme seulement pour les colonnes a vignettes (toutes les lignes
        # font PROJECT_ROW_HEIGHT) : dans les colonnes classiques, un fichier
        # image peut desormais prendre une hauteur differente des autres
        # lignes (voir RowDelegate), donc les hauteurs n'y sont plus uniformes.
        self.list.setUniformItemSizes(self.has_thumbnails)
        # L'espacement entre lignes est gere a la main dans les delegates
        # (voir ROW_SPACING) plutot que via QListView.setSpacing(), qui
        # ajoute la valeur des DEUX cotes de chaque ligne (donc un ecart reel
        # de 2x la valeur demandee, et jamais de valeur impaire exacte).
        self.list.setSpacing(0)
        self.list.setItemDelegate(ProjectTileDelegate(self) if self.has_thumbnails else RowDelegate(self))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setViewportMargins(0, 0, 0, 0)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.customContextMenuRequested.connect(self._on_context_menu)

        # self.card : porte le fond/la bordure/le rayon REELS de la colonne
        # (voir refresh_colors/app_style.column_frame_qss) — self, lui, ne
        # sert plus qu'a reserver l'EMPLACEMENT plein (largeur allouee,
        # cible du redimensionnement a la souris) et a inserer ce card en
        # retrait de Padding px sur chaque cote (voir refresh_header/
        # app_style.column_padding_for) : une "carte flottante" qui peut
        # RETRECIR sans deplacer la frontiere de redimensionnement ni les
        # colonnes voisines — voir la remarque de l'utilisateur, "je veux
        # que le fond de la colonne se replie ... pour toutes les colonnes
        # de l'appli".
        self.card = _ColumnCard()
        self.card.setObjectName("ColumnCard")
        # Voir _RoundedCornersEffect : remplace setMask() (crenele, voir la
        # remarque de l'utilisateur "les arrondis sont degueulasse, ils ne
        # sont pas lisses") par un decoupage anti-aliase.
        self._card_effect = _RoundedCornersEffect(self.card)
        self.card.setGraphicsEffect(self._card_effect)

        # self._content : porte l'entete/la liste, en retrait de la bordure
        # (voir refresh_header, reserve()) DANS self.card — separe de
        # self.card pour lui appliquer son PROPRE decoupage arrondi (voir
        # self._content_effect ci-dessous, rayon RETRECI de l'epaisseur de
        # bordure, _radius_shrink, meme calcul que le clip du FOND dans
        # _paint_bordered_rect) : une simple marge DROITE/UNIFORME (voir
        # reserve()) ne degage assez de place que le long des segments
        # DROITS du cadre — a un COIN arrondi, l'anneau de la bordure
        # plonge plus profondement vers le centre (jusqu'a `radius` px en
        # diagonale) que cette marge (juste `thickness` px) ne le prevoit,
        # laissant l'entete/la liste recouvrir le trace courbe de la
        # bordure a chaque coin — voir la remarque de l'utilisateur,
        # capture a l'appui, "il n'y a toujours pas de bordure dans les
        # angles".
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_effect = _RoundedCornersEffect(self._content)
        self._content.setGraphicsEffect(self._content_effect)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(header)
        # Espace REGLABLE entre l'entete et le 1er item de la liste (voir
        # Colonnes > Texte > "Espace avant le premier item"/refresh_header,
        # qui pilote sa hauteur) — voir la remarque de l'utilisateur,
        # "ajoute un slider qui cree un espace entre l'entete et le
        # premier item de la liste". Widget dedie (PAS un simple padding
        # sur le TOP de la liste elle-meme) : un padding QListWidget
        # colorerait cet espace comme le fond de la liste (C['void']),
        # pas comme celui, distinct, de la colonne SOUS l'entete — voir la
        # meme remarque que column_frame_qss pour ce fond.
        self.header_gap_spacer = QWidget()
        self.header_gap_spacer.setStyleSheet("background: transparent;")
        self.header_gap_spacer.setFixedHeight(0)
        content_layout.addWidget(self.header_gap_spacer)
        content_layout.addWidget(self.list, 1)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(0, 0, 1, 0)   # voir refresh_header, qui l'ajuste a l'epaisseur de bordure
        layout.setSpacing(0)
        layout.addWidget(self._content)
        self._column_layout = layout

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, qui l'ajuste a Padding
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.card)
        self._outer_layout = outer_layout

        self.setFixedWidth(self._pin_column_width or self._user_width or col_width(title))
        # Hauteur FIXE (voir GROUP_COLUMN_DEFAULT_HEIGHT) SEULEMENT pour une
        # colonne du groupe IN/OVER/OUT/LOGICIELS QUI N'EST PAS la derniere
        # de l'ordre courant (voir fill_height/set_group_fill_height) : une
        # colonne NORMALE (fill_height=False ET group_kind=None) n'appelle
        # jamais setFixedHeight, elle reste etiree sur toute la hauteur
        # disponible par columns_layout (comportement INCHANGE).
        if self._group_kind is not None and not fill_height:
            self.setFixedHeight(self._group_user_height or GROUP_COLUMN_DEFAULT_HEIGHT)
        self.setObjectName("Column")
        # Transparent EXPLICITE (self ne peint plus rien lui-meme desormais,
        # voir self.card ci-dessus) : sans lui, ce QWidget nu heriterait du
        # fond OPAQUE par defaut de la feuille de style globale, masquant le
        # fond de #ColumnsHost (voir PipelineBrowser.refresh_colors) la ou
        # Padding fait justement RETRECIR self.card en dessous de la pleine
        # largeur/hauteur de self.
        self.setStyleSheet("#Column { background: transparent; }")

        # Redimensionnement par glisser-deposer sur la bordure droite.
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        # Redimensionnement de la HAUTEUR des lignes : Ctrl + clic entre 2
        # lignes + glisser (voir row_resize_begin/_in_row_resize_zone) —
        # voir la remarque de l'utilisateur, "je veux pouvoir redimensionner
        # la hauteur des lignes directement dans l'interface ... appuyer sur
        # la touche controle du clavier et cliquer entre deux lignes et
        # glisser".
        self._row_resizing = False
        self._row_resize_start_y = 0
        self._row_resize_start_height = 0
        self._row_resize_row_index = -1
        # Limite doItemsLayout() (recalcule le sizeHint() de CHAQUE ligne,
        # pas un simple repaint) a ~60/s pendant un glisser (largeur OU
        # hauteur de ligne) : sans ca, il se rejoue a CHAQUE evenement
        # MouseMove brut, potentiellement bien plus de 60/s sur une souris a
        # haut taux de rafraichissement — voir la remarque de l'utilisateur,
        # "il y a des ralentissements dans les animations, optimise un
        # maximum". Front montant (1er mouvement applique tout de suite) +
        # purge finale (_flush_layout_throttle, pour ne jamais rater le tout
        # dernier mouvement avant le prochain palier).
        self._layout_throttle_timer = QTimer(self)
        self._layout_throttle_timer.setSingleShot(True)
        self._layout_throttle_timer.setInterval(16)
        self._layout_throttle_timer.timeout.connect(self._flush_layout_throttle)
        self._layout_pending = False
        self.setMouseTracking(True)
        header.setMouseTracking(True)
        header.installEventFilter(self)
        # `_group_header_widgets` : header_fill (fond/rayon, voir plus haut)
        # ET les 2 labels COUVRENT ENTIEREMENT header (header_fill occupe
        # tout header, moins juste le Padding d'entete, souvent 0) — sans
        # installer AUSSI le filtre sur eux, la souris ne touche quasiment
        # JAMAIS `header` lui-meme (seulement l'etroite marge de Padding, si
        # non nulle) : le glisser d'un en-tete du groupe IN/OVER/OUT/
        # LOGICIELS ne demarrait alors QUE par hasard, selon le pixel exact
        # survole — voir la remarque de l'utilisateur, "le changement ne
        # fonctionne pas tout le temps, il est des fois impossible de faire
        # le changement" — MEME piege/MEME correctif que PreviewColumn.
        # install_resize_filter pour la bordure de redimensionnement.
        # Assigne AVANT installEventFilter() : celui-ci peut redeclencher
        # eventFilter() de maniere SYNCHRONE (evenements internes Qt) avant
        # meme la fin de cette boucle — sans l'attribut deja pose, ce 1er
        # appel plantait avec AttributeError (_group_header_widgets
        # manquant).
        if self._group_kind is not None:
            self._group_header_widgets = (header, header_fill, self.title_label)
            for w in self._group_header_widgets:
                w.setMouseTracking(True)
                w.installEventFilter(self)
        else:
            self._group_header_widgets = ()
        self.list.viewport().installEventFilter(self)
        # La scrollbar verticale est un widget a part, positionne PAR-DESSUS
        # le bord droit du viewport des que la liste deborde : sans son
        # propre eventFilter, ses clics/mouvements ne passaient jamais par
        # _in_resize_zone, rendant la bordure de redimensionnement
        # inaccessible chaque fois qu'une scrollbar est visible.
        self.list.verticalScrollBar().installEventFilter(self)

        # Rejoue immediatement le style au-dessus (header_fill/le cadre de
        # cette colonne, tous 2 fixes en dur juste plus haut) : necessaire
        # pour cette colonne, dont le style EFFECTIF (general ou surcharge,
        # voir app_style.column_style_for) peut deja differer du style
        # partage par les autres colonnes des la construction.
        self.refresh_header()
        self.refresh_colors()

        self.refresh()

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

    @property
    def is_resizing(self) -> bool:
        return self._resizing

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
                if not self._in_resize_zone(local_x):
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
                    if _step_badge_rect(row_rect, preview_left).contains(pos):
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

    def refresh(self):
        current = self.current_path()
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
                entries.extend((path, label, step, False) for path in list_entries(source))
                # Raccourcis propres a CHAQUE source (voir _add_shortcut, qui
                # enregistre dans la source choisie) : sinon un raccourci cree
                # depuis IN/OVER/OUT/LOGICIELS restait invisible.
                for shortcut in load_shortcuts(source):
                    target = Path(shortcut.get("target", ""))
                    if target.is_dir():
                        entries.append((target, label, step, True))
                        if shortcut.get("name"):
                            aliases[str(target)] = str(shortcut["name"])
            if self._only_recognized_software:
                # Uniquement des REPERTOIRES DE LOGICIEL reconnus (voir
                # software_icon_key/app_style.custom_softwares) — pas de
                # fichier isole ni de dossier non reconnu qui trainerait
                # dans le dossier de travail — voir la remarque de
                # l'utilisateur, "dans la colonne logiciel, il ne doit y
                # avoir que des repertoires logiciel".
                entries = [
                    (path, label, step, is_shortcut) for path, label, step, is_shortcut in entries
                    if path.is_dir() and software_icon_key(path.name) is not None
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
            entries = [(path, None, None, False) for path in list_entries(self.directory, _STATUS_FOLDER_SET)]
            # Raccourcis (voir load_shortcuts/ROLE_IS_SHORTCUT, Column._on_
            # context_menu "Ajouter un raccourci") : dossiers d'AILLEURS sur
            # le disque, affiches comme s'ils etaient physiquement ICI —
            # propres a CE dossier (jamais pour une colonne du groupe IN/
            # OVER/OUT/LOGICIELS, source_dirs deja exclu par ce `else`) —
            # voir la remarque de l'utilisateur, "faire comme si il etait
            # au meme endroit que les autres repertoires de l'emplacement
            # actuel". Cible manquante (dossier deplace/supprime depuis) :
            # ignoree silencieusement, pas d'entree fantome.
            for shortcut in load_shortcuts(self.directory):
                target = Path(shortcut.get("target", ""))
                if target.is_dir():
                    entries.append((target, None, None, True))
                    if shortcut.get("name"):
                        aliases[str(target)] = str(shortcut["name"])
        # Filtres de contenu (voir __init__ show_dirs/show_files/omit_dirs/
        # omit_files, ColumnConfigDialog) : SEULEMENT pour un niveau de la
        # chaine CONFIGUREE — toute colonne NORMALE garde ses valeurs par
        # defaut (True/True/vide), donc ce bloc ne change RIEN pour elle
        # (le `if` court-circuite direct au cas commun, entries INCHANGE).
        if (not self._show_dirs or not self._show_files or self._omit_dirs or self._omit_files
                or GLOBAL_OMIT_DIR_NAMES or GLOBAL_OMIT_FILE_NAMES or GLOBAL_OMIT_FILE_EXTENSIONS):
            filtered = []
            for path, label, step, is_shortcut in entries:
                is_dir = path.is_dir()
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
        for path, label, step, is_shortcut in entries:
            # Un raccourci peut porter un NOM D'AFFICHAGE (clic droit > Renommer le raccourci) : le
            # dossier cible garde le sien.
            item = QListWidgetItem(aliases.get(str(path)) if is_shortcut and str(path) in aliases else path.name)
            item.setData(ROLE_PATH, str(path))
            is_dir = path.is_dir()
            item.setData(ROLE_ISDIR, is_dir)
            item.setData(ROLE_SOURCE_LABEL, label)
            item.setData(ROLE_SOURCE_STEP, step)
            item.setData(ROLE_IS_SHORTCUT, is_shortcut)
            meta = ""
            if not is_dir:
                try:
                    meta = human_size(path.stat().st_size)
                except OSError:
                    pass
            elif self.has_thumbnails:
                count = count_entries(path, _STATUS_FOLDER_SET)
                meta = f"{count} element{'s' if count != 1 else ''}"
            item.setData(ROLE_META, meta)
            self.list.addItem(item)
            if current and path == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def relayout(self, do_layout: bool = True):
        """Reapplique la mise en page (tailles de ligne) apres un changement
        de reglage purement cosmetique (police, hauteur de ligne...), SANS
        retourner sur le disque : le contenu deja charge (noms, tailles,
        vignettes) reste valable, seul son rendu change. Utilise par
        PipelineBrowser.refresh_all_columns(rescan=False), notamment pendant
        la previsualisation en direct de la fenetre de parametres, ou un
        column.refresh() complet (rescan du dossier, y compris le comptage
        recursif des colonnes a vignettes) serait rejoue a chaque cran de
        slider pour rien.

        `do_layout=False` (voir PipelineBrowser._apply_settings, qui compare
        col_row_height()/col_spacing() avant/apres apply_all_settings) saute
        le doItemsLayout() — le SEUL poste vraiment couteux ici (recalcule le
        sizeHint() de CHAQUE ligne visible) — quand ce cran de slider n'a
        PAS touche a la hauteur/l'espacement des lignes de CETTE colonne
        (couleur, bordure, rayon, padding de selection...)."""
        if do_layout:
            self.list.doItemsLayout()

    def refresh_colors(self):
        """Reapplique les couleurs (voir C, mutable via app_style.set_color)
        aux qss fixes une fois pour toutes a la construction — necessaire
        car un changement de couleur depuis la fenetre de parametres ne
        retouche pas les widgets deja construits (voir la remarque sur
        set_color dans app_style.py)."""
        # Style APPLIQUE POUR DE VRAI a TOUTE colonne desormais (voir
        # app_style.column_header_qss/column_frame_qss — le style general
        # Colonnes/Entetes, "Type" seule pouvant le SURCHARGER depuis
        # Colonnes > Type, voir SettingsWindow._build_column_type_page),
        # pas seulement l'apercu de la fenetre de parametres comme avant —
        # voir la remarque de l'utilisateur, "je veux que tu en fasse de
        # meme pour toute les colonnes de l'appli. les settings doivent
        # refletter a 100% ce qui se passe dans l'appli".
        self.header_fill.setStyleSheet(column_header_qss("ColumnHeader", self.style_title))
        frame = column_frame_style(self.style_title, self._suppress_left())
        # scaled() ICI, sur le MEME dict que celui repasse tel quel au
        # masque (voir _update_card_mask, qui relit self.card._radius
        # plutot que de recalculer independamment) : sans ca, peinture et
        # masque pouvaient utiliser 2 rayons LEGEREMENT differents des que
        # l'echelle d'interface (Application > Scale) n'est pas 100%.
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        # scaled() sur l'epaisseur AUSSI (pas seulement le rayon ci-dessus) :
        # refresh_header reserve deja scaled(border_thickness) comme marge
        # pour cette bordure — la peindre ICI avec l'epaisseur BRUTE (non
        # scaled) desaccordait les deux des que l'echelle d'interface
        # (Application > Scale) n'est pas 100%, laissant un filet trop fin/
        # epais par rapport a la marge qui lui est reservee.
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        self._update_card_mask()
        # PAS de reapplication de self.title_label ici (BUG corrige, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette ligne existait AVANT le systeme de
        # surcharge par titre (header_font_color/family/bold/italic/taille,
        # voir refresh_header ci-dessous) et l'ecrasait INCONDITIONNELLEMENT
        # avec la couleur GENERIQUE role_color('colhead', ...) — refresh_
        # colors() est TOUJOURS appelee APRES refresh_header() (voir
        # PipelineBrowser._apply_settings/add_column/Column.__init__), donc
        # toute surcharge de "Couleur du titre" pour CETTE colonne (Colonnes
        # > Type/Projets/.../Logiciels/IN/OVER/OUT/Inspecteur) etait
        # silencieusement annulee des le refresh SUIVANT. refresh_header()
        # gere deja CE style correctement (voir sa remarque de tete, `s =
        # column_style_for(self.style_title)`), y compris le cas SANS
        # surcharge (repli sur la valeur GENERALE de "header_font_color",
        # deja identique par defaut a l'ancienne couleur fixe ici) : rien
        # d'autre a faire.

    def _suppress_left(self) -> bool:
        """Voir _column_suppress_left (module-level, factorisee pour etre
        partagee avec PreviewColumn)."""
        return _column_suppress_left(self, self.style_title)

    def refresh_header(self):
        """Reapplique hauteur/padding/police de l'entete (voir HEADER_HEIGHT/
        HEADER_PADDING, role 'colhead') — reglable en direct depuis
        Parametres > Entetes. HEADER_PADDING est la marge de header (voir
        __init__) : l'espace entre le fond colore (header_fill) et les
        bords de la colonne, pas la marge du texte a l'interieur du fond.

        Style EFFECTIF de CETTE colonne (voir app_style.column_style_for —
        general, ou surcharge Colonnes > Type pour "Type") plutot que les
        globals HEADER_HEIGHT/HEADER_PADDING partages a l'ancienne."""
        s = column_style_for(self.style_title)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", ui_state.HEADER_HEIGHT))
        padding = int(s.get("header_padding", ui_state.HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)   # 0 = valeur reglee valide (voir scaled)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/hauteur du titre (voir COLUMN_FRAME_KEYS/
        # app_style.column_style_for, Settings > General > Colonnes >
        # Entetes — OU sa surcharge Colonnes > Type/Projets/Sous-projets,
        # voir la remarque de l'utilisateur, "mets a jour egalement les
        # colonnes overidees ... avec tous les nouveaux parametres de
        # general") — "" (Systeme, aucune surcharge choisie) retombe
        # EXACTEMENT sur le role "colhead" d'origine (_resolve_font_family,
        # fallback_role) : comportement INCHANGE tant que l'utilisateur ne
        # personnalise pas.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.title_label.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.title_label.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")
        # Padding droit des icones (voir __init__, bouton punaise) :
        # marge droite DIRECTEMENT pilotee par ce reglage (PAS 10 + la
        # valeur — voir la remarque de l'utilisateur, "je veux que la
        # valeur 0 soit tres collee contre le bord de la colonne") —
        # seulement si une icone existe reellement sur cette colonne
        # (jamais "Type"/les colonnes Focus, voir __init__).
        if self._pin_btn is not None:
            self.header_fill.layout().setContentsMargins(
                10, 0, int(s.get("header_icon_right_padding", 0)), 0)
        # Espace avant le 1er item (voir __init__/self.header_gap_spacer,
        # Colonnes > Texte) : cle "item_*", donc seulement definie pour
        # "Type" (voir app_style.column_style_for) — 0 pour toute autre
        # colonne, comme avant ce reglage.
        self.header_gap_spacer.setFixedHeight(scaled(int(s.get("item_header_gap", 0) or 0), 0))
        # Bordure du CADRE : reserve, sur CHAQUE cote EFFECTIVEMENT peint
        # (voir column_frame_qss/_suppress_left — meme regle ICI pour le
        # cote gauche), la meme epaisseur que celle reellement dessinee la
        # — sinon le contenu (liste/entete, colle a self.card sans marge)
        # recouvrirait le filet, cote par cote — voir _TableFrame dans
        # settings_window.py, meme necessite/meme raison, deja documentee
        # la-bas. 1er essai : UNE seule marge, a droite (l'ancien filet
        # unique code en dur) — insuffisant des que les 4 cotes peuvent
        # etre actives independamment, voir la remarque de l'utilisateur,
        # "quand je met une valeur de padding, il n'y a pas de bordure sur
        # tous les cotes de la colonne" (le filet HAUT/GAUCHE/BAS restait
        # bien peint par la QSS, mais aussitot recouvert par l'entete/la
        # liste, qui n'en reservaient pas la place).
        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._column_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        # Padding de la colonne, PAR COTE (voir settings_window.
        # _ColumnPreview.setPadding/Colonnes > Colonnes > Padding) : fait
        # RETRECIR self.card (fond + bordure) de ce nombre de px sur chaque
        # cote choisi, PAS un simple retrait de son contenu — voir la
        # remarque de l'utilisateur, "je veux que le fond de la colonne se
        # replie". Cote GAUCHE mis a 0 si cette colonne est COLLEE a une
        # voisine (meme regle que _suppress_left pour la bordure) : sinon
        # l'ecart VISIBLE entre 2 colonnes collees cumulait le padding
        # DROIT de celle de gauche ET le padding GAUCHE de celle de
        # droite — le double de la valeur reglee — voir la remarque de
        # l'utilisateur, "la distance entre 2 colonnes doit etre la valeur
        # du padding et non celle du padding*2".
        col_pad = dict(column_padding_for(self.style_title))
        if self._suppress_left():
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()

    def _refresh_pin_icon(self):
        """Applique l'icone punaise (01 par defaut, 02 si active, voir
        _toggle_pin/_pin_icon_pixmap) — no-op sur "Type" (pas de bouton,
        voir __init__)."""
        if self._pin_btn is not None:
            self._pin_btn.setIcon(QIcon(_pin_icon_pixmap(self._pin_active, 14)))

    def _toggle_pin(self):
        """Punaise d'en-tete — voir __init__/effective_row_height, la
        remarque de l'utilisateur, "punaise_02.png lorsque l'on clique
        dessus, les valeurs de dimensions de colonnes et de lignes sont
        alors overridees par les valeurs du json se trouvant a la base du
        repertoire en cours ... lorsque l'on rappuie sur cette icone,
        l'icone redevient punaise_01.png et prend en compte les valeurs
        par defaut des settings". Desactiver NE SUPPRIME PAS les valeurs
        enregistrees (juste `pinned: False`) : rappuyer plus tard restaure
        exactement la largeur/hauteur figees precedemment, sans avoir a
        redimensionner de nouveau a la main."""
        if self._pin_active:
            self._pin_active = False
            self._pin_column_width = None
            self._pin_row_height = None
            _update_layout_setting(self.directory, "pinned", False)
        else:
            self._pin_active = True
            self._pin_column_width = self.width()
            self._pin_row_height = self.effective_row_height()
            data = load_layout_settings(self.directory)
            data["pinned"] = True
            data["pinned_column_width"] = self._pin_column_width
            data["pinned_row_height"] = self._pin_row_height
            save_layout_settings(self.directory, data)
        self._refresh_pin_icon()
        self.setFixedWidth(self._pin_column_width or self._user_width or col_width(self.style_title))
        self.list.doItemsLayout()
        if self._on_resize is not None:
            # Colonne du groupe : les voisines suivent la largeur (commune).
            self._on_resize(self.width())

    def _update_card_mask(self):
        """Decoupe VRAIMENT self.card (fond + TOUS ses enfants — entete ET
        liste) a la silhouette EXACTE de son rayon d'angle — voir la
        remarque de l'utilisateur, capture a l'appui, "le fond et l'entete
        passent toujours devant la bordure de la colonne" : reserver une
        marge DROITE (voir refresh_header) ne protege que les segments
        DROITS des bords, jamais la zone COURBE d'un coin — l'entete
        (coins hauts) ET la liste (coins bas, ses propres lignes restant
        toujours des rectangles PLEINS, sans rayon) y debordaient donc
        encore des que column_border_radius > 0. Qt ne clippe jamais
        automatiquement des enfants au rayon QSS de leur parent — voir
        _TableFrame dans settings_window.py, qui avait DEJA essaye puis
        ABANDONNE un masque pour cette meme raison : un decoupage BINAIRE,
        non anti-aliase, degrade le rendu du coin arrondi lui-meme. Ce
        compromis reste neanmoins prefere ICI (une seule silhouette
        exterieure, generalement grande, contre de nombreux petits coins de
        ligne pour _TableFrame) plutot que de laisser la bordure invisible
        — voir la meme remarque de l'utilisateur, qui persiste malgre 2
        correctifs precedents (reserve de marge, "0px solid transparent")
        insuffisants a eux seuls."""
        # self.card._radius (deja SCALE, voir refresh_colors) — PAS
        # recalcule independamment ici : garantit le MEME rayon que celui
        # reellement peint (voir _ColumnCard.paintEvent/la docstring de
        # cette classe), plutot que 2 sources qui pourraient diverger.
        # activate() FORCE la resolution immediate du layout (largeur/
        # hauteur de self.card) : setContentsMargins()/setFixedWidth()
        # n'appliquent la nouvelle geometrie qu'au PROCHAIN cycle de
        # peinture (activation PARESSEUSE de Qt) — sans ce forçage,
        # self.card.rect() ci-dessous pouvait encore renvoyer l'ANCIENNE
        # taille au moment ou le masque est calcule, produisant un masque
        # decale/trop grand par rapport a ce qui est reellement peint —
        # voir la remarque de l'utilisateur, capture a l'appui, "les
        # arrondis ne sont pas du tout recouvert par la bordure".
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        # Desactive CE decoupage-ci des qu'une bordure existe (thickness>0) :
        # dans ce cas, _ColumnCard.paintEvent peint DEJA fond+bordure
        # exactement dans le silhouette voulu (voir _paint_bordered_rect,
        # qui a son PROPRE antialiasing sur le trait), et self._content est
        # DEJA reduit plus etroit par _content_effect ci-dessous (donc
        # jamais debordant) — ce masque-ci n'a plus RIEN a proteger, il ne
        # fait plus que reappliquer une 2e passe d'antialiasing PAR-DESSUS
        # celle, deja correcte, du trait — exactement au MEME rayon, donc
        # sur les MEMES pixels de transition : les 2 alphas partiels se
        # MULTIPLIENT plutot que de s'additionner, ce qui faisait carrement
        # disparaitre la bordure dans la courbe — voir la remarque de
        # l'utilisateur, capture a l'appui, "la bordure disparait
        # completement dans l'arrondi de l'angle". Reste ACTIF quand il n'y
        # a PAS de bordure (thickness<=0) : LA, _content_effect est lui-meme
        # desactive (voir plus bas) et ce masque-ci redevient le SEUL a
        # empecher l'entete/la liste (coins carres) de deborder du fond
        # arrondi.
        self._card_effect.setEnabled(self.card._thickness <= 0)
        # self._content (entete+liste) : decoupe a un rayon RETRECI de
        # l'epaisseur de bordure REELLEMENT peinte (self.card._thickness,
        # deja scaled — voir refresh_colors) — MEME formule que le clip du
        # FOND dans _paint_bordered_rect (_radius_shrink(radius, thickness))
        # — pour rester en retrait de l'anneau de la bordure jusque dans
        # les coins, pas seulement le long des segments droits (voir
        # reserve()/la docstring de self._content ci-dessus)."""
        # +1px de MARGE SUPPLEMENTAIRE (au-dela du strict inner_radius
        # geometrique) : self._content (coins CARRES, jamais son propre
        # rayon — voir column_header_qss, "le rognage visuel est deja
        # garanti par ce decoupage") est un ENFANT peint PAR-DESSUS
        # self.card (Z-order Qt normal) — a epaisseur de bordure FAIBLE
        # (1px), le bord antialiase de CE decoupage (inner_radius) et celui,
        # deja antialiase, du trait de bordure (juste 1px plus loin, a
        # `radius`) tombent quasiment sur LES MEMES pixels : le contenu,
        # AU-DESSUS, y "mangeait" alors la bordure au lieu de s'arreter
        # juste avant elle — voir la remarque de l'utilisateur, capture a
        # l'appui, "la bordure disparait completement dans l'arrondi de
        # l'angle". Cette marge laisse un peu d'air entre les 2 contours
        # pour que la bordure garde une zone a elle, sans concurrence.
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._content_effect.setRadius(_radius_dict(inner_radius))
        # Desactive ce 2e decoupage des qu'il n'a plus rien a proteger
        # (aucune bordure reellement peinte, thickness<=0) : inner_radius
        # egale alors radius au chiffre pres, donc self._content (deja a
        # l'interieur du silhouette de self.card, qui l'enveloppe ET tous
        # ses enfants dans SA PROPRE passe d'antialiasing via _card_effect)
        # n'a plus besoin d'etre roule une 2e fois — un 2e QGraphicsEffect,
        # rasterise dans SA PROPRE pixmap hors-ecran independante, ne
        # retombe JAMAIS EXACTEMENT sur les memes pixels que le 1er (chaque
        # passe d'antialiasing calcule sa propre couverture sous-pixel) :
        # 2 arrondis quasi identiques mais jamais superposables au pixel
        # pres laissaient un lisere visible a chaque coin — voir la
        # remarque de l'utilisateur, "je veux que le lissage de l'arrondi
        # soit parfait ce qui est loin d'etre le cas". Toujours REACTIVE
        # des qu'une bordure existe a nouveau (thickness>0) : LA, le rayon
        # interieur retrecit vraiment et reste indispensable (voir la
        # docstring de self._content plus haut, "l'entete/la liste
        # recouvrait le trace courbe de la bordure a chaque coin").
        self._content_effect.setEnabled(self.card._thickness > 0)

    def current_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(ROLE_PATH)) if item else None

    def reselect_current(self):
        """Rejoue la selection de la ligne courante (voir FileListWidget.
        mouseReleaseEvent) : ferme les colonnes a droite et reaffiche son contenu."""
        item = self.list.currentItem()
        if item is not None:
            self.selected.emit(self, Path(item.data(ROLE_PATH)))

    def _on_current_changed(self, item, _previous):
        self.selected.emit(self, Path(item.data(ROLE_PATH)) if item else None)

    def _on_double_clicked(self, item):
        self.activated.emit(Path(item.data(ROLE_PATH)))

    def _on_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            menu = QMenu(self)
            menu.setFont(font(11, 400))
            act_new_folder = menu.addAction("Nouveau dossier")
            act_new_text_file = menu.addAction("Nouveau document texte") if self._show_files else None
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
        menu = QMenu(self)
        menu.setFont(font(11, 400))
        act_open = menu.addAction("Ouvrir")
        act_rename = menu.addAction("Renommer le raccourci…" if is_shortcut else "Renommer")
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        act_render_preview_low = None
        act_render_preview_high = None
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

        menu.addSeparator()
        act_copy_file = menu.addAction("Copier")
        act_copy_path = menu.addAction("Copier le chemin")
        menu.addSeparator()
        # Meme menu qu'un dossier standard (renommer/image/copier agissent sur
        # le dossier CIBLE) ; "Retirer le raccourci" retire seulement l'ENTREE.
        act_remove_shortcut = menu.addAction("Retirer le raccourci") if is_shortcut else None
        act_add_shortcut = menu.addAction("Ajouter un raccourci...")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is act_open:
            self.activated.emit(path)
        elif chosen is act_rename:
            if is_shortcut:
                self._rename_shortcut(path, item.text())
            else:
                self._rename_item(path)
        elif chosen is act_reveal:
            reveal_in_file_manager(path)
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
        elif act_remove_shortcut is not None and chosen is act_remove_shortcut:
            for source in (self._source_dirs if self._source_dirs is not None else [self.directory]):
                remove_shortcut(source, path)
            self.refresh()
        elif chosen is act_add_shortcut:
            QTimer.singleShot(150, self._add_shortcut)

    def _add_context_slider(self, menu: QMenu, label_text: str, value: int, vmin: int, vmax: int, on_change):
        """Ligne "slider + valeur px en temps reel" du menu contextuel
        (voir _on_context_menu, "Taille de l'icone"/"Padding gauche de
        l'icone"/"Padding gauche du texte") — reutilise TEL QUEL le
        _SliderField de la fenetre de parametres (slider + boite de
        saisie px, deja avec sa valeur en temps reel) — voir la remarque
        de l'utilisateur, "je veux que le style [du slider] soit celui des
        settings" (remplace l'ancien QSlider habille a la main). Import
        DIFFERE (jamais au niveau module, meme raison que settings_window
        important pipeline_browser) : sans danger ici, appele bien apres
        que les deux modules soient charges."""
        import settings_window as sw

        action = QWidgetAction(menu)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)
        label = QLabel(label_text)
        label.setFont(font(11, 400))
        field = sw._SliderField(vmin, vmax, value, slider_width=120, box_width=60)
        field.valueChanged.connect(on_change)
        layout.addWidget(label)
        layout.addWidget(field, 1)
        action.setDefaultWidget(widget)
        menu.addAction(action)

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

    def _create_folder(self):
        name, ok = QInputDialog.getText(
            self, "Nouveau dossier", "Nom du dossier :", QLineEdit.Normal, "Nouveau dossier"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau dossier", "Le nom contient des caracteres interdits.")
            return
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            # Colonne IN/OVER/OUT (contenu FUSIONNE de plusieurs colonnes de
            # set, voir __init__/PipelineBrowser.update_preview_stack) :
            # `self.directory` n'est qu'un repli parmi plusieurs sources
            # possibles — demande a QUEL NIVEAU (quelle colonne de set
            # actuellement affichee) ce nouveau dossier doit reellement
            # etre cree sur le disque, plutot que de choisir silencieusement
            # le premier — voir la remarque de l'utilisateur, "je veux
            # pouvoir creer des repertoires dans les colonnes in over et
            # out. quand c'est le cas, je veux que le soft me demande a
            # quel niveau (quelle colonne) il doit les enregistrer".
            choice, ok_level = QInputDialog.getItem(
                self, "Nouveau dossier", "A quel niveau enregistrer ce dossier ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau dossier", f"« {name} » existe deja.")
            return
        try:
            # parents=True : `target_dir` (repli sur un NIVEAU DE SET
            # choisi, voir ci-dessus) peut lui-meme ne pas encore exister
            # (in/over/out jamais cree pour ce niveau precis) — voir la
            # remarque de l'utilisateur, capture a l'appui, "il y a un
            # probleme quand on cree un repertoire alors que la hierarchie
            # n'est pas encore creee ... que toute la hierarchie soit
            # creee en meme temps que le repertoire" (WinError 3, "chemin
            # d'acces introuvable").
            new_path.mkdir(parents=True)
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau dossier", f"Impossible de creer le dossier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

    def _create_text_file(self):
        """"Nouveau document texte" (voir _on_context_menu) : cree un fichier
        .txt vierge, MEME mecanique que _create_folder (nom/caracteres
        interdits/choix du niveau pour une colonne IN/OVER/OUT fusionnee/
        creation des dossiers parents manquants) — voir la remarque de
        l'utilisateur, "dans les colonnes ou le texte est permis, merci
        d'ajouter une option 'nouveau document texte' qui permet de creer
        un fichier txt vierge"."""
        name, ok = QInputDialog.getText(
            self, "Nouveau document texte", "Nom du fichier :", QLineEdit.Normal, "Nouveau document texte"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau document texte", "Le nom contient des caracteres interdits.")
            return
        if not name.lower().endswith(".txt"):
            name += ".txt"
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            choice, ok_level = QInputDialog.getItem(
                self, "Nouveau document texte", "A quel niveau enregistrer ce fichier ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau document texte", f"« {name} » existe deja.")
            return
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text("", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau document texte", f"Impossible de creer le fichier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

    def _add_shortcut(self):
        """"Ajouter un raccourci" (voir _on_context_menu, ROLE_IS_SHORTCUT/
        load_shortcuts/add_shortcut) : va chercher un repertoire A
        N'IMPORTE QUEL autre emplacement du disque et l'affiche comme s'il
        etait physiquement dans CE dossier — voir la remarque de
        l'utilisateur, "aller chercher un repertoire dans un emplacement
        autre ... et de faire comme si il etait au meme endroit que les
        autres repertoires de l'emplacement actuel"."""
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            # MEME choix de niveau que _create_folder, MEME raison (colonne
            # IN/OVER/OUT, contenu fusionne de plusieurs colonnes de set).
            choice, ok_level = QInputDialog.getItem(
                self, "Ajouter un raccourci", "A quel niveau enregistrer ce raccourci ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        chosen = QFileDialog.getExistingDirectory(self, "Choisir un repertoire", str(target_dir))
        if not chosen:
            return
        chosen_path = Path(chosen)
        if chosen_path == target_dir or chosen_path.parent == target_dir:
            QMessageBox.warning(self, "Ajouter un raccourci", "Ce repertoire est deja ici.")
            return
        add_shortcut(target_dir, chosen_path)
        self.refresh()

    def _change_thumbnail(self, path: Path):
        _prompt_change_thumbnail(self, path, lambda: self.list.viewport().update())

    def _capture_thumbnail(self, path: Path):
        _prompt_capture_thumbnail(self, path, lambda: self.list.viewport().update())

    def _save_thumbnail_pixmap(self, path: Path, pix: QPixmap):
        _save_thumbnail_pixmap_for(path, pix, self, lambda: self.list.viewport().update())

    def _reset_thumbnail(self, path: Path):
        _prompt_reset_thumbnail(self, path, lambda: self.list.viewport().update())

    def _unique_dest_path(self, src: Path, dest_dir: Path | None = None) -> Path:
        """Chemin de destination dans `dest_dir` (par defaut ce dossier), en
        evitant les collisions (« nom - copie », « nom - copie (2) », ...)."""
        dest_dir = dest_dir if dest_dir is not None else self.directory
        dest = dest_dir / src.name
        if not dest.exists():
            return dest
        stem, suffix = (src.stem, src.suffix) if src.is_file() else (src.name, "")
        candidate = dest_dir / f"{stem} - copie{suffix}"
        i = 2
        while candidate.exists():
            candidate = dest_dir / f"{stem} - copie ({i}){suffix}"
            i += 1
        return candidate

    def _paste_items(self):
        mime = QApplication.clipboard().mimeData()
        if not mime.hasUrls():
            return
        last_dest = None
        errors = []
        for url in mime.urls():
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            dest = self._unique_dest_path(src)
            try:
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")
        if errors:
            QMessageBox.warning(self, "Coller", "Impossible de coller :\n" + "\n".join(errors))
        self.refresh()
        if last_dest:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.list.setCurrentItem(it)
                    break

    def _rename_shortcut(self, path: Path, shown: str):
        """Change le nom AFFICHE d'un raccourci (cle `name` de .pipeline_shortcuts.json) ; le dossier
        cible n'est jamais renomme. Nom vide = retour au nom du dossier."""
        new_name, ok = QInputDialog.getText(
            self, "Renommer le raccourci", "Nom affiché :", QLineEdit.Normal, shown
        )
        if not ok:
            return
        new_name = new_name.strip()
        for source in (self._source_dirs if self._source_dirs is not None else [self.directory]):
            shortcuts = load_shortcuts(source)
            changed = False
            for sc in shortcuts:
                if sc.get("target") == str(path):
                    if new_name and new_name != path.name:
                        sc["name"] = new_name
                    else:
                        sc.pop("name", None)
                    changed = True
            if changed:
                save_shortcuts(source, shortcuts)
        self.refresh()

    def _rename_item(self, path: Path):
        new_name, ok = QInputDialog.getText(
            self, "Renommer", "Nouveau nom :", QLineEdit.Normal, path.name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == path.name:
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Renommer", "Le nom contient des caracteres interdits.")
            return
        new_path = path.with_name(new_name)
        if new_path.exists():
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe deja.")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Renommer", f"Impossible de renommer :\n{exc}")
            return
        # Un raccourci pointant vers ce dossier doit suivre son nouveau nom.
        for source in (self._source_dirs if self._source_dirs is not None else [self.directory]):
            shortcuts = load_shortcuts(source)
            if any(sc.get("target") == str(path) for sc in shortcuts):
                for sc in shortcuts:
                    if sc.get("target") == str(path):
                        sc["target"] = str(new_path)
                save_shortcuts(source, shortcuts)
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

# Texte d'entete des 2 colonnes fantomes Focus (voir PreviewColumn.
# display_title/PipelineBrowser.update_preview_stack) — cle = titre REEL de
# la colonne source (Projets/Sous-projet, voir column.column_title) — voir
# la remarque de l'utilisateur, "il doit y avoir deux colonnes, une focus
# projet et l'autre focus sous projet, je veux aucune autre entete".
_FOCUS_LEVEL_LABEL = {"Projets": "Focus Projet", "Sous-projet": "Focus Sous-projet"}
