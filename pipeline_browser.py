import json
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import (
    QByteArray, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, QTimer,
)
from PySide6.QtGui import (
    QAction,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    PREVIEW_STACK_TITLE,
    STYLESHEET_COLOR_KEYS,
    apply_dwm_frame,
    apply_style,
    auto_collapse_set_columns,
    column_gap,
    refresh_style,
    resize_hit_test,
    role_color,
    role_font,
    scaled,
    start_native_move,
    column_style_for,
)
import ui_state
from config import (
    COLUMN_LABELS,
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
    load_settings,
)
from settings_window import (
    SettingsWindow,
)
from browser_core import (
    COLUMN_SETTINGS,
    DEFAULT_WORK_DIR_TYPE,
    GROUP_COLUMN_DEFAULT_HEIGHT,
    GROUP_COLUMN_MAX_HEIGHT,
    GROUP_COLUMN_MIN_HEIGHT,
    ROLE_PATH,
    ROLE_SOURCE_LABEL,
    STATUS_FOLDERS,
    STATUS_HEIGHT,
    TITLEBAR_HEIGHT,
    TOPBAR_HEIGHT,
    WORK_DIR_TYPES,
    _WIDGET_SIZE_MAX,
    _hide_resize_width,
    _is_globally_omitted_path,
    _named_subdir,
    _show_resize_width,
    _update_layout_setting,
    apply_all_settings,
    col_width,
    load_layout_settings,
    load_project_columns,
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
    IconButton,
    PreviewColumn,
)


# ==========================================================================
# Barre de titre intrinseque : la fenetre principale est sans decoration
# systeme (voir PipelineBrowser.__init__), donc cette barre en tient lieu —
# deplacement, reduction/agrandissement/fermeture — avec le meme habillage
# sombre que le reste de l'appli plutot que le chrome blanc/bleu de Windows.
# ==========================================================================

class TitleBar(QWidget):

    def __init__(self, window: "PipelineBrowser", parent=None):
        super().__init__(parent)
        self._window = window
        self.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        # objectName + selecteur ID (voir la meme remarque pour #CentralFrame
        # et #DetailPanel) : sans ce ciblage strict, le "border-bottom" nu se
        # propageait au title_label (le seul enfant sans bordure propre),
        # qui se retrouvait souligne sur sa seule largeur de texte au lieu du
        # filet visant a courir sur toute la largeur de la barre.
        self.setObjectName("TitleBar")
        # Indispensable pour qu'une sous-classe de QWidget (comme celle-ci)
        # peigne effectivement son propre style — sans lui, le fond et la
        # bordure ci-dessus sont ignores au rendu (seul un QWidget "nu",
        # sans sous-classe, les applique automatiquement) : voir Column, qui
        # pose deja cet attribut pour la meme raison.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        self.setMouseTracking(True)

        icon = QLabel()
        self._icon = icon
        icon_size = scaled(9)
        icon.setFixedSize(icon_size, icon_size)
        # Icone perso (voir Settings > ICONES > General, UI_ICON_APP_LOGO)
        # si l'utilisateur en a choisi une, sinon le carre neutre d'origine.
        custom_logo = custom_ui_icon_pixmap(UI_ICON_APP_LOGO, icon_size)
        if custom_logo is not None:
            icon.setPixmap(custom_logo)
            icon.setStyleSheet("background: transparent;")
        else:
            icon.setStyleSheet(f"border: 1px solid {C['mark_dir_bd']}; background: transparent;")
        # Transparent aux clics : sans ca, cliquer PILE sur l'icone ou le
        # texte du titre (plutot qu'a cote, sur le fond nu de la barre) ne
        # declenche jamais TitleBar.mousePressEvent ci-dessous — un widget
        # enfant sous le curseur capte l'evenement souris meme s'il n'en
        # fait rien, Qt ne le remonte pas tout seul au parent. C'etait la
        # cause du "des fois le clic ne deplace pas la fenetre".
        icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.title_label = QLabel(window.windowTitle())
        self.title_label.setFont(role_font("app", 11, 400, tracking=0.01))
        self.title_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(icon)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.btn_min = self._make_button("min", window.showMinimized)
        self.btn_max = self._make_button("max", self._toggle_max)
        self.btn_close = self._make_button("close", window.close)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def refresh_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) a la
        hauteur de la barre et a ses boutons — construits une seule fois
        (contrairement aux colonnes, jamais reconstruits), donc sans cela le
        slider d'echelle ne les affecterait qu'au prochain lancement."""
        self.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        self._icon.setFixedSize(scaled(9), scaled(9))
        for btn in (self.btn_min, self.btn_max, self.btn_close):
            btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))

    def _make_button(self, kind: str, slot) -> IconButton:
        btn = IconButton(kind, C["label"], C["text"])
        btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))
        btn.setCursor(Qt.ArrowCursor)
        btn.setFlat(True)
        btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; border: none;"
            "}"
            "QPushButton:hover {"
            f"  background: {C['hover']};"
            "}"
        )
        btn.clicked.connect(slot)
        return btn

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_max()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Voir app_style.start_native_move : SendMessage synchrone
            # plutot que QWindow.startSystemMove() (qui POSTE son SC_MOVE,
            # asynchrone) — evite que la fenetre "rate" le debut du glisser
            # si d'autres evenements souris arrivent avant que Windows ne
            # traite ce message en file.
            start_native_move(self._window)
            event.accept()
        else:
            super().mousePressEvent(event)

# ==========================================================================
# Fenetre principale
# ==========================================================================

class PipelineBrowser(QMainWindow):

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
        self._pending_stylesheet_rebuild = False
        self._stylesheet_rebuild_timer = QTimer(self)
        self._stylesheet_rebuild_timer.setSingleShot(True)
        self._stylesheet_rebuild_timer.setInterval(250)
        self._stylesheet_rebuild_timer.timeout.connect(self._flush_stylesheet_rebuild)

        # --- barre du haut ---
        self.root_label = QLabel("Root")
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")

        self.root_field = QLineEdit(str(root))
        self.root_field.setFont(role_font("info", 12, 400))
        self.root_field.setFixedHeight(scaled(24))
        self.root_field.returnPressed.connect(self.reload)

        self.btn_browse = QPushButton("Parcourir")
        self.btn_reload = QPushButton("Refresh")
        self.btn_last_place = QPushButton("↩ Dernier endroit")
        # IconButton (voir la classe, juste avant TitleBar), PAS un glyphe
        # de police "⚙" : aucune police testee (sans_family(), Segoe UI
        # Symbol...) ne le rendait de facon fiable a cette taille — meme
        # correctif que pour les boutons min/max/close de TitleBar.
        self.btn_settings = IconButton("gear", role_color("buttons", "#c4cacf"), C["text"])
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
            btn.setFixedHeight(scaled(24))
            btn.setCursor(Qt.ArrowCursor)
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place):
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.setFixedWidth(scaled(28))
        self.btn_settings.setToolTip("Parametres")
        self.btn_last_place.setToolTip("Revenir a l'endroit ouvert a la derniere fermeture")
        self.btn_browse.clicked.connect(self.browse_root)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_last_place.clicked.connect(self.go_to_last_place)
        self.btn_settings.clicked.connect(self.open_settings)
        # Chemin ouvert a la derniere fermeture (voir closeEvent) : l'appli
        # s'ouvre toujours a la racine, ce bouton permet d'y revenir a la
        # demande plutot que d'y naviguer automatiquement (voir
        # _restore_window_state).
        self._last_place: Path | None = None
        self.btn_last_place.setEnabled(False)

        self.synced_label = QLabel("")
        self.synced_label.setFont(role_font("info2", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")

        topbar = QWidget()
        self.topbar = topbar
        topbar.setFixedHeight(TOPBAR_HEIGHT)
        # objectName + selecteur ID : voir la remarque sur #TitleBar plus
        # haut (meme piege, meme correctif) — root_label et synced_label,
        # simples QLabel sans bordure propre, heriteraient sinon du
        # border-bottom nu et se retrouveraient chacun souligne.
        topbar.setObjectName("TopBar")
        topbar.setStyleSheet(
            f"#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['border']}; }}"
        )
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(10, 0, 10, 0)
        top_layout.setSpacing(10)
        top_layout.addWidget(self.root_label)
        top_layout.addWidget(self.root_field, 1)
        top_layout.addWidget(self.btn_browse)
        top_layout.addWidget(self.btn_reload)
        top_layout.addWidget(self.btn_last_place)
        top_layout.addWidget(self.synced_label)
        top_layout.addWidget(self.btn_settings)

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
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- barre de statut ---
        self.path_label = QLabel("")
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right = QLabel("read-only")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")

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
        status_layout.addWidget(self.status_right)

        self.titlebar = TitleBar(self)

        # objectName + selecteur ID : une regle "nue" (sans selecteur) posee
        # via setStyleSheet sur un widget conteneur se propage a TOUS ses
        # descendants sans style propre (fond ET bordure y compris) — un
        # "border" ici sans ce ciblage strict entourait chaque QLabel de
        # l'inspecteur d'un cadre. Le contour est peint ici meme (pas
        # seulement laisse a Windows/_apply_native_frame) : DWM ne le
        # rendait pas de facon fiable dans tous les cas (coins carres
        # compris), ce filet QSS garantit un contour visible tout autour de
        # la fenetre quel que soit le reglage de coins.
        central = QWidget()
        self.central = central
        central.setObjectName("CentralFrame")
        # Indispensable pour que le "border"/"border-radius" ci-dessous soit
        # reellement peint : sur un QWidget nu, Qt applique le fond du QSS
        # via un chemin rapide qui ignore ce flag, mais PAS la bordure — sans
        # lui, la bordure etait silencieusement ignorée (verifie pixel par
        # pixel : le bord de la fenetre restait exactement la couleur de
        # fond, jamais {C['border']}). Meme remarque que pour TitleBar/
        # Column plus bas, mais leur cas ne concernait jusque-la que le fond.
        central.setAttribute(Qt.WA_StyledBackground, True)
        central.setStyleSheet(
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {ui_state.WINDOW_RADIUS}px; }}"
        )
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
        layout.addWidget(topbar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(statusbar)
        self.setCentralWidget(central)

        self.addAction(QAction(self, shortcut="F5", triggered=self.reload))
        self.reload()
        self._apply_native_frame()

        self._restore_window_state()
        self._idle_preview_scheduler = _IdlePreviewScheduler(self)

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
        self.btn_last_place.setEnabled(self._last_place is not None)

    def go_to_last_place(self):
        if self._last_place is not None:
            self._navigate_to(self._last_place)

    def _navigate_to(self, target: Path):
        """Deplie les colonnes jusqu'a `target` en simulant les selections
        successives, sans effet si `target` n'existe plus ou n'est pas sous
        la racine actuellement affichee."""
        root = Path(self.root_field.text())
        try:
            parts = target.relative_to(root).parts
        except ValueError:
            return
        current = root
        for part in parts:
            current = current / part
            if not self.columns:
                return
            column = self.columns[-1]
            match = None
            for i in range(column.list.count()):
                item = column.list.item(i)
                if Path(item.data(ROLE_PATH)).name == part:
                    match = item
                    break
            if match is None:
                return
            column.list.setCurrentItem(match)
            if not current.is_dir():
                return

    def closeEvent(self, event):
        state = load_window_state()
        state["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        state["last_path"] = str(self.columns[-1].directory) if self.columns else ""
        save_window_state(state)
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

    # -- gestion des colonnes ------------------------------------------

    def reload(self):
        root = Path(self.root_field.text())
        self.prune_after(-1)
        self.detail.clear()
        if not root.is_dir():
            self.path_label.setText(f"Introuvable : {root}")
            self.synced_label.setText("")
            return
        self._project_columns_collapsed = False
        self._auto_collapse_armed = True
        self.add_column(root, 0)
        self.path_label.setText(str(root))
        self.synced_label.setText(datetime.now().strftime("scan %H:%M:%S"))
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
        if self._group_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._group_stack_wrapper)
            self._group_stack_wrapper.setParent(None)
            self._group_stack_wrapper.deleteLater()
            self._group_stack_wrapper = None
        self.group_columns = []
        self._group_context_key = None
        self._last_active_group_column = None

    def _clear_image_preview_columns(self):
        if self._preview_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._preview_stack_wrapper)
            self._preview_stack_wrapper.setParent(None)
            self._preview_stack_wrapper.deleteLater()
            self._preview_stack_wrapper = None
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
            directory, title, is_focus_level=is_focus_level, style_title=style_title,
            display_title=display_title,
            show_dirs=show_dirs, show_files=show_files, omit_dirs=omit_dirs, omit_files=omit_files)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
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
        self._detach_group_stack()
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
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()

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
            column.list.setUniformItemSizes(column.has_thumbnails)
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

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        for i, column in enumerate(self.columns):
            column.set_active(i == last_selected)
        # Colonnes du groupe IN/OVER/OUT/LOGICIELS : UNE SEULE a la fois
        # doit apparaitre "focus" (voir _last_active_group_column, mis a
        # jour par _on_group_item_selected a CHAQUE clic sur l'une d'elles)
        # — pas les 4 independamment des qu'elles ont chacune une
        # selection (1ere version de ce correctif, revenue sur elle : voir
        # la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir").
        for column in self.group_columns:
            column.set_active(
                column is self._last_active_group_column and column.current_path() is not None)

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
        if path is not None and not path.is_dir():
            return None
        return path

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

    def update_preview_stack(self):
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
            wrapper = QWidget()
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
                    PREVIEW_STACK_TITLE, on_toggle=self._toggle_project_columns if offset == 0 else None,
                    user_width=self._preview_column_user_width,
                    on_resize=self._on_preview_column_resized, fit_height=True,
                    display_title=_FOCUS_LEVEL_LABEL.get(level_title, PREVIEW_STACK_TITLE))
                if offset == 0:
                    column.set_toggle_state(self._project_columns_collapsed)
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
        group_wrapper = QWidget()
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
                stable_directory, style_title,
                source_dirs=source_dirs, source_labels=source_labels, display_title=display,
                user_width=self._group_column_user_width, on_resize=self._on_group_column_resized,
                group_kind=kind, on_reorder=self._on_group_reorder,
                user_height=self._group_column_user_heights.get(kind), on_height_resize=self._on_group_height_resized,
                on_height_resize_begin=self._on_group_height_resize_begin,
                on_height_resize_end=self._on_group_height_resize_end,
                fill_height=fill,
                only_recognized_software=(kind == "logiciels" and work_dir_only_recognized_software),
                on_group_maximize=self._on_group_maximize, on_group_equalize=self._on_group_equalize)
            column.selected.connect(lambda col, p, k=kind: self._on_group_item_selected(col, p, k))
            column.activated.connect(self.on_activated)
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

        self._group_stack_wrapper = group_wrapper
        self.columns_layout.insertWidget(anchor + group_anchor_offset, group_wrapper)

        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _on_group_item_selected(self, column: Column, path: Path | None, kind: str) -> None:
        """Reagit a un clic sur une ligne du groupe IN/OVER/OUT/LOGICIELS
        (voir update_preview_stack) : un dossier ouvre son contenu dans une
        VRAIE colonne suivante (voir _open_group_folder) — navigation
        normale, pas l'explorateur Windows. Un fichier ne fait rien de plus
        ici (deja previsualise dans l'inspecteur par la selection normale
        de Column/on_selected — non branche pour ce groupe, voir sa
        remarque) ; double-clic l'ouvre malgre tout via l'application par
        defaut (voir Column.activated/on_activated, cable separement).
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
        if path is not None:
            for other in self.group_columns:
                if other is not column:
                    other.list.clearSelection()
                    other.list.setCurrentItem(None)
        # "focus" BRILLANT reserve au point VRAIMENT courant : un FICHIER
        # (rien ne s'ouvre plus loin) reste actif ; un DOSSIER ouvre une
        # VRAIE colonne plus loin qui devient alors le point courant reel —
        # cette ligne redevient "chemin" (non focus, bleu FONCE) comme une
        # colonne ancestrale de la chaine normale — voir la remarque de
        # l'utilisateur, "in/references qui est actuellement en focus
        # alors qu'il ne devrait pas non plus, il devrait par contre lui
        # etre en bleu fonce puisqu'il fait partie du cheminement".
        if path is not None:
            is_folder = path.is_dir()
            self._last_active_group_column = None if is_folder else column
        self.update_active_column()
        if path is None or not path.is_dir():
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
            if column.width() != new_width:
                column._user_width = new_width
                column.setFixedWidth(new_width)

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

    def on_selected(self, column: Column, path: Path | None):
        index = self.columns.index(column)
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
            self.update_preview_stack()
            self._sync_collapse_state()
            return
        self.path_label.setText(str(path))
        self.detail.show_path(path)
        if path.is_dir():
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
        self.update_preview_stack()

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
                self._apply_project_columns_collapsed(False)
        elif auto_collapse_set_columns() and self._auto_collapse_armed and not self._project_columns_collapsed:
            self._apply_project_columns_collapsed(True)
            self._auto_collapse_armed = False

    def _toggle_project_columns(self):
        """Reagit a l'icone unique portee par la colonne des vignettes
        (voir PreviewColumn/update_preview_stack) : bascule les colonnes de
        la chaine (voir _apply_project_columns_collapsed), et desarme le
        repli automatique pour que ce choix manuel ne soit pas aussitot
        ecrase par _sync_collapse_state tant que la chaine reste la meme.
        Toujours disponible, MEME si le repli automatique est desactive
        (voir auto_collapse_set_columns/_sync_collapse_state) : c'est un
        geste manuel independant."""
        self._apply_project_columns_collapsed(not self._project_columns_collapsed)

    def _on_preview_column_resized(self, new_width: int):
        """Relais de PreviewColumn.resize_update (voir _preview_column_
        user_width, sa remarque de tete) : conserve la largeur choisie a la
        main pour qu'elle survive a la PROCHAINE reconstruction des
        colonnes Focus (update_preview_stack, appelee a chaque navigation),
        ET la repercute TOUT DE SUITE sur les AUTRES colonnes Focus (voir
        PreviewColumn.set_width_external) : ce sont des colonnes SEPAREES
        (voir la remarque de l'utilisateur, "deux colonnes separees, une
        en dessous de l'autre") mais elles doivent rester alignees a la
        meme largeur, glisser le bord de L'UNE suffit a redimensionner
        les autres."""
        self._preview_column_user_width = new_width
        for column in self.image_preview_columns:
            if column.width() != new_width:
                column.set_width_external(new_width)
        self._auto_collapse_armed = False

    def _apply_project_columns_collapsed(self, collapsed: bool):
        """Replie/deplie EXACTEMENT les N premieres colonnes de self.columns
        (voir _chain_expected_total), N = le nombre d'etapes du projet
        courant — jamais au-dela : une colonne de contenu ouverte depuis le
        groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) reste
        TOUJOURS deployee, quoi qu'il arrive aux colonnes de set — voir la
        remarque de l'utilisateur, "attention a bien rabattre toutes
        colonnes ... c'est toutes les colonnes avant les colonnes de
        focus"."""
        self._project_columns_collapsed = collapsed
        expected_total = self._chain_expected_total()
        for c in self.columns[:expected_total]:
            c.set_collapsed(collapsed)
        if self.image_preview_columns:
            self.image_preview_columns[0].set_toggle_state(collapsed)

    def on_activated(self, path: Path):
        open_path(path)

    def browse_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Racine du pipeline", self.root_field.text()
        )
        if chosen:
            self.root_field.setText(chosen)
            self.reload()

    def open_settings(self):
        # Deja ouverte : la ramener au premier plan plutot que d'en ouvrir
        # une seconde (qui ecraserait sa propre previsualisation). La
        # fenetre precedente est detruite cote C++ des sa fermeture (voir
        # WA_DeleteOnClose ci-dessous) : la reference Python devient alors
        # invalide et tout appel dessus (meme isVisible()) leve un
        # RuntimeError qu'il faut absorber pour pouvoir en rouvrir une neuve.
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None:
            try:
                still_visible = existing.isVisible()
            except RuntimeError:
                still_visible = False
            if still_visible:
                existing.raise_()
                existing.activateWindow()
                return
        dialog = SettingsWindow(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        # Non modale : la fenetre principale reste interactive et se
        # met a jour en direct pendant qu'on ajuste les parametres.
        dialog.settingsChanged.connect(self._apply_settings)
        dialog.settingsSaved.connect(self._apply_settings)
        self._settings_dialog = dialog
        dialog.show()

    def _apply_settings(self, settings: dict):
        """Applique des reglages (live, pendant qu'on les ajuste dans la
        fenetre de parametres, ou definitifs a l'enregistrement — les deux
        cas appellent cette meme methode). N'ecrit jamais sur le disque
        (voir SettingsWindow._on_save pour la persistance).

        Si la racine n'a pas change, les colonnes existantes sont juste
        rafraichies sur place (refresh_all_columns) : la navigation en cours
        (profondeur, selection) n'est PAS perdue. Un reload() complet n'a
        lieu que si la racine elle-meme a change, ce qui invalide de toute
        facon le chemin courant."""
        # Cliche AVANT/APRES (voir refresh_all_columns(relayout_titles=...))
        # de la hauteur/l'espacement de ligne EFFECTIFS (COLUMN_SETTINGS,
        # deja resolus general/surcharge par apply_all_settings) de CHAQUE
        # colonne : seules celles ou cette paire a reellement change auront
        # besoin d'un doItemsLayout() plus bas — un cran de slider qui ne
        # touche qu'une couleur/bordure/rayon/padding n'affecte le sizeHint()
        # d'AUCUNE ligne, quelle que soit la colonne — voir la remarque de
        # l'utilisateur, "il y a des ralentissements dans les animations,
        # optimise un maximum".
        prev_geometry = {title: (conf["height"], conf["spacing"]) for title, conf in COLUMN_SETTINGS.items()}
        prev_omissions = (GLOBAL_OMIT_DIR_NAMES.copy(), GLOBAL_OMIT_FILE_NAMES.copy(),
                          GLOBAL_OMIT_FILE_EXTENSIONS.copy())
        apply_all_settings(settings)
        omissions_changed = prev_omissions != (GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_NAMES,
                                                GLOBAL_OMIT_FILE_EXTENSIONS)
        changed_titles = {
            title for title, conf in COLUMN_SETTINGS.items()
            if (conf["height"], conf["spacing"]) != prev_geometry.get(title)
        }
        # column_gap() : apply_all_settings vient de le mettre a jour (voir
        # set_column_gap ci-dessus), mais c'est un global — encore besoin
        # de le repercuter ICI sur l'instance reelle de columns_layout,
        # comme refresh_all_columns le fait deja pour la largeur/hauteur
        # des colonnes.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))
        if settings["root_path"] != self.root_field.text():
            self.root_field.setText(settings["root_path"])
            self.reload()
        else:
            self.refresh_all_columns(
                rescan=omissions_changed,
                relayout_titles=None if omissions_changed else changed_titles,
            )
        if omissions_changed:
            hidden_path = self.detail._current_path
            if hidden_path and _is_globally_omitted_path(Path(hidden_path)):
                self.detail.clear()
            idle_scheduler = getattr(self, "_idle_preview_scheduler", None)
            if idle_scheduler is not None:
                if idle_scheduler.scan_cancel_event is not None:
                    idle_scheduler.scan_cancel_event.set()
                idle_scheduler.queue.clear()
                idle_scheduler.done.clear()
                if (idle_scheduler.active_key is not None and idle_scheduler.cancel_event is not None):
                    if _is_globally_omitted_path(Path(idle_scheduler.active_key)):
                        idle_scheduler.cancel_event.set()
                idle_scheduler.last_scan = 0.0
        # app.setStyleSheet (dans refresh_colors -> refresh_style) repolit
        # TOUS les widgets de TOUTES les fenetres de l'appli — le poste le
        # plus cher, et de loin, de tout ce rafraichissement (mesure a
        # plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte, voir _flush_stylesheet_rebuild). Un slider qui ne
        # touche ni aux couleurs, ni au cadre/rayon des boutons, ni au
        # cadre/rayon des zones de saisie, ni au rayon des tableaux (largeur
        # de colonne, echelle, hauteur d'entete...) n'a aucune raison de le
        # declencher a chaque cran : seule une vraie difference sur ces
        # points (les seuls que build_stylesheet lit reellement) force la
        # reconstruction complete de la feuille de style — MAIS durant un
        # glisser de COULEUR, cette difference est reelle a CHAQUE tick, ce
        # gate seul ne suffit donc plus (voir la remarque de l'utilisateur,
        # "il y a toujours un tres gros problemes de performance") : la
        # reconstruction elle-meme est donc REGROUPEE (voir
        # _flush_stylesheet_rebuild), jamais appelee directement ici.
        colors = settings.get("colors") or {}
        style_key = (
            tuple(colors.get(k, C[k]) for k in STYLESHEET_COLOR_KEYS),
            settings.get("button_radius"),
            settings.get("button_frame"),
            settings.get("input_radius"),
            settings.get("input_frame"),
            settings.get("table_radius"),
        )
        if style_key != self._last_style_key:
            self._last_style_key = style_key
            self._pending_stylesheet_rebuild = True
            if not self._stylesheet_rebuild_timer.isActive():
                self._stylesheet_rebuild_timer.start()
        self.refresh_colors(rebuild_stylesheet=False)
        self.refresh_chrome_sizes()
        self._apply_native_frame()

    def _flush_stylesheet_rebuild(self):
        """Reconstruction DIFFEREE et REGROUPEE de la feuille de style
        globale (voir _apply_settings/app_style.refresh_style) — le SEUL
        appel a ce chemin couteux (mesure a plus de 3 SECONDES une fois la
        fenetre de parametres ouverte, des milliers de widgets ayant
        chacun leur propre QSS local a re-cascader contre le nouveau QSS
        d'appli). `_stylesheet_rebuild_timer` (250ms, singleShot, voir
        __init__) le declenche au plus tot 250ms apres le DERNIER
        changement de style_key — pendant un glisser continu de couleur,
        cela ramene un cout de plusieurs secondes PAR TICK (~30ms) a un
        seul appel toutes les ~250ms, invisible a l'oeil (le style
        GENERIQUE — boutons/scrollbars/menus — n'est de toute facon pas ce
        qu'on regarde en glissant une pastille de couleur ; tout le reste
        du retour visuel en direct passe par refresh_colors(rebuild_
        stylesheet=False), deja rejoue a chaque tick, DEJA rapide)."""
        if not self._pending_stylesheet_rebuild:
            return
        self._pending_stylesheet_rebuild = False
        app = QApplication.instance()
        if app is not None:
            refresh_style(app)

    def refresh_chrome_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) aux
        widgets permanents de la fenetre (barre de titre, barre du haut),
        qui comme leurs polices (voir refresh_chrome_fonts) ne sont
        construits qu'une fois et ne suivraient donc pas le slider d'echelle
        sans ce rafraichissement explicite."""
        self.titlebar.refresh_sizes()
        self.root_field.setFixedHeight(scaled(24))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFixedHeight(scaled(24))
        self.btn_settings.setFixedWidth(scaled(28))

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.titlebar.title_label.setFont(role_font("titles", 11, 400, tracking=0.01))
        self.titlebar.title_label.setStyleSheet(f"color: {role_color('titles', C['label'])}; background: transparent;")
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.root_field.setFont(role_font("info", 12, 400))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place):
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.set_colors(role_color("buttons", "#c4cacf"), C["text"])
        self.synced_label.setFont(role_font("info2", 10, 400))
        self.synced_label.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        for column in self.columns:
            column.refresh_header()
        self.detail.refresh_header()
        for column in self.image_preview_columns:
            column.refresh_header()
        for column in self.group_columns:
            column.refresh_header()
        is_dir = True
        if self.columns:
            selected = self.columns[-1].current_path()
            if selected is not None:
                is_dir = selected.is_dir()
        self.detail.refresh_fonts(is_dir)

    def refresh_colors(self, rebuild_stylesheet: bool = True):
        """Reapplique toutes les couleurs (voir app_style.C, mutable via
        set_color) aux widgets dont le style QSS a ete fixe une fois pour
        toutes a la construction — indispensable pour que la page Couleurs
        de la fenetre de parametres s'applique en temps reel (voir la
        remarque sur set_color dans app_style.py).

        rebuild_stylesheet=False saute uniquement le app.setStyleSheet
        global (repolissage de TOUS les widgets de l'appli, tres couteux) :
        a utiliser quand on sait qu'aucune des valeurs lues par
        build_stylesheet (couleurs, cadre/rayon des boutons, cadre/rayon des
        zones de saisie, rayon des tableaux) n'a bouge (voir _apply_settings),
        le reste de cette methode restant assez leger pour tourner a chaque
        rafraichissement."""
        if rebuild_stylesheet:
            app = QApplication.instance()
            if app is not None:
                refresh_style(app)
        self.central.setStyleSheet(
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {ui_state.WINDOW_RADIUS}px; }}"
        )
        self.columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['window']}; }}")
        self.titlebar.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        for btn in (self.titlebar.btn_min, self.titlebar.btn_max, self.titlebar.btn_close):
            btn.set_colors(C["label"], C["text"])
        self.topbar.setStyleSheet(f"#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['border']}; }}")
        self.statusbar.setStyleSheet(f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}")
        for column in self.columns:
            column.refresh_colors()
        for column in self.group_columns:
            column.refresh_colors()
        for column in self.image_preview_columns:
            column.refresh_colors()
        self.detail.refresh_colors()
        self.refresh_chrome_fonts()

def main():
    settings = load_settings()
    apply_all_settings(settings)
    root = Path(settings["root_path"])

    app = QApplication(sys.argv)
    apply_style(app)
    window = PipelineBrowser(root)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
