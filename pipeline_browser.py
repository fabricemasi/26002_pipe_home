import json
import os
import sys
from pathlib import Path
import threading
import time
from PySide6.QtCore import (
    QByteArray, QCoreApplication, QEasingCurve, QEvent, QEventLoop, QObject, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, QSizeF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QFontMetrics,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    resolve_color_ref,
    PREVIEW_STACK_TITLE,
    STYLESHEET_COLOR_KEYS,
    apply_dwm_frame,
    apply_style,
    auto_collapse_set_columns,
    column_gap,
    build_stylesheet,
    resize_hit_test,
    role_color,
    role_font,
    font,
    scaled,
    start_native_move,
    column_style_for,
)
import config as _config
import ui_state
from config import (
    COLUMN_LABELS,
    RAW_EXTENSIONS,
    PREVIEWABLE_EXTENSIONS,
    RENDERABLE_3D_EXTENSIONS,
    SOFTWARE_COLUMN_LABEL,
)
from previews import (
    UI_ICON_APP_LOGO,
    _IdlePreviewScheduler,
    custom_ui_icon_pixmap,
)
from config import (
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
)
from settings_store import (
    DEFAULT_SETTINGS,
    load_settings,
    save_live_state,
    save_settings,
)
from settings_widgets import (
    Menu, shadow_look, TOGGLE_STYLE_LISTENERS, _Toggle, make_space_actions, set_space_above, set_space_below,
    space_target, widget_at_path, widget_path,
)
from browser_core import (
    COLUMN_SETTINGS,
    DEFAULT_WORK_DIR_TYPE,
    GROUP_COLUMN_DEFAULT_HEIGHT,
    GROUP_COLUMN_MAX_HEIGHT,
    GROUP_COLUMN_MIN_HEIGHT,
    ROLE_ISDIR,
    ROLE_MEDIA_COUNTS,
    ROLE_PATH,
    ROLE_SOURCE_LABEL,
    STATUS_FOLDERS,
    STATUS_HEIGHT,
    TITLEBAR_HEIGHT,
    WORK_DIR_TYPES,
    _WIDGET_SIZE_MAX,
    _hide_resize_width,
    _is_globally_omitted_path,
    _named_subdir,
    _show_resize_width,
    _update_layout_setting,
    apply_all_settings,
    _resolve_font_family,
    col_width,
    load_layout_settings,
    load_project_columns,
    open_in_file_manager,
    open_path,
    project_thumbnail_pixmap,
    status_folder_state,
)
from column import (
    Column,
    _FOCUS_LEVEL_LABEL,
)
from detail_panel import (
    DetailPanel,
    load_window_state,
    save_window_state,
)
from preview_column import (
    PureRefImagesTask,
    _PUR_EXPORT_POOL,
    pur_image_files,
    IconButton,
    style_focus_button,
    PreviewColumn,
)
from previews import (
    migrate_cache_names,
)
from browser_core import (
    _FadeOverlay,
)
from fm_visionneuse.focus import (
    FilterChips, FocusFilmstrip, FocusGallery, FocusImageLoader, FocusInfoPanel, FocusOverlay, filter_window, fit_rect,
    placeholder_pixmap,
)
from fm_visionneuse import file_attributes
from fm_visionneuse import file_filters
from fm_visionneuse.focus import thumbnail as focus_thumbnail
from fm_visionneuse import focus as _focus
from config import (
    PUR_PREVIEW_EXTENSIONS,
)
import previews as _previews
import software_launch
import shiboken6
from interface_edit_targets import PaintedTarget


from browser_core import (
    _SlideOverlay,
    DETAIL_PANEL_MIN_WIDTH,
)
from browser_core import (
    _HoverPrime,
    entry_is_dir,
)
from previews import (
    sweep_preview_cache_if_due,
)

# Découpage (2026-10-28) : classes de tête et méthodes par responsabilité dans main_window/ (carte :
# docs/agents/fm_browser.md). Réexportées ici : `pipeline_browser.X` reste valable en LECTURE ; pour PATCHER
# un nom, viser le module de main_window/ qui l'utilise.
from main_window.helpers import CentralFrame, _AppInputWatch, _MouseBackFilter, _anim_running, _set_qss  # noqa: F401
from main_window.title_bar import (
    TitleBar, _CRUMB_LOOK_CACHE, _CrumbChip, _ViewerGroup, _build_crumb_look, _crumb_look, _crumb_state,
)
from main_window.interface_move import _InterfaceMoveFrame, _InterfaceMoveMode, _InterfaceObjectStore  # noqa: F401
from main_window.viewer_buttons import _ViewerButtonDrag, _shown_or_pending  # noqa: F401
from main_window.settings_link import settings_window_v2_preload_enabled  # noqa: F401
from main_window.board_module import _DrawingRelay  # noqa: F401
from main_window.columns import ColumnsMixin
from main_window.crumbs import CrumbsMixin
from main_window.preview_stack import PreviewStackMixin
from main_window.group_columns import GroupColumnsMixin
from main_window.selection import SelectionMixin
from main_window.columns_hidden import ColumnsHiddenMixin
from main_window.gallery import GalleryMixin
from main_window.viewer import ViewerMixin
from main_window.viewer_buttons import ViewerButtonsMixin
from main_window.viewer_chrome import ViewerChromeMixin
from main_window.collapse import CollapseMixin
from main_window.settings_link import SettingsLinkMixin
from main_window.chrome import ChromeMixin
from main_window.md_module import MdModuleMixin
from main_window.video_module import VideoModuleMixin
from main_window.board_module import BoardModuleMixin


class PipelineBrowser(
    ColumnsMixin, CrumbsMixin, PreviewStackMixin, GroupColumnsMixin, SelectionMixin, ColumnsHiddenMixin, GalleryMixin,
    ViewerMixin, ViewerButtonsMixin, ViewerChromeMixin, CollapseMixin, SettingsLinkMixin, ChromeMixin, MdModuleMixin,
    VideoModuleMixin, BoardModuleMixin, QMainWindow,
):
    _bulk_navigation = False        # _navigate_to en cours : niveaux intermediaires sans fondu ni animation

    @property
    def _project_columns_hidden(self) -> bool:
        return self.__dict__.get("_columns_hidden_flag", False)

    @_project_columns_hidden.setter
    def _project_columns_hidden(self, value):
        """Colonnes masquees (visionneuse, planche) : le filtre du bouton « precedent » de la souris n'est
        pose qu'a ce moment. Pose en permanence sur l'application, il etait appele pour CHAQUE evenement de
        l'appli (~50 000 pendant quelques clics de navigation) pour ne rien faire."""
        value = bool(value)
        self.__dict__["_columns_hidden_flag"] = value
        back = self.__dict__.get("_mouse_back")
        if back is not None:
            app = QApplication.instance()
            if value:
                app.installEventFilter(back)
            else:
                app.removeEventFilter(back)


    def __init__(self, root: Path):
        super().__init__()
        self.setWindowTitle("Pipeline Browser")
        # Sans decoration systeme : le chrome blanc/bleu de Windows (barre de
        # titre, boutons min/max/fermer natifs) est remplace par la barre
        # intrinseque de l'appli (voir TitleBar), habillee comme le reste de
        # l'interface. Le redimensionnement par les bords, perdu avec le
        # cadre systeme, est retrouve via nativeEvent (voir plus bas).
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # Fond translucide (voir Parametres > General > "Border radius de la
        # fenetre principale") : indispensable pour qu'un rayon de bordure
        # non nul, applique plus bas en QSS sur `central`, laisse voir au
        # travers des coins au lieu de les peindre carres derriere le
        # widget arrondi. Actif en permanence (rayon 0 = coins carres, rendu
        # identique a avant) pour que le reglage marche en direct sans
        # devoir re-afficher la fenetre.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1280, 620)
        self.columns: list[Column] = []
        # Etat courant (unique source de verite, voir _sync_collapse_state/
        # _toggle_project_columns) de repli de Type/Projets/Sous-projet, et
        # icone associee sur la colonne des vignettes (voir
        # PreviewColumn.set_toggle_state).
        self._project_columns_collapsed = False
        self._project_columns_hidden = False
        self._columns_fade = None
        self._focus_overlay = None    # objet en focus au centre (voir _start_focus_overlay)
        self._focus_src = None        # (pixmap, QRect dans le viewport) de l'objet dans l'inspecteur
        self._focus_gallery = None    # planche des images du dossier (voir _toggle_focus_gallery)
        self._viewer_entry_source = None   # double-clic sur une ligne : apercu de la ligne (depart du vol)
        self._floating_gallery_btn = None   # son bouton quand il n'y a pas de colonne Focus
        self._lightroom_btn = None          # ouvrir la photo courante dans Lightroom Classic
        self._viewer_100_btn = None         # afficher l'image a sa taille reelle
        self._recursive_btn = None          # « Récursif » : photos des sous-dossiers aussi
        self._viewer_folder: Path | None = None       # dossier de la visionneuse (liste, mode récursif)
        self._viewer_entry_folder: Path | None = None  # double-clic sur un dossier : lui, pas le parent du 1er fichier
        self._pending_folder_view = None    # (dossier, colonne) en attente du parcours récursif
        self._viewer_purs: list = []        # planches PureRef du dossier de la visionneuse
        self._pur_buttons: list = []        # un bouton « ouvrir » par planche (en haut a droite)
        # Filtres de la planche (file_filters ; le temps de la session) : bouton filtre (planche ouverte),
        # elements du filtre ecrits a cote, fenetre des filtres, fichiers des portees larges (parcours en fond).
        self._viewer_filter: dict = dict(file_filters.DEFAULT_FILTER)
        self._viewer_filter_enabled = False
        self._filter_btn = None
        self._filter_chips = None
        self._filter_window = None
        self._filter_scopes_cache: list = []
        self._scope_files: dict = {}        # dossier de la portee -> [(chemin, taille, date)]
        self._filter_task = None
        self._filter_timer = None
        self._pending_filter = None
        self._gallery_list: list = []       # fichiers montres par la planche (filtres ou non)
        self._viewer_base: list = []        # fichiers de la visionneuse avant filtre (colonne en cours)
        self._button_drag = _ViewerButtonDrag(self)   # Ctrl + glisser un bouton de la rangee
        self._focus_home = None       # place de l'objet en focus dans l'inspecteur, gardee pendant la planche
        self._select_fade = None
        self._columns_slide = None
        self._slide_snapshot = None
        # Prechauffage (voir _prewarm_snapshots) : le 1er usage des boutons de repli /
        # de masquage doit etre aussi fluide que les suivants, donc les captures
        # (et le premier rendu a froid des colonnes, ~150 ms) sont faites des que
        # l'interface se repose, pas au clic.
        self._prewarm_timer = QTimer(self)
        self._prewarm_timer.setSingleShot(True)
        self._prewarm_timer.setInterval(700)
        self._prewarm_timer.timeout.connect(self._prewarm_snapshots)
        self._columns_snapshot = None
        self._columns_epoch = 0
        # Tant que ce drapeau est vrai, la prochaine fois que Sous-projet
        # obtient une selection declenche le repli automatique une fois
        # (voir _sync_collapse_state) — desarme par un repli/depli manuel
        # (icone) pour ne pas annuler le choix de l'utilisateur tant que la
        # selection reste la meme, puis rearme des que Sous-projet perd sa
        # selection (retour en arriere).
        self._auto_collapse_armed = True
        # Signature du dernier RENDU de update_preview_stack (voir
        # _preview_style_snapshot/refresh_all_columns) — permet a
        # refresh_all_columns(rescan=False) de sauter une reconstruction
        # complete (detruit/recree jusqu'a 6 widgets, RE-SCANNE LE DISQUE :
        # vignettes/in/over/out/logiciels) quand rien de ce dont depend le
        # RENDU n'a change depuis le dernier appel — voir la remarque de
        # l'utilisateur, "gros ralentissements ... les manips sont donc
        # tres lourdes". None : jamais encore rendu, le premier appel via
        # cette voie reconstruit TOUJOURS (repli surs).
        self._last_preview_style_snapshot: str | None = None
        # Groupe IN/OVER/OUT/LOGICIELS (voir update_preview_stack) : 4
        # colonnes fantomes EMPILEES VERTICALEMENT (meme principe que
        # _preview_stack_wrapper ci-dessous) — reconstruites SEULEMENT
        # quand le contexte de navigation change reellement (voir
        # _group_context_key ci-dessous), jamais a chaque appel : ces
        # instances restent stables d'une navigation a l'autre, EXACTEMENT
        # comme Type/Projets/Sous-projet — voir la remarque de
        # l'utilisateur, "leur comportement ne fonctionne pas du tout ...
        # base toi sur les colonnes creees avant les focus".
        self._group_stack_wrapper: QWidget | None = None
        self.group_columns: list[Column] = []
        # (terminal_path, tuple(levels), work_dir_style) de la DERNIERE
        # construction reussie du groupe (voir update_preview_stack) — None
        # tant qu'aucune construction n'a encore eu lieu (repli sur : le
        # premier appel reconstruit toujours).
        self._group_context_key: object | None = None
        # Colonne du groupe IN/OVER/OUT/LOGICIELS la plus RECEMMENT
        # selectionnee (voir update_active_column/_on_group_item_selected) —
        # une SEULE des 4 doit apparaitre "focus" (fond bleu) a la fois,
        # pas les 4 independamment des qu'elles ont chacune une selection —
        # voir la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir".
        self._last_active_group_column: Column | None = None
        # Largeur commune aux 4 colonnes du groupe (voir Column.__init__
        # user_width/on_resize, _on_group_column_resized) — MEME principe/
        # MEME raison que _preview_column_user_width plus bas (colonnes
        # RECONSTRUITES a chaque navigation) — voir la remarque de
        # l'utilisateur, "les 4 colonnes doivent avoir la meme largeur
        # constamment".
        self._group_column_user_width: int | None = None
        # Hauteur INDEPENDANTE de chacune des colonnes du groupe (voir
        # Column.__init__ user_height/on_height_resize/fill_height,
        # _on_group_height_resized), par kind ("in"/"over"/"out"/
        # "logiciels") — PAS une largeur commune : contrairement a la
        # largeur (memes proportions pour les 4), chaque colonne garde SA
        # PROPRE hauteur — voir la remarque de l'utilisateur, "je ne veux
        # pas qu'elles aient toute la meme hauteur, mais chacune leur
        # hauteur". La DERNIERE colonne de _group_column_order n'y figure
        # jamais activement (voir fill_height) : elle reste etiree jusqu'en
        # bas de la page, jamais une hauteur fixe.
        self._group_column_user_heights: dict[str, int] = {}
        # Etat du glisser de hauteur EN COURS (voir _on_group_height_resize_
        # begin/_on_group_height_resized) : (colonne du dessus, colonne du
        # dessous, sa hauteur de depart, la hauteur de depart de sa voisine)
        # — None hors glisser. Scission a 2 (voir leurs remarques) : SEULES
        # ces 2 colonnes-la sont jamais touchees, jamais tout le groupe.
        self._group_height_drag: tuple[Column, Column, int, int] | None = None
        # Configuration de chaine de navigation DU PROJET COURANT (voir
        # load_project_columns/on_selected/ColumnConfigDialog) — None tant
        # qu'aucun projet n'est selectionne OU que le projet selectionne n'a
        # pas de fichier de configuration (repli sur la chaine legacy fixe,
        # voir COLUMN_LABELS) — voir la remarque de l'utilisateur, "cette
        # configuration [doit changer] suivant les besoins de l'utilisateur".
        self._active_project_config: dict | None = None
        # Ordre d'affichage des 4 colonnes du groupe (voir update_preview_
        # stack/_on_group_reorder) — LOGICIELS en premier par defaut, voir
        # la remarque de l'utilisateur, "la colonne logiciel doit etre en
        # premiere position en haut". Reordonnable par glisser-deposer de
        # l'entete (voir Column.__init__ group_kind/on_reorder).
        self._group_column_order: list[str] = ["logiciels", "in", "over", "out"]
        # Groupe des animations de position en cours (voir
        # _reorder_group_columns_animated) — reference gardee pour ne pas
        # etre ramassee par le GC avant la fin, meme raison que Column.
        # _width_anim.
        self._group_reorder_anim: QParallelAnimationGroup | None = None
        # Colonnes fantomes PERMANENTES des vignettes (voir _PreviewBlock) :
        # jamais remplacees par une vraie colonne, contrairement au groupe
        # IN/OVER/OUT/LOGICIELS ci-dessus (dont le clic sur une ligne ouvre,
        # lui, une vraie colonne). UNE VRAIE colonne fantome SEPAREE par niveau
        # selectionne (Projets, Sous-projet), PLUS une derniere colonne
        # fantome vide (voir PreviewColumn.set_preview_block/set_empty) —
        # chacune avec son PROPRE cadre/bordure/entete (voir app_style.
        # column_style_for), empilees VERTICALEMENT dans UN SEUL conteneur
        # (voir _preview_stack_wrapper ci-dessous), lui-meme insere comme
        # UNE SEULE colonne dans columns_layout — voir la remarque de
        # l'utilisateur, "je veux les trois colonnes ... les unes sur les
        # autres" puis "chaque colonne doit avoir sa propre entete" puis,
        # apres un essai fusionnant tout dans une seule carte, "non, tu as
        # merger les deux colonnes en une seule, ce que je veux c'est deux
        # colonnes separees, une en dessous de l'autre !".
        self.image_preview_columns: list[PreviewColumn] = []
        # Conteneur vertical (QWidget+QVBoxLayout) qui heberge les colonnes
        # ci-dessus, INSERE comme un SEUL element de columns_layout — voir
        # update_preview_stack.
        self._preview_stack_wrapper: QWidget | None = None
        # Largeur choisie a la main sur la colonne Focus (voir PreviewColumn.
        # resize_begin/resize_update, _on_preview_column_resized) — vit ICI
        # (pas sur les instances PreviewColumn elles-memes) car update_
        # preview_stack() les RECONSTRUIT entierement a chaque navigation :
        # sans ce relais, tout glisser de bordure serait perdu des le clic
        # suivant. PARTAGEE par toutes (pas par niveau) : ce sont des
        # colonnes SEPAREES mais elles doivent rester alignees a la meme
        # largeur (voir PreviewColumn.set_width_external) — None = pas
        # encore ajustee a la main, retombe sur col_width("Projets") — voir
        # la remarque de l'utilisateur, "je veux pouvoir controler la
        # largeur des colonnes focus projet et sous projet en slidant les
        # bords de celles-ci".
        self._preview_column_user_width: int | None = None
        # Cle (couleurs + rayon des boutons) du dernier _apply_settings :
        # sert a ne reconstruire la feuille de style globale (voir
        # refresh_colors) que lorsque l'un des deux a vraiment change,
        # plutot qu'a chaque cran de n'importe quel slider.
        self._last_style_key = None
        # app.setStyleSheet (voir refresh_colors/refresh_style) est de
        # LOIN le poste le plus cher de tout ce rafraichissement — mesure
        # a plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte (des milliers de widgets, chacun avec son propre QSS
        # local a re-cascader) — voir la remarque de l'utilisateur, "il y
        # a toujours un tres gros problemes de performance dans les
        # settings". Le gate ci-dessus (style_key) evite de le rejouer
        # quand RIEN n'a change, mais durant un glisser de COULEUR, la
        # valeur change reellement a CHAQUE tick (~30ms) : ce gate seul ne
        # peut donc rien y faire. Regroupe ici les reconstructions
        # rapprochees (voir _flush_stylesheet_rebuild) : le reste de
        # refresh_colors (couleurs des colonnes/boutons individuels, DEJA
        # rapide et DEJA la source principale du retour visuel en direct)
        # continue de tourner a CHAQUE tick, seul cet appel natif couteux
        # est repousse a un rythme beaucoup plus lache — invisible a
        # l'oeil (le style GENERIQUE — boutons/scrollbars/menus — n'est de
        # toute facon pas ce qu'on regarde en glissant une pastille de
        # couleur), mais qui evite l'accumulation de secondes de latence.
        # Reperes de la barre de navigation (choix de chaque colonne) : mises a jour regroupees.
        self._crumb_timer = QTimer(self)
        self._crumb_timer.setSingleShot(True)
        self._crumb_timer.setInterval(0)
        self._crumb_timer.timeout.connect(self._refresh_crumbs)
        self._pending_stylesheet_rebuild = False
        self._stylesheet_rebuild_timer = QTimer(self)
        self._stylesheet_rebuild_timer.setSingleShot(True)
        self._stylesheet_rebuild_timer.setInterval(250)
        self._stylesheet_rebuild_timer.timeout.connect(self._flush_stylesheet_rebuild)

        # --- barre de navigation (ex barre du haut, supprimee) : racine, parcourir, presets, reglages ---
        self.root_field = QLineEdit(str(root))
        self.root_field.setFont(role_font("info", 11, 400))
        self.root_field.setFixedHeight(self._nav_input_height())
        self.root_field.setFixedWidth(scaled(190))
        self.root_field.setToolTip("Racine des projets")
        self.root_field.returnPressed.connect(self.reload)

        # Boutons de la barre : TOUS de la meme taille, chacun avec son icone (Reglages > Barre de navigation).
        self.btn_browse = IconButton("browse", role_color("buttons", "#c4cacf"), C["text"])
        self.btn_presets = IconButton("presets", role_color("buttons", "#c4cacf"), C["text"])
        # IconButton (voir la classe, juste avant TitleBar), PAS un glyphe
        # de police "⚙" : aucune police testee (sans_family(), Segoe UI
        # Symbol...) ne le rendait de facon fiable a cette taille — meme
        # correctif que pour les boutons min/max/close de TitleBar.
        self.btn_settings = IconButton("gear", role_color("buttons", "#c4cacf"), C["text"])
        # Ancien bouton de la fenetre v1 (retiree) : cache, garde pour les chemins de widgets enregistres.
        self.btn_style = IconButton("sliders", role_color("buttons", "#c4cacf"), C["text"])
        # Repli / depli des colonnes de set (ex bouton de la colonne Focus), maintenant dans la barre.
        self.btn_collapse = IconButton("dchevron_right", role_color("buttons", "#c4cacf"), C["text"])
        # Modes (demande de l'utilisateur) : visionneuse sur la selection, editeur de texte (grise tant que la
        # selection n'est pas un fichier texte, voir _sync_mode_buttons).
        self.btn_viewer = IconButton("viewer", role_color("buttons", "#c4cacf"), C["text"])
        self.btn_text_editor = IconButton("text_editor", role_color("buttons", "#c4cacf"), C["text"])
        # Board (paquet board/, facon Miro) : grise tant que la selection n'est pas un fichier .mro.
        self.btn_board = IconButton("board", role_color("buttons", "#c4cacf"), C["text"])
        # Module video (paquet fm_video/) : grise tant que la selection n'est pas une video ou une image.
        self.btn_video = IconButton("video", role_color("buttons", "#c4cacf"), C["text"])
        self.btn_video.setToolTip("Module vidéo (vidéo, séquence d'images EXR / TIFF / PNG…)")
        self.btn_video.clicked.connect(self._toggle_video)
        self._video = None
        self._video_buttons = []
        self.btn_viewer.setToolTip("Visionneuse (sélection en cours)")
        self.btn_text_editor.setToolTip("Éditeur Markdown / code (sélectionner une note, un fichier texte ou de code)")
        self.btn_board.setToolTip("Board (sélectionner un fichier .mro — clic droit dans une colonne > Créer un mro)")
        self.btn_viewer.clicked.connect(self._on_viewer_button)
        self.btn_text_editor.clicked.connect(self._toggle_md_editor)
        self.btn_board.clicked.connect(self._toggle_board)
        self._md_open = False                    # module Markdown / code (paquet mdeditor/) ouvert
        self._editor_buttons = []
        self._board = None
        self._drawing_relay = None               # lecture de dessin DXF / DWG en cours (_open_cad_drawing)
        self._board_buttons = []
        for btn in (self.btn_browse, self.btn_presets, self.btn_settings, self.btn_collapse, self.btn_viewer,
                    self.btn_text_editor, self.btn_board, self.btn_video):
            btn.setCursor(Qt.ArrowCursor)
            btn.setFlat(True)
            btn.setStyleSheet("QPushButton { background: transparent; border: none; }"
                              f"QPushButton:hover {{ background: {C['hover']}; }}")
        self.btn_browse.setToolTip("Parcourir…")
        self.btn_presets.setToolTip("Gérer les presets…")
        self.btn_settings.setToolTip("Parametres")
        self.btn_collapse.setToolTip("Replier les colonnes de set")
        self.btn_collapse.clicked.connect(lambda: self._toggle_project_columns())
        _HoverPrime(self.btn_collapse, self._prime_slide_snapshot)      # capture preparee des le survol
        self.btn_style.setToolTip("Parametres visuels")
        self.btn_style.setVisible(False)
        self.btn_browse.clicked.connect(self.browse_root)
        self.btn_presets.clicked.connect(self._open_preset_manager)
        self.btn_settings.clicked.connect(lambda: self.open_settings("general"))
        # Chemin ouvert a la derniere fermeture (voir closeEvent, go_to_last_place).
        self._last_place: Path | None = None

        self.preview_cache_progress = QProgressBar()
        self.preview_cache_progress.setFixedSize(scaled(132), scaled(15))
        self.preview_cache_progress.setTextVisible(False)
        self.preview_cache_progress.setRange(0, 1)
        self.preview_cache_progress.setValue(0)
        self.preview_cache_progress.setVisible(False)
        self.preview_cache_progress.setToolTip("Mise en cache des aperçus")
        self.preview_cache_progress.setStyleSheet(
            f"QProgressBar {{ background: {C['chrome']}; border: 1px solid {C['border']}; "
            f"border-radius: 3px; }} QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}"
        )

        # Presets : menu deroulant (preset actif) dans la barre ; « Gerer les presets… » = l'icone btn_presets
        # (settings_presets.py, briques des reglages).
        import settings_window_v2
        from settings_presets import PresetPicker
        settings_window_v2.seed_window_look(ui_state.APPLIED_SETTINGS or load_settings())
        self.preset_picker = PresetPicker()
        self.preset_picker.manage.hide()
        self.preset_picker.select.setFixedHeight(self._nav_input_height())
        self.preset_picker.refresh(ui_state.APPLIED_SETTINGS or load_settings())
        self.preset_picker.presetChosen.connect(self._choose_preset)
        self.preset_picker.manageRequested.connect(self._open_preset_manager)
        self._preset_manager = None

        # --- zone des colonnes ---
        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        # column_gap() (pas 0 en dur) : lit deja la valeur persistee (voir
        # apply_all_settings, appele par main() AVANT la construction de
        # cette fenetre) — Fenetre de parametres > Colonnes > Distance
        # entre colonnes, voir la remarque de l'utilisateur. max(0, ...) :
        # column_gap() peut valoir -1 (voir set_column_gap/la remarque de
        # l'utilisateur, "que les bordures ne se cumulent pas"), mais
        # QBoxLayout.setSpacing() n'accepte PAS un espacement reellement
        # negatif — verifie directement, TOUTE valeur negative y retombe
        # silencieusement sur l'espacement du STYLE (6px ici, pire qu'un
        # simple 0) plutot que -1px reel. L'effet "-1" (filet non cumule)
        # passe donc par Column._suppress_left()/DetailPanel._suppress_left()
        # (chacune masque son propre bord gauche quand collee a sa voisine),
        # pas par un espacement negatif ici.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))

        self.detail = DetailPanel()
        from background_status import BackgroundStatus
        self._background_status = BackgroundStatus(self.detail)
        self.detail.preview_double_clicked.connect(self._toggle_project_columns_hidden)
        self._detail_state_width = {}   # {replie: largeur de l'inspecteur} (voir _set_columns_collapsed_now)
        self._inspector_visible = False
        self.detail.hide()
        self._inspector_shortcut = QShortcut(QKeySequence("I"), self)
        self._inspector_shortcut.setContext(Qt.WindowShortcut)
        self._inspector_shortcut.activated.connect(self._toggle_inspector)

        # objectName + selecteur ID : le fond au-dela de la derniere colonne
        # (l'espace que la colonne Inspecteur, desormais a largeur fixe, ne
        # comble plus) est C["window"] ("Fond") — DISTINCT du fond de chaque
        # colonne/panneau (C["void"], peint par chacun sur lui-meme, voir
        # Column/PreviewColumn/DetailPanel), qui ne depend plus de ce widget
        # pour son propre "vide" — voir la remarque de l'utilisateur,
        # nouvelle capture annotee a l'appui (auparavant les deux etaient
        # confondus dans le meme C["void"]).
        columns_host = QWidget()
        self.columns_host = columns_host
        columns_host.setObjectName("ColumnsHost")
        columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['window']}; }}")
        host_layout = QHBoxLayout(columns_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addLayout(self.columns_layout)
        host_layout.addStretch(1)
        host_layout.addWidget(self.detail, 0)

        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(columns_host)
        # Molette en etat focus : image suivante / precedente (voir eventFilter).
        self.scroll.viewport().installEventFilter(self)
        # Clic dans le vide a cote de l'image en focus : elle se replie dans la planche.
        columns_host.installEventFilter(self)
        # Bouton « precedent » de la souris : sortie de la visionneuse (voir _MouseBackFilter).
        self._mouse_back = _MouseBackFilter(self)
        self._project_columns_hidden = self._project_columns_hidden   # filtre pose seulement colonnes masquees
        self._focus_wheel = 0
        self._focus_path = None       # fichier montre au centre quand il attend son apercu (voir _focus_on_file)
        _previews._PREVIEW_DECODE_MANAGER.ready.connect(self._on_focus_preview_ready)
        # Visionneuse (colonnes masquees, image seule au centre, voir _enter_viewer) : fichiers a
        # apercu du dossier et rang de celui montre ; images decodees en fond ; la colonne et
        # l'inspecteur (masques) ne suivent qu'au repos (_viewer_sync) ou au retour des colonnes.
        self._viewer_paths: list = []
        self._viewer_index = -1
        self._viewer_previews: dict = {}      # apercus des voisines non-images (PSD, 3D...), pour le ruban
        self._focus_origin_badge = QLabel(self.scroll.viewport())
        self._focus_origin_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._focus_origin_badge.setStyleSheet(
            "color: #d7e0e8; background: #30363dcc; border-radius: 3px; padding: 3px 7px; font-size: 10px;"
        )
        self._focus_origin_badge.hide()
        self._focus_images = FocusImageLoader(self)
        self._focus_images.ready.connect(self._on_focus_image_ready)
        self._viewer_sync = QTimer(self)
        self._viewer_sync.setSingleShot(True)
        self._viewer_sync.setInterval(self._VIEWER_SYNC_MS)
        self._viewer_sync.timeout.connect(self._sync_viewer_selection)
        self._large_lightroom_timer = QTimer(self)
        self._large_lightroom_timer.setInterval(10000)
        self._large_lightroom_timer.timeout.connect(self._request_current_lightroom_preview)
        # Capture des colonnes pour leur RETOUR, faite d'avance au repos dans la visionneuse (_pregrab_columns).
        self._return_grab = QTimer(self)
        self._return_grab.setSingleShot(True)
        self._return_grab.setInterval(900)
        self._return_grab.timeout.connect(self._pregrab_columns)
        self._gallery_deselected = False         # colonne deselectionnee d'avance, planche ouverte
        self._filmstrip = None
        self._viewer_keys: list = []
        self._viewer_cursor = None
        self._viewer_idle = QTimer(self)        # la pellicule revient au moindre mouvement de souris
        self._viewer_idle.setInterval(150)
        self._viewer_idle.timeout.connect(self._poll_viewer_cursor)
        self._focus_pinch = 0
        # Planches PureRef dans la visionneuse : chaque .pur est remplace par ses images (fichiers du
        # cache, voir preview_column.pur_image_files) ; image -> (planche, rang) pour suivre la colonne.
        self._pur_expansions: dict = {}         # planche -> (date, [fichiers])
        self._pur_sources: dict = {}            # image (str) -> (planche Path, rang)
        self._pur_tasks: dict = {}              # planche (str) -> PureRefImagesTask en cours
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- barre de statut ---
        self.path_label = QLabel("")
        import lightroom_bridge
        lightroom_bridge._signal_bus().failed.connect(self._on_lightroom_proxy_error)
        lightroom_bridge._signal_bus().updated.connect(self._on_lightroom_attribute_written)
        self._lightroom_error_connected = True
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right = QLabel("read-only")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        self.md_margin_slider = QSlider(Qt.Horizontal)
        self.md_margin_slider.setRange(0, 1000)
        self.md_margin_slider.setFixedWidth(scaled(140))
        self.md_margin_slider.setToolTip("Marge gauche et droite du module Markdown")
        self.md_margin_slider.setValue(int((ui_state.APPLIED_SETTINGS or {}).get("md_module_padding", 0)))
        self.md_margin_slider.valueChanged.connect(self._set_md_margin)
        self.md_margin_slider.hide()
        self._md_margin_timer = QTimer(self)
        self._md_margin_timer.setSingleShot(True)
        self._md_margin_timer.setInterval(300)
        self._md_margin_timer.timeout.connect(self._persist_md_margin)

        statusbar = QWidget()
        self.statusbar = statusbar
        statusbar.setFixedHeight(STATUS_HEIGHT)
        # objectName + selecteur ID : meme piege/correctif que #TitleBar.
        statusbar.setObjectName("StatusBar")
        statusbar.setStyleSheet(
            f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}"
        )
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(12)
        status_layout.addWidget(self.path_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.preview_cache_progress)
        status_layout.addWidget(self.status_right)
        status_layout.addWidget(self.md_margin_slider)

        self.titlebar = TitleBar(self)
        self.titlebar._background_status = self._background_status
        self.titlebar.add_tools(self.root_field, self.btn_browse, self.preset_picker, self.btn_presets,
                                self.btn_settings, self.btn_collapse, self.btn_viewer, self.btn_text_editor,
                                self.btn_board, self.btn_video)
        self._sync_mode_buttons()
        self.titlebar.refresh_sizes()
        self.titlebar.refresh_look()

        # objectName + selecteur ID : une regle "nue" (sans selecteur) posee
        # via setStyleSheet sur un widget conteneur se propage a TOUS ses
        # descendants sans style propre (fond ET bordure y compris) — un
        # "border" ici sans ce ciblage strict entourait chaque QLabel de
        # l'inspecteur d'un cadre. Le contour est peint ici meme (pas
        # seulement laisse a Windows/_apply_native_frame) : DWM ne le
        # rendait pas de facon fiable dans tous les cas (coins carres
        # compris), ce filet QSS garantit un contour visible tout autour de
        # la fenetre quel que soit le reglage de coins.
        central = CentralFrame()           # fond, filet et coins PEINTS (main_window/helpers.py), plus en QSS
        self.central = central
        central.setObjectName("CentralFrame")
        layout = QVBoxLayout(central)
        # Marge de 1px (= l'epaisseur du filet ci-dessus), PAS 0 : a marge
        # nulle, les enfants (titlebar, colonnes...) sont peints PAR-DESSUS
        # la bordure de central sur ses 4 cotes (verifie pixel par pixel),
        # la rendant invisible malgre WA_StyledBackground — l'ordre de
        # peinture Qt fait passer les enfants apres le fond/bordure du
        # parent, donc un enfant a bord franc la recouvre entierement.
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.titlebar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(statusbar)
        self.setCentralWidget(central)

        self.addAction(QAction(self, shortcut="F5", triggered=self.reload))
        self.reload()
        self._apply_native_frame()

        self._restore_window_state()
        self._idle_preview_scheduler = _IdlePreviewScheduler(self)
        self._idle_preview_scheduler.cache_progress.connect(self._update_preview_cache_progress)
        self._interface_move_mode = _InterfaceMoveMode(self)
        # Les aperçus demandés par les colonnes arrivent avant le balayage
        # automatique (actuellement optionnel) : la barre reste utile dans ce
        # cas aussi, même si le nombre total n'est pas encore connu.
        self._preview_cache_active = set()
        _previews._PREVIEW_DECODE_MANAGER.started.connect(self._preview_cache_started)
        _previews._PREVIEW_DECODE_MANAGER.ready.connect(self._preview_cache_finished)
        _previews._PREVIEW_DECODE_MANAGER.turntable_ready.connect(self._preview_cache_finished)
        import settings_element_style       # clic droit > « Override settings » sur les elements des reglages
        settings_element_style.add_listener(self._on_element_style_saved)

    def _update_preview_cache_progress(self, visible: bool, completed: int, total: int, message: str):
        """Affiche l'avancement du cache automatique sans interrompre l'interface."""
        bar = self.preview_cache_progress
        if not visible:
            bar.setVisible(False)
            return
        bar.setVisible(True)
        if total <= 0:
            bar.setRange(0, 0)
            bar.setToolTip(message or "Recherche des images à mettre en cache…")
        else:
            bar.setRange(0, total)
            bar.setValue(min(completed, total))
            bar.setToolTip(message or f"Mise en cache des images — {completed}/{total}")

    def _on_lightroom_proxy_error(self, path: str, message: str):
        self.path_label.setText(f"Lightroom · {Path(path).name} : {message}")

    def _on_lightroom_attribute_written(self, path: str, field: str):
        if field == "open":
            self.path_label.setText(f"Lightroom · {Path(path).name} ouvert en mode Développement")
            return
        labels = {"rating": "note", "color": "couleur", "status": "drapeau", "keywords": "mots-clés"}
        self.path_label.setText(f"Lightroom · {labels.get(field, field)} enregistré pour {Path(path).name}")

    def _preview_cache_started(self, path: str):
        """Affiche au moins un indicateur pendant un cache lancé par une colonne."""
        self._preview_cache_active.add(path)
        scheduler = self._idle_preview_scheduler
        if scheduler.scan_in_progress or scheduler.batch_total:
            return
        bar = self.preview_cache_progress
        bar.setRange(0, 0)
        bar.setVisible(True)
        bar.setToolTip(f"Mise en cache de {Path(path).name}")

    def _preview_cache_finished(self, path: str, *_args):
        self._preview_cache_active.discard(path)
        scheduler = self._idle_preview_scheduler
        if self._preview_cache_active or scheduler.scan_in_progress or scheduler.batch_total:
            return
        self.preview_cache_progress.setVisible(False)

    def _restore_window_state(self):
        """Reapplique la position/taille de fenetre au moment de la derniere
        fermeture (voir closeEvent). L'appli s'ouvre toujours a la racine :
        le dossier parcouru a la derniere fermeture n'est pas retrouve
        automatiquement, mais retenu pour le bouton "Dernier endroit" (voir
        go_to_last_place)."""
        state = load_window_state()
        geometry_b64 = state.get("geometry")
        if geometry_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode("ascii")))
            except (ValueError, TypeError):
                pass
        last_path = state.get("last_path")
        self._last_place = Path(last_path) if last_path else None

    def go_to_last_place(self):
        if self._last_place is not None:
            self._navigate_to(self._last_place)

    def _navigate_to(self, target: Path):
        """Deplie les colonnes jusqu'a `target` en simulant les selections
        successives (a partir de la PREMIERE colonne, quel que soit l'endroit
        ou l'on se trouve deja), sans effet si `target` n'existe plus ou n'est
        pas sous la racine actuellement affichee. Un dossier in/over/out est
        franchi : la suite se cherche dans les colonnes du groupe IN/OVER/OUT/
        LOGICIELS, qui ouvrent ensuite leur propre colonne de contenu."""
        root = Path(self.root_field.text())
        try:
            parts = target.relative_to(root).parts
        except ValueError:
            return
        self._nav_plan = {"root": root, "parts": parts, "index": 0, "column": 0, "current": root}
        self._resume_path_navigation()

    def _resume_path_navigation(self):
        """Un niveau par tour Qt ; les colonnes en lecture reprennent par leur signal loaded."""
        plan = getattr(self, "_nav_plan", None)
        if plan is None or getattr(self, "_remote_selection", None):
            return
        if plan["index"] >= len(plan["parts"]):
            self._nav_plan = None
            if self.columns:
                for column in reversed(self.columns):
                    path = column.current_path()
                    if path is not None:
                        self.detail.show_path(path)
                        break
                last = self.columns[-1]
                QTimer.singleShot(0, lambda c=last: self._animate_column_in(c))
            return
        col_index = plan["column"]
        if not self.columns:
            self._nav_plan = None
            return
        candidates = ([self.columns[col_index]] if col_index < len(self.columns)
                      else [self.columns[-1], *self.group_columns])
        if any(c.loading or c._load_timer.isActive() for c in candidates):
            return
        part = plan["parts"][plan["index"]]
        current = plan["current"] / part
        match = column = None
        for candidate in candidates:
            for i in range(candidate.list.count()):
                item = candidate.list.item(i)
                if Path(item.data(ROLE_PATH)).name == part:
                    match, column = item, candidate
                    break
            if match is not None:
                break
        plan["index"] += 1
        plan["current"] = current
        if match is None:
            # Les dossiers de statut sont franchis dans le groupe, hors liste.
            if part.lower() not in STATUS_FOLDERS:
                self._nav_plan = None
                return
        else:
            in_group = column in self.group_columns
            is_dir = bool(match.data(ROLE_ISDIR))
            self._bulk_navigation = self._navigating_step = True
            try:
                if column.list.currentItem() is match:
                    column.reselect_current()
                else:
                    column.list.setCurrentItem(match)
            finally:
                self._bulk_navigation = self._navigating_step = False
            plan["column"] = len(self.columns) - 1 if in_group else col_index + 1
            if not is_dir:
                plan["index"] = len(plan["parts"])
        QTimer.singleShot(0, self._resume_path_navigation)

    # -- Espace au-dessus d'un element de la fenetre (clic droit la ou rien d'autre n'a de menu) --
    # Les lignes des colonnes ont leur propre ligne de menu (Column.set_item_space) ; ici, tout le
    # reste. Retenu dans les reglages (`ui_spaces`, cle = chemin du widget dans la fenetre).

    def contextMenuEvent(self, event):
        clicked = self.childAt(event.pos())
        target = space_target(clicked, self)
        key = widget_path(target, self) if target is not None else None
        if key is None:
            event.ignore()
            return
        menu = Menu(self)
        make_space_actions(menu, int(getattr(target, "_space_above_px", 0)), int(getattr(target, "_space_below_px", 0)),
                           lambda value, t=target, k=key: self._set_ui_space(t, k, value),
                           lambda value, t=target, k=key: self._set_ui_space(t, k, value, below=True),
                           widget=clicked)
        menu.exec(event.globalPos())
        event.accept()

    _UI_SPACE_KEYS = {False: "ui_spaces", True: "ui_spaces_below"}

    def _set_ui_space(self, target: QWidget, key: str, height: int, below: bool = False):
        (set_space_below if below else set_space_above)(target, height)
        name = self._UI_SPACE_KEYS[below]
        stores = self._ui_space_stores = getattr(self, "_ui_space_stores", None) or {}
        if name not in stores:
            stores[name] = dict((ui_state.APPLIED_SETTINGS or {}).get(name) or {})
        spaces = stores[name]
        if height:
            spaces[key] = int(height)
        else:
            spaces.pop(key, None)
        timer = getattr(self, "_ui_space_timer", None)
        if timer is None:
            timer = self._ui_space_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_ui_spaces)
        timer.start()

    def _save_ui_spaces(self):
        settings = load_settings()
        for name, spaces in (getattr(self, "_ui_space_stores", None) or {}).items():
            settings[name] = dict(spaces)
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS[name] = dict(spaces)
        save_settings(settings)

    def _apply_ui_spaces(self):
        import settings_element_style            # styles propres (« Override settings ») des elements
        settings_element_style.reapply_soon(self, ui_state.APPLIED_SETTINGS)
        for below, name in self._UI_SPACE_KEYS.items():
            for key, height in ((ui_state.APPLIED_SETTINGS or {}).get(name) or {}).items():
                target = widget_at_path(self, key)
                if target is not None and height:
                    (set_space_below if below else set_space_above)(target, int(height))
        # Style choisi a la main pour un toggle de la fenetre (clic droit > Style du toggle).
        overrides = (ui_state.APPLIED_SETTINGS or {}).get("toggle_style_overrides") or {}
        for toggle in self.findChildren(_Toggle):
            key = overrides.get(self._toggle_id(toggle) or "")
            if key:
                toggle.setStyleKey(key)

    def _toggle_id(self, toggle: QWidget) -> str | None:
        path = widget_path(toggle, self)
        return f"main|{path}" if path else None

    def _set_toggle_style(self, toggle: QWidget, key: str | None):
        toggle_id = self._toggle_id(toggle)
        if toggle_id is None:
            return
        settings = load_settings()
        overrides = dict(settings.get("toggle_style_overrides") or {})
        if key:
            overrides[toggle_id] = key
        else:
            overrides.pop(toggle_id, None)
        settings["toggle_style_overrides"] = overrides
        save_settings(settings)
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["toggle_style_overrides"] = dict(overrides)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_ui_spaces_applied", False):
            self._ui_spaces_applied = True
            QTimer.singleShot(0, self._apply_ui_spaces)

    def closeEvent(self, event):
        video_pane = getattr(self, "_video", None)
        if video_pane is not None:                                      # module video : fils de fond arretes
            video_pane.shutdown()
        board_pane = getattr(self, "_board", None)
        if board_pane is not None and not board_pane.confirm_leave():   # board : enregistre (contenu + vue)
            event.ignore()
            return
        import fm_markdown.pane as md_pane
        pane = md_pane.instance(create=False)
        if getattr(self, "_md_open", False) and pane is not None and not pane.confirm_leave():
            event.ignore()                                            # module Markdown : tout est enregistre
            return
        if pane is not None and pane.parentWidget() is None:
            pane.deleteLater()           # page prechargee sans parent : detruite avant l'application (QtWebEngine)
        automatic = getattr(self, "_automatic_tasks", None)
        if automatic is not None:
            automatic.stop()
        state = load_window_state()
        state["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        state["last_path"] = str(self.columns[-1].directory) if self.columns else ""
        save_window_state(state)
        dialog = getattr(self, "_settings_dialog_v2", None)       # fenetre sans parent : elle part avec celle-ci
        if dialog is not None:
            try:
                dialog.close()
                dialog.deleteLater()
            except RuntimeError:
                pass
        import fm_markdown.css_sync as css_sync                       # feuille partagee avec Obsidian : rien en attente
        css_sync.engine().flush()
        self._nav_plan = None
        pending = getattr(self, "_remote_selection", None)
        if pending is not None:
            from column_loading import loader
            loader().cancel(pending[0], self)
            self._remote_selection = None
        for column in [*self.columns, *self.group_columns]:
            if hasattr(column, "cancel_loading"):
                column.cancel_loading()
        super().closeEvent(event)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redonne le redimensionnement par les bords a cette fenetre sans
        decoration systeme (voir __init__) — voir app_style.resize_hit_test
        pour le detail (partage avec SettingsWindow.nativeEvent)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _apply_native_frame(self):
        """Coins/bordure DWM (voir app_style.apply_dwm_frame) + accrochage
        aux bords (resizable=True, seule cette fenetre est vraiment
        redimensionnable par l'utilisateur — voir nativeEvent/WM_NCHITTEST
        pour le redimensionnement par les bords, gere a la main)."""
        apply_dwm_frame(self, ui_state.WINDOW_RADIUS, C["border"], resizable=True)


def _save_menu_layouts(layouts: dict) -> None:
    """Disposition des menus contextuels choisie a la main (settings_menu) : etat temps reel, ecrit aussitot,
    SEULE (save_live_state : jamais le preset actif fige dans le fichier au passage)."""
    from settings_store import save_live_state
    save_live_state("context_menu_layouts", layouts)
    if isinstance(ui_state.APPLIED_SETTINGS, dict):
        ui_state.APPLIED_SETTINGS["context_menu_layouts"] = layouts


def _install_context_menus() -> None:
    """Menus contextuels (settings_menu) : habillage = Reglages > Menu contextuel, lu a chaque ouverture."""
    from config import DATA_DIR, ICONS_DIR
    from browser_core import _resolve_font_family
    import settings_menu
    settings_menu.install(
        values=lambda: ui_state.APPLIED_SETTINGS,
        load_layouts=lambda: (ui_state.APPLIED_SETTINGS or {}).get("context_menu_layouts") or {},
        save_layouts=_save_menu_layouts,
        font_family=lambda label, size, weight: _resolve_font_family(label, size, weight),
        icon_dir=DATA_DIR / "menu_icons", icon_sources=(ICONS_DIR,))


def _install_qt_message_filter():
    """Retire deux avertissements Qt inoffensifs qui noyaient la console :
    - « QWidgetWindow(...) must be a top level window » : une video affichee dans une
      QScrollArea (la zone des colonnes) rend natifs tous ses parents (comportement
      de Qt), puis chaque menu ou boite de dialogue ouvert depuis eux le signale ;
    - les alertes libpng sur le profil colorimetrique de certaines captures PNG.
    Tous les autres messages restent affiches."""
    from PySide6.QtCore import QLoggingCategory, qInstallMessageHandler
    QLoggingCategory.setFilterRules("qt.gui.imageio.warning=false")

    def handler(_mode, _context, message):
        if "must be a top level window" in message:
            return
        sys.stderr.write(message + "\n")

    qInstallMessageHandler(handler)


def _main_toggle_style_listener(toggle, key):
    """Style choisi au clic droit sur un toggle de la fenetre principale : enregistre pour lui."""
    window = toggle.window()
    if isinstance(window, PipelineBrowser):
        window._set_toggle_style(toggle, key)


TOGGLE_STYLE_LISTENERS.append(_main_toggle_style_listener)


def _install_error_log():
    """Exceptions Python non rattrapees (dont celles des fonctions appelees par Qt : peinture, souris…) : ecrites aussi
    dans `data/error_log.txt` (`pythonw` n'a pas de console). Aucun gestionnaire d'exceptions Windows (`faulthandler`
    fait planter QtWebEngine)."""
    import traceback
    log = Path(__file__).with_name("data") / "error_log.txt"
    previous = sys.excepthook

    def hook(kind, value, trace):
        try:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("\n--- " + time.strftime("%Y-%m-%d %H:%M:%S") + " ---\n")
                handle.write("".join(traceback.format_exception(kind, value, trace)))
        except OSError:
            pass
        previous(kind, value, trace)
    sys.excepthook = hook


def main():
    _install_error_log()
    _install_qt_message_filter()
    settings = load_settings(startup=True)      # le preset par defaut devient le preset actif
    apply_all_settings(settings)
    root = Path(settings["root_path"])
    _config.ROOT = root
    # Cache en arriere-plan : index des noms (lu une fois), anciens noms renommes, puis menage (ni images
    # inutiles ni apercus de fichiers supprimes). Rien de tout cela sur le fil de l'interface.
    threading.Thread(target=lambda: (migrate_cache_names(), sweep_preview_cache_if_due()),
                     name="preview-cache-sweep", daemon=True).start()

    # Le winId() d'une fenetre enfant (reglages, config des colonnes : voir
    # apply_dwm_frame) rendait natifs ses « freres », dont #CentralFrame : un
    # cadre natif dans la fenetre translucide n'est plus recompose image par
    # image et les animations des colonnes sautaient des l'ouverture des
    # reglages (tests/_probe_screen_anim.py).
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    # QtWebEngine (inspecteur des notes, module Markdown) cree apres l'application : contextes OpenGL partages.
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    # OpenGL : echange de tampons SANS attendre le balayage de l'ecran (format de la FENETRE, a poser avant
    # l'application) — une image de retard en moins pendant un pan du CAD ; la couche GPU cadence elle-meme ses
    # images (fm_cad/cad_gpu.py, FramePacer).
    try:
        from fm_cad.cad_gpu import low_latency_format
        low_latency_format()
    except Exception:                                   # noqa: BLE001 - paquet du board absent : format par defaut
        pass
    app = QApplication(sys.argv)
    apply_style(app)
    _install_context_menus()
    window = PipelineBrowser(root)
    window.show()
    window._start_settings_idle_watch()     # reglages prepares apres 1 min sans activite sur l'appli (rien au lancement)
    window._start_theme_link()              # aspect : preset fm_theme lie, suivi en direct (fm_theme/live.py)
    QTimer.singleShot(6000, window._preload_md_editor)       # module Markdown / code prepare en fond
    QTimer.singleShot(4500, window._preload_video)            # module video : bibliotheques chargees en fond
    QTimer.singleShot(1500, window._start_css_sync)          # feuille CSS partagee avec Obsidian
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
