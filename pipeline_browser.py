import json
import sys
from datetime import datetime
from pathlib import Path
import threading
import time
from PySide6.QtCore import (
    QByteArray, QCoreApplication, QEasingCurve, QEvent, QEventLoop, QObject, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, QSizeF, Qt, QTimer,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
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
    refresh_style,
    resize_hit_test,
    role_color,
    role_font,
    scaled,
    start_native_move,
    column_style_for,
)
import config as _config
import ui_state
from config import (
    COLUMN_LABELS,
    SETTINGS_V1_ENABLED,
    IMAGE_EXTENSIONS,
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
    save_settings,
)
from settings_widgets import (
    Menu, menu_row,
    TOGGLE_STYLE_LISTENERS, _Toggle, make_space_actions, set_space_above, set_space_below, space_target,
    widget_at_path, widget_path,
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
    ROLE_ISDIR,
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
from focus import (
    FilterChips, FocusFilmstrip, FocusGallery, FocusImageLoader, FocusInfoPanel, FocusOverlay, filter_window, fit_rect,
    placeholder_pixmap,
)
import file_attributes
import file_filters
from focus import thumbnail as focus_thumbnail
import focus as _focus
from config import PUR_PREVIEW_EXTENSIONS
import previews as _previews
import software_launch
import shiboken6


def _anim_running(overlay) -> bool:
    """Overlay d'animation (fondu, glissement) reellement en cours. Un overlay
    detruit sans etre alle au bout (objet Qt supprime) ne compte pas : sinon
    son drapeau `running` reste vrai et bloque toutes les animations suivantes."""
    return overlay is not None and overlay.running and shiboken6.isValid(overlay)
from browser_core import (
    _SlideOverlay,
    DETAIL_PANEL_MIN_WIDTH,
)
from browser_core import (
    _HoverPrime,
)
from previews import (
    sweep_preview_cache,
)


# ==========================================================================
# Barre de titre intrinseque : la fenetre principale est sans decoration
# systeme (voir PipelineBrowser.__init__), donc cette barre en tient lieu —
# deplacement, reduction/agrandissement/fermeture — avec le meme habillage
# sombre que le reste de l'appli plutot que le chrome blanc/bleu de Windows.
# ==========================================================================

def _set_qss(widget, qss: str) -> None:
    """setStyleSheet seulement si la feuille change : sur un conteneur qui
    porte toute la fenetre, Qt repolit tous les descendants meme pour un
    texte identique (~7 ms par appel, rejoue a chaque cran de slider)."""
    if widget.styleSheet() != qss:
        widget.setStyleSheet(qss)


class _MouseBackFilter(QObject):
    """Bouton « precedent » de la souris (sur le cote) dans la fenetre, visionneuse ouverte (planche
    comprise) : on sort de la visionneuse, les colonnes reviennent. Filtre d'APPLICATION : l'image,
    la planche, la pellicule recoivent le clic avant la fenetre."""

    def __init__(self, browser: "PipelineBrowser"):
        super().__init__(browser)
        self._browser = browser

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        if event.button() != Qt.BackButton or not self._browser._project_columns_hidden:
            return False
        if not (watched.isWidgetType() and watched.window() is self._browser):
            return False
        if kind == QEvent.MouseButtonPress:
            self._browser._set_columns_hidden(False)
        return True                       # avale aussi le relachement (rien d'autre ne le voit)


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

def _shown_or_pending(widget) -> bool:
    """Visible, ou sur le point de l'etre : un widget tout juste (re)construit (ex. colonne Focus
    rebatie par une navigation pendant que les colonnes sont masquees) n'est pas encore visible
    mais Qt l'affichera de lui-meme, faute d'avoir ete masque explicitement. Un widget masque
    expres par ailleurs (WA_WState_ExplicitShowHide + cache) n'est pas concerne."""
    return widget.isVisible() or not widget.testAttribute(Qt.WA_WState_ExplicitShowHide)


class _ViewerButtonDrag(QObject):
    """Ctrl + glisser un bouton de la rangee de la visionneuse / planche (masquer, planche, filtre,
    PureRef) : regle de l'appli pour tout deplacement — le bouton suit le curseur a 75 %
    (DRAG_GHOST_OPACITY), son emplacement d'origine reste a 25 %, le seul emplacement vise est en
    surbrillance (`settings_layout._ReorderOverlay`, axe x, pose sur une bande de la hauteur de la
    rangee). Sans Ctrl, le clic garde son sens."""

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.press = None                    # (bouton, position globale de l'appui)
        self.overlay = None
        self.strip = None
        self.keys: list = []

    def hook(self, button):
        if not getattr(button, "_row_drag_hooked", False):
            button._row_drag_hooked = True
            button.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.press = (obj, event.globalPosition().toPoint())
                return True                  # Ctrl : pas de clic
            return False
        if self.press is None or self.press[0] is not obj:
            return False
        if kind == QEvent.MouseMove:
            pos = event.globalPosition().toPoint()
            if self.overlay is None and (pos - self.press[1]).manhattanLength() >= 4:
                self._start(obj)
            if self.overlay is not None:
                self.overlay.follow(self.strip.mapFromGlobal(pos).x())
            return True
        if kind == QEvent.MouseButtonRelease:
            self._finish()
            return True
        return kind == QEvent.MouseButtonDblClick

    def _start(self, button):
        from types import SimpleNamespace
        from settings_layout import _ReorderOverlay
        browser = self.browser
        viewport = browser.scroll.viewport()
        items = browser._viewer_row_items()
        widgets = [w for _k, w in items]
        if button not in widgets:
            self.press = None
            return
        self.keys = [k for k, _w in items]
        rects = [QRect(w.mapTo(viewport, QPoint(0, 0)), w.size()) for w in widgets]
        top = min(r.top() for r in rects)
        bottom = max(r.bottom() for r in rects)
        left = min(r.left() for r in rects) - scaled(8, 0)
        right = max(r.right() for r in browser._button_rects()) + scaled(8, 0)
        strip = self.strip = QWidget(viewport)
        strip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        strip.setStyleSheet("background: transparent;")     # les autres boutons restent visibles dessous
        strip.setGeometry(left, top, max(1, right - left), bottom - top + 1)
        strip.show()
        strip.raise_()
        spans = [(r.left() - left, r.right() + 1 - left) for r in rects]
        head = SimpleNamespace(_column_spans=lambda: spans, _order=list(range(len(spans))))
        source = widgets.index(button)
        grab_dx = strip.mapFromGlobal(self.press[1]).x() - spans[source][0]
        # Voile de l'emplacement d'origine : la couleur du fond juste a gauche de la rangee.
        probe = viewport.grab(QRect(max(0, left - 2), top + (bottom - top) // 2, 1, 1)).toImage()
        self.overlay = _ReorderOverlay(strip, head, source, button.grab(), 0, grab_dx)
        self.overlay.setStyleSheet("background: transparent;")
        self.overlay.veil_color = probe.pixelColor(0, 0).name() if not probe.isNull() else C["void"]

    def _finish(self):
        overlay, strip = self.overlay, self.strip
        self.press = self.overlay = self.strip = None
        if overlay is None:
            return
        target, source = overlay.target, overlay.source
        strip.hide()
        strip.deleteLater()
        if target is not None:
            self.browser._move_viewer_button(self.keys, source, target)


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
        self._project_columns_hidden = False
        self._columns_fade = None
        self._focus_overlay = None    # objet en focus au centre (voir _start_focus_overlay)
        self._focus_src = None        # (pixmap, QRect dans le viewport) de l'objet dans l'inspecteur
        self._focus_gallery = None    # planche des images du dossier (voir _toggle_focus_gallery)
        self._viewer_entry_source = None   # double-clic sur une ligne : apercu de la ligne (depart du vol)
        self._floating_gallery_btn = None   # son bouton quand il n'y a pas de colonne Focus
        self._viewer_purs: list = []        # planches PureRef du dossier de la visionneuse
        self._pur_buttons: list = []        # un bouton « ouvrir » par planche (en haut a droite)
        # Filtres de la planche (file_filters ; le temps de la session) : bouton filtre (planche ouverte),
        # elements du filtre ecrits a cote, fenetre des filtres, fichiers des portees larges (parcours en fond).
        self._viewer_filter: dict = dict(file_filters.DEFAULT_FILTER)
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
        self.btn_style = IconButton("sliders", role_color("buttons", "#c4cacf"), C["text"])
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_style, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
            btn.setFixedHeight(scaled(24))
            btn.setCursor(Qt.ArrowCursor)
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place):
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.setFixedWidth(scaled(28))
        self.btn_style.setFixedWidth(scaled(28))
        self.btn_style.setToolTip("Parametres visuels")
        self.btn_settings.setToolTip("Parametres generaux" if SETTINGS_V1_ENABLED else "Parametres")
        # Fenetres v1 desactivees (config.SETTINGS_V1_ENABLED) : un seul bouton, qui ouvre la v2.
        self.btn_style.setVisible(SETTINGS_V1_ENABLED)
        self.btn_last_place.setToolTip("Revenir a l'endroit ouvert a la derniere fermeture")
        self.btn_browse.clicked.connect(self.browse_root)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_last_place.clicked.connect(self.go_to_last_place)
        self.btn_settings.clicked.connect(lambda: self.open_settings("general"))
        self.btn_style.clicked.connect(lambda: self.open_settings("visuel"))
        # Clic droit : fenetre de reglages v2 (maquette comparative, voir
        # settings_window_v2.py) — n'affecte pas la fenetre reelle.
        self.btn_style.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_style.customContextMenuRequested.connect(self._open_settings_v2_menu)
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
        # Presets : menu deroulant (preset actif) + « Gerer les presets… » (settings_presets.py, briques
        # des reglages).
        import settings_window_v2
        from settings_presets import PresetPicker
        settings_window_v2.seed_window_look(ui_state.APPLIED_SETTINGS or load_settings())
        self.preset_picker = PresetPicker()
        self.preset_picker.refresh(ui_state.APPLIED_SETTINGS or load_settings())
        self.preset_picker.presetChosen.connect(self._choose_preset)
        self.preset_picker.manageRequested.connect(self._open_preset_manager)
        self._preset_manager = None
        top_layout.addWidget(self.preset_picker)
        top_layout.addWidget(self.btn_style)
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
        self.detail.preview_double_clicked.connect(self._toggle_project_columns_hidden)
        self._detail_state_width = {}   # {replie: largeur de l'inspecteur} (voir _set_columns_collapsed_now)

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
        QApplication.instance().installEventFilter(self._mouse_back)
        self._viewer_press = None
        self._focus_wheel = 0
        self._focus_path = None       # fichier montre au centre quand il attend son apercu (voir _focus_on_file)
        _previews._PREVIEW_DECODE_MANAGER.ready.connect(self._on_focus_preview_ready)
        # Visionneuse (colonnes masquees, image seule au centre, voir _enter_viewer) : fichiers a
        # apercu du dossier et rang de celui montre ; images decodees en fond ; la colonne et
        # l'inspecteur (masques) ne suivent qu'au repos (_viewer_sync) ou au retour des colonnes.
        self._viewer_paths: list = []
        self._viewer_index = -1
        self._viewer_previews: dict = {}      # apercus des voisines non-images (PSD, 3D...), pour le ruban
        self._focus_images = FocusImageLoader(self)
        self._focus_images.ready.connect(self._on_focus_image_ready)
        self._viewer_sync = QTimer(self)
        self._viewer_sync.setSingleShot(True)
        self._viewer_sync.setInterval(self._VIEWER_SYNC_MS)
        self._viewer_sync.timeout.connect(self._sync_viewer_selection)
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
        import settings_element_style       # clic droit > « Override settings » sur les elements des reglages
        settings_element_style.add_listener(self._on_element_style_saved)
        settings_element_style.TARGET_RESOLVERS.append(self._override_targets)

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
        current = root
        col_index = 0
        for part in parts:
            current = current / part
            if not self.columns:
                return
            if col_index < len(self.columns):
                candidates = [self.columns[col_index]]
            else:
                candidates = [self.columns[-1], *self.group_columns]
            match = None
            column = None
            for candidate in candidates:
                for i in range(candidate.list.count()):
                    item = candidate.list.item(i)
                    if Path(item.data(ROLE_PATH)).name == part:
                        match, column = item, candidate
                        break
                if match is not None:
                    break
            if match is None:
                if part.lower() in STATUS_FOLDERS and current.is_dir():
                    continue
                return
            in_group = column in self.group_columns
            if column.list.currentItem() is match:
                column.reselect_current()
            else:
                column.list.setCurrentItem(match)
            col_index = len(self.columns) - 1 if in_group else col_index + 1
            if not current.is_dir():
                return

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
        self._project_columns_hidden = False
        self._sync_viewer_chrome()
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
            directory, title, is_focus_level=is_focus_level, style_title=style_title,
            display_title=display_title,
            show_dirs=show_dirs, show_files=show_files, omit_dirs=omit_dirs, omit_files=omit_files)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
        column.view_requested.connect(lambda path, c=column: self._view_in_viewer(path, c))
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
            if selected is not None and selected.is_dir():
                key = _previews.software_icon_key(selected.name)
                if software_launch.can_launch(key):
                    software = (key, selected)
        # Nom du SET (dossier terminal de la chaine) : nom du favori ajoute dans le logiciel (demande de l'utilisateur).
        set_path = self._chain_terminal_path() if software is not None else None
        set_name = set_path.name if set_path is not None else None
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

    def update_preview_stack(self, if_changed: bool = False):
        """`if_changed` (selection d'un FICHIER) : la pile (vignettes Focus, groupe IN/OVER/OUT/LOGICIELS)
        ne depend que de la CHAINE des dossiers selectionnes et de l'habillage ; inchangee, elle n'est pas
        reconstruite (~100 ms : le retour aux colonnes depuis la visionneuse, qui resynchronise la colonne
        sur l'image montree, en etait bloque d'autant — saccade signalee)."""
        self._columns_epoch += 1
        self._prewarm_timer.start()
        key = self._preview_stack_key()
        if not (if_changed and key == getattr(self, "_preview_stack_built", None)):
            self._update_preview_stack_impl()
            self._preview_stack_built = key
        self._enforce_hidden_columns(final=True)

    def _preview_stack_key(self):
        """Ce dont depend la pile d'apercus : colonnes de la chaine (objet, dossier, selection), config du
        projet, habillage des colonnes Focus."""
        chain = self.columns[:self._chain_expected_total()]
        return (tuple((id(c), str(c.directory), str(c.current_path())) for c in chain), len(self.columns),
                id(self._active_project_config), self._preview_style_snapshot())

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
                    on_hide_columns=self._toggle_project_columns_hidden if offset == 0 else None,
                    on_gallery=self._toggle_focus_gallery if offset == 0 else None,
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
                on_resize_end=self._on_group_column_resize_end,
                group_kind=kind, on_reorder=self._on_group_reorder,
                user_height=self._group_column_user_heights.get(kind), on_height_resize=self._on_group_height_resized,
                on_height_resize_begin=self._on_group_height_resize_begin,
                on_height_resize_end=self._on_group_height_resize_end,
                fill_height=fill,
                only_recognized_software=(kind == "logiciels" and work_dir_only_recognized_software),
                on_group_maximize=self._on_group_maximize, on_group_equalize=self._on_group_equalize)
            column.selected.connect(lambda col, p, k=kind: self._on_group_item_selected(col, p, k))
            column.activated.connect(self.on_activated)
            column.view_requested.connect(lambda path, c=column: self._view_in_viewer(path, c))
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
        self.detail.show_path(path)
        if not path.is_dir():
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

    def on_selected(self, column: Column, path: Path | None):
        """Si des colonnes sont deja deployees apres `column`, elles s'estompent
        toutes ensemble pendant que la navigation s'applique
        et que la nouvelle colonne sort de dessous."""
        if column not in self.columns:
            # Colonne deja retiree (signal emis pendant sa destruction, ou focus
            # passe a une liste pendant une reconstruction) : rien a naviguer.
            return
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        overlay = self._fade_before_select(column)
        self._on_selected_now(column, path)
        if overlay is not None:
            # Au-dessus de l'apparition (creee en differe par _on_selected_now) : l'ancien
            # contenu s'estompe PENDANT que la nouvelle colonne sort de dessous.
            QTimer.singleShot(0, lambda: self._raise_select_fade(overlay))

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
            image = viewport.grab(rect).toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
            dpr = image.devicePixelRatio()
            region = QRect(int(x0 * dpr), 0, image.width() - int(x0 * dpr), image.height())
            pixmap = QPixmap.fromImage(image.copy(region))
            pixmap.setDevicePixelRatio(dpr)
            target = QRect(rect.x() + x0, rect.y(), rect.width() - x0, rect.height())
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
            # Deselection : la pile n'est refaite que si la chaine a change (deselectionner un fichier, ex.
            # sortie de la planche, la reconstruisait pour rien : ~95 ms au clic).
            self.update_preview_stack(if_changed=True)
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
        self.update_preview_stack(if_changed=not path.is_dir())   # un fichier : pile refaite si la chaine change
        self._slide_snapshot = None   # les colonnes de droite ont change : capture perimee
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
            try:
                snapshot = self._grab_set_columns_at(x)
            finally:
                if fade_up:
                    fade.show()
            if snapshot is None:
                return
            left, right, x, background, limit = snapshot
            overlay = _SlideOverlay(
                viewport, left, right, x - column.width(), x, background, 0.0, 1.0, 200,
                None, on_done=lambda: setattr(self, "_columns_slide", None), limit=limit,
                emerge=True)
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
            QTimer.singleShot(0, self._auto_collapse_now)

    def _toggle_project_columns_hidden(self):
        """Bouton « masquer les colonnes » (voir PreviewColumn.hide_btn) : TOUTES
        les colonnes disparaissent en fondu puis quittent la mise en page — leur
        place est liberee ; seuls les deux boutons restent. Un nouveau clic
        ramene tout (fondu inverse). Le fondu anime une capture fixe de la zone
        (voir _FadeOverlay) pendant que les vrais widgets sont deja masques."""
        self._set_columns_hidden(not self._project_columns_hidden)

    def _hideable_widgets(self) -> list:
        """Tout ce que columns_layout contient, sauf le conteneur des vignettes
        Focus (qui porte les boutons)."""
        widgets = []
        for i in range(self.columns_layout.count()):
            widget = self.columns_layout.itemAt(i).widget()
            if widget is not None and widget is not self._preview_stack_wrapper:
                widgets.append(widget)
        return widgets

    def _toggled_widgets(self) -> list:
        return self._hideable_widgets() + list(self.image_preview_columns[1:]) + [self.detail]

    def _apply_columns_hidden(self, hidden: bool):
        """Masque/restaure INSTANTANEMENT ; ne restaure que ce que le bouton a
        lui-meme masque (une colonne de set deja repliee reste repliee)."""
        if self.image_preview_columns and self.image_preview_columns[0].hide_btn is not None:
            # Le focus reste sur le bouton : masquer une liste qui l'a le donnerait a
            # une autre liste, qui changerait de selection (et rebatirait les colonnes).
            self.image_preview_columns[0].hide_btn.setFocus()
        elif hidden:
            # Pas de bouton (masquage par double-clic sans colonnes Focus) : le
            # focus est gare sur la zone des colonnes, pour la meme raison.
            self.scroll.viewport().setFocus()
        for widget in self._toggled_widgets():
            if hidden:
                if _shown_or_pending(widget):
                    widget._hidden_by_toggle = True
                    widget.setVisible(False)
            elif getattr(widget, "_hidden_by_toggle", False):
                widget._hidden_by_toggle = False
                widget.setVisible(True)
        if self.image_preview_columns:
            self.image_preview_columns[0].set_buttons_only(hidden)

    def _columns_visible_rect(self) -> QRect:
        viewport = self.scroll.viewport()
        rect = QRect()
        candidates = [*self._hideable_widgets(), *self.image_preview_columns, self.detail]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        for widget in candidates:
            if widget.isVisible():
                rect = rect.united(QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size()))
        return rect.intersected(viewport.rect())

    def _columns_content_right(self) -> int:
        """Bord droit (repere du viewport) de la derniere colonne visible, inspecteur exclu."""
        viewport = self.scroll.viewport()
        right = 0
        candidates = [*self._hideable_widgets(), *self.image_preview_columns]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        for widget in candidates:
            if widget.isVisible() and widget.width() > 0:
                right = max(right, widget.mapTo(viewport, QPoint(0, 0)).x() + widget.width())
        return right

    def _column_spans(self, rect: QRect) -> list:
        """Bandes (x0, x1), dans le repere de `rect`, une par colonne visible, de gauche a
        droite ; elles se touchent (l'espace entre deux colonnes va a la precedente)."""
        viewport = self.scroll.viewport()
        candidates = [*self._hideable_widgets(), *self.image_preview_columns, self.detail]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        starts = sorted({max(0, widget.mapTo(viewport, QPoint(0, 0)).x() - rect.x())
                         for widget in candidates if widget.isVisible() and widget.width() > 0})
        starts = [x for x in starts if x < rect.width()]
        if len(starts) < 2:
            return []
        starts[0] = 0
        return list(zip(starts, [*starts[1:], rect.width()]))

    def _button_rects(self) -> list:
        rects = self._base_button_rects()
        for widget in (self._filter_btn, self._filter_chips):
            if widget is not None and widget.isVisible():
                rects.append(widget.geometry())
        rects.extend(b.geometry() for b in self._pur_buttons if b.isVisible())
        return rects

    def _base_button_rects(self) -> list:
        """Boutons repli / masquer / planche (ou le bouton flottant) : les autres viennent a leur suite."""
        viewport = self.scroll.viewport()
        rects = []
        if self.image_preview_columns:
            pc = self.image_preview_columns[0]
            for button in (pc.toggle_btn, pc.hide_btn, pc.gallery_btn):
                if button is not None and (button is not pc.gallery_btn or button.isVisible()):
                    rects.append(QRect(button.mapTo(viewport, QPoint(0, 0)), button.size()))
        floating = self._floating_gallery_btn
        if floating is not None and floating.isVisible():
            rects.append(floating.geometry())
        return rects

    def _fade_snapshot_fresh(self) -> bool:
        """La capture « masquer » depend de la taille, de la navigation ET de l'etat
        replie/deplie des colonnes de set."""
        cached = self._columns_snapshot
        return (cached is not None and len(cached) > 5 and cached[2] == self.scroll.viewport().size()
                and cached[3] == self._columns_epoch and cached[5] == self._project_columns_collapsed
                and time.monotonic() - cached[4] < 8.0)

    def _grab_columns(self) -> tuple:
        """Capture de la zone des colonnes dans son etat actuel, avec les boutons
        effaces (transparents) : ils restent reels et ne s'estompent pas. Les
        boutons ne sont PAS masques pour la capture : masquer celui qui a le
        focus le transmettrait a une liste, qui changerait de selection."""
        if _anim_running(self._columns_slide):
            self._columns_slide.finish_now()   # jamais de capture avec un overlay par-dessus
        rect = self._columns_visible_rect()
        viewport = self.scroll.viewport()
        self._columns_spans = self._column_spans(rect)
        image = viewport.grab(rect).toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        for button_rect in self._button_rects():
            painter.fillRect(button_rect.translated(-rect.topLeft()), Qt.transparent)
        painter.end()
        return QPixmap.fromImage(image), rect, viewport.size(), self._columns_epoch

    def _set_columns_hidden(self, hidden: bool, animate: bool = True):
        # Sans colonnes Focus (donc sans bouton), on ne masque que si un objet
        # peut partir au centre : on revient par Echap ou le bouton « precedent » de la souris.
        if hidden == self._project_columns_hidden or (
                hidden and not self.image_preview_columns and self._focus_source() is None
                and getattr(self, "_viewer_entry_source", None) is None):
            return
        if not hidden:
            if self._focus_gallery is not None:
                # Sortie depuis la PLANCHE : aucune image n'a le focus, donc aucune selectionnee.
                self._leave_viewer_unselected()
            else:
                self._close_focus_gallery(animate=False)   # l'image revient au centre avant de repartir
                self._flush_viewer_sync()                   # colonne + inspecteur sur l'image montree
                if self._focus_overlay is not None:
                    self._focus_overlay.reset_view()        # repart ajustee, sans zoom
        self._project_columns_hidden = hidden
        self._sync_floating_gallery_btn()
        for preview_column in self.image_preview_columns:
            preview_column.set_hide_state(hidden)
        overlay = self._columns_fade
        if _anim_running(overlay):
            # Clic pendant un fondu : on repart de l'opacite courante, a l'envers.
            overlay.retarget(0.0 if hidden else 1.0, None if hidden else self._show_columns_now)
            if self._focus_overlay is not None:
                self._focus_overlay.retarget(1.0 if hidden else 0.0)
            if hidden:
                self._enter_viewer()
            return
        if not animate:
            self._apply_columns_hidden(hidden)
            if hidden:
                self._enter_viewer()
            return
        if hidden:
            if self._columns_slide is not None:
                self._columns_slide.finish_now()   # on ne capture jamais un mouvement en cours
            self.columns_layout.activate()
            self._clear_focus_overlay()
            home = self._focus_source()
            self._focus_src = self._entry_focus_source(home)      # double-clic : depuis la ligne
            from_row = self._focus_src is not home
            if not self._fade_snapshot_fresh():
                self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)
            self._apply_columns_hidden(True)
            self._start_columns_fade(1.0, 0.0, None)
            self._start_focus_overlay(1.0)
            if from_row:
                self._focus_src = home
                overlay = self._focus_overlay
                if overlay is not None:
                    overlay._on_finished = lambda o=overlay, h=home: self._send_focus_home(o, h)
            self._enter_viewer()
            return
        if not self._fade_snapshot_fresh() and self._columns_snapshot is not None and \
                (self._columns_snapshot[2] != self.scroll.viewport().size()
                 or self._columns_snapshot[3] != self._columns_epoch
                 or (len(self._columns_snapshot) > 5 and self._columns_snapshot[5] != self._project_columns_collapsed)):
            self._columns_snapshot = None
        snapshot = self._columns_snapshot
        if snapshot is None:
            # Capture perimee (navigation, redimensionnement ou visionneuse pendant le masquage) :
            # on affiche, on capture, on re-masque avant tout rendu a l'ecran (aucun retour a la
            # boucle d'evenements entre les deux). PAS de setUpdatesEnabled(False) ici : grab()
            # respecte ce drapeau et rendait une capture VIDE (fond seul) -> pas de fondu, les
            # colonnes surgissaient d'un coup a la fin.
            try:
                self._apply_columns_hidden(False)
                self._settle_columns_layout()
                self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)
                self._retarget_focus_source()
            finally:
                self._apply_columns_hidden(True)
        elif len(snapshot) > 6 and snapshot[6] is not None:
            self._retarget_focus_source(snapshot[6])     # capture faite d'avance : sa place de retour
        self._start_columns_fade(0.0, 1.0, self._show_columns_now)
        self._start_focus_overlay(0.0)

    def _leave_viewer_unselected(self):
        """Sortie de la visionneuse alors que la planche est ouverte (aucune image en grand) : la
        planche disparait, l'image en focus aussi (rien ne repart vers l'inspecteur) et la colonne du
        dossier n'a plus AUCUN fichier selectionne (meme chemin qu'un re-clic sur la ligne : les
        colonnes ouvertes apres elle se ferment, l'inspecteur se vide). Appele colonnes encore
        masquees : la deselection se fait sans fondu, celui du retour des colonnes suffit."""
        gallery = self._focus_gallery
        self._focus_gallery = None
        self._set_gallery_buttons_state(False)
        if gallery is not None:
            self._gallery_memory = (gallery.path_keys(), gallery.first_visible_row())
            gallery.blockSignals(True)
            gallery.hide()
            gallery.deleteLater()
        self._viewer_sync.stop()
        self._clear_focus_overlay()
        self._focus_src = None
        if not self._gallery_deselected:
            self._deselect_viewer_file()
        self._gallery_deselected = False

    def _deselect_viewer_file(self):
        """La colonne du dossier de la visionneuse n'a plus AUCUN fichier selectionne (meme chemin qu'un
        re-clic), l'inspecteur se vide. Colonnes masquees : sans fondu."""
        column, current = self._focus_file_column()
        if column is None:
            # Colonne pas encore alignee sur le fichier (navigation en attente) : celle qui montre
            # un fichier du dossier de la visionneuse.
            folder = Path(self._viewer_paths[0]).parent if self._viewer_paths else None
            column = next((c for c in [*self.columns, *self.group_columns]
                           if folder is not None and c.current_path() is not None
                           and c.current_path().parent == folder), None)
        if column is not None:
            self.on_reclicked(column)
        else:
            self.detail.clear()

    def _retarget_focus_source(self, relevee: tuple | None = None):
        """Capture perimee : l'inspecteur vient d'etre re-affiche pour la refaire,
        on en profite pour relever la vraie place de l'objet en focus (et son
        contenu actuel) comme point d'arrivee du retour. `relevee` : place deja
        relevee lors de la capture faite d'avance (_pregrab_columns), `(source,)`."""
        source = self._focus_source() if relevee is None else relevee[0]
        self._focus_src = source
        overlay = self._focus_overlay
        if source is None:
            self._clear_focus_overlay()
        elif overlay is not None:
            if getattr(self.detail, "_current_path", None) != self._focus_path:
                # Autre fichier que celui montre : son image. Sinon l'image du centre (pleine
                # definition) repart telle quelle, sans passer par l'apercu de l'inspecteur.
                overlay._base = source[0]
                overlay._natural = None
                overlay._cache_key = None
            overlay.set_geometry_target(None, QRectF(source[1]))     # meme zone : l'image ne saute pas

    def _show_columns_now(self):
        self._apply_columns_hidden(False)
        self._clear_focus_overlay()
        self._focus_src = None

    def _start_columns_fade(self, start: float, end: float, on_finished):
        pixmap, rect = self._columns_snapshot[0], self._columns_snapshot[1]
        self.columns_layout.activate()
        spans = getattr(self, "_columns_spans", [])
        overlay = _FadeOverlay(self.scroll.viewport(), pixmap, rect, start, end, 420 if len(spans) > 1 else 260,
                               on_finished, on_done=lambda: setattr(self, "_columns_fade", None))
        overlay.set_spans(spans)
        holes = self._button_rects()
        if self._focus_src is not None:
            holes.append(self._focus_src[1])   # l'objet en focus voyage a part : pas de double dans le fondu
        overlay.set_holes(holes)
        overlay.show()
        overlay.raise_()
        self._columns_fade = overlay
        if self._focus_overlay is not None:
            self._focus_overlay.raise_()
        self._raise_viewer_chrome()

    def _focus_source(self):
        """(pixmap, QRect en coordonnees du viewport) de l'objet en focus tel que
        l'inspecteur l'affiche, ou None. Exige l'inspecteur visible et mis en page."""
        if not self.detail.isVisible():
            return None
        source = self.detail.focus_source()
        if source is None:
            return None
        pixmap, rect = source
        viewport = self.scroll.viewport()
        return pixmap, QRect(self.detail.mapTo(viewport, rect.topLeft()), rect.size())

    def _focus_area(self) -> QRect:
        return self.scroll.viewport().rect()

    def _start_focus_overlay(self, end: float):
        """Fait voyager l'objet en focus : end=1.0 de l'inspecteur vers le centre
        (masquage), end=0.0 du centre vers l'inspecteur (retour). Meme duree que
        le fondu des colonnes."""
        source = self._focus_src
        if source is None:
            return
        pixmap, rect = source
        spans = getattr(self, "_columns_spans", [])
        duration = 420 if len(spans) > 1 else 260
        overlay = self._focus_overlay
        if overlay is not None:
            overlay._duration = duration
            overlay.retarget(end)
            overlay.raise_()
            self._raise_viewer_chrome()
            return
        area = self._viewer_area()
        overlay = FocusOverlay(self.scroll.viewport(), pixmap, QRectF(rect), FocusOverlay.target_rect(pixmap, area),
                                1.0 - end, end, duration,
                                on_double_click=self._toggle_project_columns_hidden,
                                on_wheel=self._on_focus_wheel)
        overlay.show()
        overlay.raise_()
        self._focus_overlay = overlay
        self._raise_viewer_chrome()

    def _clear_focus_overlay(self):
        overlay = self._focus_overlay
        self._focus_overlay = None
        self._focus_home = None
        self._focus_path = None
        if overlay is not None:
            overlay.dispose()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pur_buttons or self._filter_btn is not None:
            self._sync_filter_button()               # bouton filtre puis boutons PureRef : a la suite des autres
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.set_geometry_target(self._viewer_area())
        if self._focus_gallery is not None:
            self._focus_gallery.setGeometry(self._gallery_rect())
        self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
        if self._filmstrip is not None:
            self._filmstrip.setGeometry(self._filmstrip_rect())
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.setGeometry(self._info_rect())

    # -- Planche des images du dossier (etat focus) --

    def _toggle_focus_gallery(self):
        """Bouton voisin de « masquer » (etat focus seulement) : image en cours <-> planche de
        toutes les images du dossier de l'image en cours."""
        if self._focus_gallery is not None:
            self._close_focus_gallery()
        else:
            self._open_focus_gallery()

    def _focus_file_column(self):
        """(colonne, chemin) du fichier affiche par l'inspecteur ; colonne None si introuvable. Double-clic
        sur une ligne en cours : CE fichier et sa colonne (`_viewer_entry_path`), quoi que montre
        l'inspecteur."""
        entry = getattr(self, "_viewer_entry_path", None)
        if entry is not None:
            return entry
        current = getattr(self.detail, "_current_path", None)
        if not current:
            return None, None
        path = Path(current)
        for column in [*self.columns, *self.group_columns]:
            if column.current_path() == path:
                return column, path
        return None, path

    def _gallery_paths(self, rescan: bool = True) -> tuple:
        """Fichiers de la planche et fichier en cours : ceux de la visionneuse s'ils sont connus
        (l'image montree peut avoir devance la colonne, voir _viewer_sync), sinon relus ; filtre applique
        (voir _filtered_gallery)."""
        if 0 <= self._viewer_index < len(self._viewer_paths):
            paths = list(self._viewer_base or self._viewer_paths)
            current = str(self._viewer_paths[self._viewer_index])
        else:
            paths, current = self._scan_viewer_paths()
        return self._filtered_gallery(paths, current, rescan)

    # -- Filtres de la planche (demande de l'utilisateur) --

    def _filtered_gallery(self, paths: list, current: str | None, rescan: bool = True) -> tuple:
        """Filtre de la planche applique a `paths` (colonne en cours) ou, portee plus large, aux fichiers
        du dossier de la portee : parcourus EN FOND (`rescan` : relus a l'ouverture de la planche), la
        colonne filtree en attendant le premier parcours. Fichier en cours : None s'il est ecarte."""
        spec = file_filters.normalized(self._viewer_filter)
        if not file_filters.is_active(spec):
            return paths, current
        folder = self._filter_scope_folder(spec["scope"])
        entries = paths
        if folder is not None:
            known = self._scope_files.get(str(folder))
            if rescan or known is None:
                self._start_filter_scan(folder)
            if known is not None:
                entries = known
        found = file_filters.filter_entries(entries, spec, self._filter_root())
        return found, (current if current is not None and any(str(p) == current for p in found) else None)

    def _filter_root(self) -> Path:
        return Path(self.root_field.text())

    def _filter_provenances(self) -> list:
        """Provenances proposees : les fixes, puis les sous-dossiers de in / over / out des fichiers connus
        (colonne en cours et portees deja parcourues)."""
        entries = list(self._viewer_base or self._viewer_paths)
        for known in self._scope_files.values():
            entries.extend(known)
        return file_filters.provenance_choices(entries, self._filter_root())

    def _filter_scopes(self) -> list:
        """(cle, libelle) des portees : la colonne en cours, chaque dossier de la chaine du set (Type,
        Projet, Sous-projet…), toute la racine."""
        scopes = [(file_filters.SCOPE_LOCAL, "Local (colonne en cours)")]
        for index in range(min(len(self.columns), self._chain_expected_total())):
            column = self.columns[index]
            chosen = column.current_path()
            if chosen is None or not chosen.is_dir():
                break
            title = column.title_label.text() or column.column_title
            scopes.append((f"level:{index}", f"{title.capitalize()} : {chosen.name}"))
        scopes.append((file_filters.SCOPE_ROOT, "Toute la racine"))
        self._filter_scopes_cache = scopes
        return scopes

    def _filter_scope_folder(self, scope: str) -> Path | None:
        """Dossier parcouru pour une portee large ; None = la colonne en cours."""
        if scope == file_filters.SCOPE_ROOT:
            return Path(self.root_field.text())
        if scope.startswith("level:"):
            try:
                column = self.columns[int(scope.split(":", 1)[1])]
            except (ValueError, IndexError):
                return None
            chosen = column.current_path()
            return chosen if chosen is not None and chosen.is_dir() else None
        return None

    def _filter_scope_label(self, scope: str) -> str:
        labels = dict(self._filter_scopes_cache)
        if scope not in labels:
            labels = dict(self._filter_scopes())
        return labels.get(scope, "")

    def _start_filter_scan(self, folder: Path):
        task = self._filter_task
        if task is not None:
            if task.folder == folder and not task.cancel:
                return                                   # deja en cours
            task.cancel = True
        task = self._filter_task = file_filters.FilterScanTask(folder)
        task.signals.finished.connect(self._on_filter_scan_done)
        file_filters.pool().start(task)

    def _on_filter_scan_done(self, folder: str, entries):
        task = self._filter_task
        if task is not None and str(task.folder) == folder:
            self._filter_task = None
        self._scope_files[folder] = entries
        # Images des planches PureRef parcourues : rangees comme celles de la visionneuse (nom affiche
        # « planche.pur · n/N », planche retrouvee au retour aux colonnes, attributs de la planche).
        boards: dict = {}
        for entry in entries:
            if len(entry) > 3:
                boards.setdefault(entry[3], []).append(entry[0])
        for (pur, mtime), images in boards.items():
            self._remember_pur(pur, mtime, images)
        self._refresh_focus_gallery(rescan=False)
        self._sync_filter_button()

    def _sync_filter_button(self):
        """Planche ouverte : bouton filtre a la suite des autres boutons (rouge quand un filtre agit), et les
        elements du filtre ecrits a cote, en « style code » (FilterChips) ; puis les boutons PureRef."""
        want = self._project_columns_hidden and self._focus_gallery is not None
        button, chips = self._filter_btn, self._filter_chips
        if not want:
            for widget in (button, chips):
                if widget is not None:
                    widget.hide()
            self._sync_pur_buttons()
            return
        viewport = self.scroll.viewport()
        if button is None:
            button = self._filter_btn = IconButton("filter", role_color("buttons", "#c4cacf"), C["text"],
                                                   parent=viewport)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._open_filter_window)
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(self._filter_button_menu)
            chips = self._filter_chips = FilterChips(viewport)
        style_focus_button(button)
        spec = file_filters.normalized(self._viewer_filter)
        active = file_filters.is_active(spec)
        settings = ui_state.APPLIED_SETTINGS or {}
        button.set_alert(resolve_color_ref(settings.get("viewer_filter_active_color") or "#c62828")
                         if active else None)
        button.setToolTip("Filtres de la planche (clic droit : retirer le filtre)" if active
                          else "Filtres de la planche")
        button.show()
        button.raise_()
        if active:
            items = file_filters.describe(spec, [name for name, _c in _focus.filter_colors()],
                                          self._filter_scope_label(spec["scope"]))
            if self._filter_task is not None:
                items.append("recherche…")
            else:
                count = len(self._gallery_list)
                items.append(f"{count} fichier{'s' if count > 1 else ''}")
            chips.restyle()
            chips.set_items(items)
            chips.show()
            chips.raise_()
        else:
            chips.hide()
        self._sync_pur_buttons()

    def _filter_button_menu(self, pos):
        if not file_filters.is_active(self._viewer_filter):
            return
        menu = Menu(self)
        menu.addAction("Retirer le filtre", self._clear_viewer_filter)
        menu.exec(self._filter_btn.mapToGlobal(pos))

    def _clear_viewer_filter(self):
        if self._filter_window is not None:
            self._filter_window.close()          # rouverte, elle repart des valeurs vides
        self._set_viewer_filter(dict(file_filters.DEFAULT_FILTER))

    def _open_filter_window(self):
        window = self._filter_window
        if window is not None:
            window.raise_()
            window.activateWindow()
            return
        window = self._filter_window = filter_window(
            self._viewer_filter, self._filter_scopes(), settings=ui_state.APPLIED_SETTINGS, parent=self,
            provenances=self._filter_provenances())
        window.styleChanged.connect(self._on_filter_window_changed)
        window.destroyed.connect(lambda *_a: setattr(self, "_filter_window", None))
        window.on_row_style = self._open_filter_row_style      # clic droit > « Style des filtres actives… »
        window.show()

    def _open_filter_row_style(self):
        """Style des lignes ou un filtre est applique (fond, bordures) : fenetre « a la volee », valeurs
        appliquees en direct et enregistrees comme les styles des diapositives (_on_filmstrip_style)."""
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        previous = getattr(self, "_filter_row_window", None)
        if previous is not None:
            try:
                previous.raise_()
                previous.activateWindow()
                return
            except RuntimeError:
                pass
        settings = dict(DEFAULT_SETTINGS)
        settings.update(ui_state.APPLIED_SETTINGS or load_settings())
        window = self._filter_row_window = QuickStyleWindow(
            "Filtres actifs", v2.FILTER_ROW_SPECS, settings, title="Style des filtres activés",
            settings=settings, parent=self)
        window.styleChanged.connect(self._on_filter_row_style)
        window.destroyed.connect(lambda *_a: setattr(self, "_filter_row_window", None))
        window.show()

    def _on_filter_row_style(self, values: dict):
        self._on_filmstrip_style(values, light=True)          # applique + enregistre (et preset actif)
        # Enregistre EN TEMPS REEL (demande de l'utilisateur) : tout de suite, sauf pendant un geste
        # (curseur tire) ou l'ecriture attend le relachement (minuteur de _on_filmstrip_style).
        if QApplication.mouseButtons() == Qt.NoButton:
            self._flush_filmstrip_style()
        window = self._filter_window
        if window is not None:
            try:
                window.refresh_marks()
            except RuntimeError:
                pass

    def _on_filter_window_changed(self, values: dict):
        """Changement dans la fenetre des filtres : applique apres une courte pause (frappe au clavier)."""
        self._pending_filter = values
        if self._filter_timer is None:
            self._filter_timer = QTimer(self)
            self._filter_timer.setSingleShot(True)
            self._filter_timer.setInterval(250)
            self._filter_timer.timeout.connect(lambda: self._set_viewer_filter(self._pending_filter))
        self._filter_timer.start()

    def _set_viewer_filter(self, spec: dict | None):
        self._viewer_filter = file_filters.normalized(spec)
        self._refresh_focus_gallery(rescan=True)
        self._sync_filter_button()

    def _refresh_focus_gallery(self, rescan: bool = True):
        """Filtre change (ou parcours termine) : la planche est refaite sur place avec les fichiers retenus,
        en fondu (sans vague)."""
        old = self._focus_gallery
        if old is None:
            return
        paths, current = self._gallery_paths(rescan=rescan)
        if [str(p) for p in paths] == [str(p) for p in self._gallery_list]:
            return
        gallery = self._make_focus_gallery(paths, current)
        self._focus_gallery = gallery
        gallery.show()
        gallery.reveal_current(None)
        gallery.warm_cells(False)
        gallery.start_ripple(wave=False)
        gallery.raise_()
        old.blockSignals(True)
        old.hide()
        old.deleteLater()
        self._raise_gallery_buttons()

    def _scan_viewer_paths(self) -> tuple:
        """Fichiers a apercu (images, 3D, PSD, plans, videos...) du dossier du fichier en cours,
        dans l'ordre de sa colonne (ordre choisi a la main compris) ; a defaut de colonne, ceux du
        dossier, tries par nom. Aucune lecture disque par fichier (les lignes savent si elles
        sont des dossiers)."""
        column, current = self._focus_file_column()
        if current is None:
            return [], None
        if column is not None:
            items = [column.list.item(i) for i in range(column.list.count())]
            paths = [Path(item.data(ROLE_PATH)) for item in items if not item.data(ROLE_ISDIR)]
        else:
            try:
                paths = sorted((p for p in current.parent.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
            except OSError:
                paths = []
        # Planches PureRef comprises : leurs images y entrent (voir _expand_viewer_pureref).
        images = [p for p in paths if p.suffix.lower() in PREVIEWABLE_EXTENSIONS | PUR_PREVIEW_EXTENSIONS]
        return images, str(current)

    def _gallery_rect(self) -> QRect:
        """Zone des colonnes, sous les boutons (qui restent cliquables)."""
        area = self._focus_area()
        top = max((r.bottom() for r in self._button_rects()), default=0) + 10
        return QRect(area.x() + 16, top, max(1, area.width() - 32), max(1, area.bottom() - top))

    def _sync_floating_gallery_btn(self):
        """Focus SANS colonne Focus (donc sans bouton « masquer », retour par double-clic) : le
        bouton de la planche flotte seul en haut a gauche de la zone des colonnes, meme style.
        Avec une colonne Focus, c'est elle qui le porte (PreviewColumn.gallery_btn)."""
        self._sync_viewer_chrome()
        want = self._project_columns_hidden and not self.image_preview_columns
        button = self._floating_gallery_btn
        if not want:
            if button is not None:
                button.hide()
            return
        if button is None:
            button = self._floating_gallery_btn = IconButton(
                "gallery", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._toggle_focus_gallery)
        style_focus_button(button)
        style = column_style_for(PREVIEW_STACK_TITLE)
        button.move(scaled(int(style.get("preview_toggle_x", 8)), 0) + scaled(8, 0), scaled(10, 0))
        self._set_gallery_buttons_state(self._focus_gallery is not None)
        button.show()
        button.raise_()
        self._layout_viewer_buttons()

    def _set_gallery_buttons_state(self, shown: bool):
        if self.image_preview_columns:
            self.image_preview_columns[0].set_gallery_state(shown)
        button = self._floating_gallery_btn
        if button is not None:
            button.set_kind("single_image" if shown else "gallery")
            button.setToolTip("Revenir a l'image en cours" if shown else "Toutes les images du dossier")
        self._sync_filter_button()

    def _open_focus_gallery(self):
        if not self._project_columns_hidden:
            return
        paths, current = self._gallery_paths()
        if not paths and not file_filters.is_active(self._viewer_filter):
            return
        viewport = self.scroll.viewport()
        gallery = self._make_focus_gallery(paths, current)
        self._focus_gallery = gallery
        self._sync_viewer_chrome()                 # pellicule et raccourcis de l'image : retires
        gallery.show()
        memory = getattr(self, "_gallery_memory", None)
        gallery.reveal_current(memory[1] if memory is not None and memory[0] == gallery.path_keys() else None)
        # Les cases apparaissent en vague depuis l'image ; vague coupee (Reglages > Visionneuse) :
        # toutes ensemble, en fondu. Leurs images sont faites avant qu'elles ne se montrent.
        wave = bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_gallery_ripple_enabled", True))
        gallery.warm_cells(wave)
        gallery.start_ripple(wave=wave)
        self._return_grab.start()          # au repos : sortie vers les colonnes preparee d'avance
        gallery.raise_()
        gallery.setFocus()
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.finish_now()
            # L'image en focus se pose dans sa vignette (et la case reste vide pendant le vol) ;
            # sa place dans l'inspecteur est gardee pour le retour des colonnes.
            tile = gallery.image_rect_in(viewport, current, overlay._base)
            if tile is None:
                overlay.hide()
            else:
                self._focus_home = overlay._source
                gallery.set_hidden_path(current)
                overlay._source = QRectF(tile)
                overlay._duration = self._GALLERY_FLIGHT_MS
                overlay.retarget(0.0, self._on_focus_landed_in_gallery)
                overlay.raise_()
        self._set_gallery_buttons_state(True)
        self._raise_gallery_buttons()

    def _make_focus_gallery(self, paths: list, current: str | None):
        gallery = FocusGallery(self.scroll.viewport(), paths, current, on_split=self._on_gallery_split,
                               on_menu=self._filmstrip_menu)
        gallery.setGeometry(self._gallery_rect())
        gallery.chosen.connect(self._on_gallery_chosen)
        gallery.zoomed_into.connect(self._on_gallery_chosen)
        gallery.closed.connect(self._close_focus_gallery)
        gallery.outside_clicked.connect(lambda: self._set_columns_hidden(False))   # clic a cote du tableau
        self._gallery_list = [Path(p) for p in paths]
        return gallery

    def _raise_gallery_buttons(self):
        for button in (self._floating_gallery_btn, self._filter_btn, self._filter_chips, *self._pur_buttons):
            if button is not None and button.isVisible():
                button.raise_()

    _GALLERY_FLIGHT_MS = 380

    def _on_focus_landed_in_gallery(self):
        """L'image est dans sa case : la planche la dessine, l'objet en focus se cache."""
        if self._focus_overlay is not None:
            self._focus_overlay.hide()
        if self._focus_gallery is not None:
            self._focus_gallery.set_hidden_path(None)

    def _close_focus_gallery(self, animate: bool = True, path: str | None = None):
        """Retour a l'image : elle quitte sa vignette (`path`, par defaut le fichier de
        l'inspecteur) pour le centre pendant que la planche s'estompe. `animate=False` : tout de
        suite (les colonnes reviennent : l'objet doit etre au centre, avec sa place d'origine)."""
        gallery = self._focus_gallery
        if gallery is None:
            overlay = self._focus_overlay
            if not animate and overlay is not None and self._focus_home is not None:
                # Retour de vignette encore en vol : l'objet est pose au centre avec sa vraie place.
                overlay.jump(1.0)
                overlay._source = self._focus_home
                self._focus_home = None
            return
        self._focus_gallery = None
        if self._gallery_deselected:
            # Retour a l'image depuis la planche : la colonne et l'inspecteur la reprennent (deselectionnes
            # d'avance pour la sortie, _pregrab_columns).
            self._gallery_deselected = False
            self._viewer_sync.start()
        # Position de la planche (premiere ligne visible), retrouvee a sa prochaine ouverture sur le
        # meme dossier (_open_focus_gallery) : jamais recentree sur l'image.
        self._gallery_memory = (gallery.path_keys(), gallery.first_visible_row())
        self._set_gallery_buttons_state(False)
        self._sync_viewer_chrome()
        self._park_keyboard_focus()
        gallery.blockSignals(True)
        gallery.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay = self._focus_overlay
        viewport = self.scroll.viewport()
        if path is None:
            path = self._focus_path or getattr(self.detail, "_current_path", None)
        tile = gallery.image_rect_in(viewport, path, overlay._base) if (animate and overlay is not None) else None
        home = self._focus_home

        def restore_home():
            if self._focus_overlay is overlay and overlay is not None and home is not None:
                overlay._source = home       # au centre (valeur 1) : rien ne bouge a l'ecran
            if self._focus_home is home:
                self._focus_home = None

        def drop_gallery():
            gallery.hide()
            gallery.deleteLater()

        if overlay is None:
            drop_gallery()
            restore_home()
            return
        if tile is None:
            overlay.jump(1.0)
            restore_home()
            overlay.show()
            overlay.raise_()
            if animate:
                gallery.fade(0.0, self._GALLERY_FLIGHT_MS, drop_gallery)
            else:
                drop_gallery()
            return
        gallery.set_hidden_path(path)
        overlay.jump(0.0)
        overlay._source = QRectF(tile)
        overlay._duration = self._GALLERY_FLIGHT_MS
        overlay.show()
        overlay.raise_()
        overlay.retarget(1.0, restore_home)
        gallery.fade(0.0, self._GALLERY_FLIGHT_MS, drop_gallery)

    def _on_gallery_chosen(self, path: Path):
        """Vignette choisie : elle devient le fichier selectionne (colonne + inspecteur) et
        l'image en focus au centre."""
        gallery = self._focus_gallery
        self._focus_on_file(path, gallery.tile_pixmap(path, None) if gallery is not None else None)
        # La vignette choisie s'envole vers le centre (voir _close_focus_gallery).
        if gallery is not None:
            gallery.current = str(path)          # son cadre d'accent pendant que la planche s'estompe
        self._close_focus_gallery(path=str(path))

    def _focus_on_file(self, path: Path, fallback: QPixmap | None = None):
        """`path` (choisi dans la planche) devient l'image au centre ; la colonne et l'inspecteur
        suivent au repos (voir _viewer_sync)."""
        listed = self._gallery_list if self._focus_gallery is not None else []
        if path in listed and listed != self._viewer_paths:
            # Planche filtree (ou filtre retire) : la visionneuse parcourt les fichiers de la planche.
            self._viewer_paths = list(listed)
            if self._filmstrip is not None:
                self._filmstrip.set_paths(self._viewer_paths, listed.index(path))
        index = next((i for i, p in enumerate(self._viewer_paths) if p == path), -1)
        if index < 0:
            paths, _current = self._scan_viewer_paths()
            index = next((i for i, p in enumerate(paths) if p == path), -1)
            if index < 0:
                return
            self._viewer_paths = paths
            if self._filmstrip is not None:
                self._filmstrip.set_paths(paths, index)
        self._viewer_go(index, 0, fallback)

    def _focus_pixmap(self, path: Path, fallback: QPixmap | None = None) -> QPixmap:
        """Image a montrer au centre pour `path` en attendant mieux, SANS rien decoder ici :
        son apercu deja en memoire ou en cache disque (rendu 3D, PSD, plan, video...), sinon la
        petite vignette des colonnes ou `fallback` (vignette de la planche), sinon une carte « pas
        d'apercu ». Les images courantes arrivent en pleine definition par FocusImageLoader, les
        autres apercus par _on_focus_preview_ready."""
        self._focus_path = str(path)
        mtime = _previews.cached_mtime(path)
        if mtime is not None:
            cached = _previews._file_image_cache.get(str(path))
            if cached is not None and cached[0] == mtime and not cached[1].isNull():
                return cached[1]
            if not self._focus_images.supports(path):
                pixmap, _stale = _previews._read_preview_pixmap(path, mtime)
                if pixmap is not None and not pixmap.isNull():
                    return pixmap
            small = _previews.file_image_pixmap(path, asynchronous=True)     # demande l'apercu en fond
            if fallback is None and small is not None and not small.isNull():
                fallback = small
        if fallback is not None and not fallback.isNull():
            return fallback
        if self._focus_images.supports(path):
            note = "Chargement…"
        elif path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
            note = "Aperçu pas encore rendu (clic droit dans la colonne pour le rendre)"
        else:
            note = "Aperçu en cours de chargement…"
        return placeholder_pixmap(path, note)

    def _on_focus_preview_ready(self, path_str: str, mtime: float, image):
        """Apercu du pipeline arrive : vignette de la pellicule, voisine du ruban, ou image au
        centre qui n'avait encore rien de mieux (il remplace la carte / la petite vignette)."""
        if not self._project_columns_hidden:
            return
        if self._filmstrip is not None and self._filmstrip.isVisible():
            self._filmstrip.update()
        overlay = self._focus_overlay
        if overlay is None or image is None or image.isNull():
            return
        if path_str != self._focus_path:
            if overlay.animating():
                overlay.update()
            return
        path = Path(path_str)
        if self._focus_images.get(path) is not None:
            return                                  # deja en pleine definition
        overlay.upgrade(QPixmap.fromImage(image), self._focus_images.known_natural(path))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and watched is self.scroll.viewport() and self._on_focus_wheel(event):
            return True
        if (event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
                and watched in (self.scroll.viewport(), self.columns_host) and event.button() == Qt.LeftButton):
            self._on_viewer_background_click(event)
        return super().eventFilter(watched, event)

    # -- Visionneuse : clic a cote de l'image --
    # Clic dans le vide a cote de l'image (ni sur elle, ni sur la pellicule, un bouton ou le tableau
    # des parametres) : elle se replie dans la PLANCHE (`_open_focus_gallery`, elle vole dans sa case).

    def _viewer_background_at(self, global_pos) -> bool:
        if not self._viewer_active():
            return False
        return QApplication.widgetAt(global_pos) in (self.scroll.viewport(), self.columns_host)

    def _gallery_background_at(self, global_pos) -> bool:
        """Planche ouverte : le fond autour d'elle (entre elle et les bords de la zone)."""
        if not (self._project_columns_hidden and self._focus_gallery is not None):
            return False
        return QApplication.widgetAt(global_pos) in (self.scroll.viewport(), self.columns_host)

    def _on_viewer_background_click(self, event):
        pos = event.globalPosition().toPoint()
        if event.type() == QEvent.MouseButtonPress:
            self._viewer_press = pos if (self._viewer_background_at(pos) or self._gallery_background_at(pos)) else None
            return
        press, self._viewer_press = self._viewer_press, None
        if press is None or (pos - press).manhattanLength() >= QApplication.startDragDistance():
            return
        if self._viewer_background_at(pos):
            # Demande de l'utilisateur : l'image se replie dans la PLANCHE (elle vole dans sa case,
            # comme G), pas dans la pellicule — qui peut d'ailleurs etre coupee dans les reglages.
            self._open_focus_gallery()
        elif self._gallery_background_at(pos):
            self._set_columns_hidden(False)        # planche : clic a cote du tableau = retour aux colonnes

    def _on_focus_wheel(self, event) -> bool:
        """Etat focus (image seule au centre) : la molette passe d'une image a l'autre du dossier,
        vers le bas = suivante. Recue sur l'image elle-meme (FocusOverlay, on_wheel) ou n'importe
        ou dans la zone des colonnes masquees. Crans cumules (pave tactile : petits deltas)."""
        if not self._project_columns_hidden or self._focus_gallery is not None:
            return False
        if event.modifiers() & Qt.ControlModifier:
            self._viewer_ctrl_wheel(event)
            return True
        self._focus_wheel += event.angleDelta().y() or event.angleDelta().x()
        steps = int(self._focus_wheel / 120)
        if steps:
            self._focus_wheel -= steps * 120
            self._step_focus_image(-steps)
        return True

    def _step_focus_image(self, step: int):
        """Fichier `step` places plus loin (negatif : avant) parmi les fichiers a apercu de la
        colonne du fichier en cours (images, mais aussi .ma, .obj, .blend, PSD, plans, videos...),
        dans son ordre ; aux extremites, l'image rebondit (bump) au lieu de changer."""
        count = len(self._viewer_paths)
        if not step or not 0 <= self._viewer_index < count:
            return
        overlay = self._focus_overlay
        if overlay is not None and overlay.running:
            overlay.finish_now()
        target = max(0, min(count - 1, self._viewer_index + step))
        if target == self._viewer_index:
            if overlay is not None:
                overlay.bump(step)
            return
        self._viewer_go(target, target - self._viewer_index)

    # -- Visionneuse : ruban, pellicule, clavier, zoom --

    _VIEWER_SYNC_MS = 700

    def _enter_viewer(self):
        """Colonnes masquees : la visionneuse prend la main. Liste des fichiers du dossier (ordre
        de la colonne), image en cours a sa place definitive (taille reelle lue dans l'entete) et
        demandee en pleine definition, voisines prechargees, pellicule et clavier."""
        paths, current = self._scan_viewer_paths()
        self._viewer_purs = [p for p in paths if p.suffix.lower() in PUR_PREVIEW_EXTENSIONS]
        paths, self._viewer_index = self._expand_viewer_pureref(paths, current)
        self._viewer_paths = self._viewer_base = paths
        self._viewer_previews = {}
        if self._filmstrip is not None and self._viewer_index >= 0:
            self._filmstrip.set_paths(paths, self._viewer_index)
        self._sync_viewer_chrome()                       # pellicule creee : sa bande est reservee
        self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
        if self._viewer_index >= 0:
            path = paths[self._viewer_index]
            self._focus_path = str(path)
            overlay = self._focus_overlay
            if overlay is not None:
                self._attach_viewer(overlay)
                # Place definitive (taille reelle, au-dessus de la pellicule), posee en debut de vol :
                # rien ne saute.
                overlay.set_natural(self._focus_images.natural_size(path) or overlay._natural, self._viewer_area())
                hit = self._focus_images.get(path)
                if hit is not None:
                    overlay.upgrade(hit[0], hit[2], hit[1])
                else:
                    self._focus_images.request(path, urgent=True)
            self._prefetch_viewer(self._viewer_index, 1)

    # -- Planches PureRef : leurs images dans la visionneuse --

    def _expand_viewer_pureref(self, paths: list, current: str | None) -> tuple:
        """(liste, rang du fichier en cours) ou chaque planche .pur est remplacee par ses images
        quand elles existent deja en fichiers ; sinon la planche reste (son apercu) et ses images
        sont extraites en fond (_on_pur_images_ready la remplacera). Planche en cours : l'image que
        l'inspecteur montre."""
        out, index = [], -1
        for path in paths:
            files = self._pur_files(path) if path.suffix.lower() in PUR_PREVIEW_EXTENSIONS else None
            if files:
                if str(path) == current:
                    shown = getattr(self.detail, "_pur_image_index", 0) \
                        if getattr(self.detail, "_pur_image_path", None) == str(path) else 0
                    index = len(out) + max(0, min(len(files) - 1, int(shown or 0)))
                out.extend(files)
                continue
            if str(path) == current:
                index = len(out)
            out.append(path)
        return out, index

    def _pur_files(self, pur: Path) -> list | None:
        mtime = _previews.cached_mtime(pur)
        if mtime is None:
            return None
        known = self._pur_expansions.get(str(pur))
        if known is not None and known[0] == mtime:
            return known[1] or None
        files = pur_image_files(pur, mtime)
        if files is None:
            self._start_pur_images(pur, mtime)
            return None
        self._remember_pur(pur, mtime, files)
        return files or None

    def _remember_pur(self, pur: Path, mtime: float, files: list):
        files = [Path(f) for f in files]
        self._pur_expansions[str(pur)] = (mtime, files)
        for rank, image in enumerate(files):
            self._pur_sources[str(image)] = (pur, rank)
            file_attributes.set_alias(image, pur.parent, f"{pur.name}/{image.name}")   # attributs : ceux de la planche
            _focus.DISPLAY_NAMES[str(image)] = f"{pur.name} · {rank + 1}/{len(files)}"

    def _start_pur_images(self, pur: Path, mtime: float):
        task = self._pur_tasks.get(str(pur))
        if task is not None and task.mtime == mtime:
            return
        task = PureRefImagesTask(pur, mtime)
        task.signals.finished.connect(self._on_pur_images_ready)
        self._pur_tasks[str(pur)] = task
        _PUR_EXPORT_POOL.start(task)

    def _on_pur_images_ready(self, pur_str: str, mtime: float, files, error: str):
        """Images d'une planche pretes : si la visionneuse la montre encore, elle est remplacee par
        ses images, sans changer l'image regardee (ou par sa 1re image si c'etait elle)."""
        self._pur_tasks.pop(pur_str, None)
        pur = Path(pur_str)
        if not files:
            self._pur_expansions[pur_str] = (mtime, [])
            return
        self._remember_pur(pur, mtime, files)
        try:
            pos = next(i for i, p in enumerate(self._viewer_paths) if str(p) == pur_str)
        except StopIteration:
            return
        images = self._pur_expansions[pur_str][1]
        self._viewer_paths[pos:pos + 1] = images
        current = self._viewer_index
        if current > pos:
            self._viewer_index = current + len(images) - 1
        if self._filmstrip is not None:
            self._filmstrip.set_paths(self._viewer_paths, self._viewer_index)
        if current == pos and self._viewer_active():
            self._viewer_go(pos, 0)                 # la planche montree devient sa 1re image

    def _viewer_active(self) -> bool:
        return (self._project_columns_hidden and self._focus_gallery is None
                and 0 <= self._viewer_index < len(self._viewer_paths))

    def _sync_viewer_chrome(self):
        """Pellicule, raccourcis clavier et suivi de la souris : actifs seulement colonnes
        masquees, image seule au centre (pas pendant la planche)."""
        if not self._project_columns_hidden:
            self._viewer_sync.stop()
            self._viewer_paths, self._viewer_index = [], -1
            self._viewer_base = []
            self._viewer_purs = []
        self._sync_pur_buttons()
        active = self._viewer_active()
        if active and not self._viewer_keys:
            self._ensure_viewer_keys()
        for shortcut in self._viewer_keys:
            shortcut.setEnabled(active)
        self._sync_info_panel(active)
        strip = self._filmstrip
        if not active or not self._filmstrip_enabled():
            self._viewer_idle.stop()
            if strip is not None and not strip.isHidden():
                strip.hide()
            if active and self._focus_overlay is not None:
                self._focus_overlay.set_holes(self._button_rects())
            return
        if strip is None:
            strip = self._filmstrip = FocusFilmstrip(
                self.scroll.viewport(), focus_thumbnail, on_wheel=self._on_focus_wheel,
                on_double_click=self._toggle_project_columns_hidden,
                on_resized=self._on_filmstrip_resized, on_split=self._on_filmstrip_split,
                on_menu=self._filmstrip_menu)
            strip.keep_shown = self._film_style_open
            strip.chosen.connect(self._on_filmstrip_chosen)
            strip.set_paths(self._viewer_paths, self._viewer_index)
        if strip.isHidden():
            strip.setGeometry(self._filmstrip_rect())
            strip.set_current(self._viewer_index)
            strip.set_position(self._viewer_index)
            strip.show()
            strip.reveal()
        strip.raise_()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())
        holder = QApplication.focusWidget()
        if holder is None or not holder.isVisible():
            # Le widget qui avait le clavier a disparu (colonnes Focus rebaties par la navigation
            # de la visionneuse) : sans lui, plus aucun raccourci ne repondrait.
            self._park_keyboard_focus()
        if not self._viewer_idle.isActive():
            self._viewer_cursor = None
            self._viewer_idle.start()

    def _sync_pur_buttons(self):
        """Visionneuse (ou planche) ouverte sur un dossier qui contient des planches PureRef : un
        bouton par fichier, a la suite des autres boutons (repli / masquer / planche, ou le bouton
        flottant), sur leur ligne, qui l'ouvre dans PureRef (logiciel par defaut). Meme habillage
        que ces boutons (style_focus_button), largeur = le nom."""
        purs = self._viewer_purs if self._project_columns_hidden else []
        viewport = self.scroll.viewport()
        while len(self._pur_buttons) < len(purs):
            button = IconButton("text", role_color("buttons", "#c4cacf"), C["text"], parent=viewport)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _c=False, b=button: open_path(b._pur_path))
            self._pur_buttons.append(button)
        for button, pur in zip(self._pur_buttons, purs):
            style_focus_button(button)
            button._pur_path = pur
            button.set_text_label(pur.name)
            button.setToolTip(f"Ouvrir {pur.name} dans PureRef")
            width = button.fontMetrics().horizontalAdvance(pur.name) + scaled(20)
            button.setFixedWidth(max(button.width(), width))
            button.show()
            button.raise_()
        for button in self._pur_buttons[len(purs):]:
            button.hide()
        self._layout_viewer_buttons()

    # -- Rangee des boutons de la visionneuse / planche : ordre choisi a la main (Ctrl + glisser) --

    _BUTTON_DEFAULT_ORDER = ("hide", "gallery", "filter", "pur")

    def _viewer_row_items(self) -> list:
        """(identifiant, bouton) des boutons deplacables de la rangee, dans l'ordre retenu
        (`viewer_button_order`) ; ceux qui n'y sont pas encore suivent, dans l'ordre par defaut. Le bouton
        de repliement reste en tete (sa place est un reglage)."""
        items = []
        if self.image_preview_columns:
            pc = self.image_preview_columns[0]
            for key, button in (("hide", pc.hide_btn), ("gallery", pc.gallery_btn)):
                if button is not None and not button.isHidden():
                    items.append((key, button))
        for key, button in (("gallery", self._floating_gallery_btn), ("filter", self._filter_btn)):
            if button is not None and not button.isHidden():
                items.append((key, button))
        items.extend((f"pur:{b._pur_path.name}", b) for b in self._pur_buttons if not b.isHidden())
        order = list((ui_state.APPLIED_SETTINGS or {}).get("viewer_button_order") or [])
        defaults = self._BUTTON_DEFAULT_ORDER

        def rank(pair):
            index, (key, _button) = pair
            if key in order:
                return (0, order.index(key), index)
            return (1, defaults.index(key.split(":", 1)[0]), index)
        return [item for _i, item in sorted(enumerate(items), key=rank)]

    def _layout_viewer_buttons(self):
        """Pose la rangee dans l'ordre retenu, a la suite du bouton de repliement (ou depuis la place du
        bouton flottant) ; les elements du filtre suivent son bouton. Colonnes masquees seulement (sinon
        la colonne Focus place elle-meme ses boutons)."""
        if not self._project_columns_hidden:
            return
        viewport = self.scroll.viewport()
        pc = self.image_preview_columns[0] if self.image_preview_columns else None
        if pc is not None and pc.toggle_btn is not None:
            start = QRect(pc.toggle_btn.mapTo(viewport, QPoint(0, 0)), pc.toggle_btn.size())
            x, y = start.right() + 1 + scaled(4, 0), start.top()
        else:
            style = column_style_for(PREVIEW_STACK_TITLE)
            x, y = scaled(int(style.get("preview_toggle_x", 8)), 0) + scaled(8, 0), scaled(10, 0)
        gap = scaled(4, 0)
        chips = self._filter_chips
        for key, button in self._viewer_row_items():
            parent = button.parentWidget()
            button.move(QPoint(x, y) if parent is viewport else parent.mapFrom(viewport, QPoint(x, y)))
            x += button.width() + gap
            self._button_drag.hook(button)
            if key == "filter" and chips is not None and not chips.isHidden():
                chips.move(x - gap + scaled(6), y + (button.height() - chips.height()) // 2)
                x = chips.x() + chips.width() + scaled(6)
        if pc is not None:
            pc.fit_buttons()

    def _move_viewer_button(self, keys: list, source: int, target: int):
        """Glisser termine : le bouton `source` passe devant l'emplacement `target` (0..len) ; ordre
        enregistre aussitot (etat temps reel), les boutons absents gardent leur rang relatif a la fin."""
        keys = list(keys)
        moved = keys.pop(source)
        keys.insert(target - (1 if target > source else 0), moved)
        settings = ui_state.APPLIED_SETTINGS if isinstance(ui_state.APPLIED_SETTINGS, dict) else {}
        saved = list(settings.get("viewer_button_order") or [])
        order = keys + [k for k in saved if k not in keys]
        settings["viewer_button_order"] = order
        from settings_store import save_live_state
        save_live_state("viewer_button_order", order)
        self._layout_viewer_buttons()

    @staticmethod
    def _filmstrip_enabled() -> bool:
        """Reglages > Visionneuse > « Diapositives sous l'image en focus » (la pellicule)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_filmstrip_enabled", True))

    @staticmethod
    def _info_enabled() -> bool:
        """Reglages > Visionneuse > « Parametres de l'image » (tableau a droite de l'image)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_info_enabled", False))

    @staticmethod
    def _viewer_slide_enabled() -> bool:
        """Reglages > Visionneuse > « Effet slide entre les images » (le ruban)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_slide_enabled", True))

    def _apply_viewer_settings(self):
        """Reglages de la visionneuse appliques en direct : pellicule affichee ou non, et l'image
        au centre recalee sur la zone qui lui revient (la bande de la pellicule est liberee)."""
        self._sync_viewer_toggle_keys()
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.restyle()                     # habillage des reglages : suit leurs changements
        self._sync_viewer_chrome()
        strip = self._filmstrip
        if strip is not None and strip.isVisible():
            # Habillage des diapositives (Reglages > Visionneuse > Tableau / sous-cellules) : la
            # bande suit la hauteur des cellules (image + texte).
            if strip.height() != strip.strip_height():
                strip.setGeometry(self._filmstrip_rect())
            strip.update()
            strip.reveal()                       # montree pendant qu'on la regle (sinon effacee)
        if self._focus_gallery is not None:
            self._focus_gallery.restyle()        # la planche : memes reglages
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.restyle()                    # Reglages > Visionneuse > Focus : cadre de l'image
        if overlay is not None and self._project_columns_hidden:
            overlay.set_geometry_target(self._viewer_area())
            self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())

    # -- Diapositives : sous-cellules image | texte, tableau a la volee (clic droit) --

    def _on_filmstrip_split(self, ratio: float, final: bool):
        """Ctrl + bordure image | texte d'une diapositive : hauteur du texte, appliquee en direct (seule
        la bande suit pendant le geste ; l'image au centre se recale au relachement) et enregistree."""
        self._on_filmstrip_style({"viewer_film_text_ratio": round(float(ratio), 4)}, light=not final)
        if final:
            self._flush_filmstrip_style()

    def _on_gallery_split(self, height: int, final: bool):
        """Ctrl + bordure image | texte d'une case de la planche : hauteur du texte (px), en direct,
        enregistree."""
        self._on_filmstrip_style({"viewer_gallery_text_height": int(height)}, light=True)
        if self._focus_gallery is not None:
            self._focus_gallery.restyle()
        if final:
            self._flush_filmstrip_style()

    def _filmstrip_menu(self, global_pos):
        """Clic droit sur la pellicule : style du tableau, de la sous-cellule image ou de la sous-cellule
        texte, dans la fenetre « Changement de style a la volee » (pas d'override : une seule visionneuse,
        ce sont les valeurs de Reglages > Visionneuse)."""
        from settings_window_v2 import VIEWER_FILM_GROUPS
        menu = Menu(self)
        head = menu.addAction("Changement de style à la volée")
        head.setEnabled(False)
        menu.addSeparator()
        names = {"Tableau": "Tableau…", "Sous cellule image": "Cellule image…", "Sous cellule texte": "Cellule texte…"}
        actions = {menu.addAction(names.get(title, title)): (title, group) for title, group in VIEWER_FILM_GROUPS}
        chosen = menu.exec(global_pos)
        if chosen in actions:
            QTimer.singleShot(0, lambda: self._open_filmstrip_style(*actions[chosen]))

    def _open_filmstrip_style(self, title: str, group: str):
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        previous, self._film_style_window = getattr(self, "_film_style_window", None), None
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:              # deja detruite
                pass
        settings = dict(DEFAULT_SETTINGS)
        settings.update(ui_state.APPLIED_SETTINGS or load_settings())
        window = self._film_style_window = QuickStyleWindow(
            f"Visionneuse : {title}", v2.CATALOG[group], settings, title=f"Diapositives — {title.lower()}",
            settings=settings, parent=self)
        window.styleChanged.connect(self._on_filmstrip_style)
        window.destroyed.connect(lambda *_a, w=window: self._forget_film_style_window(w))
        window.move(QCursor.pos() + QPoint(12, 12))
        window.show()

    def _film_style_open(self) -> bool:
        """Une fenetre qui regle les diapositives est ouverte (tableau a la volee, reglages v2) : la
        pellicule reste affichee pour qu'on voie l'effet."""
        for window in (getattr(self, "_film_style_window", None), getattr(self, "_settings_dialog_v2", None)):
            try:
                if window is not None and window.isVisible():
                    return True
            except RuntimeError:
                pass
        return False

    def _forget_film_style_window(self, window):
        if getattr(self, "_film_style_window", None) is window:
            self._film_style_window = None
        self._flush_filmstrip_style()

    def _on_filmstrip_style(self, values: dict, light: bool = False):
        """Valeurs des diapositives changees (tableau a la volee, bordure image | texte) : appliquees aussitot,
        ecrites sur le disque 300 ms apres la derniere (regroupe un glissement de curseur)."""
        if not isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS = load_settings()
        ui_state.APPLIED_SETTINGS.update(values)
        pending = getattr(self, "_film_style_pending", None)
        if pending is None:
            pending = self._film_style_pending = {}
        pending.update(values)
        timer = getattr(self, "_film_style_timer", None)
        if timer is None:
            timer = self._film_style_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._flush_filmstrip_style)
        timer.start()
        strip = self._filmstrip
        if light:
            if strip is not None and strip.isVisible():
                strip.setGeometry(self._filmstrip_rect())
                strip.update()
        else:
            self._apply_viewer_settings()

    def _flush_filmstrip_style(self):
        """Enregistre les valeurs en attente ; la fenetre de reglages ouverte les reprend (ses tableaux
        Visionneuse sont refaits), sinon elle les ecraserait avec ses anciennes valeurs."""
        timer = getattr(self, "_film_style_timer", None)
        if timer is not None:
            timer.stop()
        pending = getattr(self, "_film_style_pending", None)
        if not pending:
            return
        values, self._film_style_pending = dict(pending), {}
        settings = load_settings()
        settings.update(values)
        save_settings(settings)
        # Preset par defaut actif : le mettre a jour aussi, sinon load_settings le rejoue PAR-DESSUS le
        # fichier au prochain lancement et les valeurs a la volee sont perdues (bug signale).
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.update(values))
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(values)
        except RuntimeError:                  # fenetre de reglages detruite
            pass

    def _on_filmstrip_resized(self):
        """Vignettes de la pellicule zoomees (Ctrl+molette) : sa bande change de hauteur, l'image
        au centre se recale sur la zone qui lui reste."""
        if self._filmstrip is not None and self._filmstrip.isVisible():
            self._filmstrip.setGeometry(self._filmstrip_rect())
        self._apply_viewer_settings()

    def _raise_viewer_chrome(self):
        """La pellicule et le bouton flottant restent au-dessus de l'image et des fondus."""
        for widget in (self._filmstrip, getattr(self, "_info_panel", None), self._floating_gallery_btn,
                       *self._pur_buttons):
            if widget is not None and widget.isVisible():
                widget.raise_()

    def _park_keyboard_focus(self):
        """Clavier gare sur le bouton « masquer » (ou la zone des colonnes) : jamais sur un champ
        texte visible, qui avalerait les raccourcis de la visionneuse."""
        if not self._project_columns_hidden:
            return
        if self.image_preview_columns and self.image_preview_columns[0].hide_btn is not None:
            self.image_preview_columns[0].hide_btn.setFocus()
        else:
            self.scroll.viewport().setFocus()

    def _filmstrip_rect(self) -> QRect:
        viewport = self.scroll.viewport()
        height = self._filmstrip.strip_height() if self._filmstrip is not None else 0
        return QRect(0, viewport.height() - height, viewport.width(), height)

    def _viewer_area(self) -> QRect:
        """Zone ou l'image se pose au centre : celle des colonnes, moins la bande de la pellicule
        (reservee meme quand elle s'efface : l'image ne bouge jamais et n'est jamais couverte) et
        moins celle du tableau des parametres a droite (Reglages > Visionneuse)."""
        area = QRect(self._focus_area())
        if not (self._project_columns_hidden and 0 <= self._viewer_index < len(self._viewer_paths)):
            return area                     # (planche ouverte comprise : l'image y revient a la meme place)
        strip = self._filmstrip
        if strip is not None and self._filmstrip_enabled():
            area.setHeight(max(1, area.height() - max(0, strip.strip_height() - scaled(30))))
        if self._info_enabled():
            # Bande du tableau retiree des DEUX cotes : l'image reste centree sur toute la largeur,
            # sans jamais passer sous le tableau.
            band = min(FocusInfoPanel.panel_width() + scaled(16), max(0, area.width() // 2 - 1))
            area.adjust(band, 0, -band, 0)
        return area

    def _info_rect(self) -> QRect:
        """Place du tableau des parametres : a droite de l'image, au-dessus de la pellicule."""
        full, area = self._focus_area(), self._viewer_area()
        margin = scaled(16)
        width = FocusInfoPanel.panel_width()
        return QRect(full.right() + 1 - margin - width, area.y() + margin, width,
                     max(1, area.height() - 2 * margin))

    def _sync_info_panel(self, active: bool):
        """Tableau des parametres de l'image (Reglages > Visionneuse > « Parametres de l'image »,
        touche I) : visible visionneuse ouverte, sur le fichier en cours."""
        panel = getattr(self, "_info_panel", None)
        if not (active and self._info_enabled()):
            if panel is not None and not panel.isHidden():
                panel.hide()
            return
        if panel is None:
            panel = self._info_panel = FocusInfoPanel(self.scroll.viewport())
        panel.setGeometry(self._info_rect())
        if 0 <= self._viewer_index < len(self._viewer_paths):
            panel.set_path(self._viewer_paths[self._viewer_index])
        if panel.isHidden():
            panel.show()
        panel.raise_()

    def _viewer_fit_size(self) -> QSize:
        """Zone ou l'image est ajustee, en pixels physiques (marges de fit_rect retirees)."""
        area = self._viewer_area()
        dpr = self.devicePixelRatioF() or 1.0
        return QSize(max(1, round((area.width() - 80) * dpr)), max(1, round((area.height() - 80) * dpr)))

    def _attach_viewer(self, overlay):
        overlay.set_viewer(self._viewer_neighbour, self._on_viewer_moved, self._button_rects(),
                           on_click=self._on_viewer_image_click)

    def _on_viewer_image_click(self):
        """Clic simple sur l'image en focus : comme a cote d'elle, elle se replie dans la PLANCHE."""
        if self._viewer_active():
            self._open_focus_gallery()

    def _viewer_go(self, index: int, delta: int = 0, fallback: QPixmap | None = None):
        """Montre le fichier de rang `index` ; `delta` = son ecart avec le precedent (le ruban
        glisse de ce cote). Rien de bloquant : image prete, sinon la meilleure en memoire en
        attendant (_on_focus_image_ready la remplace)."""
        paths = self._viewer_paths
        if not 0 <= index < len(paths):
            return
        self._viewer_index = index
        path = paths[index]
        self._focus_path = str(path)
        pixmap, natural, full = self._viewer_image(path, fallback)
        overlay = self._focus_overlay
        if overlay is None and self._project_columns_hidden and not pixmap.isNull():
            # Colonnes masquees sans objet au centre (fichier sans apercu au depart) : on le cree.
            size = natural if natural is not None else QSizeF(pixmap.width(), pixmap.height())
            target = fit_rect(size, self._viewer_area())
            overlay = self._focus_overlay = FocusOverlay(
                self.scroll.viewport(), pixmap, target, target, 1.0, 1.0, 1,
                on_double_click=self._toggle_project_columns_hidden, on_wheel=self._on_focus_wheel)
            self._attach_viewer(overlay)
            overlay.show()
            overlay.raise_()
            self._raise_viewer_chrome()
            delta = 0
        # Reglages > Visionneuse > « Effet slide entre les images » coupe : l'image change sur place
        # (pas de ruban) ; la pellicule, elle, defile comme avant ; `delta` sert aussi au prechargement.
        slide = delta if self._viewer_slide_enabled() else 0
        if overlay is not None and not pixmap.isNull():
            overlay.show_image(pixmap, natural, full, slide)
        # Le retour vers l'inspecteur doit viser la place de la NOUVELLE image : capture refaite.
        self._columns_snapshot = None
        self._prefetch_viewer(index, -1 if delta < 0 else 1)
        strip = self._filmstrip
        if strip is not None:
            strip.set_current(index)
            if not delta:
                strip.set_position(index)
            elif not slide:                          # pas de ruban a suivre : la pellicule glisse seule
                strip.glide_to(index)
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.set_path(path)
            strip.reveal()
        self._viewer_sync.start()

    def _viewer_image(self, path: Path, fallback: QPixmap | None = None) -> tuple:
        """(pixmap, taille reelle ou None, image pleine definition ou None) pour `path`."""
        hit = self._focus_images.get(path)
        if hit is not None:
            return hit[0], hit[2], hit[1]
        natural = self._focus_images.natural_size(path)
        self._focus_images.request(path, urgent=True)
        return self._focus_pixmap(path, fallback), natural, None

    def _viewer_neighbour(self, k: int):
        """Voisine k du ruban, pour le dessin du glissement : seulement ce qui est deja en memoire."""
        i = self._viewer_index + k
        if not 0 <= i < len(self._viewer_paths):
            return None
        path = self._viewer_paths[i]
        hit = self._focus_images.get(path)
        if hit is not None:
            return hit[0], hit[2]
        pixmap = self._viewer_previews.get(str(path))
        if pixmap is None:
            cached = _previews._file_image_cache.get(str(path))
            pixmap = cached[1] if cached is not None else None
        if pixmap is None or pixmap.isNull():
            # Defilement rapide : la petite vignette des colonnes en attendant, plutot que du vide.
            pixmap = _previews.file_image_pixmap(path, asynchronous=True)
        if pixmap is None or pixmap.isNull():
            return None
        return pixmap, self._focus_images.known_natural(path)

    def _prefetch_viewer(self, index: int, direction: int):
        """Prepare les voisines (d'abord dans le sens de la marche) : decodage en fond des images,
        apercus des autres fichiers lus apres le glissement (lecture disque)."""
        paths = self._viewer_paths
        later = []
        self._focus_images.retain(paths[max(0, index - 3):index + 4])
        for k in (direction, -direction, 2 * direction, 3 * direction, -2 * direction):
            i = index + k
            if not 0 <= i < len(paths):
                continue
            path = paths[i]
            if self._focus_images.supports(path):
                self._focus_images.natural_size(path)
                self._focus_images.request(path)
            elif str(path) not in self._viewer_previews:
                later.append(path)
        if later:
            QTimer.singleShot(FocusOverlay.SLIDE_MS + 40, lambda: self._prefetch_previews(later))

    def _prefetch_previews(self, paths: list):
        if not self._project_columns_hidden:
            return
        for path in paths:
            key = str(path)
            if key in self._viewer_previews:
                continue
            mtime = _previews.cached_mtime(path)
            if mtime is None:
                continue
            cached = _previews._file_image_cache.get(key)
            pixmap = cached[1] if cached is not None and cached[0] == mtime else None
            if pixmap is None:
                pixmap, _stale = _previews._read_preview_pixmap(path, mtime)
            if pixmap is None or pixmap.isNull():
                _previews.file_image_pixmap(path, asynchronous=True)
                continue
            if len(self._viewer_previews) > 48:
                self._viewer_previews.clear()
            self._viewer_previews[key] = pixmap

    def _on_viewer_moved(self, offset: float):
        """Chaque pas du ruban : la pellicule glisse avec lui (sauf quand elle glisse seule, effet slide
        coupe : un pas sans decalage, zoom ou rebond, l'arreterait net)."""
        strip = self._filmstrip
        if strip is not None and self._viewer_index >= 0 and not (offset == 0 and strip.gliding()):
            strip.set_position(self._viewer_index - offset)

    def _on_focus_image_ready(self, key: str):
        """Image pleine definition prete : celle du centre se precise (sans bouger), une voisine
        en plein glissement apparait."""
        overlay = self._focus_overlay
        if overlay is None or not self._project_columns_hidden:
            return
        if 0 <= self._viewer_index < len(self._viewer_paths) and key == str(self._viewer_paths[self._viewer_index]):
            hit = self._focus_images.get(Path(key))
            if hit is not None:
                overlay.upgrade(hit[0], hit[2], hit[1])
        elif overlay.animating():
            overlay.update()

    def _on_filmstrip_chosen(self, index: int):
        if index != self._viewer_index:
            self._viewer_go(index, index - self._viewer_index)

    def _viewer_jump(self, index: int):
        index = max(0, min(len(self._viewer_paths) - 1, index))
        if 0 <= self._viewer_index != index:
            self._viewer_go(index, index - self._viewer_index)

    def _sync_viewer_selection(self):
        """Au repos : la colonne (masquee) et l'inspecteur passent sur l'image montree. Repousse
        tant que l'image bouge (pas d'a-coup en plein glissement)."""
        if not self._viewer_active():
            return
        overlay = self._focus_overlay
        if overlay is not None and overlay.animating():
            self._viewer_sync.start()
            return
        self._select_viewer_file(self._viewer_paths[self._viewer_index])
        self._return_grab.start()                # colonnes changees : leur capture de retour, au repos

    def _settle_columns_layout(self):
        """Colonnes re-affichees le temps d'une capture : leurs mises en page en attente (inspecteur mis a
        jour pendant le masquage : un widget cache ne se remet pas en page) sont faites TOUT DE SUITE, sans
        rien peindre. Sinon capture et place de retour de l'image etaient relevees sur l'ancienne mise en
        page : l'image arrivait 50 a 80 px a cote de l'apercu de l'inspecteur et sautait a la fin."""
        self.columns_layout.activate()
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        self.columns_layout.activate()

    def _pregrab_columns(self):
        """Visionneuse ouverte, au repos : la capture des colonnes pour leur retour est faite D'AVANCE
        (colonnes affichees, capturees, re-masquees sans retour a la boucle d'evenements : rien ne
        s'affiche), avec la place de retour de l'image dans l'inspecteur. Le retour la trouve a jour et
        demarre aussitot ; avant, il la refaisait au clic (~50 ms) apres la synchro de la colonne (~100 ms) :
        la saccade signalee au retour aux colonnes."""
        if not self._project_columns_hidden:
            return
        overlay, gallery = self._focus_overlay, self._focus_gallery
        if (_anim_running(self._columns_fade) or self._viewer_sync.isActive()
                or (overlay is not None and (overlay.running or overlay.animating()))
                or (gallery is not None and gallery._busy())):
            self._return_grab.start()            # une animation tourne : plus tard
            return
        if gallery is not None and not self._gallery_deselected:
            # Planche ouverte : sa sortie vers les colonnes laisse la colonne SANS fichier selectionne. Cette
            # deselection est faite d'avance (colonnes masquees : rien ne se voit) pour que la capture du
            # retour la montre deja ; la sortie demarre alors aussitot (avant : ~90 ms au clic). Revenir a
            # une image la reselectionne (_close_focus_gallery -> synchro).
            self._gallery_deselected = True
            self._deselect_viewer_file()
        cached = self._columns_snapshot
        if (cached is not None and len(cached) > 5 and cached[2] == self.scroll.viewport().size()
                and cached[3] == self._columns_epoch and cached[5] == self._project_columns_collapsed):
            return                               # deja a jour
        try:
            self._apply_columns_hidden(False)
            self._settle_columns_layout()
            snapshot = self._grab_columns()
            source = self._focus_source()        # place de retour (inspecteur affiche le temps de la capture)
            self._columns_snapshot = (*snapshot, time.monotonic(), self._project_columns_collapsed, (source,))
        finally:
            self._apply_columns_hidden(True)

    def _flush_viewer_sync(self):
        """Tout de suite (retour des colonnes) : la colonne et l'inspecteur rattrapent l'image."""
        pending = self._viewer_sync.isActive()
        self._viewer_sync.stop()
        if pending and 0 <= self._viewer_index < len(self._viewer_paths):
            self._select_viewer_file(self._viewer_paths[self._viewer_index])

    def _select_viewer_file(self, path: Path):
        source = self._pur_sources.get(str(path))
        if source is not None:
            # Image d'une planche PureRef : la planche dans sa colonne, l'inspecteur sur cette image.
            self._select_viewer_file(source[0])
            # L'inspecteur va sur CETTE image de la planche, meme si ses images ne sont pas encore listees
            # (extraction en fond : avant, il finissait sur la premiere — signale).
            self.detail.select_pur_image(str(source[0]), source[1])
            return
        key = str(path)
        column, current = self._focus_file_column()
        if current is not None and str(current) == key:
            return
        candidates = [column] if column is not None else []
        candidates += [c for c in [*self.columns, *self.group_columns] if c is not column]
        for candidate in candidates:
            view = candidate.list
            for i in range(view.count()):
                item = view.item(i)
                if item.data(ROLE_PATH) == key:
                    if view.currentItem() is not item:
                        view.setCurrentItem(item)          # navigation : l'inspecteur suit
                    view.scrollToItem(item)
                    return
        # Fichier d'un autre dossier (planche filtree sur une portee large) : les colonnes vont jusqu'a lui.
        self._navigate_to(path)

    def _ensure_viewer_keys(self):
        """Raccourcis de la visionneuse (actifs seulement image seule au centre, voir
        _sync_viewer_chrome) : fleches / Page / Espace / Retour arriere = suivante / precedente,
        Debut / Fin, G = planche, + / - / 0 / 1 = zoom (- sur l'image ajustee : planche), Echap =
        dezoomer puis revenir aux colonnes."""
        def add(keys, slot):
            for key in keys:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WindowShortcut)
                shortcut.setEnabled(False)
                shortcut.activated.connect(slot)
                self._viewer_keys.append(shortcut)
        add(("Right", "Down", "PgDown", "Space"), lambda: self._step_focus_image(1))
        add(("Left", "Up", "PgUp", "Backspace"), lambda: self._step_focus_image(-1))
        add(("Home",), lambda: self._viewer_jump(0))
        add(("End",), lambda: self._viewer_jump(len(self._viewer_paths) - 1))
        add(("G",), self._toggle_focus_gallery)
        add(("+", "="), lambda: self._viewer_zoom(1.25))
        add(("-",), lambda: self._viewer_zoom(0.8))
        add(("0",), lambda: self._focus_overlay is not None and self._focus_overlay.zoom_reset())
        add(("1",), lambda: self._focus_overlay is not None and self._focus_overlay.zoom_toggle_actual())
        add(("Esc",), self._viewer_escape)
        # Touches reglables (Reglages > Visionneuse, colonne Raccourci) : chacune bascule sa ligne.
        self._viewer_toggle_keys = {}
        for setting in self._VIEWER_TOGGLES:
            shortcut = QShortcut(self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setEnabled(False)
            shortcut.activated.connect(lambda setting=setting: self._toggle_viewer_setting(setting))
            self._viewer_keys.append(shortcut)
            self._viewer_toggle_keys[setting] = shortcut
        self._sync_viewer_toggle_keys()

    # Lignes de Reglages > Visionneuse qui ont une touche : reglage -> (cle de la touche, defaut).
    _VIEWER_TOGGLES = {"viewer_filmstrip_enabled": ("viewer_filmstrip_shortcut", True),
                       "viewer_info_enabled": ("viewer_info_shortcut", False)}

    def _on_element_style_saved(self, key: str, value):
        """Override d'un element enregistre (clic droit > Override settings) : les reglages appliques
        le connaissent ; une surcharge de colonne restyle la fenetre (regroupe, 60 ms)."""
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        if key == "element_style_overrides":
            return
        timer = getattr(self, "_override_apply_timer", None)
        if timer is None:
            timer = self._override_apply_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(lambda: self._apply_settings(dict(ui_state.APPLIED_SETTINGS or {})))
        timer.start()

    def _override_targets(self, widget):
        """« Override settings » sur une colonne de la fenetre (settings_element_style.TARGET_RESOLVERS) :
        ses tableaux de surcharge (onglet de la colonne dans les reglages)."""
        import settings_element_style as es
        if widget is None or widget.window() is not self:
            return []
        node = widget
        while node is not None and not isinstance(node, (Column, PreviewColumn)):
            node = node.parentWidget()
        if node is None:
            return []
        title = getattr(node, "style_title", None) or node.column_title
        shown = getattr(node, "display_title", None) or node.column_title
        return [es.ColumnTarget(title, node, str(shown))]

    def _sync_viewer_toggle_keys(self):
        applied = ui_state.APPLIED_SETTINGS or {}
        for setting, shortcut in (getattr(self, "_viewer_toggle_keys", None) or {}).items():
            shortcut.setKey(QKeySequence(str(applied.get(self._VIEWER_TOGGLES[setting][0]) or "")))

    def _toggle_viewer_setting(self, setting: str):
        """Touche d'une ligne de Reglages > Visionneuse : bascule le reglage, l'enregistre aussitot ;
        la fenetre de reglages ouverte suit (sa ligne est mise a jour)."""
        default = self._VIEWER_TOGGLES[setting][1]
        enabled = not bool((ui_state.APPLIED_SETTINGS or {}).get(setting, default))
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            for store in (dialog.stores.values() if dialog is not None and dialog.isVisible() else ()):
                for spec, widget in store.get("specs", ()):
                    if getattr(spec, "key", None) == setting:
                        widget.setChecked(enabled)
        except RuntimeError:
            pass
        settings = load_settings()
        settings[setting] = enabled
        save_settings(settings)
        import browser_core                       # preset par defaut actif : sinon il rejoue l'ancienne valeur
        browser_core._sync_default_preset_override(settings, lambda preset: preset.__setitem__(setting, enabled))
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[setting] = enabled
        self._apply_viewer_settings()

    def _viewer_zoom(self, factor: float):
        overlay = self._focus_overlay
        if overlay is None:
            return
        if factor < 1.0 and not overlay.zoomed():
            self._open_focus_gallery()               # dezoomer l'image ajustee = voir tout le dossier
            return
        overlay.zoom_by(factor)

    def _viewer_escape(self):
        overlay = self._focus_overlay
        if overlay is not None and overlay.zoomed():
            overlay.zoom_reset()
        else:
            self._set_columns_hidden(False)

    def _viewer_ctrl_wheel(self, event):
        """Ctrl+molette : zoom autour du curseur ; vers l'arriere sur l'image ajustee, ouvre la
        planche (zoom « semantique », le pendant de Ctrl+molette avant dans la planche)."""
        overlay = self._focus_overlay
        delta = event.angleDelta().y()
        if overlay is None or not delta:
            return
        if delta < 0 and not overlay.zoomed():
            self._focus_pinch += delta
            if self._focus_pinch <= -120:
                self._focus_pinch = 0
                self._open_focus_gallery()
            return
        self._focus_pinch = 0
        anchor = QPointF(overlay.mapFromGlobal(event.globalPosition().toPoint()))
        overlay.zoom_by(1.2 ** (delta / 120), anchor)

    def _poll_viewer_cursor(self):
        """La pellicule s'efface quand la souris ne bouge plus et revient au moindre mouvement
        au-dessus de la fenetre (releve leger, pas de suivi de souris sur toute la zone)."""
        pos = QCursor.pos()
        if pos == self._viewer_cursor:
            return
        moved = self._viewer_cursor is not None
        self._viewer_cursor = pos
        if moved and self._filmstrip is not None and self.rect().contains(self.mapFromGlobal(pos)):
            self._filmstrip.reveal()

    def _enforce_hidden_columns(self, final: bool = False):
        try:
            self._enforce_hidden_columns_now(final)
        finally:
            # Colonnes Focus apparues / disparues, ou retour force : le bouton flottant suit.
            self._sync_floating_gallery_btn()

    def _enforce_hidden_columns_now(self, final: bool = False):
        """Garde tout masque pendant que le bouton « masquer » est actif, y
        compris ce que la navigation vient de (re)construire. Sans colonne
        Focus (donc sans bouton pour revenir) ni objet au centre (double-clic
        pour revenir), tout est reaffiche — decision prise uniquement apres une
        reconstruction COMPLETE des vignettes (`final`), pas pendant l'etat
        transitoire d'une navigation."""
        if not self._project_columns_hidden:
            return
        if not self.image_preview_columns and self._focus_overlay is not None:
            # Masque par double-clic sur un apercu, sans colonnes Focus : rien a
            # reconstruire, on garde juste tout masque.
            if not _anim_running(self._columns_fade):
                self._apply_columns_hidden(True)
            return
        if not self.image_preview_columns:
            if final:
                self._project_columns_hidden = False
                self._apply_columns_hidden(False)
                self._clear_focus_overlay()
                self._focus_src = None
            else:
                for widget in self._toggled_widgets():
                    if _shown_or_pending(widget):
                        widget._hidden_by_toggle = True
                        widget.setVisible(False)
            return
        if _anim_running(self._columns_fade):
            return
        self._apply_columns_hidden(True)
        for preview_column in self.image_preview_columns:
            preview_column.set_hide_state(True)

    def _auto_expand_now(self):
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        if self._project_columns_collapsed and (self._chain_terminal_path() is None or not focus_enabled):
            self._apply_project_columns_collapsed(False)

    def _auto_collapse_now(self):
        """Repli automatique differe (voir _sync_collapse_state), re-verifie : la
        navigation a pu changer entre-temps."""
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        if (self._chain_terminal_path() is not None and focus_enabled and auto_collapse_set_columns()
                and not self._project_columns_collapsed):
            self._apply_project_columns_collapsed(True)

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

    def _apply_project_columns_collapsed(self, collapsed: bool, animate: bool = True):
        """Replie/deplie EXACTEMENT les N premieres colonnes de self.columns
        (voir _chain_expected_total), N = le nombre d'etapes du projet
        courant — jamais au-dela : une colonne de contenu ouverte depuis le
        groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) reste
        TOUJOURS deployee, quoi qu'il arrive aux colonnes de set — voir la
        remarque de l'utilisateur, "attention a bien rabattre toutes
        colonnes ... c'est toutes les colonnes avant les colonnes de
        focus". Le mouvement est joue sur des captures (voir _SlideOverlay) :
        l'etat final est applique tout de suite, sans animer de largeur reelle
        (ce qui recalculait toutes les colonnes a chaque image)."""
        was_collapsed = self._project_columns_collapsed
        self._project_columns_collapsed = collapsed
        self._columns_snapshot = None   # le contenu des colonnes change : capture du fondu perimee
        if self.image_preview_columns:
            self.image_preview_columns[0].set_toggle_state(collapsed)
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        slide = self._columns_slide
        if _anim_running(slide) and slide.emerge:
            slide.finish_now()   # apparition d'une colonne : on la termine, elle ne se « retourne » pas
            slide = None
        if _anim_running(slide):
            # Clic pendant le mouvement : repart de la position courante.
            slide.retarget(0.0 if collapsed else 1.0, None if collapsed else self._expand_columns_now)
            return
        if (not animate or self._project_columns_hidden or not targets or was_collapsed == collapsed
                or not self.isVisible()):
            self._set_columns_collapsed_now(collapsed)
            return
        viewport = self.scroll.viewport()
        cached = self._slide_snapshot
        valid = (cached is not None and cached[5] == self._columns_epoch and cached[6] == viewport.size()
                 and cached[7] == len(targets))
        if collapsed:
            self._detail_state_width[False] = self.detail.width()   # etat deplie reel, avant repli
            if valid and time.monotonic() - cached[8] < 8.0:
                snapshot = cached[:5]             # amorcee au survol du bouton
            else:
                self.columns_layout.activate()
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                snapshot = self._grab_set_columns()   # etat deplie actuel
            self._set_columns_collapsed_now(True)
        elif valid:
            snapshot = cached[:5]                 # capture deja prise au repli : aucun cout au depart
        else:
            snapshot = self._grab_expanded_silently()   # etat deplie final, jamais affiche
        if snapshot is not None and self._snapshot_blank(snapshot):
            # Capture vide (colonnes pas encore peintes) : on ne l'anime jamais sur un fond
            # vide. Nouvelle capture, cette fois sans suspendre les mises a jour.
            self._slide_snapshot = None
            snapshot = None if collapsed else self._grab_expanded_silently(suspend=False)
            if snapshot is not None and self._snapshot_blank(snapshot):
                snapshot = None
        if snapshot is None:
            self._set_columns_collapsed_now(collapsed)
            return
        self._slide_snapshot = (*snapshot, self._columns_epoch, viewport.size(), len(targets), time.monotonic())
        left, right, x_expanded, background, limit = snapshot
        self.columns_layout.activate()
        x_collapsed = self._set_columns_anchor_x()
        follow = None
        overlay_ref = []
        if self.detail.isVisible():
            # w_expanded : largeur de l'inspecteur dans la capture (colonnes depliees) ;
            # w_collapsed : sa largeur colonnes repliees (deja appliquee ici).
            widths = self._detail_state_width
            follow = self._detail_follow(
                overlay_ref, self.detail.width(),
                widths.get(False, self.detail.width()), limit)
        overlay = _SlideOverlay(
            viewport, left, right, x_collapsed, x_expanded, background,
            0.0 if collapsed is False else 1.0, 0.0 if collapsed else 1.0, 200,
            None if collapsed else self._expand_columns_now,
            on_done=self._slide_done, limit=limit, on_progress=follow)
        overlay_ref.append(overlay)
        if follow is not None:
            follow(overlay._value)
        overlay.show()
        overlay.raise_()
        self._columns_slide = overlay

    def _slide_done(self):
        self._columns_slide = None
        self._columns_snapshot = None   # etat final change : toute capture du fondu est perimee

    def _prime_slide_snapshot(self):
        """Au survol du bouton de repli : prepare la capture de l'etat deplie."""
        if (self._project_columns_hidden or _anim_running(self._columns_slide)
                or not self.isVisible()):
            return
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        if self._project_columns_collapsed:
            # Replie : il faut deplier un instant (sans rien afficher) pour capturer
            # l'etat deplie. Differe et conditionne a un survol qui dure, pour ne
            # pas figer l'interface quand la souris ne fait que passer.
            QTimer.singleShot(60, self._prime_expanded_snapshot)
            return
        cached = self._slide_snapshot
        size = self.scroll.viewport().size()
        if (not targets or (cached is not None and cached[5] == self._columns_epoch and cached[6] == size
                            and cached[7] == len(targets) and time.monotonic() - cached[8] < 8.0)):
            return
        self.columns_layout.activate()
        snapshot = self._grab_set_columns()
        if snapshot is not None:
            self._slide_snapshot = (*snapshot, self._columns_epoch, size, len(targets), time.monotonic())

    def _prime_expanded_snapshot(self, force: bool = False):
        column = self.image_preview_columns[0] if self.image_preview_columns else None
        if (column is None or column.toggle_btn is None or not (force or column.toggle_btn.underMouse())
                or not self._project_columns_collapsed or self._project_columns_hidden
                or _anim_running(self._columns_slide)):
            return
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        size = self.scroll.viewport().size()
        cached = self._slide_snapshot
        if not targets or (cached is not None and cached[5] == self._columns_epoch and cached[6] == size
                           and cached[7] == len(targets) and time.monotonic() - cached[8] < 8.0):
            return
        snapshot = self._grab_expanded_silently()
        if snapshot is not None:
            self._slide_snapshot = (*snapshot, self._columns_epoch, size, len(targets), time.monotonic())

    def _prewarm_snapshots(self):
        """Apres 700 ms sans navigation : prepare les captures des deux boutons, en
        deux temps (chacun court) et seulement si l'utilisateur n'est pas en train
        d'agir (bouton de souris, menu, animation en cours)."""
        if (not self.isVisible() or self._project_columns_hidden or not self.image_preview_columns
                or QApplication.mouseButtons() != Qt.NoButton or QApplication.activePopupWidget() is not None
                or _anim_running(self._columns_slide)
                or _anim_running(self._columns_fade)):
            return
        self._prime_fade_snapshot()
        QTimer.singleShot(40, self._prewarm_slide)

    def _prewarm_slide(self):
        if (not self.isVisible() or self._project_columns_hidden or QApplication.mouseButtons() != Qt.NoButton
                or QApplication.activePopupWidget() is not None):
            return
        if self._project_columns_collapsed:
            self._prime_expanded_snapshot(force=True)
        else:
            self._prime_slide_snapshot()

    def _prime_fade_snapshot(self):
        """Au survol du bouton « masquer » : prepare la capture des colonnes."""
        if (self._project_columns_hidden or not self.image_preview_columns or not self.isVisible()
                or _anim_running(self._columns_fade)
                or _anim_running(self._columns_slide)):
            return
        if self._fade_snapshot_fresh():
            return
        self.columns_layout.activate()
        self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)

    @staticmethod
    def _snapshot_blank(snapshot) -> bool:
        """True si la capture des colonnes de set ne contient que la couleur de fond."""
        left, _right, _x, background, _limit = snapshot
        if left.isNull():
            return True
        image = left.toImage().scaled(48, 48, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        bg = background.rgb()
        return all((image.pixel(i, j) & 0xFFFFFF) == (bg & 0xFFFFFF)
                   for i in range(image.width()) for j in range(image.height()))

    def _grab_expanded_silently(self, suspend: bool = True):
        """Capture l'etat DEPLIE alors que les colonnes sont repliees, sans que cet etat
        ne soit jamais affiche : aucun retour a la boucle d'evenements entre le depli
        et le repli (sinon l'ecran se repeint et les colonnes « clignotent »), et les
        mises a jour sont suspendues par precaution."""
        viewport = self.scroll.viewport()
        host = self.columns_host
        if suspend:
            viewport.setUpdatesEnabled(False)
            host.setUpdatesEnabled(False)
        try:
            self._set_columns_collapsed_now(False)
            self.columns_layout.activate()
            snapshot = self._grab_set_columns()
        finally:
            self._set_columns_collapsed_now(True)
            if suspend:
                host.setUpdatesEnabled(True)
                viewport.setUpdatesEnabled(True)
        return snapshot

    def _set_columns_collapsed_now(self, collapsed: bool):
        for column in self.columns[:self._chain_expected_total()]:
            column.set_collapsed(collapsed, animate=False)
        self._fit_detail_now()
        # Largeur de l'inspecteur dans chaque etat, memorisee pour l'animation du depliage.
        self._detail_state_width[collapsed] = self.detail.width()

    def _fit_detail_width(self) -> int:
        """Largeur de l'inspecteur qui evite tout debordement (donc toute barre de
        defilement) avec les colonnes dans leur etat actuel : sa largeur voulue, reduite
        au besoin jusqu'a DETAIL_PANEL_MIN_WIDTH."""
        self.columns_layout.invalidate()   # sizeHint() est mis en cache : largeurs des colonnes qui viennent de changer
        available = self.scroll.viewport().width() - self.columns_layout.sizeHint().width()
        return max(DETAIL_PANEL_MIN_WIDTH, min(self.detail._natural_width, available))

    def _fit_detail_now(self):
        if not self.detail.isVisible() or self.detail._resizing:
            return
        width = self._fit_detail_width()
        if self.detail.width() != width:
            self.detail.setFixedWidth(width)
        self.columns_host.layout().activate()   # replace l'inspecteur (capture, limite)

    def _detail_follow(self, overlay_ref: list, w_collapsed: int, w_expanded: int, limit: int):
        """Callback de progression du depliage : l'inspecteur se redimensionne en meme
        temps que les colonnes qui arrivent contre lui, et la capture (limitee a son bord
        gauche, `limit` quand il vaut `w_expanded`) suit."""
        def follow(p: float):
            width = max(1, int(round(w_collapsed + (w_expanded - w_collapsed) * p)))
            if self.detail.width() != width:
                self.detail.setFixedWidth(width)
            overlay = overlay_ref[0] if overlay_ref else None
            if overlay is not None:
                viewport = self.scroll.viewport()
                overlay.setGeometry(QRect(0, 0, max(1, limit + w_expanded - width), viewport.height()))
        return follow

    def _expand_columns_now(self):
        self._set_columns_collapsed_now(False)

    def _set_columns_anchor_x(self) -> int:
        """Abscisse (dans le viewport) du 1er widget place APRES les colonnes de set ;
        a defaut (rien encore a droite, par exemple pendant une navigation), le
        bord droit des colonnes de set elles-memes."""
        viewport = self.scroll.viewport()
        index = self._chain_expected_total()
        if index < self.columns_layout.count():
            widget = self.columns_layout.itemAt(index).widget()
            if widget is not None and widget.isVisible():
                return max(0, widget.mapTo(viewport, QPoint(0, 0)).x())
        edge = 0
        for column in self.columns[:index]:
            if column.isVisible() and column.width() > 0:
                edge = max(edge, column.mapTo(viewport, QPoint(column.width(), 0)).x())
        return edge + self.columns_layout.spacing() if edge else 0

    def _grab_set_columns(self):
        """(colonnes de set, colonnes a droite JUSQU'A L'INSPECTEUR, abscisse de
        separation, couleur de fond, abscisse de l'inspecteur) dans l'etat actuel ;
        None si rien a animer. L'inspecteur n'est jamais capture : il ne bouge pas."""
        return self._grab_set_columns_at(self._set_columns_anchor_x())

    def _grab_set_columns_at(self, x: int):
        viewport = self.scroll.viewport()
        width, height = viewport.width(), viewport.height()
        limit = width
        if self.detail.isVisible():
            limit = min(width, max(0, self.detail.mapTo(viewport, QPoint(0, 0)).x()))
        if x <= 0 or x > limit or height <= 0:
            return None
        left = viewport.grab(QRect(0, 0, x, height))
        right = viewport.grab(QRect(x, 0, limit - x, height)) if limit - x > 0 else QPixmap()
        return left, right, x, QColor(C["window"]), limit

    def on_activated(self, path: Path):
        # Double-clic (ou "Ouvrir") : un dossier s'ouvre dans l'explorateur
        # Windows, un fichier dans son application par defaut. Une note .md d'un coffre Obsidian
        # s'ouvre dans Obsidian, SUR cette note (demande de l'utilisateur) ; a defaut, son logiciel.
        if path.is_dir():
            open_in_file_manager(path)
            return
        if path.suffix.lower() == ".md":
            import markdown_preview
            url = markdown_preview.obsidian_open_url(path)
            if url is not None:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                if QDesktopServices.openUrl(QUrl(url)):
                    return
        open_path(path)

    def _view_in_viewer(self, path: Path, column=None):
        """Double-clic sur une ligne d'une colonne (image, planche PureRef, fichier qui a un apercu,
        voir column.opens_in_viewer) : la visionneuse de l'appli (colonnes masquees, l'image au centre),
        une fois que le clic l'a montree dans l'inspecteur. L'image part de l'apercu de la LIGNE
        (pas de celui de l'inspecteur) ; le retour aux colonnes la ramene dans l'inspecteur."""
        if self._project_columns_hidden:
            return

        def go():
            source = column.preview_source(path) if column is not None else None
            if source is not None:
                pixmap, rect = source
                viewport = self.scroll.viewport()
                self._viewer_entry_source = (pixmap, QRect(viewport.mapFromGlobal(rect.topLeft()), rect.size()))
            # La visionneuse s'ouvre sur CE fichier, meme si l'inspecteur ne le montre pas : double-clic sur
            # la ligne DEJA selectionnee = son 1er clic est un re-clic, qui la deselectionne et vide
            # l'inspecteur ; la visionneuse ne trouvait alors aucun fichier et seule la miniature de la
            # ligne arrivait au centre, a sa petite taille (bug signale). Au retour, la colonne et
            # l'inspecteur reprennent l'image montree (_flush_viewer_sync).
            self._viewer_entry_path = (column, Path(path))
            try:
                self._set_columns_hidden(True)
            finally:
                self._viewer_entry_source = None
                self._viewer_entry_path = None
            if not self._project_columns_hidden:
                self.on_activated(path)          # rien a montrer (planche sans apercu...) : son logiciel

        QTimer.singleShot(0, go)

    def _entry_focus_source(self, home):
        """Depart du vol vers la visionneuse quand on vient d'un double-clic sur une ligne : la place de
        l'apercu de la ligne, avec l'image de l'inspecteur (meme fichier, meilleure definition)."""
        entry = getattr(self, "_viewer_entry_source", None)
        if entry is None:
            return home
        pixmap = home[0] if home is not None else entry[0]
        dpr = pixmap.devicePixelRatio() or 1.0
        size = QSize(round(pixmap.width() / dpr), round(pixmap.height() / dpr))
        size.scale(entry[1].size(), Qt.KeepAspectRatio)
        rect = QRect(0, 0, max(1, size.width()), max(1, size.height()))
        rect.moveCenter(entry[1].center())
        return pixmap, rect

    def _send_focus_home(self, overlay, home):
        """Vol depuis une ligne termine (image au centre, rien ne bouge) : le retour aux colonnes la
        ramenera dans l'inspecteur, sa vraie place, pas sur la ligne."""
        if overlay is self._focus_overlay and home is not None and shiboken6.isValid(overlay):
            overlay.set_geometry_target(None, QRectF(home[1]))

    def browse_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Racine du pipeline", self.root_field.text()
        )
        if chosen:
            self.root_field.setText(chosen)
            self.reload()

    # -- Presets (menu deroulant de la barre du haut, fenetre « Gerer les presets ») --

    def _choose_preset(self, name: str):
        """Menu deroulant : `name` devient le preset actif ("" = aucun) ; ses valeurs sont appliquees a
        toute l'appli et enregistrees (pipeline_settings.json)."""
        from settings_store import apply_preset
        settings = apply_preset(name)
        self._apply_settings(settings)
        # Valeurs de punaise propres au preset (browser_core.PIN_LAYOUT_KEYS) : chaque colonne reprend les siennes.
        for column in self.findChildren(Column):
            try:
                column.reload_pin_state()
            except RuntimeError:
                pass
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(settings)        # ses champs ouverts suivent le preset
        except RuntimeError:
            pass
        self._refresh_preset_ui(settings)

    def _refresh_preset_ui(self, settings: dict | None = None):
        import settings_window_v2
        settings = settings or ui_state.APPLIED_SETTINGS or load_settings()
        settings_window_v2.seed_window_look(settings)
        self.preset_picker.restyle()
        self.preset_picker.refresh(settings)

    def _open_preset_manager(self):
        from settings_presets import PresetManagerWindow
        window = self._preset_manager
        try:
            if window is not None and window.isVisible():
                window.raise_()
                window.activateWindow()
                return
        except RuntimeError:
            pass
        window = self._preset_manager = PresetManagerWindow(ui_state.APPLIED_SETTINGS or load_settings(), parent=self)
        window.presetsChanged.connect(lambda: self.preset_picker.refresh())
        window.destroyed.connect(lambda *_a: setattr(self, "_preset_manager", None))
        window.adjustSize()
        anchor = self.preset_picker.mapToGlobal(QPoint(0, self.preset_picker.height() + 6))
        window.move(anchor)
        window.show()

    def _open_settings_v2_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        menu = Menu(self)
        action = menu.addAction("Reglages v2 (comparaison de conception)")
        if menu.exec(self.btn_style.mapToGlobal(pos)) is action:
            self.open_settings_v2()

    def open_settings_v2(self):
        """Ouvre la maquette comparative (settings_window_v2.py) : le temps de
        construction et le nombre de widgets s'affichent en bas de fenetre."""
        import settings_window_v2
        existing = getattr(self, "_settings_dialog_v2", None)
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                return
        except RuntimeError:
            pass
        dialog = settings_window_v2.SettingsWindowV2(self)
        # Sections branchees (settings_window_v2.WIRED_SECTIONS) : apercu en
        # direct et enregistrement passent par les memes rappels que la
        # fenetre reelle.
        dialog.settingsChanged.connect(self._apply_settings)
        dialog.settingsSaved.connect(self._apply_settings)
        self._settings_dialog_v2 = dialog
        dialog.show()

    def open_settings(self, mode: str = "visuel"):
        """Ouvre l'une des deux fenetres de reglages : "visuel" (aspect de
        l'application, attribut `_settings_dialog` lu par browser_core pour
        les valeurs en direct) ou "general" (tout le reste). Deja ouverte :
        on la ramene au premier plan. Fermee, elle est seulement cachee et
        reutilisee a l'ouverture suivante (voir SettingsWindow.reopen) ; un
        RuntimeError (objet Qt detruit) est absorbe ici. La premiere
        construction est longue et traite des evenements : le drapeau
        `_settings_opening` ignore tout appel pendant ce temps."""
        if not SETTINGS_V1_ENABLED:
            self.open_settings_v2()
            return
        if getattr(self, "_settings_opening", False):
            return
        attr = "_settings_dialog_general" if mode == "general" else "_settings_dialog"
        existing = getattr(self, attr, None)
        if existing is not None:
            try:
                still_visible = existing.isVisible()
            except RuntimeError:
                still_visible = False
            if still_visible:
                existing.raise_()
                existing.activateWindow()
                return
        self._settings_opening = True
        self.btn_settings.setEnabled(False)
        self.btn_style.setEnabled(False)
        try:
            if existing is not None:
                try:
                    stale = existing.is_stale()
                except RuntimeError:
                    stale = True
                if stale:
                    # L'habillage a change sur le disque depuis sa construction
                    # (reopen() ne le rejouerait pas) : on la reconstruit.
                    try:
                        existing.deleteLater()
                    except RuntimeError:
                        pass
                    existing = None
            if existing is not None:
                # Fenetre deja construite, simplement cachee a sa fermeture
                # (pas de WA_DeleteOnClose) : la reconstruire coute plusieurs
                # secondes, la remettre a zero quelques dizaines de ms.
                try:
                    existing.reopen()
                    existing.show()
                    existing.raise_()
                    existing.activateWindow()
                    return
                except RuntimeError:   # objet Qt detruit entre-temps
                    pass
            dialog = SettingsWindow(self, mode=mode)
            # Non modale : la fenetre principale reste interactive et se
            # met a jour en direct pendant qu'on ajuste les parametres.
            dialog.settingsChanged.connect(self._apply_settings)
            dialog.settingsSaved.connect(self._apply_settings)
            setattr(self, attr, dialog)
            dialog.show()
        finally:
            self._settings_opening = False
            self.btn_settings.setEnabled(True)
            self.btn_style.setEnabled(True)

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
        if self._last_style_key is None:
            # Premier changement : la reference est l'etat DEJA applique (sans
            # elle, le tout premier cran de n'importe quel slider declenchait
            # une reconstruction globale de plus d'une seconde).
            self._last_style_key = self._style_key(load_settings())
        prev_geometry = {title: (conf["height"], conf["spacing"]) for title, conf in COLUMN_SETTINGS.items()}
        prev_omissions = (GLOBAL_OMIT_DIR_NAMES.copy(), GLOBAL_OMIT_FILE_NAMES.copy(),
                          GLOBAL_OMIT_FILE_EXTENSIONS.copy())
        apply_all_settings(settings)
        picker = getattr(self, "preset_picker", None)
        if picker is not None:
            picker.restyle()                        # habillage des reglages (palette M) : suit
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
        style_key = self._style_key(settings)
        if style_key != self._last_style_key:
            self._last_style_key = style_key
            self._pending_stylesheet_rebuild = True
            # Relance a chaque changement (et non plus toutes les 250 ms) : la reconstruction coute ~430 ms
            # (toutes les fenetres repolies) ; faite PENDANT un glisser de couleur, elle le figeait (signale).
            self._stylesheet_rebuild_timer.start()
        self.refresh_colors(rebuild_stylesheet=False)
        self.refresh_chrome_sizes()
        self._apply_native_frame()
        self._apply_viewer_settings()
        import settings_element_style            # styles propres des elements : pas effaces par le restylage
        settings_element_style.reapply_soon(self, ui_state.APPLIED_SETTINGS)

    @staticmethod
    def _style_key(settings: dict) -> tuple:
        """Ce que build_stylesheet lit reellement : si elle ne bouge pas, la
        feuille de style globale n'a pas a etre reconstruite."""
        colors = settings.get("colors") or {}
        return (
            tuple(colors.get(k, C[k]) for k in STYLESHEET_COLOR_KEYS),
            settings.get("button_radius"),
            settings.get("button_frame"),
            settings.get("input_radius"),
            settings.get("input_frame"),
            settings.get("table_radius"),
        )

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
        if QApplication.mouseButtons() != Qt.NoButton:
            # Geste en cours (curseur de couleur tenu) : on attend qu'il soit relache.
            self._stylesheet_rebuild_timer.start()
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
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_style, self.btn_settings):
            btn.setFixedHeight(scaled(24))
        self.btn_settings.setFixedWidth(scaled(28))
        self.btn_style.setFixedWidth(scaled(28))

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.titlebar.title_label.setFont(role_font("titles", 11, 400, tracking=0.01))
        self.titlebar.title_label.setStyleSheet(f"color: {role_color('titles', C['label'])}; background: transparent;")
        self.root_label.setFont(role_font("app", 10, 600, tracking=0.8, caps=True))
        self.root_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.root_field.setFont(role_font("info", 12, 400))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place, self.btn_style, self.btn_settings):
            btn.setFont(role_font("buttons", 11, 500))
        for btn in (self.btn_browse, self.btn_reload, self.btn_last_place):
            btn.setStyleSheet(f"color: {role_color('buttons', '#c4cacf')};")
        self.btn_settings.set_colors(role_color("buttons", "#c4cacf"), C["text"])
        self.btn_style.set_colors(role_color("buttons", "#c4cacf"), C["text"])
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
        _set_qss(self.central,
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {ui_state.WINDOW_RADIUS}px; }}"
        )
        _set_qss(self.columns_host, f"#ColumnsHost {{ background: {C['window']}; }}")
        _set_qss(self.titlebar, f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        for btn in (self.titlebar.btn_min, self.titlebar.btn_max, self.titlebar.btn_close):
            btn.set_colors(C["label"], C["text"])
        _set_qss(self.topbar, f"#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['border']}; }}")
        _set_qss(self.statusbar, f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}")
        for column in self.columns:
            column.refresh_colors()
        for column in self.group_columns:
            column.refresh_colors()
        for column in self.image_preview_columns:
            column.refresh_colors()
        self.detail.refresh_colors()
        self.refresh_chrome_fonts()

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


def main():
    _install_qt_message_filter()
    settings = load_settings(startup=True)      # le preset par defaut devient le preset actif
    apply_all_settings(settings)
    root = Path(settings["root_path"])
    _config.ROOT = root
    migrate_cache_names()
    # Menage du cache en arriere-plan : ni images inutiles ni apercus de fichiers supprimes.
    threading.Thread(target=sweep_preview_cache, name="preview-cache-sweep", daemon=True).start()

    # Le winId() d'une fenetre enfant (reglages, config des colonnes : voir
    # apply_dwm_frame) rendait natifs ses « freres », dont #CentralFrame : un
    # cadre natif dans la fenetre translucide n'est plus recompose image par
    # image et les animations des colonnes sautaient des l'ouverture des
    # reglages (tests/_probe_screen_anim.py).
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    app = QApplication(sys.argv)
    apply_style(app)
    _install_context_menus()
    window = PipelineBrowser(root)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
