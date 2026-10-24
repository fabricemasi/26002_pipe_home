import json
import math
import os
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMenu
from PySide6.QtCore import (
    QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    INSPECTOR_TITLE,
    column_gap,
    font,
    role_color,
    role_font,
    scaled,
    resolve_color_ref,
    column_frame_style,
    column_header_qss,
    column_padding_for,
    column_style_for,
)
import ui_state
from config import (
    ABC_EXTENSIONS,
    ABR_EXTENSIONS,
    BLEND_EXTENSIONS,
    DATA_DIR,
    DWG_EXTENSIONS,
    DXF_EXTENSIONS,
    EXR_EXTENSIONS,
    FBX_EXTENSIONS,
    CUBE_EXTENSIONS,
    RAW_EXTENSIONS,
    HDR_EXTENSIONS,
    HOUDINI_SCENE_EXTENSIONS,
    FONT_EXTENSIONS,
    ILLUSTRATOR_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MAYA_SCENE_EXTENSIONS,
    OBJ_EXTENSIONS,
    PREVIEW_MAX_HEIGHT,
    PREVIEW_MIN_HEIGHT,
    PDF_EXTENSIONS,
    PSD_EXTENSIONS,
    PUR_PREVIEW_EXTENSIONS,
    RENDERABLE_3D_EXTENSIONS,
    TEXT_PREVIEW_EXTENSIONS,
    TEXT_PREVIEW_PANEL_HEIGHT,
    TX_EXTENSIONS,
    VIDEO_EXTENSIONS,
    VIDEO_PLAYBACK_ENABLED,
    _MANUAL_3D_PREVIEW_MODE,
    _MANUAL_3D_PREVIEW_REQUESTS,
    _STALE_PREVIEW_PATHS,
)
from previews import (
    TURNTABLE_EXTENSIONS,
    TURNTABLE_FRAME_COUNT,
    _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES,
    _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM,
    _IdlePreviewScheduler,
    _PREVIEW_DECODE_MANAGER,
    _RenderLogTable,
    _bounded_cache_set,
    _cache_file_preview,
    _cached_file_image_pixmap,
    _file_image_column_cache,
    _file_image_high_cache,
    _is_preview_protected,
    _read_preview_pixmap,
    _read_render_log_entries,
    _render_log_line,
    _render_log_path,
    _set_preview_protected,
    _turntable_frames,
    _write_render_log,
    file_image_pixmap,
)
from settings_store import (
    M,
    _sync_dynamic_M,
    load_settings,
)
from settings_theme import _set_text_role
from settings_widgets import (
    Menu, menu_row,
    _MiniSlider,
    _Toggle,
    _radius_dict,
    _radius_shrink,
    _sync_toggle_style,
)
from browser_core import (
    DETAIL_PANEL_MAX_WIDTH,
    DETAIL_PANEL_MIN_WIDTH,
    _hide_resize_width,
    _persist_detail_panel_width,
    _resolve_font_family,
    _show_resize_width,
    count_entries,
    entry_is_dir,
    entry_mtime,
    entry_size,
    listed_count,
    human_size,
)
from capture_widgets import (
    _ColumnCard,
    _RoundedCornersEffect,
)
from preview_column import (
    _PUR_EXPORT_POOL,
    _PureRefExportTask,
    pur_image_files,
    pur_embedded_image_ranges,
    pur_file_major_version,
    read_pur_embedded_image,
    read_pur_exported_image,
    read_text_preview,
)
import markdown_preview
from previews import (
    delete_preview_cache,
    ai_has_pdf_content,
    pdf_page_count,
    _render_pdf_page,
)
from previews import (
    _file_image_cache_path,
    _find_stale_preview_cache,
)
from browser_core import (
    reveal_in_file_manager,
)


# ==========================================================================
# Panneau de details
# ==========================================================================

class _TurntableSlider(_MiniSlider):
    """Curseur de lecture qui reprend le style Slider des paramètres."""

    def _apply_size(self):
        _MiniSlider._apply_size(self)
        height = self.height()
        self.setMinimumWidth(scaled(48))
        self.setMaximumWidth(16_777_215)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

class _VideoView(QWidget):
    """Affichage video SANS fenetre native : QVideoWidget (backend ffmpeg) cree une
    surface de rendu native qui rend natifs ses ancetres (#CentralFrame) des que la
    lecture demarre — les animations des colonnes ne s'affichaient plus qu'en une image,
    comme avec le winId() des reglages (voir AGENTS.md). On peint donc les images du
    QVideoSink nous-memes, dans un widget ordinaire."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._on_frame)

    def _on_frame(self, frame):
        if self.isVisible() and frame.isValid():
            self._image = frame.toImage()
            self.update()

    def hideEvent(self, event):
        self._image = QImage()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if not self._image.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            scaled = self._image.size().scaled(self.size(), Qt.KeepAspectRatio)
            target = QRect(QPoint(0, 0), scaled)
            target.moveCenter(self.rect().center())
            painter.drawImage(target, self._image)
        painter.setPen(QColor("#282c30"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class DetailPanel(QWidget):

    FIELDS = ["kind", "size", "modified", "proxy_source", "full_source"]
    # Double-clic sur l'apercu (image, turntable ou video) : meme effet que le
    # bouton « masquer les colonnes » (voir PipelineBrowser).
    preview_double_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # objectName + selecteur ID (voir la meme remarque pour #CentralFrame
        # dans PipelineBrowser).
        self.setObjectName("DetailPanel")
        # self ne peint plus rien lui-meme desormais (voir self.card
        # ci-dessous, EXACTEMENT le meme principe que Column.card) — voir la
        # remarque de l'utilisateur, "la colonne inspecteur est differente
        # des autres, je veux exactement le meme style, parametres par
        # parametres" : l'inspecteur suit maintenant Colonnes > Colonnes/
        # Entetes (padding/bordure/rayon par cote, fond, rayon d'entete...)
        # au lieu d'un simple filet de gauche fixe et d'un fond fige sur
        # C['void'] — voir INSPECTOR_TITLE (colonne "virtuelle", toujours
        # generale : aucun onglet de surcharge dedie, comme Logiciels/
        # Contenu).
        self.setStyleSheet("#DetailPanel { background: transparent; }")
        # Largeur fixe par defaut (et non un stretch qui la ferait grandir
        # avec la fenetre) : un inspecteur qui s'etire jusqu'a occuper tout
        # l'espace restant laisse un vide enorme autour de son contenu des
        # que la fenetre est large. Restee ajustable a la souris (voir
        # mousePressEvent) comme n'importe quelle colonne, via ce meme filet
        # de gauche.
        self.setFixedWidth(ui_state.DETAIL_PANEL_WIDTH)
        # Largeur « voulue » (choisie a la main) : la largeur reelle peut etre
        # reduite temporairement pour laisser la place aux colonnes (voir
        # PipelineBrowser._fit_detail_width).
        self._natural_width = ui_state.DETAIL_PANEL_WIDTH
        self.setMouseTracking(True)
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0

        # En-tete identique dans l'esprit a celui des colonnes (voir Column) :
        # meme hauteur/fond/police, pour que l'inspecteur se lise comme une
        # colonne de plus plutot que comme un panneau a part. Le badge a
        # droite reprend le type de l'element selectionne (voir show_path).
        # header (exterieur, hauteur/padding EFFECTIFS, voir refresh_header)
        # enveloppe header_fill (interieur, fond/rayon/cadre CONFIGURABLE de
        # column_header_qss) — meme separation exterieur/interieur que
        # Column.header, voir sa remarque.
        header = QWidget()
        header.setObjectName("DetailHeaderOuter")
        header.setFixedHeight(scaled(ui_state.HEADER_HEIGHT))
        self.header = header
        header_outer_layout = QVBoxLayout(header)
        pad = scaled(ui_state.HEADER_PADDING, 0)   # 0 = valeur reglee valide (voir scaled)
        header_outer_layout.setContentsMargins(pad, pad, pad, pad)
        header_outer_layout.setSpacing(0)

        header_fill = QWidget()
        header_fill.setObjectName("DetailHeader")
        header_fill.setStyleSheet(column_header_qss("DetailHeader", INSPECTOR_TITLE))
        self.header_fill = header_fill
        self.header_title = QLabel("Inspecteur")
        self.header_title.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.header_title.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        self.badge = QLabel("")
        self.badge.setFont(role_font("info", 9, 600, tracking=0.6, caps=True))
        self.badge.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        header_layout = QHBoxLayout(header_fill)
        self._header_layout = header_layout
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.header_title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.badge)
        header_outer_layout.addWidget(header_fill)

        self.name = QLabel("")
        self.name.setFont(role_font("folders", 12, 600, tracking=0.12))
        self.name.setStyleSheet(f"color: {role_color('folders', C['text'])}; background: transparent;")
        self.name_row = QWidget()
        name_row_layout = QHBoxLayout(self.name_row)
        name_row_layout.setContentsMargins(0, 0, 0, 0)
        name_row_layout.setSpacing(6)
        name_row_layout.addWidget(self.name, 1)
        _sync_toggle_style(ui_state.APPLIED_SETTINGS or load_settings())
        self.render_protection_toggle = _Toggle(
            False, style_override="toggle1", show_label=False, parent=self
        )
        self.render_protection_toggle.setToolTip(
            "Protège cet aperçu contre les remplacements automatiques"
        )
        self.render_protection_toggle.hide()
        self.render_protection_toggle.toggled.connect(self._on_render_protection_toggled)
        self.open_render_log_button = QPushButton("Ouvrir le journal")
        self.open_render_log_button.setToolTip("Ouvrir le journal des rendus automatiques")
        self.open_render_log_button.setCursor(Qt.PointingHandCursor)
        self.open_render_log_button.setFixedHeight(scaled(24))
        self.open_render_log_button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            f"border-radius: 3px; padding: 0 7px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
        )
        self.open_render_log_button.clicked.connect(self.open_preview_render_log)
        name_row_layout.addWidget(self.open_render_log_button)

        self.pur_navigation = QWidget()
        pur_nav_layout = QHBoxLayout(self.pur_navigation)
        pur_nav_layout.setContentsMargins(0, 0, 0, 0)
        pur_nav_layout.setSpacing(6)
        self.pur_previous_button = QPushButton("‹")
        self.pur_next_button = QPushButton("›")
        for button in (self.pur_previous_button, self.pur_next_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(scaled(28), scaled(24))
            button.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; font-size: 16px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
                f"QPushButton:disabled {{ color: {C['dim']}; }}"
            )
        self.pur_image_counter = QLabel("")
        self.pur_image_counter.setAlignment(Qt.AlignCenter)
        self.pur_image_counter.setStyleSheet(
            f"color: {role_color('info', '#aab1b6')}; background: transparent;"
        )
        pur_nav_layout.addStretch(1)
        pur_nav_layout.addWidget(self.pur_previous_button)
        pur_nav_layout.addWidget(self.pur_image_counter)
        pur_nav_layout.addWidget(self.pur_next_button)
        pur_nav_layout.addStretch(1)
        self.pur_navigation.hide()
        self.pur_previous_button.clicked.connect(lambda: self._navigate_pur_image(-1))
        self.pur_next_button.clicked.connect(lambda: self._navigate_pur_image(1))

        self.well = QFrame()
        self.well.setObjectName("PreviewWell")
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.well.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.well.setStyleSheet(self._well_qss())
        self._preview_pixmap: QPixmap | None = None
        self._preview_request_path: str | None = None
        self._current_path: str | None = None
        self._pur_image_path: str | None = None
        self._pdf_path: str | None = None
        self._pdf_page = 0
        self._pdf_pages = 0
        self._pdf_zoom = 1.0
        self._pdf_view = [0.0, 0.0]  # coin haut-gauche de la zone visible (fractions de la page)
        self._pdf_wheel = 0
        self._pdf_drag = None
        self._pur_image_ranges: list[tuple[int, int, str]] = []
        self._pur_exported_images: list[str] = []
        self._pur_export_task: _PureRefExportTask | None = None
        self._pur_image_index = 0
        # (planche, rang) demande par la visionneuse (image regardee) : applique des que cette image existe.
        self._pur_wanted: tuple | None = None
        self._preview_generation_paths: set[str] = set()
        self._auto_preview_paths: set[str] = set()
        self._auto_preview_log_count = 0
        self.well_label = QLabel(self.well)
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        # Clic droit sur l'apercu (image, turntable ou video) : voir
        # _show_preview_context_menu.
        for preview_widget in (self.well, self.well_label):
            preview_widget.installEventFilter(self)
            preview_widget.setContextMenuPolicy(Qt.CustomContextMenu)
            preview_widget.customContextMenuRequested.connect(
                lambda pos, w=preview_widget: self._show_preview_context_menu(w.mapToGlobal(pos)))
        self._turntable_frame_paths = []
        self._turntable_frame_index = 0
        self._preview_media_preferences = {}
        self._preview_render_modes = {}
        self._turntable_timer = QTimer(self)
        self._turntable_timer.setInterval(83)
        self._turntable_timer.timeout.connect(self._advance_turntable)
        self.preview_dimensions_value = QLabel("—")
        self.preview_dimensions_value.setObjectName("PreviewInfoValue")
        self.preview_dimensions_value.setWordWrap(True)
        self.preview_log = _RenderLogTable(self.well)
        self.preview_log.setFrameShape(QFrame.NoFrame)
        self.preview_log.setFont(font(9, 400, mono=True, smoothing="none"))
        self.preview_log.setStyleSheet(
            "QTableWidget { background: #1a1c1e; alternate-background-color: #24272a; color: #00ff00; border: none; gridline-color: #34383c; }"
            "QHeaderView::section { background: #303438; color: #ddd; padding: 4px; border: 1px solid #45494d; }"
        )
        well_layout = QVBoxLayout(self.well)
        well_layout.setContentsMargins(0, 0, 0, 0)
        well_layout.setSpacing(0)
        well_layout.addWidget(self.well_label)
        well_layout.addWidget(self.preview_log)
        self.preview_log.hide()
        self.preview_progress = QWidget(self.well)
        progress_layout = QVBoxLayout(self.preview_progress)
        progress_layout.setContentsMargins(18, 14, 18, 14)
        progress_layout.setSpacing(8)
        self.preview_progress_label = QLabel("Génération de l’aperçu…")
        self.preview_progress_label.setAlignment(Qt.AlignCenter)
        self.preview_progress_label.setStyleSheet(
            f"color: {role_color('info', '#aab1b6')}; background: transparent; border: none;"
        )
        self.preview_progress_bar = QProgressBar()
        self.preview_progress_bar.setRange(0, 0)
        self.preview_progress_bar.setTextVisible(False)
        self.preview_progress_bar.setFixedHeight(5)
        self.preview_progress_bar.setStyleSheet(
            "QProgressBar { background: #282c30; border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background: #7fa8cf; border-radius: 2px; }"
        )
        progress_layout.addWidget(self.preview_progress_label)
        progress_layout.addWidget(self.preview_progress_bar)
        self.preview_progress.hide()
        well_layout.addWidget(self.preview_progress)
        _PREVIEW_DECODE_MANAGER.started.connect(self._on_preview_generation_started)
        _PREVIEW_DECODE_MANAGER.progress.connect(self._on_preview_generation_progress)
        _PREVIEW_DECODE_MANAGER.ready.connect(self._on_3d_preview_ready)
        _PREVIEW_DECODE_MANAGER.turntable_ready.connect(self._on_turntable_ready)
        try:
            import lightroom_bridge
            lightroom_bridge._signal_bus().profile_ready.connect(self._on_lightroom_profile_ready)
            lightroom_bridge._signal_bus().sources_ready.connect(self._on_lightroom_sources)
        except (ImportError, OSError, ValueError):
            pass

        # Extrait de contenu pour les fichiers texte/code (voir
        # TEXT_PREVIEW_EXTENSIONS/read_text_preview) : remplace le "well"
        # image le temps de l'affichage, jamais les deux a la fois (voir
        # show_path). Widget distinct plutot qu'un simple QLabel dans
        # `well` : un QPlainTextEdit sait faire defiler un texte plus long
        # que la hauteur disponible, ce qu'un QLabel ne fait pas.
        self.text_preview = QPlainTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setFrameShape(QFrame.NoFrame)
        self.text_preview.setFixedHeight(TEXT_PREVIEW_PANEL_HEIGHT)
        self.text_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_preview.setFont(font(10, 400, mono=True))
        self.text_preview.setStyleSheet(
            f"QPlainTextEdit {{ background: {C['well']}; color: {role_color('info', '#aab1b6')};"
            f" border: 1px solid #282c30; padding: 6px; }}"
        )
        self.text_preview.hide()

        # Lecture (silencieuse, en boucle) des videos selectionnees : plutot
        # que la frame figee de file_image_pixmap (toujours utilisee comme
        # vignette dans les colonnes, ou tant que la lecture n'a pas
        # demarre). Widget distinct du "well" : QVideoWidget a besoin de sa
        # propre surface de rendu, jamais affiche en meme temps que well/
        # text_preview (voir show_path/_stop_video).
        self.video_widget = _VideoView()
        self.video_widget.installEventFilter(self)
        self._preview_widgets = (self.well, self.well_label, self.video_widget)
        self.video_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_widget.customContextMenuRequested.connect(
            lambda pos: self._show_preview_context_menu(self.video_widget.mapToGlobal(pos)))
        self.video_widget.hide()
        self._video_player = QMediaPlayer(self)
        self._video_audio = QAudioOutput(self)
        self._video_audio.setMuted(True)
        self._video_player.setAudioOutput(self._video_audio)
        self._video_player.setVideoSink(self.video_widget.sink)
        self._video_player.setLoops(QMediaPlayer.Loops.Infinite)

        self.values: dict[str, QLabel] = {}
        for key in self.FIELDS:
            value = QLabel("")
            value.setObjectName("PreviewInfoValue")
            value.setWordWrap(True)
            self.values[key] = value
        self.preview_stale_badge = QLabel("PÉRIMÉ")
        self.preview_stale_badge.setFont(role_font("info2", 8, 700))
        self.preview_stale_badge.setToolTip("Aperçu conservé en attendant sa régénération")
        self.preview_stale_badge.setStyleSheet(
            "color: #1d1608; background: #e5b85c; border-radius: 2px; padding: 1px 5px;"
        )
        self.preview_stale_badge.hide()
        self.preview_origin_badge = QLabel("")
        self.preview_origin_badge.setFont(role_font("info2", 8, 700))
        self.preview_origin_badge.hide()
        self.preview_profile_badge = QLabel("")
        self.preview_profile_badge.setFont(role_font("info2", 8, 700))
        self.preview_profile_badge.hide()
        # Tableau des informations = un VRAI tableau des reglages (style commun des tableaux, clic droit
        # > Override settings pour lui donner le sien) : Parametre | Valeur, une ligne par information
        # (Type, Taille, Modifie, Dimensions), puis la ligne des boutons d'apercu sur toute la largeur.
        self.preview_info_table = self._build_info_table()
        self.preview_controls_cell = QWidget()
        self.preview_controls_cell.setStyleSheet("background: transparent;")
        self.preview_meta_badges = QWidget(self.preview_controls_cell)
        meta_badges_layout = QHBoxLayout(self.preview_meta_badges)
        meta_badges_layout.setContentsMargins(0, 0, 0, 0)
        meta_badges_layout.setSpacing(3)
        meta_badges_layout.addWidget(self.preview_origin_badge)
        meta_badges_layout.addWidget(self.preview_profile_badge)
        # Cellule des boutons : UNE ligne compacte (voir _reflow_preview_controls : elle se range sur
        # plusieurs lignes seulement quand le tableau est trop etroit).
        controls_layout = QGridLayout(self.preview_controls_cell)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setHorizontalSpacing(3)
        controls_layout.setVerticalSpacing(3)
        self._preview_controls_layout = controls_layout
        self.preview_media_row = QWidget(self.preview_controls_cell)
        media_layout = QHBoxLayout(self.preview_media_row)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(2)
        self.preview_media_group = QButtonGroup(self)
        self.preview_media_group.setExclusive(True)
        self.preview_image_button = QPushButton("Image")
        self.preview_turntable_button = QPushButton("Turntable")
        self.lightroom_preview_button = QPushButton("Créer l’aperçu Lightroom")
        self.lightroom_preview_button.setToolTip("Demander à Lightroom de recalculer l’aperçu de cette photo")
        self.lightroom_preview_button.setCursor(Qt.PointingHandCursor)
        self.preview_media_buttons = {
            "image": self.preview_image_button,
            "turntable": self.preview_turntable_button,
        }
        media_button_style = (
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            "border-radius: 3px; padding: 0 6px; font-size: 9px; min-height: 18px; max-height: 18px; }"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
            f"QPushButton:checked {{ background: {M['accent']}; color: {M['accent_fg']}; border-color: {M['accent_border']}; }}"
        )
        for media, button in self.preview_media_buttons.items():
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(media_button_style)
            self.preview_media_group.addButton(button)
            button.clicked.connect(lambda _checked=False, selected=media: self._select_preview_media(selected))
            media_layout.addWidget(button)
        self.lightroom_preview_button.setStyleSheet(media_button_style)
        self.lightroom_preview_button.clicked.connect(self._request_lightroom_preview)
        self.preview_media_buttons["image"].setChecked(True)
        self.render_action_buttons = {}
        render_button_style = (
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            "border-radius: 3px; padding: 0 6px; font-size: 9px; min-height: 18px; max-height: 18px; }"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
            f"QPushButton:disabled {{ color: {C['dim']}; }}"
        )
        for media, mode, title in (("image", "low", "Image LOW"), ("image", "high", "Image HIGH"),
                                   ("turntable", "low", "Turntable LOW"),
                                   ("turntable", "high", "Turntable HIGH")):
            button = QPushButton(title, self.preview_controls_cell)
            button.setToolTip(f"Calculer {media} {mode.upper()} POLY")
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(render_button_style)
            button.clicked.connect(lambda _checked=False, m=media, r=mode: self._render_preview_media(m, r))
            self.render_action_buttons[(media, mode)] = button
        self.render_protection_label = QLabel("PROTÉGER LE RENDU")
        self.render_protection_label.setObjectName("PreviewInfoHeading")
        self.render_protection_label.setFont(role_font("info", 8, 600))
        self.render_protection_label.setWordWrap(False)
        self.preview_protection_widget = QWidget(self.preview_controls_cell)
        protection_row = QHBoxLayout(self.preview_protection_widget)
        protection_row.setContentsMargins(0, 0, 0, 0)
        protection_row.setSpacing(3)
        protection_row.addWidget(self.render_protection_toggle)
        protection_row.addWidget(self.render_protection_label)
        self.preview_stale_badge.setParent(self.preview_controls_cell)
        self._preview_controls_items = [
            self.preview_media_row,
            self.lightroom_preview_button,
            self.render_action_buttons[("image", "low")], self.render_action_buttons[("image", "high")],
            self.render_action_buttons[("turntable", "low")], self.render_action_buttons[("turntable", "high")],
            self.preview_protection_widget, self.preview_stale_badge, self.preview_meta_badges,
        ]
        self._preview_controls_wide = None
        self._reflow_preview_controls(True)
        self._attach_controls_row()

        self.turntable_controls = QWidget()
        turntable_controls_layout = QHBoxLayout(self.turntable_controls)
        turntable_controls_layout.setContentsMargins(0, 2, 0, 0)
        turntable_controls_layout.setSpacing(5)
        self.turntable_play_button = QPushButton("▶")
        self.turntable_play_button.setToolTip("Lecture / pause du turntable")
        self.turntable_play_button.clicked.connect(self._toggle_turntable_playback)
        self.turntable_stop_button = QPushButton("■")
        self.turntable_stop_button.setToolTip("Arrêter et revenir à la première image")
        self.turntable_stop_button.clicked.connect(self._stop_turntable_playback)
        self.turntable_previous_button = QPushButton("‹")
        self.turntable_previous_button.setToolTip("Image précédente")
        self.turntable_previous_button.clicked.connect(lambda: self._step_turntable(-1))
        self.turntable_slider = _TurntableSlider(0, TURNTABLE_FRAME_COUNT - 1, 0, width=220)
        self.turntable_slider.setToolTip("Faire défiler les images du turntable")
        self.turntable_slider.valueChanged.connect(self._on_turntable_slider_changed)
        self.turntable_next_button = QPushButton("›")
        self.turntable_next_button.setToolTip("Image suivante")
        self.turntable_next_button.clicked.connect(lambda: self._step_turntable(1))
        self.turntable_counter = QLabel("— / 72")
        self.turntable_counter.setAlignment(Qt.AlignCenter)
        self.turntable_counter.setMinimumWidth(scaled(48))
        self.turntable_counter.setStyleSheet(f"color: {role_color('info', '#aab1b6')}; background: transparent;")
        self.turntable_render_button = QPushButton("↻")
        self.turntable_render_button.setToolTip("Recalculer les 72 images du turntable")
        self.turntable_render_button.clicked.connect(self._render_turntable)
        control_button_style = (
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            "border-radius: 3px; padding: 0; min-width: 26px; min-height: 24px; }"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
            f"QPushButton:disabled {{ color: {C['dim']}; }}"
        )
        for button in (self.turntable_play_button, self.turntable_stop_button,
                       self.turntable_previous_button, self.turntable_next_button,
                       self.turntable_render_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(control_button_style)
        turntable_controls_layout.addWidget(self.turntable_play_button)
        turntable_controls_layout.addWidget(self.turntable_stop_button)
        turntable_controls_layout.addWidget(self.turntable_previous_button)
        turntable_controls_layout.addWidget(self.turntable_slider, 1)
        turntable_controls_layout.addWidget(self.turntable_next_button)
        turntable_controls_layout.addWidget(self.turntable_counter)
        turntable_controls_layout.addWidget(self.turntable_render_button)
        self.turntable_controls.hide()
        self._set_preview_controls_visible(False)
        self._apply_preview_table_style()

        content = QVBoxLayout()
        self._content_layout = content
        content.setContentsMargins(16, 14, 16, 14)
        content.setSpacing(8)
        content.addWidget(self.name_row)
        content.addWidget(self.preview_info_table)
        content.addWidget(self.pur_navigation)
        content.addWidget(self.well, 1)
        content.addWidget(self.turntable_controls)
        content.addWidget(self.text_preview)
        content.addWidget(self.video_widget, 1)
        # Ressort final (facteur 0) : il ne prend la place que quand aucun element extensible
        # (apercu, video, note) n'est affiche — sans selection, le tableau reste donc en haut.
        content.addStretch(0)

        # self.card/self._inner : MEME structure a 2 niveaux que Column.card/
        # Column._content (voir leurs remarques respectives) — self.card
        # porte le fond/la bordure/le rayon REELS (_ColumnCard, peints a la
        # main via _paint_bordered_rect, voir refresh_colors), self._inner
        # (entete + contenu) est decoupe a sa silhouette arrondie EXACTE
        # (double QGraphicsEffect, voir _update_card_mask) — necessaire pour
        # les MEMES raisons que Column (Qt ne clippe jamais automatiquement
        # des enfants au rayon QSS de leur parent).
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._inner_effect = _RoundedCornersEffect(self._inner)
        self._inner.setGraphicsEffect(self._inner_effect)
        inner_layout = QVBoxLayout(self._inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addWidget(header)
        inner_layout.addLayout(content, 1)

        self.card = _ColumnCard()
        self.card.setObjectName("DetailPanelCard")
        self._card_effect = _RoundedCornersEffect(self.card)
        self.card.setGraphicsEffect(self._card_effect)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste a l'epaisseur de bordure
        card_layout.setSpacing(0)
        card_layout.addWidget(self._inner)
        self._card_layout = card_layout

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste au Padding
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.card)
        self._outer_layout = outer_layout

        # self.card couvre TOUTE la surface de self (outer_layout, marges a
        # 0, voir plus haut) : sans ceci, la bordure GAUCHE de redimensionnement
        # (voir mousePressEvent/mouseMoveEvent ci-dessous) n'etait JAMAIS
        # accessible a la souris — self.card (et self._inner/header par-
        # dessus) interceptait tout mouvement/clic AVANT qu'ils n'atteignent
        # self — voir la remarque de l'utilisateur, "la selection du bord de
        # la colonne inspecteur est toujours aussi peinible a selectionner
        # pour la redimension". MEME mecanique que PreviewColumn.eventFilter
        # (voir sa docstring de tete, MEME correctif deja applique la-bas).
        self.card.setMouseTracking(True)
        self.card.installEventFilter(self)
        self.header.setMouseTracking(True)
        self.header.installEventFilter(self)

        # Une seule surface reçoit sur toute sa hauteur le survol ET le clic,
        # y compris au-dessus des enfants interactifs de l'inspecteur.
        self._resize_handle = QLabel("⋮", self)
        self._resize_handle.setObjectName("InspectorResizeHandle")
        self._resize_handle.setAlignment(Qt.AlignCenter)
        self._resize_handle.setToolTip("Glisser pour redimensionner l’inspecteur")
        self._resize_handle.setStyleSheet(
            "#InspectorResizeHandle { background: transparent; color: #727980; font-size: 18px; }"
            "#InspectorResizeHandle:hover { background: rgba(125, 150, 170, 45); color: #d7e2eb; }")
        self._resize_handle.setMouseTracking(True)
        self._resize_handle.setCursor(Qt.SizeHorCursor)
        self._resize_handle.installEventFilter(self)
        self._resize_handle.setGeometry(0, 0, scaled(16), self.height())
        self._resize_handle.raise_()

        self.clear()
        self.refresh_header()
        self.refresh_colors()

    def refresh_header(self):
        """Reapplique hauteur/padding de l'entete + bordure/padding du cadre
        — MEME logique que Column.refresh_header (voir sa docstring),
        applique ici a l'inspecteur pour la premiere fois — voir la
        remarque de l'utilisateur, "la colonne inspecteur est differente
        des autres, je veux exactement le meme style, parametres par
        parametres". Style EFFECTIF via INSPECTOR_TITLE, TOUJOURS general
        (aucun onglet de surcharge dedie, comme Logiciels/Contenu — voir
        app_style.column_style_for)."""
        s = column_style_for(INSPECTOR_TITLE)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", ui_state.HEADER_HEIGHT))
        padding = int(s.get("header_padding", ui_state.HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)   # 0 = valeur reglee valide (voir scaled)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/taille du titre (voir Column.refresh_header,
        # MEME logique/MEMES cles — bug corrige au passage, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette methode n'appliquait jusqu'ici QUE
        # hauteur/padding/bordure, jamais la police/couleur du titre (voir
        # refresh_fonts, qui la fixait a la couleur GENERIQUE role_color
        # sans jamais lire de surcharge) — desormais l'onglet Colonnes >
        # Inspecteur > Entetes > "Couleur du titre" fonctionne enfin ici.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.header_title.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.header_title.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")

        # Bordure du CADRE : reserve, sur CHAQUE cote EFFECTIVEMENT peint, la
        # meme epaisseur que celle reellement dessinee la (voir Column.
        # refresh_header, MEME raison — sinon l'entete/le contenu, colles a
        # self.card sans marge, recouvriraient le filet).
        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._card_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        # Padding, PAR COTE (voir Column.refresh_header, MEME logique "carte
        # flottante") — cote gauche a 0 si collee a la derniere colonne
        # (meme regle que la bordure ci-dessus).
        col_pad = dict(column_padding_for(INSPECTOR_TITLE))
        if suppress_left:
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()

    def _suppress_left(self) -> bool:
        """L'inspecteur est TOUJOURS la derniere "colonne" de la rangee
        (voir PipelineBrowser.__init__) : contrairement a Column.
        _suppress_left, inutile d'y chercher un voisin de gauche par
        indexOf — il en existe TOUJOURS un (au moins "Type"). Meme
        condition que l'ancienne app_style.column_seam_border() qu'elle
        remplace ici : Distance entre colonnes <= 0 ET aucun padding actif
        de ce cote — sinon 2 filets se cumuleraient a cette frontiere."""
        if column_gap() > 0:
            return False
        return column_padding_for(INSPECTOR_TITLE)["left"] <= 0

    def _update_card_mask(self):
        """MEME mecanisme que Column._update_card_mask (voir sa docstring
        pour le detail du double decoupage anti-aliase)."""
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        self._card_effect.setEnabled(self.card._thickness <= 0)
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._inner_effect.setRadius(_radius_dict(inner_radius))
        self._inner_effect.setEnabled(self.card._thickness > 0)

    # -- redimensionnement par glisser-deposer sur la bordure gauche,
    # comme n'importe quelle colonne (voir Column.resize_begin/update/end) --

    def _max_width(self) -> int:
        """Largeur maximale ATTEIGNABLE au glisser : toute la place
        disponible jusqu'a la colonne d'en face (la rangee Type/Projets/...
        a gauche), PAS une constante fixe — voir la remarque de
        l'utilisateur, "augmente cette limite a la place disponible jusqu'a
        la colonne en face". `win.scroll`/`win.columns_layout` (voir
        PipelineBrowser.__init__) : largeur du viewport visible moins la
        largeur REELLE actuelle de la rangee de colonnes (sizeHint() d'un
        QHBoxLayout aux enfants a largeur fixe = leur somme + espacements) —
        DETAIL_PANEL_MIN_WIDTH en repli si l'un des deux manque (fenetre pas
        encore construite) ou si le resultat tombe en-dessous."""
        win = self.window()
        scroll = getattr(win, "scroll", None)
        columns_layout = getattr(win, "columns_layout", None)
        if scroll is None or columns_layout is None:
            return DETAIL_PANEL_MAX_WIDTH
        available = scroll.viewport().width() - columns_layout.sizeHint().width()
        return max(DETAIL_PANEL_MIN_WIDTH, available)

    def _in_resize_zone(self, x: int) -> bool:
        """Bord GAUCHE (contrairement a Column/PreviewColumn, bord DROIT —
        l'inspecteur est TOUJOURS la DERNIERE colonne de la rangee, voir
        _suppress_left)."""
        return 0 <= x < scaled(16)

    def _resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        self.grabMouse()
        self.setCursor(Qt.SizeHorCursor)
        _show_resize_width(self, self.width())

    def _resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(
            DETAIL_PANEL_MIN_WIDTH,
            min(self._max_width(), self._resize_start_width - delta),
        )
        self.setFixedWidth(new_width)
        self._natural_width = new_width
        win = self.window()
        if hasattr(win, "_slide_snapshot"):
            win._slide_snapshot = None   # largeur changee : capture du depliage perimee
        _show_resize_width(self, new_width)

    def _resize_end(self):
        self._resizing = False
        self.releaseMouse()
        self.unsetCursor()
        _hide_resize_width(self)
        _persist_detail_panel_width(self.window(), self.width())

    def eventFilter(self, obj, event):
        """MEME mecanique que PreviewColumn.eventFilter/Column.eventFilter
        (voir leur docstring de tete) : installe sur self.card/self.header
        (voir __init__) — sans cela, ces widgets ENFANTS, qui couvrent TOUTE
        la surface de self, interceptent l'evenement souris AVANT que self
        ne le voie, rendant la bordure de redimensionnement inaccessible —
        voir la remarque de l'utilisateur, "la selection du bord de la
        colonne inspecteur est toujours aussi peinible a selectionner pour
        la redimension"."""
        etype = event.type()
        if etype in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide) and                 obj in getattr(self, "_md_slot_watch", ()):
            self._place_markdown_view()
            return False
        if obj in getattr(self, "_preview_widgets", ()):
            # Apercu : seul le double-clic est intercepte (voir
            # preview_double_clicked), le reste suit son cours normal.
            if etype == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.preview_double_clicked.emit()
                return True
            if self._pdf_path is not None and self._pdf_path == self._current_path:
                if self._pdf_event(event):
                    return True
            return False
        if etype == QEvent.MouseMove:
            if self._resizing:
                self._resize_update(event.globalPosition().toPoint().x())
                return True
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_x) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._in_resize_zone(local_x):
                self._resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonRelease and self._resizing:
            self._resize_end()
            return True
        elif etype == QEvent.Leave and not self._resizing:
            obj.unsetCursor()
        return False

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._resizing:
            self._resize_update(event.globalPosition().toPoint().x())
            return
        self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(x) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        x = event.position().toPoint().x()
        if event.button() == Qt.LeftButton and self._in_resize_zone(x):
            self._resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resize_end()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._resizing:
            self.unsetCursor()
        super().leaveEvent(event)

    def _delete_preview(self, path: Path):
        """Supprime l'APERCU en cache (image, turntable) du fichier affiche,
        apres confirmation ; le fichier lui-meme n'est jamais touche."""
        answer = QMessageBox.question(
            self, "Supprimer l'apercu",
            f"Supprimer l'apercu (image et turntable) de « {path.name} » ?\n\n"
            "Le fichier lui-meme n'est pas touche.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        delete_preview_cache(path)
        reload_browser = getattr(self.window(), "reload", None)
        if reload_browser is not None:
            reload_browser()

    def _set_preview_controls_visible(self, visible: bool):
        """Affiche/masque la ligne des boutons du tableau ; masquee, elle sort aussi des lignes du
        tableau (le style commun arrondit alors le bas de la ligne des valeurs)."""
        row = getattr(self, "_controls_row", None)
        if row is None:
            return
        meta = self.preview_info_table._flat_rows
        entry = self._controls_row_meta
        if visible and entry not in meta:
            meta.append(entry)
        elif not visible and entry in meta:
            meta.remove(entry)
        row.setVisible(visible)
        self._restyle_info_table()

    def _request_lightroom_preview(self):
        if not self._current_path:
            return
        import lightroom_bridge
        self.lightroom_preview_button.setEnabled(False)
        self.lightroom_preview_button.setText("Demande envoyée…")
        lightroom_bridge.create_preview(Path(self._current_path))
        QTimer.singleShot(25000, self._restore_lightroom_preview_button)

    def _restore_lightroom_preview_button(self):
        self.lightroom_preview_button.setText("Créer l’aperçu Lightroom")
        self.lightroom_preview_button.setEnabled(True)

    def _reflow_preview_controls(self, wide: bool):
        """Range les boutons sur UNE ligne (panneau large) ou sur plusieurs
        (panneau etroit)."""
        if getattr(self, "_preview_controls_wide", None) == wide:
            return
        self._preview_controls_wide = wide
        layout = self._preview_controls_layout
        for item in self._preview_controls_items:
            layout.removeWidget(item)
        media, lr_preview, low_i, high_i, low_t, high_t, protection, badge, meta_badges = self._preview_controls_items
        if wide:
            for column, item in enumerate(self._preview_controls_items):
                layout.addWidget(item, 0, column)
            layout.setColumnStretch(len(self._preview_controls_items), 1)
        else:
            layout.setColumnStretch(len(self._preview_controls_items), 0)
            layout.addWidget(media, 0, 0, 1, 2)
            layout.addWidget(lr_preview, 0, 2, 1, 2)
            layout.addWidget(badge, 0, 4)
            layout.addWidget(meta_badges, 0, 5, 1, 2)
            layout.addWidget(low_i, 1, 0)
            layout.addWidget(high_i, 1, 1)
            layout.addWidget(low_t, 2, 0)
            layout.addWidget(high_t, 2, 1)
            layout.addWidget(protection, 3, 0, 1, 6)

    def _show_preview_context_menu(self, global_pos):
        """Menu clic droit de l'apercu (image, turntable ou video) du fichier
        affiche dans l'inspecteur."""
        path_text = getattr(self, "_current_path", None)
        if not path_text:
            return
        path = Path(path_text)
        menu = Menu(self)
        menu.setFont(font(11, 400))
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        menu.addSeparator()
        act_copy_file = menu.addAction("Copier l'apercu")
        act_copy_path = menu.addAction("Copier le chemin de l'apercu")
        menu.addSeparator()
        act_delete = menu.addAction("Supprimer l'apercu...")
        chosen = menu.exec(global_pos)
        if chosen is act_delete:
            self._delete_preview(path)
        elif chosen is act_reveal:
            reveal_in_file_manager(self._preview_image_path(path))
        elif chosen is act_copy_file:
            image_path = self._preview_image_path(path)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(image_path))])
            image = QImage(str(image_path)) if image_path.suffix.lower() in IMAGE_EXTENSIONS else QImage()
            if not image.isNull():
                mime.setImageData(image)
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(self._preview_image_path(path)))

    def _preview_image_path(self, path: Path) -> Path:
        """Chemin du fichier IMAGE affiche : image du cache d'un modele 3D (ou
        image courante de son turntable) ; sinon le fichier lui-meme (image,
        video...)."""
        if path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS:
            return path
        if self._selected_preview_media() == "turntable":
            if self._turntable_frame_paths:
                index = max(0, min(len(self._turntable_frame_paths) - 1, self._turntable_frame_index))
                return Path(self._turntable_frame_paths[index])
            return path
        try:
            mode = self._preview_render_modes.get((self._current_path, "image"), "low")
            mtime = path.stat().st_mtime
            current = _file_image_cache_path(path, mtime, render_mode=mode)
            if current.is_file():
                return current
            return _find_stale_preview_cache(path, mtime, current) or path
        except OSError:
            return path

    def _stop_video(self):
        """Coupe la lecture en cours et cache le lecteur : appele avant
        toute selection (voir show_path/clear), pas seulement pour un
        fichier non-video — quitter la selection d'une video ne doit
        jamais la laisser jouer en arriere-plan, invisible."""
        if self._video_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._video_player.stop()
        self._video_player.setSource(QUrl())
        self.video_widget.hide()

    @staticmethod
    def _well_qss() -> str:
        """Cadre de l'apercu : fond, filet et coins arrondis (3 px), sur lui seul (selecteur par nom)."""
        return f"#PreviewWell {{ background: {C['well']}; border: 1px solid #282c30; border-radius: 3px; }}"

    def clear(self):
        self._turntable_timer.stop()
        self._turntable_frame_paths = []
        self._set_preview_controls_visible(False)
        self._preview_request_path = None
        self._current_path = None
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
        self._pur_wanted = None
        self._pdf_path = None
        self.pur_navigation.hide()
        self.name.setText("")
        self.badge.setText("")
        self.preview_dimensions_value.setText("—")
        self.preview_stale_badge.hide()
        self.well.hide()
        self._preview_pixmap = None
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.well_label.clear()
        self.well_label.show()
        self.preview_log.hide()
        self.preview_progress.hide()
        self._hide_text_views()
        self.text_preview.clear()
        self._stop_video()
        for value in self.values.values():
            value.setText("")

    def refresh_fonts(self, is_dir: bool = True):
        """Reapplique les polices de role (voir role_font) : necessaire car
        ce panneau, contrairement aux colonnes, n'est pas reconstruit par
        PipelineBrowser.reload() apres un changement de reglages. Geometrie
        de l'entete (hauteur/padding) desormais dans refresh_header, PAS
        ici (voir sa docstring). Police/couleur du TITRE d'entete
        (self.header_title) AUSSI desormais dans refresh_header (bug
        corrige, voir sa remarque) — cette methode-ci ne touche plus qu'au
        NOM du fichier/dossier selectionne et aux champs de detail."""
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self.open_render_log_button.setFont(role_font("buttons", 10, 500))
        # Valeurs du tableau : role de texte des reglages (voir _build_info_table).
        for value in (*self.values.values(), self.preview_dimensions_value):
            _set_text_role(value, "value")
        self.preview_stale_badge.setFont(role_font("info2", 8, 700))

    def refresh_colors(self):
        """Reapplique les couleurs — MEME logique que Column.refresh_colors
        (voir sa docstring), applique ici a l'inspecteur pour la premiere
        fois (voir la remarque de l'utilisateur, "je veux exactement le
        meme style, parametres par parametres") : fond/bordure/rayon du
        cadre suivent desormais Colonnes > Colonnes, comme toute colonne."""
        self.header_fill.setStyleSheet(column_header_qss("DetailHeader", INSPECTOR_TITLE))
        frame = column_frame_style(INSPECTOR_TITLE, self._suppress_left())
        # scaled() ICI, sur le MEME dict que celui repasse tel quel au
        # masque (voir _update_card_mask/Column.refresh_colors, MEME raison).
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        self._update_card_mask()
        self.well.setStyleSheet(self._well_qss())
        self._apply_preview_table_style()
        self.open_render_log_button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            f"border-radius: 3px; padding: 0 7px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
        )
        self.refresh_fonts(True if not self.values["kind"].text() else self.values["kind"].text() == "Dossier")

    INFO_TABLE_DIMS = "Inspecteur/Informations#0"

    _INFO_ROWS = (("kind", "Type"), ("size", "Taille"), ("modified", "Modifié"),
                  ("dimensions", "Dimensions · ratio · taille"),
                  # Photos Lightroom (demande de l'utilisateur) : d'ou vient le proxy (colonnes, inspecteur,
                  # diapositives) et l'image en plein ecran ; lignes masquees pour les autres fichiers.
                  ("proxy_source", "Source du proxy"),
                  ("full_source", "Source de l'aperçu plein écran"))
    _SOURCE_ROWS = ("proxy_source", "full_source")

    def _build_info_table(self):
        """Tableau des informations : le tableau Parametre | Valeur des reglages (_flat_cells_table) ;
        style commun des tableaux, Override settings au clic droit, dimensions enregistrees."""
        import settings_window_v2 as v2
        from settings_cells import keep_table_dims
        settings = ui_state.APPLIED_SETTINGS or load_settings()
        v2.seed_window_look(settings)
        rows = []
        for key, label in self._INFO_ROWS:
            value = self.preview_dimensions_value if key == "dimensions" else self.values[key]
            _set_text_role(value, "value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)     # meme justification que sa cellule
            rows.append((label, value, None))
        frame = v2._flat_cells_table(rows)
        keep_table_dims(frame, self.INFO_TABLE_DIMS, settings)
        return frame

    def _fit_info_table(self):
        """Tant que les colonnes n'ont pas ete reglees a la main (dimensions enregistrees), le tableau
        prend toute la largeur de l'inspecteur : la colonne Valeur recoit ce que laisse celle des
        libelles ; reglees, elles gardent leur largeur (comme tout tableau des reglages)."""
        from settings_layout import _ResizableTableHeader
        from settings_widgets import _TABLE_DIMS
        frame = getattr(self, "preview_info_table", None)
        if frame is None or _TABLE_DIMS.get(frame.dimsKey()):
            return
        head = frame.findChild(_ResizableTableHeader)
        margins = self._content_layout.contentsMargins() if hasattr(self, "_content_layout") else None
        room = self.width() - (margins.left() + margins.right() if margins is not None else 32)
        room -= frame.layout().contentsMargins().left() + frame.layout().contentsMargins().right()
        if head is None or room < 120:
            return
        widths = head.columnWidths()
        widths = [widths[0], max(60, room - widths[0])]
        if widths == head.columnWidths():
            return
        frame._dims_autosave_paused = True
        try:
            head.setColumnWidths(widths)
        finally:
            frame._dims_autosave_paused = False

    def _attach_controls_row(self):
        """Ligne des boutons d'apercu : une ligne du tableau sur toute sa largeur (style des lignes du
        tableau, alternance et arrondi du bas compris)."""
        from settings_layout import _table_row
        row, row_layout = _table_row(M["table_row_b"], False)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.addWidget(self.preview_controls_cell)
        self.preview_info_table.layout().addWidget(row)
        self._controls_row = row
        self._controls_row_meta = (row, M["table_row_b"], False)
        self.preview_info_table._flat_rows.append(self._controls_row_meta)
        self._restyle_info_table()

    def _restyle_info_table(self):
        """Style du tableau : le sien s'il a un override (clic droit > Override settings), sinon le commun."""
        from settings_layout import set_table_look
        from settings_widgets import ELEMENT_LOOKS
        frame = self.preview_info_table
        set_table_look(frame, ELEMENT_LOOKS.get(f"table:{frame.dimsKey()}"))
        from settings_layout import apply_part_looks
        from settings_widgets import PART_LOOKS
        if PART_LOOKS.get(frame.dimsKey()) or getattr(frame, "_text_look", None):    # cellule / ligne / colonne, police
            apply_part_looks(frame)

    def _apply_preview_table_style(self):
        """Applique au tableau de l'inspecteur le style des tableaux des reglages (ceux APPLIQUES, apercu
        en direct compris : relire le disque ecrasait l'apercu de la fenetre de reglages ouverte)."""
        import settings_window_v2 as v2
        settings = ui_state.APPLIED_SETTINGS or load_settings()
        # Rien de ce que lit ce tableau n'a change (ex. couleur d'un menu en cours de glisser) : ~10 ms
        # economisees a chaque cran de l'apercu en direct.
        sig = json.dumps({k: v for k, v in settings.items()
                          if k == "colors" or k.startswith(("table_", "toggle", "element_style", "slider_"))},
                         sort_keys=True, default=str)
        if sig == getattr(self, "_preview_table_sig", None):
            return
        self._preview_table_sig = sig
        colors = settings.get("colors") or {}
        _sync_dynamic_M(colors)
        if "colors" in settings:
            v2.seed_window_look(settings)
        self._restyle_info_table()
        _sync_toggle_style(settings)
        self.render_protection_toggle.apply_style()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        handle = getattr(self, "_resize_handle", None)
        if handle is not None:
            handle.setGeometry(0, 0, scaled(16), self.height())
            handle.raise_()
        self._fit_info_table()
        self._reflow_preview_controls(self.preview_info_table.width() >= scaled(520))
        self._update_preview()

    def _update_preview(self):
        if self._preview_pixmap is None:
            self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
            self.preview_dimensions_value.setText("—")
            if self.preview_log.isVisible():
                return
            if self.preview_progress.isVisible():
                return
            self.well_label.clear()
            return
        pw, ph = self._preview_pixmap.width(), self._preview_pixmap.height()
        if pw <= 0 or ph <= 0:
            self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
            self.preview_dimensions_value.setText("—")
            self.well_label.clear()
            return
        # Largeur disponible = largeur du panneau moins ses marges (16 de
        # chaque cote). Jamais d'agrandissement au-dela de la taille reelle
        # de l'image, et jamais plus haut que PREVIEW_MAX_HEIGHT.
        avail_w = max(self.width() - 32, 50)
        scale = min(1.0, avail_w / pw, PREVIEW_MAX_HEIGHT / ph)
        final_w = max(1, round(pw * scale))
        final_h = max(1, round(ph * scale))
        ratio_gcd = math.gcd(final_w, final_h)
        self.preview_dimensions_value.setText(
            f"{final_w} × {final_h} px · {final_w // ratio_gcd}:{final_h // ratio_gcd} · {scale * 100:.0f}%"
        )
        self.well.setMinimumHeight(max(final_h, PREVIEW_MIN_HEIGHT))
        if self._pdf_zoom > 1.0 and self._pdf_path is not None and self._pdf_path == self._current_path:
            # Zoom PDF : on decoupe la zone visible dans la page pleine resolution.
            span = 1.0 / self._pdf_zoom
            crop = QRect(round(self._pdf_view[0] * pw), round(self._pdf_view[1] * ph),
                         max(1, round(span * pw)), max(1, round(span * ph)))
            self.preview_dimensions_value.setText(
                f"{final_w} × {final_h} px · zoom {self._pdf_zoom * 100:.0f}%")
            self.well_label.setPixmap(self._preview_pixmap.copy(crop).scaled(
                final_w, final_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            return
        scaled = self._preview_pixmap.scaled(
            final_w, final_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.well_label.setPixmap(scaled)

    # -- Notes Markdown : rendu du module Markdown (markdown_preview, habillage de l'onglet Markdown) et edition --

    _MD_AUTOSAVE_MS = 800

    def _md_widgets(self) -> list:
        return [w for w in (getattr(self, "markdown_bar", None), getattr(self, "markdown_slot", None),
                            getattr(self, "markdown_editor", None)) if w is not None]

    def _text_shown(self) -> bool:
        """Un apercu texte (brut ou note Markdown, lue ou editee) occupe la place de l'image."""
        return self.text_preview.isVisible() or any(w.isVisible() for w in self._md_widgets())

    def _hide_markdown(self):
        self._flush_markdown()
        self._md_path = None                   # plus de note active (Ctrl+E / Ctrl+S sans effet)
        for widget in self._md_widgets():
            widget.hide()

    def _hide_text_views(self):
        self.text_preview.hide()
        self._hide_markdown()

    def _ensure_markdown_widgets(self) -> bool:
        """Barre (Modifier / Lecture + etat d'enregistrement), vue web (lecture) et editeur
        (source), crees au premier .md ; ils prennent toute la hauteur de l'apercu."""
        if getattr(self, "markdown_view", None) is not None:
            return True
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtGui import QKeySequence, QShortcut
        except ImportError:
            return False
        self._md_path = None          # note affichee
        self._md_info = None          # encodage / fins de ligne / date lue (markdown_preview.read_note)
        self._md_dirty = False
        self._md_editing = False      # mode garde d'une note a l'autre, comme un onglet d'Obsidian
        self._md_save_timer = QTimer(self)
        self._md_save_timer.setSingleShot(True)
        self._md_save_timer.setInterval(self._MD_AUTOSAVE_MS)
        self._md_save_timer.timeout.connect(self._save_markdown)

        bar = self.markdown_bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(8)
        button = self.markdown_mode_button = QPushButton("Modifier")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(scaled(24))
        button.setToolTip("Basculer lecture / edition (Ctrl+E) ; enregistrement automatique (Ctrl+S pour forcer)")
        button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; padding: 0 10px; "
            f"border: 1px solid {C['btn_border']}; border-radius: 3px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}")
        button.clicked.connect(self._toggle_markdown_mode)
        status = self.markdown_status = QLabel("")
        status.setStyleSheet(f"color: {role_color('info', '#aab1b6')}; background: transparent;")
        bar_layout.addWidget(button)
        bar_layout.addWidget(status)
        bar_layout.addStretch(1)

        # La vue web n'est PAS dans la carte : la carte est decoupee a ses coins arrondis par un
        # QGraphicsEffect (_RoundedCornersEffect), et une vue web sous un effet reste figee a
        # l'ecran sur sa premiere image (la page defile, l'affichage non). Elle est donc enfant
        # direct du panneau, posee sur `markdown_slot`, qui lui garde sa place dans la mise en
        # page (voir _place_markdown_view) ; sa visibilite est celle de la place.
        slot = self.markdown_slot = QWidget()
        slot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        view = self.markdown_view = QWebEngineView(self)
        view.hide()
        view.page().setBackgroundColor(QColor(C["well"]))
        view.setContextMenuPolicy(Qt.NoContextMenu)

        editor = self.markdown_editor = QPlainTextEdit()
        editor.setFrameShape(QFrame.NoFrame)
        editor.setFont(font(11, 400, mono=True))
        editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        editor.setTabStopDistance(4 * editor.fontMetrics().horizontalAdvance(" "))
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {C['well']}; color: {C['text']};"
            f" border: 1px solid #282c30; padding: 10px; }}")
        editor.textChanged.connect(self._on_markdown_edited)

        layout = self._content_layout
        index = layout.indexOf(self.text_preview) + 1
        layout.insertWidget(index, bar)
        layout.insertWidget(index + 1, slot, 1)
        layout.insertWidget(index + 2, editor, 1)
        for widget in (bar, slot, editor):
            widget.hide()
        self._md_slot_watch = (slot, self._inner, self.card)   # la place bouge avec eux
        for widget in self._md_slot_watch:
            if widget is not self.card:                         # deja filtre (redimensionnement)
                widget.installEventFilter(self)
        for keys, slot in (("Ctrl+E", self._toggle_markdown_mode), ("Ctrl+S", self._flush_markdown)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda slot=slot: self._md_path is not None and slot())
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._flush_markdown)      # rien de perdu en quittant
        return True

    def _show_markdown(self, path: Path) -> bool:
        """Note .md : lue comme dans le mode lecture du module Markdown (meme rendu, memes reglages) ou
        editee en texte source, au choix (bouton Modifier / Lecture, Ctrl+E). Faux si ce n'est pas
        une note ou si QtWebEngine / markdown-it manquent : l'extrait texte brut prend le relais."""
        if path.suffix.lower() not in markdown_preview.MARKDOWN_EXTENSIONS or not markdown_preview.available():
            return False
        if not self._ensure_markdown_widgets():
            return False
        if (self._md_path == path and self.markdown_bar.isVisible()
                and not markdown_preview.changed_on_disk(path, self._md_info)):
            return True                        # meme note reaffichee : edition (curseur, annulation) intacte
        self._flush_markdown()                 # la note precedente d'abord
        try:
            text, info = markdown_preview.read_note(path)
        except OSError:
            return False
        self._md_path, self._md_info, self._md_dirty = path, info, False
        self.text_preview.hide()
        self.markdown_bar.show()
        self._load_markdown_editor(text)
        self._apply_markdown_mode(text)
        return True

    def _load_markdown_editor(self, text: str, keep_cursor: bool = False):
        """Texte de la note dans l'editeur ; `keep_cursor` : rechargement de la meme note (curseur
        garde a sa place, borne a la nouvelle longueur)."""
        editor = self.markdown_editor
        position = editor.textCursor().position() if keep_cursor else 0
        editor.blockSignals(True)
        editor.setPlainText(text)
        editor.blockSignals(False)
        editor.document().clearUndoRedoStacks()
        if keep_cursor:
            cursor = editor.textCursor()
            cursor.setPosition(min(position, len(text)))
            editor.setTextCursor(cursor)

    def refresh_markdown_style(self):
        """Onglet Markdown des reglages change : la note affichee en lecture est rendue a nouveau (meme habillage
        que le module Markdown)."""
        if getattr(self, "_md_path", None) is not None and not self._md_editing and \
                getattr(self, "markdown_view", None) is not None and self.markdown_view.isVisible():
            self._apply_markdown_mode()

    def _apply_markdown_mode(self, text: str | None = None):
        """Affiche la note dans le mode courant ; en lecture, rendu du texte `text` (celui de
        l'editeur : ce qu'on vient d'ecrire, sans relire le disque)."""
        path = self._md_path
        if path is None:
            return
        editing = self._md_editing
        self.markdown_mode_button.setText("Lecture" if editing else "Modifier")
        self.markdown_slot.setVisible(not editing)
        self.markdown_editor.setVisible(editing)
        if editing:
            self.markdown_editor.setFocus()
        else:
            page = markdown_preview.render_page(path, text if text is not None else self.markdown_editor.toPlainText())
            self.markdown_view.setHtml(page, QUrl.fromLocalFile(str(path.parent) + "/"))
        self._update_markdown_status()

    def _place_markdown_view(self):
        """Pose la vue web sur sa place (`markdown_slot`) : meme rectangle, meme visibilite."""
        slot, view = self.markdown_slot, self.markdown_view
        shown = slot.isVisibleTo(self)
        if shown:
            view.setGeometry(QRect(slot.mapTo(self, QPoint(0, 0)), slot.size()))
            handle = getattr(self, "_resize_handle", None)
            if not view.isVisibleTo(self):
                view.show()
                view.raise_()
                if handle is not None:
                    handle.raise_()             # la poignee de redimensionnement reste au-dessus
        elif view.isVisibleTo(self):
            view.hide()

    def _toggle_markdown_mode(self):
        if self._md_path is None:
            return
        if self._md_editing and not self._flush_markdown():
            return                             # enregistrement refuse (conflit) : on reste en edition
        if not self._md_editing and markdown_preview.changed_on_disk(self._md_path, self._md_info):
            # Modifiee ailleurs pendant la lecture : on edite la version du disque.
            try:
                text, self._md_info = markdown_preview.read_note(self._md_path)
                self._load_markdown_editor(text, keep_cursor=True)
            except OSError:
                pass
        self._md_editing = not self._md_editing
        self._apply_markdown_mode()

    def _on_markdown_edited(self):
        self._md_dirty = True
        self._md_save_timer.start()
        self._update_markdown_status()

    def _update_markdown_status(self):
        if not self._md_editing:
            text = ""
        elif self._md_dirty:
            text = "Modifications en cours…"
        else:
            text = "Enregistré"
        self.markdown_status.setText(text)

    def _flush_markdown(self) -> bool:
        """Enregistre tout de suite les modifications en attente (changement de fichier, retour en
        lecture, Ctrl+S, fermeture). Faux si l'enregistrement a ete refuse."""
        timer = getattr(self, "_md_save_timer", None)
        if timer is not None:
            timer.stop()
        return self._save_markdown()

    def _save_markdown(self) -> bool:
        """Ecrit la note si elle a change. Si le fichier a ete modifie ailleurs depuis sa lecture
        (Obsidian, synchro), on demande : garder ma version, ou recharger celle du disque."""
        path, info = getattr(self, "_md_path", None), getattr(self, "_md_info", None)
        if path is None or info is None or not self._md_dirty:
            return True
        if markdown_preview.changed_on_disk(path, info):
            box = QMessageBox(QMessageBox.Warning, "Note modifiée ailleurs",
                              f"« {path.name} » a été modifiée en dehors de l'inspecteur "
                              "(Obsidian, synchronisation…) depuis son ouverture.", parent=self)
            keep = box.addButton("Garder ma version", QMessageBox.AcceptRole)
            reload = box.addButton("Recharger le fichier", QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is reload:
                try:
                    text, self._md_info = markdown_preview.read_note(path)
                except OSError:
                    return False
                self._md_dirty = False
                self._load_markdown_editor(text, keep_cursor=True)
                self._update_markdown_status()
                return True
            if box.clickedButton() is not keep:
                return False
        try:
            markdown_preview.write_note(path, self.markdown_editor.toPlainText(), info)
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", f"{path.name} :\n{exc}")
            return False
        self._md_dirty = False
        self._update_markdown_status()
        return True

    def focus_source(self):
        """Objet en focus (aujourd'hui : l'apercu image/turntable affiche) pour
        l'animation « masquer les colonnes » : (pixmap pleine taille, QRect de
        l'image telle qu'affichee, en coordonnees de ce panneau), ou None si
        rien d'affichable (pas d'apercu, journal de rendu, video...)."""
        shown = self.well_label.pixmap()
        if (self._preview_pixmap is None or self._preview_pixmap.isNull() or shown is None or shown.isNull()
                or not self.well_label.isVisible()):
            return None
        dpr = shown.devicePixelRatio() or 1.0
        w, h = round(shown.width() / dpr), round(shown.height() / dpr)
        label = self.well_label.rect()
        top_left = self.well_label.mapTo(self, QPoint((label.width() - w) // 2, (label.height() - h) // 2))
        return self._preview_pixmap, QRect(top_left, QSize(w, h))

    def _refresh_preview_stale_badge(self, path: Path | None = None):
        key = str(path) if path is not None else self._current_path
        if key and self._selected_preview_media() == "turntable":
            try:
                mode = self._preview_render_modes.get((key, "turntable"), "low")
                stale = bool(self._turntable_frame_paths and not _turntable_frames(
                    Path(key), Path(key).stat().st_mtime, render_mode=mode))
            except OSError:
                stale = False
            self.preview_stale_badge.setVisible(stale)
            return
        self.preview_stale_badge.setVisible(bool(key and self._preview_pixmap is not None and key in _STALE_PREVIEW_PATHS))
        self._refresh_preview_origin_badge(key)

    def _refresh_preview_origin_badge(self, path_key: str | None = None, force: bool = False):
        """Lignes « Source du proxy » / « Source de l'aperçu plein écran » du tableau (plus d'encart
        au-dessus de l'image) : lues EN FOND (catalogue et Previews.lrdata de Lightroom), relues
        quand l'aperçu arrive (`force`, la source a pu changer)."""
        self.preview_origin_badge.hide()
        path_key = path_key or self._current_path
        if not path_key or (not force and path_key == getattr(self, "_sources_asked", None)):
            return
        self._sources_asked = path_key
        try:
            import lightroom_bridge
            if lightroom_bridge.is_managed(Path(path_key)):
                lightroom_bridge.request_sources(Path(path_key))
        except (ImportError, OSError, ValueError):
            pass

    def _on_lightroom_sources(self, path_key: str, proxy: str, full: str):
        if path_key != self._current_path:
            return
        for key, text in (("proxy_source", proxy), ("full_source", full)):
            self.values[key].setText(text)
            self.values[key].setToolTip(text)

    def _set_source_rows_visible(self, visible: bool):
        """Lignes des sources : seulement pour une photo d'un dossier associe a Lightroom ; masquees,
        elles sortent aussi des lignes du tableau (alternance, arrondi du bas)."""
        meta = self.preview_info_table._flat_rows
        if not hasattr(self, "_source_rows"):
            # Ligne du tableau (entree de _flat_rows) qui contient chaque valeur, relevee une fois.
            self._source_rows = [entry for entry in meta
                                 if any(entry[0].isAncestorOf(self.values[key]) for key in self._SOURCE_ROWS)]
        for entry in self._source_rows:
            if visible and entry not in meta:
                controls = getattr(self, "_controls_row_meta", None)       # toujours la derniere
                meta.insert(meta.index(controls) if controls in meta else len(meta), entry)
            elif not visible and entry in meta:
                meta.remove(entry)
            entry[0].setVisible(visible)
        self._restyle_info_table()

    def _on_lightroom_profile_ready(self, path_key: str, profile: str, base_profile: str, error: str):
        if path_key != self._current_path:
            return
        if error:
            self.preview_profile_badge.setText("PROFIL LR INDISPONIBLE")
            self.preview_profile_badge.setToolTip(error)
            foreground, background = "#ffd28a", "#493515"
        elif profile:
            self.preview_profile_badge.setText(f"PROFIL LR : {profile}")
            details = f"Profil de développement Lightroom : {profile}"
            if base_profile and base_profile != profile:
                details += f" (profil caméra de base : {base_profile})"
            self.preview_profile_badge.setToolTip(details)
            foreground, background = "#9ed8ff", "#17364a"
        else:
            self.preview_profile_badge.setText("PROFIL LR NON IDENTIFIÉ")
            self.preview_profile_badge.setToolTip(
                "Lightroom n’a pas renvoyé de nom de profil pour cette photo."
            )
            foreground, background = "#ffd28a", "#493515"
        self.preview_profile_badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 2px; padding: 1px 5px;"
        )
        self.preview_profile_badge.show()

    def _request_lightroom_profile(self, path: Path):
        try:
            import lightroom_bridge
            cached = lightroom_bridge.develop_profile(path)
            if cached:
                self._on_lightroom_profile_ready(str(path), cached[0], cached[1], "")
            else:
                self.preview_profile_badge.setText("PROFIL LR : lecture…")
                self.preview_profile_badge.setToolTip(
                    "Lecture des paramètres de développement de cette photo dans Lightroom."
                )
                self.preview_profile_badge.setStyleSheet(
                    "color: #9ed8ff; background: #17364a; border-radius: 2px; padding: 1px 5px;"
                )
                self.preview_profile_badge.show()
            lightroom_bridge.request_develop_profile(path)
        except (ImportError, OSError, ValueError):
            self.preview_profile_badge.hide()

    def _selected_preview_media(self) -> str:
        return "turntable" if self.preview_turntable_button.isChecked() else "image"

    def _render_preview_media(self, media: str, render_mode: str):
        if not self._current_path:
            return
        path = Path(self._current_path)
        if path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS:
            return
        if self._current_path in _PREVIEW_DECODE_MANAGER.active:
            return
        self._preview_render_modes[(self._current_path, media)] = render_mode
        self._select_preview_media(media)
        if media == "turntable":
            self._render_turntable(render_mode)
        else:
            self._start_3d_preview(path, render_mode)

    def _refresh_render_action_buttons(self):
        enabled = bool(self._current_path and self._current_path not in _PREVIEW_DECODE_MANAGER.active)
        for button in self.render_action_buttons.values():
            button.setEnabled(enabled)

    def _select_preview_media(self, media: str | None = None):
        self._turntable_timer.stop()
        self._turntable_frame_paths = []
        media = media or self._selected_preview_media()
        button = self.preview_media_buttons.get(media, self.preview_image_button)
        button.setChecked(True)
        if not self._current_path:
            return
        path = Path(self._current_path)
        if path.suffix.lower() not in TURNTABLE_EXTENSIONS:
            return
        self._preview_media_preferences[self._current_path] = media
        is_turntable = media == "turntable"
        self.turntable_controls.setVisible(is_turntable)
        self.turntable_play_button.setText("▶")
        if not is_turntable:
            mode = self._preview_render_modes.get((self._current_path, "image"), "low")
            self._preview_pixmap = _cached_file_image_pixmap(path, mode)
            self._update_preview()
            self._refresh_preview_stale_badge(path)
            return
        try:
            mode = self._preview_render_modes.get((self._current_path, "turntable"), "low")
            self._turntable_frame_paths = _turntable_frames(path, path.stat().st_mtime,
                                                           allow_stale=True, render_mode=mode)
        except OSError:
            pass
        self._turntable_frame_index = 0
        if self._turntable_frame_paths:
            self.turntable_slider.blockSignals(True)
            self.turntable_slider.setValue(0)
            self.turntable_slider.blockSignals(False)
            self._show_turntable_frame()
            self._turntable_timer.start()
            self.turntable_play_button.setText("Ⅱ")
            self._update_turntable_control_state(True)
        else:
            self._preview_pixmap = None
            self._update_preview()
            self.well_label.setText("Turntable en attente du rendu automatique\n↻ pour le calculer maintenant")
            self.turntable_counter.setText("— / 72")
            self.turntable_play_button.setText("▶")
            self._update_turntable_control_state(False)
        self._refresh_preview_stale_badge(path)

    def _update_turntable_control_state(self, has_frames: bool):
        for button in (self.turntable_play_button, self.turntable_stop_button,
                       self.turntable_previous_button, self.turntable_next_button):
            button.setEnabled(has_frames)
        self.turntable_slider.setEnabled(has_frames)

    def _on_turntable_slider_changed(self, index: int):
        if not self._turntable_frame_paths:
            return
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_index = max(0, min(len(self._turntable_frame_paths) - 1, index))
        self._show_turntable_frame()

    def _step_turntable(self, step: int):
        if not self._turntable_frame_paths:
            return
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_index = (self._turntable_frame_index + step) % len(self._turntable_frame_paths)
        self._show_turntable_frame()

    def _stop_turntable_playback(self):
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        if self._turntable_frame_paths:
            self._turntable_frame_index = 0
            self._show_turntable_frame()

    def _show_turntable_frame(self):
        if not self._turntable_frame_paths:
            return
        frame = self._turntable_frame_paths[self._turntable_frame_index]
        pixmap = QPixmap(str(frame))
        if not pixmap.isNull():
            self._preview_pixmap = pixmap
            self._update_preview()
            self.turntable_counter.setText(f"{self._turntable_frame_index + 1} / 72")
            self.turntable_slider.blockSignals(True)
            self.turntable_slider.setValue(self._turntable_frame_index)
            self.turntable_slider.blockSignals(False)

    def _advance_turntable(self):
        if self._turntable_frame_paths and not self.preview_log.isVisible():
            self._turntable_frame_index = (self._turntable_frame_index + 1) % len(self._turntable_frame_paths)
            self._show_turntable_frame()

    def _toggle_turntable_playback(self):
        if self._turntable_timer.isActive():
            self._turntable_timer.stop()
            self.turntable_play_button.setText("▶")
        elif self._turntable_frame_paths:
            self._turntable_timer.start()
            self.turntable_play_button.setText("Ⅱ")

    def _render_turntable(self, render_mode: str | None = None):
        if not self._current_path:
            return
        path = Path(self._current_path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        self._turntable_timer.stop()
        render_mode = render_mode or self._preview_render_modes.get((self._current_path, "turntable"), "low")
        root_field = getattr(self.window(), "root_field", None)
        _PREVIEW_DECODE_MANAGER.request(path, mtime, force_render=True, media_type="turntable",
                                       render_mode=render_mode,
                                       log_directory=Path(root_field.text()) if root_field is not None else None)

    def _on_turntable_ready(self, path_str, mtime, image):
        self._refresh_render_action_buttons()
        self._preview_generation_paths.discard(path_str)
        self._auto_preview_paths.discard(path_str)
        if not self._preview_generation_paths:
            self.preview_log.hide()
            self.preview_progress.hide()
            self.well_label.show()
        if path_str == self._current_path and self._selected_preview_media() == "turntable":
            self._select_preview_media()
            if image is None and not self._turntable_frame_paths:
                self.well_label.setText("Turntable indisponible — consulter le journal de rendu")
        else:
            self._update_preview()

    def _pdf_geometry(self):
        """(largeur, hauteur) de la page telle qu'affichee a zoom 1, et coin haut-gauche
        de cette zone dans well_label."""
        pix = self._preview_pixmap
        if pix is None or pix.isNull():
            return None
        scale = min(1.0, max(self.width() - 32, 50) / pix.width(), PREVIEW_MAX_HEIGHT / pix.height())
        w, h = max(1, round(pix.width() * scale)), max(1, round(pix.height() * scale))
        label = self.well_label.size()
        return w, h, (label.width() - w) / 2, (label.height() - h) / 2

    def _pdf_clamp_view(self):
        span = 1.0 / self._pdf_zoom
        self._pdf_view[0] = max(0.0, min(1.0 - span, self._pdf_view[0]))
        self._pdf_view[1] = max(0.0, min(1.0 - span, self._pdf_view[1]))

    def _pdf_set_zoom(self, zoom: float, u: float = 0.5, v: float = 0.5):
        """Zoom (1 = page entiere) en gardant fixe le point (u, v) de la zone visible."""
        old = self._pdf_zoom
        zoom = max(1.0, min(8.0, zoom))
        if zoom == old:
            return
        self._pdf_view[0] += u * (1 / old - 1 / zoom)
        self._pdf_view[1] += v * (1 / old - 1 / zoom)
        self._pdf_zoom = zoom
        self._pdf_clamp_view()
        self._update_preview()

    def _pdf_event(self, event) -> bool:
        """Molette = page suivante/precedente (ou defilement si zoome), Ctrl+molette =
        zoom, glisser = deplacer la page zoomee, clic milieu = zoom 1."""
        etype = event.type()
        if etype == QEvent.Wheel:
            delta = event.angleDelta().y()
            if not delta:
                return False
            if event.modifiers() & Qt.ControlModifier:
                geo = self._pdf_geometry()
                u = v = 0.5
                if geo:
                    pos = self.well_label.mapFromGlobal(event.globalPosition().toPoint())
                    u = max(0.0, min(1.0, (pos.x() - geo[2]) / geo[0]))
                    v = max(0.0, min(1.0, (pos.y() - geo[3]) / geo[1]))
                self._pdf_set_zoom(self._pdf_zoom * 1.2 ** (delta / 120), u, v)
            elif self._pdf_zoom > 1.0:
                self._pdf_view[1] -= delta / 120 * 0.1 / self._pdf_zoom
                self._pdf_clamp_view()
                self._update_preview()
            else:
                self._pdf_wheel += delta
                steps = int(self._pdf_wheel / 120)
                if steps:
                    self._pdf_wheel -= steps * 120
                    self._navigate_pdf_page(-steps)
            return True
        if etype == QEvent.MouseButtonPress:
            if event.button() == Qt.MiddleButton:
                self._pdf_set_zoom(1.0)
                return True
            if event.button() == Qt.LeftButton and self._pdf_zoom > 1.0:
                self._pdf_drag = event.globalPosition().toPoint()
                return True
        elif etype == QEvent.MouseMove and self._pdf_drag is not None:
            geo = self._pdf_geometry()
            now = event.globalPosition().toPoint()
            if geo:
                self._pdf_view[0] -= (now.x() - self._pdf_drag.x()) / geo[0] / self._pdf_zoom
                self._pdf_view[1] -= (now.y() - self._pdf_drag.y()) / geo[1] / self._pdf_zoom
                self._pdf_clamp_view()
                self._update_preview()
            self._pdf_drag = now
            return True
        elif etype == QEvent.MouseButtonRelease and self._pdf_drag is not None:
            self._pdf_drag = None
            return True
        return False

    def _navigate_pdf_page(self, step: int):
        """Affiche la page courante + `step` du PDF selectionne (0 = recharger)."""
        if self._pdf_path != self._current_path:
            return
        page = max(0, min(self._pdf_pages - 1, self._pdf_page + step))
        image = _render_pdf_page(Path(self._pdf_path), 1800, page)
        if image is None:
            self.pur_image_counter.setText("Page illisible")
        else:
            self._pdf_page = page
            self._preview_pixmap = QPixmap.fromImage(image)
            self.well.show()
            self.well_label.show()
            self._update_preview()
        self.pur_image_counter.setText(f"Page {self._pdf_page + 1} / {self._pdf_pages}")
        self.pur_previous_button.setEnabled(self._pdf_page > 0)
        self.pur_next_button.setEnabled(self._pdf_page + 1 < self._pdf_pages)

    def select_pur_image(self, path_str: str, index: int):
        """Visionneuse -> inspecteur : la planche `path_str` montre son image n° `index` (celle regardee),
        pas la premiere. Images pas encore connues (extraction en cours) : rang retenu, applique des qu'il
        existe (_apply_pur_wanted)."""
        self._pur_wanted = (path_str, int(index))
        if self._pur_image_path == path_str and self._apply_pur_wanted(path_str):
            self._navigate_pur_image(0)

    def _apply_pur_wanted(self, path_str: str) -> bool:
        wanted = self._pur_wanted
        if wanted is None or wanted[0] != path_str:
            return False
        total = len(self._pur_exported_images) or len(self._pur_image_ranges)
        if wanted[1] >= total:
            return False                       # pas encore extraite : on attend
        self._pur_image_index = wanted[1]
        self._pur_wanted = None
        return True

    def _navigate_pur_image(self, step: int):
        if self._pdf_path is not None:
            self._navigate_pdf_page(step)
            return
        if self._pur_image_path != self._current_path:
            return
        direction = -1 if step < 0 else 1
        index = self._pur_image_index + step if step else self._pur_image_index
        total = len(self._pur_exported_images) or len(self._pur_image_ranges)
        while 0 <= index < total:
            if self._pur_exported_images:
                image = read_pur_exported_image(Path(self._pur_exported_images[index]))
            else:
                image = read_pur_embedded_image(Path(self._pur_image_path), self._pur_image_ranges[index])
            if image is not None and not image.isNull():
                self._pur_image_index = index
                self._preview_pixmap = QPixmap.fromImage(image)
                suffix = " (extraction en cours)" if self._pur_export_task is not None else ""
                self.pur_image_counter.setText(f"Image {index + 1} / {total}{suffix}")
                self.pur_previous_button.setEnabled(index > 0)
                self.pur_next_button.setEnabled(index + 1 < total)
                self.well.show()
                self.well_label.show()
                self._update_preview()
                return
            index += direction
        self.pur_previous_button.setEnabled(index > 0)
        self.pur_next_button.setEnabled(False if direction > 0 else index + 1 < total)

    def _start_pur_export(self, path: Path, mtime: float):
        current = self._pur_export_task
        if current is not None and str(current.path) == str(path) and current.mtime == mtime:
            return
        task = _PureRefExportTask(path, mtime)
        task.signals.progress.connect(self._on_pur_export_progress)
        task.signals.finished.connect(self._on_pur_export_finished)
        self._pur_export_task = task
        _PUR_EXPORT_POOL.start(task)

    def _on_pur_export_progress(self, path_str: str, mtime: float, files):
        if path_str != self._current_path or path_str != self._pur_image_path:
            return
        try:
            if Path(path_str).stat().st_mtime != mtime:
                return
        except OSError:
            return
        self._pur_exported_images = list(files)
        self._apply_pur_wanted(path_str)
        self.pur_next_button.setEnabled(self._pur_image_index + 1 < len(files))
        self._navigate_pur_image(0)

    def _on_pur_export_finished(self, path_str: str, mtime: float, files, error: str):
        if self._pur_export_task is not None and str(self._pur_export_task.path) == path_str:
            self._pur_export_task = None
        if path_str != self._current_path or path_str != self._pur_image_path:
            return
        try:
            current_mtime = Path(path_str).stat().st_mtime
        except OSError:
            return
        if current_mtime != mtime:
            return
        if files:
            self._pur_exported_images = list(files)
            self._apply_pur_wanted(path_str)
            self._pur_image_index = min(self._pur_image_index, len(files) - 1)
            self.pur_next_button.setEnabled(self._pur_image_index + 1 < len(files))
            self._navigate_pur_image(0)
        elif error:
            self.pur_image_counter.setText(error)
            self.pur_previous_button.setEnabled(False)
            self.pur_next_button.setEnabled(False)

    def _start_3d_preview(self, path: Path, render_mode: str = "low"):
        """Affiche la barre d'activite et lance le rendu 3D en arriere-plan."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        self._preview_request_path = str(path)
        self._preview_pixmap = None
        self.well_label.clear()
        root_field = getattr(self.window(), "root_field", None)
        _PREVIEW_DECODE_MANAGER.request(path, mtime, force_render=True, render_mode=render_mode,
                                       log_directory=Path(root_field.text()) if root_field is not None else None)
        if str(path) in _PREVIEW_DECODE_MANAGER.active and str(path) not in self._preview_generation_paths:
            self._on_preview_generation_started(str(path))

    def prepare_auto_preview_log(self, path: Path):
        """Marque le prochain rendu automatique avant le signal started."""
        self._auto_preview_paths.add(str(path))

    def open_preview_render_log(self):
        """Affiche les journaux disponibles, avec choix du jour."""
        window = self.window()
        root_field = getattr(window, "root_field", None)
        if root_field is None:
            QMessageBox.warning(self, "Journal des rendus", "La racine du navigateur est introuvable.")
            return
        root = Path(root_field.text().strip())
        try:
            path = _render_log_path(root)
            if not path.is_file():
                path = _write_render_log(root)
            days = sorted((item.stem.removeprefix("pipeline_preview_render_")
                           for item in root.glob("pipeline_preview_render_????-??-??.html")
                           if item.is_file()), reverse=True)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Journal des rendus", f"Impossible de lire le journal :\n{exc}")
            return
        dialog = getattr(self, "_render_log_dialog", None)
        if dialog is None:
            dialog = QDialog(self)
            dialog.resize(1400, 650)
            layout = QVBoxLayout(dialog)
            day_row = QHBoxLayout()
            day_row.addWidget(QLabel("Jour :", dialog))
            day_combo = QComboBox(dialog)
            day_combo.currentIndexChanged.connect(self._load_selected_render_log)
            day_row.addWidget(day_combo)
            day_row.addStretch(1)
            layout.addLayout(day_row)
            table = _RenderLogTable(dialog)
            layout.addWidget(table)
            buttons = QHBoxLayout()
            refresh = QPushButton("Actualiser", dialog)
            refresh.clicked.connect(self.open_preview_render_log)
            buttons.addWidget(refresh)
            buttons.addStretch(1)
            close = QPushButton("Fermer", dialog)
            close.clicked.connect(dialog.close)
            buttons.addWidget(close)
            layout.addLayout(buttons)
            self._render_log_dialog = dialog
            self._render_log_dialog_table = table
            self._render_log_day_combo = day_combo
            self._render_log_refresh_timer = QTimer(dialog)
            self._render_log_refresh_timer.setInterval(500)
            self._render_log_refresh_timer.timeout.connect(self._refresh_open_render_log)
            dialog.finished.connect(lambda _result: self._render_log_refresh_timer.stop())
        combo = self._render_log_day_combo
        selected = combo.currentData() if getattr(self, "_render_log_root", None) == root else None
        self._render_log_root = root
        combo.blockSignals(True)
        combo.clear()
        for day in days:
            combo.addItem("/".join(reversed(day.split("-"))), day)
        index = combo.findData(selected or datetime.now().strftime("%Y-%m-%d"))
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)
        self._load_selected_render_log()
        self._render_log_refresh_timer.start()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _load_selected_render_log(self, *_):
        day = self._render_log_day_combo.currentData()
        if not day:
            return
        path = self._render_log_root / f"pipeline_preview_render_{day}.html"
        try:
            entries = _read_render_log_entries(path)
        except (OSError, ValueError) as exc:
            self._render_log_dialog_table.clear()
            QMessageBox.warning(self, "Journal des rendus", f"Impossible de lire le journal :\n{exc}")
            return
        self._render_log_dialog.setWindowTitle(f"Journal des rendus — {day}")
        self._render_log_dialog.setToolTip(str(path))
        self._render_log_dialog_table.load_entries(entries)
        self._render_log_dialog_table.ensureCursorVisible()
        stamp = path.stat()
        self._render_log_loaded_signature = (stamp.st_mtime_ns, stamp.st_size)

    def _refresh_open_render_log(self):
        day = self._render_log_day_combo.currentData()
        if not day:
            return
        path = self._render_log_root / f"pipeline_preview_render_{day}.html"
        try:
            stamp = path.stat()
            signature = (stamp.st_mtime_ns, stamp.st_size)
            if signature == getattr(self, "_render_log_loaded_signature", None):
                return
            entries = _read_render_log_entries(path)
        except (OSError, ValueError):
            return
        table = self._render_log_dialog_table
        vertical = table.verticalScrollBar()
        at_bottom = vertical.value() >= vertical.maximum() - 2
        old_position = vertical.value()
        table.load_entries(entries)
        vertical.setValue(vertical.maximum() if at_bottom else old_position)
        self._render_log_loaded_signature = signature

    def _on_preview_generation_started(self, path_str: str):
        self._refresh_render_action_buttons()
        was_idle = not self._preview_generation_paths
        self._preview_generation_paths.add(path_str)
        automatic = path_str in self._auto_preview_paths
        if self._text_shown() or self.video_widget.isVisible():
            if not automatic:
                return
            self._hide_text_views()
            self._stop_video()
            self.well.show()
        if was_idle:
            if automatic:
                if self._auto_preview_log_count == 0:
                    self.preview_log.clear()
                else:
                    self.preview_log.appendPlainText(_IdlePreviewScheduler.LOG_SEPARATOR)
            else:
                self.preview_log.clear()
                self._auto_preview_log_count = 0
        if automatic:
            self._auto_preview_log_count += 1
        self.well.show()
        self.preview_log.show()
        self.preview_progress.hide()
        self.well_label.hide()
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.preview_log.appendPlainText(_render_log_line(f"> Aperçu en cours : {path_str}"),
                                         **self._preview_log_metadata(path_str))
        self.preview_log.ensureCursorVisible()

    def _on_preview_generation_progress(self, path_str: str, percent: int, message: str):
        if path_str not in self._preview_generation_paths:
            return
        if self._text_shown() or self.video_widget.isVisible():
            if path_str not in self._auto_preview_paths:
                return
            self._hide_text_views()
            self._stop_video()
            self.well.show()
        if not self.preview_log.isVisible():
            self.well.show()
            self.preview_log.show()
            self.well_label.hide()
            self.preview_progress.hide()
        self.preview_log.appendPlainText(_render_log_line(f"[{percent:3d}%] {Path(path_str).name} — {message}"),
                                         **self._preview_log_metadata(path_str))
        self.preview_log.ensureCursorVisible()

    def _preview_log_metadata(self, path_str):
        task = _PREVIEW_DECODE_MANAGER.active.get(path_str)
        root_field = getattr(self.window(), "root_field", None)
        return {"source": path_str, "media_type": getattr(task, "media_type", "image"),
                "render_mode": getattr(task, "render_mode", ""),
                "output_path": getattr(task, "output_path", ""),
                "root": Path(root_field.text()) if root_field is not None else None}

    def _on_3d_preview_ready(self, path_str: str, mtime: float, image):
        """Met en cache le resultat du worker, puis l'affiche s'il est toujours selectionne."""
        if path_str == self._current_path:
            self._restore_lightroom_preview_button()
            self._refresh_preview_origin_badge(path_str, force=True)
        self._refresh_render_action_buttons()
        was_requested = path_str == self._preview_request_path or path_str in self._preview_generation_paths
        self._preview_generation_paths.discard(path_str)
        self._auto_preview_paths.discard(path_str)
        path = Path(path_str)
        try:
            from previews import cached_mtime, is_remote_path
            still_current_file = (cached_mtime(path) if is_remote_path(path) else entry_mtime(path)) == mtime
        except OSError:
            still_current_file = False
        pix = None
        completed_mode = _PREVIEW_DECODE_MANAGER.last_completed_mode.get(path_str, "low")
        if still_current_file and image is not None and not image.isNull():
            pix = QPixmap.fromImage(image)
            if completed_mode == "high" and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
                _bounded_cache_set(_file_image_high_cache, path_str, (mtime, pix))
                small = pix.scaled(_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM, _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM,
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
                _bounded_cache_set(_file_image_column_cache, path_str, (mtime, small),
                                   _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES)
            else:
                _cache_file_preview(path_str, mtime, pix, path_str in _STALE_PREVIEW_PATHS)
            # Les delegates des colonnes consultent le meme cache; les
            # repeindre leur fait afficher le rendu qui vient d'etre produit.
            for widget in QApplication.allWidgets():
                if isinstance(widget, QAbstractItemView):
                    # Une vue qui sait ne repeindre que la case concernee (la planche de la visionneuse,
                    # qui ne doit rien refaire pendant son animation d'ouverture) le fait elle-meme.
                    hook = getattr(widget, "preview_ready", None)
                    if hook is not None:
                        hook(path_str)
                    else:
                        widget.viewport().update()
        selected_mode = self._preview_render_modes.get((path_str, "image"), "low")
        show_result = completed_mode == selected_mode or path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS
        if (self._preview_request_path == path_str or self._current_path == path_str) and show_result:
            if pix is None and path_str in _STALE_PREVIEW_PATHS and still_current_file:
                pix, _is_stale = _read_preview_pixmap(path, mtime)
            self._preview_request_path = None
            if pix is not None and path.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    import lightroom_bridge
                    managed = lightroom_bridge.is_managed(path)
                except (ImportError, OSError, ValueError):
                    managed = False
                if managed:
                    self._preview_pixmap = pix
                else:
                    source_pix = QPixmap(path_str)
                    self._preview_pixmap = source_pix if not source_pix.isNull() else pix
            else:
                self._preview_pixmap = pix
            self._update_preview()
            self._refresh_preview_stale_badge(path)
        elif self._preview_request_path == path_str:
            self._preview_request_path = None
        if not was_requested:
            return
        if self._preview_generation_paths:
            if not self._text_shown() and not self.video_widget.isVisible():
                completion_percent = 100 if pix is not None else 0
                completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
                self.preview_log.appendPlainText(
                    _render_log_line(f"[{completion_percent:3d}%] {path.name} — {completion_message}")
                )
                self.preview_log.ensureCursorVisible()
            return
        if not self._text_shown() and not self.video_widget.isVisible():
            completion_percent = 100 if pix is not None else 0
            completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
            self.preview_log.appendPlainText(
                _render_log_line(f"[{completion_percent:3d}%] {path.name} — {completion_message}")
            )
            self.preview_log.ensureCursorVisible()
            self.preview_log.hide()
        self.preview_progress.hide()
        self.well_label.show()
        self._update_preview()
        if path_str == self._current_path and self._selected_preview_media() == "turntable":
            self._select_preview_media()

    def show_loading_step(self, label: str, depth: int = 0):
        """Reutilise le "puits" de l'Inspecteur (self.well/well_label, le
        "carre noir" a cote des metadonnees) comme indicateur de
        chargement PENDANT la construction de la fenetre de parametres
        (voir SettingsWindow._report_loading_step, appele entre chaque
        section) — voir la remarque de l'utilisateur, "la fenetre de
        settings est toujours tres longue a charger ... peux tu faire une
        sorte d'animation dans le champ apercu de l'inspecteur et afficher
        tous les elements que tu charges en temps reel". Chaque etape
        s'AJOUTE a la suite des precedentes (jamais remplacee), comme un
        fichier LOG qui se construit ligne par ligne dans un terminal —
        voir la remarque de l'utilisateur, "fait ca comme si c'etait un
        vieil ordinateur qui balancait des lignes de code dans un
        terminal, ne supprime pas les etapes d'avant mais met les
        suivantes a la ligne"."""
        if not getattr(self, "_loading_log_lines", None):
            self._loading_log_lines = []
            # self.well est CACHE par defaut (voir clear()/show_path()) tant
            # qu'aucun fichier/dossier n'est selectionne dans l'appli — sans
            # ce show() explicite, l'animation restait invisible des que la
            # fenetre de parametres s'ouvrait sans rien de selectionne au
            # prealable.
            self.well.show()
            self.well_label.setPixmap(QPixmap())
            self.well_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.well_label.setWordWrap(False)
            # Police CODE de l'appli (mono_family, voir font()), vert pur
            # (0,255,0) et SANS lissage (smoothing="none", voir font()) —
            # voir la remarque de l'utilisateur, "je veux que la police
            # soit code de l'appli, qu'elle soit verte 0,255,0 et qu'elle
            # ne soit pas lissee".
            self.well_label.setFont(font(9, 400, mono=True, smoothing="none"))
            self.well_label.setStyleSheet(
                "background: transparent; border: none; color: rgb(0, 255, 0); padding: 6px;")
        # Indentation par niveau (tab = 2 caracteres, voir _report_
        # construction_step cote settings_window) — voir la remarque de
        # l'utilisateur, "quand tu load les settings, incrémente les
        # differents niveaux de settings (tab = 2 carac)".
        self._loading_log_lines.append(f"{'  ' * max(0, depth)}> {label}")
        self.well_label.setText("\n".join(self._loading_log_lines))
        self.well_label.adjustSize()
        # Se redimensionne selon le contenu, jusqu'a 1000px maxi (PAS une
        # hauteur fixe) — voir la remarque de l'utilisateur, "je veux que
        # le carre d'apercu soit plus haut que ca, qu'il se redimensionne
        # si besoin jusqu'a une hauteur de 1000px maxi".
        needed = self.well_label.sizeHint().height() + 12
        self.well.setMinimumHeight(max(PREVIEW_MIN_HEIGHT, min(1000, needed)))

    def clear_loading_step(self):
        """Restaure l'apparence normale du puits (voir show_loading_step) —
        _update_preview() y remet la vignette REELLEMENT selectionnee
        (ou rien), pas besoin de la memoriser a part."""
        self._loading_log_lines = []
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setWordWrap(False)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        self._update_preview()

    def _on_render_protection_toggled(self, protected: bool):
        if not self._current_path:
            return
        path = Path(self._current_path)
        if path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS:
            return
        _set_preview_protected(path, protected)
        if protected and _PREVIEW_DECODE_MANAGER.active.get(str(path)) is not None:
            # Une protection active pendant un rendu automatique annule la
            # prochaine étape dès que le worker consulte son cancel_event.
            scheduler = getattr(self.window(), "_idle_preview_scheduler", None)
            if scheduler is not None and scheduler.active_key == str(path):
                if scheduler.cancel_event is not None:
                    scheduler.cancel_event.set()

    def _show_video(self, path: Path):
        """Dimensionne le lecteur video sur la frame deja mise en cache
        (voir file_image_pixmap/_decode_video_frame) — meme calcul que
        _update_preview pour une image fixe — puis lance la lecture,
        silencieuse et en boucle (voir __init__)."""
        static = file_image_pixmap(path)
        avail_w = max(self.width() - 32, 50)
        if static is not None and not static.isNull() and static.width() > 0 and static.height() > 0:
            scale = min(1.0, avail_w / static.width(), PREVIEW_MAX_HEIGHT / static.height())
            self.video_widget.setFixedSize(
                max(1, round(static.width() * scale)), max(1, round(static.height() * scale))
            )
        else:
            self.video_widget.setFixedSize(avail_w, PREVIEW_MIN_HEIGHT)
        self.video_widget.show()
        self._video_player.setSource(QUrl.fromLocalFile(str(path)))
        self._video_player.play()

    def _fill_folder_count(self, path: str, scan=True):
        from previews import is_remote_path
        if getattr(self, "_current_path", None) != path:
            return                                # selection changee entre-temps
        count = listed_count(path)
        if count is None:
            if not scan or is_remote_path(path):
                return
            count = count_entries(Path(path))
        self.values["size"].setText(f"{count} elements")

    def show_path(self, path: Path):
        if getattr(self, "_md_path", None) is not None and Path(self._md_path) != path:
            self._flush_markdown()             # note en cours d'edition : enregistree avant de partir
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_paths = []
        self._current_path = str(path)
        self._refresh_render_action_buttons()
        # Type, date et taille repris de la lecture du dossier (`os.scandir`) : chaque `is_dir()` / `stat()`
        # etait un aller-retour de plus par clic sur un partage reseau (6 par selection, mesure).
        is_dir = entry_is_dir(path)
        supports_turntable = not is_dir and path.suffix.lower() in TURNTABLE_EXTENSIONS
        try:
            import lightroom_bridge
            lightroom_managed = not is_dir and lightroom_bridge.is_managed(path)
        except (ImportError, OSError, ValueError):
            lightroom_managed = False
        self.lightroom_preview_button.setVisible(lightroom_managed)
        self.lightroom_preview_button.setText("Créer l’aperçu Lightroom")
        self.lightroom_preview_button.setEnabled(True)
        self._set_preview_controls_visible(supports_turntable or lightroom_managed)
        self._set_source_rows_visible(lightroom_managed)
        if lightroom_managed:
            for key in self._SOURCE_ROWS:
                self.values[key].setText("…")
            self._refresh_preview_origin_badge(str(path), force=True)
        preferred_media = self._preview_media_preferences.get(str(path), "image")
        self.preview_media_buttons.get(preferred_media, self.preview_image_button).setChecked(True)
        self.turntable_controls.setVisible(supports_turntable and preferred_media == "turntable")
        self._update_turntable_control_state(False)
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
        if self._pur_wanted is not None and self._pur_wanted[0] != str(path):
            self._pur_wanted = None              # rang demande pour une autre planche : oublie
        self._pdf_path = None
        self.pur_navigation.hide()
        self.name.setText(path.name)
        is_renderable_3d = not is_dir and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS
        self.render_protection_toggle.blockSignals(True)
        self.render_protection_toggle.setChecked(
            is_renderable_3d and _is_preview_protected(path)
        )
        self.render_protection_toggle.blockSignals(False)
        self.render_protection_toggle.setVisible(is_renderable_3d)
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self._preview_pixmap = None
        self._preview_request_path = None
        self.preview_stale_badge.hide()
        self.preview_origin_badge.hide()
        self.preview_profile_badge.hide()
        if lightroom_managed:
            self._request_lightroom_profile(path)
        self.preview_progress.hide()
        if self._preview_generation_paths:
            self.preview_log.show()
            self.well_label.hide()
        else:
            self.preview_log.hide()
            self.well_label.show()
        self._stop_video()
        is_text_preview = not is_dir and path.suffix.lower() in TEXT_PREVIEW_EXTENSIONS
        # Lecture coupee (VIDEO_PLAYBACK_ENABLED) : une video passe par l'apercu fixe plus bas.
        is_video = VIDEO_PLAYBACK_ENABLED and not is_dir and path.suffix.lower() in VIDEO_EXTENSIONS
        if is_video:
            # Lecture reelle (voir _stop_video/video_widget), pas la frame
            # figee de file_image_pixmap : celle-ci ne sert plus ici qu'a
            # dimensionner le lecteur avant que la premiere image ne soit
            # decodee (voir _show_video). well/text_preview jamais affiches
            # en meme temps.
            self.well.hide()
            self._hide_text_views()
            self._show_video(path)
        elif is_text_preview and self._show_markdown(path):
            # Note Markdown rendue comme le mode lecture du module Markdown (voir _show_markdown).
            self.well.hide()
        elif is_text_preview:
            # Extrait de contenu (voir read_text_preview) plutot que le
            # "well" image : les deux ne s'affichent jamais ensemble.
            self.well.hide()
            self._hide_markdown()
            content_text = read_text_preview(path)
            self.text_preview.setPlainText(content_text if content_text is not None else "(apercu indisponible)")
            self.text_preview.show()
        else:
            self._hide_text_views()
            self.well.show()
            if not is_dir:
                suffix = path.suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    # Décodage et lecture du cache disque par le worker existant.
                    self._preview_pixmap = file_image_pixmap(path, asynchronous=True)
                elif suffix in OBJ_EXTENSIONS | ABC_EXTENSIONS:
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        render_mode = _MANUAL_3D_PREVIEW_MODE.pop(str(path), "low")
                        self._preview_render_modes[(str(path), "image")] = render_mode
                        _cached_file_image_pixmap(path)  # charge l'ancien rendu si disponible
                        self._start_3d_preview(path, render_mode)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(
                            path, self._preview_render_modes.get((str(path), "image"), "low"))
                elif suffix in (BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS | HOUDINI_SCENE_EXTENSIONS):
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        render_mode = _MANUAL_3D_PREVIEW_MODE.pop(str(path), "low")
                        self._preview_render_modes[(str(path), "image")] = render_mode
                        _cached_file_image_pixmap(path)
                        self._start_3d_preview(path, render_mode)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(
                            path, self._preview_render_modes.get((str(path), "image"), "low"))
                elif suffix in ILLUSTRATOR_EXTENSIONS and not ai_has_pdf_content(path):
                    # .ai sans contenu PDF : vignette XMP (voir previews._decode_ai_image).
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
                    else:
                        self.well_label.setText("Fichier Illustrator sans aperçu (enregistré sans contenu PDF).")
                elif suffix in PDF_EXTENSIONS or suffix in ILLUSTRATOR_EXTENSIONS:
                    # Un .ai moderne est un PDF : memes planches feuilletables.
                    self._pdf_pages = pdf_page_count(path)
                    if self._pdf_pages:
                        self._pdf_path = str(path)
                        self._pdf_page = 0
                        self._pdf_zoom = 1.0
                        self._pdf_view = [0.0, 0.0]
                        self.pur_navigation.show()
                        self._navigate_pdf_page(0)
                    else:
                        self.well_label.setText("PDF illisible (protégé ou corrompu).")
                elif suffix in DWG_EXTENSIONS or suffix in DXF_EXTENSIONS:
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
                elif suffix in PUR_PREVIEW_EXTENSIONS:
                    # Indexe les images embarquees sans les decoder, puis
                    # l'inspecteur ne charge que celle actuellement choisie.
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        mtime = None
                    self._pur_image_ranges = pur_embedded_image_ranges(path, mtime)
                    pur_version = pur_file_major_version(path)
                    is_pur_v2 = pur_version is not None and pur_version >= 2
                    if self._pur_image_ranges or is_pur_v2:
                        self._pur_image_path = str(path)
                        self.pur_navigation.show()
                        self.pur_previous_button.setEnabled(False)
                        self.pur_next_button.setEnabled(len(self._pur_image_ranges) > 1)
                        ready = pur_image_files(path, mtime) if (is_pur_v2 and mtime is not None) else None
                        if is_pur_v2 and ready:
                            # Deja extraites (par la visionneuse ou une visite precedente) : tout de suite,
                            # sans attendre une nouvelle extraction (qui finissait sur la 1re image).
                            self._pur_exported_images = [str(p) for p in ready]
                        elif is_pur_v2:
                            self.pur_image_counter.setText("Extraction des images PureRef…")
                            self.pur_next_button.setEnabled(False)
                            if mtime is not None:
                                self._start_pur_export(path, mtime)
                        if self._pur_image_ranges or self._pur_exported_images:
                            self._apply_pur_wanted(str(path))
                            self._navigate_pur_image(0)
                        else:
                            self.well_label.setText("Extraction des images PureRef en cours…")
                    else:
                        self.well_label.setText("Aucune image intégrée lisible dans ce fichier PureRef.")
                elif (suffix in PSD_EXTENSIONS
                      or suffix in EXR_EXTENSIONS or suffix in HDR_EXTENSIONS
                      or suffix in CUBE_EXTENSIONS or suffix in RAW_EXTENSIONS
                      or suffix in TX_EXTENSIONS or suffix in FONT_EXTENSIONS
                      or suffix in ABR_EXTENSIONS or suffix in VIDEO_EXTENSIONS):
                    # Rendu genere (.obj, voir _decode_obj_image), vignette
                    # embarquee extraite (.psd/.psb, voir
                    # _decode_psd_thumbnail) ou tone-mapping HDR (.exr/.hdr,
                    # voir _decode_exr_image/_decode_hdr_image) : pas un
                    # fichier que QPixmap sait charger directement, passe
                    # par le meme cache que les cartes-fichier
                    # (file_image_pixmap).
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
            self._update_preview()
            self._refresh_preview_stale_badge(path)
        stamp = entry_mtime(path)
        modified = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M") if stamp is not None else "-"
        if is_dir:
            kind = "Dossier"
            # Nombre d'elements : repris de la lecture du dossier par la colonne qui s'ouvre juste apres (meme
            # clic, avant le retour a la boucle) ; sinon compte a ce moment-la. Jamais une 2e lecture du dossier.
            size = "…"
            # La colonne le fournit à son arrivée ; attendre ne doit jamais
            # déclencher une seconde énumération sur le fil de l'interface.
            QTimer.singleShot(0, self, lambda p=str(path): self._fill_folder_count(p, scan=False))
        else:
            kind = (path.suffix[1:].upper() + " file") if path.suffix else "Fichier"
            file_size = entry_size(path)
            size = human_size(file_size) if file_size is not None else "-"
        self.values["kind"].setText(kind)
        self.values["size"].setText(size)
        self.values["modified"].setText(modified)
        if supports_turntable and preferred_media == "turntable":
            self._select_preview_media()

        if is_dir:
            self.badge.setText("DOSSIER")
            self.badge.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        else:
            self.badge.setText(path.suffix[1:].upper() if path.suffix else "FICHIER")
            self.badge.setStyleSheet("color: #7fa8cf; background: transparent;")

# ==========================================================================
# Etat de session (position/taille de la fenetre, dernier dossier parcouru) :
# separe des parametres utilisateur (pipeline_settings.json, gere par
# settings_window.py) puisque ce n'est pas un reglage mais un etat automatique
# de l'appli, sauvegarde a la fermeture et restaure au demarrage suivant.
# ==========================================================================

WINDOW_STATE_PATH = Path(os.environ.get("PIPELINE_MAIN_WINDOW_STATE_FILE",
                                       str(DATA_DIR / "pipeline_window_state.json")))

def load_window_state() -> dict:
    try:
        if WINDOW_STATE_PATH.is_file():
            data = json.loads(WINDOW_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}

def save_window_state(state: dict) -> None:
    try:
        WINDOW_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
