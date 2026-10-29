import json
import shutil
import time
from pathlib import Path
from PySide6.QtCore import (
    QEasingCurve, QEvent, QFile, QMimeData, QObject, QPoint, QRect, QRunnable, QSize,
    QThreadPool, Qt, QTimer, QUrl, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QCursor,
    QIcon,
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
    QStyleOptionViewItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
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
    IMAGE_EXTENSIONS,
    PREVIEWABLE_EXTENSIONS,
    RENDERABLE_3D_EXTENSIONS,
    THUMBNAIL_COLUMN_LABELS,
    _MANUAL_3D_PREVIEW_MODE,
    _MANUAL_3D_PREVIEW_REQUESTS,
    _STALE_PREVIEW_PATHS,
)
from previews import (
    _PREVIEW_DECODE_MANAGER,
    is_remote_path,
    software_icon_key,
)
from config import (
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
)
from settings_widgets import (
    Menu, menu_row,
    _radius_dict,
    _radius_shrink,
    _SliderField,
    run_space_menu_hooks,
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
    ROLE_LIGHTROOM_SHORTCUT,
    ROLE_SPACE_ABOVE,
    ROLE_SPACE_BELOW,
    ROLE_PIN_BOTTOM,
    ROLE_BOTTOM_GAP,
    ROLE_TITLE_ABOVE,
    ROLE_META,
    ROLE_MEDIA_COUNTS,
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
    _show_resize_width,
    _show_row_resize_indicator,
    _step_badge_rect,
    _update_layout_setting,
    add_shortcut,
    col_row_height,
    col_spacing,
    col_width,
    count_entries,
    entry_is_dir,
    entry_size,
    human_size,
    list_entries,
    remember_entry,
    load_layout_settings,
    load_project_columns,
    load_shortcuts,
    project_thumbnail_path,
    remove_shortcut,
    save_shortcuts,
    reveal_in_file_manager,
    save_layout_settings,
    software_choices,
    software_icon_pixmap,
)
from column_config import (
    ColumnConfigDialog,
)
from capture_widgets import (
    FileListWidget,
    item_order_key,
    _ColumnCard,
    _RoundedCornersEffect,
    _column_suppress_left,
)
from row_delegates import (
    ProjectTileDelegate,
    RowDelegate,
)


from column_parts.shared import opens_in_viewer, _MediaCountSignals, _MediaCountTask, _MEDIA_COUNT_POOL, _shortcut_present
from column_parts.geometry import ColumnGeometryMixin
from column_parts.loading import ColumnLoadingMixin
from column_parts.rows import ColumnRowsMixin
from column_parts.appearance import ColumnAppearanceMixin
from column_parts.context_menu import ColumnContextMenuMixin
from column_parts.file_operations import ColumnFileOperationsMixin

__all__ = [
    'json', 'shutil', 'time', 'Path', 'QEasingCurve',
    'QEvent', 'QFile', 'QMimeData', 'QObject', 'QPoint',
    'QRect', 'QRunnable', 'QSize', 'QThreadPool', 'Qt',
    'QTimer', 'QUrl', 'QVariantAnimation', 'Signal', 'QCursor',
    'QIcon', 'QApplication', 'QDialog', 'QFileDialog', 'QFrame',
    'QHBoxLayout', 'QInputDialog', 'QLabel', 'QLineEdit', 'QListWidgetItem',
    'QStyleOptionViewItem', 'QMenu', 'QMessageBox', 'QPushButton', 'QVBoxLayout',
    'QWidget', 'C', 'columns_resizable', 'font', 'header_qss',
    'role_color', 'role_font', 'scaled', 'ui_scale', 'resolve_color_ref',
    'column_frame_style', 'column_header_qss', 'column_padding_for', 'column_style_for', 'ui_state',
    'IMAGE_EXTENSIONS', 'PREVIEWABLE_EXTENSIONS', 'RENDERABLE_3D_EXTENSIONS', 'THUMBNAIL_COLUMN_LABELS', '_MANUAL_3D_PREVIEW_MODE',
    '_MANUAL_3D_PREVIEW_REQUESTS', '_STALE_PREVIEW_PATHS', '_PREVIEW_DECODE_MANAGER', 'is_remote_path', 'software_icon_key',
    'GLOBAL_OMIT_DIR_NAMES', 'GLOBAL_OMIT_FILE_EXTENSIONS', 'GLOBAL_OMIT_FILE_NAMES', 'Menu', 'menu_row',
    '_radius_dict', '_radius_shrink', '_SliderField', 'run_space_menu_hooks', 'COLUMN_MAX_WIDTH',
    'COLUMN_MIN_WIDTH', 'COLUMN_RESIZE_MARGIN', 'COLUMN_SETTINGS', 'GROUP_COLUMN_DEFAULT_HEIGHT', 'GROUP_COLUMN_MAX_HEIGHT',
    'GROUP_COLUMN_MIN_HEIGHT', 'ROLE_ISDIR', 'ROLE_IS_SHORTCUT', 'ROLE_LIGHTROOM_SHORTCUT', 'ROLE_SPACE_ABOVE',
    'ROLE_SPACE_BELOW', 'ROLE_PIN_BOTTOM', 'ROLE_BOTTOM_GAP', 'ROLE_TITLE_ABOVE', 'ROLE_META',
    'ROLE_MEDIA_COUNTS', 'ROLE_PATH', 'ROLE_SOURCE_LABEL', 'ROLE_SOURCE_STEP', 'ROW_RESIZE_MAX_HEIGHT',
    'ROW_RESIZE_MIN_HEIGHT', '_STATUS_FOLDER_SET', '_WIDGET_SIZE_MAX', '_col_key', '_hide_resize_width',
    '_is_globally_omitted_dir', '_is_globally_omitted_file', '_make_group_drag_ghost', '_persist_column_width', '_persist_row_height',
    '_pin_icon_pixmap', '_prompt_capture_thumbnail', '_prompt_change_thumbnail', '_prompt_reset_thumbnail', '_resolve_font_family',
    '_row_preview_left_x', '_show_resize_width', '_show_row_resize_indicator', '_step_badge_rect', '_update_layout_setting',
    'add_shortcut', 'col_row_height', 'col_spacing', 'col_width', 'count_entries',
    'entry_is_dir', 'entry_size', 'human_size', 'list_entries', 'remember_entry',
    'load_layout_settings', 'load_project_columns', 'load_shortcuts', 'project_thumbnail_path', 'remove_shortcut',
    'save_shortcuts', 'reveal_in_file_manager', 'save_layout_settings', 'software_choices', 'software_icon_pixmap',
    'ColumnConfigDialog', 'FileListWidget', 'item_order_key', '_ColumnCard', '_RoundedCornersEffect',
    '_column_suppress_left', 'ProjectTileDelegate', 'RowDelegate', 'opens_in_viewer', '_MediaCountSignals',
    '_MediaCountTask', '_MEDIA_COUNT_POOL', '_shortcut_present', 'Column', '_FOCUS_LEVEL_LABEL',
]

class Column(ColumnGeometryMixin, ColumnLoadingMixin, ColumnRowsMixin, ColumnAppearanceMixin, ColumnContextMenuMixin, ColumnFileOperationsMixin, QWidget):

    # Valeurs de classe : le filtre d'événements peut être appelé PENDANT __init__ (avant ces attributs) ; il
    # levait alors une AttributeError à chaque événement de construction.
    _group_kind = None
    _group_header_widgets = ()

    selected = Signal(object, object)   # (Column, Path | None)
    activated = Signal(object)          # Path
    view_requested = Signal(object)     # Path : double-clic sur une image (visionneuse de l'appli)
    folder_view_requested = Signal(object)   # Path : double-clic sur un dossier (visionneuse sur son contenu)
    folder_gallery_requested = Signal(object)  # Path : menu « Ouvrir la visionneuse à cet endroit » (planche)
    recursive_requested = Signal(bool)       # menu « Récursif » : photos des sous-dossiers aussi
    loaded = Signal()                      # contenu disponible, sélection/navigation différée

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
                 on_group_maximize=None, on_group_equalize=None, async_load: bool = False):
        super().__init__(parent)
        self._async_load = async_load
        self._loaded_data = None
        self._load_key = None
        self.loading = False
        self._load_error = ""
        self._row_iterator = None
        self._row_timer = QTimer(self)
        self._row_timer.setSingleShot(True)
        self._row_timer.timeout.connect(self._advance_rows)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._start_load)
        self._revalidate_timer = QTimer(self)
        self._revalidate_timer.setInterval(5000)
        self._revalidate_timer.timeout.connect(self._revalidate_if_visible)
        if async_load:
            from column_loading import loader
            loader().ready.connect(self._column_data_ready)
            self._revalidate_timer.start()
        self._media_counts_generation = 0
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
        layout_data = {} if async_load else load_layout_settings(directory)
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

            # LOGICIELS : « + » = menu des logiciels des reglages, le choix cree son dossier ici
            # (demande de l'utilisateur, voir _open_software_menu).
            if self._group_kind == "logiciels":
                self._software_btn = _group_header_btn(
                    "+", "Ajouter un logiciel : cree son dossier dans cette colonne",
                    lambda: self._open_software_menu())
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
        # Bouton « ouvrir le logiciel ici » (voir set_launcher), cree a la demande, place avant la punaise.
        self._header_layout = header_layout
        self._launch_btn = None
        self._launch_key = None
        self._launch_click = None
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
        if async_load:
            from PySide6.QtWidgets import QListView
            self.list.setLayoutMode(QListView.Batched)
            self.list.setBatchSize(128)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        # Hauteur commune dans les deux délégués ; seuls les espaces ajoutés
        # à une ligne et les lignes collées en bas empêchent l'optimisation.
        self.sync_uniform_sizes()
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

        if async_load:
            self._start_load(force=False)
        else:
            self.refresh()



# Texte d'entete des 2 colonnes fantomes Focus (voir PreviewColumn.
# display_title/PipelineBrowser.update_preview_stack) — cle = titre REEL de
# la colonne source (Projets/Sous-projet, voir column.column_title) — voir
# la remarque de l'utilisateur, "il doit y avoir deux colonnes, une focus
# projet et l'autre focus sous projet, je veux aucune autre entete".
_FOCUS_LEVEL_LABEL = {"Projets": "Focus Projet", "Sous-projet": "Focus Sous-projet"}
