import json
import math
import os
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QMimeData
from PySide6.QtGui import (
    QImage,
)
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
from settings_widgets import Menu, _MiniSlider, _Toggle, _sync_toggle_style
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
    update_card_mask,
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
from fm_markdown import preview as markdown_preview
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


from detail_panel_parts.resize import ResizeMixin
from detail_panel_parts.preview_controls import PreviewControlsMixin
from detail_panel_parts.info_table import InfoTableMixin
from detail_panel_parts.markdown import MarkdownMixin
from detail_panel_parts.sources import SourcesMixin
from detail_panel_parts.turntable import TurntableMixin
from detail_panel_parts.pdf_pur import PdfPurMixin
from detail_panel_parts.render_log import RenderLogMixin
from detail_panel_parts.show import ShowMixin


class DetailPanel(
    ResizeMixin, PreviewControlsMixin, InfoTableMixin, MarkdownMixin, SourcesMixin, TurntableMixin, PdfPurMixin,
    RenderLogMixin, ShowMixin, QWidget,
):

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
        update_card_mask(self)

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
